from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tme3bot.worker.supervisor import WorkerSupervisor


class FakeApi:
    def __init__(self, command):
        self.command = command
        self.results = []

    def poll(self):
        return {"command": self.command}

    def report(self, operation_id, result):
        self.results.append((operation_id, dict(result)))


class FakeDocker:
    def __init__(self, *, stop_ok=True, start_ok=True, running=True):
        self.stop_ok = stop_ok
        self.start_ok = start_ok
        self.running = running
        self.calls = []

    def validate_target(self):
        self.calls.append(("validate",))

    def stop(self):
        self.calls.append(("stop",))
        if self.stop_ok:
            self.running = False
        return self.stop_ok

    def start(self):
        self.calls.append(("start",))
        if self.start_ok:
            self.running = True
        return self.start_ok

    def is_running(self):
        self.calls.append(("is_running",))
        return self.running


class WorkerSupervisorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = datetime(2026, 11, 25, tzinfo=timezone.utc)
        self.command = {
            "operation_id": "op-1",
            "idempotency_key": "op-1",
            "action": "restart_worker",
        }
        self.api = FakeApi(self.command)
        self.docker = FakeDocker()
        self.config = {
            "worker": "remote-1",
            "compose_root": "/www/wwwroot/downloads/bot",
            "compose_file": "docker-compose.worker.yml",
            "project": "worker-project",
            "service": "worker",
        }
        self.supervisor = WorkerSupervisor(
            self.config,
            self.api,
            self.docker,
            Path(self.temp.name) / "state.json",
            clock=lambda: self.now,
            min_restart_interval_seconds=120,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_restart_stops_and_starts_only_after_validating_fixed_target(self):
        self.supervisor.run_once()

        self.assertEqual(
            self.docker.calls,
            [("validate",), ("stop",), ("start",), ("is_running",)],
        )
        self.assertEqual(self.api.results[0][0], "op-1")
        self.assertEqual(
            self.api.results[0][1],
            {
                "container_stopped": True,
                "container_running": True,
                "restart_succeeded": True,
                "failure_code": "",
            },
        )

    def test_failure_before_stop_does_not_report_container_stopped(self):
        self.docker.stop_ok = False

        self.supervisor.run_once()

        result = self.api.results[0][1]
        self.assertFalse(result["container_stopped"])
        self.assertFalse(result["restart_succeeded"])
        self.assertEqual(self.docker.calls, [("validate",), ("stop",), ("is_running",)])

    def test_duplicate_delivery_reports_saved_result_without_restarting_again(self):
        self.supervisor.run_once()
        calls_after_first = list(self.docker.calls)

        self.supervisor.run_once()

        self.assertEqual(self.docker.calls, calls_after_first)
        self.assertEqual(len(self.api.results), 2)
        self.assertEqual(self.api.results[0], self.api.results[1])

    def test_restart_rate_limit_fails_before_docker_stop(self):
        self.supervisor.run_once()
        self.api.command = {
            "operation_id": "op-2",
            "idempotency_key": "op-2",
            "action": "restart_worker",
        }
        self.now += timedelta(seconds=30)

        self.supervisor.run_once()

        self.assertEqual(self.docker.calls.count(("stop",)), 1)
        self.assertEqual(self.api.results[-1][0], "op-2")
        self.assertEqual(self.api.results[-1][1]["failure_code"], "RESTART_RATE_LIMITED")
        self.assertFalse(self.api.results[-1][1]["container_stopped"])

    def test_unknown_or_arbitrary_command_is_never_run(self):
        self.api.command = {
            "operation_id": "op-evil",
            "idempotency_key": "op-evil",
            "action": "run_shell",
        }

        self.supervisor.run_once()

        self.assertEqual(self.docker.calls, [])
        self.assertEqual(self.api.results, [])

    def test_target_mismatch_fails_before_docker_commands(self):
        self.config["service"] = "backend"

        with self.assertRaises(ValueError):
            WorkerSupervisor(
                self.config,
                self.api,
                self.docker,
                Path(self.temp.name) / "invalid.json",
            )

        self.assertEqual(self.docker.calls, [])

    def test_recovery_finishes_restart_if_supervisor_crashed_after_container_stopped(self):
        state_path = Path(self.temp.name) / "state.json"
        state_path.write_text(
            '{"last_restart_at":"","operations":{"op-1":{"phase":"stopping"}}}',
            encoding="utf-8",
        )
        self.docker.running = False

        self.supervisor.run_once()

        self.assertEqual(self.docker.calls, [("is_running",), ("start",), ("is_running",)])
        self.assertTrue(self.api.results[0][1]["container_stopped"])
        self.assertTrue(self.api.results[0][1]["restart_succeeded"])

    def test_failed_stop_that_did_stop_container_still_starts_it(self):
        self.docker.stop_ok = False
        self.docker.running = False

        self.supervisor.run_once()

        self.assertEqual(self.docker.calls, [("validate",), ("stop",), ("is_running",), ("start",), ("is_running",)])
        self.assertTrue(self.api.results[0][1]["container_stopped"])
        self.assertTrue(self.api.results[0][1]["restart_succeeded"])


if __name__ == "__main__":
    unittest.main()
