import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from tme3bot.domain.models import DomainError
from tme3bot.worker.executor import WorkerJobExecutor
from tme3bot.worker.runtime_settings import WorkerRuntimeSettings


class RuntimeProfileManager:
    def __init__(self, root: Path, profiles: list[str]):
        self.profiles = profiles
        self.base_config = SimpleNamespace(
            default_profile="default",
            tdl_export_storage=root / "default" / ".tdl",
            profile_root=str(root / "default"),
        )

    def list_profiles(self):
        return list(self.profiles)


class WorkerRuntimeSettingsTests(unittest.TestCase):
    def test_storage_profile_override_persists_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker_settings.json"
            settings = WorkerRuntimeSettings(path, default_storage_profile="default")
            self.assertEqual(settings.storage_profile(), "default")

            settings.set_storage_profile("archive")
            restarted = WorkerRuntimeSettings(path, default_storage_profile="from-env")

            self.assertEqual(restarted.storage_profile(), "archive")

    def test_tts_overrides_and_password_persist_but_public_status_is_boolean(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker_settings.json"
            defaults = {
                "tts_helper_urls": ["http://one:5000", "http://two:5000", "http://three:5000"],
                "tts_tor_control_hosts": ["tor-one", "tor-two", "tor-three"],
                "tts_tor_control_ports": [9051, 9051, 9051],
                "tts_tor_control_password": "bootstrap-secret",
                "tts_part_retries": 4,
            }
            settings = WorkerRuntimeSettings(
                path, default_storage_profile="default", default_tts_settings=defaults
            )
            settings.set_tts_settings(
                {"tts_tor_control_password": "new-secret", "tts_part_retries": 6}
            )
            restarted = WorkerRuntimeSettings(
                path,
                default_storage_profile="default",
                default_tts_settings={**defaults, "tts_tor_control_password": "old-env-secret"},
            )

            self.assertEqual(restarted.tts_settings()["tts_part_retries"], 6)
            self.assertEqual(restarted.tts_settings()["tts_tor_control_password"], "new-secret")
            self.assertTrue(restarted.has_tts_password())

            restarted.set_tts_settings({"tts_tor_control_password": ""})
            self.assertFalse(restarted.has_tts_password())

    def test_worker_token_rotation_accepts_old_until_gateway_uses_new_token(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = WorkerRuntimeSettings(
                Path(directory) / "worker_settings.json",
                default_storage_profile="default",
                default_worker_api_token="initial-worker-token",
            )
            settings.set_worker_api_token("rotated-worker-token")
            self.assertTrue(settings.worker_token_matches("initial-worker-token"))
            self.assertTrue(settings.worker_token_matches("rotated-worker-token"))
            self.assertFalse(settings.worker_token_matches("initial-worker-token"))

    def test_operational_settings_persist_and_update_executor_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            defaults = {
                "job_stall_timeout_seconds": 600,
                "tdl_export_stall_timeout_seconds": 300,
                "tdl_download_stall_timeout_seconds": 300,
            }
            path = root / "worker_settings.json"
            settings = WorkerRuntimeSettings(
                path,
                default_storage_profile="default",
                default_operational_settings=defaults,
            )
            settings.set_operational_settings({"tdl_export_stall_timeout_seconds": 480})
            reloaded = WorkerRuntimeSettings(
                path,
                default_storage_profile="default",
                default_operational_settings=defaults,
            )
            self.assertEqual(reloaded.operational_settings()["tdl_export_stall_timeout_seconds"], 480)

            executor = self._executor_with_tts_settings(root)
            executor.runtime_settings.default_operational_settings = defaults
            updated = executor.update_worker_settings(
                {
                    "job_stall_timeout_seconds": 900,
                    "tdl_download_stall_timeout_seconds": 420,
                }
            )
            self.assertEqual(updated["job_stall_timeout_seconds"], 900)
            self.assertEqual(updated["tdl_download_stall_timeout_seconds"], 420)
            self.assertEqual(executor.config.job_stall_timeout_seconds, 900)
            self.assertEqual(executor.config.tdl_download_stall_timeout_seconds, 420)

    def test_operational_settings_cannot_change_while_any_job_is_active(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            defaults = {"job_stall_timeout_seconds": 600}
            executor = self._executor_with_tts_settings(
                root, active={"job-1": ("default", "export")}
            )
            executor.runtime_settings.default_operational_settings = defaults

            with self.assertRaises(DomainError) as raised:
                executor.update_worker_settings({"job_stall_timeout_seconds": 900})

            self.assertEqual(raised.exception.code, "WORKER_SETTINGS_BUSY")
            self.assertEqual(executor.runtime_settings.operational_settings()["job_stall_timeout_seconds"], 600)

    def _executor_with_tts_settings(self, root: Path, *, active=None):
        executor = WorkerJobExecutor.__new__(WorkerJobExecutor)
        executor.config = SimpleNamespace(state_file=root / "state.json")
        executor.profile_manager = RuntimeProfileManager(root, ["default"])
        executor.runtime_settings = WorkerRuntimeSettings(
            root / "worker_settings.json",
            default_storage_profile="default",
            default_tts_settings={
                "tts_helper_urls": ["http://one:5000", "http://two:5000", "http://three:5000"],
                "tts_tor_control_hosts": ["tor-one", "tor-two", "tor-three"],
                "tts_tor_control_ports": [9051, 9051, 9051],
                "tts_tor_control_password": "bootstrap-secret",
                "tts_part_retries": 4,
                "tts_retry_base_seconds": 2.0,
                "tts_newnym_after_retries": 3,
            },
        )
        executor._lock = threading.RLock()
        executor._active = active or {}
        executor._active_commands = {}
        executor._quick_active = set()
        executor._quick_verify_active = set()
        return executor

    def test_invalid_tts_helper_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            executor = self._executor_with_tts_settings(Path(directory))
            with self.assertRaises(DomainError) as raised:
                executor.update_worker_settings({"tts_helper_urls": ["file:///etc/passwd", "http://two:5000", "http://three:5000"]})
            self.assertEqual(raised.exception.code, "INVALID_TTS_SETTINGS")

    def test_tts_settings_cannot_change_while_tts_job_is_running(self):
        with tempfile.TemporaryDirectory() as directory:
            executor = self._executor_with_tts_settings(
                Path(directory), active={"job-1": ("default", "tts")}
            )
            with self.assertRaises(DomainError) as raised:
                executor.update_worker_settings({"tts_part_retries": 5})
            self.assertEqual(raised.exception.code, "WORKER_SETTINGS_BUSY")

    def test_web_setting_only_accepts_profiles_with_local_tdl_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_path = root / "default" / ".tdl"
            session_path.mkdir(parents=True)
            manager = RuntimeProfileManager(root, ["default", "archive"])
            executor = WorkerJobExecutor.__new__(WorkerJobExecutor)
            executor.config = SimpleNamespace(
                state_file=root / "state.json", worker_storage_profile="archive"
            )
            executor.profile_manager = manager
            executor.runtime_settings = WorkerRuntimeSettings(
                root / "worker_settings.json", default_storage_profile="archive"
            )
            executor._lock = threading.RLock()
            executor._active = {}
            executor._active_commands = {}
            executor._quick_active = set()
            executor._quick_verify_active = set()

            self.assertEqual(executor.available_storage_profiles(), ["default"])
            self.assertFalse(executor.worker_settings()["storage_profile_available"])
            with self.assertRaises(DomainError) as raised:
                executor.update_storage_profile("archive")
            self.assertEqual(raised.exception.code, "STORAGE_PROFILE_UNAVAILABLE")

            saved = executor.update_storage_profile("default")
            self.assertEqual(saved["storage_profile"], "default")
            self.assertTrue(saved["storage_profile_available"])

    def test_profile_cannot_change_while_storage_job_is_running(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "default" / ".tdl").mkdir(parents=True)
            executor = WorkerJobExecutor.__new__(WorkerJobExecutor)
            executor.config = SimpleNamespace(
                state_file=root / "state.json", worker_storage_profile="default"
            )
            executor.profile_manager = RuntimeProfileManager(root, ["default"])
            executor.runtime_settings = WorkerRuntimeSettings(
                root / "worker_settings.json", default_storage_profile="default"
            )
            executor._lock = threading.RLock()
            executor._active = {"storage-job": ("default", "storage_upload")}
            executor._active_commands = {}
            executor._quick_active = set()
            executor._quick_verify_active = set()

            with self.assertRaises(DomainError) as raised:
                executor.update_storage_profile("default")
            self.assertEqual(raised.exception.code, "WORKER_SETTINGS_BUSY")

    def test_profile_cannot_change_during_quickmode_before_quick_lane_is_marked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "default" / ".tdl").mkdir(parents=True)
            executor = WorkerJobExecutor.__new__(WorkerJobExecutor)
            executor.config = SimpleNamespace(
                state_file=root / "state.json", worker_storage_profile="default"
            )
            executor.profile_manager = RuntimeProfileManager(root, ["default"])
            executor.runtime_settings = WorkerRuntimeSettings(
                root / "worker_settings.json", default_storage_profile="default"
            )
            executor._lock = threading.RLock()
            executor._active = {"quick-job": ("default", "export")}
            executor._active_commands = {
                "quick-job": {"kind": "export", "payload": {"quick_mode": True}}
            }
            executor._quick_active = set()
            executor._quick_verify_active = set()

            with self.assertRaises(DomainError) as raised:
                executor.update_storage_profile("default")
            self.assertEqual(raised.exception.code, "WORKER_SETTINGS_BUSY")


if __name__ == "__main__":
    unittest.main()
