"""Durable operation and per-worker event store for explicit Vault distribution."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from tme3bot.domain.operations import utc_now


class ProfileDistributionStore:
    def __init__(self, database_path: Path) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS profile_distribution_operations (
                    id TEXT PRIMARY KEY,
                    actor_user_id INTEGER NOT NULL,
                    idempotency_sha256 TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    bundle_sha256 TEXT NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    target_workers_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(actor_user_id,idempotency_sha256)
                );
                CREATE TABLE IF NOT EXISTS profile_distribution_targets (
                    operation_id TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    reason_code TEXT NOT NULL DEFAULT '',
                    archive_message_id INTEGER,
                    archive_sha256 TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(operation_id,worker),
                    FOREIGN KEY(operation_id) REFERENCES profile_distribution_operations(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS profile_distribution_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    sequence INTEGER,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    code TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(operation_id,worker,sequence),
                    FOREIGN KEY(operation_id,worker) REFERENCES profile_distribution_targets(operation_id,worker) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_profile_distribution_profile
                    ON profile_distribution_operations(profile,created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_profile_distribution_pending
                    ON profile_distribution_targets(status,updated_at);
                CREATE INDEX IF NOT EXISTS idx_profile_distribution_events_operation
                    ON profile_distribution_events(operation_id,id);
                CREATE TABLE IF NOT EXISTS profile_distribution_artifact_parts (
                    operation_id TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    part_index INTEGER NOT NULL,
                    part_total INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    archive_sha256 TEXT NOT NULL,
                    PRIMARY KEY(operation_id,worker,part_index),
                    FOREIGN KEY(operation_id,worker) REFERENCES profile_distribution_targets(operation_id,worker) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS profile_distribution_retries (
                    operation_id TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    idempotency_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(operation_id,worker,idempotency_sha256),
                    FOREIGN KEY(operation_id,worker) REFERENCES profile_distribution_targets(operation_id,worker) ON DELETE CASCADE
                );
                """
            )

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _request_hash(profile: str, revision: int, workers: list[str]) -> str:
        del revision, workers  # These are server snapshots, not client request input.
        canonical = json.dumps(
            {"profile": profile},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def create(
        self,
        *,
        actor_user_id: int,
        idempotency_key: str,
        profile: str,
        revision: int,
        bundle_sha256: str,
        telegram_user_id: int,
        target_workers: list[str],
    ) -> tuple[dict[str, Any], bool]:
        key_hash = hashlib.sha256(str(idempotency_key).encode("utf-8")).hexdigest()
        request_hash = self._request_hash(profile, revision, target_workers)
        now = utc_now()
        with self._lock, self._db() as db:
            existing = db.execute(
                "SELECT * FROM profile_distribution_operations WHERE actor_user_id=? AND idempotency_sha256=?",
                (int(actor_user_id), key_hash),
            ).fetchone()
            if existing is not None:
                if str(existing["request_sha256"]) != request_hash:
                    raise ValueError("IDEMPOTENCY_KEY_REUSED")
                operation_id = str(existing["id"])
                return self._operation_locked(db, operation_id), False
            operation_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO profile_distribution_operations "
                "(id,actor_user_id,idempotency_sha256,request_sha256,profile,revision,bundle_sha256,telegram_user_id,target_workers_json,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,'queued',?,?)",
                (
                    operation_id,
                    int(actor_user_id),
                    key_hash,
                    request_hash,
                    profile,
                    int(revision),
                    bundle_sha256,
                    int(telegram_user_id),
                    json.dumps(target_workers, separators=(",", ":")),
                    now,
                    now,
                ),
            )
            for worker in target_workers:
                db.execute(
                    "INSERT INTO profile_distribution_targets "
                    "(operation_id,worker,status,phase,updated_at) VALUES(?,?,'queued','queued',?)",
                    (operation_id, worker, now),
                )
                self._append_event_locked(db, operation_id, worker, "queued", "queued", "PROFILE_DISTRIBUTION_QUEUED", now)
            return self._operation_locked(db, operation_id), True

    def _append_event_locked(
        self, db: sqlite3.Connection, operation_id: str, worker: str,
        phase: str, status: str, code: str, created_at: str | None = None,
        sequence: int | None = None,
    ) -> None:
        db.execute(
            "INSERT OR IGNORE INTO profile_distribution_events "
            "(operation_id,worker,sequence,phase,status,code,created_at) VALUES(?,?,?,?,?,?,?)",
            (operation_id, worker, sequence, phase, status, code[:64], created_at or utc_now()),
        )

    def event(
        self, operation_id: str, worker: str, phase: str, status: str,
        code: str = "", sequence: int | None = None,
    ) -> bool:
        allowed_phases = {
            "queued", "archive_upload", "archive_download", "bundle_validation", "worker_dispatch",
            "download_staging", "download_validation", "download_install",
            "export_staging", "export_validation", "export_install",
            "upload_staging", "upload_validation", "upload_install",
            "identity_install", "session_commit", "transaction_rollback",
            "completed", "waiting_worker", "failed",
        }
        allowed_statuses = {"queued", "running", "waiting", "succeeded", "failed"}
        if phase not in allowed_phases or status not in allowed_statuses:
            raise ValueError("PROFILE_DISTRIBUTION_EVENT_INVALID")
        if code and (len(code) > 64 or not code.replace("_", "").replace("-", "").isalnum() or code.upper() != code):
            raise ValueError("PROFILE_DISTRIBUTION_EVENT_INVALID")
        if sequence is not None and (type(sequence) is not int or sequence < 1):
            raise ValueError("PROFILE_DISTRIBUTION_EVENT_INVALID")
        with self._lock, self._db() as db:
            exists = db.execute(
                "SELECT 1 FROM profile_distribution_targets WHERE operation_id=? AND worker=?",
                (operation_id, worker),
            ).fetchone()
            if exists is None:
                return False
            if sequence is not None:
                previous = db.execute(
                    "SELECT phase,status,code FROM profile_distribution_events WHERE operation_id=? AND worker=? AND sequence=?",
                    (operation_id, worker, sequence),
                ).fetchone()
                if previous is not None:
                    if (str(previous["phase"]), str(previous["status"]), str(previous["code"])) != (phase, status, code):
                        raise ValueError("PROFILE_DISTRIBUTION_EVENT_CONFLICT")
                    return False
            self._append_event_locked(db, operation_id, worker, phase, status, code, sequence=sequence)
            if status == "failed":
                target_status = "failed"
                reason_code = code
            elif status == "succeeded" and phase == "completed":
                target_status = "ready"
                reason_code = ""
            elif status == "waiting":
                target_status = "waiting"
                reason_code = code
            else:
                target_status = "running" if status in {"running", "succeeded"} else "queued"
                reason_code = ""
            db.execute(
                "UPDATE profile_distribution_targets SET status=?,phase=?,reason_code=?,updated_at=? "
                "WHERE operation_id=? AND worker=?",
                (target_status, phase, reason_code, utc_now(), operation_id, worker),
            )
            self._refresh_operation_locked(db, operation_id)
            return True

    def update_target(
        self, operation_id: str, worker: str, status: str, phase: str,
        reason_code: str = "",
    ) -> None:
        if status not in {"queued", "running", "waiting", "ready", "failed"}:
            raise ValueError("PROFILE_DISTRIBUTION_STATUS_INVALID")
        with self._lock, self._db() as db:
            row = db.execute(
                "SELECT status,phase,reason_code FROM profile_distribution_targets WHERE operation_id=? AND worker=?",
                (operation_id, worker),
            ).fetchone()
            if row is None:
                return
            if (str(row["status"]), str(row["phase"]), str(row["reason_code"])) != (status, phase, reason_code):
                self._append_event_locked(
                    db, operation_id, worker, phase,
                    "succeeded" if status == "ready" else "failed" if status == "failed" else "waiting" if status == "waiting" else "running" if status == "running" else "queued",
                    reason_code,
                )
            db.execute(
                "UPDATE profile_distribution_targets SET status=?,phase=?,reason_code=?,updated_at=? "
                "WHERE operation_id=? AND worker=?",
                (status, phase, reason_code[:64], utc_now(), operation_id, worker),
            )
            self._refresh_operation_locked(db, operation_id)

    def record_artifact(self, operation_id: str, worker: str, message_id: int, digest: str) -> None:
        with self._lock, self._db() as db:
            db.execute(
                "UPDATE profile_distribution_targets SET archive_message_id=?,archive_sha256=?,updated_at=? "
                "WHERE operation_id=? AND worker=? AND archive_message_id IS NULL",
                (int(message_id), str(digest), utc_now(), operation_id, worker),
            )

    def artifact_parts(self, operation_id: str, worker: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT part_index,part_total,message_id,archive_sha256 FROM profile_distribution_artifact_parts "
                "WHERE operation_id=? AND worker=? ORDER BY part_index",
                (operation_id, worker),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_artifact_part(
        self, operation_id: str, worker: str, *, part_index: int,
        part_total: int, message_id: int, archive_sha256: str,
    ) -> None:
        if not (1 <= int(part_index) <= int(part_total) <= 100) or int(message_id) < 1:
            raise ValueError("PROFILE_DISTRIBUTION_ARTIFACT_INVALID")
        with self._lock, self._db() as db:
            existing = db.execute(
                "SELECT part_total,message_id,archive_sha256 FROM profile_distribution_artifact_parts "
                "WHERE operation_id=? AND worker=? AND part_index=?",
                (operation_id, worker, int(part_index)),
            ).fetchone()
            if existing is not None:
                if (
                    int(existing["part_total"]) != int(part_total)
                    or int(existing["message_id"]) != int(message_id)
                    or str(existing["archive_sha256"]) != str(archive_sha256)
                ):
                    raise ValueError("PROFILE_DISTRIBUTION_ARTIFACT_CONFLICT")
                return
            db.execute(
                "INSERT INTO profile_distribution_artifact_parts "
                "(operation_id,worker,part_index,part_total,message_id,archive_sha256) VALUES(?,?,?,?,?,?)",
                (operation_id, worker, int(part_index), int(part_total), int(message_id), str(archive_sha256)),
            )
            db.execute(
                "UPDATE profile_distribution_targets SET archive_message_id=COALESCE(archive_message_id,?),archive_sha256=?,updated_at=? "
                "WHERE operation_id=? AND worker=?",
                (int(message_id), str(archive_sha256), utc_now(), operation_id, worker),
            )

    def get_target(self, operation_id: str, worker: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM profile_distribution_targets WHERE operation_id=? AND worker=?",
                (operation_id, worker),
            ).fetchone()
        return dict(row) if row is not None else None

    def pending_targets(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT o.id AS operation_id,o.profile,o.revision,o.bundle_sha256,o.telegram_user_id, "
                "t.worker,t.status,t.phase,t.reason_code,t.archive_message_id,t.archive_sha256 "
                "FROM profile_distribution_operations o JOIN profile_distribution_targets t ON t.operation_id=o.id "
                "WHERE t.status IN ('queued','waiting') ORDER BY o.created_at,t.worker LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def operation(self, operation_id: str, actor_user_id: int | None = None) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM profile_distribution_operations WHERE id=?" + (" AND actor_user_id=?" if actor_user_id is not None else ""),
                (operation_id, int(actor_user_id)) if actor_user_id is not None else (operation_id,),
            ).fetchone()
            if row is None:
                return None
            return self._operation_locked(db, operation_id)

    def _operation_locked(self, db: sqlite3.Connection, operation_id: str) -> dict[str, Any]:
        row = db.execute(
            "SELECT * FROM profile_distribution_operations WHERE id=?", (operation_id,)
        ).fetchone()
        workers = [
            dict(item)
            for item in db.execute(
                "SELECT worker,status,phase,reason_code,archive_message_id,archive_sha256,updated_at "
                "FROM profile_distribution_targets WHERE operation_id=? ORDER BY worker",
                (operation_id,),
            ).fetchall()
        ]
        return {
            "id": str(row["id"]),
            "profile": str(row["profile"]),
            "revision": int(row["revision"]),
            "bundle_sha256": str(row["bundle_sha256"]),
            "target_workers": json.loads(str(row["target_workers_json"])),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "workers": workers,
        }

    def events(self, operation_id: str, *, after_id: int = 0, limit: int = 200) -> dict[str, Any]:
        with self._db() as db:
            rows = db.execute(
                "SELECT id,operation_id,worker,sequence,phase,status,code,created_at "
                "FROM profile_distribution_events WHERE operation_id=? AND id>? ORDER BY id LIMIT ?",
                (operation_id, max(0, int(after_id)), max(1, min(int(limit), 500))),
            ).fetchall()
            maximum = int(db.execute(
                "SELECT COALESCE(MAX(id),0) FROM profile_distribution_events WHERE operation_id=?",
                (operation_id,),
            ).fetchone()[0])
            active = db.execute(
                "SELECT 1 FROM profile_distribution_targets WHERE operation_id=? AND status IN ('queued','running','waiting') LIMIT 1",
                (operation_id,),
            ).fetchone() is not None
        return {"items": [dict(row) for row in rows], "active": active, "next_after_id": maximum}

    def list_for_profile(self, profile: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._db() as db:
            ids = [str(row[0]) for row in db.execute(
                "SELECT id FROM profile_distribution_operations WHERE profile=? ORDER BY created_at DESC LIMIT ?",
                (profile, max(1, min(int(limit), 50))),
            ).fetchall()]
            return [self._operation_locked(db, operation_id) for operation_id in ids]

    def has_active_profile(self, profile: str) -> bool:
        with self._db() as db:
            return db.execute(
                "SELECT 1 FROM profile_distribution_operations WHERE profile=? "
                "AND status IN ('queued','running','waiting') LIMIT 1",
                (str(profile),),
            ).fetchone() is not None

    def retry_worker(self, operation_id: str, worker: str, idempotency_key: str) -> bool:
        key_hash = hashlib.sha256(str(idempotency_key).encode("utf-8")).hexdigest()
        with self._lock, self._db() as db:
            row = db.execute(
                "SELECT status FROM profile_distribution_targets WHERE operation_id=? AND worker=?",
                (operation_id, worker),
            ).fetchone()
            if row is None:
                return False
            if db.execute(
                "SELECT 1 FROM profile_distribution_retries WHERE operation_id=? AND worker=? AND idempotency_sha256=?",
                (operation_id, worker, key_hash),
            ).fetchone() is not None:
                return True
            if str(row["status"]) == "ready":
                return False
            db.execute(
                "INSERT INTO profile_distribution_retries(operation_id,worker,idempotency_sha256,created_at) VALUES(?,?,?,?)",
                (operation_id, worker, key_hash, utc_now()),
            )
            if str(row["status"]) in {"queued", "running"}:
                return True
            self._append_event_locked(db, operation_id, worker, "queued", "queued", "PROFILE_DISTRIBUTION_RETRY_QUEUED")
            db.execute(
                "UPDATE profile_distribution_targets SET status='queued',phase='queued',reason_code='',updated_at=? "
                "WHERE operation_id=? AND worker=?",
                (utc_now(), operation_id, worker),
            )
            db.execute(
                "UPDATE profile_distribution_operations SET status='queued',updated_at=? WHERE id=?",
                (utc_now(), operation_id),
            )
            return True

    def recover_interrupted(self) -> int:
        with self._lock, self._db() as db:
            cursor = db.execute(
                "UPDATE profile_distribution_targets SET status='waiting',phase='waiting_worker',reason_code='BACKEND_RESTARTED',updated_at=? "
                "WHERE status='running'",
                (utc_now(),),
            )
            db.execute(
                "UPDATE profile_distribution_operations SET status='waiting',updated_at=? "
                "WHERE id IN (SELECT operation_id FROM profile_distribution_targets WHERE status='waiting') "
                "AND status='running'",
                (utc_now(),),
            )
            return int(cursor.rowcount)

    def _refresh_operation_locked(self, db: sqlite3.Connection, operation_id: str) -> None:
        statuses = [str(row[0]) for row in db.execute(
            "SELECT status FROM profile_distribution_targets WHERE operation_id=?", (operation_id,)
        ).fetchall()]
        if statuses and all(value == "ready" for value in statuses):
            status = "succeeded"
        elif any(value in {"queued", "running", "waiting"} for value in statuses):
            status = "waiting" if all(value in {"waiting", "ready"} for value in statuses) else "running"
        elif any(value == "failed" for value in statuses):
            status = "failed"
        else:
            status = "queued"
        db.execute(
            "UPDATE profile_distribution_operations SET status=?,updated_at=? WHERE id=?",
            (status, utc_now(), operation_id),
        )
