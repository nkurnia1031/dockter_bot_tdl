import unittest

from tme3bot.background_schedule import (
    GatewayBackgroundSchedule,
    run_event_driven_loop,
)


class _StopSignal:
    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True


class _WakeSignal:
    def __init__(self, *, signalled):
        self.signalled = signalled
        self.timeouts = []
        self.clears = 0

    def wait(self, timeout):
        self.timeouts.append(timeout)
        return self.signalled

    def clear(self):
        self.clears += 1


class BackgroundScheduleTests(unittest.TestCase):
    def test_full_keeps_existing_background_cadence(self):
        schedule = GatewayBackgroundSchedule.for_mode("full")

        self.assertEqual(schedule.job_recovery_seconds, 2)
        self.assertEqual(schedule.queue_recovery_seconds, 2)
        self.assertEqual(schedule.queue_reconcile_seconds, 20)
        self.assertEqual(schedule.profile_distribution_seconds, 3)
        self.assertEqual(schedule.profile_provisioning_seconds, 10)
        self.assertEqual(schedule.storage_recovery_seconds, 60)
        self.assertEqual(schedule.storage_trash_seconds, 60)
        self.assertTrue(schedule.scheduled_backups_enabled)

    def test_lite_uses_configured_recovery_and_slower_trash_without_scheduled_backups(self):
        schedule = GatewayBackgroundSchedule.for_mode(
            "lite", recovery_seconds=45, trash_seconds=7200
        )

        self.assertEqual(schedule.job_recovery_seconds, 45)
        self.assertEqual(schedule.queue_recovery_seconds, 45)
        self.assertEqual(schedule.queue_reconcile_seconds, 45)
        self.assertEqual(schedule.profile_distribution_seconds, 45)
        self.assertEqual(schedule.profile_provisioning_seconds, 45)
        self.assertEqual(schedule.storage_recovery_seconds, 45)
        self.assertEqual(schedule.storage_trash_seconds, 7200)
        self.assertFalse(schedule.scheduled_backups_enabled)

    def test_wake_and_recovery_timeout_both_run_the_maintenance_callback(self):
        for signalled in (True, False):
            with self.subTest(signalled=signalled):
                stop = _StopSignal()
                wake = _WakeSignal(signalled=signalled)
                calls = []

                def callback():
                    calls.append("tick")
                    stop.set()

                run_event_driven_loop(
                    stop,
                    wake,
                    recovery_seconds=30,
                    callback=callback,
                )

                self.assertEqual(calls, ["tick"])
                self.assertEqual(wake.timeouts, [30])
                self.assertEqual(wake.clears, 1)


if __name__ == "__main__":
    unittest.main()
