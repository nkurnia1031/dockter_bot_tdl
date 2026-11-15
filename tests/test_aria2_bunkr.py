from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import httpx

from tme3bot.worker.aria2_bunkr import (
    Aria2BunkrLinks,
    BunkrFile,
    BunkrLinkError,
    BunkrResolver,
    BunkrTaskStore,
    redact_aria2_response,
)


class FakeResolver:
    def __init__(self):
        self.size = 100
        self.ranges = True
        self.etag = '"stable-file-v1"'
        self.last_modified = ""
        self.fail_resolve = False
        self.direct = "https://cdn.example.invalid/file?token=secret"

    @staticmethod
    def normalize_source(source):
        return str(source).split("?", 1)[0]

    def preview(self, source):
        if "/a/" in source:
            return {
                "kind": "album",
                "title": "Album Test",
                "files": [
                    {"item_id": "one", "source_url": "https://bunkr.cr/f/one", "file_name": "one.bin", "thumbnail_url": "https://img.invalid/one.jpg"},
                    {"item_id": "two", "source_url": "https://bunkr.cr/f/two", "file_name": "two.bin", "thumbnail_url": ""},
                ],
            }
        return {
            "kind": "file",
            "title": "single.bin",
            "files": [{"item_id": "single", "source_url": source, "file_name": "single.bin", "thumbnail_url": ""}],
        }

    def resolve_file(self, source, item_id=None):
        if self.fail_resolve:
            raise RuntimeError("temporary resolver failure")
        identifier = item_id or "single"
        return BunkrFile(identifier, source, f"{identifier}.bin", direct_url=self.direct)

    def probe(self, _url):
        return self.size, self.ranges

    def probe_metadata(self, _url):
        return SimpleNamespace(
            size=self.size,
            range_supported=self.ranges,
            etag=self.etag,
            last_modified=self.last_modified,
        )


class FakeRpc:
    def __init__(self):
        self.calls = []
        self.gids = iter([f"{value:016x}" for value in range(1, 20)])
        self.status = {}
        self.uris = {}
        self.change_uri_result = [1, 1]

    def __call__(self, method, *params):
        self.calls.append((method, params))
        if method == "addUri":
            gid = next(self.gids)
            options = params[1] if len(params) > 1 else {}
            self.status[gid] = {
                "gid": gid,
                "status": "paused" if options.get("pause") == "true" else "waiting",
                "completedLength": "0",
                "totalLength": "100",
            }
            self.uris[gid] = [{"uri": "https://cdn.invalid/old?token=secret", "status": "used"}]
            return gid
        if method == "tellStatus":
            return dict(self.status.get(params[0], {}))
        if method == "getUris":
            return list(self.uris.get(params[0], []))
        if method in {"pause", "forcePause"}:
            self.status[params[0]]["status"] = "paused"
            return params[0]
        if method == "unpause":
            self.status[params[0]]["status"] = "active"
            return params[0]
        if method == "changeOption":
            return "OK"
        if method == "changeUri":
            return self.change_uri_result
        if method == "tellActive":
            return [dict(item) for item in self.status.values() if item.get("status") == "active"]
        if method == "tellWaiting":
            return [dict(item) for item in self.status.values() if item.get("status") == "waiting"]
        if method == "tellStopped":
            return []
        return "OK"


class FakeRecoveryEvents:
    def __init__(self, gids):
        self.gids = list(gids)
        self.consumed = []

    def read(self):
        return {"error_event_gids": list(self.gids)}

    def consume_error_events(self, gids):
        self.consumed.extend(gids)
        consumed = set(gids)
        self.gids = [gid for gid in self.gids if gid not in consumed]


