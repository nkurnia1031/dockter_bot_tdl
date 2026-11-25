from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


LOGGER = logging.getLogger("tme3bot.worker.supervisor")
FIXED_TARGETS = {
    "local": {
        "compose_root": "/www/wwwroot/dockter_bot_tdl",
        "compose_file": "docker-compose.gateway.yml",
        "service": "worker-local",
    },
    "remote-1": {
        "compose_root": "/www/wwwroot/downloads/bot",
        "compose_file": "docker-compose.worker.yml",
        "service": "worker",
    },
    "remote-2": {
        "compose_root": "/www/wwwroot/dockter_bot_tdl",
        "compose_file": "docker-compose.worker.yml",
        "service": "worker",
    },
}
_OPERATION_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,80}$")
_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def _now_iso(clock: Callable[[], datetime]) -> str:
    current = clock()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def validate_supervisor_config(config: dict[str, Any]) -> dict[str, str]:
    if not isinstance(config, dict):
        raise ValueError("Supervisor configuration must be an object.")
    worker = str(config.get("worker") or "").strip().lower()
    target = FIXED_TARGETS.get(worker)
    if target is None:
        raise ValueError("Worker is not in the fixed supervisor allowlist.")
    for key, expected in target.items():
        if str(config.get(key) or "") != expected:
            raise ValueError("Supervisor target does not match the fixed Compose allowlist.")
    project = str(config.get("project") or "").strip()
    if not _PROJECT_RE.fullmatch(project):
        raise ValueError("Compose project label is invalid.")
    return {"worker": worker, **target, "project": project}


