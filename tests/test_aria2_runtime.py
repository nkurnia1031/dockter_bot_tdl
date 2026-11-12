from __future__ import annotations

import json
import signal
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

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
            self.server.calls.append(request)
            method = request.get("method")
            if method in {"aria2.addUri", "aria2.addTorrent", "aria2.addMetalink"}:
                result = "new-gid"
            elif method == "aria2.getGlobalOption":
                result = {
                    "max-concurrent-downloads": "3",
                    "max-overall-download-limit": "0",
                    "rpc-secret": self.server.rpc_secret,
                    "save-session": "/private/session",
                }
            elif method == "aria2.changeGlobalOption":
                result = "OK"
            elif method in {"aria2.remove", "aria2.removeDownloadResult"}:
                result = "gid-one"
            else:
                result = {"version": "1.36.0", "enabledFeatures": ["BitTorrent"]}
            status = 200
            body = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": result,
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
        self.server.calls = []
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
        config = self.runtime._read_config()
        self.assertEqual(config["input-file"], str(self.runtime.session_file))
        self.assertEqual(config["save-session"], str(self.runtime.session_file))
        self.assertEqual(config["continue"], "true")
        self.assertEqual(config["save-session-interval"], "30")
        self.assertEqual(config["rpc-save-upload-metadata"], "true")
        self.assertEqual(config["bt-save-metadata"], "true")
        self.assertEqual(config["bt-load-saved-metadata"], "true")
        self.assertEqual(config["dht-file-path"], str(self.state / "dht.dat"))
        self.assertEqual(config["dht-file-path6"], str(self.state / "dht6.dat"))
        self.assertEqual(config["lowest-speed-limit"], "0")
        self.assertEqual(config["max-tries"], "0")

    def test_rpc_injects_private_secret_and_clamps_upload_to_workspace(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "add-1", "method": "aria2.addUri",
            "params": [["https://example.test/file.bin"], {"out": "file.bin"}],
        }, requested_directory=str(self.destination))

        self.assertEqual(result["result"], "new-gid")
        forwarded = self.server.calls[-1]
        self.assertEqual(forwarded["params"][0], f"token:{self.server.rpc_secret}")
        options = forwarded["params"][2]
        self.assertEqual(options["dir"], str(self.destination))
        self.assertEqual(options["allow-overwrite"], "false")
        self.assertEqual(options["auto-file-renaming"], "false")
        self.assertEqual(options["lowest-speed-limit"], "0")
        self.assertEqual(options["max-tries"], "0")
        self.assertNotIn(self.server.rpc_secret, json.dumps(result))

    def test_rpc_rejects_paths_outside_workspace_and_managed_methods(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        before = len(self.server.calls)

        outside = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "add-2", "method": "aria2.addUri",
            "params": [["https://example.test/file.bin"], {}],
        }, requested_directory=str(self.root))
        shutdown = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "bad", "method": "aria2.shutdown", "params": [],
        })
        managed_option = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "managed", "method": "aria2.addUri",
            "params": [["https://example.test/file.bin"], {"rpc-save-upload-metadata": "false"}],
        })
        command_hook = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "hook", "method": "aria2.addUri",
            "params": [["https://example.test/file.bin"], {"on-download-complete": "touch /tmp/x"}],
        })

        self.assertIn("error", outside)
        self.assertIn("error", shutdown)
        self.assertIn("error", managed_option)
        self.assertIn("error", command_hook)
        self.assertEqual(len(self.server.calls), before)

    def test_rpc_uses_selected_workspace_folder_and_keeps_collision_policy(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        selected = self.workspace / "selected"
        selected.mkdir()
        existing = selected / "already-there.bin"
        existing.write_bytes(b"keep existing data")

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "selected-folder", "method": "aria2.addUri",
            "params": [["https://example.test/already-there.bin"], {
                "dir": str(selected), "out": existing.name, "allow-overwrite": "true",
                "auto-file-renaming": "true",
            }],
        })

        self.assertEqual(result.get("result"), "new-gid")
        options = self.server.calls[-1]["params"][2]
        self.assertEqual(options["dir"], str(selected))
        self.assertEqual(options["allow-overwrite"], "false")
        self.assertEqual(options["auto-file-renaming"], "false")
        self.assertEqual(existing.read_bytes(), b"keep existing data")

    def test_rpc_defaults_to_private_aria2_folder_only_when_no_folder_was_selected(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "default-folder", "method": "aria2.addUri",
            "params": [["https://example.test/file.bin"], {}],
        })

        self.assertEqual(result.get("result"), "new-gid")
        self.assertEqual(
            self.server.calls[-1]["params"][2]["dir"],
            str(self.destination),
        )

    def test_rpc_normalizes_torrent_options_without_a_uri_list(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        selected = self.workspace / "torrent-target"
        selected.mkdir()

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "torrent", "method": "aria2.addTorrent",
            "params": ["YmFzZTY0", {"dir": str(selected)}],
        })

        self.assertEqual(result.get("result"), "new-gid")
        forwarded = self.server.calls[-1]["params"]
        self.assertEqual(forwarded[2], [])
        self.assertEqual(forwarded[3]["dir"], str(selected))
        self.assertEqual(forwarded[3]["allow-overwrite"], "false")

    def test_rpc_never_returns_managed_secrets_or_paths_from_global_options(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "options", "method": "aria2.getGlobalOption", "params": [],
        })

        self.assertEqual(result["result"], {
            "max-concurrent-downloads": "3",
            "max-overall-download-limit": "0",
        })
        self.assertNotIn(self.server.rpc_secret, json.dumps(result))

    def test_safe_global_transfer_settings_are_persisted_for_container_restart(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "settings", "method": "aria2.changeGlobalOption",
            "params": [{"max-overall-download-limit": "1M", "max-concurrent-downloads": "6"}],
        })

        self.assertEqual(result.get("result"), "OK")
        self.assertEqual(self.runtime._read_config()["max-overall-download-limit"], "1048576")
        self.assertEqual(self.runtime._read_config()["max-concurrent-downloads"], "6")
        restarted = Aria2Runtime(
            state_root=self.state,
            workspace_root=self.workspace,
            hook_script_path=self.hook,
            rpc_url=f"http://127.0.0.1:{self.server.server_port}/jsonrpc",
        )
        restarted.ensure()
        self.assertEqual(restarted._read_config()["max-overall-download-limit"], "1048576")

    def test_unsafe_global_transfer_settings_are_rejected_before_rpc(self):
        self.runtime.ensure()
        before = len(self.server.calls)

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "unsafe", "method": "aria2.changeGlobalOption",
            "params": [{"rpc-secret": "do-not-allow"}],
        })

        self.assertIn("error", result)
        self.assertEqual(len(self.server.calls), before)

    def test_out_of_range_global_transfer_settings_are_rejected_before_rpc(self):
        self.runtime.ensure()
        before = len(self.server.calls)

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "unsafe-range", "method": "aria2.changeGlobalOption",
            "params": [{"max-concurrent-downloads": "99"}],
        })

        self.assertIn("error", result)
        self.assertEqual(len(self.server.calls), before)

    def test_native_speed_abort_and_retry_limit_are_locked_to_disabled_and_unlimited(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        self.runtime.config_file.write_text(
            "lowest-speed-limit=102400\nmax-tries=7\n", encoding="utf-8"
        )
        self.runtime.ensure()
        config = self.runtime._read_config()
        self.assertEqual(config["lowest-speed-limit"], "0")
        self.assertEqual(config["max-tries"], "0")

        before = len(self.server.calls)
        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "native-options", "method": "aria2.changeGlobalOption",
            "params": [{"lowest-speed-limit": "100K", "max-tries": "5"}],
        })
        self.assertIn("error", result)
        self.assertEqual(len(self.server.calls), before)

    def test_cancel_and_remove_task_results_leave_workspace_partial_files_untouched(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        partial = self.destination / "partial.bin"
        control = self.destination / "partial.bin.aria2"
        partial.write_bytes(b"partial payload")
        control.write_bytes(b"control state")

        cancelled = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "cancel", "method": "aria2.remove", "params": ["gid-one"],
        })
        removed_result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "remove-result", "method": "aria2.removeDownloadResult",
            "params": ["gid-one"],
        })

        self.assertEqual(cancelled.get("result"), "gid-one")
        self.assertEqual(removed_result.get("result"), "gid-one")
        self.assertEqual(partial.read_bytes(), b"partial payload")
        self.assertEqual(control.read_bytes(), b"control state")

    def test_intentional_signal_shutdown_does_not_report_aria2_as_failed(self):
        handlers = {}

        class FakeProcess:
            def __init__(self):
                self.returncode = None
                self.signalled = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = -signal.SIGTERM

            def wait(self, timeout=None):
                del timeout
                if not self.signalled:
                    self.signalled = True
                    handlers[signal.SIGTERM](signal.SIGTERM, None)
                return self.returncode

            def kill(self):
                self.returncode = -signal.SIGKILL

        class FakeCoordinator:
            interval_seconds = 1

            def __init__(self, *_args, **_kwargs):
                pass

            def tick(self):
                pass

        def install_handler(number, handler):
            previous = handlers.get(number)
            handlers[number] = handler
            return previous

        process = FakeProcess()
        with (
            patch("tme3bot.worker.aria2_runtime.subprocess.Popen", return_value=process),
            patch("tme3bot.worker.aria2_runtime.Aria2RecoveryCoordinator", FakeCoordinator),
            patch("tme3bot.worker.aria2_runtime.signal.signal", side_effect=install_handler),
        ):
            self.runtime.run()

        self.assertEqual(process.returncode, -signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
