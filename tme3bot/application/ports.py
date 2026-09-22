from __future__ import annotations

from typing import Any, Protocol

from tme3bot.domain.models import Job, JobEvent


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


class WorkerDispatcher(Protocol):
    def dispatch(self, worker: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def cancel(self, worker: str, job_id: str) -> bool: ...

    def quickmode_scan(self, worker: str) -> dict[str, Any]: ...


class ActorResolver(Protocol):
    def resolve(self, telegram_user_id: int): ...


class StorageDelivery(Protocol):
    def deliver(self, item: Any, telegram_user_id: int) -> dict[str, Any]: ...
