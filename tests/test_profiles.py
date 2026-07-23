import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from tme3bot.config import AppConfig
from tme3bot.profiles import (
    DOWNLOAD_MODE_ISOLATED,
    build_profile_config,
    normalize_profile_name,
    set_profile_download_mode,
)


class ProfileTests(unittest.TestCase):
    def make_config(self, root: Path) -> AppConfig:
        return AppConfig(
            bot_token="token",
            profile_root=str(root),
            profiles_root=root / "profiles",
            default_profile="default",
            tme3_host="t.me3",
            download_root=root / "download",
            export_pending_dir=root / "exports" / "pending",
            export_processing_dir=root / "exports" / "processing",
            export_done_dir=root / "exports" / "done",
            export_failed_dir=root / "exports" / "failed",
            state_file=root / "state.json",
            legacy_max_json=root / "max.json",
            tdl_export_user="user1",
            tdl_download_user="root",
            tdl_export_home=root / "user1",
            tdl_download_home=root / "root",
            tdl_export_storage=root / "user1" / ".tdl",
            tdl_download_storage=root / "root" / ".tdl",
            tdl_export_namespace="default",
            tdl_download_namespace="default",
            tdl_export_stall_timeout_seconds=300,
            tdl_download_stall_timeout_seconds=1800,
            temp_root=root / "tmp",
            log_level="INFO",
        )

    def test_default_profile_keeps_legacy_single_profile_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)

            profile_config = build_profile_config(config, "default")

            self.assertEqual(profile_config.download_root, root / "download")
            self.assertEqual(profile_config.state_file, root / "state.json")
            self.assertEqual(profile_config.tdl_export_storage, root / "user1" / ".tdl")

    def test_named_profile_uses_shared_default_download_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)

            profile_config = build_profile_config(config, "Bot 01")

            self.assertEqual(
                profile_config.profile_root, str(root / "profiles" / "bot-01")
            )
            self.assertEqual(profile_config.download_root, root / "download")
            self.assertEqual(
                profile_config.state_file, root / "profiles" / "bot-01" / "state.json"
            )
            self.assertEqual(
                profile_config.tdl_download_storage,
                root / "profiles" / "bot-01" / "root" / ".tdl",
            )
            self.assertEqual(
                profile_config.tdl_export_storage,
                root / "profiles" / "bot-01" / "user1" / ".tdl",
            )

    def test_named_profile_can_use_isolated_download_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            set_profile_download_mode(config, "Bot 01", DOWNLOAD_MODE_ISOLATED)

            profile_config = build_profile_config(config, "Bot 01")

            self.assertEqual(
                profile_config.download_root, root / "profiles" / "bot-01" / "download"
            )

    def test_normalize_profile_name(self) -> None:
        self.assertEqual(normalize_profile_name(" Bot 01!! "), "bot-01")

    def test_app_config_uses_container_profile_root_not_compose_host_path(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "BOT_TOKEN": "token",
                "PROFILE_ROOT": "/host/bot01",
            },
            clear=False,
        ):
            with patch.dict("os.environ", {"PROFILE_DATA_ROOT": ""}, clear=False):
                config = AppConfig.from_env()

        self.assertEqual(config.profile_root, "/data")


if __name__ == "__main__":
    unittest.main()
