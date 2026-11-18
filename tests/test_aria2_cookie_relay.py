from __future__ import annotations

import json
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from tme3bot.worker.aria2_cookie_relay import (
    Aria2CookieRelayServer,
    Aria2CookieTaskStore,
    redact_cookie_task_urls,
)
from tme3bot.worker.aria2_runtime import Aria2Runtime


class _OriginHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._serve_file()

    def do_HEAD(self):
        self._serve_file()

    def _serve_file(self):
        self.server.received_cookies.append(self.headers.get("Cookie", ""))
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", self.server.redirect_target)
            self.end_headers()
            return
        if self.path != "/secure/archive.zip":
            self.send_error(404)
            return
        body = b"secure-archive-payload"
        range_header = self.headers.get("Range")
        if range_header == "bytes=0-5":
            body = body[:6]
            self.send_response(206)
            self.send_header("Content-Range", "bytes 0-5/22")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", 'attachment; filename="archive.zip"')
        self.send_header("X-Upstream-Private", "must-not-pass")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


class _FakeAria2:
    def __init__(self):
        self.calls = []
        self.status = "active"
        self.gid = "abcd1234abcd1234"
        self.next_gid = 0

    def __call__(self, method, *params):
        self.calls.append((method, params))
        if method == "addUri":
            self.next_gid += 1
            self.gid = f"{self.next_gid:016x}"
            self.status = "active"
            self.uris, self.options = params
            return self.gid
        if method == "tellActive":
            return [{"gid": self.gid, "status": self.status, "files": [{"uris": [{"uri": self.uris[0]}]}]}] if self.status == "active" else []
        if method == "tellWaiting":
            return []
        if method == "tellStopped":
            return [{"gid": self.gid, "status": self.status, "files": [{"uris": [{"uri": self.uris[0]}]}]}] if self.status in {"complete", "error", "removed"} else []
        return "OK"


