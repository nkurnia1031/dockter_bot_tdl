from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from tme3bot.domain.models import Actor, DomainError, Job, JobEvent, JobStatus
from tme3bot.domain.operations import Operation, OperationStatus, ensure_operation_transition, utc_now
from tme3bot.application.ports import OperationRepository


@dataclass(frozen=True)
class PreparedOperation:
    profile: str
    target: dict[str, Any]
    private_payload: dict[str, Any]
    phase: str = "queued"
    job: Job | None = None
    execution_plan: dict[str, Any] | None = None
    command_payload: dict[str, Any] | None = None


class OperationHandler(Protocol):
    def __call__(self, actor: Actor, target: dict[str, Any], input_data: dict[str, Any]) -> PreparedOperation: ...


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DomainError("OPERATION_INPUT_INVALID", "Input operation harus berupa JSON yang valid.", status_code=422) from exc


class OperationsService:
    """Validates bounded actions and persists them without executing side effects."""

    MAX_REQUEST_BYTES = 1024 * 1024
    MAX_TARGET_BYTES = 16 * 1024

    def __init__(self, store: OperationRepository, handlers: Mapping[str, OperationHandler] | None = None) -> None:
        self.store = store
        self._handlers = dict(handlers or {})
        self._command_handlers: dict[str, Any] = {}

    def register_command_handler(self, topic: str, handler) -> None:
        normalized = str(topic or "").strip().lower()
        if not re.fullmatch(r"operation\.[a-z][a-z0-9_.-]{0,62}", normalized):
            raise ValueError("Nama operation command tidak valid.")
        if not callable(handler):
            raise ValueError("Command handler harus callable.")
        self._command_handlers[normalized] = handler

    def command_handler(self, topic: str):
        return self._command_handlers.get(str(topic or "").strip().lower())

    def supports_command(self, topic: str) -> bool:
        return self.command_handler(topic) is not None

    def register_handler(self, kind: str, handler: OperationHandler) -> None:
        normalized = str(kind or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", normalized):
            raise ValueError("Nama operation kind tidak valid.")
        self._handlers[normalized] = handler

    def supported_kinds(self) -> list[str]:
        return sorted(self._handlers)

    @staticmethod
    def _idempotency_hash(key: str) -> str:
        value = str(key or "").strip()
        if not value or len(value) > 200:
            raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key wajib diisi dan maksimal 200 karakter.", status_code=422)
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _payload_hash(payload: Any) -> str:
        return hashlib.sha256(_canonical(payload)).hexdigest()

    def submit(
        self, actor: Actor, *, kind: str, target: dict[str, Any],
        input_data: dict[str, Any], idempotency_key: str,
    ) -> tuple[Operation, bool]:
        normalized_kind = str(kind or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", normalized_kind):
            raise DomainError("OPERATION_KIND_INVALID", "Kind operation tidak valid.", status_code=422)
        if not isinstance(target, dict) or not isinstance(input_data, dict):
            raise DomainError("OPERATION_REQUEST_INVALID", "Target dan input harus berupa object.", status_code=422)
        request = {"kind": normalized_kind, "target": target, "input": input_data}
        request_bytes = _canonical(request)
        if len(request_bytes) > self.MAX_REQUEST_BYTES:
            raise DomainError("OPERATION_INPUT_TOO_LARGE", "Input operation melebihi batas ukuran.", status_code=413)
        if len(_canonical(target)) > self.MAX_TARGET_BYTES:
            raise DomainError("OPERATION_TARGET_TOO_LARGE", "Target operation melebihi batas ukuran.", status_code=422)
        key_hash = self._idempotency_hash(idempotency_key)
        payload_hash = hashlib.sha256(request_bytes).hexdigest()
        previous = self.store.find_idempotent(actor.telegram_user_id, "submit", key_hash, payload_hash)
        if previous is not None:
            return previous, False
        handler = self._handlers.get(normalized_kind)
        if handler is None:
            raise DomainError(
                "OPERATION_KIND_UNAVAILABLE",
                "Kind operation belum memiliki handler aktif.",
                status_code=422,
                details={"kind": normalized_kind, "supported_kinds": self.supported_kinds()},
            )
        prepared = handler(actor, target, input_data)
        if not isinstance(prepared, PreparedOperation):
            raise DomainError("OPERATION_HANDLER_INVALID", "Handler operation menghasilkan kontrak yang tidak valid.", status_code=500)
        if prepared.job is not None:
            if prepared.execution_plan is None or prepared.command_payload is None:
                raise DomainError("OPERATION_HANDLER_INVALID", "Job membutuhkan execution plan dan command.", status_code=500)
            if prepared.job.actor_user_id != actor.telegram_user_id or prepared.job.profile != prepared.profile:
                raise DomainError("OPERATION_HANDLER_INVALID", "Job operation tidak cocok dengan actor atau profile.", status_code=500)
        if len(_canonical(prepared.target)) > self.MAX_TARGET_BYTES:
            raise DomainError("OPERATION_TARGET_TOO_LARGE", "Target publik handler melebihi batas ukuran.", status_code=500)
        now = utc_now()
        operation = Operation(
            id=str(uuid.uuid4()), kind=normalized_kind,
            actor_user_id=int(actor.telegram_user_id), profile=str(prepared.profile),
            target=prepared.target, status=OperationStatus.QUEUED,
            phase=str(prepared.phase or "queued"), revision=1, attempt=1,
            job_id=prepared.job.id if prepared.job else None,
            created_at=now, updated_at=now,
        )
        return self.store.create_submission(
            operation,
            private_payload=prepared.private_payload,
            request_sha256=payload_hash,
            key_sha256=key_hash,
            job=prepared.job,
            execution_plan=prepared.execution_plan,
            command_payload=prepared.command_payload,
        )

    def get(self, actor: Actor, operation_id: str) -> Operation:
        operation = self.store.get_for_actor(operation_id, actor.telegram_user_id)
        if operation is None:
            raise DomainError("OPERATION_NOT_FOUND", "Operation tidak ditemukan.", status_code=404)
        return operation

    def list(
        self, actor: Actor, *, status: str | None = None, cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[Operation], str | None]:
        if status is not None:
            try:
                OperationStatus(status)
            except ValueError as exc:
                raise DomainError("OPERATION_STATUS_INVALID", "Status operation tidak valid.", status_code=422) from exc
        try:
            offset = max(0, int(cursor or "0"))
        except (TypeError, ValueError) as exc:
            raise DomainError("OPERATION_CURSOR_INVALID", "Cursor harus berupa offset numerik.", status_code=422) from exc
        selected_limit = max(1, min(int(limit), 100))
        items, has_more = self.store.list_for_actor(
            actor.telegram_user_id, status=status, offset=offset, limit=selected_limit
        )
        next_cursor = str(offset + len(items)) if has_more else None
        return items, next_cursor

    def cancel(self, actor: Actor, operation_id: str, idempotency_key: str) -> tuple[Operation, bool]:
        key_hash = self._idempotency_hash(idempotency_key)
        request_hash = self._payload_hash({"operation_id": operation_id, "action": "cancel"})
        previous = self.store.find_idempotent(actor.telegram_user_id, "cancel", key_hash, request_hash)
        if previous is not None:
            return previous, False
        operation = self.get(actor, operation_id)
        if operation.status == OperationStatus.CANCELLING:
            return operation, False
        ensure_operation_transition(operation.status, OperationStatus.CANCELLING)
        return self.store.apply_action(
            operation_id=operation_id, actor_user_id=actor.telegram_user_id,
            action="cancel", key_sha256=key_hash, payload_sha256=request_hash,
            expected_revision=operation.revision,
            target_status=OperationStatus.CANCELLING, phase="cancelling",
            topic="operation.cancel",
        )

    def retry(self, actor: Actor, operation_id: str, idempotency_key: str) -> tuple[Operation, bool]:
        key_hash = self._idempotency_hash(idempotency_key)
        request_hash = self._payload_hash({"operation_id": operation_id, "action": "retry"})
        previous = self.store.find_idempotent(actor.telegram_user_id, "retry", key_hash, request_hash)
        if previous is not None:
            return previous, False
        operation = self.get(actor, operation_id)
        if operation.status == OperationStatus.NEEDS_RECONCILIATION:
            raise DomainError("OPERATION_RECONCILIATION_REQUIRED", "Operation harus direkonsiliasi sebelum dapat diulang.", status_code=409)
        if operation.status not in {OperationStatus.FAILED, OperationStatus.CANCELLED}:
            raise DomainError("OPERATION_NOT_RETRYABLE", "Hanya operation failed atau cancelled yang dapat diulang.", status_code=409)
        ensure_operation_transition(operation.status, OperationStatus.QUEUED, retry=True)
        return self.store.apply_action(
            operation_id=operation_id, actor_user_id=actor.telegram_user_id,
            action="retry", key_sha256=key_hash, payload_sha256=request_hash,
            expected_revision=operation.revision,
            target_status=OperationStatus.QUEUED, phase="retry_queued",
            topic="operation.retry", retry=True,
        )

    def set_visibility(
        self, actor: Actor, operation_id: str, dismissed: bool, idempotency_key: str
    ) -> tuple[Operation, bool]:
        key_hash = self._idempotency_hash(idempotency_key)
        request_hash = self._payload_hash({"operation_id": operation_id, "dismissed": bool(dismissed)})
        previous = self.store.find_idempotent(actor.telegram_user_id, "visibility", key_hash, request_hash)
        if previous is not None:
            return previous, False
        self.get(actor, operation_id)
        return self.store.set_visibility(
            operation_id=operation_id, actor_user_id=actor.telegram_user_id,
            dismissed=bool(dismissed), key_sha256=key_hash,
            payload_sha256=request_hash,
        )

    def on_job_event(self, event: JobEvent) -> None:
        operation = self.store.get_by_job_id(event.job_id)
        if operation is None:
            return
        mapping = {
            JobStatus.QUEUED: OperationStatus.QUEUED,
            JobStatus.DISPATCHED: OperationStatus.RUNNING,
            JobStatus.RUNNING: OperationStatus.RUNNING,
            JobStatus.PAUSED: OperationStatus.PAUSED,
            JobStatus.SUCCEEDED: OperationStatus.SUCCEEDED,
            JobStatus.FAILED: OperationStatus.FAILED,
            JobStatus.CANCELLED: OperationStatus.CANCELLED,
        }
        status = mapping[event.status]
        try:
            self.store.transition_from_job(
                operation.id, expected_revision=operation.revision,
                status=status, phase="job_" + event.status.value,
                safe_progress={"job_status": event.status.value},
            )
        except DomainError:
            # A late or out-of-order job event cannot move a cancelling or terminal operation backwards.
            return

    def mark_waiting_worker_for_job(self, job_id: str) -> None:
        operation = self.store.get_by_job_id(str(job_id))
        if operation is None or operation.status.terminal or operation.status in {
            OperationStatus.CANCELLING, OperationStatus.NEEDS_RECONCILIATION,
        }:
            return
        if operation.status == OperationStatus.WAITING_WORKER:
            return
        try:
            self.store.transition_from_job(
                operation.id,
                expected_revision=operation.revision,
                status=OperationStatus.WAITING_WORKER,
                phase="waiting_worker",
                safe_progress={"phase": "waiting_worker"},
            )
        except DomainError:
            return
