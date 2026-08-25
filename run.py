#!/usr/bin/env python3
from __future__ import annotations

import os
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tarfile
import hashlib
import urllib.request
from getpass import getpass
from pathlib import Path

try:
    from tme3bot.infrastructure.http_client import request_json
    from tme3bot.names import normalize_profile_name
except ModuleNotFoundError:  # First-run bootstrap before Python dependencies exist.
    request_json = None  # type: ignore[assignment]
    normalize_profile_name = None  # type: ignore[assignment]


PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
LEGACY_ENV_FILE = PROJECT_DIR / "env"
USAGE = """Usage: python3 run.py <command>

Commands:
  check         Check/install tools, Git state, base image, and published images
  up            Build if needed, start container in background, then show status
  start         Alias for up
  build         Build image only
  build-base    Build the Go/tdl/Python base image once and create base-migrate.zip
  migrate       Build split images elsewhere and create migrate.zip for Oracle
  worker list   List workers registered in the gateway data volume
  worker add <name> <url> [token]   Register/update a worker without rebuilding
  worker remove <name>              Remove a worker registration
  backup now                        Create encrypted backups for gateway and workers
  backup list                       List recorded backup runs
  backup status                     Show backup status
  update        Rebuild with cache, reuse host tdl, recreate running container
  deploy [gateway|worker] [--pull]  Deploy; use --pull on low-memory targets
  deploy web [--rollback]           Install static UI release; no Node/Docker build
  publish [gateway|worker|--all] [--build-base]  Build locally and push images
  cleanup       Remove dangling local Docker images left by rebuilds
  clean         Alias for cleanup
  restart       Restart the bot container
  stop          Stop the bot container
  down          Stop and remove the bot container, keep mounted PROFILE_ROOT data
  logs          Follow docker logs, including realtime tdl output
  status        Show compose service status
  shell         Open a shell as root inside the container
  add-profile <profile>    Create profile directories and permissions only
  add_profil <profile>     Alias for add-profile
  identity <profile>      Read the profile's TDL session identity into identity.json
  login-root [profile]     Deprecated alias: prepare download session directory
  login-export [profile]   Deprecated alias: prepare export session directory
  help          Show this help

Notes:
  - Data lives in PROFILE_ROOT mounted to /data.
  - Set COMPOSE_FILE to docker-compose.gateway.yml or docker-compose.worker.yml for split deployments.
  - update/down will not remove .tdl, download, exports, or state.json.
  - Builds prefer the host tdl binary and use a fixed fallback when unavailable.
  - cleanup keeps tagged images and images used by containers.
  - For updateable deploys, edit code, then run: python3 run.py update
"""


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    env = load_env_file()

    try:
        if action in {"help", "-h", "--help"}:
            print(USAGE)
            return 0
        if action == "check":
            bootstrap_python_dependencies(env, install="--no-install" not in sys.argv[2:])
            preflight = preflight_report(env, install="--no-install" not in sys.argv[2:])
            print_preflight_report(preflight)
            return int(preflight.get("exit_code", 0))
        if action in {"up", "start"}:
            ensure_profile_root(env)
            ensure_base_image_available(env)
            prepare_tdl_build_asset(env)
            run_compose(["up", "-d", "--build"], env)
            run_compose(["ps"], env)
            return 0
        if action == "build":
            require_env_file()
            ensure_base_image_available(env)
            prepare_tdl_build_asset(env)
            run_compose(["build"], env)
            return 0
        if action in {"build-base", "base"}:
            build_base_image(env)
            return 0
        if action == "migrate":
            migrate_images(env)
            return 0
        if action == "worker":
            manage_workers(env, sys.argv[2:])
            return 0
        if action == "backup":
            manage_backup(env, sys.argv[2:])
            return 0
        if action == "update":
            ensure_profile_root(env)
            ensure_base_image_available(env)
            prepare_tdl_build_asset(env)
            run_compose(["build"], env)
            run_compose(["up", "-d", "--remove-orphans"], env)
            run_compose(["ps"], env)
            return 0
        if action == "deploy":
            if len(sys.argv) > 2 and sys.argv[2].strip().lower() == "web":
                deploy_web(env, sys.argv[3:])
                return 0
            if len(sys.argv) == 2 or sys.argv[2].startswith("--"):
                deploy_all(env, sys.argv[2:])
                return 0
            deploy_application(env, sys.argv[2:])
            return 0
        if action == "publish":
            publish_application(env, sys.argv[2:])
            return 0
        if action in {"cleanup", "clean"}:
            run_docker(["image", "prune", "--force"], env)
            return 0
        if action == "restart":
            require_env_file()
            args = ["restart"]
            if service := configured_service(env):
                args.append(service)
            run_compose(args, env)
            return 0
        if action == "stop":
            require_env_file()
            args = ["stop"]
            if service := configured_service(env):
                args.append(service)
            run_compose(args, env)
            return 0
        if action == "down":
            require_env_file()
            run_compose(["down"], env)
            return 0
        if action == "logs":
            require_env_file()
            args = ["logs", "-f"]
            if service := configured_service(env):
                args.append(service)
            run_compose(args, env)
            return 0
        if action == "status":
            require_env_file()
            run_compose(["ps"], env)
            return 0
        if action == "shell":
            require_env_file()
            run_compose(["exec", shell_service(env), "bash"], env)
            return 0
        if action in {"add-profile", "add_profil"}:
            ensure_profile_root(env)
            add_profile(env, sys.argv[2] if len(sys.argv) > 2 else None)
            return 0
        if action == "identity":
            ensure_profile_root(env)
            write_profile_identity(env, sys.argv[2] if len(sys.argv) > 2 else None)
            return 0
        if action == "login-root":
            ensure_profile_root(env)
            add_profile(env, sys.argv[2] if len(sys.argv) > 2 else None)
            return 0
        if action == "login-export":
            ensure_profile_root(env)
            add_profile(env, sys.argv[2] if len(sys.argv) > 2 else None)
            return 0

        print(f"Command tidak dikenal: {action}", file=sys.stderr)
        print(USAGE)
        return 1
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def bootstrap_python_dependencies(env: dict[str, str], *, install: bool) -> None:
    """Install this CLI's Python dependencies when a VPS is truly new."""
    global request_json, normalize_profile_name
    if _python_requirements_ready():
        return
    requirements = PROJECT_DIR / "requirements.txt"
    if not install:
        raise RuntimeError(
            f"Python dependency belum tersedia. Jalankan python -m pip install -r {requirements}."
        )
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            cwd=PROJECT_DIR,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        if not sys.platform.startswith("linux"):
            raise RuntimeError("pip belum tersedia untuk memasang requirements Python.")
        subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], check=True)
    pip = [sys.executable, "-m", "pip", "install", "-r", str(requirements)]
    print("$ " + shlex.join(pip))
    try:
        subprocess.run(pip, cwd=PROJECT_DIR, check=True)
    except subprocess.CalledProcessError:
        # Debian/Ubuntu may provide packages through dpkg. Those packages do
        # not always contain a pip RECORD file, so pip cannot uninstall them
        # when requirements pins a newer version (notably PyJWT). Retry only
        # for the system interpreter and install over the distro package
        # instead of removing files owned by apt.
        if not _system_python_install_fallback_available():
            raise
        fallback = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--ignore-installed",
        ]
        if _pip_supports_flag("--break-system-packages"):
            fallback.append("--break-system-packages")
        fallback.extend(["-r", str(requirements)])
        print(
            "Instalasi pip normal gagal; menghindari uninstall paket Debian "
            "dan mencoba instalasi system-safe: " + shlex.join(fallback)
        )
        subprocess.run(fallback, cwd=PROJECT_DIR, check=True)
    from tme3bot.infrastructure.http_client import request_json as imported_request_json
    from tme3bot.names import normalize_profile_name as imported_normalize_profile_name

    request_json = imported_request_json
    normalize_profile_name = imported_normalize_profile_name


