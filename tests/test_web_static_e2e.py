from __future__ import annotations

import json
import os
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
WEB_BUILD = ROOT / "web" / "build"
RUN_E2E = os.environ.get("TME3_RUN_WEB_STATIC_E2E") == "1"


class QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def copyfile(self, source, outputfile) -> None:
        try:
            super().copyfile(source, outputfile)
        except BrokenPipeError:
            pass


def api_payload(path: str, authenticated: bool) -> dict[str, object]:
    if path == "/auth/browser/session":
        if not authenticated:
            return {"authenticated": False, "profiles": []}
        return {
            "authenticated": True,
            "actor": {"telegram_user_id": 42, "profile": "default", "worker_route": "local"},
            "profiles": ["default"],
        }
    if path == "/workers":
        return {"items": [{"name": "local", "url": "http://127.0.0.1:8080", "enabled": True, "selected": True}]}
    if path == "/profiles/local":
        return {
            "profiles": [{"name": "default", "workers": ["local"]}],
            "runtime_readiness": {"checked_at": "", "workers": [], "cells": []},
        }
    if path == "/dashboard/summary":
        return {"jobs": {"active": 0, "failed": 0}, "profile": "default", "worker": "local"}
    if path == "/jobs/metrics":
        return {"workers": [{"worker": "local", "status": "idle", "enabled": True, "active_jobs": 0}]}
    if path == "/utility/tree":
        return {"path": "/workspace", "items": [], "folders": [], "files": []}
    if path == "/storage/settings":
        return {"title": "Storage test", "channel_id": ""}
    if path == "/runtime/secrets":
        return {"telegram_bot_token_configured": False, "telegram_tts_chat_configured": False}
    if path == "/backups/status":
        return {
            "enabled": False,
            "schedule": "03:00",
            "timezone": "Asia/Jakarta",
            "retention": 7,
            "volume_size": "45m",
            "channel": "",
            "storage_trash_retention_days": 30,
            "job_stall_timeout_seconds": 600,
            "job_cancel_grace_seconds": 30,
        }
    if path == "/aria2-rpc-local":
        return {"result": {}}
    if path == "/workers/local/aria2/health":
        return {
            "ready": False,
            "worker": "local",
            "reason_code": "ARIA2_NOT_READY",
            "engine": {"ready": False, "version": None},
            "hook": {"ready": False, "script_present": False, "configured": False, "run_count": 0, "last_result": "never"},
        }
    return {
        "items": [],
        "workers": [],
        "cells": [],
        "profiles": [],
        "errors": [],
        "summaries": [],
        "total": 0,
        "next_offset": None,
        "enabled": False,
        "supported": False,
        "ready": False,
        "path": "/workspace",
        "folders": [],
        "files": [],
    }


