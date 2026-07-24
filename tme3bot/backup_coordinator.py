"""Gateway orchestration, channel upload, scheduling, and retention."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tme3bot.backup_service import BackupService, sha256_file

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupNodeJob:
    """Worker-neutral command payload for one node backup."""

    backup_run_id: str
    node_name: str
    password: str
    channel_ref: str
    channel_id: int
    volume_size: str


class BackupCoordinator:
    def __init__(self, config, bot, catalog, worker_registry=None, remote_router=None, local_worker=None) -> None:
        self.config = config
        self.bot = bot
        self.catalog = catalog
        self.service = BackupService(config, catalog)
        self.worker_registry = worker_registry
        self.remote_router = remote_router
        self.local_worker = local_worker
        self._lock = threading.RLock()
        self._active_run: str | None = None

    def validate(self) -> None:
        if not self.config.backup_channel_ref or not self.config.backup_channel_id:
            raise ValueError("BACKUP_CHANNEL_REF dan BACKUP_CHANNEL_ID wajib dikonfigurasi.")
        try:
            ZoneInfo(self.config.backup_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Timezone backup tidak dikenal: {self.config.backup_timezone}") from exc

    def start_now(self) -> str:
        self.validate()
        with self._lock:
            if self._active_run:
                return self._active_run
            run_id = uuid.uuid4().hex
            self._active_run = run_id
        threading.Thread(target=self._execute, args=(run_id,), daemon=True, name="tme3-backup-coordinator").start()
        return run_id

    def _execute(self, run_id: str) -> None:
        try:
            password = self.service.password()
            self._run_gateway(run_id, password)
            for worker_name in self._worker_names():
                self.catalog.start_backup_run(run_id, worker_name)
                job = BackupNodeJob(
                    backup_run_id=run_id,
                    node_name=worker_name,
                    password=password,
                    channel_ref=self.config.backup_channel_ref,
                    channel_id=self.config.backup_channel_id,
                    volume_size=self.config.backup_volume_size,
                )
                try:
                    if self.remote_router is not None:
                        self.remote_router.enqueue_backup(worker_name, job)
                    elif self.local_worker is not None:
                        self.local_worker.enqueue(job)
                    else:
                        self.catalog.finish_backup_run(run_id, worker_name, "offline", "Worker backend tidak tersedia.")
                except Exception as exc:
                    self.catalog.finish_backup_run(run_id, worker_name, "offline", str(exc))
                    LOGGER.warning("Worker backup %s offline: %s", worker_name, exc)
        except Exception as exc:
            LOGGER.exception("Gateway backup failed")
            self.catalog.start_backup_run(run_id, self.config.backup_node_name)
            self.catalog.finish_backup_run(run_id, self.config.backup_node_name, "failed", str(exc))
        finally:
            with self._lock:
                self._active_run = None

    def _run_gateway(self, run_id: str, password: str) -> None:
        node_name = self.config.backup_node_name
        self.catalog.start_backup_run(run_id, node_name)
        archive = self.service.create_archive(run_id, node_name, password=password, volume_size=self.config.backup_volume_size)
        try:
            for part in archive.parts:
                digest, size = sha256_file(part)
                with part.open("rb") as document:
                    message = self.bot.send_document(
                        chat_id=self.config.backup_channel_id,
                        document=document,
                        filename=part.name,
                        caption=f"#backup #node_{node_name} #run_{run_id[:12]}\nPart: {part.name}",
                    )
                self.catalog.upsert_backup_part(
                    run_id=run_id, node_name=node_name, part_name=part.name,
                    channel_id=self.config.backup_channel_id,
                    channel_message_id=int(message.message_id), file_size=size,
                    sha256=digest, status="active",
                )
            self.catalog.finish_backup_run(run_id, node_name, "complete")
            self.prune_node(node_name)
        finally:
            for part in archive.parts:
                try:
                    part.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning("Tidak bisa menghapus backup sementara %s", part)

    def handle_worker_callback(self, payload: dict) -> None:
        run_id = str(payload.get("backup_run_id", ""))
        node_name = str(payload.get("node_name", ""))
        if not run_id or not node_name:
            raise ValueError("Callback backup membutuhkan backup_run_id dan node_name.")
        status = payload.get("status")
        if payload.get("part_name"):
            required = {"channel_id", "channel_message_id", "file_size", "sha256"}
            missing = sorted(required - set(payload))
            if missing:
                raise ValueError(f"Field callback backup kurang: {', '.join(missing)}")
            self.catalog.upsert_backup_part(
                run_id=run_id, node_name=node_name, part_name=str(payload["part_name"]),
                channel_id=int(payload["channel_id"]), channel_message_id=int(payload["channel_message_id"]),
                file_size=int(payload["file_size"]), sha256=str(payload["sha256"]), status="active",
            )
        if status == "complete":
            self.catalog.finish_backup_run(run_id, node_name, "complete")
            self.prune_node(node_name)
        elif status == "failed":
            self.catalog.finish_backup_run(run_id, node_name, "failed", str(payload.get("error", "backup gagal")))

    def prune_node(self, node_name: str) -> None:
        for run in self.catalog.backup_retention_candidates(node_name, self.config.backup_retention):
            parts = self.catalog.backup_parts(str(run["run_id"]), node_name)
            cleanup_failed = False
            for part in parts:
                try:
                    self.bot.delete_message(
                        chat_id=int(part["channel_id"]),
                        message_id=int(part["channel_message_id"]),
                    )
                except Exception as exc:
                    cleanup_failed = True
                    LOGGER.warning("Backup cleanup gagal untuk %s: %s", part["part_name"], exc)
            if cleanup_failed:
                self.catalog.finish_backup_run(str(run["run_id"]), node_name, "cleanup_failed", "Gagal menghapus sebagian backup lama.")
            else:
                self.catalog.delete_backup_run(str(run["run_id"]), node_name)

    def _worker_names(self) -> list[str]:
        if self.worker_registry is not None:
            names = self.worker_registry.names()
            if names:
                return names
        if self.local_worker is not None:
            return ["worker-local"]
        return []

    def status(self) -> list[dict[str, object]]:
        return self.catalog.backup_runs(limit=100)

    def next_run(self) -> datetime:
        timezone = ZoneInfo(self.config.backup_timezone)
        now = datetime.now(timezone)
        hour, minute = (int(value) for value in self.config.backup_schedule.split(":", 1))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)


class BackupScheduler:
    def __init__(self, config, coordinator: BackupCoordinator) -> None:
        self.config = config
        self.coordinator = coordinator
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.config.backup_enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="tme3-backup-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        try:
            next_run = self.coordinator.next_run()
        except Exception:
            LOGGER.exception("Backup scheduler configuration invalid")
            return
        while not self._stop.is_set():
            delay = max(1.0, (next_run - datetime.now(next_run.tzinfo)).total_seconds())
            if self._stop.wait(min(delay, 60.0)):
                return
            if datetime.now(next_run.tzinfo) >= next_run:
                try:
                    self.coordinator.start_now()
                except Exception:
                    LOGGER.exception("Scheduled backup could not start")
                next_run = self.coordinator.next_run()
