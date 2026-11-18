"""Own the per-worker aria2 configuration and expose safe health information."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

from tme3bot.database_paths import ensure_private_directory
from tme3bot.worker.aria2_bunkr import (
    Aria2BunkrLinks,
    BunkrLinkError,
    redact_aria2_response,
    redact_sensitive_urls_in_text,
)
from tme3bot.worker.aria2_recovery import (
    Aria2RecoveryCoordinator,
    Aria2RecoveryStateStore,
)


DEFAULT_RPC_URL = "http://aria2:6800/jsonrpc"
DEFAULT_HOOK_PATH = Path("/usr/local/bin/aria2-retry-on-low-speed.py")
LOGGER = logging.getLogger(__name__)
RPC_OPENER = build_opener(ProxyHandler({}))
ARIA2_RPC_METHODS = frozenset({
    "aria2.getVersion", "aria2.getSessionInfo", "aria2.getGlobalStat",
    "aria2.getGlobalOption", "aria2.changeGlobalOption", "aria2.tellActive",
    "aria2.tellWaiting", "aria2.tellStopped", "aria2.tellStatus", "aria2.getFiles", "aria2.getUris",
    "aria2.getPeers", "aria2.getServers", "aria2.getStatus", "aria2.getOption",
    "aria2.changeOption", "aria2.addUri", "aria2.addTorrent", "aria2.addMetalink",
    "aria2.remove", "aria2.forceRemove", "aria2.pause", "aria2.forcePause",
    "aria2.pauseAll", "aria2.unpause", "aria2.forceUnpause", "aria2.unpauseAll",
    "aria2.removeDownloadResult", "aria2.purgeDownloadResult",
    "aria2.changePosition", "aria2.forcePauseAll", "aria2.forceUnpauseAll",
})
SAFE_GLOBAL_OPTIONS = frozenset({
    "max-overall-download-limit", "max-overall-upload-limit",
    "max-concurrent-downloads", "max-connection-per-server", "split",
    "disk-cache", "retry-wait", "timeout",
    "connect-timeout", "file-allocation",
})
BLOCKED_OPTIONS = frozenset({
    "rpc-secret", "enable-rpc", "rpc-listen-port", "rpc-listen-all",
    "rpc-allow-origin-all", "input-file", "save-session", "log",
    "on-download-error", "daemon", "conf-path", "listen-port", "dht-listen-port",
    "rpc-save-upload-metadata", "bt-save-metadata", "bt-load-saved-metadata",
    "dht-file-path", "dht-file-path6",
    "on-download-start", "on-download-pause", "on-download-stop",
    "on-download-complete", "on-bt-download-complete",
    "load-cookies", "save-cookies", "netrc-path", "ca-certificate",
    "certificate", "private-key", "ssh-host-key-md",
    "all-proxy", "all-proxy-user", "all-proxy-passwd",
})


class Aria2Runtime:
    """Keep aria2's private state and health behind a small worker interface."""

    def __init__(
        self,
        *,
        state_root: Path | str,
        workspace_root: Path | str,
        hook_script_path: Path | str = DEFAULT_HOOK_PATH,
        rpc_url: str = DEFAULT_RPC_URL,
    ) -> None:
        self.state_root = Path(state_root)
        self.workspace_root = Path(workspace_root)
        self.download_root = self.workspace_root / "aria2"
        self.hook_script_path = Path(hook_script_path)
        self.rpc_url = str(rpc_url or DEFAULT_RPC_URL)
        self.config_file = self.state_root / "aria2.conf"
        self.secret_file = self.state_root / "rpc.secret"
        self.tor_proxy_token_file = Path(
            os.environ.get(
                "ARIA2_TOR_PROXY_TOKEN_FILE",
                str(self.state_root / "tor-proxy.token"),
            )
        )
        self.session_file = self.state_root / "aria2.session"
        self.hook_status_file = self.state_root / "aria2-hook-status.json"
        self.recovery_store = Aria2RecoveryStateStore(
            self.state_root / "aria2-recovery.json"
        )
        self.bunkr_links = Aria2BunkrLinks(
            workspace_root=self.workspace_root,
            state_root=self.state_root,
            rpc=self._bunkr_rpc,
            tor_proxy_url=self._tor_proxy_url,
        )
        self._settings_lock = threading.Lock()

    def ensure(self) -> None:
        ensure_private_directory(self.state_root)
        root = self.workspace_root.resolve(strict=True)
        self.download_root.mkdir(mode=0o755, parents=True, exist_ok=True)
        destination = self.download_root.resolve(strict=True)
        if not destination.is_relative_to(root):
            raise ValueError("Aria2 destination must stay within Workspace.")

        secret = self._ensure_secret()
        ensure_private_directory(self.tor_proxy_token_file.parent)
        self._ensure_tor_proxy_token()
        if not self.session_file.exists():
            self._write_private(self.session_file, "")
        self._write_private_atomic(self.config_file, self._config_text(secret))

    def health(self) -> dict[str, object]:
        config = self._read_config()
        hook_configured = config.get("on-download-error") == str(self.hook_script_path)
        hook_present = self.hook_script_path.is_file() and os.access(
            self.hook_script_path, os.X_OK
        )
        hook = {
            "ready": hook_present and hook_configured,
            "script_present": hook_present,
            "configured": hook_configured,
            "run_count": 0,
            "last_run_at": None,
            "last_result": "never",
        }
        try:
            status = json.loads(self.hook_status_file.read_text(encoding="utf-8"))
            if isinstance(status, dict):
                hook["run_count"] = max(0, int(status.get("hookRunCount", 0)))
                hook["last_run_at"] = status.get("lastHookRunAt")
                hook["last_result"] = str(status.get("lastHookResult", "unknown"))
        except (OSError, ValueError, TypeError):
            pass

        version = self._probe_version(config.get("rpc-secret", ""))
        engine = {"ready": version is not None, "version": version}
        ready = bool(engine["ready"] and hook["ready"])
        reason_code = ""
        if not engine["ready"]:
            reason_code = "ARIA2_ENGINE_UNAVAILABLE"
        elif not hook["ready"]:
            reason_code = "ARIA2_HOOK_UNAVAILABLE"
        return {
            "ready": ready,
            "reason_code": reason_code,
            "engine": engine,
            "hook": hook,
            "recovery": {
                "speed_threshold_bytes_per_second": self.recovery_store.get_speed_threshold(),
                "external_retry_limit": 10,
            },
        }

    def run(self) -> None:
        self.ensure()
        process = subprocess.Popen(
            ["aria2c", f"--conf-path={self.config_file}", "--daemon=false"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        output_thread = threading.Thread(
            target=self._forward_aria2_output,
            args=(process.stdout,),
            daemon=True,
            name="aria2-log-forwarder",
        )
        output_thread.start()
        secret = self.secret_file.read_text(encoding="utf-8").strip()

        def call(method: str, *params):
            return self._internal_rpc(secret, method, *params)

        coordinator = Aria2RecoveryCoordinator(
            call,
            self.recovery_store,
            workspace_root=self.workspace_root,
            ignore_error_gid=self.bunkr_links.is_bunkr_task,
        )
        stopping = threading.Event()
        previous_handlers = {}

        def stop(signum, _frame):
            del signum
            stopping.set()
            if process.poll() is None:
                process.terminate()

        for signal_number in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signal_number] = signal.signal(signal_number, stop)
        try:
            while process.poll() is None and not stopping.is_set():
                try:
                    self.bunkr_links.tick(self.recovery_store)
                    coordinator.tick()
                except Exception:
                    # RPC failures can contain transfer URLs or credentials.
                    LOGGER.warning("Aria2 recovery coordinator tick failed")
                try:
                    process.wait(timeout=coordinator.interval_seconds)
                except subprocess.TimeoutExpired:
                    pass
            if process.poll() is None:
                process.terminate()
            return_code = process.wait(timeout=10)
            if return_code and not stopping.is_set():
                raise SystemExit(return_code)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            output_thread.join()
            if process.stdout is not None:
                process.stdout.close()
            for signal_number, handler in previous_handlers.items():
                signal.signal(signal_number, handler)

    @staticmethod
    def _forward_aria2_output(stream) -> None:
        if stream is None:
            return
        try:
            for line in stream:
                sys.stdout.write(redact_sensitive_urls_in_text(line))
                sys.stdout.flush()
        except (OSError, ValueError):
            LOGGER.warning("Aria2 output stream closed before it was fully read")

    def recovery_settings(self) -> dict[str, int]:
        return {
            "speed_threshold_bytes_per_second": self.recovery_store.get_speed_threshold()
        }

    def update_recovery_settings(self, payload: object) -> dict[str, int]:
        if not isinstance(payload, dict) or set(payload) != {"speed_threshold_bytes_per_second"}:
            raise ValueError("Only the Aria2 speed threshold can be changed here.")
        threshold = self.recovery_store.set_speed_threshold(
            payload["speed_threshold_bytes_per_second"]
        )
        return {"speed_threshold_bytes_per_second": threshold}

    def rpc(
        self, request_payload: dict[str, Any], *, requested_directory: str = ""
    ) -> dict[str, Any]:
        request_id = request_payload.get("id") if isinstance(request_payload, dict) else None
        if (
            not isinstance(request_payload, dict)
            or request_payload.get("jsonrpc") != "2.0"
            or not isinstance(request_payload.get("method"), str)
            or request_payload.get("method") not in ARIA2_RPC_METHODS
        ):
            return _rpc_error(request_id, -32600, "Invalid or unsupported JSON-RPC request.")
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int, type(None))):
            return _rpc_error(None, -32600, "Invalid JSON-RPC request id.")
        if isinstance(request_id, str) and len(request_id) > 128:
            return _rpc_error(None, -32600, "Invalid JSON-RPC request id.")
        params = request_payload.get("params", [])
        if not isinstance(params, list) or len(params) > 20:
            return _rpc_error(request_id, -32602, "Invalid JSON-RPC parameters.")
        if any(isinstance(value, str) and value.startswith("token:") for value in params):
            return _rpc_error(request_id, -32602, "Client-supplied RPC credentials are not accepted.")

        method = request_payload["method"]
        route_requested = "tme3_route" in request_payload
        requested_route = request_payload.get("tme3_route")
        route_methods = {
            "aria2.addUri", "aria2.addTorrent", "aria2.addMetalink", "aria2.changeOption",
        }
        if route_requested and (
            method not in route_methods
            or not isinstance(requested_route, str)
            or requested_route not in {"non", "tor"}
        ):
            return _rpc_error(request_id, -32602, "Aria2 download route is invalid.")
        params = list(params)
        if method in {"aria2.addUri", "aria2.addTorrent", "aria2.addMetalink"}:
            options_index = {
                "aria2.addUri": 1,
                "aria2.addTorrent": 2,
                "aria2.addMetalink": 1,
            }[method]
            if method == "aria2.addTorrent":
                if len(params) == 1:
                    params.extend([[], {}])
                elif len(params) == 2 and isinstance(params[1], dict):
                    params.insert(1, [])
                elif len(params) > 1 and params[1] is None:
                    params[1] = []
                if len(params) > 1 and not isinstance(params[1], list):
                    return _rpc_error(request_id, -32602, "Torrent URI list is invalid.")
            options = params[options_index] if len(params) > options_index else {}
            if options is None:
                options = {}
            safe_options, error = self._safe_download_options(
                options,
                requested_directory=requested_directory,
                create=True,
            )
            if error:
                return _rpc_error(request_id, -32602, error)
            if route_requested:
                try:
                    safe_options.update(self.bunkr_links.route_options_for(requested_route))
                except BunkrLinkError as exc:
                    return _rpc_error(request_id, -32000, str(exc))
            while len(params) <= options_index:
                params.append(None)
            params[options_index] = safe_options
        elif method == "aria2.changeOption":
            if len(params) < 2:
                return _rpc_error(request_id, -32602, "Download options are required.")
            if route_requested and (
                not isinstance(params[0], str)
                or not re.fullmatch(r"[0-9a-fA-F]{16}", params[0])
            ):
                return _rpc_error(request_id, -32602, "Aria2 task id is invalid.")
            if route_requested and self.bunkr_links.store.contains(params[0]):
                return _rpc_error(
                    request_id,
                    -32602,
                    "Task ini dikelola dari tab Bunkr; ubah rute melalui daftar task Bunkr.",
                )
            safe_options, error = self._safe_download_options(params[1], create=False)
            if error:
                return _rpc_error(request_id, -32602, error)
            params[1] = safe_options
        elif method == "aria2.changeGlobalOption":
            if not params or not isinstance(params[0], dict):
                return _rpc_error(request_id, -32602, "Global transfer options are required.")
            safe_options, error = _safe_global_options(params[0])
            if error:
                return _rpc_error(request_id, -32602, error)
            params[0] = safe_options

        lock = self._settings_lock if method == "aria2.changeGlobalOption" else nullcontext()
        with lock:
            try:
                secret = self.secret_file.read_text(encoding="utf-8").strip()
                if not secret:
                    return _rpc_error(request_id, -32000, "Aria2 RPC is not configured.")
                if route_requested and method == "aria2.changeOption":
                    try:
                        status = self._internal_rpc(secret, "tellStatus", params[0], ["status"])
                    except Exception:
                        return _rpc_error(request_id, -32000, "Status task tidak dapat diperiksa.")
                    if not isinstance(status, dict) or status.get("status") != "paused":
                        return _rpc_error(
                            request_id,
                            -32000,
                            "Jeda task sebelum mengganti rute unduhan.",
                        )
                    try:
                        route_options = self.bunkr_links.route_options_for(requested_route)
                    except BunkrLinkError as exc:
                        return _rpc_error(request_id, -32000, str(exc))
                    params[1].update(route_options)
                body = json.dumps({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": [f"token:{secret}", *params],
                }).encode("utf-8")
                rpc_request = Request(
                    self.rpc_url,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with RPC_OPENER.open(rpc_request, timeout=30) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except Exception:
                return _rpc_error(request_id, -32000, "Aria2 worker is unavailable.")
            if (
                method == "aria2.changeGlobalOption"
                and isinstance(result, dict)
                and "error" not in result
            ):
                try:
                    self._persist_safe_global_options(params[0])
                except OSError:
                    return _rpc_error(
                        request_id,
                        -32000,
                        "Settings were applied but could not be saved for restart.",
                    )
        if not isinstance(result, dict):
            return _rpc_error(request_id, -32000, "Aria2 returned an invalid response.")
        result = self._redact_managed_result(method, params, result)
        result = _redact_aria2_proxy_options(result)
        result["jsonrpc"] = "2.0"
        result["id"] = request_id
        if method == "aria2.getGlobalOption" and isinstance(result.get("result"), dict):
            result["result"] = {
                key: value for key, value in result["result"].items()
                if key in SAFE_GLOBAL_OPTIONS
            }
        return result

    def bunkr_links_preview(self, payload: object) -> dict[str, Any]:
        return self.bunkr_links.preview(payload)

    def bunkr_links_enqueue(self, payload: object) -> dict[str, Any]:
        return self.bunkr_links.enqueue(payload)

    def bunkr_links_tasks(self) -> dict[str, Any]:
        return self.bunkr_links.tasks()

    def bunkr_link_task_control(self, gid: str, action: str, payload: object = None) -> dict[str, Any]:
        if action == "pause":
            return self.bunkr_links.pause(gid)
        if action == "resume":
            return self.bunkr_links.resume(gid)
        if action == "route":
            route = payload.get("route") if isinstance(payload, dict) else None
            return self.bunkr_links.set_route(gid, route)
        raise ValueError("Aria2 task action is unsupported.")

    def _bunkr_rpc(self, method: str, *params: object) -> object:
        secret = self.secret_file.read_text(encoding="utf-8").strip()
        if not secret:
            raise RuntimeError("Aria2 RPC is not configured.")
        return self._internal_rpc(secret, method, *params)

    def _redact_managed_result(
        self, method: str, params: list[Any], response: dict[str, Any]
    ) -> dict[str, Any]:
        result = response.get("result")
        gids: set[str] = set()
        if method in {"aria2.getUris", "aria2.getFiles", "aria2.getOption", "aria2.tellStatus", "aria2.getStatus"} and params:
            gids.add(str(params[0]))
        elif method in {"aria2.tellActive", "aria2.tellWaiting", "aria2.tellStopped"}:
            if isinstance(result, list):
                gids.update(str(item.get("gid")) for item in result if isinstance(item, dict))
        if not gids or not any(self.bunkr_links.store.contains(gid) for gid in gids):
            return response
        managed = {gid for gid in gids if self.bunkr_links.store.contains(gid)}
        if method in {"aria2.getUris", "aria2.getFiles", "aria2.getOption", "aria2.tellStatus", "aria2.getStatus"} and managed:
            response["result"] = redact_aria2_response(result)
            return response

        def sanitize(value: Any) -> Any:
            if isinstance(value, list):
                return [sanitize(item) for item in value]
            if isinstance(value, dict):
                gid = str(value.get("gid") or "")
                if gid in managed:
                    return redact_aria2_response(value)
                updated = dict(value)
                for key, item in updated.items():
                    updated[key] = sanitize(item)
                return updated
            return value

        response["result"] = sanitize(result)
        return response

    def ui_asset_path(self, asset_path: str) -> Path | None:
        root = Path(os.environ.get("ARIA2_UI_ROOT", "/opt/ariang"))
        try:
            resolved_root = root.resolve(strict=True)
            relative = PurePosixPath(str(asset_path or "index.html"))
            if relative.is_absolute() or "\\" in str(asset_path) or any(
                part in {"", ".", ".."} for part in relative.parts
            ):
                return None
            resolved_file = resolved_root.joinpath(*relative.parts).resolve(strict=True)
            resolved_file.relative_to(resolved_root)
            return resolved_file if resolved_file.is_file() else None
        except (OSError, ValueError):
            return None

    def _safe_download_options(
        self,
        raw_options: object,
        *,
        requested_directory: str = "",
        create: bool,
    ) -> tuple[dict[str, str] | None, str]:
        if not isinstance(raw_options, dict):
            return None, "Download options must be an object."
        if any(str(key) in BLOCKED_OPTIONS for key in raw_options):
            return None, "Managed aria2 options cannot be changed."
        options = {
            str(key): ("true" if value is True else "false" if value is False else str(value))
            for key, value in raw_options.items() if value is not None
        }
        directory_value = requested_directory or options.get("dir")
        if create and not directory_value:
            directory_value = str(self.download_root)
        if directory_value:
            try:
                workspace = self.workspace_root.resolve(strict=True)
                candidate = Path(directory_value)
                if not candidate.is_absolute():
                    candidate = workspace / candidate
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(workspace)
                if not resolved.is_dir():
                    raise ValueError
            except (OSError, ValueError):
                return None, "Download folder must be an existing directory inside Workspace."
            options["dir"] = str(resolved)
        if "out" in options:
            output_name = options["out"]
            if (
                not output_name
                or output_name in {".", ".."}
                or "/" in output_name
                or "\\" in output_name
            ):
                return None, "Download filename is invalid."
        options["allow-overwrite"] = "false"
        options["auto-file-renaming"] = "false"
        # Existing AriaNg per-download options and restored session entries must
        # not re-enable Aria2's native slow-speed abort or finite retry cap.
        options["lowest-speed-limit"] = "0"
        options["max-tries"] = "0"
        return options, ""

    def _ensure_secret(self) -> str:
        try:
            secret = self.secret_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            secret = ""
        if not secret:
            secret = secrets.token_urlsafe(32)
            descriptor = os.open(
                self.secret_file,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(secret + "\n")
        self.secret_file.chmod(0o600)
        return secret

    def _ensure_tor_proxy_token(self) -> str:
        try:
            self.tor_proxy_token_file.lstat()
            if not self.tor_proxy_token_file.is_file() or self.tor_proxy_token_file.is_symlink():
                raise ValueError("Aria2 Tor proxy token path must be a regular file.")
            token = self.tor_proxy_token_file.read_text(encoding="utf-8").strip()
            if token:
                self.tor_proxy_token_file.chmod(0o600)
                return token
        except FileNotFoundError:
            pass
        token = secrets.token_urlsafe(32)
        self._write_private_atomic(self.tor_proxy_token_file, token + "\n")
        return token

    def _tor_proxy_url(self) -> str:
        try:
            token = self.tor_proxy_token_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise BunkrLinkError(
                "ARIA2_TOR_UNAVAILABLE: kredensial proxy internal belum siap."
            ) from exc
        if not token:
            raise BunkrLinkError(
                "ARIA2_TOR_UNAVAILABLE: kredensial proxy internal belum siap."
            )
        return f"http://aria2:{quote(token, safe='')}@tts-1:8118"

    def _read_config(self) -> dict[str, str]:
        values: dict[str, str] = {}
        try:
            lines = self.config_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return values
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
        return values

    def _config_text(self, secret: str, *, overrides: dict[str, str] | None = None) -> str:
        managed = {
            "dir": str(self.download_root),
            "enable-rpc": "true",
            "rpc-listen-port": "6800",
            "rpc-listen-all": "true",
            "rpc-secret": secret,
            "rpc-allow-origin-all": "false",
            "rpc-save-upload-metadata": "true",
            "input-file": str(self.session_file),
            "save-session": str(self.session_file),
            "save-session-interval": "30",
            "auto-save-interval": "30",
            "log": str(self.state_root / "aria2.log"),
            "log-level": "notice",
            "console-log-level": "warn",
            "continue": "true",
            "check-integrity": "true",
            "disk-cache": "64M",
            "max-concurrent-downloads": "3",
            "max-connection-per-server": "5",
            "max-overall-download-limit": "0",
            "max-overall-upload-limit": "0",
            # Native low-speed abort is disabled; the coordinator uses its own
            # dynamic threshold and never asks aria2 to cancel a slow job.
            "lowest-speed-limit": "0",
            "max-tries": "0",
            "retry-wait": "0",
            "timeout": "60",
            "connect-timeout": "10",
            "split": "5",
            "file-allocation": "none",
            "on-download-error": str(self.hook_script_path),
            "enable-dht": "true",
            "enable-dht6": "false",
            "dht-file-path": str(self.state_root / "dht.dat"),
            "dht-file-path6": str(self.state_root / "dht6.dat"),
            "bt-save-metadata": "true",
            "bt-load-saved-metadata": "true",
            "listen-port": "6881-6999",
            "dht-listen-port": "6881-6999",
            "follow-torrent": "true",
        }
        existing = self._read_config()
        for key in SAFE_GLOBAL_OPTIONS:
            if existing.get(key):
                managed[key] = existing[key]
        for key, value in (overrides or {}).items():
            if key in SAFE_GLOBAL_OPTIONS:
                managed[key] = value
        managed["lowest-speed-limit"] = "0"
        managed["max-tries"] = "0"
        return "# aria2 configuration managed by tme3bot\n" + "".join(
            f"{key}={value}\n" for key, value in managed.items()
        )

    @staticmethod
    def _write_private(path: Path, value: str) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(value)
        path.chmod(0o600)

    @staticmethod
    def _write_private_atomic(path: Path, value: str) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(value)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _persist_safe_global_options(self, options: dict[str, str]) -> None:
        secret = self.secret_file.read_text(encoding="utf-8").strip()
        self._write_private_atomic(
            self.config_file,
            self._config_text(secret, overrides=options),
        )

    def _probe_version(self, secret: str) -> str | None:
        if not secret:
            return None
        body = json.dumps({
            "jsonrpc": "2.0", "id": "worker-health", "method": "aria2.getVersion",
            "params": [f"token:{secret}"],
        }).encode("utf-8")
        request = Request(
            self.rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with RPC_OPENER.open(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        result = payload.get("result") if isinstance(payload, dict) else None
        version = result.get("version") if isinstance(result, dict) else None
        return str(version) if version else None

    def _internal_rpc(self, secret: str, method: str, *params: object) -> object:
        body = json.dumps({
            "jsonrpc": "2.0",
            "id": "aria2-recovery-coordinator",
            "method": f"aria2.{method}",
            "params": [f"token:{secret}", *params],
        }).encode("utf-8")
        request = Request(
            self.rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with RPC_OPENER.open(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict) or "error" in payload:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            raise RuntimeError(str(error.get("message") or "Aria2 RPC failed."))
        return payload.get("result")


def _safe_global_options(raw_options: dict[str, Any]) -> tuple[dict[str, str] | None, str]:
    options: dict[str, str] = {}
    for raw_key, raw_value in raw_options.items():
        key = str(raw_key)
        value = str(raw_value)
        if key not in SAFE_GLOBAL_OPTIONS:
            return None, "Only safe transfer settings can be changed."
        if key in {"max-concurrent-downloads", "max-connection-per-server", "split", "retry-wait", "timeout", "connect-timeout"}:
            try:
                parsed = int(value)
            except ValueError:
                return None, "Transfer setting value is invalid."
            bounds = {
                "max-concurrent-downloads": (1, 20),
                "max-connection-per-server": (1, 16),
                "split": (1, 32),
                "retry-wait": (0, 3600),
                "timeout": (1, 600),
                "connect-timeout": (1, 60),
            }[key]
            if not bounds[0] <= parsed <= bounds[1]:
                return None, "Transfer setting value is outside the supported range."
            value = str(parsed)
        elif key in {"max-overall-download-limit", "max-overall-upload-limit", "disk-cache"}:
            if not re.fullmatch(r"\d+(?:[KMG])?", value, re.IGNORECASE):
                return None, "Transfer limit format is invalid."
            numeric = int(re.match(r"\d+", value).group(0))
            suffix = value[-1:].upper() if value[-1:].isalpha() else ""
            bytes_value = numeric * {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[suffix]
            maximum = 512 * 1024**2 if key == "disk-cache" else 1024**3
            if bytes_value > maximum:
                return None, "Transfer limit exceeds the supported maximum."
            value = str(bytes_value)
        elif key == "file-allocation" and value not in {"none", "prealloc", "trunc", "falloc"}:
            return None, "File allocation mode is unsupported."
        options[key] = value
    if not options:
        return None, "At least one transfer setting is required."
    return options, ""


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _redact_aria2_proxy_options(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact_aria2_proxy_options(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_aria2_proxy_options(item)
            for key, item in value.items()
            if key not in {"all-proxy", "all-proxy-user", "all-proxy-passwd"}
        }
    if isinstance(value, str):
        return redact_sensitive_urls_in_text(value)
    return value


def main() -> int:
    state_root = Path(os.environ.get("ARIA2_STATE_ROOT", "/state"))
    workspace_root = Path(os.environ.get("UTILITY_WORKSPACE_ROOT", "/workspace"))
    hook_path = Path(
        os.environ.get("ARIA2_HOOK_PATH", str(DEFAULT_HOOK_PATH))
    )
    rpc_url = os.environ.get("ARIA2_RPC_URL", DEFAULT_RPC_URL)
    runtime = Aria2Runtime(
        state_root=state_root,
        workspace_root=workspace_root,
        hook_script_path=hook_path,
        rpc_url=rpc_url,
    )
    if len(sys.argv) > 1 and sys.argv[1] == "healthcheck":
        return 0 if runtime.health()["ready"] else 1
    runtime.run()
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())
