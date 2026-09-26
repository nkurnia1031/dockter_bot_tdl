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

JAKARTA_TZ = ZoneInfo("Asia/Jakarta")


def jakarta_timestamp() -> str:
    """Return human-facing worker log timestamps in the project timezone."""
    return datetime.now(JAKARTA_TZ).isoformat()


_PROGRESS_BAR_RE = re.compile(r"\[[ .#<>-]{8,}\]\s*\[[^\]]+\]")
BAR_ONLY_PROGRESS_KEY = "__bar_only__"
RUNTIME_STATS_KEY = "__runtime_stats__"


def _is_named_progress_key(value: str | None) -> bool:
    return value not in {None, BAR_ONLY_PROGRESS_KEY, RUNTIME_STATS_KEY}


def progress_line_key(value: str) -> str | None:
    """Return a stable key for a repeated TDL progress-bar line.

    TDL prints the same transfer state repeatedly, often with a separate
    full-width bar line.  The text before the first bar identifies the active
    transfer; a blank prefix is the bar-only companion line.
    """
    line = str(value).strip()
    if is_tdl_telemetry_line(line):
        return RUNTIME_STATS_KEY
    match = _PROGRESS_BAR_RE.search(line)
    if match is None:
        return None
    prefix = line[: match.start()].strip()
    # The percentage is part of the changing bar state, not its identity.
    prefix = re.sub(r"\s+\d+(?:\.\d+)?%\s*$", "", prefix)
    return prefix[:240] or BAR_ONLY_PROGRESS_KEY


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


def _quick_message_matches(message: dict[str, Any], name: str, caption: str, message_id: int | None = None) -> bool:
    """Match a storage message without persisting or returning its contents."""
    if message_id is not None:
        try:
            if int(message.get("id")) != int(message_id):
                return False
        except (TypeError, ValueError):
            return False
        # The manifest stores the channel message ID immediately after the
        # physical upload. For photos, TDL may omit the original local name
        # from the exported message JSON, so an exact message ID is stronger
        # evidence than requiring the name to be repeated in the payload.
        return True
    haystack = json.dumps(message, ensure_ascii=False, default=str).casefold()
    caption_parts = [part.strip().casefold() for part in str(caption).splitlines() if part.strip()]
    return all(part in haystack for part in caption_parts) and str(name).casefold() in haystack


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
                if line.startswith("$ "):
                    retained = [
                        existing
                        for existing in self._lines
                        if progress_line_key(existing) is None
                    ]
                    self._lines = retained
                    self._characters = sum(len(existing) + 1 for existing in retained)
                progress_key = progress_line_key(line)
                if progress_key == BAR_ONLY_PROGRESS_KEY and any(
                    _is_named_progress_key(progress_line_key(existing))
                    for existing in self._lines
                ):
                    # TDL emits a descriptive transfer line followed by a
                    # full-width companion bar. Keep the informative line;
                    # retaining both duplicates the same state in the UI.
                    continue
                if progress_key is not None:
                    if _is_named_progress_key(progress_key):
                        retained = [
                            existing
                            for existing in self._lines
                            if progress_line_key(existing) != BAR_ONLY_PROGRESS_KEY
                        ]
                        self._lines = retained
                        self._characters = sum(len(existing) + 1 for existing in retained)
                    # Keep one current bar per transfer instead of filling the
                    # bounded snapshot with identical TDL redraws.
                    for index in range(len(self._lines) - 1, -1, -1):
                        if progress_line_key(self._lines[index]) != progress_key:
                            continue
                        removed = self._lines.pop(index)
                        self._characters -= len(removed) + 1
                        break
                line_size = len(line) + 1
                while self._lines and (
                    len(self._lines) >= self.max_lines
                    or self._characters + line_size > self.max_characters
                ):
                    removed = self._lines.pop(0)
                    self._characters -= len(removed) + 1
                    self.truncated = True
                if line_size > self.max_characters:
                    line = line[-max(1, self.max_characters - 1) :]
                    line_size = len(line) + 1
                    self.truncated = True
                self._lines.append(line)
                self._characters += line_size

    def value(self) -> dict[str, Any]:
        with self._lock:
            return {
                "lines": list(reversed(self._lines)),
                "line_count": len(self._lines),
                "truncated": self.truncated,
                "order": "newest_first",
            }


