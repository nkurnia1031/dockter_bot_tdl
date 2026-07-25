"""Create encrypted, runtime-only per-node backup archives."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tme3bot.storage_catalog import StorageCatalog
from tme3bot.utility import UtilitySettingsStore

LOGGER = logging.getLogger(__name__)

RUNTIME_ENV_KEYS = (
    "APP_ROLE", "PROFILE_DATA_ROOT", "PROFILES_ROOT", "DEFAULT_PROFILE", "TME3_HOST",
    "BOT_TOKEN", "BOT_USERNAME", "BACKEND_API_URL", "BACKEND_INTERNAL_TOKEN",
    "FRONTEND_SERVICE_TOKEN", "MANAGEMENT_API_TOKEN", "AUTH_JWT_SECRET",
    "AUTH_ACCESS_MINUTES", "AUTH_REFRESH_DAYS", "AUTH_CHALLENGE_MINUTES",
    "GATEWAY_API_URL", "GATEWAY_API_TOKEN", "WORKER_API_TOKEN",
    "WORKER_ENDPOINTS", "WORKER_API_TOKENS", "WORKER_ROUTES", "WORKER_BIND_HOST",
    "GATEWAY_PORT", "WORKER_PORT", "DOWNLOAD_ROOT", "EXPORT_ROOT", "STATE_FILE",
    "LEGACY_MAX_JSON", "TDL_EXPORT_USER", "TDL_DOWNLOAD_USER", "TDL_EXPORT_HOME",
    "TDL_DOWNLOAD_HOME", "TDL_EXPORT_STORAGE", "TDL_DOWNLOAD_STORAGE",
    "TDL_EXPORT_NAMESPACE", "TDL_DOWNLOAD_NAMESPACE", "UTILITY_WORKSPACE_ROOT",
    "UTILITY_FOLDERS_FILE", "UTILITY_SETTINGS_FILE", "STORAGE_CHANNEL",
    "STORAGE_CHANNEL_REF", "STORAGE_CHANNEL_ID", "STORAGE_CHANNEL_USERNAME", "STORAGE_DB_FILE",
    "BACKUP_ENABLED", "BACKUP_CHANNEL", "BACKUP_CHANNEL_REF", "BACKUP_CHANNEL_ID",
    "BACKUP_CHANNEL_USERNAME", "BACKUP_SCHEDULE", "BACKUP_TIMEZONE",
    "BACKUP_RETENTION", "BACKUP_VOLUME_SIZE", "BACKUP_NODE_NAME", "LOG_LEVEL",
)


@dataclass(frozen=True)
class BackupArchive:
    run_id: str
    node_name: str
    archive_path: Path
    parts: tuple[Path, ...]
    created_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_node_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
    return normalized[:64] or "node"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class BackupService:
    def __init__(self, config, catalog: StorageCatalog | None = None) -> None:
        self.config = config
        self.catalog = catalog

    def password(self) -> str:
        values = UtilitySettingsStore(self.config.utility_settings_file).get()
        password = values.get("compress_password", "").strip()
        if not password:
            raise ValueError("Password backup tidak tersedia di Utility Settings.")
        return password

    def create_archive(self, run_id: str, node_name: str, password: str | None = None, volume_size: str | None = None) -> BackupArchive:
        password = password or self.password()
        if not password:
            raise ValueError("Password backup tidak boleh kosong.")
        created_at = utc_now()
        safe_node = safe_node_name(node_name)
        output_dir = Path(self.config.temp_root) / "backups" / safe_node
        output_dir.mkdir(parents=True, exist_ok=True)
        archive_path = output_dir / f"backup-{safe_node}-{created_at.replace(':', '').replace('+00:00', 'Z')}.7z"
        with tempfile.TemporaryDirectory(prefix=f"backup-{safe_node}-", dir=str(output_dir)) as raw_staging:
            staging = Path(raw_staging)
            if self.catalog is not None:
                self._build_gateway_staging(staging)
            else:
                self._build_worker_staging(staging)
            self._write_runtime_env(staging)
            self._write_manifest(staging, run_id, node_name, created_at)
            self._make_7z(staging, archive_path, password, volume_size or self.config.backup_volume_size)
        parts = tuple(sorted(archive_path.parent.glob(archive_path.name + ".*")))
        if archive_path.exists():
            parts = (archive_path,) + parts
        if not parts:
            raise RuntimeError("7z tidak menghasilkan file backup.")
        return BackupArchive(run_id, node_name, archive_path, parts, created_at)

    def _build_gateway_staging(self, staging: Path) -> None:
        data_root = Path(self.config.profile_root)
        data_target = staging / "data"
        data_target.mkdir(parents=True, exist_ok=True)
        if self.catalog is not None and Path(self.config.storage_db_file).exists():
            self.catalog.backup_database_to(data_target / "storage.db")
        for name in (
            "state.json", "max.json", "workers.json", "worker_routes.json", "profile_state.json", "profiles.json",
            "labels.json", "utility_folders.json", "utility_settings.json",
        ):
            self._copy_file(data_root / name, data_target / name)
        self._copy_profile_metadata(Path(self.config.profiles_root), data_target / "profiles")
        self._copy_json_tree(Path(self.config.export_pending_dir), data_target / "exports" / "pending")
        self._copy_json_tree(Path(self.config.export_processing_dir), data_target / "exports" / "processing")
        self._copy_json_tree(Path(self.config.export_done_dir), data_target / "exports" / "done")
        self._copy_json_tree(Path(self.config.export_failed_dir), data_target / "exports" / "failed")

    def _build_worker_staging(self, staging: Path) -> None:
        data_root = Path(self.config.profile_root)
        data_target = staging / "data"
        data_target.mkdir(parents=True, exist_ok=True)
        for name in ("state.json", "max.json", "profile_state.json", "identity.json", "profile.json"):
            self._copy_file(data_root / name, data_target / name)
        self._copy_profile_metadata(Path(self.config.profiles_root), data_target / "profiles")
        for source, name in (
            (self.config.tdl_download_home, "root/.tdl"),
            (self.config.tdl_export_home, "user1/.tdl"),
        ):
            self._copy_tree(Path(source) / ".tdl", data_target / name)
        profiles_root = Path(self.config.profiles_root)
        if profiles_root.exists():
            for profile in profiles_root.iterdir():
                if not profile.is_dir():
                    continue
                profile_target = data_target / "profiles" / profile.name
                self._copy_tree(profile / "root" / ".tdl", profile_target / "root/.tdl")
                self._copy_tree(profile / "user1" / ".tdl", profile_target / "user1/.tdl")
                self._copy_json_tree(profile / "exports" / "pending", profile_target / "exports/pending")
                self._copy_json_tree(profile / "exports" / "processing", profile_target / "exports/processing")
                self._copy_json_tree(profile / "exports" / "done", profile_target / "exports/done")
                self._copy_json_tree(profile / "exports" / "failed", profile_target / "exports/failed")
        self._copy_json_tree(Path(self.config.export_pending_dir), data_target / "exports" / "pending")
        self._copy_json_tree(Path(self.config.export_processing_dir), data_target / "exports" / "processing")
        self._copy_json_tree(Path(self.config.export_done_dir), data_target / "exports" / "done")
        self._copy_json_tree(Path(self.config.export_failed_dir), data_target / "exports" / "failed")

    @staticmethod
    def _copy_file(source: Path, destination: Path) -> None:
        if not source.is_file():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    @classmethod
    def _copy_tree(cls, source: Path, destination: Path) -> None:
        if not source.exists():
            return
        for path in source.rglob("*"):
            if not path.is_file() or any(part in {"log", "__pycache__"} for part in path.parts):
                continue
            cls._copy_file(path, destination / path.relative_to(source))

    @classmethod
    def _copy_json_tree(cls, source: Path, destination: Path) -> None:
        if not source.exists():
            return
        for path in source.rglob("*.json"):
            if path.is_file():
                cls._copy_file(path, destination / path.relative_to(source))

    @classmethod
    def _copy_profile_metadata(cls, source: Path, destination: Path) -> None:
        if not source.exists():
            return
        for path in source.rglob("*"):
            if path.is_file() and path.name in {"state.json", "identity.json", "profile.json", "max.json"}:
                cls._copy_file(path, destination / path.relative_to(source))

    def _write_runtime_env(self, staging: Path) -> None:
        lines = []
        for key in RUNTIME_ENV_KEYS:
            if key in os.environ:
                lines.append(f"{key}={shlex.quote(os.environ[key])}")
        (staging / "runtime.env").write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            (staging / "runtime.env").chmod(0o600)
        except OSError:
            pass

    def _write_manifest(self, staging: Path, run_id: str, node_name: str, created_at: str) -> Path:
        manifest = {
            "run_id": run_id,
            "node_name": node_name,
            "created_at": created_at,
            "included": [str(path.relative_to(staging)) for path in staging.rglob("*") if path.is_file()],
            "excluded": ["workspace media", "download media", "docker logs", "temporary locks"],
            "secret_keys": list(RUNTIME_ENV_KEYS),
        }
        path = staging / "backup-manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
        return path

    @staticmethod
    def _make_7z(staging: Path, output: Path, password: str, volume_size: str) -> None:
        binary = os.getenv("SEVEN_ZIP_BINARY", "7z").strip() or "7z"
        command = [binary, "a", str(output), ".", "-r", "-v" + volume_size, "-mx=0", "-mhe=on", "-p" + password, "-y"]
        try:
            completed = subprocess.run(command, cwd=str(staging), check=False, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError("7z tidak tersedia di node backup.") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "7z gagal")[-1000:]
            raise RuntimeError(f"7z backup gagal: {detail}")
