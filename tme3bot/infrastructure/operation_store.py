from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from tme3bot.domain.models import DomainError, Job
from tme3bot.domain.operations import Operation, OperationStatus, ensure_operation_transition
from tme3bot.infrastructure.job_store import SqliteJobRepository


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SqliteOperationStore:
    """Durable operation, idempotency, attempt, and outbox storage."""

    def __init__(self, jobs: SqliteJobRepository) -> None:
        self.jobs = jobs
        self.path = Path(jobs.path)
        self._initialize()

    def _initialize(self) -> None:
        db = self.jobs._connect()
        try:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    actor_user_id INTEGER NOT NULL,
                    profile TEXT NOT NULL,
                    target_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    attempt INTEGER NOT NULL DEFAULT 1,
                    progress_json TEXT NOT NULL DEFAULT '{}',
                    job_id TEXT,
                    error_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS operations_actor_created
                    ON operations(actor_user_id, created_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS operations_job
                    ON operations(job_id);
                CREATE TABLE IF NOT EXISTS operation_payloads (
                    operation_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    FOREIGN KEY(operation_id) REFERENCES operations(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS operation_attempts (
                    operation_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    job_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_code TEXT,
                    PRIMARY KEY(operation_id, attempt),
                    FOREIGN KEY(operation_id) REFERENCES operations(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS operation_outbox (
                    id TEXT PRIMARY KEY,
                    operation_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at TEXT NOT NULL,
                    lease_token TEXT,
                    lease_until TEXT,
                    last_error_code TEXT,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    UNIQUE(operation_id, attempt, topic),
                    FOREIGN KEY(operation_id) REFERENCES operations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS operation_outbox_pending
                    ON operation_outbox(status, available_at, lease_until, created_at);
                CREATE TABLE IF NOT EXISTS operation_idempotency (
                    actor_user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    key_sha256 TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(actor_user_id, action, key_sha256),
                    FOREIGN KEY(operation_id) REFERENCES operations(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS operation_visibility (
                    operation_id TEXT NOT NULL,
                    actor_user_id INTEGER NOT NULL,
                    dismissed INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(operation_id, actor_user_id),
                    FOREIGN KEY(operation_id) REFERENCES operations(id) ON DELETE CASCADE
                );
                """
            )
            db.commit()
        finally:
            db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self.jobs.unit_of_work() as db:
            yield db

    @staticmethod
    def _operation(row: sqlite3.Row | None, *, dismissed: bool = False) -> Operation | None:
        if row is None:
            return None
        target = _load(row["target_json"], {})
        progress = _load(row["progress_json"], {})
        error = _load(row["error_json"], None)
        return Operation(
            id=str(row["id"]), kind=str(row["kind"]),
            actor_user_id=int(row["actor_user_id"]), profile=str(row["profile"]),
            target=target if isinstance(target, dict) else {},
            status=OperationStatus(str(row["status"])), phase=str(row["phase"]),
            revision=int(row["revision"]), attempt=int(row["attempt"]),
            progress=progress if isinstance(progress, dict) else {},
            job_id=str(row["job_id"]) if row["job_id"] else None,
            error=error if isinstance(error, dict) else None,
            created_at=_parse_datetime(row["created_at"]) or _now(),
            updated_at=_parse_datetime(row["updated_at"]) or _now(),
            started_at=_parse_datetime(row["started_at"]),
            finished_at=_parse_datetime(row["finished_at"]),
            dismissed=bool(dismissed),
        )

    def _get_in_transaction(
        self, db: sqlite3.Connection, operation_id: str, actor_user_id: int | None = None
    ) -> Operation | None:
        clauses = ["o.id = ?"]
        values: list[object] = [operation_id]
        if actor_user_id is not None:
            clauses.append("o.actor_user_id = ?")
            values.append(int(actor_user_id))
        row = db.execute(
            "SELECT o.*, COALESCE(v.dismissed, 0) AS dismissed "
            "FROM operations o LEFT JOIN operation_visibility v "
            "ON v.operation_id=o.id AND v.actor_user_id=o.actor_user_id "
            "WHERE " + " AND ".join(clauses),
            values,
        ).fetchone()
        return self._operation(row, dismissed=bool(row["dismissed"]) if row else False)

    def _lookup_idempotency(
        self, db: sqlite3.Connection, actor_user_id: int, action: str,
        key_sha256: str, payload_sha256: str,
    ) -> Operation | None:
        row = db.execute(
            "SELECT payload_sha256, operation_id FROM operation_idempotency "
            "WHERE actor_user_id=? AND action=? AND key_sha256=?",
            (int(actor_user_id), action, key_sha256),
        ).fetchone()
        if row is None:
            return None
        if str(row["payload_sha256"]) != payload_sha256:
            raise DomainError(
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency-Key sudah digunakan dengan request berbeda.",
                status_code=409,
            )
        operation = self._get_in_transaction(db, str(row["operation_id"]), int(actor_user_id))
        if operation is None:
            raise DomainError("OPERATION_NOT_FOUND", "Operation tidak ditemukan.", status_code=404)
        return operation

    def find_idempotent(
        self, actor_user_id: int, action: str, key_sha256: str, payload_sha256: str
    ) -> Operation | None:
        with self.jobs._db() as db:
            return self._lookup_idempotency(db, actor_user_id, action, key_sha256, payload_sha256)

    def create_submission(
        self,
        operation: Operation,
        *,
        private_payload: dict[str, Any],
        request_sha256: str,
        key_sha256: str,
        job: Job | None = None,
        execution_plan: dict[str, Any] | None = None,
        command_payload: dict[str, Any] | None = None,
    ) -> tuple[Operation, bool]:
        if job is not None and (execution_plan is None or command_payload is None):
            raise ValueError("Job operation membutuhkan execution plan dan command payload.")
        now = operation.created_at.isoformat()
        with self._transaction() as db:
            duplicate = self._lookup_idempotency(
                db, operation.actor_user_id, "submit", key_sha256, request_sha256
            )
            if duplicate is not None:
                return duplicate, False
            db.execute(
                """INSERT INTO operations(
                       id, kind, actor_user_id, profile, target_json, status, phase,
                       revision, attempt, progress_json, job_id, error_json,
                       created_at, updated_at, started_at, finished_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    operation.id, operation.kind, operation.actor_user_id,
                    operation.profile, _dump(operation.target), operation.status.value,
                    operation.phase, operation.revision, operation.attempt,
                    _dump(operation.progress), operation.job_id,
                    _dump(operation.error) if operation.error else None,
                    now, operation.updated_at.isoformat(),
                    operation.started_at.isoformat() if operation.started_at else None,
                    operation.finished_at.isoformat() if operation.finished_at else None,
                ),
            )
            db.execute(
                "INSERT INTO operation_payloads(operation_id, payload_json, request_sha256) VALUES (?, ?, ?)",
                (operation.id, _dump(private_payload), request_sha256),
            )
            db.execute(
                "INSERT INTO operation_idempotency(actor_user_id, action, key_sha256, payload_sha256, operation_id, created_at) VALUES (?, 'submit', ?, ?, ?, ?)",
                (operation.actor_user_id, key_sha256, request_sha256, operation.id, now),
            )
            db.execute(
                "INSERT INTO operation_attempts(operation_id, attempt, status, job_id, created_at, updated_at) VALUES (?, 1, ?, ?, ?, ?)",
                (operation.id, operation.status.value, operation.job_id, now, now),
            )
            self._insert_outbox(db, operation.id, operation.attempt, "operation.accepted", {"operation_id": operation.id, "attempt": operation.attempt}, now)
            if job is not None:
                assert execution_plan is not None and command_payload is not None
                SqliteJobRepository.insert_prepared_job(db, job, execution_plan, command_payload)
            return operation, True

    def get_for_actor(self, operation_id: str, actor_user_id: int) -> Operation | None:
        with self.jobs._db() as db:
            return self._get_in_transaction(db, operation_id, actor_user_id)

    def get_by_job_id(self, job_id: str) -> Operation | None:
        with self.jobs._db() as db:
            row = db.execute("SELECT id FROM operations WHERE job_id=? ORDER BY created_at DESC LIMIT 1", (job_id,)).fetchone()
            return self._get_in_transaction(db, str(row["id"])) if row else None

    def list_for_actor(
        self, actor_user_id: int, *, status: str | None, offset: int, limit: int
    ) -> tuple[list[Operation], bool]:
        clauses = ["o.actor_user_id = ?"]
        values: list[object] = [int(actor_user_id)]
        if status:
            clauses.append("o.status = ?")
            values.append(status)
        values.append(max(1, min(int(limit), 100)) + 1)
        values.append(max(0, int(offset)))
        with self.jobs._db() as db:
            rows = db.execute(
                "SELECT o.*, COALESCE(v.dismissed, 0) AS dismissed "
                "FROM operations o LEFT JOIN operation_visibility v "
                "ON v.operation_id=o.id AND v.actor_user_id=o.actor_user_id "
                "WHERE " + " AND ".join(clauses)
                + " ORDER BY o.created_at DESC, o.id DESC LIMIT ? OFFSET ?",
                values,
            ).fetchall()
        has_more = len(rows) > max(1, min(int(limit), 100))
        rows = rows[: max(1, min(int(limit), 100))]
        return [self._operation(row, dismissed=bool(row["dismissed"])) for row in rows], has_more

    def get_private_payload(self, operation_id: str) -> dict[str, Any] | None:
        with self.jobs._db() as db:
            row = db.execute("SELECT payload_json FROM operation_payloads WHERE operation_id=?", (operation_id,)).fetchone()
        value = _load(row["payload_json"], None) if row else None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _insert_outbox(
        db: sqlite3.Connection, operation_id: str, attempt: int,
        topic: str, payload: dict[str, Any], now: str,
    ) -> str:
        message_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO operation_outbox(
                   id, operation_id, attempt, topic, payload_json, status,
                   attempts, available_at, created_at
               ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)""",
            (message_id, operation_id, int(attempt), topic, _dump(payload), now, now),
        )
        return message_id

    def apply_action(
        self,
        *,
        operation_id: str,
        actor_user_id: int,
        action: str,
        key_sha256: str,
        payload_sha256: str,
        expected_revision: int,
        target_status: OperationStatus,
        phase: str,
        topic: str,
        retry: bool = False,
    ) -> tuple[Operation, bool]:
        now = _now().isoformat()
        with self._transaction() as db:
            duplicate = self._lookup_idempotency(db, actor_user_id, action, key_sha256, payload_sha256)
            if duplicate is not None:
                return duplicate, False
            current = self._get_in_transaction(db, operation_id, actor_user_id)
            if current is None:
                raise DomainError("OPERATION_NOT_FOUND", "Operation tidak ditemukan.", status_code=404)
            if current.revision != int(expected_revision):
                raise DomainError(
                    "OPERATION_REVISION_CONFLICT", "Operation sudah berubah; muat ulang sebelum mencoba lagi.",
                    status_code=409,
                    details={"expected_revision": int(expected_revision), "current_revision": current.revision},
                )
            ensure_operation_transition(current.status, target_status, retry=retry)
            attempt = current.attempt + (1 if retry else 0)
            started_at = current.started_at
            finished_at = current.finished_at
            if target_status == OperationStatus.RUNNING and started_at is None:
                started_at = datetime.fromisoformat(now)
            if target_status.terminal:
                finished_at = datetime.fromisoformat(now)
            elif retry:
                started_at = None
                finished_at = None
            next_error = None if retry else current.error
            db.execute(
                """UPDATE operations SET status=?, phase=?, revision=revision+1,
                       attempt=?, error_json=?, updated_at=?, started_at=?, finished_at=?
                   WHERE id=? AND actor_user_id=? AND revision=?""",
                (
                    target_status.value, phase, attempt,
                    _dump(next_error) if next_error else None, now,
                    started_at.isoformat() if started_at else None,
                    finished_at.isoformat() if finished_at else None,
                    operation_id, int(actor_user_id), int(expected_revision),
                ),
            )
            db.execute(
                "INSERT INTO operation_idempotency(actor_user_id, action, key_sha256, payload_sha256, operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (int(actor_user_id), action, key_sha256, payload_sha256, operation_id, now),
            )
            db.execute(
                "UPDATE operation_attempts SET status=?, updated_at=?, error_code=? WHERE operation_id=? AND attempt=?",
                (current.status.value, now, (current.error or {}).get("code"), operation_id, current.attempt),
            )
            if retry:
                db.execute(
                    "INSERT INTO operation_attempts(operation_id, attempt, status, job_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (operation_id, attempt, target_status.value, current.job_id, now, now),
                )
                if current.job_id:
                    self._reset_job_for_retry(db, current.job_id, now)
            else:
                db.execute(
                    "UPDATE operation_attempts SET status=?, updated_at=? WHERE operation_id=? AND attempt=?",
                    (target_status.value, now, operation_id, current.attempt),
                )
            self._insert_outbox(db, operation_id, attempt, topic, {"operation_id": operation_id, "attempt": attempt}, now)
            updated = self._get_in_transaction(db, operation_id, actor_user_id)
            assert updated is not None
            return updated, True

    @staticmethod
    def _reset_job_for_retry(db: sqlite3.Connection, job_id: str, now: str) -> None:
        row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return
        from tme3bot.domain.models import JobStatus

        if not JobStatus(str(row["status"])).terminal:
            raise DomainError("JOB_NOT_RETRYABLE", "Job terkait belum selesai.", status_code=409)
        sequence = int(db.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM job_events WHERE job_id=?", (job_id,)
        ).fetchone()[0])
        db.execute(
            """UPDATE jobs SET status='queued', progress=?, result=NULL, error=NULL,
                   progress_sequence=?, archived_at=NULL, updated_at=? WHERE id=?""",
            (_dump({"phase": "queued", "operation_retry": True}), sequence, now, job_id),
        )
        db.execute("DELETE FROM job_resource_leases WHERE job_id=?", (job_id,))
        db.execute(
            "UPDATE job_execution_plans SET queued_at=?, admitted_at=NULL, released_at=NULL, blocked_reason=NULL WHERE job_id=?",
            (now, job_id),
        )
        db.execute(
            "UPDATE job_telegram_notifications SET status='pending', terminal_notified_at=NULL, last_status_hash=NULL, error=NULL WHERE job_id=?",
            (job_id,),
        )

    def set_visibility(
        self,
        *,
        operation_id: str,
        actor_user_id: int,
        dismissed: bool,
        key_sha256: str,
        payload_sha256: str,
    ) -> tuple[Operation, bool]:
        now = _now().isoformat()
        with self._transaction() as db:
            duplicate = self._lookup_idempotency(db, actor_user_id, "visibility", key_sha256, payload_sha256)
            if duplicate is not None:
                return duplicate, False
            operation = self._get_in_transaction(db, operation_id, actor_user_id)
            if operation is None:
                raise DomainError("OPERATION_NOT_FOUND", "Operation tidak ditemukan.", status_code=404)
            db.execute(
                """INSERT INTO operation_visibility(operation_id, actor_user_id, dismissed, updated_at)
                   VALUES (?, ?, ?, ?) ON CONFLICT(operation_id, actor_user_id)
                   DO UPDATE SET dismissed=excluded.dismissed, updated_at=excluded.updated_at""",
                (operation_id, int(actor_user_id), int(dismissed), now),
            )
            db.execute(
                "INSERT INTO operation_idempotency(actor_user_id, action, key_sha256, payload_sha256, operation_id, created_at) VALUES (?, 'visibility', ?, ?, ?, ?)",
                (int(actor_user_id), key_sha256, payload_sha256, operation_id, now),
            )
            updated = self._get_in_transaction(db, operation_id, actor_user_id)
            assert updated is not None
            return updated, True

    def transition_from_job(
        self, operation_id: str, *, expected_revision: int,
        status: OperationStatus, phase: str, safe_progress: dict[str, Any],
    ) -> Operation | None:
        now = _now().isoformat()
        with self._transaction() as db:
            current = self._get_in_transaction(db, operation_id)
            if current is None or current.revision != int(expected_revision):
                return None
            ensure_operation_transition(current.status, status)
            started = current.started_at or (datetime.fromisoformat(now) if status == OperationStatus.RUNNING else None)
            finished = datetime.fromisoformat(now) if status.terminal else None
            sanitized_error = {"code": "JOB_FAILED", "message": "Pekerjaan gagal."} if status == OperationStatus.FAILED else None
            db.execute(
                """UPDATE operations SET status=?, phase=?, progress_json=?, error_json=?,
                       revision=revision+1, updated_at=?, started_at=?, finished_at=?
                   WHERE id=? AND revision=?""",
                (
                    status.value, phase, _dump(safe_progress),
                    _dump(sanitized_error) if sanitized_error else None,
                    now, started.isoformat() if started else None,
                    finished.isoformat() if finished else None,
                    operation_id, int(expected_revision),
                ),
            )
            db.execute(
                "UPDATE operation_attempts SET status=?, updated_at=?, error_code=? WHERE operation_id=? AND attempt=?",
                (status.value, now, sanitized_error["code"] if sanitized_error else None, operation_id, current.attempt),
            )
            return self._get_in_transaction(db, operation_id)

    def claim_outbox(self, *, limit: int = 50, lease_seconds: int = 30) -> list[dict[str, Any]]:
        now = _now()
        now_text = now.isoformat()
        lease_until = (now + timedelta(seconds=max(1, min(int(lease_seconds), 3600)))).isoformat()
        claimed: list[dict[str, Any]] = []
        with self._transaction() as db:
            rows = db.execute(
                """SELECT id FROM operation_outbox
                   WHERE (status='pending' AND available_at<=?)
                      OR (status='inflight' AND lease_until<=?)
                   ORDER BY available_at, created_at, id LIMIT ?""",
                (now_text, now_text, max(1, min(int(limit), 500))),
            ).fetchall()
            for row in rows:
                message_id = str(row["id"])
                token = secrets.token_urlsafe(24)
                db.execute(
                    """UPDATE operation_outbox SET status='inflight', attempts=attempts+1,
                           lease_token=?, lease_until=? WHERE id=?""",
                    (token, lease_until, message_id),
                )
                value = db.execute("SELECT * FROM operation_outbox WHERE id=?", (message_id,)).fetchone()
                claimed.append({
                    "id": message_id, "operation_id": str(value["operation_id"]),
                    "attempt": int(value["attempt"]), "topic": str(value["topic"]),
                    "payload": _load(value["payload_json"], {}),
                    "attempts": int(value["attempts"]), "lease_token": token,
                    "lease_until": lease_until,
                })
        return claimed

    def acknowledge_outbox(self, message_id: str, lease_token: str) -> bool:
        now = _now().isoformat()
        with self._transaction() as db:
            cursor = db.execute(
                """UPDATE operation_outbox SET status='delivered', lease_token=NULL,
                       lease_until=NULL, delivered_at=?
                   WHERE id=? AND status='inflight' AND lease_token=?""",
                (now, message_id, lease_token),
            )
            return cursor.rowcount == 1

    def retry_outbox(
        self, message_id: str, lease_token: str, *, delay_seconds: int, error_code: str
    ) -> bool:
        now = _now()
        available = now + timedelta(seconds=max(0, min(int(delay_seconds), 86400)))
        safe_code = "".join(char for char in str(error_code).upper() if char.isalnum() or char == "_")[:64] or "DELIVERY_FAILED"
        with self._transaction() as db:
            cursor = db.execute(
                """UPDATE operation_outbox SET status='pending', available_at=?,
                       lease_token=NULL, lease_until=NULL, last_error_code=?
                   WHERE id=? AND status='inflight' AND lease_token=?""",
                (available.isoformat(), safe_code, message_id, lease_token),
            )
            return cursor.rowcount == 1