class CommandMilestoneRecorder:
    """Persist bounded command results without allowing telemetry to fail work."""

    def __init__(
        self,
        publisher: WorkerEventPublisher,
        job_id: str,
        secrets: list[str],
        before_command: Callable[[], None] | None = None,
    ):
        self.publisher = publisher
        self.job_id = job_id
        self.secrets = secrets
        self.before_command = before_command
        self._counter = 0
        self._lock = threading.Lock()

    def command_started(self, command: list[str], log_prefix: str) -> str:
        """Create the pending milestone before a subprocess begins work."""
        if self.before_command is not None:
            self.before_command()
        with self._lock:
            self._counter += 1
            command_id = f"{self.job_id}:command:{self._counter}"
        try:
            self.publisher.emit(
                self.job_id,
                "running",
                "command.started",
                result={
                    "command_id": command_id,
                    "command": sanitize_command(command, self.secrets),
                    "log_prefix": str(log_prefix),
                    "status": "running",
                },
            )
        except Exception:
            LOGGER.warning(
                "Command start milestone failed for job %s; physical command continues",
                self.job_id,
                exc_info=True,
            )
        return command_id

    def command_completed(
        self,
        command: list[str],
        returncode: int,
        output: str,
        duration_seconds: float,
        log_prefix: str,
        command_id: object | None = None,
    ) -> None:
        """Complete the pending milestone with bounded, sanitized output."""
        try:
            tail, truncated = bounded_output_tail(sanitize_text(output, self.secrets))
            result = {
                "command": sanitize_command(command, self.secrets),
                "log_prefix": str(log_prefix),
                "returncode": int(returncode),
                "duration_seconds": round(max(0.0, float(duration_seconds)), 3),
                "output_tail": [
                    sanitize_text(line, self.secrets)
                    for line in tail
                ],
                "output_truncated": bool(truncated),
            }
            if command_id is not None:
                result["command_id"] = str(command_id)
            self.publisher.emit(
                self.job_id,
                "running",
                "command.completed",
                result=result,
            )
        except Exception:
            LOGGER.warning(
                "Command milestone failed for job %s; physical command already finished",
                self.job_id,
                exc_info=True,
            )

    def __call__(
        self,
        command: list[str],
        returncode: int,
        output: str,
        duration_seconds: float,
        log_prefix: str,
    ) -> None:
        self.command_completed(
            command,
            returncode,
            output,
            duration_seconds,
            log_prefix,
        )


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
        self._workers: dict[str, str] = {}
        self._audit_callbacks: dict[str, Callable[[str], None]] = {}
        self._lock = threading.RLock()

    def bind_job_worker(self, job_id: str, worker: str) -> None:
        with self._lock:
            self._workers[str(job_id)] = str(worker)

    def register_audit_callback(
        self, job_id: str, callback: Callable[[str], None]
    ) -> None:
        with self._lock:
            self._audit_callbacks[str(job_id)] = callback

    def unregister_audit_callback(self, job_id: str) -> None:
        with self._lock:
            self._audit_callbacks.pop(str(job_id), None)

    def _audit(self, job_id: str, message: str) -> None:
        with self._lock:
            callback = self._audit_callbacks.get(str(job_id))
        if callback is None:
            return
        try:
            callback(message)
        except Exception:
            # A diagnostic sink must never affect telemetry or physical work.
            LOGGER.debug("Worker telemetry audit callback failed", exc_info=True)

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
        timeout_seconds: float = 5.0,
        max_attempts: int = 1,
    ) -> None:
        with self._lock:
            sequence = self._sequences.get(job_id, 1) + 1
            self._sequences[job_id] = sequence
            worker = self._workers.get(job_id)
        payload = {
            "sequence": sequence,
            "status": status,
            "event_type": event_type,
            "sent_at": utc_now().isoformat(),
            "transient": transient,
            "progress": json_value(progress or {}),
            "result": json_value(result) if result is not None else None,
            "error": json_value(error) if error is not None else None,
        }
        if worker:
            payload["worker"] = worker
        last_error: Exception | None = None
        attempts = max(1, int(max_attempts))
        timeout = max(0.5, float(timeout_seconds))
        started_monotonic = time.monotonic()
        self._audit(
            job_id,
            "[telemetry] send "
            f"sequence={sequence} event={event_type} transient={bool(transient)} "
            f"attempts={attempts} timeout={timeout:g}s",
        )
        for attempt in range(attempts):
            try:
                response = request_json(
                    self.backend_url,
                    self.token,
                    "POST",
                    f"/internal/v1/jobs/{job_id}/events",
                    payload,
                    timeout=timeout,
                )
                if isinstance(response, dict) and response.get("accepted") is False:
                    self._audit(
                        job_id,
                        "[telemetry] ignored "
                        f"sequence={sequence} event={event_type} reason=backend_rejected",
                    )
                    return
                self._audit(
                    job_id,
                    "[telemetry] delivered "
                    f"sequence={sequence} event={event_type} "
                    f"duration={time.monotonic() - started_monotonic:.3f}s",
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
                    self._audit(
                        job_id,
                        "[telemetry] ignored "
                        f"sequence={sequence} event={event_type} status=409 terminal",
                    )
                    return
                last_error = exc
                status = getattr(exc, "status", None)
                status_text = f" status={status}" if status is not None else ""
                self._audit(
                    job_id,
                    "[telemetry] failed "
                    f"sequence={sequence} event={event_type} attempt={attempt + 1}"
                    f" error_type={type(exc).__name__}{status_text}",
                )
                if attempt + 1 < attempts:
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
            self._workers.pop(job_id, None)
            self._audit_callbacks.pop(job_id, None)
