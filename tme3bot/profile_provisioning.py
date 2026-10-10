from __future__ import annotations

import io
import hashlib
import json
import os
import re
import sqlite3
import stat
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tme3bot.domain.operations import OperationStatus
from tme3bot.names import normalize_profile_name


MAX_SESSION_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_PROFILE_BUNDLE_BYTES = 300 * 1024 * 1024
_PROFILE_LOGIN_TTL_SECONDS = 15 * 60
_PHONE_RE = re.compile(r"^[+0-9(). -]{4,32}$")


def profile_transfer_is_secure(worker_url: str) -> bool:
    """Allow HTTPS remote workers and explicit internal Compose service hosts."""
    try:
        parsed = urlsplit(str(worker_url))
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return False
        return parsed.scheme == "https" or (
            parsed.scheme == "http"
            and parsed.hostname
            in {"worker-local", "resolver", "local", "localhost", "127.0.0.1", "::1"}
        )
    except ValueError:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_zip_entries(
    data: bytes, max_bytes: int = MAX_SESSION_ARCHIVE_BYTES
) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    if not data or len(data) > max_bytes:
        raise ValueError("Ukuran ZIP sesi kosong atau melebihi batas.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("File sesi harus berupa ZIP yang valid.") from exc
    if len(infos) > 10_000:
        raise ValueError("ZIP sesi memiliki terlalu banyak file.")
    total = 0
    normalized: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
    seen: set[tuple[str, ...]] = set()
    for info in infos:
        path = PurePosixPath(info.filename.replace("\\", "/"))
        parts = tuple(part for part in path.parts if part not in {"", "."})
        mode = info.external_attr >> 16
        if (
            path.is_absolute()
            or not parts
            or any(part == ".." for part in parts)
            or stat.S_ISLNK(mode)
        ):
            raise ValueError("ZIP sesi berisi path yang tidak aman.")
        if any(len(part.encode("utf-8")) > 255 for part in parts) or len(
            "/".join(parts).encode("utf-8")
        ) > 1024:
            raise ValueError("ZIP sesi memiliki nama file terlalu panjang.")
        if parts in seen:
            raise ValueError("ZIP sesi berisi nama file duplikat.")
        seen.add(parts)
        if info.flag_bits & 0x1:
            raise ValueError("ZIP sesi terenkripsi tidak didukung.")
        total += int(info.file_size)
        if info.file_size < 0 or total > max_bytes:
            raise ValueError("Ukuran isi ZIP sesi melebihi batas.")
        normalized.append((info, parts))
    return normalized


def extract_single_session(data: bytes) -> dict[str, bytes]:
    """Read a ZIP containing exactly one top-level .tdl directory."""
    entries = _safe_zip_entries(data)
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info, parts in entries:
            if info.is_dir():
                continue
            if len(parts) < 2 or parts[0] != ".tdl":
                raise ValueError("ZIP harus berisi satu folder .tdl/ pada root.")
            relative = "/".join(parts[1:])
            files[relative] = archive.read(info)
    if not any(name.startswith("data/") and payload for name, payload in files.items()):
        raise ValueError("Folder .tdl tidak berisi database sesi TDL.")
    return files


def build_profile_bundle(single_session: dict[str, bytes], telegram_user_id: int) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for root in ("root/.tdl", "user1/.tdl"):
            for name, data in single_session.items():
                archive.writestr(f"{root}/{name}", data)
        archive.writestr(
            "identity.json",
            json.dumps(
                {
                    "telegram_user_id": int(telegram_user_id),
                    "tdl_user_id": int(telegram_user_id),
                },
                separators=(",", ":"),
            ),
        )
    return output.getvalue()


def validate_profile_bundle(data: bytes) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    entries = _safe_zip_entries(data, MAX_PROFILE_BUNDLE_BYTES)
    found = {"root/.tdl": False, "user1/.tdl": False}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info, parts in entries:
            path = "/".join(parts)
            for root in found:
                if path.startswith(root + "/") and not info.is_dir():
                    found[root] = True
            if path not in {"identity.json", "root", "user1", "root/.tdl", "user1/.tdl"} and not (
                path.startswith("root/.tdl/") or path.startswith("user1/.tdl/")
            ):
                raise ValueError("Bundle profil memiliki struktur yang tidak dikenal.")
    if not all(found.values()):
        raise ValueError("Bundle harus memiliki sesi root/.tdl dan user1/.tdl.")
    return entries


def profile_bundle_identity(data: bytes) -> int:
    """Read the Telegram identity embedded in a validated bundle."""
    validate_profile_bundle(data)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            identity = json.loads(archive.read("identity.json").decode("utf-8"))
        if not isinstance(identity, dict):
            raise TypeError("Identity bundle harus berupa object.")
        return int(identity.get("telegram_user_id", identity.get("tdl_user_id")))
    except (KeyError, ValueError, TypeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise ValueError("Identity bundle profil tidak valid.") from exc


class ProfileProvisioningStore:
    """Persistent encrypted session vault and profile distribution state."""

    def __init__(self, database: Path, vault_root: Path) -> None:
        self.database = Path(database)
        self.vault_root = Path(vault_root)
        self.key_path = self.vault_root / "vault.key"
        self.vault_root.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(self.vault_root, 0o700)
        self._lock = threading.RLock()
        self._key = self._load_or_create_key()
        self._initialize()

    def _load_or_create_key(self) -> bytes:
        try:
            key = self.key_path.read_bytes()
            if len(key) != 32:
                raise RuntimeError("Kunci profile vault tidak valid.")
            if os.name == "posix":
                os.chmod(self.key_path, 0o600)
            return key
        except FileNotFoundError:
            if self.database.exists():
                db = None
                try:
                    db = sqlite3.connect(self.database)
                    present = db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile_sessions'"
                    ).fetchone()
                    if present and db.execute("SELECT 1 FROM profile_sessions LIMIT 1").fetchone():
                        raise RuntimeError("Kunci profile vault hilang; data sesi terenkripsi tidak dapat dibuka.")
                except sqlite3.Error:
                    pass
                finally:
                    if db is not None:
                        db.close()
            key = AESGCM.generate_key(bit_length=256)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            try:
                fd = os.open(str(self.key_path), flags, 0o600)
            except FileExistsError:
                for _ in range(50):
                    try:
                        key = self.key_path.read_bytes()
                    except FileNotFoundError:
                        key = b""
                    if len(key) == 32:
                        if os.name == "posix":
                            os.chmod(self.key_path, 0o600)
                        return key
                    time.sleep(0.01)
                raise RuntimeError("Kunci profile vault tidak valid.")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(key)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                self.key_path.unlink(missing_ok=True)
                raise
            return key

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS profile_sessions (
                    profile TEXT PRIMARY KEY,
                    telegram_user_id INTEGER NOT NULL,
                    encrypted_bundle BLOB NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    desired_revision INTEGER NOT NULL DEFAULT 0,
                    format_version INTEGER NOT NULL DEFAULT 1,
                    bundle_sha256 TEXT,
                    source_worker TEXT
                );
                CREATE TABLE IF NOT EXISTS profile_session_revisions (
                    profile TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    format_version INTEGER NOT NULL,
                    bundle_sha256 TEXT NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    source_worker TEXT,
                    encrypted_bundle BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(profile, revision)
                );
                CREATE TABLE IF NOT EXISTS profile_provisionings (
                    id TEXT PRIMARY KEY,
                    profile TEXT NOT NULL,
                    actor_user_id INTEGER NOT NULL,
                    bootstrap_worker TEXT NOT NULL,
                    source TEXT NOT NULL,
                    method TEXT,
                    status TEXT NOT NULL,
                    telegram_user_id INTEGER,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profile_distributions (
                    profile TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provisioning_id TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL,
                    desired_revision INTEGER,
                    installed_revision INTEGER,
                    installed_sha256 TEXT,
                    installed_telegram_user_id INTEGER,
                    sync_requested INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(profile, worker)
                );
                CREATE TABLE IF NOT EXISTS profile_sync_requests (
                    operation_id TEXT PRIMARY KEY,
                    actor_user_id INTEGER NOT NULL,
                    profile TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    desired_revision INTEGER NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'check',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_profile_sync_requests_target
                    ON profile_sync_requests(profile, worker, desired_revision, status);
                CREATE TABLE IF NOT EXISTS profile_legacy_candidates (
                    profile TEXT NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    source_worker TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    PRIMARY KEY(profile, telegram_user_id, source_worker)
                );
                CREATE TABLE IF NOT EXISTS profile_diagnostic_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    actor_user_id INTEGER NOT NULL,
                    operation_id TEXT,
                    profile TEXT,
                    worker TEXT,
                    event_type TEXT NOT NULL,
                    code TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_profile_diagnostic_logs_actor_category
                    ON profile_diagnostic_logs(actor_user_id,category,id DESC);
                CREATE INDEX IF NOT EXISTS idx_profile_diagnostic_logs_operation
                    ON profile_diagnostic_logs(operation_id,id);
                CREATE TABLE IF NOT EXISTS profile_sync_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    sequence INTEGER,
                    revision INTEGER,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    code TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_profile_sync_logs_target
                    ON profile_sync_logs(profile,worker,id DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_profile_sync_logs_event
                    ON profile_sync_logs(worker,run_id,sequence)
                    WHERE sequence IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_profile_sync_logs_server_event
                    ON profile_sync_logs(worker,run_id,phase,status,code)
                    WHERE sequence IS NULL;
                CREATE INDEX IF NOT EXISTS idx_profile_provisionings_status
                    ON profile_provisionings(status, updated_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_profile_sessions_user_id
                    ON profile_sessions(telegram_user_id);
                DROP INDEX IF EXISTS idx_profile_provisionings_pending;
                CREATE UNIQUE INDEX idx_profile_provisionings_pending
                    ON profile_provisionings(profile)
                    WHERE status IN ('authenticating','validating','distributing');
                """
            )
            self._ensure_columns(
                db,
                "profile_sessions",
                {
                    "desired_revision": "INTEGER NOT NULL DEFAULT 0",
                    "format_version": "INTEGER NOT NULL DEFAULT 1",
                    "bundle_sha256": "TEXT",
                    "source_worker": "TEXT",
                },
            )
            self._ensure_columns(
                db,
                "profile_distributions",
                {
                    "desired_revision": "INTEGER",
                    "installed_revision": "INTEGER",
                    "installed_sha256": "TEXT",
                    "installed_telegram_user_id": "INTEGER",
                    "sync_requested": "INTEGER NOT NULL DEFAULT 0",
                },
            )
            self._ensure_columns(
                db,
                "profile_sync_requests",
                {"mode": "TEXT NOT NULL DEFAULT 'check'"},
            )
            # Additive migration: make each pre-versioned vault row revision 1.
            legacy_rows = db.execute(
                "SELECT profile,telegram_user_id,encrypted_bundle,source,updated_at,desired_revision "
                "FROM profile_sessions WHERE desired_revision=0"
            ).fetchall()
            for row in legacy_rows:
                profile = str(row["profile"])
                plaintext = self._decrypt(profile, bytes(row["encrypted_bundle"]))
                digest = hashlib.sha256(plaintext).hexdigest()
                source_row = db.execute(
                    "SELECT bootstrap_worker FROM profile_provisionings WHERE profile=? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (profile,),
                ).fetchone()
                source_worker = str(source_row[0]) if source_row else None
                db.execute(
                    "INSERT OR IGNORE INTO profile_session_revisions "
                    "(profile,revision,format_version,bundle_sha256,telegram_user_id,source,source_worker,encrypted_bundle,created_at) "
                    "VALUES(?,1,1,?,?,?,?,?,?)",
                    (
                        profile,
                        digest,
                        int(row["telegram_user_id"]),
                        str(row["source"]),
                        source_worker,
                        bytes(row["encrypted_bundle"]),
                        str(row["updated_at"]),
                    ),
                )
                db.execute(
                    "UPDATE profile_sessions SET desired_revision=1,format_version=1,bundle_sha256=?,source_worker=? WHERE profile=?",
                    (digest, source_worker, profile),
                )
                db.execute(
                    "UPDATE profile_distributions SET desired_revision=1, "
                    "installed_revision=CASE WHEN status='ready' THEN 1 ELSE installed_revision END, "
                    "installed_sha256=CASE WHEN status='ready' THEN ? ELSE installed_sha256 END, "
                    "installed_telegram_user_id=CASE WHEN status='ready' THEN ? ELSE installed_telegram_user_id END "
                    "WHERE profile=?",
                    (digest, int(row["telegram_user_id"]), profile),
                )

    @staticmethod
    def _ensure_columns(db: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def _safe_log_details(category: str, details: dict[str, Any] | None) -> dict[str, Any]:
        details = details if isinstance(details, dict) else {}
        if category == "tts":
            allowed = {
                "ready", "reason_code", "helpers_ready", "capability_ready",
                "profile_session_ready", "profile_sync_ready", "helpers", "queued_jobs",
            }
            result = {key: details[key] for key in allowed if key in details}
            for key in ("ready", "helpers_ready", "capability_ready", "profile_session_ready", "profile_sync_ready"):
                if key in result:
                    result[key] = bool(result[key])
            if "queued_jobs" in result:
                value = result["queued_jobs"]
                result["queued_jobs"] = max(0, min(1_000_000, int(value))) if isinstance(value, int) else 0
            if "reason_code" in result:
                result["reason_code"] = re.sub(r"[^a-z0-9_-]", "", str(result["reason_code"]).lower())[:64]
            if isinstance(result.get("helpers"), list):
                result["helpers"] = [
                    {
                        "slot": item.get("slot"),
                        "status": item.get("status") if item.get("status") in {"ready", "bootstrapping", "tor_unreachable", "helper_unreachable"} else "helper_unreachable",
                        "bootstrap_percent": item.get("bootstrap_percent") if isinstance(item.get("bootstrap_percent"), int) and 0 <= item.get("bootstrap_percent") <= 100 else None,
                    }
                    for item in result["helpers"]
                    if isinstance(item, dict)
                ][:3]
        else:
            allowed = {"ready", "reason_code", "checks", "attempt", "bundle_size_bytes", "target_count"}
            result = {key: details[key] for key in allowed if key in details}
            if isinstance(result.get("checks"), list):
                result["checks"] = [
                    {
                        "name": re.sub(r"[^a-z0-9_-]", "", str(item.get("name") or "check").lower())[:48],
                        "ready": bool(item.get("ready")),
                        "code": re.sub(r"[^A-Z0-9_-]", "", str(item.get("code") or "").upper())[:64],
                    }
                    for item in result["checks"]
                    if isinstance(item, dict)
                ][:8]
            if "ready" in result:
                result["ready"] = bool(result["ready"])
            if "reason_code" in result:
                result["reason_code"] = re.sub(r"[^A-Z0-9_-]", "", str(result["reason_code"]).upper())[:64]
            for key in ("attempt", "bundle_size_bytes", "target_count"):
                if key in result:
                    value = result[key]
                    result[key] = max(0, min(2**31 - 1, int(value))) if isinstance(value, int) else 0
        # Log payloads are deliberately limited to scalar statuses and bounded lists.
        return result

    def append_diagnostic_log(
        self,
        *,
        category: str,
        actor_user_id: int,
        event_type: str,
        code: str,
        profile: str | None = None,
        worker: str | None = None,
        operation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        category = str(category)
        if category not in {"tts", "profile_export", "profile_operation"}:
            raise ValueError("Kategori log diagnostik tidak valid.")
        safe_details = self._safe_log_details(category, details)
        event_type = re.sub(r"[^a-z0-9_]", "", str(event_type).lower())[:64] or "event"
        code = re.sub(r"[^A-Z0-9_-]", "", str(code).upper())[:64] or "UNKNOWN"
        created_at = _now()
        with self._lock, self._db() as db:
            db.execute(
                "INSERT INTO profile_diagnostic_logs(category,actor_user_id,operation_id,profile,worker,event_type,code,details_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    category, int(actor_user_id), str(operation_id) if operation_id else None,
                    str(profile)[:48] if profile else None, str(worker)[:48] if worker else None,
                    event_type, code, json.dumps(safe_details, separators=(",", ":")), created_at,
                ),
            )
            db.execute(
                "DELETE FROM profile_diagnostic_logs WHERE id NOT IN "
                "(SELECT id FROM profile_diagnostic_logs ORDER BY id DESC LIMIT 10000)"
            )

    def diagnostic_logs(
        self, actor_user_id: int, category: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        safe_limit = min(500, max(1, int(limit)))
        with self._db() as db:
            rows = db.execute(
                "SELECT id,category,operation_id,profile,worker,event_type,code,details_json,created_at "
                "FROM profile_diagnostic_logs WHERE actor_user_id=? AND category=? ORDER BY id DESC LIMIT ?",
                (int(actor_user_id), str(category), safe_limit),
            ).fetchall()
        return [self._diagnostic_log_row(row) for row in rows]

    def append_profile_sync_log(
        self,
        *,
        profile: str,
        worker: str,
        run_id: str,
        phase: str,
        status: str,
        code: str = "",
        revision: int | None = None,
        sequence: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> int | None:
        safe_details = self._safe_profile_sync_details(details)
        now = _now()
        with self._lock, self._db() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO profile_sync_logs "
                "(profile,worker,run_id,sequence,revision,phase,status,code,details_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    str(profile)[:48], str(worker)[:48], str(run_id)[:64],
                    int(sequence) if sequence is not None else None,
                    int(revision) if revision is not None else None,
                    re.sub(r"[^a-z0-9_-]", "", str(phase).lower())[:64] or "event",
                    str(status)[:24],
                    re.sub(r"[^A-Z0-9_-]", "", str(code).upper())[:64],
                    json.dumps(safe_details, separators=(",", ":")), now,
                ),
            )
            db.execute(
                "DELETE FROM profile_sync_logs WHERE id NOT IN "
                "(SELECT id FROM profile_sync_logs ORDER BY id DESC LIMIT 50000)"
            )
            return int(cursor.lastrowid) if cursor.rowcount else None

    def profile_sync_logs(
        self, profile: str, worker: str, *, after_id: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        safe_limit = min(500, max(1, int(limit)))
        with self._db() as db:
            latest = db.execute(
                "SELECT run_id,status FROM profile_sync_logs "
                "WHERE profile=? AND worker=? ORDER BY id DESC LIMIT 1",
                (str(profile), str(worker)),
            ).fetchone()
            if int(after_id) <= 0:
                rows = db.execute(
                    "SELECT id,profile,worker,run_id,sequence,revision,phase,status,code,details_json,created_at "
                    "FROM profile_sync_logs WHERE profile=? AND worker=? ORDER BY id DESC LIMIT ?",
                    (str(profile), str(worker), safe_limit),
                ).fetchall()[::-1]
            else:
                rows = db.execute(
                    "SELECT id,profile,worker,run_id,sequence,revision,phase,status,code,details_json,created_at "
                    "FROM profile_sync_logs WHERE profile=? AND worker=? AND id>? ORDER BY id LIMIT ?",
                    (str(profile), str(worker), int(after_id), safe_limit),
                ).fetchall()
        items = []
        for row in rows:
            try:
                details = json.loads(str(row["details_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                details = {}
            items.append({
                "id": int(row["id"]),
                "profile": str(row["profile"]),
                "worker": str(row["worker"]),
                "run_id": str(row["run_id"]),
                "sequence": int(row["sequence"]) if row["sequence"] is not None else None,
                "revision": int(row["revision"]) if row["revision"] is not None else None,
                "phase": str(row["phase"]),
                "status": str(row["status"]),
                "code": str(row["code"]),
                "details": details if isinstance(details, dict) else {},
                "created_at": str(row["created_at"]),
            })
        last_id = items[-1]["id"] if items else max(0, int(after_id))
        latest_status = str(latest["status"]) if latest else ""
        return {
            "items": items,
            "next_after_id": last_id,
            "latest_run_id": str(latest["run_id"]) if latest else None,
            "latest_status": latest_status or None,
            "active": latest_status in {"queued", "running"},
        }

    @staticmethod
    def _safe_profile_sync_details(details: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(details, dict):
            return {}
        allowed = {"desired_revision", "installed_revision", "bundle_bytes", "entry_count", "attempt"}
        result: dict[str, Any] = {}
        for key in allowed:
            value = details.get(key)
            if type(value) is int:
                result[key] = max(0, min(2**31 - 1, value))
        return result

    def operation_accepts_bundle(self, operation_id: str) -> bool:
        with self._db() as db:
            row = db.execute(
                "SELECT status,source FROM profile_provisionings WHERE id=?", (str(operation_id),)
            ).fetchone()
        return bool(row is not None and str(row["status"]) == "validating" and str(row["source"]) == "adoption")

    def provisioning_logs(self, operation_id: str, actor_user_id: int, limit: int = 500) -> list[dict[str, Any]] | None:
        safe_limit = min(500, max(1, int(limit)))
        with self._db() as db:
            owner = db.execute(
                "SELECT actor_user_id FROM profile_provisionings WHERE id=?", (str(operation_id),)
            ).fetchone()
            if owner is None or int(owner["actor_user_id"]) != int(actor_user_id):
                return None
            rows = db.execute(
                "SELECT id,category,operation_id,profile,worker,event_type,code,details_json,created_at "
                "FROM profile_diagnostic_logs WHERE operation_id=? ORDER BY id DESC LIMIT ?",
                (str(operation_id), safe_limit),
            ).fetchall()
        return [self._diagnostic_log_row(row) for row in rows]

    @staticmethod
    def _diagnostic_log_row(row: sqlite3.Row) -> dict[str, Any]:
        try:
            details = json.loads(str(row["details_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            details = {}
        return {
            "id": int(row["id"]),
            "category": str(row["category"]),
            "operation_id": str(row["operation_id"]) if row["operation_id"] else None,
            "profile": str(row["profile"]) if row["profile"] else None,
            "worker": str(row["worker"]) if row["worker"] else None,
            "event": str(row["event_type"]),
            "code": str(row["code"]),
            "details": details if isinstance(details, dict) else {},
            "created_at": str(row["created_at"]),
        }

    def _encrypt(self, profile: str, data: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + AESGCM(self._key).encrypt(nonce, data, profile.encode("utf-8"))

    def _decrypt(self, profile: str, data: bytes) -> bytes:
        return AESGCM(self._key).decrypt(data[:12], data[12:], profile.encode("utf-8"))

    def begin(
        self,
        *,
        profile: str,
        actor_user_id: int,
        bootstrap_worker: str,
        source: str,
        method: str | None = None,
        target_workers: list[str],
        status: str = "authenticating",
    ) -> str:
        if status not in {"authenticating", "validating"}:
            raise ValueError("Status provisioning awal tidak valid.")
        operation_id = str(uuid.uuid4())
        now = _now()
        with self._lock, self._db() as db:
            try:
                db.execute(
                    "INSERT INTO profile_provisionings(id,profile,actor_user_id,bootstrap_worker,source,method,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (operation_id, profile, int(actor_user_id), bootstrap_worker, source, method, status, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise FileExistsError("Profil sedang menjalani provisioning lain.") from exc
            for worker in target_workers:
                db.execute(
                    "INSERT INTO profile_distributions(profile,worker,status,provisioning_id,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(profile,worker) DO UPDATE SET status='waiting',provisioning_id=excluded.provisioning_id,error=NULL,updated_at=excluded.updated_at",
                    (profile, worker, "waiting", operation_id, now),
                )
        return operation_id

    def store_bundle(self, operation_id: str, user_id: int, bundle: bytes) -> None:
        validate_profile_bundle(bundle)
        if profile_bundle_identity(bundle) != int(user_id):
            raise ValueError("Identity bundle tidak cocok dengan sesi TDL.")
        now = _now()
        bundle_sha256 = hashlib.sha256(bundle).hexdigest()
        with self._lock, self._db() as db:
            row = db.execute(
                "SELECT profile,source,status,bootstrap_worker FROM profile_provisionings WHERE id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            if str(row["status"]) not in {"authenticating", "validating"}:
                raise ValueError("Provisioning profil sudah tidak menerima sesi.")
            profile = str(row["profile"])
            latest = db.execute(
                "SELECT COALESCE(MAX(revision),0) FROM profile_session_revisions WHERE profile=?",
                (profile,),
            ).fetchone()
            revision = int(latest[0] or 0) + 1
            encrypted_bundle = self._encrypt(profile, bundle)
            db.execute(
                "INSERT INTO profile_session_revisions "
                "(profile,revision,format_version,bundle_sha256,telegram_user_id,source,source_worker,encrypted_bundle,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    profile,
                    revision,
                    1,
                    bundle_sha256,
                    int(user_id),
                    str(row["source"]),
                    str(row["bootstrap_worker"]),
                    encrypted_bundle,
                    now,
                ),
            )
            try:
                db.execute(
                    "INSERT INTO profile_sessions(profile,telegram_user_id,encrypted_bundle,active,source,updated_at,desired_revision,format_version,bundle_sha256,source_worker) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(profile) DO UPDATE SET telegram_user_id=excluded.telegram_user_id,encrypted_bundle=excluded.encrypted_bundle,active=0,source=excluded.source,updated_at=excluded.updated_at,desired_revision=excluded.desired_revision,format_version=excluded.format_version,bundle_sha256=excluded.bundle_sha256,source_worker=excluded.source_worker",
                    (
                        profile,
                        int(user_id),
                        encrypted_bundle,
                        0,
                        str(row["source"]),
                        now,
                        revision,
                        1,
                        bundle_sha256,
                        str(row["bootstrap_worker"]),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise FileExistsError("Akun Telegram tersebut sudah terdaftar pada profil lain.") from exc
            db.execute(
                "UPDATE profile_distributions SET status='waiting',error=NULL,desired_revision=?,installed_revision=NULL,installed_sha256=NULL,installed_telegram_user_id=NULL,sync_requested=0,updated_at=? WHERE profile=?",
                (revision, now, profile),
            )
            db.execute(
                "DELETE FROM profile_legacy_candidates WHERE profile=?", (profile,)
            )
            db.execute(
                "UPDATE profile_sync_requests SET desired_revision=?,status='pending',updated_at=? WHERE profile=? AND status='pending'",
                (revision, now, profile),
            )
            db.execute(
                "UPDATE profile_provisionings SET telegram_user_id=?,status='distributing',error=NULL,updated_at=? WHERE id=?",
                (int(user_id), now, operation_id),
            )

    def bundle(self, profile: str) -> tuple[int, bytes] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT telegram_user_id,encrypted_bundle FROM profile_session_revisions "
                "WHERE profile=? AND revision=(SELECT desired_revision FROM profile_sessions WHERE profile=?)",
                (profile, profile),
            ).fetchone()
            if row is None:
                row = db.execute(
                    "SELECT telegram_user_id,encrypted_bundle FROM profile_sessions WHERE profile=?",
                    (profile,),
                ).fetchone()
        if row is None:
            return None
        return int(row["telegram_user_id"]), self._decrypt(profile, bytes(row["encrypted_bundle"]))

    def desired_revision(self, profile: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT profile,desired_revision,format_version,bundle_sha256,telegram_user_id,source,source_worker "
                "FROM profile_sessions WHERE profile=?",
                (str(profile),),
            ).fetchone()
        if row is None or int(row["desired_revision"] or 0) < 1 or not row["bundle_sha256"]:
            return None
        return {
            "profile": str(row["profile"]),
            "revision": int(row["desired_revision"]),
            "format_version": int(row["format_version"]),
            "bundle_sha256": str(row["bundle_sha256"]),
            "telegram_user_id": int(row["telegram_user_id"]),
            "source": str(row["source"]),
            "source_worker": str(row["source_worker"] or ""),
        }

    def vaulted_identities(self) -> dict[str, int]:
        with self._db() as db:
            rows = db.execute(
                "SELECT profile,telegram_user_id FROM profile_sessions ORDER BY profile"
            ).fetchall()
        return {str(row["profile"]): int(row["telegram_user_id"]) for row in rows}

    def is_vaulted(self, profile: str) -> bool:
        with self._db() as db:
            return db.execute(
                "SELECT 1 FROM profile_sessions WHERE profile=?", (str(profile),)
            ).fetchone() is not None

    def record_legacy_discovery(
        self, profile: str, telegram_user_id: int, source_worker: str = "legacy-unattributed"
    ) -> bool:
        """Keep old worker identity reports as adoption candidates, never as vault data."""
        normalized = normalize_profile_name(profile)
        if not normalized:
            raise ValueError("Nama profile tidak valid.")
        with self._lock, self._db() as db:
            if db.execute(
                "SELECT 1 FROM profile_sessions WHERE profile=?", (normalized,)
            ).fetchone():
                return False
            db.execute(
                "INSERT INTO profile_legacy_candidates(profile,telegram_user_id,source_worker,discovered_at) "
                "VALUES(?,?,?,?) ON CONFLICT(profile,telegram_user_id,source_worker) "
                "DO UPDATE SET discovered_at=excluded.discovered_at",
                (normalized, int(telegram_user_id), str(source_worker)[:48], _now()),
            )
        return True

    def legacy_candidates(self, profile: str | None = None) -> list[dict[str, Any]]:
        with self._db() as db:
            if profile is None:
                rows = db.execute(
                    "SELECT profile,source_worker,discovered_at FROM profile_legacy_candidates ORDER BY profile,source_worker"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT profile,source_worker,discovered_at FROM profile_legacy_candidates WHERE profile=? ORDER BY source_worker",
                    (str(profile),),
                ).fetchall()
        return [
            {"profile": str(row["profile"]), "source_worker": str(row["source_worker"]), "discovered_at": str(row["discovered_at"])}
            for row in rows
        ]

    def profile_manifest(self, worker: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT p.profile,p.desired_revision,p.format_version,p.bundle_sha256,p.active, "
                "d.status,d.installed_revision,d.installed_sha256,d.sync_requested "
                "FROM profile_sessions p JOIN profile_distributions d ON d.profile=p.profile "
                "WHERE d.worker=? ORDER BY p.profile",
                (str(worker),),
            ).fetchall()
        return [
            {
                "profile": str(row["profile"]),
                "revision": int(row["desired_revision"]),
                "format_version": int(row["format_version"]),
                "bundle_sha256": str(row["bundle_sha256"]),
                "admission_status": (
                    "ready" if bool(row["active"])
                    and str(row["status"]) == "ready"
                    and row["installed_revision"] is not None
                    and int(row["installed_revision"]) == int(row["desired_revision"])
                    and str(row["installed_sha256"] or "") == str(row["bundle_sha256"])
                    else "pending"
                ),
                "sync_requested": bool(row["sync_requested"]),
            }
            for row in rows
        ]

    def bundle_for_worker(self, profile: str, revision: int, worker: str) -> dict[str, Any] | None:
        with self._db() as db:
            assigned = db.execute(
                "SELECT desired_revision FROM profile_distributions WHERE profile=? AND worker=?",
                (str(profile), str(worker)),
            ).fetchone()
            if assigned is None or assigned["desired_revision"] is None or int(assigned["desired_revision"]) != int(revision):
                return None
            row = db.execute(
                "SELECT revision,format_version,bundle_sha256,telegram_user_id,encrypted_bundle "
                "FROM profile_session_revisions WHERE profile=? AND revision=?",
                (str(profile), int(revision)),
            ).fetchone()
        if row is None:
            return None
        return {
            "profile": str(profile),
            "revision": int(row["revision"]),
            "format_version": int(row["format_version"]),
            "bundle_sha256": str(row["bundle_sha256"]),
            "telegram_user_id": int(row["telegram_user_id"]),
            "bundle": self._decrypt(str(profile), bytes(row["encrypted_bundle"])),
        }

    def acknowledge_bundle(
        self, profile: str, worker: str, revision: int, bundle_sha256: str,
        telegram_user_id: int, *, error_code: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self._lock, self._db() as db:
            assignment = db.execute(
                "SELECT desired_revision FROM profile_distributions WHERE profile=? AND worker=?",
                (str(profile), str(worker)),
            ).fetchone()
            expected = db.execute(
                "SELECT bundle_sha256,telegram_user_id FROM profile_session_revisions WHERE profile=? AND revision=?",
                (str(profile), int(revision)),
            ).fetchone()
            if assignment is None or expected is None:
                return {"accepted": False, "reason": "not_assigned"}
            desired = int(assignment["desired_revision"] or 0)
            stale = desired != int(revision)
            metadata_matches = (
                str(expected["bundle_sha256"]) == str(bundle_sha256)
                and int(expected["telegram_user_id"]) == int(telegram_user_id)
            )
            if not metadata_matches:
                db.execute(
                    "UPDATE profile_distributions SET status='failed',error='ACK_METADATA_MISMATCH',updated_at=? WHERE profile=? AND worker=?",
                    (now, str(profile), str(worker)),
                )
                return {"accepted": False, "reason": "metadata_mismatch", "desired_revision": desired}
            if stale:
                db.execute(
                    "UPDATE profile_distributions SET status='waiting',error='STALE_REVISION_ACK', "
                    "installed_revision=CASE WHEN ? IS NULL THEN installed_revision ELSE ? END, "
                    "installed_sha256=CASE WHEN ? IS NULL THEN installed_sha256 ELSE ? END, "
                    "installed_telegram_user_id=CASE WHEN ? IS NULL THEN installed_telegram_user_id ELSE ? END, "
                    "sync_requested=1,updated_at=? WHERE profile=? AND worker=?",
                    (
                        error_code, int(revision), error_code, str(bundle_sha256),
                        error_code, int(telegram_user_id), now, str(profile), str(worker),
                    ),
                )
            elif error_code:
                safe_code = re.sub(r"[^A-Z0-9_-]", "", str(error_code).upper())[:64] or "INSTALL_FAILED"
                db.execute(
                    "UPDATE profile_distributions SET status='failed',error=?,sync_requested=1,updated_at=? WHERE profile=? AND worker=?",
                    (safe_code, now, str(profile), str(worker)),
                )
            else:
                db.execute(
                    "UPDATE profile_distributions SET status='ready',error=NULL,installed_revision=?,installed_sha256=?,installed_telegram_user_id=?,sync_requested=0,updated_at=? WHERE profile=? AND worker=?",
                    (int(revision), str(bundle_sha256), int(telegram_user_id), now, str(profile), str(worker)),
                )
            current_revision = db.execute(
                "SELECT desired_revision FROM profile_sessions WHERE profile=?", (str(profile),)
            ).fetchone()
            return {
                "accepted": not stale and not bool(error_code),
                "reason": "stale_revision" if stale else ("install_failed" if error_code else "installed"),
                "desired_revision": int(current_revision[0]) if current_revision else desired,
            }

    def distribution_provisioning_id(self, profile: str, worker: str) -> str | None:
        with self._db() as db:
            row = db.execute(
                "SELECT provisioning_id FROM profile_distributions WHERE profile=? AND worker=?",
                (str(profile), str(worker)),
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    def request_sync(
        self, operation_id: str, actor_user_id: int, profile: str, worker: str,
        revision: int, mode: str = "check",
    ) -> None:
        now = _now()
        with self._lock, self._db() as db:
            current = db.execute(
                "SELECT desired_revision FROM profile_sessions WHERE profile=?", (str(profile),)
            ).fetchone()
            if current is None or int(current["desired_revision"]) != int(revision):
                raise ValueError("Revision profil berubah sebelum permintaan sinkronisasi disimpan.")
            assigned = db.execute(
                "SELECT 1 FROM profile_distributions WHERE profile=? AND worker=?",
                (str(profile), str(worker)),
            ).fetchone()
            if assigned is None:
                raise KeyError(worker)
            db.execute(
                "INSERT INTO profile_sync_requests(operation_id,actor_user_id,profile,worker,desired_revision,mode,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,'pending',?,?) ON CONFLICT(operation_id) DO UPDATE SET desired_revision=excluded.desired_revision,mode=excluded.mode,status='pending',updated_at=excluded.updated_at",
                (str(operation_id), int(actor_user_id), str(profile), str(worker), int(revision), str(mode), now, now),
            )
            db.execute(
                "UPDATE profile_distributions SET desired_revision=?, "
                "status=CASE WHEN installed_revision=desired_revision AND installed_sha256=(SELECT bundle_sha256 FROM profile_sessions WHERE profile=?) THEN status ELSE 'waiting' END, "
                "error=NULL,sync_requested=1,updated_at=? WHERE profile=? AND worker=?",
                (int(revision), str(profile), now, str(profile), str(worker)),
            )

    def cancel_sync_request(self, operation_id: str) -> dict[str, Any] | None:
        with self._lock, self._db() as db:
            request = db.execute(
                "SELECT profile,worker,desired_revision,mode,status FROM profile_sync_requests WHERE operation_id=?",
                (str(operation_id),),
            ).fetchone()
            if request is None or str(request["status"]) != "pending":
                return None
            db.execute(
                "UPDATE profile_sync_requests SET status='cancelled',updated_at=? WHERE operation_id=?",
                (_now(), str(operation_id)),
            )
            still_pending = db.execute(
                "SELECT 1 FROM profile_sync_requests WHERE profile=? AND worker=? AND status='pending' LIMIT 1",
                (str(request["profile"]), str(request["worker"])),
            ).fetchone()
            if not still_pending:
                db.execute(
                    "UPDATE profile_distributions SET sync_requested=0 WHERE profile=? AND worker=?",
                    (str(request["profile"]), str(request["worker"])),
                )
            return {
                "profile": str(request["profile"]),
                "worker": str(request["worker"]),
                "desired_revision": int(request["desired_revision"]),
                "mode": str(request["mode"]),
            }

    def finish_sync_requests(self, profile: str, worker: str, revision: int, status: str) -> list[dict[str, Any]]:
        if status not in {"succeeded", "failed"}:
            raise ValueError("Status operasi sinkronisasi tidak valid.")
        now = _now()
        with self._lock, self._db() as db:
            rows = db.execute(
                "SELECT operation_id,actor_user_id FROM profile_sync_requests WHERE profile=? AND worker=? AND desired_revision=? AND status='pending' ORDER BY created_at",
                (str(profile), str(worker), int(revision)),
            ).fetchall()
            db.execute(
                "UPDATE profile_sync_requests SET status=?,updated_at=? WHERE profile=? AND worker=? AND desired_revision=? AND status='pending'",
                (status, now, str(profile), str(worker), int(revision)),
            )
            return [
                {"operation_id": str(row["operation_id"]), "actor_user_id": int(row["actor_user_id"])}
                for row in rows
            ]

    def sync_requests(self, profile: str, worker: str, revision: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT operation_id,actor_user_id,desired_revision,mode FROM profile_sync_requests WHERE profile=? AND worker=? AND status='pending'"
        values: list[Any] = [str(profile), str(worker)]
        if revision is not None:
            query += " AND desired_revision=?"
            values.append(int(revision))
        with self._db() as db:
            rows = db.execute(query + " ORDER BY created_at", values).fetchall()
        return [
            {"operation_id": str(row["operation_id"]), "actor_user_id": int(row["actor_user_id"]), "desired_revision": int(row["desired_revision"]), "mode": str(row["mode"])}
            for row in rows
        ]

    def active_profiles(self) -> list[str]:
        with self._db() as db:
            rows = db.execute(
                "SELECT profile FROM profile_sessions WHERE active=1 ORDER BY profile"
            ).fetchall()
        return [str(row["profile"]) for row in rows]

    def mark_active(self, operation_id: str) -> tuple[str, int]:
        now = _now()
        with self._lock, self._db() as db:
            row = db.execute(
                "SELECT profile,telegram_user_id FROM profile_sessions WHERE profile=(SELECT profile FROM profile_provisionings WHERE id=?)",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            profile = str(row["profile"])
            user_id = int(row["telegram_user_id"])
            pending = db.execute(
                "SELECT COUNT(*) AS total FROM profile_distributions WHERE profile=? AND provisioning_id=? AND status!='ready'",
                (profile, operation_id),
            ).fetchone()
            if pending and int(pending["total"]):
                return profile, user_id
            db.execute("UPDATE profile_sessions SET active=1,updated_at=? WHERE profile=?", (now, profile))
            db.execute(
                "UPDATE profile_provisionings SET status='active',updated_at=?,error=NULL WHERE id=?",
                (now, operation_id),
            )
            return profile, user_id

    def update_distribution(
        self, profile: str, worker: str, status: str, error: str | None = None,
        provisioning_id: str | None = None,
    ) -> None:
        with self._lock, self._db() as db:
            db.execute(
                "INSERT INTO profile_distributions(profile,worker,status,provisioning_id,error,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(profile,worker) DO UPDATE SET status=excluded.status,provisioning_id=COALESCE(excluded.provisioning_id,profile_distributions.provisioning_id),error=excluded.error,updated_at=excluded.updated_at",
                (profile, worker, status, provisioning_id, error, _now()),
            )
            revision = db.execute(
                "SELECT desired_revision,bundle_sha256,telegram_user_id FROM profile_sessions WHERE profile=?",
                (str(profile),),
            ).fetchone()
            if revision is not None:
                if status == "ready":
                    db.execute(
                        "UPDATE profile_distributions SET desired_revision=?,installed_revision=?,installed_sha256=?,installed_telegram_user_id=?,sync_requested=0 WHERE profile=? AND worker=?",
                        (
                            int(revision["desired_revision"]),
                            int(revision["desired_revision"]),
                            str(revision["bundle_sha256"] or ""),
                            int(revision["telegram_user_id"]),
                            str(profile),
                            str(worker),
                        ),
                    )
                else:
                    db.execute(
                        "UPDATE profile_distributions SET desired_revision=? WHERE profile=? AND worker=?",
                        (int(revision["desired_revision"]), str(profile), str(worker)),
                    )

    def distribution_ready(self, profile: str, worker: str) -> bool:
        with self._db() as db:
            row = db.execute(
                "SELECT 1 FROM profile_sessions WHERE profile=?", (profile,)
            ).fetchone()
            item = db.execute(
                "SELECT d.status,d.desired_revision,d.installed_revision,d.installed_sha256,p.bundle_sha256 "
                "FROM profile_distributions d JOIN profile_sessions p ON p.profile=d.profile "
                "WHERE d.profile=? AND d.worker=?",
                (profile, worker),
            ).fetchone()
        # Legacy profiles without a vault retain their pre-existing behavior.
        if row is None:
            return True
        # A worker can use its installed session as soon as it acknowledges
        # its own distribution. Global activation remains gated on every
        # worker in the provisioning snapshot, but an offline worker must not
        # block targets that are already ready.
        return bool(
            item is not None
            and str(item["status"]) == "ready"
            and item["desired_revision"] is not None
            and item["installed_revision"] is not None
            and int(item["installed_revision"]) == int(item["desired_revision"])
            and str(item["installed_sha256"] or "") == str(item["bundle_sha256"] or "")
        )

    def provisioning(self, operation_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM profile_provisionings WHERE id=?", (operation_id,)
            ).fetchone()
            targets = db.execute(
                "SELECT worker,status,error,updated_at,desired_revision,installed_revision FROM profile_distributions WHERE provisioning_id=? ORDER BY worker",
                (operation_id,),
            ).fetchall()
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "profile": str(row["profile"]),
            "actor_user_id": int(row["actor_user_id"]),
            "source": str(row["source"]),
            "bootstrap_worker": str(row["bootstrap_worker"]),
            "status": str(row["status"]),
            "error": str(row["error"] or ""),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "workers": [
                {
                    "worker": str(item["worker"]),
                    "status": str(item["status"]),
                    "error": str(item["error"] or ""),
                    "updated_at": str(item["updated_at"]),
                    "desired_revision": int(item["desired_revision"]) if item["desired_revision"] is not None else None,
                    "installed_revision": int(item["installed_revision"]) if item["installed_revision"] is not None else None,
                }
                for item in targets
            ],
        }

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._db() as db:
            profiles = db.execute(
                "SELECT profile,active,source,updated_at,desired_revision,format_version,bundle_sha256,source_worker "
                "FROM profile_sessions ORDER BY profile"
            ).fetchall()
            results = []
            for profile in profiles:
                workers = db.execute(
                    "SELECT worker,status,error,updated_at,desired_revision,installed_revision,installed_sha256,installed_telegram_user_id,sync_requested "
                    "FROM profile_distributions WHERE profile=? ORDER BY worker",
                    (profile["profile"],),
                ).fetchall()
                results.append(
                    {
                        "name": str(profile["profile"]),
                        "active": bool(profile["active"]),
                        "source": str(profile["source"]),
                        "updated_at": str(profile["updated_at"]),
                        "desired_revision": int(profile["desired_revision"]),
                        "format_version": int(profile["format_version"]),
                        "bundle_sha256": str(profile["bundle_sha256"] or ""),
                        "source_worker": str(profile["source_worker"] or ""),
                        "workers": [
                            {
                                "worker": str(item["worker"]),
                                "status": str(item["status"]),
                                "error": str(item["error"] or ""),
                                "updated_at": str(item["updated_at"]),
                                "desired_revision": int(item["desired_revision"]) if item["desired_revision"] is not None else None,
                                "installed_revision": int(item["installed_revision"]) if item["installed_revision"] is not None else None,
                                "installed_sha256": str(item["installed_sha256"] or ""),
                                "sync_requested": bool(item["sync_requested"]),
                            }
                            for item in workers
                        ],
                    }
                )
        return results

    def pending_operations(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT id,profile,bootstrap_worker,source,method,status,updated_at FROM profile_provisionings WHERE status IN ('validating','distributing')"
            ).fetchall()
        return [dict(row) for row in rows]

    def all_provisionings(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT id,profile,actor_user_id,source,method,status,updated_at FROM profile_provisionings WHERE status NOT IN ('cancelled') ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def fail(self, operation_id: str, error: str) -> None:
        with self._lock, self._db() as db:
            db.execute(
                "UPDATE profile_provisionings SET status='failed',error=?,updated_at=? WHERE id=? AND status!='cancelled'",
                (str(error)[:240], _now(), operation_id),
            )

    def mark_validating(self, operation_id: str) -> bool:
        with self._lock, self._db() as db:
            cursor = db.execute(
                "UPDATE profile_provisionings SET status='validating',error=NULL,updated_at=? WHERE id=? AND status='authenticating'",
                (_now(), operation_id),
            )
            return cursor.rowcount == 1

    def set_error(self, operation_id: str, error: str) -> None:
        with self._lock, self._db() as db:
            db.execute(
                "UPDATE profile_provisionings SET error=?,updated_at=? WHERE id=? AND status='validating'",
                (str(error)[:240], _now(), operation_id),
            )

    def waiting_distributions(self) -> list[tuple[str, str, str | None]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT profile,worker,provisioning_id FROM profile_distributions WHERE status IN ('waiting','failed') ORDER BY updated_at"
            ).fetchall()
        return [(str(row["profile"]), str(row["worker"]), row["provisioning_id"]) for row in rows]

    def add_worker_for_active_profiles(self, worker: str) -> None:
        now = _now()
        with self._db() as db:
            rows = db.execute(
                "SELECT profile,desired_revision FROM profile_sessions"
            ).fetchall()
            for row in rows:
                db.execute(
                    "INSERT OR IGNORE INTO profile_distributions(profile,worker,status,updated_at,desired_revision) VALUES(?,?,?,?,?)",
                    (str(row["profile"]), worker, "waiting", now, int(row["desired_revision"])),
                )

    def cancel(self, operation_id: str) -> dict[str, Any]:
        info = self.provisioning(operation_id)
        if info is None:
            raise KeyError(operation_id)
        with self._lock, self._db() as db:
            if info["status"] == "active":
                raise ValueError("Provisioning yang sudah aktif tidak dapat dibatalkan.")
            rows = db.execute(
                "SELECT profile,worker,status FROM profile_distributions WHERE provisioning_id=?",
                (operation_id,),
            ).fetchall()
            db.execute("UPDATE profile_provisionings SET status='cancelled',updated_at=? WHERE id=?", (_now(), operation_id))
            db.execute("DELETE FROM profile_sessions WHERE profile=? AND active=0", (info["profile"],))
            db.execute("DELETE FROM profile_session_revisions WHERE profile=? AND NOT EXISTS (SELECT 1 FROM profile_sessions WHERE profile=? )", (info["profile"], info["profile"]))
            db.execute("DELETE FROM profile_distributions WHERE profile=? AND provisioning_id=?", (info["profile"], operation_id))
        return {"profile": info["profile"], "workers": [(str(row["worker"]), str(row["status"])) for row in rows], "source": info["source"]}

    def retry(self, operation_id: str, source_worker: str | None = None) -> None:
        with self._lock, self._db() as db:
            row = db.execute("SELECT profile,status,source,bootstrap_worker FROM profile_provisionings WHERE id=?", (operation_id,)).fetchone()
            if row is None:
                raise KeyError(operation_id)
            if str(row["status"]) == "active":
                db.execute("UPDATE profile_distributions SET status='waiting',error=NULL,updated_at=? WHERE profile=? AND status IN ('waiting','failed')", (_now(), row["profile"]))
            elif row["status"] == "distributing":
                db.execute("UPDATE profile_distributions SET status='waiting',error=NULL,updated_at=? WHERE provisioning_id=?", (_now(), operation_id))
            elif str(row["source"]) == "adoption" and str(row["status"]) == "failed":
                worker = str(source_worker or row["bootstrap_worker"])
                db.execute(
                    "UPDATE profile_provisionings SET status='validating',bootstrap_worker=?,error=NULL,updated_at=? WHERE id=?",
                    (worker, _now(), operation_id),
                )
                db.execute(
                    "UPDATE profile_distributions SET status='waiting',error=NULL,provisioning_id=?,updated_at=? WHERE profile=?",
                    (operation_id, _now(), row["profile"]),
                )


class ProfileProvisioningService:
    def __init__(
        self, store: ProfileProvisioningStore, profile_manager, worker_registry,
        dispatcher, operation_service=None,
    ) -> None:
        self.store = store
        self.profile_manager = profile_manager
        self.worker_registry = worker_registry
        self.dispatcher = dispatcher
        self.operation_service = operation_service
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._processing_lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._wake.set()
        self._thread = threading.Thread(target=self._loop, name="profile-provisioning", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(10)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.process_once()
            except Exception:
                # The next pass retries durable waiting rows.
                pass

    def process_once(self) -> None:
        if not self._processing_lock.acquire(blocking=False):
            return
        try:
            self._process_once()
        finally:
            self._processing_lock.release()

    def _complete_login(self, operation_id: str) -> None:
        info = self.store.provisioning(operation_id)
        if info is None or info["status"] != "validating":
            return
        worker = str(info["bootstrap_worker"])
        try:
            bundle = self.dispatcher.profile_login_bundle(worker, operation_id)
            session = extract_single_session(bundle)
            user_id = int(self.dispatcher.validate_profile_session(worker, bundle))
            if self.profile_manager.profile_registry.profile_for_user(user_id) is not None:
                raise FileExistsError("Akun Telegram tersebut sudah terdaftar pada profil lain.")
            self.store.store_bundle(operation_id, user_id, build_profile_bundle(session, user_id))
        except FileExistsError:
            self.store.fail(operation_id, "Akun Telegram tersebut sudah terdaftar pada profil lain.")
            try:
                self.dispatcher.cancel_profile_login(worker, operation_id)
            except Exception:
                pass
            return
        except ValueError as exc:
            self.store.fail(operation_id, str(exc) or "Sesi TDL tidak valid.")
            try:
                self.dispatcher.cancel_profile_login(worker, operation_id)
            except Exception:
                pass
            return
        except Exception as exc:
            if getattr(exc, "status", None) in {404, 422}:
                self.store.fail(operation_id, "Worker tidak dapat memvalidasi sesi TDL. Mulai login baru.")
                try:
                    self.dispatcher.cancel_profile_login(worker, operation_id)
                except Exception:
                    pass
                return
            # Network and worker timeouts are retried by the background loop.
            self.store.set_error(
                operation_id,
                "Worker belum dapat memvalidasi sesi; sinkronisasi akan dicoba ulang.",
            )
            return
        try:
            self.dispatcher.cancel_profile_login(worker, operation_id)
        except Exception:
            pass

    def _operation_log(
        self,
        operation_id: str,
        event_type: str,
        code: str,
        *,
        worker: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        info = self.store.provisioning(operation_id)
        if info is None:
            return
        self.store.append_diagnostic_log(
            category="profile_operation",
            actor_user_id=int(info["actor_user_id"]),
            operation_id=operation_id,
            profile=str(info["profile"]),
            worker=worker or str(info["bootstrap_worker"]),
            event_type=event_type,
            code=code,
            details=details,
        )

    @staticmethod
    def _export_error(code: str) -> tuple[str, str]:
        messages = {
            "PROFILE_IDENTITY_MISSING": "Worker sumber belum memiliki identity.json yang valid.",
            "PROFILE_IDENTITY_INVALID": "Identitas pada worker sumber tidak valid.",
            "PROFILE_IDENTITY_UNSAFE": "File identitas pada worker sumber tidak aman.",
            "PROFILE_ROOT_SESSION_MISSING": "Sesi root TDL belum tersedia pada worker sumber.",
            "PROFILE_USER1_SESSION_MISSING": "Sesi user1 TDL belum tersedia pada worker sumber.",
            "PROFILE_ROOT_SESSION_EMPTY": "Database sesi root TDL kosong pada worker sumber.",
            "PROFILE_USER1_SESSION_EMPTY": "Database sesi user1 TDL kosong pada worker sumber.",
            "PROFILE_SESSION_UNSAFE": "Sesi TDL worker sumber memiliki struktur file yang tidak aman.",
            "PROFILE_SESSION_UNREADABLE": "Sesi TDL worker sumber tidak dapat dibaca.",
            "PROFILE_SESSION_BUSY": "Sesi worker sedang dipakai job lain. Coba periksa atau adopsi lagi setelah job selesai.",
            "PROFILE_SESSION_UNAVAILABLE": "Struktur sesi worker sumber belum lengkap.",
            "WORKER_UPDATE_REQUIRED": "Perbarui worker sumber agar pemeriksaan dan ekspor sesi tersedia.",
            "WORKER_UNAVAILABLE": "Worker sumber tidak dapat dihubungi. Pilih worker lain atau coba lagi nanti.",
            "DUPLICATE_TELEGRAM_IDENTITY": "Akun Telegram ini sudah terdaftar pada profil lain.",
            "PROFILE_NAME_INVALID": "Nama profil tidak valid.",
        }
        if code not in messages:
            code = "SOURCE_EXPORT_FAILED"
            messages[code] = "Worker sumber gagal mengekspor sesi. Periksa log JSON untuk kode diagnosis."
        return code, messages[code]

    def _complete_adoption(self, operation_id: str) -> None:
        info = self.store.provisioning(operation_id)
        if info is None or info["status"] != "validating" or info["source"] != "adoption":
            return
        worker = str(info["bootstrap_worker"])
        profile = str(info["profile"])
        self._operation_log(operation_id, "source_export_started", "SOURCE_EXPORT_STARTED", worker=worker)
        try:
            diagnose = getattr(self.dispatcher, "profile_export_diagnostics", None)
            if callable(diagnose):
                result = diagnose(worker, profile)
                if not isinstance(result, dict):
                    raise RuntimeError("PROFILE_DIAGNOSTICS_UNAVAILABLE")
                checks = result.get("checks") if isinstance(result.get("checks"), list) else []
                reasons = result.get("reason_codes") if isinstance(result.get("reason_codes"), list) else []
                self._operation_log(
                    operation_id,
                    "source_preflight_completed",
                    "SOURCE_READY" if result.get("ready") else (str(reasons[0]) if reasons else "SOURCE_NOT_READY"),
                    worker=worker,
                    details={"ready": bool(result.get("ready")), "checks": checks},
                )
                if not result.get("ready"):
                    code, message = self._export_error(str(reasons[0]) if reasons else "SOURCE_EXPORT_FAILED")
                    self.store.fail(operation_id, message)
                    self._operation_log(operation_id, "source_export_failed", code, worker=worker, details={"reason_code": code})
                    return

            user_id, bundle = self.dispatcher.export_profile_bundle(worker, profile)
            if not self.store.operation_accepts_bundle(operation_id):
                self._operation_log(operation_id, "source_export_discarded", "OPERATION_CANCELLED", worker=worker)
                return
            validate_profile_bundle(bundle)
            registered_id = self.profile_manager.profile_registry.profile_for_user(user_id)
            if registered_id is not None and registered_id != profile:
                raise FileExistsError("DUPLICATE_TELEGRAM_IDENTITY")
            self.store.store_bundle(operation_id, int(user_id), bundle)
            self._operation_log(
                operation_id,
                "bundle_stored",
                "BUNDLE_STORED",
                worker=worker,
                details={"bundle_size_bytes": len(bundle), "target_count": len(info["workers"])},
            )
        except FileExistsError:
            code, message = self._export_error("DUPLICATE_TELEGRAM_IDENTITY")
            self.store.fail(operation_id, message)
            self._operation_log(operation_id, "source_export_failed", code, worker=worker, details={"reason_code": code})
        except Exception as exc:
            raw_code = ""
            payload = getattr(exc, "payload", None)
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    raw_code = str(error.get("code") or "")
            status = getattr(exc, "status", None)
            if not raw_code and status == 404:
                raw_code = "WORKER_UPDATE_REQUIRED"
            elif not raw_code and status in {409, 422}:
                raw_code = "PROFILE_SESSION_UNAVAILABLE"
            elif not raw_code and isinstance(status, int) and status >= 500:
                raw_code = "WORKER_UNAVAILABLE"
            if not raw_code and str(exc).startswith("PROFILE_"):
                raw_code = str(exc)
            code, message = self._export_error(raw_code or "SOURCE_EXPORT_FAILED")
            self.store.fail(operation_id, message)
            self._operation_log(
                operation_id,
                "source_export_failed",
                code,
                worker=worker,
                details={"reason_code": code},
            )

    def _process_once(self) -> None:
        for operation in self.store.pending_operations():
            if operation["status"] == "validating":
                try:
                    if str(operation.get("source") or "") == "adoption":
                        self._complete_adoption(str(operation["id"]))
                    else:
                        self._complete_login(str(operation["id"]))
                except Exception:
                    # A later background pass retries worker and TDL outages.
                    pass
        for name in self.worker_registry.names():
            self.store.add_worker_for_active_profiles(name)
        for profile, worker, operation_id in self.store.waiting_distributions():
            pair = self.store.bundle(profile)
            if pair is None:
                continue
            user_id, bundle = pair
            desired = self.store.desired_revision(profile)
            if desired is None:
                continue
            revision = int(desired["revision"])
            sync_run_id = uuid.uuid4().hex
            worker_record = self.worker_registry.get(worker)
            if worker_record is not None and not profile_transfer_is_secure(
                str(worker_record.get("url") or "")
            ):
                self.store.append_profile_sync_log(
                    profile=profile, worker=worker, run_id=sync_run_id,
                    revision=revision, phase="worker_unreachable", status="failed",
                    code="PROFILE_TRANSFER_REQUIRES_HTTPS",
                )
                self.store.update_distribution(
                    profile,
                    worker,
                    "failed",
                    "Worker remote harus memakai URL HTTPS untuk menerima sesi.",
                    operation_id,
                )
                continue
            try:
                self.store.append_profile_sync_log(
                    profile=profile, worker=worker, run_id=sync_run_id,
                    revision=revision, phase="queued", status="queued",
                    code="PROFILE_SYNC_QUEUED",
                    details={"desired_revision": revision},
                )
                installed = self.dispatcher.install_profile_bundle(
                    worker,
                    profile,
                    user_id,
                    bundle,
                    operation_id or f"sync-{sync_run_id}",
                    sync_run_id=sync_run_id,
                    revision=revision,
                )
                if not isinstance(installed, dict) or not installed.get("ready"):
                    raise RuntimeError("Worker tidak mengonfirmasi sesi siap.")
                self.store.update_distribution(profile, worker, "ready", provisioning_id=operation_id)
                if operation_id:
                    self._operation_log(
                        operation_id,
                        "target_install_ready",
                        "TARGET_INSTALL_READY",
                        worker=worker,
                    )
                desired = self.store.desired_revision(profile)
                if desired is not None:
                    self._complete_sync_operations(
                        profile, worker, int(desired["revision"]), succeeded=True
                    )
                if not operation_id:
                    self.dispatcher.commit_profile_bundle(
                        worker, profile, f"sync-{sync_run_id}",
                        sync_run_id=sync_run_id, revision=revision,
                    )
                    self.store.append_profile_sync_log(
                        profile=profile, worker=worker, run_id=sync_run_id,
                        revision=revision, phase="completed", status="succeeded",
                        code="PROFILE_SYNC_INSTALLED",
                    )
                else:
                    current_operation = self.store.provisioning(operation_id)
                    if current_operation and current_operation["status"] == "active":
                        # An explicit retry of an already-active profile only
                        # refreshes the affected worker. Commit its replacement
                        # immediately so the previous session backup is removed.
                        self.dispatcher.commit_profile_bundle(
                            worker, profile, operation_id,
                            sync_run_id=sync_run_id, revision=revision,
                        )
                        self.store.append_profile_sync_log(
                            profile=profile, worker=worker, run_id=sync_run_id,
                            revision=revision, phase="completed", status="succeeded",
                            code="PROFILE_SYNC_INSTALLED",
                        )
            except Exception as exc:
                raw_code = getattr(exc, "code", "WORKER_UNAVAILABLE")
                payload = getattr(exc, "payload", None)
                if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                    raw_code = payload["error"].get("code") or raw_code
                if str(exc).startswith("PROFILE_"):
                    raw_code = str(exc)
                sync_code = re.sub(r"[^A-Z0-9_-]", "", str(raw_code).upper())[:64] or "WORKER_UNAVAILABLE"
                self.store.append_profile_sync_log(
                    profile=profile, worker=worker, run_id=sync_run_id,
                    revision=revision, phase="worker_unreachable", status="waiting",
                    code=sync_code,
                )
                current = self.store.provisioning(operation_id) if operation_id else None
                previous = next(
                    (item for item in current["workers"] if item["worker"] == worker),
                    None,
                ) if current else None
                self.store.update_distribution(
                    profile,
                    worker,
                    "waiting",
                    "Worker belum menerima sesi; sinkronisasi akan dicoba ulang.",
                    operation_id,
                )
                if operation_id and (not previous or previous["status"] != "waiting" or not previous["error"]):
                    self._operation_log(
                        operation_id,
                        "target_install_waiting",
                        "TARGET_INSTALL_RETRYING",
                        worker=worker,
                    )
            if operation_id:
                info = self.store.provisioning(operation_id)
                if info and info["status"] == "distributing" and all(
                    item["status"] == "ready" for item in info["workers"]
                ):
                    profile_name, user_id = self.store.mark_active(operation_id)
                    self._operation_log(operation_id, "distribution_complete", "PROFILE_DISTRIBUTED")
                    with self._lock:
                        self.profile_manager.profile_registry.register_vaulted(profile_name, user_id)
                    for item in info["workers"]:
                        commit_run_id = uuid.uuid4().hex
                        current_revision = self.store.desired_revision(profile_name)
                        revision_value = int(current_revision["revision"]) if current_revision else 0
                        self.store.append_profile_sync_log(
                            profile=profile_name,
                            worker=str(item["worker"]),
                            run_id=commit_run_id,
                            revision=revision_value or None,
                            phase="session_commit",
                            status="queued",
                            code="PROFILE_COMMIT_QUEUED",
                        )
                        try:
                            self.dispatcher.commit_profile_bundle(
                                item["worker"],
                                profile_name,
                                operation_id,
                                **(
                                    {"sync_run_id": commit_run_id, "revision": revision_value}
                                    if revision_value > 0
                                    else {}
                                ),
                            )
                            self.store.append_profile_sync_log(
                                profile=profile_name,
                                worker=str(item["worker"]),
                                run_id=commit_run_id,
                                revision=revision_value or None,
                                phase="completed",
                                status="succeeded",
                                code="PROFILE_SYNC_INSTALLED",
                            )
                        except Exception:
                            self.store.append_profile_sync_log(
                                profile=profile_name,
                                worker=str(item["worker"]),
                                run_id=commit_run_id,
                                revision=revision_value or None,
                                phase="session_commit",
                                status="failed",
                                code="PROFILE_INSTALL_COMMIT_FAILED",
                            )
                            # Installation was already confirmed. A later
                            # idempotent sync can clean up a stale backup.
                            pass

    def ready(self, profile: str, worker: str) -> bool:
        return self.store.distribution_ready(profile, worker)

    def profiles(self, actor_user_id: int | None = None) -> list[dict[str, Any]]:
        managed = {item["name"]: item for item in self.store.list_profiles()}
        operations = self.store.all_provisionings()
        latest_operations: list[dict[str, Any]] = []
        seen_operations: set[str] = set()
        for operation in operations:
            name = str(operation["profile"])
            if name not in seen_operations:
                latest_operations.append(operation)
                seen_operations.add(name)
        output = []
        for name in self.profile_manager.list_profiles():
            item = managed.get(name)
            if item is None:
                output.append({
                    "name": name,
                    "active": True,
                    "status": "legacy",
                    "vault": False,
                    "adoptable": True,
                    "adoption_candidates": self.store.legacy_candidates(name),
                    "workers": [],
                })
            else:
                output.append({**item, "status": "active" if item["active"] else "distributing", "vault": True})
        known = {item["name"] for item in output}
        for operation in latest_operations:
            name = str(operation["profile"])
            if name in known:
                current = next(item for item in output if item["name"] == name)
                if operation["updated_at"] >= current.get("updated_at", ""):
                    if actor_user_id is None or int(operation.get("actor_user_id", -1)) == int(actor_user_id):
                        current["operation_id"] = str(operation["id"])
                        if str(operation.get("source")) == "adoption" and not current.get("vault"):
                            details = self.store.provisioning(str(operation["id"])) or {}
                            current.update({
                                "source": "adoption",
                                "status": str(operation["status"]),
                                "error": str(details.get("error") or ""),
                                    "bootstrap_worker": str(details.get("bootstrap_worker") or ""),
                                "workers": details.get("workers", []),
                            })
                continue
            current = self.store.provisioning(str(operation["id"])) or {}
            owner_user_id = int(current.get("actor_user_id", -1))
            current.pop("actor_user_id", None)
            output.append({
                "name": name,
                "active": False,
                "status": str(operation["status"]),
                "source": str(operation["source"]),
                "vault": name in managed,
                "operation_id": (
                    str(operation["id"])
                    if actor_user_id is None
                    or owner_user_id == int(actor_user_id)
                    else None
                ),
                "updated_at": str(operation["updated_at"]),
                "workers": current.get("workers", []),
            })
            known.add(name)
        return output

    def _validate_new(self, name: str, bootstrap_worker: str) -> str:
        requested = str(name or "").strip().lower()
        profile = normalize_profile_name(name)
        if not profile or profile != requested or profile == self.profile_manager.default_profile:
            raise ValueError("Nama profil tidak valid atau merupakan profil default.")
        if profile in self.profile_manager.list_profiles():
            raise FileExistsError("Nama profil sudah terdaftar.")
        if self.worker_registry.get(bootstrap_worker) is None:
            raise KeyError(bootstrap_worker)
        if not self.worker_registry.names():
            raise RuntimeError("Belum ada worker terdaftar untuk menyiapkan profil.")
        return profile

    def upload(self, name: str, worker: str, data: bytes, actor_user_id: int) -> str:
        profile = self._validate_new(name, worker)
        session = extract_single_session(data)
        user_id = int(self.dispatcher.validate_profile_session(worker, data))
        if self.profile_manager.profile_registry.profile_for_user(user_id) is not None:
            raise ValueError("Akun Telegram tersebut sudah terdaftar pada profil lain.")
        with self._lock:
            profile = self._validate_new(profile, worker)
            if self.profile_manager.profile_registry.profile_for_user(user_id) is not None:
                raise ValueError("Akun Telegram tersebut sudah terdaftar pada profil lain.")
            targets = self.worker_registry.names()
            if not targets:
                raise RuntimeError("Belum ada worker terdaftar untuk menyimpan profil.")
            operation_id = self.store.begin(profile=profile, actor_user_id=actor_user_id, bootstrap_worker=worker, source="upload", target_workers=targets)
            try:
                self.store.store_bundle(operation_id, user_id, build_profile_bundle(session, user_id))
            except Exception:
                self.store.cancel(operation_id)
                raise
        self._wake.set()
        return operation_id

    def start_login(self, name: str, worker: str, method: str, phone: str | None, actor_user_id: int) -> str:
        profile = self._validate_new(name, worker)
        selected_method = method.strip().lower()
        if selected_method not in {"qr", "code"}:
            raise ValueError("Metode login harus qr atau code.")
        if selected_method == "code":
            phone_value = str(phone or "").strip()
            if not _PHONE_RE.fullmatch(phone_value):
                raise ValueError("Nomor telepon tidak valid untuk login kode.")
        else:
            phone_value = ""
        with self._lock:
            profile = self._validate_new(profile, worker)
            targets = self.worker_registry.names()
            if not targets:
                raise RuntimeError("Belum ada worker terdaftar untuk menyimpan profil.")
            operation_id = self.store.begin(profile=profile, actor_user_id=actor_user_id, bootstrap_worker=worker, source="login", method=selected_method, target_workers=targets)
        try:
            self.dispatcher.start_profile_login(worker, operation_id, selected_method, phone_value)
        except Exception:
            self.store.cancel(operation_id)
            raise
        return operation_id

    def login_state(self, operation_id: str) -> dict[str, Any]:
        info = self.store.provisioning(operation_id)
        if info is None:
            raise KeyError(operation_id)
        if info["status"] == "authenticating":
            worker = str(info["bootstrap_worker"])
            try:
                state = self.dispatcher.profile_login_state(worker, operation_id)
            except Exception as exc:
                if getattr(exc, "status", None) != 404:
                    raise
                message = "Proses login pada worker sudah berakhir. Mulai login baru."
                self.store.fail(operation_id, message)
                try:
                    self.dispatcher.cancel_profile_login(worker, operation_id)
                except Exception:
                    pass
                state = {"status": "failed", "error": message}
            if state.get("status") in {"failed", "expired"}:
                message = str(state.get("error") or "Login TDL gagal.")
                self.store.fail(operation_id, message)
                info = self.store.provisioning(operation_id) or info
                info.pop("actor_user_id", None)
                return {**info, "login": {"status": "failed", "error": message}}
            if state.get("status") == "ready":
                self.store.mark_validating(operation_id)
                self._wake.set()
                info = self.store.provisioning(operation_id) or info
                info.pop("actor_user_id", None)
                return {**info, "login": {"status": "validating"}}
            info.pop("actor_user_id", None)
            return {**info, "login": state}
        if info["status"] == "validating":
            info["login"] = {"status": "validating"}
        info.pop("actor_user_id", None)
        return info

    def login_input(self, operation_id: str, actor_user_id: int, field_name: str, value: str) -> dict[str, Any]:
        info = self.store.provisioning(operation_id)
        if info is None:
            raise KeyError(operation_id)
        if int(info["actor_user_id"]) != int(actor_user_id):
            raise PermissionError("Provisioning ini dimiliki actor lain.")
        if info["status"] != "authenticating":
            raise ValueError("Provisioning tidak sedang menunggu input login.")
        return self.dispatcher.profile_login_input(
            info["bootstrap_worker"], operation_id, field_name, value
        )

    def adopt(self, profile: str, worker: str, actor_user_id: int) -> str:
        profile = normalize_profile_name(profile)
        if not profile:
            raise ValueError("Nama profil tidak valid.")
        if profile not in self.profile_manager.list_profiles():
            raise KeyError(profile)
        if self.store.bundle(profile) is not None:
            raise FileExistsError("Profil sudah tersimpan di vault.")
        if self.worker_registry.get(worker) is None:
            raise KeyError(worker)
        with self._lock:
            if self.store.bundle(profile) is not None:
                raise FileExistsError("Profil sudah tersimpan di vault.")
            targets = self.worker_registry.names()
            if not targets:
                raise RuntimeError("Belum ada worker terdaftar untuk menyimpan profil.")
            operation_id = self.store.begin(
                profile=profile,
                actor_user_id=actor_user_id,
                bootstrap_worker=worker,
                source="adoption",
                target_workers=targets,
                status="validating",
            )
        self._operation_log(operation_id, "adoption_queued", "ADOPTION_QUEUED", worker=worker)
        self._wake.set()
        return operation_id

    def diagnose_adoption(self, profile: str, worker: str, actor_user_id: int) -> dict[str, Any]:
        selected_profile = normalize_profile_name(profile)
        if not selected_profile or selected_profile not in self.profile_manager.list_profiles():
            raise KeyError(profile)
        if self.store.bundle(selected_profile) is not None:
            raise FileExistsError("Profil sudah tersimpan di vault.")
        if self.worker_registry.get(worker) is None:
            raise KeyError(worker)
        diagnose = getattr(self.dispatcher, "profile_export_diagnostics", None)
        if not callable(diagnose):
            result = {
                "ready": False,
                "reason_codes": ["WORKER_UPDATE_REQUIRED"],
                "checks": [{"name": "worker_capability", "ready": False, "code": "WORKER_UPDATE_REQUIRED"}],
            }
        else:
            try:
                raw = diagnose(worker, selected_profile)
                reasons = raw.get("reason_codes") if isinstance(raw, dict) else None
                checks = raw.get("checks") if isinstance(raw, dict) else None
                safe_reasons = [
                    str(code)
                    for code in reasons[:8]
                    if isinstance(code, str) and re.fullmatch(r"(?:PROFILE|WORKER)_[A-Z0-9_]{1,56}", code)
                ] if isinstance(reasons, list) else []
                result = {
                    "ready": bool(isinstance(raw, dict) and raw.get("ready")),
                    "reason_codes": safe_reasons or ([] if isinstance(raw, dict) and raw.get("ready") else ["PROFILE_DIAGNOSTICS_UNAVAILABLE"]),
                    "checks": checks if isinstance(checks, list) else [],
                }
            except Exception:
                result = {
                    "ready": False,
                    "reason_codes": ["WORKER_UNAVAILABLE"],
                    "checks": [{"name": "worker_connection", "ready": False, "code": "WORKER_UNAVAILABLE"}],
                }
        reasons = result["reason_codes"] or ["PROFILE_DIAGNOSTICS_UNAVAILABLE"]
        code = reasons[0]
        self.store.append_diagnostic_log(
            category="profile_export",
            actor_user_id=int(actor_user_id),
            profile=selected_profile,
            worker=worker,
            event_type="source_check",
            code=code,
            details={"ready": result["ready"], "reason_code": code, "checks": result["checks"]},
        )
        return {
            "profile": selected_profile,
            "worker": worker,
            "ready": result["ready"],
            "reason_codes": reasons,
            "checks": ProfileProvisioningStore._safe_log_details("profile_export", {"checks": result["checks"]}).get("checks", []),
            "logs_url": "/api/v1/diagnostics/profile-exports/logs?limit=100",
        }

    def _require_owner(self, operation_id: str, actor_user_id: int) -> dict[str, Any]:
        info = self.store.provisioning(operation_id)
        if info is None:
            raise KeyError(operation_id)
        if int(info["actor_user_id"]) != int(actor_user_id):
            raise PermissionError("Provisioning ini dimiliki actor lain.")
        return info

    def operation(self, operation_id: str, actor_user_id: int) -> dict[str, Any]:
        info = self._require_owner(operation_id, actor_user_id)
        if info["status"] == "authenticating":
            return self.login_state(operation_id)
        info.pop("actor_user_id", None)
        return info

    def cancel(self, operation_id: str, actor_user_id: int) -> dict[str, Any]:
        with self._lock:
            info = self._require_owner(operation_id, actor_user_id)
            if info["source"] == "adoption" and info["status"] == "distributing":
                raise ValueError("Adopsi tidak dapat dibatalkan setelah distribusi dimulai.")
            result = self.store.cancel(operation_id)
        if info["source"] != "adoption":
            try:
                self.dispatcher.cancel_profile_login(info["bootstrap_worker"], operation_id)
            except Exception:
                pass
        if info["source"] != "adoption":
            for worker, _status in result["workers"]:
                try:
                    self.dispatcher.remove_profile_bundle(worker, info["profile"], operation_id)
                except Exception:
                    pass
        return {"cancelled": True, "profile": info["profile"]}

    def retry(self, operation_id: str, actor_user_id: int, source_worker: str | None = None) -> None:
        with self._lock:
            info = self._require_owner(operation_id, actor_user_id)
            if info["source"] == "adoption":
                if info["status"] != "failed":
                    raise ValueError("Adopsi hanya dapat dicoba ulang setelah gagal.")
                selected_worker = str(source_worker or info["bootstrap_worker"])
                if self.worker_registry.get(selected_worker) is None:
                    raise KeyError(selected_worker)
                self.store.retry(operation_id, selected_worker)
            else:
                if source_worker:
                    raise ValueError("Worker sumber hanya berlaku untuk retry adopsi.")
                self.store.retry(operation_id)
        if info["source"] == "adoption":
            self._operation_log(
                operation_id,
                "adoption_retry_queued",
                "ADOPTION_RETRY_QUEUED",
                worker=str(source_worker or info["bootstrap_worker"]),
            )
        self._wake.set()

    def worker_ready(self, profile: str, worker: str) -> bool:
        return self.ready(profile, worker)

    def _complete_sync_operations(
        self, profile: str, worker: str, revision: int, *, succeeded: bool
    ) -> None:
        requests = self.store.finish_sync_requests(
            profile, worker, revision, "succeeded" if succeeded else "failed"
        )
        if self.operation_service is None:
            return
        operation_store = self.operation_service.store
        for request in requests:
            operation = operation_store.get_for_actor(
                request["operation_id"], request["actor_user_id"]
            )
            if operation is None or operation.status.terminal:
                continue
            if operation.status == OperationStatus.WAITING_WORKER:
                operation = operation_store.transition_from_job(
                    operation.id,
                    expected_revision=operation.revision,
                    status=OperationStatus.RUNNING,
                    phase="install_confirmed",
                    safe_progress={"worker": worker},
                )
                if operation is None:
                    continue
            operation_store.transition_from_job(
                operation.id,
                expected_revision=operation.revision,
                status=(OperationStatus.SUCCEEDED if succeeded else OperationStatus.FAILED),
                phase="installed" if succeeded else "install_failed",
                safe_progress={"worker": worker, "installed_revision": int(revision)},
            )
