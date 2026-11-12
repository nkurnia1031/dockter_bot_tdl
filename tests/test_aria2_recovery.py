from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tme3bot.worker.aria2_recovery import (
    Aria2RecoveryCoordinator,
    Aria2RecoveryStateStore,
)


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds: float = 1.0):
        self.value += seconds


class FakeAria2:
    def __init__(self):
        self.jobs = {
            "gid-active": {
                "gid": "gid-active", "status": "active", "completedLength": "0",
                "downloadSpeed": "0", "totalLength": "1000",
                "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
            }
        }
        self.calls = []
        self.next_gid = 1
        self.fail_next = {}
        self.before_pause = None
        self.fail_waiting_page = False
        self.accept_then_fail_add_uri = False

    def __call__(self, method, *params):
        self.calls.append((method, params))
        if self.fail_next.get(method, 0):
            self.fail_next[method] -= 1
            raise RuntimeError(f"fake {method} failure")
        if method == "tellActive":
            return [job for job in self.jobs.values() if job["status"] == "active"]
        if method == "tellWaiting":
            waiting = [job for job in self.jobs.values() if job["status"] in {"waiting", "paused"}]
            if len(params) >= 2:
                offset, limit = int(params[0]), int(params[1])
                if offset > 0 and self.fail_waiting_page:
                    raise RuntimeError("fake waiting-page failure")
                return waiting[offset:offset + limit]
            return waiting
        if method == "tellStopped":
            stopped = [job for job in self.jobs.values() if job["status"] in {"error", "complete", "removed"}]
            if len(params) >= 2:
                offset, limit = int(params[0]), int(params[1])
                return stopped[offset:offset + limit]
            return stopped
        if method == "tellStatus":
            return dict(self.jobs.get(str(params[0]), {"gid": str(params[0]), "status": "removed"}))
        if method == "pause":
            if self.before_pause is not None:
                self.before_pause(str(params[0]))
            self.jobs[str(params[0])]["status"] = "paused"
            return str(params[0])
        if method == "unpause":
            self.jobs[str(params[0])]["status"] = "active"
            return str(params[0])
        if method == "getOption":
            return {
                "dir": "/workspace", "out": "file.bin", "continue": "true",
                "load-cookies": "/database/aria2/cookies.txt",
            }
        if method == "addUri":
            gid = f"retry-{self.next_gid}"
            self.next_gid += 1
            self.jobs[gid] = {
                "gid": gid, "status": "active", "completedLength": "0",
                "downloadSpeed": "0", "totalLength": "1000",
                "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
            }
            if self.accept_then_fail_add_uri:
                self.accept_then_fail_add_uri = False
                raise RuntimeError("fake addUri response timeout after acceptance")
            return gid
        if method == "removeDownloadResult":
            self.jobs.pop(str(params[0]), None)
            return str(params[0])
        return "OK"


