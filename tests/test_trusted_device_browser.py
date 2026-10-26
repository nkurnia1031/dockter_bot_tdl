import unittest

from tools.trusted_device_browser import open_trusted_context
from tools.trusted_device_store import TrustedDeviceError


class TrustedDeviceBrowserPolicyTests(unittest.TestCase):
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
