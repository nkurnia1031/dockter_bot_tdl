from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import yaml

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
                self.server.tasks[result] = {
                    "gid": result,
                    "status": "active",
                    "totalLength": "1",
                    "completedLength": "0",
                }
            elif method == "aria2.tellActive":
                result = list(self.server.tasks.values())
            elif method in {"aria2.tellWaiting", "aria2.tellStopped"}:
                result = []
            elif method == "aria2.tellStatus":
                result = {
                    "gid": request.get("params", [None, ""])[1],
                    "status": getattr(self.server, "task_status", "paused"),
                }
            elif method == "aria2.changeOption":
                result = "OK"
            elif method == "aria2.unpause":
                result = "active"
            elif method == "aria2.getOption":
                result = {
                    "all-proxy": "http://aria2:proxy-secret@tts-1:8118",
                    "all-proxy-user": "aria2",
                    "all-proxy-passwd": "proxy-secret",
                }
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
        self.server.tasks = {}
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
        first_proxy_token = self.runtime.tor_proxy_token_file.read_text(encoding="utf-8").strip()
        self.server.rpc_secret = first_secret
        self.runtime.ensure()
        health = self.runtime.health()

        self.assertTrue(first_secret)
        self.assertEqual(first_secret, self.runtime.secret_file.read_text(encoding="utf-8").strip())
        self.assertEqual(self.runtime.secret_file.stat().st_mode & 0o777, 0o600)
        self.assertTrue(first_proxy_token)
        self.assertEqual(first_proxy_token, self.runtime.tor_proxy_token_file.read_text(encoding="utf-8").strip())
        self.assertEqual(self.runtime.tor_proxy_token_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.runtime.tor_proxy_token_file.parent.stat().st_mode & 0o777, 0o700)
        self.assertTrue(self.destination.is_dir())
        self.assertTrue(health["ready"])
        self.assertTrue(health["engine"]["ready"])
        self.assertTrue(health["hook"]["ready"])
        self.assertEqual(health["engine"]["version"], "1.36.0")
        self.assertNotIn(first_secret, json.dumps(health))
        self.assertNotIn(first_proxy_token, json.dumps(health))

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

    def test_rpc_routes_plain_ariang_download_through_tor_without_exposing_proxy_secret(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        proxy_url = "http://aria2:proxy-secret@tts-1:8118"
        self.runtime.bunkr_links.tor_ready = lambda: True
        self.runtime.bunkr_links.tor_proxy_url = lambda: proxy_url

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "tor-add", "method": "aria2.addUri",
            "params": [["https://example.test/file.bin"], {}], "tme3_route": "tor",
        }, requested_directory=str(self.destination))

        self.assertEqual(result["result"], "new-gid")
        added = self.server.calls[-1]
        options = added["params"][2]
        self.assertEqual(options["all-proxy"], proxy_url)
        self.assertEqual(options["proxy-method"], "tunnel")
        self.assertNotIn("proxy-secret", json.dumps(result))
        self.assertNotIn(self.server.rpc_secret, json.dumps(result))

        status = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "tor-options", "method": "aria2.getOption",
            "params": ["new-gid"],
        })
        self.assertNotIn("proxy-secret", json.dumps(status))
        self.assertNotIn("all-proxy", json.dumps(status))

    def test_tor_task_is_listed_for_ariang_and_uses_the_shared_proxy_token(self):
        compose = yaml.safe_load(
            (Path(__file__).resolve().parents[1] / "docker-compose.worker.yml").read_text(
                encoding="utf-8"
            )
        )
        configured_token_path = compose["services"]["worker"]["environment"].get(
            "ARIA2_TOR_PROXY_TOKEN_FILE"
        )
        self.assertEqual(configured_token_path, "/database/aria2-proxy/token")

        shared_token_file = self.root / "database" / "aria2-proxy" / "token"
        shared_token_file.parent.mkdir(parents=True)
        shared_token_file.write_text("shared-tor-token\n", encoding="utf-8")
        with patch.dict(os.environ, {"ARIA2_TOR_PROXY_TOKEN_FILE": str(shared_token_file)}):
            runtime = Aria2Runtime(
                state_root=self.state,
                workspace_root=self.workspace,
                hook_script_path=self.hook,
                rpc_url=f"http://127.0.0.1:{self.server.server_port}/jsonrpc",
            )
        runtime.ensure()
        self.server.rpc_secret = runtime.secret_file.read_text(encoding="utf-8").strip()
        runtime.bunkr_links.tor_ready = lambda: True

        submitted = runtime.rpc({
            "jsonrpc": "2.0",
            "id": "tor-visible-task",
            "method": "aria2.addUri",
            "params": [["https://check.torproject.org/api/ip"], {}],
            "tme3_route": "tor",
        }, requested_directory=str(self.destination))
        listed = runtime.rpc({
            "jsonrpc": "2.0",
            "id": "aria-ng-active-list",
            "method": "aria2.tellActive",
            "params": [],
        })

        self.assertEqual(submitted.get("result"), "new-gid")
        self.assertIn(
            "new-gid",
            {item["gid"] for item in listed.get("result", [])},
            "AriaNg's active-task query must contain the submitted GID",
        )
        forwarded_add = next(
            call for call in self.server.calls if call.get("method") == "aria2.addUri"
        )
        options = forwarded_add["params"][2]
        self.assertEqual(
            options["all-proxy"],
            "http://aria2:shared-tor-token@tts-1:8118",
        )
        self.assertEqual(options["proxy-method"], "tunnel")
        self.assertEqual(shared_token_file.read_text(encoding="utf-8"), "shared-tor-token\n")
        self.assertFalse((self.state / "tor-proxy.token").exists())

    def test_rpc_non_route_clears_proxy_for_new_ariang_download(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "direct-add", "method": "aria2.addUri",
            "params": [["https://example.test/file.bin"], {}], "tme3_route": "non",
        }, requested_directory=str(self.destination))

        self.assertEqual(result["result"], "new-gid")
        options = self.server.calls[-1]["params"][2]
        self.assertEqual(options["all-proxy"], "")
        self.assertEqual(options["proxy-method"], "get")

    def test_rpc_tor_route_fails_visibly_without_falling_back_when_tor_is_unavailable(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        self.runtime.bunkr_links.tor_ready = lambda: False
        before = len(self.server.calls)

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "tor-unavailable", "method": "aria2.addUri",
            "params": [["https://example.test/file.bin"], {}], "tme3_route": "tor",
        }, requested_directory=str(self.destination))

        self.assertIn("error", result)
        self.assertIn("ARIA2_TOR_UNAVAILABLE", result["error"]["message"])
        self.assertEqual(len(self.server.calls), before)

    def test_tor_route_returns_a_sanitized_rpc_error_when_shared_token_is_missing(self):
        missing_token_file = self.root / "database" / "aria2-proxy" / "token"
        with patch.dict(os.environ, {"ARIA2_TOR_PROXY_TOKEN_FILE": str(missing_token_file)}):
            runtime = Aria2Runtime(
                state_root=self.state,
                workspace_root=self.workspace,
                hook_script_path=self.hook,
                rpc_url=f"http://127.0.0.1:{self.server.server_port}/jsonrpc",
            )
        self.destination.mkdir(parents=True, exist_ok=True)
        runtime.bunkr_links.tor_ready = lambda: True

        result = runtime.rpc({
            "jsonrpc": "2.0", "id": "missing-tor-token", "method": "aria2.addUri",
            "params": [["https://example.test/file.bin"], {}], "tme3_route": "tor",
        }, requested_directory=str(self.destination))

        self.assertIn("error", result)
        self.assertIn("ARIA2_TOR_UNAVAILABLE", result["error"]["message"])
        self.assertNotIn(str(missing_token_file), json.dumps(result))
        self.assertEqual(self.server.calls, [])

    def test_rpc_applies_selected_route_only_to_the_paused_task_being_edited(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        proxy_url = "http://aria2:proxy-secret@tts-1:8118"
        self.runtime.bunkr_links.tor_ready = lambda: True
        self.runtime.bunkr_links.tor_proxy_url = lambda: proxy_url

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "edit-tor", "method": "aria2.changeOption",
            "params": ["1234567890abcdef", {}], "tme3_route": "tor",
        })

        self.assertEqual(result["result"], "OK")
        methods = [call["method"] for call in self.server.calls[-2:]]
        self.assertEqual(methods, ["aria2.tellStatus", "aria2.changeOption"])
        self.assertEqual(self.server.calls[-1]["params"][2]["all-proxy"], proxy_url)
        self.assertEqual(self.server.calls[-1]["params"][1], "1234567890abcdef")

    def test_rpc_holds_paused_task_when_tor_route_change_cannot_be_applied(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        self.runtime.bunkr_links.tor_ready = lambda: False
        before = len(self.server.calls)

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "edit-tor-unavailable", "method": "aria2.changeOption",
            "params": ["1234567890abcdef", {}], "tme3_route": "tor",
        })

        self.assertIn("error", result)
        self.assertIn("ARIA2_TOR_UNAVAILABLE", result["error"]["message"])
        self.assertEqual(
            [call["method"] for call in self.server.calls[before:]],
            ["aria2.tellStatus"],
        )

    def test_rpc_rejects_editing_route_while_task_is_not_paused(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        self.server.task_status = "active"
        before = len(self.server.calls)

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "edit-active", "method": "aria2.changeOption",
            "params": ["1234567890abcdef", {}], "tme3_route": "tor",
        })

        self.assertIn("error", result)
        self.assertIn("jeda", result["error"]["message"].lower())
        calls = self.server.calls[before:]
        self.assertEqual([call["method"] for call in calls], ["aria2.tellStatus"])

    def test_rpc_rejects_route_metadata_on_unpause(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        before = len(self.server.calls)

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "resume-tor", "method": "aria2.unpause",
            "params": ["1234567890abcdef"], "tme3_route": "tor",
        })

        self.assertIn("error", result)
        self.assertEqual(self.server.calls[before:], [])

    def test_rpc_rejects_route_edit_for_tasks_owned_by_bunkr_links(self):
        self.runtime.ensure()
        self.server.rpc_secret = self.runtime.secret_file.read_text(encoding="utf-8").strip()
        task_key = self.runtime.bunkr_links.store.reserve({
            "kind": "direct", "source_url": "", "item_id": "", "album_name": "",
            "file_name": "managed.bin", "destination": str(self.destination / "managed.bin"),
            "route": "tor",
        }, destination_exists=False)
        self.runtime.bunkr_links.store.set_gid(task_key, "1234567890abcdef", status="queued")

        result = self.runtime.rpc({
            "jsonrpc": "2.0", "id": "edit-managed", "method": "aria2.changeOption",
            "params": ["1234567890abcdef", {}], "tme3_route": "non",
        })

        self.assertIn("error", result)
        self.assertEqual(self.server.calls, [])

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
                self.stdout = io.StringIO("")

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

    def test_aria2_process_output_redacts_signed_urls_before_docker_logs(self):
        handlers = {}

        class FakeProcess:
            def __init__(self):
                self.returncode = None
                self.stdout = io.StringIO(
                    "download error https://cdn.invalid/file.zip?token=signed-secret\n"
                    "proxy failure http://aria2:proxy-secret@tts-1:8118\n"
                )

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = -signal.SIGTERM

            def wait(self, timeout=None):
                del timeout
                self.returncode = 0
                return self.returncode

            def kill(self):
                self.returncode = -signal.SIGKILL

        def install_handler(number, handler):
            previous = handlers.get(number)
            handlers[number] = handler
            return previous

        process = FakeProcess()
        captured = io.StringIO()
        with (
            patch("tme3bot.worker.aria2_runtime.subprocess.Popen", return_value=process) as popen,
            patch("tme3bot.worker.aria2_runtime.Aria2RecoveryCoordinator") as coordinator,
            patch("tme3bot.worker.aria2_runtime.signal.signal", side_effect=install_handler),
            redirect_stdout(captured),
        ):
            coordinator.return_value.interval_seconds = 1
            self.runtime.run()

        popen.assert_called_once()
        self.assertIs(popen.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertIs(popen.call_args.kwargs["stderr"], subprocess.STDOUT)
        self.assertNotIn("signed-secret", captured.getvalue())
        self.assertNotIn("proxy-secret", captured.getvalue())
        self.assertIn("[query disembunyikan]", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