class Aria2RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temporary.name) / "aria2-recovery.json"
        self.store = Aria2RecoveryStateStore(self.state_file)
        self.clock = FakeClock()
        self.aria = FakeAria2()
        self.coordinator = Aria2RecoveryCoordinator(
            self.aria, self.store, clock=self.clock, interval_seconds=1
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_threshold_is_persisted_validated_and_zero_disables_only_speed_intervention(self):
        self.assertEqual(self.store.get_speed_threshold(), 100_000)
        self.store.set_speed_threshold(0)
        self.assertEqual(Aria2RecoveryStateStore(self.state_file).get_speed_threshold(), 0)
        with self.assertRaises(ValueError):
            self.store.set_speed_threshold(-1)
        with self.assertRaises(ValueError):
            self.store.set_speed_threshold(1_073_741_825)

    def test_slow_job_is_paused_then_resumed_by_monitor_after_warmup_and_low_window(self):
        for _ in range(71):
            self.coordinator.tick()
            self.clock.advance()
        self.assertEqual(self.aria.jobs["gid-active"]["status"], "paused")
        self.assertEqual(
            [method for method, _ in self.aria.calls].count("pause"), 1
        )

        self.clock.advance(3)
        self.coordinator.tick()
        self.assertEqual(self.aria.jobs["gid-active"]["status"], "active")
        self.assertEqual(
            [method for method, _ in self.aria.calls].count("unpause"), 1
        )

    def _run_until_paused(self, coordinator, *, max_seconds=400):
        for _ in range(max_seconds):
            coordinator.tick()
            if self.aria.jobs["gid-active"]["status"] == "paused":
                return
            self.clock.advance()
        self.fail("speed monitor did not pause the low-speed job")

    def _resume_and_observe_without_spike(self, coordinator):
        self.clock.advance(3)
        coordinator.tick()
        self.assertEqual(self.aria.jobs["gid-active"]["status"], "active")
        for _ in range(10):
            self.clock.advance()
            coordinator.tick()

    def test_two_initial_cycles_without_spike_disable_until_later_speed_spike_rearms(self):
        self._run_until_paused(self.coordinator)
        self._resume_and_observe_without_spike(self.coordinator)
        self.assertEqual(self.store.read()["jobs"]["gid-active"]["initial_cycles"], 1)

        self.clock.advance(300)
        self._run_until_paused(self.coordinator)
        self._resume_and_observe_without_spike(self.coordinator)
        state = self.store.read()["jobs"]["gid-active"]
        self.assertEqual(state["initial_cycles"], 2)
        self.assertTrue(state["intervention_disabled"])

        before = [method for method, _ in self.aria.calls].count("pause")
        self.aria.jobs["gid-active"]["completedLength"] = "200000"
        self.clock.advance()
        self.coordinator.tick()
        self.assertFalse(self.store.read()["jobs"]["gid-active"]["intervention_disabled"])
        self.aria.jobs["gid-active"]["completedLength"] = "200000"
        for _ in range(11):
            self.clock.advance()
            self.coordinator.tick()
            if self.aria.jobs["gid-active"]["status"] == "paused":
                break
        self.assertEqual([method for method, _ in self.aria.calls].count("pause"), before + 1)

    def test_threshold_zero_keeps_error_retry_available_but_never_pauses_for_speed(self):
        self.store.set_speed_threshold(0)
        for _ in range(100):
            self.coordinator.tick()
            self.clock.advance()
        self.assertEqual(self.aria.jobs["gid-active"]["status"], "active")
        self.assertFalse(any(method == "pause" for method, _ in self.aria.calls))

    def test_restart_resumes_only_a_job_marked_as_monitor_paused(self):
        self.store.update_job("gid-active", {
            "monitor_paused": True, "resume_at": 1000, "phase": "pause_wait",
            "ever_spiked": False, "initial_cycles": 1,
        })
        self.aria.jobs["gid-active"]["status"] = "paused"
        restarted = Aria2RecoveryCoordinator(
            self.aria, self.store, clock=self.clock, interval_seconds=1
        )

        restarted.tick()

        self.assertEqual(self.aria.jobs["gid-active"]["status"], "active")
        self.assertEqual([method for method, _ in self.aria.calls].count("unpause"), 1)
        self.assertFalse(self.store.read()["jobs"]["gid-active"]["monitor_paused"])

    def test_monitor_pause_intent_is_persisted_before_rpc_and_restart_can_reconcile_it(self):
        job = self.aria.jobs["gid-active"]
        self.coordinator._observe_speed(job, 100_000, 0, {})
        observation = self.coordinator.observations["gid-active"]
        observation["active_seconds"] = 60
        observation["warmup_finished_at"] = 0
        self.aria.before_pause = lambda _gid: self.assertEqual(
            self.store.read()["jobs"]["gid-active"]["phase"], "pause_intent"
        )

        self.coordinator._observe_speed(job, 100_000, 10, self.store.read()["jobs"])

        self.assertEqual(self.aria.jobs["gid-active"]["status"], "paused")
        self.assertEqual(self.store.read()["jobs"]["gid-active"]["phase"], "pause_wait")

    def test_corrupt_recovery_state_is_preserved_and_reported(self):
        contents = b'{"version":'
        self.state_file.write_bytes(contents)

        with self.assertRaisesRegex(RuntimeError, "corrupt"):
            self.store.update(lambda state: state.update({"speed_threshold_bytes_per_second": 1}))

        self.assertEqual(self.state_file.read_bytes(), contents)

    def test_malformed_recovery_sections_are_preserved_and_reported(self):
        malformed_states = (
            {"jobs": []},
            {"retry_paths": {"/workspace/file.bin": None}},
            {"jobs": {"gid-one": {"monitor_paused": True, "resume_at": "later"}}},
            {"retry_paths": {"/workspace/file.bin": {"retry_count": "two"}}},
            {"retry_paths": {"/workspace/file.bin": {"retry_count": -1}}},
        )
        for malformed in malformed_states:
            with self.subTest(section=next(iter(malformed))):
                value = {
                    "version": 1,
                    "speed_threshold_bytes_per_second": 100_000,
                    "jobs": {},
                    "retry_paths": {},
                    "error_event_gids": [],
                    "error_event_seen_at": {},
                    "error_event_retry_after": {},
                    **malformed,
                }
                contents = json.dumps(value).encode("utf-8")
                self.state_file.write_bytes(contents)

                with self.assertRaisesRegex(RuntimeError, "malformed"):
                    self.store.update(lambda state: state.update({"boot_id": "new"}))

                self.assertEqual(self.state_file.read_bytes(), contents)

    def test_stopped_single_file_http_error_is_retried_once_and_old_result_removed_after_progress(self):
        self.aria.jobs.pop("gid-active")
        self.aria.jobs["stopped-error"] = {
            "gid": "stopped-error", "status": "error", "completedLength": "0",
            "downloadSpeed": "0", "totalLength": "1000", "errorCode": "1",
            "errorMessage": "connection reset",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }
        self.coordinator.tick()
        self.clock.advance(5)
        self.coordinator.tick()

        retry_calls = [call for call in self.aria.calls if call[0] == "addUri"]
        self.assertEqual(len(retry_calls), 1)
        self.assertEqual(retry_calls[0][1][0], ["https://host/file.bin"])
        self.assertEqual(retry_calls[0][1][1]["out"], "file.bin")
        self.assertEqual(retry_calls[0][1][1]["load-cookies"], "/database/aria2/cookies.txt")

        self.aria.jobs["retry-1"]["completedLength"] = "10"
        self.clock.advance()
        self.coordinator.tick()

        self.assertNotIn("stopped-error", self.aria.jobs)
        self.assertEqual(self.store.read()["retry_paths"]["/workspace/file.bin"]["retry_count"], 0)

    def test_rpc_submission_failures_do_not_consume_transfer_retry_budget(self):
        self.aria.jobs.pop("gid-active")
        self.aria.jobs["stopped-error"] = {
            "gid": "stopped-error", "status": "error", "completedLength": "0",
            "totalLength": "1000", "errorCode": "1", "errorMessage": "failed",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }
        self.coordinator.tick()
        self.clock.advance(5)
        self.aria.fail_next["getOption"] = 1
        self.coordinator.tick()

        state = self.store.read()["retry_paths"]["/workspace/file.bin"]
        self.assertEqual(state["retry_count"], 0)
        self.assertEqual(state["submission_failures"], 1)
        self.assertFalse(state["pending_gid"])
        self.assertFalse(any(method == "addUri" for method, _ in self.aria.calls))

        self.clock.advance(5)
        self.aria.fail_next["addUri"] = 1
        self.coordinator.tick()
        state = self.store.read()["retry_paths"]["/workspace/file.bin"]
        self.assertEqual(state["retry_count"], 0)
        self.assertEqual(state["submission_failures"], 1)
        self.assertTrue(state["submission_unknown"])

        self.clock.advance(15)
        self.coordinator.tick()
        state = self.store.read()["retry_paths"]["/workspace/file.bin"]
        self.assertFalse(state["submission_unknown"])
        self.assertEqual(state["submission_failures"], 2)
        self.assertEqual(state["retry_count"], 0)

        self.clock.advance(15)
        self.coordinator.tick()
        state = self.store.read()["retry_paths"]["/workspace/file.bin"]
        self.assertEqual(state["retry_count"], 1)
        self.assertEqual(state["submission_failures"], 0)
        self.assertTrue(state["pending_gid"])

    def test_accepted_adduri_with_lost_response_is_reconciled_without_duplicate_submission(self):
        self.aria.jobs.pop("gid-active")
        self.aria.jobs["stopped-error"] = {
            "gid": "stopped-error", "status": "error", "completedLength": "0",
            "totalLength": "1000", "errorCode": "1", "errorMessage": "failed",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }
        self.coordinator.tick()
        self.clock.advance(5)
        self.aria.accept_then_fail_add_uri = True
        self.coordinator.tick()
        state = self.store.read()["retry_paths"]["/workspace/file.bin"]
        self.assertTrue(state["submission_unknown"])
        self.assertEqual(state["retry_count"], 0)
        self.assertEqual(len([call for call in self.aria.calls if call[0] == "addUri"]), 1)

        self.clock.advance(5)
        self.coordinator.tick()

        state = self.store.read()["retry_paths"]["/workspace/file.bin"]
        self.assertFalse(state["submission_unknown"])
        self.assertEqual(state["retry_count"], 1)
        self.assertEqual(state["pending_gid"], "retry-1")
        self.assertEqual(len([call for call in self.aria.calls if call[0] == "addUri"]), 1)

    def test_lost_response_does_not_adopt_a_historical_stopped_job_at_the_same_path(self):
        self.aria.jobs.pop("gid-active")
        self.aria.jobs["historical-complete"] = {
            "gid": "historical-complete", "status": "complete", "completedLength": "1000",
            "totalLength": "1000",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }
        self.aria.jobs["stopped-error"] = {
            "gid": "stopped-error", "status": "error", "completedLength": "0",
            "totalLength": "1000", "errorCode": "1", "errorMessage": "failed",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }
        self.coordinator.tick()
        self.clock.advance(5)
        self.aria.fail_next["addUri"] = 1
        self.coordinator.tick()
        self.assertTrue(self.store.read()["retry_paths"]["/workspace/file.bin"]["submission_unknown"])

        self.clock.advance(5)
        self.coordinator.tick()

        state = self.store.read()["retry_paths"]["/workspace/file.bin"]
        self.assertFalse(state["submission_unknown"])
        self.assertFalse(state.get("pending_gid"))
        self.assertEqual(state["retry_count"], 0)
        self.assertEqual(state["submission_failures"], 1)

    def test_live_duplicate_after_first_thousand_waiting_jobs_suppresses_retry(self):
        self.aria.jobs.pop("gid-active")
        for index in range(1001):
            gid = f"waiting-{index}"
            path = "/workspace/file.bin" if index == 1000 else f"/workspace/queued-{index}.bin"
            self.aria.jobs[gid] = {
                "gid": gid, "status": "waiting", "completedLength": "0",
                "totalLength": "1000",
                "files": [{"path": path, "uris": [{"uri": "https://host/file.bin"}]}],
            }
        self.aria.jobs["stopped-error"] = {
            "gid": "stopped-error", "status": "error", "completedLength": "0",
            "totalLength": "1000", "errorCode": "1", "errorMessage": "failed",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }

        self.coordinator.tick()
        self.clock.advance(5)
        self.coordinator.tick()

        self.assertFalse(any(method == "addUri" for method, _ in self.aria.calls))
        self.assertIn(
            ("tellWaiting", (1000, 1000, ["gid", "status", "completedLength", "totalLength", "files"])),
            self.aria.calls,
        )

    def test_queue_pagination_failure_defers_retry_without_erasing_error(self):
        self.aria.jobs.pop("gid-active")
        for index in range(1000):
            gid = f"waiting-{index}"
            self.aria.jobs[gid] = {
                "gid": gid, "status": "waiting", "completedLength": "0",
                "totalLength": "1000",
                "files": [{"path": f"/workspace/queued-{index}.bin", "uris": [{"uri": "https://host/queued.bin"}]}],
            }
        self.aria.jobs["stopped-error"] = {
            "gid": "stopped-error", "status": "error", "completedLength": "0",
            "totalLength": "1000", "errorCode": "1", "errorMessage": "failed",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }
        self.coordinator.tick()
        self.clock.advance(5)
        self.aria.fail_waiting_page = True

        self.coordinator.tick()

        state = self.store.read()["retry_paths"]["/workspace/file.bin"]
        self.assertEqual(state["canonical_gid"], "stopped-error")
        self.assertFalse(any(method == "addUri" for method, _ in self.aria.calls))
        self.assertFalse(any(
            method == "removeDownloadResult" and params == ("stopped-error",)
            for method, params in self.aria.calls
        ))

    def test_error_hook_event_triggers_retry_without_polling_all_stopped_rows_each_second(self):
        self.aria.jobs.pop("gid-active")
        gid = "0123456789abcdef"
        self.aria.jobs[gid] = {
            "gid": gid, "status": "error", "completedLength": "0",
            "totalLength": "1000", "errorCode": "1", "errorMessage": "failed",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }
        self.store.update(lambda state: state.update({
            "last_stopped_reconcile_at": 0,
            "error_event_gids": [gid],
        }))

        self.coordinator.tick()
        self.assertEqual(self.store.read()["error_event_gids"], [])
        self.assertFalse(any(method == "tellStopped" for method, _ in self.aria.calls))

        self.clock.advance(5)
        self.coordinator.tick()
        self.assertEqual(len([call for call in self.aria.calls if call[0] == "addUri"]), 1)
        self.assertEqual(len([call for call in self.aria.calls if call[0] == "tellStopped"]), 1)

    def test_error_hook_events_are_deferred_and_checked_one_per_tick(self):
        self.aria.jobs.pop("gid-active")
        gids = ["0123456789abcdef", "1123456789abcdef"]
        for gid in gids:
            self.aria.jobs[gid] = {
                "gid": gid, "status": "error", "completedLength": "0",
                "totalLength": "1000", "errorCode": "1", "errorMessage": "failed",
                "files": [{"path": f"/workspace/{gid}.bin", "uris": [{"uri": f"https://host/{gid}.bin"}]}],
            }
        self.store.update(lambda state: state.update({
            "last_stopped_reconcile_at": 0,
            "error_event_gids": gids,
            "error_event_seen_at": {gid: 0 for gid in gids},
        }))
        self.aria.fail_next["tellStatus"] = 1

        self.coordinator.tick()

        state = self.store.read()
        self.assertEqual(len([call for call in self.aria.calls if call[0] == "tellStatus"]), 1)
        self.assertEqual(state["error_event_gids"], gids)
        self.assertEqual(state["error_event_retry_after"][gids[0]], 60)
        self.assertEqual(state["error_event_seen_at"][gids[0]], 0)

    def test_active_same_path_suppresses_external_retry_and_manual_pause_is_never_recovered(self):
        self.aria.jobs["stopped-error"] = {
            "gid": "stopped-error", "status": "error", "completedLength": "0",
            "totalLength": "1000", "errorCode": "1", "errorMessage": "failed",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }
        self.coordinator.tick()
        self.clock.advance(5)
        self.coordinator.tick()
        self.assertFalse(any(method == "addUri" for method, _ in self.aria.calls))

        self.aria.jobs["gid-active"]["status"] = "paused"
        self.coordinator.tick()
        self.assertEqual(self.aria.jobs["gid-active"]["status"], "paused")
        self.assertFalse(any(method == "unpause" for method, _ in self.aria.calls))

    def test_external_retry_has_backoff_and_stops_after_ten_attempts(self):
        self.aria.jobs.pop("gid-active")
        self.aria.jobs["stopped-error"] = {
            "gid": "stopped-error", "status": "error", "completedLength": "0",
            "totalLength": "1000", "errorCode": "1", "errorMessage": "failed",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }
        self.coordinator.tick()
        attempts = 0
        for attempt in range(1, 11):
            delays = (5, 15, 30, 60, 120, 300)
            self.clock.advance(delays[min(attempt - 1, len(delays) - 1)])
            self.coordinator.tick()
            attempts = len([call for call in self.aria.calls if call[0] == "addUri"])
            self.assertEqual(attempts, attempt)
            retry_gid = f"retry-{attempt}"
            self.aria.jobs[retry_gid]["status"] = "error"
            self.clock.advance()
            self.coordinator.tick()
        self.clock.advance(600)
        self.coordinator.tick()
        self.assertEqual(len([call for call in self.aria.calls if call[0] == "addUri"]), 10)
        self.assertNotIn("retry-10", self.aria.jobs)

    def test_retry_backoff_and_attempt_count_survive_coordinator_restart(self):
        self.aria.jobs.pop("gid-active")
        self.aria.jobs["stopped-error"] = {
            "gid": "stopped-error", "status": "error", "completedLength": "0",
            "totalLength": "1000", "errorCode": "1", "errorMessage": "failed",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }
        self.store.update_retry("/workspace/file.bin", {
            "canonical_gid": "stopped-error",
            "retry_count": 2,
            "pending_gid": "",
            "next_retry_at": 15,
            "manual_stop": False,
        })
        self.store.update(lambda state: state.update({"last_stopped_reconcile_at": 1}))
        restarted = Aria2RecoveryCoordinator(
            self.aria, self.store, clock=self.clock, interval_seconds=1
        )

        restarted.tick()
        self.assertFalse(any(method == "addUri" for method, _ in self.aria.calls))
        self.clock.advance(15)
        restarted.tick()

        self.assertEqual(len([call for call in self.aria.calls if call[0] == "addUri"]), 1)
        self.assertEqual(
            self.store.read()["retry_paths"]["/workspace/file.bin"]["retry_count"], 3
        )

    def test_unsupported_protocol_is_not_retried(self):
        self.aria.jobs.pop("gid-active")
        self.aria.jobs["torrent-error"] = {
            "gid": "torrent-error", "status": "error", "completedLength": "0",
            "totalLength": "1000", "errorCode": "1", "errorMessage": "failed",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "magnet:?xt=urn:btih:test"}]}],
        }
        self.coordinator.tick()
        self.clock.advance(500)
        self.coordinator.tick()
        self.assertFalse(any(method == "addUri" for method, _ in self.aria.calls))

    def test_completed_zero_byte_replacement_removes_old_error_without_resetting_budget(self):
        self.aria.jobs.pop("gid-active")
        self.aria.jobs["stopped-error"] = {
            "gid": "stopped-error", "status": "error", "completedLength": "0",
            "totalLength": "0", "errorCode": "1", "errorMessage": "failed",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }
        self.aria.jobs["retry-complete"] = {
            "gid": "retry-complete", "status": "complete", "completedLength": "0",
            "totalLength": "0",
            "files": [{"path": "/workspace/file.bin", "uris": [{"uri": "https://host/file.bin"}]}],
        }
        self.store.update_retry("/workspace/file.bin", {
            "canonical_gid": "stopped-error",
            "pending_gid": "retry-complete",
            "old_gid": "stopped-error",
            "retry_count": 3,
            "baseline_completed": 0,
        })

        self.coordinator.tick()

        self.assertNotIn("stopped-error", self.aria.jobs)
        self.assertEqual(
            self.store.read()["retry_paths"]["/workspace/file.bin"]["retry_count"], 3
        )
        self.assertFalse(any(method == "addUri" for method, _ in self.aria.calls))


if __name__ == "__main__":
    unittest.main()
