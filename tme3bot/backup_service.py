"""Create encrypted, runtime-only per-node backup archives."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import threading
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tme3bot.database_paths import DatabasePaths
from tme3bot.storage_catalog import StorageCatalog
from tme3bot.infrastructure.source_store import SqliteSourceRepository
from tme3bot.utility import UtilitySettingsStore
from tme3bot.tdl_output import clean_tdl_output_line, parse_percent
from tme3bot.tdl import (
    SubprocessRunner,
    notify_command_completed,
    notify_command_started,
    preflight_command,
)

LOGGER = logging.getLogger(__name__)

RUNTIME_ENV_KEYS = (
    "APP_ROLE", "PROFILE_DATA_ROOT", "PROFILES_ROOT", "DEFAULT_PROFILE", "TME3_HOST",
    "BOT_TOKEN", "BOT_USERNAME", "BACKEND_API_URL", "BACKEND_INTERNAL_TOKEN",
    "FRONTEND_SERVICE_TOKEN", "MANAGEMENT_API_TOKEN", "AUTH_JWT_SECRET",
    "AUTH_ACCESS_MINUTES", "AUTH_REFRESH_DAYS", "AUTH_CHALLENGE_MINUTES",
    "GATEWAY_API_URL", "GATEWAY_API_TOKEN", "WORKER_API_TOKEN",
    "WORKER_ENDPOINTS", "WORKER_API_TOKENS", "WORKER_ROUTES", "WORKER_BIND_HOST",
    "GATEWAY_PORT", "WORKER_PORT", "DOWNLOAD_ROOT", "EXPORT_ROOT", "STATE_FILE",
    "LEGACY_MAX_JSON", "TDL_EXPORT_HOME",
    "TDL_DOWNLOAD_HOME", "TDL_EXPORT_STORAGE", "TDL_DOWNLOAD_STORAGE",
    "TDL_EXPORT_NAMESPACE", "TDL_DOWNLOAD_NAMESPACE", "UTILITY_WORKSPACE_ROOT",
    "UTILITY_FOLDERS_FILE", "UTILITY_SETTINGS_FILE", "STORAGE_CHANNEL",
    "STORAGE_CHANNEL_REF", "STORAGE_CHANNEL_ID", "STORAGE_CHANNEL_USERNAME", "STORAGE_DB_FILE",
    "STORAGE_TRASH_RETENTION_DAYS",
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
    def __init__(
        self,
        config,
        catalog: StorageCatalog | None = None,
        progress_callback=None,
        command_callback=None,
    ) -> None:
        self.config = config
        self.catalog = catalog
        self.progress_callback = progress_callback
        self.command_callback = command_callback
        self._process_lock = threading.RLock()
        self._current_process: subprocess.Popen[str] | None = None
        self._current_owner: str | None = None

    def cancel_current(self, owner_job_id: str | None = None) -> bool:
        """Interrupt only this backup service's active 7z process."""
        with self._process_lock:
            process = self._current_process
            owner = self._current_owner
            if owner_job_id is not None and owner != str(owner_job_id):
                return False
            if process is None or process.poll() is not None:
                return False
            SubprocessRunner._interrupt_process(process)
            return True

    def _progress(self, phase: str, **values) -> None:
        if self.progress_callback is not None:
            self.progress_callback({"phase": phase, **values})

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
        safe_run = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(run_id).strip())[:80] or "run"
        archive_path = output_dir / (
            f"backup-{safe_node}-{created_at.replace(':', '').replace('+00:00', 'Z')}-{safe_run}.7z"
        )
        if self._archive_outputs(archive_path):
            raise FileExistsError("Output backup untuk run ini sudah ada.")
        try:
            with tempfile.TemporaryDirectory(prefix=f"backup-{safe_node}-", dir=str(output_dir)) as raw_staging:
                staging = Path(raw_staging)
                self._progress("staging", message="Mengumpulkan data runtime", indeterminate=True)
                self._checkpoint()
                if self.catalog is not None:
                    self._build_gateway_staging(staging)
                else:
                    self._build_worker_staging(staging)
                self._checkpoint()
                self._write_runtime_env(staging)
                self._write_manifest(staging, run_id, node_name, created_at)
                staging_files = [path for path in staging.rglob("*") if path.is_file()]
                staging_bytes = sum(path.stat().st_size for path in staging_files)
                self._progress(
                    "compressing",
                    message=f"Mengompres {len(staging_files)} file runtime",
                    files_total=len(staging_files),
                    bytes_total=staging_bytes,
                    percent=0,
                    indeterminate=False,
                )
                self._make_7z(staging, archive_path, password, volume_size or self.config.backup_volume_size)
        except BaseException as exc:
            leftovers = self._remove_archive_outputs(archive_path)
            if leftovers:
                names = ", ".join(path.name for path in leftovers)
                raise RuntimeError(
                    f"Backup gagal dan output parsial tertinggal: {names}"
                ) from exc
            raise
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
            self._backup_sqlite_snapshot(
                Path(self.config.storage_db_file), data_target / "storage.db"
            )
            source_snapshot = SqliteSourceRepository.export_database_snapshot(data_target / "storage.db")
            state_backup = data_target / "source-state-backup.json"
            state_backup.write_text(
                json.dumps(source_snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            try:
                state_backup.chmod(0o600)
            except OSError:
                pass
        for name in (
            "state.json", "max.json", "workers.json", "worker_routes.json", "profile_state.json", "profiles.json",
            "labels.json", "utility_folders.json", "utility_settings.json",
        ):
            self._copy_file(data_root / name, data_target / name)
        vault_key = data_root / "profile-vault" / "vault.key"
        if vault_key.is_file():
            vault_key_target = data_target / "profile-vault" / "vault.key"
            self._copy_file(vault_key, vault_key_target)
            try:
                vault_key_target.chmod(0o600)
            except OSError:
                pass
        self._copy_profile_metadata(
            Path(self.config.profiles_root), data_target / "profiles"
        )
        self._copy_json_tree(Path(self.config.export_pending_dir), data_target / "exports" / "pending")
        self._copy_json_tree(Path(self.config.export_processing_dir), data_target / "exports" / "processing")
        self._copy_json_tree(Path(self.config.export_done_dir), data_target / "exports" / "done")
        self._copy_json_tree(Path(self.config.export_failed_dir), data_target / "exports" / "failed")

    def _build_worker_staging(self, staging: Path) -> None:
        data_root = Path(self.config.profile_root)
        data_target = staging / "data"
        database_target = staging / "database"
        database_paths = DatabasePaths(getattr(self.config, "database_root", "/database"))
        data_target.mkdir(parents=True, exist_ok=True)
        database_target.mkdir(parents=True, exist_ok=True)
        for name in ("identity.json", "profile.json"):
            self._copy_file(data_root / name, data_target / name)
        self._copy_profile_metadata(
            Path(self.config.profiles_root), data_target / "profiles", include_state=False
        )
        self._backup_sqlite_snapshot(
            database_paths.sqlite("worker-command-journal.sqlite3"),
            database_target / "worker-command-journal.sqlite3",
        )
        self._backup_sqlite_snapshot(
            database_paths.sqlite("public-download-links.sqlite3"),
            database_target / "public-download-links.sqlite3",
        )
        default_profile = str(getattr(self.config, "default_profile", "default"))
        profile_names = [default_profile]
        profiles_root = Path(self.config.profiles_root)
        if profiles_root.exists():
            for profile in profiles_root.iterdir():
                if not profile.is_dir() or profile.is_symlink():
                    continue
                if profile.name != default_profile:
                    profile_names.append(profile.name)
        for profile_name in profile_names:
            for lane in ("download", "export", "upload"):
                self._copy_tree(
                    database_paths.tdl(profile_name, lane),
                    database_target / "tdl" / profile_name / lane / ".tdl",
                )
        if profiles_root.exists():
            for profile in profiles_root.iterdir():
                if not profile.is_dir() or profile.is_symlink():
                    continue
                profile_target = data_target / "profiles" / profile.name
                self._copy_json_tree(profile / "exports" / "pending", profile_target / "exports/pending")
                self._copy_json_tree(profile / "exports" / "processing", profile_target / "exports/processing")
                self._copy_json_tree(profile / "exports" / "done", profile_target / "exports/done")
                self._copy_json_tree(profile / "exports" / "failed", profile_target / "exports/failed")
        self._copy_json_tree(Path(self.config.export_pending_dir), data_target / "exports" / "pending")
        self._copy_json_tree(Path(self.config.export_processing_dir), data_target / "exports" / "processing")
        self._copy_json_tree(Path(self.config.export_done_dir), data_target / "exports" / "done")
        self._copy_json_tree(Path(self.config.export_failed_dir), data_target / "exports" / "failed")

    def _checkpoint(self) -> None:
        preflight_command(self.command_callback)

    @staticmethod
    def _archive_outputs(archive_path: Path) -> list[Path]:
        return sorted(
            path
            for path in archive_path.parent.glob(archive_path.name + "*")
            if path == archive_path or path.name.startswith(archive_path.name + ".")
        )

    @classmethod
    def _remove_archive_outputs(cls, archive_path: Path) -> list[Path]:
        leftovers = []
        for path in cls._archive_outputs(archive_path):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                leftovers.append(path)
        return leftovers

    def _copy_file(self, source: Path, destination: Path) -> None:
        self._checkpoint()
        if not source.is_file():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with source.open("rb") as input_file, destination.open("wb") as output_file:
                while True:
                    self._checkpoint()
                    block = input_file.read(1024 * 1024)
                    if not block:
                        break
                    output_file.write(block)
            shutil.copystat(source, destination)
        except BaseException:
            try:
                destination.unlink()
            except OSError:
                pass
            raise

    def _copy_tree(self, source: Path, destination: Path) -> None:
        self._checkpoint()
        if not source.exists():
            return
        for path in source.rglob("*"):
            self._checkpoint()
            if not path.is_file() or any(part in {"log", "__pycache__"} for part in path.parts):
                continue
            self._copy_file(path, destination / path.relative_to(source))

    def _copy_json_tree(self, source: Path, destination: Path) -> None:
        self._checkpoint()
        if not source.exists():
            return
        for path in source.rglob("*.json"):
            self._checkpoint()
            if path.is_file():
                self._copy_file(path, destination / path.relative_to(source))

    def _copy_profile_metadata(
        self, source: Path, destination: Path, *, include_state: bool = True
    ) -> None:
        self._checkpoint()
        if not source.exists():
            return
        allowed = {"identity.json", "profile.json"}
        if include_state:
            allowed.update({"state.json", "max.json"})
        for path in source.rglob("*"):
            self._checkpoint()
            if path.is_file() and path.name in allowed:
                self._copy_file(path, destination / path.relative_to(source))

    def _backup_sqlite_snapshot(self, source: Path, destination: Path) -> None:
        """Copy a live SQLite journal consistently, including any WAL pages."""
        self._checkpoint()
        if not source.is_file():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_connection = sqlite3.connect(
            f"file:{source.resolve().as_posix()}?mode=ro", uri=True, timeout=15
        )
        target_connection = sqlite3.connect(destination)

        def checkpoint(_status: int, _remaining: int, _total: int) -> None:
            self._checkpoint()

        try:
            source_connection.backup(
                target_connection, pages=100, progress=checkpoint, sleep=0.05
            )
            target_connection.commit()
            self._checkpoint()
        finally:
            target_connection.close()
            source_connection.close()
        try:
            destination.chmod(0o600)
        except OSError:
            pass

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

    def _make_7z(self, staging: Path, output: Path, password: str, volume_size: str) -> None:
        binary = os.getenv("SEVEN_ZIP_BINARY", "7z").strip() or "7z"
        command = [binary, "a", str(output), ".", "-r", "-v" + volume_size, "-mx=0", "-mhe=on", "-p" + password, "-y", "-bsp1"]
        started = time.monotonic()
        output_lines: list[str] = []
        try:
            # Serialize final cancellation preflight, spawn, and process
            # registration so an accepted cancel cannot miss the 7z process.
            with self._process_lock:
                preflight_command(self.command_callback)
                process = subprocess.Popen(
                    command,
                    cwd=str(staging),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=os.name != "nt",
                )
                self._current_process = process
                self._current_owner = (
                    str(getattr(self.command_callback, "job_id", "") or "") or None
                )
        except FileNotFoundError as exc:
            if self.command_callback is not None:
                notify_command_completed(
                    self.command_callback,
                    command,
                    -1,
                    str(exc),
                    max(0.0, time.monotonic() - started),
                    "backup-compress",
                )
            raise RuntimeError("7z tidak tersedia di node backup.") from exc
        command_id = notify_command_started(
            self.command_callback, command, "backup-compress"
        )
        assert process.stdout is not None
        buffer: list[str] = []
        try:
            while True:
                char = process.stdout.read(1)
                if not char:
                    break
                if char in {"\r", "\n"}:
                    line = clean_tdl_output_line("".join(buffer))
                    buffer = []
                    if not line:
                        continue
                    output_lines.append(line)
                    percent = parse_percent(line)
                    if percent is not None:
                        elapsed = max(0.0, time.monotonic() - started)
                        eta = (
                            int(elapsed * (100.0 - percent) / percent)
                            if percent > 0
                            else None
                        )
                        self._progress(
                            "compressing",
                            message="Membuat arsip backup terenkripsi",
                            percent=percent,
                            eta_seconds=eta,
                            elapsed_seconds=int(elapsed),
                            indeterminate=False,
                        )
                else:
                    buffer.append(char)
            if buffer:
                output_lines.append(clean_tdl_output_line("".join(buffer)))
            process.stdout.close()
            code = process.wait()
        finally:
            if process.poll() is None:
                SubprocessRunner._terminate_process(process)
            with self._process_lock:
                if self._current_process is process:
                    self._current_process = None
                    self._current_owner = None
        output = "\n".join(output_lines)
        notify_command_completed(
            self.command_callback,
            command,
            int(code),
            output,
            max(0.0, time.monotonic() - started),
            "backup-compress",
            command_id,
        )
        if code != 0:
            detail = output[-1000:] or "7z gagal"
            raise RuntimeError(f"7z backup gagal: {detail}")
        self._progress(
            "compressing",
            message="Arsip backup selesai dibuat",
            percent=100,
            elapsed_seconds=int(time.monotonic() - started),
            indeterminate=False,
        )
