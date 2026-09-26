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
                    queued_at TEXT,
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

    def reset_for_retry(self, job_id: str, payload: dict[str, Any]) -> Job:
        """Reset a terminal row for a new attempt without changing its ID.

        The old lifecycle remains in ``job_events``. A monotonically
        increasing event sequence lets the worker publish the new attempt
        without colliding with the previous attempt's telemetry.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown job: {job_id}")
            if not JobStatus(str(row["status"])).terminal:
                raise ValueError("Hanya job terminal yang dapat diulang.")
            max_sequence = int(
                db.execute(
                    "SELECT COALESCE(MAX(sequence), 0) FROM job_events WHERE job_id = ?",
                    (job_id,),
                ).fetchone()[0]
            )
            db.execute(
                """
                UPDATE jobs
                SET status = 'queued', payload = ?, progress = ?, result = NULL,
                    error = NULL, progress_sequence = ?, archived_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    _dump(payload),
                    _dump({"phase": "queued", "retry_sequence": max_sequence + 1}),
                    max_sequence,
                    now,
                    job_id,
                ),
            )
            db.execute(
                "DELETE FROM job_resource_leases WHERE job_id = ?", (job_id,)
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

    def quickmode_limits(self, workers: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
        names = sorted({str(item).strip().lower() for item in workers if str(item).strip()})
        with self._db() as db:
            limits = {
                str(row["worker"]): int(row["max_concurrent"])
                for row in db.execute(
                    "SELECT worker, max_concurrent FROM quickmode_worker_limits"
                ).fetchall()
            }
            active = {
                str(row["worker"]): int(row["count"])
                for row in db.execute(
                    "SELECT worker, COUNT(*) AS count FROM job_quickmode_slots GROUP BY worker"
                ).fetchall()
            }
            queued = {
                str(row["worker"]): int(row["count"])
                for row in db.execute(
                    """
                    SELECT worker, COUNT(*) AS count FROM jobs
                    WHERE status = 'queued'
                      AND (payload LIKE '%\"quick_mode\":true%' OR payload LIKE '%\"quick_mode\": true%')
                    GROUP BY worker
                    """
                ).fetchall()
            }
        return [
            {
                "worker": name,
                "max_concurrent": limits.get(name, 2),
                "active": active.get(name, 0),
                "queued": queued.get(name, 0),
            }
            for name in names
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
                        lease_until, delivered_at, last_error_code, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, NULL, NULL, NULL, ?)
                    ON CONFLICT(job_id, part_index) DO UPDATE SET
                        worker = excluded.worker,
                        title = excluded.title,
                        artifact_ref = CASE WHEN job_tts_deliveries.status = 'delivered' THEN job_tts_deliveries.artifact_ref ELSE excluded.artifact_ref END,
                        byte_size = CASE WHEN job_tts_deliveries.status = 'delivered' THEN job_tts_deliveries.byte_size ELSE excluded.byte_size END,
                        total_parts = excluded.total_parts,
                        status = CASE WHEN job_tts_deliveries.status = 'delivered' THEN 'delivered' ELSE 'pending' END,
                        available_at = excluded.available_at,
                        lease_until = NULL,
                        last_error_code = NULL
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
        self, limit: int = 10, lease_seconds: int = 180
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        lease_until = (now + timedelta(seconds=max(30, int(lease_seconds)))).isoformat()
        claimed: list[dict[str, Any]] = []
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """
                SELECT d.id FROM job_tts_deliveries d
                JOIN jobs j ON j.id = d.job_id
                  WHERE j.status IN ('dispatched', 'running')
                    AND d.status IN ('pending', 'claimed')
                    AND d.available_at <= ?
                    AND (d.lease_until IS NULL OR d.lease_until <= ?)
                    AND NOT EXISTS (
                        SELECT 1 FROM job_tts_deliveries earlier
                        WHERE earlier.job_id = d.job_id
                          AND earlier.part_index < d.part_index
                          AND earlier.status != 'delivered'
                    )
                  ORDER BY d.created_at, d.part_index LIMIT ?
                """,
                (now.isoformat(), now.isoformat(), max(1, min(int(limit), 100))),
            ).fetchall()
            for item in rows:
                delivery_id = str(item["id"])
                db.execute(
                    "UPDATE job_tts_deliveries SET status = 'claimed', lease_until = ?, attempts = attempts + 1 WHERE id = ?",
                    (lease_until, delivery_id),
                )
                row = db.execute(
                    "SELECT id, job_id, title, part_index, total_parts, byte_size, attempts FROM job_tts_deliveries WHERE id = ?",
                    (delivery_id,),
                ).fetchone()
                if row is not None:
                    claimed.append(dict(row))
        return claimed

    def get_tts_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM job_tts_deliveries WHERE id = ?", (str(delivery_id),)
            ).fetchone()
        return dict(row) if row is not None else None

    def complete_tts_delivery(
        self, delivery_id: str, *, delivered: bool
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
            else:
                delay = min(300, 2 ** min(int(row["attempts"]), 8))
                db.execute(
                    "UPDATE job_tts_deliveries SET status = 'pending', lease_until = NULL, available_at = ?, last_error_code = 'TELEGRAM_SEND_FAILED' WHERE id = ?",
                    ((now + timedelta(seconds=delay)).isoformat(), str(delivery_id)),
                )
        return self.get_tts_delivery(delivery_id)

    def tts_delivery_summary(self, job_id: str) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute(
                "SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered, SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled FROM job_tts_deliveries WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
        return {
            "total_parts": int(row["total"] or 0),
            "delivered_parts": int(row["delivered"] or 0),
            "cancelled_parts": int(row["cancelled"] or 0),
        }

    def cancel_tts_deliveries(self, job_id: str) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE job_tts_deliveries SET status = 'cancelled', lease_until = NULL WHERE job_id = ? AND status != 'delivered'",
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
                SELECT p.*, j.worker, j.profile, j.status, j.payload
                FROM job_execution_plans p JOIN jobs j ON j.id = p.job_id
                WHERE p.job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if plan_row is None:
                return {"admitted": True, "position": 1, "blocked_reason": None}
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
            placeholders = ",".join("?" for _ in desired)
            conflicts = []
            if desired:
                conflicts = db.execute(
                    f"SELECT resource_key, job_id FROM job_resource_leases "
                    f"WHERE resource_key IN ({placeholders}) AND job_id != ?",
                    (*sorted(desired), job_id),
                ).fetchall()
            if conflicts:
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
        if status:
            clauses.append("status = ?")
            values.append(status)
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
                f"SELECT * FROM jobs{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
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
        worker: str | None = None,
        quick_mode: bool | None = None,
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
