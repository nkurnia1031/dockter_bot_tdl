from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from tme3bot.infrastructure.secret_store import AesGcmSecretStore


class SqliteDecryptHistoryStore:
    """Store browser-decrypted results encrypted and scoped to their actor."""

    def __init__(self, database: Path, key_path: Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._secrets = AesGcmSecretStore(key_path, require_existing_key=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.database), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            db = self._connect()
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    def _initialize(self) -> None:
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS decrypt_history (
                    id TEXT PRIMARY KEY,
                    actor_user_id INTEGER NOT NULL,
                    result_ciphertext BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS decrypt_history_actor_created
                    ON decrypt_history(actor_user_id, created_at DESC, id DESC);
                """
            )

    @staticmethod
    def _aad(actor_user_id: int, record_id: str) -> bytes:
        return f"decrypt-history:v1:{int(actor_user_id)}:{record_id}".encode("utf-8")

    def add(self, actor_user_id: int, result: str) -> dict[str, Any]:
        actor_id = int(actor_user_id)
        if actor_id <= 0:
            raise ValueError("ID pengguna dekripsi tidak valid.")
        value = str(result)
        if not value or len(value) > 65536:
            raise ValueError("Hasil dekripsi kosong atau terlalu panjang.")
        record_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        ciphertext = self._secrets.encrypt(value, self._aad(actor_id, record_id))
        with self._db() as db:
            db.execute(
                "INSERT INTO decrypt_history(id,actor_user_id,result_ciphertext,created_at) VALUES(?,?,?,?)",
                (record_id, actor_id, ciphertext, created_at),
            )
        return {"id": record_id, "result": value, "created_at": created_at}

    def list_for_actor(
        self, actor_user_id: int, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        actor_id = int(actor_user_id)
        if actor_id <= 0 or not 1 <= int(limit) <= 100 or int(offset) < 0:
            raise ValueError("Filter riwayat dekripsi tidak valid.")
        with self._db() as db:
            rows = db.execute(
                "SELECT id,actor_user_id,result_ciphertext,created_at FROM decrypt_history "
                "WHERE actor_user_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                (actor_id, int(limit), int(offset)),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "result": self._secrets.decrypt(
                    bytes(row["result_ciphertext"]),
                    self._aad(actor_id, str(row["id"])),
                ),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def count_for_actor(self, actor_user_id: int) -> int:
        actor_id = int(actor_user_id)
        if actor_id <= 0:
            raise ValueError("ID pengguna dekripsi tidak valid.")
        with self._db() as db:
            row = db.execute(
                "SELECT COUNT(*) AS total FROM decrypt_history WHERE actor_user_id=?",
                (actor_id,),
            ).fetchone()
        return int(row["total"] if row else 0)
