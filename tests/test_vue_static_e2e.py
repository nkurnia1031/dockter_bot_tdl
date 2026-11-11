from __future__ import annotations

import os
import socket
import subprocess
import time
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import parse_qs, urlparse

try:
    from playwright.sync_api import BrowserContext, Page, Route, sync_playwright
except ImportError:  # The browser suite installs Playwright explicitly in CI.
    BrowserContext = Page = Route = None  # type: ignore[assignment,misc]
    sync_playwright = None


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
BUILD_ROOT = WEB_ROOT / "build"
RUN_E2E = os.environ.get("TME3_RUN_VUE_STATIC_E2E") == "1"

ROUTES = [
    ("/", "Ringkasan operasional"),
    ("/activity/", "Aktivitas"),
    ("/storage/", "Cloud Storage"),
    ("/downloads/", "Download manager"),
    ("/aria2/", "AriaNg"),
    ("/chat-send/", "Kirim ke Chat"),
    ("/exports/", "Source & pembuatan export"),
    ("/quick-mode/", "Pantau dan ulangi Quick Mode"),
    ("/tts/", "TTS Novel"),
    ("/decrypt/", "Dekripsi teks"),
    ("/utility/", "Utility Workspace"),
    ("/backups/", "Backup terenkripsi"),
    ("/profiles/", "Profil lokal"),
    ("/profiles/vault/", "Vault profil"),
    ("/workers/", "Worker & routing"),
    ("/settings/", "Pengaturan"),
    ("/development/", "Pengembangan"),
]


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _api_fixture(path: str) -> dict[str, object]:
    empty: dict[str, object] = {
        "items": [],
        "profiles": [],
        "workers": [],
        "total": 0,
        "offset": 0,
        "next_offset": None,
        "supported": False,
        "errors": [],
        "summaries": [],
        "runtime_readiness": {"workers": [], "cells": []},
        "telegram_bot_token_configured": False,
        "telegram_tts_chat_configured": False,
    }
    if path == "/auth/browser/session":
        return {
            "authenticated": True,
            "actor": {"telegram_user_id": 4242, "profile": "default", "worker_route": "local"},
            "profiles": ["default"],
        }
    if path == "/workers":
        return {"items": [{"name": "local", "url": "http://worker.invalid", "enabled": True, "selected": True}]}
    if path == "/profiles/local":
        return {
            "profiles": [{"name": "default", "workers": ["local"], "exclusive_worker": "local"}],
            "runtime_readiness": {"workers": [], "cells": []},
            "items": [],
        }
    if path == "/jobs/metrics":
        return {"workers": []}
    if path == "/dashboard/summary":
        return {"jobs": {"active": 0, "failed": 0}, "workers": {"total": 1}}
    if path == "/backups/status":
        return {"items": [], "settings": {}, "active": False, "latest": None}
    if path == "/runtime/secrets":
        return {"telegram_bot_token_configured": False, "telegram_tts_chat_configured": False}
    if path == "/tts/workers":
        return {"items": [{"name": "local", "enabled": True}]}
    if path == "/storage/settings":
        return {"title": "Test Storage", "channel_id": 0}
    if path == "/storage/browser":
        return {
            "current_folder": None,
            "breadcrumbs": [],
            "folders": [],
            "items": [{
                "id": 1,
                "display_name": "test-archive.zip",
                "original_name": "test-archive.zip",
                "file_size": 128,
                "mime_type": "application/zip",
                "owner_profile": "default",
                "uploaded_at": "2026-11-11T00:00:00Z",
                "folder": "My Drive",
                "status": "active",
            }],
            "total_folders": 0,
            "total_items": 1,
        }
    if path == "/storage/folders/tree":
        return {"items": []}
    return empty


