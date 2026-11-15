from __future__ import annotations

import unittest
from unittest.mock import patch

from tme3bot.worker import tts_helper


class _FakeProxy:
    def __init__(self, ready: bool):
        self.is_ready = ready

    def ready(self) -> bool:
        return self.is_ready


class TtsHelperProxyReadinessTests(unittest.TestCase):
    def test_aria2_proxy_readiness_requires_both_internal_proxy_and_tor(self):
        client = tts_helper.app.test_client()
        with patch.object(tts_helper, "_ARIA2_TOR_PROXY", _FakeProxy(True)), patch.object(
            tts_helper, "_tor_ready", return_value=True
        ):
            ready = client.get("/aria2-proxy-readyz")
        self.assertEqual(ready.status_code, 200)

        with patch.object(tts_helper, "_ARIA2_TOR_PROXY", _FakeProxy(False)), patch.object(
            tts_helper, "_tor_ready", return_value=True
        ):
            proxy_missing = client.get("/aria2-proxy-readyz")
        self.assertEqual(proxy_missing.status_code, 503)

        with patch.object(tts_helper, "_ARIA2_TOR_PROXY", _FakeProxy(True)), patch.object(
            tts_helper, "_tor_ready", return_value=False
        ):
            tor_missing = client.get("/aria2-proxy-readyz")
        self.assertEqual(tor_missing.status_code, 503)
        self.assertNotIn("token", ready.text.lower())


if __name__ == "__main__":
    unittest.main()
