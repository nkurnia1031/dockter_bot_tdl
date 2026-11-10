from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from tme3bot.worker.executor import WorkerJobExecutor


class FakeUploadClient:
    def __init__(self, profile: str, calls: list[tuple[str, str, str]], outcomes=None) -> None:
        self.profile = profile
        self.calls = calls
        self.sent_messages: list[dict[str, object]] = []
        self.export_requests: list[tuple[str, int, int]] = []
        self.progress_callback = None
        self.outcomes = list(outcomes or [])

    def upload(self, file_path, chat_ref, caption, *, status_callback=None):
        if status_callback is not None:
            status_callback("uploading")
        self.calls.append((self.profile, Path(file_path).name, chat_ref))
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            if outcome is not None:
                self.sent_messages.append({
                    "id": getattr(outcome, "message_id", len(self.calls)),
                    "date": time.time(),
                    "file_name": Path(file_path).name,
                    "caption": caption,
                })
                return outcome
        self.sent_messages.append({
            "id": len(self.calls),
            "date": time.time(),
            "file_name": Path(file_path).name,
            "caption": caption,
        })
        return SimpleNamespace(message_id=len(self.calls), output="ok")

    def export_messages_by_time(self, chat_ref, start, end, export_path, *, with_content=True):
        del export_path, with_content
        self.export_requests.append((chat_ref, start, end))
        return SimpleNamespace(messages=[
            message for message in self.sent_messages
            if start <= float(message["date"]) <= end
        ])


class FakeProfileManager:
    def __init__(self, clients: dict[str, FakeUploadClient]) -> None:
        self.clients = clients

    def runtime(self, profile: str):
        return SimpleNamespace(
            upload_tdl_client=self.clients[profile],
            export_tdl_client=self.clients[profile],
            export_operation_lock=threading.RLock(),
            upload_operation_lock=threading.RLock(),
        )

    def list_profiles(self):
        return list(self.clients)

    def local_profiles(self):
        # The durable worker start hook must not need to prepare upload lanes
        # for these focused command-boundary tests.
        return []


class FakePublisher:
    def __init__(self) -> None:
        self.events = []
        self._lock = threading.RLock()

    @property
    def sender_ready(self):
        return True

    def attach_outbox(self, _outbox):
        pass

    def start_sender(self):
        pass

    def begin(self, *_args):
        pass

    def bind_job_worker(self, *_args):
        pass

    def bind_command(self, *_args):
        pass

    def register_audit_callback(self, *_args):
        pass

    def unregister_audit_callback(self, *_args):
        pass

    def forget(self, *_args):
        pass

    def emit(self, job_id, status, event_type, **kwargs):
        with self._lock:
            self.events.append({
                "job_id": job_id,
                "status": status,
                "event_type": event_type,
                **kwargs,
            })

    def events_for(self, job_id):
        with self._lock:
            return [event for event in self.events if event["job_id"] == job_id]


