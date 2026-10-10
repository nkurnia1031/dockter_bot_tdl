import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tme3bot.config import AppConfig
from tme3bot.worker.profile_sessions import ProfileSessionManager
from tme3bot.worker.executor import WorkerJobExecutor


def make_config(root: Path) -> AppConfig:
    return AppConfig(
        bot_token="",
        app_role="worker",
        profile_root=str(root / "data"),
        profiles_root=root / "data/profiles",
        default_profile="default",
        tme3_host="t.me3",
        download_root=root / "data/download",
        export_pending_dir=root / "data/exports/pending",
        export_processing_dir=root / "data/exports/processing",
        export_done_dir=root / "data/exports/done",
        export_failed_dir=root / "data/exports/failed",
        state_file=root / "data/state.json",
        legacy_max_json=root / "data/max.json",
        tdl_export_user="user1",
        tdl_download_user="root",
        tdl_export_home=root / "data/user1",
        tdl_download_home=root / "data/root",
        tdl_export_storage=root / "data/user1/.tdl",
        tdl_download_storage=root / "data/root/.tdl",
        tdl_export_namespace="export-ns",
        tdl_download_namespace="download-ns",
        tdl_export_stall_timeout_seconds=300,
        tdl_download_stall_timeout_seconds=300,
        temp_root=root / "tmp",
        log_level="INFO",
        leave_helper_binary="/usr/local/bin/tdl-leave",
    )


