"""Persistent catalog for the shared Telegram storage channel."""

from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

CAPTION_LIMIT = 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _caption_value(value: str, limit: int = 300) -> str:
    value = " ".join(str(value or "").split())
    return value[:limit]


def _slug(value: str) -> str:
    value = re.sub(r"[^\w-]+", "_", value.strip(), flags=re.UNICODE).strip("_")
    return value[:48]


def build_storage_caption(folder: str, name: str, keywords: str = "") -> str:
    folder = _caption_value(folder)
    name = _caption_value(name)
    keywords = _caption_value(keywords, 600)
    keyword_list = [item.strip() for item in keywords.split(",") if item.strip()]
    tags = ["#storage"]
    if folder:
        tags.append(f"#folder_{_slug(folder)}")
    tags.extend(f"#kw_{_slug(item)}" for item in keyword_list if _slug(item))
    lines = [f"📁 Folder: {folder or '-'}", f"📄 Name: {name or '-'}", f"🔑 Keywords: {keywords or '-'}", " ".join(tags)]
    caption = "\n".join(lines)
    return caption if len(caption) <= CAPTION_LIMIT else caption[: CAPTION_LIMIT - 1].rstrip() + "…"


@dataclass(frozen=True)
class StorageItem:
    id: int
    upload_id: str
    owner_user_id: int
    owner_profile: str
    channel_id: int
    channel_message_id: int
    original_name: str
    display_name: str
    folder: str
    keywords: str
    caption: str
    file_size: int | None
    mime_type: str
    sha256: str
    uploaded_at: str
    updated_at: str
    status: str


