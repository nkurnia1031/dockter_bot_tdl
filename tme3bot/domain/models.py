from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DomainError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class JobStatus(str, Enum):
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }


ALLOWED_JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {
        JobStatus.DISPATCHED,
        JobStatus.RUNNING,
        JobStatus.PAUSED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.DISPATCHED: {
        JobStatus.RUNNING,
        JobStatus.PAUSED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.RUNNING: {
        JobStatus.PAUSED,
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.PAUSED: {
        JobStatus.QUEUED,
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.SUCCEEDED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


class AuthChallengeStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    CONSUMED = "consumed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class Actor:
    telegram_user_id: int
    profile: str
    authorized: bool = True


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    profile: str
    actor_user_id: int
    worker: str
    status: JobStatus
    payload: dict[str, Any]
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    archived_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def ensure_transition(self, target: JobStatus) -> None:
        if target == self.status:
            return
        if target not in ALLOWED_JOB_TRANSITIONS[self.status]:
            raise DomainError(
                "INVALID_JOB_TRANSITION",
                f"Job tidak dapat berubah dari {self.status.value} ke {target.value}.",
                status_code=409,
            )


@dataclass(frozen=True)
class JobEvent:
    job_id: str
    sequence: int
    status: JobStatus
    event_type: str
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utc_now)
