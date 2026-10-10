from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from tme3bot.infrastructure.secret_store import AesGcmSecretStore


class SettingsConflict(ValueError):
    def __init__(self, current_version: int) -> None:
        super().__init__("Pengaturan sudah berubah. Muat ulang sebelum menyimpan.")
        self.current_version = current_version


class SettingsScopeError(ValueError):
    pass


_SPECS: dict[str, dict[str, Any]] = {
    "backup_enabled": {"type": "boolean", "scope": "backend", "apply_policy": "immediate"},
    "backup_schedule": {"type": "time", "scope": "backend", "apply_policy": "immediate"},
    "backup_timezone": {"type": "timezone", "scope": "backend", "apply_policy": "immediate"},
    "backup_retention": {"type": "integer", "scope": "backend", "apply_policy": "immediate"},
    "backup_volume_size": {"type": "size", "scope": "backend", "apply_policy": "immediate"},
    "backup_channel": {"type": "chat_ref", "scope": "backend", "apply_policy": "immediate"},
    "backup_channel_id": {"type": "integer", "scope": "backend", "apply_policy": "immediate"},
    "storage_trash_retention_days": {"type": "integer", "scope": "backend", "apply_policy": "immediate"},
    "job_stall_timeout_seconds": {"type": "integer", "scope": "backend", "apply_policy": "immediate"},
    "job_cancel_grace_seconds": {"type": "integer", "scope": "backend", "apply_policy": "immediate"},
    "move_size": {"type": "size", "scope": "backend", "apply_policy": "next_job"},
    "compress_size": {"type": "size", "scope": "backend", "apply_policy": "next_job"},
    "compress_password": {"type": "string", "scope": "backend", "secret": True, "nullable": True, "apply_policy": "next_job"},
    "rclone_destination": {"type": "rclone_destination", "scope": "backend", "apply_policy": "next_job"},
    "bot_token": {"type": "string", "scope": "telegram", "secret": True, "nullable": True, "apply_policy": "service_restart"},
    "telegram_tts_chat_id": {"type": "chat_ref", "scope": "telegram", "secret": True, "nullable": True, "apply_policy": "immediate"},
    "worker_job_stall_timeout_seconds": {"type": "integer", "scope": "worker", "apply_policy": "safe_point"},
    "tdl_export_stall_timeout_seconds": {"type": "integer", "scope": "worker", "apply_policy": "safe_point"},
    "tdl_download_stall_timeout_seconds": {"type": "integer", "scope": "worker", "apply_policy": "safe_point"},
    "storage_profile": {"type": "profile", "scope": "worker", "apply_policy": "safe_point"},
    "tts_helper_urls": {"type": "url_list", "scope": "worker", "apply_policy": "safe_point"},
    "tts_tor_control_hosts": {"type": "host_list", "scope": "worker", "apply_policy": "safe_point"},
    "tts_tor_control_ports": {"type": "port_list", "scope": "worker", "apply_policy": "safe_point"},
    "tts_part_retries": {"type": "integer", "scope": "worker", "apply_policy": "next_job"},
    "tts_retry_base_seconds": {"type": "number", "scope": "worker", "apply_policy": "next_job"},
    "tts_newnym_after_retries": {"type": "integer", "scope": "worker", "apply_policy": "next_job"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class SqliteSettingsStore:
    """Backend-owned desired settings, encrypted secrets, ACKs and audit metadata."""

    def __init__(self, database: Path, key_path: Path) -> None:
        self.database = Path(database)
        self.key_path = Path(key_path)
        self._lock = threading.RLock()
        self._secret_store = AesGcmSecretStore(
            self.key_path, require_existing_key=self._has_encrypted_secrets()
        )
        self._initialize()

    def _has_encrypted_secrets(self) -> bool:
        if not self.database.exists():
            return False
        try:
            with closing(sqlite3.connect(self.database)) as db:
                table = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_setting_values'"
                ).fetchone()
                if table is None:
                    return False
                return db.execute(
                    "SELECT 1 FROM runtime_setting_values WHERE secret_ciphertext IS NOT NULL LIMIT 1"
                ).fetchone() is not None
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("Database runtime settings tidak dapat dibuka.") from exc

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS runtime_setting_scopes (
                    scope TEXT NOT NULL,
                    worker TEXT NOT NULL DEFAULT '',
                    desired_version INTEGER NOT NULL DEFAULT 0,
                    applied_version INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'applied',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(scope, worker)
                );
                CREATE TABLE IF NOT EXISTS runtime_setting_values (
                    scope TEXT NOT NULL,
                    worker TEXT NOT NULL DEFAULT '',
                    setting_key TEXT NOT NULL,
                    value_json TEXT,
                    secret_ciphertext BLOB,
                    is_secret INTEGER NOT NULL DEFAULT 0,
                    is_cleared INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(scope, worker, setting_key)
                );
                CREATE TABLE IF NOT EXISTS runtime_settings_migrations (
                    migration_key TEXT PRIMARY KEY,
                    completed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_settings_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    worker TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL,
                    actor_user_id INTEGER,
                    changed_keys_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_settings_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    worker TEXT NOT NULL DEFAULT '',
                    desired_version INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    UNIQUE(scope, worker, desired_version)
                );
                """
            )

    @staticmethod
    def setting_scope(key: str) -> str:
        spec = _SPECS.get(key)
        if spec is None:
            raise ValueError("Pengaturan runtime tidak dikenal.")
        return str(spec["scope"])

    def seed_once(self, migration_key: str, values: dict[str, Any], *, source: str) -> bool:
        """Import a legacy snapshot once; existing rows and tombstones always win."""
        migration_key = str(migration_key).strip()
        if not migration_key or len(migration_key) > 120:
            raise ValueError("Penanda migrasi runtime settings tidak valid.")
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for key, value in values.items():
            if key not in _SPECS:
                continue
            grouped.setdefault((self.setting_scope(key), ""), {})[key] = value
        if not grouped:
            grouped[("backend", "")] = {}
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM runtime_settings_migrations WHERE migration_key=?",
                (migration_key,),
            ).fetchone():
                db.rollback()
                return False
            changed: dict[tuple[str, str], list[str]] = {}
            for (scope, worker), group in grouped.items():
                for key, value in group.items():
                    present = db.execute(
                        "SELECT 1 FROM runtime_setting_values WHERE scope=? AND worker=? AND setting_key=?",
                        (scope, worker, key),
                    ).fetchone()
                    if present:
                        continue
                    self._write_value(db, scope, worker, key, value, cleared=False)
                    changed.setdefault((scope, worker), []).append(key)
            now = _now()
            for (scope, worker), keys in changed.items():
                db.execute(
                    "INSERT INTO runtime_setting_scopes(scope,worker,desired_version,applied_version,status,updated_at) "
                    "VALUES(?,?,1,1,'applied',?) ON CONFLICT(scope,worker) DO UPDATE SET "
                    "desired_version=MAX(desired_version,1), applied_version=MAX(applied_version,1), updated_at=excluded.updated_at",
                    (scope, worker, now),
                )
                self._audit(db, scope, worker, 1, None, keys, source)
            db.execute(
                "INSERT INTO runtime_settings_migrations(migration_key,completed_at) VALUES(?,?)",
                (migration_key, now),
            )
            db.commit()
        return True

    def seed_worker_once(self, worker: str, values: dict[str, Any], *, source: str) -> bool:
        """Import one online worker's local runtime JSON at most once."""
        worker = str(worker).strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", worker):
            raise SettingsScopeError("Nama worker tidak valid.")
        migration_key = f"worker-runtime-json-v1:{worker}"
        normalized = dict(values)
        if "job_stall_timeout_seconds" in normalized:
            normalized["worker_job_stall_timeout_seconds"] = normalized.pop(
                "job_stall_timeout_seconds"
            )
        accepted = {
            key: value for key, value in normalized.items()
            if key in _SPECS and _SPECS[key]["scope"] == "worker"
        }
        for key, value in accepted.items():
            self._validate_value(key, value)
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM runtime_settings_migrations WHERE migration_key=?",
                (migration_key,),
            ).fetchone():
                db.rollback()
                return False
            changed = []
            for key, value in accepted.items():
                present = db.execute(
                    "SELECT 1 FROM runtime_setting_values WHERE scope='worker' AND worker=? AND setting_key=?",
                    (worker, key),
                ).fetchone()
                if present:
                    continue
                self._write_value(db, "worker", worker, key, value, cleared=False)
                changed.append(key)
            now = _now()
            if changed:
                db.execute(
                    "INSERT INTO runtime_setting_scopes(scope,worker,desired_version,applied_version,status,updated_at) "
                    "VALUES('worker',?,1,1,'applied',?) ON CONFLICT(scope,worker) DO UPDATE SET "
                    "desired_version=MAX(desired_version,1), applied_version=MAX(applied_version,1), "
                    "status='applied', updated_at=excluded.updated_at",
                    (worker, now),
                )
                self._audit(db, "worker", worker, 1, None, changed, source)
            db.execute(
                "INSERT INTO runtime_settings_migrations(migration_key,completed_at) VALUES(?,?)",
                (migration_key, now),
            )
            db.commit()
        return True

    def _aad(self, scope: str, worker: str, key: str) -> bytes:
        return f"runtime-settings:v1:{scope}:{worker}:{key}".encode("utf-8")

    @staticmethod
    def _job_secret_aad(job_id: str, key: str) -> bytes:
        return f"job-settings:v1:{str(job_id)}:{key}".encode("utf-8")

    def encrypt_job_secret(self, job_id: str, key: str, value: str) -> bytes:
        """Encrypt a backend-only, job-pinned secret such as a TTS recipient."""
        if key not in {"telegram_tts_chat_id", "tdl_access_target", "tdl_storage_chat_ref"} or not str(job_id).strip():
            raise ValueError("Snapshot secret job tidak dikenal.")
        return self._secret_store.encrypt(str(value), self._job_secret_aad(job_id, key))

    def decrypt_job_secret(self, job_id: str, key: str, ciphertext: bytes) -> str:
        if key not in {"telegram_tts_chat_id", "tdl_access_target", "tdl_storage_chat_ref"} or not str(job_id).strip():
            raise ValueError("Snapshot secret job tidak dikenal.")
        return self._secret_store.decrypt(
            bytes(ciphertext), self._job_secret_aad(job_id, key)
        )

    def _write_value(
        self, db: sqlite3.Connection, scope: str, worker: str, key: str,
        value: Any, *, cleared: bool,
    ) -> None:
        is_secret = bool(_SPECS[key].get("secret"))
        value_json = None
        ciphertext = None
        if not cleared:
            if is_secret:
                ciphertext = self._secret_store.encrypt(
                    str(value), self._aad(scope, worker, key)
                )
            else:
                value_json = _json(value)
        db.execute(
            "INSERT INTO runtime_setting_values(scope,worker,setting_key,value_json,secret_ciphertext,is_secret,is_cleared) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(scope,worker,setting_key) DO UPDATE SET "
            "value_json=excluded.value_json, secret_ciphertext=excluded.secret_ciphertext, "
            "is_secret=excluded.is_secret, is_cleared=excluded.is_cleared",
            (scope, worker, key, value_json, ciphertext, int(is_secret), int(cleared)),
        )

    def _read_value(self, row: sqlite3.Row, scope: str, worker: str) -> Any:
        if bool(row["is_cleared"]):
            return ""
        if bool(row["is_secret"]):
            return self._secret_store.decrypt(
                bytes(row["secret_ciphertext"] or b""),
                self._aad(scope, worker, str(row["setting_key"])),
            )
        return json.loads(str(row["value_json"] or "null"))

    def get_values(
        self, scope: str, *, worker: str = "", include_secrets: bool = False,
        include_cleared: bool = True,
    ) -> dict[str, Any]:
        scope, worker = self._normalize_scope(scope, worker)
        with self._lock, self._db() as db:
            rows = db.execute(
                "SELECT * FROM runtime_setting_values WHERE scope=? AND worker=? ORDER BY setting_key",
                (scope, worker),
            ).fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            key = str(row["setting_key"])
            if bool(row["is_cleared"]):
                if include_cleared:
                    result[key] = ""
                continue
            if bool(row["is_secret"]) and not include_secrets:
                continue
            result[key] = self._read_value(row, scope, worker)
        return result

    def update(
        self, scope: str, values: dict[str, Any], *, expected_version: int,
        worker: str = "", clear: list[str] | tuple[str, ...] = (),
        actor_user_id: int | None = None, source: str = "web",
    ) -> dict[str, Any]:
        scope, worker = self._normalize_scope(scope, worker)
        if not isinstance(values, dict):
            raise ValueError("Daftar nilai pengaturan tidak valid.")
        clear_keys = [str(key) for key in clear]
        if len(set(clear_keys)) != len(clear_keys):
            raise ValueError("Daftar pengaturan yang dikosongkan duplikat.")
        if set(values) & set(clear_keys):
            raise ValueError("Satu pengaturan tidak dapat diubah dan dikosongkan bersamaan.")
        touched = set(values) | set(clear_keys)
        if not touched:
            raise ValueError("Pilih pengaturan yang akan disimpan atau dikosongkan.")
        for key in touched:
            spec = _SPECS.get(key)
            if spec is None or spec["scope"] != scope:
                raise SettingsScopeError("Pengaturan tidak termasuk scope yang dipilih.")
            if key in clear_keys and not spec.get("nullable"):
                raise ValueError("Pengaturan ini tidak dapat dikosongkan.")
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT desired_version,status FROM runtime_setting_scopes WHERE scope=? AND worker=?",
                (scope, worker),
            ).fetchone()
            current_version = int(current["desired_version"]) if current else 0
            if current_version != int(expected_version):
                db.rollback()
                raise SettingsConflict(current_version)
            existing = {
                row["setting_key"]: self._read_value(row, scope, worker)
                for row in db.execute(
                    "SELECT * FROM runtime_setting_values WHERE scope=? AND worker=?",
                    (scope, worker),
                ).fetchall()
            }
            candidate = {**existing, **values}
            for key in clear_keys:
                candidate[key] = ""
            self._validate(scope, candidate, values, clear_keys)
            version = current_version + 1
            for key, value in values.items():
                self._write_value(db, scope, worker, key, value, cleared=False)
            for key in clear_keys:
                self._write_value(db, scope, worker, key, None, cleared=True)
            now = _now()
            pending = scope == "worker" or bool(
                current and str(current["status"]) in {"pending", "error"}
            ) or any(
                _SPECS[key].get("apply_policy") == "service_restart" for key in touched
            )
            applied_version = int(current["desired_version"] if current else 0)
            if not pending and scope != "worker":
                applied_version = version
            status = "pending" if pending else "applied"
            db.execute(
                "INSERT INTO runtime_setting_scopes(scope,worker,desired_version,applied_version,status,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(scope,worker) DO UPDATE SET "
                "desired_version=excluded.desired_version, applied_version=excluded.applied_version, "
                "status=excluded.status, updated_at=excluded.updated_at",
                (scope, worker, version, applied_version, status, now),
            )
            self._audit(db, scope, worker, version, actor_user_id, sorted(touched), source)
            db.execute(
                "INSERT INTO runtime_settings_outbox(scope,worker,desired_version,status,created_at) VALUES(?,?,?,?,?)",
                (scope, worker, version, "pending" if pending else "delivered", now),
            )
            if not pending:
                db.execute(
                    "UPDATE runtime_settings_outbox SET delivered_at=? WHERE scope=? AND worker=? AND desired_version=?",
                    (now, scope, worker, version),
                )
            db.commit()
        return self.snapshot(scope, worker=worker)

    def update_legacy(
        self, values: dict[str, Any], *, actor_user_id: int | None = None
    ) -> None:
        grouped: dict[str, dict[str, Any]] = {}
        for key, value in values.items():
            if key not in _SPECS:
                continue
            grouped.setdefault(self.setting_scope(key), {})[key] = value
        for scope, group in grouped.items():
            snap = self.snapshot(scope)
            self.update(
                scope, group, expected_version=int(snap["desired_version"]),
                source="legacy-adapter", actor_user_id=actor_user_id,
            )

    def snapshot(self, scope: str, *, worker: str = "") -> dict[str, Any]:
        scope, worker = self._normalize_scope(scope, worker)
        with self._lock, self._db() as db:
            row = db.execute(
                "SELECT * FROM runtime_setting_scopes WHERE scope=? AND worker=?",
                (scope, worker),
            ).fetchone()
            value_rows = db.execute(
                "SELECT * FROM runtime_setting_values WHERE scope=? AND worker=? ORDER BY setting_key",
                (scope, worker),
            ).fetchall()
        version = int(row["desired_version"]) if row else 0
        applied = int(row["applied_version"]) if row else 0
        settings: dict[str, Any] = {}
        secrets_status: dict[str, bool] = {}
        for item in value_rows:
            key = str(item["setting_key"])
            if bool(item["is_secret"]):
                secrets_status[key] = not bool(item["is_cleared"])
            elif not bool(item["is_cleared"]):
                settings[key] = json.loads(str(item["value_json"] or "null"))
        return {
            "scope": scope,
            "worker": worker or None,
            "desired_version": version,
            "applied_version": applied,
            "status": str(row["status"]) if row else "unconfigured",
            "settings": settings,
            "secret_status": secrets_status,
            "updated_at": str(row["updated_at"]) if row else None,
        }

    def manifest(self, worker: str) -> dict[str, Any]:
        worker = str(worker).strip().lower()
        if not worker:
            raise SettingsScopeError("Identitas worker wajib diisi.")
        snap = self.snapshot("worker", worker=worker)
        settings = self.get_values("worker", worker=worker, include_secrets=True)
        if "worker_job_stall_timeout_seconds" in settings:
            settings["job_stall_timeout_seconds"] = settings.pop(
                "worker_job_stall_timeout_seconds"
            )
        return {
            "scope": "worker",
            "worker": worker,
            "desired_version": snap["desired_version"],
            "settings": self.get_values("worker", worker=worker, include_secrets=True),
        }

    def acknowledge(
        self, scope: str, worker: str, applied_version: int,
        *, success: bool = True, error_code: str = "",
    ) -> dict[str, Any]:
        scope, worker = self._normalize_scope(scope, worker)
        if scope != "worker" or not worker:
            raise SettingsScopeError("ACK hanya berlaku untuk scope worker yang terdaftar.")
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT desired_version,applied_version FROM runtime_setting_scopes WHERE scope=? AND worker=?",
                (scope, worker),
            ).fetchone()
            if row is None or int(applied_version) != int(row["desired_version"]):
                db.rollback()
                raise SettingsConflict(int(row["desired_version"]) if row else 0)
            status = "applied" if success else "error"
            db.execute(
                "UPDATE runtime_setting_scopes SET applied_version=?,status=?,updated_at=? WHERE scope=? AND worker=?",
                (int(applied_version) if success else int(row["applied_version"]), status, _now(), scope, worker),
            )
            db.execute(
                "UPDATE runtime_settings_outbox SET status=?,delivered_at=? WHERE scope=? AND worker=? AND desired_version=?",
                ("delivered" if success else "error", _now() if success else None, scope, worker, int(applied_version)),
            )
            if not success:
                # Error codes are intentionally metadata-only and never include worker output.
                self._audit(db, scope, worker, int(applied_version), None, [], f"ack-error:{_safe_code(error_code)}")
            db.commit()
        return self.snapshot(scope, worker=worker)

    def schema(self, scope: str | None = None) -> list[dict[str, Any]]:
        if scope is not None and scope not in {"backend", "telegram", "worker"}:
            raise SettingsScopeError("Scope runtime settings tidak dikenal.")
        result = []
        for key, spec in _SPECS.items():
            if scope is not None and spec["scope"] != scope:
                continue
            result.append({
                "key": key,
                "scope": spec["scope"],
                "type": spec["type"],
                "secret": bool(spec.get("secret")),
                "clearable": bool(spec.get("nullable")),
                "apply_policy": spec.get("apply_policy", "immediate"),
                "managed": True,
            })
        # Environment-only/deployment values are visible as metadata, never editable here.
        result.extend([
            {"key": "backend_bind_host", "scope": "deployment", "type": "string", "secret": False, "clearable": False, "apply_policy": "redeploy", "managed": False},
            {"key": "backend_port", "scope": "deployment", "type": "integer", "secret": False, "clearable": False, "apply_policy": "redeploy", "managed": False},
            {"key": "utility_workspace_root", "scope": "deployment", "type": "path", "secret": False, "clearable": False, "apply_policy": "redeploy", "managed": False},
        ])
        return result

    def _validate(
        self, scope: str, candidate: dict[str, Any], values: dict[str, Any], clear: list[str],
    ) -> None:
        for key, value in values.items():
            self._validate_value(key, value)
        if scope == "backend":
            utility_keys = {"move_size", "compress_size", "compress_password", "rclone_destination"}
            if utility_keys & (set(values) | set(clear)):
                from tme3bot.utility import _validate_password, _validate_size, validate_rclone_destination

                for key in ("move_size", "compress_size"):
                    if key in candidate:
                        _validate_size(str(candidate[key]))
                if candidate.get("compress_password"):
                    _validate_password(str(candidate["compress_password"]))
                if candidate.get("rclone_destination"):
                    validate_rclone_destination(str(candidate["rclone_destination"]))
            runtime_keys = {
                "backup_enabled", "backup_schedule", "backup_timezone", "backup_retention",
                "backup_volume_size", "backup_channel", "backup_channel_id",
                "storage_trash_retention_days", "job_stall_timeout_seconds", "job_cancel_grace_seconds",
            }
            if runtime_keys & (set(values) | set(clear)):
                from tme3bot.backend_runtime_settings import BackendRuntimeSettings
                from tme3bot.chat_refs import normalize_bot_api_chat_ref
                from tme3bot.channel_ref import compact_channel_ref

                current = {key: value for key, value in candidate.items() if key in runtime_keys}
                # Validate fields present in the imported baseline, including computed channel metadata.
                if runtime_keys <= set(current):
                    normalized = BackendRuntimeSettings._normalize(current)
                    BackendRuntimeSettings._validate(normalized)
                elif "backup_channel" in current and current["backup_channel"]:
                    normalize_bot_api_chat_ref(compact_channel_ref(str(current["backup_channel"])))
        elif scope == "telegram":
            if "bot_token" in values and values["bot_token"]:
                token = str(values["bot_token"])
                if len(token) > 256 or ":" not in token or any(ch.isspace() for ch in token):
                    raise ValueError("Token bot Telegram tidak valid.")
            if candidate.get("telegram_tts_chat_id"):
                from tme3bot.chat_refs import normalize_tdl_chat_ref
                normalize_tdl_chat_ref(str(candidate["telegram_tts_chat_id"]))
        elif scope == "worker":
            pass

    @staticmethod
    def _validate_value(key: str, value: Any) -> None:
        kind = _SPECS[key]["type"]
        if kind == "boolean":
            valid = isinstance(value, bool)
        elif kind == "integer":
            valid = isinstance(value, int) and not isinstance(value, bool)
            if valid:
                bounds = {
                    "backup_retention": (1, 3650), "storage_trash_retention_days": (1, 3650),
                    "job_stall_timeout_seconds": (0, 86400), "job_cancel_grace_seconds": (0, 3600),
                    "tdl_export_stall_timeout_seconds": (0, 86400),
                    "tdl_download_stall_timeout_seconds": (0, 86400),
                    "worker_job_stall_timeout_seconds": (0, 86400),
                    "tts_part_retries": (0, 10), "tts_newnym_after_retries": (1, 20),
                    "backup_channel_id": (-(2**63 - 1), 2**63 - 1),
                }.get(key)
                if bounds:
                    valid = bounds[0] <= value <= bounds[1]
        elif kind == "number":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
            if valid:
                valid = 0.1 <= float(value) <= 60
        elif kind in {"size", "string", "time", "timezone", "chat_ref", "rclone_destination", "profile"}:
            valid = isinstance(value, str)
            if valid and kind == "size":
                valid = bool(re.fullmatch(r"[1-9][0-9]{0,5}(?:\.[0-9]{1,2})?(?:[kmgt]i?b?|b)", value.lower()))
            elif valid and kind == "time":
                valid = bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value))
            elif valid and kind == "timezone":
                try:
                    from zoneinfo import ZoneInfo
                    ZoneInfo(value)
                except (ValueError, KeyError):
                    valid = False
            elif valid and kind == "rclone_destination":
                valid = bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*:[^\x00-\x1f]+", value))
            elif valid and kind == "profile":
                valid = bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}", value.strip()))
            elif valid and kind == "chat_ref" and value:
                try:
                    if key == "telegram_tts_chat_id":
                        from tme3bot.chat_refs import normalize_tdl_chat_ref
                        normalize_tdl_chat_ref(value)
                    else:
                        from tme3bot.chat_refs import normalize_bot_api_chat_ref
                        normalize_bot_api_chat_ref(value)
                except ValueError:
                    valid = False
            elif valid and kind == "string" and key == "compress_password":
                valid = not value or 8 <= len(value) <= 128
            elif valid and key == "bot_token":
                valid = not value or (len(value) <= 256 and ":" in value and not any(ch.isspace() for ch in value))
            elif valid and key in {"compress_password"}:
                valid = not value or 8 <= len(value) <= 128
        elif kind in {"url_list", "host_list", "port_list"}:
            valid = isinstance(value, (list, tuple)) and len(value) == 3
            if valid and kind == "url_list":
                try:
                    for item in value:
                        parsed = urlsplit(str(item).strip())
                        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                            valid = False
                            break
                        _ = parsed.port
                except ValueError:
                    valid = False
            elif valid and kind == "host_list":
                valid = all(str(item).strip() and len(str(item)) <= 253 and not any(ch.isspace() for ch in str(item)) for item in value)
            elif valid and kind == "port_list":
                valid = all(isinstance(item, int) and not isinstance(item, bool) and 1 <= item <= 65535 for item in value)
        else:
            valid = False
        if not valid:
            raise ValueError(f"Nilai untuk pengaturan {key} tidak valid.")

    @staticmethod
    def _normalize_scope(scope: str, worker: str) -> tuple[str, str]:
        scope = str(scope).strip().lower()
        if scope not in {"backend", "telegram", "worker"}:
            raise SettingsScopeError("Scope runtime settings tidak dikenal.")
        worker = str(worker or "").strip().lower()
        if scope == "worker":
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", worker):
                raise SettingsScopeError("Nama worker tidak valid atau belum dipilih.")
        elif worker:
            raise SettingsScopeError("Parameter worker hanya berlaku untuk scope worker.")
        return scope, worker

    @staticmethod
    def _audit(
        db: sqlite3.Connection, scope: str, worker: str, version: int,
        actor_user_id: int | None, keys: list[str], source: str,
    ) -> None:
        db.execute(
            "INSERT INTO runtime_settings_audit(scope,worker,version,actor_user_id,changed_keys_json,source,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (scope, worker, version, actor_user_id, _json(keys), _safe_code(source), _now()),
        )


def _safe_code(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.:-]", "_", str(value or ""))
    return value[:80]
