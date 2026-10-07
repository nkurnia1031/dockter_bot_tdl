from __future__ import annotations

import base64
import html
import json
import socket
import unittest
from urllib.parse import quote

import httpx

from tme3bot.worker.safelink_resolver import (
    SafelinkCancelled,
    SafelinkResolveError,
    assert_public_http_url,
    decode_safelinkearn_url,
    resolve_shortlink,
)


def _public_dns(host: str, port: int, *, type: int):
    del host, port, type
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def _livewire_page(step: int, phase: int, *, captcha: bool = False) -> str:
    initial = {
        "fingerprint": {"id": f"component-{step}-{phase}", "name": "pages.show"},
        "serverMemo": {
            "data": {"phase": phase, "captcha": False, "hasCaptcha": False},
            "checksum": "test-checksum",
        },
    }
    if captcha:
        initial["serverMemo"]["data"].update({"captcha": False, "hasCaptcha": True})
    encoded = html.escape(json.dumps(initial, separators=(",", ":")), quote=True)
    captcha_text = "Complete this CAPTCHA to continue" if captcha else ""
    return (
        f'<div wire:initial-data="{encoded}">Step {step}/5</div>'
        f"<p>{captcha_text}</p><script>window.livewire_token='csrf-test'</script>"
    )


class ResolverHttpTests(unittest.TestCase):
    def test_rejects_private_and_non_http_addresses(self):
        for value in (
            "http://127.0.0.1/admin",
            "http://169.254.169.254/latest/meta-data",
            "file:///etc/passwd",
        ):
            with self.subTest(value=value), self.assertRaises(SafelinkResolveError):
                assert_public_http_url(value, resolver=_public_dns)

        private_dns = lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))
        ]
        with self.assertRaisesRegex(SafelinkResolveError, "jaringan privat"):
            assert_public_http_url("https://public.example", resolver=private_dns)

    def test_decodes_safelinkearn_without_requesting_final_destination(self):
        target = "https://www.mediafire.com/file/test-file"
        encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        self.assertEqual(
            decode_safelinkearn_url(
                f"https://safelinkearn.com/?shortid={quote(encoded)}",
                resolver=_public_dns,
            ),
            target,
        )

        private = base64.urlsafe_b64encode(b"http://127.0.0.1/").decode().rstrip("=")
        self.assertIsNone(
            decode_safelinkearn_url(
                f"https://safelinkearn.com/?shortid={quote(private)}",
                resolver=_public_dns,
            )
        )

    def test_posts_livewire_events_over_http_and_never_fetches_destination(self):
        target = "https://www.mediafire.com/file/test-file"
        encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        pages = [(1, 0), (2, 1), (3, 2), (4, 3), (5, 4), (5, 5)]
        page_index = 0
        events: list[str] = []
        requests: list[httpx.Request] = []
        gate_base = "https://invest.datapendidikan.com"
        safelink_url = f"https://safelinkearn.com/?shortid={quote(encoded)}"

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal page_index
            requests.append(request)
            host = request.url.host
            if request.method == "GET" and host == "pndk.to":
                return httpx.Response(302, headers={"Location": f"{gate_base}/step/1"}, request=request)
            if request.method == "GET" and host == "invest.datapendidikan.com":
                step, phase = pages[page_index]
                headers = {"Content-Type": "text/html; charset=utf-8"}
                if page_index == 0:
                    headers["Set-Cookie"] = "gate_session=kept; Path=/; HttpOnly"
                return httpx.Response(
                    200,
                    headers=headers,
                    text=_livewire_page(step, phase),
                    request=request,
                )
            if request.method == "POST" and host == "invest.datapendidikan.com":
                self.assertEqual(request.headers.get("x-csrf-token"), "csrf-test")
                self.assertEqual(request.headers.get("cookie"), "gate_session=kept")
                payload = json.loads(request.content)
                event = payload["updates"][0]["payload"]["event"]
                events.append(event)
                if page_index < len(pages) - 1:
                    page_index += 1
                    next_url = f"{gate_base}/step/{page_index + 1}"
                else:
                    next_url = "https://adtival.network/redirect"
                return httpx.Response(
                    200,
                    json={"effects": {"emits": [{"event": "setLink", "params": [next_url]}]}},
                    request=request,
                )
            if request.method == "GET" and host == "adtival.network":
                return httpx.Response(302, headers={"Location": safelink_url}, request=request)
            raise AssertionError(f"Unexpected resolver request: {request.method} {request.url.host}")

        client_factory = lambda: httpx.Client(
            transport=httpx.MockTransport(handler), trust_env=False, follow_redirects=False
        )
        progress: list[dict[str, str]] = []
        result = resolve_shortlink(
            "https://pndk.to/example",
            resolver=_public_dns,
            http_client_factory=client_factory,
            on_progress=progress.append,
            sleep=lambda _seconds: None,
        )

        self.assertEqual(result, {"destination_url": target})
        self.assertEqual(events, ["changePhase"] * 5 + ["getData"])
        self.assertTrue(any(item["phase"] == "completed" for item in progress))
        self.assertFalse(any(request.url.host in {"safelinkearn.com", "www.mediafire.com"} for request in requests))

    def test_stops_when_page_requests_captcha(self):
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(request.method)
            if request.url.host == "pndk.to":
                return httpx.Response(302, headers={"Location": "https://invest.datapendidikan.com/step"}, request=request)
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text=_livewire_page(1, 0, captcha=True),
                request=request,
            )

        with self.assertRaisesRegex(SafelinkResolveError, "CAPTCHA"):
            resolve_shortlink(
                "https://pndk.to/example",
                resolver=_public_dns,
                http_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
                sleep=lambda _seconds: None,
            )
        self.assertEqual(requested, ["GET", "GET"])

    def test_rejects_private_redirect_before_requesting_it(self):
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.host)
            return httpx.Response(
                302,
                headers={"Location": "http://127.0.0.1/private"},
                request=request,
            )

        with self.assertRaisesRegex(SafelinkResolveError, "jaringan privat"):
            resolve_shortlink(
                "https://pndk.to/example",
                resolver=_public_dns,
                http_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
            )
        self.assertEqual(requests, ["pndk.to"])

    def test_retries_transient_get_but_does_not_replay_livewire_post(self):
        shortlink_attempts = 0
        post_attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal shortlink_attempts, post_attempts
            if request.method == "GET" and request.url.host == "pndk.to":
                shortlink_attempts += 1
                if shortlink_attempts == 1:
                    return httpx.Response(503, request=request)
                return httpx.Response(302, headers={"Location": "https://invest.datapendidikan.com/step"}, request=request)
            if request.method == "GET":
                return httpx.Response(
                    200,
                    headers={"Content-Type": "text/html"},
                    text=_livewire_page(1, 0),
                    request=request,
                )
            post_attempts += 1
            raise httpx.ReadTimeout("ambiguous Livewire response", request=request)

        with self.assertRaisesRegex(SafelinkResolveError, "tidak dapat dipastikan"):
            resolve_shortlink(
                "https://pndk.to/example",
                resolver=_public_dns,
                http_client_factory=lambda: httpx.Client(
                    transport=httpx.MockTransport(handler), trust_env=False
                ),
                sleep=lambda _seconds: None,
            )
        self.assertEqual(shortlink_attempts, 2)
        self.assertEqual(post_attempts, 1)

    def test_cancelled_job_does_not_make_a_request(self):
        requests: list[httpx.Request] = []
        transport = httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, request=request)
        )
        with self.assertRaises(SafelinkCancelled):
            resolve_shortlink(
                "https://pndk.to/example",
                resolver=_public_dns,
                http_client_factory=lambda: httpx.Client(transport=transport),
                is_cancelled=lambda: True,
            )
        self.assertEqual(requests, [])


if __name__ == "__main__":
    unittest.main()