class StorageCatalog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def backup_database_to(self, destination: Path) -> None:
        """Create a consistent SQLite snapshot, including WAL contents."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            source = self._connect()
            target = sqlite3.connect(str(destination))
            try:
                source.backup(target)
                target.commit()
            finally:
                target.close()
                source.close()

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._db() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS storage_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    upload_id TEXT NOT NULL UNIQUE,
                    owner_user_id INTEGER NOT NULL,
                    owner_profile TEXT NOT NULL,
                    channel_id INTEGER NOT NULL,
                    channel_message_id INTEGER NOT NULL,
                    original_name TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    folder TEXT NOT NULL DEFAULT '',
                    keywords TEXT NOT NULL DEFAULT '',
                    caption TEXT NOT NULL DEFAULT '',
                    file_size INTEGER,
                    mime_type TEXT NOT NULL DEFAULT '',
                    sha256 TEXT NOT NULL DEFAULT '',
                    uploaded_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    UNIQUE(channel_id, channel_message_id)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS storage_items_fts USING fts5(
                    display_name, original_name, folder, keywords, caption,
                    item_id UNINDEXED
                );
                CREATE TABLE IF NOT EXISTS backup_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    node_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    error TEXT,
                    UNIQUE(run_id, node_name)
                );
                CREATE TABLE IF NOT EXISTS backup_parts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    node_name TEXT NOT NULL,
                    part_name TEXT NOT NULL,
                    channel_id INTEGER NOT NULL,
                    channel_message_id INTEGER NOT NULL,
                    file_size INTEGER,
                    sha256 TEXT NOT NULL DEFAULT '',
                    uploaded_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    UNIQUE(run_id, node_name, part_name)
                );
                CREATE INDEX IF NOT EXISTS idx_backup_runs_node ON backup_runs(node_name, started_at);
                CREATE INDEX IF NOT EXISTS idx_backup_parts_run ON backup_parts(run_id, node_name);
                """
            )
            try:
                db.execute(
                    """CREATE VIRTUAL TABLE IF NOT EXISTS storage_items_trigram
                       USING fts5(display_name, original_name, folder, keywords,
                                  caption, item_id UNINDEXED, tokenize='trigram')"""
                )
                self._trigram_enabled = True
            except sqlite3.OperationalError:
                self._trigram_enabled = False
            db.execute("CREATE INDEX IF NOT EXISTS idx_storage_owner ON storage_items(owner_user_id, status)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_storage_status ON storage_items(status)")
            self._rebuild_fts_locked(db)

    def _rebuild_fts_locked(self, db: sqlite3.Connection) -> None:
        db.execute("DELETE FROM storage_items_fts")
        db.execute(
            """INSERT INTO storage_items_fts(display_name, original_name, folder, keywords, caption, item_id)
               SELECT display_name, original_name, folder, keywords, caption, id
               FROM storage_items WHERE status != 'deleted'"""
        )
        if getattr(self, "_trigram_enabled", False):
            db.execute("DELETE FROM storage_items_trigram")
            db.execute(
                """INSERT INTO storage_items_trigram(
                       display_name, original_name, folder, keywords, caption, item_id
                   )
                   SELECT display_name, original_name, folder, keywords, caption, id
                   FROM storage_items WHERE status != 'deleted'"""
            )

    @staticmethod
    def _item(row: sqlite3.Row | None) -> StorageItem | None:
        return StorageItem(**dict(row)) if row is not None else None

    def get(self, item_id: int, *, include_deleted: bool = False) -> StorageItem | None:
        with self._lock, self._db() as db:
            row = db.execute("SELECT * FROM storage_items WHERE id = ?", (item_id,)).fetchone()
            item = self._item(row)
            if item and item.status == "deleted" and not include_deleted:
                return None
            return item

    def get_by_upload_id(self, upload_id: str) -> StorageItem | None:
        with self._lock, self._db() as db:
            return self._item(db.execute("SELECT * FROM storage_items WHERE upload_id = ?", (upload_id,)).fetchone())

    def insert_item(self, **values) -> StorageItem:
        """Insert a callback result, returning the existing item on retry."""
        upload_id = str(values["upload_id"])
        with self._lock, self._db() as db:
            existing = db.execute("SELECT * FROM storage_items WHERE upload_id = ?", (upload_id,)).fetchone()
            if existing is not None:
                return self._item(existing)  # type: ignore[return-value]
            now = values.get("uploaded_at") or utc_now()
            values["uploaded_at"] = now
            values.setdefault("updated_at", now)
            values.setdefault("status", "active")
            values.setdefault("file_size", None)
            values.setdefault("mime_type", "")
            values.setdefault("sha256", "")
            values.setdefault("caption", build_storage_caption(values["folder"], values["display_name"], values.get("keywords", "")))
            db.execute(
                """INSERT INTO storage_items
                (upload_id, owner_user_id, owner_profile, channel_id, channel_message_id,
                 original_name, display_name, folder, keywords, caption, file_size,
                 mime_type, sha256, uploaded_at, updated_at, status)
                VALUES (:upload_id, :owner_user_id, :owner_profile, :channel_id,
                 :channel_message_id, :original_name, :display_name, :folder, :keywords,
                 :caption, :file_size, :mime_type, :sha256, :uploaded_at, :updated_at, :status)""",
                values,
            )
            item_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
            self._sync_fts_locked(db, item_id)
            return self._item(db.execute("SELECT * FROM storage_items WHERE id = ?", (item_id,)).fetchone())  # type: ignore[return-value]

    def _sync_fts_locked(self, db: sqlite3.Connection, item_id: int) -> None:
        db.execute("DELETE FROM storage_items_fts WHERE item_id = ?", (item_id,))
        db.execute(
            """INSERT INTO storage_items_fts(display_name, original_name, folder, keywords, caption, item_id)
               SELECT display_name, original_name, folder, keywords, caption, id
               FROM storage_items WHERE id = ? AND status != 'deleted'""", (item_id,)
        )
        if getattr(self, "_trigram_enabled", False):
            db.execute("DELETE FROM storage_items_trigram WHERE item_id = ?", (item_id,))
            db.execute(
                """INSERT INTO storage_items_trigram(
                       display_name, original_name, folder, keywords, caption, item_id
                   )
                   SELECT display_name, original_name, folder, keywords, caption, id
                   FROM storage_items WHERE id = ? AND status != 'deleted'""",
                (item_id,),
            )

    def search(self, query: str = "", *, owner_user_id: int | None = None, limit: int = 10, offset: int = 0) -> list[StorageItem]:
        limit, offset = max(1, min(int(limit), 100)), max(0, int(offset))
        with self._lock, self._db() as db:
            params: list[object] = []
            if query.strip():
                terms = [re.sub(r'[^\w-]', '', part) for part in query.split()]
                terms = [term for term in terms if term]
                if not terms:
                    return []
                exact_query = " AND ".join(f'"{term}"*' for term in terms)
                if getattr(self, "_trigram_enabled", False) and len(query.strip()) >= 3:
                    where = """i.id IN (
                        SELECT item_id FROM storage_items_fts
                        WHERE storage_items_fts MATCH ?
                        UNION
                        SELECT item_id FROM storage_items_trigram
                        WHERE storage_items_trigram MATCH ?
                    )"""
                    params.extend([exact_query, query.strip()])
                else:
                    where = "i.id IN (SELECT item_id FROM storage_items_fts WHERE storage_items_fts MATCH ?)"
                    params.append(exact_query)
            else:
                where = "1=1"
            where += " AND i.status = 'active'"
            if owner_user_id is not None:
                where += " AND i.owner_user_id = ?"
                params.append(owner_user_id)
            params.extend([limit, offset])
            rows = db.execute(f"SELECT i.* FROM storage_items i WHERE {where} ORDER BY i.id DESC LIMIT ? OFFSET ?", params).fetchall()
            return [self._item(row) for row in rows]  # type: ignore[misc]

    def count(self, query: str = "", *, owner_user_id: int | None = None) -> int:
        total = 0
        while True:
            page = self.search(
                query, owner_user_id=owner_user_id, limit=100, offset=total
            )
            total += len(page)
            if len(page) < 100:
                return total

    def _owned_update(self, item_id: int, owner_user_id: int, changes: dict[str, object]) -> StorageItem:
        with self._lock, self._db() as db:
            row = db.execute("SELECT * FROM storage_items WHERE id = ?", (item_id,)).fetchone()
            item = self._item(row)
            if item is None:
                raise KeyError("Storage item tidak ditemukan.")
            if item.owner_user_id != int(owner_user_id):
                raise PermissionError("Item storage hanya dapat diubah oleh pemiliknya.")
            changes["updated_at"] = utc_now()
            assignments = ", ".join(f"{key} = :{key}" for key in changes)
            changes["id"] = item_id
            db.execute(f"UPDATE storage_items SET {assignments} WHERE id = :id", changes)
            self._sync_fts_locked(db, item_id)
            return self._item(db.execute("SELECT * FROM storage_items WHERE id = ?", (item_id,)).fetchone())  # type: ignore[return-value]

    def rename(self, item_id: int, owner_user_id_or_name: int | str, display_name: str | None = None) -> StorageItem:
        # Keep the old call shape for compatibility, but rename is intentionally
        # available to every authorized user. The numeric argument is ignored.
        display_name = str(owner_user_id_or_name) if display_name is None else display_name
        display_name = " ".join(display_name.split()).strip()
        if not display_name:
            raise ValueError("Nama tampilan tidak boleh kosong.")
        item = self.get(item_id)
        if item is None:
            raise KeyError("Storage item tidak ditemukan.")
        caption = build_storage_caption(item.folder, display_name, item.keywords)
        return self._owned_update(item_id, item.owner_user_id, {"display_name": display_name, "caption": caption})

    def update_metadata(self, item_id: int, owner_user_id: int, *, folder: str | None = None, keywords: str | None = None) -> StorageItem:
        item = self.get(item_id)
        if item is None:
            raise KeyError("Storage item tidak ditemukan.")
        new_folder = item.folder if folder is None else " ".join(folder.split()).strip()
        new_keywords = item.keywords if keywords is None else " ".join(keywords.split()).strip()
        return self._owned_update(item_id, owner_user_id, {"folder": new_folder, "keywords": new_keywords, "caption": build_storage_caption(new_folder, item.display_name, new_keywords)})

    def mark_deleted(self, item_id: int, owner_user_id: int, *, failed: bool = False) -> StorageItem:
        return self._owned_update(item_id, owner_user_id, {"status": "delete_failed" if failed else "deleted"})

    def mark_status(self, item_id: int, status: str) -> StorageItem:
        if status not in {"active", "uploading", "failed", "delete_failed"}:
            raise ValueError("Status storage tidak valid.")
        with self._lock, self._db() as db:
            db.execute("UPDATE storage_items SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now(), item_id))
            self._sync_fts_locked(db, item_id)
            return self._item(db.execute("SELECT * FROM storage_items WHERE id = ?", (item_id,)).fetchone())  # type: ignore[return-value]

    def start_backup_run(self, run_id: str, node_name: str) -> None:
        with self._lock, self._db() as db:
            db.execute(
                """INSERT INTO backup_runs(run_id, node_name, started_at, status)
                   VALUES (?, ?, ?, 'running')
                   ON CONFLICT(run_id, node_name) DO NOTHING""",
                (run_id, node_name, utc_now()),
            )

    def finish_backup_run(self, run_id: str, node_name: str, status: str = "complete", error: str | None = None) -> None:
        if status not in {"complete", "failed", "offline", "cleanup_failed"}:
            raise ValueError("Status backup tidak valid.")
        with self._lock, self._db() as db:
            db.execute(
                "UPDATE backup_runs SET completed_at = ?, status = ?, error = ? WHERE run_id = ? AND node_name = ?",
                (utc_now(), status, error[:1000] if error else None, run_id, node_name),
            )

    def upsert_backup_part(self, **values) -> None:
        values.setdefault("uploaded_at", utc_now())
        values.setdefault("status", "active")
        with self._lock, self._db() as db:
            db.execute(
                """INSERT INTO backup_parts
                   (run_id, node_name, part_name, channel_id, channel_message_id,
                    file_size, sha256, uploaded_at, status)
                   VALUES (:run_id, :node_name, :part_name, :channel_id,
                    :channel_message_id, :file_size, :sha256, :uploaded_at, :status)
                   ON CONFLICT(run_id, node_name, part_name) DO UPDATE SET
                    channel_id=excluded.channel_id,
                    channel_message_id=excluded.channel_message_id,
                    file_size=excluded.file_size,
                    sha256=excluded.sha256,
                    uploaded_at=excluded.uploaded_at,
                    status=excluded.status""",
                values,
            )

    def backup_parts(self, run_id: str, node_name: str) -> list[dict[str, object]]:
        with self._lock, self._db() as db:
            rows = db.execute(
                "SELECT * FROM backup_parts WHERE run_id = ? AND node_name = ? ORDER BY part_name",
                (run_id, node_name),
            ).fetchall()
            return [dict(row) for row in rows]

    def backup_runs(self, node_name: str | None = None, limit: int = 50) -> list[dict[str, object]]:
        with self._lock, self._db() as db:
            if node_name:
                rows = db.execute(
                    "SELECT * FROM backup_runs WHERE node_name = ? ORDER BY started_at DESC LIMIT ?",
                    (node_name, max(1, min(limit, 200))),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM backup_runs ORDER BY started_at DESC LIMIT ?",
                    (max(1, min(limit, 200)),),
                ).fetchall()
            return [dict(row) for row in rows]

    def backup_retention_candidates(self, node_name: str, retention: int) -> list[dict[str, object]]:
        runs = [run for run in self.backup_runs(node_name, 500) if run["status"] == "complete"]
        return runs[max(1, retention):]

    def delete_backup_run(self, run_id: str, node_name: str) -> None:
        with self._lock, self._db() as db:
            db.execute("DELETE FROM backup_parts WHERE run_id = ? AND node_name = ?", (run_id, node_name))
            db.execute("DELETE FROM backup_runs WHERE run_id = ? AND node_name = ?", (run_id, node_name))


def storage_item_dict(item: StorageItem) -> dict[str, object]:
    return asdict(item)