class WorkerSupervisor:
    """Execute only the fixed, local Compose worker restart operation."""

    def __init__(
        self,
        config: dict[str, Any],
        api,
        docker,
        state_path: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
        min_restart_interval_seconds: int = 120,
    ) -> None:
        self.target = validate_supervisor_config(config)
        self.api = api
        self.docker = docker
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.min_restart_interval_seconds = max(30, int(min_restart_interval_seconds))

    def _read_state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"last_restart_at": "", "operations": {}}
        if not isinstance(payload, dict):
            return {"last_restart_at": "", "operations": {}}
        operations = payload.get("operations")
        return {
            "last_restart_at": str(payload.get("last_restart_at") or ""),
            "operations": operations if isinstance(operations, dict) else {},
        }

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=".worker-supervisor-", dir=str(self.state_path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, self.state_path)
            try:
                os.chmod(self.state_path, 0o600)
            except OSError:
                pass
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _safe_result(
        *,
        container_stopped: bool,
        container_running: bool,
        restart_succeeded: bool,
        failure_code: str = "",
    ) -> dict[str, Any]:
        return {
            "container_stopped": bool(container_stopped),
            "container_running": bool(container_running),
            "restart_succeeded": bool(restart_succeeded),
            "failure_code": str(failure_code or "")[:64],
        }

    def _persist_result(
        self, state: dict[str, Any], operation_id: str, result: dict[str, Any]
    ) -> None:
        operations = state.setdefault("operations", {})
        operations[operation_id] = {
            "phase": "complete",
            "result": result,
            "report_pending": True,
        }
        while len(operations) > 16:
            oldest = next(iter(operations))
            if oldest == operation_id:
                break
            operations.pop(oldest, None)
        self._write_state(state)

    def _report_saved_result(self, state: dict[str, Any], operation_id: str) -> bool:
        entry = state.get("operations", {}).get(operation_id)
        if not isinstance(entry, dict) or entry.get("phase") != "complete":
            return False
        result = entry.get("result")
        if not isinstance(result, dict):
            return False
        try:
            self.api.report(operation_id, result)
        except Exception as exc:
            LOGGER.warning("Worker restart result report deferred (%s).", type(exc).__name__)
            entry["report_pending"] = True
            self._write_state(state)
            return False
        entry["report_pending"] = False
        self._write_state(state)
        return True

    def _rate_limited(self, state: dict[str, Any]) -> bool:
        previous = _parse_time(str(state.get("last_restart_at") or ""))
        if previous is None:
            return False
        current = self.clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return (current - previous).total_seconds() < self.min_restart_interval_seconds

    def _perform_restart(self, state: dict[str, Any], operation_id: str) -> dict[str, Any]:
        if self._rate_limited(state):
            try:
                running = bool(self.docker.is_running())
            except Exception:
                running = False
            return self._safe_result(
                container_stopped=False,
                container_running=running,
                restart_succeeded=False,
                failure_code="RESTART_RATE_LIMITED",
            )
        try:
            self.docker.validate_target()
        except Exception as exc:
            LOGGER.warning("Worker restart target validation failed (%s).", type(exc).__name__)
            return self._safe_result(
                container_stopped=False,
                container_running=False,
                restart_succeeded=False,
                failure_code="COMPOSE_TARGET_INVALID",
            )

        state.setdefault("operations", {})[operation_id] = {"phase": "stopping"}
        self._write_state(state)
        try:
            stopped = bool(self.docker.stop())
        except Exception as exc:
            LOGGER.warning("Worker Compose stop failed (%s).", type(exc).__name__)
            stopped = False
        if not stopped:
            try:
                still_running = bool(self.docker.is_running())
            except Exception:
                still_running = True
            if still_running:
                return self._safe_result(
                    container_stopped=False,
                    container_running=True,
                    restart_succeeded=False,
                    failure_code="COMPOSE_STOP_FAILED",
                )
            # Docker may have stopped the container even if the CLI timed out
            # or returned an error. Confirmed stopped state must be recovered.
        return self._start_after_confirmed_stop(state, operation_id)

    def _start_after_confirmed_stop(
        self, state: dict[str, Any], operation_id: str
    ) -> dict[str, Any]:
        state["last_restart_at"] = _now_iso(self.clock)
        state["operations"][operation_id] = {"phase": "stopped", "container_stopped": True}
        self._write_state(state)
        try:
            started = bool(self.docker.start())
        except Exception as exc:
            LOGGER.warning("Worker Compose start failed (%s).", type(exc).__name__)
            started = False
        try:
            running = bool(self.docker.is_running())
        except Exception:
            running = False
        success = started and running
        return self._safe_result(
            container_stopped=True,
            container_running=running,
            restart_succeeded=success,
            failure_code="" if success else "COMPOSE_START_FAILED",
        )

    def _recover_interrupted_restart(
        self, state: dict[str, Any], operation_id: str
    ) -> dict[str, Any]:
        entry = state.get("operations", {}).get(operation_id)
        if not isinstance(entry, dict):
            return self._perform_restart(state, operation_id)
        phase = str(entry.get("phase") or "")
        if phase == "stopped" and entry.get("container_stopped") is True:
            try:
                running = bool(self.docker.is_running())
            except Exception:
                running = False
            if not running:
                try:
                    started = bool(self.docker.start())
                except Exception:
                    started = False
                try:
                    running = bool(self.docker.is_running())
                except Exception:
                    running = False
            else:
                started = True
            success = started and running
            return self._safe_result(
                container_stopped=True,
                container_running=running,
                restart_succeeded=success,
                failure_code="" if success else "COMPOSE_START_FAILED",
            )
        if phase == "stopping":
            try:
                running = bool(self.docker.is_running())
            except Exception:
                running = True
            if not running:
                return self._start_after_confirmed_stop(state, operation_id)
            # The previous process died before proving Docker stopped the
            # worker. The service is still running, so retry this idempotent
            # fixed-target stop once and persist the confirmed transition.
            try:
                stopped = bool(self.docker.stop())
            except Exception:
                stopped = False
            if stopped:
                return self._start_after_confirmed_stop(state, operation_id)
            try:
                running = bool(self.docker.is_running())
            except Exception:
                running = True
            if not running:
                return self._start_after_confirmed_stop(state, operation_id)
            return self._safe_result(
                container_stopped=False,
                container_running=True,
                restart_succeeded=False,
                failure_code="COMPOSE_STOP_FAILED",
            )
        # A crash during docker stop leaves the exact stop outcome uncertain.
        # Do not issue a second disruptive stop or claim jobs were interrupted.
        return self._safe_result(
            container_stopped=False,
            container_running=self._is_running_safely(),
            restart_succeeded=False,
            failure_code="RESTART_OUTCOME_UNKNOWN",
        )

    def _is_running_safely(self) -> bool:
        try:
            return bool(self.docker.is_running())
        except Exception:
            return False

    def run_once(self) -> dict[str, Any] | None:
        state = self._read_state()
        for operation_id, entry in list(state.get("operations", {}).items()):
            if isinstance(entry, dict) and entry.get("report_pending") is True:
                self._report_saved_result(state, str(operation_id))
        response = self.api.poll()
        command = response.get("command") if isinstance(response, dict) else None
        if not isinstance(command, dict):
            return None
        operation_id = str(command.get("operation_id") or "")
        if (
            command.get("action") != "restart_worker"
            or not _OPERATION_ID_RE.fullmatch(operation_id)
            or command.get("idempotency_key") != operation_id
        ):
            LOGGER.error("Rejected unknown worker supervisor command.")
            return None

        existing = state.get("operations", {}).get(operation_id)
        if isinstance(existing, dict) and existing.get("phase") == "complete":
            self._report_saved_result(state, operation_id)
            return existing.get("result")
        if isinstance(existing, dict):
            result = self._recover_interrupted_restart(state, operation_id)
        else:
            result = self._perform_restart(state, operation_id)
        self._persist_result(state, operation_id, result)
        self._report_saved_result(state, operation_id)
        return result


