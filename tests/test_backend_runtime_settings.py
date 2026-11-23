import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from tme3bot.backend_runtime_settings import BackendRuntimeSettings
from tme3bot.backup_coordinator import BackupScheduler


DEFAULTS = {
    "backup_enabled": True,
    "backup_schedule": "03:00",
    "backup_timezone": "Asia/Jakarta",
    "backup_retention": 7,
    "backup_volume_size": "45m",
    "backup_channel": "123",
    "storage_trash_retention_days": 30,
    "job_stall_timeout_seconds": 600,
    "job_cancel_grace_seconds": 30,
    "bot_token": "123456:abcdefghijklmnopqrstuvwxyzABCDE12345",
    "telegram_tts_chat_id": "",
}


class BackendRuntimeSettingsTests(unittest.TestCase):
    def test_settings_are_persisted_and_loaded_on_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            first = BackendRuntimeSettings(path, DEFAULTS)
            first.update({"backup_schedule": "04:20", "backup_retention": 14})

            second = BackendRuntimeSettings(path, DEFAULTS)

            self.assertEqual(second.get()["backup_schedule"], "04:20")
            self.assertEqual(second.get()["backup_retention"], 14)
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_update_does_not_replace_current_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = BackendRuntimeSettings(Path(directory) / "settings.json", DEFAULTS)
            with self.assertRaises(ValueError):
                settings.update({"backup_timezone": "Invalid/Timezone"})
            self.assertEqual(settings.get()["backup_timezone"], "Asia/Jakarta")

    def test_backup_scheduler_rechecks_settings_after_web_wake(self):
        calculated = threading.Event()
        scheduled = SimpleNamespace(backup_enabled=False, backup_schedule="03:00", backup_timezone="UTC")

        class Coordinator:
            def next_run(self):
                calculated.set()
                return datetime.now(timezone.utc) + timedelta(days=1)

            def start_now(self):
                raise AssertionError("Backup must not run before the scheduled time")

        scheduler = BackupScheduler(scheduled, Coordinator())
        scheduler.start()
        try:
            self.assertFalse(calculated.wait(0.1))
            scheduled.backup_enabled = True
            scheduler.wake()
            self.assertTrue(calculated.wait(1.0))
            scheduled.backup_enabled = False
            scheduler.wake()
        finally:
            scheduler.stop()
            if scheduler._thread is not None:
                scheduler._thread.join(timeout=1)

    def test_lite_disables_scheduled_backup_loop_but_manual_coordinator_remains_available(self):
        class Coordinator:
            def __init__(self):
                self.scheduled_checks = 0
                self.manual_runs = 0

            def next_run(self):
                self.scheduled_checks += 1
                return datetime.now(timezone.utc) + timedelta(days=1)

            def start_now(self):
                self.manual_runs += 1
                return "manual-run"

        coordinator = Coordinator()
        scheduler = BackupScheduler(
            SimpleNamespace(backup_enabled=True, backup_schedule="03:00", backup_timezone="UTC"),
            coordinator,
            scheduling_enabled=False,
        )

        scheduler.start()
        scheduler.wake()

        self.assertIsNone(scheduler._thread)
        self.assertEqual(coordinator.scheduled_checks, 0)
        self.assertEqual(coordinator.start_now(), "manual-run")
        self.assertEqual(coordinator.manual_runs, 1)


if __name__ == "__main__":
    unittest.main()
