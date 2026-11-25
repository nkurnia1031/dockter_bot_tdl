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

    def test_on_demand_unhealthy_result_requires_two_failed_probes(self):
        calls = []
        self.monitor.checker = lambda name: calls.append(name) or {"healthy": False}

        snapshot = self.monitor.probe_worker("remote-1")

        self.assertEqual(calls, ["remote-1", "remote-1"])
        self.assertEqual(snapshot["status"], "offline")
        self.assertEqual(snapshot["health_probe_failures"], 2)
        self.assertTrue(snapshot["restart_probe_confirmed"])

    def test_snapshot_does_not_turn_unknown_or_stale_into_unresponsive(self):
        self.monitor.mark_unresponsive(
            "remote-1", reason="operator_stop_cancel_unconfirmed"
        )

        self.assertEqual(self.monitor.snapshot("remote-1")["status"], "unknown")
        self.assertTrue(
            self.monitor.snapshot("remote-1")["cancellation_unconfirmed"]
        )

        self.monitor.refresh_once()
        self.now += timedelta(seconds=61)
        snapshot = self.monitor.snapshot("remote-1")
        self.assertEqual(snapshot["status"], "stale")
        self.assertTrue(snapshot["cancellation_unconfirmed"])

    def test_healthy_probe_does_not_keep_worker_quarantined_for_old_cancel(self):
        self.monitor.refresh_once()
        self.monitor.mark_unresponsive(
            "remote-1", reason="event_backlog_cancel_unconfirmed"
        )

        self.monitor.refresh_once()
        snapshot = self.monitor.snapshot("remote-1")
        self.assertEqual(snapshot["status"], "ready")
        self.assertTrue(snapshot["healthy"])
        self.assertTrue(snapshot["cancellation_unconfirmed"])

        self.monitor.clear_unresponsive("remote-1")
        self.assertEqual(self.monitor.snapshot("remote-1")["status"], "ready")

    def test_failed_probe_keeps_unconfirmed_cancel_visible(self):
        self.monitor.mark_unresponsive(
            "remote-1", reason="event_backlog_cancel_unconfirmed"
        )
        self.monitor.checker = lambda _name: {"healthy": False}
        self.monitor.refresh_once()

        snapshot = self.monitor.snapshot("remote-1")
        self.assertEqual(snapshot["status"], "offline")
        self.assertEqual(
            snapshot["reason"], "event_backlog_cancel_unconfirmed"
        )
        self.assertFalse(snapshot["healthy"])


if __name__ == "__main__":
    unittest.main()
