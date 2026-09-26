from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
import shutil
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tme3bot.backup_service import BackupService, sha256_file
from tme3bot.command_audit import bounded_output_tail, sanitize_command, sanitize_text
from tme3bot.domain.models import DomainError, utc_now
from tme3bot.export_catalog import discard_export_without_media, inspect_export_json
from tme3bot.infrastructure.http_client import JsonHttpError, request_json
from tme3bot.profile_queue import ResourceAwareQueue
from tme3bot.progress_reporter import ProgressReporter
from tme3bot.profiles import build_profile_config
from tme3bot.rclone import RcloneRunner
from tme3bot.service import ExportJobResult
from tme3bot.storage_catalog import build_storage_caption
from tme3bot.tdl import ProcessStalledError, TDLStalledError
from tme3bot.tdl_output import is_tdl_telemetry_line
from tme3bot.utility import DEFAULT_UTILITY_SETTINGS, UtilityRunner
from tme3bot.worker.quick_export import (
    QUICK_PHASES,
    QuickModeError,
    QuickThumbnailBuilder,
    migrate_legacy_quick_stage,
    quick_folder_name,
    quick_stage_root,
    quick_storage_caption,
    quick_year,
    read_quick_manifest,
    scan_quick_stages,
    ensure_quick_tdl_client,
    ensure_quick_stage_writable,
    visual_media,
    write_quick_manifest,
)

LOGGER = logging.getLogger(__name__)
from .executor_support import (
    BAR_ONLY_PROGRESS_KEY,
    CommandMilestoneRecorder,
    JAKARTA_TZ,
    JobLogSnapshot,
    RUNTIME_STATS_KEY,
    WorkerEventPublisher,
    _PROGRESS_BAR_RE,
    _has_transfer_telemetry,
    _is_named_progress_key,
    _quick_message_matches,
    _utility_progress_message,
    jakarta_timestamp,
    json_value,
    progress_line_key,
    storage_logical_folder,
    storage_relative_folders,
)




























from .executor_backup import BackupExecutorMixin
from .executor_downloads import DownloadExecutorMixin
from .executor_quickmode import QuickModeExecutorMixin
from .executor_storage import StorageExecutorMixin
from .executor_utility import UtilityExecutorMixin
from .executor_workspace import WorkspaceExecutorMixin

