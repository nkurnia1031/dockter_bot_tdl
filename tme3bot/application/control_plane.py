from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, Callable

from tme3bot.application.ports import JobRepository, WorkerDispatcher
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
        self.worker_registry = worker_registry
        self.utility_folders = utility_folders
        self.utility_settings = utility_settings
        self.backup_coordinator = backup_coordinator
        self.storage_delivery = storage_delivery
        self.label_store = label_store
        self._event_observers: list[Callable[[JobEvent], None]] = []

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
        if selected != actor.profile:
            raise DomainError(
                "PROFILE_FORBIDDEN",
                "Actor tidak memiliki akses ke profile tersebut.",
                status_code=403,
            )
        return selected

    def submit_job(
        self,
        actor: Actor,
        kind: str,
        payload: dict[str, Any],
        *,
        profile: str | None = None,
        worker: str | None = None,
    ) -> Job:
        selected_profile = self.require_profile(actor, profile)
        selected_worker = worker or self.profile_manager.worker_route(selected_profile)
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
        dispatched = JobEvent(
            job_id=job.id,
            sequence=1,
            status=JobStatus.DISPATCHED,
            event_type="dispatched",
            progress={"worker": selected_worker},
        )
        job = self.jobs.append_event(dispatched)[0]
        command = {
            "job_id": job.id,
            "kind": kind,
            "profile": selected_profile,
            "actor_user_id": actor.telegram_user_id,
            "payload": payload,
        }
        try:
            self.dispatcher.dispatch(selected_worker, command)
            return self.jobs.get(job.id) or job
        except Exception as exc:
            failed = JobEvent(
                job_id=job.id,
                sequence=2,
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

    def append_worker_event(self, event: JobEvent) -> Job:
        job, inserted = self.jobs.append_event(event)
        # Side effects are idempotent and intentionally replayed when a worker
        # retries an already persisted event after a transient API failure.
        self._apply_event_side_effects(job, event)
        if inserted:
            for observer in tuple(self._event_observers):
                observer(event)
        return job

    def add_event_observer(self, observer: Callable[[JobEvent], None]) -> None:
        self._event_observers.append(observer)

    def set_worker_route(self, actor: Actor, route: str) -> str:
        if self.jobs.has_active(actor.profile):
            raise DomainError(
                "PROFILE_BUSY",
                "Profile masih memiliki job aktif; worker belum dapat diganti.",
                status_code=409,
            )
        return self.profile_manager.set_worker_route(actor.profile, route)

    def cancel_job(self, actor: Actor, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
        self.require_profile(actor, job.profile)
        if job.status.terminal:
            return job
        if not self.dispatcher.cancel(job.worker, job.id):
            raise DomainError(
                "JOB_NOT_CANCELLABLE",
                "Worker tidak dapat membatalkan job tersebut.",
                status_code=409,
            )
        sequence = max((item.sequence for item in self.jobs.events(job.id)), default=0) + 1
        return self.jobs.append_event(
            JobEvent(
                job_id=job.id,
                sequence=sequence,
                status=JobStatus.CANCELLED,
                event_type="cancelled",
            )
        )[0]

    @staticmethod
    def _redacted_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if kind not in {"backup_node", "utility"}:
            return dict(payload)
        return _redact_secrets(payload)

    def _apply_event_side_effects(self, job: Job, event: JobEvent) -> None:
        result = event.result or {}
        if event.event_type == "storage.item_uploaded" and self.storage_catalog is not None:
            item = result.get("item")
            if isinstance(item, dict):
                self.storage_catalog.insert_item(**item)
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
