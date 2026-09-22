from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import shutil
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from tme3bot.backup_service import BackupService, sha256_file
from tme3bot.domain.models import utc_now
from tme3bot.export_catalog import discard_export_without_media, inspect_export_json
from tme3bot.infrastructure.http_client import JsonHttpError, request_json
from tme3bot.profile_queue import ResourceAwareQueue
from tme3bot.progress_reporter import ProgressReporter
from tme3bot.profiles import build_profile_config
from tme3bot.rclone import RcloneRunner
from tme3bot.service import ExportJobResult
from tme3bot.storage_catalog import build_storage_caption
from tme3bot.tdl import ProcessStalledError, TDLStalledError
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


def storage_relative_folders(root: Path) -> list[str]:
    """Return nested directories, including empty ones, as portable paths."""
    return [
        path.relative_to(root).as_posix()
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_dir())
    ]


def storage_logical_folder(
    root: Path, path: Path, destination_path: str, preserve_structure: bool
) -> tuple[str, str]:
    relative = path.relative_to(root).parent.as_posix() if preserve_structure else "."
    relative = "" if relative == "." else relative
    logical = "/".join(
        part for part in (str(destination_path).strip("/"), relative) if part
    )
    return logical, relative


def _utility_progress_message(utility: str, phase: str, item: str) -> str:
    labels = {
        "compressing": "Mengompres",
        "extracting": "Mengekstrak",
        "item_completed": "Selesai memproses",
        "item_failed": "Gagal memproses",
        "pindah_starting": "Menyiapkan pemindahan",
        "export_starting": "Menyiapkan organizer export",
    }
    action = labels.get(phase, f"Menjalankan {utility}")
    return f"{action} {item}".strip()


def _has_transfer_telemetry(progress) -> bool:
    return any(
        value is not None
        for value in (
            progress.percent,
            progress.speed_bps,
            progress.eta_seconds,
            progress.transferred_bytes,
        )
    )


class JobLogSnapshot:
    """Bounded raw command output retained with the persistent job history."""

    max_lines = 5_000
    max_characters = 1_000_000

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._characters = 0
        self.truncated = False
        self._lock = threading.RLock()

    def add(self, value: str) -> None:
        with self._lock:
            for raw_line in str(value).splitlines() or [str(value)]:
                line = raw_line.rstrip()
                if not line:
                    continue
                if len(self._lines) >= self.max_lines or self._characters + len(line) + 1 > self.max_characters:
                    self.truncated = True
                    return
                self._lines.append(line)
                self._characters += len(line) + 1

    def value(self) -> dict[str, Any]:
        with self._lock:
            return {
                "lines": list(self._lines),
                "line_count": len(self._lines),
                "truncated": self.truncated,
            }


def json_value(value: Any) -> Any:
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)


