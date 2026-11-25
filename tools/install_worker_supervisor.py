from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tme3bot.worker.supervisor import FIXED_TARGETS
from tme3bot.worker.supervisor_auth import derive_supervisor_token


SYSTEMD_TEMPLATE = """[Unit]
Description=TME3Bot fixed-target Docker worker supervisor (%i)
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=root
Group=root
ExecStart=/usr/bin/python3 /usr/local/libexec/tme3bot/worker_supervisor.py run --config /etc/tme3bot/worker-supervisor/%i.json
Restart=always
RestartSec=5
UMask=0077
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true
ReadWritePaths=/var/lib/tme3bot/worker-supervisor

[Install]
WantedBy=multi-user.target
"""


def _read_worker_token(path: Path) -> str:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith("WORKER_API_TOKEN="):
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not value or "\n" in value or "\r" in value:
            break
        return value
    raise ValueError("WORKER_API_TOKEN is missing from the selected worker env file.")


def _docker_target(
    root: Path,
    compose_file: Path,
    service: str,
    compose_env_file: str = "",
) -> tuple[str, str]:
    compose = ["docker", "compose"]
    if compose_env_file:
        compose.extend(["--env-file", compose_env_file])
    listed = subprocess.run(
        [*compose, "-f", str(compose_file), "ps", "-aq", service],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if listed.returncode != 0:
        raise RuntimeError("Docker Compose could not inspect the expected worker service.")
    container_id = next((line.strip() for line in listed.stdout.splitlines() if line.strip()), "")
    if not container_id:
        raise RuntimeError("Expected worker container was not found; start the intended Compose service first.")
    inspected = subprocess.run(
        ["docker", "inspect", container_id],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if inspected.returncode != 0:
        raise RuntimeError("Docker could not inspect the expected worker container.")
    payload = json.loads(inspected.stdout)
    container = payload[0] if isinstance(payload, list) and payload else {}
    labels = ((container.get("Config") or {}).get("Labels") or {})
    project = str(labels.get("com.docker.compose.project") or "")
    working_dir = str(labels.get("com.docker.compose.project.working_dir") or "")
    actual_service = str(labels.get("com.docker.compose.service") or "")
    if (
        not project
        or Path(working_dir).resolve() != root.resolve()
        or actual_service != service
    ):
        raise RuntimeError("Worker Compose labels do not match the fixed host mapping.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project):
        raise RuntimeError("Worker Compose project label is invalid.")
    return project, container_id


def _atomic_private_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".worker-supervisor-", dir=str(path.parent))
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def install(worker: str, gateway_url: str, worker_env: Path | None = None) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("Run this installer as root on the Docker host.")
    name = str(worker or "").strip().lower()
    target = FIXED_TARGETS.get(name)
    if target is None:
        raise ValueError("Worker is not in the fixed host allowlist.")
    root = Path(target["compose_root"])
    compose_file = root / target["compose_file"]
    if not root.is_dir() or not compose_file.is_file():
        raise RuntimeError("The fixed Compose checkout or file is missing on this host.")
    if worker_env is None:
        default_env = target.get("worker_env_file") or str(root / ".env.worker")
        worker_env = Path(default_env)
    worker_env = worker_env.resolve()
    expected_worker_env = Path(
        target.get("worker_env_file") or str(root / ".env.worker")
    ).resolve()
    if worker_env != expected_worker_env or not worker_env.is_file():
        raise RuntimeError("Worker env file must match the fixed host mapping.")
    worker_token = _read_worker_token(worker_env)
    token = derive_supervisor_token(name, worker_token)
    del worker_token
    project, _container_id = _docker_target(
        root,
        compose_file,
        target["service"],
        str(target.get("compose_env_file") or ""),
    )

    origin = str(gateway_url or "").strip().rstrip("/")
    if not origin.startswith("https://") and not (
        name == "local" and origin.startswith("http://127.0.0.1")
    ):
        raise ValueError("Use the gateway HTTPS origin; worker-local may use host loopback.")

    config = {
        "worker": name,
        **target,
        "project": project,
        "gateway_url": origin,
        "token_file": f"/etc/tme3bot/worker-supervisor/{name}.token",
        "state_file": f"/var/lib/tme3bot/worker-supervisor/{name}.json",
        "poll_interval_seconds": 3,
    }
    config_path = Path(f"/etc/tme3bot/worker-supervisor/{name}.json")
    token_path = Path(config["token_file"])
    _atomic_private_write(config_path, json.dumps(config, separators=(",", ":")).encode("utf-8"))
    _atomic_private_write(token_path, (token + "\n").encode("utf-8"))

    runtime_destination = Path("/usr/local/libexec/tme3bot/worker_supervisor.py")
    runtime_destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    source_runtime = Path(__file__).resolve().parent.parent / "tme3bot" / "worker" / "supervisor.py"
    shutil.copyfile(source_runtime, runtime_destination)
    os.chmod(runtime_destination, 0o755)
    unit_path = Path("/etc/systemd/system/tme3bot-worker-supervisor@.service")
    unit_path.write_text(SYSTEMD_TEMPLATE, encoding="utf-8")
    os.chmod(unit_path, 0o644)
    state_dir = Path("/var/lib/tme3bot/worker-supervisor")
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    for command in (
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable", "--now", f"tme3bot-worker-supervisor@{name}.service"],
    ):
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"systemd operation failed: {command[1]}")
    print(f"Worker supervisor installed and enabled for {name} (Compose project {project}).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the fixed-target TME3Bot worker supervisor")
    parser.add_argument("--worker", required=True, choices=sorted(FIXED_TARGETS))
    parser.add_argument("--gateway-url", required=True)
    parser.add_argument("--worker-env", type=Path)
    args = parser.parse_args()
    try:
        install(args.worker, args.gateway_url, args.worker_env)
    except Exception as exc:
        print(f"Supervisor install failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
