from __future__ import annotations

import json
import os
import threading
import unittest
from email.parser import BytesParser
from email.policy import default as email_policy
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

            if path == "/runtime/mode":
                payload = {"mode": "full"}
            elif path == "/auth/browser/session":
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
            expect(page.get_by_text("PRATINJAU LINK · 3 FILE")).to_be_visible()
            expect(page.locator("#bunkr-panel label:has(input[type=checkbox])")).to_have_count(3)
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

    def test_native_ariang_route_picker_is_per_task_in_the_new_links_tab(self) -> None:
        from playwright.sync_api import expect
        from tme3bot.api.routes.workers import _aria2_rpc_setup_script

        context = self.browser.new_context(viewport={"width": 1365, "height": 900})
        context.add_cookies([{
            "name": "tme3_csrf",
            "value": "local-e2e-csrf",
            "url": self.origin,
            "sameSite": "Lax",
        }])
        rpc_calls: list[dict[str, object]] = []
        reject_tor_route_change = [False]
        setup_script = _aria2_rpc_setup_script("local")

        def multipart_fields(request):
            content_type = request.headers.get("content-type", "")
            raw = request.post_data_buffer or b""
            message = BytesParser(policy=email_policy).parsebytes(
                b"MIME-Version: 1.0\r\nContent-Type: "
                + content_type.encode("ascii")
                + b"\r\n\r\n"
                + raw
            )
            return {
                part.get_param("name", header="content-disposition"):
                    part.get_payload(decode=True) or b""
                for part in message.iter_parts()
            }

        def mock_api(route) -> None:
            request = route.request
            parsed = urlsplit(request.url)
            path = parsed.path.removeprefix("/api/v1")
            if path == "/aria2-cookie-rpc-local":
                fields = multipart_fields(request)
                cookie_request = json.loads(fields["request"].decode("utf-8"))
                rpc_calls.append({
                    "path": path,
                    "body": cookie_request,
                    "csrf": request.headers.get("x-csrf-token", ""),
                    "cookie_bytes": fields["cookies"],
                    "content_type": request.headers.get("content-type", ""),
                })
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "jsonrpc": "2.0", "id": cookie_request.get("id"), "result": "cookie-gid",
                }))
                return
            if path == "/runtime/mode":
                payload = {"mode": "full"}
            elif path == "/auth/browser/session":
                payload = {
                    "authenticated": True,
                    "actor": {"telegram_user_id": 42, "profile": "default", "worker_route": "local"},
                    "profiles": ["default"],
                }
            elif path == "/workers":
                payload = {"items": [{"name": "local", "enabled": True, "selected": True}]}
            elif path == "/workers/local/aria2/health":
                payload = {
                    "worker": "local", "ready": True, "reason_code": "",
                    "engine": {"ready": True, "version": "1.37.0"},
                    "hook": {"ready": True, "script_present": True, "configured": True},
                    "recovery": {"speed_threshold_bytes_per_second": 100000},
                }
            elif path == "/aria2-rpc-local":
                body = request.post_data_json
                rpc_calls.append({
                    "path": path,
                    "body": body,
                    "csrf": request.headers.get("x-csrf-token", ""),
                })
                method = body.get("method")
                if method == "aria2.tellStatus":
                    result = {"gid": body["params"][0], "status": "active"}
                elif method in {"aria2.pause", "aria2.changeOption"}:
                    if method == "aria2.changeOption" and reject_tor_route_change[0]:
                        route.fulfill(status=200, content_type="application/json", body=json.dumps({
                            "jsonrpc": "2.0",
                            "id": body.get("id"),
                            "error": {"code": -32000, "message": "ARIA2_TOR_UNAVAILABLE: Tor worker belum siap."},
                        }))
                        return
                    result = "OK"
                elif method == "aria2.unpause":
                    result = "active"
                else:
                    result = "new-gid"
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "jsonrpc": "2.0", "id": body.get("id"), "result": result,
                }))
                return
            elif path == "/aria2-ui/local/index.html":
                body = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>.tab-pane {{ display: none; }} .tab-pane.active {{ display: block; }}</style><script>{setup_script}</script></head>