class DockerComposeWorkerAdapter:
    def __init__(self, target: dict[str, str], *, timeout_seconds: int = 45) -> None:
        self.target = validate_supervisor_config(target)
        self.timeout_seconds = max(10, int(timeout_seconds))
        self.compose_path = Path(self.target["compose_root"]) / self.target["compose_file"]

    def _run(self, args: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=self.target["compose_root"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout or self.timeout_seconds,
        )

    def validate_target(self) -> None:
        if not self.compose_path.is_file():
            raise RuntimeError("Expected Compose file is missing.")
        listed = self._run([
            "docker", "compose", "-p", self.target["project"], "-f",
            str(self.compose_path), "ps", "-aq", self.target["service"],
        ])
        if listed.returncode != 0:
            raise RuntimeError("Compose could not inspect the fixed service.")
        container_id = next((line.strip() for line in listed.stdout.splitlines() if line.strip()), "")
        if not container_id:
            raise RuntimeError("The fixed worker container does not exist.")
        inspected = self._run(["docker", "inspect", container_id])
        if inspected.returncode != 0:
            raise RuntimeError("Docker could not inspect the fixed worker container.")
        payload = json.loads(inspected.stdout)
        container = payload[0] if isinstance(payload, list) and payload else {}
        labels = ((container.get("Config") or {}).get("Labels") or {})
        actual = {
            "project": str(labels.get("com.docker.compose.project") or ""),
            "working_dir": str(labels.get("com.docker.compose.project.working_dir") or ""),
            "service": str(labels.get("com.docker.compose.service") or ""),
        }
        if (
            actual["project"] != self.target["project"]
            or Path(actual["working_dir"]).resolve() != Path(self.target["compose_root"]).resolve()
            or actual["service"] != self.target["service"]
        ):
            raise RuntimeError("Docker labels do not match the installed fixed target.")

    def stop(self) -> bool:
        result = self._run([
            "docker", "compose", "-p", self.target["project"], "-f",
            str(self.compose_path), "stop", "--timeout", "15", self.target["service"],
        ])
        return result.returncode == 0

    def start(self) -> bool:
        result = self._run([
            "docker", "compose", "-p", self.target["project"], "-f",
            str(self.compose_path), "start", self.target["service"],
        ])
        return result.returncode == 0

    def is_running(self) -> bool:
        listed = self._run([
            "docker", "compose", "-p", self.target["project"], "-f",
            str(self.compose_path), "ps", "-q", self.target["service"],
        ])
        container_id = next((line.strip() for line in listed.stdout.splitlines() if line.strip()), "")
        if listed.returncode != 0 or not container_id:
            return False
        inspected = self._run([
            "docker", "inspect", "--format", "{{.State.Running}}", container_id,
        ])
        return inspected.returncode == 0 and inspected.stdout.strip().lower() == "true"


class SupervisorApiClient:
    def __init__(self, config: dict[str, Any], token_file: Path | str, *, timeout: int = 12) -> None:
        self.target = validate_supervisor_config(config)
        self.worker = self.target["worker"]
        self.origin = str(config.get("gateway_url") or "").strip().rstrip("/")
        if not self.origin.startswith("https://") and not (
            self.worker == "local" and self.origin.startswith("http://127.0.0.1")
        ):
            raise ValueError("Gateway URL must use HTTPS, except loopback for worker-local.")
        self.token_file = Path(token_file)
        self.timeout = max(3, min(30, int(timeout)))

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self.token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError("Supervisor token file is empty.")
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.origin + path,
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "X-Worker-Token": token,
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(64 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Gateway supervisor endpoint returned HTTP {exc.code}.") from None
        if len(raw) > 64 * 1024:
            raise RuntimeError("Gateway supervisor response exceeded the size limit.")
        value = json.loads(raw or b"{}")
        if not isinstance(value, dict):
            raise RuntimeError("Gateway supervisor response is invalid.")
        return value

    def poll(self) -> dict[str, Any]:
        return self._request(
            "GET", f"/internal/v1/worker-supervisors/{self.worker}/commands/next"
        )

    def report(self, operation_id: str, result: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/internal/v1/worker-supervisors/{self.worker}/operations/{operation_id}/result",
            result,
        )


def load_config(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    target = validate_supervisor_config(payload)
    payload.update(target)
    token_file = Path(str(payload.get("token_file") or ""))
    if not token_file.is_absolute() or not token_file.is_file():
        raise ValueError("Supervisor token file is missing.")
    if os.name == "posix" and token_file.stat().st_mode & 0o077:
        raise ValueError("Supervisor token file must be private to root.")
    return payload


def run_daemon(config_path: Path | str) -> None:
    config = load_config(config_path)
    api = SupervisorApiClient(config, config["token_file"])
    docker = DockerComposeWorkerAdapter(config)
    supervisor = WorkerSupervisor(
        config,
        api,
        docker,
        str(config.get("state_file") or "/var/lib/tme3bot/worker-supervisor/state.json"),
    )
    interval = max(1.0, min(15.0, float(config.get("poll_interval_seconds") or 3)))
    while True:
        try:
            supervisor.run_once()
        except Exception as exc:
            LOGGER.warning("Worker supervisor poll deferred (%s).", type(exc).__name__)
        time.sleep(interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fixed-target TME3Bot worker Docker supervisor")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--config", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_daemon(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
