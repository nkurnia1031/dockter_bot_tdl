from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tme3bot.infrastructure.settings_store import (
    SettingsConflict,
    SettingsScopeError,
    SqliteSettingsStore,
)
from tme3bot.utility import UtilitySettingsStore


class DesiredSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = root / "data.sqlite"
        self.key = root / "private" / "settings.key"
        self.store = SqliteSettingsStore(self.database, self.key)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_secrets_are_encrypted_and_audit_contains_only_key_names(self) -> None:
        secret = "987654:very-private-bot-token"
        self.store.seed_once(
            "telegram-import-v1", {"bot_token": secret}, source="legacy-env"
        )
        snap = self.store.snapshot("telegram")
        self.assertNotIn(secret, str(snap))
        self.assertTrue(snap["secret_status"]["bot_token"])
        self.assertEqual(self.store.get_values("telegram", include_secrets=True)["bot_token"], secret)

        with sqlite3.connect(self.database) as db:
            values = db.execute(
                "SELECT secret_ciphertext, value_json FROM runtime_setting_values WHERE setting_key='bot_token'"
            ).fetchone()
            audit = db.execute(
                "SELECT changed_keys_json, source FROM runtime_settings_audit WHERE scope='telegram'"
            ).fetchone()
        self.assertIsNotNone(values[0])
        self.assertIsNone(values[1])
        self.assertNotIn(secret.encode(), self.database.read_bytes())
        self.assertNotIn(secret, str(audit))
        self.assertIn("bot_token", audit[0])
        if os.name == "posix":
            self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.key.parent.stat().st_mode & 0o777, 0o700)

    def test_expected_version_is_compare_and_swap(self) -> None:
        snapshot = self.store.update(
            "worker", {"tts_part_retries": 4}, expected_version=0, worker="remote-1"
        )
        self.assertEqual(snapshot["desired_version"], 1)
        self.assertEqual(snapshot["applied_version"], 0)
        self.assertEqual(snapshot["status"], "pending")
        with self.assertRaises(SettingsConflict) as caught:
            self.store.update(
                "worker", {"tts_part_retries": 5}, expected_version=0, worker="remote-1"
            )
        self.assertEqual(caught.exception.current_version, 1)

    def test_explicit_clear_survives_restart_and_does_not_reseed_legacy_env(self) -> None:
        old_token = "123456:legacy-bot-token-value"
        self.store.seed_once(
            "telegram-env-v1", {"bot_token": old_token}, source="legacy-env"
        )
        current = self.store.snapshot("telegram")
        cleared = self.store.update(
            "telegram",
            {},
            expected_version=current["desired_version"],
            clear=["bot_token"],
        )
        self.assertFalse(cleared["secret_status"]["bot_token"])

        restarted = SqliteSettingsStore(self.database, self.key)
        self.assertFalse(restarted.seed_once(
            "telegram-env-v1", {"bot_token": old_token}, source="legacy-env"
        ))
        self.assertEqual(restarted.get_values("telegram", include_secrets=True)["bot_token"], "")
        self.assertFalse(restarted.snapshot("telegram")["secret_status"]["bot_token"])

    def test_missing_encryption_key_fails_closed_when_ciphertext_exists(self) -> None:
        self.store.seed_once(
            "telegram-key-test-v1",
            {"bot_token": "123456:secret-token-for-key-test"},
            source="fixture",
        )
        self.key.unlink()
        with self.assertRaisesRegex(RuntimeError, "Kunci runtime settings hilang"):
            SqliteSettingsStore(self.database, self.key)

    def test_scope_and_value_validation_reject_misrouted_or_unsafe_settings(self) -> None:
        with self.assertRaises(SettingsScopeError):
            self.store.update(
                "backend", {"tts_helper_urls": ["http://a", "http://b", "http://c"]},
                expected_version=0,
            )
        with self.assertRaises(ValueError):
            self.store.update(
                "worker", {"tts_helper_urls": ["file:///etc/passwd"]},
                expected_version=0, worker="local",
            )
        with self.assertRaises(ValueError):
            self.store.update(
                "worker", {"tts_tor_control_ports": [9050, 0, 9052]},
                expected_version=0, worker="local",
            )

    def test_ack_must_match_registered_worker_scope_and_desired_version(self) -> None:
        with self.assertRaises(SettingsScopeError):
            self.store.acknowledge("backend", "local", 0)
        with self.assertRaises(SettingsConflict):
            self.store.acknowledge("worker", "local", 1)
        self.store.update("worker", {"tts_part_retries": 2}, expected_version=0, worker="local")
        result = self.store.acknowledge("worker", "local", 1)
        self.assertEqual(result["applied_version"], 1)
        self.assertEqual(result["status"], "applied")

    def test_legacy_worker_json_is_imported_once_per_worker(self) -> None:
        legacy = {
            "storage_profile": "storage",
            "job_stall_timeout_seconds": 500,
            "tts_part_retries": 4,
            "worker_api_token_configured": True,
        }
        self.assertTrue(self.store.seed_worker_once("remote-1", legacy, source="legacy-worker-json"))
        self.assertFalse(self.store.seed_worker_once("remote-1", legacy, source="legacy-worker-json"))
        settings = self.store.get_values("worker", worker="remote-1")
        self.assertEqual(settings["storage_profile"], "storage")
        self.assertEqual(settings["worker_job_stall_timeout_seconds"], 500)
        self.assertNotIn("worker_api_token_configured", settings)
        self.assertEqual(self.store.snapshot("worker", worker="remote-1")["status"], "applied")

    def test_utility_legacy_adapter_reads_and_writes_sqlite_without_returning_secret_metadata(self) -> None:
        self.store.seed_once(
            "utility-json-v1",
            {
                "move_size": "4g",
                "compress_size": "4g",
                "compress_password": "legacy-password-123",
                "rclone_destination": "googledrive:backup",
            },
            source="legacy-json",
        )
        utility = UtilitySettingsStore(Path(self.temp.name) / "old.json", desired_store=self.store)
        self.assertEqual(utility.get()["compress_password"], "legacy-password-123")
        utility.set("rclone_destination", "googledrive:archive")
        self.assertEqual(utility.get()["rclone_destination"], "googledrive:archive")
        self.assertEqual(self.store.snapshot("backend")["settings"]["rclone_destination"], "googledrive:archive")


if __name__ == "__main__":
    unittest.main()
