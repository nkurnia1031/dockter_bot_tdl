from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from tme3bot.worker import resolver_addon
from tme3bot.worker.resolver_client import resolve_with_addon
from tme3bot.worker.safelink_resolver import SafelinkCancelled


class ResolverAddonTests(unittest.TestCase):
    def test_addon_streams_progress_and_result_without_auth_setup(self):
        def fake_resolve(url, *, on_progress, is_cancelled):
            self.assertEqual(url, "https://pndk.to/example")
            on_progress({"phase": "resolving", "message": "Membaca langkah 1/5."})
            return {"destination_url": "https://example.org/file"}

        with (
            patch.object(resolver_addon, "_browser_ready", return_value=True),
            patch.object(resolver_addon, "resolve_shortlink", side_effect=fake_resolve),
            TestClient(resolver_addon.app) as client,
        ):
            response = client.post("/resolve", json={"url": "https://pndk.to/example"})

        self.assertEqual(response.status_code, 200)
        lines = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(lines[0]["type"], "progress")
        self.assertEqual(lines[0]["phase"], "resolving")
        self.assertEqual(lines[1]["type"], "result")
        self.assertEqual(lines[1]["destination_url"], "https://example.org/file")
        self.assertEqual(lines[-1]["type"], "done")

    def test_worker_client_forwards_progress_and_reads_destination(self):
        body = (
            b'{"type":"heartbeat"}\n'
            b'{"type":"progress","phase":"resolving","message":"Menunggu langkah."}\n'
            b'{"type":"result","destination_url":"https://example.org/file"}\n'
        )
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, content=body, request=request)
        )
        progress = []
        with patch(
            "tme3bot.worker.resolver_client.httpx.Client",
            return_value=httpx.Client(transport=transport, trust_env=False),
        ):
            result = resolve_with_addon(
                "https://pndk.to/example",
                on_progress=progress.append,
                is_cancelled=lambda: False,
            )

        self.assertEqual(result, {"destination_url": "https://example.org/file"})
        self.assertEqual(progress, [{"type": "progress", "phase": "resolving", "message": "Menunggu langkah."}])

    def test_worker_client_aborts_stream_when_job_is_cancelled(self):
        def handler(request):
            return httpx.Response(
                200,
                content=b'{"type":"heartbeat"}\n',
                request=request,
            )

        transport = httpx.MockTransport(handler)
        with patch(
            "tme3bot.worker.resolver_client.httpx.Client",
            return_value=httpx.Client(transport=transport, trust_env=False),
        ):
            with self.assertRaisesRegex(SafelinkCancelled, "dibatalkan"):
                resolve_with_addon(
                    "https://pndk.to/example",
                    on_progress=lambda _item: None,
                    is_cancelled=lambda: True,
                )


if __name__ == "__main__":
    unittest.main()