<body class="hold-transition skin-aria-ng sidebar-mini fixed">
  <header class="main-header"><nav class="navbar"><div class="navbar-toolbar">
    <ul class="nav navbar-nav"><li><a class="toolbar" href="#!/new">New</a></li></ul>
  </div></nav></header>
  <main><form id="new-task" name="newTaskForm">
    <div class="nav-tabs-custom">
      <ul class="nav nav-tabs" role="tablist">
        <li class="active"><a role="tab" aria-selected="true" data-tab="links" ng-click="changeTab('links')">Links</a></li>
        <li><a role="tab" aria-selected="false" data-tab="options" ng-click="changeTab('options')">Options</a></li>
      </ul>
      <div class="tab-content">
        <div class="tab-pane active" data-panel="links" ng-class="{{'active': context.currentTab === 'links'}}"><label for="task-uri">URI</label>
          <input id="task-uri" value="https://example.test/file.bin"></div>
        <div class="tab-pane" data-panel="options" ng-class="{{'active': context.currentTab === 'options'}}"><div class="settings-table"></div></div>
      </div>
    </div>
    <button type="submit">Add task</button>
  </form></main>
  <script>
    document.querySelectorAll('[data-tab]').forEach((tab) => tab.addEventListener('click', () => {{
      document.querySelectorAll('[data-tab]').forEach((item) => item.setAttribute('aria-selected', String(item === tab)));
      document.querySelectorAll('[data-panel]').forEach((panel) => {{
        panel.classList.toggle('active', panel.dataset.panel === tab.dataset.tab);
      }});
    }}));
    const submitTask = (uri) => {{
      const request = new XMLHttpRequest();
      request.open('POST', '/api/v1/aria2-rpc-local');
      request.setRequestHeader('Content-Type', 'application/json');
      request.send(JSON.stringify({{jsonrpc:'2.0', id:'add-task', method:'aria2.addUri', params:[[uri], {{}}]}}));
    }};
    const unrelated = document.createElement('button');
    unrelated.type = 'button';
    unrelated.id = 'unrelated-task';
    unrelated.textContent = 'Add unrelated task';
    document.body.appendChild(unrelated);
    unrelated.addEventListener('click', () => submitTask('https://unrelated.example.test/other.bin'));
    document.getElementById('new-task').addEventListener('submit', (event) => {{
      event.preventDefault();
      if (window.dropNextTaskSubmission) {{
        window.dropNextTaskSubmission = false;
        return;
      }}
      submitTask(document.getElementById('task-uri').value);
    }});
  </script>
