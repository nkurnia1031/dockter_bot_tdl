from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_WORKER_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
_PROFILE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")
_PHASE_RE = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
_WORKER_STATUSES = {"queued", "running", "succeeded", "failed", "disabled"}
_PROFILE_STATUSES = {"queued", "running", "succeeded", "failed"}
_PROFILE_CHECKS = {"export", "download", "upload", "storage", "tts"}
_CLEANUP_STATUSES = {"not_needed", "succeeded", "failed"}
_RETAINED_SCAN_OPERATIONS = 32


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _load(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        result = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return result if isinstance(result, dict) else {}


class ProfileScanOperationStore:
    """Persist safe, resumable progress for the latest cross-worker profile scan."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS profile_scan_operations (
                    id TEXT PRIMARY KEY,
                    started_by INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    progress_json TEXT NOT NULL,
                    error_code TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS profile_scan_created "
                "ON profile_scan_operations(created_at DESC)"
            )
            rows = db.execute(
                "SELECT id, progress_json FROM profile_scan_operations "
                "WHERE status IN ('queued','running')"
            ).fetchall()
            for row in rows:
                progress = _load(row["progress_json"])
                for worker in progress.get("workers", []):
                    if not isinstance(worker, dict):
                        continue
                    if worker.get("status") in {"queued", "running"}:
                        worker["status"] = "failed"
                        worker["phase"] = "interrupted"
                        worker["error_code"] = "PROFILE_SCAN_INTERRUPTED"
                    for profile in worker.get("profiles", []):
                        if isinstance(profile, dict) and profile.get("status") in {"queued", "running"}:
                            profile["status"] = "failed"
                            profile["phase"] = "interrupted"
                            profile["error_code"] = "PROFILE_SCAN_INTERRUPTED"
                db.execute(
                    "UPDATE profile_scan_operations SET status='failed', progress_json=?, "
                    "error_code='PROFILE_SCAN_INTERRUPTED', updated_at=?, finished_at=? WHERE id=?",
                    (_dump(self._summarize(progress)), _now(), _now(), str(row["id"])),
                )

    @staticmethod
    def _summarize(progress: dict[str, Any]) -> dict[str, Any]:
        workers = progress.get("workers")
        workers = workers if isinstance(workers, list) else []
        completed_workers = sum(
            1 for item in workers
            if isinstance(item, dict) and item.get("status") in {"succeeded", "failed", "disabled"}
        )
        profiles = [
            profile
            for worker in workers if isinstance(worker, dict)
            for profile in worker.get("profiles", []) if isinstance(profile, dict)
        ]
        completed_profiles = sum(
            1 for item in profiles if item.get("status") in {"succeeded", "failed"}
        )
        return {
            "workers": workers,
            "total_workers": len(workers),
            "completed_workers": completed_workers,
            "total_profiles": len(profiles),
            "completed_profiles": completed_profiles,
        }

    @classmethod
    def _public(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "status": str(row["status"]),
            "progress": cls._summarize(_load(row["progress_json"])),
            "error_code": str(row["error_code"] or ""),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "finished_at": str(row["finished_at"] or ""),
        }

    def create(self, started_by: int) -> tuple[dict[str, Any], bool]:
        now = _now()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM profile_scan_operations WHERE status IN ('queued','running') "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            if existing is not None:
                db.commit()
                public = self._public(existing)
                assert public is not None
                return public, False
            operation_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO profile_scan_operations(id,started_by,status,progress_json,created_at,updated_at) "
                "VALUES(?,?,'queued',?,?,?)",
                (operation_id, int(started_by), _dump({"workers": []}), now, now),
            )
            db.execute(
                "DELETE FROM profile_scan_operations WHERE id NOT IN ("
                "SELECT id FROM profile_scan_operations "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?)",
                (_RETAINED_SCAN_OPERATIONS,),
            )
            row = db.execute(
                "SELECT * FROM profile_scan_operations WHERE id=?", (operation_id,)
            ).fetchone()
            db.commit()
            public = self._public(row)
            assert public is not None
            return public, True

    def get(self, operation_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM profile_scan_operations WHERE id=?", (str(operation_id),)
            ).fetchone()
        return self._public(row)

    def latest(self) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM profile_scan_operations ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        return self._public(row)

    def set_status(self, operation_id: str, status: str, *, error_code: str = "") -> None:
        if status not in {"running", "succeeded", "failed"}:
            raise ValueError("Status scan operation tidak valid.")
        safe_code = error_code if _CODE_RE.fullmatch(str(error_code or "")) else ""
        now = _now()
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE profile_scan_operations SET status=?,error_code=?,updated_at=?,finished_at=? WHERE id=?",
                (status, safe_code, now, now if status in {"succeeded", "failed"} else None, str(operation_id)),
            )

    def report_worker(
        self,
        operation_id: str,
        worker_name: str,
        status: str,
        *,
        phase: str = "",
        error_code: str = "",
        profiles: list[str] | None = None,
    ) -> None:
        name = str(worker_name or "").strip().lower()
        if not _WORKER_RE.fullmatch(name) or status not in _WORKER_STATUSES:
            return
        safe_phase = phase if _PHASE_RE.fullmatch(str(phase or "")) else ""
        safe_code = error_code if _CODE_RE.fullmatch(str(error_code or "")) else ""
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT progress_json FROM profile_scan_operations WHERE id=?", (str(operation_id),)
            ).fetchone()
            if row is None:
                db.rollback()
                return
            progress = _load(row["progress_json"])
            workers = progress.get("workers")
            workers = workers if isinstance(workers, list) else []
            current = next(
                (item for item in workers if isinstance(item, dict) and item.get("name") == name),
                None,
            )
            if current is None:
                current = {"name": name, "profiles": []}
                workers.append(current)
            current.update({"status": status, "phase": safe_phase, "error_code": safe_code})
            if profiles is not None:
                safe_profiles = []
                seen: set[str] = set()
                for raw_profile in profiles:
                    profile_name = str(raw_profile or "").strip().lower()
                    if _PROFILE_RE.fullmatch(profile_name) and profile_name not in seen:
                        seen.add(profile_name)
                        safe_profiles.append({
                            "name": profile_name,
                            "status": "queued",
                            "phase": "queued",
                            "error_code": "",
                        })
                current["profiles"] = safe_profiles
            progress["workers"] = workers[:128]
            db.execute(
                "UPDATE profile_scan_operations SET progress_json=?,updated_at=? WHERE id=?",
                (_dump(self._summarize(progress)), _now(), str(operation_id)),
            )
            db.commit()

    def report_profile(
        self,
        operation_id: str,
        worker_name: str,
        profile_name: str,
        status: str,
        *,
        phase: str = "",
        error_code: str = "",
        checks: dict[str, Any] | None = None,
        cleanup: dict[str, Any] | None = None,
    ) -> None:
        worker = str(worker_name or "").strip().lower()
        profile = str(profile_name or "").strip().lower()
        if not _WORKER_RE.fullmatch(worker) or not _PROFILE_RE.fullmatch(profile):
            return
        if status not in _PROFILE_STATUSES:
            return
        safe_phase = phase if _PHASE_RE.fullmatch(str(phase or "")) else ""
        safe_code = error_code if _CODE_RE.fullmatch(str(error_code or "")) else ""
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT progress_json FROM profile_scan_operations WHERE id=?", (str(operation_id),)
            ).fetchone()
            if row is None:
                db.rollback()
                return
            progress = _load(row["progress_json"])
            workers = progress.get("workers")
            workers = workers if isinstance(workers, list) else []
            current_worker = next(
                (item for item in workers if isinstance(item, dict) and item.get("name") == worker),
                None,
            )
            if current_worker is None:
                current_worker = {"name": worker, "status": "running", "profiles": []}
                workers.append(current_worker)
            profiles = current_worker.get("profiles")
            profiles = profiles if isinstance(profiles, list) else []
            current_profile = next(
                (item for item in profiles if isinstance(item, dict) and item.get("name") == profile),
                None,
            )
            if current_profile is None:
                current_profile = {"name": profile}
                profiles.append(current_profile)
            current_profile.update({"status": status, "phase": safe_phase, "error_code": safe_code})
            if checks is not None:
                safe_checks: dict[str, dict[str, Any]] = {}
                for runtime, raw_check in checks.items():
                    if runtime not in _PROFILE_CHECKS or not isinstance(raw_check, dict):
                        continue
                    ready = raw_check.get("ready") is True
                    reason_code = str(raw_check.get("reason_code") or "")
                    safe_checks[runtime] = {
                        "ready": ready,
                        "reason_code": (
                            reason_code if _CODE_RE.fullmatch(reason_code) else ""
                        ),
                    }
                current_profile["checks"] = safe_checks
            if cleanup is not None:
                cleanup_status = str(cleanup.get("status") or "")
                if cleanup_status not in _CLEANUP_STATUSES:
                    cleanup_status = "failed"
                safe_items = []
                for raw_item in cleanup.get("items", [])[:8] if isinstance(cleanup.get("items"), list) else []:
                    if not isinstance(raw_item, dict):
                        continue
                    target = str(raw_item.get("target") or "")
                    status_value = str(raw_item.get("status") or "")
                    message_id = raw_item.get("message_id")
                    if (
                        target not in {"storage", "tts"}
                        or status_value not in {"succeeded", "failed"}
                        or isinstance(message_id, bool)
                        or not isinstance(message_id, int)
                        or message_id <= 0
                    ):
                        continue
                    code = str(raw_item.get("error_code") or "")
                    safe_items.append({
                        "target": target,
                        "message_id": message_id,
                        "status": status_value,
                        "error_code": code if _CODE_RE.fullmatch(code) else "",
                    })
                current_profile["cleanup"] = {
                    "status": cleanup_status,
                    "items": safe_items,
                }
            current_worker["profiles"] = profiles[:256]
            progress["workers"] = workers[:128]
            db.execute(
                "UPDATE profile_scan_operations SET progress_json=?,updated_at=? WHERE id=?",
                (_dump(self._summarize(progress)), _now(), str(operation_id)),
            )
            db.commit()