@unittest.skipUnless(RUN_E2E, "Set TME3_RUN_WEB_STATIC_E2E=1 to run local static Web browser tests")
class StaticWebPlaywrightE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not WEB_BUILD.is_dir():
            raise AssertionError("Build web/ first with pnpm build")
        from playwright.sync_api import sync_playwright

        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(QuietStaticHandler, directory=str(WEB_BUILD)),
        )
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)

    def make_page(self, *, authenticated: bool = True, reduced_motion: str = "no-preference"):
        context = self.browser.new_context(
            viewport={"width": 1365, "height": 900},
            reduced_motion=reduced_motion,
        )
        context.add_cookies([{
            "name": "tme3_csrf",
            "value": "local-e2e-csrf",
            "url": self.origin,
            "sameSite": "Lax",
        }])

        def mock_api(route) -> None:
            parsed = urlsplit(route.request.url)
            path = parsed.path.removeprefix("/api/v1")
            if path == "/auth/browser/challenge" and route.request.method == "POST":
                self.challenge_csrf = route.request.headers.get("x-csrf-token", "")
                payload: dict[str, object] = {
                    "verification_uri": "https://t.me/example_bot?start=local-e2e",
                    "expires_at": "2099-01-01T00:00:00Z",
                    "interval": 60,
                }
            elif path == "/auth/browser/challenge":
                payload = {"authenticated": False, "profiles": []}
            elif path == "/auth/browser/refresh":
                payload = {"authenticated": False, "profiles": []}
            else:
                payload = api_payload(path, authenticated)
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

        context.route("**/api/v1/**", mock_api)
        return context, context.new_page()

    def test_all_static_deep_links_render_their_shell_and_route_context(self) -> None:
        routes = [
            ("/", "Ringkasan"),
            ("/activity/", "Aktivitas"),
            ("/storage/", "Storage"),
            ("/downloads/", "Download"),
            ("/aria2/", "AriaNg"),
            ("/chat-send/", "Kirim ke Chat"),
            ("/exports/", "Export"),
            ("/quick-mode/", "Quick Mode"),
            ("/tts/", "TTS"),
            ("/decrypt/", "Dekripsi"),
            ("/utility/", "Utility"),
            ("/backups/", "Backup"),
            ("/profiles/", "Profil / Vault"),
            ("/profiles/vault/", "Vault profil"),
            ("/workers/", "Workers"),
            ("/settings/", "Pengaturan"),
            ("/development/", "Pengembangan"),
        ]
        context, page = self.make_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(f"{page.url}: {error}"))
        try:
            for path, title in routes:
                response = page.goto(f"{self.origin}{path}", wait_until="domcontentloaded")
                self.assertIsNotNone(response, path)
                self.assertEqual(response.status, 200, path)
                breadcrumb = page.locator(".breadcrumb strong")
                breadcrumb.wait_for(state="visible", timeout=10000)
                self.assertEqual(breadcrumb.inner_text(), title, path)
                if path == "/":
                    duration = page.locator(".route-transition").evaluate(
                        "element => getComputedStyle(element).animationDuration"
                    )
                    self.assertEqual(duration, "0.22s")
            self.assertEqual(errors, [], "Browser runtime errors: " + " | ".join(errors))
        finally:
            context.close()

    def test_theme_persists_and_mobile_drawer_navigates(self) -> None:
        context, page = self.make_page(reduced_motion="reduce")
        try:
            page.goto(f"{self.origin}/", wait_until="domcontentloaded")
            self.assertEqual(page.locator("html").get_attribute("data-theme"), "dark")
            page.get_by_role("button", name="Pilih tema").click()
            page.get_by_role("menuitem", name="Terang").click()
            self.assertEqual(page.locator("html").get_attribute("data-theme"), "light")
            page.reload(wait_until="domcontentloaded")
            self.assertEqual(page.locator("html").get_attribute("data-theme"), "light")
            self.assertTrue(page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches"))
            duration = page.locator(".route-transition").evaluate(
                "element => getComputedStyle(element).animationDuration"
            )
            self.assertLessEqual(float(duration.removesuffix("s")), 0.0001)

            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="Buka navigasi").click()
            drawer = page.get_by_role("dialog", name="Navigasi mobile")
            drawer.wait_for(state="visible")
            drawer.get_by_role("link", name="Storage").click()
            page.wait_for_url("**/storage/", timeout=10000)
            drawer.wait_for(state="hidden")
        finally:
            context.close()

    def test_login_challenge_sends_csrf_header_without_production(self) -> None:
        self.challenge_csrf = ""
        context, page = self.make_page(authenticated=False)
        try:
            page.goto(f"{self.origin}/storage/", wait_until="domcontentloaded")
            page.get_by_role("heading", name="Masuk dengan Telegram").wait_for(state="visible")
            page.get_by_role("button", name="Mulai login").click()
            page.get_by_role("link", name="Buka bot Telegram").wait_for(state="visible")
            self.assertEqual(self.challenge_csrf, "local-e2e-csrf")
        finally:
            context.close()

