from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from tme3bot.worker.aria2_runtime import Aria2Runtime
from tme3bot.worker.tor_http_proxy import TorHttpProxyServer


RUN_E2E = os.environ.get("TME3_RUN_ARIA2_TOR_E2E") == "1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@unittest.skipUnless(
    RUN_E2E,
    "Set TME3_RUN_ARIA2_TOR_E2E=1 to run real aria2 + Tor egress E2E",
)
class Aria2TorE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        for binary in ("aria2c", "tor"):
            if shutil.which(binary) is None:
                self.fail(f"Required E2E binary is missing: {binary}")

        self.temporary = tempfile.TemporaryDirectory(prefix="aria2-tor-e2e-")
        self.root = Path(self.temporary.name)
        self.database = self.root / "database"
        self.shared_token_file = self.database / "aria2-proxy" / "token"
        self.shared_token_file.parent.mkdir(parents=True)
        self.shared_token_file.write_text("isolated-e2e-token\n", encoding="utf-8")
        self.shared_token_file.chmod(0o600)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.destination = self.workspace / "aria2"
        self.hook = self.root / "aria2-error-hook.py"
        self.hook.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        self.hook.chmod(0o700)

        self.tor_process: subprocess.Popen | None = None
        self.aria2_process: subprocess.Popen | None = None
        self.proxy: TorHttpProxyServer | None = None
        self.runtime: Aria2Runtime | None = None
        try:
            self.socks_port = _free_port()
            self._start_tor()

            self.proxy = TorHttpProxyServer(
                token_file=self.shared_token_file,
                socks_host="127.0.0.1",
                socks_port=self.socks_port,
                host="127.0.0.1",
                port=0,
            )
            self.proxy.start()

            rpc_port = _free_port()
            with patch.dict(
                os.environ,
                {"ARIA2_TOR_PROXY_TOKEN_FILE": str(self.shared_token_file)},
            ):
                self.runtime = Aria2Runtime(
                    state_root=self.database / "aria2",
                    workspace_root=self.workspace,
                    hook_script_path=self.hook,
                    rpc_url=f"http://127.0.0.1:{rpc_port}/jsonrpc",
                )
            self.runtime.ensure()

            self.aria2_process = subprocess.Popen(
                [
                    "aria2c",
                    f"--conf-path={self.runtime.config_file}",
                    "--daemon=false",
                    "--rpc-listen-all=false",
                    f"--rpc-listen-port={rpc_port}",
                    f"--dir={self.destination}",
                    "--console-log-level=warn",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._wait_for_aria2()

            self.runtime.bunkr_links.tor_ready = self.proxy.ready
            token = self.shared_token_file.read_text(encoding="utf-8").strip()
            proxy_host, proxy_port = self.proxy.address
            self.runtime.bunkr_links.tor_proxy_url = lambda: (
                f"http://aria2:{quote(token, safe='')}@{proxy_host}:{proxy_port}"
            )
        except Exception:
            self._stop_processes()
            self.temporary.cleanup()
            raise

    def tearDown(self) -> None:
        self._stop_processes()
        self.temporary.cleanup()

    def _start_tor(self) -> None:
        data_dir = self.root / "tor-data"
        data_dir.mkdir(mode=0o700)
        log_file = self.root / "tor.log"
        self.tor_process = subprocess.Popen(
            [
                "tor",
                "--SocksPort", f"127.0.0.1:{self.socks_port}",
                "--DataDirectory", str(data_dir),
                "--AvoidDiskWrites", "1",
                "--Log", f"notice file {log_file}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self.tor_process.poll() is not None:
                self.fail("Tor exited before bootstrap completed")
            try:
                if "Bootstrapped 100%" in log_file.read_text(encoding="utf-8", errors="replace"):
                    return
            except OSError:
                pass
            time.sleep(1)
        self.fail("Tor did not finish bootstrapping within five minutes")

    def _wait_for_aria2(self) -> None:
        assert self.runtime is not None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.aria2_process and self.aria2_process.poll() is not None:
                self.fail("aria2c exited before its JSON-RPC endpoint became ready")
            result = self.runtime.rpc({
                "jsonrpc": "2.0",
                "id": "e2e-ready",
                "method": "aria2.getVersion",
                "params": [],
            })
            if isinstance(result.get("result"), dict):
                return
            time.sleep(0.2)
        self.fail("aria2c JSON-RPC did not become ready")

    def _visible_gids(self) -> set[str]:
        assert self.runtime is not None
        queries = (
            ("aria2.tellActive", []),
            ("aria2.tellWaiting", [0, 1000]),
            ("aria2.tellStopped", [0, 1000]),
        )
        visible: set[str] = set()
        for index, (method, params) in enumerate(queries):
            response = self.runtime.rpc({
                "jsonrpc": "2.0",
                "id": f"aria-ng-list-{index}",
                "method": method,
                "params": params,
            })
            rows = response.get("result", [])
            if isinstance(rows, list):
                visible.update(
                    str(row.get("gid")) for row in rows
                    if isinstance(row, dict) and row.get("gid")
                )
        return visible

    def _stop_processes(self) -> None:
        for process in (self.aria2_process,):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        if self.proxy is not None:
            self.proxy.close()
        if self.tor_process is not None and self.tor_process.poll() is None:
            self.tor_process.terminate()
            try:
                self.tor_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.tor_process.kill()
                self.tor_process.wait(timeout=5)

    def test_tor_routed_task_is_listed_and_download_body_confirms_tor_exit(self) -> None:
        assert self.runtime is not None
        last_status: dict[str, object] = {}
        for attempt in range(2):
            response = self.runtime.rpc(
                {
                    "jsonrpc": "2.0",
                    "id": f"tor-e2e-add-{attempt}",
                    "method": "aria2.addUri",
                    "params": [
                        ["https://check.torproject.org/api/ip"],
                        {"out": f"tor-egress-{attempt}.json"},
                    ],
                    "tme3_route": "tor",
                },
                requested_directory=str(self.destination),
            )
            gid = response.get("result")
            self.assertIsInstance(gid, str, "Tor submission must return an aria2 GID")
            self.assertEqual(len(gid), 16)

            deadline = time.monotonic() + 30
            while gid not in self._visible_gids() and time.monotonic() < deadline:
                time.sleep(0.2)
            self.assertIn(
                gid,
                self._visible_gids(),
                "the GID must appear in aria2 active/waiting/stopped lists consumed by AriaNg",
            )

            deadline = time.monotonic() + 90
            status: dict[str, object] = {}
            while time.monotonic() < deadline:
                status_response = self.runtime.rpc({
                    "jsonrpc": "2.0",
                    "id": f"tor-e2e-status-{attempt}",
                    "method": "aria2.tellStatus",
                    "params": [gid, ["gid", "status", "errorCode", "errorMessage"]],
                })
                result = status_response.get("result")
                if isinstance(result, dict):
                    status = result
                    if result.get("status") in {"complete", "error", "removed"}:
                        break
                time.sleep(1)

            if status.get("status") == "complete":
                downloaded = self.destination / f"tor-egress-{attempt}.json"
                self.assertTrue(
                    downloaded.is_file(),
                    "completed AriaNg task must produce its result file",
                )
                result_body = json.loads(downloaded.read_text(encoding="utf-8"))
                self.assertIs(
                    result_body.get("IsTor"),
                    True,
                    "the downloaded response must prove Tor egress",
                )
                self.runtime.rpc({
                    "jsonrpc": "2.0",
                    "id": f"tor-e2e-remove-result-{attempt}",
                    "method": "aria2.removeDownloadResult",
                    "params": [gid],
                })
                return

            last_status = status
            if status.get("status") != "error" or attempt == 1:
                break
            self.runtime.rpc({
                "jsonrpc": "2.0",
                "id": f"tor-e2e-remove-error-{attempt}",
                "method": "aria2.removeDownloadResult",
                "params": [gid],
            })

        self.fail(
            "Tor-routed task must complete and prove Tor egress; "
            f"last aria2 status: {json.dumps(last_status, sort_keys=True)}"
        )


if __name__ == "__main__":
    unittest.main()