class Aria2CookieRelayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "database" / "aria2"
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.origin_state = self.root / "origin"
        self.origin_state.mkdir()
        self.key_file = self.origin_state / "key.pem"
        self.cert_file = self.origin_state / "cert.pem"
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(self.key_file), "-out", str(self.cert_file),
                "-days", "1", "-subj", "/CN=127.0.0.1",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.http_origin = ThreadingHTTPServer(("127.0.0.1", 0), _OriginHandler)
        self.https_origin = ThreadingHTTPServer(("127.0.0.1", 0), _OriginHandler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(str(self.cert_file), str(self.key_file))
        self.https_origin.socket = tls.wrap_socket(self.https_origin.socket, server_side=True)
        self.http_origin.received_cookies = []
        self.https_origin.received_cookies = []
        self.http_origin.redirect_target = ""
        self.https_origin_thread = threading.Thread(target=self.https_origin.serve_forever, daemon=True)
        self.http_origin_thread = threading.Thread(target=self.http_origin.serve_forever, daemon=True)
        self.https_origin_thread.start()
        self.http_origin_thread.start()
        self.http_origin.redirect_target = (
            f"https://127.0.0.1:{self.https_origin.server_port}/secure/archive.zip"
        )
        self.rpc = _FakeAria2()
        self.ssl_unverified = ssl._create_unverified_context()
        self.relay = Aria2CookieRelayServer(
            state_root=self.state,
            rpc=self.rpc,
            rpc_secret=lambda: "aria2-test-secret",
            tor_proxy_url=lambda: "",
            ssl_context=self.ssl_unverified,
            listen_host="127.0.0.1",
            listen_port=0,
        )
        self.relay.start()
        self.runtime = Aria2Runtime(
            state_root=self.state,
            workspace_root=self.workspace,
            cookie_relay_url=self.relay.base_url,
            rpc_url="http://127.0.0.1:1/jsonrpc",
        )

    def tearDown(self):
        self.relay.close()
        for server in (self.http_origin, self.https_origin):
            server.shutdown()
            server.server_close()
        self.http_origin_thread.join(timeout=2)
        self.https_origin_thread.join(timeout=2)
        self.temporary.cleanup()

    def test_cookie_task_survives_restart_respects_cookie_rules_and_cleans_terminal_tasks(self):
        self.runtime.ensure()
        self.runtime.secret_file.write_text("aria2-test-secret\n", encoding="utf-8")
        http_url = f"http://127.0.0.1:{self.http_origin.server_port}/start"
        cookie_file = (
            "# Netscape HTTP Cookie File\n"
            f"127.0.0.1\tFALSE\t/secure\tTRUE\t4102444800\tsid\tper-task-cookie\n"
            f"127.0.0.1\tFALSE\t/outside\tTRUE\t4102444800\tpath_cookie\twrong-path\n"
            f"localhost\tFALSE\t/\tFALSE\t4102444800\tother_host\twrong-host\n"
            f"127.0.0.1\tFALSE\t/\tTRUE\t4102444800\tsecure_host\twrong-scheme\n"
            f"127.0.0.1\tFALSE\t/\tFALSE\t4102444800\thost_cookie\tvalid-host\n"
        ).encode()

        result = self.runtime.rpc(
            {
                "jsonrpc": "2.0",
                "id": "cookie-task",
                "method": "aria2.addUri",
                "params": [[http_url], {"out": "archive.zip"}],
            },
            cookie_file=cookie_file,
        )

        self.assertEqual(result["result"], self.rpc.gid)
        self.assertNotIn("per-task-cookie", json.dumps(result))
        relay_uri = self.rpc.uris[0]
        relay_token = urlsplit(relay_uri).path.split("/")[2]
        redacted_uri = redact_cookie_task_urls(relay_uri)
        self.assertIn("[task-token]", redacted_uri)
        self.assertNotIn(relay_token, redacted_uri)
        public_status = self.runtime._restore_cookie_task_uris(
            "aria2.tellStatus",
            [self.rpc.gid],
            {"result": {
                "gid": self.rpc.gid,
                "errorMessage": f"Transfer failed for {relay_uri}",
                "files": [{"uris": [{"uri": relay_uri}]}],
            }},
        )
        serialized_status = json.dumps(public_status)
        self.assertNotIn(relay_token, serialized_status)
        self.assertIn(http_url, serialized_status)
        self.assertIn("[task-token]", serialized_status)

        self.rpc.status = "pruned"
        self.relay.reconcile(force=True)
        retained_task = self.relay.store.task_for_gid(self.rpc.gid)
        self.assertIsNotNone(retained_task)
        self.assertTrue(self.relay.store.cookie_path(relay_token).is_file())
        self.rpc.status = "active"

        relay_port = urlsplit(relay_uri).port
        self.relay.close()
        self.relay = Aria2CookieRelayServer(
            state_root=self.state,
            rpc=self.rpc,
            rpc_secret=lambda: "aria2-test-secret",
            tor_proxy_url=lambda: "",
            ssl_context=self.ssl_unverified,
            listen_host="127.0.0.1",
            listen_port=relay_port,
        )
        self.relay.start()
        self.runtime = Aria2Runtime(
            state_root=self.state,
            workspace_root=self.workspace,
            cookie_relay_url=self.relay.base_url,
            rpc_url="http://127.0.0.1:1/jsonrpc",
        )

        with urlopen(Request(relay_uri, method="HEAD"), context=self.ssl_unverified) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("Content-Length"), "22")
            self.assertIsNone(response.headers.get("X-Upstream-Private"))
            self.assertEqual(response.read(), b"")
        with urlopen(Request(relay_uri, headers={"Range": "bytes=0-5"}), context=self.ssl_unverified) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"secure")
            self.assertEqual(response.headers.get("Content-Range"), "bytes 0-5/22")
            self.assertIsNone(response.headers.get("X-Upstream-Private"))
        https_cookies = [set(value.split("; ")) for value in self.https_origin.received_cookies]
        http_cookies = [set(value.split("; ")) for value in self.http_origin.received_cookies]
        self.assertEqual(https_cookies, [
            {"sid=per-task-cookie", "secure_host=wrong-scheme", "host_cookie=valid-host"},
            {"sid=per-task-cookie", "secure_host=wrong-scheme", "host_cookie=valid-host"},
        ])
        self.assertEqual(http_cookies, [
            {"host_cookie=valid-host"}, {"host_cookie=valid-host"},
        ])

        self.rpc.status = "removed"
        self.relay.reconcile(force=True)
        with self.assertRaises(Exception):
            urlopen(relay_uri, context=self.ssl_unverified)

        completed = self.runtime.rpc(
            {
                "jsonrpc": "2.0",
                "id": "complete-cookie-task",
                "method": "aria2.addUri",
                "params": [[http_url], {"out": "complete.zip"}],
            },
            cookie_file=cookie_file,
        )
        self.assertEqual(completed["result"], self.rpc.gid)
        completed_uri = self.rpc.uris[0]
        self.rpc.status = "complete"
        self.relay.reconcile(force=True)
        with self.assertRaises(Exception):
            urlopen(completed_uri, context=self.ssl_unverified)
        self.assertEqual(self.relay.store.tasks(), [])

    def test_store_removes_orphaned_cookie_jars_on_startup(self):
        cookie_root = self.state / "cookie-tasks"
        cookie_root.mkdir(parents=True, exist_ok=True)
        orphan = cookie_root / ("f" * 64 + ".cookies")
        orphan.write_text("stale-cookie", encoding="utf-8")

        Aria2CookieTaskStore(self.state)

        self.assertFalse(orphan.exists())

    def test_store_rejects_symlinked_cookie_and_database_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "database" / "aria2"
            state.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            (state / "cookie-tasks").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(ValueError):
                Aria2CookieTaskStore(state)

            (state / "cookie-tasks").unlink()
            (state / "aria2-cookie-tasks.sqlite3").symlink_to(outside / "db.sqlite3")
            with self.assertRaises(ValueError):
                Aria2CookieTaskStore(state)


if __name__ == "__main__":
    unittest.main()
