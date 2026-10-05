from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from tme3bot.domain.models import DomainError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OperationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    WAITING_WORKER = "waiting_worker"
    PAUSED = "paused"
    NEEDS_RECONCILIATION = "needs_reconciliation"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


_ALLOWED_TRANSITIONS: dict[OperationStatus, set[OperationStatus]] = {
    OperationStatus.QUEUED: {
        OperationStatus.RUNNING, OperationStatus.WAITING_USER,
        OperationStatus.WAITING_WORKER, OperationStatus.PAUSED,
        OperationStatus.NEEDS_RECONCILIATION, OperationStatus.CANCELLING,
        OperationStatus.FAILED, OperationStatus.CANCELLED,
    },
    OperationStatus.RUNNING: {
        OperationStatus.WAITING_USER, OperationStatus.WAITING_WORKER,
        OperationStatus.PAUSED, OperationStatus.NEEDS_RECONCILIATION,
        OperationStatus.CANCELLING, OperationStatus.SUCCEEDED,
        OperationStatus.FAILED, OperationStatus.CANCELLED,
    },
    OperationStatus.WAITING_USER: {
        OperationStatus.QUEUED, OperationStatus.RUNNING,
        OperationStatus.CANCELLING, OperationStatus.FAILED,
        OperationStatus.CANCELLED,
    },
    OperationStatus.WAITING_WORKER: {
        OperationStatus.QUEUED, OperationStatus.RUNNING,
        OperationStatus.NEEDS_RECONCILIATION, OperationStatus.CANCELLING,
        OperationStatus.FAILED, OperationStatus.CANCELLED,
    },
    OperationStatus.PAUSED: {
        OperationStatus.QUEUED, OperationStatus.RUNNING,
        OperationStatus.CANCELLING, OperationStatus.FAILED,
        OperationStatus.CANCELLED,
    },
    OperationStatus.NEEDS_RECONCILIATION: {
        OperationStatus.SUCCEEDED, OperationStatus.FAILED,
        OperationStatus.CANCELLED,
    },
    OperationStatus.CANCELLING: {
        OperationStatus.NEEDS_RECONCILIATION, OperationStatus.SUCCEEDED,
        OperationStatus.FAILED, OperationStatus.CANCELLED,
    },
    OperationStatus.SUCCEEDED: set(),
    OperationStatus.FAILED: set(),
    OperationStatus.CANCELLED: set(),
}


def ensure_operation_transition(
    current: OperationStatus,
    target: OperationStatus,
    *,
    retry: bool = False,
) -> None:
    if current == target:
        return
    if retry and current in {OperationStatus.FAILED, OperationStatus.CANCELLED} and target == OperationStatus.QUEUED:
        return
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise DomainError(
            "INVALID_OPERATION_TRANSITION",
            f"Operation tidak dapat berubah dari {current.value} ke {target.value}.",
            status_code=409,
        )


@dataclass(frozen=True)
class Operation:
    id: str
    kind: str
    actor_user_id: int
    profile: str
    target: dict[str, Any]
    status: OperationStatus
    phase: str
    revision: int
    attempt: int
    progress: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None
    error: dict[str, str] | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    dismissed: bool = False

    def to_public(self, *, status_url: str | None = None) -> dict[str, Any]:
        return {
            "operation_id": self.id,
            "kind": self.kind,
            "profile": self.profile,
            "target": self.target,
            "status": self.status.value,
            "phase": self.phase,
            "revision": self.revision,
            "attempt": self.attempt,
            "progress": self.progress,
            "job_id": self.job_id,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "dismissed": self.dismissed,
            **({"status_url": status_url} if status_url else {}),
        }
