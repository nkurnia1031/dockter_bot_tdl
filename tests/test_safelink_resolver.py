from __future__ import annotations

import base64
import socket
import unittest
from contextlib import AbstractContextManager

from tme3bot.safelink import normalize_shortlink_url
from tme3bot.worker.safelink_resolver import (
    SafelinkCancelled,
    SafelinkResolveError,
    _guard_request,
    assert_public_http_url,
    decode_safelinkearn_url,
    resolve_shortlink,
)


def _public_dns(host: str, port: int, *, type: int):
    del host, port, type
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def advance_ms(self, milliseconds: int):
        self.value += milliseconds / 1000


class FakeLocator:
    def __init__(self, page, selector: str):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def all(self):
        return self.page.buttons if self.selector == "button:visible" else []

    def count(self):
        return 0

    def inner_text(self, timeout=0):
        del timeout
        return self.page.body

    def is_visible(self):
        return False

    def click(self, timeout=0):
        del timeout


class FakeButton:
    def __init__(self, page, *, label: str, handler: str, enabled_after: float = 0):
        self.page = page
        self.label = label
        self.handler = handler
        self.enabled_after = enabled_after

    def inner_text(self, timeout=0):
        del timeout
        return self.label

    def get_attribute(self, name: str):
        return self.handler if name == "x-on:click" else None

    def is_disabled(self):
        return self.page.clock.value < self.enabled_after

    def click(self, timeout=0):
        del timeout
        self.page.clicks += 1
        self.page.current_url = self.page.destination_page


class FakeDownload:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class FakePage:
    def __init__(
        self,
        clock: FakeClock,
        body: str,
        destination_page: str | None,
        *,
        download_on_wait: bool = False,
    ):
        self.clock = clock
        self.body = body
        self.destination_page = destination_page or "https://pndk.to/test"
        self.current_url = ""
        self.gotos: list[str] = []
        self.clicks = 0
        self.buttons = (
            [FakeButton(self, label="Scroll Down", handler="next", enabled_after=1.4)]
            if destination_page
            else []
        )
        self.frames = []
        self.download_handler = None
        self.download_on_wait = download_on_wait
        self.download = FakeDownload()

    @property
    def url(self):
        return self.current_url

    def goto(self, url: str, **kwargs):
        del kwargs
        self.gotos.append(url)
        self.current_url = url

    def wait_for_timeout(self, milliseconds: int):
        self.clock.advance_ms(milliseconds)
        if self.download_on_wait and self.download_handler is not None:
            self.download_on_wait = False
            self.download_handler(self.download)

    def on(self, event: str, callback):
        if event == "download":
            self.download_handler = callback

    def locator(self, selector: str):
        if selector == "body":
            return FakeLocator(self, selector)
        return FakeLocator(self, selector)

    def get_by_role(self, *args, **kwargs):
        del args, kwargs
        return FakeLocator(self, "role")


class FakeOverlayLocator:
    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def is_visible(self):
        return True

    def click(self, timeout=0):
        del timeout
        self.page.current_url = "https://pndk.to/code"


class FakeContext:
    def __init__(self, page: FakePage):
        self.page = page
        self.route_handler = None
        self.downloads_allowed = None

    def route(self, pattern, handler):
        del pattern
        self.route_handler = handler

    def new_page(self):
        return self.page


class FakeBrowser:
    def __init__(self, context: FakeContext):
        self.context = context

    def new_context(self, **kwargs):
        self.context.downloads_allowed = kwargs.get("accept_downloads")
        return self.context

    def close(self):
        pass


class FakePlaywright:
    def __init__(self, browser: FakeBrowser):
        self.chromium = self
        self.browser = browser

    def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return self.browser


class FakePlaywrightFactory(AbstractContextManager):
    def __init__(self, browser: FakeBrowser):
        self.playwright = FakePlaywright(browser)

    def __enter__(self):
        return self.playwright

    def __exit__(self, *exc):
        del exc
        return False


class FakeRoute:
    def __init__(self, url: str):
        self.request = type("Request", (), {"url": url})()
        self.aborted = False
        self.continued = False

    def abort(self):
        self.aborted = True

    def continue_(self):
        self.continued = True


class FakeOverlayPage(FakePage):
    def get_by_role(self, *args, **kwargs):
        del args, kwargs
        return FakeOverlayLocator(self)


