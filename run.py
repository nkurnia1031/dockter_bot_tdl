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
from getpass import getpass
from pathlib import Path

from tme3bot.infrastructure.http_client import request_json
from tme3bot.names import normalize_profile_name


PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
LEGACY_ENV_FILE = PROJECT_DIR / "env"
USAGE = """Usage: python3 run.py <command>

Commands:
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
    action = sys.argv[1] if len(sys.argv) > 1 else "up"
    env = load_env_file()

    try:
        if action in {"help", "-h", "--help"}:
            print(USAGE)
            return 0
        if action in {"up", "start"}:
            ensure_profile_root(env)
            prepare_tdl_build_asset(env)
            run_compose(["up", "-d", "--build"], env)
            run_compose(["ps"], env)
            return 0
        if action == "build":
            require_env_file()
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
            prepare_tdl_build_asset(env)
            run_compose(["build"], env)
            run_compose(["up", "-d", "--remove-orphans"], env)
            run_compose(["ps"], env)
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


def run_docker(args: list[str], dotenv: dict[str, str]) -> None:
    docker_cmd = dotenv.get("DOCKER_CMD") or os.getenv("DOCKER_CMD", "docker")
    command = shlex.split(docker_cmd) + args
    print("$ " + shlex.join(command))
    subprocess.run(command, cwd=PROJECT_DIR, env=compose_env(dotenv), check=True)


def migrate_images(env: dict[str, str]) -> Path:
    """Build both split deployment images and package them for an offline load."""
    require_env_file()
    validate_local_base_image()
    prepare_tdl_build_asset(env)

    image_names: list[str] = []
    for compose_file, example_overrides in (
        (
            "docker-compose.gateway.yml",
            {
                "BACKEND_ENV_FILE": ".env.backend.example",
                "TELEGRAM_ENV_FILE": ".env.telegram.example",
                "LOCAL_WORKER_ENV_FILE": ".env.worker.local.example",
                "WEB_ENV_FILE": ".env.web.example",
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


def build_base_image(env: dict[str, str]) -> Path:
    """Build and export the expensive immutable runtime/Go base image once."""
    prepare_tdl_build_asset(env)
    image_name = (
        env.get("TME3BOT_BASE_IMAGE") or "tme3bot-base:py310-tdl0203"
    ).strip()
    platform = (env.get("BASE_PLATFORM") or "linux/amd64").strip()
    if not image_name:
        raise RuntimeError("TME3BOT_BASE_IMAGE tidak boleh kosong.")
    if not platform:
        raise RuntimeError("BASE_PLATFORM tidak boleh kosong.")

    run_docker(
        [
            "build",
            "--platform",
            platform,
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
