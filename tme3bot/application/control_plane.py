from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from tme3bot.application.ports import JobRepository, WorkerDispatcher
from tme3bot.application.worker_health import probe_worker_health
from tme3bot.application.job_scheduler import build_execution_plan
from tme3bot.background_schedule import run_event_driven_loop
from tme3bot.domain.models import Actor, DomainError, Job, JobEvent, JobStatus, utc_now
from tme3bot.domain.worker_contract import (
    CAP_QUICKMODE_STAGING,
    CAP_DURABLE_COMMANDS_V1,
    CAP_BACKUP_VERIFY,
    CAP_PUBLIC_DOWNLOAD_LINKS,
    CAP_SAFELINK_RESOLVE,
    CAP_SHARED_EXPORT_CURSOR,
    CAP_STORAGE_DOWNLOAD,
    CAP_TTS,
    DURABLE_COMMAND_CAPABILITIES,
    require_worker_contract,
)
from tme3bot.chat_refs import normalize_tdl_chat_ref
from tme3bot.tdl_access_fingerprint import (
    normalize_profiles,
    normalize_session_fingerprints,
)
from tme3bot.url_parser import parse_tme3_url
from tme3bot.utility import (
    DEFAULT_UTILITY_SETTINGS,
    normalize_video_options,
    validate_rclone_destination,
)
from tme3bot.safelink import normalize_shortlink_url
from tme3bot.worker_registry import worker_local_urls, worker_names_for_mode

_DURABLE_JOB_KINDS = frozenset({
    "export", "leave", "download", "utility", "storage_upload", "storage_download", "tts",
    "safelink_resolve", "tdl_access_verify", "backup_verify", "chat_send",
})
_STORAGE_DURABLE_DISPATCH_KEY = "_storage_durable_dispatch"
_WORKER_UNRESPONSIVE_EVENT_LATENCY_MS = 2_000.0
_WORKER_UNRESPONSIVE_CANCEL_TIMEOUT_SECONDS = 2.5
_WORKER_HEALTH_UNSET = object()
_LITE_PROGRESS_COUNTER_FIELDS = (
    "succeeded", "failed", "skipped", "ambiguous", "cancelled", "retryable",
)
_LITE_PROGRESS_OUTCOME_COUNTER_FIELDS = (
    "succeeded", "failed", "skipped", "ambiguous", "cancelled",
)
_LITE_PROGRESS_SUMMARY_FIELDS = (
    "active_file", "stage", "status", "completed", "processed",
    "processed_from_counters", "total", "unit", "percent",
    "progress_updated_at", "worker_updated_at", *_LITE_PROGRESS_COUNTER_FIELDS,
)
_ACTIVE_PROGRESS_REFRESH_STATUSES = (
    JobStatus.QUEUED.value,
    JobStatus.DISPATCHED.value,
    JobStatus.RUNNING.value,
    JobStatus.PAUSED.value,
)


