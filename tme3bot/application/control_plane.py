from __future__ import annotations

import uuid
import threading
import time
from dataclasses import asdict
from typing import Any, Callable

from tme3bot.application.ports import JobRepository, WorkerDispatcher
from tme3bot.application.job_scheduler import build_execution_plan
from tme3bot.domain.models import Actor, DomainError, Job, JobEvent, JobStatus


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
        self._event_observers: list[Callable[[JobEvent], None]] = []
        self._scheduler_stop = threading.Event()
        self._scheduler_thread: threading.Thread | None = None

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
    ) -> Job:
        selected_profile, selected_worker = self.resolve_target(
            actor, profile=profile, worker=worker
        )
        available_profiles = ()
        list_profiles = getattr(self.profile_manager, "list_profiles", None)
        if callable(list_profiles):
            available_profiles = list_profiles()
        execution = build_execution_plan(
            kind,
            selected_profile,
            selected_worker,
            payload,
            available_profiles,
        )
        job = Job(
            id=str(uuid.uuid4()),
            kind=kind,
            profile=selected_profile,
            actor_user_id=actor.telegram_user_id,
            worker=selected_worker,
            status=JobStatus.QUEUED,
            payload=self._redacted_payload(kind, payload),
        )
        self.jobs.create(job)
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
        dispatched = JobEvent(
            job_id=job.id,
            sequence=1,
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
                self._dispatch_pending_jobs()
            except Exception:
                # A later tick retries; one unavailable worker must not stop
                # admission for every other profile.
                import logging

                logging.getLogger(__name__).exception("Pending job dispatch failed")

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
        job, inserted = self.jobs.append_event(event)
        # Side effects are idempotent and intentionally replayed when a worker
        # retries an already persisted event after a transient API failure.
        self._apply_event_side_effects(job, event)
        if inserted:
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

    def terminate_active_jobs(self, actor: Actor, *, profile: str | None = None) -> dict[str, int]:
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
                    error={"code": "JOB_TERMINATED", "message": "Job queued dibatalkan."},
                )
            )
            self.jobs.release_execution(job.id)
            self._dispatch_pending_jobs(job.profile)
            return self.jobs.get(job.id) or job
        if not self.dispatcher.cancel(job.worker, job.id):
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
        if kind not in {"backup_node", "utility"}:
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
