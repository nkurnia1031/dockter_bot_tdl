import unittest
from unittest.mock import MagicMock, patch

from tme3bot.worker.resolver_client import resolve_with_addon
from tme3bot.worker.safelink_resolver import (
    SafelinkResolveError,
    SafelinkRuntimeUnavailable,
)


class ResolverClientTests(unittest.TestCase):
    def response_context(self, status_code):
        response = MagicMock()
        response.status_code = status_code
        stream = MagicMock()
        stream.__enter__.return_value = response
        client = MagicMock()
        client.__enter__.return_value = client
        client.stream.return_value = stream
        return client

    def test_addon_unavailable_is_a_runtime_failure(self):
        client = self.response_context(503)
        with patch("tme3bot.worker.resolver_client.httpx.Client", return_value=client):
            with self.assertRaises(SafelinkRuntimeUnavailable) as raised:
                resolve_with_addon(
                    "https://pndk.to/example",
                    on_progress=lambda _item: None,
                    is_cancelled=lambda: False,
                )
        self.assertEqual(raised.exception.code, "RESOLVER_RUNTIME_UNAVAILABLE")

    def test_request_rejection_is_not_misclassified_as_runtime_failure(self):
        client = self.response_context(422)
        with patch("tme3bot.worker.resolver_client.httpx.Client", return_value=client):
            with self.assertRaises(SafelinkResolveError) as raised:
                resolve_with_addon(
                    "https://pndk.to/example",
                    on_progress=lambda _item: None,
                    is_cancelled=lambda: False,
                )
        self.assertNotIsInstance(raised.exception, SafelinkRuntimeUnavailable)


if __name__ == "__main__":
    unittest.main()
