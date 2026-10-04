from __future__ import annotations

import io
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

from tme3bot.names import normalize_profile_name


MAX_SESSION_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_PROFILE_BUNDLE_BYTES = 300 * 1024 * 1024
_PROFILE_LOGIN_TTL_SECONDS = 15 * 60
_PHONE_RE = re.compile(r"^[+0-9(). -]{4,32}$")


def profile_transfer_is_secure(worker_url: str) -> bool:
    """Allow HTTPS remote workers and explicit internal deployment hosts."""
    try:
        parsed = urlsplit(str(worker_url))
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return False
        return parsed.scheme == "https" or (
            parsed.scheme == "http"
            and parsed.hostname in {"worker-local", "local", "localhost", "127.0.0.1", "::1"}
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
                    updated_at TEXT NOT NULL
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
                    PRIMARY KEY(profile, worker)
                );
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
    ) -> str:
        operation_id = str(uuid.uuid4())
        now = _now()
        with self._lock, self._db() as db:
            try:
                db.execute(
                    "INSERT INTO profile_provisionings(id,profile,actor_user_id,bootstrap_worker,source,method,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (operation_id, profile, int(actor_user_id), bootstrap_worker, source, method, "authenticating", now, now),
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
        with self._lock, self._db() as db:
            row = db.execute(
                "SELECT profile,source,status FROM profile_provisionings WHERE id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            if str(row["status"]) not in {"authenticating", "validating"}:
                raise ValueError("Provisioning profil sudah tidak menerima sesi.")
            profile = str(row["profile"])
            try:
                db.execute(
                    "INSERT INTO profile_sessions(profile,telegram_user_id,encrypted_bundle,active,source,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(profile) DO UPDATE SET telegram_user_id=excluded.telegram_user_id,encrypted_bundle=excluded.encrypted_bundle,active=0,source=excluded.source,updated_at=excluded.updated_at",
                    (
                        profile,
                        int(user_id),
                        self._encrypt(profile, bundle),
                        0,
                        str(row["source"]),
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise FileExistsError("Akun Telegram tersebut sudah terdaftar pada profil lain.") from exc
            db.execute(
                "UPDATE profile_provisionings SET telegram_user_id=?,status='distributing',error=NULL,updated_at=? WHERE id=?",
                (int(user_id), now, operation_id),
            )

    def bundle(self, profile: str) -> tuple[int, bytes] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT telegram_user_id,encrypted_bundle FROM profile_sessions WHERE profile=?",
                (profile,),
            ).fetchone()
        if row is None:
            return None
        return int(row["telegram_user_id"]), self._decrypt(profile, bytes(row["encrypted_bundle"]))

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
                "SELECT COUNT(*) AS total FROM profile_distributions WHERE profile=? AND status!='ready'",
                (profile,),
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

    def distribution_ready(self, profile: str, worker: str) -> bool:
        with self._db() as db:
            row = db.execute(
                "SELECT active FROM profile_sessions WHERE profile=?", (profile,)
            ).fetchone()
            item = db.execute(
                "SELECT status FROM profile_distributions WHERE profile=? AND worker=?",
                (profile, worker),
            ).fetchone()
        # Legacy profiles without a vault retain their pre-existing behavior.
        if row is None:
            return True
        return bool(int(row["active"])) and item is not None and str(item["status"]) == "ready"

    def provisioning(self, operation_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM profile_provisionings WHERE id=?", (operation_id,)
            ).fetchone()
            targets = db.execute(
                "SELECT worker,status,error,updated_at FROM profile_distributions WHERE provisioning_id=? ORDER BY worker",
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
                {"worker": str(item["worker"]), "status": str(item["status"]), "error": str(item["error"] or ""), "updated_at": str(item["updated_at"])}
                for item in targets
            ],
        }

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._db() as db:
            profiles = db.execute(
                "SELECT profile,active,source,updated_at FROM profile_sessions ORDER BY profile"
            ).fetchall()
            results = []
            for profile in profiles:
                workers = db.execute(
                    "SELECT worker,status,error,updated_at FROM profile_distributions WHERE profile=? ORDER BY worker",
                    (profile["profile"],),
                ).fetchall()
                results.append(
                    {
                        "name": str(profile["profile"]),
                        "active": bool(profile["active"]),
                        "source": str(profile["source"]),
                        "updated_at": str(profile["updated_at"]),
                        "workers": [
                            {"worker": str(item["worker"]), "status": str(item["status"]), "error": str(item["error"] or ""), "updated_at": str(item["updated_at"])}
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
                "SELECT profile FROM profile_sessions WHERE active=1"
            ).fetchall()
            for row in rows:
                db.execute(
                    "INSERT OR IGNORE INTO profile_distributions(profile,worker,status,updated_at) VALUES(?,?,?,?)",
                    (str(row["profile"]), worker, "waiting", now),
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
            db.execute("DELETE FROM profile_distributions WHERE profile=? AND provisioning_id=?", (info["profile"], operation_id))
        return {"profile": info["profile"], "workers": [(str(row["worker"]), str(row["status"])) for row in rows], "source": info["source"]}

    def retry(self, operation_id: str) -> None:
        with self._lock, self._db() as db:
            row = db.execute("SELECT profile,status FROM profile_provisionings WHERE id=?", (operation_id,)).fetchone()
            if row is None:
                raise KeyError(operation_id)
            if str(row["status"]) == "active":
                db.execute("UPDATE profile_distributions SET status='waiting',error=NULL,updated_at=? WHERE profile=? AND status IN ('waiting','failed')", (_now(), row["profile"]))
            elif row["status"] == "distributing":
                db.execute("UPDATE profile_distributions SET status='waiting',error=NULL,updated_at=? WHERE provisioning_id=?", (_now(), operation_id))


class ProfileProvisioningService:
    def __init__(self, store: ProfileProvisioningStore, profile_manager, worker_registry, dispatcher) -> None:
        self.store = store
        self.profile_manager = profile_manager
        self.worker_registry = worker_registry
        self.dispatcher = dispatcher
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

    def _process_once(self) -> None:
        for operation in self.store.pending_operations():
            if operation["status"] == "validating":
                try:
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
            worker_record = self.worker_registry.get(worker)
            if worker_record is not None and not profile_transfer_is_secure(
                str(worker_record.get("url") or "")
            ):
                self.store.update_distribution(
                    profile,
                    worker,
                    "failed",
                    "Worker remote harus memakai URL HTTPS untuk menerima sesi.",
                    operation_id,
                )
                continue
            try:
                installed = self.dispatcher.install_profile_bundle(
                    worker, profile, user_id, bundle, operation_id or ""
                )
                if not isinstance(installed, dict) or not installed.get("ready"):
                    raise RuntimeError("Worker tidak mengonfirmasi sesi siap.")
                self.store.update_distribution(profile, worker, "ready", provisioning_id=operation_id)
                if not operation_id:
                    self.dispatcher.commit_profile_bundle(worker, profile, "sync-" + profile)
                else:
                    current_operation = self.store.provisioning(operation_id)
                    if current_operation and current_operation["status"] == "active":
                        # An explicit retry of an already-active profile only
                        # refreshes the affected worker. Commit its replacement
                        # immediately so the previous session backup is removed.
                        self.dispatcher.commit_profile_bundle(worker, profile, operation_id)
            except Exception:
                self.store.update_distribution(
                    profile,
                    worker,
                    "waiting",
                    "Worker belum menerima sesi; sinkronisasi akan dicoba ulang.",
                    operation_id,
                )
            if operation_id:
                info = self.store.provisioning(operation_id)
                if info and info["status"] == "distributing" and all(
                    item["status"] == "ready" for item in info["workers"]
                ):
                    profile_name, user_id = self.store.mark_active(operation_id)
                    with self._lock:
                        self.profile_manager.profile_registry.register(profile_name, user_id)
                    for item in info["workers"]:
                        try:
                            self.dispatcher.commit_profile_bundle(
                                item["worker"], profile_name, operation_id
                            )
                        except Exception:
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
        user_id, bundle = self.dispatcher.export_profile_bundle(worker, profile)
        validate_profile_bundle(bundle)
        registered_id = self.profile_manager.profile_registry.profile_for_user(user_id)
        if registered_id is not None and registered_id != profile:
            raise ValueError("Identity worker sumber tidak cocok dengan profil yang dipilih.")
        with self._lock:
            if self.store.bundle(profile) is not None:
                raise FileExistsError("Profil sudah tersimpan di vault.")
            targets = self.worker_registry.names()
            if not targets:
                raise RuntimeError("Belum ada worker terdaftar untuk menyimpan profil.")
            operation_id = self.store.begin(profile=profile, actor_user_id=actor_user_id, bootstrap_worker=worker, source="adoption", target_workers=targets)
            try:
                self.store.store_bundle(operation_id, int(user_id), bundle)
            except Exception:
                self.store.cancel(operation_id)
                raise
        self._wake.set()
        return operation_id

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
            if info["source"] == "adoption" and info["status"] in {"validating", "distributing"}:
                raise ValueError("Adopsi tidak dapat dibatalkan setelah distribusi dimulai.")
            result = self.store.cancel(operation_id)
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

    def retry(self, operation_id: str, actor_user_id: int) -> None:
        with self._lock:
            self._require_owner(operation_id, actor_user_id)
            self.store.retry(operation_id)
        self._wake.set()

    def worker_ready(self, profile: str, worker: str) -> bool:
        return self.ready(profile, worker)
