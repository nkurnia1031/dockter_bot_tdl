#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from tme3bot.names import normalize_profile_name


PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
SERVICE_NAME = os.getenv("SERVICE_NAME", "tme3bot")


USAGE = """Usage: python3 run.py <command>

Commands:
  up            Build if needed, start container in background, then show status
  start         Alias for up
  build         Build image only
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
            run_compose(["restart", SERVICE_NAME], env)
            return 0
        if action == "stop":
            require_env_file()
            run_compose(["stop", SERVICE_NAME], env)
            return 0
        if action == "down":
            require_env_file()
            run_compose(["down"], env)
            return 0
        if action == "logs":
            require_env_file()
            run_compose(["logs", "-f", SERVICE_NAME], env)
            return 0
        if action == "status":
            require_env_file()
            run_compose(["ps"], env)
            return 0
        if action == "shell":
            require_env_file()
            run_compose(["exec", SERVICE_NAME, "bash"], env)
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
    if not ENV_FILE.exists():
        raise RuntimeError(
            ".env tidak ditemukan. Buat dari .env.example lalu isi BOT_TOKEN dan PROFILE_ROOT."
        )


def load_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}

    env: dict[str, str] = {}
    for raw_line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        parsed = parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        env[key] = value
    return env


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
    profile_root = env.get("PROFILE_ROOT", "").strip()
    if not profile_root:
        raise RuntimeError(
            "PROFILE_ROOT kosong/tidak terbaca di .env\n"
            'Format yang didukung: PROFILE_ROOT=/path, PROFILE_ROOT = "/path", atau export PROFILE_ROOT=/path'
        )

    root = Path(profile_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    ensure_host_subdirs(root, env)
    print(f"PROFILE_ROOT: {root}")
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
        "exec", "-T", SERVICE_NAME, "runuser", "-u", "user1", "--",
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


def compose_base_command() -> list[str]:
    compose_cmd = os.getenv("COMPOSE_CMD", "docker compose")
    return shlex.split(compose_cmd)


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
    command = compose_base_command() + args
    print("$ " + shlex.join(command))
    subprocess.run(command, cwd=PROJECT_DIR, env=compose_env(dotenv), check=True)


def run_docker(args: list[str], dotenv: dict[str, str]) -> None:
    docker_cmd = dotenv.get("DOCKER_CMD") or os.getenv("DOCKER_CMD", "docker")
    command = shlex.split(docker_cmd) + args
    print("$ " + shlex.join(command))
    subprocess.run(command, cwd=PROJECT_DIR, env=compose_env(dotenv), check=True)


def add_profile(env: dict[str, str], profile_name: str | None) -> None:
    profile = normalize_profile_name(profile_name)
    if not profile:
        raise RuntimeError(
            "Nama profile wajib diisi. Contoh: python3 run.py add-profile irang"
        )

    ensure_container_profile_dirs(env, profile)
    profile_root = map_data_path(
        Path(env.get("PROFILE_ROOT", ".")).expanduser(), f"/data/profiles/{profile}"
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
    run_compose(["exec", SERVICE_NAME, "bash", "-lc", command], env)


if __name__ == "__main__":
    raise SystemExit(main())
