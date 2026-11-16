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
WEB_BUILD = Path(os.environ.get("TME3_WEB_BUILD_DIR", ROOT / "web" / "build"))
RUN_E2E = os.environ.get("TME3_RUN_ARIA2_LINKS_UI_E2E") == "1"


class QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def copyfile(self, source, outputfile) -> None:
        try:
            super().copyfile(source, outputfile)
        except BrokenPipeError:
            pass


@unittest.skipUnless(RUN_E2E, "Set TME3_RUN_ARIA2_LINKS_UI_E2E=1 to run local mocked browser E2E")
class Aria2LinksBrowserE2ETests(unittest.TestCase):
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

    def test_bunkr_tab_previews_album_selects_files_and_queues_them(self) -> None:
        from playwright.sync_api import expect

        context = self.browser.new_context(viewport={"width": 1365, "height": 900})
        context.add_cookies([{
            "name": "tme3_csrf",
            "value": "local-e2e-csrf",
            "url": self.origin,
            "sameSite": "Lax",
        }])
        calls: list[dict[str, object]] = []
        task = {
            "gid": "1111111111111111",
            "kind": "bunkr",
            "file_name": "one.zip",
            "status": "waiting",
            "completed_bytes": 0,
            "total_bytes": 100,
            "speed_bytes_per_second": 0,
            "error_code": "",
            "reason_code": "",
            "refresh_attempts": 0,
            "retry_after_seconds": 0,
            "route": "tor",
            "route_change_allowed": True,
        }

        def mock_api(route) -> None:
            request = route.request
            parsed = urlsplit(request.url)
            path = parsed.path.removeprefix("/api/v1")
            body = request.post_data_json if request.post_data else None
            headers = request.headers
            calls.append({
                "path": path,
                "method": request.method,
                "body": body,
                "csrf": headers.get("x-csrf-token", ""),
            })

            if path == "/auth/browser/session":
                payload = {
                    "authenticated": True,
                    "actor": {"telegram_user_id": 42, "profile": "default", "worker_route": "local"},
                    "profiles": ["default"],
                }
            elif path == "/workers":
                payload = {"items": [{"name": "local", "enabled": True, "selected": True}]}
            elif path == "/profiles/local":
                payload = {"profiles": [{"name": "default", "workers": ["local"]}], "runtime_readiness": {"checked_at": "", "workers": [], "cells": []}}
            elif path == "/workers/local/aria2/health":
                payload = {
                    "worker": "local",
                    "ready": True,
                    "reason_code": "",
                    "engine": {"ready": True, "version": "1.37.0"},
                    "hook": {"ready": True, "script_present": True, "configured": True},
                    "recovery": {"speed_threshold_bytes_per_second": 100000},
                }
            elif path == "/workers/local/aria2/recovery-settings":
                payload = {"speed_threshold_bytes_per_second": 100000}
            elif path == "/aria2-rpc-local":
                payload = {"result": {
                    "max-overall-download-limit": "0",
                    "max-overall-upload-limit": "0",
                    "max-concurrent-downloads": "3",
                    "max-connection-per-server": "5",
                    "split": "5",
                    "retry-wait": "0",
                    "timeout": "60",
                    "connect-timeout": "10",
                    "disk-cache": "64M",
                }}
            elif path == "/workers/local/aria2/links/tasks":
                payload = {"items": [task] if calls and any(call["path"].endswith("/enqueue") for call in calls) else []}
            elif path == "/workers/local/aria2/links/preview":
                payload = {"items": [
                    {"source_index": 0, "kind": "direct", "title": "direct.bin", "error": "", "files": [
                        {"item_id": "", "file_name": "direct.bin", "thumbnail_url": ""},
                    ]},
                    {"source_index": 1, "kind": "album", "title": "Album Demo", "error": "", "files": [
                        {"item_id": "album-one", "file_name": "one.zip", "thumbnail_url": "https://images.test/one.jpg"},
                        {"item_id": "album-two", "file_name": "two.zip", "thumbnail_url": ""},
                    ]},
                ]}
            elif path == "/workers/local/aria2/links/enqueue":
                payload = {"items": [
                    {"source_index": 0, "file_name": "direct.bin", "status": "queued", "route": "tor"},
                    {"source_index": 1, "file_name": "one.zip", "status": "queued", "route": "tor"},
                ]}
            elif path.startswith("/aria2-ui/"):
                route.fulfill(status=200, content_type="text/html", body="<!doctype html><title>AriaNg fake</title>")
                return
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({}))
                return

            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

        context.route("**/api/v1/**", mock_api)
        context.route("https://images.test/**", lambda route: route.fulfill(status=200, content_type="image/gif", body=b"GIF89a"))
        page = context.new_page()
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error.stack or error)))
        try:
            response = page.goto(f"{self.origin}/aria2/", wait_until="domcontentloaded")
            self.assertIsNotNone(response)
            self.assertEqual(response.status, 200)
            page.get_by_role("tab", name="Bunkr").click()
            try:
                expect(page.get_by_text("Belum ada task pada worker ini.")).to_be_visible(timeout=10000)
            except AssertionError:
                self.fail(
                    "Idle task list did not settle. "
                    f"API calls: {calls[-20:]}; alerts: {page.locator('[role=alert]').all_inner_texts()}; "
                    f"browser errors: {page_errors}"
                )
            self.assertEqual(
                sum(call["path"].endswith("/aria2/links/tasks") for call in calls),
                1,
                "An idle Bunkr panel must fetch its task list once and must not start polling.",
            )
            textarea = page.get_by_label("Link Bunkr atau URL langsung")
            textarea.fill("https://cdn.example.test/direct.bin\nhttps://bunkr.cr/a/album-demo")
            page.get_by_role("button", name="Periksa link").click()

            try:
                expect(page.get_by_role("heading", name="Pilih file untuk antrean")).to_be_visible(timeout=10000)
            except AssertionError:
                self.fail(
                    "Bunkr preview did not appear. "
                    f"API calls: {calls[-20:]}; alerts: {page.locator('[role=alert]').all_inner_texts()}; "
                    f"browser errors: {page_errors}"
                )
            expect(page.locator("#bunkr-panel img")).to_have_count(1)
            page.get_by_role("button", name="Pilih semua").click()
            page.get_by_label("Pilih two.zip").uncheck()
            page.locator("#bunkr-panel").get_by_label("Rute unduh", exact=True).select_option("tor")
            page.get_by_role("button", name="Masukkan pilihan ke Aria2").click()
            expect(page.get_by_role("status").filter(has_text="2 task masuk antrean")).to_be_visible()
            expect(page.get_by_text("one.zip", exact=True)).to_be_visible()

            preview_call = next(call for call in calls if call["path"].endswith("/preview"))
            enqueue_call = next(call for call in calls if call["path"].endswith("/enqueue"))
            self.assertEqual(preview_call["body"], {"sources": [
                "https://cdn.example.test/direct.bin", "https://bunkr.cr/a/album-demo"
            ]})
            self.assertEqual(enqueue_call["body"], {
                "sources": ["https://cdn.example.test/direct.bin", "https://bunkr.cr/a/album-demo"],
                "selections": {"0": [""], "1": ["album-one"]},
                "directory": "/workspace/aria2",
                "route": "tor",
            })
            self.assertTrue(all(call["csrf"] == "local-e2e-csrf" for call in calls if call["method"] == "POST"))
            self.assertNotIn("signed-secret", page.locator("body").inner_text())
            self.assertEqual(page_errors, [], "Browser runtime errors: " + " | ".join(page_errors))
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
