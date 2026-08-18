from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tme3bot.domain.models import Job, JobEvent, JobStatus


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


class SqliteJobRepository:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def _db(self):
        with self._lock:
            db = self._connect()
            try:
                yield db
                db.commit()
            finally:
                db.close()

    def _initialize(self) -> None:
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    actor_user_id INTEGER NOT NULL,
                    worker TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    progress TEXT NOT NULL DEFAULT '{}',
                    result TEXT,
                    error TEXT,
                    progress_sequence INTEGER NOT NULL DEFAULT 0,
                    archived_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_profile_status
                    ON jobs(profile, status, updated_at);
                CREATE INDEX IF NOT EXISTS jobs_actor_updated
                    ON jobs(actor_user_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS job_events (
                    job_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    progress TEXT NOT NULL DEFAULT '{}',
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, sequence),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS job_execution_plans (
                    job_id TEXT PRIMARY KEY,
                    concurrency_keys TEXT NOT NULL,
                    queue_group TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 100,
                    lane TEXT NOT NULL,
                    admitted_at TEXT,
                    released_at TEXT,
                    blocked_reason TEXT,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS job_resource_leases (
                    resource_key TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS job_commands (
                    job_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS job_telegram_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    telegram_chat_id INTEGER NOT NULL,
                    profile TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    terminal_notified_at TEXT,
                    message_id INTEGER,
                    last_status_hash TEXT,
                    error TEXT,
                    UNIQUE(job_id, telegram_chat_id),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS job_telegram_notifications_pending
                    ON job_telegram_notifications(status, terminal_notified_at);
                """
            )
            columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "archived_at" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN archived_at TEXT")
            if "progress_sequence" not in columns:
                db.execute(
                    "ALTER TABLE jobs ADD COLUMN progress_sequence INTEGER NOT NULL DEFAULT 0"
                )

    def create(self, job: Job) -> Job:
        with self._db() as db:
            db.execute(
                """
                INSERT INTO jobs(
                    id, kind, profile, actor_user_id, worker, status, payload,
                    progress, result, error, archived_at, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.kind,
                    job.profile,
                    job.actor_user_id,
                    job.worker,
                    job.status.value,
                    _dump(job.payload),
                    _dump(job.progress),
                    _dump(job.result) if job.result is not None else None,
                    _dump(job.error) if job.error is not None else None,
                    job.archived_at.isoformat() if job.archived_at else None,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )
        return job

    def get(self, job_id: str) -> Job | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row)

    def save_execution_plan(
        self, job_id: str, plan: dict[str, Any], command_payload: dict[str, Any]
    ) -> None:
        with self._db() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO job_execution_plans(
                    job_id, concurrency_keys, queue_group, priority, lane,
                    admitted_at, released_at, blocked_reason
                ) VALUES(?, ?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (
                    job_id,
                    _dump(plan.get("resource_keys", [])),
                    str(plan.get("queue_group", "")),
                    int(plan.get("priority", 100)),
                    str(plan.get("lane", "unknown")),
                ),
            )
            # This is an internal gateway table. It is never returned through
            # JobResponse; the public jobs.payload remains redacted.
            db.execute(
                "INSERT OR REPLACE INTO job_commands(job_id, payload) VALUES(?, ?)",
                (job_id, _dump(command_payload)),
            )

    def execution_plan(self, job_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM job_execution_plans WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "resource_keys": _load(row["concurrency_keys"], []),
            "queue_group": str(row["queue_group"]),
            "priority": int(row["priority"]),
            "lane": str(row["lane"]),
            "blocked_reason": row["blocked_reason"],
        }

    def command_payload(self, job_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT payload FROM job_commands WHERE job_id = ?", (job_id,)
            ).fetchone()
        return _load(row["payload"], None) if row is not None else None

    def create_telegram_notification(
        self,
        job_id: str,
        telegram_user_id: int,
        telegram_chat_id: int,
        profile: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            row = db.execute(
                """
                SELECT * FROM job_telegram_notifications
                WHERE job_id = ? AND telegram_chat_id = ?
                """,
                (job_id, int(telegram_chat_id)),
            ).fetchone()
            if row is None:
                db.execute(
                    """
                    INSERT INTO job_telegram_notifications(
                        job_id, telegram_user_id, telegram_chat_id, profile,
                        status, created_at
                    ) VALUES(?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        job_id,
                        int(telegram_user_id),
                        int(telegram_chat_id),
                        profile,
                        now,
                    ),
                )
                row = db.execute(
                    "SELECT * FROM job_telegram_notifications WHERE id = last_insert_rowid()"
                ).fetchone()
        assert row is not None
        return dict(row)

    def telegram_notification(self, notification_id: int) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM job_telegram_notifications WHERE id = ?",
                (int(notification_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def pending_telegram_notifications(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                """
                SELECT * FROM job_telegram_notifications
                WHERE status = 'pending' AND terminal_notified_at IS NULL
                ORDER BY created_at, id
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_telegram_notification(
        self, notification_id: int, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "status",
            "terminal_notified_at",
            "message_id",
            "last_status_hash",
            "error",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return self.telegram_notification(notification_id)
        current = self.telegram_notification(notification_id)
        if current is None:
            return None
        if current.get("terminal_notified_at") and updates.get("terminal_notified_at"):
            updates.pop("terminal_notified_at", None)
            if not updates:
                return current
        if "error" in updates and not isinstance(updates["error"], str):
            updates["error"] = _dump(updates["error"])
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self._db() as db:
            db.execute(
                f"UPDATE job_telegram_notifications SET {assignments} WHERE id = ?",
                (*updates.values(), int(notification_id)),
            )
        return self.telegram_notification(notification_id)

    def try_acquire_execution(self, job_id: str) -> dict[str, Any]:
        """Acquire all keys or return a deterministic queue position."""
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                DELETE FROM job_resource_leases
                WHERE job_id IN (
                    SELECT id FROM jobs WHERE status IN ('succeeded', 'failed', 'cancelled')
                )
                """
            )
            plan_row = db.execute(
                "SELECT * FROM job_execution_plans WHERE job_id = ?", (job_id,)
            ).fetchone()
            if plan_row is None:
                return {"admitted": True, "position": 1, "blocked_reason": None}
            keys = set(_load(plan_row["concurrency_keys"], []))
            if not keys:
                return {"admitted": True, "position": 1, "blocked_reason": None}
            placeholders = ",".join("?" for _ in keys)
            conflicts = db.execute(
                f"SELECT resource_key, job_id FROM job_resource_leases WHERE resource_key IN ({placeholders})",
                tuple(keys),
            ).fetchall()
            conflicts = [item for item in conflicts if str(item["job_id"]) != job_id]
            if conflicts:
                queued_rows = db.execute(
                    """
                    SELECT p.job_id, p.concurrency_keys
                    FROM job_execution_plans p
                    JOIN jobs j ON j.id = p.job_id
                    WHERE j.status = 'queued' AND j.created_at <= (
                        SELECT created_at FROM jobs WHERE id = ?
                    )
                    ORDER BY j.created_at, p.priority, p.job_id
                    """,
                    (job_id,),
                ).fetchall()
                position = 1
                for queued in queued_rows:
                    if set(_load(queued["concurrency_keys"], [])) & keys:
                        if str(queued["job_id"]) == job_id:
                            break
                        position += 1
                reason = f"Menunggu {str(conflicts[0]['resource_key'])}"
                db.execute(
                    "UPDATE job_execution_plans SET blocked_reason = ? WHERE job_id = ?",
                    (reason, job_id),
                )
                return {"admitted": False, "position": position, "blocked_reason": reason}
            worker = db.execute(
                "SELECT worker FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            for key in keys:
                db.execute(
                    "INSERT INTO job_resource_leases(resource_key, job_id, acquired_at, worker) VALUES(?, ?, ?, ?)",
                    (key, job_id, now, str(worker["worker"] if worker else "")),
                )
            db.execute(
                "UPDATE job_execution_plans SET admitted_at = ?, blocked_reason = NULL WHERE job_id = ?",
                (now, job_id),
            )
            return {"admitted": True, "position": 1, "blocked_reason": None}

    def release_execution(self, job_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("DELETE FROM job_resource_leases WHERE job_id = ?", (job_id,))
            db.execute(
                "UPDATE job_execution_plans SET released_at = ? WHERE job_id = ?",
                (now, job_id),
            )

    def set_queue_info(self, job_id: str, position: int, reason: str | None) -> None:
        with self._db() as db:
            row = db.execute("SELECT progress FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return
            progress = _load(row["progress"], {})
            progress["position"] = max(1, int(position))
            if reason:
                progress["blocked_reason"] = reason
            else:
                progress.pop("blocked_reason", None)
            db.execute(
                "UPDATE jobs SET progress = ?, updated_at = ? WHERE id = ?",
                (_dump(progress), datetime.now(timezone.utc).isoformat(), job_id),
            )

    def list(
        self,
        *,
        actor_user_id: int | None = None,
        profile: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        worker: str | None = None,
        archived: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Job]:
        clauses, values = [], []
        if actor_user_id is not None:
            clauses.append("actor_user_id = ?")
            values.append(int(actor_user_id))
        if profile is not None:
            clauses.append("profile = ?")
            values.append(profile)
        if kind:
            clauses.append("kind = ?")
            values.append(kind)
        if status:
            clauses.append("status = ?")
            values.append(status)
        if worker:
            clauses.append("worker = ?")
            values.append(worker)
        if archived is True:
            clauses.append("archived_at IS NOT NULL")
        elif archived is False:
            clauses.append("archived_at IS NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(max(1, min(int(limit), 200)))
        values.append(max(0, int(offset)))
        with self._db() as db:
            rows = db.execute(
                f"SELECT * FROM jobs{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                values,
            ).fetchall()
        return [job for row in rows if (job := self._job(row)) is not None]

    def count(
        self,
        *,
        profile: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        worker: str | None = None,
        archived: bool | None = None,
    ) -> int:
        clauses, values = [], []
        for column, value in (
            ("profile", profile),
            ("kind", kind),
            ("status", status),
            ("worker", worker),
        ):
            if value:
                clauses.append(f"{column} = ?")
                values.append(value)
        if archived is True:
            clauses.append("archived_at IS NOT NULL")
        elif archived is False:
            clauses.append("archived_at IS NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._db() as db:
            return int(db.execute(f"SELECT COUNT(*) FROM jobs{where}", values).fetchone()[0])

    def set_archived(self, job_id: str, archived: bool) -> Job:
        now = datetime.now(timezone.utc).isoformat() if archived else None
        with self._db() as db:
            row = db.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown job: {job_id}")
            if not JobStatus(str(row["status"])).terminal:
                raise ValueError("Hanya job terminal yang dapat diarsipkan.")
            db.execute(
                "UPDATE jobs SET archived_at = ?, updated_at = ? WHERE id = ?",
                (now, datetime.now(timezone.utc).isoformat(), job_id),
            )
        result = self.get(job_id)
        assert result is not None
        return result

    def purge(self, job_id: str) -> bool:
        with self._db() as db:
            row = db.execute(
                "SELECT status, archived_at FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return False
            if not JobStatus(str(row["status"])).terminal or not row["archived_at"]:
                raise ValueError("Job harus terminal dan diarsipkan sebelum purge.")
            db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return True

    def append_event(self, event: JobEvent) -> tuple[Job, bool]:
        with self._db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (event.job_id,)).fetchone()
            job = self._job(row)
            if job is None:
                raise KeyError(f"Unknown job: {event.job_id}")
            existing = db.execute(
                "SELECT 1 FROM job_events WHERE job_id = ? AND sequence = ?",
                (event.job_id, event.sequence),
            ).fetchone()
            if existing:
                return job, False
            job.ensure_transition(event.status)
            db.execute(
                """
                INSERT INTO job_events(
                    job_id, sequence, status, event_type, progress, result,
                    error, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.job_id,
                    event.sequence,
                    event.status.value,
                    event.event_type,
                    _dump(event.progress),
                    _dump(event.result) if event.result is not None else None,
                    _dump(event.error) if event.error is not None else None,
                    event.created_at.isoformat(),
                ),
            )
            progress = event.progress or job.progress
            result = event.result if event.result is not None else job.result
            error = event.error if event.error is not None else job.error
            db.execute(
                """
                UPDATE jobs
                SET status = ?, progress = ?, result = ?, error = ?,
                    progress_sequence = MAX(progress_sequence, ?), updated_at = ?
                WHERE id = ?
                """,
                (
                    event.status.value,
                    _dump(progress),
                    _dump(result) if result is not None else None,
                    _dump(error) if error is not None else None,
                    event.sequence,
                    event.created_at.isoformat(),
                    event.job_id,
                ),
            )
            return (
                replace(
                    job,
                    status=event.status,
                    progress=progress,
                    result=result,
                    error=error,
                    updated_at=event.created_at,
                ),
                True,
            )

    def update_progress_snapshot(self, event: JobEvent) -> tuple[Job, bool]:
        """Keep only the newest high-frequency telemetry snapshot."""
        with self._db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (event.job_id,)).fetchone()
            job = self._job(row)
            if job is None:
                raise KeyError(f"Unknown job: {event.job_id}")
            if job.status.terminal:
                return job, False
            current_sequence = int(row["progress_sequence"] or 0)
            if event.sequence <= current_sequence:
                return job, False
            job.ensure_transition(event.status)
            db.execute(
                """
                UPDATE jobs
                SET status = ?, progress = ?, progress_sequence = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    event.status.value,
                    _dump(event.progress),
                    event.sequence,
                    event.created_at.isoformat(),
                    event.job_id,
                ),
            )
            return (
                replace(
                    job,
                    status=event.status,
                    progress=event.progress,
                    updated_at=event.created_at,
                ),
                True,
            )

    def events(self, job_id: str, *, after_sequence: int = 0) -> list[JobEvent]:
        with self._db() as db:
            rows = db.execute(
                """
                SELECT * FROM job_events
                WHERE job_id = ? AND sequence > ?
                ORDER BY sequence
                """,
                (job_id, int(after_sequence)),
            ).fetchall()
        return [self._event(row) for row in rows]

    def has_active(self, profile: str) -> bool:
        active = (
            JobStatus.QUEUED.value,
            JobStatus.DISPATCHED.value,
            JobStatus.RUNNING.value,
        )
        with self._db() as db:
            row = db.execute(
                "SELECT 1 FROM jobs WHERE profile = ? AND status IN (?, ?, ?) LIMIT 1",
                (profile, *active),
            ).fetchone()
        return row is not None

    @staticmethod
    def _job(row: sqlite3.Row | None) -> Job | None:
        if row is None:
            return None
        return Job(
            id=str(row["id"]),
            kind=str(row["kind"]),
            profile=str(row["profile"]),
            actor_user_id=int(row["actor_user_id"]),
            worker=str(row["worker"]),
            status=JobStatus(str(row["status"])),
            payload=_load(row["payload"], {}),
            progress=_load(row["progress"], {}),
            result=_load(row["result"], None),
            error=_load(row["error"], None),
            archived_at=(
                datetime.fromisoformat(row["archived_at"])
                if row["archived_at"]
                else None
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _event(row: sqlite3.Row) -> JobEvent:
        return JobEvent(
            job_id=str(row["job_id"]),
            sequence=int(row["sequence"]),
            status=JobStatus(str(row["status"])),
            event_type=str(row["event_type"]),
            progress=_load(row["progress"], {}),
            result=_load(row["result"], None),
            error=_load(row["error"], None),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
