from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tme3bot.domain.models import Job, JobEvent, JobStatus
from tme3bot.resource_locks import first_resource_conflict


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _quick_mode_sql(quick_mode: bool | None) -> tuple[str, list[object]]:
    """Filter the compact JSON payload without requiring SQLite JSON1."""
    marker = "(payload LIKE '%\"quick_mode\":true%' OR payload LIKE '%\"quick_mode\": true%')"
    if quick_mode is True:
        return marker, []
    if quick_mode is False:
        return f"NOT {marker}", []
    return "", []


def _append_status_filter(
    clauses: list[str],
    values: list[object],
    *,
    status: str | None,
    statuses: tuple[str, ...] | None,
) -> None:
    if statuses is None:
        if status:
            clauses.append("status = ?")
            values.append(status)
        return

    selected = tuple(dict.fromkeys(value for value in statuses if value))
    if not selected:
        return
    if len(selected) == 1:
        clauses.append("status = ?")
        values.append(selected[0])
        return

    placeholders = ", ".join("?" for _ in selected)
    clauses.append(f"status IN ({placeholders})")
    values.extend(selected)


def _elapsed_between(started_at: str, finished_at: str) -> float:
    try:
        started = datetime.fromisoformat(str(started_at))
        finished = datetime.fromisoformat(str(finished_at))
    except (TypeError, ValueError):
        return 0.0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    return max(0.0, (finished - started).total_seconds())


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

    @contextmanager
    def unit_of_work(self):
        """Expose one write transaction for multi-repository SQLite units."""
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

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
                    settings_version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS job_private_values (
                    job_id TEXT NOT NULL,
                    setting_key TEXT NOT NULL,
                    ciphertext BLOB NOT NULL,
                    PRIMARY KEY(job_id, setting_key),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
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
                CREATE TABLE IF NOT EXISTS late_worker_events (
                    job_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, sequence, event_type),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS late_worker_events_type
                    ON late_worker_events(job_id, event_type, sequence);
                CREATE TABLE IF NOT EXISTS job_execution_plans (
                    job_id TEXT PRIMARY KEY,
                    concurrency_keys TEXT NOT NULL,
                    queue_group TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 100,
                    lane TEXT NOT NULL,
                    queued_at TEXT,
                    admitted_at TEXT,
                    released_at TEXT,
                    blocked_reason TEXT,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS job_resource_leases (
                    resource_key TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    PRIMARY KEY(resource_key, job_id),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS quickmode_worker_limits (
                    worker TEXT PRIMARY KEY,
                    max_concurrent INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS job_quickmode_slots (
                    job_id TEXT PRIMARY KEY,
                    worker TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS job_quickmode_slots_worker
                    ON job_quickmode_slots(worker);
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
                CREATE TABLE IF NOT EXISTS job_tts_deliveries (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    title TEXT NOT NULL,
                    artifact_ref TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    part_index INTEGER NOT NULL,
                    total_parts INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at TEXT NOT NULL,
                    lease_until TEXT,
                    uploaded_at REAL,
                    sender_profile TEXT,
                    delivered_at TEXT,
                    last_error_code TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(job_id, part_index),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS job_tts_deliveries_pending
                    ON job_tts_deliveries(status, available_at, lease_until);
                CREATE TABLE IF NOT EXISTS tts_service_health (
                    service TEXT PRIMARY KEY,
                    ready INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
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
            if "settings_version" not in columns:
                db.execute(
                    "ALTER TABLE jobs ADD COLUMN settings_version INTEGER NOT NULL DEFAULT 0"
                )
            tts_delivery_columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(job_tts_deliveries)").fetchall()
            }
            if "uploaded_at" not in tts_delivery_columns:
                db.execute("ALTER TABLE job_tts_deliveries ADD COLUMN uploaded_at REAL")
            if "sender_profile" not in tts_delivery_columns:
                db.execute("ALTER TABLE job_tts_deliveries ADD COLUMN sender_profile TEXT")
            db.execute(
                """
                UPDATE jobs
                SET progress_sequence = (
                    SELECT COALESCE(MAX(sequence), 0)
                    FROM job_events WHERE job_events.job_id = jobs.id
                )
                WHERE status IN ('queued', 'dispatched', 'running', 'paused')
                  AND progress_sequence < (
                    SELECT COALESCE(MAX(sequence), 0)
                    FROM job_events WHERE job_events.job_id = jobs.id
                  )
                """
            )
            plan_columns = {
                str(row["name"])
                for row in db.execute(
                    "PRAGMA table_info(job_execution_plans)"
                ).fetchall()
            }
            if "queued_at" not in plan_columns:
                db.execute("ALTER TABLE job_execution_plans ADD COLUMN queued_at TEXT")
            db.execute(
                "CREATE INDEX IF NOT EXISTS job_execution_plans_queued_at "
                "ON job_execution_plans(queued_at, priority, job_id)"
            )
            db.execute(
                """
                UPDATE job_execution_plans SET queued_at = (
                    SELECT created_at FROM jobs WHERE jobs.id = job_execution_plans.job_id
                ) WHERE queued_at IS NULL
                """
            )
            db.execute(
                """
                INSERT OR IGNORE INTO job_quickmode_slots(job_id, worker, acquired_at)
                SELECT id, worker, updated_at FROM jobs
                WHERE status IN ('dispatched', 'running')
                  AND (payload LIKE '%\"quick_mode\":true%'
                       OR payload LIKE '%\"quick_mode\": true%')
                """
            )
            db.commit()
            self._ensure_resource_lease_schema(db)

    @staticmethod
    def _ensure_resource_lease_schema(db: sqlite3.Connection) -> None:
        """Allow multiple shared holders while preserving existing leases."""
        db.execute("BEGIN IMMEDIATE")
        columns = db.execute("PRAGMA table_info(job_resource_leases)").fetchall()
        primary_key = [
            str(row["name"])
            for row in sorted(columns, key=lambda item: int(item["pk"]))
            if int(row["pk"])
        ]
        if primary_key == ["resource_key"]:
            db.execute(
                "ALTER TABLE job_resource_leases RENAME TO job_resource_leases_legacy"
            )
            db.execute(
                """
                CREATE TABLE job_resource_leases (
                    resource_key TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    PRIMARY KEY(resource_key, job_id),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                )
                """
            )
            db.execute(
                """
                INSERT INTO job_resource_leases(
                    resource_key, job_id, acquired_at, worker
                )
                SELECT resource_key, job_id, acquired_at, worker
                FROM job_resource_leases_legacy
                """
            )
            db.execute("DROP TABLE job_resource_leases_legacy")
        elif primary_key != ["resource_key", "job_id"]:
            raise RuntimeError("Unsupported job resource lease schema.")
        db.execute(
            "CREATE INDEX IF NOT EXISTS job_resource_leases_job_id "
            "ON job_resource_leases(job_id)"
        )

    def create(self, job: Job) -> Job:
        return self.create_with_private_values(job, {})

    def create_with_private_values(
        self,
        job: Job,
        private_values: dict[str, bytes],
        *,
        execution_plan: dict[str, Any] | None = None,
        command_payload: dict[str, Any] | None = None,
    ) -> Job:
        if (execution_plan is None) != (command_payload is None):
            raise ValueError("Execution plan dan command payload harus disimpan bersama.")
        with self._db() as db:
            if execution_plan is not None and command_payload is not None:
                self.insert_prepared_job(
                    db,
                    job,
                    execution_plan,
                    command_payload,
                    private_values,
                )
                return job
            db.execute(
                """
                INSERT INTO jobs(
                    id, kind, profile, actor_user_id, worker, status, payload,
                    progress, result, error, progress_sequence, archived_at,
                    settings_version, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    max(0, int(job.progress_sequence)),
                    job.archived_at.isoformat() if job.archived_at else None,
                    max(0, int(job.settings_version)),
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )
            self._insert_private_values(db, job.id, private_values)
        return job

    @staticmethod
    def _insert_private_values(
        db: sqlite3.Connection, job_id: str, private_values: dict[str, bytes] | None
    ) -> None:
        for key, ciphertext in (private_values or {}).items():
            db.execute(
                "INSERT INTO job_private_values(job_id,setting_key,ciphertext) VALUES(?,?,?)",
                (str(job_id), str(key), sqlite3.Binary(ciphertext)),
            )

    def private_value(self, job_id: str, key: str) -> bytes | None:
        with self._db() as db:
            row = db.execute(
                "SELECT ciphertext FROM job_private_values WHERE job_id=? AND setting_key=?",
                (str(job_id), str(key)),
            ).fetchone()
        return bytes(row["ciphertext"]) if row is not None else None

    @staticmethod
    def insert_prepared_job(
        db: sqlite3.Connection,
        job: Job,
        execution_plan: dict[str, Any],
        command_payload: dict[str, Any],
        private_values: dict[str, bytes] | None = None,
    ) -> None:
        """Insert a job, scheduler plan, and private command on a caller's transaction."""
        db.execute(
            """INSERT INTO jobs(
                   id, kind, profile, actor_user_id, worker, status, payload,
                   progress, result, error, progress_sequence, archived_at,
                   settings_version, created_at, updated_at
               ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job.id, job.kind, job.profile, job.actor_user_id, job.worker,
                job.status.value, _dump(job.payload), _dump(job.progress),
                _dump(job.result) if job.result is not None else None,
                _dump(job.error) if job.error is not None else None,
                max(0, int(job.progress_sequence)),
                job.archived_at.isoformat() if job.archived_at else None,
                max(0, int(job.settings_version)),
                job.created_at.isoformat(), job.updated_at.isoformat(),
            ),
        )
        SqliteJobRepository._insert_private_values(db, job.id, private_values)
        db.execute(
            """INSERT INTO job_execution_plans(
                   job_id, concurrency_keys, queue_group, priority, lane,
                   queued_at, admitted_at, released_at, blocked_reason
               ) VALUES(?, ?, ?, ?, ?, ?, NULL, NULL, NULL)""",
            (
                job.id,
                _dump(execution_plan.get("resource_keys", [])),
                str(execution_plan.get("queue_group", "")),
                int(execution_plan.get("priority", 100)),
                str(execution_plan.get("lane", "unknown")),
                str(execution_plan.get("queued_at") or datetime.now(timezone.utc).isoformat()),
            ),
        )
        db.execute(
            "INSERT INTO job_commands(job_id, payload) VALUES(?, ?)",
            (job.id, _dump(command_payload)),
        )

    def get(self, job_id: str) -> Job | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row)

    def reset_for_retry(
        self, job_id: str, payload: dict[str, Any], *,
        settings_version: int | None = None,
        private_values: dict[str, bytes] | None = None,
        execution_plan: dict[str, Any] | None = None,
        command_payload: dict[str, Any] | None = None,
        retry_event: JobEvent | None = None,
    ) -> Job:
        """Reset a terminal row for a new attempt without changing its ID.

        The old lifecycle remains in ``job_events``. A monotonically
        increasing event sequence lets the worker publish the new attempt
        without colliding with the previous attempt's telemetry.
        """
        if (execution_plan is None) != (command_payload is None):
            raise ValueError("Execution plan dan command payload harus disimpan bersama.")
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,settings_version,progress_sequence FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown job: {job_id}")
            if not JobStatus(str(row["status"])).terminal:
                raise ValueError("Hanya job terminal yang dapat diulang.")
            max_sequence = max(
                int(row["progress_sequence"] or 0),
                db.execute(
                    "SELECT COALESCE(MAX(sequence), 0) FROM job_events WHERE job_id = ?",
                    (job_id,),
                ).fetchone()[0]
            )
            selected_settings_version = (
                max(0, int(settings_version))
                if settings_version is not None
                else int(row["settings_version"] or 0)
            )
            db.execute(
                """
                UPDATE jobs
                SET status = 'queued', payload = ?, progress = ?, result = NULL,
                    error = NULL, progress_sequence = ?, archived_at = NULL,
                    settings_version = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    _dump(payload),
                    _dump({"phase": "queued", "retry_sequence": max_sequence + 1}),
                    max_sequence,
                    selected_settings_version,
                    now,
                    job_id,
                ),
            )
            if private_values is not None:
                db.execute("DELETE FROM job_private_values WHERE job_id=?", (job_id,))
                self._insert_private_values(db, job_id, private_values)
            db.execute(
                "DELETE FROM job_resource_leases WHERE job_id = ?", (job_id,)
            )
            if execution_plan is not None and command_payload is not None:
                db.execute(
                    """
                    INSERT OR REPLACE INTO job_execution_plans(
                        job_id, concurrency_keys, queue_group, priority, lane,
                        queued_at, admitted_at, released_at, blocked_reason
                    ) VALUES(?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
                    """,
                    (
                        job_id,
                        _dump(execution_plan.get("resource_keys", [])),
                        str(execution_plan.get("queue_group", "")),
                        int(execution_plan.get("priority", 100)),
                        str(execution_plan.get("lane", "unknown")),
                        str(execution_plan.get("queued_at") or now),
                    ),
                )
                db.execute(
                    "INSERT OR REPLACE INTO job_commands(job_id, payload) VALUES(?, ?)",
                    (job_id, _dump(command_payload)),
                )
            if retry_event is not None:
                db.execute(
                    """
                    INSERT INTO job_events(
                        job_id, sequence, status, event_type, progress, result,
                        error, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        retry_event.job_id,
                        retry_event.sequence,
                        retry_event.status.value,
                        retry_event.event_type,
                        _dump(retry_event.progress),
                        _dump(retry_event.result) if retry_event.result is not None else None,
                        _dump(retry_event.error) if retry_event.error is not None else None,
                        retry_event.created_at.isoformat(),
                    ),
                )
                progress = {
                    "phase": "queued",
                    "retry_sequence": retry_event.sequence,
                    **retry_event.progress,
                }
                db.execute(
                    "UPDATE jobs SET progress = ?, progress_sequence = ? WHERE id = ?",
                    (_dump(progress), retry_event.sequence, job_id),
                )
            # A reused job ID also reuses its Telegram status message, but it
            # must become eligible for a fresh terminal notification.
            db.execute(
                """
                UPDATE job_telegram_notifications
                SET status = 'pending', terminal_notified_at = NULL,
                    last_status_hash = NULL, error = NULL
                WHERE job_id = ?
                """,
                (job_id,),
            )
        result = self.get(job_id)
        if result is None:
            raise KeyError(f"Unknown job: {job_id}")
        return result

    def save_execution_plan(
        self, job_id: str, plan: dict[str, Any], command_payload: dict[str, Any]
    ) -> None:
        with self._db() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO job_execution_plans(
                    job_id, concurrency_keys, queue_group, priority, lane,
                    queued_at, admitted_at, released_at, blocked_reason
                ) VALUES(?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (
                    job_id,
                    _dump(plan.get("resource_keys", [])),
                    str(plan.get("queue_group", "")),
                    int(plan.get("priority", 100)),
                    str(plan.get("lane", "unknown")),
                    datetime.now(timezone.utc).isoformat(),
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
            "queued_at": str(row["queued_at"] or ""),
            "blocked_reason": row["blocked_reason"],
        }

    def command_payload(self, job_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT payload FROM job_commands WHERE job_id = ?", (job_id,)
            ).fetchone()
        return _load(row["payload"], None) if row is not None else None

    def update_command_payload(self, job_id: str, payload: dict[str, Any]) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE job_commands SET payload = ? WHERE job_id = ?",
                (_dump(payload), job_id),
            )

    def advance_durable_attempt(
        self, job_id: str, attempt: int, payload: dict[str, Any]
    ) -> str:
        """Persist a retried command identity without dropping a fresh cancel."""
        target_attempt = max(1, int(attempt))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT j.status, j.progress, j.progress_sequence,
                          c.payload AS command_payload
                   FROM jobs AS j JOIN job_commands AS c ON c.job_id=j.id
                   WHERE j.id=?""",
                (str(job_id),),
            ).fetchone()
            if row is None:
                db.commit()
                return "job_missing"
            if str(row["status"]) != JobStatus.QUEUED.value:
                db.commit()
                return "not_queued"
            current_payload = _load(row["command_payload"], None)
            current, nested_key = self._dispatch_record(current_payload)
            if current is None or not isinstance(current_payload, dict):
                db.commit()
                return "not_durable"
            current_attempt = max(1, int(current.get("attempt") or 1))
            if current_attempt >= target_attempt:
                db.commit()
                return "already_advanced"
            if current.get("dispatch_started"):
                db.commit()
                return "dispatch_started"

            queued_attempt = int(
                db.execute(
                    "SELECT COUNT(*) FROM job_events WHERE job_id=? AND event_type='retry_started'",
                    (str(job_id),),
                ).fetchone()[0]
            ) + 1
            replacement, replacement_key = self._dispatch_record(payload)
            if replacement is None:
                db.commit()
                return "not_durable"
            replacement = dict(replacement)
            # Cancellation intent belongs to a logical queued attempt. Discard
            # an old marker, but preserve a cancel requested for this retry.
            cancel_attempt = int(
                current.get("cancel_before_dispatch_attempt") or current_attempt
            )
            if current.get("cancel_before_dispatch") and cancel_attempt >= queued_attempt:
                replacement["cancel_before_dispatch"] = True
                replacement["cancel_before_dispatch_attempt"] = cancel_attempt
            else:
                replacement["cancel_before_dispatch"] = False
                replacement.pop("cancel_before_dispatch_attempt", None)

            after_attempt = int(current.get("cancel_after_dispatch_attempt") or 0)
            if current.get("cancel_after_dispatch") and after_attempt >= target_attempt:
                replacement["cancel_after_dispatch"] = True
                replacement["cancel_after_dispatch_attempt"] = after_attempt
                replacement["cancel_after_dispatch_accepted"] = bool(
                    current.get("cancel_after_dispatch_accepted")
                )
            else:
                replacement["cancel_after_dispatch"] = False
                replacement.pop("cancel_after_dispatch_attempt", None)
                replacement["cancel_after_dispatch_accepted"] = False

            replacement["attempt"] = target_attempt
            replacement["dispatch_started"] = False
            stored_payload = dict(payload)
            if replacement_key:
                stored_payload[replacement_key] = replacement
            else:
                stored_payload = replacement
            db.execute(
                "UPDATE job_commands SET payload=? WHERE job_id=?",
                (_dump(stored_payload), str(job_id)),
            )
            retry_count = int(
                db.execute(
                    "SELECT COUNT(*) FROM job_events WHERE job_id=? AND event_type='retry_started'",
                    (str(job_id),),
                ).fetchone()[0]
            )
            if retry_count < target_attempt - 1:
                max_sequence = max(
                    int(row["progress_sequence"] or 0),
                    int(
                        db.execute(
                            "SELECT COALESCE(MAX(sequence),0) FROM job_events WHERE job_id=?",
                            (str(job_id),),
                        ).fetchone()[0]
                    ),
                )
                retry_event = JobEvent(
                    job_id=str(job_id),
                    sequence=max_sequence + 1,
                    status=JobStatus.QUEUED,
                    event_type="retry_started",
                    progress={"phase": "queued", "retry_attempt": target_attempt},
                )
                db.execute(
                    """INSERT INTO job_events(
                           job_id, sequence, status, event_type, progress, result,
                           error, created_at
                       ) VALUES(?, ?, ?, ?, ?, NULL, NULL, ?)""",
                    (
                        retry_event.job_id,
                        retry_event.sequence,
                        retry_event.status.value,
                        retry_event.event_type,
                        _dump(retry_event.progress),
                        retry_event.created_at.isoformat(),
                    ),
                )
                db.execute(
                    "UPDATE jobs SET progress=?,progress_sequence=?,updated_at=? WHERE id=?",
                    (
                        _dump({
                            "phase": "queued",
                            "retry_sequence": retry_event.sequence,
                            **retry_event.progress,
                        }),
                        retry_event.sequence,
                        datetime.now(timezone.utc).isoformat(),
                        str(job_id),
                    ),
                )
            db.commit()
            return "advanced"

    def dispatch_cancel_requests(self, limit: int = 500) -> list[tuple[Job, int]]:
        """Return active jobs with an unacknowledged post-dispatch cancel intent."""
        bounded_limit = max(1, min(int(limit), 5000))
        with self._db() as db:
            rows = db.execute(
                """SELECT j.*, c.payload AS command_payload
                   FROM jobs AS j JOIN job_commands AS c ON c.job_id=j.id
                   WHERE j.status IN ('queued','dispatched','running','paused')
                     AND c.payload LIKE '%\"cancel_after_dispatch\":true%'
                     AND c.payload NOT LIKE '%\"cancel_after_dispatch_accepted\":true%'
                   ORDER BY j.updated_at, j.id LIMIT ?""",
                (bounded_limit,),
            ).fetchall()
        result: list[tuple[Job, int]] = []
        for row in rows:
            payload = _load(row["command_payload"], None)
            record, _nested_key = self._dispatch_record(payload)
            if not isinstance(record, dict):
                continue
            if not record.get("cancel_after_dispatch"):
                continue
            if record.get("cancel_after_dispatch_accepted"):
                continue
            attempt = max(1, int(record.get("cancel_after_dispatch_attempt") or record.get("attempt") or 1))
            job = self._job(row)
            if job is not None:
                result.append((job, attempt))
        return result

    def acknowledge_dispatch_cancellation(self, job_id: str, attempt: int) -> bool:
        """Stop scheduler retries once the worker has durably accepted cancel."""
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM job_commands WHERE job_id=?", (str(job_id),)
            ).fetchone()
            if row is None:
                db.commit()
                return False
            payload = _load(row["payload"], None)
            record, nested_key = self._dispatch_record(payload)
            if record is None or not isinstance(payload, dict):
                db.commit()
                return False
            if int(record.get("cancel_after_dispatch_attempt") or 0) != int(attempt):
                db.commit()
                return False
            record["cancel_after_dispatch_accepted"] = True
            if nested_key:
                payload[nested_key] = record
            db.execute(
                "UPDATE job_commands SET payload=? WHERE job_id=?",
                (_dump(payload), str(job_id)),
            )
            db.commit()
            return True

    @staticmethod
    def _dispatch_record(payload: Any) -> tuple[dict[str, Any] | None, str | None]:
        if not isinstance(payload, dict):
            return None, None
        if payload.get("dispatch_mode") == "durable":
            return payload, None
        storage = payload.get("_storage_durable_dispatch")
        if isinstance(storage, dict) and storage.get("command_id") and storage.get("dispatch_token"):
            return storage, "_storage_durable_dispatch"
        return None, None

    def begin_queued_worker_dispatch(
        self,
        job_id: str,
        *,
        attempt: int | None = None,
        command_id: str | None = None,
        operation_id: str | None = None,
    ) -> str:
        """Atomically claim dispatch only for the current command attempt."""
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT j.status, c.payload AS command_payload
                   FROM jobs AS j
                   JOIN job_commands AS c ON c.job_id=j.id
                   WHERE j.id=?""",
                (str(job_id),),
            ).fetchone()
            if row is None or str(row["status"]) != JobStatus.QUEUED.value:
                db.commit()
                return "not_queued"
            payload = _load(row["command_payload"], None)
            record, nested_key = self._dispatch_record(payload)
            if record is None or not isinstance(payload, dict):
                db.commit()
                return "not_durable"
            if attempt is not None and int(record.get("attempt") or 1) != int(attempt):
                db.commit()
                return "stale_attempt"
            if command_id is not None and str(record.get("command_id") or "") != str(command_id):
                db.commit()
                return "stale_command"
            operation_status = ""
            operations_table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='operations'"
            ).fetchone()
            if operation_id is not None:
                if operations_table is None:
                    db.commit()
                    return "stale_attempt"
                operation_row = db.execute(
                    "SELECT id, attempt, status FROM operations WHERE job_id=? AND id=?",
                    (str(job_id), str(operation_id)),
                ).fetchone()
                if (
                    operation_row is None
                    or int(operation_row["attempt"] or 1) != int(attempt or 1)
                ):
                    db.commit()
                    return "stale_attempt"
                operation_status = str(operation_row["status"] or "")
            elif operations_table is not None:
                operation_row = db.execute(
                    "SELECT status FROM operations WHERE job_id=?",
                    (str(job_id),),
                ).fetchone()
                operation_status = str(operation_row["status"] or "") if operation_row else ""
            if operation_status in {
                "cancelling", "cancelled", "succeeded", "failed", "needs_reconciliation"
            }:
                db.commit()
                return (
                    "operation_cancelling_dispatched"
                    if record.get("dispatch_started")
                    else "operation_cancelling"
                )
            queued_attempt = int(
                db.execute(
                    "SELECT COUNT(*) FROM job_events WHERE job_id=? AND event_type='retry_started'",
                    (str(job_id),),
                ).fetchone()[0]
            ) + 1
            cancel_attempt = int(record.get("cancel_before_dispatch_attempt") or 1)
            if record.get("cancel_before_dispatch") and cancel_attempt == queued_attempt:
                db.commit()
                return "cancel_requested"
            if record.get("cancel_before_dispatch"):
                # A queued retry supersedes cancellation intent from the prior
                # attempt. Keep this reset inside the same transaction as the
                # dispatch claim so a fresh cancel cannot be lost.
                record["cancel_before_dispatch"] = False
                record.pop("cancel_before_dispatch_attempt", None)
            if not record.get("dispatch_started"):
                record["dispatch_started"] = True
                if nested_key:
                    payload[nested_key] = record
                db.execute(
                    "UPDATE job_commands SET payload=? WHERE job_id=?",
                    (_dump(payload), str(job_id)),
                )
            elif record.get("cancel_after_dispatch"):
                # Leave the delivery intent in place; the scheduler retries
                # until the worker confirms it has recorded the cancellation.
                if nested_key:
                    payload[nested_key] = record
                    db.execute(
                        "UPDATE job_commands SET payload=? WHERE job_id=?",
                        (_dump(payload), str(job_id)),
                    )
            db.commit()
            return "started"

    def begin_durable_dispatch(
        self,
        job_id: str,
        *,
        attempt: int | None = None,
        command_id: str | None = None,
        operation_id: str | None = None,
    ) -> bool:
        """Compatibility wrapper for durable operation command dispatch."""
        return self.begin_queued_worker_dispatch(
            job_id,
            attempt=attempt,
            command_id=command_id,
            operation_id=operation_id,
        ) == "started"

    def request_queued_cancellation(self, job_id: str) -> str:
        """Reserve queued cancellation atomically against worker dispatch.

        A returned ``dispatch_started`` means the command may have reached a
        worker and must be cancelled there. ``safe`` is reserved for legacy
        commands that have no one-way durable dispatch boundary.
        """
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT j.status, j.progress, c.payload AS command_payload
                   FROM jobs AS j
                   LEFT JOIN job_commands AS c ON c.job_id=j.id
                   WHERE j.id=?""",
                (str(job_id),),
            ).fetchone()
            if row is None or JobStatus(str(row["status"])).terminal:
                db.commit()
                return "terminal"
            status = str(row["status"])
            progress = _load(row["progress"], {})
            queued = status == JobStatus.QUEUED.value or (
                status == JobStatus.PAUSED.value
                and isinstance(progress, dict)
                and progress.get("pause_kind") == "queued"
            )
            if not queued:
                db.commit()
                return "not_queued"
            payload = _load(row["command_payload"], None)
            record, nested_key = self._dispatch_record(payload)
            if record is None or not isinstance(payload, dict):
                db.commit()
                return "safe"
            queued_attempt = int(
                db.execute(
                    "SELECT COUNT(*) FROM job_events WHERE job_id=? AND event_type='retry_started'",
                    (str(job_id),),
                ).fetchone()[0]
            ) + 1
            if record.get("dispatch_started"):
                same_intent = (
                    record.get("cancel_after_dispatch")
                    and int(record.get("cancel_after_dispatch_attempt") or 0)
                    == queued_attempt
                )
                record["cancel_after_dispatch"] = True
                record["cancel_after_dispatch_attempt"] = queued_attempt
                if not same_intent:
                    record["cancel_after_dispatch_accepted"] = False
                if nested_key:
                    payload[nested_key] = record
                db.execute(
                    "UPDATE job_commands SET payload=? WHERE job_id=?",
                    (_dump(payload), str(job_id)),
                )
                db.commit()
                return "dispatch_started"
            record["cancel_before_dispatch"] = True
            record["cancel_before_dispatch_attempt"] = queued_attempt
            if nested_key:
                payload[nested_key] = record
            db.execute(
                "UPDATE job_commands SET payload=? WHERE job_id=?",
                (_dump(payload), str(job_id)),
            )
            db.commit()
            return "cancel_requested"

    def quickmode_limits(self, workers: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
        names = sorted({str(item).strip().lower() for item in workers if str(item).strip()})
        if not names:
            return []
        requested_workers = ", ".join("(?)" for _ in names)
        with self._db() as db:
            rows = db.execute(
                f"""
                WITH requested(worker) AS (VALUES {requested_workers}),
                active AS (
                    SELECT slots.worker, COUNT(*) AS count
                    FROM job_quickmode_slots AS slots
                    JOIN requested ON requested.worker = slots.worker
                    GROUP BY slots.worker
                ),
                queued AS (
                    SELECT jobs.worker, COUNT(*) AS count
                    FROM jobs
                    JOIN requested ON requested.worker = jobs.worker
                    WHERE jobs.status = 'queued'
                      AND (jobs.payload LIKE '%\"quick_mode\":true%'
                           OR jobs.payload LIKE '%\"quick_mode\": true%')
                    GROUP BY jobs.worker
                )
                SELECT requested.worker,
                    COALESCE(limits.max_concurrent, 2) AS max_concurrent,
                    COALESCE(active.count, 0) AS active,
                    COALESCE(queued.count, 0) AS queued
                FROM requested
                LEFT JOIN quickmode_worker_limits AS limits
                    ON limits.worker = requested.worker
                LEFT JOIN active ON active.worker = requested.worker
                LEFT JOIN queued ON queued.worker = requested.worker
                ORDER BY requested.worker
                """,
                names,
            ).fetchall()
        return [
            {
                "worker": str(row["worker"]),
                "max_concurrent": int(row["max_concurrent"]),
                "active": int(row["active"]),
                "queued": int(row["queued"]),
            }
            for row in rows
        ]

    def set_quickmode_limit(self, worker: str, max_concurrent: int) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute(
                """
                INSERT INTO quickmode_worker_limits(worker, max_concurrent, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(worker) DO UPDATE SET
                    max_concurrent = excluded.max_concurrent,
                    updated_at = excluded.updated_at
                """,
                (str(worker).strip().lower(), int(max_concurrent), now),
            )
        return next(item for item in self.quickmode_limits([worker]))

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

    def create_tts_deliveries(
        self, job_id: str, worker: str, title: str, parts: list[dict[str, Any]]
    ) -> int:
        now = datetime.now(timezone.utc)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            for item in parts:
                part_index = int(item["part_index"])
                db.execute(
                    """
                    INSERT INTO job_tts_deliveries(
                        id, job_id, worker, title, artifact_ref, byte_size,
                        part_index, total_parts, status, attempts, available_at,
                        lease_until, uploaded_at, sender_profile, delivered_at, last_error_code, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, NULL, NULL, NULL, NULL, NULL, ?)
                    ON CONFLICT(job_id, part_index) DO UPDATE SET
                        worker = excluded.worker,
                        title = excluded.title,
                        artifact_ref = CASE WHEN job_tts_deliveries.status = 'delivered' OR (job_tts_deliveries.status IN ('claimed', 'reconciliation_required') AND job_tts_deliveries.uploaded_at IS NOT NULL AND job_tts_deliveries.sender_profile IS NOT NULL) THEN job_tts_deliveries.artifact_ref ELSE excluded.artifact_ref END,
                        byte_size = CASE WHEN job_tts_deliveries.status = 'delivered' OR (job_tts_deliveries.status IN ('claimed', 'reconciliation_required') AND job_tts_deliveries.uploaded_at IS NOT NULL AND job_tts_deliveries.sender_profile IS NOT NULL) THEN job_tts_deliveries.byte_size ELSE excluded.byte_size END,
                        total_parts = excluded.total_parts,
                        status = CASE WHEN job_tts_deliveries.status = 'delivered' THEN 'delivered' WHEN job_tts_deliveries.status = 'claimed' AND job_tts_deliveries.uploaded_at IS NOT NULL AND job_tts_deliveries.sender_profile IS NOT NULL THEN 'claimed' ELSE 'pending' END,
                        available_at = excluded.available_at,
                        lease_until = CASE WHEN job_tts_deliveries.status = 'claimed' AND job_tts_deliveries.uploaded_at IS NOT NULL AND job_tts_deliveries.sender_profile IS NOT NULL THEN job_tts_deliveries.lease_until ELSE NULL END,
                        uploaded_at = CASE WHEN job_tts_deliveries.status IN ('claimed', 'reconciliation_required') AND job_tts_deliveries.uploaded_at IS NOT NULL AND job_tts_deliveries.sender_profile IS NOT NULL THEN job_tts_deliveries.uploaded_at ELSE NULL END,
                        sender_profile = CASE WHEN job_tts_deliveries.status IN ('claimed', 'reconciliation_required') AND job_tts_deliveries.uploaded_at IS NOT NULL AND job_tts_deliveries.sender_profile IS NOT NULL THEN job_tts_deliveries.sender_profile ELSE NULL END,
                        last_error_code = CASE WHEN job_tts_deliveries.last_error_code = 'TELEGRAM_SEND_FAILED' AND job_tts_deliveries.uploaded_at IS NULL THEN job_tts_deliveries.last_error_code WHEN job_tts_deliveries.last_error_code = 'TDL_UPLOAD_IN_PROGRESS' AND job_tts_deliveries.uploaded_at IS NOT NULL AND job_tts_deliveries.sender_profile IS NOT NULL THEN job_tts_deliveries.last_error_code ELSE NULL END
                    """,
                    (
                        secrets.token_hex(16),
                        job_id,
                        str(worker),
                        str(title)[:200],
                        str(item["artifact_ref"]),
                        max(1, int(item["byte_size"])),
                        part_index,
                        int(item["total_parts"]),
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
            row = db.execute(
                "SELECT COUNT(*) FROM job_tts_deliveries WHERE job_id = ? AND status != 'cancelled'",
                (job_id,),
            ).fetchone()
        return int(row[0])

    def claim_tts_deliveries(
        self,
        limit: int = 10,
        lease_seconds: int = 180,
        *,
        worker: str | None = None,
        job_id: str | None = None,
        include_artifact_ref: bool = False,
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        lease_until = (now + timedelta(seconds=max(30, int(lease_seconds)))).isoformat()
        claimed: list[dict[str, Any]] = []
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            filters = [
                "j.status IN ('dispatched', 'running')",
                "d.status IN ('pending', 'claimed')",
                "d.available_at <= ?",
                "(d.lease_until IS NULL OR d.lease_until <= ?)",
            ]
            params: list[Any] = [now.isoformat(), now.isoformat()]
            if worker is not None:
                filters.append("d.worker = ?")
                params.append(str(worker))
            if job_id is not None:
                filters.append("d.job_id = ?")
                params.append(str(job_id))
            columns = "d.id, d.status, d.attempts, d.uploaded_at, d.sender_profile, d.last_error_code"
            if include_artifact_ref:
                columns += ", d.artifact_ref"
            rows = db.execute(
                f"""
                SELECT {columns} FROM job_tts_deliveries d
                JOIN jobs j ON j.id = d.job_id
                  WHERE {' AND '.join(filters)}
                    AND NOT EXISTS (
                        SELECT 1 FROM job_tts_deliveries earlier
                        WHERE earlier.job_id = d.job_id
                          AND earlier.part_index < d.part_index
                          AND earlier.status != 'delivered'
                          AND NOT (
                              earlier.status = 'claimed'
                              AND earlier.uploaded_at IS NOT NULL
                              AND earlier.sender_profile IS NOT NULL
                          )
                    )
                ORDER BY d.created_at, d.part_index LIMIT ?
                """,
                (*params, max(1, min(int(limit), 100))),
            ).fetchall()
            for item in rows:
                delivery_id = str(item["id"])
                was_verification_pending = (
                    str(item["status"]) == "claimed"
                    and item["uploaded_at"] is not None
                    and bool(item["sender_profile"])
                    and str(item["last_error_code"] or "") != "TDL_UPLOAD_IN_PROGRESS"
                )
                was_reconciliation_pending = (
                    str(item["status"]) in {"pending", "claimed"}
                    and item["uploaded_at"] is not None
                    and bool(item["sender_profile"])
                    and (
                        str(item["status"]) == "pending"
                        or str(item["last_error_code"] or "") == "TDL_UPLOAD_IN_PROGRESS"
                    )
                )
                first_attempt = int(item["attempts"] or 0) == 0
                safe_retry = (
                    str(item["last_error_code"] or "") == "TELEGRAM_SEND_FAILED"
                    and item["uploaded_at"] is None
                    and not item["sender_profile"]
                )
                upload_in_progress = (
                    str(item["last_error_code"] or "") == "TDL_UPLOAD_IN_PROGRESS"
                    and item["uploaded_at"] is not None
                    and bool(item["sender_profile"])
                )
                db.execute(
                    "UPDATE job_tts_deliveries SET status = 'claimed', lease_until = ?, attempts = attempts + 1 WHERE id = ?",
                    (lease_until, delivery_id),
                )
                fields = "id, job_id, title, part_index, total_parts, byte_size, attempts, created_at, uploaded_at, sender_profile"
                if include_artifact_ref:
                    fields += ", artifact_ref"
                row = db.execute(
                    f"SELECT {fields} FROM job_tts_deliveries WHERE id = ?",
                    (delivery_id,),
                ).fetchone()
                if row is not None:
                    claimed_item = dict(row)
                    claimed_item["verification_pending"] = was_verification_pending
                    claimed_item["reconciliation_pending"] = was_reconciliation_pending
                    claimed_item["first_attempt"] = first_attempt
                    claimed_item["safe_retry"] = safe_retry
                    claimed_item["upload_in_progress"] = upload_in_progress
                    claimed.append(claimed_item)
        return claimed

    def get_tts_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM job_tts_deliveries WHERE id = ?", (str(delivery_id),)
            ).fetchone()
        return dict(row) if row is not None else None

    def complete_tts_delivery(
        self,
        delivery_id: str,
        *,
        delivered: bool,
        reconciliation_required: bool = False,
        verification_pending: bool = False,
        upload_in_progress: bool = False,
        uploaded_at: float | None = None,
        sender_profile: str | None = None,
    ) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        with self._db() as db:
            row = db.execute(
                "SELECT attempts, status FROM job_tts_deliveries WHERE id = ?", (str(delivery_id),)
            ).fetchone()
            if row is None:
                return None
            if str(row["status"]) != "claimed":
                pass
            elif delivered:
                db.execute(
                    "UPDATE job_tts_deliveries SET status = 'delivered', lease_until = NULL, delivered_at = ?, last_error_code = NULL WHERE id = ?",
                    (now.isoformat(), str(delivery_id)),
                )
            elif verification_pending and uploaded_at is not None and sender_profile:
                db.execute(
                    "UPDATE job_tts_deliveries SET status = 'claimed', lease_until = ?, uploaded_at = ?, sender_profile = ?, last_error_code = ? WHERE id = ?",
                    (
                        (now + timedelta(seconds=180)).isoformat(),
                        float(uploaded_at),
                        str(sender_profile).strip().lower(),
                        "TDL_UPLOAD_IN_PROGRESS" if upload_in_progress else None,
                        str(delivery_id),
                    ),
                )
            elif reconciliation_required:
                delay = min(300, 2 ** min(int(row["attempts"]), 8))
                db.execute(
                    "UPDATE job_tts_deliveries SET status = 'reconciliation_required', lease_until = NULL, available_at = ?, uploaded_at = COALESCE(?, uploaded_at), sender_profile = COALESCE(?, sender_profile), last_error_code = ? WHERE id = ?",
                    (
                        (now + timedelta(seconds=delay)).isoformat(),
                        float(uploaded_at) if uploaded_at is not None else None,
                        str(sender_profile).strip().lower() if sender_profile else None,
                        "TDL_UPLOAD_IN_PROGRESS" if upload_in_progress else "TTS_DELIVERY_RECONCILIATION_FAILED",
                        str(delivery_id),
                    ),
                )
            else:
                delay = min(300, 2 ** min(int(row["attempts"]), 8))
                db.execute(
                    "UPDATE job_tts_deliveries SET status = 'pending', lease_until = NULL, available_at = ?, uploaded_at = NULL, sender_profile = NULL, last_error_code = 'TELEGRAM_SEND_FAILED' WHERE id = ?",
                    ((now + timedelta(seconds=delay)).isoformat(), str(delivery_id)),
                )
        return self.get_tts_delivery(delivery_id)

    def tts_delivery_summary(self, job_id: str) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute(
                "SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered, SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled, SUM(CASE WHEN status = 'claimed' AND uploaded_at IS NOT NULL AND sender_profile IS NOT NULL THEN 1 ELSE 0 END) AS verification_pending, SUM(CASE WHEN status NOT IN ('delivered', 'cancelled') AND uploaded_at IS NOT NULL AND sender_profile IS NOT NULL THEN 1 ELSE 0 END) AS unverified_uploaded FROM job_tts_deliveries WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
        return {
            "total_parts": int(row["total"] or 0),
            "delivered_parts": int(row["delivered"] or 0),
            "cancelled_parts": int(row["cancelled"] or 0),
            "verification_pending_parts": int(row["verification_pending"] or 0),
            "unverified_uploaded_parts": int(row["unverified_uploaded"] or 0),
        }

    def cancel_tts_deliveries(self, job_id: str) -> None:
        with self._db() as db:
            db.execute(
                """
                UPDATE job_tts_deliveries
                SET status = 'cancelled', lease_until = NULL
                WHERE job_id = ?
                  AND status NOT IN ('delivered', 'reconciliation_required')
                  AND NOT (uploaded_at IS NOT NULL AND sender_profile IS NOT NULL)
                """,
                (str(job_id),),
            )

    def reset_tts_deliveries(self, job_id: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM job_tts_deliveries WHERE job_id = ?", (str(job_id),))

    def set_tts_telegram_ready(self, ready: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute(
                "INSERT INTO tts_service_health(service, ready, updated_at) VALUES('telegram', ?, ?) ON CONFLICT(service) DO UPDATE SET ready = excluded.ready, updated_at = excluded.updated_at",
                (1 if ready else 0, now),
            )

    def tts_telegram_ready(self, max_age_seconds: int = 90) -> bool:
        with self._db() as db:
            row = db.execute(
                "SELECT ready, updated_at FROM tts_service_health WHERE service = 'telegram'"
            ).fetchone()
        if row is None or not bool(row["ready"]):
            return False
        try:
            updated = datetime.fromisoformat(str(row["updated_at"]))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        return (datetime.now(timezone.utc) - updated).total_seconds() <= max_age_seconds

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
                """
                SELECT p.*, j.worker, j.profile, j.status, j.payload,
                    c.payload AS command_payload
                FROM job_execution_plans p JOIN jobs j ON j.id = p.job_id
                LEFT JOIN job_commands c ON c.job_id = j.id
                WHERE p.job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if plan_row is None:
                return {"admitted": True, "position": 1, "blocked_reason": None}
            if str(plan_row["status"]) != JobStatus.QUEUED.value:
                return {"admitted": False, "position": 1, "blocked_reason": None}
            stored_command = _load(plan_row["command_payload"], None)
            is_durable_dispatch = (
                isinstance(stored_command, dict)
                and stored_command.get("dispatch_mode") == "durable"
            )
            if (
                plan_row["admitted_at"]
                and not plan_row["released_at"]
                and not is_durable_dispatch
            ):
                return {
                    "admitted": False,
                    "position": 1,
                    "blocked_reason": None,
                }
            is_quick_mode = _quick_mode_sql(True)[0] and bool(
                db.execute(
                    "SELECT 1 FROM jobs WHERE id = ? AND " + _quick_mode_sql(True)[0],
                    (job_id,),
                ).fetchone()
            )
            worker_name = str(plan_row["worker"])
            if is_quick_mode:
                # Order with scheduler timestamps because queue_info updates
                # jobs.updated_at. Preserve worker queue positions, but enforce
                # FIFO only among jobs from one profile. A job blocked on that
                # profile's TDL lease must not waste a slot another profile can use.
                earlier = db.execute(
                    """
                    SELECT p.job_id, j.profile
                    FROM job_execution_plans p
                    JOIN jobs j ON j.id = p.job_id
                    WHERE j.worker = ? AND j.status = 'queued'
                      AND j.id != ? AND p.queued_at <= ?
                      AND (j.payload LIKE '%\"quick_mode\":true%'
                           OR j.payload LIKE '%\"quick_mode\": true%')
                    ORDER BY p.queued_at, p.priority, p.job_id
                    """,
                    (worker_name, job_id, str(plan_row["queued_at"] or now)),
                ).fetchall()
                same_profile_earlier = any(
                    str(item["profile"]) == str(plan_row["profile"])
                    for item in earlier
                )
                active_slots = int(
                    db.execute(
                        "SELECT COUNT(*) FROM job_quickmode_slots WHERE worker = ?",
                        (worker_name,),
                    ).fetchone()[0]
                )
                position = active_slots + len(earlier) + 1
                if same_profile_earlier:
                    reason = "Menunggu giliran FIFO profile Quick Mode"
                    db.execute(
                        "UPDATE job_execution_plans SET blocked_reason = ? WHERE job_id = ?",
                        (reason, job_id),
                    )
                    return {"admitted": False, "position": position, "blocked_reason": reason}
                limit_row = db.execute(
                    "SELECT max_concurrent FROM quickmode_worker_limits WHERE worker = ?",
                    (worker_name,),
                ).fetchone()
                max_concurrent = int(limit_row["max_concurrent"]) if limit_row else 2
                slot = db.execute(
                    "SELECT 1 FROM job_quickmode_slots WHERE job_id = ?", (job_id,)
                ).fetchone()
                if slot is None and active_slots >= max_concurrent:
                    reason = f"Batas Quick Mode worker tercapai ({active_slots}/{max_concurrent})"
                    db.execute(
                        "UPDATE job_execution_plans SET blocked_reason = ? WHERE job_id = ?",
                        (reason, job_id),
                    )
                    return {"admitted": False, "position": position, "blocked_reason": reason}
            keys = set(_load(plan_row["concurrency_keys"], []))
            if not keys:
                if is_quick_mode:
                    db.execute(
                        "INSERT OR IGNORE INTO job_quickmode_slots(job_id, worker, acquired_at) VALUES(?, ?, ?)",
                        (job_id, worker_name, now),
                    )
                db.execute(
                    "UPDATE job_execution_plans SET admitted_at = ?, released_at = NULL, blocked_reason = NULL WHERE job_id = ?",
                    (now, job_id),
                )
                return {"admitted": True, "position": 1, "blocked_reason": None}
            active_leases = db.execute(
                "SELECT resource_key, job_id FROM job_resource_leases "
                "WHERE job_id != ? ORDER BY acquired_at, job_id, resource_key",
                (job_id,),
            ).fetchall()
            active_conflict: tuple[str, str] | None = None
            for lease in active_leases:
                active_conflict = first_resource_conflict(
                    keys, {str(lease["resource_key"])}
                )
                if active_conflict is not None:
                    break

            queued_rows = db.execute(
                """
                SELECT p.job_id, p.concurrency_keys
                FROM job_execution_plans p
                JOIN jobs j ON j.id = p.job_id
                WHERE j.status = 'queued' AND j.archived_at IS NULL
                  AND j.worker = ?
                ORDER BY COALESCE(p.queued_at, j.created_at), p.priority, p.job_id
                """,
                (worker_name,),
            ).fetchall()
            position = 1
            earlier_conflict: tuple[str, str] | None = None
            for queued in queued_rows:
                queued_job_id = str(queued["job_id"])
                if queued_job_id == job_id:
                    break
                queued_keys = set(_load(queued["concurrency_keys"], []))
                queue_conflict = first_resource_conflict(keys, queued_keys)
                if queue_conflict is not None:
                    position += 1
                    if earlier_conflict is None:
                        earlier_conflict = queue_conflict

            if active_conflict is not None or earlier_conflict is not None:
                blocker = active_conflict or earlier_conflict
                assert blocker is not None
                reason = f"Menunggu {blocker[1]}"
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
                    "INSERT OR IGNORE INTO job_resource_leases(resource_key, job_id, acquired_at, worker) VALUES(?, ?, ?, ?)",
                    (key, job_id, now, str(worker["worker"] if worker else "")),
                )
            if is_quick_mode:
                db.execute(
                    "INSERT OR IGNORE INTO job_quickmode_slots(job_id, worker, acquired_at) VALUES(?, ?, ?)",
                    (job_id, worker_name, now),
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
            db.execute("DELETE FROM job_quickmode_slots WHERE job_id = ?", (job_id,))
            db.execute(
                "UPDATE job_execution_plans SET released_at = ? WHERE job_id = ?",
                (now, job_id),
            )
            row = db.execute(
                """
                SELECT j.progress, p.queued_at, p.admitted_at
                FROM jobs j LEFT JOIN job_execution_plans p ON p.job_id = j.id
                WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
            if row is not None:
                progress = _load(row["progress"], {})
                timing = progress.get("timing")
                timing = dict(timing) if isinstance(timing, dict) else {}
                queued_at = str(row["queued_at"] or "")
                admitted_at = str(row["admitted_at"] or "")
                timing.update({"released_at": now})
                if queued_at:
                    timing["queued_at"] = queued_at
                if admitted_at:
                    timing["admitted_at"] = admitted_at
                    timing["worker_seconds"] = round(
                        _elapsed_between(admitted_at, now), 3
                    )
                progress["timing"] = timing
                db.execute(
                    "UPDATE jobs SET progress = ? WHERE id = ?",
                    (_dump(progress), job_id),
                )

    def replace_execution_resources(
        self, job_id: str, resource_keys: set[str] | list[str] | tuple[str, ...]
    ) -> bool:
        """Atomically replace an active job's lease set.

        Quick Mode uses this at ``json_ready`` to release the export lane and
        retain only its staging lock.  If the next phase conflicts with an
        existing lease, nothing is changed and the caller can keep the old
        reservation rather than running without a scheduler guard.
        """
        desired = {str(item) for item in resource_keys if str(item)}
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT worker FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            plan = db.execute(
                "SELECT concurrency_keys FROM job_execution_plans WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None or plan is None:
                return False
            active_leases = db.execute(
                "SELECT resource_key FROM job_resource_leases WHERE job_id != ?",
                (job_id,),
            ).fetchall()
            if any(
                first_resource_conflict(
                    desired, {str(lease["resource_key"])}
                )
                is not None
                for lease in active_leases
            ):
                return False
            db.execute("DELETE FROM job_resource_leases WHERE job_id = ?", (job_id,))
            for key in sorted(desired):
                db.execute(
                    "INSERT INTO job_resource_leases(resource_key, job_id, acquired_at, worker) VALUES(?, ?, ?, ?)",
                    (key, job_id, datetime.now(timezone.utc).isoformat(), str(row["worker"])),
                )
            db.execute(
                "UPDATE job_execution_plans SET concurrency_keys = ?, released_at = NULL, blocked_reason = NULL WHERE job_id = ?",
                (_dump(sorted(desired)), job_id),
            )
            return True

    def set_queue_info(self, job_id: str, position: int, reason: str | None) -> None:
        with self._db() as db:
            row = db.execute(
                """
                SELECT j.progress, j.created_at, p.queued_at, p.admitted_at,
                    p.released_at
                FROM jobs j LEFT JOIN job_execution_plans p ON p.job_id = j.id
                WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                return
            progress = _load(row["progress"], {})
            timing = progress.get("timing")
            timing = dict(timing) if isinstance(timing, dict) else {}
            queued_at = str(row["queued_at"] or row["created_at"] or "")
            admitted_at = str(row["admitted_at"] or "")
            now = datetime.now(timezone.utc)
            timing["queued_at"] = queued_at or None
            timing["queue_wait_seconds"] = round(
                _elapsed_between(queued_at, admitted_at or now.isoformat()), 3
            )
            if admitted_at:
                timing["admitted_at"] = admitted_at
            if row["released_at"]:
                timing["released_at"] = str(row["released_at"])
            progress["timing"] = timing
            progress["position"] = max(1, int(position))
            if reason:
                progress["blocked_reason"] = reason
            else:
                progress.pop("blocked_reason", None)
            db.execute(
                "UPDATE jobs SET progress = ?, updated_at = ? WHERE id = ?",
                (_dump(progress), datetime.now(timezone.utc).isoformat(), job_id),
            )

    def monitor_metrics(
        self,
        *,
        profile: str | None = None,
        worker: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Aggregate queue, phase, and worker event metrics for the monitor."""
        current_time = now or datetime.now(timezone.utc)
        window_start = (current_time - timedelta(hours=24)).isoformat()
        active_states = ("queued", "dispatched", "running", "paused")
        clauses = [
            "((j.status IN (?, ?, ?, ?)) OR "
            "(COALESCE(p.admitted_at, j.created_at) >= ? AND j.archived_at IS NULL))"
        ]
        values: list[object] = [*active_states, window_start]
        if profile:
            clauses.append("j.profile = ?")
            values.append(str(profile))
        if worker:
            clauses.append("j.worker = ?")
            values.append(str(worker))
        with self._db() as db:
            rows = db.execute(
                """
                SELECT j.worker, j.status, j.kind, j.payload, j.progress,
                    j.created_at, j.updated_at, p.queued_at, p.admitted_at
                FROM jobs j LEFT JOIN job_execution_plans p ON p.job_id = j.id
                WHERE """ + " AND ".join(clauses),
                values,
            ).fetchall()

        workers: dict[str, dict[str, Any]] = {}
        queue_wait_samples: list[float] = []
        latency_total = 0.0
        latency_count = 0
        phase_totals: dict[str, float] = {}
        for row in rows:
            name = str(row["worker"] or "")
            if not name:
                continue
            metrics = workers.setdefault(
                name,
                {
                    "worker": name,
                    "queued_jobs": 0,
                    "dispatched_jobs": 0,
                    "running_jobs": 0,
                    "paused_jobs": 0,
                    "quickmode_queued": 0,
                    "quickmode_active": 0,
                    "quickmode_paused": 0,
                    "average_queue_wait_seconds": None,
                    "event_latency": {"count": 0, "average_ms": None},
                    "phase_seconds": {},
                    "last_seen_at": None,
                },
            )
            status = str(row["status"])
            if status in active_states:
                metrics[f"{status}_jobs"] += 1
            payload = _load(row["payload"], {})
            progress = _load(row["progress"], {})
            if not isinstance(progress, dict):
                progress = {}
            quick_mode = bool(payload.get("quick_mode")) if isinstance(payload, dict) else False
            active = status in {"dispatched", "running"}
            if quick_mode and status == "queued":
                metrics["quickmode_queued"] += 1
            elif quick_mode and active:
                metrics["quickmode_active"] += 1
            elif quick_mode and status == "paused":
                metrics["quickmode_paused"] += 1

            queued_at = str(row["queued_at"] or row["created_at"] or "")
            admitted_at = str(row["admitted_at"] or "")
            if admitted_at and queued_at and admitted_at >= window_start:
                wait = _elapsed_between(queued_at, admitted_at)
                queue_wait_samples.append(wait)
                metrics.setdefault("_queue_wait_samples", []).append(wait)

            observability = progress.get("observability") if isinstance(progress, dict) else {}
            observability = observability if isinstance(observability, dict) else {}
            last_seen = str(
                observability.get("last_event_at")
                or progress.get("worker_heartbeat_at")
                or progress.get("worker_output_at")
                or (row["updated_at"] if active else "")
            )
            if last_seen and (
                not metrics["last_seen_at"] or last_seen > metrics["last_seen_at"]
            ):
                metrics["last_seen_at"] = last_seen

            latency = observability.get("event_latency")
            if isinstance(latency, dict):
                count = int(latency.get("count") or 0)
                total = float(latency.get("total_ms") or 0.0)
                metrics["event_latency"]["count"] += count
                metrics["event_latency"]["_total_ms"] = (
                    float(metrics["event_latency"].get("_total_ms") or 0.0) + total
                )
                latency_count += count
                latency_total += total

            durations = observability.get("phase_durations_seconds")
            if isinstance(durations, dict):
                for phase, seconds in durations.items():
                    if isinstance(seconds, (int, float)) and seconds >= 0:
                        metrics["phase_seconds"][str(phase)] = (
                            float(metrics["phase_seconds"].get(str(phase), 0.0))
                            + float(seconds)
                        )
                        phase_totals[str(phase)] = phase_totals.get(str(phase), 0.0) + float(seconds)
            current_phase = str(observability.get("phase") or "")
            current_seconds = observability.get("phase_elapsed_seconds")
            if (
                current_phase
                and not JobStatus(status).terminal
                and isinstance(current_seconds, (int, float))
                and current_seconds > 0
            ):
                metrics["phase_seconds"][current_phase] = (
                    float(metrics["phase_seconds"].get(current_phase, 0.0))
                    + float(current_seconds)
                )
                phase_totals[current_phase] = phase_totals.get(current_phase, 0.0) + float(current_seconds)

        for metrics in workers.values():
            samples = metrics.pop("_queue_wait_samples", [])
            if samples:
                metrics["average_queue_wait_seconds"] = round(sum(samples) / len(samples), 3)
            latency = metrics["event_latency"]
            total = float(latency.pop("_total_ms", 0.0))
            latency["average_ms"] = round(total / latency["count"], 3) if latency["count"] else None
            metrics["phase_seconds"] = {
                phase: round(seconds, 3)
                for phase, seconds in metrics["phase_seconds"].items()
            }

        return {
            "measured_at": current_time.isoformat(),
            "window_hours": 24,
            "queued_jobs": sum(item["queued_jobs"] for item in workers.values()),
            "dispatched_jobs": sum(item["dispatched_jobs"] for item in workers.values()),
            "running_jobs": sum(item["running_jobs"] for item in workers.values()),
            "paused_jobs": sum(item["paused_jobs"] for item in workers.values()),
            "average_queue_wait_seconds": round(
                sum(queue_wait_samples) / len(queue_wait_samples), 3
            ) if queue_wait_samples else None,
            "event_latency": {
                "count": latency_count,
                "average_ms": round(latency_total / latency_count, 3)
                if latency_count
                else None,
            },
            "phase_seconds": {
                phase: round(seconds, 3) for phase, seconds in phase_totals.items()
            },
            "workers": [workers[name] for name in sorted(workers)],
        }

    def list(
        self,
        *,
        actor_user_id: int | None = None,
        profile: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        statuses: tuple[str, ...] | None = None,
        worker: str | None = None,
        quick_mode: bool | None = None,
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
        _append_status_filter(clauses, values, status=status, statuses=statuses)
        if worker:
            clauses.append("worker = ?")
            values.append(worker)
        quick_clause, quick_values = _quick_mode_sql(quick_mode)
        if quick_clause:
            clauses.append(quick_clause)
            values.extend(quick_values)
        if archived is True:
            clauses.append("archived_at IS NOT NULL")
        elif archived is False:
            clauses.append("archived_at IS NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(max(1, min(int(limit), 200)))
        values.append(max(0, int(offset)))
        with self._db() as db:
            rows = db.execute(
                f"SELECT * FROM jobs{where} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
                values,
            ).fetchall()
        return [job for row in rows if (job := self._job(row)) is not None]

    def list_queued_for_scheduler(
        self, *, profile: str | None = None, limit: int = 1000
    ) -> list[Job]:
        """Return oldest queued commands using scheduler timestamps."""
        clauses = ["j.status = 'queued'", "j.archived_at IS NULL"]
        values: list[object] = []
        if profile is not None:
            clauses.append("j.profile = ?")
            values.append(str(profile))
        values.append(max(1, min(int(limit), 5000)))
        with self._db() as db:
            rows = db.execute(
                "SELECT j.* FROM jobs j "
                "LEFT JOIN job_execution_plans p ON p.job_id = j.id "
                "WHERE " + " AND ".join(clauses) +
                " ORDER BY COALESCE(p.queued_at, j.created_at), p.priority, j.id LIMIT ?",
                values,
            ).fetchall()
        return [job for row in rows if (job := self._job(row)) is not None]

    def count(
        self,
        *,
        profile: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        statuses: tuple[str, ...] | None = None,
        worker: str | None = None,
        quick_mode: bool | None = None,
        archived: bool | None = None,
    ) -> int:
        clauses, values = [], []
        for column, value in (("profile", profile), ("kind", kind)):
            if value:
                clauses.append(f"{column} = ?")
                values.append(value)
        _append_status_filter(clauses, values, status=status, statuses=statuses)
        if worker:
            clauses.append("worker = ?")
            values.append(worker)
        quick_clause, quick_values = _quick_mode_sql(quick_mode)
        if quick_clause:
            clauses.append(quick_clause)
            values.extend(quick_values)
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
            # Worker phase telemetry is intentionally sparse.  Merge it with
            # the previous snapshot so start/end timestamps and transfer
            # context survive a terminal event or a later progress update.
            progress = {**job.progress, **(event.progress or {})}
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
            if event.status == JobStatus.PAUSED:
                # A paused Quick Mode job still owns its physical resource
                # leases, but no longer consumes a scheduler concurrency slot.
                db.execute(
                    "DELETE FROM job_quickmode_slots WHERE job_id = ?",
                    (event.job_id,),
                )
            elif event.status.terminal:
                db.execute(
                    "DELETE FROM job_quickmode_slots WHERE job_id = ?",
                    (event.job_id,),
                )
            elif job.status == JobStatus.PAUSED and event.status == JobStatus.QUEUED:
                # Resume order is operator click order, independent of the
                # original job creation time.
                queued_at = event.created_at
                queued_at_row = db.execute(
                    """
                    SELECT MAX(p.queued_at) AS queued_at
                    FROM job_execution_plans p JOIN jobs j ON j.id = p.job_id
                    WHERE j.worker = ? AND j.status = 'queued' AND j.id != ?
                      AND (j.payload LIKE '%\"quick_mode\":true%'
                           OR j.payload LIKE '%\"quick_mode\": true%')
                    """,
                    (job.worker, event.job_id),
                ).fetchone()
                latest_queued_at = queued_at_row["queued_at"] if queued_at_row else None
                if latest_queued_at:
                    try:
                        latest = datetime.fromisoformat(str(latest_queued_at))
                        if latest >= queued_at:
                            queued_at = latest + timedelta(microseconds=1)
                    except ValueError:
                        pass
                db.execute(
                    "UPDATE job_execution_plans SET queued_at = ?, admitted_at = NULL, blocked_reason = NULL WHERE job_id = ?",
                    (queued_at.isoformat(), event.job_id),
                )
            return (
                replace(
                    job,
                    status=event.status,
                    progress=progress,
                    result=result,
                    error=error,
                    updated_at=event.created_at,
                    progress_sequence=max(job.progress_sequence, event.sequence),
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
                    _dump({**job.progress, **(event.progress or {})}),
                    event.sequence,
                    event.created_at.isoformat(),
                    event.job_id,
                ),
            )
            return (
                replace(
                    job,
                    status=event.status,
                    progress={**job.progress, **(event.progress or {})},
                    updated_at=event.created_at,
                    progress_sequence=event.sequence,
                ),
                True,
            )

    def update_result(self, job_id: str, result: dict[str, Any]) -> Job:
        """Update a terminal job's result without changing its lifecycle state."""
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute(
                "UPDATE jobs SET result=?,updated_at=? WHERE id=?",
                (_dump(result), now, str(job_id)),
            )
            row = db.execute("SELECT * FROM jobs WHERE id=?", (str(job_id),)).fetchone()
        job = self._job(row)
        if job is None:
            raise KeyError(f"Unknown job: {job_id}")
        return job

    def complete_storage_upload_reconciliation(
        self,
        job_id: str,
        result: dict[str, Any],
        *,
        progress: dict[str, Any],
    ) -> Job:
        """Atomically resolve a failed Storage upload after every item is verified."""
        value = result.get("value", result) if isinstance(result, dict) else None
        items = value.get("items") if isinstance(value, dict) else None
        if (
            not isinstance(items, list)
            or not items
            or any(
                not isinstance(item, dict)
                or item.get("status") not in {"succeeded", "skipped"}
                for item in items
            )
        ):
            raise ValueError("Storage upload reconciliation is not complete.")

        job_key = str(job_id)
        now = datetime.now(timezone.utc)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_key,)).fetchone()
            job = self._job(row)
            if job is None:
                raise KeyError(f"Unknown job: {job_key}")
            if job.kind != "storage_upload" or job.status != JobStatus.FAILED:
                raise ValueError("Only a failed Storage upload can be reconciled as succeeded.")
            sequence = int(job.progress_sequence) + 1
            event = JobEvent(
                job_id=job_key,
                sequence=sequence,
                status=JobStatus.SUCCEEDED,
                event_type="storage.reconciliation_applied",
                progress={"phase": "succeeded", **dict(progress or {})},
                result=result,
                error=None,
                created_at=now,
            )
            merged_progress = {**job.progress, **event.progress}
            db.execute(
                """INSERT INTO job_events(
                    job_id, sequence, status, event_type, progress, result, error, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, NULL, ?)""",
                (
                    job_key,
                    sequence,
                    JobStatus.SUCCEEDED.value,
                    event.event_type,
                    _dump(event.progress),
                    _dump(result),
                    now.isoformat(),
                ),
            )
            db.execute(
                """UPDATE jobs SET status = ?, progress = ?, result = ?, error = NULL,
                    progress_sequence = ?, updated_at = ? WHERE id = ?""",
                (
                    JobStatus.SUCCEEDED.value,
                    _dump(merged_progress),
                    _dump(result),
                    sequence,
                    now.isoformat(),
                    job_key,
                ),
            )
            db.execute("DELETE FROM job_quickmode_slots WHERE job_id = ?", (job_key,))
            updated = self._job(
                db.execute("SELECT * FROM jobs WHERE id = ?", (job_key,)).fetchone()
            )
        if updated is None:
            raise KeyError(f"Unknown job: {job_key}")
        return updated

    def record_late_worker_event(
        self, job_id: str, event: dict[str, Any]
    ) -> tuple[Job, bool]:
        """Persist worker evidence received after backend stall failure.

        Store a bounded job summary without reopening it. Storage Sync batches
        also have durable rows because a long scan can exceed the summary cap.
        """
        job_key = str(job_id)
        event_record = dict(event)
        try:
            sequence = int(event_record.get("sequence"))
        except (TypeError, ValueError):
            raise ValueError("Late worker event requires a valid sequence.")
        event_type = str(event_record.get("event_type") or "").strip()
        if sequence < 1 or not event_type:
            raise ValueError("Late worker event requires sequence and event type.")

        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_key,)).fetchone()
            job = self._job(row)
            if job is None:
                raise KeyError(f"Unknown job: {job_key}")
            result = dict(job.result) if isinstance(job.result, dict) else {}
            existing_job_event = db.execute(
                "SELECT status, event_type, result, error FROM job_events "
                "WHERE job_id = ? AND sequence = ?",
                (job_key, sequence),
            ).fetchone()
            if existing_job_event is not None:
                stored_event_type = str(existing_job_event["event_type"])
                if stored_event_type == event_type:
                    matches = (
                        str(existing_job_event["status"]) == str(event_record.get("status"))
                        and _load(existing_job_event["result"], None) == event_record.get("result")
                        and _load(existing_job_event["error"], None) == event_record.get("error")
                    )
                    return job, matches
            durable_sync_batch = event_type == "storage.sync_batch"
            existing_row = (
                db.execute(
                    "SELECT event_json FROM late_worker_events "
                    "WHERE job_id = ? AND sequence = ? AND event_type = ?",
                    (job_key, sequence, event_type),
                ).fetchone()
                if durable_sync_batch
                else None
            )
            if existing_row is not None:
                existing = _load(existing_row["event_json"], {})
                existing = existing if isinstance(existing, dict) else {}
                comparable_keys = ("sequence", "event_type", "status", "result", "error")
                matches = all(
                    existing.get(key) == event_record.get(key)
                    for key in comparable_keys
                )
                return job, matches

            records = result.get("late_worker_events")
            records = list(records) if isinstance(records, list) else []
            if not durable_sync_batch:
                existing = next(
                    (
                        item
                        for item in records
                        if isinstance(item, dict)
                        and item.get("sequence") == sequence
                        and item.get("event_type") == event_type
                    ),
                    None,
                )
                if existing is not None:
                    comparable_keys = (
                        "sequence", "event_type", "status", "result", "error"
                    )
                    return job, all(
                        existing.get(key) == event_record.get(key)
                        for key in comparable_keys
                    )

            event_record.setdefault(
                "received_at", datetime.now(timezone.utc).isoformat()
            )
            if durable_sync_batch:
                db.execute(
                    "INSERT INTO late_worker_events(job_id, sequence, event_type, event_json, received_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        job_key,
                        sequence,
                        event_type,
                        _dump(event_record),
                        str(event_record["received_at"]),
                    ),
                )
            records.append(event_record)
            result["late_worker_events"] = records[-256:]
            if str(event_record.get("status") or "") in {
                JobStatus.SUCCEEDED.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
            }:
                result["late_worker_terminal"] = event_record
            db.execute(
                "UPDATE jobs SET result = ?, updated_at = ? WHERE id = ?",
                (_dump(result), str(event_record["received_at"]), job_key),
            )
            updated_row = db.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_key,)
            ).fetchone()
            updated = self._job(updated_row)
            if updated is None:
                raise KeyError(f"Unknown job: {job_key}")
            return updated, True

    def late_worker_events(
        self, job_id: str, *, event_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Read durable late Storage Sync batches for reconciliation."""
        clauses = ["job_id = ?"]
        values: list[object] = [str(job_id)]
        if event_type:
            clauses.append("event_type = ?")
            values.append(str(event_type))
        with self._db() as db:
            rows = db.execute(
                "SELECT event_json FROM late_worker_events WHERE "
                + " AND ".join(clauses)
                + " ORDER BY sequence, event_type",
                values,
            ).fetchall()
        return [
            value
            for row in rows
            if isinstance((value := _load(row["event_json"], {})), dict)
        ]

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
            JobStatus.PAUSED.value,
        )
        with self._db() as db:
            row = db.execute(
                "SELECT 1 FROM jobs WHERE profile = ? AND status IN (?, ?, ?, ?) LIMIT 1",
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
            settings_version=int(row["settings_version"] or 0),
            progress_sequence=int(row["progress_sequence"] or 0),
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