class ProfileTdlDiagnosticsTests(unittest.TestCase):
    def prepare_profile(self, config: AppConfig, profile: str = "default") -> Path:
        if profile == "default":
            root = Path(config.profile_root)
        else:
            root = config.profiles_root / profile
        root.mkdir(parents=True, exist_ok=True)
        (root / "identity.json").write_text(
            json.dumps({"telegram_user_id": 424242}), encoding="utf-8"
        )
        for session in ("root/.tdl", "user1/.tdl"):
            data = root / session / "data"
            data.mkdir(parents=True, exist_ok=True)
            namespace = "download-ns" if session.startswith("root/") else "export-ns"
            (data / namespace).write_bytes(b"bolt database")
        return root

    def test_tdl_diagnosis_checks_each_session_with_its_own_runtime_config(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = make_config(root)
            profile_root = self.prepare_profile(config)
            manager = ProfileSessionManager(config)
            commands = []
            snapshot_databases = []

            def fake_run(command, *, cwd, env, timeout, stdout, stderr, check):
                commands.append((command, Path(cwd), env["HOME"], timeout))
                copied_database = Path(command[command.index("--storage") + 1]) / command[command.index("--namespace") + 1]
                snapshot_databases.append((copied_database, copied_database.read_bytes()))
                identity_file = Path(command[command.index("--identity-file") + 1])
                identity_file.write_text(
                    json.dumps({"telegram_user_id": 424242}), encoding="utf-8"
                )
                return subprocess.CompletedProcess(command, 0)

            with patch("tme3bot.worker.profile_sessions.subprocess.run", side_effect=fake_run):
                result = manager.diagnose_tdl_sessions("default")

            self.assertTrue(result["ready"])
            self.assertTrue(result["identity_match"])
            self.assertEqual([item["name"] for item in result["sessions"]], ["root", "user1"])
            self.assertEqual(len(commands), 2)
            root_command, root_cwd, root_home, root_timeout = commands[0]
            export_command, export_cwd, export_home, export_timeout = commands[1]
            self.assertEqual(root_command[:4], ["runuser", "-u", "root", "--"])
            self.assertEqual(
                Path(root_command[root_command.index("--storage") + 1]),
                snapshot_databases[0][0].parent,
            )
            self.assertEqual(root_command[root_command.index("--namespace") + 1], "download-ns")
            self.assertNotEqual(
                Path(root_command[root_command.index("--storage") + 1]),
                config.tdl_download_storage / "data",
            )
            self.assertNotEqual(
                Path(export_command[export_command.index("--storage") + 1]),
                config.tdl_export_storage / "data",
            )
            self.assertEqual(root_cwd, config.tdl_download_home)
            self.assertEqual(root_home, str(config.tdl_download_home))
            self.assertEqual(root_timeout, 60)
            self.assertEqual(export_command[:4], ["runuser", "-u", "user1", "--"])
            self.assertEqual(
                Path(export_command[export_command.index("--storage") + 1]),
                snapshot_databases[1][0].parent,
            )
            self.assertEqual(export_command[export_command.index("--namespace") + 1], "export-ns")
            self.assertEqual(export_cwd, config.tdl_export_home)
            self.assertEqual(export_home, str(config.tdl_export_home))
            self.assertEqual(export_timeout, 60)
            self.assertTrue(
                all(
                    Path(command[command.index("--identity-file") + 1]).parent != profile_root
                    for command, _cwd, _home, _timeout in commands
                )
            )
            self.assertTrue(
                all(
                    not Path(command[command.index("--identity-file") + 1]).exists()
                    and not Path(command[command.index("--identity-file") + 1]).parent.exists()
                    for command, _cwd, _home, _timeout in commands
                )
            )
            self.assertTrue((profile_root / "identity.json").is_file())
            self.assertEqual(
                [data for _path, data in snapshot_databases],
                [b"bolt database", b"bolt database"],
            )
            self.assertTrue(all(not path.exists() for path, _data in snapshot_databases))
            self.assertEqual(
                (profile_root / "root/.tdl/data/download-ns").read_bytes(),
                b"bolt database",
            )
            self.assertNotIn("424242", json.dumps(result))
            self.assertNotIn(str(profile_root), json.dumps(result))

    def test_tdl_diagnosis_reports_mismatch_without_exposing_ids(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = make_config(root)
            self.prepare_profile(config)
            manager = ProfileSessionManager(config)

            def fake_run(command, **_kwargs):
                identity_file = Path(command[command.index("--identity-file") + 1])
                user_id = 424242 if "download-ns" in command else 987654
                identity_file.write_text(
                    json.dumps({"telegram_user_id": user_id}), encoding="utf-8"
                )
                return subprocess.CompletedProcess(command, 0)

            with patch("tme3bot.worker.profile_sessions.subprocess.run", side_effect=fake_run):
                result = manager.diagnose_tdl_sessions("default")

            self.assertFalse(result["ready"])
            self.assertFalse(result["identity_match"])
            self.assertIn("PROFILE_SESSION_IDENTITY_MISMATCH", result["reason_codes"])
            self.assertNotIn("424242", json.dumps(result))
            self.assertNotIn("987654", json.dumps(result))

    def test_missing_bolt_database_is_not_opened_or_created(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = make_config(root)
            profile_root = self.prepare_profile(config)
            bolt_file = profile_root / "root/.tdl/data/download-ns"
            bolt_file.unlink()
            manager = ProfileSessionManager(config)
            with patch("tme3bot.worker.profile_sessions.subprocess.run") as run:
                result = manager.diagnose_tdl_sessions("default")
            self.assertEqual(run.call_count, 1)
            command = run.call_args.args[0]
            self.assertEqual(command[:4], ["runuser", "-u", "user1", "--"])
            self.assertFalse(bolt_file.exists())
            self.assertFalse(result["ready"])
            self.assertIn("PROFILE_ROOT_SESSION_DATABASE_MISSING", result["reason_codes"])

    def test_busy_profile_lock_prevents_opening_any_session(self):
        class BusyLock:
            def acquire(self, *, blocking):
                return False

            def release(self):
                raise AssertionError("busy lock must not be released by this call")

        export_lock = BusyLock()
        download_lock = BusyLock()

        class Manager:
            def profile_operation_locks(self, _profile):
                return export_lock, download_lock

            def session_config(self, _profile):
                raise AssertionError("busy diagnostic must not resolve/open runtime")

        class Sessions:
            def diagnose_tdl_sessions(self, *_args):
                raise AssertionError("busy session must not open Bolt")

        executor = object.__new__(WorkerJobExecutor)
        executor.profile_manager = Manager()
        executor._profile_sessions = Sessions()
        result = executor.diagnose_profile_tdl("default")
        self.assertFalse(result["ready"])
        self.assertEqual(result["reason_codes"], ["PROFILE_SESSION_BUSY"])


if __name__ == "__main__":
    unittest.main()
