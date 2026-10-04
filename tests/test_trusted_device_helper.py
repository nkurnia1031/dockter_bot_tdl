from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from tools.trusted_device import browser_state, canonical_payload
from tools.trusted_device_store import TrustedDeviceError, TrustedDeviceStore, WindowsDpapi


class FakeProtector:
    def protect(self, data: bytes, entropy: bytes) -> bytes:
        return b"encrypted:" + bytes(value ^ entropy[index % len(entropy)] for index, value in enumerate(data))

    def unprotect(self, data: bytes, entropy: bytes) -> bytes:
        if not data.startswith(b"encrypted:"):
            raise TrustedDeviceError("bad encrypted data")
        value = data[len(b"encrypted:"):]
        return bytes(byte ^ entropy[index % len(entropy)] for index, byte in enumerate(value))


class TrustedDeviceHelperTests(unittest.TestCase):
    def make_store(self, temp, origin="https://ui.example.test", events=None):
        events = events if events is not None else []

        def acl(path):
            events.append(("acl", Path(path)))

        protector = FakeProtector()
        original = protector.protect

        def protect(data, entropy):
            events.append(("protect", None))
            return original(data, entropy)

        protector.protect = protect
        return TrustedDeviceStore(origin, base_dir=Path(temp) / "trusted", protector=protector, acl_applier=acl), events

    def test_private_key_is_encrypted_and_acl_is_applied_before_files(self):
        with tempfile.TemporaryDirectory() as temp:
            store, events = self.make_store(temp)
            private = bytes(range(32))
            public = bytes(range(32, 64))
            enrollment = store.save_credentials(device_id="fd9f67f1-bba8-4011-9ed3-0f819ac8df10", name="Builder", public_key=public, private_key=private)
            self.assertEqual(events[0][0], "acl")
            self.assertEqual(events[1][0], "protect")
            raw_document = store.credentials_path.read_bytes()
            self.assertNotIn(base64.urlsafe_b64encode(private).rstrip(b"="), raw_document)
            self.assertNotIn("private_key_dpapi", enrollment)
            self.assertEqual(store.credentials()[1], private)

    def test_dpapi_failure_has_no_plaintext_fallback(self):
        class BrokenProtector:
            def protect(self, *_):
                raise TrustedDeviceError("DPAPI unavailable")

        with tempfile.TemporaryDirectory() as temp:
            store = TrustedDeviceStore("https://ui.example.test", base_dir=Path(temp), protector=BrokenProtector(), acl_applier=lambda _: None)
            with self.assertRaises(TrustedDeviceError):
                store.save_credentials(device_id="fd9f67f1-bba8-4011-9ed3-0f819ac8df10", name="Laptop", public_key=bytes(32), private_key=bytes(32))
            self.assertFalse(store.credentials_path.exists())

    @unittest.skipUnless(os.name == "nt", "Windows CurrentUser DPAPI only")
    def test_windows_current_user_dpapi_round_trip(self):
        protector = WindowsDpapi()
        secret = bytes(range(32))
        entropy = b"trusted-device-test-origin"
        encrypted = protector.protect(secret, entropy)
        self.assertNotEqual(encrypted, secret)
        self.assertEqual(protector.unprotect(encrypted, entropy), secret)
        with self.assertRaises(TrustedDeviceError):
            protector.unprotect(encrypted, b"another-origin")

    @unittest.skipUnless(os.name == "nt", "Windows ACL and CurrentUser DPAPI only")
    def test_windows_store_protects_persisted_key_with_acl(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        with tempfile.TemporaryDirectory() as temp:
            private = Ed25519PrivateKey.generate()
            private_bytes = private.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
            public_bytes = private.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            store = TrustedDeviceStore(
                "https://ui.example.test",
                base_dir=Path(temp) / "trusted-device",
                protector=WindowsDpapi(),
            )
            store.save_credentials(
                device_id="fd9f67f1-bba8-4011-9ed3-0f819ac8df10",
                name="Windows test laptop",
                public_key=public_bytes,
                private_key=private_bytes,
            )
            self.assertEqual(store.credentials()[1], private_bytes)
            store.new_browser_state_path()
            self.assertEqual(store.credentials()[1], private_bytes)

    def test_origin_scopes_storage_and_wrong_origin_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            first, _ = self.make_store(temp, "https://one.example.test")
            second, _ = self.make_store(temp, "https://two.example.test")
            self.assertNotEqual(first.root, second.root)
            first.save_credentials(device_id="fd9f67f1-bba8-4011-9ed3-0f819ac8df10", name="Laptop", public_key=bytes(32), private_key=bytes(range(32)))
            with self.assertRaises(TrustedDeviceError):
                second.credentials()

    def test_stale_cleanup_only_removes_old_state_files_under_private_root(self):
        with tempfile.TemporaryDirectory() as temp:
            store, _ = self.make_store(temp)
            fresh = store.new_browser_state_path()
            stale = store.new_browser_state_path()
            fresh.write_text("fresh", encoding="utf-8")
            stale.write_text("stale", encoding="utf-8")
            fresh.touch()
            stale.touch()
            import os
            os.utime(fresh, (950, 950))
            os.utime(stale, (600, 600))
            store.clean_stale_states(now=1000)
            self.assertTrue(fresh.exists())
            self.assertFalse(stale.exists())

    def test_signature_payload_pins_origin_protocol_device_and_expiry(self):
        challenge = {
            "protocol_version": "tme3-device-auth-v1",
            "origin": "https://ui.example.test",
            "device_id": "fd9f67f1-bba8-4011-9ed3-0f819ac8df10",
            "challenge_id": "3fc16ed4-f991-4faa-b80a-5c21c40d9a6e",
            "nonce": base64.urlsafe_b64encode(bytes(32)).decode().rstrip("="),
            "expires_unix": int(time.time()) + 60,
        }
        payload = canonical_payload(challenge, challenge["origin"], challenge["device_id"])
        self.assertEqual(payload.decode().splitlines()[1], "browser-session")
        with self.assertRaises(TrustedDeviceError):
            canonical_payload({**challenge, "origin": "https://attacker.example"}, "https://ui.example.test", challenge["device_id"])

    def test_browser_state_keeps_secure_cookie_attributes_and_never_returns_token(self):
        state = browser_state("https://ui.example.test", [
            "tme3_access=access-value; Max-Age=900; Path=/; HttpOnly; Secure; SameSite=lax",
            "tme3_refresh=refresh-value; Max-Age=86400; Path=/; HttpOnly; Secure; SameSite=lax",
            "tme3_csrf=csrf-value; Max-Age=86400; Path=/; Secure; SameSite=lax",
        ])
        self.assertEqual({cookie["name"] for cookie in state["cookies"]}, {"tme3_access", "tme3_refresh", "tme3_csrf"})
        self.assertTrue(all(cookie["secure"] for cookie in state["cookies"]))
        self.assertTrue(next(cookie for cookie in state["cookies"] if cookie["name"] == "tme3_access")["httpOnly"])
        self.assertEqual(state["origins"], [])
        with self.assertRaises(TrustedDeviceError):
            browser_state("https://ui.example.test", ["tme3_access=unsafe; Path=/; HttpOnly; SameSite=lax"])
        with self.assertRaises(TrustedDeviceError):
            browser_state("https://ui.example.test", ["tme3_access=unsafe; Domain=evil.example; Path=/; HttpOnly; Secure"])
        with self.assertRaises(TrustedDeviceError):
            browser_state("https://ui.example.test", ["tme3_csrf=hidden; Max-Age=900; Path=/; HttpOnly; Secure"])


if __name__ == "__main__":
    unittest.main()
