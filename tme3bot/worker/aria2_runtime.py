"""Own the per-worker aria2 configuration and expose safe health information."""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from tme3bot.database_paths import ensure_private_directory


DEFAULT_RPC_URL = "http://aria2:6800/jsonrpc"
DEFAULT_HOOK_PATH = Path("/usr/local/bin/aria2-retry-on-low-speed.py")
RPC_OPENER = build_opener(ProxyHandler({}))


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
        self.session_file = self.state_root / "aria2.session"
        self.hook_status_file = self.state_root / "aria2-hook-status.json"

    def ensure(self) -> None:
        ensure_private_directory(self.state_root)
        root = self.workspace_root.resolve(strict=True)
        self.download_root.mkdir(mode=0o755, parents=True, exist_ok=True)
        destination = self.download_root.resolve(strict=True)
        if not destination.is_relative_to(root):
            raise ValueError("Aria2 destination must stay within Workspace.")

        secret = self._ensure_secret()
        if not self.session_file.exists():
            self._write_private(self.session_file, "")
        self._write_private(self.config_file, self._config_text(secret))

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
        }

    def run(self) -> None:
        self.ensure()
        os.execvp("aria2c", ["aria2c", f"--conf-path={self.config_file}", "--daemon=false"])

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

    def _config_text(self, secret: str) -> str:
        managed = {
            "dir": str(self.download_root),
            "enable-rpc": "true",
            "rpc-listen-port": "6800",
            "rpc-listen-all": "true",
            "rpc-secret": secret,
            "rpc-allow-origin-all": "false",
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
            "lowest-speed-limit": "102400",
            "max-tries": "0",
            "on-download-error": str(self.hook_script_path),
            "enable-dht": "true",
            "enable-dht6": "false",
            "listen-port": "6881-6999",
            "dht-listen-port": "6881-6999",
            "follow-torrent": "true",
        }
        existing = self._read_config()
        # Preserve operator-selected transfer settings while keeping service,
        # RPC, path, session, and hook settings owned by this runtime.
        for key in ("lowest-speed-limit", "max-concurrent-downloads", "disk-cache"):
            if existing.get(key):
                managed[key] = existing[key]
        return "# aria2 configuration managed by tme3bot\n" + "".join(
            f"{key}={value}\n" for key, value in managed.items()
        )

    @staticmethod
    def _write_private(path: Path, value: str) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(value)
        path.chmod(0o600)

    def _probe_version(self, secret: str) -> str | None:
        if not secret:
            return None
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "worker-health",
                "method": "aria2.getVersion",
                "params": [f"token:{secret}"],
            }
        ).encode("utf-8")
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
