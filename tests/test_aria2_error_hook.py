from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HOOK_PATH = Path(__file__).parents[1] / "docker/aria2/aria2-retry-on-low-speed.py"


def load_hook():
    spec = importlib.util.spec_from_file_location("aria2_error_hook", HOOK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load aria2 error hook")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Aria2ErrorHookTests(unittest.TestCase):
    def test_hook_records_error_for_coordinator_without_rpc_or_retry(self):
        hook = load_hook()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hook.STATUS_FILE = root / "aria2-hook-status.json"
            hook.STATUS_LOCK_FILE = root / "aria2-hook-status.lock"
            hook.RECOVERY_FILE = root / "aria2-recovery.json"
            hook.RECOVERY_LOCK_FILE = root / "aria2-recovery.json.lock"

            with patch("sys.argv", ["aria2-error-hook", "0123456789abcdef"]):
                self.assertEqual(hook.main(), 0)
                self.assertEqual(hook.main(), 0)

            status = json.loads(hook.STATUS_FILE.read_text(encoding="utf-8"))
            self.assertEqual(status["hookRunCount"], 2)
            self.assertEqual(status["lastHookResult"], "coordinator-observes-error")
            self.assertEqual(hook.STATUS_FILE.stat().st_mode & 0o777, 0o600)
            recovery = json.loads(hook.RECOVERY_FILE.read_text(encoding="utf-8"))
            self.assertEqual(recovery["error_event_gids"], ["0123456789abcdef"])
            self.assertEqual(hook.RECOVERY_FILE.stat().st_mode & 0o777, 0o600)

    def test_hook_recovers_from_invalid_status_content(self):
        hook = load_hook()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hook.STATUS_FILE = root / "aria2-hook-status.json"
            hook.STATUS_LOCK_FILE = root / "aria2-hook-status.lock"
            hook.RECOVERY_FILE = root / "aria2-recovery.json"
            hook.RECOVERY_LOCK_FILE = root / "aria2-recovery.json.lock"
            hook.STATUS_FILE.write_text("[]", encoding="utf-8")

            with patch("sys.argv", ["aria2-error-hook"]):
                self.assertEqual(hook.main(), 0)

            status = json.loads(hook.STATUS_FILE.read_text(encoding="utf-8"))
            self.assertEqual(status["hookRunCount"], 1)
            self.assertIsNone(status["containerStartedAt"])

    def test_hook_preserves_corrupt_recovery_state_instead_of_resetting_retry_history(self):
        hook = load_hook()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hook.STATUS_FILE = root / "aria2-hook-status.json"
            hook.STATUS_LOCK_FILE = root / "aria2-hook-status.lock"
            hook.RECOVERY_FILE = root / "aria2-recovery.json"
            hook.RECOVERY_LOCK_FILE = root / "aria2-recovery.json.lock"
            original = b'{"version":'
            hook.RECOVERY_FILE.write_bytes(original)

            with patch("sys.argv", ["aria2-error-hook", "0123456789abcdef"]):
                self.assertEqual(hook.main(), 1)

            self.assertEqual(hook.RECOVERY_FILE.read_bytes(), original)
            status = json.loads(hook.STATUS_FILE.read_text(encoding="utf-8"))
            self.assertEqual(status["lastHookResult"], "hook-error")


if __name__ == "__main__":
    unittest.main()
