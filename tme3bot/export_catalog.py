"""Gateway-owned catalog for export JSON artifacts.

The worker owns the physical JSON file.  The gateway only persists an opaque
artifact key and statistics needed by frontends.
"""

from __future__ import annotations

import json
import mimetypes
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tme3bot.media import has_downloadable_media


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def inspect_export_json(path: Path) -> dict[str, Any]:
    """Return safe media statistics without assuming a single TDL JSON shape."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    messages = payload.get("messages", []) if isinstance(payload, dict) else []
    if not isinstance(messages, list):
        messages = []
    counts = {"message_count": len(messages), "media_count": 0, "photo_count": 0,
              "video_count": 0, "other_media_count": 0}
    expected_bytes = 0
    has_expected_bytes = False
    for message in messages:
        if not isinstance(message, dict):
            continue
        if not has_downloadable_media(message):
            continue
        counts["media_count"] += 1
        file_value = next(
            (
                message.get(key)
                for key in ("file", "document", "media", "file_name", "FileName")
                if message.get(key)
            ),
            "",
        )
        name = ""
        size = None
        if isinstance(file_value, dict):
            name = str(file_value.get("name") or file_value.get("path") or "")
            raw_size = file_value.get("size")
            if isinstance(raw_size, (int, float)) and raw_size >= 0:
                size = int(raw_size)
        else:
            name = str(file_value)
            raw_size = message.get("size")
            if isinstance(raw_size, (int, float)) and raw_size >= 0:
                size = int(raw_size)
        kind = str(message.get("type") or "").lower()
        mime = str(message.get("mime_type") or mimetypes.guess_type(name)[0] or "")
        if "photo" in kind or mime.startswith("image/"):
            counts["photo_count"] += 1
        elif "video" in kind or mime.startswith("video/"):
            counts["video_count"] += 1
        else:
            counts["other_media_count"] += 1
        if size is not None:
            expected_bytes += size
            has_expected_bytes = True
    metadata = payload.get("tme3bot", {}) if isinstance(payload, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        **counts,
        "expected_media_bytes": expected_bytes if has_expected_bytes else None,
        "json_bytes": Path(path).stat().st_size,
        "chat_ref": str(metadata.get("chat_ref") or payload.get("id") or ""),
        "label": metadata.get("label"),
    }


def discard_export_without_media(path: Path, stats: dict[str, Any]) -> bool:
    """Remove an export JSON when its inspected media count is exactly zero.

    The worker calls this only after the JSON has been parsed successfully.  A
    missing file is treated as an idempotent success, while an unknown or
    non-zero media count is never removed.  This keeps a malformed/unsupported
    export safe and avoids accidentally deleting a useful artifact when the
    inspector cannot determine its contents.
    """
    media_count = stats.get("media_count")
    if (
        isinstance(media_count, bool)
        or not isinstance(media_count, (int, float))
        or media_count != 0
    ):
        return False
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
    return True


class ExportArtifactCatalog:
    STATUSES = {
        "pending", "processing", "downloaded", "failed", "deleted", "archived"
    }

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
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
                CREATE TABLE IF NOT EXISTS export_artifacts (
                    id TEXT PRIMARY KEY,
                    profile TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    export_job_id TEXT,
                    filename TEXT NOT NULL,
                    artifact_key TEXT NOT NULL,
                    chat_ref TEXT NOT NULL DEFAULT '',
                    label TEXT,
                    status TEXT NOT NULL,
                    json_bytes INTEGER,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    media_count INTEGER NOT NULL DEFAULT 0,
                    photo_count INTEGER NOT NULL DEFAULT 0,
                    video_count INTEGER NOT NULL DEFAULT 0,
                    other_media_count INTEGER NOT NULL DEFAULT 0,
                    expected_media_bytes INTEGER,
                    actual_downloaded_bytes INTEGER,
                    download_directory TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    archived_at TEXT,
                    UNIQUE(profile, worker, artifact_key)
                );
                CREATE INDEX IF NOT EXISTS export_artifacts_queue
                    ON export_artifacts(profile, status, created_at);
                CREATE INDEX IF NOT EXISTS export_artifacts_worker
                    ON export_artifacts(worker, profile, status);
                CREATE INDEX IF NOT EXISTS export_artifacts_scope_created
                    ON export_artifacts(profile, worker, archived_at, created_at DESC);
                CREATE INDEX IF NOT EXISTS export_artifacts_global_created
                    ON export_artifacts(archived_at, created_at DESC);
                """
            )
            self._ensure_column(
                db,
                "export_artifacts",
                "available",
                "INTEGER NOT NULL DEFAULT 1",
            )
            self._ensure_column(
                db, "export_artifacts", "last_seen_inventory_id", "TEXT"
            )
            self._ensure_column(db, "export_artifacts", "last_seen_at", "TEXT")
            self._ensure_column(db, "export_artifacts", "missing_at", "TEXT")
            db.execute(
                """CREATE INDEX IF NOT EXISTS export_artifacts_inventory
                   ON export_artifacts(profile, worker, last_seen_inventory_id)"""
            )

    @staticmethod
    def _ensure_column(
        db: sqlite3.Connection, table: str, column: str, declaration: str
    ) -> None:
        columns = {
            str(row["name"])
            for row in db.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @classmethod
    def _record_from_values(cls, values: dict[str, Any], now: str) -> dict[str, Any]:
        status = str(values.get("status") or "pending")
        if status not in cls.STATUSES:
            raise ValueError("Status artifact tidak valid.")
        record = {
            "id": str(values.get("id") or uuid.uuid4()),
            "profile": str(values["profile"]),
            "worker": str(values["worker"]),
            "export_job_id": values.get("export_job_id"),
            "filename": str(values["filename"]),
            "artifact_key": str(values["artifact_key"]),
            "chat_ref": str(values.get("chat_ref") or ""),
            "label": values.get("label"),
            "status": status,
            "json_bytes": values.get("json_bytes"),
            "message_count": int(values.get("message_count") or 0),
            "media_count": int(values.get("media_count") or 0),
            "photo_count": int(values.get("photo_count") or 0),
            "video_count": int(values.get("video_count") or 0),
            "other_media_count": int(values.get("other_media_count") or 0),
            "expected_media_bytes": values.get("expected_media_bytes"),
            "actual_downloaded_bytes": values.get("actual_downloaded_bytes"),
            "download_directory": values.get("download_directory"),
            "error": values.get("error"),
            "created_at": str(values.get("created_at") or now),
            "started_at": values.get("started_at"),
            "completed_at": values.get("completed_at"),
            "archived_at": values.get("archived_at"),
            "available": int(bool(values.get("available", True))),
            "last_seen_inventory_id": values.get("last_seen_inventory_id"),
            "last_seen_at": values.get("last_seen_at"),
            "missing_at": values.get("missing_at"),
        }
        if record["last_seen_inventory_id"] and not record["last_seen_at"]:
            record["last_seen_at"] = now
        if record["available"]:
            record["missing_at"] = None
        return record

    @staticmethod
    def _upsert_sql(record: dict[str, Any]) -> str:
        columns = ", ".join(record)
        placeholders = ", ".join(f":{name}" for name in record)
        updates = ", ".join(
            f"{name}=excluded.{name}"
            for name in record
            if name
            not in {
                "id",
                "profile",
                "worker",
                "artifact_key",
                "created_at",
                "archived_at",
            }
        )
        return f"""INSERT INTO export_artifacts({columns}) VALUES({placeholders})
            ON CONFLICT(profile, worker, artifact_key) DO UPDATE SET {updates}"""

    def upsert(self, **values: Any) -> dict[str, Any]:
        now = utc_now()
        record = self._record_from_values(values, now)
        with self._db() as db:
            db.execute(self._upsert_sql(record), record)
            row = db.execute(
                """SELECT * FROM export_artifacts
                   WHERE profile=? AND worker=? AND artifact_key=?""",
                (record["profile"], record["worker"], record["artifact_key"]),
            ).fetchone()
        return dict(row)

    def upsert_many(self, values: list[dict[str, Any]]) -> int:
        """Upsert an inventory batch in one SQLite transaction.

        Inventory can contain hundreds of JSON files.  Keeping one connection,
        one transaction, and one request per batch avoids the per-file commit
        and HTTP round-trip that made reconcile appear stalled.
        """
        if not values:
            return 0
        now = utc_now()
        records = [self._record_from_values(item, now) for item in values]
        with self._db() as db:
            db.executemany(self._upsert_sql(records[0]), records)
        return len(records)

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM export_artifacts WHERE id=?", (artifact_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_by_key(
        self, profile: str, worker: str, artifact_key: str
    ) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                """SELECT * FROM export_artifacts
                   WHERE profile=? AND worker=? AND artifact_key=?""",
                (profile, worker, artifact_key),
            ).fetchone()
        return dict(row) if row else None

    def list(
        self,
        *,
        profile: str | None = None,
        status: str | None = None,
        archived: bool | None = False,
        worker: str | None = None,
        available: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses, params = [], []
        if profile:
            clauses.append("profile=?")
            params.append(profile)
        if status:
            clauses.append("status=?")
            params.append(status)
        if worker:
            clauses.append("worker=?")
            params.append(worker)
        if available is not None:
            clauses.append("available=?")
            params.append(int(available))
        if archived is True:
            clauses.append("archived_at IS NOT NULL")
        elif archived is False:
            clauses.append("archived_at IS NULL")
        where = " AND ".join(clauses) or "1=1"
        with self._db() as db:
            total = int(db.execute(
                f"SELECT COUNT(*) FROM export_artifacts WHERE {where}", params
            ).fetchone()[0])
            rows = db.execute(
                f"""SELECT * FROM export_artifacts WHERE {where}
                    ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                [*params, max(1, min(limit, 200)), max(0, offset)],
            ).fetchall()
        return [dict(row) for row in rows], total

    def update_status(
        self, artifact_id: str, status: str, **changes: Any
    ) -> dict[str, Any]:
        if status not in self.STATUSES:
            raise ValueError("Status artifact tidak valid.")
        allowed = {
            "actual_downloaded_bytes", "download_directory", "error",
            "started_at", "completed_at", "archived_at", "available",
            "last_seen_inventory_id", "last_seen_at", "missing_at",
        }
        values = {key: value for key, value in changes.items() if key in allowed}
        if status == "processing" and "started_at" not in values:
            values["started_at"] = utc_now()
        if status == "downloaded" and "completed_at" not in values:
            values["completed_at"] = utc_now()
        values["status"] = status
        assignments = ", ".join(f"{key}=:{key}" for key in values)
        values["id"] = artifact_id
        with self._db() as db:
            db.execute(
                f"UPDATE export_artifacts SET {assignments} WHERE id=:id", values
            )
        result = self.get(artifact_id)
        if result is None:
            raise KeyError("Artifact tidak ditemukan.")
        return result

    def complete_inventory(
        self, profile: str, worker: str, inventory_id: str
    ) -> int:
        """Mark catalog rows absent when a worker inventory completes."""
        now = utc_now()
        with self._db() as db:
            cursor = db.execute(
                """UPDATE export_artifacts
                   SET available=0, missing_at=COALESCE(missing_at, ?)
                   WHERE profile=? AND worker=?
                     AND (last_seen_inventory_id IS NULL
                          OR last_seen_inventory_id<>?)""",
                (now, profile, worker, inventory_id),
            )
        return int(cursor.rowcount)

    def mark_missing(
        self, profile: str, worker: str, artifact_key: str
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._db() as db:
            db.execute(
                """UPDATE export_artifacts
                   SET available=0, missing_at=COALESCE(missing_at, ?)
                   WHERE profile=? AND worker=? AND artifact_key=?""",
                (now, profile, worker, artifact_key),
            )
        return self.get_by_key(profile, worker, artifact_key)

    def archive(self, artifact_id: str) -> dict[str, Any]:
        item = self.get(artifact_id)
        if item is None:
            raise KeyError("Artifact tidak ditemukan.")
        if item["status"] not in {"downloaded", "failed", "deleted"}:
            raise ValueError("Hanya artifact terminal yang dapat diarsipkan.")
        return self.update_status(
            artifact_id, "archived", archived_at=utc_now()
        )

    def restore(self, artifact_id: str) -> dict[str, Any]:
        item = self.get(artifact_id)
        if item is None:
            raise KeyError("Artifact tidak ditemukan.")
        restored = "downloaded" if item.get("completed_at") and not item.get("error") else "failed"
        return self.update_status(artifact_id, restored, archived_at=None)

    def purge(self, artifact_id: str) -> bool:
        with self._db() as db:
            row = db.execute(
                "SELECT archived_at FROM export_artifacts WHERE id=?", (artifact_id,)
            ).fetchone()
            if row is None:
                return False
            if not row["archived_at"]:
                raise ValueError("Artifact harus diarsipkan sebelum purge.")
            db.execute("DELETE FROM export_artifacts WHERE id=?", (artifact_id,))
        return True

    def summary(self, profile: str | None = None, worker: str | None = None) -> dict[str, int]:
        clauses, params = [], []
        if profile:
            clauses.append("profile=?")
            params.append(profile)
        if worker:
            clauses.append("worker=?")
            params.append(worker)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._db() as db:
            rows = db.execute(
                """SELECT status, COUNT(*) AS total FROM export_artifacts
                   """ + where + " GROUP BY status", params
            ).fetchall()
        return {str(row["status"]): int(row["total"]) for row in rows}

    def origins(self, *, include_archived: bool = False) -> list[tuple[str, str]]:
        clause = "" if include_archived else " WHERE archived_at IS NULL"
        with self._db() as db:
            rows = db.execute(
                "SELECT DISTINCT profile, worker FROM export_artifacts"
                + clause
                + " ORDER BY profile, worker"
            ).fetchall()
        return [(str(row["profile"]), str(row["worker"])) for row in rows]
