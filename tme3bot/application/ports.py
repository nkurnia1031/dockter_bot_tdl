from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from tme3bot.domain.models import Job, JobEvent
from tme3bot.domain.operations import Operation, OperationStatus


class JobRepository(Protocol):
    def create(self, job: Job) -> Job: ...

    def get(self, job_id: str) -> Job | None: ...

    def reset_for_retry(self, job_id: str, payload: dict[str, Any]) -> Job: ...

    def list(
        self,
        *,
        actor_user_id: int | None = None,
        profile: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        worker: str | None = None,
        quick_mode: bool | None = None,
        archived: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Job]: ...

    def count(
        self,
        *,
        profile: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        worker: str | None = None,
        quick_mode: bool | None = None,
        archived: bool | None = None,
    ) -> int: ...

    def command_payload(self, job_id: str) -> dict[str, Any] | None: ...

    def try_acquire_execution(self, job_id: str) -> dict[str, Any]: ...

    def set_queue_info(self, job_id: str, position: int, reason: str | None) -> None: ...

    def monitor_metrics(
        self,
        *,
        profile: str | None = None,
        worker: str | None = None,
        now=None,
    ) -> dict[str, Any]: ...

    def release_execution(self, job_id: str) -> None: ...

    def replace_execution_resources(
        self, job_id: str, resource_keys: set[str] | list[str] | tuple[str, ...]
    ) -> bool: ...

    def append_event(self, event: JobEvent) -> tuple[Job, bool]: ...

    def update_progress_snapshot(self, event: JobEvent) -> tuple[Job, bool]: ...

    def events(self, job_id: str, *, after_sequence: int = 0) -> list[JobEvent]: ...

    def has_active(self, profile: str) -> bool: ...

    def create_telegram_notification(
        self,
        job_id: str,
        telegram_user_id: int,
        telegram_chat_id: int,
        profile: str,
    ) -> dict[str, Any]: ...

    def pending_telegram_notifications(self, limit: int = 100) -> list[dict[str, Any]]: ...

    def update_telegram_notification(
        self, notification_id: int, values: dict[str, Any]
    ) -> dict[str, Any] | None: ...


class OperationRepository(Protocol):
    def find_idempotent(self, actor_user_id: int, action: str, key_sha256: str, payload_sha256: str) -> Operation | None: ...

    def create_submission(self, operation: Operation, **values) -> tuple[Operation, bool]: ...

    def get_for_actor(self, operation_id: str, actor_user_id: int) -> Operation | None: ...

    def list_for_actor(self, actor_user_id: int, *, status: str | None, offset: int, limit: int) -> tuple[list[Operation], bool]: ...

    def apply_action(self, **values) -> tuple[Operation, bool]: ...

    def set_visibility(self, **values) -> tuple[Operation, bool]: ...

    def get_by_job_id(self, job_id: str) -> Operation | None: ...

    def transition_from_job(self, operation_id: str, *, expected_revision: int, status: OperationStatus, phase: str, safe_progress: dict[str, Any]) -> Operation | None: ...


class WorkerDispatcher(Protocol):
    def dispatch(self, worker: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def cancel(self, worker: str, job_id: str) -> bool: ...

    def worker_settings(self, worker: str) -> dict[str, Any]: ...

    def update_worker_settings(
        self, worker: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    def quickmode_scan(self, worker: str) -> dict[str, Any]: ...


class ActorResolver(Protocol):
    def resolve(self, telegram_user_id: int): ...


class ProfileStateStore(Protocol):
    """Profile-scoped source state used by export and metadata endpoints."""

    def load(self) -> Any: ...

    def get_source(self, chat_ref: str) -> Any | None: ...

    def list_sources(self) -> list[tuple[str, Any]]: ...

    def upsert_source(
        self,
        chat_ref: str,
        label: str | None,
        last_id: int,
        warmup_url: str | None = None,
        warmup_done: bool | None = None,
    ) -> Any: ...

    def mark_warmup_done(self, chat_ref: str) -> None: ...

    def delete_source(self, chat_ref: str) -> bool: ...

    def delete_sources(self, chat_refs: Iterable[str]) -> list[str]: ...


class SourceRepository(Protocol):
    """Backend-owned source records with atomic revision-checked commits."""

    def is_enabled(self) -> bool: ...

    def set_enabled(self, enabled: bool) -> None: ...

    def get_source(self, profile: str, chat_ref: str) -> Any | None: ...

    def list_sources(self, profile: str) -> list[tuple[str, Any]]: ...

    def upsert_source(
        self,
        profile: str,
        chat_ref: str,
        label: str | None,
        last_id: int,
        warmup_url: str | None = None,
        warmup_done: bool | None = None,
    ) -> Any: ...

    def commit_source(
        self,
        profile: str,
        chat_ref: str,
        source: Any,
        *,
        expected_revision: int,
        peer_type: str | None = None,
        peer_id: str | None = None,
    ) -> Any: ...

    def mark_warmup_done(self, profile: str, chat_ref: str) -> None: ...

    def delete_sources(self, profile: str, chat_refs: Iterable[str]) -> list[str]: ...


class StorageDelivery(Protocol):
    def deliver(self, item: Any, telegram_user_id: int) -> dict[str, Any]: ...
