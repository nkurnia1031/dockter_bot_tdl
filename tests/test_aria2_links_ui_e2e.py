from __future__ import annotations

import os
import unittest

from tme3bot.api.routes.workers import _aria2_links_setup_script


RUN_E2E = os.environ.get("TME3_RUN_ARIA2_LINKS_UI_E2E") == "1"


@unittest.skipUnless(RUN_E2E, "Set TME3_RUN_ARIA2_LINKS_UI_E2E=1 to run the local mocked browser E2E")
class Aria2LinksBrowserE2ETests(unittest.TestCase):
    def test_mixed_links_album_selection_folder_tor_and_task_route_controls(self):
        from playwright.sync_api import sync_playwright

        html = """
        <!doctype html>
        <html><body>
          <form name="newTaskForm">
            <textarea name="urls"></textarea>
            <button type="submit">Add</button>
          </form>
        </body></html>
        """
        setup_script = _aria2_links_setup_script("local")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.route(
                "http://links.test/**",
                lambda route: route.fulfill(status=200, content_type="text/html", body=html),
            )
            page.goto("http://links.test/")
            page.evaluate("document.cookie = 'tme3_csrf=csrf-test; path=/'")
            page.evaluate(
                "localStorage.setItem('tme3-aria2-folder:local', '/workspace/selected-folder')"
            )
            page.evaluate("""() => {
              window.__linksCalls = [];
              window.__linksTask = null;
              window.fetch = async (input, init = {}) => {
                const path = String(input);
                const body = init.body ? JSON.parse(init.body) : null;
                const headers = new Headers(init.headers || {});
                window.__linksCalls.push({path, method: init.method || 'GET', body, csrf: headers.get('X-CSRF-Token')});
                let result = {};
                if (path.endsWith('/preview')) {
                  result = {items: [
                    {source_index: 0, kind: 'direct', title: 'direct.bin', error: '', files: [
                      {item_id: '', file_name: 'direct.bin', thumbnail_url: ''}
                    ]},
                    {source_index: 1, kind: 'album', title: 'Album Demo', error: '', files: [
                      {item_id: 'album-one', file_name: 'one.zip', thumbnail_url: 'https://images.test/one.jpg'},
                      {item_id: 'album-two', file_name: 'two.zip', thumbnail_url: ''}
                    ]}
                  ]};
                } else if (path.endsWith('/enqueue')) {
                  window.__linksTask = {
                    gid: '1111111111111111', file_name: 'direct.bin', status: 'waiting',
                    route: body.route, completed_bytes: 0, total_bytes: 100, speed_bytes_per_second: 0,
                    error_code: '', reason_code: ''
                  };
                  result = {items: [
                    {source_index: 0, file_name: 'direct.bin', status: 'queued', route: body.route},
                    {source_index: 1, file_name: 'one.zip', status: 'queued', route: body.route}
                  ]};
                } else if (path.endsWith('/tasks')) {
                  result = {items: window.__linksTask ? [window.__linksTask] : []};
                } else if (path.endsWith('/pause')) {
                  window.__linksTask.status = 'paused'; result = {gid: window.__linksTask.gid, status: 'paused'};
                } else if (path.endsWith('/route')) {
                  window.__linksTask.route = body.route; result = {gid: window.__linksTask.gid, status: 'paused', route: body.route};
                } else if (path.endsWith('/resume')) {
                  window.__linksTask.status = 'active'; result = {gid: window.__linksTask.gid, status: 'active'};
                } else {
                  throw new Error(`Unexpected mocked request: ${path}`);
                }
                return new Response(JSON.stringify(result), {status: 200, headers: {'Content-Type': 'application/json'}});
              };
            }""")
            page.add_script_tag(content=setup_script)

            page.locator('form[name="newTaskForm"] textarea').fill(
                "https://cdn.example.test/direct.bin\nhttps://bunkr.cr/a/album-demo"
            )
            page.locator('form[name="newTaskForm"] button[type="submit"]').click()
            dialog = page.get_by_role("dialog", name="Pilih file Bunkr")
            dialog.wait_for(state="visible")
            self.assertEqual(dialog.locator("img").count(), 1)
            checkboxes = dialog.locator('input[type="checkbox"]')
            self.assertEqual(checkboxes.count(), 3)
            checkboxes.nth(2).uncheck()
            page.locator('[data-tme3-links-panel] select[aria-label="Rute unduh"]').select_option("tor")
            dialog.get_by_role("button", name="Tambahkan ke Aria2").click()
            page.get_by_text("2 task masuk antrean").wait_for()

            calls = page.evaluate("window.__linksCalls")
            preview_call = next(call for call in calls if call["path"].endswith("/preview"))
            enqueue_call = next(call for call in calls if call["path"].endswith("/enqueue"))
            self.assertEqual(preview_call["body"]["sources"], [
                "https://cdn.example.test/direct.bin", "https://bunkr.cr/a/album-demo"
            ])
            self.assertEqual(enqueue_call["body"]["selections"], {"0": [""], "1": ["album-one"]})
            self.assertEqual(enqueue_call["body"]["directory"], "/workspace/selected-folder")
            self.assertEqual(enqueue_call["body"]["route"], "tor")
            self.assertTrue(all(call["csrf"] == "csrf-test" for call in calls if call["method"] == "POST"))
            self.assertNotIn("signed-secret", page.locator("body").inner_text())

            page.get_by_role("button", name="Jeda").click()
            route = page.get_by_label("Rute task direct.bin")
            route.select_option("non")
            page.get_by_role("button", name="Ubah rute").click()
            page.get_by_text("Rute task direct.bin diperbarui.").wait_for()
            page.get_by_role("button", name="Lanjutkan").click()

            calls = page.evaluate("window.__linksCalls")
            self.assertTrue(any(
                call["path"].endswith("/tasks/1111111111111111/route")
                and call["body"] == {"route": "non"}
                for call in calls
            ))
            self.assertTrue(any(call["path"].endswith("/tasks/1111111111111111/resume") for call in calls))


if __name__ == "__main__":
    unittest.main()
