from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from tme3bot.chat_refs import canonical_chat_key
from tme3bot.names import normalize_profile_name
from tme3bot.persistence import utc_now_iso
from tme3bot.state import SourceState, StateSnapshot, normalize_chat_ref


class SourceRevisionConflict(RuntimeError):
    """A source write was based on an outdated revision."""

    def __init__(self, expected_revision: int, current_revision: int) -> None:
        super().__init__("Source revision conflict.")
        self.expected_revision = int(expected_revision)
        self.current_revision = int(current_revision)

    def details(self) -> dict[str, int]:
        return {
            "expected_revision": self.expected_revision,
            "current_revision": self.current_revision,
        }


class MigrationPlanConflict(RuntimeError):
    """A migration plan or one of its optimistic revision checks is stale."""


class SqliteSourceRepository:
    """Backend-owned, profile-scoped source state in the application database."""

    FEATURE_KEY = "backend_source_state"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        db = self._connect()
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_records (
                    profile TEXT NOT NULL,
                    canonical_chat_key TEXT NOT NULL,
                    last_id INTEGER NOT NULL,
                    label TEXT,
                    updated_at TEXT NOT NULL,
                    warmup_url TEXT,
                    warmup_done INTEGER NOT NULL DEFAULT 0,
                    warmup_done_at TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    peer_type TEXT,
                    peer_id TEXT,
                    PRIMARY KEY (profile, canonical_chat_key)
                );
                CREATE INDEX IF NOT EXISTS source_records_peer
                    ON source_records(profile, peer_type, peer_id);
                CREATE TABLE IF NOT EXISTS source_repository_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_migration_ledger (
                    migration_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    canonical_chat_key TEXT NOT NULL,
                    plan_sha256 TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    backup_sha256 TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    status TEXT NOT NULL,
                    cursor_before INTEGER,
                    cursor_after INTEGER,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (migration_id, profile, canonical_chat_key)
                );
                CREATE TABLE IF NOT EXISTS source_migration_runs (
                    migration_id TEXT PRIMARY KEY,
                    plan_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            db.commit()
        finally:
            db.close()

    @staticmethod
    def export_database_snapshot(path: Path) -> dict[str, object]:
        """Read source rows and migration ledger without opening unrelated tables."""
        database = Path(path)
        if not database.is_file():
            return {"version": 1, "sources": [], "ledger": [], "runs": []}
        uri = database.resolve().as_uri() + "?mode=ro"
        db = sqlite3.connect(uri, uri=True, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            tables = {
                str(row[0])
                for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            sources: list[dict[str, object]] = []
            if "source_records" in tables:
                columns = {str(row[1]) for row in db.execute("PRAGMA table_info(source_records)")}
                required = {"profile", "canonical_chat_key", "last_id"}
                if required.issubset(columns):
                    selected = [
                        name for name in (
                            "profile", "canonical_chat_key", "last_id", "label",
                            "updated_at", "warmup_url", "warmup_done", "warmup_done_at",
                            "revision", "peer_type", "peer_id",
                        ) if name in columns
                    ]
                    for row in db.execute(
                        "SELECT " + ",".join(selected) + " FROM source_records "
                        "ORDER BY profile, canonical_chat_key"
                    ):
                        sources.append({key: row[key] for key in selected})
            ledger: list[dict[str, object]] = []
            if "source_migration_ledger" in tables:
                columns = {str(row[1]) for row in db.execute("PRAGMA table_info(source_migration_ledger)")}
                selected = [
                    name for name in (
                        "migration_id", "profile", "canonical_chat_key", "plan_sha256",
                        "input_sha256", "backup_sha256", "decision", "status",
                        "cursor_before", "cursor_after", "created_at",
                    ) if name in columns
                ]
                if selected:
                    for row in db.execute(
                        "SELECT " + ",".join(selected) + " FROM source_migration_ledger "
                        "ORDER BY migration_id, profile, canonical_chat_key"
                    ):
                        ledger.append({key: row[key] for key in selected})
            runs: list[dict[str, object]] = []
            if "source_migration_runs" in tables:
                for row in db.execute(
                    "SELECT migration_id, plan_sha256, created_at FROM source_migration_runs ORDER BY migration_id"
                ):
                    runs.append({key: row[key] for key in ("migration_id", "plan_sha256", "created_at")})
            return {"version": 1, "sources": sources, "ledger": ledger, "runs": runs}
        finally:
            db.close()

    def apply_migration_plan(
        self,
        *,
        migration_id: str,
        plan_sha256: str,
        backup_sha256: str,
        rows: list[dict[str, object]],
    ) -> bool:
        """Apply approved sources and ledger decisions atomically; return replay status."""
        if not migration_id.strip() or not plan_sha256.strip() or not backup_sha256.strip():
            raise ValueError("Identitas migrasi dan checksum wajib diisi.")
        now = utc_now_iso()
        input_sha256 = str(rows[0].get("input_sha256") or "") if rows else ""
        with self._transaction(write=True) as db:
            previous = db.execute(
                "SELECT plan_sha256 FROM source_migration_runs WHERE migration_id=?",
                (migration_id,),
            ).fetchone()
            if previous is not None:
                if str(previous["plan_sha256"]) != plan_sha256:
                    raise MigrationPlanConflict("Migration ID sudah dipakai oleh plan berbeda.")
                return True

            for item in rows:
                profile = self._profile(str(item["profile"]))
                chat_key = self._chat_key(str(item["chat_ref"]))
                current = db.execute(
                    "SELECT * FROM source_records WHERE profile=? AND canonical_chat_key=?",
                    (profile, chat_key),
                ).fetchone()
                current_revision = int(current["revision"]) if current else 0
                expected_revision = int(item["expected_revision"])
                if current_revision != expected_revision:
                    raise SourceRevisionConflict(expected_revision, current_revision)

            db.execute(
                "INSERT INTO source_migration_runs(migration_id, plan_sha256, created_at) VALUES (?, ?, ?)",
                (migration_id, plan_sha256, now),
            )
            blocked = False
            for item in rows:
                profile = self._profile(str(item["profile"]))
                chat_key = self._chat_key(str(item["chat_ref"]))
                decision = str(item["decision"])
                status = str(item["status"])
                before = item.get("cursor_before")
                after = item.get("cursor_after")
                blocked = blocked or status != "approved"
                if status == "approved":
                    source = SourceState(
                        last_id=int(after or 0),
                        label=item.get("label") if item.get("label") is None else str(item.get("label")),
                        updated_at=str(item.get("updated_at") or now),
                        warmup_url=(str(item["warmup_url"]) if item.get("warmup_url") is not None else None),
                        warmup_done=bool(item.get("warmup_done", True)),
                        warmup_done_at=(str(item["warmup_done_at"]) if item.get("warmup_done_at") is not None else None),
                    )
                    current = db.execute(
                        "SELECT * FROM source_records WHERE profile=? AND canonical_chat_key=?",
                        (profile, chat_key),
                    ).fetchone()
                    revision = int(current["revision"]) + 1 if current else 1
                    peer_type = current["peer_type"] if current else None
                    peer_id = current["peer_id"] if current else None
                    db.execute(
                        """INSERT INTO source_records (
                               profile, canonical_chat_key, last_id, label, updated_at,
                               warmup_url, warmup_done, warmup_done_at, revision, peer_type, peer_id
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(profile, canonical_chat_key) DO UPDATE SET
                               last_id=excluded.last_id, label=excluded.label,
                               updated_at=excluded.updated_at, warmup_url=excluded.warmup_url,
                               warmup_done=excluded.warmup_done,
                               warmup_done_at=excluded.warmup_done_at,
                               revision=excluded.revision, peer_type=excluded.peer_type,
                               peer_id=excluded.peer_id""",
                        self._record_values(profile, chat_key, source, revision, peer_type, peer_id),
                    )
                db.execute(
                    """INSERT INTO source_migration_ledger (
                           migration_id, profile, canonical_chat_key, plan_sha256,
                           input_sha256, backup_sha256, decision, status,
                           cursor_before, cursor_after, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        migration_id, profile, chat_key, plan_sha256,
                        str(item.get("input_sha256") or input_sha256), backup_sha256,
                        decision, status,
                        int(before) if before is not None else None,
                        int(after) if after is not None else None,
                        now,
                    ),
                )
            gate_value = "disabled" if blocked else "enabled"
            db.execute(
                """INSERT INTO source_repository_metadata(key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (self.FEATURE_KEY, gate_value, now),
            )
            for item in rows:
                if str(item["status"]) != "approved":
                    continue
                profile = self._profile(str(item["profile"]))
                chat_key = self._chat_key(str(item["chat_ref"]))
                saved = db.execute(
                    "SELECT last_id, label, warmup_url, warmup_done, warmup_done_at "
                    "FROM source_records WHERE profile=? AND canonical_chat_key=?",
                    (profile, chat_key),
                ).fetchone()
                expected_label = str(item["label"]) if item.get("label") is not None else None
                expected_warmup_url = str(item["warmup_url"]) if item.get("warmup_url") is not None else None
                expected_warmup_at = str(item["warmup_done_at"]) if item.get("warmup_done_at") is not None else None
                if (
                    saved is None
                    or int(saved["last_id"]) < int(item.get("cursor_after") or 0)
                    or saved["label"] != expected_label
                    or saved["warmup_url"] != expected_warmup_url
                    or bool(saved["warmup_done"]) != bool(item.get("warmup_done", True))
                    or saved["warmup_done_at"] != expected_warmup_at
                ):
                    raise MigrationPlanConflict("Verifikasi cursor hasil migrasi gagal.")
        return False

    @staticmethod
    def _profile(profile: str) -> str:
        normalized = normalize_profile_name(profile)
        if not normalized:
            raise ValueError("Nama profile tidak valid.")
        return normalized

    @staticmethod
    def _chat_key(chat_ref: str) -> str:
        key = canonical_chat_key(chat_ref)
        if not key:
            raise ValueError("chat_ref tidak boleh kosong.")
        return key

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> SourceState:
        return SourceState(
            last_id=int(row["last_id"]),
            label=row["label"],
            updated_at=str(row["updated_at"]),
            warmup_url=row["warmup_url"],
            warmup_done=bool(row["warmup_done"]),
            warmup_done_at=row["warmup_done_at"],
            revision=int(row["revision"]),
        )

    @staticmethod
    def _record_values(
        profile: str,
        chat_key: str,
        source: SourceState,
        revision: int,
        peer_type: str | None,
        peer_id: str | None,
    ) -> tuple[object, ...]:
        return (
            profile,
            chat_key,
            int(source.last_id),
            source.label,
            source.updated_at or utc_now_iso(),
            source.warmup_url,
            int(bool(source.warmup_done)),
            source.warmup_done_at,
            int(revision),
            peer_type,
            peer_id,
        )

    def is_enabled(self) -> bool:
        with self._transaction() as db:
            row = db.execute(
                "SELECT value FROM source_repository_metadata WHERE key=?",
                (self.FEATURE_KEY,),
            ).fetchone()
        return bool(row and row["value"] == "enabled")

    def set_enabled(self, enabled: bool) -> None:
        value = "enabled" if enabled else "disabled"
        with self._transaction(write=True) as db:
            db.execute(
                """INSERT INTO source_repository_metadata(key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value=excluded.value, updated_at=excluded.updated_at""",
                (self.FEATURE_KEY, value, utc_now_iso()),
            )

    def get_source(self, profile: str, chat_ref: str) -> SourceState | None:
        profile_key = self._profile(profile)
        chat_key = self._chat_key(chat_ref)
        with self._transaction() as db:
            row = db.execute(
                "SELECT * FROM source_records WHERE profile=? AND canonical_chat_key=?",
                (profile_key, chat_key),
            ).fetchone()
        return self._source_from_row(row) if row is not None else None

    def list_sources(self, profile: str) -> list[tuple[str, SourceState]]:
        profile_key = self._profile(profile)
        with self._transaction() as db:
            rows = db.execute(
                "SELECT * FROM source_records WHERE profile=? ORDER BY canonical_chat_key",
                (profile_key,),
            ).fetchall()
        return [
            (str(row["canonical_chat_key"]), self._source_from_row(row))
            for row in rows
        ]

    def upsert_source(
        self,
        profile: str,
        chat_ref: str,
        label: str | None,
        last_id: int,
        warmup_url: str | None = None,
        warmup_done: bool | None = None,
    ) -> SourceState:
        profile_key = self._profile(profile)
        chat_key = self._chat_key(chat_ref)
        now = utc_now_iso()
        with self._transaction(write=True) as db:
            current = db.execute(
                "SELECT * FROM source_records WHERE profile=? AND canonical_chat_key=?",
                (profile_key, chat_key),
            ).fetchone()
            current_source = self._source_from_row(current) if current else None
            next_label = label if label is not None else (current_source.label if current_source else None)
            next_warmup_url = (
                current_source.warmup_url
                if current_source and current_source.warmup_url
                else warmup_url
            )
            next_warmup_done = current_source.warmup_done if current_source else True
            next_warmup_done_at = current_source.warmup_done_at if current_source else None
            if warmup_done is not None:
                next_warmup_done = bool(warmup_done)
                next_warmup_done_at = now if warmup_done else None

            source = SourceState(
                last_id=max(int(last_id), current_source.last_id if current_source else int(last_id)),
                label=next_label,
                updated_at=now,
                warmup_url=next_warmup_url,
                warmup_done=next_warmup_done,
                warmup_done_at=next_warmup_done_at,
            )
            revision = (current_source.revision if current_source else 0) + 1
            peer_type = current["peer_type"] if current else None
            peer_id = current["peer_id"] if current else None
            db.execute(
                """INSERT INTO source_records (
                       profile, canonical_chat_key, last_id, label, updated_at,
                       warmup_url, warmup_done, warmup_done_at, revision, peer_type, peer_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(profile, canonical_chat_key) DO UPDATE SET
                       last_id=excluded.last_id, label=excluded.label,
                       updated_at=excluded.updated_at, warmup_url=excluded.warmup_url,
                       warmup_done=excluded.warmup_done,
                       warmup_done_at=excluded.warmup_done_at,
                       revision=excluded.revision, peer_type=excluded.peer_type,
                       peer_id=excluded.peer_id""",
                self._record_values(profile_key, chat_key, source, revision, peer_type, peer_id),
            )
            source.revision = revision
        return source

    def commit_source(
        self,
        profile: str,
        chat_ref: str,
        source: SourceState,
        *,
        expected_revision: int,
        peer_type: str | None = None,
        peer_id: str | None = None,
    ) -> SourceState:
        profile_key = self._profile(profile)
        chat_key = self._chat_key(chat_ref)
        with self._transaction(write=True) as db:
            current = db.execute(
                "SELECT * FROM source_records WHERE profile=? AND canonical_chat_key=?",
                (profile_key, chat_key),
            ).fetchone()
            current_revision = int(current["revision"]) if current else 0
            if int(expected_revision) != current_revision:
                raise SourceRevisionConflict(int(expected_revision), current_revision)

            saved = SourceState(
                last_id=max(int(source.last_id), int(current["last_id"]) if current else int(source.last_id)),
                label=source.label,
                updated_at=utc_now_iso(),
                warmup_url=source.warmup_url,
                warmup_done=bool(source.warmup_done),
                warmup_done_at=source.warmup_done_at,
            )
            revision = current_revision + 1
            selected_peer_type = peer_type if peer_type is not None else (current["peer_type"] if current else None)
            selected_peer_id = peer_id if peer_id is not None else (current["peer_id"] if current else None)
            db.execute(
                """INSERT INTO source_records (
                       profile, canonical_chat_key, last_id, label, updated_at,
                       warmup_url, warmup_done, warmup_done_at, revision, peer_type, peer_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(profile, canonical_chat_key) DO UPDATE SET
                       last_id=excluded.last_id, label=excluded.label,
                       updated_at=excluded.updated_at, warmup_url=excluded.warmup_url,
                       warmup_done=excluded.warmup_done,
                       warmup_done_at=excluded.warmup_done_at,
                       revision=excluded.revision, peer_type=excluded.peer_type,
                       peer_id=excluded.peer_id""",
                self._record_values(
                    profile_key,
                    chat_key,
                    saved,
                    revision,
                    selected_peer_type,
                    selected_peer_id,
                ),
            )
            saved.revision = revision
        return saved

    def mark_warmup_done(self, profile: str, chat_ref: str) -> None:
        profile_key = self._profile(profile)
        chat_key = self._chat_key(chat_ref)
        now = utc_now_iso()
        with self._transaction(write=True) as db:
            db.execute(
                """UPDATE source_records
                   SET warmup_done=1, warmup_done_at=?, updated_at=?, revision=revision+1
                   WHERE profile=? AND canonical_chat_key=?""",
                (now, now, profile_key, chat_key),
            )

    def delete_sources(self, profile: str, chat_refs: Iterable[str]) -> list[str]:
        profile_key = self._profile(profile)
        keys = sorted(
            {
                key
                for item in chat_refs
                if (key := normalize_chat_ref(str(item)))
            }
        )
        if not keys:
            return []
        deleted: list[str] = []
        with self._transaction(write=True) as db:
            for start in range(0, len(keys), 500):
                batch = keys[start : start + 500]
                placeholders = ",".join("?" for _ in batch)
                params = [profile_key, *batch]
                rows = db.execute(
                    f"SELECT canonical_chat_key FROM source_records WHERE profile=? AND canonical_chat_key IN ({placeholders})",
                    params,
                ).fetchall()
                deleted.extend(str(row["canonical_chat_key"]) for row in rows)
                db.execute(
                    f"DELETE FROM source_records WHERE profile=? AND canonical_chat_key IN ({placeholders})",
                    params,
                )
        return sorted(deleted)


class SqliteProfileStateStore:
    """StateStore-compatible adapter that binds the shared repository to a profile."""

    def __init__(self, repository: SqliteSourceRepository, profile: str) -> None:
        self.repository = repository
        self.profile = repository._profile(profile)

    def load(self) -> StateSnapshot:
        return StateSnapshot(
            sources={key: source for key, source in self.list_sources()},
            migration={"backend_source_state": True, "skipped_keys": []},
        )

    def get_source(self, chat_ref: str) -> SourceState | None:
        return self.repository.get_source(self.profile, chat_ref)

    def list_sources(self) -> list[tuple[str, SourceState]]:
        return self.repository.list_sources(self.profile)

    def upsert_source(
        self,
        chat_ref: str,
        label: str | None,
        last_id: int,
        warmup_url: str | None = None,
        warmup_done: bool | None = None,
    ) -> SourceState:
        return self.repository.upsert_source(
            self.profile, chat_ref, label, last_id, warmup_url, warmup_done
        )

    def commit_source(
        self,
        chat_ref: str,
        source: SourceState,
        *,
        expected_revision: int,
        peer_type: str | None = None,
        peer_id: str | None = None,
    ) -> SourceState:
        return self.repository.commit_source(
            self.profile,
            chat_ref,
            source,
            expected_revision=expected_revision,
            peer_type=peer_type,
            peer_id=peer_id,
        )

    def mark_warmup_done(self, chat_ref: str) -> None:
        self.repository.mark_warmup_done(self.profile, chat_ref)

    def delete_source(self, chat_ref: str) -> bool:
        return bool(self.delete_sources([chat_ref]))

    def delete_sources(self, chat_refs: Iterable[str]) -> list[str]:
        return self.repository.delete_sources(self.profile, chat_refs)