@unittest.skipUnless(RUN_E2E and sync_playwright is not None, "Set TME3_RUN_VUE_STATIC_E2E=1 and install Playwright Chromium")
class VueStaticBundleE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (BUILD_ROOT / "index.html").is_file():
            raise RuntimeError("Build web/build terlebih dahulu sebelum menjalankan static E2E.")
        for required in ("index.html", "200.html", "build-info.json", "robots.txt"):
            if not (BUILD_ROOT / required).is_file():
                raise RuntimeError(f"Bundle static tidak memiliki {required}.")

        cls.port = _free_port()
        cls.origin = f"http://127.0.0.1:{cls.port}"
        cls.preview = subprocess.Popen(
            ["pnpm", "exec", "vite", "preview", "--host", "127.0.0.1", "--port", str(cls.port), "--strictPort"],
            cwd=WEB_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if cls.preview.poll() is not None:
                raise RuntimeError("Vite preview berhenti sebelum siap.")
            try:
                with urlopen(cls.origin, timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                time.sleep(0.1)
        else:
            cls.preview.terminate()
            raise RuntimeError("Vite preview tidak siap dalam 15 detik.")

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls) -> None:
        browser = getattr(cls, "browser", None)
        if browser:
            browser.close()
        playwright = getattr(cls, "playwright", None)
        if playwright:
            playwright.stop()
        preview = getattr(cls, "preview", None)
        if preview and preview.poll() is None:
            preview.terminate()
            try:
                preview.wait(timeout=5)
            except subprocess.TimeoutExpired:
                preview.kill()
                preview.wait(timeout=5)

    def _context(self, authenticated: bool = True) -> tuple[BrowserContext, list[str], list[str]]:
        context = self.browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_cookies([{"name": "tme3_csrf", "value": "local-e2e-csrf", "url": self.origin}])
        external_requests: list[str] = []
        csrf_headers: list[str] = []

        def fake_api(route: Route) -> None:
            request_url = route.request.url
            parsed = urlparse(request_url)
            if parsed.netloc != urlparse(self.origin).netloc or parsed.scheme != "http":
                external_requests.append(request_url)
                route.abort()
                return
            if not parsed.path.startswith("/api/v1/"):
                route.continue_()
                return

            api_path = parsed.path.removeprefix("/api/v1")
            method = route.request.method.upper()
            if api_path == "/jobs":
                kind = parse_qs(parsed.query).get("kind", [""])[0]
                items = [{
                    "id": "local-history-job-1",
                    "kind": "storage_upload",
                    "status": "succeeded",
                    "worker": "local",
                    "created_at": "2026-11-11T00:00:00Z",
                    "updated_at": "2026-11-11T00:00:01Z",
                    "progress": {},
                    "result": {"message": "Completed"},
                }] if kind == "storage_upload" else []
                route.fulfill(json={"items": items})
                return
            if api_path == "/auth/browser/session" and not authenticated:
                route.fulfill(status=401, json={"error": {"message": "local signed-out fixture"}})
                return
            if api_path == "/auth/browser/refresh" and not authenticated:
                route.fulfill(status=401, json={"error": {"message": "local signed-out fixture"}})
                return
            if api_path == "/auth/browser/challenge" and method == "POST":
                csrf_headers.append(route.request.headers.get("x-csrf-token", ""))
                route.fulfill(json={
                    "verification_uri": "https://t.me/local_test_bot",
                    "expires_at": "2099-01-01T00:00:00Z",
                    "interval": 60,
                })
                return
            route.fulfill(json=_api_fixture(api_path))

        context.route("**/*", fake_api)
        return context, external_requests, csrf_headers

    def test_all_deep_links_navigation_theme_motion_and_local_api(self) -> None:
        context, external_requests, _ = self._context()
        page = context.new_page()
        runtime_errors: list[str] = []
        page.on("pageerror", lambda error: runtime_errors.append(str(error)))
        try:
            for path, expected_heading in ROUTES:
                requested_path = path if path == "/" else path.rstrip("/")
                page.goto(self.origin + requested_path, wait_until="domcontentloaded")
                heading = page.locator(".page-content main h1").first
                heading.wait_for(state="visible", timeout=10000)
                self.assertIn(expected_heading.casefold(), (heading.inner_text() or "").casefold())
                self.assertEqual(urlparse(page.url).path, path)

            page.goto(self.origin + "/", wait_until="domcontentloaded")
            page.locator(".page-content main h1").wait_for(state="visible")
            page.evaluate("""() => {
              window.__tmeRouteDurations = [];
              const root = document.querySelector('.page-content');
              window.__tmeRouteObserver = new MutationObserver(() => {
                for (const node of root.querySelectorAll('.route-enter-active')) {
                  window.__tmeRouteDurations.push(getComputedStyle(node).transitionDuration);
                }
              });
              window.__tmeRouteObserver.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] });
            }""")
            page.locator('aside[aria-label="Navigasi utama"] a[href="/activity/"]').click()
            page.locator(".page-content main h1").filter(has_text="Aktivitas").wait_for(state="visible")
            page.wait_for_function("window.__tmeRouteDurations.length > 0")
            duration = page.evaluate("parseFloat(window.__tmeRouteDurations.at(-1))")
            self.assertGreater(duration, 0.1, "Route transition should remain visible with normal motion enabled")

            page.get_by_label("Tema").select_option("light")
            self.assertEqual(page.locator("html").get_attribute("data-theme"), "light")
            self.assertEqual(page.evaluate("localStorage.getItem('tme3-theme')"), "light")

            page.emulate_media(reduced_motion="reduce")
            page.evaluate("window.__tmeRouteDurations = []")
            page.locator('aside[aria-label="Navigasi utama"] a[href="/storage/"]').click()
            page.locator(".page-content main h1").filter(has_text="Cloud Storage").wait_for(state="visible")
            page.wait_for_function("window.__tmeRouteDurations.length > 0")
            reduced_duration = page.evaluate("parseFloat(window.__tmeRouteDurations.at(-1))")
            self.assertLessEqual(reduced_duration, 0.001, "Reduced-motion preference should shorten route transitions")

            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="Buka navigasi").click()
            mobile_nav = page.get_by_role("dialog", name="Navigasi mobile")
            mobile_nav.get_by_role("link", name="Download").click()
            page.locator(".page-content main h1").filter(has_text="Download manager").wait_for(state="visible")
            mobile_nav.wait_for(state="hidden")

            self.assertEqual(external_requests, [], "The static E2E must never request any non-local origin")
            self.assertEqual(runtime_errors, [], "Vue routes must not produce uncaught browser errors")
        finally:
            context.close()

    def test_static_bundle_has_direct_entrypoints_for_every_known_route(self) -> None:
        index_html = (BUILD_ROOT / "index.html").read_bytes()
        for path, _ in ROUTES:
            if path == "/":
                continue
            with self.subTest(path=path):
                route_entry = BUILD_ROOT / path.strip("/") / "index.html"
                self.assertTrue(route_entry.is_file(), f"Static route entrypoint missing: {route_entry}")
                self.assertEqual(route_entry.read_bytes(), index_html)

    def test_storage_history_table_styles_and_detail_modal_geometry(self) -> None:
        context, external_requests, _ = self._context()
        page = context.new_page()
        try:
            page.goto(self.origin + "/storage/", wait_until="domcontentloaded")
            page.get_by_role("heading", name="Cloud Storage").wait_for(state="visible")
            page.wait_for_timeout(400)

            table = page.locator(".activity-table").first
            table.wait_for(state="visible")
            styles = page.evaluate("""() => {
              const table = document.querySelector('.activity-table');
              const header = table?.querySelector('th');
              const wrapper = table?.closest('.activity-table-wrap');
              return {
                overflowX: wrapper && getComputedStyle(wrapper).overflowX,
                wrapperBorder: wrapper && getComputedStyle(wrapper).borderTopWidth,
                headerPadding: header && getComputedStyle(header).paddingTop,
                headerBorder: header && getComputedStyle(header).borderBottomWidth,
                headerTransform: header && getComputedStyle(header).textTransform,
              };
            }""")
            self.assertEqual(styles["overflowX"], "auto")
            self.assertGreater(float(str(styles["wrapperBorder"]).removesuffix("px")), 0)
            self.assertGreater(float(str(styles["headerPadding"]).removesuffix("px")), 0)
            self.assertGreater(float(str(styles["headerBorder"]).removesuffix("px")), 0)
            self.assertEqual(styles["headerTransform"], "uppercase")

            page.get_by_role("button", name="Detail test-archive.zip").click()
            dialog = page.get_by_role("dialog", name="Detail file")
            dialog.wait_for(state="visible")
            geometry = page.evaluate("""() => {
              const backdrop = document.querySelector('.modal-backdrop');
              const rect = backdrop.getBoundingClientRect();
              return {
                position: getComputedStyle(backdrop).position,
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height,
                viewportWidth: innerWidth,
                viewportHeight: innerHeight,
              };
            }""")
            self.assertEqual(geometry["position"], "fixed")
            self.assertAlmostEqual(geometry["x"], 0, delta=1)
            self.assertAlmostEqual(geometry["y"], 0, delta=1)
            self.assertAlmostEqual(geometry["width"], geometry["viewportWidth"], delta=1)
            self.assertAlmostEqual(geometry["height"], geometry["viewportHeight"], delta=1)
            self.assertEqual(external_requests, [])
        finally:
            context.close()

    def test_login_challenge_sends_csrf_from_local_cookie(self) -> None:
        context, external_requests, csrf_headers = self._context(authenticated=False)
        page = context.new_page()
        runtime_errors: list[str] = []
        page.on("pageerror", lambda error: runtime_errors.append(str(error)))
        try:
            page.goto(self.origin + "/settings/", wait_until="domcontentloaded")
            page.get_by_role("heading", name="Masuk dengan Telegram").wait_for(state="visible")
            page.get_by_role("button", name="Mulai login").click()
            page.get_by_role("link", name="Buka bot Telegram").wait_for(state="visible")
            self.assertEqual(csrf_headers, ["local-e2e-csrf"])
            self.assertEqual(external_requests, [], "The login test does not follow the Telegram URL")
            self.assertEqual(runtime_errors, [])
        finally:
            context.close()
