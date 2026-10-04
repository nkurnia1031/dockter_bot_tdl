from __future__ import annotations

import base64
import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tme3bot.domain.models import Actor, DomainError
from tme3bot.infrastructure.auth import BotAuthService, SqliteAuthRepository
from tme3bot.infrastructure.device_auth import DeviceAuthService, challenge_payload


class DeviceAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "auth.sqlite"
        self.repo = SqliteAuthRepository(self.path)
        self.authorized = True

        def actor(user_id: int) -> Actor:
            if user_id != 42 or not self.authorized:
                raise DomainError("UNAUTHORIZED_ACTOR", "denied", status_code=403)
            return Actor(user_id, "default")

        self.auth = BotAuthService(self.repo, actor, "s" * 48, "test_bot", refresh_days=30)
        self.devices = DeviceAuthService(self.repo, self.auth, "https://ui.example.test")
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.device_id = "fd9f67f1-bba8-4011-9ed3-0f819ac8df10"
        self.devices.register(
            42,
            device_id=self.device_id,
            name="Builder laptop",
            algorithm="Ed25519",
            public_key=base64.urlsafe_b64encode(self.public).decode().rstrip("="),
            origin="https://ui.example.test/",
        )

    def tearDown(self):
        self.temp.cleanup()

    def _login_device(self, *, remote="127.0.0.1"):
        challenge = self.devices.create_challenge(self.device_id, remote)
        payload = challenge_payload(
            origin=challenge["origin"],
            device_id=challenge["device_id"],
            challenge_id=challenge["challenge_id"],
            nonce=challenge["nonce"],
            expires_unix=challenge["expires_unix"],
        )
        signature = base64.urlsafe_b64encode(self.private.sign(payload)).decode().rstrip("=")
        pair = self.devices.exchange(self.device_id, challenge["challenge_id"], signature, remote)
        return challenge, pair, signature

    def test_device_session_coexists_with_telegram_and_another_device_session(self):
        _, first_device, _ = self._login_device()
        first_claims = self.auth.decode_access(first_device.access_token)
        self.assertEqual(first_claims["session_kind"], "device")

        telegram = self.auth._new_web_session(42)
        device_refresh = self.auth.refresh(first_device.refresh_token)
        self.assertEqual(self.auth.decode_access(device_refresh.access_token)["device_id"], self.device_id)
        self.assertEqual(self.auth.decode_access(telegram.access_token)["session_kind"], "telegram")

        second_id = "3fc16ed4-f991-4faa-b80a-5c21c40d9a6e"
        second_key = Ed25519PrivateKey.generate()
        second_public = second_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.devices.register(42, device_id=second_id, name="Agent", algorithm="Ed25519", public_key=base64.urlsafe_b64encode(second_public).decode().rstrip("="), origin="https://ui.example.test")
        _, second_device, _ = self._login_device_for(second_id, second_key, "127.0.0.2")
        self.assertEqual(self.auth.decode_access(first_device.access_token)["telegram_user_id"], 42)
        self.assertEqual(self.auth.decode_access(second_device.access_token)["telegram_user_id"], 42)

        next_telegram = self.auth._new_web_session(42)
        with self.assertRaises(DomainError):
            self.auth.refresh(telegram.refresh_token)
        self.assertEqual(self.auth.decode_access(next_telegram.access_token)["telegram_user_id"], 42)
        self.assertEqual(self.auth.decode_access(second_device.access_token)["device_id"], second_id)

    def _login_device_for(self, device_id, private, remote):
        challenge = self.devices.create_challenge(device_id, remote)
        payload = challenge_payload(origin=challenge["origin"], device_id=device_id, challenge_id=challenge["challenge_id"], nonce=challenge["nonce"], expires_unix=challenge["expires_unix"])
        signature = base64.urlsafe_b64encode(private.sign(payload)).decode().rstrip("=")
        pair = self.devices.exchange(device_id, challenge["challenge_id"], signature, remote)
        return challenge, pair, signature

    def test_revoke_invalidates_access_refresh_and_pending_challenge(self):
        challenge, pair, signature = self._login_device()
        pending = self.devices.create_challenge(self.device_id, "127.0.0.2")
        self.devices.revoke(42, self.device_id)
        with self.assertRaises(DomainError):
            self.auth.decode_access(pair.access_token)
        with self.assertRaises(DomainError):
            self.auth.refresh(pair.refresh_token)
        with self.assertRaises(DomainError):
            self.devices.exchange(self.device_id, pending["challenge_id"], signature, "127.0.0.2")

    def test_signature_replay_attempt_limit_origin_and_expiry_are_enforced(self):
        challenge = self.devices.create_challenge(self.device_id, "127.0.0.1")
        bad = base64.urlsafe_b64encode(bytes(64)).decode().rstrip("=")
        for _ in range(5):
            with self.assertRaises(DomainError) as error:
                self.devices.exchange(self.device_id, challenge["challenge_id"], bad, "127.0.0.1")
            self.assertEqual(error.exception.status_code, 401)
        with self.assertRaises(DomainError) as limited:
            self.devices.exchange(self.device_id, challenge["challenge_id"], bad, "127.0.0.1")
        self.assertEqual(limited.exception.status_code, 429)

        challenge, pair, signature = self._login_device(remote="127.0.0.3")
        with self.assertRaises(DomainError) as replay:
            self.devices.exchange(self.device_id, challenge["challenge_id"], signature, "127.0.0.3")
        self.assertEqual(replay.exception.status_code, 401)
        with self.assertRaises(DomainError) as unavailable:
            DeviceAuthService(self.repo, self.auth, "http://ui.example.test").create_challenge(self.device_id, "127.0.0.4")
        self.assertEqual(unavailable.exception.status_code, 503)
        with self.assertRaises(DomainError) as untrusted:
            self.devices.register(42, device_id="fd9f67f1-bba8-4011-9ed3-0f819ac8df11", name="bad", algorithm="Ed25519", public_key=base64.urlsafe_b64encode(self.public).decode().rstrip("="), origin="http://ui.example.test")
        self.assertEqual(untrusted.exception.status_code, 422)

        expired = self.devices.create_challenge(self.device_id, "127.0.0.4")
        with self.repo._immediate() as db:
            db.execute("UPDATE auth_device_challenges SET expires_at = ? WHERE id = ?", ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), expired["challenge_id"]))
        payload = challenge_payload(origin=expired["origin"], device_id=self.device_id, challenge_id=expired["challenge_id"], nonce=expired["nonce"], expires_unix=expired["expires_unix"])
        expired_signature = base64.urlsafe_b64encode(self.private.sign(payload)).decode().rstrip("=")
        with self.assertRaises(DomainError) as too_late:
            self.devices.exchange(self.device_id, expired["challenge_id"], expired_signature, "127.0.0.4")
        self.assertEqual(too_late.exception.status_code, 410)

    def test_exchange_is_consumed_atomically_under_concurrent_replay(self):
        challenge = self.devices.create_challenge(self.device_id, "127.0.0.5")
        payload = challenge_payload(origin=challenge["origin"], device_id=self.device_id, challenge_id=challenge["challenge_id"], nonce=challenge["nonce"], expires_unix=challenge["expires_unix"])
        signature = base64.urlsafe_b64encode(self.private.sign(payload)).decode().rstrip("=")

        def exchange():
            try:
                return self.devices.exchange(self.device_id, challenge["challenge_id"], signature, "127.0.0.5")
            except DomainError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: exchange(), range(2)))
        self.assertEqual(sum(item is not None for item in results), 1)

    def test_device_actor_revocation_is_checked_on_exchange_and_access(self):
        _, pair, _ = self._login_device()
        self.authorized = False
        with self.assertRaises(DomainError):
            self.auth.decode_access(pair.access_token)
        with self.assertRaises(DomainError):
            self.auth.refresh(pair.refresh_token)

    def test_device_limits_are_persisted_in_auth_sqlite(self):
        self.devices.create_challenge(self.device_id, "198.51.100.40")
        self.devices.create_challenge(self.device_id, "198.51.100.41")
        self.devices.create_challenge(self.device_id, "198.51.100.42")
        with self.assertRaises(DomainError) as too_many:
            self.devices.create_challenge(self.device_id, "198.51.100.43")
        self.assertEqual(too_many.exception.status_code, 429)
        restarted = SqliteAuthRepository(self.path)
        with restarted._db() as db:
            hashed_ip = hashlib.sha256(b"198.51.100.40").hexdigest()
            row = db.execute("SELECT request_count FROM auth_device_rate_limits WHERE rate_key = ?", (f"ip:{hashed_ip}",)).fetchone()
        self.assertEqual(row["request_count"], 1)

    def test_device_session_without_live_device_record_is_rejected(self):
        now = datetime.now(timezone.utc).isoformat()
        with self.repo._db() as db:
            db.execute(
                "INSERT INTO auth_sessions(id, telegram_user_id, refresh_token_hash, created_at, expires_at, last_used_at, session_kind, device_id) VALUES(?, ?, ?, ?, ?, ?, 'device', ?)",
                ("orphaned-device-session", 42, "orphaned-hash", now, (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), now, "missing-device"),
            )
        self.assertIsNone(self.repo.active_session_by_id("orphaned-device-session"))

    def test_old_auth_sessions_migrate_to_telegram_kind(self):
        legacy_path = Path(self.temp.name) / "legacy.sqlite"
        import sqlite3
        db = sqlite3.connect(legacy_path)
        db.executescript("CREATE TABLE auth_sessions(id TEXT PRIMARY KEY, telegram_user_id INTEGER NOT NULL, refresh_token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, last_used_at TEXT NOT NULL, revoked_at TEXT); INSERT INTO auth_sessions VALUES('legacy', 42, 'hash', 'a', 'b', 'a', NULL);")
        db.close()
        migrated = SqliteAuthRepository(legacy_path)
        self.assertEqual(migrated.active_session_by_id("legacy")["session_kind"], "telegram")

    def test_registration_is_actor_scoped_and_revoked_key_cannot_be_reused(self):
        rows = self.devices.list_for_actor(42)
        self.assertEqual(rows[0]["algorithm"], "Ed25519")
        self.assertNotIn("public_key", rows[0])
        self.devices.revoke(42, self.device_id)
        with self.assertRaises(DomainError) as conflict:
            self.devices.register(42, device_id=self.device_id, name="Builder laptop", algorithm="Ed25519", public_key=base64.urlsafe_b64encode(self.public).decode().rstrip("="), origin="https://ui.example.test")
        self.assertEqual(conflict.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
