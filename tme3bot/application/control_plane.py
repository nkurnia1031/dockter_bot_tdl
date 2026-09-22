from __future__ import annotations

import uuid
import logging
import threading
import time
from copy import deepcopy
from dataclasses import asdict
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from tme3bot.application.ports import JobRepository, WorkerDispatcher
from tme3bot.application.job_scheduler import build_execution_plan
from tme3bot.domain.models import Actor, DomainError, Job, JobEvent, JobStatus, utc_now
from tme3bot.utility import DEFAULT_UTILITY_SETTINGS


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
        backup_coordinator=None,
        storage_delivery=None,
        label_store=None,
        job_stall_timeout_seconds: int = 600,
        job_cancel_grace_seconds: int = 30,
    ) -> None:
        self.jobs = jobs
        self.dispatcher = dispatcher
        self.profile_manager = profile_manager
        self.storage_catalog = storage_catalog
        self.export_catalog = export_catalog
        self.worker_registry = worker_registry
        self.utility_folders = utility_folders
        self.utility_settings = utility_settings
        self.backup_coordinator = backup_coordinator
        self.storage_delivery = storage_delivery
        self.label_store = label_store
        self.job_stall_timeout_seconds = max(0, int(job_stall_timeout_seconds))
        self.job_cancel_grace_seconds = max(0, int(job_cancel_grace_seconds))
        self._event_observers: list[Callable[[JobEvent], None]] = []
        self._scheduler_stop = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        self._stale_cancel_requested: dict[str, Any] = {}

    def actor(self, telegram_user_id: int) -> Actor:
        profile = self.profile_manager.profile_for_user(telegram_user_id)
        if profile is None:
            raise DomainError(
                "UNAUTHORIZED_ACTOR",
                "Telegram user belum memiliki identity TDL.",
                status_code=403,
            )
        return Actor(int(telegram_user_id), profile)

    def require_profile(self, actor: Actor, profile: str | None) -> str:
        selected = profile or actor.profile
        available = getattr(self.profile_manager, "list_profiles", None)
        profiles = list(available()) if callable(available) else []
        if profiles and selected not in profiles:
            raise DomainError(
                "PROFILE_NOT_FOUND",
                "Profile target tidak ditemukan.",
                status_code=404,
            )
        return selected

    def resolve_target(
        self, actor: Actor, *, profile: str | None = None, worker: str | None = None
    ) -> tuple[str, str]:
        selected_profile = self.require_profile(actor, profile)
        selected_worker = str(worker or self.profile_manager.worker_route(selected_profile)).strip().lower()
        if not selected_worker:
            raise DomainError("WORKER_REQUIRED", "Worker target wajib dipilih.", status_code=422)
        if self.worker_registry is not None:
            names = self.worker_registry.names()
            if names and selected_worker not in names:
                raise DomainError("WORKER_NOT_FOUND", "Worker target tidak ditemukan.", status_code=404)
            get_worker = getattr(self.worker_registry, "get", None)
            worker_record = get_worker(selected_worker) if callable(get_worker) else None
            if worker_record is not None and not bool(worker_record.get("enabled", True)):
                raise DomainError(
                    "WORKER_DISABLED",
                    "Worker sedang dinonaktifkan dan tidak menerima job baru.",
                    status_code=409,
                )
        return selected_profile, selected_worker

    def submit_job(
        self,
        actor: Actor,
        kind: str,
        payload: dict[str, Any],
        *,
        profile: str | None = None,
        worker: str | None = None,
        job_id: str | None = None,
    ) -> Job:
        selected_profile, selected_worker = self.resolve_target(
            actor, profile=profile, worker=worker
        )
        available_profiles = ()
        list_profiles = getattr(self.profile_manager, "list_profiles", None)
        if callable(list_profiles):
            available_profiles = list_profiles()
        job_id = str(job_id or uuid.uuid4())
        redacted_payload = self._redacted_payload(kind, payload)
        existing = self.jobs.get(job_id)
        if existing is not None and existing.status.terminal:
            # Retry is an in-place reset. The event stream remains attached to
            # the stable ID, while the current row becomes the new attempt.
            job = self.jobs.reset_for_retry(job_id, redacted_payload)
            retry_attempt = 1 + sum(
                1
                for event in self.jobs.events(job_id)
                if event.event_type == "retry_started"
            )
            retry_meta = payload.get("quick_retry") or payload.get("export_retry") or {}
            retry_meta = retry_meta if isinstance(retry_meta, dict) else {}
            retry_phase = str(
                retry_meta.get("resume_phase")
                or retry_meta.get("retry_phase")
                or "exporting"
            )
            sequence = max(
                (event.sequence for event in self.jobs.events(job_id)), default=0
            ) + 1
            self.jobs.append_event(
                JobEvent(
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
            )
            job = self.jobs.get(job_id) or job
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
                profile=selected_profile,
                actor_user_id=actor.telegram_user_id,
                worker=selected_worker,
                status=JobStatus.QUEUED,
                payload=redacted_payload,
            )
            self.jobs.create(job)
        retry_meta = payload.get("quick_retry") or {}
        retry_meta = retry_meta if isinstance(retry_meta, dict) else {}
        stable_stage_id = retry_meta.get("stage_job_id")
        execution = build_execution_plan(
            kind,
            selected_profile,
            selected_worker,
            payload,
            available_profiles,
            stage_job_id=(
                str(stable_stage_id or job_id)
                if kind == "export" and bool(payload.get("quick_mode"))
                else None
            ),
        )
        command = {
            "job_id": job.id,
            "kind": kind,
            "profile": selected_profile,
            "actor_user_id": actor.telegram_user_id,
            "worker": selected_worker,
            "execution": execution.as_dict(),
            "payload": payload,
        }
        self.jobs.save_execution_plan(job.id, execution.as_dict(), payload)
        admission = self.jobs.try_acquire_execution(job.id)
        self.jobs.set_queue_info(
            job.id, int(admission.get("position", 1)), admission.get("blocked_reason")
        )
        if not admission.get("admitted"):
            return self.jobs.get(job.id) or job
        try:
            self._dispatch_admitted_job(self.jobs.get(job.id) or job, command)
            return self.jobs.get(job.id) or job
        except Exception as exc:
            self.jobs.release_execution(job.id)
            sequence = max(
                (event.sequence for event in self.jobs.events(job.id)), default=0
            ) + 1
            failed = JobEvent(
                job_id=job.id,
                sequence=sequence,
                status=JobStatus.FAILED,
                event_type="dispatch_failed",
                error={"code": "WORKER_UNAVAILABLE", "message": str(exc)},
            )
            self.jobs.append_event(failed)
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Worker {selected_worker} tidak dapat menerima job: {exc}",
                status_code=503,
            ) from exc

    def _dispatch_admitted_job(self, job: Job, command: dict[str, Any]) -> None:
        sequence = max(
            (event.sequence for event in self.jobs.events(job.id)), default=0
        ) + 1
        command["event_sequence_start"] = sequence
        dispatched = JobEvent(
            job_id=job.id,
            sequence=sequence,
            status=JobStatus.DISPATCHED,
            event_type="dispatched",
            progress={"worker": job.worker, "position": 1},
        )
        self.jobs.append_event(dispatched)
        self.dispatcher.dispatch(job.worker, command)

    def start_scheduler(self) -> None:
        """Resume queued commands after backend restart or terminal events."""
        if self._scheduler_thread is not None:
            return
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="backend-job-dispatcher",
        )
        self._scheduler_thread.start()

    def stop_scheduler(self) -> None:
        self._scheduler_stop.set()

    def _scheduler_loop(self) -> None:
        while not self._scheduler_stop.wait(2.0):
            try:
                self._recover_stale_jobs()
                self._dispatch_pending_jobs()
            except Exception:
                # A later tick retries; one unavailable worker must not stop
                # admission for every other profile.
                import logging

                logging.getLogger(__name__).exception("Pending job dispatch failed")

    def _recover_stale_jobs(self, *, now=None) -> None:
        """Cancel jobs whose worker has stopped reporting progress.

        Worker cancellation is deliberately best-effort.  The backend still
        needs a terminal state when a worker, network connection, or a child
        process is wedged, otherwise the lane remains occupied forever.
        """
        if self.job_stall_timeout_seconds <= 0:
            return
        current_time = now or utc_now()
        active_statuses = (JobStatus.DISPATCHED.value, JobStatus.RUNNING.value)
        active_ids: set[str] = set()
        forced = False
        for status in active_statuses:
            for job in self.jobs.list(
                status=status,
                archived=False,
                offset=0,
                limit=1000,
            ):
                active_ids.add(job.id)
                updated_at = job.updated_at or job.created_at
                age = (current_time - updated_at).total_seconds()
                if age <= self.job_stall_timeout_seconds:
                    self._stale_cancel_requested.pop(job.id, None)
                    continue

                requested_at = self._stale_cancel_requested.get(job.id)
                if requested_at is None:
                    try:
                        signalled = bool(self.dispatcher.cancel(job.worker, job.id))
                    except Exception:
                        logging.getLogger(__name__).exception(
                            "Stale job cancellation failed for %s", job.id
                        )
                        signalled = False
                    if signalled:
                        self._stale_cancel_requested[job.id] = current_time
                    else:
                        self._force_cancel_stale_job(job, age)
                        forced = True
                    continue

                grace_age = (current_time - requested_at).total_seconds()
                if grace_age >= self.job_cancel_grace_seconds:
                    self._force_cancel_stale_job(job, age)
                    forced = True

        for job_id in tuple(self._stale_cancel_requested):
            if job_id not in active_ids:
                self._stale_cancel_requested.pop(job_id, None)
        if forced:
            self._dispatch_pending_jobs()

    def _force_cancel_stale_job(self, job: Job, age_seconds: float) -> None:
        current = self.jobs.get(job.id)
        if current is None or current.status.terminal:
            self._stale_cancel_requested.pop(job.id, None)
            return
        sequence = max(
            (item.sequence for item in self.jobs.events(job.id)), default=0
        ) + 1
        phase = str(job.progress.get("phase") or "cancelled")
        self.jobs.append_event(
            JobEvent(
                job_id=job.id,
                sequence=sequence,
                status=JobStatus.CANCELLED,
                event_type="backend_stall_cancelled",
                progress={
                    "phase": phase,
                    "terminal_phase": "cancelled",
                    "finished_at": utc_now().isoformat(),
                    "stale_seconds": round(age_seconds, 1),
                },
                error={
                    "code": "JOB_STALLED",
                    "message": (
                        "Job dibatalkan backend karena tidak ada progress "
                        f"selama {round(age_seconds)} detik."
                    ),
                },
            )
        )
        self.jobs.release_execution(job.id)
        self._stale_cancel_requested.pop(job.id, None)

    def _dispatch_pending_jobs(self, profile: str | None = None) -> None:
        list_profiles = getattr(self.profile_manager, "list_profiles", None)
        profiles = [profile] if profile else (
            list(list_profiles()) if callable(list_profiles) else []
        )
        if profile is None and not profiles:
            profiles = sorted(
                {
                    item.profile
                    for item in self.jobs.list(status=JobStatus.QUEUED.value, limit=200)
                }
            )
        for selected in profiles:
            for queued in self.jobs.list(
                profile=selected,
                status=JobStatus.QUEUED.value,
                archived=False,
                offset=0,
                limit=200,
            ):
                admission = self.jobs.try_acquire_execution(queued.id)
                self.jobs.set_queue_info(
                    queued.id,
                    int(admission.get("position", 1)),
                    admission.get("blocked_reason"),
                )
                if not admission.get("admitted"):
                    continue
                command_payload = self.jobs.command_payload(queued.id)
                if not isinstance(command_payload, dict):
                    self.jobs.release_execution(queued.id)
                    sequence = max((event.sequence for event in self.jobs.events(queued.id)), default=0) + 1
                    self.jobs.append_event(
                        JobEvent(
                            job_id=queued.id,
                            sequence=sequence,
                            status=JobStatus.FAILED,
                            event_type="dispatch_failed",
                            error={
                                "code": "LEGACY_COMMAND_UNAVAILABLE",
                                "message": "Payload internal job lama tidak tersedia setelah migrasi scheduler.",
                            },
                        )
                    )
                    continue
                command = {
                    "job_id": queued.id,
                    "kind": queued.kind,
                    "profile": queued.profile,
                    "worker": queued.worker,
                    "actor_user_id": queued.actor_user_id,
                    "execution": self.jobs.execution_plan(queued.id) or {},
                    "payload": command_payload,
                }
                try:
                    self._dispatch_admitted_job(queued, command)
                except Exception as exc:
                    self.jobs.release_execution(queued.id)
                    sequence = max((event.sequence for event in self.jobs.events(queued.id)), default=0) + 1
                    self.jobs.append_event(
                        JobEvent(
                            job_id=queued.id,
                            sequence=sequence,
                            status=JobStatus.FAILED,
                            event_type="dispatch_failed",
                            error={"code": "WORKER_UNAVAILABLE", "message": str(exc)},
                        )
                    )

    def append_worker_event(self, event: JobEvent) -> Job:
        current = self.jobs.get(event.job_id)
        if current is None:
            raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
        if current.status.terminal:
            # A worker can finish an interrupt race after the backend already
            # forced a terminal state.  Do not turn that harmless late event
            # into an INTERNAL_ERROR or resurrect the lane.
            logging.getLogger(__name__).warning(
                "Ignoring late worker event %s for terminal job %s",
                event.event_type,
                event.job_id,
            )
            return current
        # A reused job ID keeps its old event history. Events from an older
        # worker attempt therefore have a sequence at or below the last
        # persisted event and must not be applied to the new attempt.
        latest_sequence = max(
            (item.sequence for item in self.jobs.events(event.job_id)), default=0
        )
        if event.sequence <= latest_sequence:
            return current
        job, inserted = self.jobs.append_event(event)
        self._stale_cancel_requested.pop(event.job_id, None)
        # Side effects are idempotent and intentionally replayed when a worker
        # retries an already persisted event after a transient API failure.
        self._apply_event_side_effects(job, event)
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
                plan = self.jobs.execution_plan(job.id) or {}
                current_keys = set(plan.get("resource_keys") or [])
                export_keys = {
                    key
                    for key in current_keys
                    if ":kind:export" in str(key) or ":tdl:export" in str(key)
                }
                if export_keys:
                    remaining = current_keys - export_keys
                    replacer = getattr(self.jobs, "replace_execution_resources", None)
                    if callable(replacer) and replacer(job.id, remaining):
                        self._dispatch_pending_jobs()
            if event.status.terminal:
                self.jobs.release_execution(job.id)
            for observer in tuple(self._event_observers):
                observer(event)
            if event.status.terminal:
                self._dispatch_pending_jobs()
        return job

    def update_worker_progress(self, event: JobEvent) -> Job:
        """Update the latest telemetry without growing persistent event history."""
        job, _ = self.jobs.update_progress_snapshot(event)
        return job

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
        interrupted = forced = 0
        for job in active:
            try:
                signalled = (
                    False
                    if job.status == JobStatus.QUEUED
                    else bool(self.dispatcher.cancel(job.worker, job.id))
                )
            except Exception:
                signalled = False
            if signalled:
                interrupted += 1
                continue
            sequence = max((item.sequence for item in self.jobs.events(job.id)), default=0) + 1
            self.jobs.append_event(
                JobEvent(
                    job_id=job.id,
                    sequence=sequence,
                    status=JobStatus.CANCELLED,
                    event_type="force_cancelled",
                    progress={
                        "phase": "cancelled",
                        "finished_at": utc_now().isoformat(),
                    },
                    error={
                        "code": "JOB_TERMINATED_STALE",
                        "message": "Job dihentikan karena worker tidak lagi memiliki proses aktif.",
                    },
                )
            )
            self.jobs.release_execution(job.id)
            forced += 1
        if forced:
            self._dispatch_pending_jobs(selected_profile)
        return {"total": len(active), "interrupted": interrupted, "force_cancelled": forced}

    def retry_job(
        self,
        actor: Actor,
        job_id: str,
        *,
        resume_phase: str | None = None,
        single_phase: bool = False,
    ) -> Job:
        """Restart an export attempt while preserving its stable job ID."""
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

    def cancel_job(self, actor: Actor, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
        self.require_profile(actor, job.profile)
        if job.status.terminal:
            return job
        if job.status == JobStatus.QUEUED:
            sequence = max((item.sequence for item in self.jobs.events(job.id)), default=0) + 1
            self.jobs.append_event(
                JobEvent(
                    job_id=job.id,
                    sequence=sequence,
                    status=JobStatus.CANCELLED,
                    event_type="cancelled_queued",
                    progress={
                        "phase": "cancelled",
                        "finished_at": utc_now().isoformat(),
                    },
                    error={"code": "JOB_TERMINATED", "message": "Job queued dibatalkan."},
                )
            )
            self.jobs.release_execution(job.id)
            self._dispatch_pending_jobs(job.profile)
            return self.jobs.get(job.id) or job
        try:
            cancelled = self.dispatcher.cancel(job.worker, job.id)
        except Exception as exc:
            current = self.jobs.get(job.id)
            if current is not None and current.status.terminal:
                return current
            raise DomainError(
                "WORKER_CANCEL_UNAVAILABLE",
                f"Worker {job.worker} tidak dapat menerima permintaan terminate: {exc}",
                status_code=503,
            ) from exc
        if not cancelled:
            current = self.jobs.get(job.id)
            if current is not None and current.status.terminal:
                return current
            raise DomainError(
                "JOB_NOT_CANCELLABLE",
                "Worker tidak memiliki proses aktif yang dapat dihentikan.",
                status_code=409,
            )
        # The worker emits the terminal ``cancelled`` event only after the
        # interrupted process has actually stopped. Marking it terminal here
        # would reject late log/final events and make the UI lie about a still
        # running process.
        return self.jobs.get(job.id) or job

    @staticmethod
    def _redacted_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if kind not in {"backup_node", "utility", "export"}:
            return dict(payload)
        if kind == "export" and not bool(payload.get("quick_mode")):
            return dict(payload)
        return _redact_secrets(payload)

    def _apply_event_side_effects(self, job: Job, event: JobEvent) -> None:
        result = event.result or {}
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
        if event.event_type == "storage.item_uploaded" and self.storage_catalog is not None:
            item = result.get("item")
            if isinstance(item, dict):
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
