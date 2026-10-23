from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from tme3bot.domain.models import utc_now
from tme3bot.tdl_access_fingerprint import (
    normalize_session_fingerprints,
    tdl_access_inventory_fingerprint,
)

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
    def inventory_fingerprint(
        profiles: list[str] | tuple[str, ...],
        session_fingerprints: dict[str, str] | None = None,
    ) -> str:
        return tdl_access_inventory_fingerprint(profiles, session_fingerprints)

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
                "error_code TEXT, checked_at TEXT NOT NULL, session_fingerprint TEXT NOT NULL DEFAULT '', "
                "PRIMARY KEY(worker,purpose,destination_hash,inventory_hash,profile))"
            )
            columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(tdl_access_profiles)").fetchall()
            }
            if "session_fingerprint" not in columns:
                db.execute(
                    "ALTER TABLE tdl_access_profiles ADD COLUMN session_fingerprint TEXT NOT NULL DEFAULT ''"
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
        *,
        session_fingerprints: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        worker, purpose, destination_hash, inventory_hash = self._validate(
            worker, purpose, destination_hash, inventory_hash
        )
        now = utc_now().isoformat()
        rows: list[tuple[str, int, str | None, str]] = []
        seen: set[str] = set()
        fingerprints = normalize_session_fingerprints(session_fingerprints)
        for item in results:
            if not isinstance(item, dict):
                continue
            profile = str(item.get("profile") or "").strip().lower()
            if not _PROFILE.fullmatch(profile) or profile in seen:
                continue
            seen.add(profile)
            rows.append((
                profile,
                int(item.get("ready") is True),
                _safe_error_code(item.get("error_code")),
                fingerprints.get(profile, ""),
            ))
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM tdl_access_profiles WHERE worker=? AND purpose=? AND destination_hash=?",
                (worker, purpose, destination_hash),
            )
            db.executemany(
                "INSERT INTO tdl_access_profiles(worker,purpose,destination_hash,inventory_hash,profile,ready,error_code,checked_at,session_fingerprint) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                [
                    (worker, purpose, destination_hash, inventory_hash, profile, ready, code, now, fingerprint)
                    for profile, ready, code, fingerprint in rows
                ],
            )
            db.execute("COMMIT")
        return self.snapshot(
            worker,
            purpose,
            destination_hash,
            inventory_hash,
            session_fingerprints=session_fingerprints,
        )

    def snapshot(
        self,
        worker: str,
        purpose: str,
        destination_hash: str,
        inventory_hash: str,
        *,
        session_fingerprints: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        worker, purpose, destination_hash, inventory_hash = self._validate(
            worker, purpose, destination_hash, inventory_hash
        )
        with self._lock, self._connect() as db:
            if session_fingerprints is None:
                rows = db.execute(
                    "SELECT profile,ready,error_code,checked_at FROM tdl_access_profiles "
                    "WHERE worker=? AND purpose=? AND destination_hash=? AND inventory_hash=? ORDER BY profile",
                    (worker, purpose, destination_hash, inventory_hash),
                ).fetchall()
            else:
                fingerprints = normalize_session_fingerprints(session_fingerprints)
                rows = db.execute(
                    "SELECT profile,ready,error_code,checked_at,session_fingerprint FROM tdl_access_profiles "
                    "WHERE worker=? AND purpose=? AND destination_hash=? ORDER BY profile,checked_at DESC",
                    (worker, purpose, destination_hash),
                ).fetchall()
                latest: dict[str, sqlite3.Row] = {}
                for row in rows:
                    profile = str(row["profile"])
                    if profile not in latest:
                        latest[profile] = row
                rows = [
                    row for profile, row in latest.items()
                    if fingerprints.get(profile)
                    and str(row["session_fingerprint"] or "") == fingerprints[profile]
                ]
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
        self,
        worker: str,
        purpose: str,
        destination_hash: str,
        inventory_hash: str,
        *,
        session_fingerprints: dict[str, str] | None = None,
    ) -> list[str]:
        return [
            str(item["profile"])
            for item in self.snapshot(
                worker,
                purpose,
                destination_hash,
                inventory_hash,
                session_fingerprints=session_fingerprints,
            )
            if item["ready"]
        ]

    def invalidate_profile(
        self,
        worker: str,
        destination_hash: str,
        profile: str,
        session_fingerprint: str,
        error_code: str,
        *,
        purpose: str = "storage",
    ) -> bool:
        """Invalidate one purpose-scoped proof without affecting other lanes."""
        worker = str(worker or "").strip().lower()
        selected_purpose = str(purpose or "").strip().lower()
        destination = str(destination_hash or "").strip().lower()
        selected_profile = str(profile or "").strip().lower()
        fingerprint = str(session_fingerprint or "").strip().lower()
        code = _safe_error_code(error_code)
        if (
            not worker
            or selected_purpose not in {"storage", "tts"}
            or not re.fullmatch(r"[a-f0-9]{64}", destination)
            or not _PROFILE.fullmatch(selected_profile)
            or not re.fullmatch(r"[a-f0-9]{64}", fingerprint)
            or not code
        ):
            return False
        now = utc_now().isoformat()
        with self._lock, self._connect() as db:
            cursor = db.execute(
                "UPDATE tdl_access_profiles SET ready=0,error_code=?,checked_at=? "
                "WHERE worker=? AND purpose=? AND destination_hash=? "
                "AND profile=? AND session_fingerprint=?",
                (code, now, worker, selected_purpose, destination, selected_profile, fingerprint),
            )
            return cursor.rowcount > 0

    def choose_next(
        self,
        worker: str,
        purpose: str,
        destination_hash: str,
        inventory_hash: str,
        *,
        session_fingerprints: dict[str, str] | None = None,
    ) -> str | None:
        worker, purpose, destination_hash, inventory_hash = self._validate(
            worker, purpose, destination_hash, inventory_hash
        )
        now = utc_now().isoformat()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if session_fingerprints is None:
                rows = db.execute(
                    "SELECT profile FROM tdl_access_profiles WHERE worker=? AND purpose=? "
                    "AND destination_hash=? AND inventory_hash=? AND ready=1 ORDER BY profile",
                    (worker, purpose, destination_hash, inventory_hash),
                ).fetchall()
                profiles = [str(row["profile"]) for row in rows]
            else:
                fingerprints = normalize_session_fingerprints(session_fingerprints)
                rows = db.execute(
                    "SELECT profile,session_fingerprint FROM tdl_access_profiles WHERE worker=? AND purpose=? "
                    "AND destination_hash=? AND ready=1 ORDER BY profile,checked_at DESC",
                    (worker, purpose, destination_hash),
                ).fetchall()
                seen: set[str] = set()
                profiles = []
                for row in rows:
                    profile = str(row["profile"])
                    if profile in seen:
                        continue
                    seen.add(profile)
                    if (
                        fingerprints.get(profile)
                        and str(row["session_fingerprint"] or "") == fingerprints[profile]
                    ):
                        profiles.append(profile)
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