class Aria2BunkrLinksTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.rpc = FakeRpc()
        self.resolver = FakeResolver()
        self.links = Aria2BunkrLinks(
            workspace_root=self.workspace,
            state_root=self.root / "database",
            rpc=self.rpc,
            resolver=self.resolver,
            tor_ready=lambda: True,
            tor_proxy_url=lambda: "http://aria2:test-proxy-token@tts-1:8118",
            clock=lambda: 1000.0,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_preview_mixed_batch_returns_album_items_without_signed_urls(self):
        result = self.links.preview({"sources": [
            "https://example.invalid/direct.zip",
            "https://bunkr.cr/a/album?token=source-secret",
        ]})
        self.assertEqual([item["kind"] for item in result["items"]], ["direct", "album"])
        self.assertEqual(result["items"][1]["files"][0]["file_name"], "one.bin")
        self.assertNotIn("source-secret", repr(result))
        self.assertNotIn("cdn.example.invalid", repr(result))

    def test_existing_task_database_adds_validator_columns_in_place(self):
        path = self.root / "database" / "legacy-aria2-link-tasks.sqlite3"
        path.parent.mkdir(exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute(
                """CREATE TABLE aria2_link_tasks (
                    task_key TEXT PRIMARY KEY,
                    gid TEXT UNIQUE,
                    kind TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    album_name TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    route TEXT NOT NULL,
                    expected_size INTEGER,
                    range_supported INTEGER NOT NULL DEFAULT 0,
                    source_scheme TEXT NOT NULL DEFAULT 'https',
                    source_port INTEGER NOT NULL DEFAULT 443,
                    status TEXT NOT NULL,
                    reason_code TEXT NOT NULL DEFAULT '',
                    refresh_attempts INTEGER NOT NULL DEFAULT 0,
                    retry_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                )"""
            )

        store = BunkrTaskStore(path)
        store.reserve({
            "kind": "bunkr",
            "source_url": "https://bunkr.cr/f/one",
            "item_id": "one",
            "album_name": "",
            "file_name": "one.bin",
            "destination": str(self.workspace / "one.bin"),
            "route": "non",
            "expected_size": 100,
            "range_supported": True,
            "source_scheme": "https",
            "source_port": 443,
            "expected_etag": '"stable-file-v1"',
            "expected_last_modified": "Tue, 12 Nov 2024 10:00:00 GMT",
        }, destination_exists=False)

        row = store.tasks()[0]
        self.assertEqual(row["expected_etag"], '"stable-file-v1"')
        self.assertEqual(row["expected_last_modified"], "Tue, 12 Nov 2024 10:00:00 GMT")

    def test_album_enqueue_creates_one_task_per_selected_file_in_album_folder(self):
        result = self.links.enqueue({
            "sources": ["https://bunkr.cr/a/album"],
            "selections": {"0": ["one", "two"]},
            "directory": str(self.workspace),
            "route": "non",
        })
        self.assertEqual([item["status"] for item in result["items"]], ["queued", "queued"])
        self.assertEqual(len([call for call in self.rpc.calls if call[0] == "addUri"]), 2)
        rows = self.links.store.tasks()
        self.assertEqual({Path(row["destination"]).parent.name for row in rows}, {"Album Test"})
        self.assertTrue(all("token=secret" not in row["source_url"] for row in rows))

    def test_explicit_empty_album_selection_does_not_enqueue_default_all(self):
        result = self.links.enqueue({
            "sources": ["https://bunkr.cr/a/album"],
            "selections": {"0": []},
            "directory": str(self.workspace),
            "route": "non",
        })
        self.assertEqual(result["items"], [
            {"source_index": 0, "status": "skipped", "reason_code": "NO_ITEMS_SELECTED"}
        ])
        self.assertFalse(any(call[0] == "addUri" for call in self.rpc.calls))

    def test_filename_conflict_skips_that_item_without_overwrite(self):
        album = self.workspace / "Album Test"
        album.mkdir()
        (album / "one.bin").write_bytes(b"existing")
        result = self.links.enqueue({
            "sources": ["https://bunkr.cr/a/album"],
            "selections": {"0": ["one", "two"]},
            "directory": str(self.workspace),
            "route": "non",
        })
        self.assertEqual([item["reason_code"] for item in result["items"]], ["FILE_CONFLICT", ""])
        self.assertEqual(len([call for call in self.rpc.calls if call[0] == "addUri"]), 1)
        self.assertEqual((album / "one.bin").read_bytes(), b"existing")

    def test_album_folder_symlink_cannot_escape_workspace(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.workspace / "Album Test").symlink_to(outside, target_is_directory=True)
        result = self.links.enqueue({
            "sources": ["https://bunkr.cr/a/album"],
            "selections": {"0": ["one"]},
            "directory": str(self.workspace),
            "route": "non",
        })
        self.assertEqual(result["items"][0]["status"], "failed")
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse(any(call[0] == "addUri" for call in self.rpc.calls))

    def test_tor_route_is_applied_per_task_and_unavailable_tor_fails_closed(self):
        result = self.links.enqueue({
            "sources": ["https://example.invalid/direct.zip"],
            "selections": {}, "directory": str(self.workspace), "route": "tor",
        })
        self.assertEqual(result["items"][0]["route"], "tor")
        add_call = next(call for call in self.rpc.calls if call[0] == "addUri")
        self.assertEqual(
            add_call[1][1]["all-proxy"],
            "http://aria2:test-proxy-token@tts-1:8118",
        )
        self.links.tor_ready = lambda: False
        held = self.links.enqueue({
            "sources": ["https://example.invalid/another.zip"],
            "selections": {}, "directory": str(self.workspace), "route": "tor",
        })["items"][0]
        self.assertEqual(held["status"], "held")
        self.assertEqual(held["reason_code"], "ARIA2_TOR_UNAVAILABLE")
        held_options = [call for call in self.rpc.calls if call[0] == "addUri"][-1][1][1]
        self.assertEqual(held_options["pause"], "true")
        held_task = next(item for item in self.links.tasks()["items"] if item["gid"] == held["gid"])
        self.assertEqual(held_task["status"], "held")
        self.assertEqual(held_task["reason_code"], "ARIA2_TOR_UNAVAILABLE")

    def test_tor_route_rejects_unrecognized_protocols(self):
        result = self.links.enqueue({
            "sources": ["gopher://files.example.invalid/archive.zip"],
            "selections": {}, "directory": str(self.workspace), "route": "tor",
        })
        self.assertEqual(result["items"][0]["status"], "failed")
        self.assertFalse(any(call[0] == "addUri" for call in self.rpc.calls))

    def test_tor_route_supports_aria2_protocols_and_nonstandard_http_ports(self):
        urls = [
            "http://example.invalid:8080/http.bin",
            "https://example.invalid:8443/https.bin",
            "ftp://example.invalid:21/ftp.bin",
            "sftp://example.invalid:22/sftp.bin",
        ]
        result = self.links.enqueue({
            "sources": urls,
            "selections": {},
            "directory": str(self.workspace),
            "route": "tor",
        })

        self.assertEqual([item["status"] for item in result["items"]], ["queued"] * 4)
        calls = [call for call in self.rpc.calls if call[0] == "addUri"]
        self.assertEqual(len(calls), 4)
        for _method, params in calls:
            self.assertIn("all-proxy", params[1])
            self.assertEqual(params[1]["proxy-method"], "tunnel")

    def test_task_route_change_requires_paused_task_and_changes_only_that_task(self):
        created = self.links.enqueue({
            "sources": ["https://example.invalid/direct.zip"],
            "selections": {}, "directory": str(self.workspace), "route": "non",
        })["items"][0]
        gid = created["gid"]
        with self.assertRaisesRegex(BunkrLinkError, "Jeda task"):
            self.links.set_route(gid, "tor")
        self.links.pause(gid)
        result = self.links.set_route(gid, "tor")
        self.assertEqual(result["route"], "tor")
        self.links.resume(gid)
        self.assertEqual(self.links.store.get(gid)["route"], "tor")

    def test_active_tor_task_is_held_when_worker_tor_service_becomes_unhealthy(self):
        queued = self.links.enqueue({
            "sources": ["https://example.invalid/direct.zip"],
            "selections": {}, "directory": str(self.workspace), "route": "tor",
        })["items"][0]
        gid = queued["gid"]
        self.rpc.status[gid]["status"] = "active"
        self.links.tor_ready = lambda: False
        self.links.clock = lambda: 1011.0

        self.links.tick()

        self.assertEqual(self.rpc.status[gid]["status"], "paused")
        task = next(item for item in self.links.tasks()["items"] if item["gid"] == gid)
        self.assertEqual(task["status"], "held")
        self.assertEqual(task["reason_code"], "ARIA2_TOR_UNAVAILABLE")

    def test_only_bunkr_error_events_are_consumed_by_link_refresh_manager(self):
        direct = self.links.enqueue({
            "sources": ["https://downloads.example.invalid/direct.bin"],
            "selections": {}, "directory": str(self.workspace), "route": "non",
        })["items"][0]
        bunkr = self.links.enqueue({
            "sources": ["https://bunkr.cr/f/file"],
            "selections": {"0": ["single"]}, "directory": str(self.workspace), "route": "non",
        })["items"][0]
        recovery = FakeRecoveryEvents([direct["gid"], bunkr["gid"]])

        self.links.tick(recovery)

        self.assertEqual(recovery.consumed, [bunkr["gid"]])
        self.assertEqual(recovery.gids, [direct["gid"]])
        self.assertFalse(self.links.is_bunkr_task(direct["gid"]))
        self.assertTrue(self.links.is_bunkr_task(bunkr["gid"]))

    def test_resume_keeps_tor_task_held_when_tor_is_still_unhealthy(self):
        queued = self.links.enqueue({
            "sources": ["https://example.invalid/direct.zip"],
            "selections": {}, "directory": str(self.workspace), "route": "tor",
        })["items"][0]
        gid = queued["gid"]
        self.links.pause(gid)
        self.links.tor_ready = lambda: False

        with self.assertRaisesRegex(BunkrLinkError, "ARIA2_TOR_UNAVAILABLE"):
            self.links.resume(gid)

        task = next(item for item in self.links.tasks()["items"] if item["gid"] == gid)
        self.assertEqual(task["status"], "held")
        self.assertEqual(task["reason_code"], "ARIA2_TOR_UNAVAILABLE")

    def test_tor_route_remains_attached_when_unavailable_and_resume_cannot_bypass_it(self):
        queued = self.links.enqueue({
            "sources": ["https://example.invalid/direct.zip"],
            "selections": {}, "directory": str(self.workspace), "route": "non",
        })["items"][0]
        gid = queued["gid"]
        self.links.pause(gid)
        self.links.tor_ready = lambda: False

        with self.assertRaisesRegex(BunkrLinkError, "ARIA2_TOR_UNAVAILABLE"):
            self.links.set_route(gid, "tor")

        self.assertEqual(self.links.store.get(gid)["route"], "tor")
        with self.assertRaisesRegex(BunkrLinkError, "ARIA2_TOR_UNAVAILABLE"):
            self.links.resume(gid)
        self.assertFalse(any(call[0] == "unpause" and call[1][0] == gid for call in self.rpc.calls))

        self.links.tor_ready = lambda: True
        self.links.resume(gid)
        route_change_index = max(
            index for index, call in enumerate(self.rpc.calls)
            if call[0] == "changeOption" and call[1][0] == gid
        )
        resume_index = max(
            index for index, call in enumerate(self.rpc.calls)
            if call[0] == "unpause" and call[1][0] == gid
        )
        self.assertLess(route_change_index, resume_index)
        route_options = self.rpc.calls[route_change_index][1][1]
        self.assertTrue(route_options["all-proxy"].startswith("http://aria2:"))
        self.assertEqual(route_options["proxy-method"], "tunnel")

    def test_aria2_http_authorization_error_code_refreshes_same_bunkr_task(self):
        result = self.links.enqueue({
            "sources": ["https://bunkr.cr/f/single"],
            "selections": {"0": ["single"]},
            "directory": str(self.workspace), "route": "non",
        })["items"][0]
        gid = result["gid"]
        self.rpc.status[gid].update({
            "status": "active",
            "completedLength": "0",
            "totalLength": "100",
            "errorCode": "24",
            "errorMessage": "Authorization failed.",
        })

        self.links.tick()

        self.assertEqual(len([call for call in self.rpc.calls if call[0] == "changeUri"]), 1)
        self.assertEqual(len(self.links.store.tasks()), 1)

    def test_same_size_partial_with_different_etag_is_held_for_review(self):
        result = self.links.enqueue({
            "sources": ["https://bunkr.cr/f/single"],
            "selections": {"0": ["single"]},
            "directory": str(self.workspace), "route": "non",
        })["items"][0]
        gid = result["gid"]
        self.rpc.status[gid].update({
            "status": "active",
            "completedLength": "50",
            "totalLength": "100",
            "errorMessage": "HTTP 403 Forbidden",
        })
        self.resolver.etag = '"different-file-v2"'

        self.links.tick()

        row = self.links.store.get(gid)
        self.assertEqual(row["status"], "held")
        self.assertEqual(row["reason_code"], "BUNKR_PARTIAL_METADATA_MISMATCH")
        self.assertFalse(any(call[0] == "changeUri" for call in self.rpc.calls))

    def test_expired_url_is_replaced_on_same_gid_and_mismatch_holds_partial(self):
        result = self.links.enqueue({
            "sources": ["https://bunkr.cr/f/single"],
            "selections": {"0": ["single"]},
            "directory": str(self.workspace), "route": "non",
        })["items"][0]
        gid = result["gid"]
        self.rpc.status[gid].update({
            "status": "active", "completedLength": "50", "totalLength": "100",
            "errorMessage": "HTTP 403 Forbidden",
        })
        self.links.tick()
        self.assertIn(("changeUri", (gid, 1, ["https://cdn.invalid/old?token=secret"], [self.resolver.direct])), self.rpc.calls)
        self.assertEqual(self.links.store.get(gid)["status"], "active")
        self.assertEqual(len(self.links.store.tasks()), 1)

        self.rpc.status[gid]["errorMessage"] = "HTTP 401 Unauthorized"
        self.resolver.size = 101
        self.links.store.update(gid, retry_at=0)
        self.links.tick()
        self.assertEqual(self.links.store.get(gid)["status"], "held")
        self.assertEqual(self.links.store.get(gid)["reason_code"], "BUNKR_PARTIAL_METADATA_MISMATCH")

    def test_temporary_refresh_failure_persists_retry_without_leaking_signed_url(self):
        result = self.links.enqueue({
            "sources": ["https://bunkr.cr/f/single"],
            "selections": {"0": ["single"]},
            "directory": str(self.workspace), "route": "non",
        })["items"][0]
        gid = result["gid"]
        self.rpc.status[gid].update({
            "status": "active", "completedLength": "0", "totalLength": "100",
            "errorMessage": "HTTP 401 Unauthorized",
        })
        self.resolver.fail_resolve = True
        self.links.tick()
        row = self.links.store.get(gid)
        self.assertEqual(row["status"], "refreshing")
        self.assertEqual(row["refresh_attempts"], 1)
        self.assertGreater(row["retry_at"], 1000.0)
        self.assertNotIn("token=secret", repr(row))

    def test_refresh_retry_survives_manager_restart_without_adding_another_gid(self):
        result = self.links.enqueue({
            "sources": ["https://bunkr.cr/f/single"],
            "selections": {"0": ["single"]},
            "directory": str(self.workspace), "route": "non",
        })["items"][0]
        gid = result["gid"]
        self.rpc.status[gid].update({
            "status": "active", "completedLength": "0", "totalLength": "100",
            "errorMessage": "HTTP 401 Unauthorized",
        })
        self.resolver.fail_resolve = True
        self.links.tick()
        self.assertEqual(self.links.store.get(gid)["status"], "refreshing")

        self.resolver.fail_resolve = False
        self.links = Aria2BunkrLinks(
            workspace_root=self.workspace,
            state_root=self.root / "database",
            rpc=self.rpc,
            resolver=self.resolver,
            tor_ready=lambda: True,
            tor_proxy_url=lambda: "http://aria2:test-proxy-token@tts-1:8118",
            clock=lambda: 1006.0,
        )
        self.links.tick()

        self.assertEqual(self.links.store.get(gid)["status"], "active")
        self.assertEqual(len([call for call in self.rpc.calls if call[0] == "addUri"]), 1)
        self.assertEqual(len([call for call in self.rpc.calls if call[0] == "changeUri"]), 1)

    def test_uri_refresh_is_not_marked_success_when_aria2_replaces_no_uri(self):
        result = self.links.enqueue({
            "sources": ["https://bunkr.cr/f/single"],
            "selections": {"0": ["single"]},
            "directory": str(self.workspace), "route": "non",
        })["items"][0]
        gid = result["gid"]
        self.rpc.status[gid].update({
            "status": "active", "completedLength": "0", "totalLength": "100",
            "errorMessage": "HTTP 403 Forbidden",
        })
        self.rpc.change_uri_result = [1, 0]

        self.links.tick()

        row = self.links.store.get(gid)
        self.assertEqual(row["status"], "refreshing")
        self.assertEqual(row["reason_code"], "BUNKR_URL_REFRESH_RETRYING")
        self.assertEqual(row["refresh_attempts"], 1)

    def test_stopped_history_is_not_fetched_on_every_coordinator_tick(self):
        self.links.enqueue({
            "sources": ["https://bunkr.cr/f/single"],
            "selections": {"0": ["single"]},
            "directory": str(self.workspace), "route": "non",
        })
        self.links.tick()
        self.links.tick()
        self.assertEqual(sum(call[0] == "tellStopped" for call in self.rpc.calls), 1)

        self.links.clock = lambda: 1061.0
        self.links.tick()
        self.assertEqual(sum(call[0] == "tellStopped" for call in self.rpc.calls), 2)

    def test_public_aria2_response_redacts_urls_and_proxy_options(self):
        safe = redact_aria2_response({
            "uris": [{"uri": "https://cdn.invalid/x?token=secret", "status": "used"}],
            "errorMessage": "HTTP 403 at https://cdn.invalid/x?token=secret",
            "all-proxy": "socks5h://tts-1:9050",
        })
        serialized = repr(safe)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("tts-1", serialized)
        self.assertIn("[URL disembunyikan]", serialized)


class BunkrResolverTests(unittest.TestCase):
    def test_probe_does_not_expose_signed_url_in_httpx_logs(self):
        def handler(request):
            self.assertEqual(request.url.params.get("token"), "signed-secret")
            return httpx.Response(
                206,
                headers={
                    "Content-Range": "bytes 0-0/1234",
                    "Accept-Ranges": "bytes",
                    "ETag": '"stable-file-v1"',
                    "Last-Modified": "Tue, 12 Nov 2024 10:00:00 GMT",
                },
            )

        resolver = BunkrResolver(
            client_factory=lambda **kwargs: httpx.Client(
                transport=httpx.MockTransport(handler), **kwargs
            )
        )
        with self.assertLogs("httpx", level="INFO") as captured:
            size, supports_ranges = resolver.probe(
                "https://cdn.bunkr.cr/archive.zip?token=signed-secret&ex=123"
            )

        self.assertEqual(size, 1234)
        self.assertTrue(supports_ranges)
        metadata = resolver.probe_metadata(
            "https://cdn.bunkr.cr/archive.zip?token=signed-secret&ex=123"
        )
        self.assertEqual(metadata.etag, '"stable-file-v1"')
        self.assertEqual(metadata.last_modified, "Tue, 12 Nov 2024 10:00:00 GMT")
        self.assertNotIn("signed-secret", "\n".join(captured.output))

    def test_preview_returns_safe_file_metadata_and_resolve_signs_url(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.host == "bunkr.cr":
                return httpx.Response(
                    200,
                    text=(
                        '<html><head><meta property="og:image" content="//img.bunkr.cr/cover.jpg">'
                        '</head><body><h1>archive.zip</h1>'
                        '<script>var jsCDN = "https:\\/\\/cdn.bunkr.cr\\/storage\\/archive.zip";</script>'
                        '</body></html>'
                    ),
                )
            if request.url.host == "glb-apisign.cdn.cr":
                self.assertEqual(request.url.params.get("path"), "/storage/archive.zip")
                return httpx.Response(200, json={"token": "signed-secret", "ex": "123"})
            self.fail(f"unexpected request host: {request.url.host}")

        resolver = BunkrResolver(
            client_factory=lambda **kwargs: httpx.Client(
                transport=httpx.MockTransport(handler), **kwargs
            )
        )
        source = "https://bunkr.cr/f/archive-id?source-secret=hidden"

        preview = resolver.preview(source)
        self.assertEqual(preview["kind"], "file")
        self.assertEqual(preview["title"], "archive.zip")
        self.assertEqual(preview["files"][0]["thumbnail_url"], "https://img.bunkr.cr/cover.jpg")
        self.assertNotIn("source-secret", repr(preview))
        self.assertNotIn("signed-secret", repr(preview))

        resolved = resolver.resolve_file(source)
        self.assertEqual(
            resolved.direct_url,
            "https://cdn.bunkr.cr/storage/archive.zip?token=signed-secret&ex=123",
        )
        self.assertEqual([request.method for request in requests], ["GET", "GET", "GET", "GET"])

    def test_fallback_download_api_uses_gzip_and_deflate_before_signing(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.host == "bunkr.cr":
                return httpx.Response(
                    200,
                    text='<html><body><h1>archive.rar</h1><script data-file-id="file-42"></script></body></html>',
                )
            if request.url.host == "dl.bunkr.cr":
                self.assertEqual(request.method, "POST")
                self.assertEqual(request.headers.get("accept-encoding"), "gzip, deflate")
                self.assertEqual(request.read(), b'{"id":"file-42"}')
                return httpx.Response(
                    200,
                    json={
                        "mediafiles": "https://cdn.bunkr.cr/base/",
                        "path": "/storage/media/archive.rar",
                    },
                )
            if request.url.host == "glb-apisign.cdn.cr":
                self.assertEqual(request.url.params.get("path"), "/storage/media/archive.rar")
                return httpx.Response(200, json={"token": "fresh", "ex": "456"})
            self.fail(f"unexpected request host: {request.url.host}")

        resolver = BunkrResolver(
            client_factory=lambda **kwargs: httpx.Client(
                transport=httpx.MockTransport(handler), **kwargs
            )
        )
        resolved = resolver.resolve_file("https://bunkr.cr/f/file-42")
        self.assertEqual(resolved.file_name, "archive.rar")
        self.assertEqual(
            resolved.direct_url,
            "https://cdn.bunkr.cr/storage/media/archive.rar?token=fresh&ex=456",
        )
        self.assertEqual(
            [(request.method, request.url.host) for request in requests],
            [
                ("GET", "bunkr.cr"),
                ("POST", "dl.bunkr.cr"),
                ("GET", "glb-apisign.cdn.cr"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
