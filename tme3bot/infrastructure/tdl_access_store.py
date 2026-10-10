from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from tme3bot.domain.models import utc_now

_PROFILE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_PURPOSES = {"tts", "storage"}


class SqliteTdlAccessStore:
    """Persist destination-specific sender checks and per-target rotation state."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @staticmethod
    def destination_fingerprint(destination: str) -> str:
        value = str(destination or "").strip()
        if not value:
            return ""
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def inventory_fingerprint(profiles: list[str] | tuple[str, ...]) -> str:
        normalized = sorted({str(item).strip().lower() for item in profiles if str(item).strip()})
        return hashlib.sha256(
            json.dumps(normalized, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _initialize(self) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS tdl_access_profiles ("
                "worker TEXT NOT NULL, purpose TEXT NOT NULL, destination_hash TEXT NOT NULL, "
                "inventory_hash TEXT NOT NULL, profile TEXT NOT NULL, ready INTEGER NOT NULL, "
                "error_code TEXT, checked_at TEXT NOT NULL, "
                "PRIMARY KEY(worker,purpose,destination_hash,inventory_hash,profile))"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_tdl_access_profiles_lookup "
                "ON tdl_access_profiles(worker,purpose,destination_hash,inventory_hash,ready)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS tdl_access_rotation ("
                "worker TEXT NOT NULL, purpose TEXT NOT NULL, destination_hash TEXT NOT NULL, "
                "inventory_hash TEXT NOT NULL, next_index INTEGER NOT NULL DEFAULT 0, "
                "updated_at TEXT NOT NULL, "
                "PRIMARY KEY(worker,purpose,destination_hash,inventory_hash))"
            )

    @staticmethod
    def _validate(worker: str, purpose: str, destination_hash: str, inventory_hash: str) -> tuple[str, str, str, str]:
        selected_worker = str(worker or "").strip().lower()
        selected_purpose = str(purpose or "").strip().lower()
        destination = str(destination_hash or "").strip().lower()
        inventory = str(inventory_hash or "").strip().lower()
        if not selected_worker or selected_purpose not in _PURPOSES or not re.fullmatch(r"[a-f0-9]{64}", destination) or not re.fullmatch(r"[a-f0-9]{64}", inventory):
            raise ValueError("TDL access verification key is invalid")
        return selected_worker, selected_purpose, destination, inventory

    def replace_results(
        self,
        worker: str,
        purpose: str,
        destination_hash: str,
        inventory_hash: str,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        worker, purpose, destination_hash, inventory_hash = self._validate(
            worker, purpose, destination_hash, inventory_hash
        )
        now = utc_now().isoformat()
        rows: list[tuple[str, int, str | None]] = []
        seen: set[str] = set()
        for item in results:
            if not isinstance(item, dict):
                continue
            profile = str(item.get("profile") or "").strip().lower()
            if not _PROFILE.fullmatch(profile) or profile in seen:
                continue
            seen.add(profile)
            rows.append((profile, int(item.get("ready") is True), _safe_error_code(item.get("error_code"))))
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM tdl_access_profiles WHERE worker=? AND purpose=? AND destination_hash=?",
                (worker, purpose, destination_hash),
            )
            db.executemany(
                "INSERT INTO tdl_access_profiles(worker,purpose,destination_hash,inventory_hash,profile,ready,error_code,checked_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                [
                    (worker, purpose, destination_hash, inventory_hash, profile, ready, code, now)
                    for profile, ready, code in rows
                ],
            )
            db.execute("COMMIT")
        return self.snapshot(worker, purpose, destination_hash, inventory_hash)

    def snapshot(
        self, worker: str, purpose: str, destination_hash: str, inventory_hash: str
    ) -> list[dict[str, Any]]:
        worker, purpose, destination_hash, inventory_hash = self._validate(
            worker, purpose, destination_hash, inventory_hash
        )
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT profile,ready,error_code,checked_at FROM tdl_access_profiles "
                "WHERE worker=? AND purpose=? AND destination_hash=? AND inventory_hash=? ORDER BY profile",
                (worker, purpose, destination_hash, inventory_hash),
            ).fetchall()
        return [
            {
                "profile": str(row["profile"]),
                "ready": bool(row["ready"]),
                "error_code": row["error_code"],
                "checked_at": str(row["checked_at"]),
            }
            for row in rows
        ]

    def verified_profiles(
        self, worker: str, purpose: str, destination_hash: str, inventory_hash: str
    ) -> list[str]:
        return [
            str(item["profile"])
            for item in self.snapshot(worker, purpose, destination_hash, inventory_hash)
            if item["ready"]
        ]

    def choose_next(
        self, worker: str, purpose: str, destination_hash: str, inventory_hash: str
    ) -> str | None:
        worker, purpose, destination_hash, inventory_hash = self._validate(
            worker, purpose, destination_hash, inventory_hash
        )
        now = utc_now().isoformat()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT profile FROM tdl_access_profiles WHERE worker=? AND purpose=? "
                "AND destination_hash=? AND inventory_hash=? AND ready=1 ORDER BY profile",
                (worker, purpose, destination_hash, inventory_hash),
            ).fetchall()
            profiles = [str(row["profile"]) for row in rows]
            if not profiles:
                db.execute("COMMIT")
                return None
            cursor = db.execute(
                "SELECT next_index FROM tdl_access_rotation WHERE worker=? AND purpose=? "
                "AND destination_hash=? AND inventory_hash=?",
                (worker, purpose, destination_hash, inventory_hash),
            ).fetchone()
            index = int(cursor["next_index"] if cursor else 0) % len(profiles)
            selected = profiles[index]
            db.execute(
                "INSERT INTO tdl_access_rotation(worker,purpose,destination_hash,inventory_hash,next_index,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(worker,purpose,destination_hash,inventory_hash) "
                "DO UPDATE SET next_index=excluded.next_index,updated_at=excluded.updated_at",
                (worker, purpose, destination_hash, inventory_hash, (index + 1) % len(profiles), now),
            )
            db.execute("COMMIT")
        return selected


def _safe_error_code(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text if re.fullmatch(r"[A-Z0-9_-]{1,64}", text) else None