class ChatSendWorkerTests(unittest.TestCase):
    def _run_job(
        self,
        workspace: Path,
        clients: dict[str, FakeUploadClient],
        job_id: str,
        payload: dict,
        *,
        profile: str = "default",
    ):
        database_root = workspace.parent / f"{workspace.name}-database"
        database_root.mkdir(parents=True, exist_ok=True)
        config = SimpleNamespace(
            state_file=database_root / "state.json",
            database_root=database_root,
            utility_workspace_root=workspace,
            backup_node_name="local",
            temp_root=database_root / "tmp",
            default_profile=profile,
            worker_api_token="",
            worker_storage_profile="storage",
            job_stall_timeout_seconds=600,
            tdl_export_stall_timeout_seconds=300,
            tdl_download_stall_timeout_seconds=300,
            tts_helper_urls=(),
            tts_tor_control_hosts=(),
            tts_tor_control_ports=(),
            tts_part_retries=4,
            tts_retry_base_seconds=2.0,
            tts_newnym_after_retries=3,
        )
        publisher = FakePublisher()
        executor = WorkerJobExecutor(config, FakeProfileManager(clients), publisher)
        command_id = f"command-{job_id}"
        envelope = {
            "command_id": command_id,
            "job_id": job_id,
            "operation_id": f"operation-{job_id}",
            "attempt": 1,
            "dispatch_token": f"dispatch-{job_id}",
            "event_sequence_start": 1,
            "execution_plan": {},
            "job": {
                "kind": "chat_send",
                "profile": profile,
                "actor_user_id": 42,
                "worker": "local",
                "payload": payload,
            },
        }
        executor.start()
        try:
            deadline = time.monotonic() + 2
            while not executor.durable_commands_ready() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(executor.durable_commands_ready())
            executor.accept_durable_command(envelope)

            deadline = time.monotonic() + 5
            status = executor.durable_command_status(command_id)
            while status and status["status"] not in {
                "succeeded", "failed", "cancelled", "needs_reconciliation",
            } and time.monotonic() < deadline:
                time.sleep(0.01)
                status = executor.durable_command_status(command_id)
            self.assertIsNotNone(status)
            self.assertIn(status["status"], {
                "succeeded", "failed", "cancelled", "needs_reconciliation",
            })
            events = publisher.events_for(job_id)
            result_event = next(
                (event for event in reversed(events) if isinstance(event.get("result"), dict)
                 and isinstance(event["result"].get("value"), dict)),
                None,
            )
            self.assertIsNotNone(result_event, events)
            return result_event["result"]["value"], events
        finally:
            executor.command_runner.stop()
            executor._jobs.stop()

    def test_chat_send_recurses_selected_folders_and_records_each_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            first = workspace / "first"
            nested = first / "nested"
            second = workspace / "second"
            nested.mkdir(parents=True)
            second.mkdir()
            (first / "one.txt").write_text("one")
            (nested / "two.bin").write_bytes(b"two")
            (second / "three.zip").write_bytes(b"three")
            calls: list[tuple[str, str, str]] = []
            result, emitted = self._run_job(
                workspace,
                {"default": FakeUploadClient("default", calls)},
                "chat-send-1",
                {
                    "chat_ref": "@target",
                    "folders": [str(first), str(second)],
                    "_tdl_sender_profiles": ["default"],
                    "transfer_mode": "copy",
                },
            )

            self.assertEqual(
                calls,
                [
                    ("default", "two.bin", "@target"),
                    ("default", "one.txt", "@target"),
                    ("default", "three.zip", "@target"),
                ],
            )
            self.assertEqual(result["succeeded"], 3)
            self.assertEqual(result["failed"], 0)
            self.assertEqual(
                [item["path"] for item in result["items"]],
                ["first/nested/two.bin", "first/one.txt", "second/three.zip"],
            )
            self.assertTrue(any(
                event["event_type"] == "chat_send.progress"
                for event in emitted
            ))

    def test_chat_send_verifies_each_file_through_same_profile_export_lane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            folder = workspace / "batch"
            folder.mkdir()
            (folder / "episode 7.mkv").write_bytes(b"video")
            calls: list[tuple[str, str, str]] = []
            client = FakeUploadClient("irang", calls)

            result, _emitted = self._run_job(
                workspace,
                {"irang": client},
                "chat-send-export-verification",
                {
                    "chat_ref": "@target",
                    "folders": [str(folder)],
                    "_tdl_sender_profiles": ["irang"],
                },
            )

        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["items"][0]["message_id"], 1)
        self.assertEqual(len(client.export_requests), 1)
        self.assertEqual(client.export_requests[0][0], "@target")
        self.assertLessEqual(
            client.export_requests[0][2] - client.export_requests[0][1], 120
        )

    def test_chat_send_does_not_follow_symlinks_or_escape_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "workspace"
            root.mkdir()
            outside = Path(temp_dir) / "outside.txt"
            outside.write_text("private")
            selected = root / "selected"
            selected.mkdir()
            (selected / "safe.txt").write_text("safe")
            (selected / "escape.txt").symlink_to(outside)
            calls: list[tuple[str, str, str]] = []
            result, _emitted = self._run_job(
                root,
                {"default": FakeUploadClient("default", calls)},
                "chat-send-2",
                {
                    "chat_ref": "123456789",
                    "folders": [str(selected)],
                    "_tdl_sender_profiles": ["default"],
                    "transfer_mode": "copy",
                },
            )

            self.assertEqual(calls, [("default", "safe.txt", "123456789")])
            self.assertEqual(result["succeeded"], 1)
            self.assertFalse(any("escape.txt" in item["path"] for item in result["items"]))

    def test_chat_send_rotates_profiles_after_each_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            folder = workspace / "batch"
            folder.mkdir()
            for name in ("one", "two", "three"):
                (folder / f"{name}.txt").write_text(name)
            calls: list[tuple[str, str, str]] = []
            result, _ = self._run_job(workspace, {
                "default": FakeUploadClient("default", calls),
                "archive": FakeUploadClient("archive", calls),
            }, "chat-send-rotate", {
                    "chat_ref": "@target", "folders": [str(folder)],
                    "_tdl_sender_profiles": ["default", "archive"],
            })

            self.assertEqual([item[0] for item in calls], ["default", "archive", "default"])
            self.assertEqual([item["profile"] for item in result["items"]], ["default", "archive", "default"])
            self.assertEqual(result["succeeded"], 3)

    def test_chat_send_falls_back_only_on_explicit_access_denial(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            folder = workspace / "batch"
            folder.mkdir()
            (folder / "one.txt").write_text("one")
            (folder / "two.txt").write_text("two")
            calls: list[tuple[str, str, str]] = []
            result, _ = self._run_job(workspace, {
                "default": FakeUploadClient("default", calls, [RuntimeError("CHAT_FORBIDDEN")]),
                "archive": FakeUploadClient("archive", calls),
            }, "chat-send-fallback", {
                    "chat_ref": "@target", "folders": [str(folder)],
                    "_tdl_sender_profiles": ["default", "archive"],
            })

            self.assertEqual([item[0] for item in calls], ["default", "archive", "default"])
            self.assertEqual(result["items"][0]["status"], "succeeded")
            self.assertEqual([attempt["profile"] for attempt in result["items"][0]["attempts"]], ["default", "archive"])
            self.assertEqual(result["items"][1]["profile"], "default")

    def test_chat_send_rotates_starting_profile_after_all_senders_are_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            folder = workspace / "batch"
            folder.mkdir()
            (folder / "one.txt").write_text("one")
            (folder / "two.txt").write_text("two")
            calls: list[tuple[str, str, str]] = []

            def denied_twice():
                return [RuntimeError("CHAT_FORBIDDEN") for _ in range(2)]

            result, _ = self._run_job(workspace, {
                "default": FakeUploadClient("default", calls, denied_twice()),
                "archive": FakeUploadClient("archive", calls, denied_twice()),
            }, "chat-send-denied", {
                    "chat_ref": "@target", "folders": [str(folder)],
                    "_tdl_sender_profiles": ["default", "archive"],
            })

            self.assertEqual(
                [profile for profile, _name, _chat in calls],
                ["default", "archive", "archive", "default"],
            )
            self.assertEqual(result["failed"], 2)
            self.assertTrue(all(item["retryable"] for item in result["items"]))

    def test_chat_send_does_not_retry_ambiguous_upload_on_another_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            folder = workspace / "batch"
            folder.mkdir()
            (folder / "one.txt").write_text("one")
            calls: list[tuple[str, str, str]] = []
            result, _ = self._run_job(workspace, {
                "default": FakeUploadClient("default", calls, [TimeoutError("network timeout")]),
                "archive": FakeUploadClient("archive", calls),
            }, "chat-send-ambiguous", {
                    "chat_ref": "@target", "folders": [str(folder)],
                    "_tdl_sender_profiles": ["default", "archive"],
            })

            self.assertEqual([item[0] for item in calls], ["default"])
            self.assertEqual(result["items"][0]["status"], "ambiguous")
            self.assertFalse(result["items"][0]["retryable"])

    def test_chat_send_move_deletes_only_confirmed_successful_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            folder = workspace / "batch"
            folder.mkdir()
            success = folder / "a_success.txt"
            failure = folder / "z_failure.txt"
            success.write_text("success")
            failure.write_text("failure")
            calls: list[tuple[str, str, str]] = []
            result, _ = self._run_job(workspace, {
                "default": FakeUploadClient("default", calls, [None, RuntimeError("CHAT_FORBIDDEN")]),
            }, "chat-send-move", {
                    "chat_ref": "@target", "folders": [str(folder)],
                    "_tdl_sender_profiles": ["default"], "transfer_mode": "move",
            })

            by_name = {item["name"]: item for item in result["items"]}
            self.assertFalse(success.exists())
            self.assertTrue(failure.exists())
            self.assertEqual(by_name["a_success.txt"]["cleanup_status"], "deleted")
            self.assertEqual(by_name["z_failure.txt"]["cleanup_status"], "retained_upload_failed")

    def test_chat_send_move_keeps_source_if_file_changes_during_upload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            folder = workspace / "batch"
            folder.mkdir()
            source = folder / "file.txt"
            source.write_text("before")
            calls: list[tuple[str, str, str]] = []

            class MutatingUploadClient(FakeUploadClient):
                def upload(self, file_path, chat_ref, caption, *, status_callback=None):
                    source.write_text("changed after upload began")
                    return super().upload(file_path, chat_ref, caption, status_callback=status_callback)

            result, _ = self._run_job(workspace, {
                "default": MutatingUploadClient("default", calls),
            }, "chat-send-move-changed", {
                    "chat_ref": "@target", "folders": [str(folder)],
                    "_tdl_sender_profiles": ["default"], "transfer_mode": "move",
            })

            self.assertTrue(source.exists())
            self.assertEqual(result["items"][0]["status"], "succeeded")
            self.assertEqual(result["items"][0]["cleanup_status"], "cleanup_skipped_source_changed")

    def test_chat_send_move_uses_starting_identity_for_later_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            folder = workspace / "batch"
            folder.mkdir()
            first = folder / "a_first.txt"
            later = folder / "z_later.txt"
            first.write_text("first")
            later.write_text("later before upload")
            calls: list[tuple[str, str, str]] = []

            class MutatingUploadClient(FakeUploadClient):
                def upload(self, file_path, chat_ref, caption, *, status_callback=None):
                    if Path(file_path).name == first.name:
                        later.write_text("later changed before its turn")
                    return super().upload(file_path, chat_ref, caption, status_callback=status_callback)

            result, _ = self._run_job(workspace, {
                "default": MutatingUploadClient("default", calls),
            }, "chat-send-move-later-changed", {
                "chat_ref": "@target", "folders": [str(folder)],
                "_tdl_sender_profiles": ["default"], "transfer_mode": "move",
            })

            by_name = {item["name"]: item for item in result["items"]}
            self.assertFalse(first.exists())
            self.assertTrue(later.exists())
            self.assertEqual([name for _profile, name, _chat in calls], [first.name])
            self.assertEqual(by_name[first.name]["cleanup_status"], "deleted")
            self.assertEqual(by_name[later.name]["status"], "failed")
            self.assertEqual(
                by_name[later.name]["cleanup_status"],
                "cleanup_skipped_source_changed",
            )

    def test_chat_send_retry_reports_missing_source_instead_of_empty_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            folder = workspace / "batch"
            folder.mkdir()
            calls: list[tuple[str, str, str]] = []
            result, _ = self._run_job(workspace, {
                "default": FakeUploadClient("default", calls),
            }, "chat-send-retry-missing", {
                    "chat_ref": "@target", "folders": [str(folder)],
                    "_tdl_sender_profiles": ["default"],
                    "_retry_paths": ["batch/missing.txt"],
            })

            self.assertEqual(calls, [])
            self.assertEqual(result["outcome"], "failed")
            self.assertEqual(result["items"][0]["path"], "batch/missing.txt")
            self.assertEqual(result["items"][0]["error_code"], "CHAT_SEND_SOURCE_MISSING")
            self.assertFalse(result["items"][0]["retryable"])


if __name__ == "__main__":
    unittest.main()
