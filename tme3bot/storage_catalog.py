"""Persistent catalog for the shared Telegram storage channel."""

from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
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
    folder_id: int | None = None
    trashed_at: str | None = None
    trashed_by: int | None = None
    caption_sync_status: str = "synced"
    purge_error: str | None = None


@dataclass(frozen=True)
class StorageFolder:
    id: int
    parent_id: int | None
    name: str
    name_key: str
    created_by_user_id: int
    created_at: str
    updated_at: str
    status: str
    trashed_at: str | None
    trashed_by: int | None
    purge_error: str | None


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
                CREATE TABLE IF NOT EXISTS storage_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_id INTEGER REFERENCES storage_folders(id),
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL,
                    created_by_user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    trashed_at TEXT,
                    trashed_by INTEGER,
                    purge_error TEXT
                );
                CREATE TABLE IF NOT EXISTS storage_caption_queue (
                    item_id INTEGER PRIMARY KEY REFERENCES storage_items(id),
                    caption TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(db, "storage_items", "folder_id", "INTEGER")
            self._ensure_column(db, "storage_items", "trashed_at", "TEXT")
            self._ensure_column(db, "storage_items", "trashed_by", "INTEGER")
            self._ensure_column(db, "storage_items", "caption_sync_status", "TEXT NOT NULL DEFAULT 'synced'")
            self._ensure_column(db, "storage_items", "purge_error", "TEXT")
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
            db.execute("CREATE INDEX IF NOT EXISTS idx_storage_folder ON storage_items(folder_id, status)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_storage_folder_parent ON storage_folders(parent_id, status)")
            db.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS uq_storage_folder_active
                   ON storage_folders(COALESCE(parent_id, 0), name_key)
                   WHERE status = 'active'"""
            )
            self._migrate_legacy_folders_locked(db)
            self._dedupe_items_locked(db)
            self._rebuild_fts_locked(db)

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, name: str, definition: str) -> None:
        columns = {str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def _folder_name(name: str) -> str:
        name = " ".join(str(name).split()).strip()
        if (
            not name
            or name in {".", ".."}
            or len(name) > 120
            or "/" in name
            or "\\" in name
            or any(ord(char) < 32 for char in name)
        ):
            raise ValueError("Nama folder tidak valid (maksimal 120 karakter, tanpa slash).")
        return name

    @staticmethod
    def _folder(row: sqlite3.Row | None) -> StorageFolder | None:
        return StorageFolder(**dict(row)) if row is not None else None

    def _ensure_path_locked(
        self, db: sqlite3.Connection, path: str, creator: int, parent_id: int | None = None
    ) -> int | None:
        parts = [part.strip() for part in re.split(r"[\\/]+", str(path)) if part.strip()]
        current = parent_id
        for raw_name in parts:
            name = self._folder_name(raw_name)
            key = name.casefold()
            row = db.execute(
                """SELECT id FROM storage_folders
                   WHERE COALESCE(parent_id, 0)=COALESCE(?, 0)
                     AND name_key=? AND status='active'""",
                (current, key),
            ).fetchone()
            if row is None:
                now = utc_now()
                db.execute(
                    """INSERT INTO storage_folders
                       (parent_id,name,name_key,created_by_user_id,created_at,updated_at,status)
                       VALUES (?,?,?,?,?,?,'active')""",
                    (current, name, key, int(creator), now, now),
                )
                current = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
            else:
                current = int(row["id"])
        return current

    def _migrate_legacy_folders_locked(self, db: sqlite3.Connection) -> None:
        rows = db.execute(
            "SELECT id, owner_user_id, folder FROM storage_items WHERE folder_id IS NULL AND TRIM(folder) != ''"
        ).fetchall()
        for row in rows:
            folder_id = self._ensure_path_locked(
                db, str(row["folder"]), int(row["owner_user_id"])
            )
            db.execute("UPDATE storage_items SET folder_id=? WHERE id=?", (folder_id, row["id"]))

    def _dedupe_items_locked(self, db: sqlite3.Connection) -> None:
        used: dict[tuple[int, str], int] = {}
        rows = db.execute(
            "SELECT id,folder_id,display_name,folder,keywords FROM storage_items WHERE status='active' ORDER BY id"
        ).fetchall()
        for row in rows:
            folder_key = int(row["folder_id"] or 0)
            original = str(row["display_name"])
            key = (folder_key, original.casefold())
            if key not in used:
                used[key] = 1
                continue
            stem, dot, suffix = original.rpartition(".")
            if not dot or not stem:
                stem, suffix = original, ""
            number = used[key] + 1
            candidate = f"{stem} ({number}){'.' + suffix if suffix else ''}"
            while (folder_key, candidate.casefold()) in used:
                number += 1
                candidate = f"{stem} ({number}){'.' + suffix if suffix else ''}"
            used[key] = number
            used[(folder_key, candidate.casefold())] = 1
            caption = build_storage_caption(str(row["folder"]), candidate, str(row["keywords"]))
            db.execute(
                """UPDATE storage_items SET display_name=?,caption=?,
                   caption_sync_status='pending',updated_at=? WHERE id=?""",
                (candidate, caption, utc_now(), row["id"]),
            )
            self._enqueue_caption_locked(db, int(row["id"]), caption)

    def ensure_path(
        self, path: str, creator: int, *, parent_id: int | None = None
    ) -> StorageFolder | None:
        with self._lock, self._db() as db:
            folder_id = self._ensure_path_locked(db, path, creator, parent_id)
            if folder_id is None:
                return None
            return self._folder(db.execute("SELECT * FROM storage_folders WHERE id=?", (folder_id,)).fetchone())

    def folder_path(self, folder_id: int | None) -> str:
        if folder_id is None:
            return ""
        with self._lock, self._db() as db:
            return self._folder_path_locked(db, folder_id)

    def _folder_path_locked(self, db: sqlite3.Connection, folder_id: int | None) -> str:
        names: list[str] = []
        seen: set[int] = set()
        while folder_id is not None:
            if folder_id in seen:
                raise ValueError("Siklus folder terdeteksi.")
            seen.add(folder_id)
            row = db.execute("SELECT id,parent_id,name FROM storage_folders WHERE id=?", (folder_id,)).fetchone()
            if row is None:
                break
            names.append(str(row["name"]))
            folder_id = int(row["parent_id"]) if row["parent_id"] is not None else None
        return "/".join(reversed(names))

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
            folder_id = values.get("folder_id")
            if folder_id is None and values.get("folder"):
                folder_id = self._ensure_path_locked(
                    db, str(values["folder"]), int(values["owner_user_id"])
                )
            values["folder_id"] = folder_id
            values["folder"] = self._folder_path_locked(db, folder_id)
            values["display_name"] = self._unique_item_name_locked(
                db, folder_id, str(values["display_name"])
            )
            values.setdefault("trashed_at", None)
            values.setdefault("trashed_by", None)
            values.setdefault("caption_sync_status", "synced")
            values.setdefault("purge_error", None)
            expected_caption = build_storage_caption(
                values["folder"], values["display_name"], values.get("keywords", "")
            )
            caption_needs_sync = bool(
                values.get("caption") and values.get("caption") != expected_caption
            )
            values["caption"] = expected_caption
            if caption_needs_sync:
                values["caption_sync_status"] = "pending"
            db.execute(
                """INSERT INTO storage_items
                (upload_id, owner_user_id, owner_profile, channel_id, channel_message_id,
                 original_name, display_name, folder, keywords, caption, file_size,
                 mime_type, sha256, uploaded_at, updated_at, status, folder_id,
                 trashed_at, trashed_by, caption_sync_status, purge_error)
                VALUES (:upload_id, :owner_user_id, :owner_profile, :channel_id,
                 :channel_message_id, :original_name, :display_name, :folder, :keywords,
                 :caption, :file_size, :mime_type, :sha256, :uploaded_at, :updated_at,
                 :status, :folder_id, :trashed_at, :trashed_by, :caption_sync_status,
                 :purge_error)""",
                values,
            )
            item_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
            if caption_needs_sync:
                self._enqueue_caption_locked(db, item_id, expected_caption)
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
        display_name = self._unique_item_name(item.folder_id, display_name, exclude_id=item_id)
        caption = build_storage_caption(item.folder, display_name, item.keywords)
        changed = self._admin_update(item_id, {"display_name": display_name, "caption": caption})
        self.enqueue_caption(item_id, caption)
        return changed

    def update_metadata(self, item_id: int, owner_user_id: int, *, folder: str | None = None, keywords: str | None = None) -> StorageItem:
        item = self.get(item_id)
        if item is None:
            raise KeyError("Storage item tidak ditemukan.")
        new_folder = item.folder if folder is None else " ".join(folder.split()).strip()
        new_keywords = item.keywords if keywords is None else " ".join(keywords.split()).strip()
        if folder is not None:
            destination = self.ensure_path(new_folder, owner_user_id)
            item = self.move_items([item_id], destination.id if destination else None)[0]
            new_folder = item.folder
        caption = build_storage_caption(new_folder, item.display_name, new_keywords)
        changed = self._admin_update(
            item_id,
            {"keywords": new_keywords, "caption": caption, "caption_sync_status": "pending"},
        )
        self.enqueue_caption(item_id, caption)
        return changed

    def _admin_update(self, item_id: int, changes: dict[str, object]) -> StorageItem:
        with self._lock, self._db() as db:
            if db.execute("SELECT 1 FROM storage_items WHERE id=?", (item_id,)).fetchone() is None:
                raise KeyError("Storage item tidak ditemukan.")
            changes["updated_at"] = utc_now()
            changes["id"] = item_id
            assignments = ", ".join(f"{key}=:{key}" for key in changes if key != "id")
            db.execute(f"UPDATE storage_items SET {assignments} WHERE id=:id", changes)
            self._sync_fts_locked(db, item_id)
            return self._item(db.execute("SELECT * FROM storage_items WHERE id=?", (item_id,)).fetchone())  # type: ignore[return-value]

    def _unique_item_name(
        self, folder_id: int | None, name: str, *, exclude_id: int | None = None
    ) -> str:
        name = " ".join(str(name).split()).strip()
        if not name:
            raise ValueError("Nama file tidak boleh kosong.")
        with self._lock, self._db() as db:
            return self._unique_item_name_locked(
                db, folder_id, name, exclude_id=exclude_id
            )

    @staticmethod
    def _unique_item_name_locked(
        db: sqlite3.Connection, folder_id: int | None, name: str,
        *, exclude_id: int | None = None,
    ) -> str:
            stem, dot, suffix = name.rpartition(".")
            if not dot or not stem:
                stem, suffix = name, ""
            candidate, number = name, 2
            while db.execute(
                """SELECT 1 FROM storage_items WHERE COALESCE(folder_id,0)=COALESCE(?,0)
                   AND LOWER(display_name)=LOWER(?) AND status='active' AND id != COALESCE(?, -1)""",
                (folder_id, candidate, exclude_id),
            ).fetchone():
                candidate = f"{stem} ({number}){'.' + suffix if suffix else ''}"
                number += 1
            return candidate

    def create_folder(
        self, name: str, creator: int, parent_id: int | None = None
    ) -> StorageFolder:
        name = self._folder_name(name)
        with self._lock, self._db() as db:
            if parent_id is not None:
                parent = db.execute(
                    "SELECT status FROM storage_folders WHERE id=?", (parent_id,)
                ).fetchone()
                if parent is None or parent["status"] != "active":
                    raise KeyError("Folder induk tidak ditemukan.")
            if db.execute(
                """SELECT 1 FROM storage_folders WHERE COALESCE(parent_id,0)=COALESCE(?,0)
                   AND name_key=? AND status='active'""",
                (parent_id, name.casefold()),
            ).fetchone():
                raise ValueError("Nama folder sudah digunakan.")
            now = utc_now()
            db.execute(
                """INSERT INTO storage_folders
                   (parent_id,name,name_key,created_by_user_id,created_at,updated_at,status)
                   VALUES (?,?,?,?,?,?,'active')""",
                (parent_id, name, name.casefold(), int(creator), now, now),
            )
            folder_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
            return self._folder(db.execute("SELECT * FROM storage_folders WHERE id=?", (folder_id,)).fetchone())  # type: ignore[return-value]

    def get_folder(self, folder_id: int, *, include_deleted: bool = False) -> StorageFolder | None:
        with self._lock, self._db() as db:
            folder = self._folder(db.execute("SELECT * FROM storage_folders WHERE id=?", (folder_id,)).fetchone())
            if folder and folder.status == "deleted" and not include_deleted:
                return None
            return folder

    def folder_tree(self, *, include_trash: bool = False) -> list[dict[str, object]]:
        with self._lock, self._db() as db:
            where = "status != 'deleted'" if include_trash else "status='active'"
            rows = db.execute(f"SELECT * FROM storage_folders WHERE {where} ORDER BY name_key").fetchall()
            return [{**dict(row), "path": self._folder_path_locked(db, int(row["id"]))} for row in rows]

    def breadcrumbs(self, folder_id: int | None) -> list[dict[str, object]]:
        if folder_id is None:
            return []
        with self._lock, self._db() as db:
            result: list[dict[str, object]] = []
            current = folder_id
            while current is not None:
                row = db.execute("SELECT id,parent_id,name FROM storage_folders WHERE id=?", (current,)).fetchone()
                if row is None:
                    raise KeyError("Folder tidak ditemukan.")
                result.append({"id": int(row["id"]), "name": str(row["name"])})
                current = int(row["parent_id"]) if row["parent_id"] is not None else None
            return list(reversed(result))

    def _descendants_locked(self, db: sqlite3.Connection, folder_id: int) -> list[int]:
        rows = db.execute(
            """WITH RECURSIVE tree(id) AS (
                 SELECT id FROM storage_folders WHERE id=?
                 UNION ALL SELECT f.id FROM storage_folders f JOIN tree t ON f.parent_id=t.id
               ) SELECT id FROM tree""",
            (folder_id,),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def is_ancestor(self, folder_id: int, possible_descendant: int | None) -> bool:
        if possible_descendant is None:
            return False
        with self._lock, self._db() as db:
            return possible_descendant in self._descendants_locked(db, folder_id)

    def rename_folder(self, folder_id: int, name: str) -> StorageFolder:
        return self.move_folder(folder_id, destination_id=None, name=name, keep_parent=True)

    def move_folder(
        self, folder_id: int, destination_id: int | None, *, name: str | None = None,
        keep_parent: bool = False,
    ) -> StorageFolder:
        with self._lock, self._db() as db:
            row = db.execute("SELECT * FROM storage_folders WHERE id=? AND status='active'", (folder_id,)).fetchone()
            if row is None:
                raise KeyError("Folder tidak ditemukan.")
            parent_id = row["parent_id"] if keep_parent else destination_id
            if parent_id is not None and int(parent_id) in self._descendants_locked(db, folder_id):
                raise ValueError("Folder tidak dapat dipindahkan ke dirinya atau turunannya.")
            new_name = self._folder_name(name if name is not None else str(row["name"]))
            conflict = db.execute(
                """SELECT 1 FROM storage_folders WHERE COALESCE(parent_id,0)=COALESCE(?,0)
                   AND name_key=? AND status='active' AND id != ?""",
                (parent_id, new_name.casefold(), folder_id),
            ).fetchone()
            if conflict:
                raise ValueError("Nama folder sudah digunakan di tujuan.")
            db.execute(
                "UPDATE storage_folders SET parent_id=?,name=?,name_key=?,updated_at=? WHERE id=?",
                (parent_id, new_name, new_name.casefold(), utc_now(), folder_id),
            )
            self._refresh_subtree_locked(db, folder_id)
            return self._folder(db.execute("SELECT * FROM storage_folders WHERE id=?", (folder_id,)).fetchone())  # type: ignore[return-value]

    def _refresh_subtree_locked(self, db: sqlite3.Connection, folder_id: int) -> None:
        for current in self._descendants_locked(db, folder_id):
            path = self._folder_path_locked(db, current)
            items = db.execute("SELECT id,display_name,keywords FROM storage_items WHERE folder_id=?", (current,)).fetchall()
            for item in items:
                caption = build_storage_caption(path, str(item["display_name"]), str(item["keywords"]))
                db.execute(
                    """UPDATE storage_items SET folder=?,caption=?,caption_sync_status='pending',
                       updated_at=? WHERE id=?""",
                    (path, caption, utc_now(), item["id"]),
                )
                self._enqueue_caption_locked(db, int(item["id"]), caption)
                self._sync_fts_locked(db, int(item["id"]))

    def move_items(self, item_ids: list[int], destination_id: int | None) -> list[StorageItem]:
        if destination_id is not None:
            folder = self.get_folder(destination_id)
            if folder is None or folder.status != "active":
                raise KeyError("Folder tujuan tidak ditemukan.")
        result = []
        for item_id in item_ids:
            item = self.get(item_id)
            if item is None:
                continue
            name = self._unique_item_name(destination_id, item.display_name, exclude_id=item_id)
            path = self.folder_path(destination_id)
            caption = build_storage_caption(path, name, item.keywords)
            result.append(self._admin_update(item_id, {
                "folder_id": destination_id, "folder": path, "display_name": name,
                "caption": caption, "caption_sync_status": "pending",
            }))
            self.enqueue_caption(item_id, caption)
        return result

    def trash_items(self, item_ids: list[int], actor: int) -> list[StorageItem]:
        now = utc_now()
        return [self._admin_update(item_id, {"status": "trashed", "trashed_at": now, "trashed_by": actor}) for item_id in item_ids if self.get(item_id)]

    def restore_items(self, item_ids: list[int]) -> list[StorageItem]:
        result = []
        for item_id in item_ids:
            item = self.get(item_id, include_deleted=True)
            if item is None or item.status not in {"trashed", "purge_failed"}:
                continue
            name = self._unique_item_name(item.folder_id, item.display_name, exclude_id=item_id)
            result.append(self._admin_update(item_id, {
                "status": "active", "display_name": name, "trashed_at": None,
                "trashed_by": None, "purge_error": None,
            }))
        return result

    def trash_folders(self, folder_ids: list[int], actor: int) -> list[StorageFolder]:
        now = utc_now()
        with self._lock, self._db() as db:
            affected: list[int] = []
            for folder_id in folder_ids:
                affected.extend(self._descendants_locked(db, folder_id))
            for folder_id in set(affected):
                db.execute(
                    "UPDATE storage_folders SET status='trashed',trashed_at=?,trashed_by=?,updated_at=? WHERE id=?",
                    (now, actor, now, folder_id),
                )
                db.execute(
                    "UPDATE storage_items SET status='trashed',trashed_at=?,trashed_by=?,updated_at=? WHERE folder_id=? AND status!='deleted'",
                    (now, actor, now, folder_id),
                )
            return [self._folder(db.execute("SELECT * FROM storage_folders WHERE id=?", (folder_id,)).fetchone()) for folder_id in folder_ids]  # type: ignore[misc]

    def restore_folders(self, folder_ids: list[int]) -> list[StorageFolder]:
        with self._lock, self._db() as db:
            restored = []
            for folder_id in folder_ids:
                row = db.execute("SELECT * FROM storage_folders WHERE id=?", (folder_id,)).fetchone()
                if row is None:
                    continue
                name = str(row["name"])
                base, number = name, 2
                while db.execute(
                    """SELECT 1 FROM storage_folders WHERE COALESCE(parent_id,0)=COALESCE(?,0)
                       AND name_key=? AND status='active' AND id != ?""",
                    (row["parent_id"], name.casefold(), folder_id),
                ).fetchone():
                    name = f"{base} ({number})"
                    number += 1
                for current in self._descendants_locked(db, folder_id):
                    db.execute(
                        """UPDATE storage_folders SET status='active',trashed_at=NULL,
                           trashed_by=NULL,purge_error=NULL,updated_at=? WHERE id=?""",
                        (utc_now(), current),
                    )
                    db.execute(
                        """UPDATE storage_items SET status='active',trashed_at=NULL,
                           trashed_by=NULL,purge_error=NULL,updated_at=? WHERE folder_id=?""",
                        (utc_now(), current),
                    )
                db.execute("UPDATE storage_folders SET name=?,name_key=? WHERE id=?", (name, name.casefold(), folder_id))
                restored.append(self._folder(db.execute("SELECT * FROM storage_folders WHERE id=?", (folder_id,)).fetchone()))
            return restored  # type: ignore[return-value]

    def browser(
        self, folder_id: int | None, *, scope: str = "current", query: str = "",
        sort: str = "name", order: str = "asc", limit: int = 50, offset: int = 0,
        retention_days: int = 30,
    ) -> dict[str, object]:
        limit, offset = max(1, min(int(limit), 200)), max(0, int(offset))
        sort_column = {"name": "display_name", "updated_at": "updated_at", "size": "file_size", "type": "mime_type"}.get(sort, "display_name")
        direction = "DESC" if order == "desc" else "ASC"
        with self._lock, self._db() as db:
            params: list[object] = []
            status = "trashed" if scope == "trash" else "active"
            clauses = ["status=?"]
            params.append(status)
            if scope == "current":
                clauses.append("COALESCE(folder_id,0)=COALESCE(?,0)")
                params.append(folder_id)
            elif scope == "recent":
                clauses.append("updated_at >= ?")
                params.append((datetime.now(timezone.utc) - timedelta(days=30)).replace(microsecond=0).isoformat())
            if query.strip():
                clauses.append("(LOWER(display_name) LIKE ? OR LOWER(original_name) LIKE ? OR LOWER(keywords) LIKE ?)")
                needle = f"%{query.strip().casefold()}%"
                params.extend([needle, needle, needle])
            where = " AND ".join(clauses)
            total_items = int(db.execute(f"SELECT COUNT(*) FROM storage_items WHERE {where}", params).fetchone()[0])
            rows = db.execute(
                f"SELECT * FROM storage_items WHERE {where} ORDER BY {sort_column} {direction}, id DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            folder_params: list[object] = [status]
            folder_where = "status=?"
            if scope == "current":
                folder_where += " AND COALESCE(parent_id,0)=COALESCE(?,0)"
                folder_params.append(folder_id)
            elif scope not in {"global", "recent", "trash"}:
                folder_where += " AND 0"
            if query.strip():
                folder_where += " AND LOWER(name) LIKE ?"
                folder_params.append(f"%{query.strip().casefold()}%")
            total_folders = int(
                db.execute(
                    f"SELECT COUNT(*) FROM storage_folders WHERE {folder_where}",
                    folder_params,
                ).fetchone()[0]
            )
            folders = db.execute(
                f"SELECT * FROM storage_folders WHERE {folder_where} ORDER BY name_key LIMIT ? OFFSET ?",
                [*folder_params, limit, offset],
            ).fetchall()
            current = None if folder_id is None else db.execute("SELECT * FROM storage_folders WHERE id=?", (folder_id,)).fetchone()
            return {
                "current_folder": dict(current) if current else None,
                "breadcrumbs": self.breadcrumbs(folder_id),
                "folders": [{**dict(row), "path": self._folder_path_locked(db, int(row["id"]))} for row in folders],
                "items": [storage_item_dict(self._item(row), retention_days) for row in rows],
                "total_folders": total_folders,
                "total_items": total_items,
            }

    def _enqueue_caption_locked(self, db: sqlite3.Connection, item_id: int, caption: str) -> None:
        now = utc_now()
        db.execute(
            """INSERT INTO storage_caption_queue(item_id,caption,next_attempt_at,updated_at)
               VALUES (?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET
               caption=excluded.caption,next_attempt_at=excluded.next_attempt_at,
               updated_at=excluded.updated_at""",
            (item_id, caption, now, now),
        )

    def enqueue_caption(self, item_id: int, caption: str) -> None:
        with self._lock, self._db() as db:
            self._enqueue_caption_locked(db, item_id, caption)
            db.execute("UPDATE storage_items SET caption_sync_status='pending' WHERE id=?", (item_id,))

    def pending_captions(self, limit: int = 20) -> list[dict[str, object]]:
        with self._lock, self._db() as db:
            rows = db.execute(
                """SELECT q.*,i.channel_id,i.channel_message_id FROM storage_caption_queue q
                   JOIN storage_items i ON i.id=q.item_id
                   WHERE q.next_attempt_at <= ? ORDER BY q.updated_at LIMIT ?""",
                (utc_now(), limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def finish_caption(self, item_id: int, error: str | None = None) -> None:
        with self._lock, self._db() as db:
            if error is None:
                db.execute("DELETE FROM storage_caption_queue WHERE item_id=?", (item_id,))
                db.execute("UPDATE storage_items SET caption_sync_status='synced' WHERE id=?", (item_id,))
            else:
                row = db.execute("SELECT attempts FROM storage_caption_queue WHERE item_id=?", (item_id,)).fetchone()
                attempts = int(row["attempts"] if row else 0) + 1
                delay = min(3600, 2 ** min(attempts, 10))
                next_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).replace(microsecond=0).isoformat()
                db.execute(
                    """UPDATE storage_caption_queue SET attempts=?,next_attempt_at=?,
                       last_error=?,updated_at=? WHERE item_id=?""",
                    (attempts, next_at, error[:1000], utc_now(), item_id),
                )
                db.execute("UPDATE storage_items SET caption_sync_status='failed' WHERE id=?", (item_id,))

    def due_trash_items(self, retention_days: int) -> list[StorageItem]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))).replace(microsecond=0).isoformat()
        with self._lock, self._db() as db:
            rows = db.execute(
                "SELECT * FROM storage_items WHERE status IN ('trashed','purge_failed') AND trashed_at <= ?",
                (cutoff,),
            ).fetchall()
            return [self._item(row) for row in rows]  # type: ignore[misc]

    def due_trash_folders(self, retention_days: int) -> list[StorageFolder]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))).replace(microsecond=0).isoformat()
        with self._lock, self._db() as db:
            rows = db.execute(
                """SELECT f.* FROM storage_folders f
                   LEFT JOIN storage_folders p ON p.id=f.parent_id
                   WHERE f.status IN ('trashed','purge_failed')
                     AND f.trashed_at <= ?
                     AND (p.id IS NULL OR p.status NOT IN ('trashed','purge_failed'))""",
                (cutoff,),
            ).fetchall()
            return [self._folder(row) for row in rows]  # type: ignore[misc]

    def mark_purged(self, item_id: int, error: str | None = None) -> StorageItem:
        return self._admin_update(item_id, {
            "status": "purge_failed" if error else "deleted",
            "purge_error": error[:1000] if error else None,
        })

    def folder_item_ids(self, folder_ids: list[int]) -> list[int]:
        with self._lock, self._db() as db:
            descendants: set[int] = set()
            for folder_id in folder_ids:
                descendants.update(self._descendants_locked(db, folder_id))
            if not descendants:
                return []
            marks = ",".join("?" for _ in descendants)
            return [
                int(row["id"])
                for row in db.execute(
                    f"SELECT id FROM storage_items WHERE folder_id IN ({marks}) AND status!='deleted'",
                    list(descendants),
                )
            ]

    def mark_folders_purged(self, folder_ids: list[int], error: str | None = None) -> None:
        with self._lock, self._db() as db:
            descendants: set[int] = set()
            for folder_id in folder_ids:
                descendants.update(self._descendants_locked(db, folder_id))
            for folder_id in descendants:
                db.execute(
                    "UPDATE storage_folders SET status=?,purge_error=?,updated_at=? WHERE id=?",
                    ("purge_failed" if error else "deleted", error[:1000] if error else None, utc_now(), folder_id),
                )

    def mark_deleted(self, item_id: int, owner_user_id: int, *, failed: bool = False) -> StorageItem:
        del owner_user_id
        return self._admin_update(item_id, {"status": "delete_failed" if failed else "deleted"})

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


def storage_item_dict(item: StorageItem, retention_days: int = 30) -> dict[str, object]:
    values = asdict(item)
    values["folder_path"] = item.folder
    values["purge_at"] = None
    if item.trashed_at:
        try:
            values["purge_at"] = (
                datetime.fromisoformat(item.trashed_at)
                + timedelta(days=max(1, int(retention_days)))
            ).replace(microsecond=0).isoformat()
        except ValueError:
            pass
    return values
