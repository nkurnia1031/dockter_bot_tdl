from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ACTIVE_RESTART_STATUSES = ("queued", "restarting")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _load(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw) if raw else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


class SqliteWorkerRestartStore:
    """Small durable queue and audit record for host-side worker restarts."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        return db

    @contextmanager
    def _db(self):
        db = self._connect()
        try:
            yield db
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._lock, self._db() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS worker_restart_operations (
                    id TEXT PRIMARY KEY,
                    worker TEXT NOT NULL,
                    actor_user_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    active_job_ids_json TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    lease_until TEXT
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS worker_restart_worker_status "
                "ON worker_restart_operations(worker,status,created_at DESC)"
            )
            db.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS worker_restart_one_active
                ON worker_restart_operations(worker)
                WHERE status IN ('queued','restarting')"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS worker_supervisor_heartbeats (
                    worker TEXT PRIMARY KEY,
                    last_seen_at TEXT NOT NULL
                )"""
            )

    @staticmethod
    def _operation(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        active_ids = _load(row["active_job_ids_json"], [])
        active_ids = active_ids if isinstance(active_ids, list) else []
        result = _load(row["result_json"], {})
        return {
            "id": str(row["id"]),
            "worker": str(row["worker"]),
            "actor_user_id": int(row["actor_user_id"]),
            "status": str(row["status"]),
            "active_job_ids": [str(value) for value in active_ids if str(value)],
            "active_job_count": len(active_ids),
            "result": result if isinstance(result, dict) else {},
            "attempts": int(row["attempts"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "lease_until": str(row["lease_until"] or ""),
        }

    def create(self, worker: str, actor_user_id: int, active_job_ids: list[str]) -> tuple[dict[str, Any], bool]:
        name = str(worker or "").strip().lower()
        now = _iso(_now())
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                current = db.execute(
                    "SELECT * FROM worker_restart_operations WHERE worker=? "
                    "AND status IN ('queued','restarting') ORDER BY created_at DESC LIMIT 1",
                    (name,),
                ).fetchone()
                if current is not None:
                    db.commit()
                    return self._operation(current), False
                operation_id = str(uuid.uuid4())
                db.execute(
                    "INSERT INTO worker_restart_operations "
                    "(id,worker,actor_user_id,status,active_job_ids_json,created_at,updated_at) "
                    "VALUES (?,?,?,'queued',?,?,?)",
                    (
                        operation_id,
                        name,
                        int(actor_user_id),
                        json.dumps(list(dict.fromkeys(active_job_ids)), separators=(",", ":")),
                        now,
                        now,
                    ),
                )
                row = db.execute(
                    "SELECT * FROM worker_restart_operations WHERE id=?", (operation_id,)
                ).fetchone()
                db.commit()
                return self._operation(row), True
            except Exception:
                db.rollback()
                raise

    def active(self, worker: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM worker_restart_operations WHERE worker=? "
                "AND status IN ('queued','restarting') ORDER BY created_at DESC LIMIT 1",
                (str(worker or "").strip().lower(),),
            ).fetchone()
        return self._operation(row)

    def has_active_restart(self, worker: str) -> bool:
        return self.active(worker) is not None

    def get(self, operation_id: str, *, worker: str | None = None) -> dict[str, Any] | None:
        query = "SELECT * FROM worker_restart_operations WHERE id=?"
        values: list[Any] = [str(operation_id)]
        if worker is not None:
            query += " AND worker=?"
            values.append(str(worker).strip().lower())
        with self._db() as db:
            row = db.execute(query, values).fetchone()
        return self._operation(row)

    def record_supervisor_heartbeat(self, worker: str) -> str:
        name = str(worker or "").strip().lower()
        now = _iso(_now())
        with self._db() as db:
            db.execute(
                "INSERT INTO worker_supervisor_heartbeats(worker,last_seen_at) VALUES (?,?) "
                "ON CONFLICT(worker) DO UPDATE SET last_seen_at=excluded.last_seen_at",
                (name, now),
            )
        return now

    def supervisor_seen_at(self, worker: str) -> str | None:
        with self._db() as db:
            row = db.execute(
                "SELECT last_seen_at FROM worker_supervisor_heartbeats WHERE worker=?",
                (str(worker or "").strip().lower(),),
            ).fetchone()
        return str(row[0]) if row else None

    def claim_next(self, worker: str, *, lease_seconds: int = 120) -> dict[str, Any] | None:
        name = str(worker or "").strip().lower()
        now_dt = _now()
        now = _iso(now_dt)
        lease_until = _iso(now_dt + timedelta(seconds=max(30, min(300, int(lease_seconds)))))
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    "INSERT INTO worker_supervisor_heartbeats(worker,last_seen_at) VALUES (?,?) "
                    "ON CONFLICT(worker) DO UPDATE SET last_seen_at=excluded.last_seen_at",
                    (name, now),
                )
                row = db.execute(
                    "SELECT * FROM worker_restart_operations WHERE worker=? AND ("
                    "status='queued' OR (status='restarting' AND (lease_until IS NULL OR lease_until<=?))) "
                    "ORDER BY created_at LIMIT 1",
                    (name, now),
                ).fetchone()
                if row is None:
                    db.commit()
                    return None
                db.execute(
                    "UPDATE worker_restart_operations SET status='restarting',attempts=attempts+1,"
                    "updated_at=?,lease_until=? WHERE id=?",
                    (now, lease_until, row["id"]),
                )
                row = db.execute(
                    "SELECT * FROM worker_restart_operations WHERE id=?", (row["id"],)
                ).fetchone()
                db.commit()
                return self._operation(row)
            except Exception:
                db.rollback()
                raise

    def finish(
        self, operation_id: str, worker: str, *, status: str, result: dict[str, Any]
    ) -> dict[str, Any] | None:
        if status not in {"succeeded", "failed"}:
            raise ValueError("Worker restart terminal status is invalid.")
        name = str(worker or "").strip().lower()
        now = _iso(_now())
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT * FROM worker_restart_operations WHERE id=? AND worker=?",
                    (str(operation_id), name),
                ).fetchone()
                if row is None:
                    db.commit()
                    return None
                if row["status"] in {"succeeded", "failed"}:
                    db.commit()
                    return self._operation(row)
                db.execute(
                    "UPDATE worker_restart_operations SET status=?,result_json=?,updated_at=?,lease_until=NULL "
                    "WHERE id=? AND worker=?",
                    (status, json.dumps(result, ensure_ascii=False, separators=(",", ":")), now, str(operation_id), name),
                )
                db.execute(
                    "INSERT INTO worker_supervisor_heartbeats(worker,last_seen_at) VALUES (?,?) "
                    "ON CONFLICT(worker) DO UPDATE SET last_seen_at=excluded.last_seen_at",
                    (name, now),
                )
                row = db.execute(
                    "SELECT * FROM worker_restart_operations WHERE id=?", (str(operation_id),)
                ).fetchone()
                db.commit()
                return self._operation(row)
            except Exception:
                db.rollback()
                raise