</body></html>"""
                route.fulfill(status=200, content_type="text/html", body=body)
                return
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({}))
                return
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

        context.route("**/api/v1/**", mock_api)
        page = context.new_page()
        try:
            page.goto(f"{self.origin}/aria2/", wait_until="domcontentloaded")
            frame = page.frame_locator('iframe[title="aria2 local"]')
            links_panel = frame.locator("form[name='newTaskForm'] .tab-pane[data-panel='links']")
            expect(links_panel).to_be_visible()
            route_picker = links_panel.get_by_role("combobox", name="Rute unduhan")
            expect(route_picker).to_be_visible(timeout=10000)
            options_tab = frame.get_by_role("tab", name="Options")
            options_tab.click()
            expect(options_tab).to_have_attribute("aria-selected", "true")
            options_panel = frame.locator("form[name='newTaskForm'] .tab-pane[data-panel='options']")
            self.assertEqual(options_panel.get_by_role("combobox", name="Rute unduhan").count(), 0)
            frame.get_by_role("tab", name="Links").click()
            route_picker.select_option("tor")
            with page.expect_response(
                lambda response: response.url.endswith("/aria2-rpc-local")
                and response.request.method == "POST"
            ):
                frame.get_by_role("button", name="Add task").click()
            upload_call = next(call for call in rpc_calls if call["body"].get("method") == "aria2.addUri")
            self.assertEqual(upload_call["csrf"], "local-e2e-csrf")
            self.assertEqual(upload_call["body"], {
                "jsonrpc": "2.0",
                "id": "add-task",
                "method": "aria2.addUri",
                "params":[["https://example.test/file.bin"], {
                    "dir": "/workspace/aria2",
                    "allow-overwrite": "false",
                    "auto-file-renaming": "false",
                }],
                "tme3_route": "tor",
            })
            self.assertEqual(frame.locator(".navbar-toolbar").get_by_label("Rute unduhan").count(), 0)
            self.assertIsNone(frame.locator("body").evaluate("() => localStorage.getItem('tme3-aria2-route:local')"))

            route_picker.select_option("non")
            with page.expect_response(
                lambda response: response.url.endswith("/aria2-rpc-local")
                and response.request.method == "POST"
            ):
                frame.get_by_role("button", name="Add task").click()
            direct_call = [call for call in rpc_calls if call["body"].get("method") == "aria2.addUri"][-1]
            self.assertEqual(direct_call["body"].get("tme3_route"), "non")

            # A cookie form submit whose AriaNg handler never creates an RPC
            # must not leave a cookie waiting for a later task with the same URL.
            cookie_bytes = (
                b"# Netscape HTTP Cookie File\n"
                b".example.test\tTRUE\t/\tTRUE\t2000000000\tsid\tui-cookie-secret\n"
            )
            stale_url = "https://example.test/same-url.bin"
            rpc_count_before_stale = len(rpc_calls)
            frame.locator("#task-uri").fill(stale_url)
            frame.locator("#tme3-cookie-file").set_input_files({
                "name": "cookies.txt", "mimeType": "text/plain", "buffer": cookie_bytes,
            })
            frame.locator("form[name='newTaskForm']").evaluate(
                "form => { form.ownerDocument.defaultView.dropNextTaskSubmission = true; }"
            )
            frame.get_by_role("button", name="Add task").click()
            self.assertEqual(len(rpc_calls), rpc_count_before_stale)
            self.assertEqual(frame.locator("#tme3-cookie-file").input_value(), "")
            with page.expect_response(
                lambda response: response.url.endswith("/aria2-rpc-local")
                and response.request.method == "POST"
                and stale_url in (response.request.post_data or "")
            ):
                frame.get_by_role("button", name="Add task").click()
            stale_followup = rpc_calls[-1]
            self.assertEqual(stale_followup["path"], "/aria2-rpc-local")
            self.assertNotIn("cookie_bytes", stale_followup)

            cookie_url = "https://example.test/cookie-url.bin"
            frame.locator("#task-uri").fill(cookie_url)
            route_picker.select_option("tor")
            frame.locator("#tme3-cookie-file").set_input_files({
                "name": "cookies.txt", "mimeType": "text/plain", "buffer": cookie_bytes,
            })
            with page.expect_response(
                lambda response: response.url.endswith("/aria2-cookie-rpc-local")
                and response.request.method == "POST"
            ):
                frame.get_by_role("button", name="Add task").click()
            cookie_call = rpc_calls[-1]
            self.assertEqual(cookie_call["cookie_bytes"], cookie_bytes)
            self.assertTrue(str(cookie_call["content_type"]).startswith("multipart/form-data; boundary="))
            self.assertEqual(cookie_call["csrf"], "local-e2e-csrf")
            self.assertEqual(cookie_call["body"].get("tme3_route"), "tor")
            self.assertEqual(cookie_call["body"]["method"], "aria2.addUri")
            self.assertEqual(frame.locator("#tme3-cookie-file").input_value(), "")

            second_cookie_bytes = (
                b"# Netscape HTTP Cookie File\n"
                b".example.test\tTRUE\t/\tTRUE\t2000000000\tsid\tsecond-cookie-fixture\n"
            )
            route_picker.select_option("non")
            frame.locator("#tme3-cookie-file").set_input_files({
                "name": "cookies.txt", "mimeType": "text/plain", "buffer": second_cookie_bytes,
            })
            with page.expect_response(
                lambda response: response.url.endswith("/aria2-cookie-rpc-local")
                and response.request.method == "POST"
            ):
                frame.get_by_role("button", name="Add task").click()
            second_cookie_call = rpc_calls[-1]
            self.assertEqual(second_cookie_call["cookie_bytes"], second_cookie_bytes)
            self.assertEqual(second_cookie_call["body"].get("tme3_route"), "non")

            route_picker.select_option("non")
            with page.expect_response(
                lambda response: response.url.endswith("/aria2-rpc-local")
                and response.request.method == "POST"
                and cookie_url in (response.request.post_data or "")
            ):
                frame.get_by_role("button", name="Add task").click()
            repeated_call = rpc_calls[-1]
            self.assertEqual(repeated_call["path"], "/aria2-rpc-local")
            self.assertNotIn("cookie_bytes", repeated_call)

            with page.expect_response(
                lambda response: response.url.endswith("/aria2-rpc-local")
                and response.request.method == "POST"
                and "unrelated.example.test/other.bin" in (response.request.post_data or "")
            ):
                frame.locator("#unrelated-task").click()
            unrelated_call = next(
                call for call in rpc_calls
                if call["path"] == "/aria2-rpc-local"
                and "unrelated.example.test/other.bin" in json.dumps(call["body"])
            )
            self.assertNotIn("cookie_bytes", unrelated_call)
            self.assertNotIn("ui-cookie-secret", page.locator("body").inner_text())

            route_picker.select_option("non")
            with page.expect_response(
                lambda response: response.url.endswith("/aria2-rpc-local")
                and response.request.method == "POST"
            ):
                frame.get_by_role("button", name="Add task").click()
            self.assertEqual(rpc_calls[-1]["body"].get("method"), "aria2.addUri")
            self.assertNotIn("cookie_bytes", rpc_calls[-1])

            frame.locator("main").evaluate("""(main) => {
              main.innerHTML = `<section class="content"><div class="nav-tabs-custom">
                <ul class="nav nav-tabs"><li class="active"><a ng-click="changeTab('settings')">Settings</a></li></ul>
                <div class="tab-content"><div class="tab-pane active" ng-class="{'active': context.currentTab === 'settings'}">
                  <div class="settings-table"></div>
                </div></div>
              </div></section>`;
              location.hash = '#!/task/detail/0123456789abcdef';
            }""")
            edit_control = frame.locator('[data-tme3-route="tme3-edit-task-route-control"]')
            expect(edit_control).to_be_visible(timeout=10000)
            frame.get_by_label("Rute task").select_option("tor")
            frame.get_by_role("button", name="Terapkan rute").click()
            expect(edit_control.get_by_role("status")).to_have_text(
                "Rute Tor diterapkan pada task ini.", timeout=10000
            )
            edited_calls = rpc_calls[-4:]
            self.assertEqual(
                [call["body"]["method"] for call in edited_calls],
                ["aria2.tellStatus", "aria2.pause", "aria2.changeOption", "aria2.unpause"],
            )
            self.assertEqual(edited_calls[2]["body"].get("tme3_route"), "tor")
            self.assertEqual(edited_calls[2]["body"]["params"], ["0123456789abcdef", {}])
            self.assertNotIn("tme3_route", edited_calls[-1]["body"])
            self.assertTrue(all(call["csrf"] == "local-e2e-csrf" for call in edited_calls))

            reject_tor_route_change[0] = True
            frame.get_by_label("Rute task").select_option("tor")
            frame.get_by_role("button", name="Terapkan rute").click()
            expect(edit_control.get_by_role("status")).to_have_text(
                "ARIA2_TOR_UNAVAILABLE: Tor worker belum siap.", timeout=10000
            )
            failed_edit_calls = rpc_calls[-3:]
            self.assertEqual(
                [call["body"]["method"] for call in failed_edit_calls],
                ["aria2.tellStatus", "aria2.pause", "aria2.changeOption"],
            )
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
