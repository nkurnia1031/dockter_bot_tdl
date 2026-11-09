from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tme3bot.worker.aria2_runtime import Aria2Runtime


class _Aria2RpcHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(size).decode("utf-8"))
        token = request.get("params", [""])[0]
        if token != f"token:{self.server.rpc_secret}":
            status = 401
            body = {"error": {"code": 1, "message": "Unauthorized"}}
        else:
            status = 200
            body = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {"version": "1.36.0", "enabledFeatures": ["BitTorrent"]},
            }
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format, *_args):
        return


class Aria2RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "database" / "aria2"
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.destination = self.workspace / "aria2"
        self.hook = self.root / "aria2-retry-on-low-speed.py"
        self.hook.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        self.hook.chmod(0o755)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Aria2RpcHandler)
        self.server.rpc_secret = ""
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.runtime = Aria2Runtime(
            state_root=self.state,
            workspace_root=self.workspace,
            hook_script_path=self.hook,
            rpc_url=f"http://127.0.0.1:{self.server.server_port}/jsonrpc",
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def test_bootstrap_persists_private_state_and_reports_hooked_rpc_health(self):
        self.runtime.ensure()
        first_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        self.server.rpc_secret = first_secret
        self.runtime.ensure()
        health = self.runtime.health()

        self.assertTrue(first_secret)
        self.assertEqual(first_secret, self.runtime.secret_file.read_text(encoding="utf-8").strip())
        self.assertEqual(self.runtime.secret_file.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.destination.is_dir())
        self.assertTrue(health["ready"])
        self.assertTrue(health["engine"]["ready"])
        self.assertTrue(health["hook"]["ready"])
        self.assertEqual(health["engine"]["version"], "1.36.0")
        self.assertNotIn(first_secret, json.dumps(health))

    def test_health_is_not_ready_when_the_custom_hook_is_missing(self):
        self.hook.unlink()
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()

        health = self.runtime.health()

        self.assertFalse(health["ready"])
        self.assertTrue(health["engine"]["ready"])
        self.assertFalse(health["hook"]["ready"])
        self.assertEqual(health["reason_code"], "ARIA2_HOOK_UNAVAILABLE")

    def test_restart_bootstrap_preserves_aria2_session(self):
        self.runtime.ensure()
        session = "gid-one\n"
        self.runtime.session_file.write_text(session, encoding="utf-8")
        self.runtime.ensure()

        self.assertEqual(self.runtime.session_file.read_text(encoding="utf-8"), session)
        self.assertEqual(self.runtime.session_file.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
