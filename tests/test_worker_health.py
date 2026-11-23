from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tme3bot.application.worker_health import WorkerHealthMonitor


class FakeRegistry:
    def __init__(self, workers):
        self.workers = workers

    def list(self):
        return {name: dict(value) for name, value in self.workers.items()}


class WorkerHealthMonitorTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 22, tzinfo=timezone.utc)
        self.registry = FakeRegistry({
            "remote-1": {"enabled": True},
            "disabled": {"enabled": False},
        })
        self.calls = []
        self.monitor = WorkerHealthMonitor(
            self.registry,
            lambda name: self.calls.append(name) or {"healthy": name == "remote-1"},
            interval_seconds=30,
            max_age_seconds=60,
            clock=lambda: self.now,
        )

    def test_refresh_caches_health_without_exposing_worker_credentials(self):
        self.monitor.refresh_once()

        self.assertEqual(self.calls, ["remote-1"])
        self.assertEqual(self.monitor.snapshot("remote-1")["status"], "ready")
        self.assertEqual(self.monitor.snapshot("disabled")["status"], "disabled")
        self.assertNotIn("token", self.monitor.snapshot("remote-1"))

    def test_snapshot_distinguishes_unknown_offline_and_stale(self):
        self.assertEqual(self.monitor.snapshot("remote-1")["status"], "unknown")

        self.monitor.refresh_once()
        self.registry.workers["offline"] = {"enabled": True}
        self.monitor.refresh_once()
        self.assertEqual(self.monitor.snapshot("offline")["status"], "offline")

        self.now += timedelta(seconds=61)
        self.assertEqual(self.monitor.snapshot("remote-1")["status"], "stale")

    def test_probe_exception_is_cached_as_offline(self):
        self.monitor.checker = lambda _name: (_ for _ in ()).throw(OSError("offline"))
        self.monitor.refresh_once()

        snapshot = self.monitor.snapshot("remote-1")
        self.assertEqual(snapshot["status"], "offline")
        self.assertEqual(snapshot["healthy"], False)

    def test_unresponsive_override_survives_probe_until_cleared(self):
        self.monitor.refresh_once()
        self.monitor.mark_unresponsive(
            "remote-1", reason="event_backlog_cancel_unconfirmed"
        )

        self.monitor.refresh_once()
        snapshot = self.monitor.snapshot("remote-1")
        self.assertEqual(snapshot["status"], "unresponsive")
        self.assertEqual(
            snapshot["reason"], "event_backlog_cancel_unconfirmed"
        )
        self.assertFalse(snapshot["healthy"])

        self.monitor.clear_unresponsive("remote-1")
        self.assertEqual(self.monitor.snapshot("remote-1")["status"], "ready")


if __name__ == "__main__":
    unittest.main()