class ControlPlane:
    """Application facade used by every frontend adapter."""

    def __init__(
        self,
        jobs: JobRepository,
        dispatcher: WorkerDispatcher,
        profile_manager,
        *,
        storage_catalog=None,
        export_catalog=None,
        worker_registry=None,
        utility_folders=None,
        utility_settings=None,
        runtime_settings_store=None,
        backup_coordinator=None,
        storage_delivery=None,
        local_profile_catalog=None,
        runtime_readiness_gate=None,
        label_store=None,
        export_cursor_service=None,
        tdl_access_store=None,
        tdl_access_target_resolver=None,
        job_stall_timeout_seconds: int = 600,
        job_cancel_grace_seconds: int = 30,
        gateway_mode: str = "full",
        gateway_lite_local_stack_enabled: bool = False,
        worker_health_cache=None,
        worker_restart_store=None,
        scheduler_recovery_seconds: float = 2.0,
    ) -> None:
        self.jobs = jobs
        self.dispatcher = dispatcher
        self.profile_manager = profile_manager
        self.storage_catalog = storage_catalog
        self.export_catalog = export_catalog
        self.worker_registry = worker_registry
        self.utility_folders = utility_folders
        self.utility_settings = utility_settings
        self.runtime_settings_store = runtime_settings_store
        self.backup_coordinator = backup_coordinator
        self.storage_delivery = storage_delivery
        self.local_profile_catalog = local_profile_catalog
        self.runtime_readiness_gate = runtime_readiness_gate
        self.label_store = label_store
        self.export_cursor_service = export_cursor_service
        self.tdl_access_store = tdl_access_store
        self.tdl_access_target_resolver = tdl_access_target_resolver
        self.gateway_mode = str(gateway_mode or "full").strip().lower()
        self.gateway_lite_local_stack_enabled = bool(
            gateway_lite_local_stack_enabled
        )
        self.worker_health_cache = worker_health_cache
        self.worker_restart_store = worker_restart_store
        self.scheduler_recovery_seconds = max(0.1, float(scheduler_recovery_seconds))
        self._clock = utc_now
        self.job_stall_timeout_seconds = max(0, int(job_stall_timeout_seconds))
        self.job_cancel_grace_seconds = max(0, int(job_cancel_grace_seconds))
        self._event_observers: list[Callable[[JobEvent], None]] = []
        self._scheduler_stop = threading.Event()
        self._scheduler_wake = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        self._stale_cancel_requested: dict[str, Any] = {}
        self._stale_worker_probe_results: dict[str, tuple[Any, bool]] = {}
        self._stale_job_lock = threading.RLock()
        self._high_latency_cancel_attempts: dict[str, dict[str, Any]] = {}
        self._unresponsive_workers: dict[str, str] = {}
        self._storage_source_action_guard = threading.Lock()
        self._storage_source_action_locks: dict[str, dict[str, Any]] = {}
        self._tts_route_lock = threading.Lock()
        self._tts_round_robin = 0
        self._tts_sender_round_robin: dict[str, int] = {}
        self.add_event_observer(self._invalidate_runtime_readiness_from_event)
        self._restore_unresponsive_workers()

    @staticmethod
    def _job_event_latency_ms(job: Job) -> float | None:
        progress = job.progress if isinstance(job.progress, dict) else {}
        observability = progress.get("observability")
        observability = observability if isinstance(observability, dict) else {}
        event_latency = observability.get("event_latency")
        event_latency = event_latency if isinstance(event_latency, dict) else {}
        value = event_latency.get("last_ms")
        if not isinstance(value, (int, float)) or value < 0:
            telemetry = progress.get("backend_telemetry")
            telemetry = telemetry if isinstance(telemetry, dict) else {}
            value = telemetry.get("event_latency_ms")
        if not isinstance(value, (int, float)) or value < 0:
            return None
        return float(value)

    @staticmethod
    def _progress_number(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    @classmethod
    def _compact_worker_progress(
        cls,
        stored_progress: dict[str, Any],
        worker_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Keep only the compact fields Lite needs from a worker checkpoint."""
        merged = dict(stored_progress) if isinstance(stored_progress, dict) else {}
        snapshot = worker_snapshot if isinstance(worker_snapshot, dict) else {}
        worker_progress = snapshot.get("progress")
        if isinstance(worker_progress, dict):
            merged.update(worker_progress)

        item = merged.get("item") if isinstance(merged.get("item"), dict) else {}
        overall = merged.get("overall") if isinstance(merged.get("overall"), dict) else {}
        active_items = merged.get("active_items")
        active_item = (
            active_items[0]
            if isinstance(active_items, list)
            and active_items
            and isinstance(active_items[0], dict)
            else {}
        )
        name = (
            active_item.get("name")
            or item.get("name")
            or merged.get("tdl_file_name")
            or merged.get("current_json_name")
        )
        if isinstance(name, str):
            name = name.replace("\x00", "").strip()[:255] or None
        else:
            name = None

        completed_value = overall.get("files_current", overall.get("current"))
        total_value = overall.get("files_total", overall.get("total"))
        unit = overall.get("unit")
        unit = str(unit)[:32] if isinstance(unit, str) and unit else None
        if unit is None and any(key in overall for key in ("files_current", "files_total")):
            unit = "files"
        if completed_value is None:
            completed_value = merged.get("current_json_index")
        if total_value is None:
            total_value = merged.get("total_json")

        def count_value(value: Any) -> int | None:
            parsed = cls._progress_number(value)
            return max(0, int(parsed)) if parsed is not None else None

        completed = count_value(completed_value)
        total = count_value(total_value)
        raw_counters = merged.get("counters")
        raw_counters = raw_counters if isinstance(raw_counters, dict) else {}
        counters = {
            counter_name: count_value(raw_counters.get(counter_name))
            for counter_name in _LITE_PROGRESS_COUNTER_FIELDS
        }
        outcome_counters_available = any(
            counters[counter_name] is not None
            for counter_name in _LITE_PROGRESS_OUTCOME_COUNTER_FIELDS
        )
        if outcome_counters_available:
            for counter_name in ("succeeded", "failed", "skipped"):
                counters[counter_name] = (
                    counters[counter_name] if counters[counter_name] is not None else 0
                )
        processed_from_counters = outcome_counters_available
        processed = completed
        if processed_from_counters:
            processed = sum(
                counters[counter_name] or 0
                for counter_name in _LITE_PROGRESS_OUTCOME_COUNTER_FIELDS
            )
        percent_value = cls._progress_number(
            overall.get("percent", item.get("percent", merged.get("tdl_percent")))
        )
        percent_progress = completed if completed is not None else processed
        if percent_value is None and percent_progress is not None and total:
            percent_value = percent_progress * 100 / total
        percent = (
            round(min(100.0, max(0.0, percent_value)), 1)
            if percent_value is not None
            else None
        )
        stage = merged.get("phase") or snapshot.get("phase")
        status = item.get("status") or active_item.get("status") or snapshot.get("status")
        progress_updated_at = merged.get("updated_at")
        progress_updated_at = (
            progress_updated_at[:64]
            if isinstance(progress_updated_at, str) and progress_updated_at
            else None
        )
        return {
            "active_file": name,
            "stage": str(stage)[:80] if stage else None,
            "status": str(status)[:80] if status else None,
            "completed": completed,
            "processed": processed,
            "processed_from_counters": processed_from_counters,
            "total": total,
            "unit": unit,
            "percent": percent,
            "progress_updated_at": progress_updated_at,
            **counters,
        }

    @classmethod
    def _stale_worker_progress(
        cls, job: Job, checked_at: str, reason_code: str
    ) -> dict[str, Any]:
        previous = job.progress.get("lite_worker_refresh")
        summary = cls._compact_worker_progress(job.progress)
        if isinstance(previous, dict):
            for key in _LITE_PROGRESS_SUMMARY_FIELDS:
                current_value = summary.get(key)
                previous_value = previous.get(key)
                if previous_value is not None and (
                    current_value is None
                    or (
                        key == "processed_from_counters"
                        and current_value is False
                        and previous_value is True
                    )
                ):
                    summary[key] = previous_value
            refreshed_at = previous.get("refreshed_at")
        else:
            refreshed_at = None
        return {
            **summary,
            "state": "stale",
            "stale": True,
            "checked_at": checked_at,
            "refreshed_at": refreshed_at,
            "reason_code": reason_code,
        }

    @staticmethod
    def _job_has_unconfirmed_worker_cancel(job: Job) -> bool:
        progress = job.progress if isinstance(job.progress, dict) else {}
        result = job.result if isinstance(job.result, dict) else {}
        return bool(
            job.status == JobStatus.CANCELLED
            and progress.get("worker_unresponsive") is True
            and progress.get("worker_confirmation") == "not_received"
            and not result.get("late_worker_terminal")
        )

    @staticmethod
    def _job_unresponsive_reason(job: Job) -> str:
        progress = job.progress if isinstance(job.progress, dict) else {}
        return str(
            progress.get("worker_unresponsive_reason")
            or "event_backlog_cancel_unconfirmed"
        )[:96]

    @staticmethod
    def _persisted_high_latency_cancel_request(job: Job) -> dict[str, Any] | None:
        progress = job.progress if isinstance(job.progress, dict) else {}
        request = progress.get("backend_cancel_request")
        if not isinstance(request, dict):
            return None
        # Only an operator Stop may survive into the recovery loop. Older
        # versions also wrote this marker automatically when telemetry was
        # delayed, so untagged markers must not trigger another cancellation.
        if request.get("source") != "operator_stop":
            return None
        status = str(request.get("signal_status") or "")
        if status not in {"pending", "accepted"}:
            return None
        try:
            latency_ms = float(request.get("latency_ms"))
        except (TypeError, ValueError):
            latency_ms = _WORKER_UNRESPONSIVE_EVENT_LATENCY_MS
        return {
            "requested_at": request.get("requested_at"),
            "signal_status": status,
            "latency_ms": max(0.0, latency_ms),
            "source": "operator_stop",
            "in_flight": False,
        }

    @staticmethod
    def _cancelled_after_stop_event(event: JobEvent) -> JobEvent:
        """Keep the public lifecycle cancelled while retaining worker outcome."""
        progress = dict(event.progress or {})
        progress.update(
            {
                "phase": "cancelled",
                "terminal_phase": "cancelled",
                "finished_at": event.created_at.isoformat(),
                "cancelled_after_stop": True,
                "worker_terminal_status": event.status.value,
                "worker_terminal_event_type": event.event_type,
                "worker_terminal_error": _redact_secrets(event.error),
            }
        )
        return replace(
            event,
            status=JobStatus.CANCELLED,
            event_type="cancelled_after_stop",
            progress=progress,
            error={
                "code": "JOB_TERMINATED",
                "message": (
                    "Permintaan Stop diterima; event terminal worker setelahnya "
                    "tidak mengubah status pembatalan."
                ),
            },
        )

    @staticmethod
    def _cancel_request_time(request: dict[str, Any]) -> datetime | None:
        value = request.get("requested_at")
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None
        else:
            return None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

    def _cancel_request_grace_expired(
        self, request: dict[str, Any], now: datetime
    ) -> bool:
        requested_at = self._cancel_request_time(request)
        if requested_at is None:
            return True
        current_time = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
        return (
            current_time - requested_at
        ).total_seconds() >= self.job_cancel_grace_seconds

    def _persist_high_latency_cancel_request(
        self, job: Job, request: dict[str, Any]
    ) -> Job:
        current = self.jobs.get(job.id)
        if current is None or current.status.terminal:
            return current or job
        requested_at = self._cancel_request_time(request)
        cancel_metadata = {
            "requested_at": (
                requested_at.isoformat() if requested_at is not None else ""
            ),
            "signal_status": str(request.get("signal_status") or "pending"),
            "latency_ms": round(float(request.get("latency_ms") or 0.0), 3),
            "source": str(request.get("source") or "operator_stop"),
        }
        updated, _ = self.jobs.update_progress_metadata(
            current.id,
            {"backend_cancel_request": cancel_metadata},
            remove_keys=("backend_telemetry",),
        )
        return updated

    def _clear_pending_cancel_request(self, job_id: str) -> None:
        with self._stale_job_lock:
            current = self.jobs.get(job_id)
            if current is not None and not current.status.terminal:
                self.jobs.update_progress_metadata(
                    job_id, {}, remove_keys=("backend_cancel_request",)
                )
            self._high_latency_cancel_attempts.pop(job_id, None)

    def _restore_unresponsive_workers(self) -> None:
        reader = getattr(self.jobs, "unconfirmed_worker_cancellations", None)
        lister = getattr(self.jobs, "list", None)
        marker = getattr(self.worker_health_cache, "mark_unresponsive", None)
        if not callable(reader) and not callable(lister):
            return
        try:
            jobs = (
                reader()
                if callable(reader)
                else lister(
                    status=JobStatus.CANCELLED.value,
                    archived=None,
                    offset=0,
                    limit=1_000,
                )
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Could not restore worker quarantine state"
            )
            return
        for job in jobs:
            if not self._job_has_unconfirmed_worker_cancel(job):
                continue
            worker = str(job.worker or "").strip().lower()
            if not worker:
                continue
            reason = self._job_unresponsive_reason(job)
            self._unresponsive_workers[worker] = reason
            if callable(marker):
                marker(worker, reason=reason)

    def _mark_worker_unresponsive(self, worker: str, *, reason: str) -> None:
        name = str(worker or "").strip().lower()
        if not name:
            return
        safe_reason = str(reason or "worker_unresponsive")[:96]
        with self._stale_job_lock:
            self._unresponsive_workers[name] = safe_reason
        marker = getattr(self.worker_health_cache, "mark_unresponsive", None)
        if callable(marker):
            marker(name, reason=safe_reason)

    def _clear_worker_unresponsive(self, worker: str) -> None:
        name = str(worker or "").strip().lower()
        with self._stale_job_lock:
            self._unresponsive_workers.pop(name, None)
            self._stale_worker_probe_results.pop(name, None)
        clearer = getattr(self.worker_health_cache, "clear_unresponsive", None)
        if callable(clearer):
            clearer(name)

    def _worker_unresponsive_reason(
        self, worker: str, *, health_snapshot: Any = _WORKER_HEALTH_UNSET
    ) -> str | None:
        name = str(worker or "").strip().lower()
        restarting = getattr(self.worker_restart_store, "has_active_restart", None)
        if callable(restarting) and restarting(name):
            return "worker_restart_in_progress"
        should_probe = health_snapshot is _WORKER_HEALTH_UNSET
        if health_snapshot is _WORKER_HEALTH_UNSET:
            snapshotter = getattr(self.worker_health_cache, "snapshot", None)
            health_snapshot = snapshotter(name) if callable(snapshotter) else None
        if (
            isinstance(health_snapshot, dict)
            and health_snapshot.get("status") == "ready"
            and health_snapshot.get("healthy") is True
        ):
            self._clear_worker_unresponsive(name)
            return None
        with self._stale_job_lock:
            reason = self._unresponsive_workers.get(name)
        snapshot_unresponsive = (
            isinstance(health_snapshot, dict)
            and health_snapshot.get("status") in {"offline", "unresponsive"}
        )
        if not reason and not snapshot_unresponsive:
            return None

        # A delayed event or old health snapshot is not a reachability result.
        # Confirm with at most two fresh probes before holding worker admission.
        probe_confirmed = bool(
            isinstance(health_snapshot, dict)
            and health_snapshot.get("restart_probe_confirmed") is True
        )
        if (
            should_probe
            and isinstance(health_snapshot, dict)
            and health_snapshot.get("status") == "offline"
            and probe_confirmed
            and health_snapshot.get("age_seconds") is not None
        ):
            # WorkerHealthMonitor already ran two probes and keeps this
            # confirmation only while its snapshot is fresh. Reuse it across
            # queued jobs instead of probing the same offline worker again.
            should_probe = False
        if should_probe or (snapshot_unresponsive and not probe_confirmed):
            health_snapshot = self._probe_worker_health_snapshot(name)
        if (
            isinstance(health_snapshot, dict)
            and health_snapshot.get("status") == "ready"
            and health_snapshot.get("healthy") is True
        ):
            self._clear_worker_unresponsive(name)
            return None
        status = (
            str((health_snapshot or {}).get("status") or "").strip().lower()
            if isinstance(health_snapshot, dict)
            else ""
        )
        probe_confirmed = bool(
            isinstance(health_snapshot, dict)
            and health_snapshot.get("restart_probe_confirmed") is True
        )
        if status in {"offline", "unresponsive"} and probe_confirmed:
            if reason:
                return reason
            return str((health_snapshot or {}).get("reason") or "worker_offline")
        # Unknown/stale/one failed probe does not quarantine a worker. The
        # actual requested operation is allowed to verify its own endpoint.
        return None

    def _probe_worker_health_snapshot(self, worker: str) -> dict[str, Any] | None:
        name = str(worker or "").strip().lower()
        probe = getattr(self.worker_health_cache, "probe_worker", None)
        if callable(probe):
            try:
                result = probe(name)
            except Exception:
                result = None
            if isinstance(result, dict):
                status = str(result.get("status") or "").strip().lower()
                if status in {"ready", "offline", "unresponsive", "disabled", "unknown", "stale"}:
                    return result
                return None

        checker = getattr(self.dispatcher, "check_worker_fast", None)
        if not callable(checker):
            return None
        return probe_worker_health(checker, name)

    def _require_worker_responsive(
        self, worker: str, *, health_snapshot: Any = _WORKER_HEALTH_UNSET
    ) -> None:
        reason = self._worker_unresponsive_reason(
            worker, health_snapshot=health_snapshot
        )
        if reason:
            if reason == "worker_restart_in_progress":
                raise DomainError(
                    "WORKER_RESTART_IN_PROGRESS",
                    f"Worker {worker} sedang direstart; job baru ditahan sampai operasi selesai.",
                    status_code=409,
                    details={"worker": str(worker), "health": "restarting"},
                )
            offline = reason == "worker_offline"
            raise DomainError(
                "WORKER_OFFLINE" if offline else "WORKER_UNRESPONSIVE",
                f"Worker {worker} tidak dapat dijangkau atau tidak sehat. Periksa worker dan restart jika diperlukan.",
                status_code=503,
                details={
                    "worker": str(worker),
                    "health": "offline" if offline else "unresponsive",
                    "reason": reason,
                },
            )

    def _refresh_worker_unresponsive_state(self, worker: str) -> None:
        reader = getattr(self.jobs, "unconfirmed_worker_cancellations", None)
        lister = getattr(self.jobs, "list", None)
        if not callable(reader) and not callable(lister):
            return
        try:
            jobs = (
                reader(worker=str(worker or "").strip().lower())
                if callable(reader)
                else lister(
                    status=JobStatus.CANCELLED.value,
                    worker=str(worker or "").strip().lower(),
                    archived=None,
                    offset=0,
                    limit=1_000,
                )
            )
        except Exception:
            # Keep the quarantine when its persisted evidence cannot be read.
            return
        normalized = str(worker or "").strip().lower()
        remaining = next(
            (
                job for job in jobs
                if self._job_has_unconfirmed_worker_cancel(job)
            ),
            None,
        )
        if remaining is None:
            self._clear_worker_unresponsive(normalized)
        else:
            self._mark_worker_unresponsive(
                normalized, reason=self._job_unresponsive_reason(remaining)
            )

    @contextmanager
    def _storage_source_action_lock(self, source_job_id: str):
        key = str(source_job_id)
        with self._storage_source_action_guard:
            entry = self._storage_source_action_locks.get(key)
            if entry is None:
                entry = {"lock": threading.RLock(), "users": 0}
                self._storage_source_action_locks[key] = entry
            entry["users"] += 1
        try:
            with entry["lock"]:
                yield
        finally:
            with self._storage_source_action_guard:
                entry["users"] -= 1
                if entry["users"] == 0 and self._storage_source_action_locks.get(key) is entry:
                    del self._storage_source_action_locks[key]

    def actor(self, telegram_user_id: int) -> Actor:
        profile = self.profile_manager.profile_for_user(telegram_user_id)
        if profile is None:
            raise DomainError(
                "UNAUTHORIZED_ACTOR",
                "Telegram user belum memiliki identity TDL.",
                status_code=403,
            )
        return Actor(int(telegram_user_id), profile)

    def refresh_active_job_progress(self, actor: Actor) -> dict[str, Any]:
        """Refresh compact worker checkpoints for this actor's active jobs."""
        selected_profile = self.require_profile(actor, None)
        total = self.jobs.count(
            profile=selected_profile,
            statuses=_ACTIVE_PROGRESS_REFRESH_STATUSES,
            archived=False,
        )
        active_jobs: list[Job] = []
        offset = 0
        while offset < total:
            page = self.jobs.list(
                profile=selected_profile,
                statuses=_ACTIVE_PROGRESS_REFRESH_STATUSES,
                archived=False,
                offset=offset,
                limit=500,
            )
            if not page:
                break
            active_jobs.extend(page)
            offset += len(page)

        worker_jobs: dict[str, list[str]] = {}
        waiting_jobs: set[str] = set()
        for job in active_jobs:
            pause_kind = str(job.progress.get("pause_kind") or "")
            if job.status == JobStatus.QUEUED or (
                job.status == JobStatus.PAUSED and pause_kind == "queued"
            ):
                waiting_jobs.add(job.id)
                continue
            worker_jobs.setdefault(str(job.worker or "").strip(), []).append(job.id)

        snapshots_by_worker: dict[str, dict[str, dict[str, Any]]] = {}
        failed_workers: set[str] = set()

        def read_worker_snapshots(worker: str, job_ids: list[str]):
            reader = getattr(self.dispatcher, "job_progress_snapshots", None)
            if not callable(reader):
                raise RuntimeError("worker progress snapshot is unavailable")
            return reader(worker, job_ids)

        selected_workers = [(worker, ids) for worker, ids in worker_jobs.items() if worker]
        if selected_workers:
            with ThreadPoolExecutor(max_workers=min(8, len(selected_workers))) as pool:
                futures = {
                    pool.submit(read_worker_snapshots, worker, ids): worker
                    for worker, ids in selected_workers
                }
                for future in as_completed(futures):
                    worker = futures[future]
                    try:
                        raw_items = future.result()
                        items = (
                            raw_items.get("items", [])
                            if isinstance(raw_items, dict)
                            else raw_items
                        )
                        if not isinstance(items, list):
                            raise ValueError("worker progress response is invalid")
                        allowed_ids = set(worker_jobs[worker])
                        snapshots_by_worker[worker] = {
                            str(item.get("job_id")): item
                            for item in items
                            if isinstance(item, dict)
                            and str(item.get("job_id") or "") in allowed_ids
                        }
                    except Exception as exc:
                        failed_workers.add(worker)
                        logging.getLogger(__name__).info(
                            "Manual job progress refresh failed for worker %s (%s)",
                            worker,
                            type(exc).__name__,
                        )

        checked_at = utc_now().isoformat()
        updated_jobs: list[Job] = []
        for job in active_jobs:
            if job.id in waiting_jobs:
                snapshot = {
                    **self._compact_worker_progress(job.progress),
                    "state": "waiting_worker",
                    "stale": False,
                    "checked_at": checked_at,
                    "refreshed_at": None,
                }
            else:
                worker = str(job.worker or "").strip()
                worker_snapshot = snapshots_by_worker.get(worker, {}).get(job.id)
                if worker in failed_workers or not worker:
                    reason_code = "WORKER_UNAVAILABLE" if worker else "WORKER_UNASSIGNED"
                    snapshot = self._stale_worker_progress(job, checked_at, reason_code)
                elif worker_snapshot is None:
                    snapshot = self._stale_worker_progress(
                        job, checked_at, "SNAPSHOT_NOT_FOUND"
                    )
                else:
                    snapshot = {
                        **self._compact_worker_progress(job.progress, worker_snapshot),
                        "state": "fresh",
                        "stale": False,
                        "checked_at": checked_at,
                        "refreshed_at": checked_at,
                    }
                    source_updated_at = worker_snapshot.get("updated_at")
                    if isinstance(source_updated_at, str) and source_updated_at:
                        snapshot["worker_updated_at"] = source_updated_at[:64]
            current, _ = self.jobs.update_progress_metadata(
                job.id, {"lite_worker_refresh": snapshot}
            )
            updated_jobs.append(current)
        return {
            "items": updated_jobs,
            "total": len(updated_jobs),
            "checked_at": checked_at,
        }

    def _worker_names_for_mode(self, selected=None) -> list[str]:
        registry = self.worker_registry
        if registry is None:
            return []
        list_workers = getattr(registry, "list", None)
        records = list_workers() if callable(list_workers) else None
        names = list(records) if isinstance(records, dict) else list(registry.names())
        if selected is not None:
            selected_names = {str(name) for name in selected}
            names = [name for name in names if name in selected_names]
        if not isinstance(records, dict):
            records = {}
            for name in names:
                record = registry.get(name)
                if isinstance(record, dict):
                    records[name] = record
        else:
            records = {name: records[name] for name in names if name in records}
        config = getattr(self.profile_manager, "base_config", None)
        return worker_names_for_mode(
            records,
            self.gateway_mode,
            local_urls=worker_local_urls(config),
            include_local_in_lite=self.gateway_lite_local_stack_enabled,
        )

    def require_profile(self, actor: Actor, profile: str | None) -> str:
        selected = profile or actor.profile
        available = getattr(self.profile_manager, "list_profiles", None)
        profiles = list(available()) if callable(available) else []
        if (
            selected != actor.profile
            and profiles
            and selected not in profiles
            and not self.verified_profile_workers(selected)
        ):
            raise DomainError(
                "PROFILE_NOT_FOUND",
                "Profile target tidak ditemukan.",
                status_code=404,
            )
        return selected

    def verified_profile_workers(self, profile: str) -> set[str] | None:
        """Return catalog owners, or None when catalog admission is not configured."""
        store = self.local_profile_catalog
        snapshot = getattr(store, "snapshot", None)
        if not callable(snapshot):
            return None
        normalized = str(profile or "").strip().lower()
        catalog = snapshot()
        for item in catalog.get("profiles", []) if isinstance(catalog, dict) else []:
            if not isinstance(item, dict) or str(item.get("name") or "").strip().lower() != normalized:
                continue
            raw_workers = item.get("workers")
            if not isinstance(raw_workers, list):
                return set()
            return {
                str(worker or "").strip().lower()
                for worker in raw_workers
                if str(worker or "").strip()
            }
        return set()

    def verified_profiles_for_worker(self, worker: str) -> list[str] | None:
        """Return verified catalog profiles for a worker, or None without a catalog."""
        snapshot = getattr(self.local_profile_catalog, "snapshot", None)
        if not callable(snapshot):
            return None
        normalized_worker = str(worker or "").strip().lower()
        catalog = snapshot()
        return sorted({
            str(item.get("name") or "").strip().lower()
            for item in (catalog.get("profiles", []) if isinstance(catalog, dict) else [])
            if isinstance(item, dict)
            and normalized_worker in {
                str(owner or "").strip().lower()
                for owner in (item.get("workers") or [])
            }
            and str(item.get("name") or "").strip()
        })

    def _require_lite_explicit_worker(self, requested_worker: str | None) -> None:
        if self.gateway_mode == "lite" and not str(requested_worker or "").strip():
            raise DomainError(
                "LITE_REMOTE_WORKER_REQUIRED",
                "Pilih worker secara eksplisit; Lite tidak memakai route otomatis.",
                status_code=422,
            )

    def resolve_target(
        self, actor: Actor, *, profile: str | None = None, worker: str | None = None,
        allow_disabled_worker: bool = False,
    ) -> tuple[str, str]:
        self._require_lite_explicit_worker(worker)
        selected_profile = self.require_profile(actor, profile)
        # Profile catalogs and stored scan evidence may help choose a target;
        # the selected worker's actual command is the source of truth.
        owners = self.verified_profile_workers(selected_profile) if profile is not None else None
        routed = str(self.profile_manager.worker_route(selected_profile) or "").strip().lower()
        if worker:
            selected_worker = str(worker).strip().lower()
        elif owners:
            selected_worker = routed if routed in owners else sorted(owners)[0]
        else:
            selected_worker = routed
        if not selected_worker:
            raise DomainError("WORKER_REQUIRED", "Worker target wajib dipilih.", status_code=422)
        if self.worker_registry is not None:
            names = self.worker_registry.names()
            if names and selected_worker not in names:
                raise DomainError("WORKER_NOT_FOUND", "Worker target tidak ditemukan.", status_code=404)
            get_worker = getattr(self.worker_registry, "get", None)
            worker_record = get_worker(selected_worker) if callable(get_worker) else None
            if (
                worker_record is not None
                and not bool(worker_record.get("enabled", True))
                and not allow_disabled_worker
            ):
                raise DomainError(
                    "WORKER_DISABLED",
                    "Worker sedang dinonaktifkan dan tidak menerima job baru.",
                    status_code=409,
                )
        if self.gateway_mode == "lite":
            self._require_lite_remote_worker(
                selected_worker, requested_worker=worker
            )
        else:
            self._require_worker_responsive(selected_worker)
        return selected_profile, selected_worker

    def _require_lite_remote_worker(
        self, selected_worker: str, *, requested_worker: str | None
    ) -> None:
        if self.gateway_mode != "lite":
            return
        self._require_lite_explicit_worker(requested_worker)
        worker_name = str(selected_worker or "").strip().lower()
        config = getattr(self.profile_manager, "base_config", None)
        if not worker_name:
            raise DomainError(
                "LITE_REMOTE_WORKER_REQUIRED",
                "Pilih worker yang terdaftar dan aktif secara eksplisit.",
                status_code=409,
            )
        registry = self.worker_registry
        get_worker = getattr(registry, "get", None)
        record = get_worker(worker_name) if callable(get_worker) else None
        if record is None:
            raise DomainError(
                "WORKER_NOT_FOUND",
                "Worker tidak terdaftar. Pilih worker yang tersedia dan aktif.",
                status_code=404,
            )
        if not worker_names_for_mode(
            {worker_name: record},
            "lite",
            local_urls=worker_local_urls(config),
            include_local_in_lite=self.gateway_lite_local_stack_enabled,
        ):
            raise DomainError(
                "LITE_REMOTE_WORKER_REQUIRED",
                "Worker ini tidak tersedia pada konfigurasi Lite saat ini.",
                status_code=409,
            )
        if not bool(record.get("enabled", True)):
            raise DomainError(
                "WORKER_DISABLED",
                "Worker sedang dinonaktifkan dan tidak menerima job baru.",
                status_code=409,
            )
        snapshotter = getattr(self.worker_health_cache, "snapshot", None)
        snapshot = snapshotter(worker_name) if callable(snapshotter) else None
        if not (
            isinstance(snapshot, dict)
            and snapshot.get("status") == "ready"
            and snapshot.get("healthy") is True
        ):
            snapshot = self._probe_worker_health_snapshot(worker_name)
        # Unknown/stale snapshots are not proof of a dead worker. The shared
        # gate performs up to two fresh probes and blocks only when both fail.
        self._require_worker_responsive(worker_name, health_snapshot=snapshot)

    def _worker_ack_wait_timed_out(self, stored: dict[str, Any]) -> bool:
        if self.gateway_mode != "lite":
            return False
        raw = str(stored.get("worker_ack_wait_started_at") or "").strip()
        if not raw:
            return False
        try:
            started = datetime.fromisoformat(raw)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return (now - started).total_seconds() >= 600

    def _expire_worker_ack_wait(self, job: Job) -> dict[str, str]:
        self._fail_queued_job(
            job,
            "WORKER_ACK_TIMEOUT",
            "Worker tidak mengakui job dalam 10 menit; job dihentikan tanpa dialihkan ke worker lain.",
        )
        return {"status": "terminal", "reason": "worker_ack_timeout"}

    def _wait_for_worker_ack(self, job: Job, stored: dict[str, Any]) -> bool:
        """Persist Lite's connectivity-only acknowledgement deadline."""
        if self.gateway_mode != "lite":
            return False
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        updater = getattr(self.jobs, "update_command_payload_fields", None)
        if callable(updater):
            current = updater(
                job.id,
                set_if_missing={"worker_ack_wait_started_at": now.isoformat()},
            ) or {}
        else:
            current = self.jobs.command_payload(job.id)
            if not isinstance(current, dict):
                current = dict(stored)
            if not current.get("worker_ack_wait_started_at"):
                current["worker_ack_wait_started_at"] = now.isoformat()
                self.jobs.update_command_payload(job.id, current)
        if self._worker_ack_wait_timed_out(current):
            self._expire_worker_ack_wait(job)
            return True
        return False

    def _clear_worker_ack_wait(self, job_id: str, stored: dict[str, Any]) -> None:
        if self.gateway_mode != "lite":
            return
        updater = getattr(self.jobs, "update_command_payload_fields", None)
        if callable(updater):
            updater(job_id, remove=("worker_ack_wait_started_at",))
            return
        if "worker_ack_wait_started_at" not in stored:
            return
        current = self.jobs.command_payload(job_id)
        if not isinstance(current, dict):
            current = dict(stored)
        current.pop("worker_ack_wait_started_at", None)
        self.jobs.update_command_payload(job_id, current)

    @staticmethod
    def _is_worker_connectivity_error(exc: Exception) -> bool:
        kind = str(getattr(exc, "kind", "") or "").strip().lower()
        if kind in {"network", "timeout", "no_ack"}:
            return True
        status = getattr(exc, "status", None)
        if status is not None:
            try:
                # A worker HTTP 5xx means the command was not accepted. Keep
                # it queued under Lite's acknowledgement deadline; 4xx is an
                # explicit rejection and must fail immediately.
                response_status = int(status)
                return 500 <= response_status < 600 or response_status in {408, 425, 429}
            except (TypeError, ValueError):
                return False
        if kind:
            return False
        return isinstance(exc, (TimeoutError, ConnectionError, OSError))

    @staticmethod
    def _worker_rejection_status(exc: Exception) -> int | None:
        try:
            status = int(getattr(exc, "status", 0))
        except (TypeError, ValueError):
            return None
        return status if 400 <= status < 500 and status not in {408, 425, 429} else None

    def _handle_worker_dispatch_exception(
        self, job: Job, stored: dict[str, Any], exc: Exception
    ) -> dict[str, str]:
        if self._is_worker_connectivity_error(exc):
            if self._wait_for_worker_ack(job, stored):
                return {"status": "terminal", "reason": "worker_ack_timeout"}
            return {"status": "wait", "reason": "not_ready"}
        self._clear_worker_ack_wait(job.id, stored)
        rejection_status = self._worker_rejection_status(exc)
        if rejection_status is not None:
            self._fail_queued_job(
                job,
                "WORKER_REJECTED_COMMAND",
                f"Worker menolak command (HTTP {rejection_status}); periksa endpoint dan kredensial worker.",
            )
            return {"status": "terminal", "reason": "worker_rejected"}
        return {"status": "wait", "reason": "not_ready"}

    def _assert_profile_admission(
        self,
        kind: str,
        profile: str,
        worker: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if kind not in {
            "export", "leave", "download", "download_clear_failed",
            "storage_upload", "storage_download", "storage_reconcile", "storage_sync", "tts",
            "tdl_access_verify", "backup_verify", "artifact_inventory",
            "artifact_delete", "backup_node", "chat_send",
        }:
            return
        registry = getattr(self.profile_manager, "profile_registry", None)
        check_deletion = getattr(registry, "local_deletion_active", None)
        values = payload if isinstance(payload, dict) else {}
        rclone_storage = (
            kind in {"storage_upload", "storage_download"}
            and str(values.get("provider") or "telegram").strip().lower() == "rclone"
        )
        candidates = [profile]
        if rclone_storage:
            candidates = []
        elif values.get("_tdl_sender_profiles_use_worker_inventory") is True:
            candidates = []
        elif kind in {"storage_upload", "storage_download", "storage_reconcile", "storage_sync", "tts", "chat_send"}:
            candidates = values.get("_tdl_sender_profiles") or candidates
        elif kind == "tdl_access_verify":
            candidates = (
                values.get("candidate_profiles") or []
                if "candidate_profiles" in values
                else candidates
            )
        elif kind == "backup_node":
            list_profiles = getattr(self.profile_manager, "list_profiles", None)
            candidates = list_profiles() if callable(list_profiles) else candidates
        for candidate in candidates:
            normalized = str(candidate or "").strip().lower()
            if normalized and callable(check_deletion) and check_deletion(normalized, worker):
                raise DomainError(
                    "PROFILE_DELETION_IN_PROGRESS",
                    f"Profil {normalized} sedang dihapus dari worker {worker}; job TDL baru ditahan.",
                    status_code=409,
                    details={"profile": normalized, "worker": worker},
                )

    def submit_job(
        self,
        actor: Actor,
        kind: str,
        payload: dict[str, Any],
        *,
        profile: str | None = None,
        worker: str | None = None,
        job_id: str | None = None,
        private_job_values: dict[str, str] | None = None,
    ) -> Job:
        if self.gateway_mode == "lite" and kind == "backup_node":
            raise DomainError(
                "LITE_BACKUP_ARCHIVE_JOB_DISABLED",
                "Pembuatan arsip backup worker tidak tersedia pada mode Lite.",
                status_code=409,
            )
        self._require_lite_explicit_worker(worker)
        owner_profile = (
            actor.profile
            if kind in {"leave", "tts", "storage_upload"}
            else self.require_profile(actor, profile)
        )
        execution_profile = owner_profile
        internal_payload = deepcopy(payload)
        if kind == "storage_upload":
            internal_payload[_STORAGE_DURABLE_DISPATCH_KEY] = {
                "command_id": str(uuid.uuid4()),
                "dispatch_token": secrets.token_urlsafe(32),
                "attempt": 1,
                "dispatch_started": False,
            }
        private_values = dict(private_job_values or {})
        if kind == "tts":
            target_chat = self._tdl_access_target("tts")
            if not target_chat:
                raise DomainError("TTS_CHAT_UNAVAILABLE", "Chat tujuan TTS belum dikonfigurasi.", status_code=503)
            selected_worker = self._select_tts_worker(worker, destination=target_chat)
            if self.gateway_mode == "lite":
                # Lite submit must not wait on a worker RPC to discover its
                # sender inventory. Let the worker try its current local
                # profiles when it executes the durable command.
                sender_profiles = []
                execution_profile = owner_profile
                internal_payload["_tdl_sender_profiles_use_worker_inventory"] = True
            else:
                # This worker-inventory mode is an execution policy reserved
                # for Lite. Never let caller-supplied internal payload values
                # override Full mode's capability-derived sender snapshot.
                internal_payload.pop("_tdl_sender_profiles_use_worker_inventory", None)
                sender_profiles = self._worker_profile_candidates(selected_worker, "tts")
                execution_profile = self._select_tts_sender_profile(
                    selected_worker, sender_profiles or [owner_profile]
                )
            internal_payload.update(
                _tdl_sender_profile=execution_profile,
                _tdl_sender_profiles=[execution_profile, *[item for item in sender_profiles if item != execution_profile]],
            )
            private_values["telegram_tts_chat_id"] = target_chat
        elif kind == "storage_upload":
            _, selected_worker = self.resolve_target(
                actor, worker=worker
            )
            provider = str(internal_payload.get("provider") or "telegram").strip().lower()
            if provider not in {"telegram", "rclone"}:
                raise DomainError("STORAGE_PROVIDER_INVALID", "Tujuan upload Storage tidak valid.", status_code=422)
            if provider == "rclone":
                internal_payload["provider"] = provider
                internal_payload["rclone_destination"] = str(
                    internal_payload.get("rclone_destination")
                    or self._utility_settings_snapshot().get("rclone_destination", "googledrive:backup")
                )
                try:
                    validate_rclone_destination(internal_payload["rclone_destination"])
                except ValueError as exc:
                    raise DomainError("RCLONE_DESTINATION_INVALID", "Root rclone yang dikonfigurasi tidak valid.", status_code=409) from exc
                internal_payload["_tdl_sender_profiles"] = []
                target_chat = ""
            else:
                target_chat = ""
            retry_source_id = str(internal_payload.get("_storage_retry_of") or "").strip()
            retry_source = self.jobs.get(retry_source_id) if retry_source_id else None
            if provider == "telegram" and retry_source_id:
                if (
                    retry_source is None
                    or retry_source.kind != "storage_upload"
                    or retry_source.actor_user_id != actor.telegram_user_id
                    or retry_source.profile != owner_profile
                    or retry_source.worker != selected_worker
                ):
                    raise DomainError(
                        "STORAGE_RETRY_SOURCE_INVALID",
                        "Snapshot tujuan upload asli tidak dapat digunakan untuk Retry.",
                        status_code=409,
                    )
                target_chat = str(
                    self.private_job_value(retry_source.id, "tdl_storage_chat_ref") or ""
                ).strip()
                if not target_chat:
                    raise DomainError(
                        "STORAGE_RETRY_SNAPSHOT_UNAVAILABLE",
                        "Snapshot tujuan upload asli tidak tersedia.",
                        status_code=409,
                    )
                private_values["tdl_storage_chat_ref"] = target_chat
            elif provider == "telegram":
                target_chat = self._tdl_access_target("storage")
                if not target_chat:
                    raise DomainError("TDL_ACCESS_TARGET_UNAVAILABLE", "Tujuan TDL Storage belum dikonfigurasi.", status_code=503)
                execution_profile, sender_profiles, _session_fingerprints = (
                    self._storage_sender_snapshot(
                        selected_worker, destination=target_chat,
                        fallback_profile=owner_profile,
                    )
                )
                internal_payload.update(
                    provider="telegram",
                    _tdl_sender_profile=execution_profile,
                    _tdl_sender_profiles=[execution_profile, *[item for item in sender_profiles if item != execution_profile]],
                )
                private_values["tdl_storage_chat_ref"] = target_chat
            if provider == "telegram" and retry_source_id and retry_source is not None:
                execution_profile, sender_profiles, _session_fingerprints = (
                    self._storage_sender_snapshot(
                        selected_worker, destination=target_chat,
                        fallback_profile=owner_profile,
                    )
                )
                internal_payload.update(
                    provider="telegram",
                    _tdl_sender_profile=execution_profile,
                    _tdl_sender_profiles=[execution_profile, *[item for item in sender_profiles if item != execution_profile]],
                )
            if provider == "telegram":
                if self.gateway_mode == "lite":
                    # New and retried Storage jobs rotate through the worker's
                    # current local profiles. Carry that fact so cancellation
                    # interrupts whichever Upload lane is active, including a
                    # profile that was not visible to this gateway.
                    internal_payload["_tdl_sender_profiles_use_worker_inventory"] = True
                else:
                    # This marker is internal and must never be accepted from
                    # an operator-controlled payload in Full mode.
                    internal_payload.pop("_tdl_sender_profiles_use_worker_inventory", None)
                list_targets = getattr(self.storage_catalog, "upload_target_paths", None)
                if callable(list_targets):
                    internal_payload["_existing_storage_target_paths"] = list_targets(
                        internal_payload.get("destination_folder_id"),
                        preserve_structure=bool(
                            internal_payload.get("preserve_structure", True)
                        ),
                    )
        elif kind == "storage_download":
            owner_profile, selected_worker = self.resolve_target(
                actor,
                profile=owner_profile,
                worker=worker,
            )
            internal_payload = self._prepare_durable_payload(
                actor, kind, internal_payload, owner_profile, selected_worker
            )
            provider = str(internal_payload.get("provider") or "").strip().lower()
            if provider == "telegram":
                target_chat = self._tdl_access_target("storage")
                if not target_chat:
                    raise DomainError(
                        "TDL_ACCESS_TARGET_UNAVAILABLE",
                        "Tujuan TDL Storage belum dikonfigurasi.",
                        status_code=503,
                    )
                private_values["tdl_storage_chat_ref"] = target_chat
        elif kind == "storage_sync":
            selected_profile = owner_profile
            _, selected_worker = self.resolve_target(
                actor,
                profile=selected_profile,
                worker=worker,
            )
            try:
                channel_id = int(internal_payload.get("channel_id"))
            except (TypeError, ValueError):
                raise DomainError(
                    "STORAGE_SYNC_CHANNEL_INVALID",
                    "Channel Storage belum dikonfigurasi.",
                    status_code=503,
                ) from None
            if channel_id == 0 or set(internal_payload) - {"channel_id"}:
                raise DomainError(
                    "STORAGE_SYNC_REQUEST_INVALID",
                    "Target sinkronisasi Storage tidak valid.",
                    status_code=422,
                )
            catalog_ids = getattr(self.storage_catalog, "channel_message_ids", None)
            if not callable(catalog_ids):
                raise DomainError(
                    "STORAGE_SYNC_CATALOG_UNAVAILABLE",
                    "Katalog Storage tidak tersedia untuk memverifikasi pesan yang hilang.",
                    status_code=503,
                )
            candidate_message_ids = catalog_ids(channel_id)
            if not isinstance(candidate_message_ids, list):
                raise DomainError(
                    "STORAGE_SYNC_CANDIDATES_INVALID",
                    "Daftar pesan katalog tidak valid untuk verifikasi sinkronisasi.",
                    status_code=503,
                )
            destination = self._tdl_access_target("storage")
            if not destination:
                raise DomainError(
                    "TDL_ACCESS_TARGET_UNAVAILABLE",
                    "Tujuan TDL Storage belum dikonfigurasi.",
                    status_code=503,
                )
            execution_profile = selected_profile
            internal_payload = {
                "channel_id": channel_id,
                "_storage_sync_candidate_message_ids": candidate_message_ids,
                "_tdl_sender_profile": selected_profile,
                "_tdl_sender_profiles": [selected_profile],
            }
            private_values["tdl_storage_chat_ref"] = destination
        elif kind == "storage_reconcile":
            _, selected_worker = self.resolve_target(
                actor, worker=worker
            )
            reconcile_provider = str(
                internal_payload.get("_storage_reconcile_provider") or "telegram"
            ).strip().lower()
            if reconcile_provider not in {"telegram", "rclone"}:
                raise DomainError(
                    "STORAGE_RECONCILIATION_PROVIDER_INVALID",
                    "Provider rekonsiliasi Storage tidak didukung.",
                    status_code=422,
                )
            if reconcile_provider == "rclone":
                destination = str(
                    internal_payload.get("rclone_destination") or ""
                ).strip()
                try:
                    validate_rclone_destination(destination)
                except ValueError as exc:
                    raise DomainError(
                        "STORAGE_RECONCILIATION_SNAPSHOT_UNAVAILABLE",
                        "Snapshot tujuan rclone untuk rekonsiliasi tidak tersedia.",
                        status_code=409,
                    ) from exc
                internal_payload["_storage_reconcile_provider"] = "rclone"
                internal_payload["rclone_destination"] = destination
                internal_payload["_tdl_sender_profiles"] = []
                private_values.pop("tdl_storage_chat_ref", None)
            else:
                sender_profiles = [
                    str(item).strip().lower()
                    for item in internal_payload.get("_tdl_sender_profiles", [])
                    if str(item).strip()
                ]
                internal_payload["_storage_reconcile_provider"] = "telegram"
                if self.gateway_mode == "lite":
                    # The worker owns its live profile inventory. Do not
                    # synchronously probe capabilities or pin this job to a
                    # stale profile recorded by the original upload.
                    internal_payload["_tdl_sender_profiles_use_worker_inventory"] = True
                    internal_payload["_tdl_sender_profiles"] = []
                    internal_payload.pop("_tdl_sender_profile", None)
                else:
                    internal_payload.pop("_tdl_sender_profiles_use_worker_inventory", None)
                    internal_payload["_tdl_sender_profiles"] = list(dict.fromkeys(sender_profiles))
                    internal_payload["_tdl_sender_profile"] = (
                        internal_payload["_tdl_sender_profiles"][0]
                        if internal_payload["_tdl_sender_profiles"]
                        else owner_profile
                    )
                if not private_values.get("tdl_storage_chat_ref"):
                    raise DomainError(
                        "STORAGE_RECONCILIATION_SNAPSHOT_UNAVAILABLE",
                        "Snapshot tujuan Storage untuk rekonsiliasi tidak tersedia.",
                        status_code=409,
                    )
        else:
            owner_profile, selected_worker = self.resolve_target(
                actor,
                profile=owner_profile if kind in {
                    "export", "leave", "download", "download_clear_failed",
                    "storage_download", "artifact_inventory", "artifact_delete", "backup_verify",
                } else None,
                worker=worker,
            )
            execution_profile = owner_profile
        if kind == "tts":
            if self.gateway_mode == "lite":
                self._require_lite_remote_worker(
                    selected_worker, requested_worker=worker
                )
            else:
                self._require_worker_responsive(selected_worker)
        if kind == "utility":
            submitted_utility_settings = internal_payload.get("settings")
            internal_payload = self._prepare_durable_payload(
                actor,
                "utility",
                {
                    key: internal_payload.get(key)
                    for key in (
                        "utility", "folders", "password", "flatten_action",
                        "flatten_fingerprints", "video_options",
                    )
                    if key in internal_payload
                },
                owner_profile,
                selected_worker,
            )
            if isinstance(submitted_utility_settings, dict):
                internal_payload["settings"] = deepcopy(submitted_utility_settings)
        self._require_runtime_readiness(
            kind, execution_profile, selected_worker, internal_payload
        )
        if kind == "export" and bool(internal_payload.get("quick_mode")):
            target_chat, sender_profiles = self._quick_storage_access_snapshot(
                selected_worker,
                execution_profile,
                internal_payload.get("quick_settings"),
            )
            internal_payload["_quick_storage_sender_profiles"] = sender_profiles
            private_values["tdl_storage_chat_ref"] = target_chat
        self._assert_profile_admission(
            kind, execution_profile, selected_worker, internal_payload
        )
        if kind == "export" and self._shared_export_cursor_enabled():
            self._require_shared_export_cursor_worker(selected_worker)
        available_profiles = ()
        list_profiles = getattr(self.profile_manager, "list_profiles", None)
        if callable(list_profiles):
            available_profiles = list_profiles()
        job_id = str(job_id or uuid.uuid4())
        redacted_payload = self._redacted_payload(kind, internal_payload)
        settings_version = self._worker_settings_version(selected_worker)
        encrypted_private_values = self._encrypt_private_job_values(
            job_id, private_values
        )
        existing = self.jobs.get(job_id)
        retry_event = None
        retry_attempt = 1
        if existing is not None and existing.status.terminal:
            # Keep the retry event and command payload with the queue reset so
            # the scheduler cannot observe a half-prepared queued job.
            retry_attempt = 1 + sum(
                1
                for event in self.jobs.events(job_id)
                if event.event_type == "retry_started"
            )
            retry_meta = internal_payload.get("quick_retry") or internal_payload.get("export_retry") or {}
            retry_meta = retry_meta if isinstance(retry_meta, dict) else {}
            retry_phase = str(
                retry_meta.get("resume_phase")
                or retry_meta.get("retry_phase")
                or "exporting"
            )
            sequence = existing.progress_sequence + 1
            retry_event = JobEvent(
                job_id=job_id,
                sequence=sequence,
                status=JobStatus.QUEUED,
                event_type="retry_started",
                progress={
                    "phase": "queued",
                    "retry_attempt": retry_attempt,
                    "retry_phase": retry_phase,
                },
            )
            job = existing
        elif existing is not None:
            raise DomainError(
                "JOB_NOT_TERMINAL",
                "Job dengan ID tersebut masih aktif dan belum dapat digunakan ulang.",
                status_code=409,
            )
        else:
            job = Job(
                id=job_id,
                kind=kind,
                profile=owner_profile,
                actor_user_id=actor.telegram_user_id,
                worker=selected_worker,
                status=JobStatus.QUEUED,
                payload=redacted_payload,
                settings_version=settings_version,
            )
        retry_meta = internal_payload.get("quick_retry") or {}
        retry_meta = retry_meta if isinstance(retry_meta, dict) else {}
        stable_stage_id = retry_meta.get("stage_job_id")
        execution_payload = self._plan_payload_with_verified_peer(
            execution_profile, kind, internal_payload
        )
        execution = build_execution_plan(
            kind,
            execution_profile,
            selected_worker,
            execution_payload,
            available_profiles,
            stage_job_id=(
                str(stable_stage_id or job_id)
                if kind == "export" and bool(internal_payload.get("quick_mode"))
                else None
            ),
        )
        command = {
            "job_id": job.id,
            "attempt": 1 + sum(
                1
                for event in self.jobs.events(job.id)
                if event.event_type == "retry_started"
            ) + (1 if retry_event is not None else 0),
            "kind": kind,
            "profile": execution_profile,
            "actor_user_id": actor.telegram_user_id,
            "worker": selected_worker,
            "execution": execution.as_dict(),
        }
        if retry_event is not None:
            reset = self.jobs.reset_for_retry
            reset(
                job_id,
                redacted_payload,
                settings_version=settings_version,
                private_values=encrypted_private_values or None,
                execution_plan=execution.as_dict(),
                command_payload=internal_payload,
                retry_event=retry_event,
            )
            job = self.jobs.get(job_id) or job
        else:
            creator = getattr(self.jobs, "create_with_private_values", None)
            if not callable(creator):
                raise DomainError(
                    "JOB_PRIVATE_STORAGE_UNAVAILABLE",
                    "Penyimpanan privat job belum tersedia.",
                    status_code=503,
                )
            creator(
                job,
                encrypted_private_values,
                execution_plan=execution.as_dict(),
                command_payload=internal_payload,
            )
        self.wake_scheduler()
        command["payload"] = self._worker_payload(job.id, kind, internal_payload)
        admission = self.jobs.try_acquire_execution(job.id)
        current_job = self.jobs.get(job.id)
        if current_job is not None and current_job.status == JobStatus.QUEUED:
            self.jobs.set_queue_info(
                job.id,
                int(admission.get("position", 1)),
                admission.get("blocked_reason"),
            )
        if not admission.get("admitted"):
            return current_job or job
        try:
            self._dispatch_admitted_job(self.jobs.get(job.id) or job, command)
            return self.jobs.get(job.id) or job
        except Exception as exc:
            self.jobs.release_execution(job.id)
            failure = self._worker_dispatch_error(selected_worker, exc)
            latest_job = self.jobs.get(job.id)
            sequence = (
                latest_job.progress_sequence if latest_job is not None
                else job.progress_sequence
            ) + 1
            failed = JobEvent(
                job_id=job.id,
                sequence=sequence,
                status=JobStatus.FAILED,
                event_type="dispatch_failed",
                error={"code": failure.code, "message": failure.message},
            )
            self.append_worker_event(failed)
            raise failure from exc

    @staticmethod
    def _worker_dispatch_error(worker: str, exc: Exception) -> DomainError:
        if isinstance(exc, DomainError) and exc.code == "WORKER_INCOMPATIBLE":
            return exc
        return DomainError(
            "WORKER_UNAVAILABLE",
            f"Worker {worker} tidak dapat menerima job: {exc}",
            status_code=503,
        )

    def prepare_durable_job(self, actor: Actor, target: dict[str, Any], input_data: dict[str, Any]):
        """Validate and persist a job plan without performing worker I/O."""
        from tme3bot.application.operations import PreparedOperation

        if set(input_data) - {"job_kind", "payload"}:
            raise DomainError("OPERATION_INPUT_INVALID", "Input job operation tidak dikenal.", status_code=422)
        kind = str(input_data.get("job_kind") or "").strip().lower()
        payload = input_data.get("payload")
        if kind not in _DURABLE_JOB_KINDS:
            raise DomainError("JOB_KIND_INVALID", "Jenis job belum didukung oleh dispatch background.", status_code=422)
        if not isinstance(payload, dict):
            raise DomainError("JOB_PAYLOAD_INVALID", "Payload job harus berupa object.", status_code=422)
        if set(target) - {"profile", "worker"}:
            raise DomainError("OPERATION_TARGET_INVALID", "Target hanya boleh berisi profile dan worker.", status_code=422)
        self._require_lite_explicit_worker(target.get("worker"))
        owner_profile = (
            actor.profile
            if kind in {"leave", "tts", "storage_upload", "tdl_access_verify", "chat_send"}
            else self.require_profile(actor, str(target.get("profile") or actor.profile))
        )
        execution_profile = owner_profile
        if kind == "safelink_resolve":
            selected_worker = self._select_safelink_worker(
                str(target.get("worker") or "").strip() or None
            )
        elif kind == "tts":
            target_chat = self._tdl_access_target("tts")
            selected_worker = self._select_tts_worker(
                str(target.get("worker") or "").strip() or None,
                destination=target_chat,
            )
            if not target_chat:
                raise DomainError("TTS_CHAT_UNAVAILABLE", "Chat tujuan TTS belum dikonfigurasi.", status_code=503)
            if self.gateway_mode == "lite":
                sender_profiles = []
                execution_profile = owner_profile
            else:
                sender_profiles = self._worker_profile_candidates(selected_worker, "tts")
                execution_profile = self._select_tts_sender_profile(
                    selected_worker, sender_profiles or [owner_profile]
                )
        elif kind == "tdl_access_verify":
            if not str(target.get("worker") or "").strip():
                raise DomainError("WORKER_REQUIRED", "Worker target wajib dipilih untuk verifikasi akses TDL.", status_code=422)
            owner_profile, selected_worker = self.resolve_target(
                actor, worker=str(target.get("worker"))
            )
        else:
            if not str(target.get("worker") or "").strip():
                raise DomainError("WORKER_REQUIRED", "Worker target wajib dipilih untuk job background.", status_code=422)
            owner_profile, selected_worker = self.resolve_target(
                actor,
                profile=owner_profile if kind in {
                    "export", "leave", "download", "download_clear_failed",
                    "artifact_inventory", "artifact_delete", "backup_verify",
                } else None,
                worker=str(target.get("worker")),
            )
        if kind in {"tts", "safelink_resolve"}:
            if self.gateway_mode == "lite":
                self._require_lite_remote_worker(
                    selected_worker,
                    requested_worker=str(target.get("worker") or "").strip() or None,
                )
            else:
                self._require_worker_responsive(selected_worker)
        payload = self._prepare_durable_payload(
            actor, kind, payload, owner_profile, selected_worker
        )
        if kind == "tts" and self.gateway_mode == "lite":
            payload["_tdl_sender_profiles_use_worker_inventory"] = True
        if kind == "storage_upload" and str(payload.get("provider") or "telegram").strip().lower() == "telegram":
            if self.gateway_mode == "lite":
                # The worker must use its current profile inventory for durable
                # Operations submissions just as it does for direct Storage
                # submits and retries.
                payload["_tdl_sender_profiles_use_worker_inventory"] = True
            else:
                payload.pop("_tdl_sender_profiles_use_worker_inventory", None)
        if kind == "chat_send":
            execution_profile = payload["_tdl_sender_profiles"][0]
        quick_storage_snapshot = None
        if kind == "export" and bool(payload.get("quick_mode")):
            quick_storage_snapshot = self._quick_storage_access_snapshot(
                selected_worker,
                execution_profile,
                payload.get("quick_settings"),
            )
            payload["_quick_storage_sender_profiles"] = list(quick_storage_snapshot[1])

        private_job_values: dict[str, bytes] = {}
        if kind == "tts":
            payload.update(
                _tdl_sender_profile=execution_profile,
                _tdl_sender_profiles=[
                    execution_profile,
                    *[item for item in sender_profiles if item != execution_profile],
                ],
            )
        elif kind == "storage_upload":
            purpose = "storage"
            if str(payload.get("provider") or "telegram").strip().lower() == "telegram":
                destination = self._tdl_access_target(purpose)
                if not destination:
                    raise DomainError(
                        "TDL_ACCESS_TARGET_UNAVAILABLE",
                        f"Tujuan TDL {purpose} belum dikonfigurasi.",
                        status_code=503,
                    )
                execution_profile, sender_profiles, _session_fingerprints = (
                    self._storage_sender_snapshot(
                        selected_worker,
                        destination=destination,
                        fallback_profile=owner_profile,
                    )
                )
                payload.update(
                    _tdl_sender_profile=execution_profile,
                    _tdl_sender_profiles=[execution_profile, *[item for item in sender_profiles if item != execution_profile]],
                )
        elif kind == "tdl_access_verify":
            purpose = str(payload.get("purpose") or "")
            destination = self._tdl_access_target(purpose)
            profiles_for_lock = (
                []
                if self.gateway_mode == "lite"
                else self._worker_profile_candidates(
                    selected_worker, "storage" if purpose == "storage" else "tts"
                )
            )
            payload["candidate_profiles"] = sorted(
                {str(item).strip().lower() for item in profiles_for_lock if str(item).strip()}
            )
            if not destination:
                raise DomainError(
                    "TDL_ACCESS_TARGET_UNAVAILABLE",
                    f"Tujuan TDL {purpose} belum dikonfigurasi.",
                    status_code=503,
                )

        self._require_runtime_readiness(kind, execution_profile, selected_worker, payload)
        self._assert_profile_admission(
            kind, execution_profile, selected_worker, payload
        )

        job_id = str(uuid.uuid4())
        if kind == "export" and bool(payload.get("quick_mode")):
            retry = payload.get("quick_retry")
            retry = dict(retry) if isinstance(retry, dict) else {}
            retry.setdefault("stage_job_id", job_id)
            payload = {**payload, "quick_retry": retry}
        profiles = getattr(self.profile_manager, "list_profiles", None)
        execution_payload = self._plan_payload_with_verified_peer(
            execution_profile, kind, payload
        )
        execution = build_execution_plan(
            kind,
            execution_profile,
            selected_worker,
            execution_payload,
            profiles() if callable(profiles) else (),
            stage_job_id=job_id if kind == "export" and bool(payload.get("quick_mode")) else None,
        )
        settings_version = self._worker_settings_version(selected_worker)
        command_payload = {
            "dispatch_mode": "durable",
            "command_id": str(uuid.uuid4()),
            "dispatch_token": secrets.token_urlsafe(32),
            "attempt": 1,
            "dispatch_started": False,
            "profile_revision": 0,
            "settings_version": settings_version,
            "job_id": job_id,
            "kind": kind,
            "profile": execution_profile,
            "owner_profile": owner_profile,
            "actor_user_id": int(actor.telegram_user_id),
            "worker": selected_worker,
            "execution": execution.as_dict(),
            "payload": payload,
        }
        job = Job(
            id=job_id,
            kind=kind,
            profile=owner_profile,
            actor_user_id=int(actor.telegram_user_id),
            worker=selected_worker,
            status=JobStatus.QUEUED,
            payload=self._redacted_payload(kind, payload),
            settings_version=settings_version,
        )
        if kind == "tts":
            target_chat = self._tdl_access_target("tts")
            if not target_chat:
                raise DomainError("TTS_CHAT_UNAVAILABLE", "Chat tujuan TTS belum dikonfigurasi.", status_code=503)
            private_job_values = self._encrypt_private_job_values(
                job_id,
                {"telegram_tts_chat_id": target_chat},
            )
        elif kind == "tdl_access_verify":
            purpose = str(payload.get("purpose") or "")
            destination = self._tdl_access_target(purpose)
            private_job_values = self._encrypt_private_job_values(
                job_id, {"tdl_access_target": destination}
            )
        elif kind == "backup_verify":
            password = str(self._utility_settings_snapshot().get("compress_password") or "").strip()
            if not password:
                raise DomainError(
                    "BACKUP_PASSWORD_UNAVAILABLE",
                    "Password arsip backup belum tersedia di Pengaturan Utility.",
                    status_code=503,
                )
            private_job_values = self._encrypt_private_job_values(
                job_id, {"backup_archive_password": password}
            )
        elif kind in {"tts", "storage_upload"}:
            purpose = "tts" if kind == "tts" else "storage"
            destination = self._tdl_access_target(purpose)
            private_key = "telegram_tts_chat_id" if purpose == "tts" else "tdl_storage_chat_ref"
            private_values = {private_key: destination}
            private_job_values = self._encrypt_private_job_values(job_id, private_values)
        elif kind == "storage_download" and str(payload.get("provider") or "") == "telegram":
            destination = self._tdl_access_target("storage")
            if not destination:
                raise DomainError(
                    "TDL_ACCESS_TARGET_UNAVAILABLE",
                    "Tujuan TDL Storage belum dikonfigurasi.",
                    status_code=503,
                )
            private_job_values = self._encrypt_private_job_values(
                job_id, {"tdl_storage_chat_ref": destination}
            )
        elif quick_storage_snapshot is not None:
            destination, _sender_profiles = quick_storage_snapshot
            private_job_values = self._encrypt_private_job_values(
                job_id, {"tdl_storage_chat_ref": destination}
            )
        return PreparedOperation(
            profile=owner_profile,
            target={"profile": owner_profile, "worker": selected_worker, "job_kind": kind},
            private_payload={"job_id": job_id},
            job=job,
            private_job_values=private_job_values,
            execution_plan=execution.as_dict(),
            command_payload=command_payload,
        )

    def _require_runtime_readiness(
        self, kind: str, profile: str, worker: str, payload: dict[str, Any]
    ) -> None:
        # Readiness snapshots describe recent outcomes for the UI. They never
        # admit feature jobs; the selected worker command is the authority.
        del kind, profile, worker, payload

    def _invalidate_runtime_readiness_from_event(self, event: JobEvent) -> None:
        gate = self.runtime_readiness_gate
        if gate is None:
            return
        job = self.jobs.get(event.job_id)
        if job is None:
            return
        if job.kind not in {
            "export", "download", "tts", "storage_upload", "storage_download",
            "storage_sync", "storage_rclone_manage", "tdl_access_verify", "safelink_resolve",
        }:
            return

        result = event.result if isinstance(event.result, dict) else {}
        if isinstance(result.get("value"), dict):
            result = result["value"]

        def record(runtime: str, profile: str | None, succeeded: bool, reason: str = "") -> None:
            gate.record_command_result(
                worker=job.worker,
                profile=profile,
                runtime=runtime,
                succeeded=succeeded,
                reason_code=reason,
            )

        # Command milestones are emitted only after validation and immediately
        # around an actual TDL/rclone subprocess. This keeps input/path errors
        # from changing readiness while allowing generic command failures to
        # update the exact runtime that was exercised.
        if event.event_type == "command.completed":
            command_result = event.result if isinstance(event.result, dict) else {}
            runtime = str(command_result.get("runtime") or "").strip().lower()
            if runtime not in {"export", "download", "upload", "tts", "rclone_storage"}:
                return
            profile = str(command_result.get("profile") or job.profile).strip().lower()
            try:
                returncode = int(command_result.get("returncode"))
            except (TypeError, ValueError):
                return
            succeeded = returncode == 0
            output = "\n".join(
                str(line) for line in command_result.get("output_tail", [])
                if isinstance(line, str)
            )
            code_match = re.search(r"\b([A-Z][A-Z0-9_]{1,79})\b", output)
            reason = "" if succeeded else (code_match.group(1) if code_match else "COMMAND_FAILED")
            if runtime == "upload":
                record("upload", profile, succeeded, reason)
                record("storage", profile, succeeded, reason)
                if job.kind == "export" and bool(job.payload.get("quick_mode")) and not succeeded:
                    record("quick_mode", job.profile, False, reason)
            elif runtime == "rclone_storage":
                record(runtime, None, succeeded, reason)
                if job.kind == "export" and bool(job.payload.get("quick_mode")):
                    record("quick_mode_runtime", None, succeeded, reason)
                    if not succeeded:
                        record("quick_mode", job.profile, False, reason)
            else:
                record(runtime, profile, succeeded, reason)
                if runtime == "export" and job.kind == "export" and bool(job.payload.get("quick_mode")) and not succeeded:
                    record("quick_mode", job.profile, False, reason)
            return

        if event.event_type == "tdl_access.profile_denied" and isinstance(result, dict):
            profile = str(result.get("profile") or "").strip().lower()
            error_code = str(result.get("error_code") or "TDL_ACCESS_DENIED").strip().upper()
            if not profile:
                return
            if job.kind == "tts":
                record("tts", profile, False, error_code)
            elif job.kind == "tdl_access_verify":
                purpose = str(job.payload.get("purpose") or "")
                if purpose == "storage":
                    record("upload", profile, False, error_code)
                    record("storage", profile, False, error_code)
                elif purpose == "tts":
                    record("tts", profile, False, error_code)
            else:
                record("upload", profile, False, error_code)
                record("storage", profile, False, error_code)
            return

        if event.status == JobStatus.SUCCEEDED:
            if job.kind == "tts":
                sender_profile = str(
                    result.get("sender_profile")
                    or job.payload.get("sender_profile")
                    or job.profile
                ).strip().lower()
                record("tts_helper", None, True)
                record("tts", sender_profile, True)
            elif job.kind == "tdl_access_verify":
                purpose = str(job.payload.get("purpose") or "")
                for item in result.get("profiles", []) if isinstance(result.get("profiles"), list) else []:
                    if not isinstance(item, dict) or item.get("command_attempted") is not True:
                        continue
                    profile = str(item.get("profile") or "").strip().lower()
                    if not profile:
                        continue
                    ready = item.get("ready") is True
                    reason = str(item.get("error_code") or "COMMAND_FAILED")
                    if purpose == "storage":
                        record("upload", profile, ready, reason)
                        record("storage", profile, ready, reason)
                    elif purpose == "tts":
                        record("tts", profile, ready, reason)
            elif job.kind == "export" and bool(job.payload.get("quick_mode")):
                record("quick_mode_runtime", None, True)
                record("quick_mode", job.profile, True)
            return

        if event.status != JobStatus.FAILED or event.event_type != "failed":
            return
        error = event.error if isinstance(event.error, dict) else {}
        error_code = str(error.get("code") or "COMMAND_FAILED").strip().upper()
        message = str(error.get("message") or "")
        if error_code == "WORKER_JOB_FAILED":
            match = re.match(r"^([A-Z][A-Z0-9_]{0,79}):", message.strip())
            if match:
                error_code = match.group(1)
        # TDL and rclone outcomes are recorded from command.completed above,
        # which proves a command actually ran. A later terminal failure must
        # not overwrite that evidence or turn validation/path errors into a
        # readiness failure. TTS helper and Resolver failures are explicit
        # runtime checks reported by their workers, not profile/path checks.
        if job.kind == "tts" and error_code in {"TTS_HELPER_UNAVAILABLE", "TTS_RUNTIME_UNAVAILABLE"}:
            record("tts_helper", None, False, error_code)
        elif job.kind == "safelink_resolve" and error_code == "RESOLVER_RUNTIME_UNAVAILABLE":
            self.runtime_readiness_gate.record_resolver_failure(
                worker=job.worker, error_code=error_code
            )

    def _prepare_durable_payload(
        self,
        actor: Actor,
        kind: str,
        payload: dict[str, Any],
        profile: str,
        worker: str,
    ) -> dict[str, Any]:
        allowed: dict[str, set[str]] = {
            "export": {
                "url", "chat_ref", "start_id", "label", "use_url_message_id",
                "save_source", "quick_mode",
            },
            "leave": {"chat_refs"},
            "download": {"artifact_ids", "priority"},
            "utility": {
                "utility", "folders", "password", "flatten_action",
                "flatten_fingerprints", "video_options",
            },
            "storage_upload": {
                "folder_path", "folder", "destination_folder_id",
                "preserve_structure", "keywords", "provider", "rclone_path",
                "transfer_mode", "move_confirmed",
            },
            "storage_download": {
                "provider", "item_ids", "folder_ids", "rclone_sources",
                "destination_path", "publish_public_links",
            },
            "backup_verify": {"run_id"},
            "tts": {"title", "text"},
            "tdl_access_verify": {"purpose"},
            "safelink_resolve": {"url"},
            "chat_send": {
                "chat_ref", "folders", "profiles", "transfer_mode",
                "move_confirmed", "retry_paths",
            },
        }
        if set(payload) - allowed[kind]:
            raise DomainError(
                "JOB_PAYLOAD_INVALID",
                "Payload job memuat field yang tidak diizinkan.",
                status_code=422,
            )

        if kind == "export":
            values = dict(payload)
            for flag in ("use_url_message_id", "save_source", "quick_mode"):
                if flag in values and values[flag] is not None and type(values[flag]) is not bool:
                    raise DomainError("JOB_PAYLOAD_INVALID", "Flag export harus berupa boolean.", status_code=422)
            url = str(values.get("url") or "").strip()
            chat_ref = str(values.get("chat_ref") or "").strip()
            if not url and not chat_ref:
                raise DomainError("EXPORT_REFERENCE_REQUIRED", "Isi URL atau chat_ref untuk export.", status_code=422)
            if len(url) > 2048:
                raise DomainError("JOB_PAYLOAD_INVALID", "URL export terlalu panjang.", status_code=422)
            if chat_ref:
                try:
                    values["chat_ref"] = normalize_tdl_chat_ref(chat_ref)
                except ValueError as exc:
                    raise DomainError("INVALID_CHAT_REF", str(exc), status_code=422) from exc
            start_id = values.get("start_id")
            if start_id is not None and (type(start_id) is not int or start_id < 1):
                raise DomainError("JOB_PAYLOAD_INVALID", "Start ID harus bilangan positif.", status_code=422)
            label = values.get("label")
            if label is not None and (not isinstance(label, str) or len(label) > 120):
                raise DomainError("JOB_PAYLOAD_INVALID", "Label export tidak valid.", status_code=422)
            if bool(values.get("quick_mode")):
                values["quick_settings"] = self._utility_settings_snapshot()
            return values

        if kind == "storage_download":
            provider = str(payload.get("provider") or "").strip().lower()
            if provider not in {"telegram", "rclone"}:
                raise DomainError("STORAGE_PROVIDER_INVALID", "Sumber Storage unduhan tidak valid.", status_code=422)
            destination_raw = str(payload.get("destination_path") or "").strip()
            destination = PurePosixPath(destination_raw)
            if (
                not destination.is_absolute()
                or len(destination.parts) < 2
                or destination.parts[1] != "workspace"
                or ".." in destination.parts
                or "\\" in destination_raw
                or any(ord(char) < 32 for char in destination_raw)
            ):
                raise DomainError("STORAGE_DOWNLOAD_DESTINATION_INVALID", "Folder tujuan harus berada di dalam /workspace.", status_code=422)
            publish = payload.get("publish_public_links", False)
            if type(publish) is not bool:
                raise DomainError("JOB_PAYLOAD_INVALID", "Opsi link publik harus berupa boolean.", status_code=422)

            values: dict[str, Any] = {
                "provider": provider,
                "destination_path": str(destination),
                "publish_public_links": publish,
                "batch_id": str(uuid.uuid4()),
                "public_base_url": "",
            }
            record = self.worker_registry.get(worker) if self.worker_registry is not None else None
            if isinstance(record, dict):
                values["public_base_url"] = str(record.get("public_url") or "").strip().rstrip("/")
            if publish and not values["public_base_url"]:
                raise DomainError(
                    "PUBLIC_DOWNLOAD_ORIGIN_UNAVAILABLE",
                    "Domain HTTPS publik belum diatur untuk worker yang dipilih.",
                    status_code=409,
                )
            if publish:
                normalize_public_url = getattr(
                    self.worker_registry, "_normalize_public_url", None
                )
                if callable(normalize_public_url):
                    try:
                        values["public_base_url"] = normalize_public_url(
                            values["public_base_url"]
                        )
                    except ValueError as exc:
                        raise DomainError(
                            "PUBLIC_DOWNLOAD_ORIGIN_INVALID",
                            "Domain HTTPS publik worker tidak valid.",
                            status_code=409,
                        ) from exc

            if provider == "telegram":
                if payload.get("rclone_sources"):
                    raise DomainError("STORAGE_SELECTION_INVALID", "Pilihan rclone hanya berlaku untuk provider rclone.", status_code=422)
                item_ids = payload.get("item_ids") or []
                folder_ids = payload.get("folder_ids") or []
                if (
                    not isinstance(item_ids, list)
                    or not isinstance(folder_ids, list)
                    or any(type(value) is not int or value < 1 for value in [*item_ids, *folder_ids])
                    or self.storage_catalog is None
                ):
                    raise DomainError("STORAGE_SELECTION_INVALID", "Pilihan katalog Telegram tidak valid.", status_code=422)
                selector = getattr(self.storage_catalog, "download_selection", None)
                if not callable(selector):
                    raise DomainError("STORAGE_UNAVAILABLE", "Katalog Storage belum mendukung unduhan.", status_code=503)
                try:
                    files = selector(item_ids, folder_ids)
                except (ValueError, KeyError) as exc:
                    raise DomainError("STORAGE_SELECTION_INVALID", str(exc), status_code=409) from exc
                values["files"] = files
                if not files:
                    raise DomainError("STORAGE_SELECTION_EMPTY", "Pilihan tidak memiliki file untuk diunduh.", status_code=409)
            else:
                if payload.get("item_ids") or payload.get("folder_ids"):
                    raise DomainError("STORAGE_SELECTION_INVALID", "Pilihan katalog hanya berlaku untuk provider Telegram.", status_code=422)
                raw_sources = payload.get("rclone_sources")
                if not isinstance(raw_sources, list) or not raw_sources or len(raw_sources) > 500:
                    raise DomainError("STORAGE_SELECTION_REQUIRED", "Pilih file atau folder rclone untuk diunduh.", status_code=422)
                sources: list[dict[str, Any]] = []
                seen: set[str] = set()
                for raw in raw_sources:
                    if not isinstance(raw, dict) or set(raw) != {"path", "is_dir"} or type(raw.get("is_dir")) is not bool:
                        raise DomainError("STORAGE_SELECTION_INVALID", "Pilihan rclone tidak valid.", status_code=422)
                    source_path = str(raw.get("path") or "")
                    parts = source_path.split("/")
                    if (
                        not source_path
                        or source_path.startswith("/")
                        or len(source_path) > 2048
                        or "\0" in source_path
                        or any(not part or part in {".", ".."} for part in parts)
                    ):
                        raise DomainError("RCLONE_BROWSER_PATH_INVALID", "Path rclone harus berada di bawah root yang dikonfigurasi.", status_code=422)
                    if source_path not in seen:
                        sources.append({"path": source_path, "is_dir": raw["is_dir"]})
                        seen.add(source_path)
                if not sources:
                    raise DomainError("STORAGE_SELECTION_EMPTY", "Pilihan rclone kosong.", status_code=422)
                values["rclone_sources"] = sources
                values["rclone_destination"] = str(
                    self._utility_settings_snapshot().get("rclone_destination", "googledrive:backup")
                ).strip()
                try:
                    validate_rclone_destination(values["rclone_destination"])
                except ValueError as exc:
                    raise DomainError("RCLONE_DESTINATION_INVALID", "Root rclone yang dikonfigurasi tidak valid.", status_code=409) from exc
            return values

        if kind == "chat_send":
            try:
                chat_ref = normalize_tdl_chat_ref(str(payload.get("chat_ref") or "").strip())
            except ValueError as exc:
                raise DomainError("INVALID_CHAT_REF", str(exc), status_code=422) from exc

            raw_folders = payload.get("folders")
            if not isinstance(raw_folders, list) or not raw_folders or len(raw_folders) > 500:
                raise DomainError("CHAT_SEND_FOLDERS_REQUIRED", "Pilih satu atau beberapa folder Workspace.", status_code=422)
            folders: list[str] = []
            seen_folders: set[str] = set()
            for raw in raw_folders:
                raw_path = str(raw or "").strip()
                path = PurePosixPath(raw_path)
                if (
                    not raw_path or len(raw_path) > 2048
                    or not path.is_absolute() or len(path.parts) < 2
                    or path.parts[1] != "workspace" or ".." in path.parts
                    or "\\" in raw_path or any(ord(char) < 32 for char in raw_path)
                ):
                    raise DomainError("CHAT_SEND_FOLDER_INVALID", "Folder harus berupa path absolut di dalam /workspace.", status_code=422)
                normalized = str(path)
                if normalized not in seen_folders:
                    folders.append(normalized)
                    seen_folders.add(normalized)
            folders.sort(key=lambda value: (len(PurePosixPath(value).parts), value.casefold(), value))
            pruned: list[str] = []
            for folder in folders:
                if any(folder == parent or folder.startswith(parent.rstrip("/") + "/") for parent in pruned):
                    continue
                pruned.append(folder)

            from tme3bot.names import normalize_profile_name

            raw_profiles = payload.get("profiles")
            if not isinstance(raw_profiles, list) or not raw_profiles or len(raw_profiles) > 50:
                raise DomainError("CHAT_SEND_PROFILES_REQUIRED", "Pilih setidaknya satu profil TDL.", status_code=422)
            selected_profiles: list[str] = []
            for raw_profile in raw_profiles:
                profile_name = normalize_profile_name(str(raw_profile or ""))
                if not profile_name:
                    raise DomainError("CHAT_SEND_PROFILE_INVALID", "Nama profil TDL tidak valid.", status_code=422)
                self.require_profile(actor, profile_name)
                if profile_name not in selected_profiles:
                    selected_profiles.append(profile_name)

            transfer_mode = str(payload.get("transfer_mode") or "copy").strip().lower()
            move_confirmed = payload.get("move_confirmed", False)
            if transfer_mode not in {"copy", "move"} or type(move_confirmed) is not bool:
                raise DomainError("CHAT_SEND_MODE_INVALID", "Mode transfer tidak valid.", status_code=422)
            if transfer_mode == "move" and not move_confirmed:
                raise DomainError("CHAT_SEND_MOVE_CONFIRMATION_REQUIRED", "Move memerlukan konfirmasi eksplisit.", status_code=422)

            retry_paths = payload.get("retry_paths")
            if retry_paths is not None:
                if not isinstance(retry_paths, list) or not retry_paths or len(retry_paths) > 100_000:
                    raise DomainError("CHAT_SEND_RETRY_INVALID", "Daftar file Retry tidak valid.", status_code=422)
                normalized_retry_paths: list[str] = []
                for raw_path in retry_paths:
                    item_path = str(raw_path or "")
                    item = PurePosixPath(item_path)
                    if (
                        not item_path or item.is_absolute() or ".." in item.parts
                        or any(part in {"", "."} for part in item.parts)
                        or item.as_posix() != item_path or len(item_path) > 2048
                    ):
                        raise DomainError("CHAT_SEND_RETRY_INVALID", "Path file Retry tidak valid.", status_code=422)
                    if item_path not in normalized_retry_paths:
                        normalized_retry_paths.append(item_path)
                retry_paths = sorted(normalized_retry_paths)

            values: dict[str, Any] = {
                "chat_ref": chat_ref,
                "folders": pruned,
                "profiles": selected_profiles,
                "_tdl_sender_profiles": selected_profiles,
                "transfer_mode": transfer_mode,
                "move_confirmed": move_confirmed,
            }
            if retry_paths is not None:
                values["_retry_paths"] = retry_paths
            return values

        if kind == "leave":
            chat_refs = payload.get("chat_refs")
            if not isinstance(chat_refs, list) or not chat_refs or len(chat_refs) > 1000:
                raise DomainError("JOB_PAYLOAD_INVALID", "Daftar chat leave tidak valid.", status_code=422)
            try:
                return {"chat_refs": sorted({normalize_tdl_chat_ref(str(item)) for item in chat_refs})}
            except ValueError as exc:
                raise DomainError("INVALID_CHAT_REF", str(exc), status_code=422) from exc

        if kind == "download":
            artifact_ids = payload.get("artifact_ids")
            priority = str(payload.get("priority") or "normal").strip().lower()
            if not isinstance(artifact_ids, list) or not artifact_ids or len(artifact_ids) > 500:
                raise DomainError("JOB_PAYLOAD_INVALID", "Daftar artifact download tidak valid.", status_code=422)
            if priority not in {"normal", "next"}:
                raise DomainError("JOB_PAYLOAD_INVALID", "Prioritas download tidak valid.", status_code=422)
            if self.export_catalog is None:
                raise DomainError("ARTIFACT_CATALOG_UNAVAILABLE", "Katalog artifact belum tersedia.", status_code=503)
            artifact_keys: list[str] = []
            artifact_refs: list[dict[str, str]] = []
            retry_failed = False
            for artifact_id in artifact_ids:
                artifact = self.export_catalog.get(str(artifact_id))
                if artifact is None:
                    raise DomainError("ARTIFACT_NOT_FOUND", "Artifact tidak ditemukan.", status_code=404)
                artifact_profile = str(artifact["profile"])
                artifact_worker = str(artifact["worker"])
                self.require_profile(actor, artifact_profile)
                if (artifact_profile, artifact_worker) != (profile, worker):
                    raise DomainError("ARTIFACT_ORIGIN_MIXED", "Pilih artifact dari satu origin profile-worker.", status_code=409)
                if artifact["status"] not in {"pending", "failed"}:
                    raise DomainError("ARTIFACT_NOT_PENDING", "Artifact tidak berada pada antrean yang dapat dijalankan.", status_code=409)
                if not bool(artifact.get("available", 1)):
                    raise DomainError("ARTIFACT_UNAVAILABLE", "File artifact sudah tidak tersedia pada worker.", status_code=409)
                retry_failed = retry_failed or artifact["status"] == "failed"
                artifact_keys.append(str(artifact["artifact_key"]))
                artifact_refs.append({"key": str(artifact["artifact_key"]), "status": str(artifact["status"])})
            return {
                "retry_failed": retry_failed,
                "artifact_keys": artifact_keys,
                "artifacts": artifact_refs,
                "priority": priority,
            }

        if kind == "utility":
            utility = str(payload.get("utility") or "").strip().lower()
            folders = payload.get("folders")
            if utility not in {
                "extract", "compress", "export", "pindah", "flatten",
                "video_convert", "image_compress", "media_pipeline",
            }:
                raise DomainError("UTILITY_INVALID", "Jenis utility tidak dikenal.", status_code=422)
            if not isinstance(folders, list) or not folders or len(folders) > 500:
                raise DomainError("JOB_PAYLOAD_INVALID", "Daftar folder utility tidak valid.", status_code=422)
            normalized_folders = []
            for value in folders:
                path = PurePosixPath(str(value or ""))
                if not path.is_absolute() or not path.parts or path.parts[0] != "/" or len(path.parts) < 2 or path.parts[1] != "workspace" or ".." in path.parts:
                    raise DomainError("UTILITY_PATH_INVALID", "Folder utility harus berada di dalam /workspace.", status_code=422)
                normalized_folders.append(str(path))
            password = payload.get("password")
            if password is not None and (not isinstance(password, str) or len(password) > 512):
                raise DomainError("JOB_PAYLOAD_INVALID", "Password utility tidak valid.", status_code=422)
            submitted_video_options = payload.get("video_options")
            if utility in {"video_convert", "media_pipeline"}:
                try:
                    video_options = normalize_video_options(submitted_video_options)
                except ValueError as exc:
                    raise DomainError(
                        "UTILITY_VIDEO_OPTIONS_INVALID",
                        "Pengaturan konversi video tidak valid.",
                        status_code=422,
                    ) from exc
            else:
                if submitted_video_options is not None:
                    raise DomainError(
                        "UTILITY_VIDEO_OPTIONS_INVALID",
                        "Pengaturan video hanya berlaku untuk konversi video.",
                        status_code=422,
                    )
                video_options = None
            flatten_action = payload.get("flatten_action")
            flatten_fingerprints = payload.get("flatten_fingerprints")
            if utility == "flatten":
                if flatten_action not in {"preview", "apply"}:
                    raise DomainError(
                        "UTILITY_FLATTEN_ACTION_INVALID",
                        "Tindakan Flatten harus berupa preview atau apply.",
                        status_code=422,
                    )
                if len(set(normalized_folders)) != len(normalized_folders):
                    raise DomainError(
                        "UTILITY_FLATTEN_FOLDERS_INVALID",
                        "Folder Flatten tidak boleh dipilih lebih dari sekali.",
                        status_code=422,
                    )
                if flatten_action == "preview":
                    if flatten_fingerprints not in (None, {}):
                        raise DomainError(
                            "UTILITY_FLATTEN_SNAPSHOT_INVALID",
                            "Preview Flatten tidak menerima snapshot lama.",
                            status_code=422,
                        )
                    flatten_fingerprints = None
                else:
                    if not isinstance(flatten_fingerprints, dict) or set(flatten_fingerprints) != set(normalized_folders):
                        raise DomainError(
                            "UTILITY_FLATTEN_SNAPSHOT_INVALID",
                            "Apply Flatten memerlukan snapshot untuk semua folder pilihan.",
                            status_code=422,
                        )
                    for fingerprint in flatten_fingerprints.values():
                        if (
                            not isinstance(fingerprint, str)
                            or len(fingerprint) != 64
                            or any(character not in "0123456789abcdef" for character in fingerprint)
                        ):
                            raise DomainError(
                                "UTILITY_FLATTEN_SNAPSHOT_INVALID",
                                "Fingerprint Preview Flatten tidak valid.",
                                status_code=422,
                            )
            elif flatten_action is not None or flatten_fingerprints is not None:
                raise DomainError(
                    "UTILITY_FLATTEN_ACTION_INVALID",
                    "Opsi preview hanya berlaku untuk Flatten.",
                    status_code=422,
                )
            normalized = {
                "utility": utility,
                "folders": normalized_folders,
                "password": password,
                "settings": self._utility_settings_snapshot(),
            }
            if utility == "flatten":
                normalized["flatten_action"] = flatten_action
                if flatten_fingerprints is not None:
                    normalized["flatten_fingerprints"] = flatten_fingerprints
            if video_options is not None:
                normalized["video_options"] = video_options.to_payload()
            return normalized

        if kind == "storage_upload":
            folder_path = str(payload.get("folder_path") or "").strip()
            source_path = PurePosixPath(folder_path)
            if not source_path.is_absolute() or len(source_path.parts) < 2 or source_path.parts[1] != "workspace" or ".." in source_path.parts:
                raise DomainError("STORAGE_SOURCE_INVALID", "Folder sumber harus berada di dalam /workspace.", status_code=422)
            destination_id = payload.get("destination_folder_id")
            if destination_id is not None and (type(destination_id) is not int or destination_id < 1):
                raise DomainError("STORAGE_FOLDER_INVALID", "Folder tujuan tidak valid.", status_code=422)
            provider = str(payload.get("provider") or "telegram").strip().lower()
            if provider not in {"telegram", "rclone"}:
                raise DomainError("STORAGE_PROVIDER_INVALID", "Tujuan upload Storage tidak valid.", status_code=422)
            preserve_structure = payload.get("preserve_structure", True)
            transfer_mode = str(payload.get("transfer_mode") or "copy").strip().lower()
            move_confirmed = payload.get("move_confirmed", False)
            if type(preserve_structure) is not bool or type(move_confirmed) is not bool or transfer_mode not in {"copy", "move"}:
                raise DomainError("JOB_PAYLOAD_INVALID", "Opsi upload Storage harus berupa boolean.", status_code=422)
            if transfer_mode == "move" and not move_confirmed:
                raise DomainError("STORAGE_MOVE_CONFIRMATION_REQUIRED", "Move memerlukan konfirmasi eksplisit.", status_code=422)
            keywords = str(payload.get("keywords") or "")
            if len(keywords) > 600:
                raise DomainError("JOB_PAYLOAD_INVALID", "Keywords Storage terlalu panjang.", status_code=422)
            values = {
                "folder_path": str(source_path), "provider": provider,
                "preserve_structure": preserve_structure, "keywords": keywords,
                "transfer_mode": transfer_mode, "move_confirmed": move_confirmed,
                "batch_id": str(uuid.uuid4()), "owner_user_id": actor.telegram_user_id,
                "owner_profile": actor.profile,
            }
            if provider == "telegram":
                if payload.get("rclone_path"):
                    raise DomainError("STORAGE_TARGET_INVALID", "Path rclone hanya berlaku untuk tujuan rclone.", status_code=422)
                if self.storage_catalog is None:
                    raise DomainError("STORAGE_UNAVAILABLE", "Katalog Storage belum tersedia.", status_code=503)
                if destination_id is None and str(payload.get("folder") or "").strip():
                    folder = self.storage_catalog.ensure_path(str(payload["folder"]).strip(), actor.telegram_user_id)
                    destination_id = folder.id if folder else None
                if destination_id is not None:
                    selected = self.storage_catalog.get_folder(destination_id)
                    if selected is None or selected.status != "active":
                        raise DomainError("STORAGE_FOLDER_INVALID", "Folder tujuan tidak aktif.", status_code=409)
                values.update({
                    "folder": str(payload.get("folder") or ""),
                    "destination_folder_id": destination_id,
                    "destination_folder_path": self.storage_catalog.folder_path(destination_id),
                })
            else:
                if destination_id is not None or str(payload.get("folder") or "").strip():
                    raise DomainError("STORAGE_TARGET_INVALID", "Pilih tepat satu tujuan upload.", status_code=422)
                raw_remote_path = str(payload.get("rclone_path") or "")
                if raw_remote_path.startswith("/"):
                    raise DomainError("RCLONE_BROWSER_PATH_INVALID", "Path rclone harus berada di bawah root yang dikonfigurasi.", status_code=422)
                remote_path = raw_remote_path.strip("/")
                parts = remote_path.split("/") if remote_path else []
                if len(remote_path) > 2048 or "\0" in remote_path or any(not part or part in {".", ".."} for part in parts):
                    raise DomainError("RCLONE_BROWSER_PATH_INVALID", "Path rclone harus berada di bawah root yang dikonfigurasi.", status_code=422)
                values["rclone_path"] = remote_path
                values["rclone_destination"] = self._utility_settings_snapshot().get("rclone_destination", "googledrive:backup")
                try:
                    validate_rclone_destination(str(values["rclone_destination"] or "").strip())
                except ValueError as exc:
                    raise DomainError("RCLONE_DESTINATION_INVALID", "Root rclone yang dikonfigurasi tidak valid.", status_code=409) from exc
            return values

        if kind == "tts":
            title = str(payload.get("title") or "").strip()
            text = str(payload.get("text") or "").strip()
            if not title or len(title) > 200:
                raise DomainError("TTS_TITLE_INVALID", "Judul TTS wajib diisi dan maksimal 200 karakter.", status_code=422)
            if not text or len(text) > 100_000:
                raise DomainError("TTS_TEXT_INVALID", "Teks TTS wajib diisi dan maksimal 100.000 karakter.", status_code=422)
            return {"title": title, "text": text}

        if kind == "tdl_access_verify":
            purpose = str(payload.get("purpose") or "").strip().lower()
            if purpose not in {"tts", "storage"}:
                raise DomainError("TDL_ACCESS_PURPOSE_INVALID", "Tujuan verifikasi TDL tidak valid.", status_code=422)
            if self.tdl_access_store is None:
                raise DomainError("TDL_ACCESS_UNAVAILABLE", "Layanan verifikasi akses TDL belum aktif.", status_code=503)
            destination = self._tdl_access_target(purpose)
            if not destination:
                raise DomainError("TDL_ACCESS_TARGET_UNAVAILABLE", f"Tujuan TDL {purpose} belum dikonfigurasi.", status_code=503)
            return {
                "purpose": purpose,
                "destination_hash": self.tdl_access_store.destination_fingerprint(destination),
            }

        if kind == "backup_verify":
            run_id = str(payload.get("run_id") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", run_id):
                raise DomainError("BACKUP_SELECTION_INVALID", "Run backup yang dipilih tidak valid.", status_code=422)
            if self.storage_catalog is None:
                raise DomainError("BACKUP_CATALOG_UNAVAILABLE", "Katalog backup belum tersedia.", status_code=503)
            runs = self.storage_catalog.backup_runs(node_name=worker, limit=200)
            run = next((item for item in runs if str(item.get("run_id") or "") == run_id), None)
            if run is None:
                raise DomainError("BACKUP_RUN_NOT_FOUND", "Run backup tidak ditemukan untuk worker yang dipilih.", status_code=404)
            if str(run.get("status") or "") != "complete":
                raise DomainError("BACKUP_RUN_NOT_COMPLETE", "Run backup worker belum berstatus complete.", status_code=409)
            raw_parts = self.storage_catalog.backup_parts(run_id, worker)
            channel_ids: set[int] = set()
            for item in raw_parts if isinstance(raw_parts, list) else []:
                try:
                    channel_id = int(item.get("channel_id") or 0)
                except (AttributeError, TypeError, ValueError):
                    continue
                if channel_id:
                    channel_ids.add(channel_id)
            if len(channel_ids) > 1:
                raise DomainError("BACKUP_CHANNEL_INVALID", "Part backup tidak menunjuk ke satu channel Telegram yang sama.", status_code=409)
            from tme3bot.channel_ref import channel_tdl_ref

            if channel_ids:
                channel_ref = channel_tdl_ref(str(next(iter(channel_ids))))
            else:
                settings = {}
                getter = getattr(
                    getattr(self, "runtime_settings_store", None),
                    "get_values",
                    None,
                )
                if callable(getter):
                    try:
                        try:
                            settings = getter("backend", include_secrets=False)
                        except TypeError:
                            settings = getter("backend")
                    except Exception:
                        settings = {}
                configured_channel = (
                    settings.get("backup_channel")
                    or settings.get("backup_channel_ref")
                    or settings.get("backup_channel_id")
                ) if isinstance(settings, dict) else ""
                channel_ref = channel_tdl_ref(str(configured_channel or ""))
            if not channel_ref:
                raise DomainError("BACKUP_CHANNEL_INVALID", "Referensi channel backup tidak dapat dipakai TDL.", status_code=409)
            return {
                "run_id": run_id,
                "node_name": worker,
                "profile": profile,
                "run_record": {
                    "run_id": run_id,
                    "node_name": worker,
                    "started_at": str(run.get("started_at") or ""),
                    "status": str(run.get("status") or ""),
                },
                # The worker discovers this run's part names and message IDs
                # from `chat export --with-content`. Catalog rows are optional
                # hints only; stale IDs/checksums/status must not block a run.
                "parts": [],
                "channel_ref": channel_ref,
            }

        if kind == "safelink_resolve":
            try:
                return {"url": normalize_shortlink_url(payload.get("url"))}
            except ValueError as exc:
                raise DomainError("SAFELINK_URL_INVALID", str(exc), status_code=422) from None

        raise DomainError("JOB_KIND_INVALID", "Jenis job belum didukung oleh dispatch background.", status_code=422)

    def _utility_settings_snapshot(self) -> dict[str, Any]:
        getter = getattr(self.utility_settings, "get", None)
        values = getter() if callable(getter) else DEFAULT_UTILITY_SETTINGS
        return deepcopy(values if isinstance(values, dict) else DEFAULT_UTILITY_SETTINGS)

    def _worker_settings_version(self, worker: str) -> int:
        snapshotter = getattr(self.runtime_settings_store, "snapshot", None)
        if not callable(snapshotter):
            return 0
        try:
            snapshot = snapshotter("worker", worker=str(worker).strip().lower())
        except Exception:
            return 0
        if not isinstance(snapshot, dict):
            return 0
        try:
            return max(0, int(snapshot.get("desired_version") or 0))
        except (TypeError, ValueError):
            return 0

    def _current_tts_chat_ref(self) -> str:
        getter = getattr(self.runtime_settings_store, "get_values", None)
        if not callable(getter):
            return ""
        try:
            values = getter("telegram", include_secrets=True)
        except Exception:
            return ""
        return str(values.get("telegram_tts_chat_id") or "").strip() if isinstance(values, dict) else ""

    def _tdl_access_target(self, purpose: str) -> str:
        resolver = self.tdl_access_target_resolver
        if not callable(resolver):
            return ""
        try:
            return str(resolver(str(purpose or "").strip().lower()) or "").strip()
        except Exception:
            return ""

    def _tdl_access_candidates(
        self, worker: str, purpose: str, destination: str
    ) -> list[str]:
        context = self._tdl_access_worker_context(worker, purpose, destination)
        return context[0] if context is not None else []

    def tts_access_evidence_ready(
        self,
        worker: str,
        profile: str,
        session_fingerprint: str,
        *,
        destination: str | None = None,
    ) -> bool:
        """Check saved TTS send evidence against an observed Export session."""
        store = self.tdl_access_store
        target = str(destination or self._tdl_access_target("tts")).strip()
        selected_worker = str(worker or "").strip().lower()
        selected_profile = str(profile or "").strip().lower()
        fingerprints = normalize_session_fingerprints(
            {selected_profile: session_fingerprint}
        )
        fingerprint = fingerprints.get(selected_profile)
        if not store or not target or not selected_worker or not fingerprint:
            return False
        destination_hash = store.destination_fingerprint(target)
        # Existing TTS evidence is indexed by the local profile inventory. The
        # row's session_fingerprint binds that proof to the observed TDL tree.
        inventory_hash = store.inventory_fingerprint([selected_profile])
        results = store.snapshot(
            selected_worker,
            "tts",
            destination_hash,
            inventory_hash,
            session_fingerprints={selected_profile: fingerprint},
        )
        return any(
            item.get("profile") == selected_profile and item.get("ready") is True
            for item in results
        )

    def _tdl_access_worker_context(
        self, worker: str, purpose: str, destination: str
    ) -> tuple[list[str], dict[str, str] | None, str, str] | None:
        store = self.tdl_access_store
        checker = getattr(self.dispatcher, "capabilities", None)
        if store is None or not callable(checker) or not destination:
            return None
        try:
            capabilities = checker(worker)
        except Exception:
            return None
        if not isinstance(capabilities, dict):
            return None
        profiles, session_fingerprints = self._tdl_access_inventory(capabilities, purpose)
        destination_hash = store.destination_fingerprint(destination)
        inventory_hash = store.inventory_fingerprint(profiles, session_fingerprints)
        candidates = store.verified_profiles(
            worker,
            purpose,
            destination_hash,
            inventory_hash,
            session_fingerprints=session_fingerprints,
        )
        return candidates, session_fingerprints, destination_hash, inventory_hash

    def _tdl_access_sender_options(
        self, worker: str, purpose: str, destination: str
    ) -> tuple[str, list[str], dict[str, str] | None]:
        store = self.tdl_access_store
        if not destination or store is None:
            raise DomainError(
                "TDL_ACCESS_NOT_VERIFIED",
                "Verifikasi akses kirim TDL untuk worker dan tujuan ini terlebih dahulu.",
                status_code=409,
            )
        context = self._tdl_access_worker_context(worker, purpose, destination)
        if context is None:
            raise DomainError(
                "WORKER_OFFLINE",
                f"Worker {worker} tidak dapat diperiksa.",
                status_code=503,
            )
        candidates, session_fingerprints, destination_hash, inventory_hash = context
        selected = store.choose_next(
            worker,
            purpose,
            destination_hash,
            inventory_hash,
            session_fingerprints=session_fingerprints,
        )
        if selected:
            return selected, candidates, session_fingerprints
        raise DomainError(
            "TDL_ACCESS_NOT_VERIFIED",
            "Belum ada profil di worker ini yang terverifikasi dapat mengirim ke tujuan. Jalankan verifikasi akses TDL.",
            status_code=409,
            details={"worker": worker, "purpose": purpose},
        )

    def _storage_sender_snapshot(
        self, worker: str, *, destination: str | None = None,
        fallback_profile: str | None = None,
    ) -> tuple[str, list[str], dict[str, str]]:
        """Choose live local Upload candidates without consulting saved proofs."""
        target = str(destination or self._tdl_access_target("storage") or "").strip()
        if not target:
            raise DomainError(
                "TDL_ACCESS_TARGET_UNAVAILABLE",
                "Tujuan TDL Storage belum dikonfigurasi.",
                status_code=503,
            )
        fallback = str(fallback_profile or "").strip().lower()
        if self.gateway_mode == "lite":
            # The worker enumerates its own local sessions during execution;
            # do not hold a submit request open for a capabilities RPC.
            profiles = [fallback] if fallback else []
        else:
            profiles = self._worker_profile_candidates(worker, "storage")
        if not profiles:
            profiles = [fallback] if fallback else []
        if not profiles:
            raise DomainError("PROFILE_REQUIRED", "Pilih profil untuk mencoba upload TDL.", status_code=422)
        selected = self._select_tts_sender_profile(worker, profiles)
        return selected, [selected, *[item for item in profiles if item != selected]], {}

    def _worker_profile_candidates(self, worker: str, purpose: str) -> list[str]:
        """Return current local profile names advertised by the selected worker."""
        checker = getattr(self.dispatcher, "capabilities", None)
        capabilities: dict[str, Any] = {}
        if callable(checker):
            try:
                response = checker(str(worker or "").strip().lower())
                capabilities = response if isinstance(response, dict) else {}
            except Exception:
                capabilities = {}
        values = capabilities.get("local_profiles")
        if not isinstance(values, list):
            values = capabilities.get("profiles")
        if not isinstance(values, list):
            values = (
                capabilities.get("available_storage_profiles")
                if purpose == "storage"
                else capabilities.get("download_profiles")
                if purpose == "download"
                else capabilities.get("export_profiles")
            )
        profiles = sorted({str(item).strip().lower() for item in values or [] if str(item).strip()})
        if profiles:
            return profiles
        # A local worker used by isolated compositions may not have a remote
        # capabilities adapter. Its own profile list is still a live inventory.
        if str(worker or "").strip().lower() == str(getattr(self.profile_manager, "worker_name", "local") or "local").strip().lower():
            list_profiles = getattr(self.profile_manager, "list_profiles", None)
            if callable(list_profiles):
                return sorted({str(item).strip().lower() for item in list_profiles() if str(item).strip()})
        return []

    def _quick_storage_access_snapshot(
        self,
        worker: str,
        profile: str,
        quick_settings: dict[str, Any] | None = None,
    ) -> tuple[str, list[str]]:
        """Return the configured Telegram target and current worker profiles."""
        destination = self._tdl_access_target("storage")
        if not destination:
            raise DomainError(
                "TDL_ACCESS_TARGET_UNAVAILABLE",
                "Tujuan TDL Storage belum dikonfigurasi.",
                status_code=503,
            )
        del quick_settings
        profiles = (
            [str(profile or "").strip().lower()]
            if self.gateway_mode == "lite" and str(profile or "").strip()
            else self._worker_profile_candidates(worker, "storage")
        )
        return destination, profiles

    def _tdl_access_inventory(
        self, capabilities: dict[str, Any], purpose: str
    ) -> tuple[list[str], dict[str, str] | None]:
        if purpose == "storage":
            profiles = normalize_profiles(
                capabilities.get("local_profiles")
                or capabilities.get("profiles")
                or capabilities.get("available_storage_profiles")
            )
            return profiles, None

        raw_profiles = capabilities.get("export_profiles")
        if not isinstance(raw_profiles, list):
            raw_profiles = capabilities.get("available_storage_profiles")
        if not isinstance(raw_profiles, list):
            raw_profiles = capabilities.get("profiles", [])
        return normalize_profiles(raw_profiles), None

    def tdl_access_verification_status(self, worker: str, purpose: str) -> dict[str, Any]:
        purpose = str(purpose or "").strip().lower()
        worker = str(worker or "").strip().lower()
        if purpose not in {"tts", "storage"}:
            raise DomainError("TDL_ACCESS_PURPOSE_INVALID", "Tujuan verifikasi TDL tidak valid.", status_code=422)
        target = self._tdl_access_target(purpose)
        if not target or self.tdl_access_store is None:
            raise DomainError("TDL_ACCESS_TARGET_UNAVAILABLE", f"Tujuan TDL {purpose} belum dikonfigurasi.", status_code=503)
        if self.gateway_mode == "lite":
            self._require_lite_explicit_worker(worker)
            if worker not in self._worker_names_for_mode():
                raise DomainError(
                    "LITE_REMOTE_WORKER_REQUIRED",
                    "Status verifikasi Lite hanya tersedia untuk worker yang aktif pada konfigurasi ini.",
                    status_code=409,
                )
            # This is a saved-proof view in Lite. Never probe a worker (or
            # reveal a local target) from a status GET; an explicit scan/job
            # updates the inventory and proof snapshots.
            profiles = self.verified_profiles_for_worker(worker) or []
            session_fingerprints = None
        else:
            checker = getattr(self.dispatcher, "capabilities", None)
            try:
                capabilities = checker(worker) if callable(checker) else {}
            except Exception as exc:
                raise DomainError("WORKER_OFFLINE", f"Worker {worker} tidak dapat diperiksa.", status_code=503) from exc
            capabilities = capabilities if isinstance(capabilities, dict) else {}
            profiles, session_fingerprints = self._tdl_access_inventory(capabilities, purpose)
        destination_hash = self.tdl_access_store.destination_fingerprint(target)
        # Saved canary lookup is informational. Do not bind current results to
        # a session-generation fingerprint that changes after deployment.
        inventory_hash = self.tdl_access_store.inventory_fingerprint(profiles, None)
        results = self.tdl_access_store.snapshot(
            worker,
            purpose,
            destination_hash,
            inventory_hash,
            session_fingerprints=None,
        )
        return {
            "worker": worker,
            "purpose": purpose,
            "session": "upload" if purpose == "storage" else "export",
            "verified_profiles": [str(item["profile"]) for item in results if item["ready"]],
            "profiles": results,
            "inventory_hash": inventory_hash,
            "ready": any(item["ready"] for item in results),
        }

    def choose_tdl_sender_profile(
        self, worker: str, purpose: str, *, destination: str | None = None
    ) -> str:
        target = str(destination or self._tdl_access_target(purpose)).strip()
        selected, _candidates, _fingerprints = self._tdl_access_sender_options(
            worker, purpose, target
        )
        return selected

    def _encrypt_private_job_values(
        self, job_id: str, values: dict[str, str]
    ) -> dict[str, bytes]:
        if not values:
            return {}
        encryptor = getattr(self.runtime_settings_store, "encrypt_job_secret", None)
        if not callable(encryptor):
            raise DomainError(
                "JOB_PRIVATE_STORAGE_UNAVAILABLE",
                "Penyimpanan privat job belum tersedia.",
                status_code=503,
            )
        result: dict[str, bytes] = {}
        for key, value in values.items():
            if key not in {
                "telegram_tts_chat_id",
                "tdl_access_target",
                "tdl_storage_chat_ref",
                "tdl_sender_session_fingerprints",
                "storage_sync_session_fingerprint",
                "backup_archive_password",
            } or not isinstance(value, str) or not value.strip():
                raise DomainError(
                    "JOB_PRIVATE_VALUE_INVALID",
                    "Snapshot privat job tidak valid.",
                    status_code=422,
                )
            result[key] = encryptor(job_id, key, value.strip())
        return result

    def private_job_value(self, job_id: str, key: str) -> str | None:
        getter = getattr(self.jobs, "private_value", None)
        decryptor = getattr(self.runtime_settings_store, "decrypt_job_secret", None)
        if not callable(getter) or not callable(decryptor):
            return None
        ciphertext = getter(str(job_id), str(key))
        if ciphertext is None:
            return None
        return decryptor(str(job_id), str(key), ciphertext)

    def advance_durable_job(self, command: dict[str, Any]) -> dict[str, str]:
        private = command.get("private_payload") if isinstance(command.get("private_payload"), dict) else {}
        job_id = str(private.get("job_id") or "")
        job = self.jobs.get(job_id) if job_id else None
        if job is None:
            return {"status": "terminal", "reason": "job_missing"}
        stored = self.jobs.command_payload(job.id)
        if not isinstance(stored, dict) or stored.get("dispatch_mode") != "durable":
            return {"status": "terminal", "reason": "dispatch_mode_changed"}
        attempt = max(1, int(command.get("attempt") or 1))
        stored_attempt = max(1, int(stored.get("attempt") or 1))
        if job.status.terminal:
            if attempt <= stored_attempt:
                return {"status": "terminal", "reason": "job_terminal"}
            # Reset the public job, durable command identity, and retry event in
            # one SQLite transaction. This also drops cancellation intent from
            # the previous attempt before inspecting the new attempt below.
            retry_payload = {
                **stored,
                "attempt": attempt,
                "command_id": str(uuid.uuid4()),
                "dispatch_token": secrets.token_urlsafe(32),
                "dispatch_started": False,
                "cancel_before_dispatch": False,
                "cancel_after_dispatch": False,
                "cancel_after_dispatch_accepted": False,
            }
            retry_payload.pop("worker_ack_wait_started_at", None)
            retry_payload.pop("cancel_before_dispatch_attempt", None)
            retry_payload.pop("cancel_after_dispatch_attempt", None)
            retry_event = JobEvent(
                job_id=job.id,
                sequence=self._next_job_event_sequence(job.id, fallback=job),
                status=JobStatus.QUEUED,
                event_type="retry_started",
                progress={"phase": "queued", "retry_attempt": attempt},
            )
            execution = self.jobs.execution_plan(job.id) or stored.get("execution") or {}
            job = self.jobs.reset_for_retry(
                job.id,
                self._redacted_payload(job.kind, stored.get("payload") or {}),
                execution_plan=execution,
                command_payload=retry_payload,
                retry_event=retry_event,
            )
            # reset_for_retry persisted the event atomically; replay its
            # idempotent observers after commit.
            self.append_worker_event(retry_event)
            job = self.jobs.get(job.id) or job
            stored = self.jobs.command_payload(job.id) or retry_payload
            stored_attempt = max(1, int(stored.get("attempt") or attempt))
        if attempt > stored_attempt:
            # Some older retry rows can already be queued while their internal
            # durable command still points at the previous attempt. Atomically
            # advance the command and preserve a cancellation requested for
            # this queued attempt.
            updated = {
                **stored,
                "attempt": attempt,
                "command_id": str(uuid.uuid4()),
                "dispatch_token": secrets.token_urlsafe(32),
                "dispatch_started": False,
            }
            updated.pop("worker_ack_wait_started_at", None)
            advancer = getattr(self.jobs, "advance_durable_attempt", None)
            if callable(advancer):
                advance_state = advancer(job.id, attempt, updated)
                if advance_state == "dispatch_started":
                    return {"status": "wait", "reason": "dispatch_in_progress"}
                if advance_state in {"job_missing", "not_queued", "not_durable"}:
                    return {"status": "wait", "reason": "retry_race"}
                stored = self.jobs.command_payload(job.id) or updated
                if advance_state == "advanced":
                    retry_event = next(
                        (
                            event for event in reversed(self.jobs.events(job.id))
                            if event.event_type == "retry_started"
                            and int(event.progress.get("retry_attempt") or 0) == attempt
                        ),
                        None,
                    )
                    if retry_event is not None:
                        self.append_worker_event(retry_event)
            else:
                self.jobs.update_command_payload(job.id, updated)
                stored = updated
            job = self.jobs.get(job.id) or job
            stored_attempt = max(1, int(stored.get("attempt") or attempt))

        cancel_before_attempt = int(
            stored.get("cancel_before_dispatch_attempt") or stored_attempt
        )
        if stored.get("cancel_before_dispatch") and cancel_before_attempt == attempt:
            outcome, _current = self._cancel_queued_before_dispatch(
                job.id,
                event_type="cancelled_queued",
                message="Job queued dibatalkan sebelum dikirim ke worker.",
            )
            if outcome in {"cancelled", "terminal"}:
                return {"status": "terminal", "reason": "cancelled_before_dispatch"}
            return {"status": "wait", "reason": "cancel_race"}

        cancel_after_attempt = int(
            stored.get("cancel_after_dispatch_attempt") or stored_attempt
        )
        if (
            stored.get("cancel_after_dispatch")
            and not stored.get("cancel_after_dispatch_accepted")
            and cancel_after_attempt == attempt
            and job.status in {
                JobStatus.DISPATCHED, JobStatus.RUNNING, JobStatus.PAUSED
            }
        ):
            if self._cancel_worker_attempt(job, attempt=attempt):
                self.jobs.acknowledge_dispatch_cancellation(job.id, attempt)
                return {"status": "accepted", "reason": "cancel_requested"}
            return {"status": "wait", "reason": "cancel_pending"}
        if job.status in {JobStatus.DISPATCHED, JobStatus.RUNNING, JobStatus.PAUSED}:
            return {"status": "accepted", "reason": "already_dispatched"}
        if job.status != JobStatus.QUEUED:
            return {"status": "terminal", "reason": "job_not_queued"}
        if self._worker_unresponsive_reason(job.worker):
            return {"status": "wait", "reason": "worker_unresponsive"}

        if self.worker_registry is not None:
            record = self.worker_registry.get(job.worker)
            if record is None or not bool(record.get("enabled", True)):
                self._clear_worker_ack_wait(job.id, stored)
                return {"status": "wait", "reason": "not_ready"}
        capabilities = getattr(self.dispatcher, "capabilities", None)
        dispatch_command = getattr(self.dispatcher, "dispatch_command", None)
        if not callable(capabilities) or not callable(dispatch_command):
            return {"status": "wait", "reason": "not_ready"}
        required = set(DURABLE_COMMAND_CAPABILITIES)
        cursor_lease_held = bool(
            self.export_cursor_service is not None
            and self.export_cursor_service.job_has_active_lease(job.id)
        )
        if job.kind == "export" and (
            self._shared_export_cursor_enabled() or cursor_lease_held
        ):
            required.add(CAP_SHARED_EXPORT_CURSOR)
        if job.kind == "safelink_resolve":
            required.add(CAP_SAFELINK_RESOLVE)
        if job.kind == "backup_verify":
            required.add(CAP_BACKUP_VERIFY)
        stored_payload = stored.get("payload") if isinstance(stored.get("payload"), dict) else {}
        stored_execution_profile = str(stored.get("profile") or job.profile)
        if job.kind == "storage_download":
            required.add(CAP_STORAGE_DOWNLOAD)
            if stored_payload.get("publish_public_links") is True:
                required.add(CAP_PUBLIC_DOWNLOAD_LINKS)
        if bool((stored.get("payload") or {}).get("quick_mode")):
            required.add(CAP_QUICKMODE_STAGING)
        try:
            worker_capabilities = capabilities(job.worker)
            require_worker_contract(
                worker_capabilities, job.worker, required_capabilities=required
            )
        except DomainError as exc:
            # Capability-contract failures are deterministic and not evidence
            # that the worker is offline. They must not consume the
            # connectivity acknowledgement window.
            self._clear_worker_ack_wait(job.id, stored)
            if job.kind in {"backup_verify", "storage_download"} and exc.code == "WORKER_INCOMPATIBLE":
                self._fail_queued_job(job, exc.code, exc.message)
                return {"status": "terminal", "reason": "worker_incompatible"}
            return {"status": "wait", "reason": "not_ready"}
        except Exception as exc:
            return self._handle_worker_dispatch_exception(job, stored, exc)

        # A healthy capability probe clears a timer only before a command was
        # ever sent. Once dispatch_started is persisted, the stable command may
        # already be in the worker journal and the acknowledgement deadline
        # must span retries until its receipt is confirmed.
        if not bool(stored.get("dispatch_started")):
            self._clear_worker_ack_wait(job.id, stored)

        admission = self.jobs.try_acquire_execution(job.id)
        self.jobs.set_queue_info(
            job.id, int(admission.get("position", 1)), admission.get("blocked_reason")
        )
        if not admission.get("admitted"):
            self._clear_worker_ack_wait(job.id, stored)
            return {"status": "wait", "reason": "not_ready"}
        latest = job.progress_sequence
        envelope = {
            "command_id": str(stored["command_id"]),
            "operation_id": str(command.get("operation_id") or ""),
            "job_id": job.id,
            "attempt": attempt,
            "dispatch_token": str(stored["dispatch_token"]),
            "profile_revision": int(stored.get("profile_revision") or 0),
            "settings_version": int(stored.get("settings_version") or 0),
            "event_sequence_start": latest + 1,
            "execution_plan": self.jobs.execution_plan(job.id) or stored.get("execution") or {},
            "job": {
                "kind": job.kind,
                "profile": stored_execution_profile,
                "actor_user_id": job.actor_user_id,
                "worker": job.worker,
                "payload": self._worker_payload(
                    job.id, job.kind, stored.get("payload") or {}
                ),
            },
        }
        # Atomically persist this before the network call and only if the
        # operation has not begun cancellation. After this point an ACK may be
        # ambiguous, so cancellation must go through the worker.
        begin_queued_dispatch = getattr(
            self.jobs, "begin_queued_worker_dispatch", None
        )
        if callable(begin_queued_dispatch):
            dispatch_state = begin_queued_dispatch(
                job.id,
                attempt=attempt,
                command_id=str(stored["command_id"]),
                operation_id=str(command.get("operation_id") or "") or None,
            )
            dispatch_started = dispatch_state == "started"
        else:
            begin_dispatch = getattr(self.jobs, "begin_durable_dispatch", None)
            dispatch_started = bool(
                callable(begin_dispatch)
                and begin_dispatch(
                    job.id,
                    attempt=attempt,
                    command_id=str(stored["command_id"]),
                    operation_id=str(command.get("operation_id") or "") or None,
                )
            )
            dispatch_state = "started" if dispatch_started else "not_started"
        if not dispatch_started:
            if dispatch_state == "cancel_requested":
                outcome, _current = self._cancel_queued_before_dispatch(
                    job.id,
                    event_type="cancelled_queued",
                    message="Job queued dibatalkan sebelum dikirim ke worker.",
                )
                if outcome in {"cancelled", "terminal"}:
                    return {"status": "terminal", "reason": "cancelled_before_dispatch"}
            current = self.jobs.get(job.id)
            if current is not None and current.status in {
                JobStatus.DISPATCHED, JobStatus.RUNNING, JobStatus.PAUSED
            }:
                # A duplicate advance lost the claim because another advance
                # already crossed the dispatch boundary. Its lease belongs to
                # the active worker and must remain held.
                return {"status": "accepted", "reason": "already_dispatched"}
            if current is not None and current.status.terminal:
                return {"status": "terminal", "reason": "job_terminal"}
            if dispatch_state in {
                "stale_attempt", "stale_command", "operation_cancelling_dispatched"
            }:
                # The same job ID can already hold the resource lease for the
                # newer attempt whose RPC is in flight. A stale handler must
                # not release that lease; the current attempt owns its release.
                return {"status": "terminal", "reason": dispatch_state}
            self.jobs.release_execution(job.id)
            return {"status": "terminal", "reason": "dispatch_aborted"}
        try:
            receipt = dispatch_command(job.worker, envelope)
        except Exception as exc:
            # The stable command ID lets the next queue attempt query the
            # worker journal before resending an acceptance that may be lost.
            return self._handle_worker_dispatch_exception(job, stored, exc)
        if not isinstance(receipt, dict) or receipt.get("accepted") is not True:
            self._clear_worker_ack_wait(job.id, stored)
            return {"status": "wait", "reason": "not_ready"}
        self._clear_worker_ack_wait(job.id, stored)
        latest_payload = self.jobs.command_payload(job.id)
        latest_payload = latest_payload if isinstance(latest_payload, dict) else {}
        if (
            latest_payload.get("cancel_after_dispatch")
            and int(latest_payload.get("cancel_after_dispatch_attempt") or attempt) == attempt
            and not latest_payload.get("cancel_after_dispatch_accepted")
        ):
            if self._cancel_worker_attempt(job, attempt=attempt):
                self.jobs.acknowledge_dispatch_cancellation(job.id, attempt)
                return {"status": "accepted", "reason": "cancel_requested"}
            return {"status": "wait", "reason": "cancel_pending"}
        self.append_worker_event(JobEvent(
            job_id=job.id,
            sequence=latest + 1,
            status=JobStatus.DISPATCHED,
            event_type="durable_dispatch_accepted",
            progress={"worker": job.worker, "position": int(admission.get("position", 1))},
        ))
        return {"status": "accepted"}

    def _fail_queued_job(self, job: Job, code: str, message: str) -> None:
        sequence = self._next_job_event_sequence(job.id, fallback=job)
        self.append_worker_event(JobEvent(
            job_id=job.id,
            sequence=sequence,
            status=JobStatus.FAILED,
            event_type="preflight_failed",
            error={"code": code, "message": message},
        ))

    def _cancel_queued_before_dispatch(
        self, job_id: str, *, event_type: str, message: str
    ) -> tuple[str, Job | None]:
        """Cancel a queued job only if the worker dispatch boundary has not won."""
        with self._stale_job_lock:
            job = self.jobs.get(str(job_id))
            if job is None:
                return "terminal", None
            if job.status.terminal:
                return "terminal", job

            requester = getattr(self.jobs, "request_queued_cancellation", None)
            if callable(requester):
                boundary = requester(job.id)
            else:
                stored = self.jobs.command_payload(job.id)
                dispatch_record = stored if isinstance(stored, dict) else {}
                storage_record = (
                    dispatch_record.get("_storage_durable_dispatch")
                    if isinstance(dispatch_record.get("_storage_durable_dispatch"), dict)
                    else {}
                )
                durable = dispatch_record.get("dispatch_mode") == "durable" or bool(storage_record)
                boundary = (
                    "dispatch_started"
                    if durable
                    else "safe"
                )

            if boundary not in {"safe", "cancel_requested"}:
                return boundary, self.jobs.get(job.id) or job
            current = self.jobs.get(job.id) or job
            if current.status.terminal:
                return "terminal", current
            if not (
                current.status == JobStatus.QUEUED
                or (
                    current.status == JobStatus.PAUSED
                    and current.progress.get("pause_kind") == "queued"
                )
            ):
                return "not_queued", current
            sequence = self._next_job_event_sequence(current.id, fallback=current)
            terminal = self.append_worker_event(
                JobEvent(
                    job_id=current.id,
                    sequence=sequence,
                    status=JobStatus.CANCELLED,
                    event_type=event_type,
                    progress={
                        "phase": "cancelled",
                        "finished_at": utc_now().isoformat(),
                    },
                    error={"code": "JOB_TERMINATED", "message": message},
                ),
                dispatch_pending=False,
            )
            return (
                "cancelled" if terminal.status == JobStatus.CANCELLED else "terminal",
                terminal,
            )

    def _durable_dispatch_attempt(self, job_id: str) -> int | None:
        payload = self.jobs.command_payload(job_id)
        if not isinstance(payload, dict):
            return None
        record = payload if payload.get("dispatch_mode") == "durable" else payload.get(
            _STORAGE_DURABLE_DISPATCH_KEY
        )
        if not isinstance(record, dict) or not record.get("dispatch_started"):
            return None
        try:
            return max(1, int(record.get("attempt") or 1))
        except (TypeError, ValueError):
            return 1

    def _cancel_worker_attempt(self, job: Job, *, attempt: int | None = None) -> bool:
        return self._cancel_worker_attempt_with_timeout(
            job, attempt=attempt, timeout_seconds=None
        )

    def _cancel_worker_attempt_with_timeout(
        self,
        job: Job,
        *,
        attempt: int | None = None,
        timeout_seconds: float | None,
    ) -> bool:
        selected_attempt = (
            max(1, int(attempt)) if attempt is not None
            else self._durable_dispatch_attempt(job.id)
        )
        if timeout_seconds is not None:
            method_name = (
                "cancel_attempt_with_timeout"
                if selected_attempt is not None
                else "cancel_with_timeout"
            )
            fast_cancel = getattr(self.dispatcher, method_name, None)
            if not callable(fast_cancel):
                return False
            if selected_attempt is not None:
                return bool(
                    fast_cancel(
                        job.worker,
                        job.id,
                        selected_attempt,
                        timeout_seconds=timeout_seconds,
                    )
                )
            return bool(
                fast_cancel(
                    job.worker, job.id, timeout_seconds=timeout_seconds
                )
            )
        cancel_attempt = getattr(self.dispatcher, "cancel_attempt", None)
        if selected_attempt is not None and callable(cancel_attempt):
            return bool(cancel_attempt(job.worker, job.id, selected_attempt))
        return bool(self.dispatcher.cancel(job.worker, job.id))

    def _has_pending_dispatch_cancellation(self, job_id: str) -> bool:
        payload = self.jobs.command_payload(job_id)
        if not isinstance(payload, dict):
            return False
        record = payload if payload.get("dispatch_mode") == "durable" else payload.get(
            _STORAGE_DURABLE_DISPATCH_KEY
        )
        return bool(
            isinstance(record, dict)
            and record.get("cancel_after_dispatch")
            and not record.get("cancel_after_dispatch_accepted")
        )

    def _retry_dispatch_cancel_requests(self) -> None:
        """Deliver persisted cancellation intents after worker command acceptance."""
        list_requests = getattr(self.jobs, "dispatch_cancel_requests", None)
        acknowledge = getattr(self.jobs, "acknowledge_dispatch_cancellation", None)
        if not callable(list_requests) or not callable(acknowledge):
            return
        try:
            requests = list_requests(limit=500)
        except Exception:
            logging.getLogger(__name__).exception(
                "Could not load pending worker cancellation requests"
            )
            return
        for job, attempt in requests:
            try:
                if self._cancel_worker_attempt(job, attempt=attempt):
                    acknowledge(job.id, attempt)
            except Exception:
                logging.getLogger(__name__).warning(
                    "Worker cancellation delivery is pending for job %s",
                    job.id,
                    exc_info=True,
                )

    def advance_durable_cancel(self, command: dict[str, Any]) -> dict[str, str]:
        private = command.get("private_payload") if isinstance(command.get("private_payload"), dict) else {}
        job = self.jobs.get(str(private.get("job_id") or ""))
        if job is None or job.status.terminal:
            return {"status": "accepted", "reason": "job_terminal"}
        if job.status in {JobStatus.QUEUED, JobStatus.PAUSED}:
            outcome, current = self._cancel_queued_before_dispatch(
                job.id,
                event_type="operation_cancelled_queued",
                message="Job queued dibatalkan sebelum dikirim ke worker.",
            )
            if outcome in {"cancelled", "terminal"}:
                self._dispatch_pending_jobs()
                return {"status": "accepted"}
            job = current or job
        try:
            # A true return only means the worker accepted the cancel request.
            # Keep the durable operation command retryable until a terminal
            # worker event confirms the actual job outcome.
            signalled = self._cancel_worker_attempt(job)
            if signalled:
                attempt = self._durable_dispatch_attempt(job.id)
                if attempt is not None:
                    self.jobs.acknowledge_dispatch_cancellation(job.id, attempt)
            return {"status": "wait", "reason": "not_ready"}
        except Exception:
            return {"status": "wait", "reason": "not_ready"}

    def _select_tts_worker(self, requested: str | None = None, *, destination: str | None = None) -> str:
        del destination
        options = self.tts_worker_options()
        if not options:
            raise DomainError(
                "TTS_WORKER_UNAVAILABLE",
                "Tidak ada worker aktif untuk job TTS.",
                status_code=503,
            )
        if requested:
            selected = str(requested).strip().lower()
            for option in options:
                if option["name"].lower() == selected:
                    return option["name"]
            raise DomainError(
                "TTS_WORKER_UNAVAILABLE",
                "Worker yang dipilih tidak aktif atau tidak tersedia.",
                status_code=503,
            )
        counts = {option["name"]: option["queued_jobs"] for option in options}
        minimum = min(counts.values())
        tied = sorted(name for name, count in counts.items() if count == minimum)
        with self._tts_route_lock:
            selected = tied[self._tts_round_robin % len(tied)]
            self._tts_round_robin += 1
        return selected

    def _tts_ready_sender_fingerprints(
        self, worker: str, destination: str
    ) -> dict[str, str]:
        del destination
        gate = self.runtime_readiness_gate
        store = getattr(gate, "store", None)
        normalized_worker = str(worker or "").strip().lower()
        if store is None:
            return {}
        worker_record = self.worker_registry.get(normalized_worker) if self.worker_registry else None
        if worker_record is None or not bool(worker_record.get("enabled", True)):
            return {}
        helper_cell = store.cell(normalized_worker, None, "tts_helper")
        if helper_cell is None or helper_cell.get("status") != "ready":
            return {}
        ready: dict[str, str] = {}
        for cell in store.snapshot().get("cells", []):
            if (
                cell.get("worker") != normalized_worker
                or cell.get("runtime") != "tts"
                or cell.get("status") != "ready"
            ):
                continue
            profile = str(cell.get("profile") or "").strip().lower()
            if not profile:
                continue
            ready[profile] = ""
        return dict(sorted(ready.items()))

    def _select_tts_sender_profile(
        self, worker: str, profiles: list[str]
    ) -> str:
        choices = sorted({str(profile).strip().lower() for profile in profiles if str(profile).strip()})
        if not choices:
            raise DomainError(
                "TTS_WORKER_UNAVAILABLE",
                "Worker TTS tidak melaporkan profil pengirim lokal yang tersedia.",
                status_code=503,
            )
        with self._tts_route_lock:
            index = self._tts_sender_round_robin.get(worker, 0) % len(choices)
            self._tts_sender_round_robin[worker] = index + 1
        return choices[index]

    def tts_worker_options(self, *, destination: str | None = None) -> list[dict[str, Any]]:
        del destination
        registry = self.worker_registry
        if registry is None:
            return []
        statuses = ("queued", "dispatched", "running", "paused")
        return sorted(
            [
                {
                    "name": str(name),
                    "enabled": True,
                    "queued_jobs": sum(
                        self.jobs.count(kind="tts", worker=name, status=status, archived=False)
                        for status in statuses
                    ),
                }
                for name in self._worker_names_for_mode()
                if (record := registry.get(name)) is not None
                and bool(record.get("enabled", True))
            ],
            key=lambda option: option["name"].lower(),
        )

    def tts_worker_statuses(self, *, destination: str | None = None) -> list[dict[str, Any]]:
        registry = self.worker_registry
        if registry is None:
            return []
        statuses = ("queued", "dispatched", "running", "paused")
        result: list[dict[str, Any]] = []
        target = str(destination or self._tdl_access_target("tts") or "").strip()
        gate_store = getattr(self.runtime_readiness_gate, "store", None)
        for name in self._worker_names_for_mode():
            record = registry.get(name)
            if record is None:
                continue
            ready_profiles = self._tts_ready_sender_fingerprints(
                name, target
            )
            enabled = bool(record.get("enabled", True))
            worker_status = gate_store.worker(name) if gate_store is not None else None
            helper_cell = (
                gate_store.cell(name, None, "tts_helper")
                if gate_store is not None
                else None
            )
            cells = [
                cell for cell in gate_store.snapshot().get("cells", [])
                if cell.get("worker") == name and cell.get("runtime") == "tts"
            ] if gate_store is not None else []
            destination_fingerprint = (
                self.tdl_access_store.destination_fingerprint(target)
                if target
                and callable(getattr(self.tdl_access_store, "destination_fingerprint", None))
                else ""
            )
            if not enabled:
                reason = "WORKER_DISABLED"
            elif not target:
                reason = "TTS_CHAT_UNAVAILABLE"
            elif worker_status is not None and worker_status.get("status") == "failed":
                reason = str(worker_status.get("reason_code") or "WORKER_UNAVAILABLE")
            elif helper_cell is None or helper_cell.get("status") != "ready":
                reason = str(
                    (helper_cell or {}).get("reason_code") or "TTS_HELPER_NOT_SCANNED"
                )
            elif ready_profiles:
                reason = "READY"
            elif not cells:
                reason = "RUNTIME_NOT_SCANNED"
            else:
                reason = next(
                    (str(cell.get("reason_code") or "RUNTIME_NOT_READY") for cell in cells
                     if cell.get("status") != "ready"),
                    "TTS_DESTINATION_CHANGED",
                )
            profile_rows = []
            for cell in cells:
                profile_name = str(cell.get("profile") or "")
                if not profile_name:
                    continue
                if not enabled:
                    profile_status = "disabled"
                    profile_reason = "worker_disabled"
                elif worker_status is not None and worker_status.get("status") == "failed":
                    profile_status = "offline"
                    profile_reason = str(worker_status.get("reason_code") or "worker_unavailable").lower()
                elif helper_cell is None or helper_cell.get("status") != "ready":
                    profile_status = "not_ready"
                    profile_reason = str(
                        (helper_cell or {}).get("reason_code") or "tts_helper_not_scanned"
                    ).lower()
                elif profile_name in ready_profiles:
                    profile_status = "ready"
                    profile_reason = ""
                elif cell.get("status") == "ready":
                    profile_status = "ready"
                    profile_reason = ""
                else:
                    profile_status = "not_ready"
                    profile_reason = str(cell.get("reason_code") or "runtime_not_ready").lower()
                profile_rows.append({
                    "profile": profile_name,
                    "status": profile_status,
                    "reason_code": profile_reason,
                })
            result.append({
                "name": name,
                "enabled": enabled,
                "queued_jobs": sum(
                    self.jobs.count(kind="tts", worker=name, status=status, archived=False)
                    for status in statuses
                ),
                "ready": bool(ready_profiles),
                "reason_code": reason.lower(),
                "verified_profiles": list(ready_profiles),
                "profiles": sorted(profile_rows, key=lambda item: item["profile"]),
                "helpers": [],
                "profile_session_ready": bool(ready_profiles),
            })
        return sorted(result, key=lambda option: option["name"].lower())

    def tts_worker_diagnostics(
        self, *, profile: str | None = None, worker: str | None = None,
        destination: str | None = None,
    ) -> list[dict[str, Any]]:
        registry = self.worker_registry
        checker = getattr(self.dispatcher, "capabilities", None)
        if registry is None or not callable(checker):
            return []
        candidates = self._worker_names_for_mode([worker] if worker else None)
        target_chat = str(destination or self._tdl_access_target("tts")).strip()
        statuses = ("queued", "dispatched", "running", "paused")
        result: list[dict[str, Any]] = []
        for name in candidates:
            record = registry.get(name)
            if record is None:
                continue
            enabled = bool(record.get("enabled", True))
            item: dict[str, Any] = {
                "name": str(name),
                "enabled": enabled,
                "ready": False,
                "capability_ready": False,
                "helpers_ready": False,
                "profile_session_ready": False,
                "reason_code": "worker_disabled" if not enabled else "capability_unavailable",
                "helpers": [],
                "queued_jobs": 0,
            }
            if not enabled:
                result.append(item)
                continue
            try:
                response = checker(name)
            except Exception as exc:
                status = getattr(exc, "status", None)
                item["reason_code"] = (
                    "worker_update_required" if status == 404 else "worker_unavailable"
                )
                result.append(item)
                continue
            capabilities = response.get("capabilities", []) if isinstance(response, dict) else []
            if isinstance(response, dict) and isinstance(response.get("tts"), bool):
                item["capability_ready"] = response["tts"]
            else:
                item["capability_ready"] = bool(
                    isinstance(capabilities, list) and CAP_TTS in capabilities
                )
            health = response.get("tts_health") if isinstance(response, dict) else None
            health = health if isinstance(health, dict) else {}
            helpers = health.get("helpers")
            allowed_statuses = {"ready", "bootstrapping", "tor_unreachable", "helper_unreachable"}
            safe_helpers = []
            for helper in helpers if isinstance(helpers, list) else []:
                if not isinstance(helper, dict):
                    continue
                slot = helper.get("slot")
                if isinstance(slot, bool) or not isinstance(slot, int) or slot < 1 or slot > 3:
                    continue
                status = str(helper.get("status") or "helper_unreachable")
                if status not in allowed_statuses:
                    status = "helper_unreachable"
                percent = helper.get("bootstrap_percent")
                if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
                    percent = None
                if status in {"tor_unreachable", "helper_unreachable"}:
                    percent = None
                safe_helpers.append({"slot": slot, "status": status, "bootstrap_percent": percent})
            safe_helpers.sort(key=lambda helper: helper["slot"])
            item["helpers"] = safe_helpers
            item["helpers_ready"] = bool(health.get("helpers_ready")) and len(safe_helpers) == 3 and all(
                helper["status"] == "ready" for helper in safe_helpers
            )
            advertised_profiles = response.get("export_profiles") if isinstance(response, dict) else None
            if not isinstance(advertised_profiles, list) and isinstance(response, dict):
                advertised_profiles = response.get("available_storage_profiles", response.get("profiles", []))
            advertised_set = {str(value).strip().lower() for value in advertised_profiles if str(value).strip()} if isinstance(advertised_profiles, list) else set()
            verified_profiles = self._tdl_access_candidates(str(name), "tts", target_chat)
            # TTS sender eligibility is destination-specific and may use any
            # verified local profile; actor profile is only ownership.
            verified_profiles = [value for value in verified_profiles if value in advertised_set]
            advertised_profile = bool(verified_profiles)
            item["profile_session_ready"] = advertised_profile
            item["verified_profiles"] = verified_profiles
            if not item["helpers_ready"]:
                item["reason_code"] = "helpers_not_ready"
            elif not item["capability_ready"]:
                item["reason_code"] = "tts_capability_missing"
            elif not advertised_profile:
                item["reason_code"] = "tdl_access_unverified"
            else:
                item["ready"] = True
                item["reason_code"] = "ready"
            item["queued_jobs"] = sum(
                self.jobs.count(kind="tts", worker=name, status=status, archived=False)
                for status in statuses
            )
            result.append(item)
        return sorted(result, key=lambda option: option["name"].lower())

    def _select_safelink_worker(self, requested: str | None = None) -> str:
        registry = self.worker_registry
        if registry is None:
            raise DomainError(
                "SAFELINK_WORKER_UNAVAILABLE",
                "Belum ada worker yang dapat menjalankan resolver. Jalankan Scan Profil.",
                status_code=503,
            )
        if requested:
            selected = str(requested).strip().lower()
            record = registry.get(selected)
            if record is None:
                raise DomainError(
                    "WORKER_NOT_FOUND", "Worker resolver yang dipilih tidak ditemukan.", status_code=404
                )
            if not bool(record.get("enabled", True)):
                raise DomainError(
                    "WORKER_DISABLED",
                    f"Worker {selected} sedang dinonaktifkan dan tidak menerima job baru.",
                    status_code=409,
                    details={"worker": selected},
                )
            gate = self.runtime_readiness_gate
            require = getattr(gate, "require_resolver", None)
            if not callable(require):
                raise DomainError(
                    "RUNTIME_NOT_READY",
                    f"Runtime resolver pada worker {selected} belum dipindai. Jalankan Scan Profil.",
                    status_code=409,
                    details={"worker": selected, "profile": None, "runtime": "resolver", "reason_code": "RUNTIME_NOT_SCANNED"},
                )
            cell = require(selected)
            if cell.get("status") != "ready":
                reason_code = str(cell.get("reason_code") or "RUNTIME_NOT_SCANNED")
                raise DomainError(
                    "RUNTIME_NOT_READY",
                    f"Runtime resolver pada worker {selected} belum siap.",
                    status_code=409,
                    details={"worker": selected, "profile": None, "runtime": "resolver", "reason_code": reason_code},
                )
            return selected

        options = self.safelink_worker_options()
        ready = [item for item in options if item["enabled"] and item["status"] == "ready"]
        if not ready:
            raise DomainError(
                "SAFELINK_WORKER_UNAVAILABLE",
                "Belum ada worker resolver yang siap. Jalankan Scan Profil atau aktifkan worker.",
                status_code=503,
            )
        selected = min(ready, key=lambda item: (item["queued_jobs"], item["name"].lower()))["name"]
        gate = self.runtime_readiness_gate
        require = getattr(gate, "require_resolver", None)
        if not callable(require):
            raise DomainError(
                "RUNTIME_NOT_READY",
                f"Runtime resolver pada worker {selected} belum dipindai. Jalankan Scan Profil.",
                status_code=409,
                details={"worker": selected, "profile": None, "runtime": "resolver", "reason_code": "RUNTIME_NOT_SCANNED"},
            )
        cell = require(selected)
        if cell.get("status") != "ready":
            reason_code = str(cell.get("reason_code") or "RUNTIME_NOT_SCANNED")
            raise DomainError(
                "RUNTIME_NOT_READY",
                f"Runtime resolver pada worker {selected} belum siap.",
                status_code=409,
                details={"worker": selected, "profile": None, "runtime": "resolver", "reason_code": reason_code},
            )
        return selected

    def safelink_worker_options(self) -> list[dict[str, Any]]:
        registry = self.worker_registry
        if registry is None:
            return []
        names = self._worker_names_for_mode()
        statuses = ("queued", "dispatched", "running", "paused")
        result: list[dict[str, Any]] = []
        gate_store = getattr(self.runtime_readiness_gate, "store", None)
        for name in names:
            record = registry.get(name)
            if record is None:
                continue
            enabled = bool(record.get("enabled", True))
            worker_state = gate_store.worker(name) if callable(getattr(gate_store, "worker", None)) else None
            cell = gate_store.cell(name, None, "resolver") if callable(getattr(gate_store, "cell", None)) else None
            if not enabled:
                readiness_status, reason = "disabled", "WORKER_DISABLED"
            elif worker_state is not None and worker_state.get("status") == "failed":
                readiness_status, reason = "offline", str(worker_state.get("reason_code") or "WORKER_UNAVAILABLE")
            elif worker_state is None or cell is None:
                readiness_status, reason = "unscanned", "RUNTIME_NOT_SCANNED"
            elif cell.get("status") == "ready" and cell.get("fingerprint"):
                readiness_status, reason = "ready", ""
            else:
                readiness_status, reason = "not_ready", str(cell.get("reason_code") or "RUNTIME_NOT_READY")
            queued_jobs = sum(
                self.jobs.count(
                    kind="safelink_resolve", worker=name, status=status, archived=False
                )
                for status in statuses
            )
            result.append({
                "name": str(name),
                "enabled": enabled,
                "status": readiness_status,
                "reason_code": reason,
                "queued_jobs": queued_jobs,
            })
        return sorted(result, key=lambda option: option["name"].lower())

    def _dispatch_admitted_job(self, job: Job, command: dict[str, Any]) -> None:
        sequence = job.progress_sequence + 1
        if job.kind == "storage_upload":
            self._dispatch_storage_upload_command(job, command, sequence)
            return
        command["event_sequence_start"] = sequence
        command["payload"] = self._worker_payload(
            job.id, job.kind, command.get("payload") or {}
        )
        dispatched = JobEvent(
            job_id=job.id,
            sequence=sequence,
            status=JobStatus.DISPATCHED,
            event_type="dispatched",
            progress={"worker": job.worker, "position": 1},
        )
        admitted = self.append_worker_event(dispatched)
        if admitted.status != JobStatus.DISPATCHED:
            # A queued cancellation can win immediately before this status
            # transition. Do not send a command after the job became terminal.
            self.jobs.release_execution(job.id)
            return
        self.dispatcher.dispatch(job.worker, command)

    def _dispatch_storage_upload_command(
        self, job: Job, command: dict[str, Any], sequence: int
    ) -> None:
        """Use the durable worker command path required for parallel Storage lanes."""
        dispatch_command = getattr(self.dispatcher, "dispatch_command", None)
        if not callable(dispatch_command):
            raise DomainError(
                "WORKER_INCOMPATIBLE",
                "Worker dispatcher belum mendukung command durable untuk Storage.",
                status_code=409,
            )

        stored_payload = self.jobs.command_payload(job.id)
        if not isinstance(stored_payload, dict):
            raise DomainError(
                "JOB_COMMAND_UNAVAILABLE",
                "Payload internal upload Storage tidak tersedia.",
                status_code=500,
            )
        dispatch_data = stored_payload.get(_STORAGE_DURABLE_DISPATCH_KEY)
        dispatch_data = dispatch_data if isinstance(dispatch_data, dict) else {}
        command_id = str(dispatch_data.get("command_id") or "").strip()
        dispatch_token = str(dispatch_data.get("dispatch_token") or "").strip()
        if not command_id or not dispatch_token:
            dispatch_data = {
                "command_id": str(uuid.uuid4()),
                "dispatch_token": secrets.token_urlsafe(32),
                "attempt": max(1, int(command.get("attempt") or 1)),
                "dispatch_started": False,
            }
            stored_payload = {
                **stored_payload,
                _STORAGE_DURABLE_DISPATCH_KEY: dispatch_data,
            }
            update_payload = getattr(self.jobs, "update_command_payload", None)
            if not callable(update_payload):
                raise DomainError(
                    "JOB_COMMAND_UNAVAILABLE",
                    "Worker tidak dapat menyimpan identitas command upload Storage.",
                    status_code=500,
                )
            update_payload(job.id, stored_payload)
            command_id = dispatch_data["command_id"]
            dispatch_token = dispatch_data["dispatch_token"]

        begin_dispatch = getattr(
            self.jobs, "begin_queued_worker_dispatch", None
        )
        if callable(begin_dispatch):
            dispatch_state = begin_dispatch(
                job.id,
                attempt=max(1, int(command.get("attempt") or 1)),
                command_id=command_id,
            )
            if dispatch_state == "cancel_requested":
                self._cancel_queued_before_dispatch(
                    job.id,
                    event_type="cancelled_queued",
                    message="Job queued dibatalkan sebelum dikirim ke worker.",
                )
                self.jobs.release_execution(job.id)
                return
            if dispatch_state != "started":
                current = self.jobs.get(job.id)
                if current is not None and current.status in {
                    JobStatus.DISPATCHED, JobStatus.RUNNING, JobStatus.PAUSED
                }:
                    return
                if current is not None and current.status.terminal:
                    return
                if dispatch_state in {
                    "stale_attempt", "stale_command", "operation_cancelling_dispatched"
                }:
                    return
                self.jobs.release_execution(job.id)
                return

        internal_payload = {
            key: value
            for key, value in stored_payload.items()
            if key != _STORAGE_DURABLE_DISPATCH_KEY
        }
        execution_profile = str(
            internal_payload.get("_tdl_sender_profile")
            or command.get("profile")
            or job.profile
        )
        envelope = {
            "command_id": command_id,
            "job_id": job.id,
            "attempt": max(1, int(command.get("attempt") or 1)),
            "dispatch_token": dispatch_token,
            "profile_revision": 0,
            "settings_version": int(job.settings_version or 0),
            "event_sequence_start": sequence,
            "execution_plan": self.jobs.execution_plan(job.id)
            or command.get("execution")
            or {},
            "job": {
                "kind": job.kind,
                "profile": execution_profile,
                "actor_user_id": int(job.actor_user_id),
                "worker": job.worker,
                "payload": self._worker_payload(
                    job.id, job.kind, internal_payload
                ),
            },
        }
        receipt = dispatch_command(job.worker, envelope)
        if not isinstance(receipt, dict) or receipt.get("accepted") is not True:
            raise RuntimeError("Worker belum mengonfirmasi command upload Storage.")
        latest_payload = self.jobs.command_payload(job.id)
        latest_payload = latest_payload if isinstance(latest_payload, dict) else {}
        latest_dispatch = latest_payload.get(_STORAGE_DURABLE_DISPATCH_KEY)
        latest_dispatch = latest_dispatch if isinstance(latest_dispatch, dict) else {}
        cancel_attempt = int(latest_dispatch.get("cancel_after_dispatch_attempt") or 1)
        if (
            latest_dispatch.get("cancel_after_dispatch")
            and not latest_dispatch.get("cancel_after_dispatch_accepted")
        ):
            if self._cancel_worker_attempt(job, attempt=cancel_attempt):
                self.jobs.acknowledge_dispatch_cancellation(job.id, cancel_attempt)
        self.append_worker_event(JobEvent(
            job_id=job.id,
            sequence=sequence,
            status=JobStatus.DISPATCHED,
            event_type="durable_dispatch_accepted",
            progress={"worker": job.worker, "position": 1},
        ))

    def _worker_payload(
        self, job_id: str, kind: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if kind == "backup_verify":
            password = self.private_job_value(job_id, "backup_archive_password")
            return {**payload, **({"password": password} if password else {})}
        if kind == "storage_reconcile" and str(
            payload.get("_storage_reconcile_provider") or "telegram"
        ).strip().lower() == "rclone":
            return payload
        if kind in {"tts", "storage_upload", "storage_reconcile"}:
            if kind == "storage_upload":
                payload = {
                    key: value
                    for key, value in payload.items()
                    if key != _STORAGE_DURABLE_DISPATCH_KEY
                }
            key = "telegram_tts_chat_id" if kind == "tts" else "tdl_storage_chat_ref"
            target = self.private_job_value(job_id, key)
            result = {**payload, **({"tdl_access_target": target} if target else {})}
            return result
        if kind == "storage_sync":
            target = self.private_job_value(job_id, "tdl_storage_chat_ref")
            return {
                **payload,
                **({"tdl_access_target": target} if target else {}),
            }
        if kind == "storage_download":
            target = self.private_job_value(job_id, "tdl_storage_chat_ref")
            return {
                **payload,
                **({"tdl_access_target": target} if target else {}),
            }
        if kind != "export":
            return payload
        result = dict(payload)
        if bool(payload.get("quick_mode")):
            target = self.private_job_value(job_id, "tdl_storage_chat_ref")
            result.update(
                _quick_storage_tdl_access_target=target or "",
                _quick_storage_sender_profiles=list(
                    payload.get("_quick_storage_sender_profiles") or []
                ),
            )
        cursor_active = self._shared_export_cursor_enabled()
        if not cursor_active and self.export_cursor_service is not None:
            cursor_active = self.export_cursor_service.job_has_active_lease(job_id)
        if not cursor_active:
            return result
        return {**result, "_shared_export_cursor": True}

    def start_scheduler(self) -> None:
        """Resume queued commands after backend restart or terminal events."""
        if self._scheduler_thread is not None:
            return
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="backend-job-dispatcher",
        )
        if self.gateway_mode == "lite":
            self._scheduler_wake.set()
        self._scheduler_thread.start()

    def stop_scheduler(self) -> None:
        self._scheduler_stop.set()
        self._scheduler_wake.set()

    def wake_scheduler(self) -> None:
        self._scheduler_wake.set()

    def _scheduler_loop(self) -> None:
        def recover_and_dispatch() -> None:
            try:
                self._recover_stale_jobs()
                self._retry_dispatch_cancel_requests()
                self._dispatch_pending_jobs()
            except Exception:
                # A later tick retries; one unavailable worker must not stop
                # admission for every other profile.
                import logging

                logging.getLogger(__name__).exception("Pending job dispatch failed")

        run_event_driven_loop(
            self._scheduler_stop,
            self._scheduler_wake,
            recovery_seconds=self.scheduler_recovery_seconds,
            callback=recover_and_dispatch,
        )

    def _stale_worker_responds(self, worker: str, *, now) -> bool | None:
        """Check a stale job's worker without treating event delay as process death.

        The normal path is a read from WorkerHealthMonitor's existing snapshot.
        A targeted health probe is only used when that snapshot cannot confirm
        the worker is responding, and is rate-limited per worker rather than per
        job. Only two failed probes confirm unavailability; stale jobs are never
        terminalized here because only a confirmed Docker stop proves that the
        worker process was interrupted.
        """
        name = str(worker or "").strip().lower()
        if not name:
            return None

        snapshotter = getattr(self.worker_health_cache, "snapshot", None)
        if callable(snapshotter):
            try:
                snapshot = snapshotter(name)
            except Exception:
                snapshot = None
            if isinstance(snapshot, dict):
                status = str(snapshot.get("status") or "").strip().lower()
                if status == "ready" and snapshot.get("healthy") is True:
                    return True

        cooldown_seconds = max(30.0, self.scheduler_recovery_seconds)
        with self._stale_job_lock:
            previous = self._stale_worker_probe_results.get(name)
            if previous is not None:
                checked_at, responds = previous
                if (now - checked_at).total_seconds() < cooldown_seconds:
                    return responds

        probe = getattr(self.worker_health_cache, "probe_worker", None)
        if callable(probe):
            try:
                result = probe(name)
            except Exception:
                result = None
            if isinstance(result, dict):
                if result.get("status") == "ready" and result.get("healthy") is True:
                    responds: bool | None = True
                elif (
                    result.get("status") == "offline"
                    and result.get("restart_probe_confirmed") is True
                ):
                    responds = False
                else:
                    responds = None
                with self._stale_job_lock:
                    self._stale_worker_probe_results[name] = (now, responds)
                return responds

        checker = getattr(self.dispatcher, "check_worker_fast", None)
        if not callable(checker):
            return None
        result = probe_worker_health(checker, name)
        if result.get("status") == "ready" and result.get("healthy") is True:
            responds: bool | None = True
        elif (
            result.get("status") == "offline"
            and result.get("restart_probe_confirmed") is True
        ):
            responds = False
        else:
            responds = None
        with self._stale_job_lock:
            self._stale_worker_probe_results[name] = (now, responds)
        return responds

    def _recover_stale_jobs(self, *, now=None) -> None:
        """Keep stale jobs active until worker stop is confirmed by its supervisor.

        Event delivery latency is telemetry, not proof that the worker stopped
        responding. A stale progress timestamp may update worker reachability,
        but it never cancels a job or releases its resource lease. The explicit
        restart flow terminalizes jobs only after Docker confirms the container
        stopped.
        """
        current_time = now or utc_now()
        active_statuses = (JobStatus.DISPATCHED.value, JobStatus.RUNNING.value)
        active_ids: set[str] = set()
        forced = False
        worker_probe_results: dict[str, bool | None] = {}
        for status in active_statuses:
            for job in self.jobs.list(
                status=status,
                archived=False,
                offset=0,
                limit=1000,
            ):
                active_ids.add(job.id)
                latest = self.jobs.get(job.id)
                if latest is None or latest.status.terminal:
                    continue
                latency_ms = self._job_event_latency_ms(latest)
                with self._stale_job_lock:
                    high_latency_request = self._high_latency_cancel_attempts.get(
                        latest.id
                    )
                if high_latency_request is None:
                    high_latency_request = self._persisted_high_latency_cancel_request(
                        latest
                    )
                    if high_latency_request is not None:
                        with self._stale_job_lock:
                            self._high_latency_cancel_attempts.setdefault(
                                latest.id, high_latency_request
                            )
                            high_latency_request = self._high_latency_cancel_attempts[
                                latest.id
                            ]

                # This marker is now written only for an explicit operator
                # Stop. Untagged legacy telemetry-triggered markers are ignored.
                if high_latency_request is not None:
                    signal_status = str(
                        high_latency_request.get("signal_status") or "pending"
                    )
                    if signal_status == "accepted":
                        if self._cancel_request_grace_expired(
                            high_latency_request, current_time
                        ):
                            latest = self._force_cancel_unresponsive_job(
                                latest,
                                latency_ms=float(
                                    high_latency_request.get("latency_ms")
                                    or latency_ms
                                    or _WORKER_UNRESPONSIVE_EVENT_LATENCY_MS
                                ),
                                signal_status="accepted_no_terminal_event",
                            )
                            forced = forced or latest.status == JobStatus.CANCELLED
                    elif not high_latency_request.get("in_flight"):
                        latest = self._cancel_high_latency_job(
                            latest,
                            float(
                                high_latency_request.get("latency_ms")
                                or latency_ms
                                or _WORKER_UNRESPONSIVE_EVENT_LATENCY_MS
                            ),
                        )
                        forced = forced or latest.status == JobStatus.CANCELLED
                        with self._stale_job_lock:
                            refreshed_request = self._high_latency_cancel_attempts.get(
                                latest.id
                            )
                        if (
                            latest.status in {JobStatus.DISPATCHED, JobStatus.RUNNING}
                            and refreshed_request is not None
                            and refreshed_request.get("signal_status") == "accepted"
                            and self._cancel_request_grace_expired(
                                refreshed_request, current_time
                            )
                        ):
                            latest = self._force_cancel_unresponsive_job(
                                latest,
                                latency_ms=float(
                                    refreshed_request.get("latency_ms")
                                    or _WORKER_UNRESPONSIVE_EVENT_LATENCY_MS
                                ),
                                signal_status="accepted_no_terminal_event",
                            )
                            forced = forced or latest.status == JobStatus.CANCELLED
                    continue
                if self.job_stall_timeout_seconds <= 0:
                    continue
                with self._stale_job_lock:
                    latest = self.jobs.get(job.id)
                    if latest is None or latest.status.terminal:
                        self._stale_cancel_requested.pop(job.id, None)
                        continue
                    updated_at = latest.updated_at or latest.created_at
                    age = (current_time - updated_at).total_seconds()
                    if age <= self.job_stall_timeout_seconds:
                        self._stale_cancel_requested.pop(job.id, None)
                        continue
                worker = str(latest.worker or "").strip().lower()
                if worker not in worker_probe_results:
                    worker_probe_results[worker] = self._stale_worker_responds(
                        worker, now=current_time
                    )
                if worker_probe_results[worker] is not False:
                    # A responsive worker may be running a slow command or
                    # delivering telemetry late. An inconclusive probe also
                    # cannot prove that the process stopped.
                    self._stale_cancel_requested.pop(job.id, None)
                    continue
                # Preserve the job and its lease until Docker stop is confirmed.
                # This prevents a temporary health/API failure from making a
                # still-running process look cancelled to the rest of the app.
                with self._stale_job_lock:
                    self._unresponsive_workers[worker] = "stale_worker_probe_unavailable"
                    self._stale_cancel_requested.pop(job.id, None)

        with self._stale_job_lock:
            for job_id in tuple(self._stale_cancel_requested):
                if job_id not in active_ids:
                    self._stale_cancel_requested.pop(job_id, None)
        if forced:
            self._dispatch_pending_jobs()

    def _fail_stale_job(
        self,
        job: Job,
        age_seconds: float | None = None,
        request_state: Any = None,
        *,
        requested_at: Any = None,
        now=None,
    ) -> bool:
        current_time = now or utc_now()
        expected_request = requested_at if requested_at is not None else request_state
        with self._stale_job_lock:
            current = self.jobs.get(job.id)
            if current is None or current.status.terminal:
                if self._stale_cancel_requested.get(job.id) is expected_request:
                    self._stale_cancel_requested.pop(job.id, None)
                return False
            active_request = self._stale_cancel_requested.get(job.id)
            if expected_request is not None and active_request is not expected_request:
                return False

            updated_at = current.updated_at or current.created_at
            current_age = (current_time - updated_at).total_seconds()
            if current_age <= self.job_stall_timeout_seconds:
                self._stale_cancel_requested.pop(job.id, None)
                return False
            requested_time = (
                active_request.get("at")
                if isinstance(active_request, dict)
                else active_request
            )
            if requested_time is None:
                return False
            grace_age = (current_time - requested_time).total_seconds()
            if grace_age < self.job_cancel_grace_seconds:
                return False

            final_age = current_age if age_seconds is None else max(current_age, age_seconds)
            sequence = max(
                current.progress_sequence,
                max((item.sequence for item in self.jobs.events(job.id)), default=0),
            ) + 1
            phase = str(current.progress.get("phase") or "unknown")
            signal_status = (
                str(active_request.get("signal_status") or "not_confirmed")
                if isinstance(active_request, dict)
                else "not_confirmed"
            )
            failed = self.append_worker_event(
                JobEvent(
                    job_id=job.id,
                    sequence=sequence,
                    status=JobStatus.FAILED,
                    event_type="backend_stall_unconfirmed",
                    progress={
                        "phase": phase,
                        "terminal_phase": "failed",
                        "finished_at": current_time.isoformat(),
                        "stale_seconds": round(final_age, 1),
                        "worker_confirmation": "not_received",
                        "worker_cancel_signal": signal_status,
                        "outcome_uncertain": True,
                        "reconciliation_required": True,
                    },
                    error={
                        "code": "JOB_STALLED",
                        "message": (
                            "Worker tidak memberi konfirmasi berhenti setelah "
                            f"{round(final_age)} detik tanpa progress. Status ditandai gagal, "
                            "tetapi efek eksternal belum dapat dipastikan; periksa sebelum retry."
                        ),
                    },
                ),
                dispatch_pending=False,
            )
            # The event lifecycle updates linked operations and releases backend
            # admission. The caller dispatches queued work after the stale-job pass.
            return bool(
                failed.status == JobStatus.FAILED
                and failed.error.get("code") == "JOB_STALLED"
            )

    def _dispatch_pending_jobs(self, profile: str | None = None) -> None:
        # Always inspect the global FIFO. Releasing a slot or lease for one
        # profile may make a job from another profile eligible on that worker.
        del profile
        profiles: list[str | None] = [None]
        for selected in profiles:
            queued_lister = getattr(self.jobs, "list_queued_for_scheduler", None)
            queued_jobs = (
                queued_lister(profile=selected, limit=5000)
                if callable(queued_lister)
                else self.jobs.list(
                    profile=selected,
                    status=JobStatus.QUEUED.value,
                    archived=False,
                    offset=0,
                    limit=200,
                )
            )
            worker_availability: dict[str, str | None] = {}
            for queued in queued_jobs:
                worker_name = str(queued.worker or "").strip().lower()
                if worker_name not in worker_availability:
                    worker_availability[worker_name] = self._worker_unresponsive_reason(
                        worker_name
                    )
                if worker_availability[worker_name]:
                    continue
                command_payload = self.jobs.command_payload(queued.id)
                if (
                    isinstance(command_payload, dict)
                    and command_payload.get("dispatch_mode") == "durable"
                ):
                    # Durable operation jobs are admitted only by their RQ
                    # advance command. The legacy scheduler must not claim
                    # the same queued row or send a v1 dispatch in parallel.
                    continue
                if queued.kind == "export" and self._shared_export_cursor_enabled():
                    try:
                        self._require_shared_export_cursor_worker(queued.worker)
                    except DomainError:
                        # Keep incompatible/offline workers queued. The gate
                        # must never silently fall back to worker-local state.
                        continue
                admission = self.jobs.try_acquire_execution(queued.id)
                current = self.jobs.get(queued.id)
                sequence_cursor = (
                    current.progress_sequence if current is not None
                    else queued.progress_sequence
                )
                if current is not None and current.status == JobStatus.QUEUED:
                    self.jobs.set_queue_info(
                        queued.id,
                        int(admission.get("position", 1)),
                        admission.get("blocked_reason"),
                    )
                if not admission.get("admitted"):
                    continue
                if not isinstance(command_payload, dict):
                    sequence = sequence_cursor + 1
                    self.append_worker_event(
                        JobEvent(
                            job_id=queued.id,
                            sequence=sequence,
                            status=JobStatus.FAILED,
                            event_type="dispatch_failed",
                            error={
                                "code": "LEGACY_COMMAND_UNAVAILABLE",
                                "message": "Payload internal job lama tidak tersedia setelah migrasi scheduler.",
                            },
                        ),
                        dispatch_pending=False,
                    )
                    continue
                command = {
                    "job_id": queued.id,
                    "attempt": 1 + sum(
                        1
                        for event in self.jobs.events(queued.id)
                        if event.event_type == "retry_started"
                    ),
                    "kind": queued.kind,
                    "profile": queued.profile,
                    "worker": queued.worker,
                    "actor_user_id": queued.actor_user_id,
                    "execution": self.jobs.execution_plan(queued.id) or {},
                    "payload": command_payload,
                }
                try:
                    pause_kind = str(queued.progress.get("pause_kind") or "")
                    resumed = False
                    resume_sequence = sequence_cursor + 1
                    if pause_kind == "worker":
                        resume = getattr(self.dispatcher, "resume", None)
                        if callable(resume):
                            sequence = sequence_cursor + 1
                            resuming_job = self.append_worker_event(
                                JobEvent(
                                    job_id=queued.id,
                                    sequence=sequence,
                                    status=JobStatus.DISPATCHED,
                                    event_type="resuming",
                                    progress={"worker": queued.worker, "position": 1},
                                ),
                                dispatch_pending=False,
                            )
                            resume_sequence = resuming_job.progress_sequence + 1
                            command["event_sequence_start"] = resume_sequence
                            resumed = bool(
                                resume(queued.worker, queued.id, resume_sequence)
                            )
                    if resumed:
                        continue
                    else:
                        payload = command.get("payload")
                        if isinstance(payload, dict) and bool(payload.get("quick_mode")):
                            retry = payload.get("quick_retry")
                            retry = dict(retry) if isinstance(retry, dict) else {}
                            retry["stage_job_id"] = str(retry.get("stage_job_id") or queued.id)
                            retry["resume_phase"] = "auto"
                            payload["quick_retry"] = retry
                            self.jobs.update_command_payload(queued.id, payload)
                        if pause_kind == "worker":
                            command["event_sequence_start"] = resume_sequence
                            command["payload"] = self._worker_payload(
                                queued.id, queued.kind, command.get("payload") or {}
                            )
                            self.dispatcher.dispatch(queued.worker, command)
                        else:
                            self._dispatch_admitted_job(current or queued, command)
                except Exception as exc:
                    failure = self._worker_dispatch_error(queued.worker, exc)
                    current = self.jobs.get(queued.id)
                    sequence = (
                        current.progress_sequence if current is not None
                        else sequence_cursor
                    ) + 1
                    self.append_worker_event(
                        JobEvent(
                            job_id=queued.id,
                            sequence=sequence,
                            status=JobStatus.FAILED,
                            event_type="dispatch_failed",
                            error={"code": failure.code, "message": failure.message},
                        ),
                        dispatch_pending=False,
                    )

    def append_worker_event(
        self, event: JobEvent, *, dispatch_pending: bool = True
    ) -> Job:
        current = self.jobs.get(event.job_id)
        if current is None:
            raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
        if current.status.terminal:
            if (
                current.error
                and current.error.get("code") in {
                    "JOB_STALLED",
                    "WORKER_UNRESPONSIVE",
                }
            ):
                # Keep the uncertain backend terminal state, but retain late physical
                # outcomes and replay their idempotent catalog effects. This
                # handles worker outbox retries after an API outage/crash.
                worker_event = event
                late_record = {
                    "sequence": int(worker_event.sequence),
                    "status": worker_event.status.value,
                    "event_type": str(worker_event.event_type),
                    "result": _redact_secrets(worker_event.result),
                    "error": _redact_secrets(worker_event.error),
                }
                recorder = getattr(self.jobs, "record_late_worker_event", None)
                accepted = False
                late_job = current
                if callable(recorder):
                    late_job, accepted = recorder(worker_event.job_id, late_record)
                else:
                    existing_result = current.result if isinstance(current.result, dict) else {}
                    late_events = list(existing_result.get("late_worker_events") or [])
                    match = next(
                        (
                            item for item in late_events
                            if isinstance(item, dict)
                            and item.get("sequence") == worker_event.sequence
                            and item.get("event_type") == worker_event.event_type
                        ),
                        None,
                    )
                    accepted = match is None or all(
                        match.get(key) == late_record.get(key)
                        for key in ("sequence", "status", "event_type", "result", "error")
                    )
                    if match is None:
                        received_at = utc_now().isoformat()
                        late_events.append({**late_record, "received_at": received_at})
                        next_result = {
                            **existing_result,
                            "late_worker_events": late_events[-256:],
                        }
                        if worker_event.status.terminal:
                            next_result["late_worker_terminal"] = late_events[-1]
                        self.jobs.update_result(worker_event.job_id, next_result)
                        late_job = self.jobs.get(worker_event.job_id) or current
                if accepted:
                    applied_event = worker_event
                    if (
                        late_job.kind == "storage_sync"
                        and worker_event.status == JobStatus.SUCCEEDED
                        and worker_event.event_type == "completed"
                    ):
                        applied_event = self._apply_storage_sync_completion(
                            late_job, worker_event
                        )
                    self._apply_event_side_effects(late_job, applied_event)
                    # Late physical outcomes remain useful for readiness and
                    # operation observers, even though JOB_STALLED remains the
                    # public terminal state. Observers are required to be
                    # idempotent because outbox retries can replay this event.
                    for observer in tuple(self._event_observers):
                        observer(applied_event)
                    if applied_event is not worker_event:
                        latest = self.jobs.get(worker_event.job_id) or late_job
                        latest_result = (
                            dict(latest.result)
                            if isinstance(latest.result, dict)
                            else {}
                        )
                        latest_result["late_worker_reconciliation"] = {
                            "sequence": int(worker_event.sequence),
                            "event_type": str(worker_event.event_type),
                            "status": applied_event.status.value,
                            "result": _redact_secrets(applied_event.result),
                            "error": _redact_secrets(applied_event.error),
                        }
                        self.jobs.update_result(worker_event.job_id, latest_result)
                if worker_event.status.terminal:
                    # A late terminal confirms the physical process stopped;
                    # the backend's uncertain terminal record remains authoritative.
                    self.jobs.release_execution(event.job_id)
                    if current.error.get("code") == "WORKER_UNRESPONSIVE":
                        self._refresh_worker_unresponsive_state(current.worker)
                return self.jobs.get(event.job_id) or current
            persisted = self._persisted_worker_event(current, event)
            if persisted is not None:
                self._replay_persisted_worker_event(current, persisted)
                return self.jobs.get(event.job_id) or current
            # A worker can finish an interrupt race after the backend already
            # forced a terminal state.  Do not turn that harmless late event
            # into an INTERNAL_ERROR or resurrect the lane.
            logging.getLogger(__name__).warning(
                "Ignoring late worker event %s for terminal job %s",
                event.event_type,
                event.job_id,
            )
            return current
        # Serialize persisted worker events with transient heartbeats and the
        # watchdog's final revalidation. This prevents a fresh event from
        # landing between the stale-age check and its terminal JOB_STALLED row.
        terminal_race = False
        stale_current: Job | None = None
        stale_persisted: JobEvent | None = None
        worker_terminal_after_stop: JobEvent | None = None
        with self._stale_job_lock:
            current = self.jobs.get(event.job_id)
            if current is None:
                raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
            if current.status.terminal:
                terminal_race = True
            elif event.sequence <= current.progress_sequence:
                # The cursor also covers progress snapshots that are not
                # retained in job_events, so old worker attempts stay stale.
                stale_current = current
                stale_persisted = self._persisted_worker_event(current, event)
            else:
                if (
                    current.kind == "storage_sync"
                    and event.status == JobStatus.SUCCEEDED
                    and event.event_type == "completed"
                ):
                    event = self._apply_storage_sync_completion(current, event)
                if (
                    event.status.terminal
                    and event.status != JobStatus.CANCELLED
                    and self._persisted_high_latency_cancel_request(current) is not None
                ):
                    worker_terminal_after_stop = event
                    event = self._cancelled_after_stop_event(event)
                event = self._with_observability(current, event)
                job, inserted = self.jobs.append_event(event)
                self._stale_cancel_requested.pop(event.job_id, None)
                if event.status.terminal or event.event_type == "retry_started":
                    self._high_latency_cancel_attempts.pop(event.job_id, None)
        if terminal_race:
            # Re-enter the terminal path to preserve late-event reconciliation.
            return self.append_worker_event(event, dispatch_pending=dispatch_pending)
        if stale_current is not None:
            if stale_persisted is not None:
                # The event row may have committed before the prior API call
                # crashed while applying its catalog/readiness side effect.
                self._replay_persisted_worker_event(stale_current, stale_persisted)
            return stale_current
        # Side effects are idempotent and intentionally replayed when a worker
        # retries an already persisted event after a transient API failure.
        self._apply_event_side_effects(
            job, worker_terminal_after_stop or event
        )
        if inserted:
            self.wake_scheduler()
        if event.status.terminal and self.export_cursor_service is not None:
            lease = self.export_cursor_service.lease_for_job(job.id)
            if lease is not None:
                worker_confirmed = not (
                    event.event_type.startswith("backend_")
                    or event.event_type.startswith("force_cancelled")
                    or event.event_type in {
                        "dispatch_failed",
                        "cancelled_queued",
                        "cancelled_paused_queue",
                        "operation_cancelled_queued",
                    }
                )
                self.export_cursor_service.finish_job(
                    job.id,
                    attempt=int(lease["lease_attempt"]),
                    worker_confirmed=worker_confirmed,
                    require_applied_completion=(
                        worker_terminal_after_stop.status
                        if worker_terminal_after_stop is not None
                        else event.status
                    ) == JobStatus.SUCCEEDED,
                )
        if inserted:
            if (
                event.event_type == "export.json_ready"
                and event.status in {JobStatus.RUNNING, JobStatus.DISPATCHED}
                and job.kind == "export"
                and bool(job.payload.get("quick_mode"))
            ):
                # The export TDL session is no longer needed after JSON has
                # been created.  Let the next Quick Mode begin exporting
                # while this job uses the separate download/session lanes.
                lease_held = bool(
                    self.export_cursor_service is not None
                    and self.export_cursor_service.job_has_active_lease(job.id)
                )
                cursor_required = self._shared_export_cursor_enabled() or lease_held
                cursor_committed = bool(
                    self.export_cursor_service is not None
                    and self.export_cursor_service.completion_applied(job.id)
                )
                if not cursor_required or cursor_committed:
                    self._release_quick_export_resources(job.id)
            if event.status.terminal:
                self.jobs.release_execution(job.id)
            for observer in tuple(self._event_observers):
                observer(event)
            if dispatch_pending and event.status.terminal:
                self._dispatch_pending_jobs()
            elif dispatch_pending and event.status == JobStatus.PAUSED:
                self._dispatch_pending_jobs()
        return job

    def _persisted_worker_event(
        self, job: Job, event: JobEvent
    ) -> JobEvent | None:
        for stored in self.jobs.events(job.id, after_sequence=event.sequence - 1):
            if stored.sequence != event.sequence:
                continue
            result_matches = _stored_worker_result_matches(
                stored.result, event.result
            )
            if (
                not result_matches
                and job.kind == "storage_sync"
                and event.event_type == "completed"
            ):
                result_matches = _storage_sync_terminal_result_matches(
                    stored.result, event.result
                )
            stored_progress = stored.progress if isinstance(stored.progress, dict) else {}
            cancelled_after_stop_matches = bool(
                stored.status == JobStatus.CANCELLED
                and stored.event_type == "cancelled_after_stop"
                and stored_progress.get("cancelled_after_stop") is True
                and stored_progress.get("worker_terminal_status") == event.status.value
                and stored_progress.get("worker_terminal_event_type") == event.event_type
                and stored_progress.get("worker_terminal_error")
                == _redact_secrets(event.error)
            )
            if (
                (
                    stored.status == event.status
                    and stored.event_type == event.event_type
                    and result_matches
                    and stored.error == event.error
                )
                or (cancelled_after_stop_matches and result_matches)
            ):
                return stored
            return None
        return None

    def _replay_persisted_worker_event(self, job: Job, event: JobEvent) -> None:
        """Repair idempotent post-commit effects for an exact worker retry."""
        worker_terminal = event
        progress = event.progress if isinstance(event.progress, dict) else {}
        if progress.get("cancelled_after_stop") is True:
            try:
                worker_status = JobStatus(str(progress.get("worker_terminal_status")))
            except (TypeError, ValueError):
                worker_status = JobStatus.CANCELLED
            worker_event_type = str(progress.get("worker_terminal_event_type") or "")
            if (
                worker_status.terminal
                and worker_status != JobStatus.CANCELLED
                and worker_event_type
            ):
                worker_terminal = replace(
                    event,
                    status=worker_status,
                    event_type=worker_event_type,
                    error=progress.get("worker_terminal_error"),
                )
        self._apply_event_side_effects(job, worker_terminal)
        if event.status.terminal and self.export_cursor_service is not None:
            lease = self.export_cursor_service.lease_for_job(job.id)
            if lease is not None:
                worker_confirmed = not (
                    worker_terminal.event_type.startswith("backend_")
                    or worker_terminal.event_type.startswith("force_cancelled")
                    or worker_terminal.event_type in {
                        "dispatch_failed",
                        "cancelled_queued",
                        "cancelled_paused_queue",
                        "operation_cancelled_queued",
                    }
                )
                self.export_cursor_service.finish_job(
                    job.id,
                    attempt=int(lease["lease_attempt"]),
                    worker_confirmed=worker_confirmed,
                    require_applied_completion=(
                        worker_terminal.status == JobStatus.SUCCEEDED
                    ),
                )
        if (
            event.event_type == "export.json_ready"
            and event.status in {JobStatus.RUNNING, JobStatus.DISPATCHED}
            and job.kind == "export"
            and bool(job.payload.get("quick_mode"))
        ):
            lease_held = bool(
                self.export_cursor_service is not None
                and self.export_cursor_service.job_has_active_lease(job.id)
            )
            cursor_required = self._shared_export_cursor_enabled() or lease_held
            cursor_committed = bool(
                self.export_cursor_service is not None
                and self.export_cursor_service.completion_applied(job.id)
            )
            if not cursor_required or cursor_committed:
                self._release_quick_export_resources(job.id)
        for observer in tuple(self._event_observers):
            observer(event)
        if event.status.terminal:
            self.jobs.release_execution(job.id)
            self._dispatch_pending_jobs()
        elif event.status == JobStatus.PAUSED:
            self._dispatch_pending_jobs()

    def _apply_storage_sync_completion(self, job: Job, event: JobEvent) -> JobEvent:
        """Apply channel facts and only delete rows confirmed missing by ID lookup."""
        if self.storage_catalog is None:
            return replace(
                event,
                status=JobStatus.FAILED,
                event_type="storage.sync_apply_failed",
                error={
                    "code": "STORAGE_SYNC_CATALOG_UNAVAILABLE",
                    "message": "Katalog Storage tidak tersedia untuk menerapkan hasil sinkronisasi.",
                },
            )
        try:
            terminal = event.result if isinstance(event.result, dict) else {}
            summary = terminal.get("value") if isinstance(terminal.get("value"), dict) else {}
            channel_id = int(summary.get("channel_id") or 0)
            if channel_id == 0 or channel_id != int(job.payload.get("channel_id") or 0):
                raise ValueError("STORAGE_SYNC_CHANNEL_MISMATCH")
            message_ids: list[int] = []
            items: list[dict[str, Any]] = []
            seen: set[int] = set()
            batches = [
                (stored.sequence, stored.result)
                for stored in self.jobs.events(job.id)
                if stored.event_type == "storage.sync_batch"
            ]
            late_event_reader = getattr(self.jobs, "late_worker_events", None)
            if callable(late_event_reader):
                late_events = late_event_reader(
                    job.id, event_type="storage.sync_batch"
                )
            else:
                late_events = (
                    job.result.get("late_worker_events", [])
                    if isinstance(job.result, dict)
                    else []
                )
            if isinstance(late_events, list):
                batches.extend(
                    (
                        int(item.get("sequence") or 0),
                        item.get("result"),
                    )
                    for item in late_events
                    if isinstance(item, dict)
                    and item.get("event_type") == "storage.sync_batch"
                )
            for _sequence, raw_batch_result in sorted(batches, key=lambda item: item[0]):
                batch_result = (
                    raw_batch_result if isinstance(raw_batch_result, dict) else {}
                )
                batch_channel = int(batch_result.get("channel_id") or 0)
                raw_ids = batch_result.get("message_ids")
                raw_items = batch_result.get("items")
                if batch_channel != channel_id or not isinstance(raw_ids, list) or not isinstance(raw_items, list):
                    raise ValueError("STORAGE_SYNC_BATCH_INVALID")
                batch_ids: set[int] = set()
                for raw_id in raw_ids:
                    if isinstance(raw_id, bool):
                        raise ValueError("STORAGE_SYNC_MESSAGE_ID_INVALID")
                    message_id = int(raw_id)
                    if message_id < 1 or message_id in seen:
                        raise ValueError("STORAGE_SYNC_MESSAGE_ID_INVALID")
                    seen.add(message_id)
                    batch_ids.add(message_id)
                    message_ids.append(message_id)
                for item in raw_items:
                    if not isinstance(item, dict):
                        raise ValueError("STORAGE_SYNC_ITEM_INVALID")
                    item_id = int(item.get("channel_message_id") or 0)
                    if item_id not in batch_ids:
                        raise ValueError("STORAGE_SYNC_ITEM_INVALID")
                    items.append(item)

            raw_confirmed_missing = summary.get("confirmed_missing_message_ids", [])
            raw_verification_failed = summary.get("verification_failed_message_ids", [])
            if (
                not isinstance(raw_confirmed_missing, list)
                or not isinstance(raw_verification_failed, list)
            ):
                raise ValueError("STORAGE_SYNC_CONFIRMATION_RESULT_INVALID")
            confirmed_missing: list[int] = []
            verification_failed: list[int] = []
            for raw_ids, normalized in (
                (raw_confirmed_missing, confirmed_missing),
                (raw_verification_failed, verification_failed),
            ):
                seen_ids: set[int] = set()
                for raw_id in raw_ids:
                    if isinstance(raw_id, bool):
                        raise ValueError("STORAGE_SYNC_CONFIRMATION_RESULT_INVALID")
                    message_id = int(raw_id)
                    if message_id < 1 or message_id in seen_ids or message_id in seen:
                        raise ValueError("STORAGE_SYNC_CONFIRMATION_RESULT_INVALID")
                    seen_ids.add(message_id)
                    normalized.append(message_id)
            if set(confirmed_missing).intersection(verification_failed):
                raise ValueError("STORAGE_SYNC_CONFIRMATION_RESULT_INVALID")

            stored_command = self.jobs.command_payload(job.id)
            if isinstance(stored_command, dict):
                nested_payload = stored_command.get("payload")
                stored_payload = nested_payload if isinstance(nested_payload, dict) else stored_command
            else:
                stored_payload = job.payload
            raw_candidates = stored_payload.get("_storage_sync_candidate_message_ids", [])
            if not isinstance(raw_candidates, list):
                raise ValueError("STORAGE_SYNC_CANDIDATES_INVALID")
            candidate_ids: set[int] = set()
            for raw_id in raw_candidates:
                if isinstance(raw_id, bool):
                    raise ValueError("STORAGE_SYNC_CANDIDATES_INVALID")
                message_id = int(raw_id)
                if message_id < 1 or message_id in candidate_ids:
                    raise ValueError("STORAGE_SYNC_CANDIDATES_INVALID")
                candidate_ids.add(message_id)
            if (
                not set(confirmed_missing).issubset(candidate_ids)
                or not set(verification_failed).issubset(candidate_ids)
            ):
                raise ValueError("STORAGE_SYNC_CONFIRMATION_OUTSIDE_SNAPSHOT")

            coverage = summary.get("history_coverage")
            catalog_result = self.storage_catalog.apply_channel_sync(
                job_id=job.id,
                channel_id=channel_id,
                message_ids=message_ids,
                items=items,
                confirmed_missing_message_ids=confirmed_missing,
                actor_user_id=job.actor_user_id,
                profile=job.profile,
                history_coverage=coverage if isinstance(coverage, dict) else None,
                reported_history_complete=summary.get("history_complete"),
                reported_message_count=summary.get("messages_scanned"),
                batch_count=len(batches),
                reported_batch_count=summary.get("batch_count"),
            )
            return replace(
                event,
                result={
                    "value": {
                        **{
                            key: value
                            for key, value in summary.items()
                            if key not in {
                                "confirmed_missing_message_ids",
                                "verification_failed_message_ids",
                            }
                        },
                        "confirmed_missing_count": len(confirmed_missing),
                        "verification_failed_count": len(verification_failed),
                        "history_complete": bool(catalog_result["history_complete"]),
                        "catalog": catalog_result,
                    }
                },
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Could not apply Storage sync result for job %s", job.id
            )
            return replace(
                event,
                status=JobStatus.FAILED,
                event_type="storage.sync_apply_failed",
                error={
                    "code": "STORAGE_SYNC_APPLY_FAILED",
                    "message": "Hasil ekspor tidak valid; katalog tidak diubah.",
                },
            )

    def _shared_export_cursor_enabled(self) -> bool:
        return bool(
            self.export_cursor_service is not None
            and self.export_cursor_service.enabled
        )

    def _require_shared_export_cursor_worker(self, worker: str) -> None:
        get_capabilities = getattr(self.dispatcher, "capabilities", None)
        if not callable(get_capabilities):
            raise DomainError(
                "WORKER_INCOMPATIBLE",
                "Worker belum dapat diverifikasi untuk shared export cursor.",
                status_code=409,
                details={"worker": worker, "missing_capabilities": [CAP_SHARED_EXPORT_CURSOR]},
            )
        try:
            require_worker_contract(
                get_capabilities(worker),
                worker,
                required_capabilities={CAP_SHARED_EXPORT_CURSOR},
            )
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError(
                "WORKER_OFFLINE",
                f"Worker {worker} belum dapat diverifikasi untuk export.",
                status_code=503,
            ) from exc

    def _plan_payload_with_verified_peer(
        self, profile: str, kind: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if kind != "export" or not self._shared_export_cursor_enabled():
            return payload
        requested_ref = str(payload.get("chat_ref") or "").strip()
        if not requested_ref and payload.get("url"):
            config = getattr(self.profile_manager, "base_config", None)
            host = str(getattr(config, "tme3_host", "") or "").strip()
            if host:
                try:
                    requested_ref = parse_tme3_url(str(payload["url"]), host).chat_ref
                except ValueError:
                    requested_ref = ""
        if not requested_ref:
            return payload
        identity = self.export_cursor_service.alias_identity(profile, requested_ref)
        if not identity:
            return payload
        return {**payload, "_verified_export_peer": identity}

    def _release_quick_export_resources(self, job_id: str) -> bool:
        plan = self.jobs.execution_plan(job_id) or {}
        current_keys = set(plan.get("resource_keys") or [])
        export_keys = {
            key
            for key in current_keys
            if ":kind:export" in str(key) or ":tdl:export" in str(key)
        }
        if not export_keys:
            return False
        replacer = getattr(self.jobs, "replace_execution_resources", None)
        if callable(replacer) and replacer(job_id, current_keys - export_keys):
            self._dispatch_pending_jobs()
            return True
        return False

    def on_export_cursor_committed(self, job_id: str) -> bool:
        """Release only the Quick Mode export phase after durable completion."""
        job = self.jobs.get(str(job_id))
        if (
            job is None
            or job.kind != "export"
            or not bool(job.payload.get("quick_mode"))
            or job.status.terminal
        ):
            return False
        cursor_required = self._shared_export_cursor_enabled() or bool(
            self.export_cursor_service.job_has_active_lease(job.id)
        )
        if cursor_required and not self.export_cursor_service.completion_applied(job.id):
            return False
        return self._release_quick_export_resources(job.id)

    def update_worker_progress(self, event: JobEvent) -> Job:
        """Update the latest telemetry without growing persistent event history."""
        job, _ = self.update_worker_progress_result(event)
        return job

    def update_worker_progress_result(self, event: JobEvent) -> tuple[Job, bool]:
        """Return whether a transient worker snapshot advanced the job."""
        with self._stale_job_lock:
            current = self.jobs.get(event.job_id)
            if current is None:
                raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
            if not current.status.terminal:
                event = self._with_observability(current, event)
            job, updated = self.jobs.update_progress_snapshot(event)
            if updated:
                # Serialize heartbeat advancement and watchdog finalization so
                # a fresh snapshot cannot land between the watchdog's final
                # age check and its terminal event.
                self._stale_cancel_requested.pop(event.job_id, None)
        if not updated or job.status.terminal:
            return job, updated
        return job, updated

    def _next_job_event_sequence(self, job_id: str, *, fallback: Job | None = None) -> int:
        current = self.jobs.get(job_id) or fallback
        cursor = current.progress_sequence if current is not None else 0
        persisted = max(
            (item.sequence for item in self.jobs.events(job_id)),
            default=0,
        )
        return max(cursor, persisted) + 1

    @staticmethod
    def _with_observability(job: Job, event: JobEvent) -> JobEvent:
        """Attach phase timing and event latency to this job's own event."""
        progress = dict(event.progress or {})
        current = job.progress if isinstance(job.progress, dict) else {}
        cancel_request = current.get("backend_cancel_request")
        incoming_cancel_request = progress.get("backend_cancel_request")
        progress.pop("backend_cancel_request", None)
        if (
            event.event_type == "backend_cancel_requested_unresponsive"
            and isinstance(incoming_cancel_request, dict)
            and incoming_cancel_request.get("source") == "operator_stop"
        ):
            progress["backend_cancel_request"] = dict(incoming_cancel_request)
        elif (
            ControlPlane._persisted_high_latency_cancel_request(job) is not None
            and not event.status.terminal
            and event.event_type != "retry_started"
        ):
            progress["backend_cancel_request"] = dict(cancel_request)
        previous_phase = str(current.get("phase") or "")
        phase = str(progress.get("phase") or previous_phase)
        previous_metrics = current.get("observability")
        previous_metrics = previous_metrics if isinstance(previous_metrics, dict) else {}
        phase_durations = previous_metrics.get("phase_durations_seconds")
        phase_durations = (
            dict(phase_durations) if isinstance(phase_durations, dict) else {}
        )
        phase_started_at = previous_metrics.get("phase_started_at")
        now = event.created_at
        phase_changed = bool(phase and previous_phase and phase != previous_phase)
        should_close_phase = bool(
            phase_started_at
            and previous_phase
            and (phase_changed or event.status == JobStatus.PAUSED or event.status.terminal)
        )
        if should_close_phase:
            duration = _elapsed_since(str(phase_started_at), now)
            phase_durations[previous_phase] = round(
                float(phase_durations.get(previous_phase, 0.0)) + duration, 3
            )

        paused = event.status == JobStatus.PAUSED
        was_paused = job.status == JobStatus.PAUSED
        if event.status.terminal or paused:
            phase_started_at = None
        elif phase and (phase_changed or was_paused or not phase_started_at):
            phase_started_at = now.isoformat()

        event_latency = progress.get("backend_telemetry")
        event_latency = event_latency if isinstance(event_latency, dict) else {}
        latency_ms = event_latency.get("event_latency_ms")
        previous_latency = previous_metrics.get("event_latency")
        previous_latency = previous_latency if isinstance(previous_latency, dict) else {}
        latency_count = int(previous_latency.get("count") or 0)
        latency_total = float(previous_latency.get("total_ms") or 0.0)
        if isinstance(latency_ms, (int, float)) and latency_ms >= 0:
            latency_count += 1
            latency_total += float(latency_ms)
        observability = {
            **previous_metrics,
            "phase": phase or None,
            "phase_started_at": phase_started_at,
            "phase_durations_seconds": phase_durations,
            "phase_elapsed_seconds": (
                round(_elapsed_since(str(phase_started_at), now), 3)
                if phase_started_at
                else 0.0
            ),
            "event_latency": {
                "count": latency_count,
                "total_ms": round(latency_total, 3),
                "average_ms": round(latency_total / latency_count, 3)
                if latency_count
                else None,
                "last_ms": round(float(latency_ms), 3)
                if isinstance(latency_ms, (int, float)) and latency_ms >= 0
                else previous_latency.get("last_ms"),
            },
            "last_event_at": now.isoformat(),
        }
        progress["observability"] = observability
        return replace(event, progress=progress)

    def add_event_observer(self, observer: Callable[[JobEvent], None]) -> None:
        self._event_observers.append(observer)

    def set_worker_route(self, actor: Actor, route: str) -> str:
        # Each submitted job already stores its worker. Changing this route
        # therefore only changes the destination of future jobs; in-flight
        # work remains pinned to its original worker.
        if self.worker_registry is not None:
            # Validate route and enabled state before persisting it.  A
            # disabled route may remain visible in the registry so it can be
            # re-enabled, but it must not become the target for new jobs.
            self.resolve_target(actor, worker=route)
        return self.profile_manager.set_worker_route(actor.profile, route)

    def terminate_active_jobs(
        self,
        actor: Actor,
        *,
        profile: str | None = None,
        kind: str | None = None,
        quick_mode: bool | None = None,
    ) -> dict[str, int]:
        active_statuses = (
            JobStatus.QUEUED.value,
            JobStatus.DISPATCHED.value,
            JobStatus.RUNNING.value,
            JobStatus.PAUSED.value,
        )
        selected_profile = None if profile in {None, "", "global"} else self.require_profile(actor, profile)
        active: list[Job] = []
        for status in active_statuses:
            active.extend(
                self.jobs.list(
                    profile=selected_profile,
                    kind=kind,
                    quick_mode=quick_mode,
                    status=status,
                    archived=False,
                    offset=0,
                    limit=200,
                )
            )
        accepted = not_confirmed = cancelled_queued = 0
        cancelled_queued_jobs: list[Job] = []
        for job in active:
            if job.status == JobStatus.QUEUED or (
                job.status == JobStatus.PAUSED
                and job.progress.get("pause_kind") == "queued"
            ):
                outcome, current = self._cancel_queued_before_dispatch(
                    job.id,
                    event_type="cancelled_queued",
                    message="Job antrean dibatalkan.",
                )
                if outcome in {"cancelled", "terminal"}:
                    if outcome == "cancelled":
                        cancelled_queued += 1
                        cancelled_queued_jobs.append(job)
                    continue
                job = current or job
            try:
                signalled = self._cancel_worker_attempt(job)
            except Exception:
                signalled = False
            if signalled:
                accepted += 1
                attempt = self._durable_dispatch_attempt(job.id)
                if attempt is not None:
                    self.jobs.acknowledge_dispatch_cancellation(job.id, attempt)
                if job.kind == "tts":
                    self._cancel_tts_deliveries(job.id)
                continue
            if self._has_pending_dispatch_cancellation(job.id):
                # The worker has not accepted this command yet. The persisted
                # attempt-scoped intent will be retried by the scheduler.
                accepted += 1
                continue
            not_confirmed += 1
        if cancelled_queued:
            self._dispatch_pending_jobs(selected_profile)
        return {
            "total": len(active),
            "cancel_requested": accepted,
            "cancelled_queued": cancelled_queued,
            "not_confirmed": not_confirmed,
        }

    def _storage_reconciliation_proves_missing(
        self, source: Job, item_index: int, item: dict[str, Any]
    ) -> bool:
        proof = item.get("reconciliation")
        if not isinstance(proof, dict):
            return False
        if type(proof.get("match_count")) is not int:
            return False
        if proof.get("status") != "failed" or proof.get("match_count") != 0:
            return False
        proof_job_id = str(proof.get("job_id") or "").strip()
        verifier = self.jobs.get(proof_job_id) if proof_job_id else None
        if (
            verifier is None
            or verifier.kind != "storage_reconcile"
            # A batch reconciliation may finish with an unresolved sibling.
            # Per-item evidence is authoritative only when it proves this exact
            # item absent through its provider-specific verification path.
            or verifier.status not in {JobStatus.SUCCEEDED, JobStatus.FAILED}
            or verifier.actor_user_id != source.actor_user_id
            or verifier.profile != source.profile
            or verifier.worker != source.worker
            or str(verifier.payload.get("source_job_id") or "") != source.id
        ):
            return False
        verifier_item_index = verifier.payload.get("item_index")
        if verifier_item_index is not None and (
            type(verifier_item_index) is not int or verifier_item_index != item_index
        ):
            return False
        verifier_result = verifier.result if isinstance(verifier.result, dict) else {}
        verifier_value = verifier_result.get("value", verifier_result)
        if not isinstance(verifier_value, dict):
            return False
        if str(verifier_value.get("source_job_id") or "") != source.id:
            return False
        provider = str(source.payload.get("provider") or "telegram").strip().lower()
        if str(verifier_value.get("provider") or "telegram").strip().lower() != provider:
            return False
        evidence_items = verifier_value.get("items")
        if not isinstance(evidence_items, list):
            return False
        source_name = str(item.get("name") or "")
        for evidence in evidence_items:
            if not isinstance(evidence, dict):
                continue
            if (
                type(evidence.get("index")) is not int
                or type(evidence.get("match_count")) is not int
            ):
                continue
            if (
                evidence["index"] == item_index
                and str(evidence.get("name") or "") == source_name
                and evidence.get("status") == "failed"
                and evidence["match_count"] == 0
                and evidence.get("retryable") is True
            ):
                if provider == "rclone" and str(evidence.get("target_path") or "") != str(
                    item.get("target_path") or ""
                ):
                    continue
                return True
        return False

    @staticmethod
    def _storage_retry_item_paths(
        payload: dict[str, Any], source_items: list[Any]
    ) -> dict[int, str]:
        raw_mapping = payload.get("_storage_retry_item_indexes")
        mapped: dict[int, str] = {}
        if isinstance(raw_mapping, dict):
            for raw_index, raw_path in raw_mapping.items():
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    continue
                if isinstance(raw_index, bool) or index < 0 or not isinstance(raw_path, str):
                    continue
                mapped[index] = raw_path
            if mapped:
                return mapped

        single_index = payload.get("_storage_retry_item_index")
        if isinstance(single_index, int) and not isinstance(single_index, bool) and single_index >= 0:
            path = ""
            if single_index < len(source_items) and isinstance(source_items[single_index], dict):
                path = str(source_items[single_index].get("path") or "")
            if path:
                return {single_index: path}

        raw_paths = payload.get("_storage_retry_paths")
        selected_paths = {
            str(path)
            for path in raw_paths
            if isinstance(path, str) and path
        } if isinstance(raw_paths, list) else set()
        for index, item in enumerate(source_items):
            if isinstance(item, dict):
                path = str(item.get("path") or "")
                if path in selected_paths:
                    mapped[index] = path
        return mapped

    def _update_storage_upload_items(
        self, source: Job, value: dict[str, Any], items: list[Any]
    ) -> Job:
        value["items"] = items
        value["total"] = len(items)
        value["succeeded"] = sum(
            isinstance(item, dict) and item.get("status") == "succeeded"
            for item in items
        )
        value["skipped"] = sum(
            isinstance(item, dict) and item.get("status") == "skipped"
            for item in items
        )
        unresolved = [
            item for item in items
            if not isinstance(item, dict)
            or item.get("status") not in {"succeeded", "skipped"}
        ]
        value["failed"] = unresolved
        value["retryable"] = any(
            isinstance(item, dict) and item.get("retryable") is True
            for item in unresolved
        )
        value["ambiguous"] = sum(
            isinstance(item, dict) and item.get("status") == "needs_reconciliation"
            for item in unresolved
        )
        value["skipped_items"] = [
            item for item in items
            if isinstance(item, dict) and item.get("status") == "skipped"
        ]
        if unresolved:
            has_success = value["succeeded"] > 0 or value["skipped"] > 0
            value["outcome"] = (
                "partial_failure" if has_success
                else "needs_reconciliation"
                if any(
                    isinstance(item, dict)
                    and item.get("status") == "needs_reconciliation"
                    for item in unresolved
                )
                else "failed"
            )
        else:
            value["outcome"] = "succeeded"
        source_result = source.result if isinstance(source.result, dict) else {}
        if isinstance(source_result.get("value"), dict):
            result = {**source_result, "value": value}
        else:
            result = value
        return self.jobs.update_result(source.id, result)

    def _mark_storage_items_retrying(
        self,
        source_job_id: str,
        retry_job: Job,
        item_paths: dict[int, str],
        *,
        require_reconciliation_proof: bool,
    ) -> Job | None:
        source = self.jobs.get(source_job_id)
        if (
            source is None
            or source.kind != "storage_upload"
            or source.status not in {JobStatus.FAILED, JobStatus.CANCELLED}
            or source.actor_user_id != retry_job.actor_user_id
            or source.profile != retry_job.profile
            or source.worker != retry_job.worker
        ):
            return None
        source_result = source.result if isinstance(source.result, dict) else {}
        value = source_result.get("value", source_result)
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            return None
        items = [dict(item) if isinstance(item, dict) else item for item in value["items"]]
        changed = False
        for item_index, expected_path in item_paths.items():
            if item_index < 0 or item_index >= len(items):
                continue
            item = items[item_index]
            if (
                not isinstance(item, dict)
                or item.get("status") not in {"failed", "pending"}
                or item.get("retryable") is not True
                or str(item.get("path") or "") != expected_path
                or (
                    require_reconciliation_proof
                    and not self._storage_reconciliation_proves_missing(source, item_index, item)
                )
            ):
                continue
            item.update(status="retrying", retryable=False, retry_job_id=retry_job.id)
            items[item_index] = item
            changed = True
        if not changed:
            return None
        return self._update_storage_upload_items(source, value, items)

    def _retry_storage_upload_item(
        self, actor: Actor, original: Job, item_index: int
    ) -> Job:
        result_value = (
            original.result.get("value", original.result)
            if isinstance(original.result, dict)
            else {}
        )
        file_items = result_value.get("items") if isinstance(result_value, dict) else []
        file_items = file_items if isinstance(file_items, list) else []
        if item_index < 0 or item_index >= len(file_items):
            raise DomainError(
                "STORAGE_RETRY_UNAVAILABLE",
                "File ini tidak lagi tersedia untuk Retry.",
                status_code=409,
            )
        current_item = file_items[item_index]
        if isinstance(current_item, dict) and current_item.get("status") == "retrying":
            retry_job_id = str(current_item.get("retry_job_id") or "").strip()
            retry_job = self.jobs.get(retry_job_id) if retry_job_id else None
            if retry_job is not None:
                if retry_job.status.terminal:
                    retry_result = retry_job.result if isinstance(retry_job.result, dict) else {}
                    retry_value = retry_result.get("value", retry_result)
                    if isinstance(retry_value, dict):
                        self._apply_storage_retry_result(retry_job, retry_value)
                return retry_job
            raise DomainError(
                "STORAGE_RETRY_IN_PROGRESS",
                "Retry file ini masih berjalan.",
                status_code=409,
            )
        for candidate in self.jobs.list(
            actor_user_id=actor.telegram_user_id,
            profile=original.profile,
            kind="storage_upload",
            worker=original.worker,
            archived=False,
            offset=0,
            limit=1000,
        ):
            if candidate.status.terminal:
                continue
            command = self.jobs.command_payload(candidate.id)
            nested_payload = command.get("payload") if isinstance(command, dict) else None
            payload = nested_payload if isinstance(nested_payload, dict) else (
                command if isinstance(command, dict) else {}
            )
            candidate_value = (
                original.result.get("value", original.result)
                if isinstance(original.result, dict)
                else {}
            )
            candidate_items = candidate_value.get("items") if isinstance(candidate_value, dict) else []
            candidate_items = candidate_items if isinstance(candidate_items, list) else []
            indexed_paths = self._storage_retry_item_paths(payload, candidate_items)
            if (
                str(payload.get("_storage_retry_of") or "") == original.id
                and indexed_paths.get(item_index) == str(current_item.get("path") or "")
            ):
                self._mark_storage_items_retrying(
                    original.id,
                    candidate,
                    {item_index: str(current_item.get("path") or "")},
                    require_reconciliation_proof=False,
                )
                return candidate

        item = file_items[item_index]
        if isinstance(item, dict) and item.get("status") == "retrying":
            raise DomainError(
                "STORAGE_RETRY_IN_PROGRESS",
                "Retry file ini masih berjalan.",
                status_code=409,
            )
        if (
            not isinstance(item, dict)
            or item.get("status") not in {"failed", "pending"}
            or item.get("retryable") is not True
        ):
            raise DomainError(
                "STORAGE_RETRY_UNAVAILABLE",
                "File ini tidak dipastikan gagal sebelum terkirim.",
                status_code=409,
            )
        if not self._storage_reconciliation_proves_missing(original, item_index, item):
            raise DomainError(
                "STORAGE_RETRY_REQUIRES_RECONCILIATION",
                "Verifikasi lengkap harus memastikan file ini tidak ada di tujuan sebelum Retry.",
                status_code=409,
            )
        raw_path = str(item.get("path") or "")
        path = PurePosixPath(raw_path)
        if (
            not raw_path
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.as_posix() != raw_path
        ):
            raise DomainError(
                "STORAGE_RETRY_UNAVAILABLE",
                "Path file untuk Retry tidak valid.",
                status_code=409,
            )
        try:
            attempts = max(0, int(item.get("attempt") or 0))
        except (TypeError, ValueError):
            attempts = 0
        payload = deepcopy(original.payload)
        payload["batch_id"] = str(uuid.uuid4())
        payload["_storage_retry_paths"] = [raw_path]
        payload["_storage_file_attempts"] = {raw_path: attempts}
        payload["_storage_retry_of"] = original.id
        payload["_storage_retry_item_index"] = item_index
        payload["_storage_retry_item_indexes"] = {str(item_index): raw_path}
        retry_job = self.submit_job(
            actor,
            "storage_upload",
            payload,
            profile=original.profile,
            worker=original.worker,
        )
        self._mark_storage_items_retrying(
            original.id,
            retry_job,
            {item_index: raw_path},
            require_reconciliation_proof=True,
        )
        current_retry = self.jobs.get(retry_job.id) or retry_job
        if current_retry.status.terminal:
            child_result = current_retry.result if isinstance(current_retry.result, dict) else {}
            value = child_result.get("value", child_result)
            if isinstance(value, dict):
                self._apply_storage_retry_result(current_retry, value)
        return current_retry

    def _retry_storage_upload_batch(self, actor: Actor, original: Job) -> Job:
        result_value = (
            original.result.get("value", original.result)
            if isinstance(original.result, dict)
            else {}
        )
        file_items = result_value.get("items") if isinstance(result_value, dict) else []
        file_items = file_items if isinstance(file_items, list) else []
        retry_paths: dict[str, int] = {}
        retry_indexes: dict[str, str] = {}
        item_paths: dict[int, str] = {}
        for index, item in enumerate(file_items):
            if not isinstance(item, dict):
                continue
            if item.get("status") not in {"failed", "pending"} or item.get("retryable") is not True:
                continue
            raw_path = str(item.get("path") or "")
            path = PurePosixPath(raw_path)
            if (
                not raw_path
                or path.is_absolute()
                or any(part in {"", ".", ".."} for part in path.parts)
                or path.as_posix() != raw_path
            ):
                continue
            if raw_path in retry_paths:
                continue
            try:
                attempt = max(0, int(item.get("attempt") or 0))
            except (TypeError, ValueError):
                attempt = 0
            retry_paths[raw_path] = attempt
            retry_indexes[str(index)] = raw_path
            item_paths[index] = raw_path
        if not retry_paths:
            raise DomainError(
                "STORAGE_RETRY_UNAVAILABLE",
                "Tidak ada file yang dipastikan belum diterima Telegram. File ambigu harus direkonsiliasi sebelum Retry.",
                status_code=409,
            )

        # Do not let a repeated batch action overlap an in-flight per-file or
        # batch retry for this source job.
        for candidate in self.jobs.list(
            actor_user_id=actor.telegram_user_id,
            profile=original.profile,
            kind="storage_upload",
            worker=original.worker,
            archived=False,
            offset=0,
            limit=1000,
        ):
            if candidate.status.terminal:
                continue
            command = self.jobs.command_payload(candidate.id)
            nested_payload = command.get("payload") if isinstance(command, dict) else None
            child_payload = nested_payload if isinstance(nested_payload, dict) else (
                command if isinstance(command, dict) else {}
            )
            if str(child_payload.get("_storage_retry_of") or "") == original.id:
                raise DomainError(
                    "STORAGE_RETRY_IN_PROGRESS",
                    "Retry file dari upload ini masih berjalan.",
                    status_code=409,
                )

        payload = deepcopy(original.payload)
        payload["batch_id"] = str(uuid.uuid4())
        payload["_storage_retry_paths"] = sorted(retry_paths)
        payload["_storage_file_attempts"] = retry_paths
        payload["_storage_retry_of"] = original.id
        payload["_storage_retry_item_indexes"] = retry_indexes
        retry_job = self.submit_job(
            actor,
            "storage_upload",
            payload,
            profile=original.profile,
            worker=original.worker,
        )
        self._mark_storage_items_retrying(
            original.id,
            retry_job,
            item_paths,
            require_reconciliation_proof=False,
        )
        current_retry = self.jobs.get(retry_job.id) or retry_job
        if current_retry.status.terminal:
            child_result = current_retry.result if isinstance(current_retry.result, dict) else {}
            value = child_result.get("value", child_result)
            if isinstance(value, dict):
                self._apply_storage_retry_result(current_retry, value)
        return current_retry

    def _apply_storage_retry_result(self, retry_job: Job, result: dict[str, Any]) -> None:
        command = self.jobs.command_payload(retry_job.id)
        nested_payload = command.get("payload") if isinstance(command, dict) else None
        payload = nested_payload if isinstance(nested_payload, dict) else (
            command if isinstance(command, dict) else {}
        )
        source_job_id = str(payload.get("_storage_retry_of") or "").strip()
        if not source_job_id:
            return
        with self._storage_source_action_lock(source_job_id):
            source = self.jobs.get(source_job_id)
            if (
                source is None
                or source.kind != "storage_upload"
                or source.actor_user_id != retry_job.actor_user_id
                or source.profile != retry_job.profile
                or source.worker != retry_job.worker
                or not source.status.terminal
            ):
                return
            source_result = source.result if isinstance(source.result, dict) else {}
            value = source_result.get("value", source_result)
            if not isinstance(value, dict) or not isinstance(value.get("items"), list):
                return
            items = [dict(item) if isinstance(item, dict) else item for item in value["items"]]
            item_paths = self._storage_retry_item_paths(payload, items)
            if not item_paths:
                return
            evidence_items = result.get("items") if isinstance(result.get("items"), list) else []
            changed = False
            for item_index, expected_path in item_paths.items():
                if item_index < 0 or item_index >= len(items):
                    continue
                original_item = items[item_index]
                if (
                    not isinstance(original_item, dict)
                    or original_item.get("status") != "retrying"
                    or str(original_item.get("retry_job_id") or "") != retry_job.id
                    or str(original_item.get("path") or "") != expected_path
                ):
                    continue
                evidence = next((
                    item for item in evidence_items
                    if isinstance(item, dict)
                    and str(item.get("path") or "") == expected_path
                ), None)
                if evidence is None:
                    original_item.update(
                        status="needs_reconciliation",
                        retryable=False,
                        error="Hasil Retry belum terkonfirmasi; verifikasi ulang file.",
                    )
                    original_item.pop("reconciliation", None)
                else:
                    evidence_status = str(evidence.get("status") or "")
                    if evidence_status in {"succeeded", "skipped"}:
                        original_item["status"] = evidence_status
                        original_item["retryable"] = False
                        original_item.pop("reconciliation", None)
                        original_item.pop("source_identity", None)
                    else:
                        original_item["status"] = "needs_reconciliation"
                        original_item["retryable"] = False
                        original_item.pop("reconciliation", None)
                    for key in (
                        "upload_status", "cleanup_status", "attempt", "profile",
                        "error", "error_code", "reason", "reason_code", "attempts",
                    ):
                        if key in evidence:
                            original_item[key] = deepcopy(evidence[key])
                        elif key in {"error", "error_code", "reason", "reason_code", "attempts"}:
                            original_item.pop(key, None)
                original_item.pop("retry_job_id", None)
                items[item_index] = original_item
                changed = True
            if changed:
                self._update_storage_upload_items(source, value, items)

    def retry_job(
        self,
        actor: Actor,
        job_id: str,
        *,
        resume_phase: str | None = None,
        single_phase: bool = False,
        storage_item_index: int | None = None,
    ) -> Job:
        """Restart an export attempt while preserving its stable job ID."""
        original = self.jobs.get(job_id)
        if original is None:
            raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
        self.require_profile(actor, original.profile)
        if storage_item_index is not None and original.kind != "storage_upload":
            raise DomainError(
                "STORAGE_RETRY_UNAVAILABLE",
                "Retry per file hanya tersedia untuk upload Storage.",
                status_code=409,
            )
        if original.kind == "storage_upload":
            with self._storage_source_action_lock(original.id):
                original = self.jobs.get(job_id)
                if original is None:
                    raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
                self.require_profile(actor, original.profile)
                if not original.status.terminal:
                    raise DomainError(
                        "JOB_NOT_TERMINAL",
                        "Job masih aktif dan belum dapat diulang.",
                        status_code=409,
                    )
                if storage_item_index is not None:
                    return self._retry_storage_upload_item(actor, original, storage_item_index)
                return self._retry_storage_upload_batch(actor, original)
        if not original.status.terminal:
            raise DomainError(
                "JOB_NOT_TERMINAL",
                "Job masih aktif dan belum dapat diulang.",
                status_code=409,
            )
        if original.kind != "export":
            raise DomainError(
                "EXPORT_REQUIRED",
                "Endpoint ini hanya dapat mengulang job export.",
                status_code=409,
            )
        result_value = original.result.get("value", original.result) if isinstance(original.result, dict) else {}
        legacy_quick = bool(
            original.payload.get("quick_mode")
            or (result_value.get("quick_mode") if isinstance(result_value, dict) else False)
        )
        command_getter = getattr(self.jobs, "command_payload", None)
        command_payload = command_getter(original.id) if callable(command_getter) else None
        if not isinstance(command_payload, dict):
            # Jobs created before the internal command table existed can
            # still be retried from their persisted public payload.  Quick
            # Mode's password is intentionally not stored in that payload;
            # use the current configured settings only for this legacy
            # recovery path.
            command_payload = deepcopy(original.payload)
            if legacy_quick or bool(command_payload.get("quick_mode")):
                settings = command_payload.get("quick_settings")
                if not isinstance(settings, dict) or settings.get("compress_password") in {
                    None,
                    "",
                    "***",
                }:
                    getter = getattr(self.utility_settings, "get", None)
                    settings = getter() if callable(getter) else dict(DEFAULT_UTILITY_SETTINGS)
                if not isinstance(settings, dict):
                    raise DomainError(
                        "RETRY_PAYLOAD_UNAVAILABLE",
                        "Snapshot settings Quick Mode job lama tidak tersedia untuk retry.",
                        status_code=409,
                    )
                command_payload["quick_settings"] = settings
        payload = deepcopy(command_payload)
        if legacy_quick:
            settings = payload.get("quick_settings")
            if not isinstance(settings, dict) or settings.get("compress_password") in {
                None,
                "",
                "***",
            }:
                getter = getattr(self.utility_settings, "get", None)
                settings = getter() if callable(getter) else dict(DEFAULT_UTILITY_SETTINGS)
            if isinstance(settings, dict) and not settings.get("rclone_destination"):
                getter = getattr(self.utility_settings, "get", None)
                current = getter() if callable(getter) else DEFAULT_UTILITY_SETTINGS
                settings = dict(settings)
                settings["rclone_destination"] = str(
                    current.get("rclone_destination", "googledrive:backup")
                    if isinstance(current, dict)
                    else "googledrive:backup"
                )
            payload["quick_settings"] = settings
        if legacy_quick or bool(payload.get("quick_mode")):
            previous_retry = payload.get("quick_retry")
            previous_retry = previous_retry if isinstance(previous_retry, dict) else {}
            stage_job_id = str(previous_retry.get("stage_job_id") or original.id)
            operation_id = str(previous_retry.get("quick_operation_id") or stage_job_id)
            export_start_id, export_end_id = self._export_message_range(original)
            target_phase = (
                resume_phase.strip().lower()
                if isinstance(resume_phase, str) and resume_phase.strip()
                else None
            )
            payload["quick_mode"] = True
            if target_phase:
                payload["quick_phase"] = target_phase
            payload["quick_retry"] = {
                "retry_of": original.id,
                # Keep the historical phase for reports/backwards-compatible
                # clients, while explicitly telling the worker to inspect the
                # physical folder before choosing the actual resume phase.
                "retry_phase": target_phase or self._quick_retry_phase(original),
                "resume_phase": target_phase or "auto",
                "single_phase": bool(single_phase and target_phase and target_phase not in {"auto", "exporting"}),
                "stage_job_id": stage_job_id,
                "quick_operation_id": operation_id,
            }
            self._add_export_range(payload["quick_retry"], export_start_id, export_end_id)
        else:
            export_start_id, export_end_id = self._export_message_range(original)
            payload["quick_mode"] = False
            payload["export_retry"] = {
                "retry_of": original.id,
                "retry_phase": "exporting",
            }
            self._add_export_range(payload["export_retry"], export_start_id, export_end_id)
        return self.submit_job(
            actor,
            "export",
            payload,
            profile=original.profile,
            worker=original.worker,
            job_id=original.id,
        )

    def retry_tts_job(self, actor: Actor, job_id: str) -> Job:
        original = self.jobs.get(job_id)
        if original is None or original.kind != "tts":
            raise DomainError("TTS_JOB_NOT_FOUND", "Job TTS tidak ditemukan.", status_code=404)
        self.require_profile(actor, original.profile)
        if not original.status.terminal:
            raise DomainError("JOB_NOT_TERMINAL", "Job TTS masih aktif.", status_code=409)
        needs_delivery_reconciliation = False
        delivery_summary = getattr(self.jobs, "tts_delivery_summary", None)
        if callable(delivery_summary):
            summary = delivery_summary(job_id)
            total_parts = int(summary.get("total_parts") or 0)
            delivered_parts = int(summary.get("delivered_parts") or 0)
            needs_delivery_reconciliation = bool(
                total_parts and delivered_parts < total_parts
            )
        command_payload = self.jobs.command_payload(job_id)
        if not isinstance(command_payload, dict) or not str(command_payload.get("text") or ""):
            raise DomainError("RETRY_PAYLOAD_UNAVAILABLE", "Teks internal job TTS tidak tersedia untuk retry.", status_code=409)
        if needs_delivery_reconciliation:
            command_payload = deepcopy(command_payload)
            command_payload["_tts_reconcile_delivery"] = True
        return self.submit_job(
            actor,
            "tts",
            deepcopy(command_payload),
            profile=original.profile,
            worker=original.worker,
            job_id=original.id,
        )

    @staticmethod
    def _quick_retry_phase(job: Job) -> str:
        if job.status == JobStatus.SUCCEEDED:
            return "exporting"
        phase = str(job.progress.get("phase") or "").strip().lower()
        if phase == "json_ready":
            return "downloading"
        if phase in {
            "exporting",
            "downloading",
            "thumbnailing",
            "compressing",
            "uploading",
            "cleanup",
        }:
            return phase
        return "exporting"

    @staticmethod
    def _positive_id(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 1 else None

    def _export_message_range(self, job: Job) -> tuple[int | None, int | None]:
        """Find the original TDL message range without reading the JSON file.

        New jobs record the range in ``json_ready`` progress and the terminal
        result.  The event scan also covers a job that failed after exporting
        but before its final result was persisted.  For old rows we retain
        compatibility with the historical ``start_id``/``latest_id`` fields
        and can recover a start ID from a stored t.me URL.
        """
        candidates: list[dict[str, Any]] = []
        payload = job.payload if isinstance(job.payload, dict) else {}
        for key in ("export_retry", "quick_retry"):
            value = payload.get(key)
            if isinstance(value, dict):
                candidates.append(value)
        if isinstance(job.progress, dict):
            candidates.append(job.progress)
        if isinstance(job.result, dict):
            value = job.result.get("value", job.result)
            if isinstance(value, dict):
                candidates.append(value)
        events_getter = getattr(self.jobs, "events", None)
        if callable(events_getter):
            try:
                events = list(events_getter(job.id))
            except Exception:
                events = []
            for event in reversed(events):
                progress = getattr(event, "progress", None)
                result = getattr(event, "result", None)
                if isinstance(progress, dict):
                    candidates.append(progress)
                if isinstance(result, dict):
                    candidates.append(result)
                    value = result.get("value")
                    if isinstance(value, dict):
                        candidates.append(value)
        return self._range_from_candidates(job, candidates)

    @classmethod
    def _range_from_candidates(
        cls, job: Job, candidates: list[dict[str, Any]]
    ) -> tuple[int | None, int | None]:
        start_id: int | None = None
        end_id: int | None = None
        for candidate in candidates:
            if start_id is None:
                for key in ("export_start_id", "start_id"):
                    start_id = cls._positive_id(candidate.get(key))
                    if start_id is not None:
                        break
            if end_id is None:
                for key in ("export_end_id", "end_id", "max_message_id", "latest_id"):
                    end_id = cls._positive_id(candidate.get(key))
                    if end_id is not None:
                        break
            if start_id is not None and end_id is not None:
                break

        payload = job.payload if isinstance(job.payload, dict) else {}
        if start_id is None:
            start_id = cls._positive_id(payload.get("start_id"))
        if start_id is None:
            url = str(payload.get("url") or "").strip()
            parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
            if len(parts) >= 3 and parts[0].casefold() == "c":
                start_id = cls._positive_id(parts[2])
            elif len(parts) >= 2:
                start_id = cls._positive_id(parts[1])

        if start_id is not None and end_id is not None:
            end_id = max(start_id, end_id)
        return start_id, end_id

    @staticmethod
    def _add_export_range(
        metadata: dict[str, Any], start_id: int | None, end_id: int | None
    ) -> None:
        if start_id is not None:
            metadata["start_id"] = start_id
        if end_id is not None:
            metadata["end_id"] = max(start_id or 1, end_id)

    def _cancel_high_latency_job(self, job: Job, latency_ms: float) -> Job:
        with self._stale_job_lock:
            current = self.jobs.get(job.id)
            if current is None or current.status.terminal:
                return current or job
            request_state = self._high_latency_cancel_attempts.get(job.id)
            if request_state is None:
                request_state = self._persisted_high_latency_cancel_request(current)
            if request_state is not None and (
                request_state.get("in_flight")
                or request_state.get("signal_status") == "accepted"
            ):
                return current
            if request_state is None:
                request_state = {
                    "requested_at": utc_now().isoformat(),
                    "signal_status": "pending",
                    "latency_ms": round(float(latency_ms), 3),
                    "source": "operator_stop",
                }
            request_state["in_flight"] = True
            current = self._persist_high_latency_cancel_request(
                current, request_state
            )
            self._high_latency_cancel_attempts[job.id] = request_state
        if current.status.terminal:
            with self._stale_job_lock:
                self._high_latency_cancel_attempts.pop(job.id, None)
            return current

        signal_status = "not_confirmed"
        try:
            accepted = self._cancel_worker_attempt_with_timeout(
                current,
                attempt=None,
                timeout_seconds=_WORKER_UNRESPONSIVE_CANCEL_TIMEOUT_SECONDS,
            )
            if accepted:
                signal_status = "accepted"
                with self._stale_job_lock:
                    latest = self.jobs.get(job.id)
                    if latest is None or latest.status.terminal:
                        self._high_latency_cancel_attempts.pop(job.id, None)
                        return latest or current
                    request_state["signal_status"] = "accepted"
                    request_state["in_flight"] = False
                    current = self._persist_high_latency_cancel_request(
                        latest, request_state
                    )
                return self.jobs.get(job.id) or current
        except Exception as exc:
            signal_status = "unavailable"
            with self._stale_job_lock:
                request_state["signal_status"] = signal_status
                request_state["in_flight"] = False
            logging.getLogger(__name__).warning(
                "High-latency worker cancel failed for %s (%s)",
                job.id,
                type(exc).__name__,
            )
            accepted = False

        with self._stale_job_lock:
            request_state["signal_status"] = signal_status
            request_state["in_flight"] = False
        return self._force_cancel_unresponsive_job(
            current,
            latency_ms=latency_ms,
            signal_status=signal_status,
        )

    def _force_cancel_unresponsive_job(
        self,
        job: Job,
        *,
        latency_ms: float | None,
        signal_status: str | None,
        reason: str = "operator_stop_cancel_unconfirmed",
    ) -> Job:
        with self._stale_job_lock:
            current = self.jobs.get(job.id)
            if current is None or current.status.terminal:
                return current or job
            self._mark_worker_unresponsive(
                current.worker, reason=reason
            )
            self._stale_cancel_requested.pop(current.id, None)
            progress = (
                dict(current.progress)
                if isinstance(current.progress, dict)
                else {}
            )
            progress.pop("backend_telemetry", None)
            progress.update(
                {
                    "phase": "cancelled",
                    "terminal_phase": "cancelled",
                    "finished_at": utc_now().isoformat(),
                    "worker_confirmation": "not_received",
                    "worker_unresponsive": True,
                    "worker_unresponsive_reason": reason,
                    "outcome_uncertain": True,
                    "reconciliation_required": True,
                }
            )
            if signal_status is not None:
                progress["worker_cancel_signal"] = signal_status
            if latency_ms is not None:
                progress["event_latency_ms"] = round(float(latency_ms), 3)
            if reason == "stale_worker_probe_unavailable":
                message = (
                    "Job tidak mengirim pembaruan melewati batas stale dan worker "
                    "tidak merespons pemeriksaan ringan. Job ditandai cancelled di "
                    "gateway; status proses fisik belum terkonfirmasi."
                )
            else:
                message = (
                    "Worker tidak mengonfirmasi permintaan Stop. Job ditandai "
                    "cancelled di gateway; status proses fisik belum terkonfirmasi."
                )
            terminal = self.append_worker_event(
                JobEvent(
                    job_id=current.id,
                    sequence=self._next_job_event_sequence(
                        current.id, fallback=current
                    ),
                    status=JobStatus.CANCELLED,
                    event_type="backend_cancelled_unresponsive",
                    progress=progress,
                    error={
                        "code": "WORKER_UNRESPONSIVE",
                        "message": message,
                    },
                ),
                dispatch_pending=False,
            )
            if current.kind == "tts":
                self._cancel_tts_deliveries(current.id)
            return terminal

    def cancel_worker_jobs_after_restart(
        self, worker: str, job_ids: list[str], *, operation_id: str
    ) -> list[str]:
        """Cancel every active job on a worker after the supervisor confirms stop."""
        name = str(worker or "").strip().lower()
        targets = list(dict.fromkeys(str(value) for value in job_ids if str(value)))
        offset = 0
        while True:
            active = self.jobs.list(
                worker=name,
                statuses=_ACTIVE_PROGRESS_REFRESH_STATUSES,
                archived=False,
                offset=offset,
                limit=200,
            )
            targets.extend(
                job.id for job in active
                if job.worker == name and not job.status.terminal
            )
            if len(active) < 200:
                break
            offset += len(active)
        cancelled: list[str] = []
        for job_id in dict.fromkeys(targets):
            current = self.jobs.get(job_id)
            if current is None or current.worker != name or current.status.terminal:
                continue
            progress = dict(current.progress) if isinstance(current.progress, dict) else {}
            progress.pop("backend_telemetry", None)
            progress.update(
                {
                    "phase": "cancelled",
                    "terminal_phase": "cancelled",
                    "finished_at": utc_now().isoformat(),
                    "worker_confirmation": "container_restarted",
                    "worker_restart": {
                        "operation_id": str(operation_id),
                        "container_stopped": True,
                    },
                    "outcome_uncertain": True,
                    "reconciliation_required": True,
                }
            )
            terminal = self.append_worker_event(
                JobEvent(
                    job_id=current.id,
                    sequence=self._next_job_event_sequence(
                        current.id, fallback=current
                    ),
                    status=JobStatus.CANCELLED,
                    event_type="worker_restart_cancelled",
                    progress=progress,
                    error={
                        "code": "WORKER_RESTARTED",
                        "message": (
                            "Worker di-restart oleh operator. Job dihentikan; "
                            "hasil eksternal mungkin belum pasti."
                        ),
                    },
                ),
                dispatch_pending=False,
            )
            if terminal.status == JobStatus.CANCELLED:
                cancelled.append(current.id)
                if current.kind == "tts":
                    self._cancel_tts_deliveries(current.id)
        return cancelled

    def cancel_job(self, actor: Actor, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
        self.require_profile(actor, job.profile)
        if job.status.terminal:
            return job
        latency_ms = self._job_event_latency_ms(job)
        if (
            latency_ms is not None
            and latency_ms >= _WORKER_UNRESPONSIVE_EVENT_LATENCY_MS
        ):
            return self._cancel_high_latency_job(job, latency_ms)
        if job.status == JobStatus.PAUSED and job.progress.get("pause_kind") == "queued":
            outcome, current = self._cancel_queued_before_dispatch(
                job.id,
                event_type="cancelled_paused_queue",
                message="Job antrean Quick Mode dibatalkan.",
            )
            if outcome in {"cancelled", "terminal"}:
                if job.kind == "tts":
                    self._cancel_tts_deliveries(job.id)
                self._dispatch_pending_jobs()
                return current or self.jobs.get(job.id) or job
            job = current or job
        if job.status == JobStatus.QUEUED:
            outcome, current = self._cancel_queued_before_dispatch(
                job.id,
                event_type="cancelled_queued",
                message="Job queued dibatalkan.",
            )
            if outcome in {"cancelled", "terminal"}:
                if job.kind == "tts":
                    self._cancel_tts_deliveries(job.id)
                self._dispatch_pending_jobs(job.profile)
                return current or self.jobs.get(job.id) or job
            job = current or job
        request_state = {
            "requested_at": utc_now().isoformat(),
            "signal_status": "pending",
            "latency_ms": round(float(latency_ms or 0.0), 3),
            "source": "operator_stop",
            "in_flight": True,
        }
        with self._stale_job_lock:
            current = self.jobs.get(job.id)
            if current is None or current.status.terminal:
                return current or job
            existing_request = self._persisted_high_latency_cancel_request(current)
            if existing_request is not None:
                return current
            current = self._persist_high_latency_cancel_request(
                current, request_state
            )
            if current.status.terminal:
                return current
            self._high_latency_cancel_attempts[job.id] = request_state
            job = current

        try:
            cancelled = self._cancel_worker_attempt(job)
        except Exception as exc:
            current = self.jobs.get(job.id)
            if current is not None and current.status.terminal:
                self._high_latency_cancel_attempts.pop(job.id, None)
                return current
            if self._has_pending_dispatch_cancellation(job.id):
                request_state["in_flight"] = False
                return current or job
            self._clear_pending_cancel_request(job.id)
            raise DomainError(
                "WORKER_CANCEL_UNAVAILABLE",
                f"Worker {job.worker} tidak dapat menerima permintaan terminate: {exc}",
                status_code=503,
            ) from exc
        if not cancelled:
            current = self.jobs.get(job.id)
            if current is not None and current.status.terminal:
                self._high_latency_cancel_attempts.pop(job.id, None)
                return current
            if self._has_pending_dispatch_cancellation(job.id):
                request_state["in_flight"] = False
                return current or job
            self._clear_pending_cancel_request(job.id)
            raise DomainError(
                "JOB_NOT_CANCELLABLE",
                "Worker belum menerima permintaan pembatalan. Status job tidak diubah.",
                status_code=409,
            )

        with self._stale_job_lock:
            current = self.jobs.get(job.id)
            if current is None or current.status.terminal:
                self._high_latency_cancel_attempts.pop(job.id, None)
                return current or job
            request_state["signal_status"] = "accepted"
            request_state["in_flight"] = False
            self._high_latency_cancel_attempts[job.id] = request_state
            current = self._persist_high_latency_cancel_request(
                current, request_state
            )
            job = current
        if job.kind == "tts":
            self._cancel_tts_deliveries(job.id)
        attempt = self._durable_dispatch_attempt(job.id)
        if attempt is not None:
            self.jobs.acknowledge_dispatch_cancellation(job.id, attempt)
        # The worker emits the terminal ``cancelled`` event only after the
        # interrupted process has actually stopped. Marking it terminal here
        # would reject late log/final events and make the UI lie about a still
        # running process.
        return self.jobs.get(job.id) or job

    def reconcile_storage_upload(
        self, actor: Actor, job_id: str, *, item_index: int | None = None
    ) -> Job:
        with self._storage_source_action_lock(job_id):
            return self._reconcile_storage_upload_locked(
                actor, job_id, item_index=item_index
            )

    def _reconcile_storage_upload_locked(
        self, actor: Actor, job_id: str, *, item_index: int | None = None
    ) -> Job:
        """Queue a read-only filename scan for ambiguous files in one upload job."""
        original = self.jobs.get(job_id)
        if original is None:
            raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
        self.require_profile(actor, original.profile)
        if original.kind != "storage_upload":
            raise DomainError(
                "STORAGE_UPLOAD_REQUIRED",
                "Rekonsiliasi hanya tersedia untuk upload Storage.",
                status_code=409,
            )
        if item_index is not None and (
            not isinstance(item_index, int)
            or isinstance(item_index, bool)
            or item_index < 0
        ):
            raise DomainError(
                "STORAGE_RECONCILIATION_ITEM_UNAVAILABLE",
                "Nomor file untuk verifikasi tidak valid.",
                status_code=409,
            )
        if not original.status.terminal:
            raise DomainError(
                "JOB_NOT_TERMINAL",
                "Upload masih aktif dan belum dapat direkonsiliasi.",
                status_code=409,
            )
        current_result = original.result if isinstance(original.result, dict) else {}
        result_value = current_result.get("value", current_result)
        result_value = result_value if isinstance(result_value, dict) else {}
        source_items = result_value.get("items")
        source_items = source_items if isinstance(source_items, list) else []
        provider = str(original.payload.get("provider") or "telegram").strip().lower()
        if provider not in {"telegram", "rclone"}:
            raise DomainError(
                "STORAGE_RECONCILIATION_UNAVAILABLE",
                "Provider upload tidak didukung untuk rekonsiliasi.",
                status_code=409,
            )
        ambiguous: list[dict[str, Any]] = []
        profiles: list[str] = []
        for index, item in enumerate(source_items):
            if not isinstance(item, dict) or item.get("status") != "needs_reconciliation":
                continue
            raw_path = str(item.get("path") or "")
            path = PurePosixPath(raw_path)
            if (
                not raw_path
                or path.is_absolute()
                or any(part in {"", ".", ".."} for part in path.parts)
                or path.as_posix() != raw_path
            ):
                raise DomainError(
                    "STORAGE_RECONCILIATION_ITEM_INVALID",
                    "Checkpoint file untuk rekonsiliasi tidak valid.",
                    status_code=409,
                )
            profile_name = str(item.get("profile") or "").strip().lower()
            if profile_name:
                profiles.append(profile_name)
            candidate = {
                "index": index,
                "path": raw_path,
                "name": str(item.get("name") or path.name)[:255],
                "profile": profile_name,
            }
            if provider == "rclone":
                raw_target_path = str(item.get("target_path") or "")
                target_path = PurePosixPath(raw_target_path)
                if (
                    not raw_target_path
                    or target_path.is_absolute()
                    or any(part in {"", ".", ".."} for part in target_path.parts)
                    or target_path.as_posix() != raw_target_path
                ):
                    raise DomainError(
                        "STORAGE_RECONCILIATION_ITEM_INVALID",
                        "Path tujuan rclone untuk rekonsiliasi tidak valid.",
                        status_code=409,
                    )
                candidate["target_path"] = raw_target_path
            ambiguous.append(candidate)
        if not ambiguous:
            raise DomainError(
                "STORAGE_RECONCILIATION_UNAVAILABLE",
                "Tidak ada file ambigu yang menunggu rekonsiliasi.",
                status_code=409,
            )
        final_reconciliation = item_index is None or len(ambiguous) == 1
        if item_index is not None:
            selected_item = next(
                (item for item in ambiguous if item["index"] == item_index), None
            )
            if selected_item is None:
                raise DomainError(
                    "STORAGE_RECONCILIATION_ITEM_UNAVAILABLE",
                    "File ini tidak lagi menunggu verifikasi.",
                    status_code=409,
                )
            ambiguous = [selected_item]

        for candidate in self.jobs.list(
            actor_user_id=actor.telegram_user_id,
            profile=original.profile,
            kind="storage_reconcile",
            archived=False,
            offset=0,
            limit=1000,
        ):
            if (
                not candidate.status.terminal
                and candidate.worker == original.worker
                and str(candidate.payload.get("source_job_id") or "") == original.id
            ):
                active_index = candidate.payload.get("item_index")
                if item_index is None:
                    if active_index is None:
                        return candidate
                elif active_index is None or active_index == item_index:
                    return candidate
                raise DomainError(
                    "STORAGE_RECONCILIATION_IN_PROGRESS",
                    "Verifikasi file lain pada upload ini masih berjalan.",
                    status_code=409,
                )

        created_at = original.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        completed_at = original.updated_at
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)
        start_timestamp = max(0, int(created_at.timestamp()))
        end_timestamp = max(start_timestamp, int(completed_at.timestamp()))
        payload = {
            "source_job_id": original.id,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "_storage_reconcile_items": ambiguous,
        }
        if final_reconciliation:
            payload["_storage_reconcile_final_for_source"] = True
        if item_index is not None:
            payload["item_index"] = item_index
        if provider == "rclone":
            destination = str(original.payload.get("rclone_destination") or "").strip()
            try:
                validate_rclone_destination(destination)
            except ValueError as exc:
                raise DomainError(
                    "STORAGE_RECONCILIATION_SNAPSHOT_UNAVAILABLE",
                    "Snapshot tujuan rclone untuk rekonsiliasi tidak tersedia.",
                    status_code=409,
                ) from exc
            payload.update(
                _storage_reconcile_provider="rclone",
                provider="rclone",
                rclone_destination=destination,
                folder_path=str(original.payload.get("folder_path") or ""),
                transfer_mode=str(original.payload.get("transfer_mode") or "copy"),
            )
            private_values: dict[str, str] = {}
        else:
            target_chat = str(
                self.private_job_value(original.id, "tdl_storage_chat_ref") or ""
            ).strip()
            if self.gateway_mode == "lite":
                profiles = []
            else:
                profiles = list(dict.fromkeys(
                    [*profiles, *self._worker_profile_candidates(original.worker, "storage")]
                ))
                if not profiles:
                    profiles = [str(original.profile or "").strip().lower()]
                profiles = [profile for profile in profiles if profile]
            if not target_chat or (self.gateway_mode != "lite" and not profiles):
                raise DomainError(
                    "STORAGE_RECONCILIATION_SNAPSHOT_UNAVAILABLE",
                    "Snapshot tujuan Storage untuk rekonsiliasi tidak tersedia.",
                    status_code=409,
                )
            payload.update(
                _storage_reconcile_provider="telegram",
                _tdl_sender_profiles=profiles,
            )
            if self.gateway_mode == "lite":
                payload["_tdl_sender_profiles_use_worker_inventory"] = True
            else:
                payload["_tdl_sender_profile"] = profiles[0]
            private_values = {"tdl_storage_chat_ref": target_chat}
        return self.submit_job(
            actor,
            "storage_reconcile",
            payload,
            profile=original.profile,
            worker=original.worker,
            private_job_values=private_values,
        )

    def pause_job(self, actor: Actor, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
        self.require_profile(actor, job.profile)
        if not bool(job.payload.get("quick_mode")) and job.kind != "tts":
            raise DomainError("JOB_NOT_PAUSABLE", "Pause saat ini tersedia untuk Quick Mode dan TTS.", status_code=409)
        if job.status == JobStatus.PAUSED:
            return job
        if job.status.terminal:
            raise DomainError("JOB_NOT_PAUSABLE", "Job sudah selesai.", status_code=409)
        if job.status == JobStatus.QUEUED:
            sequence = self._next_job_event_sequence(job.id, fallback=job)
            self.append_worker_event(
                JobEvent(
                    job_id=job.id,
                    sequence=sequence,
                    status=JobStatus.PAUSED,
                    event_type="paused",
                    progress={"phase": job.progress.get("phase", "queued"), "pause_kind": "queued"},
                ),
                dispatch_pending=False,
            )
            return self.jobs.get(job.id) or job
        pause = getattr(self.dispatcher, "pause", None)
        if not callable(pause):
            raise DomainError("WORKER_PAUSE_UNAVAILABLE", "Worker belum mendukung pause.", status_code=503)
        try:
            paused = bool(pause(job.worker, job.id))
        except Exception as exc:
            raise DomainError(
                "WORKER_PAUSE_UNAVAILABLE",
                f"Worker {job.worker} tidak dapat menjeda job: {exc}",
                status_code=503,
            ) from exc
        if not paused:
            current = self.jobs.get(job.id)
            if current is not None and current.status == JobStatus.PAUSED:
                return current
            raise DomainError("JOB_NOT_PAUSABLE", "Worker tidak memiliki proses aktif yang dapat dijeda.", status_code=409)
        return self.jobs.get(job.id) or job

    def resume_job(self, actor: Actor, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
        self.require_profile(actor, job.profile)
        if job.status != JobStatus.PAUSED:
            raise DomainError("JOB_NOT_PAUSED", "Job tidak sedang dijeda.", status_code=409)
        sequence = self._next_job_event_sequence(job.id, fallback=job)
        self.append_worker_event(
            JobEvent(
                job_id=job.id,
                sequence=sequence,
                status=JobStatus.QUEUED,
                event_type="resumed_queued",
                progress={
                    "phase": job.progress.get("paused_phase") or job.progress.get("phase") or "queued",
                    "pause_kind": job.progress.get("pause_kind", "queued"),
                    "message": "Job masuk kembali ke antrean Quick Mode",
                },
            ),
            dispatch_pending=False,
        )
        self._dispatch_pending_jobs()
        return self.jobs.get(job.id) or job

    def set_quickmode_limit(self, worker: str, max_concurrent: int) -> dict[str, Any]:
        """Persist a worker's Quick Mode capacity and dispatch any new slots."""
        item = self.jobs.set_quickmode_limit(worker, max_concurrent)
        self._dispatch_pending_jobs()
        return item

    @staticmethod
    def _redacted_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if kind == "safelink_resolve":
            return {"submitted": True}
        if kind == "storage_reconcile":
            public_payload = {"source_job_id": str(payload.get("source_job_id") or "")}
            if isinstance(payload.get("item_index"), int) and not isinstance(
                payload.get("item_index"), bool
            ):
                public_payload["item_index"] = payload["item_index"]
            return public_payload
        if kind == "tdl_access_verify":
            return {"purpose": str(payload.get("purpose") or "")}
        if kind == "backup_verify":
            return {
                "run_id": str(payload.get("run_id") or ""),
                "node_name": str(payload.get("node_name") or ""),
                "part_discovery": "tdl_channel_caption_scan",
            }
        if kind == "tts":
            text = str(payload.get("text") or "")
            public = {
                "title": str(payload.get("title") or "")[:200],
                "character_count": len(text),
            }
            sender_profile = str(payload.get("_tdl_sender_profile") or "").strip()
            if sender_profile:
                public["sender_profile"] = sender_profile
            return public
        if kind == "storage_upload":
            public = {key: value for key, value in payload.items() if not str(key).startswith("_") and key != "tdl_access_target" and key != "_tdl_sender_profiles"}
            sender_profile = str(payload.get("_tdl_sender_profile") or "").strip()
            if sender_profile:
                public["sender_profile"] = sender_profile
            return public
        if kind == "storage_sync":
            return {"channel_id": int(payload.get("channel_id") or 0)}
        if kind == "storage_download":
            provider = str(payload.get("provider") or "")
            files = payload.get("files")
            sources = payload.get("rclone_sources")
            selection_count = (
                len(files) if isinstance(files, list)
                else len(sources) if isinstance(sources, list)
                else len(payload.get("item_ids") or []) + len(payload.get("folder_ids") or [])
            )
            return {
                "provider": provider,
                "selection_count": int(selection_count),
                "publish_public_links": payload.get("publish_public_links") is True,
            }
        if kind == "chat_send":
            return {
                "chat_ref": str(payload.get("chat_ref") or ""),
                "folders": list(payload.get("folders") or []),
                "profiles": list(payload.get("profiles") or []),
                "transfer_mode": str(payload.get("transfer_mode") or "copy"),
                "move_confirmed": payload.get("move_confirmed") is True,
            }
        if kind not in {"backup_node", "utility", "export"}:
            return dict(payload)
        if kind == "export" and not bool(payload.get("quick_mode")):
            return dict(payload)
        public_payload = {
            key: value
            for key, value in payload.items()
            if not str(key).startswith("_quick_storage_")
        }
        return _redact_secrets(public_payload)

    def _cancel_tts_deliveries(self, job_id: str) -> None:
        cancel = getattr(self.jobs, "cancel_tts_deliveries", None)
        if callable(cancel):
            cancel(job_id)

    def _apply_event_side_effects(self, job: Job, event: JobEvent) -> None:
        result = event.result or {}
        if isinstance(result, dict) and isinstance(result.get("value"), dict):
            result = result["value"]
        if job.kind == "storage_reconcile" and event.status.terminal and isinstance(result, dict):
            self._apply_storage_reconciliation_result(job, result)
        if job.kind == "storage_upload" and event.status.terminal and isinstance(result, dict):
            command = self.jobs.command_payload(job.id)
            nested_payload = command.get("payload") if isinstance(command, dict) else None
            payload = nested_payload if isinstance(nested_payload, dict) else (
                command if isinstance(command, dict) else {}
            )
            if payload.get("_storage_retry_of"):
                self._apply_storage_retry_result(job, result)
        if job.kind == "tdl_access_verify" and event.status == JobStatus.SUCCEEDED:
            store = self.tdl_access_store
            command = self.jobs.command_payload(job.id)
            payload = command.get("payload") if isinstance(command, dict) else None
            payload = payload if isinstance(payload, dict) else {}
            purpose = str(payload.get("purpose") or "")
            destination_hash = str(payload.get("destination_hash") or "")
            inventory_hash = str(result.get("inventory_hash") or "")
            profiles = result.get("profiles")
            session_fingerprints = (
                normalize_session_fingerprints(result.get("session_fingerprints"))
                if purpose in {"storage", "tts"}
                else None
            )
            inventory_matches = (
                purpose not in {"storage", "tts"}
                or (
                    store is not None
                    and isinstance(profiles, list)
                    and store.inventory_fingerprint(
                        normalize_profiles([
                            item.get("profile")
                            for item in profiles
                            if isinstance(item, dict)
                        ]),
                        None,
                    )
                    == inventory_hash
                )
            )
            if (
                store is not None
                and purpose
                and destination_hash
                and inventory_hash
                and isinstance(profiles, list)
                and inventory_matches
            ):
                try:
                    store.replace_results(
                        job.worker,
                        purpose,
                        destination_hash,
                        inventory_hash,
                        profiles,
                        session_fingerprints=None,
                    )
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Could not persist TDL access verification for job %s", job.id
                    )
        is_quick_mode_job = job.kind == "export" and bool(job.payload.get("quick_mode"))
        if (
            (job.kind == "storage_upload" or is_quick_mode_job)
            and event.event_type == "tdl_access.profile_denied"
            and self.tdl_access_store is not None
        ):
            profile = normalize_profiles([result.get("profile")])
            target = str(
                self.private_job_value(job.id, "tdl_storage_chat_ref")
                or ""
            ).strip()
            error_code = str(result.get("error_code") or "").strip().upper()
            proof_target = target or self._tdl_access_target("storage")
            proof_invalidator = getattr(self.tdl_access_store, "invalidate_profile", None)
            if profile and proof_target and callable(proof_invalidator):
                try:
                    proof_invalidator(
                        job.worker,
                        self.tdl_access_store.destination_fingerprint(proof_target),
                        profile[0],
                        None,
                        error_code or "TDL_ACCESS_DENIED",
                        purpose="storage",
                    )
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Could not invalidate Storage canary after a real TDL denial for job %s",
                        job.id,
                    )
            if is_quick_mode_job and profile and self.runtime_readiness_gate is not None:
                self.runtime_readiness_gate.record_quick_mode_failure(
                    worker=job.worker,
                    profile=job.profile,
                    error_code=error_code,
                )
            if profile and self.runtime_readiness_gate is not None:
                self.runtime_readiness_gate.invalidate_quick_mode_sender(
                    worker=job.worker,
                    sender_profile=profile[0],
                    reason_code=error_code or "TDL_ACCESS_NOT_VERIFIED",
                )
                self.runtime_readiness_gate.record_storage_failure(
                    worker=job.worker,
                    profile=profile[0],
                    error_code=error_code,
                )

        if (
            job.kind == "tts"
            and event.event_type == "tdl_access.profile_denied"
            and isinstance(result, dict)
        ):
            profiles = normalize_profiles([result.get("profile")])
            profile = profiles[0] if profiles else ""
            error_code = str(result.get("error_code") or "").strip().upper()
            proof_target = self.private_job_value(job.id, "telegram_tts_chat_id") or self._tdl_access_target("tts")
            proof_invalidator = getattr(self.tdl_access_store, "invalidate_profile", None)
            if profile and proof_target and callable(proof_invalidator):
                try:
                    proof_invalidator(
                        job.worker,
                        self.tdl_access_store.destination_fingerprint(proof_target),
                        profile,
                        None,
                        error_code or "TDL_ACCESS_DENIED",
                        purpose="tts",
                    )
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Could not invalidate TTS canary after a real TDL denial for job %s",
                        job.id,
                    )
            if profile and self.runtime_readiness_gate is not None:
                self.runtime_readiness_gate.record_tts_failure(
                    worker=job.worker,
                    profile=profile,
                    error_code=error_code,
                )
        if event.event_type == "storage.folder_discovered" and self.storage_catalog is not None:
            relative_path = str(result.get("relative_path", "")).strip()
            if relative_path:
                self.storage_catalog.ensure_path(
                    relative_path,
                    int(result.get("owner_user_id", job.actor_user_id)),
                    parent_id=(
                        int(result["destination_folder_id"])
                        if result.get("destination_folder_id") is not None
                        else None
                    ),
                )
        if (
            event.event_type in {"storage.item_uploaded", "storage.recovery_batch"}
            and self.storage_catalog is not None
        ):
            raw_items = (
                [result.get("item")]
                if event.event_type == "storage.item_uploaded"
                else result.get("items", [])
            )
            if isinstance(raw_items, list):
                for item in raw_items:
                    if not isinstance(item, dict):
                        continue
                    values = dict(item)
                    relative = str(values.pop("relative_folder", "") or "")
                    parent = values.get("folder_id")
                    if relative:
                        folder = self.storage_catalog.ensure_path(
                            relative,
                            int(values["owner_user_id"]),
                            parent_id=int(parent) if parent is not None else None,
                        )
                        values["folder_id"] = folder.id if folder else parent
                    self.storage_catalog.insert_item(**values)
        if event.event_type == "artifact.discovered" and self.export_catalog is not None:
            artifact = result.get("artifact")
            if isinstance(artifact, dict):
                # A media-less export is intentionally disposable and should
                # not become a downloadable artifact, even if an older or
                # incompatible worker accidentally reports it.
                if artifact.get("media_count") == 0:
                    return
                self.export_catalog.upsert(**artifact)
        if event.event_type == "artifact.inventory_batch" and self.export_catalog is not None:
            artifacts = result.get("artifacts")
            if isinstance(artifacts, list):
                self.export_catalog.upsert_many(
                    [
                        item
                        for item in artifacts
                        if isinstance(item, dict) and item.get("media_count") != 0
                    ]
                )
        if (
            event.event_type == "artifact.inventory_completed"
            and self.export_catalog is not None
        ):
            inventory = result.get("inventory")
            if isinstance(inventory, dict):
                self.export_catalog.complete_inventory(
                    str(inventory["profile"]),
                    str(inventory["worker"]),
                    str(inventory["inventory_id"]),
                )
        if event.event_type == "artifact.missing" and self.export_catalog is not None:
            artifact = result.get("artifact")
            if isinstance(artifact, dict):
                self.export_catalog.mark_missing(
                    str(artifact["profile"]),
                    str(artifact["worker"]),
                    str(artifact["artifact_key"]),
                )
        if (
            event.event_type in {
                "artifact.delete.completed",
                "artifact.delete.missing",
                "artifact.clear_failed.deleted",
                "artifact.clear_failed.missing",
            }
            and self.export_catalog is not None
        ):
            artifact_key = str(result.get("artifact_key") or "").strip()
            if artifact_key:
                artifact = self.export_catalog.get_by_key(
                    job.profile, job.worker, artifact_key
                )
                if artifact is not None:
                    if event.event_type in {
                        "artifact.delete.missing",
                        "artifact.clear_failed.missing",
                    }:
                        self.export_catalog.mark_missing(
                            job.profile, job.worker, artifact_key
                        )
                    else:
                        self.export_catalog.update_status(
                            str(artifact["id"]),
                            "deleted",
                            available=False,
                            error=None,
                            missing_at=None,
                        )
        if (
            job.kind == "artifact_delete"
            and event.status.terminal
            and self.export_catalog is not None
            and isinstance(result, dict)
        ):
            # Terminal summaries are a second source of per-file evidence if
            # the API was unavailable while individual delete events were in
            # flight. These catalog updates are safe to replay.
            for artifact_key in result.get("deleted", []) or []:
                key = str(artifact_key or "").strip()
                artifact = self.export_catalog.get_by_key(job.profile, job.worker, key) if key else None
                if artifact is not None:
                    self.export_catalog.update_status(
                        str(artifact["id"]),
                        "deleted",
                        available=False,
                        error=None,
                        missing_at=None,
                    )
            for artifact_key in result.get("missing", []) or []:
                key = str(artifact_key or "").strip()
                if key:
                    self.export_catalog.mark_missing(job.profile, job.worker, key)
        if event.event_type in {"artifact.downloaded", "artifact.failed"} and self.export_catalog is not None:
            artifact = result.get("artifact")
            if isinstance(artifact, dict):
                existing = self.export_catalog.get_by_key(
                    str(artifact["profile"]),
                    str(artifact["worker"]),
                    str(artifact["artifact_key"]),
                )
                if existing is not None:
                    self.export_catalog.update_status(
                        str(existing["id"]),
                        str(artifact["status"]),
                        download_directory=artifact.get("download_directory"),
                        error=artifact.get("error"),
                        completed_at=event.created_at.isoformat(),
                        available=True,
                        missing_at=None,
                    )
        if event.event_type == "backup.part_uploaded" and self.storage_catalog is not None:
            part = result.get("part")
            if isinstance(part, dict):
                self.storage_catalog.start_backup_run(
                    str(part["run_id"]), str(part["node_name"])
                )
                self.storage_catalog.upsert_backup_part(**part)
        if job.kind == "backup_node" and self.storage_catalog is not None:
            run_id = str(job.payload.get("backup_run_id", ""))
            node_name = str(job.payload.get("node_name", job.worker))
            if run_id and event.status == JobStatus.SUCCEEDED:
                self.storage_catalog.finish_backup_run(
                    run_id, node_name, "complete"
                )
            elif run_id and event.status == JobStatus.FAILED:
                self.storage_catalog.finish_backup_run(
                    run_id,
                    node_name,
                    "failed",
                    str((event.error or {}).get("message", "backup gagal")),
                )

    def _apply_storage_reconciliation_result(
        self, reconciliation_job: Job, result: dict[str, Any]
    ) -> None:
        source_job_id = str(reconciliation_job.payload.get("source_job_id") or "").strip()
        if not source_job_id:
            return
        with self._storage_source_action_lock(source_job_id):
            self._apply_storage_reconciliation_result_locked(
                reconciliation_job, result
            )

    def _apply_storage_reconciliation_result_locked(
        self, reconciliation_job: Job, result: dict[str, Any]
    ) -> None:
        source_job_id = str(result.get("source_job_id") or "").strip()
        source = self.jobs.get(source_job_id) if source_job_id else None
        if (
            source is None
            or source.kind != "storage_upload"
            or source.actor_user_id != reconciliation_job.actor_user_id
            or source.profile != reconciliation_job.profile
            or source.worker != reconciliation_job.worker
            or not source.status.terminal
            or str(reconciliation_job.payload.get("source_job_id") or "") != source.id
        ):
            return
        source_provider = str(source.payload.get("provider") or "telegram").strip().lower()
        result_provider = str(result.get("provider") or "telegram").strip().lower()
        if source_provider != result_provider:
            return
        source_result = source.result if isinstance(source.result, dict) else {}
        wrapped = isinstance(source_result.get("value"), dict)
        value = source_result.get("value", source_result)
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            return
        updated_items = [dict(item) if isinstance(item, dict) else item for item in value["items"]]
        seen: set[int] = set()
        expected_item_index = reconciliation_job.payload.get("item_index")
        for evidence in result.get("items", []) if isinstance(result.get("items"), list) else []:
            if not isinstance(evidence, dict):
                continue
            try:
                index = int(evidence.get("index"))
                match_count = max(0, int(evidence.get("match_count") or 0))
            except (TypeError, ValueError):
                continue
            if expected_item_index is not None and index != expected_item_index:
                continue
            if index in seen or index < 0 or index >= len(updated_items):
                continue
            seen.add(index)
            current = updated_items[index]
            if not isinstance(current, dict) or current.get("status") != "needs_reconciliation":
                continue
            if str(current.get("name") or "") != str(evidence.get("name") or ""):
                continue
            provider = str(source.payload.get("provider") or "telegram").strip().lower()
            if provider == "rclone" and str(current.get("target_path") or "") != str(
                evidence.get("target_path") or ""
            ):
                continue
            state = str(evidence.get("status") or "")
            if state == "succeeded" and match_count > 0:
                retryable = False
            elif state == "failed" and match_count == 0 and evidence.get("retryable") is True:
                retryable = True
            else:
                state = "needs_reconciliation"
                retryable = False
            current.update(
                status=state,
                retryable=retryable,
                reconciliation={
                    "job_id": reconciliation_job.id,
                    "status": state,
                    "match_count": match_count,
                },
            )
            error = str(evidence.get("error") or "")[:500]
            error_code = str(evidence.get("error_code") or "")[:100]
            if error:
                current["error"] = error
            else:
                current.pop("error", None)
            if error_code:
                current["error_code"] = error_code
            else:
                current.pop("error_code", None)
            if str(source.payload.get("transfer_mode") or "copy") == "move":
                current["upload_status"] = state
                if state == "succeeded":
                    cleanup = getattr(self.dispatcher, "storage_move_cleanup", None)
                    try:
                        if callable(cleanup):
                            cleanup_result = cleanup(
                                source.worker, source.id,
                                str(source.payload.get("folder_path") or ""),
                                str(current.get("path") or ""),
                            )
                            current["cleanup_status"] = str(
                                cleanup_result.get("cleanup_status") or "retained_unverified"
                            ) if isinstance(cleanup_result, dict) else "retained_unverified"
                        else:
                            current["cleanup_status"] = "retained_unverified"
                    except Exception:
                        current["cleanup_status"] = "cleanup_failed"
                    current.pop("source_identity", None)
                else:
                    current["cleanup_status"] = "retained_ambiguous"
            updated_items[index] = current
        if not seen:
            return
        value["items"] = updated_items
        value["total"] = len(updated_items)
        value["succeeded"] = sum(
            isinstance(item, dict) and item.get("status") == "succeeded"
            for item in updated_items
        )
        value["skipped"] = sum(
            isinstance(item, dict) and item.get("status") == "skipped"
            for item in updated_items
        )
        unresolved_items = [
            item for item in updated_items
            if not isinstance(item, dict)
            or item.get("status") not in {"succeeded", "skipped"}
        ]
        value["failed"] = unresolved_items
        value["retryable"] = any(
            isinstance(item, dict) and item.get("retryable") is True
            for item in unresolved_items
        )
        if unresolved_items:
            has_success = value["succeeded"] > 0 or value["skipped"] > 0
            value["outcome"] = (
                "partial_failure" if has_success
                else "needs_reconciliation"
                if any(
                    isinstance(item, dict) and item.get("status") == "needs_reconciliation"
                    for item in unresolved_items
                )
                else "failed"
            )
        else:
            value["outcome"] = "succeeded"
        value["skipped_items"] = [
            item for item in updated_items
            if isinstance(item, dict) and item.get("status") == "skipped"
        ]
        next_result = {**source_result, **({"value": value} if wrapped else value)}
        complete_reconciliation = getattr(
            self.jobs, "complete_storage_upload_reconciliation", None
        )
        if not unresolved_items and source.status == JobStatus.FAILED and callable(
            complete_reconciliation
        ):
            completion_progress = {
                "phase": "succeeded",
                "message": "Semua file terkonfirmasi pada tujuan Storage; upload tidak diulang.",
                "finished_at": utc_now().isoformat(),
                "overall": {"current": len(updated_items), "total": len(updated_items), "unit": "files"},
                "counters": {
                    "succeeded": value["succeeded"],
                    "failed": 0,
                    "skipped": value["skipped"],
                },
            }
            completed = complete_reconciliation(
                source.id,
                next_result,
                progress=completion_progress,
            )
            if isinstance(completed, Job) and completed.status == JobStatus.SUCCEEDED:
                applied = JobEvent(
                    job_id=completed.id,
                    sequence=completed.progress_sequence,
                    status=JobStatus.SUCCEEDED,
                    event_type="storage.reconciliation_applied",
                    progress=completion_progress,
                    result=next_result,
                    error=None,
                    created_at=completed.updated_at,
                )
                self._apply_event_side_effects(completed, applied)
                for observer in tuple(self._event_observers):
                    observer(applied)
        else:
            updater = getattr(self.jobs, "update_result", None)
            if callable(updater):
                updater(source.id, next_result)


def _elapsed_since(timestamp: str, now: datetime) -> float:
    try:
        started = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return 0.0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return max(0.0, (current - started).total_seconds())


def serializable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, (str, int, float, bool, type(None), list, dict)):
        return value
    return str(value)


def _redact_secrets(value: Any, key: str = "") -> Any:
    sensitive = {
        "password",
        "compress_password",
        "bot_token",
        "gateway_api_token",
        "worker_api_token",
        "frontend_service_token",
        "management_api_token",
        "backend_internal_token",
        "auth_jwt_secret",
    }
    if key.lower() in sensitive:
        return "***" if value else value
    if isinstance(value, dict):
        return {
            str(item_key): _redact_secrets(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _stored_worker_result_matches(stored: Any, incoming: Any) -> bool:
    """Accept the worker's original payload when backend metadata was added."""
    if isinstance(stored, dict) and isinstance(incoming, dict):
        return all(
            key in stored and _stored_worker_result_matches(stored[key], item)
            for key, item in incoming.items()
        )
    if isinstance(stored, list) and isinstance(incoming, list):
        return stored == incoming
    return stored == incoming


def _storage_sync_terminal_result_matches(stored: Any, incoming: Any) -> bool:
    """Match raw Storage Sync output to its sanitized applied completion."""
    if not isinstance(stored, dict) or not isinstance(incoming, dict):
        return False
    stored_value = stored.get("value")
    incoming_value = incoming.get("value")
    if not isinstance(stored_value, dict) or not isinstance(incoming_value, dict):
        return False
    normalized = dict(incoming_value)
    confirmed_missing = normalized.pop("confirmed_missing_message_ids", [])
    verification_failed = normalized.pop("verification_failed_message_ids", [])
    # Catalog application replaces the worker's history flag and proof ID
    # lists with the resulting flag and counts. Match the remaining original
    # fields and verify that both proof-list lengths were preserved.
    normalized.pop("history_complete", None)
    if not isinstance(confirmed_missing, list) or not isinstance(verification_failed, list):
        return False
    if len(confirmed_missing) != stored_value.get("confirmed_missing_count"):
        return False
    if len(verification_failed) != stored_value.get("verification_failed_count"):
        return False
    return _stored_worker_result_matches(stored_value, normalized)