def _system_python_install_fallback_available() -> bool:
    """Return whether it is safe to use the Debian-package fallback.

    The fallback is deliberately limited to a Linux system interpreter. A
    virtualenv already owns its site-packages and should keep normal pip
    uninstall/upgrade semantics instead.
    """

    return sys.platform.startswith("linux") and sys.prefix == sys.base_prefix


def _pip_supports_flag(flag: str) -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--help"],
            cwd=PROJECT_DIR,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return flag in (result.stdout or "") or flag in (result.stderr or "")


def _python_requirements_ready() -> bool:
    try:
        import dotenv  # noqa: F401
        import fastapi  # noqa: F401
        import pydantic  # noqa: F401
        import telegram  # noqa: F401
        import jwt  # noqa: F401
    except ImportError:
        return False
    return request_json is not None and normalize_profile_name is not None


def _command_available(command: str) -> bool:
    return shutil.which(command) is not None


def _compose_available() -> bool:
    docker = shutil.which("docker")
    if not docker:
        return False
    try:
        return subprocess.run(
            [docker, "compose", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
    except OSError:
        return False


def _legacy_compose_available() -> bool:
    return shutil.which("docker-compose") is not None


def install_missing_tools(missing: list[str]) -> list[str]:
    """Best-effort Linux bootstrap; return tools still unavailable."""
    if not missing:
        return []
    if not sys.platform.startswith("linux"):
        return missing
    package_manager = shutil.which("apt-get")
    if not package_manager:
        return missing
    packages = {
        "git": "git",
        "docker": "docker.io",
        "docker compose": "docker-compose-plugin",
        "curl": "curl",
        "7z": "p7zip-full",
        "tar": "tar",
        "openssl": "openssl",
    }
    requested = [packages[item] for item in missing if item in packages]
    if not requested:
        return missing
    prefix: list[str] = []
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        if not shutil.which("sudo"):
            return missing
        prefix = ["sudo"]
    subprocess.run(prefix + [package_manager, "update"], check=True)
    try:
        subprocess.run(
            prefix + [package_manager, "install", "-y", *requested], check=True
        )
    except subprocess.CalledProcessError:
        # Some Oracle/Ubuntu images do not expose docker-compose-plugin in the
        # enabled repositories. docker-compose is a compatible fallback for
        # this CLI and lets the operator continue without manual guesswork.
        if "docker-compose-plugin" not in requested:
            raise
        fallback = [item for item in requested if item != "docker-compose-plugin"]
        fallback.append("docker-compose")
        subprocess.run(
            prefix + [package_manager, "install", "-y", *fallback], check=True
        )
    if shutil.which("systemctl") and shutil.which("docker"):
        subprocess.run(
            ["systemctl", "enable", "--now", "docker"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return [
        item
        for item in missing
        if not (
            (_compose_available() or _legacy_compose_available())
            if item == "docker compose"
            else _command_available(item)
        )
    ]


def preflight_report(env: dict[str, str], *, install: bool) -> dict[str, object]:
    tools = ["git", "docker", "docker compose", "curl", "tar", "openssl"]
    if env.get("REQUIRE_7Z_HOST", "false").strip().lower() in {"1", "true", "yes"}:
        tools.append("7z")
    missing = [
        item
        for item in tools
        if not (
            (_compose_available() or _legacy_compose_available())
            if item == "docker compose"
            else _command_available(item)
        )
    ]
    if install and missing:
        missing = install_missing_tools(missing)

    report: dict[str, object] = {
        "tools": {item: item not in missing for item in tools},
        "missing_tools": missing,
        "git_sha": git_revision(),
        "remote_git_sha": git_remote_revision(),
        "git_clean": git_worktree_clean(),
        "base_image": None,
        "images": {},
        "exit_code": 0,
    }
    if missing:
        report["exit_code"] = 10
        return report

    try:
        require_env_file()
        if not data_root_value(env):
            raise RuntimeError(
                "PROFILE_ROOT, GATEWAY_DATA_ROOT, atau LOCAL_WORKER_DATA_ROOT belum diisi."
            )
        report["env"] = "ok"
    except RuntimeError as exc:
        report["env"] = str(exc)
        report["exit_code"] = 20

    base = configured_base_image(env)
    report["base_image"] = "READY_LOCAL" if docker_image_exists(base, env) else "MISSING"
    names = image_names_for_release(env)
    report["images"] = {
        name: image_release_status(name, report["git_sha"], env) for name in names
    }
    return report


def print_preflight_report(report: dict[str, object]) -> None:
    print("Preflight tme3bot")
    print(f"Git HEAD: {report.get('git_sha') or '-'}")
    print(f"Git remote HEAD: {report.get('remote_git_sha') or 'tidak tersedia'}")
    print(f"Worktree: {'bersih' if report.get('git_clean', True) else 'dirty'}")
    print(f"Tools missing: {', '.join(report.get('missing_tools', [])) or 'none'}")
    print(f"Environment: {report.get('env', 'not checked')}")
    print(f"Base image: {report.get('base_image') or 'not checked'}")
    images = report.get("images") or {}
    if isinstance(images, dict):
        for name, status in images.items():
            print(f"Image {name}: {status}")
    print(f"Exit code: {report.get('exit_code', 0)}")


def git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=PROJECT_DIR,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def git_worktree_clean() -> bool:
    try:
        output = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_DIR,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return True
    return not output.strip()


def git_remote_revision() -> str:
    """Read origin HEAD when credentials/network are available.

    A failed remote lookup is informational only; an immutable image tag is
    still checked against the local checkout. This keeps deploy usable on an
    offline VPS while exposing a useful stale-check when online.
    """
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            cwd=PROJECT_DIR,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or "main"
        output = subprocess.check_output(
            ["git", "ls-remote", "origin", f"refs/heads/{branch}"],
            cwd=PROJECT_DIR,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=15,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""
    return output.split()[0][:12] if output else ""


def image_names_for_release(env: dict[str, str]) -> list[str]:
    names = []
    for key, default in (
        ("GATEWAY_IMAGE_NAME", "tme3bot-gateway"),
        ("WORKER_IMAGE_NAME", "tme3bot-worker"),
    ):
        value = (env.get(key) or default).strip()
        if value and value not in names:
            names.append(value)
    if env.get("WEB_IMAGE_MODE", "").strip().lower() == "container":
        value = env.get("WEB_IMAGE_NAME", "").strip()
        if value and value not in names:
            names.append(value)
    return names


def docker_manifest_exists(image: str, tag: str, env: dict[str, str]) -> bool:
    docker_cmd = env.get("DOCKER_CMD") or os.getenv("DOCKER_CMD", "docker")
    command = shlex.split(docker_cmd) + ["manifest", "inspect", f"{image}:{tag}"]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            env=compose_env(env),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def image_release_status(image: str, revision: object, env: dict[str, str]) -> str:
    tag = str(revision or "latest")
    if docker_image_exists(f"{image}:{tag}", env):
        return "READY_LOCAL"
    if "." in image.split("/", 1)[0] and docker_manifest_exists(image, tag, env):
        return "READY_REGISTRY"
    return "MISSING"


def deploy_all(env: dict[str, str], arguments: list[str]) -> None:
    if "--status" in arguments:
        report = preflight_report(env, install=False)
        print_preflight_report(report)
        return
    bootstrap_python_dependencies(env, install=True)
    target = (env.get("DEPLOY_TARGET") or "gateway").strip().lower()
    target_env = dict(env)
    if target == "worker":
        merge_env_file(target_env, target_env.get("WORKER_ENV_FILE", ".env.worker"))
    report = preflight_report(target_env, install=True)
    print_preflight_report(report)
    if int(report.get("exit_code", 0)) != 0:
        raise RuntimeError("Preflight gagal; selesaikan masalah di atas sebelum deploy.")
    if target not in {"gateway", "worker"}:
        raise RuntimeError("DEPLOY_TARGET harus gateway atau worker.")
    image_status = report.get("images") or {}
    required_names = (
        list(image_status)
        if target == "gateway"
        else [str(target_env.get("WORKER_IMAGE_NAME") or "tme3bot-worker")]
    )
    required_statuses = [image_status.get(name, "MISSING") for name in required_names]
    if any(value == "MISSING" for value in required_statuses):
        revision = str(report.get("git_sha") or "unknown")
        raise RuntimeError(
            f"Image release {revision} belum dipublish. Jalankan di VPS builder: "
            f"python3 run.py publish --all --build-base, lalu ulangi python3 run.py deploy."
        )
    registry_ready = any(value == "READY_REGISTRY" for value in required_statuses)
    if registry_ready:
        deploy_application(target_env, [target, "--pull"])
    else:
        ensure_profile_root(target_env)
        compose_env_values = dict(target_env)
        compose_env_values["COMPOSE_FILE"] = (
            "docker-compose.gateway.yml" if target == "gateway" else "docker-compose.worker.yml"
        )
        run_compose(["up", "-d", "--remove-orphans"], compose_env_values)
        run_compose(["ps"], compose_env_values)


def require_env_file() -> None:
    if not active_env_file().exists():
        raise RuntimeError(
            ".env atau env tidak ditemukan. Buat dari .env.example lalu isi "
            "lokasi data host dan file env tiap role."
        )


def backend_management_request(
    env: dict[str, str],
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    runtime_env = dict(env)
    backend_env_name = env.get("BACKEND_ENV_FILE", ".env.backend")
    backend_env_path = Path(backend_env_name)
    if not backend_env_path.is_absolute():
        backend_env_path = PROJECT_DIR / backend_env_path
    if backend_env_path.exists():
        for raw_line in backend_env_path.read_text(encoding="utf-8-sig").splitlines():
            parsed = parse_env_line(raw_line)
            if parsed is not None:
                runtime_env.setdefault(*parsed)
    base_url = runtime_env.get("BACKEND_API_URL", "").strip().rstrip("/")
    if not base_url:
        base_url = f"http://127.0.0.1:{runtime_env.get('BACKEND_PORT', '8080')}"
    token = runtime_env.get("MANAGEMENT_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("MANAGEMENT_API_TOKEN wajib diisi.")
    return request_json(base_url, token, method, path, payload)


def manage_workers(env: dict[str, str], args: list[str]) -> None:
    command = args[0].lower() if args else "list"
    if command == "list":
        workers = backend_management_request(
            env, "GET", "/internal/v1/management/workers"
        ).get("items", [])
        if not workers:
            print("Belum ada worker terdaftar.")
            return
        for worker in workers:
            name = worker.get("name", "")
            token = worker.get("token", "")
            masked = (token[:4] + "..." + token[-4:]) if len(token) > 8 else "<set>"
            print(f"{name}\t{worker.get('url', '')}\ttoken={masked}")
        return
    if command == "add" and len(args) in {3, 4}:
        token = args[3] if len(args) == 4 else getpass("Worker API token: ")
        result = backend_management_request(
            env,
            "POST",
            "/internal/v1/management/workers",
            {"name": args[1], "url": args[2], "token": token},
        )
        name = result["name"]
        print(f"Worker tersimpan: {name}")
        return
    if command == "remove" and len(args) == 2:
        result = backend_management_request(
            env,
            "DELETE",
            f"/internal/v1/management/workers/{args[1]}",
        )
        if result.get("removed"):
            print(f"Worker dihapus: {args[1]}")
        else:
            print(f"Worker tidak ditemukan: {args[1]}")
        return
    raise RuntimeError(
        "Format: worker list | worker add <name> <url> [token] | worker remove <name>"
    )


def manage_backup(env: dict[str, str], args: list[str]) -> None:
    require_env_file()
    action = args[0].lower() if args else "status"
    if action not in {"now", "list", "status"}:
        raise RuntimeError("Format: backup now | backup list | backup status")
    if action == "now":
        result = backend_management_request(
            env, "POST", "/internal/v1/management/backups"
        )
        print(f"Backup dimulai: {result['run_id']}")
        return
    suffix = "/status" if action == "status" else ""
    result = backend_management_request(
        env, "GET", "/internal/v1/management/backups" + suffix
    )
    for item in result.get("items", []):
        print(
            f"{item.get('node_name', '-')}\t{item.get('status', '-')}\t"
            f"{item.get('started_at', '-')}\t{item.get('run_id', '-')}"
        )


def load_env_file() -> dict[str, str]:
    env_file = active_env_file()
    if not env_file.exists():
        return {}

    env: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
        parsed = parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        env[key] = value
    return env


def active_env_file() -> Path:
    configured = os.getenv("TME3BOT_ENV_FILE", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else PROJECT_DIR / path
    return ENV_FILE if ENV_FILE.exists() else LEGACY_ENV_FILE


def build_migration_archive(output: Path, image_tar: Path) -> tuple[int, int]:
    try:
        from build import build_migration_archive as package_archive
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "build.py tidak ditemukan. Ambil source terbaru lalu jalankan "
            "python3 build.py untuk membuat archive baru."
        ) from exc
    return package_archive(output, image_tar)


def build_base_archive(
    output: Path, image_tar: Path, manifest: Path | None = None
) -> tuple[int, int]:
    try:
        from build import build_base_archive as package_archive
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "build.py tidak ditemukan. Ambil source terbaru lalu jalankan "
            "python3 run.py build-base."
        ) from exc
    return package_archive(output, image_tar, manifest)


def parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export ") :].lstrip()
    if "=" not in line:
        return None

    key, value = line.split("=", 1)
    key = key.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return None
    return key, parse_env_value(value)


def parse_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""

    if value[0] in {"'", '"'}:
        quote = value[0]
        chars: list[str] = []
        escaped = False
        for char in value[1:]:
            if escaped:
                chars.append(char)
                escaped = False
                continue
            if quote == '"' and char == "\\":
                escaped = True
                continue
            if char == quote:
                break
            chars.append(char)
        return "".join(chars).strip()

    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def ensure_profile_root(env: dict[str, str]) -> Path:
    require_env_file()
    profile_root = data_root_value(env)
    if not profile_root:
        raise RuntimeError(
            "Lokasi data worker kosong/tidak terbaca di .env. Isi "
            "LOCAL_WORKER_DATA_ROOT untuk gateway atau PROFILE_ROOT untuk "
            "worker remote."
        )

    root = Path(profile_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    ensure_host_subdirs(root, env)
    print(f"Worker data root: {root}")
    return root


def ensure_host_subdirs(profile_root: Path, env: dict[str, str]) -> None:
    for key, default in {
        "DOWNLOAD_ROOT": "/data/download",
        "PROFILES_ROOT": "/data/profiles",
        "EXPORT_ROOT": "/data/exports",
        "TEMP_ROOT": "/data/tmp",
        "TDL_DOWNLOAD_HOME": "/data/root",
        "TDL_EXPORT_HOME": "/data/user1",
    }.items():
        container_path = env.get(key, default).strip() or default
        host_path = map_data_path(profile_root, container_path)
        if host_path is not None:
            host_path.mkdir(parents=True, exist_ok=True)
            if key == "DOWNLOAD_ROOT":
                (host_path / "berlabel").mkdir(parents=True, exist_ok=True)
                (host_path / "biasa").mkdir(parents=True, exist_ok=True)


def write_profile_identity(env: dict[str, str], profile_name: str | None) -> None:
    normalized = normalize_profile_name(profile_name or env.get("DEFAULT_PROFILE", "default"))
    if not normalized:
        raise RuntimeError("Nama profile tidak valid.")
    profiles_root = env.get("PROFILES_ROOT", "/data/profiles").strip() or "/data/profiles"
    if normalized == normalize_profile_name(env.get("DEFAULT_PROFILE", "default")):
        profile_root = "/data"
    else:
        profile_root = f"{profiles_root}/{normalized}"
    storage = f"{profile_root}/user1/.tdl/data"
    identity_file = f"{profile_root}/identity.json"
    namespace = env.get("TDL_EXPORT_NAMESPACE", "default").strip() or "default"
    command = [
        "exec", "-T", worker_service(env), "runuser", "-u", "user1", "--",
        env.get("LEAVE_HELPER_BINARY", "/usr/local/bin/tdl-leave"),
        "--storage", storage, "--namespace", namespace,
        "--whoami", "--identity-file", identity_file,
    ]
    run_compose(command, env)
    print(f"Identity tersimpan untuk profile {normalized}: {identity_file}")


def map_data_path(profile_root: Path, container_path: str) -> Path | None:
    normalized = container_path.replace("\\", "/")
    if normalized == "/data":
        return profile_root
    if normalized.startswith("/data/"):
        return profile_root / normalized[len("/data/") :]
    return None


def compose_base_command(dotenv: dict[str, str] | None = None) -> list[str]:
    values = dotenv or {}
    compose_cmd = values.get("COMPOSE_CMD") or os.getenv("COMPOSE_CMD", "docker compose")
    if compose_cmd.strip() == "docker compose" and not _compose_available():
        if _legacy_compose_available():
            compose_cmd = "docker-compose"
    command = shlex.split(compose_cmd)
    compose_file = values.get("COMPOSE_FILE") or os.getenv("COMPOSE_FILE", "")
    compose_file = compose_file.strip()
    for path in compose_file.split(os.pathsep):
        if path.strip():
            command.extend(["-f", path.strip()])
    return command


def configured_service(env: dict[str, str]) -> str:
    return (env.get("SERVICE_NAME") or os.getenv("SERVICE_NAME", "")).strip()


def worker_service(env: dict[str, str]) -> str:
    if service := configured_service(env):
        return service
    compose_file = (env.get("COMPOSE_FILE") or "").replace("\\", "/").lower()
    return "worker" if compose_file.endswith("docker-compose.worker.yml") else "worker-local"


def shell_service(env: dict[str, str]) -> str:
    if service := configured_service(env):
        return service
    compose_file = (env.get("COMPOSE_FILE") or "").replace("\\", "/").lower()
    return "worker" if compose_file.endswith("docker-compose.worker.yml") else "backend"


def data_root_value(env: dict[str, str]) -> str:
    return (
        env.get("PROFILE_ROOT", "").strip()
        or env.get("GATEWAY_DATA_ROOT", "").strip()
        or env.get("LOCAL_WORKER_DATA_ROOT", "").strip()
    )


def prepare_tdl_build_asset(env: dict[str, str]) -> Path | None:
    target = PROJECT_DIR / ".docker" / "tdl" / "tdl"
    target.parent.mkdir(parents=True, exist_ok=True)
    source = find_host_tdl(env)

    if source is None:
        target.unlink(missing_ok=True)
        print("tdl host tidak ditemukan; Docker akan memakai fallback tetap.")
        return None

    temporary = target.with_suffix(".tmp")
    try:
        shutil.copy2(source, temporary)
        temporary.chmod(0o755)
        temporary.replace(target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Gagal menyiapkan tdl host dari {source}: {exc}") from exc

    print(f"tdl build source: host {source}")
    return source


def find_host_tdl(env: dict[str, str]) -> Path | None:
    if not sys.platform.startswith("linux"):
        return None

    configured = env.get("TDL_HOST_BINARY", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = PROJECT_DIR / candidate
    else:
        located = shutil.which("tdl")
        if not located:
            return None
        candidate = Path(located)

    if not candidate.is_file():
        return None
    return candidate.resolve()


def compose_env(dotenv: dict[str, str]) -> dict[str, str]:
    merged = dict(os.environ)
    merged.update(dotenv)
    return merged


def run_compose(args: list[str], dotenv: dict[str, str]) -> None:
    command = compose_base_command(dotenv) + args
    print("$ " + shlex.join(command))
    subprocess.run(command, cwd=PROJECT_DIR, env=compose_env(dotenv), check=True)


def capture_compose(args: list[str], dotenv: dict[str, str]) -> str:
    command = compose_base_command(dotenv) + args
    print("$ " + shlex.join(command))
    completed = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        env=compose_env(dotenv),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def run_docker(
    args: list[str], dotenv: dict[str, str], *, stdin_text: str | None = None
) -> None:
    docker_cmd = dotenv.get("DOCKER_CMD") or os.getenv("DOCKER_CMD", "docker")
    command = shlex.split(docker_cmd) + args
    print("$ " + shlex.join(command))
    options: dict[str, object] = {
        "cwd": PROJECT_DIR,
        "env": compose_env(dotenv),
        "check": True,
    }
    if stdin_text is not None:
        options.update({"input": stdin_text, "text": True})
    subprocess.run(command, **options)


def deploy_application(
    env: dict[str, str], arguments: list[str], *, start_services: bool = True
) -> None:
    """Deploy source pulled from Git using the already-installed base image.

    The immutable Go/TDL base is deliberately never built here. Docker will
    reuse it through the Dockerfile FROM line and only rebuild the lightweight
    application layers that changed since the last deployment.
    """
    require_env_file()
    pull_only = "--pull" in arguments
    target_args = [item for item in arguments if item != "--pull"]
    target = (target_args[0].strip().lower() if target_args else "").replace("_", "-")
    if target not in {"", "gateway", "worker"}:
        raise RuntimeError("Target deploy harus gateway atau worker.")

    deploy_env = dict(env)
    # Never rely on a mutable `latest` manifest for production deployment.
    # Gateway and target use the checked-out Git revision, so they resolve the
    # exact same immutable image; the static UI is deployed separately by
    # `python3 run.py deploy web` and never participates in Docker builds.
    deploy_env["IMAGE_TAG"] = release_image_tag(deploy_env)
    if target == "gateway":
        deploy_env["COMPOSE_FILE"] = "docker-compose.gateway.yml"
    elif target == "worker":
        deploy_env["COMPOSE_FILE"] = "docker-compose.worker.yml"
        # Compose interpolation happens before env_file is loaded. Import
        # PROFILE_ROOT (and other useful defaults) so ${PROFILE_ROOT} in the
        # worker volume is valid for both build and pull deployments.
        merge_env_file(deploy_env, deploy_env.get("WORKER_ENV_FILE", ".env.worker"))

    ensure_profile_root(deploy_env)
    if pull_only:
        print("Deploy target: pull image registry, tanpa docker build.", flush=True)
        run_compose(["pull"], deploy_env)
    else:
        validate_local_base_image()
        ensure_base_image_available(deploy_env)
        prepare_tdl_build_asset(deploy_env)
        print(
            "Deploy builder: base image tidak dibangun; hanya layer aplikasi yang diperbarui.",
            flush=True,
        )
        run_compose(["build"], deploy_env)
    if not start_services:
        print("Build selesai; service tidak dijalankan karena mode publish.", flush=True)
        return
    run_compose(["up", "-d", "--remove-orphans"], deploy_env)
    run_compose(["ps"], deploy_env)


def _github_repository(env: dict[str, str]) -> str:
    configured = env.get("WEB_RELEASE_REPOSITORY", "").strip()
    if configured:
        return configured
    try:
        remote = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=PROJECT_DIR,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("WEB_RELEASE_REPOSITORY wajib diisi bila remote Git tidak tersedia.") from exc
    match = re.search(r"github\.com[/:]([^/\s]+)/([^/\s]+?)(?:\.git)?$", remote)
    if not match:
        raise RuntimeError("Remote origin bukan repository GitHub; isi WEB_RELEASE_REPOSITORY=owner/repository.")
    return f"{match.group(1)}/{match.group(2)}"


def _download(url: str, destination: Path, token: str = "", *, accept: str = "application/octet-stream") -> None:
    headers = {"Accept": accept, "User-Agent": "tme3bot-web-deploy"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def _safe_extract_tar(archive: Path, destination: Path) -> None:
    base = destination.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            if not (base / member.name).resolve().is_relative_to(base):
                raise RuntimeError("Release web berisi path tidak aman.")
        bundle.extractall(destination)


def _static_manifest(root: Path) -> list[str]:
    path = root / ".tme3bot-static-manifest.json"
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in values if isinstance(item, str) and item and not item.startswith(".")]


def _release_files(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )


def _install_static_release(source: Path, target: Path) -> None:
    """Copy only files owned by the static bundle; preserve aaPanel files."""
    target.mkdir(parents=True, exist_ok=True)
    for relative in _static_manifest(target):
        old = target / relative
        if old.is_file() or old.is_symlink():
            old.unlink(missing_ok=True)
    # Empty directories from a previous Svelte route are harmless, but stale
    # immutable assets are not useful and can consume a lot of disk space.
    shutil.rmtree(target / "_app", ignore_errors=True)
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    files = _release_files(source)
    (target / ".tme3bot-static-manifest.json").write_text(
        json.dumps(files, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def deploy_web(env: dict[str, str], arguments: list[str]) -> None:
    """Install a GitHub-built static UI without installing Node on the target."""
    root = Path(
        env.get("WEB_DEPLOY_ROOT", "/www/wwwroot/ui.utama.naufix.space")
    ).expanduser()
    releases = Path(
        env.get("WEB_RELEASE_CACHE_ROOT", str(root.parent / ".tme3bot-ui-releases"))
    ).expanduser()
    current = releases / "current"
    releases.mkdir(parents=True, exist_ok=True)
    if "--rollback" in arguments:
        active = current.resolve() if current.is_symlink() else None
        candidates = sorted(
            (item for item in releases.iterdir() if item.is_dir() and item != active),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise RuntimeError("Tidak ada release web sebelumnya untuk rollback.")
        chosen = candidates[0]
    else:
        repository = _github_repository(env)
        tag = env.get("WEB_RELEASE_TAG", "web-latest").strip() or "web-latest"
        token = env.get("WEB_RELEASE_TOKEN", "").strip()
        temp_root = Path(tempfile.mkdtemp(prefix="tme3bot-web-release-"))
        try:
            metadata = temp_root / "release.json"
            _download(
                f"https://api.github.com/repos/{repository}/releases/tags/{tag}",
                metadata,
                token,
                accept="application/vnd.github+json",
            )
            release = json.loads(metadata.read_text(encoding="utf-8"))
            assets = release.get("assets", [])
            candidates = [item for item in assets if re.fullmatch(r"web-dist-[0-9a-f]{7,40}\.tar\.gz", str(item.get("name", "")))]
            bundle = max(candidates, key=lambda item: str(item.get("created_at", "")), default=None)
            checksum = next((item for item in assets if str(item.get("name", "")) == f"{bundle['name']}.sha256"), None) if bundle else None
            if bundle is None or checksum is None:
                raise RuntimeError("Release web tidak memiliki bundle atau checksum yang valid.")
            archive = temp_root / str(bundle["name"])
            checksum_path = temp_root / str(checksum["name"])
            _download(str(bundle["url"]), archive, token)
            _download(str(checksum["url"]), checksum_path, token)
            expected = checksum_path.read_text(encoding="utf-8").split()[0].lower()
            actual = hashlib.sha256(archive.read_bytes()).hexdigest()
            if not hmac_compare(expected, actual):
                raise RuntimeError("Checksum bundle web tidak cocok; deployment dibatalkan.")
            revision = str(bundle["name"])[len("web-dist-") : -len(".tar.gz")]
            chosen = releases / revision
            if not chosen.exists():
                staging = releases / f".{revision}.staging-{os.getpid()}"
                staging.mkdir(parents=True, exist_ok=False)
                _safe_extract_tar(archive, staging)
                if not (staging / "index.html").is_file() or not (staging / "build-info.json").is_file():
                    shutil.rmtree(staging, ignore_errors=True)
                    raise RuntimeError("Bundle web tidak memiliki index.html atau build-info.json.")
                os.replace(staging, chosen)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)
    link = releases / f".current-{chosen.name}-{os.getpid()}"
    link.symlink_to(chosen, target_is_directory=True)
    os.replace(link, current)
    _install_static_release(chosen, root)
    keep = max(1, int(env.get("WEB_RELEASE_KEEP", "5")))
    active = current.resolve()
    old = sorted((item for item in releases.iterdir() if item.is_dir() and item != active), key=lambda item: item.stat().st_mtime, reverse=True)
    for item in old[keep - 1 :]:
        shutil.rmtree(item, ignore_errors=True)
    print(f"Web static aktif: {chosen.name}")
    print(f"File disalin ke: {root}")


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def publish_application(env: dict[str, str], arguments: list[str]) -> None:
    """Build on this machine and publish compose images to a registry."""
    bootstrap_python_dependencies(env, install=True)
    preflight = preflight_report(env, install=True)
    if int(preflight.get("exit_code", 0)) != 0:
        print_preflight_report(preflight)
        raise RuntimeError("Preflight builder gagal; image belum dibangun atau dipublish.")
    build_base = "--build-base" in arguments
    skip_login = "--no-login" in arguments
    publish_all = "--all" in arguments
    target_args = [
        item
        for item in arguments
        if item not in {"--pull", "--build-base", "--no-login", "--all"}
    ]
    target = (target_args[0].strip().lower() if target_args else "").replace("_", "-")
    targets = ["gateway", "worker"] if publish_all else [target or "gateway"]
    if any(item not in {"gateway", "worker"} for item in targets):
        raise RuntimeError("Target publish harus gateway, worker, atau --all.")
    publish_env = dict(env)
    publish_env["IMAGE_TAG"] = release_image_tag(publish_env)
    if build_base:
        build_base_image(publish_env)
    if not skip_login:
        login_registry(publish_env)
    for item in targets:
        target_env = dict(publish_env)
        target_env["COMPOSE_FILE"] = (
            "docker-compose.gateway.yml" if item == "gateway" else "docker-compose.worker.yml"
        )
        deploy_application(target_env, [item], start_services=False)
        run_compose(["push"], target_env)
        print(f"Image {item} berhasil dipublish dengan tag {target_env['IMAGE_TAG']}.")
    print("Target low-memory dapat memakai: python3 run.py deploy --pull")


def login_registry(env: dict[str, str]) -> None:
    """Login to the image registry without exposing the PAT in process output."""
    image = (env.get("GATEWAY_IMAGE_NAME") or env.get("WORKER_IMAGE_NAME") or "").strip()
    registry = image.split("/", 1)[0] if "/" in image else ""
    if not registry or "." not in registry:
        print("Registry login dilewati: image memakai registry lokal/Docker Hub.")
        return

    token = (env.get("GHCR_TOKEN") or env.get("WEB_RELEASE_TOKEN") or "").strip()
    if not token:
        print(
            f"Registry belum login otomatis. Jalankan `docker login {registry}` "
            "atau isi GHCR_TOKEN di .env."
        )
        return

    username = (env.get("GHCR_USERNAME") or "").strip()
    if not username and "/" in image:
        username = image.split("/", 2)[1].strip()
    if not username:
        raise RuntimeError("GHCR_USERNAME wajib diisi untuk login registry.")

    print(f"Login registry {registry} sebagai {username} menggunakan token dari env.")
    run_docker(
        ["login", registry, "--username", username, "--password-stdin"],
        env,
        stdin_text=token,
    )


def release_image_tag(env: dict[str, str]) -> str:
    configured = env.get("IMAGE_TAG", "").strip()
    if configured and configured != "latest":
        return configured
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=PROJECT_DIR,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or "latest"
    except (OSError, subprocess.CalledProcessError):
        return "latest"


def merge_env_file(env: dict[str, str], filename: str) -> None:
    path = Path(filename).expanduser()
    if not path.is_absolute():
        path = PROJECT_DIR / path
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        parsed = parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if not env.get(key, "").strip():
            env[key] = value


def migrate_images(env: dict[str, str]) -> Path:
    """Build both split deployment images and package them for an offline load."""
    require_env_file()
    validate_local_base_image()
    ensure_base_image_available(env)
    prepare_tdl_build_asset(env)

    image_names: list[str] = []
    for compose_file, example_overrides in (
        (
            "docker-compose.gateway.yml",
            {
                "BACKEND_ENV_FILE": ".env.backend.example",
                "TELEGRAM_ENV_FILE": ".env.telegram.example",
                "LOCAL_WORKER_ENV_FILE": ".env.worker.local.example",
            },
        ),
        (
            "docker-compose.worker.yml",
            {
                "WORKER_ENV_FILE": ".env.worker.example",
                # Compose validates runtime volumes even for a build-only
                # command. The builder does not mount this path; it only keeps
                # PROFILE_ROOT mandatory for real worker deployments.
                "PROFILE_ROOT": "/tmp/tme3bot-worker-build",
            },
        ),
    ):
        build_env = dict(env)
        build_env.update(example_overrides)
        build_env["COMPOSE_FILE"] = compose_file
        run_compose(["build"], build_env)
        output = capture_compose(["config", "--images"], build_env)
        resolved = [line.strip() for line in output.splitlines() if line.strip()]
        print(
            f"Compose images ({compose_file}): {', '.join(resolved) or '(none)'}",
            flush=True,
        )
        for image in resolved:
            if image and image not in image_names:
                image_names.append(image)

    if not image_names:
        raise RuntimeError(
            "Tidak ada image Docker yang ditemukan dari compose split. "
            "Pastikan run.py dan docker-compose*.yml berasal dari project yang sama."
        )

    output = (PROJECT_DIR / "migrate.zip").resolve()
    print(f"Packaging Docker images to: {output}", flush=True)
    with tempfile.TemporaryDirectory(prefix=".migrate-", dir=PROJECT_DIR) as temp_dir:
        image_tar = Path(temp_dir) / "tme3bot-images.tar"
        run_docker(["save", "-o", str(image_tar), *image_names], env)
        if not image_tar.is_file() or image_tar.stat().st_size == 0:
            raise RuntimeError(
                f"docker save selesai tetapi arsip image tidak ditemukan: {image_tar}"
            )
        count, size = build_migration_archive(output, image_tar)

    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"Arsip migrasi tidak berhasil dibuat: {output}")
    print(f"Migration archive: {output}", flush=True)
    print(f"Docker images: {', '.join(image_names)}")
    print(f"Files: {count}")
    print(f"Size: {size / 1024 / 1024:.2f} MB")
    print("Oracle: unzip migrate.zip && docker load -i images/tme3bot-images.tar")
    return output


def validate_local_base_image() -> None:
    """Stop early when extracted base artifacts no longer match the source."""
    manifest = PROJECT_DIR / "base-image-manifest.json"
    base_tar = PROJECT_DIR / "images" / "tme3bot-base.tar"
    if not base_tar.is_file():
        return
    try:
        from build import base_manifest_is_current
    except ModuleNotFoundError:
        return
    current = base_manifest_is_current(manifest)
    if current is False:
        raise RuntimeError(
            "Base image sudah tidak cocok dengan source saat ini. Jalankan "
            "python3 run.py build-base di VPS besar, lalu ekstrak base-migrate.zip "
            "ke project ini sebelum menjalankan migrate/build."
        )
    if current is None:
        print(
            "WARNING: base image ditemukan tanpa manifest; build akan mencoba "
            "menggunakannya, tetapi kompatibilitasnya tidak dapat diverifikasi."
        )


def configured_base_image(env: dict[str, str]) -> str:
    image_name = (env.get("TME3BOT_BASE_IMAGE") or "tme3bot-base:py310-tdl0203").strip()
    if not image_name:
        raise RuntimeError("TME3BOT_BASE_IMAGE tidak boleh kosong.")
    return image_name


def docker_image_exists(image_name: str, env: dict[str, str]) -> bool:
    """Check the local Docker daemon without allowing an implicit registry pull."""
    docker_cmd = env.get("DOCKER_CMD") or os.getenv("DOCKER_CMD", "docker")
    command = shlex.split(docker_cmd) + ["image", "inspect", image_name]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            env=compose_env(env),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def ensure_base_image_available(env: dict[str, str]) -> None:
    """Ensure Docker can resolve the immutable base image before Compose builds.

    Docker's default behavior is to treat an unknown FROM image as a public
    registry image. That is dangerous here because the base image is intended
    to be built once on the large builder VPS and loaded locally on every
    build host. Try the extracted tar automatically, then fail with a recovery
    command instead of letting Compose emit an opaque Docker Hub error.
    """
    image_name = configured_base_image(env)
    if docker_image_exists(image_name, env):
        return

    base_tar = PROJECT_DIR / "images" / "tme3bot-base.tar"
    if base_tar.is_file() and base_tar.stat().st_size > 0:
        print(f"Base image tidak ada di Docker; memuat {base_tar}", flush=True)
        run_docker(["load", "-i", str(base_tar)], env)
        if docker_image_exists(image_name, env):
            print(f"Base image tersedia: {image_name}", flush=True)
            return
        raise RuntimeError(
            f"{base_tar} berhasil diproses tetapi image {image_name!r} tidak "
            "ditemukan. Pastikan nama TME3BOT_BASE_IMAGE sama dengan image "
            "yang dibuat di VPS builder besar."
        )

    raise RuntimeError(
        f"Base image {image_name!r} tidak tersedia di Docker lokal dan "
        f"{base_tar} juga tidak ditemukan. Jalankan `python3 run.py build-base` "
        "di VPS besar, download/extract base-migrate.zip ke project ini, "
        "lalu jalankan `docker load -i images/tme3bot-base.tar`. Setelah itu "
        "ulang command build/migrate/deploy. Jangan menjalankan build di VPS "
        "1 GB sebelum base image dimuat."
    )


def build_base_image(env: dict[str, str]) -> Path:
    """Build and export the expensive immutable runtime/Go base image once."""
    prepare_tdl_build_asset(env)
    image_name = configured_base_image(env)
    platform = (env.get("BASE_PLATFORM") or "linux/amd64").strip()
    if not platform:
        raise RuntimeError("BASE_PLATFORM tidak boleh kosong.")

    run_docker(
        [
            "build",
            "--platform",
            platform,
            "--build-arg",
            f"BUILDPLATFORM={platform}",
            "-f",
            "Dockerfile.base",
            "-t",
            image_name,
            ".",
        ],
        env,
    )
    output = PROJECT_DIR / "base-migrate.zip"
    with tempfile.TemporaryDirectory(prefix=".base-image-", dir=PROJECT_DIR) as temp_dir:
        image_tar = Path(temp_dir) / "tme3bot-base.tar"
        run_docker(["save", "-o", str(image_tar), image_name], env)
        manifest_path = Path(temp_dir) / "base-image-manifest.json"
        try:
            from build import make_base_manifest
        except ModuleNotFoundError as exc:
            raise RuntimeError("build.py tidak ditemukan.") from exc
        manifest_path.write_text(
            json.dumps(
                make_base_manifest(image_name, platform),
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        count, size = build_base_archive(output, image_tar, manifest_path)
        # Keep the freshly built artifacts beside the source so the next
        # `build.py` archive and `run.py migrate` use the same base metadata.
        (PROJECT_DIR / "images").mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_tar, PROJECT_DIR / "images" / "tme3bot-base.tar")
        shutil.copy2(manifest_path, PROJECT_DIR / "base-image-manifest.json")

    print(f"Base image: {image_name}")
    print(f"Platform: {platform}")
    print(f"Archive: {output}")
    print(f"Files: {count}")
    print(f"Size: {size / 1024 / 1024:.2f} MB")
    print("Load: unzip base-migrate.zip && docker load -i images/tme3bot-base.tar")
    print("Next: python3 run.py migrate")
    return output


def add_profile(env: dict[str, str], profile_name: str | None) -> None:
    profile = normalize_profile_name(profile_name)
    if not profile:
        raise RuntimeError(
            "Nama profile wajib diisi. Contoh: python3 run.py add-profile irang"
        )

    ensure_container_profile_dirs(env, profile)
    profile_root = map_data_path(
        Path(data_root_value(env) or ".").expanduser(), f"/data/profiles/{profile}"
    )
    print(f"Profile siap: {profile}")
    if profile_root is not None:
        print(f"Host folder: {profile_root}")
        print(f"Copy .tdl download ke: {profile_root / 'root' / '.tdl'}")
        print(f"Copy .tdl export ke: {profile_root / 'user1' / '.tdl'}")
    print(f"Di bot Telegram, pilih dengan: /profile {profile}")


def ensure_container_profile_dirs(env: dict[str, str], profile: str) -> None:
    default_profile = (
        normalize_profile_name(env.get("DEFAULT_PROFILE", "default")) or "default"
    )
    if profile == default_profile:
        command = (
            "mkdir -p /data/root/.tdl /data/user1/.tdl /data/download /data/download/berlabel /data/download/biasa "
            "/data/exports/pending /data/exports/processing /data/exports/done "
            "/data/exports/failed /data/tmp "
            "&& chown -R user1:user1 /data/user1 /data/exports/pending /data/tmp"
        )
    else:
        command = (
            f"mkdir -p /data/profiles/{profile}/root/.tdl "
            f"/data/profiles/{profile}/user1/.tdl "
            f"/data/profiles/{profile}/download "
            f"/data/profiles/{profile}/download/berlabel "
            f"/data/profiles/{profile}/download/biasa "
            f"/data/profiles/{profile}/exports/pending "
            f"/data/profiles/{profile}/exports/processing "
            f"/data/profiles/{profile}/exports/done "
            f"/data/profiles/{profile}/exports/failed "
            f"/data/profiles/{profile}/tmp "
            f"&& chown -R user1:user1 /data/profiles/{profile}/user1 "
            f"/data/profiles/{profile}/exports/pending "
            f"/data/profiles/{profile}/tmp"
        )
    run_compose(["exec", worker_service(env), "bash", "-lc", command], env)


if __name__ == "__main__":
    raise SystemExit(main())