class SafelinkResolverTests(unittest.TestCase):
    def test_input_only_accepts_http_supported_hosts_without_credentials(self):
        self.assertEqual(normalize_shortlink_url(" https://pndk.to/a "), "https://pndk.to/a")
        for value in (
            "file:///etc/passwd",
            "https://example.com/a",
            "https://user:pass@pndk.to/a",
            "http://127.0.0.1/a",
            "https://pndk.to:99999/a",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_shortlink_url(value)

    def test_public_address_guard_rejects_private_and_reserved_targets(self):
        for url in (
            "http://127.0.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "file:///etc/passwd",
        ):
            with self.subTest(url=url), self.assertRaises(SafelinkResolveError):
                assert_public_http_url(url)

        def private_dns(host, port, *, type):
            del host, port, type
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.0.2", 0))]

        with self.assertRaises(SafelinkResolveError):
            assert_public_http_url("https://public-looking.test/", resolver=private_dns)

    def test_safelinkearn_target_is_decoded_but_private_target_is_rejected(self):
        target = "https://example.com/file?id=7"
        encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        url = f"https://www.safelinkearn.com/?shortid={encoded}"
        self.assertEqual(decode_safelinkearn_url(url, resolver=_public_dns), target)
        self.assertIsNone(
            decode_safelinkearn_url(
                "https://safelinkearn.com/?url=aHR0cDovLzEwLjAuMC4xLw==",
                resolver=lambda host, port, *, type: [
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0))
                ],
            )
        )

    def test_browser_request_guard_aborts_private_dns_and_allows_public_urls(self):
        denied = FakeRoute("http://internal.test/admin")
        _guard_request(
            denied,
            resolver=lambda host, port, *, type: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.2", 0))
            ],
        )
        allowed = FakeRoute("https://cdn.example.test/app.js")
        _guard_request(allowed, resolver=_public_dns)
        self.assertTrue(denied.aborted)
        self.assertTrue(allowed.continued)

    def test_normal_visible_click_waits_for_timer_and_returns_only_destination(self):
        clock = FakeClock()
        target = "https://example.com/destination.zip"
        encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        final_url = f"https://safelinkearn.com/?shortid={encoded}"
        page = FakePage(clock, "Step 1 / 5", final_url)
        context = FakeContext(page)
        factory = FakePlaywrightFactory(FakeBrowser(context))
        updates: list[dict[str, str]] = []

        result = resolve_shortlink(
            "https://pndk.to/code",
            on_progress=updates.append,
            timeout_seconds=20,
            resolver=_public_dns,
            monotonic=clock.now,
            playwright_factory=lambda: factory,
        )

        self.assertEqual(result, {"destination_url": target})
        self.assertEqual(page.clicks, 1)
        self.assertEqual(context.downloads_allowed, False)
        self.assertIn("Membaca langkah 1/5.", [item["message"] for item in updates])
        self.assertNotIn("pndk.to/code", repr(updates))

    def test_visible_overlay_close_control_is_used_before_resuming_steps(self):
        clock = FakeClock()
        target = "https://example.com/file"
        encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        page = FakeOverlayPage(
            clock,
            "Step 1 / 5",
            f"https://safelinkearn.com/?url={encoded}",
        )
        context = FakeContext(page)
        factory = FakePlaywrightFactory(FakeBrowser(context))
        result = resolve_shortlink(
            "https://pndk.to/code?google_vignette=1",
            timeout_seconds=20,
            resolver=_public_dns,
            monotonic=clock.now,
            playwright_factory=lambda: factory,
        )
        self.assertEqual(result, {"destination_url": target})
        self.assertEqual(len(page.gotos), 1)

    def test_captcha_stops_without_interaction(self):
        clock = FakeClock()
        page = FakePage(clock, "Please complete the CAPTCHA before continuing", None)
        context = FakeContext(page)
        factory = FakePlaywrightFactory(FakeBrowser(context))
        with self.assertRaisesRegex(SafelinkResolveError, "CAPTCHA"):
            resolve_shortlink(
                "https://pndk.to/code",
                timeout_seconds=20,
                resolver=_public_dns,
                monotonic=clock.now,
                playwright_factory=lambda: factory,
            )
        self.assertEqual(page.clicks, 0)

    def test_download_attempt_is_cancelled_and_reported_without_download(self):
        clock = FakeClock()
        page = FakePage(clock, "Step 1 / 5", None, download_on_wait=True)
        context = FakeContext(page)
        factory = FakePlaywrightFactory(FakeBrowser(context))
        with self.assertRaisesRegex(SafelinkResolveError, "mencoba mengunduh"):
            resolve_shortlink(
                "https://pndk.to/code",
                timeout_seconds=20,
                resolver=_public_dns,
                monotonic=clock.now,
                playwright_factory=lambda: factory,
            )
        self.assertTrue(page.download.cancelled)

    def test_timeout_and_retry_limit_are_bounded(self):
        clock = FakeClock()
        page = FakePage(clock, "Loading", None)
        context = FakeContext(page)
        factory = FakePlaywrightFactory(FakeBrowser(context))
        with self.assertRaisesRegex(SafelinkResolveError, "batas pengulangan"):
            resolve_shortlink(
                "https://pndk.to/code",
                timeout_seconds=100,
                max_restarts=1,
                resolver=_public_dns,
                monotonic=clock.now,
                playwright_factory=lambda: factory,
            )
        self.assertEqual(page.gotos, ["https://pndk.to/code", "https://pndk.to/code"])

    def test_cancel_is_checked_during_browser_flow(self):
        clock = FakeClock()
        page = FakePage(clock, "Step 1 / 5", None)
        context = FakeContext(page)
        factory = FakePlaywrightFactory(FakeBrowser(context))
        with self.assertRaises(SafelinkCancelled):
            resolve_shortlink(
                "https://pndk.to/code",
                is_cancelled=lambda: True,
                timeout_seconds=20,
                resolver=_public_dns,
                monotonic=clock.now,
                playwright_factory=lambda: factory,
            )


if __name__ == "__main__":
    unittest.main()
