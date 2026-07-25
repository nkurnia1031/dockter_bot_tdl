import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch
from pathlib import Path

from tme3bot.config import AppConfig
from tme3bot.profiles import (
    DOWNLOAD_MODE_ISOLATED,
    build_profile_config,
    normalize_profile_name,
    set_profile_download_mode,
    ProfileManager,
    build_profile_runtime,
)
from tme3bot.profile_registry import ProfileRegistry
from tme3bot.state import HttpStateStore, StateStore


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

    def test_worker_route_is_persisted_per_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = replace(
                self.make_config(root),
                worker_local_url="http://local:8080",
                worker_remote_url="http://remote:8080",
            )
            manager = ProfileManager(config)
            self.assertEqual(manager.worker_route("default"), "local")
            self.assertEqual(manager.set_worker_route("default", "remote"), "remote")
            reloaded = ProfileManager(config)
            self.assertEqual(reloaded.worker_route("default"), "remote")

    def test_backend_profile_registry_is_authoritative_after_worker_profile_disappears(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            (root / "profiles" / "remote-only").mkdir(parents=True)
            (root / "profiles" / "remote-only" / "identity.json").write_text(
                '{"telegram_user_id": 123}', encoding="utf-8"
            )
            manager = ProfileManager(config)
            manager.profile_registry.bootstrap_from_identities(
                {item["name"]: item.get("telegram_user_id") for item in manager.local_profile_identities()}
            )

            self.assertEqual(manager.profile_for_user(123), "remote-only")
            self.assertIn("remote-only", manager.list_profiles())
            self.assertTrue((root / "profiles.json").exists())

    def test_worker_runtime_always_uses_backend_state_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = replace(
                self.make_config(root),
                app_role="worker",
                backend_api_url="http://backend:8080",
                backend_internal_token="internal",
            )
            with patch.object(HttpStateStore, "load"):
                runtime = build_profile_runtime("default", config)
            self.assertIsInstance(runtime.state_store, HttpStateStore)

    def test_backend_runtime_never_uses_its_own_backend_api_url_for_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = replace(self.make_config(root), backend_api_url="http://backend:8080")
            runtime = build_profile_runtime("default", config)
            self.assertIsInstance(runtime.state_store, StateStore)

    def test_profile_registry_rejects_one_telegram_identity_on_two_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = ProfileRegistry(Path(temp_dir) / "profiles.json", "default")
            registry.register("one", 99)
            with self.assertRaises(ValueError):
                registry.register("two", 99)

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

    def test_app_config_accepts_custom_gateway_and_worker_ports(self) -> None:
        with patch.dict(
            "os.environ",
            {"BOT_TOKEN": "token", "GATEWAY_PORT": "9443", "WORKER_PORT": "9123"},
            clear=False,
        ):
            config = AppConfig.from_env()

        self.assertEqual(config.gateway_port, 9443)
        self.assertEqual(config.worker_port, 9123)

    def test_app_config_parses_multiple_named_worker_endpoints(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "APP_ROLE": "backend",
                "BOT_TOKEN": "token",
                "WORKER_ENDPOINTS": "local=http://worker-local:8080,remote-1=https://one.example,remote-2=https://two.example",
                "WORKER_API_TOKENS": "remote-1=one-token,remote-2=two-token",
                "WORKER_ROUTES": "irang=remote-2",
            },
            clear=False,
        ):
            config = AppConfig.from_env()

        self.assertEqual(config.worker_endpoints["remote-2"], "https://two.example")
        self.assertEqual(config.worker_api_tokens["remote-1"], "one-token")
        self.assertEqual(config.worker_routes["irang"], "remote-2")

    def test_runtime_role_validation_fails_fast_for_missing_trust_tokens(self):
        config = replace(
            self.make_config(Path("/tmp/tme3bot-test")),
            app_role="worker",
            backend_api_url="",
            backend_internal_token="",
            worker_api_token="",
        )
        with self.assertRaises(ValueError) as raised:
            config.validate_runtime()
        self.assertIn("BACKEND_API_URL", str(raised.exception))
        self.assertIn("WORKER_API_TOKEN", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
