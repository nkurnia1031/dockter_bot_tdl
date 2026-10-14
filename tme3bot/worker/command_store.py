"""Durable worker command journal and progress-event outbox."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tme3bot.domain.models import DomainError


TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "needs_reconciliation"})
_ALLOWED_COMMAND_STATUSES = frozenset(
    {"accepted", "claimed", "queued", "running", "cancelling", *TERMINAL_STATUSES}
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class WorkerCommandStore:
    """SQLite journal kept on the worker's persistent data volume."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            # Windows does not support POSIX mode bits; deployments run this
            # journal in the Linux worker container.
            pass

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._lock, self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS worker_commands (
                    command_id TEXT PRIMARY KEY,
                    job_id TEXT,
                    operation_id TEXT,
                    attempt INTEGER NOT NULL,
                    dispatch_token TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL DEFAULT 'accepted',
                    checkpoint TEXT,
                    ack TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(job_id, attempt)
                );
                CREATE INDEX IF NOT EXISTS idx_worker_commands_ready
                    ON worker_commands(status, created_at);
                CREATE TABLE IF NOT EXISTS worker_storage_upload_items (
                    command_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    profile TEXT NOT NULL DEFAULT '',
                    retryable INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT,
                    message_id INTEGER,
                    caption TEXT NOT NULL DEFAULT '',
                    result_json TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(command_id, relative_path),
                    FOREIGN KEY(command_id) REFERENCES worker_commands(command_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS worker_storage_upload_attempts (
                    command_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    profile TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retryable INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT,
                    message_id INTEGER,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(command_id, relative_path, attempt),
                    FOREIGN KEY(command_id) REFERENCES worker_commands(command_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_worker_storage_upload_items_status
                    ON worker_storage_upload_items(command_id, status);
                CREATE TABLE IF NOT EXISTS worker_event_sequences (
                    job_id TEXT PRIMARY KEY,
                    last_sequence INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS worker_event_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_json TEXT NOT NULL,
                    transient INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at TEXT NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(job_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_worker_event_outbox_ready
                    ON worker_event_outbox(status, available_at, id);
                """
            )
            upload_columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(worker_storage_upload_items)").fetchall()
            }
            if "caption" not in upload_columns:
                db.execute(
                    "ALTER TABLE worker_storage_upload_items "
                    "ADD COLUMN caption TEXT NOT NULL DEFAULT ''"
                )

    @staticmethod
    def _validate_envelope(envelope: Any) -> tuple[str, str | None, str | None, int, str]:
        if not isinstance(envelope, dict):
            raise DomainError("INVALID_WORKER_COMMAND", "Command worker tidak valid.", status_code=422)
        command_id = str(envelope.get("command_id") or "").strip()
        if not command_id or len(command_id) > 160:
            raise DomainError("INVALID_WORKER_COMMAND", "Command ID tidak valid.", status_code=422)
        attempt = envelope.get("attempt")
        if type(attempt) is not int or attempt < 1 or attempt > 1_000_000:
            raise DomainError("INVALID_WORKER_COMMAND", "Attempt command tidak valid.", status_code=422)
        dispatch_token = str(envelope.get("dispatch_token") or "").strip()
        if not dispatch_token or len(dispatch_token) > 512:
            raise DomainError("INVALID_WORKER_COMMAND", "Token dispatch tidak valid.", status_code=422)

        job_id: str | None = None
        operation_id: str | None = None
        job = envelope.get("job")
        operation = envelope.get("operation")
        if job is not None:
            if not isinstance(job, dict):
                raise DomainError("INVALID_WORKER_COMMAND", "Data job tidak valid.", status_code=422)
            job_id = str(envelope.get("job_id") or "").strip()
            if not job_id or len(job_id) > 160:
                raise DomainError("INVALID_WORKER_COMMAND", "Job ID tidak valid.", status_code=422)
            for key in ("kind", "profile", "worker"):
                if not str(job.get(key) or "").strip():
                    raise DomainError("INVALID_WORKER_COMMAND", f"Field job {key} wajib diisi.", status_code=422)
            if not isinstance(job.get("payload", {}), dict):
                raise DomainError("INVALID_WORKER_COMMAND", "Payload job tidak valid.", status_code=422)
        elif isinstance(operation, dict):
            operation_id = str(envelope.get("operation_id") or "").strip()
            if not operation_id or len(operation_id) > 160:
                raise DomainError("INVALID_WORKER_COMMAND", "Operation ID tidak valid.", status_code=422)
            if not str(operation.get("kind") or operation.get("type") or "").strip():
                raise DomainError("INVALID_WORKER_COMMAND", "Jenis operation tidak valid.", status_code=422)
        else:
            raise DomainError(
                "INVALID_WORKER_COMMAND",
                "Command harus berisi job atau operation.",
                status_code=422,
            )

        try:
            serialized = _dump(envelope)
        except (TypeError, ValueError) as exc:
            raise DomainError("INVALID_WORKER_COMMAND", "Payload command tidak dapat disimpan.", status_code=422) from exc
        if len(serialized.encode("utf-8")) > 8 * 1024 * 1024:
            raise DomainError("WORKER_COMMAND_TOO_LARGE", "Payload command melebihi batas 8 MiB.", status_code=413)
        return command_id, job_id, operation_id, attempt, dispatch_token

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "command_id": row["command_id"],
            "job_id": row["job_id"],
            "operation_id": row["operation_id"],
            "attempt": int(row["attempt"]),
            "status": row["status"],
            "phase": row["phase"],
            "checkpoint": json.loads(row["checkpoint"]) if row["checkpoint"] else None,
            "ack": json.loads(row["ack"]) if row["ack"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "accepted": row["status"] != "needs_reconciliation",
        }

    def accept(self, envelope: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        command_id, job_id, operation_id, attempt, dispatch_token = self._validate_envelope(envelope)
        serialized = _dump(envelope)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        now = _now()
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM worker_commands WHERE command_id=?", (command_id,)
            ).fetchone()
            if existing is not None:
                if existing["payload_hash"] != digest:
                    db.rollback()
                    raise DomainError(
                        "COMMAND_ID_CONFLICT",
                        "Command ID sudah digunakan dengan payload berbeda.",
                        status_code=409,
                    )
                db.commit()
                return self._public(existing), True
            if job_id is not None:
                duplicate = db.execute(
                    "SELECT command_id FROM worker_commands WHERE job_id=? AND attempt=?",
                    (job_id, attempt),
                ).fetchone()
                if duplicate is not None:
                    db.rollback()
                    raise DomainError(
                        "COMMAND_ATTEMPT_CONFLICT",
                        "Job dan attempt sudah terikat ke command lain.",
                        status_code=409,
                    )
            elif operation_id is not None:
                duplicate = db.execute(
                    "SELECT command_id FROM worker_commands WHERE operation_id=? AND attempt=?",
                    (operation_id, attempt),
                ).fetchone()
                if duplicate is not None:
                    db.rollback()
                    raise DomainError(
                        "COMMAND_ATTEMPT_CONFLICT",
                        "Operation dan attempt sudah terikat ke command lain.",
                        status_code=409,
                    )
            try:
                db.execute(
                    """INSERT INTO worker_commands
                    (command_id,job_id,operation_id,attempt,dispatch_token,payload,payload_hash,status,phase,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,'accepted','accepted',?,?)""",
                    (command_id, job_id, operation_id, attempt, dispatch_token, serialized, digest, now, now),
                )
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise DomainError("COMMAND_ATTEMPT_CONFLICT", "Attempt command sudah tercatat.", status_code=409) from exc
            row = db.execute("SELECT * FROM worker_commands WHERE command_id=?", (command_id,)).fetchone()
            db.commit()
        return self._public(row), False

    def get(self, command_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM worker_commands WHERE command_id=?", (str(command_id),)).fetchone()
        return self._public(row) if row is not None else None

    def claim_next(self) -> tuple[str, dict[str, Any]] | None:
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT command_id,payload FROM worker_commands WHERE status='accepted' ORDER BY created_at,command_id LIMIT 1"
            ).fetchone()
            if row is None:
                db.commit()
                return None
            now = _now()
            updated = db.execute(
                "UPDATE worker_commands SET status='claimed',phase='admission',updated_at=? WHERE command_id=? AND status='accepted'",
                (now, row["command_id"]),
            ).rowcount
            db.commit()
            if not updated:
                return None
        return str(row["command_id"]), json.loads(row["payload"])

    def set_status(
        self,
        command_id: str,
        status: str,
        *,
        phase: str | None = None,
        checkpoint: dict[str, Any] | None = None,
        ack: dict[str, Any] | None = None,
        only_from: tuple[str, ...] | None = None,
    ) -> bool:
        if status not in _ALLOWED_COMMAND_STATUSES:
            raise ValueError("Unknown command status")
        clauses = "command_id=?"
        values: list[Any] = [status, str(phase or status), _dump(checkpoint) if checkpoint is not None else None, _dump(ack) if ack is not None else None, _now(), str(command_id)]
        if only_from:
            clauses += " AND status IN (" + ",".join("?" for _ in only_from) + ")"
            values.extend(only_from)
        with self._db() as db:
            updated = db.execute(
                f"UPDATE worker_commands SET status=?,phase=?,checkpoint=COALESCE(?,checkpoint),ack=COALESCE(?,ack),updated_at=? WHERE {clauses}",
                values,
            ).rowcount
        return bool(updated)

    def release_claim(self, command_id: str) -> bool:
        return self.set_status(command_id, "accepted", phase="accepted", only_from=("claimed",))

    def mark_running(self, command_id: str) -> bool:
        return self.set_status(command_id, "running", phase="running", only_from=("claimed", "queued"))

    def finish(self, command_id: str, status: str, *, ack: dict[str, Any] | None = None) -> bool:
        if status not in TERMINAL_STATUSES:
            raise ValueError("finish requires terminal command status")
        return self.set_status(
            command_id, status, phase=status, ack=ack,
            only_from=("claimed", "queued", "running", "cancelling", "accepted"),
        )

    def record_storage_upload_item(
        self,
        command_id: str,
        relative_path: str,
        *,
        file_name: str,
        status: str,
        attempt: int = 0,
        profile: str = "",
        retryable: bool = False,
        error_code: str = "",
        error_message: str = "",
        message_id: int | None = None,
        caption: str | None = None,
        result_item: dict[str, Any] | None = None,
    ) -> None:
        """Persist one Storage file outcome and its latest lane attempt."""
        selected_command = str(command_id or "").strip()
        selected_path = str(relative_path or "").replace("\\", "/").strip()
        parts = selected_path.split("/")
        if (
            not selected_command
            or not selected_path
            or selected_path.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("Storage upload checkpoint requires a safe relative file path.")
        if status not in {
            "pending", "sending", "resolving", "accepted", "succeeded",
            "failed", "needs_reconciliation",
        }:
            raise ValueError("Unknown Storage upload item status")
        selected_attempt = max(0, int(attempt))
        selected_profile = str(profile or "").strip().lower()[:80]
        selected_code = str(error_code or "").strip().upper()[:100]
        selected_error = str(error_message or "").strip()[:500]
        selected_name = str(file_name or "").strip()[:255]
        selected_caption = str(caption)[:1024] if caption is not None else None
        selected_result = _dump(result_item) if isinstance(result_item, dict) else None
        now = _now()
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if selected_attempt > 0 and selected_profile:
                db.execute(
                    "INSERT INTO worker_storage_upload_attempts "
                    "(command_id,relative_path,attempt,profile,status,retryable,error_code,error_message,message_id,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(command_id,relative_path,attempt) DO UPDATE SET "
                    "profile=excluded.profile,status=excluded.status,retryable=excluded.retryable,"
                    "error_code=excluded.error_code,error_message=excluded.error_message,"
                    "message_id=excluded.message_id,updated_at=excluded.updated_at",
                    (
                        selected_command, selected_path, selected_attempt, selected_profile,
                        status, int(bool(retryable)), selected_code or None,
                        selected_error or None, message_id, now,
                    ),
                )
            db.execute(
                "INSERT INTO worker_storage_upload_items "
                "(command_id,relative_path,file_name,status,attempt,profile,retryable,error_code,error_message,message_id,caption,result_json,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(command_id,relative_path) DO UPDATE SET "
                "file_name=excluded.file_name,status=excluded.status,attempt=excluded.attempt,"
                "profile=excluded.profile,retryable=excluded.retryable,error_code=excluded.error_code,"
                "error_message=excluded.error_message,message_id=excluded.message_id,"
                "caption=COALESCE(NULLIF(excluded.caption,''),worker_storage_upload_items.caption),"
                "result_json=COALESCE(excluded.result_json,worker_storage_upload_items.result_json),"
                "updated_at=excluded.updated_at",
                (
                    selected_command, selected_path, selected_name, status, selected_attempt,
                    selected_profile, int(bool(retryable)), selected_code or None,
                    selected_error or None, message_id, selected_caption or "", selected_result, now,
                ),
            )
            db.commit()

    def storage_upload_items(self, command_id: str) -> list[dict[str, Any]]:
        selected_command = str(command_id or "").strip()
        if not selected_command:
            return []
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM worker_storage_upload_items WHERE command_id=? "
                "ORDER BY relative_path",
                (selected_command,),
            ).fetchall()
            attempts = db.execute(
                "SELECT relative_path,attempt,profile,status,retryable,error_code,error_message,message_id "
                "FROM worker_storage_upload_attempts WHERE command_id=? ORDER BY relative_path,attempt",
                (selected_command,),
            ).fetchall()
        attempts_by_path: dict[str, list[dict[str, Any]]] = {}
        for row in attempts:
            attempts_by_path.setdefault(str(row["relative_path"]), []).append(
                {
                    "attempt": int(row["attempt"]),
                    "profile": str(row["profile"] or ""),
                    "status": str(row["status"]),
                    "retryable": bool(row["retryable"]),
                    "error_code": str(row["error_code"] or ""),
                    "error_message": str(row["error_message"] or ""),
                    "message_id": row["message_id"],
                }
            )
        result = []
        for row in rows:
            result_item = None
            if row["result_json"]:
                try:
                    decoded = json.loads(row["result_json"])
                    result_item = decoded if isinstance(decoded, dict) else None
                except (TypeError, ValueError, json.JSONDecodeError):
                    result_item = None
            result.append(
                {
                    "path": str(row["relative_path"]),
                    "name": str(row["file_name"]),
                    "status": str(row["status"]),
                    "attempt": int(row["attempt"]),
                    "profile": str(row["profile"] or ""),
                    "retryable": bool(row["retryable"]),
                    "error_code": str(row["error_code"] or ""),
                    "error": str(row["error_message"] or ""),
                    "message_id": row["message_id"],
                    "caption": str(row["caption"] or ""),
                    "uploaded_item": result_item,
                    "attempts": attempts_by_path.get(str(row["relative_path"]), []),
                }
            )
        return result

    def storage_upload_items_for_job(self, job_id: str) -> dict[str, Any] | None:
        """Load the durable upload checkpoint for a source job ID."""
        selected_job = str(job_id or "").strip()
        if not selected_job:
            return None
        with self._db() as db:
            rows = db.execute(
                "SELECT command_id,payload FROM worker_commands WHERE job_id=? "
                "ORDER BY attempt DESC,updated_at DESC",
                (selected_job,),
            ).fetchall()
        for row in rows:
            try:
                envelope = json.loads(row["payload"])
                job = envelope.get("job") if isinstance(envelope, dict) else None
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(job, dict) and str(job.get("kind") or "") == "storage_upload":
                command_id = str(row["command_id"])
                return {
                    "command_id": command_id,
                    "items": self.storage_upload_items(command_id),
                }
        return None

    def list_storage_reconciliation_commands(self) -> list[dict[str, Any]]:
        """Return unreported interrupted Storage commands for startup recovery."""
        with self._db() as db:
            rows = db.execute(
                "SELECT command_id,job_id,attempt,dispatch_token,payload FROM worker_commands "
                "WHERE status='needs_reconciliation' AND phase='needs_reconciliation' AND job_id IS NOT NULL "
                "ORDER BY updated_at,command_id"
            ).fetchall()
        result = []
        for row in rows:
            try:
                envelope = json.loads(row["payload"])
                job = envelope.get("job") if isinstance(envelope, dict) else None
            except (TypeError, ValueError, json.JSONDecodeError):
                job = None
            if isinstance(job, dict) and str(job.get("kind") or "") == "storage_upload":
                result.append(
                    {
                        "command_id": str(row["command_id"]),
                        "job_id": str(row["job_id"]),
                        "attempt": int(row["attempt"]),
                        "dispatch_token": str(row["dispatch_token"]),
                        "worker": str(job.get("worker") or ""),
                    }
                )
        return result

    def mark_storage_reconciliation_reported(self, command_id: str) -> bool:
        with self._db() as db:
            changed = db.execute(
                "UPDATE worker_commands SET phase='reconciliation_reported',updated_at=? "
                "WHERE command_id=? AND status='needs_reconciliation' AND phase='needs_reconciliation'",
                (_now(), str(command_id)),
            ).rowcount
        return bool(changed)

    def request_cancel_by_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM worker_commands WHERE job_id=? AND status IN ('accepted','claimed','queued','running','cancelling') ORDER BY attempt DESC LIMIT 1",
                (str(job_id),),
            ).fetchone()
            if row is None:
                db.commit()
                return None
            status = "cancelled" if row["status"] in {"accepted", "claimed"} else "cancelling"
            db.execute(
                "UPDATE worker_commands SET status=?,phase=?,updated_at=? WHERE command_id=?",
                (status, status, _now(), row["command_id"]),
            )
            updated = db.execute("SELECT * FROM worker_commands WHERE command_id=?", (row["command_id"],)).fetchone()
            db.commit()
        return self._public(updated)

    def recover_startup(self) -> dict[str, int]:
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            now = _now()
            accepted = db.execute(
                "UPDATE worker_commands SET status='accepted',phase='accepted',updated_at=? WHERE status IN ('claimed','queued')",
                (now,),
            ).rowcount
            uncertain = 0
            for row in db.execute(
                "SELECT command_id,status,payload,phase,checkpoint FROM worker_commands WHERE status IN ('running','cancelling')"
            ).fetchall():
                envelope = json.loads(row["payload"])
                job = envelope.get("job") if isinstance(envelope.get("job"), dict) else {}
                checkpoint = json.loads(row["checkpoint"]) if row["checkpoint"] else {}
                checkpoint_progress = checkpoint.get("progress") if isinstance(checkpoint, dict) else {}
                checkpoint_progress = checkpoint_progress if isinstance(checkpoint_progress, dict) else {}
                phase = str(checkpoint_progress.get("phase") or row["phase"] or "")
                # TTS part files are deterministic checkpoints. Re-running the
                # synthesis stage reuses completed parts; delivery has not
                # started before the telegram_delivery phase marker.
                safe_tts_resume = (
                    row["status"] == "running"
                    and str(job.get("kind") or "") == "tts"
                    and phase in {"starting", "synthesizing", "merging"}
                )
                safe_export_commit_resume = (
                    row["status"] in {"running", "cancelling"}
                    and str(job.get("kind") or "") == "export"
                    and isinstance(checkpoint, dict)
                    and isinstance(checkpoint.get("cursor_commit"), dict)
                )
                safe_resume = safe_tts_resume or safe_export_commit_resume
                next_status = "accepted" if safe_resume else "needs_reconciliation"
                next_phase = (
                    "recovered_cursor_commit"
                    if safe_export_commit_resume
                    else "recovered"
                    if safe_tts_resume
                    else "needs_reconciliation"
                )
                db.execute(
                    "UPDATE worker_commands SET status=?,phase=?,updated_at=? WHERE command_id=?",
                    (next_status, next_phase, now, row["command_id"]),
                )
                if (
                    not safe_resume
                    and str(job.get("kind") or "") == "storage_upload"
                ):
                    db.execute(
                        "UPDATE worker_storage_upload_attempts SET status='needs_reconciliation',retryable=0,"
                        "error_code='STORAGE_UPLOAD_INTERRUPTED',error_message='Hasil pengiriman terputus dan perlu rekonsiliasi.',updated_at=? "
                        "WHERE command_id=? AND status IN ('sending','resolving','accepted')",
                        (now, row["command_id"]),
                    )
                    db.execute(
                        "UPDATE worker_storage_upload_items SET status='needs_reconciliation',retryable=0,"
                        "error_code='STORAGE_UPLOAD_INTERRUPTED',error_message='Hasil pengiriman terputus dan perlu rekonsiliasi.',updated_at=? "
                        "WHERE command_id=? AND status IN ('sending','resolving','accepted')",
                        (now, row["command_id"]),
                    )
                if safe_resume:
                    accepted += 1
                else:
                    uncertain += 1
            events = db.execute(
                "UPDATE worker_event_outbox SET status='pending',available_at=? WHERE status='sending'",
                (now,),
            ).rowcount
            db.commit()
        return {"requeued": accepted, "needs_reconciliation": uncertain, "events_recovered": events}

    def seed_sequence(self, job_id: str, sequence: int | None) -> None:
        if sequence is None:
            return
        with self._db() as db:
            db.execute(
                "INSERT INTO worker_event_sequences(job_id,last_sequence) VALUES (?,?) "
                "ON CONFLICT(job_id) DO UPDATE SET last_sequence=MAX(last_sequence,excluded.last_sequence)",
                (str(job_id), max(0, int(sequence))),
            )

    def append_event(self, job_id: str, payload: dict[str, Any], *, transient: bool) -> int:
        now = _now()
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT last_sequence FROM worker_event_sequences WHERE job_id=?", (str(job_id),)).fetchone()
            sequence = int(row["last_sequence"]) + 1 if row else 2
            db.execute(
                "INSERT INTO worker_event_sequences(job_id,last_sequence) VALUES (?,?) ON CONFLICT(job_id) DO UPDATE SET last_sequence=excluded.last_sequence",
                (str(job_id), sequence),
            )
            payload = {**payload, "sequence": sequence}
            if transient:
                db.execute(
                    "UPDATE worker_event_outbox SET status='superseded' WHERE job_id=? AND transient=1 AND status='pending' AND attempts=0",
                    (str(job_id),),
                )
            db.execute(
                "INSERT INTO worker_event_outbox(job_id,sequence,event_json,transient,status,available_at,created_at) VALUES (?,?,?,?, 'pending',?,?)",
                (str(job_id), sequence, _dump(payload), int(bool(transient)), now, now),
            )
            command_id = str(payload.get("command_id") or "")
            if command_id:
                progress = payload.get("progress")
                progress_snapshot = progress if isinstance(progress, dict) else {}
                checkpoint = {
                    "event_type": str(payload.get("event_type") or ""),
                    "status": str(payload.get("status") or ""),
                    "progress": progress_snapshot,
                    "event_sequence": sequence,
                }
                command_row = db.execute(
                    "SELECT checkpoint FROM worker_commands WHERE command_id=? AND job_id=? AND attempt=? AND dispatch_token=?",
                    (
                        command_id,
                        str(job_id),
                        int(payload.get("attempt") or 0),
                        str(payload.get("dispatch_token") or ""),
                    ),
                ).fetchone()
                if command_row is not None and command_row["checkpoint"]:
                    try:
                        existing_checkpoint = json.loads(command_row["checkpoint"])
                    except (TypeError, json.JSONDecodeError):
                        existing_checkpoint = {}
                    if isinstance(existing_checkpoint, dict) and isinstance(
                        existing_checkpoint.get("cursor_commit"), dict
                    ):
                        checkpoint["cursor_commit"] = existing_checkpoint["cursor_commit"]
                db.execute(
                    """UPDATE worker_commands SET phase=?,checkpoint=?,updated_at=?
                    WHERE command_id=? AND job_id=? AND attempt=? AND dispatch_token=?""",
                    (
                        str(progress_snapshot.get("phase") or payload.get("event_type") or "running"),
                        _dump(checkpoint),
                        now,
                        command_id,
                        str(job_id),
                        int(payload.get("attempt") or 0),
                        str(payload.get("dispatch_token") or ""),
                    ),
                )
            db.commit()
        return sequence

    def claim_event(self) -> tuple[int, str, int, dict[str, Any]] | None:
        now = _now()
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT e.id,e.job_id,e.sequence,e.event_json FROM worker_event_outbox e
                WHERE e.status='pending' AND e.available_at<=?
                  AND NOT EXISTS (SELECT 1 FROM worker_event_outbox p WHERE p.job_id=e.job_id AND p.sequence<e.sequence AND p.status IN ('pending','sending'))
                ORDER BY e.id LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                db.commit()
                return None
            db.execute("UPDATE worker_event_outbox SET status='sending',attempts=attempts+1 WHERE id=? AND status='pending'", (row["id"],))
            db.commit()
        return int(row["id"]), str(row["job_id"]), int(row["sequence"]), json.loads(row["event_json"])

    def acknowledge_event(self, event_id: int, *, accepted: bool, reason: str = "") -> None:
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT job_id,event_json FROM worker_event_outbox WHERE id=?",
                (int(event_id),),
            ).fetchone()
            if row is None:
                db.commit()
                return
            db.execute(
                "UPDATE worker_event_outbox SET status=?,last_error=? WHERE id=?",
                ("acked" if accepted else "ignored", str(reason)[:160] or None, int(event_id)),
            )
            event = json.loads(row["event_json"])
            event_status = str(event.get("status") or "").lower()
            command_id = str(event.get("command_id") or "")
            if command_id:
                terminal = accepted and event_status in {"succeeded", "failed", "cancelled"}
                ack = _dump(
                    {
                        "event_sequence": int(event.get("sequence") or 0),
                        "accepted": bool(accepted),
                        "reason": str(reason)[:160],
                    }
                )
                db.execute(
                    """UPDATE worker_commands SET
                    status=CASE WHEN ? THEN ? ELSE status END,
                    phase=CASE WHEN ? THEN ? ELSE phase END,
                    ack=?,updated_at=?
                    WHERE command_id=? AND job_id=? AND attempt=? AND dispatch_token=?""",
                    (
                        int(terminal),
                        event_status,
                        int(terminal),
                        event_status,
                        ack,
                        _now(),
                        command_id,
                        str(row["job_id"]),
                        int(event.get("attempt") or 0),
                        str(event.get("dispatch_token") or ""),
                    ),
                )
            db.commit()

    def retry_event(self, event_id: int, error_type: str) -> None:
        with self._db() as db:
            row = db.execute("SELECT attempts FROM worker_event_outbox WHERE id=?", (int(event_id),)).fetchone()
            if row is None:
                return
            delay = min(60, 2 ** min(max(0, int(row["attempts"]) - 1), 6))
            available = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            db.execute(
                "UPDATE worker_event_outbox SET status='pending',available_at=?,last_error=? WHERE id=?",
                (available, str(error_type)[:80], int(event_id)),
            )

    def pending_event_count(self) -> int:
        with self._db() as db:
            row = db.execute("SELECT COUNT(*) AS count FROM worker_event_outbox WHERE status IN ('pending','sending')").fetchone()
        return int(row["count"])
