import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tme3bot.backup_service import BackupService
from tme3bot.config import AppConfig
from tme3bot.storage_catalog import StorageCatalog


def make_config(root: Path) -> AppConfig:
    return AppConfig(
        bot_token="bot-secret", profile_root=str(root), profiles_root=root / "profiles",
        default_profile="default", tme3_host="t.me3", download_root=root / "download",
        export_pending_dir=root / "exports/pending", export_processing_dir=root / "exports/processing",
        export_done_dir=root / "exports/done", export_failed_dir=root / "exports/failed",
        state_file=root / "state.json", legacy_max_json=root / "max.json", tdl_export_user="user1",
        tdl_download_user="root", tdl_export_home=root / "user1", tdl_download_home=root / "root",
        tdl_export_storage=root / "user1/.tdl", tdl_download_storage=root / "root/.tdl",
        tdl_export_namespace="default", tdl_download_namespace="default",
        tdl_export_stall_timeout_seconds=300, tdl_download_stall_timeout_seconds=1800,
        temp_root=root / "tmp", log_level="INFO", utility_settings_file=root / "utility_settings.json",
        storage_db_file=root / "storage.db", backup_volume_size="45m",
    )


class BackupServiceTests(unittest.TestCase):
    def test_runtime_staging_includes_json_and_excludes_workspace_media(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            config.export_pending_dir.mkdir(parents=True)
            config.export_pending_dir.joinpath("one.json").write_text("{}", encoding="utf-8")
            config.download_root.mkdir(parents=True)
            config.download_root.joinpath("large.bin").write_bytes(b"media")
            config.state_file.write_text("{}", encoding="utf-8")
            (root / "utility_settings.json").write_text(json.dumps({"compress_password": "secret"}), encoding="utf-8")
            catalog = StorageCatalog(root / "storage.db")
            service = BackupService(config, catalog)
            staging = root / "staging"
            with patch.dict("os.environ", {"BOT_TOKEN": "bot-secret"}, clear=False):
                service._build_gateway_staging(staging)
                service._write_runtime_env(staging)
                service._write_manifest(staging, "run", "gateway", "now")
            self.assertTrue((staging / "data/storage.db").exists())
            self.assertTrue((staging / "data/exports/pending/one.json").exists())
            self.assertFalse((staging / "data/download/large.bin").exists())
            self.assertIn("BOT_TOKEN=bot-secret", (staging / "runtime.env").read_text(encoding="utf-8"))

    def test_archive_command_encrypts_headers_and_does_not_log_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            staging = root / "staging"
            staging.mkdir()
            staging.joinpath("data.txt").write_text("x", encoding="utf-8")
            output = root / "backup.7z"
            process = type(
                "Process",
                (),
                {"stdout": io.StringIO(" 50%\r 100%\r"), "wait": lambda self: 0},
            )()
            service = BackupService(make_config(root))
            with patch("tme3bot.backup_service.subprocess.Popen", return_value=process) as popen:
                service._make_7z(staging, output, "secret", "45m")
            command = popen.call_args.args[0]
            self.assertIn("-mhe=on", command)
            self.assertIn("-psecret", command)
            self.assertEqual(popen.call_args.kwargs["stderr"], __import__("subprocess").STDOUT)


if __name__ == "__main__":
    unittest.main()