class WorkerJobExecutor(
    QuickModeExecutorMixin,
    DownloadExecutorMixin,
    UtilityExecutorMixin,
    StorageExecutorMixin,
    BackupExecutorMixin,
    WorkspaceExecutorMixin,
):
    """Executes domain jobs and publishes JSON events; no UI dependency."""

    def __init__(self, config, profile_manager, publisher: WorkerEventPublisher) -> None:
        self.config = config
        self.profile_manager = profile_manager
        self.publisher = publisher
        self._active: dict[str, tuple[str, str]] = {}
        self._active_commands: dict[str, dict[str, Any]] = {}
        self._utility_runners: dict[str, UtilityRunner] = {}
        self._rclone_runners: dict[str, RcloneRunner] = {}
        self._quick_thumbnail_builders: dict[str, QuickThumbnailBuilder] = {}
        self._quick_export_clients: dict[str, Any] = {}
        self._quick_download_clients: dict[str, Any] = {}
        self._quick_active: set[str] = set()
        self._quick_verify_active: set[str] = set()
        self._quick_delete_active: set[str] = set()
        self._quick_stage_jobs: dict[str, str] = {}
        self._cancel_requested: set[str] = set()
        self._pause_events: dict[str, threading.Event] = {}
        self._paused_pending_ids: set[str] = set()
        self._known: set[str] = set()
        self._lock = threading.RLock()
        self._job_log = threading.local()
        self._log_snapshots: dict[str, JobLogSnapshot] = {}
        self._quick_log_paths: dict[str, Path] = {}
        self._quick_log_locks: dict[str, threading.RLock] = {}
        self._quick_log_named_progress: dict[str, bool] = {}
        self._quick_log_state_lock = threading.RLock()
        # Inventory statistics are derived from the JSON file.  Keep a small
        # process-local fingerprint cache so repeated reconciles do not parse
        # unchanged exports again.  The cache is intentionally disposable;
        # a worker restart simply performs one full scan.
        self._inventory_cache: dict[
            tuple[str, str], tuple[tuple[int, int, int], dict[str, Any]]
        ] = {}
        self._jobs = ResourceAwareQueue[dict[str, Any]](
            self._run,
            error_handler=self._unhandled_resource,
            thread_name_prefix="tme3-domain-worker",
        )

    def start(self) -> None:
        self.sync_profiles()
        self._recover_legacy_quick_stages()
        self._jobs.start()

    def _recover_legacy_quick_stages(self) -> None:
        """Make pre-manager Quick Mode staging visible after worker restart."""
        workspace = self._quick_workspace(self.config)
        legacy_root = workspace / ".tme3bot-quick"
        if not legacy_root.is_dir():
            return
        for candidate in sorted(legacy_root.iterdir()):
            if not candidate.is_dir():
                continue
            try:
                migrate_legacy_quick_stage(workspace, candidate.name)
            except Exception:
                LOGGER.warning(
                    "Could not migrate legacy Quick Mode staging %s", candidate, exc_info=True
                )
        try:
            legacy_root.rmdir()
        except OSError:
            pass

    def sync_profiles(self) -> None:
        """Publish only profile metadata; .tdl files remain on this worker."""
        try:
            request_json(
                self.config.backend_api_url,
                self.config.backend_internal_token,
                "POST",
                "/internal/v1/profiles/sync",
                {"profiles": self.profile_manager.local_profile_identities()},
                timeout=15,
            )
        except Exception as exc:
            # The worker can still expose its API while the backend restarts;
            # the next worker restart will retry registration.
            LOGGER.warning("Could not sync worker profile metadata to backend: %s", exc)

    def enqueue(self, command: dict[str, Any]) -> int:
        job_id = str(command["job_id"])
        worker = str(command.get("worker") or self.config.backup_node_name).strip()
        payload = command.get("payload") or {}
        quick_stage_id = None
        if str(command.get("kind") or "") == "export" and bool(payload.get("quick_mode")):
            retry = payload.get("quick_retry") or {}
            retry = retry if isinstance(retry, dict) else {}
            quick_stage_id = str(retry.get("stage_job_id") or job_id).strip()
        with self._lock:
            if quick_stage_id and quick_stage_id in self._quick_delete_active:
                raise DomainError(
                    "QUICKMODE_STAGE_BUSY",
                    "Folder staging Quick Mode sedang dihapus. Coba kirim job lagi sebentar.",
                    status_code=409,
                )
            self.publisher.begin(job_id, command.get("event_sequence_start"))
            if worker:
                self.publisher.bind_job_worker(job_id, worker)
            if job_id in self._known:
                return self._jobs.queue_size()
            self._known.add(job_id)
            if quick_stage_id:
                self._quick_stage_jobs[job_id] = quick_stage_id
        execution = command.get("execution") or {}
        resources = execution.get("resource_keys") or self._resource_keys_for_command(command)
        try:
            position = self._jobs.enqueue(
                resources,
                command,
                priority=0 if command.get("payload", {}).get("priority") == "next" else 100,
                job_id=job_id,
            )
        except Exception:
            with self._lock:
                self._known.discard(job_id)
                self._quick_stage_jobs.pop(job_id, None)
            raise
        try:
            self.publisher.emit(
                job_id,
                "dispatched",
                "queue",
                progress={"position": position, "worker": self.config.backup_node_name},
            )
        except Exception:
            LOGGER.exception("Could not publish queue position for %s", job_id)
        return position

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            was_paused = job_id in self._pause_events and self._pause_events[job_id].is_set()
            if was_paused:
                self._pause_events[job_id].clear()
            paused_pending = job_id in self._paused_pending_ids
            if paused_pending:
                self._paused_pending_ids.discard(job_id)
        if paused_pending and self._jobs.cancel_pending(job_id):
            with self._lock:
                self._known.discard(job_id)
                self._quick_stage_jobs.pop(job_id, None)
            try:
                self.publisher.emit(
                    job_id,
                    "cancelled",
                    "cancelled",
                    progress={"phase": "cancelled", "finished_at": utc_now().isoformat()},
                    error={"code": "JOB_TERMINATED", "message": "Job antrean Quick Mode dibatalkan."},
                )
                self.publisher.forget(job_id)
                return True
            except Exception:
                LOGGER.warning("Could not publish cancellation for paused queued job %s", job_id, exc_info=True)
                return False
        if was_paused:
            self._set_job_process_paused(job_id, False)
        if self._jobs.cancel_pending(job_id):
            with self._lock:
                self._known.discard(job_id)
                self._quick_stage_jobs.pop(job_id, None)
            self.publisher.forget(job_id)
            # Returning false tells the backend to persist the terminal
            # cancelled event for a command that never started.
            return False
        with self._lock:
            active = self._active.get(job_id)
            utility_runner = self._utility_runners.get(job_id)
            rclone_runner = self._rclone_runners.get(job_id)
            quick_export_client = self._quick_export_clients.get(job_id)
            quick_download_client = self._quick_download_clients.get(job_id)
        if active is None:
            return False
        profile, kind = active
        with self._lock:
            quick_active = job_id in self._quick_active
            thumbnail_builder = self._quick_thumbnail_builders.get(job_id)
            # Set this before interrupting any subprocess.  A phase can finish
            # between two interrupt calls; the worker must still terminate
            # instead of entering the next Quick Mode phase.
            self._cancel_requested.add(job_id)
        self._write_quick_log_line(
            job_id,
            f"[cancel] request received kind={kind} quick_mode={quick_active}",
        )

        cancelled = False

        def interrupt(label: str, callback) -> None:
            nonlocal cancelled
            if callback is None:
                self._write_quick_log_line(
                    job_id, f"[cancel] interrupt={label} result=unavailable"
                )
                return
            try:
                result = bool(callback())
                cancelled = result or cancelled
                self._write_quick_log_line(
                    job_id, f"[cancel] interrupt={label} result={result}"
                )
            except Exception as exc:
                # Cancellation is best effort.  One missing runtime/client
                # must not turn the API request into an HTTP 500 or prevent
                # the remaining resources from receiving the signal.
                self._write_quick_log_line(
                    job_id,
                    f"[cancel] interrupt={label} error_type={type(exc).__name__}",
                )
                LOGGER.warning(
                    "Could not interrupt %s for job %s", label, job_id, exc_info=True
                )

        try:
            runtime = self.profile_manager.runtime(profile)
        except Exception:
            runtime = None
            LOGGER.warning(
                "Could not resolve runtime for cancellation of job %s",
                job_id,
                exc_info=True,
            )
        if kind == "download":
            interrupt(
                "download",
                getattr(getattr(runtime, "download_tdl_client", None), "interrupt_current", None),
            )
        elif kind in {"export", "backup_node"}:
            interrupt(
                "export",
                getattr(getattr(runtime, "export_tdl_client", None), "interrupt_current", None),
            )
            if quick_active:
                interrupt(
                    "quick isolated export",
                    getattr(quick_export_client, "interrupt_current", None),
                )
                interrupt(
                    "quick isolated download",
                    getattr(quick_download_client, "interrupt_current", None),
                )
                interrupt(
                    "quick download",
                    getattr(getattr(runtime, "download_tdl_client", None), "interrupt_current", None),
                )
                try:
                    storage_runtime = self.profile_manager.runtime(
                        getattr(self.config, "worker_storage_profile", "storage")
                    )
                except Exception:
                    storage_runtime = None
                    LOGGER.warning(
                        "Could not resolve storage runtime for cancellation of job %s",
                        job_id,
                        exc_info=True,
                    )
                interrupt(
                    "quick storage",
                    getattr(getattr(storage_runtime, "export_tdl_client", None), "interrupt_current", None),
                )
                if thumbnail_builder is not None:
                    interrupt("quick thumbnail", thumbnail_builder.cancel_current)
                if utility_runner is not None:
                    interrupt("quick utility", utility_runner.cancel_current)
                if rclone_runner is not None:
                    interrupt("quick rclone", rclone_runner.cancel_current)
        elif kind == "storage_upload":
            try:
                storage_runtime = self.profile_manager.runtime(
                    getattr(self.config, "worker_storage_profile", "storage")
                )
            except Exception:
                storage_runtime = None
            interrupt(
                "storage upload",
                getattr(getattr(storage_runtime, "export_tdl_client", None), "interrupt_current", None),
            )
            if rclone_runner is not None:
                interrupt("storage rclone", rclone_runner.cancel_current)
        elif kind == "leave":
            interrupt(
                "leave",
                getattr(
                    getattr(getattr(runtime, "leave_service", None), "runner", None),
                    "interrupt_current",
                    None,
                ),
            )
        elif kind == "utility" and utility_runner is not None:
            interrupt("utility", utility_runner.cancel_current)
        # An active Quick Mode job is cancellable even when its current phase
        # has no subprocess (for example while resolving a Telegram result).
        return bool(cancelled or quick_active or kind in {"export", "backup_node"})

    def pause(self, job_id: str) -> bool:
        target = str(job_id)
        if self._jobs.pause_pending(target):
            try:
                self.publisher.emit(
                    target,
                    "paused",
                    "paused",
                    progress={"phase": "queued", "paused_phase": "queued", "pause_kind": "worker"},
                )
                with self._lock:
                    self._paused_pending_ids.add(target)
                return True
            except Exception:
                LOGGER.warning("Could not publish pause for queued job %s", target, exc_info=True)
                self._jobs.resume_pending(target)
                return False
        if self._jobs.is_active(target):
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                with self._lock:
                    if target in self._active_commands:
                        break
                time.sleep(0.01)
        with self._lock:
            active = self._active.get(target)
            command = self._active_commands.get(target)
            if active is None or command is None:
                return False
            pause_event = self._pause_events.setdefault(target, threading.Event())
            if pause_event.is_set():
                return True
            pause_event.set()
        self._set_job_process_paused(target, True)
        phase = self._quick_terminal_phase(command, "running")
        try:
            self.publisher.emit(
                target,
                "paused",
                "paused",
                progress={
                    "phase": phase,
                    "paused_phase": phase,
                    "pause_kind": "worker",
                    "message": "Quick Mode dijeda",
                },
            )
            return True
        except Exception:
            LOGGER.warning("Could not publish pause for job %s", target, exc_info=True)
            with self._lock:
                pause_event.clear()
            self._set_job_process_paused(target, False)
            return False

    def resume(self, job_id: str, event_sequence_start: int | None = None) -> bool:
        target = str(job_id)
        self.publisher.begin(target, event_sequence_start)
        if self._jobs.resume_pending(target, event_sequence_start=event_sequence_start):
            with self._lock:
                self._paused_pending_ids.discard(target)
            return True
        with self._lock:
            pause_event = self._pause_events.get(target)
            active = self._active.get(target)
            if pause_event is None or not pause_event.is_set() or active is None:
                return False
            pause_event.clear()
        self._set_job_process_paused(target, False)
        try:
            self.publisher.emit(
                target,
                "running",
                "resumed",
                progress={
                    "phase": "resuming",
                    "message": "Quick Mode dilanjutkan",
                    "resumed_at": utc_now().isoformat(),
                },
            )
            return True
        except Exception:
            LOGGER.warning("Could not publish resume for job %s", target, exc_info=True)
            return False

    def _set_job_process_paused(self, job_id: str, paused: bool) -> None:
        with self._lock:
            active = self._active.get(job_id)
            command = self._active_commands.get(job_id)
            clients = [
                self._quick_export_clients.get(job_id),
                self._quick_download_clients.get(job_id),
                self._quick_thumbnail_builders.get(job_id),
                self._utility_runners.get(job_id),
                self._rclone_runners.get(job_id),
            ]
        if active is not None:
            try:
                runtime = self.profile_manager.runtime(active[0])
            except Exception:
                runtime = None
            try:
                storage_profile = getattr(self.config, "worker_storage_profile", "storage")
                storage_runtime = self.profile_manager.runtime(storage_profile)
                clients.append(getattr(storage_runtime, "export_tdl_client", None))
            except Exception:
                pass
            if command and command.get("kind") == "leave" and runtime is not None:
                clients.append(getattr(getattr(runtime, "leave_service", None), "runner", None))
        seen: set[int] = set()
        for client in clients:
            if client is None or id(client) in seen:
                continue
            seen.add(id(client))
            method = getattr(client, "pause_current" if paused else "resume_current", None)
            if method is None and isinstance(client, RcloneRunner):
                method = getattr(client.runner, "pause_current" if paused else "resume_current", None)
            if callable(method):
                try:
                    method(job_id)
                except Exception:
                    LOGGER.warning("Could not %s process for job %s", "pause" if paused else "resume", job_id, exc_info=True)

    def queue_size(self, profile: str) -> int:
        del profile
        return self._jobs.queue_size()

    def capabilities(self) -> dict[str, Any]:
        """Return non-secret worker capabilities for backend target checks."""
        profiles = [str(item) for item in self.profile_manager.list_profiles()]
        storage_profile = getattr(self.config, "worker_storage_profile", "storage")
        storage_available = False
        if storage_profile in profiles:
            try:
                runtime_config = build_profile_config(
                    self.profile_manager.base_config, storage_profile
                )
                storage_available = Path(runtime_config.tdl_export_storage).exists()
            except Exception:
                storage_available = False
        return {
            "profiles": profiles,
            "storage_profile": storage_profile,
            "storage_profile_available": storage_available,
            "workspace": Path(getattr(self.config, "utility_workspace_root", "/workspace")).is_dir(),
        }

    def _unhandled_resource(self, command: dict[str, Any], exc: Exception) -> None:
        LOGGER.exception("Worker queue failed for job %s", command.get("job_id"))
        self._failed(command, exc)

    def _resource_keys_for_command(self, command: dict[str, Any]) -> set[str]:
        profile = str(command.get("profile") or "default")
        kind = str(command.get("kind") or "unknown")
        worker = str(command.get("worker") or self.config.backup_node_name)
        keys: set[str] = {f"profile:{profile}:worker:{worker}:kind:{kind}"}
        if kind in {"export", "leave"}:
            if kind == "export" and bool((command.get("payload") or {}).get("quick_mode")):
                retry = (command.get("payload") or {}).get("quick_retry") or {}
                retry = retry if isinstance(retry, dict) else {}
                retry_phase = str(
                    retry.get("resume_phase")
                    or payload.get("quick_phase")
                    or retry.get("retry_phase")
                    or "exporting"
                ).strip().lower()
                stage_job_id = str(retry.get("stage_job_id") or command.get("job_id") or "")
                if stage_job_id:
                    keys.add(f"worker:{worker}:quick-stage:{stage_job_id}")
                if retry_phase not in {"exporting", "auto"}:
                    keys.discard(f"profile:{profile}:worker:{worker}:kind:{kind}")
                else:
                    keys.add(f"profile:{profile}:worker:{worker}:tdl:export")
            else:
                keys.add(f"profile:{profile}:worker:{worker}:tdl:export")
        elif kind == "storage_upload":
            keys = {f"worker:{worker}:kind:storage_upload", f"worker:{worker}:tdl:storage"}
        elif kind in {"download", "download_clear_failed"}:
            keys.add(f"profile:{profile}:worker:{worker}:tdl:download")
        elif kind == "backup_node":
            # Current backup snapshots all profiles and uploads through the
            # export client. Keep this conservative until a dedicated lane is
            # provisioned.
            for name in self.profile_manager.list_profiles():
                keys.add(f"profile:{name}:tdl:export")
                keys.add(f"profile:{name}:tdl:download")
        elif kind == "utility":
            payload = command.get("payload") or {}
            folders = payload.get("folders") or []
            if folders:
                keys = set()
                for folder in folders:
                    normalized = str(folder).replace("\\", "/").rstrip("/")
                    parts = [part for part in normalized.split("/") if part]
                    start = 2 if parts and parts[0].casefold() == "workspace" else 1
                    if len(parts) < start:
                        parts = ["workspace"]
                        start = 1
                    for index in range(start, len(parts) + 1):
                        ancestor = "/" + "/".join(parts[:index])
                        keys.add(
                            f"worker:{worker}:workspace:{ancestor}"
                        )
            else:
                keys.add(
                    f"worker:{worker}:workspace"
                )
        elif kind.startswith("artifact_"):
            payload = command.get("payload") or {}
            artifact_ids = payload.get("artifact_ids") or payload.get("artifact_id") or []
            if not isinstance(artifact_ids, (list, tuple, set)):
                artifact_ids = [artifact_ids]
            keys.update(
                f"worker:{worker}:artifact:{item}"
                for item in artifact_ids
            )
        return keys


    def _cancel_error(self, command: dict[str, Any]) -> str:
        staging = self._quick_staging_path(command)
        if staging:
            return f"Job dihentikan oleh user (Ctrl+C). Staging dipertahankan di {staging}."
        return "Job dihentikan oleh user (Ctrl+C)."

    def _run(self, command: dict[str, Any], resource_keys: set[str]) -> None:
        del resource_keys
        job_id = str(command["job_id"])
        profile = str(command["profile"])
        kind = str(command["kind"])
        started_at = utc_now().isoformat()
        snapshot = JobLogSnapshot()
        self._job_log.snapshot = snapshot
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        quick_settings = payload.get("quick_settings") if isinstance(payload, dict) else {}
        secrets = [
            str(payload.get("password") or "") if isinstance(payload, dict) else "",
            str(quick_settings.get("compress_password") or "")
            if isinstance(quick_settings, dict)
            else "",
        ]
        self._job_log.audit = CommandMilestoneRecorder(
            self.publisher,
            job_id,
            [value for value in secrets if value],
            before_command=lambda: self._wait_if_paused(job_id),
        )
        self._job_log.job_id = job_id
        self._job_log.secrets = [value for value in secrets if value]
        try:
            self._job_log.file_path = self._quick_log_path(command)
        except Exception:
            self._job_log.file_path = None
            LOGGER.warning(
                "Could not initialize Quick Mode worker log for %s",
                job_id,
                exc_info=True,
            )
        if isinstance(self._job_log.file_path, Path):
            self._register_quick_log(job_id, self._job_log.file_path)
        self._job_log.heartbeat_at = 0.0
        self._append_job_log(
            f"[job {job_id} started: {kind} "
            f"event_sequence_start={command.get('event_sequence_start', 'missing')}]"
        )
        heartbeat_stop = threading.Event()
        heartbeat_thread: threading.Thread | None = None
        with self._lock:
            self._active[job_id] = (profile, kind)
            self._active_commands[job_id] = command
            self._pause_events.setdefault(job_id, threading.Event())
            self._log_snapshots[job_id] = snapshot
        try:
            self._wait_if_paused(job_id)
            self.publisher.emit(
                job_id,
                "running",
                "started",
                progress={
                    "phase": "starting",
                    "started_at": started_at,
                    "message": f"{kind} mulai diproses",
                    "overall": {},
                    "item": {},
                    "transfer": {},
                    "counters": {"succeeded": 0, "failed": 0, "skipped": 0},
                    "indeterminate": True,
                },
            )
            heartbeat_thread = threading.Thread(
                target=self._worker_heartbeat_loop,
                args=(job_id, heartbeat_stop),
                daemon=True,
                name=f"worker-heartbeat-{job_id[:8]}",
            )
            heartbeat_thread.start()
            result = self._execute(command)
            self._wait_if_paused(job_id)
            with self._lock:
                cancelled = job_id in self._cancel_requested
            self._append_job_log("[job terminated]" if cancelled else "[job completed]")
            self._publish_log_snapshot(job_id, snapshot)
            if cancelled:
                phase = self._quick_terminal_phase(command, "cancelled")
                staging_path = self._quick_staging_path(command)
                self.publisher.emit(
                    job_id,
                    "cancelled",
                    "cancelled",
                    progress={
                        "phase": phase,
                        **({"terminal_phase": "cancelled"} if phase != "cancelled" else {}),
                        **({"staging_path": staging_path, "staging_cleaned": False} if staging_path else {}),
                        "finished_at": utc_now().isoformat(),
                    },
                    error={"code": "JOB_TERMINATED", "message": self._cancel_error(command)},
                )
            else:
                self.publisher.emit(
                    job_id,
                    "succeeded",
                    "completed",
                    progress={
                        "phase": "completed",
                        "finished_at": utc_now().isoformat(),
                    },
                    result={"value": json_value(result)},
                )
        except Exception as exc:
            LOGGER.exception("Job %s (%s) failed", job_id, kind)
            self._append_job_log(f"[job failed: {exc}]")
            self._publish_log_snapshot(job_id, snapshot)
            with self._lock:
                if isinstance(exc, (ProcessStalledError, TDLStalledError)):
                    self._cancel_requested.add(job_id)
                cancelled = job_id in self._cancel_requested
            if cancelled:
                phase = self._quick_terminal_phase(command, "cancelled")
                staging_path = self._quick_staging_path(command)
                stalled = isinstance(exc, (ProcessStalledError, TDLStalledError))
                self.publisher.emit(
                    job_id,
                    "cancelled",
                    "cancelled",
                    progress={
                        "phase": phase,
                        **({"terminal_phase": "cancelled"} if phase != "cancelled" else {}),
                        **({"staging_path": staging_path, "staging_cleaned": False} if staging_path else {}),
                        "finished_at": utc_now().isoformat(),
                    },
                    error=(
                        {
                            "code": "JOB_STALLED",
                            "message": (
                                "Job dibatalkan karena tidak ada progress "
                                f"selama {exc.timeout_seconds} detik."
                            ),
                        }
                        if stalled
                        else {
                            "code": "JOB_TERMINATED",
                            "message": self._cancel_error(command),
                        }
                    ),
                )
            else:
                self._failed(
                    command,
                    exc,
                    started_at=started_at,
                    phase=self._quick_terminal_phase(command, "failed"),
                    staging_path=self._quick_staging_path(command),
                )
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=2)
            file_path = getattr(self._job_log, "file_path", None)
            if isinstance(file_path, Path):
                self._compact_quick_log(file_path)
            self.publisher.unregister_audit_callback(job_id)
            with self._quick_log_state_lock:
                self._quick_log_paths.pop(job_id, None)
                self._quick_log_locks.pop(job_id, None)
                self._quick_log_named_progress.pop(job_id, None)
            del self._job_log.snapshot
            del self._job_log.audit
            for name in ("job_id", "secrets", "file_path", "heartbeat_at"):
                if hasattr(self._job_log, name):
                    delattr(self._job_log, name)
            with self._lock:
                self._active.pop(job_id, None)
                self._active_commands.pop(job_id, None)
                self._pause_events.pop(job_id, None)
                # Job IDs are stable across retries. Allow the next attempt
                # to be enqueued after this run has reached a terminal event.
                self._known.discard(job_id)
                self._log_snapshots.pop(job_id, None)
                self._utility_runners.pop(job_id, None)
                self._rclone_runners.pop(job_id, None)
                self._quick_thumbnail_builders.pop(job_id, None)
                self._quick_export_clients.pop(job_id, None)
                self._quick_download_clients.pop(job_id, None)
                self._quick_active.discard(job_id)
                self._quick_stage_jobs.pop(job_id, None)
                self._cancel_requested.discard(job_id)
            self.publisher.forget(job_id)

    def _failed(
        self,
        command: dict[str, Any],
        exc: Exception,
        *,
        started_at: str | None = None,
        phase: str | None = None,
        staging_path: str | None = None,
    ) -> None:
        try:
            self.publisher.emit(
                str(command["job_id"]),
                "failed",
                "failed",
                progress={
                    "phase": phase or "failed",
                    **({"terminal_phase": "failed"} if phase and phase != "failed" else {}),
                    **({"started_at": started_at} if started_at else {}),
                    **({"staging_path": staging_path, "staging_cleaned": False} if staging_path else {}),
                    "finished_at": utc_now().isoformat(),
                },
                error={
                    "code": "WORKER_JOB_FAILED",
                    "message": str(exc)[:1000],
                },
            )
        except Exception:
            LOGGER.exception("Could not publish failure for job %s", command.get("job_id"))


    def _append_job_log(self, line: str) -> None:
        snapshot = getattr(self._job_log, "snapshot", None)
        if snapshot is not None:
            snapshot.add(line)
        file_path = getattr(self._job_log, "file_path", None)
        if isinstance(file_path, Path):
            secrets = getattr(self._job_log, "secrets", [])
            safe_lines = sanitize_text(str(line), secrets).splitlines() or [str(line)]
            job_id = getattr(self._job_log, "job_id", None)
            if job_id:
                for value in safe_lines:
                    self._write_quick_log_line(
                        str(job_id), value, secrets, fallback_path=file_path
                    )

        # Raw TDL/utility/ffmpeg output is meaningful activity even when it
        # does not contain a parseable percentage. Refresh the backend
        # watchdog from that activity, but throttle network calls so a busy
        # subprocess cannot be slowed by telemetry.
        job_id = getattr(self._job_log, "job_id", None)
        if job_id:
            now = time.monotonic()
            last = float(getattr(self._job_log, "heartbeat_at", 0.0) or 0.0)
            if now - last >= 15.0:
                self._job_log.heartbeat_at = now
                try:
                    self.publisher.emit(
                        str(job_id),
                        "running",
                        "progress.snapshot",
                        transient=True,
                        progress={
                            "worker_output_at": utc_now().isoformat(),
                            "heartbeat": True,
                        },
                    )
                except Exception:
                    LOGGER.warning(
                        "Could not publish worker output heartbeat for %s",
                        job_id,
                        exc_info=True,
                    )

    def _worker_heartbeat_loop(
        self, job_id: str, stop_event: threading.Event
    ) -> None:
        """Keep backend liveness independent from noisy subprocess output.

        A Quick Mode upload can spend a long time inside Telegram/rclone even
        when no new parseable progress line is produced.  This heartbeat is
        deliberately small and advisory; it never changes the physical job
        result and stops before the executor publishes its terminal event.
        """
        while not stop_event.wait(10.0):
            try:
                with self._lock:
                    pause_event = self._pause_events.get(job_id)
                    is_paused = pause_event is not None and pause_event.is_set()
                self.publisher.emit(
                    job_id,
                    "paused" if is_paused else "running",
                    "progress.snapshot",
                    transient=True,
                    progress={
                        "heartbeat": True,
                        "worker_heartbeat_at": utc_now().isoformat(),
                    },
                )
            except Exception:
                LOGGER.warning(
                    "Could not publish worker heartbeat for %s",
                    job_id,
                    exc_info=True,
                )

    def _wait_if_paused(self, job_id: str) -> None:
        while True:
            with self._lock:
                pause_event = self._pause_events.get(job_id)
                is_paused = pause_event is not None and pause_event.is_set()
            if not is_paused:
                return
            self._set_job_process_paused(job_id, True)
            pause_event.wait(timeout=1.0)

    def _command_callback(self):
        return getattr(self._job_log, "audit", None)

    def _publish_log_snapshot(self, job_id: str, snapshot: JobLogSnapshot) -> None:
        self.publisher.emit(
            job_id,
            "running",
            "log.snapshot",
            result={"log": snapshot.value()},
        )

    def job_log_snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            snapshot = self._log_snapshots.get(job_id)
        return snapshot.value() if snapshot is not None else None

    @contextmanager
    def _capture_tdl_output(self, client, *, log_callback=None, command_callback=None):
        previous = client.output_callback
        previous_command = getattr(client, "command_callback", None)

        def capture(line: str) -> None:
            (log_callback or self._append_job_log)(line)
            if previous is not None:
                previous(line)

        client.output_callback = capture
        callback = command_callback or self._command_callback()
        if callback is not None:
            client.command_callback = callback
        try:
            yield
        finally:
            client.output_callback = previous
            if hasattr(client, "command_callback"):
                client.command_callback = previous_command

    @contextmanager
    def _capture_tdl_commands(self, client):
        previous = getattr(client, "command_callback", None)
        callback = self._command_callback()
        if callback is not None:
            client.command_callback = callback
        try:
            yield
        finally:
            if hasattr(client, "command_callback"):
                client.command_callback = previous

    @contextmanager
    def _capture_tdl_progress(self, client, callback):
        previous = client.progress_callback

        def capture(progress) -> None:
            callback(progress)
            if previous is not None:
                previous(progress)

        client.progress_callback = capture
        try:
            yield
        finally:
            client.progress_callback = previous

    @contextmanager
    def _download_progress_operation(self, runtime, callback):
        """Bind the shared tracker callback only while owning its TDL lock."""
        with runtime.download_operation_lock:
            previous = runtime.download_progress.set_event_callback(callback)
            try:
                yield
            finally:
                runtime.download_progress.set_event_callback(previous)

    def _execute(self, command: dict[str, Any]) -> Any:
        kind = str(command["kind"])
        handlers = {
            "export": self._export,
            "leave": self._leave,
            "download": self._download,
            "download_clear_failed": self._download_clear_failed,
            "artifact_inventory": self._artifact_inventory,
            "artifact_delete": self._artifact_delete,
            "utility": self._utility,
            "storage_upload": self._storage_upload,
            "backup_node": self._backup,
        }
        handler = handlers.get(kind)
        if handler is None:
            raise ValueError(f"Jenis job tidak dikenal: {kind}.")
        return handler(command)


    def _export(self, command: dict[str, Any]) -> Any:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        payload = command["payload"]
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        quick_mode = bool(payload.get("quick_mode"))
        stage_root: Path | None = None
        quick_manifest: dict[str, Any] = {}
        resume_phase = "exporting"
        if quick_mode:
            with self._lock:
                self._quick_active.add(str(command["job_id"]))
            stage_root, quick_manifest, resume_phase, _ = self._prepare_quick_stage(
                command, runtime
            )
            retry = payload.get("quick_retry") or {}
            requested_phase = str(
                retry.get("resume_phase")
                or payload.get("quick_phase")
                or retry.get("retry_phase")
                or "exporting"
            ).strip().lower() if isinstance(retry, dict) else str(payload.get("quick_phase") or "exporting").strip().lower()
            if resume_phase == "exporting" and requested_phase != "exporting":
                self._clear_quick_stage(stage_root)
                quick_manifest = {
                    "version": 2,
                    "stage_job_id": str(quick_manifest.get("stage_job_id") or command["job_id"]),
                    "quick_operation_id": str(quick_manifest.get("quick_operation_id") or command["job_id"]),
                    "phase": "exporting",
                }
                write_quick_manifest(stage_root, quick_manifest)
            restored = self._quick_manifest_export(quick_manifest)
            can_resume = resume_phase != "exporting" and (
                restored is not None
                or resume_phase in {"thumbnailing", "compressing", "uploading", "cleanup"}
                or (
                    resume_phase == "downloading"
                    and bool(self._quick_json_path(runtime, quick_manifest, stage_root))
                )
            )
            if can_resume:
                reporter.report(
                    phase=resume_phase,
                    message=f"Melanjutkan Quick Mode dari fase {resume_phase}",
                    item={"name": str(quick_manifest.get("folder_name") or "Quick Mode")},
                    indeterminate=True,
                    force=True,
                )
                restored_result, restored_stats = restored or (
                    None,
                    dict(quick_manifest.get("stats") or {}),
                )
                return self._quick_export_pipeline(
                    command,
                    runtime,
                    restored_result,
                    restored_stats,
                    reporter,
                    stage_root=stage_root,
                    manifest=quick_manifest,
                    resume_phase=resume_phase,
                )
        export_start_id, export_end_id = self._export_retry_range(payload)
        url = payload.get("url")
        if not url:
            from urllib.parse import quote

            chat_ref = str(payload["chat_ref"]).strip()
            if not chat_ref.lstrip("-").isdigit() and not chat_ref.startswith("@"):
                chat_ref = f"@{chat_ref}"
            start_id = max(1, int(payload.get("start_id") or 1))
            label = str(payload.get("label") or "").strip()
            url = f"https://{runtime.config.tme3_host}/c/{quote(chat_ref, safe='@-')}/{start_id}"
            if label:
                url += f"/{quote(label, safe='')}"
        reporter.report(
            phase="connecting",
            message="Menghubungkan sesi Telegram untuk export",
            item={"name": str(payload.get("chat_ref") or url)},
            indeterminate=True,
            force=True,
        )
        if quick_mode:
            reporter.report(
                phase="exporting",
                message="Mengekspor JSON untuk Quick Mode",
                item={"name": str(payload.get("chat_ref") or url)},
                indeterminate=True,
                force=True,
            )

        def export_progress(progress) -> None:
            if not _has_transfer_telemetry(progress):
                return
            reporter.report(
                phase="exporting",
                message=f"Export {progress.file_name or payload.get('chat_ref') or 'chat'}",
                item={
                    "name": progress.file_name or str(payload.get("chat_ref") or url),
                    "index": progress.fraction_current,
                    "total": progress.fraction_total,
                    "percent": progress.percent,
                },
                transfer=reporter.tdl_transfer(progress),
                indeterminate=progress.percent is None,
            )

        export_client = runtime.export_tdl_client
        if quick_mode and stage_root is not None:
            export_client = self._quick_isolated_client(runtime, stage_root, "export")
            with self._lock:
                self._quick_export_clients[str(command["job_id"])] = export_client
        try:
            with runtime.export_operation_lock:
                with self._capture_tdl_output(export_client):
                    with self._capture_tdl_progress(
                        export_client, export_progress
                    ):
                        result = runtime.export_service.export_from_url(
                            str(url),
                            use_url_message_id=bool(payload.get("use_url_message_id", False)),
                            save_source=(
                                bool(payload["save_source"])
                                if "save_source" in payload
                                and payload.get("save_source") is not None
                                else None
                            ),
                            export_start_id=export_start_id,
                            export_end_id=export_end_id,
                            tdl_client=export_client if quick_mode else None,
                            output_dir=stage_root if quick_mode else None,
                        )
        finally:
            if quick_mode:
                with self._lock:
                    self._quick_export_clients.pop(str(command["job_id"]), None)
        stats = inspect_export_json(result.export_path)
        json_ready_progress = reporter.report(
            phase="json_ready",
            message=f"File JSON berhasil dibuat: {result.export_path.name}",
            overall={
                "current": 1,
                "total": 1,
                "percent": 100,
                "unit": "file",
            },
            item={"name": result.export_path.name, "percent": 100},
            extra={
                "export_start_id": result.start_id,
                "export_end_id": result.end_id,
            },
            force=True,
        )
        reporter.milestone(
            "export.json_ready",
            progress=json_ready_progress,
            result={
                "json_name": result.export_path.name,
                "exported_count": result.exported_count,
                "media_count": stats.get("media_count", 0),
                "export_start_id": result.start_id,
                "export_end_id": result.end_id,
            },
        )
        if quick_mode:
            # The two TDL sessions are independent: export uses user1/.tdl,
            # while the next phase uses root/.tdl.  Do not keep the export
            # queue reservation while this job downloads or compresses.
            self._release_quick_export_lane(command)
            if stage_root is not None:
                quick_manifest.update(
                    {
                        "phase": "downloading",
                        "folder_name": quick_folder_name(result.export_path),
                        "export_json_name": result.export_path.name,
                        "export_result": json_value(asdict(result)),
                        "stats": json_value(stats),
                    }
                )
                self._ensure_quick_export_json(
                    result.export_path, stage_root, quick_manifest
                )
                write_quick_manifest(stage_root, quick_manifest)
            if stats.get("media_count") == 0:
                reporter.report(
                    phase="failed",
                    message="Quick Mode gagal: export tidak memiliki foto maupun video.",
                    overall={
                        "current": result.exported_count,
                        "total": result.exported_count,
                        "percent": 100,
                        "unit": "messages",
                    },
                    counters={"succeeded": result.exported_count, "failed": 0},
                    force=True,
                )
                discard_export_without_media(result.export_path, stats)
                raise QuickModeError(
                    "Quick Mode gagal: export tidak memiliki foto maupun video."
                )
            if stage_root is None:
                raise QuickModeError("Staging Quick Mode belum disiapkan.")
            return self._quick_export_pipeline(
                command,
                runtime,
                result,
                stats,
                reporter,
                stage_root=stage_root,
                manifest=quick_manifest,
                resume_phase="downloading",
            )
        if stats.get("media_count") == 0:
            artifact_deleted = False
            artifact_delete_error = None
            try:
                artifact_deleted = discard_export_without_media(result.export_path, stats)
            except OSError as exc:
                # Export itself succeeded. Keep that result visible, but make
                # cleanup failure explicit so the leftover file can be fixed
                # by a later inventory/maintenance pass.
                artifact_delete_error = str(exc)
                LOGGER.warning(
                    "Could not remove media-less export %s: %s",
                    result.export_path,
                    exc,
                )
            reporter.report(
                phase="completed",
                message=(
                    f"Export selesai: {result.exported_count} message tanpa media; "
                    + (
                        "JSON dihapus otomatis"
                        if artifact_deleted
                        else "JSON gagal dihapus"
                    )
                ),
                overall={
                    "current": result.exported_count,
                    "total": result.exported_count,
                    "percent": 100,
                    "unit": "messages",
                },
                counters={"succeeded": result.exported_count, "failed": 0, "skipped": 0},
                force=True,
            )
            empty_result = {
                **asdict(result),
                **stats,
                "artifact_deleted": artifact_deleted,
                "artifact_delete_reason": "no_media",
            }
            if artifact_delete_error:
                empty_result["artifact_delete_error"] = artifact_delete_error
            # No artifact.discovered event: a media-less JSON must never enter
            # the download catalog, even if the cleanup encountered an error.
            return empty_result
        artifact = {
            **stats,
            "profile": str(command["profile"]),
            "worker": str(command.get("worker") or self.config.backup_node_name),
            "export_job_id": str(command["job_id"]),
            "filename": result.export_path.name,
            "artifact_key": result.export_path.name,
            "status": "pending",
        }
        reporter.report(
            phase="completed",
            message=(
                f"Export selesai: {result.exported_count} message"
                + (" dengan media" if result.has_media else "")
            ),
            overall={
                "current": result.exported_count,
                "total": result.exported_count,
                "percent": 100,
                "unit": "messages",
            },
            counters={"succeeded": result.exported_count},
            force=True,
        )
        self.publisher.emit(
            str(command["job_id"]),
            "running",
            "artifact.discovered",
            result={"artifact": artifact},
        )
        return {**asdict(result), **stats}


    def _leave(self, command: dict[str, Any]) -> dict[str, Any]:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        with runtime.export_operation_lock:
            result = runtime.leave_service.leave(
                [str(item) for item in command["payload"].get("chat_refs", [])],
                output_callback=self._append_job_log,
                command_callback=self._command_callback(),
            )
            deleted = runtime.state_store.delete_sources(result.succeeded)
        return {"succeeded": deleted, "failed": result.failed}