class WorkerEventPublisher:
    def __init__(self, backend_url: str, token: str) -> None:
        self.backend_url = backend_url
        self.token = token
        self._sequences: dict[str, int] = {}
        self._lock = threading.RLock()

    def emit(
        self,
        job_id: str,
        status: str,
        event_type: str,
        *,
        transient: bool = False,
        progress: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            sequence = self._sequences.get(job_id, 1) + 1
            self._sequences[job_id] = sequence
        payload = {
            "sequence": sequence,
            "status": status,
            "event_type": event_type,
            "transient": transient,
            "progress": json_value(progress or {}),
            "result": json_value(result) if result is not None else None,
            "error": json_value(error) if error is not None else None,
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                request_json(
                    self.backend_url,
                    self.token,
                    "POST",
                    f"/internal/v1/jobs/{job_id}/events",
                    payload,
                    timeout=30,
                )
                return
            except Exception as exc:
                if isinstance(exc, JsonHttpError) and exc.status == 409:
                    # A terminate request or a replay can race with the
                    # worker's final event.  The backend's event endpoint is
                    # idempotent; once it has made the job terminal, late
                    # telemetry/final events must not make the worker fail.
                    LOGGER.info(
                        "Ignoring stale event %s for completed job %s",
                        event_type,
                        job_id,
                    )
                    return
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def begin(self, job_id: str, sequence_start: int | None) -> None:
        """Seed event numbering for a reused job ID."""
        if sequence_start is None:
            return
        with self._lock:
            self._sequences[str(job_id)] = max(
                self._sequences.get(str(job_id), 0), int(sequence_start)
            )

    def forget(self, job_id: str) -> None:
        with self._lock:
            self._sequences.pop(job_id, None)


class WorkerJobExecutor:
    """Executes domain jobs and publishes JSON events; no UI dependency."""

    def __init__(self, config, profile_manager, publisher: WorkerEventPublisher) -> None:
        self.config = config
        self.profile_manager = profile_manager
        self.publisher = publisher
        self._active: dict[str, tuple[str, str]] = {}
        self._utility_runners: dict[str, UtilityRunner] = {}
        self._rclone_runners: dict[str, RcloneRunner] = {}
        self._quick_thumbnail_builders: dict[str, QuickThumbnailBuilder] = {}
        self._quick_export_clients: dict[str, Any] = {}
        self._quick_download_clients: dict[str, Any] = {}
        self._quick_active: set[str] = set()
        self._cancel_requested: set[str] = set()
        self._known: set[str] = set()
        self._lock = threading.RLock()
        self._job_log = threading.local()
        self._log_snapshots: dict[str, JobLogSnapshot] = {}
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
        self.publisher.begin(job_id, command.get("event_sequence_start"))
        with self._lock:
            if job_id in self._known:
                return self._jobs.queue_size()
            self._known.add(job_id)
        execution = command.get("execution") or {}
        resources = execution.get("resource_keys") or self._resource_keys_for_command(command)
        position = self._jobs.enqueue(
            resources,
            command,
            priority=0 if command.get("payload", {}).get("priority") == "next" else 100,
            job_id=job_id,
        )
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
        if self._jobs.cancel_pending(job_id):
            with self._lock:
                self._known.discard(job_id)
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

        cancelled = False

        def interrupt(label: str, callback) -> None:
            nonlocal cancelled
            if callback is None:
                return
            try:
                cancelled = bool(callback()) or cancelled
            except Exception:
                # Cancellation is best effort.  One missing runtime/client
                # must not turn the API request into an HTTP 500 or prevent
                # the remaining resources from receiving the signal.
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

    def _release_quick_export_lane(self, command: dict[str, Any]) -> None:
        """Free the worker's export lane after Quick JSON is ready."""
        execution = command.get("execution") or {}
        keys = set(execution.get("resource_keys") or self._resource_keys_for_command(command))
        export_keys = {
            key
            for key in keys
            if ":kind:export" in str(key) or ":tdl:export" in str(key)
        }
        if export_keys:
            self._jobs.release_resources(str(command["job_id"]), export_keys)

    def _quick_terminal_phase(self, command: dict[str, Any], fallback: str) -> str:
        """Read the last persisted Quick phase for failed/cancelled retries."""
        payload = command.get("payload") or {}
        if not bool(payload.get("quick_mode")):
            return fallback
        retry = payload.get("quick_retry") or {}
        retry = retry if isinstance(retry, dict) else {}
        stage_id = str(retry.get("stage_job_id") or command.get("job_id") or "")
        try:
            stage = migrate_legacy_quick_stage(self._quick_workspace(self.config), stage_id)
            phase = str(read_quick_manifest(stage).get("phase") or "").strip().lower()
        except Exception:
            phase = ""
        return phase if phase in {"exporting", "downloading", "thumbnailing", "compressing", "uploading", "cleanup"} else fallback

    def _quick_staging_path(self, command: dict[str, Any]) -> str | None:
        payload = command.get("payload") or {}
        if not bool(payload.get("quick_mode")):
            return None
        retry = payload.get("quick_retry") or {}
        retry = retry if isinstance(retry, dict) else {}
        stage_id = str(retry.get("stage_job_id") or command.get("job_id") or "")
        try:
            stage = migrate_legacy_quick_stage(self._quick_workspace(self.config), stage_id)
        except Exception:
            return None
        return str(stage) if stage.exists() else None

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
        snapshot.add(f"[job {job_id} started: {kind}]")
        self._job_log.snapshot = snapshot
        with self._lock:
            self._active[job_id] = (profile, kind)
            self._log_snapshots[job_id] = snapshot
        try:
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
            result = self._execute(command)
            with self._lock:
                cancelled = job_id in self._cancel_requested
            snapshot.add("[job terminated]" if cancelled else "[job completed]")
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
            snapshot.add(f"[job failed: {exc}]")
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
            del self._job_log.snapshot
            with self._lock:
                self._active.pop(job_id, None)
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
    def _capture_tdl_output(self, client):
        previous = client.output_callback

        def capture(line: str) -> None:
            self._append_job_log(line)
            if previous is not None:
                previous(line)

        client.output_callback = capture
        try:
            yield
        finally:
            client.output_callback = previous

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

    @staticmethod
    def _quick_workspace(config) -> Path:
        return Path(getattr(config, "utility_workspace_root", "/workspace")).resolve()

    def _quick_isolated_client(self, runtime, stage_root: Path, mode: str):
        """Return a per-stage TDL client, with a test/runtime fallback.

        Production profile runtimes always expose the source Bolt directory.
        Lightweight test doubles from older integrations do not, so those
        continue using their supplied client rather than copying the current
        working directory into staging.
        """
        config = getattr(runtime, "config", None)
        if config is None:
            return getattr(runtime, f"{mode}_tdl_client")
        source_storage = getattr(config, f"tdl_{mode}_storage", None)
        source_home = getattr(config, f"tdl_{mode}_home", None)
        if not source_storage or not Path(source_storage).is_dir():
            return getattr(runtime, f"{mode}_tdl_client")
        return ensure_quick_tdl_client(
            stage_root,
            mode=mode,
            source_storage=Path(source_storage),
            source_home=Path(source_home) if source_home else None,
            namespace=str(getattr(config, f"tdl_{mode}_namespace", "default")),
            run_as_user=getattr(config, f"tdl_{mode}_user", None),
            stall_timeout_seconds=int(
                getattr(config, f"tdl_{mode}_stall_timeout_seconds", 0)
            ),
            progress_callback=getattr(
                getattr(runtime, f"{mode}_tdl_client", None), "progress_callback", None
            ),
            output_callback=getattr(
                getattr(runtime, f"{mode}_tdl_client", None), "output_callback", None
            ),
        )

    def _prepare_quick_stage(
        self, command: dict[str, Any], runtime
    ) -> tuple[Path, dict[str, Any], str, str]:
        payload = command.get("payload") or {}
        retry = payload.get("quick_retry") or {}
        retry = retry if isinstance(retry, dict) else {}
        job_id = str(command["job_id"])
        stage_job_id = str(retry.get("stage_job_id") or job_id)
        workspace = self._quick_workspace(self.config)
        stage_root = migrate_legacy_quick_stage(workspace, stage_job_id)
        stage_root.mkdir(parents=True, exist_ok=True)
        ensure_quick_stage_writable(
            stage_root,
            getattr(getattr(runtime, "config", None), "tdl_export_user", None),
        )
        requested_phase = str(
            retry.get("resume_phase")
            or payload.get("quick_phase")
            or retry.get("retry_phase")
            or "exporting"
        ).strip().lower()
        if requested_phase not in {"auto", *QUICK_PHASES}:
            requested_phase = "exporting"
        operation_id = str(retry.get("quick_operation_id") or stage_job_id)
        manifest = read_quick_manifest(stage_root)
        if requested_phase == "exporting":
            if retry:
                self._clear_quick_stage(stage_root)
            manifest = {
                "version": 2,
                "stage_job_id": stage_job_id,
                "quick_operation_id": operation_id,
                "profile": str(command.get("profile") or ""),
                "worker": str(command.get("worker") or self.config.backup_node_name),
                "phase": "exporting",
                "retry_of": retry.get("retry_of"),
            }
        else:
            manifest.setdefault("version", 2)
            manifest.setdefault("stage_job_id", stage_job_id)
            manifest.setdefault("quick_operation_id", operation_id)
            manifest.setdefault("profile", str(command.get("profile") or ""))
            manifest.setdefault("worker", str(command.get("worker") or self.config.backup_node_name))
            manifest.setdefault("retry_of", retry.get("retry_of"))
        write_quick_manifest(stage_root, manifest)
        effective_phase = self._resolve_quick_retry_phase(
            "auto" if requested_phase == "auto" else requested_phase,
            stage_root,
            manifest,
            runtime,
        )
        if effective_phase != "exporting":
            # ``resume_phase=auto`` conservatively reserves the export lane
            # until the physical folder proves that export is unnecessary.
            # Release it before download/thumbnail/compress/upload so another
            # stage on the same profile-worker can export concurrently.
            self._release_quick_export_lane(command)
        # _resolve_quick_retry_phase may reconstruct the manifest from the
        # retained raw export JSON. Persist that reconstruction before the
        # worker starts the resumed phase so a second retry has the same
        # source of truth even when the backend record is incomplete.
        write_quick_manifest(stage_root, manifest)
        return stage_root, manifest, effective_phase, stage_job_id

    @staticmethod
    def _clear_quick_stage(stage_root: Path) -> None:
        for child in Path(stage_root).iterdir():
            if child.name == "quickmode.json":
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

    @staticmethod
    def _quick_manifest_export(
        manifest: dict[str, Any],
    ) -> tuple[ExportJobResult, dict[str, Any]] | None:
        raw_result = manifest.get("export_result")
        raw_stats = manifest.get("stats")
        if not isinstance(raw_result, dict) or not isinstance(raw_stats, dict):
            return None
        try:
            result = ExportJobResult(
                status=str(raw_result.get("status") or "exported"),
                chat_ref=str(raw_result.get("chat_ref") or ""),
                requested_label=(
                    str(raw_result["requested_label"])
                    if raw_result.get("requested_label") is not None
                    else None
                ),
                export_path=Path(str(raw_result.get("export_path") or "")),
                start_id=int(raw_result.get("start_id") or 1),
                latest_id=(
                    int(raw_result["latest_id"])
                    if raw_result.get("latest_id") is not None
                    else None
                ),
                exported_count=int(raw_result.get("exported_count") or 0),
                has_media=bool(raw_result.get("has_media")),
                warmup_required=bool(raw_result.get("warmup_required")),
                warning=(
                    str(raw_result["warning"])
                    if raw_result.get("warning") is not None
                    else None
                ),
                end_id=(
                    int(raw_result["end_id"])
                    if raw_result.get("end_id") is not None
                    else None
                ),
            )
        except (TypeError, ValueError):
            return None
        return result, dict(raw_stats)

    @staticmethod
    def _quick_export_from_json(
        export_json: Path,
    ) -> tuple[ExportJobResult, dict[str, Any]] | None:
        """Reconstruct Quick Mode metadata when the backend manifest is gone."""
        try:
            payload = json.loads(Path(export_json).read_text(encoding="utf-8"))
            messages = payload.get("messages", []) if isinstance(payload, dict) else []
            if not isinstance(messages, list):
                messages = []
            message_ids = []
            for message in messages:
                if not isinstance(message, dict):
                    continue
                try:
                    message_ids.append(int(message["id"]))
                except (KeyError, TypeError, ValueError):
                    continue
            stats = inspect_export_json(Path(export_json))
            metadata = payload.get("tme3bot", {}) if isinstance(payload, dict) else {}
            metadata = metadata if isinstance(metadata, dict) else {}
            latest_id = max(message_ids) if message_ids else None
            result = ExportJobResult(
                status="exported" if messages else "empty_export",
                chat_ref=str(metadata.get("chat_ref") or stats.get("chat_ref") or ""),
                requested_label=(
                    str(metadata["label"])
                    if metadata.get("label") is not None
                    else None
                ),
                export_path=Path(export_json).resolve(),
                start_id=min(message_ids) if message_ids else 1,
                latest_id=latest_id,
                exported_count=len(messages),
                has_media=int(stats.get("media_count") or 0) > 0,
                warmup_required=bool(metadata.get("warmup_required")),
                warning=None,
                end_id=latest_id,
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return result, stats

    @staticmethod
    def _quick_stage_json_path(
        stage_root: Path, manifest: dict[str, Any]
    ) -> Path | None:
        name = Path(str(manifest.get("export_json_name") or "")).name
        if not name or name != str(manifest.get("export_json_name") or ""):
            return None
        candidate = Path(stage_root) / name
        return candidate if candidate.is_file() else None

    @staticmethod
    def _ensure_quick_export_json(
        export_path: Path,
        stage_root: Path,
        manifest: dict[str, Any],
        name: str | None = None,
    ) -> Path:
        """Keep a recovery copy of the raw TDL export in Quick Mode staging."""
        name = str(name or Path(export_path).name)
        if not name or Path(name).name != name or not name.lower().endswith(".json"):
            raise QuickModeError("Nama JSON export Quick Mode tidak valid.")
        target = Path(stage_root) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            try:
                shutil.copy2(export_path, target)
            except OSError as exc:
                raise QuickModeError(
                    f"JSON export Quick Mode tidak dapat disimpan ke staging: {exc}"
                ) from exc
        manifest["export_json_name"] = name
        manifest["export_json_retained"] = True
        return target

    @staticmethod
    def _materialize_quick_json(staged_json: Path) -> Path:
        """Create a temporary workspace-only input for the download service."""
        # Keep both the download input and any temporary state inside the
        # Quick Mode workspace.  The normal /data export queues belong to the
        # Download Manager and must not receive Quick Mode leftovers.
        stage_root = Path(staged_json).parent.resolve()
        processing_root = (stage_root.parent / f".quick-processing-{stage_root.name}").resolve()
        processing_root.mkdir(parents=True, exist_ok=True)
        target = processing_root / staged_json.name
        if target.exists():
            target = processing_root / (
                f"{staged_json.stem}.quick-recovery-{uuid.uuid4().hex[:8]}.json"
            )
        shutil.copy2(staged_json, target)
        return target

    def _hydrate_quick_manifest_from_stage(
        self, stage_root: Path, manifest: dict[str, Any]
    ) -> dict[str, Any]:
        """Recover phase metadata from a retained raw export JSON."""
        candidate = self._quick_stage_json_path(stage_root, manifest)
        if candidate is None:
            candidates = sorted(
                path
                for path in Path(stage_root).glob("*.json")
                if path.name != "quickmode.json" and path.is_file()
            )
            candidate = candidates[0] if len(candidates) == 1 else None
        if candidate is None:
            return manifest
        inferred = self._quick_export_from_json(candidate)
        if inferred is None:
            return manifest
        result, stats = inferred
        manifest.setdefault("export_json_name", candidate.name)
        manifest.setdefault("folder_name", quick_folder_name(candidate))
        manifest["export_result"] = json_value(asdict(result))
        manifest["stats"] = json_value(stats)
        manifest.setdefault("phase", "downloading")
        manifest.setdefault("json_deleted", True)
        manifest["export_json_retained"] = True
        return manifest

    @staticmethod
    def _export_retry_range(payload: dict[str, Any]) -> tuple[int | None, int | None]:
        """Return a persisted message-ID range for export recovery.

        Retry metadata is intentionally kept in the internal command payload,
        because the original JSON may already have been downloaded/deleted.
        Older jobs may only have ``start_id``/``latest_id`` in their terminal
        result, which is handled by the control plane when it creates a retry.
        """
        for key in ("export_retry", "quick_retry"):
            metadata = payload.get(key)
            if not isinstance(metadata, dict):
                continue
            start = metadata.get("start_id")
            end = metadata.get("end_id")
            try:
                parsed_start = max(1, int(start)) if start is not None else None
            except (TypeError, ValueError):
                parsed_start = None
            try:
                parsed_end = max(1, int(end)) if end is not None else None
            except (TypeError, ValueError):
                parsed_end = None
            if parsed_start is not None or parsed_end is not None:
                if parsed_start is not None and parsed_end is not None:
                    parsed_end = max(parsed_start, parsed_end)
                return parsed_start, parsed_end
        return None, None

    @staticmethod
    def _quick_json_path(
        runtime, manifest: dict[str, Any], stage_root: Path | None = None
    ) -> Path | None:
        name = Path(str(manifest.get("export_json_name") or "")).name
        if not name or name != str(manifest.get("export_json_name") or ""):
            return None
        if stage_root is not None:
            staged = Path(stage_root) / name
            if staged.is_file():
                return staged
            # Quick Mode must never resume a download from the normal
            # /data exports queue.  A missing staging JSON is a safe boundary
            # that falls back to re-exporting into the workspace.
            return None
        for root in (
            getattr(runtime.config, "export_processing_dir", None),
            getattr(runtime.config, "export_failed_dir", None),
            getattr(runtime.config, "export_pending_dir", None),
        ):
            if root is None:
                continue
            candidate = Path(root) / name
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _quick_media_root(stage_root: Path, manifest: dict[str, Any]) -> Path | None:
        folder_name = Path(str(manifest.get("folder_name") or "")).name
        if not folder_name or folder_name != str(manifest.get("folder_name") or ""):
            return None
        return Path(stage_root) / folder_name

    def _resolve_quick_retry_phase(
        self,
        requested: str,
        stage_root: Path,
        manifest: dict[str, Any],
        runtime,
    ) -> str:
        if requested == "exporting":
            return requested
        hydrated = self._hydrate_quick_manifest_from_stage(stage_root, manifest)
        manifest.clear()
        manifest.update(hydrated)
        folder_name = Path(str(manifest.get("folder_name") or "")).name
        if not folder_name or folder_name == ".":
            archive_candidates = sorted(stage_root.glob("*.7z*"))
            if archive_candidates:
                folder_name = archive_candidates[0].name.split(".7z", 1)[0]
                manifest["folder_name"] = folder_name
            else:
                child_dirs = [
                    path
                    for path in stage_root.iterdir()
                    if path.is_dir() and path.name != ".tdl" and not path.is_symlink()
                ]
                if len(child_dirs) == 1:
                    folder_name = child_dirs[0].name
                    manifest["folder_name"] = folder_name
        media_root = self._quick_media_root(stage_root, manifest)
        has_media = bool(media_root and media_root.is_dir() and visual_media(media_root)[0:2] != ([], []))
        thumbnail = stage_root / f"{folder_name}.png" if folder_name else stage_root / ".missing.png"
        archives = (
            list(stage_root.glob("*.7z"))
            + list(stage_root.glob("*.7z.*"))
        )
        has_json = bool(self._quick_json_path(runtime, manifest, stage_root))
        raw_export = self._quick_manifest_export(manifest)
        # An orphan with a complete archive and PNG does not need its JSON or
        # ExportJobResult.  It can safely continue at upload and cleanup.
        if requested == "auto" and archives and thumbnail.is_file():
            return "uploading"
        if requested == "auto":
            if archives and thumbnail.is_file():
                return "uploading"
            if raw_export is None:
                return "downloading" if has_json else ("thumbnailing" if has_media else "exporting")
            if has_media and thumbnail.is_file() and not archives:
                return "compressing"
            if has_media and not thumbnail.is_file():
                return "thumbnailing"
            return "downloading" if has_json else "exporting"
        if requested == "downloading":
            # A cancellation can arrive just after TDL has deleted the JSON
            # but before the phase checkpoint is written.  Existing media is
            # then the safe dependency boundary: continue with thumbnailing
            # instead of exporting the chat a second time.
            if has_json:
                return "downloading"
            if has_media:
                return "thumbnailing"
            raise QuickModeError(
                "Resume Download tidak dapat dimulai: JSON dan media staging tidak tersedia."
            )
        if requested == "thumbnailing":
            if has_media:
                return "thumbnailing"
            if has_json:
                return "downloading"
            raise QuickModeError(
                "Thumbnail tidak dapat dibuat: media staging tidak tersedia. Gunakan Resume Download."
            )
        if requested == "compressing":
            if has_media and thumbnail.is_file():
                return "compressing"
            if has_media:
                return "thumbnailing"
            if has_json:
                return "downloading"
            raise QuickModeError(
                "Compress tidak dapat dimulai: media staging tidak tersedia."
            )
        if requested == "uploading":
            if archives and thumbnail.is_file():
                return "uploading"
            if has_media and thumbnail.is_file():
                return "compressing"
            if has_media:
                return "thumbnailing"
            if has_json:
                return "downloading"
            raise QuickModeError(
                "Upload tidak dapat dimulai: arsip atau thumbnail belum tersedia."
            )
        return "cleanup" if requested == "cleanup" else "exporting"

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

    def _quick_export_pipeline(
        self,
        command: dict[str, Any],
        runtime,
        export_result: ExportJobResult | None,
        stats: dict[str, Any],
        reporter: ProgressReporter,
        *,
        stage_root: Path | None = None,
        manifest: dict[str, Any] | None = None,
        resume_phase: str = "downloading",
    ) -> dict[str, Any]:
        """Run the post-export Quick Mode stages while retaining staging on error."""
        job_id = str(command["job_id"])
        payload = command["payload"]
        if stage_root is None:
            stage_root, prepared_manifest, _, _ = self._prepare_quick_stage(command, runtime)
            manifest = manifest or prepared_manifest
        stage_root = Path(stage_root).resolve()
        workspace = self._quick_workspace(self.config)
        try:
            stage_root.relative_to(workspace)
        except ValueError as exc:
            raise QuickModeError(
                "Staging Quick Mode harus berada di dalam workspace."
            ) from exc
        manifest = dict(manifest or read_quick_manifest(stage_root))
        operation_id = str(manifest.get("quick_operation_id") or stage_root.name)
        retry = payload.get("quick_retry") or {}
        retry = retry if isinstance(retry, dict) else {}
        single_phase = bool(retry.get("single_phase"))
        export_json_name = str(manifest.get("export_json_name") or "")
        if not export_json_name and export_result is not None:
            export_json_name = Path(export_result.export_path).name
        folder_name = str(manifest.get("folder_name") or "")
        if not folder_name and export_result is not None:
            folder_name = quick_folder_name(export_result.export_path)
        if not folder_name:
            archive_candidate = sorted(stage_root.glob("*.7z*"))
            if archive_candidate:
                folder_name = archive_candidate[0].name.split(".7z", 1)[0]
        if not folder_name:
            raise QuickModeError("Folder staging Quick Mode tidak dapat ditentukan.")
        if export_result is not None:
            self._ensure_quick_export_json(
                export_result.export_path,
                stage_root,
                manifest,
                name=export_json_name,
            )
        manifest["phase"] = resume_phase
        manifest["folder_name"] = folder_name
        if export_json_name:
            manifest["export_json_name"] = export_json_name
        if export_result is not None:
            manifest["export_result"] = json_value(asdict(export_result))
            manifest["stats"] = json_value(stats)
        media_root = stage_root / folder_name
        thumbnail_path = stage_root / f"{folder_name}.png"
        thumbnail = manifest.get("thumbnail")
        thumbnail = dict(thumbnail) if isinstance(thumbnail, dict) else {}
        storage_folder = str(manifest.get("storage_folder") or f"ModeCepat/{quick_year()}")
        caption = str(manifest.get("caption") or quick_storage_caption(folder_name, quick_year()))
        archive_names = manifest.get("archive_names")
        archive_names = archive_names if isinstance(archive_names, list) else []
        if not archive_names:
            archive_names = [path.name for path in sorted(stage_root.glob("*.7z*"))]
        archive_files: list[Path] = [
            stage_root / Path(str(name)).name
            for name in archive_names
            if str(name) and Path(str(name)).name == str(name)
        ]
        upload_result = manifest.get("upload_result")
        upload_result = dict(upload_result) if isinstance(upload_result, dict) else {"succeeded": 0}
        rclone_result = manifest.get("rclone_result")
        rclone_result = dict(rclone_result) if isinstance(rclone_result, dict) else None

        def ensure_not_cancelled() -> None:
            with self._lock:
                if job_id in self._cancel_requested:
                    raise QuickModeError("Quick Mode dibatalkan oleh user.")

        def save_manifest(**updates: Any) -> None:
            error_value = updates.get("last_error")
            if error_value:
                safe_error = str(error_value)
                settings = payload.get("quick_settings")
                if isinstance(settings, dict):
                    password = str(settings.get("compress_password") or "")
                    if password:
                        safe_error = safe_error.replace(password, "[redacted]")
                updates["last_error"] = safe_error[:1000]
            manifest.update(updates)
            manifest["last_progress_at"] = utc_now().isoformat()
            write_quick_manifest(stage_root, manifest)

        def phase_result(completed_phase: str, next_phase: str) -> dict[str, Any]:
            """Return a successful targeted-phase result without deleting staging."""
            save_manifest(phase=next_phase, last_error=None)
            return {
                **(asdict(export_result) if export_result is not None else {}),
                **stats,
                **thumbnail,
                "quick_mode": True,
                "quick_mode_status": "phase_completed",
                "quick_phase": completed_phase,
                "folder_name": folder_name,
                "storage_folder": storage_folder,
                "caption": caption,
                "archive_names": [path.name for path in archive_files],
                "thumbnail_uploaded_as_photo": completed_phase == "uploading",
                "uploaded_count": upload_result.get("succeeded", 0),
                "rclone_destination": (
                    rclone_result.get("destination")
                    if isinstance(rclone_result, dict)
                    else None
                ),
                "rclone_uploaded_count": (
                    rclone_result.get("succeeded", 0)
                    if isinstance(rclone_result, dict)
                    else 0
                ),
                "rclone_archive_names": (
                    rclone_result.get("files", [])
                    if isinstance(rclone_result, dict)
                    else []
                ),
                "stage_job_id": manifest.get("stage_job_id") or stage_root.name,
                "quick_operation_id": operation_id,
                "staging_path": str(stage_root),
                "staging_cleaned": False,
                "json_deleted": bool(manifest.get("json_deleted")),
            }

        try:
            stage_root.mkdir(parents=True, exist_ok=True)
            save_manifest(
                phase=resume_phase,
                folder_name=folder_name,
                storage_folder=storage_folder,
                caption=caption,
            )
            if export_result is not None:
                save_manifest(
                    export_json_name=export_json_name,
                    export_result=json_value(asdict(export_result)),
                    stats=json_value(stats),
                )
            phase = resume_phase
            if phase == "downloading":
                ensure_not_cancelled()
                save_manifest(phase="downloading", last_error=None)
                shutil.rmtree(media_root, ignore_errors=True)
                media_root.mkdir(parents=True, exist_ok=True)

                reporter.report(
                    phase="downloading",
                    message=f"Mengunduh media ke staging {folder_name}",
                    overall={"current": 0, "total": 1, "percent": 0, "unit": "phase"},
                    force=True,
                )

                def download_progress(event_type: str, snapshot) -> None:
                    if event_type == "progress" and not snapshot.tdl_percent and snapshot.tdl_file_name is None:
                        return
                    reporter.report(
                        phase="downloading",
                        message=(
                            f"Mengunduh {snapshot.tdl_file_name}"
                            if snapshot.tdl_file_name
                            else "Mengunduh media"
                        ),
                        batch={
                            "name": snapshot.current_json_name,
                            "index": snapshot.current_json_index or 1,
                            "total": snapshot.total_json or 1,
                            "unit": "json",
                        },
                        item={
                            "name": snapshot.tdl_file_name,
                            "index": snapshot.tdl_fraction_current,
                            "total": snapshot.tdl_fraction_total or snapshot.current_media_total,
                            "percent": snapshot.tdl_percent,
                        },
                        transfer={
                            "bytes_current": snapshot.tdl_bytes_current,
                            "speed_bps": snapshot.tdl_speed_bps,
                            "eta_seconds": snapshot.tdl_eta_seconds,
                        },
                        counters={
                            "succeeded": snapshot.success_count,
                            "failed": snapshot.failed_count,
                        },
                        indeterminate=snapshot.tdl_percent is None and snapshot.active,
                        force=event_type != "progress",
                    )

                json_path = self._quick_json_path(runtime, manifest, stage_root)
                if json_path is None and export_result is not None:
                    json_path = export_result.export_path
                if json_path is None:
                    raise QuickModeError(
                        "JSON export Quick Mode tidak tersedia untuk fase download."
                    )
                staged_json = self._quick_stage_json_path(stage_root, manifest)
                temporary_json_dir: Path | None = None
                if staged_json is not None and json_path == staged_json:
                    json_path = self._materialize_quick_json(staged_json)
                    temporary_json_dir = json_path.parent
                previous_callback = runtime.download_progress.set_event_callback(download_progress)
                download_client = self._quick_isolated_client(runtime, stage_root, "download")
                with self._lock:
                    self._quick_download_clients[job_id] = download_client
                try:
                    try:
                        with runtime.download_operation_lock:
                            with self._capture_tdl_output(download_client):
                                download_result = runtime.download_service.download_export_to(
                                    json_path,
                                    media_root,
                                    delete_json_on_success=True,
                                    workspace_root=workspace,
                                    tdl_client=download_client,
                                )
                    finally:
                        if temporary_json_dir is not None:
                            shutil.rmtree(temporary_json_dir, ignore_errors=True)
                finally:
                    with self._lock:
                        self._quick_download_clients.pop(job_id, None)
                    runtime.download_progress.set_event_callback(previous_callback)
                if download_result.status != "success_deleted":
                    save_manifest(
                        phase="downloading",
                        export_json_name=download_result.json_path.name,
                        last_error=download_result.error or download_result.status,
                    )
                    raise QuickModeError(
                        f"Download Quick Mode gagal: {download_result.error or download_result.status}"
                    )
                save_manifest(phase="thumbnailing", json_deleted=True, last_error=None)
                phase = "thumbnailing"
                if single_phase:
                    return phase_result("downloading", "thumbnailing")

            if phase == "thumbnailing":
                ensure_not_cancelled()
                save_manifest(phase="thumbnailing", last_error=None)
                reporter.report(
                    phase="thumbnailing",
                    message="Membuat thumbnail Quick Mode",
                    overall={"current": 0, "total": 1, "percent": 0, "unit": "phase"},
                    force=True,
                )
                builder = QuickThumbnailBuilder(
                    log_callback=self._append_job_log,
                    stall_timeout_seconds=getattr(
                        self.config, "job_stall_timeout_seconds", 600
                    ),
                )
                with self._lock:
                    self._quick_thumbnail_builders[job_id] = builder
                try:
                    thumbnail = builder.build(media_root, thumbnail_path)
                finally:
                    with self._lock:
                        self._quick_thumbnail_builders.pop(job_id, None)
                save_manifest(phase="compressing", thumbnail=thumbnail, last_error=None)
                phase = "compressing"
                if single_phase:
                    return phase_result("thumbnailing", "compressing")

            if phase == "compressing":
                ensure_not_cancelled()
                save_manifest(phase="compressing", last_error=None)
                reporter.report(
                    phase="compressing",
                    message="Mengompres hasil download",
                    overall={"current": 0, "total": 1, "percent": 0, "unit": "phase"},
                    force=True,
                )
                for archive in stage_root.iterdir():
                    if archive.is_file() and (
                        archive.name == f"{folder_name}.7z"
                        or archive.name.startswith(f"{folder_name}.7z.")
                    ):
                        archive.unlink(missing_ok=True)
                settings = dict(payload.get("quick_settings") or DEFAULT_UTILITY_SETTINGS)
                utility_root = Path("/app/utility") if Path("/app/utility").exists() else Path("utility")
                runner = UtilityRunner(
                    utility_root,
                    log_callback=self._append_job_log,
                    stall_timeout_seconds=getattr(
                        self.config, "job_stall_timeout_seconds", 600
                    ),
                    progress_callback=lambda value: reporter.report(
                        phase="compressing",
                        message="Mengompres hasil download",
                        item={"name": folder_name},
                        overall={"current": 0, "total": 1, "unit": "phase"},
                        indeterminate=True,
                        force=True,
                    ),
                )
                with self._lock:
                    self._utility_runners[job_id] = runner
                try:
                    compress_result = runner.run("compress", [str(stage_root)], settings=settings)
                finally:
                    with self._lock:
                        self._utility_runners.pop(job_id, None)
                if compress_result.failed:
                    detail = next(iter(compress_result.failed.values()))
                    raise QuickModeError(f"Compress Quick Mode gagal: {detail}")
                ensure_not_cancelled()
                archive_files = sorted(
                    path
                    for path in stage_root.iterdir()
                    if path.is_file()
                    and (path.name == f"{folder_name}.7z" or path.name.startswith(f"{folder_name}.7z."))
                )
                if not archive_files:
                    raise QuickModeError("Compress Quick Mode tidak menghasilkan file arsip.")
                save_manifest(
                    phase="uploading",
                    archive_names=[path.name for path in archive_files],
                    last_error=None,
                )
                phase = "uploading"
                if single_phase:
                    return phase_result("compressing", "uploading")

            if phase == "uploading":
                ensure_not_cancelled()
                archive_files = sorted(
                    path
                    for path in stage_root.iterdir()
                    if path.is_file()
                    and (path.name == f"{folder_name}.7z" or path.name.startswith(f"{folder_name}.7z."))
                )
                if not archive_files:
                    raise QuickModeError("Arsip Quick Mode tidak ditemukan untuk upload.")
                if not thumbnail_path.is_file():
                    raise QuickModeError("Thumbnail Quick Mode tidak ditemukan untuk upload.")
                year = quick_year()
                storage_folder = str(manifest.get("storage_folder") or f"ModeCepat/{year}")
                caption = str(manifest.get("caption") or quick_storage_caption(folder_name, year))
                reporter.report(
                    phase="uploading",
                    message="Mengupload arsip dan thumbnail ke storage",
                    overall={"current": 0, "total": len(archive_files) + 1, "percent": 0, "unit": "files"},
                    force=True,
                )
                upload_command = {
                    **command,
                    "kind": "storage_upload",
                    "payload": {
                        "folder_path": str(stage_root),
                        "destination_folder_path": storage_folder,
                        "preserve_structure": False,
                        "root_files_only": True,
                        "allowed_names": [path.name for path in archive_files] + [thumbnail_path.name],
                        "photo_names": [thumbnail_path.name],
                        "owner_user_id": int(command["actor_user_id"]),
                        "owner_profile": str(command["profile"]),
                        "batch_id": f"{operation_id}:quick",
                        "caption": caption,
                        "caption_override": True,
                        "keywords": "",
                    },
                }
                upload_result = self._storage_upload(upload_command)
                if upload_result.get("failed") or int(upload_result.get("succeeded", 0)) != len(archive_files) + 1:
                    failures = str(upload_result)
                    save_manifest(phase="uploading", last_error=failures[:500])
                    raise QuickModeError(
                        f"Upload Quick Mode gagal ({failures[:500]}); staging dipertahankan di {stage_root}."
                    )
                quick_settings = payload.get("quick_settings") or {}
                rclone_destination = (
                    quick_settings.get("rclone_destination", "googledrive:backup")
                    if isinstance(quick_settings, dict)
                    else "googledrive:backup"
                )
                # Legacy commands without the new snapshot use the documented
                # default, so every Quick Mode result still reaches Drive.
                rclone_result = self._rclone_upload_files(
                    command,
                    archive_files,
                    str(rclone_destination),
                    reporter,
                )
                save_manifest(
                    phase="cleanup",
                    upload_result=upload_result,
                    rclone_destination=rclone_destination,
                    rclone_result=rclone_result,
                    storage_folder=storage_folder,
                    caption=caption,
                    last_error=None,
                )
                phase = "cleanup"
                if single_phase:
                    return phase_result("uploading", "cleanup")

            if phase == "cleanup":
                ensure_not_cancelled()
                reporter.report(
                    phase="cleanup",
                    message="Membersihkan staging Quick Mode",
                    overall={"current": 1, "total": 1, "percent": 100, "unit": "phase"},
                    force=True,
                )
                shutil.rmtree(stage_root)
                return {
                    **(asdict(export_result) if export_result is not None else {}),
                    **stats,
                    **thumbnail,
                    "quick_mode": True,
                    "quick_mode_status": "completed",
                    "folder_name": folder_name,
                    "storage_folder": storage_folder,
                    "caption": caption,
                    "archive_names": [path.name for path in archive_files],
                    "thumbnail_uploaded_as_photo": True,
                    "uploaded_count": upload_result.get("succeeded", 0),
                    "rclone_destination": (
                        rclone_result.get("destination")
                        if isinstance(rclone_result, dict)
                        else None
                    ),
                    "rclone_uploaded_count": (
                        rclone_result.get("succeeded", 0)
                        if isinstance(rclone_result, dict)
                        else 0
                    ),
                    "rclone_archive_names": (
                        rclone_result.get("files", [])
                        if isinstance(rclone_result, dict)
                        else []
                    ),
                    "stage_job_id": manifest.get("stage_job_id") or stage_root.name,
                    "quick_operation_id": operation_id,
                    "staging_path": str(stage_root),
                    "staging_cleaned": True,
                    "json_deleted": True,
                }
            raise QuickModeError(f"Fase Quick Mode tidak dikenal: {phase}")
        except Exception as exc:
            if stage_root.exists():
                try:
                    save_manifest(phase=locals().get("phase", resume_phase), last_error=str(exc)[:1000])
                except Exception:
                    LOGGER.warning("Could not persist Quick Mode manifest at %s", stage_root, exc_info=True)
            if isinstance(exc, QuickModeError) and "staging dipertahankan di" in str(exc):
                raise
            raise QuickModeError(
                f"{exc}; staging dipertahankan di {stage_root}."
            ) from exc

    def _leave(self, command: dict[str, Any]) -> dict[str, Any]:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        with runtime.export_operation_lock:
            result = runtime.leave_service.leave(
                [str(item) for item in command["payload"].get("chat_refs", [])],
                output_callback=self._append_job_log,
            )
            deleted = runtime.state_store.delete_sources(result.succeeded)
        return {"succeeded": deleted, "failed": result.failed}

    def _download(self, command: dict[str, Any]) -> Any:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        payload = command["payload"]
        artifact_refs = [
            {
                "key": str(item.get("key") or ""),
                "status": str(item.get("status") or "pending"),
            }
            for item in payload.get("artifacts", [])
            if isinstance(item, dict)
        ]
        if not artifact_refs:
            artifact_refs = [
                {"key": str(item), "status": "pending"}
                for item in payload.get("artifact_keys", [])
            ]
        existing_refs: list[dict[str, str]] = []
        missing_keys: list[str] = []
        if artifact_refs:
            roots = {
                "pending": runtime.config.export_pending_dir.resolve(),
                "failed": runtime.config.export_failed_dir.resolve(),
            }
            for artifact in artifact_refs:
                key = artifact["key"]
                source_root = roots.get(artifact["status"])
                candidate = (
                    (source_root / key).resolve()
                    if source_root is not None
                    else Path("")
                )
                if (
                    source_root is not None
                    and Path(key).name == key
                    and key.lower().endswith(".json")
                    and candidate.parent == source_root
                    and candidate.is_file()
                ):
                    existing_refs.append(artifact)
                    continue
                missing_keys.append(key)
                self._append_job_log(f"[artifact missing: {key}]")
                self.publisher.emit(
                    str(command["job_id"]),
                    "running",
                    "artifact.missing",
                    result={
                        "artifact": {
                            "profile": str(command["profile"]),
                            "worker": str(command.get("worker") or self.config.backup_node_name),
                            "artifact_key": key,
                        }
                    },
                )

        def report_snapshot(snapshot, *, force: bool = False) -> dict[str, Any]:
            total_json = max(0, snapshot.total_json)
            json_done = max(
                snapshot.success_count + snapshot.failed_count,
                snapshot.current_json_index - 1,
            )
            item_percent = snapshot.tdl_percent
            overall_percent = None
            if total_json:
                partial = (
                    item_percent / 100
                    if item_percent is not None and snapshot.current_json_index
                    else 0
                )
                overall_percent = min(
                    100.0, (json_done + partial) * 100 / total_json
                )
            return reporter.report(
                phase=snapshot.phase,
                message=(
                    f"Memproses {snapshot.current_json_name}"
                    if snapshot.current_json_name
                    else "Menyiapkan antrean download"
                ),
                batch={
                    "name": snapshot.current_json_name,
                    "index": snapshot.current_json_index or None,
                    "total": total_json or None,
                    "unit": "json",
                },
                overall={
                    "current": json_done,
                    "total": total_json,
                    "percent": overall_percent,
                    "unit": "json",
                },
                item={
                    "name": snapshot.tdl_file_name,
                    "index": snapshot.tdl_fraction_current,
                    "total": (
                        snapshot.tdl_fraction_total
                        or snapshot.current_media_total
                    ),
                    "percent": item_percent,
                },
                transfer={
                    "bytes_current": snapshot.tdl_bytes_current,
                    "speed_bps": snapshot.tdl_speed_bps,
                    "eta_seconds": snapshot.tdl_eta_seconds,
                    "elapsed_seconds": snapshot.tdl_elapsed_seconds,
                },
                counters={
                    "succeeded": snapshot.success_count,
                    "failed": snapshot.failed_count,
                    "skipped": len(missing_keys),
                },
                indeterminate=item_percent is None and snapshot.active,
                force=force,
            )

        def progress_event(event_type: str, snapshot) -> None:
            progress = report_snapshot(
                snapshot, force=event_type != "progress"
            )
            milestones = {
                "json_started": "download.json_started",
                "json_completed": "download.json_completed",
                "json_failed": "download.json_failed",
            }
            milestone = milestones.get(event_type)
            if milestone:
                details = {
                    "json_name": snapshot.current_json_name,
                    "json_index": snapshot.current_json_index,
                    "json_total": snapshot.total_json,
                    "media_total": snapshot.current_media_total,
                }
                reporter.milestone(
                    milestone,
                    progress=progress,
                    result=details if event_type != "json_failed" else None,
                    error=(
                        {"message": snapshot.last_error or "Download JSON gagal."}
                        if event_type == "json_failed"
                        else None
                    ),
                )

        previous_callback = runtime.download_progress.set_event_callback(
            progress_event
        )
        try:
            with runtime.download_operation_lock:
                with self._capture_tdl_output(runtime.download_tdl_client):
                    if payload.get("retry_failed") and not artifact_refs:
                        result = runtime.download_service.retry_failed_exports()
                    elif artifact_refs:
                        if not existing_refs:
                            progress = reporter.report(
                                phase="completed",
                                message=(
                                    f"Tidak ada JSON tersedia; "
                                    f"{len(missing_keys)} dilewati"
                                ),
                                overall={
                                    "current": 0,
                                    "total": 0,
                                    "percent": 100,
                                    "unit": "json",
                                },
                                counters={"skipped": len(missing_keys)},
                                force=True,
                            )
                            reporter.milestone(
                                "download.completed",
                                progress=progress,
                                result={
                                    "success_count": 0,
                                    "failed_count": 0,
                                    "skipped_missing": len(missing_keys),
                                },
                            )
                            return {
                                "moved_count": 0,
                                "success_count": 0,
                                "failed_count": 0,
                                "skipped_missing": len(missing_keys),
                                "results": [],
                            }
                        result = runtime.download_service.download_selected_artifacts(
                            existing_refs
                        )
                    else:
                        result = runtime.download_service.download_pending_exports()
            for item in result.results:
                self.publisher.emit(
                    str(command["job_id"]),
                    "running",
                    "artifact.downloaded" if item.status == "success" else "artifact.failed",
                    result={
                        "artifact": {
                            "profile": str(command["profile"]),
                            "worker": str(command.get("worker") or self.config.backup_node_name),
                            "artifact_key": item.json_path.name,
                            "status": "downloaded" if item.status == "success" else "failed",
                            "download_directory": str(item.download_dir),
                            "error": item.error,
                            "available": True,
                        }
                    },
                )
            progress = reporter.report(
                phase="completed",
                message=(
                    f"Download selesai: {result.success_count} JSON berhasil, "
                    f"{result.failed_count} gagal, {len(missing_keys)} dilewati"
                ),
                overall={
                    "current": result.moved_count,
                    "total": result.moved_count,
                    "percent": 100,
                    "unit": "json",
                },
                counters={
                    "succeeded": result.success_count,
                    "failed": result.failed_count,
                    "skipped": len(missing_keys),
                },
                force=True,
            )
            summary = {
                **asdict(result),
                "skipped_missing": len(missing_keys),
            }
            reporter.milestone(
                "download.completed",
                progress=progress,
                result={
                    "success_count": result.success_count,
                    "failed_count": result.failed_count,
                    "skipped_missing": len(missing_keys),
                },
            )
            return summary
        finally:
            runtime.download_progress.set_event_callback(previous_callback)

    def _download_clear_failed(self, command: dict[str, Any]) -> dict[str, int]:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        return {"deleted": runtime.download_service.clear_failed_exports()}

    def _artifact_inventory(self, command: dict[str, Any]) -> dict[str, Any]:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        inventory_id = str(
            command.get("payload", {}).get("inventory_id") or uuid.uuid4()
        )
        locations = (
            ("pending", runtime.config.export_pending_dir),
            ("processing", runtime.config.export_processing_dir),
            ("downloaded", runtime.config.export_done_dir),
            ("failed", runtime.config.export_failed_dir),
        )
        discovered = 0
        inventory_batch: list[dict[str, Any]] = []
        profile_name = str(command["profile"])
        seen_cache_keys: set[tuple[str, str]] = set()

        def publish_inventory_batch() -> None:
            if not inventory_batch:
                return
            self.publisher.emit(
                str(command["job_id"]),
                "running",
                "artifact.inventory_batch",
                result={"artifacts": list(inventory_batch)},
            )
            inventory_batch.clear()

        for status, root in locations:
            for path in sorted(root.glob("*.json")):
                cache_key = (profile_name, str(path))
                try:
                    file_stat = path.stat()
                    fingerprint = (
                        int(getattr(file_stat, "st_ino", 0)),
                        int(file_stat.st_size),
                        int(file_stat.st_mtime_ns),
                    )
                except OSError as exc:
                    LOGGER.warning("Artifact inventory skipped %s: %s", path, exc)
                    continue
                seen_cache_keys.add(cache_key)
                with self._lock:
                    cached = self._inventory_cache.get(cache_key)
                if cached is not None and cached[0] == fingerprint:
                    stats = dict(cached[1])
                else:
                    try:
                        stats = inspect_export_json(path)
                    except (OSError, ValueError) as exc:
                        with self._lock:
                            self._inventory_cache.pop(cache_key, None)
                        LOGGER.warning("Artifact inventory skipped %s: %s", path, exc)
                        continue
                    with self._lock:
                        self._inventory_cache[cache_key] = (fingerprint, dict(stats))
                if stats.get("media_count") == 0:
                    try:
                        discard_export_without_media(path, stats)
                    except OSError as exc:
                        LOGGER.warning(
                            "Could not remove media-less export during inventory %s: %s",
                            path,
                            exc,
                        )
                    with self._lock:
                        self._inventory_cache.pop(cache_key, None)
                    # Do not publish an artifact for an empty export. Existing
                    # catalog rows are intentionally left to inventory
                    # completion, which marks files no longer present as
                    # unavailable for audit/history.
                    continue
                inventory_batch.append(
                    {
                        **stats,
                        "profile": profile_name,
                        "worker": str(command.get("worker") or self.config.backup_node_name),
                        "filename": path.name,
                        "artifact_key": path.name,
                        "status": status,
                        "available": True,
                        "last_seen_inventory_id": inventory_id,
                    }
                )
                discovered += 1
                if len(inventory_batch) >= 100:
                    publish_inventory_batch()
        with self._lock:
            stale_keys = [
                key
                for key in self._inventory_cache
                if key[0] == profile_name and key not in seen_cache_keys
            ]
            for key in stale_keys:
                self._inventory_cache.pop(key, None)
        publish_inventory_batch()
        inventory = {
            "inventory_id": inventory_id,
            "profile": str(command["profile"]),
            "worker": str(command.get("worker") or self.config.backup_node_name),
            "discovered": discovered,
        }
        self.publisher.emit(
            str(command["job_id"]),
            "running",
            "artifact.inventory_completed",
            result={"inventory": inventory},
        )
        return {"discovered": discovered, "inventory_id": inventory_id}

    def _artifact_delete(self, command: dict[str, Any]) -> dict[str, Any]:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        payload = command["payload"]
        keys = payload.get("artifact_keys") or []
        if not keys and payload.get("artifact_key"):
            keys = [payload["artifact_key"]]
        if not isinstance(keys, (list, tuple, set)):
            keys = [keys]
        deleted: list[str] = []
        missing: list[str] = []
        for raw_key in keys:
            key = str(raw_key)
            if Path(key).name != key or not key.lower().endswith(".json"):
                raise ValueError("Artifact key tidak valid.")
            found = False
            for root in (runtime.config.export_pending_dir, runtime.config.export_failed_dir):
                candidate = (root.resolve() / key).resolve()
                try:
                    candidate.relative_to(root.resolve())
                except ValueError:
                    continue
                if candidate.is_file():
                    candidate.unlink()
                    deleted.append(key)
                    found = True
                    break
            if not found:
                missing.append(key)
        return {"deleted": deleted, "missing": missing}

    def _utility(self, command: dict[str, Any]) -> dict[str, Any]:
        payload = command["payload"]
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        folders = [
            self._workspace_path(item, require_absolute=True)
            for item in payload.get("folders", [])
        ]
        if not folders:
            raise ValueError("Folder utility belum dipilih.")
        missing = [str(folder) for folder in folders if not folder.is_dir()]
        if missing:
            raise ValueError(f"Folder utility tidak ditemukan: {', '.join(missing)}")
        utility_name = str(payload["utility"])
        counters = {"succeeded": 0, "failed": 0, "skipped": 0}

        def utility_progress(value: dict[str, object]) -> None:
            phase = str(value.get("phase") or utility_name)
            if phase in {"item_completed", f"{utility_name}_folder_completed"}:
                counters["succeeded"] += 1
            elif phase in {"item_failed", f"{utility_name}_folder_failed"}:
                counters["failed"] += 1
            index = int(value.get("index") or value.get("folder_index") or 0)
            total = int(value.get("total") or value.get("folder_total") or len(folders))
            percent = value.get("percent")
            item_name = str(
                value.get("name")
                or value.get("folder")
                or (folders[min(max(index - 1, 0), len(folders) - 1)] if folders else "")
            )
            progress_payload = reporter.report(
                phase=phase,
                message=_utility_progress_message(utility_name, phase, item_name),
                overall={
                    "current": max(0, index - (0 if "completed" in phase else 1)),
                    "total": total,
                    "percent": (
                        float(percent)
                        if total <= 1 and isinstance(percent, (int, float))
                        else (
                            ((max(index - 1, 0) + float(percent) / 100) * 100 / total)
                            if total and isinstance(percent, (int, float))
                            else None
                        )
                    ),
                    "unit": "folders",
                },
                item={
                    "name": item_name,
                    "index": index or None,
                    "total": total or None,
                    "size_bytes": value.get("size_bytes"),
                    "percent": percent,
                },
                transfer=reporter.transfer_metrics(
                    speed_bps=value.get("speed_bps"),
                    current_bytes=value.get("bytes_current"),
                    total_bytes=value.get("size_bytes"),
                    eta_seconds=value.get("eta_seconds"),
                    elapsed_seconds=value.get("elapsed_seconds"),
                    percent=float(percent) if isinstance(percent, (int, float)) else None,
                ),
                counters=counters,
                indeterminate=bool(value.get("indeterminate", percent is None)),
                force=phase.endswith("_starting") or phase in {"item_completed", "item_failed"},
            )
            if phase in {"item_completed", "item_failed"}:
                reporter.milestone(
                    phase,
                    progress=progress_payload,
                    error=(
                        {"message": str(value.get("error")), "item": item_name}
                        if phase == "item_failed"
                        else None
                    ),
                )

        runner = UtilityRunner(
            Path("/app/utility") if Path("/app/utility").exists() else Path("utility"),
            log_callback=self._append_job_log,
            stall_timeout_seconds=getattr(
                self.config, "job_stall_timeout_seconds", 600
            ),
            progress_callback=utility_progress,
        )
        job_id = str(command["job_id"])
        with self._lock:
            self._utility_runners[job_id] = runner
        try:
            result = json_value(
                runner.run(
                    utility_name,
                    [str(item) for item in folders],
                    payload.get("password"),
                    payload.get("settings") or {},
                )
            )
            reporter.report(
                phase="completed",
                message=(
                    f"Utility selesai: {len(result.get('succeeded', []))} folder berhasil, "
                    f"{len(result.get('failed', {}))} gagal"
                ),
                overall={
                    "current": len(folders),
                    "total": len(folders),
                    "percent": 100,
                    "unit": "folders",
                },
                counters={
                    "succeeded": len(result.get("succeeded", [])),
                    "failed": len(result.get("failed", {})),
                },
                force=True,
            )
            return result
        finally:
            with self._lock:
                self._utility_runners.pop(job_id, None)

    def _rclone_upload_files(
        self,
        command: dict[str, Any],
        files: list[Path],
        destination: str,
        reporter: ProgressReporter,
        remote_names: list[str] | None = None,
    ) -> dict[str, object]:
        """Upload workspace files through the worker-local rclone config."""
        job_id = str(command["job_id"])
        workspace = self._quick_workspace(self.config)
        config_path = Path(
            getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")
        ).resolve()
        config_root = Path(getattr(self.config, "profile_root", "/data")).resolve()

        def progress(index: int, total: int, name: str) -> None:
            # A telemetry outage must not turn an already completed remote
            # copy into a false physical upload failure.
            try:
                reporter.report(
                    phase="uploading",
                    message=f"Mengupload {name} ke Google Drive",
                    overall={
                        "current": index,
                        "total": total,
                        "percent": index * 100 / total if total else 100,
                        "unit": "files",
                    },
                    item={
                        "name": name,
                        "index": index,
                        "total": total,
                        "percent": 100,
                    },
                    counters={"succeeded": index, "failed": 0},
                    force=True,
                )
            except Exception:
                LOGGER.warning(
                    "Could not publish rclone progress for %s", job_id, exc_info=True
                )

        def cancelled() -> bool:
            with self._lock:
                return job_id in self._cancel_requested

        runner = RcloneRunner(
            log_callback=self._append_job_log,
            progress_callback=progress,
            cancel_check=cancelled,
            stall_timeout_seconds=getattr(
                self.config, "job_stall_timeout_seconds", 600
            ),
        )
        with self._lock:
            self._rclone_runners[job_id] = runner
        try:
            kwargs = {"remote_names": remote_names} if remote_names is not None else {}
            return runner.copy_files(
                files,
                destination,
                config_path,
                workspace_root=workspace,
                config_root=config_root,
                **kwargs,
            )
        finally:
            with self._lock:
                self._rclone_runners.pop(job_id, None)

    def _storage_upload(self, command: dict[str, Any]) -> dict[str, Any]:
        payload = command["payload"]
        storage_profile = getattr(self.config, "worker_storage_profile", "storage")
        if storage_profile not in self.profile_manager.list_profiles():
            raise ValueError(
                f"STORAGE_PROFILE_UNAVAILABLE: profile worker {storage_profile} belum memiliki sesi TDL."
            )
        runtime = self.profile_manager.runtime(storage_profile)
        if not Path(runtime.config.tdl_export_storage).exists():
            raise ValueError(
                f"STORAGE_PROFILE_UNAVAILABLE: sesi TDL {storage_profile} belum tersedia."
            )
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        reporter.report(
            phase="scanning",
            message="Memindai file dalam folder storage",
            indeterminate=True,
            force=True,
        )
        root = self._workspace_path(str(payload["folder_path"]))
        if not root.is_dir():
            raise ValueError(f"Folder storage tidak ditemukan: {root}")
        allowed_names = {
            str(item) for item in (payload.get("allowed_names") or []) if str(item)
        }
        photo_names = {
            str(item) for item in (payload.get("photo_names") or []) if str(item)
        }
        if bool(payload.get("root_files_only")):
            files = sorted(
                path
                for path in root.iterdir()
                if path.is_file() and (not allowed_names or path.name in allowed_names)
            )
        else:
            files = sorted(path for path in root.rglob("*") if path.is_file())
        preserve_structure = bool(payload.get("preserve_structure", True))
        if preserve_structure:
            for relative in storage_relative_folders(root):
                self.publisher.emit(
                    str(command["job_id"]),
                    "running",
                    "storage.folder_discovered",
                    result={
                        "destination_folder_id": payload.get("destination_folder_id"),
                        "relative_path": relative,
                        "owner_user_id": int(payload["owner_user_id"]),
                    },
                )
        if not files:
            reporter.report(
                phase="registering",
                message="Struktur folder kosong selesai dibuat",
                overall={"current": 0, "total": 0, "unit": "files", "percent": 100},
                counters={"succeeded": 0, "failed": 0},
                force=True,
            )
            return {
                "status": "uploaded",
                "batch_id": payload["batch_id"],
                "succeeded": 0,
                "failed": [],
                "total": 0,
                "rclone_upload": bool(payload.get("rclone_upload")),
                "rclone_uploaded": 0,
            }
        file_sizes = {path: path.stat().st_size for path in files}
        total_bytes = sum(file_sizes.values())
        failed, succeeded = [], 0
        completed_bytes = 0
        last_message_id: int | None = None
        rclone_result: dict[str, object] | None = None
        reporter.milestone(
            "phase_changed",
            progress=reporter.report(
                phase="uploading",
                message=f"Siap mengupload {len(files)} file",
                overall={
                    "current": 0,
                    "total": len(files),
                    "percent": 0,
                    "unit": "files",
                    "bytes_current": 0,
                    "bytes_total": total_bytes,
                },
                counters={"succeeded": 0, "failed": 0},
                force=True,
            ),
        )
        with runtime.export_operation_lock:
            with self._capture_tdl_output(runtime.export_tdl_client):
                for index, path in enumerate(files, start=1):
                    with self._lock:
                        if str(command["job_id"]) in self._cancel_requested:
                            raise QuickModeError("Upload dibatalkan oleh user.")
                    size = file_sizes[path]
                    upload_state = {"phase": "uploading"}
                    reporter.reset_transfer()

                    def upload_progress(progress) -> None:
                        if (
                            upload_state["phase"] != "uploading"
                            or not _has_transfer_telemetry(progress)
                        ):
                            return
                        transfer = reporter.tdl_transfer(progress, total_bytes=size)
                        current_bytes = int(transfer.get("bytes_current") or 0)
                        overall_bytes = min(total_bytes, completed_bytes + current_bytes)
                        reporter.report(
                            phase="uploading",
                            message=f"Mengupload {path.name}",
                            overall={
                                "current": index - 1,
                                "total": len(files),
                                "percent": (
                                    overall_bytes * 100 / total_bytes
                                    if total_bytes
                                    else None
                                ),
                                "unit": "files",
                                "bytes_current": overall_bytes,
                                "bytes_total": total_bytes,
                            },
                            item={
                                "name": path.name,
                                "index": index,
                                "total": len(files),
                                "size_bytes": size,
                                "percent": progress.percent,
                            },
                            transfer=transfer,
                            counters={
                                "succeeded": succeeded,
                                "failed": len(failed),
                            },
                            indeterminate=progress.percent is None,
                        )

                    def upload_phase(phase: str) -> None:
                        upload_state["phase"] = phase
                        if phase == "resolving_message":
                            reporter.report(
                                phase=phase,
                                message=f"Menunggu konfirmasi Telegram untuk {path.name}",
                                overall={
                                    "current": index - 1,
                                    "total": len(files),
                                    "unit": "files",
                                },
                                item={
                                    "name": path.name,
                                    "index": index,
                                    "total": len(files),
                                    "size_bytes": size,
                                    "percent": 100,
                                },
                                counters={
                                    "succeeded": succeeded,
                                    "failed": len(failed),
                                },
                                indeterminate=True,
                                force=True,
                            )

                    try:
                        physical_upload_succeeded = False
                        counted_success = False
                        base_folder = str(
                            payload.get("destination_folder_path")
                            or payload.get("folder")
                            or ""
                        )
                        logical_folder, relative_parent = storage_logical_folder(
                            root, path, base_folder, preserve_structure
                        )
                        upload_id = str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"tme3bot:{payload['batch_id']}:{path.relative_to(root)}",
                            )
                        )
                        caption_override = bool(payload.get("caption_override"))
                        caption = (
                            str(payload.get("caption") or "")
                            if caption_override
                            else build_storage_caption(
                                logical_folder, path.name, str(payload.get("keywords", ""))
                            )
                        )
                        if not caption:
                            caption = build_storage_caption(
                                logical_folder, path.name, str(payload.get("keywords", ""))
                            )
                        reporter.report(
                            phase="uploading",
                            message=f"Mengupload {path.name}",
                            overall={
                                "current": index - 1,
                                "total": len(files),
                                "unit": "files",
                            },
                            item={
                                "name": path.name,
                                "index": index,
                                "total": len(files),
                                "size_bytes": size,
                                "percent": 0,
                            },
                            counters={
                                "succeeded": succeeded,
                                "failed": len(failed),
                            },
                            force=True,
                        )
                        with self._capture_tdl_progress(
                            runtime.export_tdl_client, upload_progress
                        ):
                            upload_kwargs = {"status_callback": upload_phase}
                            if last_message_id is not None:
                                # TDL can finish an upload before it reports the
                                # channel message ID.  Quick Mode intentionally
                                # uses the same caption for every file, so the
                                # delayed resolver must start after the message
                                # uploaded immediately before this one.
                                upload_kwargs["resolve_after_id"] = last_message_id
                            if path.name in photo_names:
                                upload_kwargs["as_photo"] = True
                            result = runtime.export_tdl_client.upload(
                                path,
                                runtime.config.storage_channel_ref,
                                caption,
                                **upload_kwargs,
                            )
                        # Telegram has accepted the file.  Failures while
                        # hashing, publishing progress, or registering the
                        # catalog event must not turn that physical upload
                        # into a false failed file.
                        physical_upload_succeeded = True
                        last_message_id = int(result.message_id)
                        reporter.report(
                            phase="hashing",
                            message=f"Memverifikasi {path.name}",
                            overall={
                                "current": index - 1,
                                "total": len(files),
                                "unit": "files",
                            },
                            item={
                                "name": path.name,
                                "index": index,
                                "total": len(files),
                                "size_bytes": size,
                                "percent": 100,
                            },
                            counters={
                                "succeeded": succeeded,
                                "failed": len(failed),
                            },
                            indeterminate=True,
                            force=True,
                        )
                        digest, size = self._digest(path)
                        item = {
                            "upload_id": upload_id,
                            "owner_user_id": int(payload["owner_user_id"]),
                            "owner_profile": str(payload["owner_profile"]),
                            "channel_id": runtime.config.storage_channel_id,
                            "channel_message_id": result.message_id,
                            "original_name": path.name,
                            "display_name": path.name,
                            "folder": logical_folder,
                            "folder_id": payload.get("destination_folder_id"),
                            "relative_folder": relative_parent,
                            "keywords": str(payload.get("keywords", "")),
                            "caption": caption,
                            "caption_override": caption_override,
                            "file_size": size,
                            "mime_type": mimetypes.guess_type(path.name)[0] or "",
                            "sha256": digest,
                            "status": "active",
                            "uploaded_at": None,
                        }
                        succeeded += 1
                        counted_success = True
                        completed_bytes += file_sizes[path]
                        progress_payload = reporter.report(
                            phase="registering",
                            message=f"{path.name} selesai diupload",
                            overall={
                                "current": index,
                                "total": len(files),
                                "percent": (
                                    completed_bytes * 100 / total_bytes
                                    if total_bytes
                                    else 100
                                ),
                                "unit": "files",
                                "bytes_current": completed_bytes,
                                "bytes_total": total_bytes,
                            },
                            item={
                                "name": path.name,
                                "index": index,
                                "total": len(files),
                                "size_bytes": size,
                                "percent": 100,
                            },
                            counters={
                                "succeeded": succeeded,
                                "failed": len(failed),
                            },
                            force=True,
                        )
                        reporter.milestone(
                            "storage.item_uploaded",
                            progress=progress_payload,
                            result={"item": item},
                        )
                    except Exception as exc:
                        with self._lock:
                            if str(command["job_id"]) in self._cancel_requested:
                                raise
                        if physical_upload_succeeded:
                            if not counted_success:
                                succeeded += 1
                                completed_bytes += file_sizes[path]
                            LOGGER.warning(
                                "Storage file %s uploaded but bookkeeping/telemetry failed; retaining success",
                                path,
                                exc_info=True,
                            )
                            continue
                        LOGGER.exception("Storage upload failed for %s", path)
                        failed.append({"name": path.name, "error": str(exc)})
                        completed_bytes += file_sizes[path]
                        progress_payload = reporter.report(
                            phase="uploading",
                            message=f"Upload gagal: {path.name}",
                            overall={
                                "current": index,
                                "total": len(files),
                                "percent": (
                                    completed_bytes * 100 / total_bytes
                                    if total_bytes
                                    else 100
                                ),
                                "unit": "files",
                                "bytes_current": completed_bytes,
                                "bytes_total": total_bytes,
                            },
                            item={
                                "name": path.name,
                                "index": index,
                                "total": len(files),
                                "size_bytes": file_sizes[path],
                            },
                            counters={
                                "succeeded": succeeded,
                                "failed": len(failed),
                            },
                            force=True,
                        )
                        reporter.milestone(
                            "item_failed",
                            progress=progress_payload,
                            error={"message": str(exc)[:500], "item": path.name},
                        )
        if payload.get("rclone_upload"):
            with self._lock:
                if str(command["job_id"]) in self._cancel_requested:
                    raise QuickModeError("Upload dibatalkan oleh user.")
            reporter.report(
                phase="uploading",
                message="Mengupload file ke Google Drive dengan rclone",
                overall={
                    "current": 0,
                    "total": len(files),
                    "percent": 0,
                    "unit": "files",
                },
                counters={"succeeded": 0, "failed": 0},
                indeterminate=True,
                force=True,
            )
            rclone_result = self._rclone_upload_files(
                command,
                files,
                str(payload.get("rclone_destination") or ""),
                reporter,
                remote_names=[
                    path.relative_to(root).as_posix()
                    if preserve_structure
                    else path.name
                    for path in files
                ],
            )

        reporter.report(
            phase="completed",
            message=f"Upload selesai: {succeeded} berhasil, {len(failed)} gagal",
            overall={
                "current": len(files),
                "total": len(files),
                "percent": 100,
                "unit": "files",
                "bytes_current": total_bytes,
                "bytes_total": total_bytes,
            },
            counters={"succeeded": succeeded, "failed": len(failed)},
            force=True,
        )
        return {
            "total": len(files),
            "succeeded": succeeded,
            "failed": failed,
            "rclone_upload": bool(payload.get("rclone_upload")),
            "rclone_destination": (
                rclone_result.get("destination") if rclone_result else None
            ),
            "rclone_uploaded": rclone_result.get("succeeded", 0) if rclone_result else 0,
            "rclone_files": rclone_result.get("files", []) if rclone_result else [],
        }

    def _backup(self, command: dict[str, Any]) -> dict[str, Any]:
        payload = command["payload"]
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        profiles = sorted(self.profile_manager.list_profiles())
        runtimes = [self.profile_manager.runtime(profile) for profile in profiles]

        def backup_progress(value: dict[str, Any]) -> None:
            percent = value.get("percent")
            reporter.report(
                phase=str(value.get("phase") or "staging"),
                message=str(value.get("message") or "Menyiapkan backup"),
                overall={
                    "current": value.get("files_current"),
                    "total": value.get("files_total"),
                    "percent": percent,
                    "unit": "files",
                    "bytes_total": value.get("bytes_total"),
                },
                transfer={
                    "eta_seconds": value.get("eta_seconds"),
                    "elapsed_seconds": value.get("elapsed_seconds"),
                },
                indeterminate=bool(value.get("indeterminate", percent is None)),
                force=str(value.get("phase")) == "staging" or percent == 100,
            )

        with ExitStack() as locks:
            for runtime in runtimes:
                locks.enter_context(runtime.export_operation_lock)
                locks.enter_context(runtime.download_operation_lock)
            archive = BackupService(
                self.config, progress_callback=backup_progress
            ).create_archive(
                str(payload["backup_run_id"]),
                str(payload["node_name"]),
                password=str(payload["password"]),
                volume_size=str(payload.get("volume_size") or self.config.backup_volume_size),
            )
        if not runtimes:
            raise RuntimeError("Tidak ada profile runtime untuk upload backup.")
        uploader = runtimes[0].export_tdl_client
        part_sizes = {part: part.stat().st_size for part in archive.parts}
        total_bytes = sum(part_sizes.values())
        completed_bytes = 0
        sent = 0
        with self._capture_tdl_output(uploader):
            for index, part in enumerate(archive.parts, start=1):
                size = part_sizes[part]
                upload_state = {"phase": "uploading"}
                reporter.reset_transfer()
                reporter.report(
                    phase="verifying",
                    message=f"Memverifikasi {part.name}",
                    overall={
                        "current": sent,
                        "total": len(archive.parts),
                        "unit": "parts",
                    },
                    item={
                        "name": part.name,
                        "index": index,
                        "total": len(archive.parts),
                        "size_bytes": size,
                    },
                    counters={"succeeded": sent},
                    indeterminate=True,
                    force=True,
                )
                digest, size = sha256_file(part)

                def part_progress(progress) -> None:
                    if (
                        upload_state["phase"] != "uploading"
                        or not _has_transfer_telemetry(progress)
                    ):
                        return
                    transfer = reporter.tdl_transfer(progress, total_bytes=size)
                    current_bytes = int(transfer.get("bytes_current") or 0)
                    overall_bytes = min(total_bytes, completed_bytes + current_bytes)
                    reporter.report(
                        phase="uploading_parts",
                        message=f"Mengupload {part.name}",
                        overall={
                            "current": sent,
                            "total": len(archive.parts),
                            "percent": (
                                overall_bytes * 100 / total_bytes
                                if total_bytes
                                else None
                            ),
                            "unit": "parts",
                            "bytes_current": overall_bytes,
                            "bytes_total": total_bytes,
                        },
                        item={
                            "name": part.name,
                            "index": index,
                            "total": len(archive.parts),
                            "size_bytes": size,
                            "percent": progress.percent,
                        },
                        transfer=transfer,
                        counters={"succeeded": sent},
                        indeterminate=progress.percent is None,
                    )

                def part_phase(phase: str) -> None:
                    upload_state["phase"] = phase
                    if phase == "resolving_message":
                        reporter.report(
                            phase=phase,
                            message=f"Menunggu konfirmasi Telegram untuk {part.name}",
                            overall={
                                "current": sent,
                                "total": len(archive.parts),
                                "unit": "parts",
                            },
                            item={
                                "name": part.name,
                                "index": index,
                                "total": len(archive.parts),
                                "size_bytes": size,
                                "percent": 100,
                            },
                            counters={"succeeded": sent},
                            indeterminate=True,
                            force=True,
                        )

                caption = (
                    f"Backup node={payload['node_name']} "
                    f"run={str(payload['backup_run_id'])[:12]}\nPart: {part.name}"
                )
                with self._capture_tdl_progress(uploader, part_progress):
                    result = uploader.upload(
                        part,
                        str(payload["channel_ref"]),
                        caption,
                        status_callback=part_phase,
                    )
                part_payload = {
                    "run_id": str(payload["backup_run_id"]),
                    "node_name": str(payload["node_name"]),
                    "part_name": part.name,
                    "channel_id": int(payload["channel_id"]),
                    "channel_message_id": result.message_id,
                    "file_size": size,
                    "sha256": digest,
                    "uploaded_at": archive.created_at,
                    "status": "active",
                }
                sent += 1
                completed_bytes += part_sizes[part]
                progress_payload = reporter.report(
                    phase="uploading_parts",
                    message=f"{part.name} selesai diupload",
                    overall={
                        "current": sent,
                        "total": len(archive.parts),
                        "percent": (
                            completed_bytes * 100 / total_bytes
                            if total_bytes
                            else 100
                        ),
                        "unit": "parts",
                        "bytes_current": completed_bytes,
                        "bytes_total": total_bytes,
                    },
                    item={
                        "name": part.name,
                        "index": index,
                        "total": len(archive.parts),
                        "size_bytes": size,
                        "percent": 100,
                    },
                    counters={"succeeded": sent},
                    force=True,
                )
                reporter.milestone(
                    "backup.part_uploaded",
                    progress=progress_payload,
                    result={"part": part_payload},
                )
        reporter.report(
            phase="completed",
            message=f"Backup selesai: {sent} part tersimpan",
            overall={
                "current": sent,
                "total": len(archive.parts),
                "percent": 100,
                "unit": "parts",
                "bytes_current": total_bytes,
                "bytes_total": total_bytes,
            },
            counters={"succeeded": sent},
            force=True,
        )
        for part in archive.parts:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("Could not remove backup staging %s", part)
        return {"parts": sent, "run_id": payload["backup_run_id"]}

    def _workspace_path(self, raw: str, *, require_absolute: bool = False) -> Path:
        root = Path(self.config.utility_workspace_root).resolve()
        path = Path(raw)
        if require_absolute and not path.is_absolute():
            raise ValueError("Path utility harus absolut dan berasal dari pilihan workspace.")
        if not path.is_absolute():
            path = root / path
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("Path harus berada di dalam workspace.") from exc
        return resolved

    def workspace_tree(self, raw: str = "/workspace") -> dict[str, Any]:
        """Return a safe, shallow directory listing for the active workspace."""
        root = Path(self.config.utility_workspace_root).resolve()
        current = self._workspace_path(raw or str(root))
        if not current.is_dir():
            raise ValueError("Folder workspace tidak ditemukan.")
        relative = current.relative_to(root)
        display_path = "/workspace" if not relative.parts else "/workspace/" + "/".join(relative.parts)
        items: list[dict[str, Any]] = []
        for entry in sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if entry.is_symlink():
                continue
            item_path = display_path.rstrip("/") + "/" + entry.name
            if entry.is_dir():
                try:
                    children = list(entry.iterdir())
                    files = sum(1 for child in children if child.is_file())
                    directories = sum(1 for child in children if child.is_dir())
                except OSError:
                    files, directories = 0, 0
                items.append({
                    "name": entry.name,
                    "path": item_path,
                    "kind": "directory",
                    "files": files,
                    "directories": directories,
                    "has_children": bool(files or directories),
                })
            elif entry.is_file():
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = None
                items.append({"name": entry.name, "path": item_path, "kind": "file", "size": size})
        return {"path": display_path, "items": items}

    def quickmode_scan(self) -> dict[str, Any]:
        """Return derived Quick Mode staging state for the manager UI."""
        workspace = self._quick_workspace(self.config)
        return {
            "worker": str(getattr(self.config, "backup_node_name", "local")),
            "items": scan_quick_stages(
                workspace,
                worker=str(getattr(self.config, "backup_node_name", "local")),
            ),
        }

    @staticmethod
    def _digest(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size
