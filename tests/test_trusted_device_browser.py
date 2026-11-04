import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.trusted_device_browser import _read_storage_state, open_trusted_context
from tools.trusted_device_store import TrustedDeviceError


class TrustedDeviceBrowserPolicyTests(unittest.TestCase):
    def _write_state(self, states: Path, *, access_expiry: int, refresh_expiry: int):
        now = 2_000_000_000
        cookies = [
            {
                "name": "tme3_access", "value": "test-access", "domain": "ui.utama.naufix.space",
                "path": "/", "secure": True, "httpOnly": True, "expires": access_expiry,
            },
            {
                "name": "tme3_refresh", "value": "test-refresh", "domain": "ui.utama.naufix.space",
                "path": "/", "secure": True, "httpOnly": True, "expires": refresh_expiry,
            },
            {
                "name": "tme3_csrf", "value": "test-csrf", "domain": "ui.utama.naufix.space",
                "path": "/", "secure": True, "httpOnly": False, "expires": refresh_expiry,
            },
        ]
        path = states / "browser-test.json"
        path.write_text(json.dumps({"cookies": cookies, "origins": []}), encoding="utf-8")
        path.chmod(0o600)
        return path, now

    def test_expired_access_cookie_can_refresh_from_live_trusted_session(self):
        with tempfile.TemporaryDirectory() as directory:
            states = Path(directory)
            expired_access = 1_999_999_000
            path, now = self._write_state(
                states, access_expiry=expired_access, refresh_expiry=2_000_000_000 + 86400
            )
            store = SimpleNamespace(states=states, origin="https://ui.utama.naufix.space")
            with patch("tools.trusted_device_browser.time.time", return_value=now):
                state = _read_storage_state(store, path)
            self.assertEqual(state["cookies"][0]["expires"], expired_access)

    def test_expired_refresh_cookie_rejects_browser_state(self):
        with tempfile.TemporaryDirectory() as directory:
            states = Path(directory)
            path, now = self._write_state(states, access_expiry=2_000_000_000 + 300, refresh_expiry=1_999_999_000)
            store = SimpleNamespace(states=states, origin="https://ui.utama.naufix.space")
            with patch("tools.trusted_device_browser.time.time", return_value=now), self.assertRaises(
                TrustedDeviceError
            ):
                _read_storage_state(store, path)

    def test_tls_error_override_rejects_non_loopback_origin(self):
        with self.assertRaises(TrustedDeviceError):
            with open_trusted_context(
                origin="https://ui.utama.naufix.space",
                storage_state="/tmp/unused-browser-state.json",
                allow_localhost_tls_errors=True,
            ):
                self.fail("Non-loopback origin must not bypass TLS validation")


if __name__ == "__main__":
    unittest.main()
