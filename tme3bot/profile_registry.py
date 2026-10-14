from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from tme3bot.names import normalize_profile_name
from tme3bot.persistence import utc_now_iso, write_json_atomic


class ProfileRegistry:
    """Gateway-owned registry for profile metadata, separate from TDL sessions.

    A worker owns its local ``.tdl`` directories.  It must never become the
    source of truth for which profiles exist or which Telegram identity is
    authorized.  Workers only register their local session identity here.
    """

    def __init__(self, path: Path, default_profile: str) -> None:
        self.path = path
        self.default_profile = normalize_profile_name(default_profile) or "default"
        self._lock = threading.RLock()
        self._profiles: dict[str, dict[str, Any]] | None = None

    def names(self) -> list[str]:
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            return sorted({self.default_profile, *self._profiles})

    def profile_for_user(self, telegram_user_id: int) -> str | None:
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            for name, value in self._profiles.items():
                if value.get("telegram_user_id") == int(telegram_user_id):
                    return name
        return None

    def register(self, name: str, telegram_user_id: int | None) -> str:
        normalized = normalize_profile_name(name)
        if not normalized:
            raise ValueError("Nama profile tidak valid.")
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            existing = self._profiles.get(normalized, {})
            value: dict[str, Any] = dict(existing)
            if telegram_user_id is not None:
                user_id = int(telegram_user_id)
                for other_name, other in self._profiles.items():
                    if other_name != normalized and other.get("telegram_user_id") == user_id:
                        raise ValueError(
                            f"Telegram user {user_id} sudah terdaftar pada profile {other_name}."
                        )
                value["telegram_user_id"] = user_id
            value["updated_at"] = utc_now_iso()
            self._profiles[normalized] = value
            self._save_locked()
        return normalized

    def register_vaulted(self, name: str, telegram_user_id: int) -> str:
        """Apply backend vault identity as authoritative registry data."""
        normalized = normalize_profile_name(name)
        if not normalized:
            raise ValueError("Nama profile tidak valid.")
        user_id = int(telegram_user_id)
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            for other_name, other in self._profiles.items():
                if other_name != normalized and other.get("telegram_user_id") == user_id:
                    other.pop("telegram_user_id", None)
                    other["updated_at"] = utc_now_iso()
            value = dict(self._profiles.get(normalized, {}))
            value["telegram_user_id"] = user_id
            value.pop("identity_cleanup", None)
            value["updated_at"] = utc_now_iso()
            self._profiles[normalized] = value
            self._save_locked()
        return normalized

    def begin_local_deletion(self, name: str, worker: str, request_token: str) -> bool:
        normalized = normalize_profile_name(name)
        worker_name = str(worker or "").strip().lower()
        token = str(request_token or "").strip()
        if not normalized or not worker_name or not token:
            return False
        key = f"{normalized}:{worker_name}"
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            deletions = self._local_deletions_locked()
            current = deletions.get(key)
            if current is not None:
                return current.get("request_token") == token
            deletions[key] = {
                "profile": normalized,
                "worker": worker_name,
                "request_token": token,
                "started_at": utc_now_iso(),
            }
            self._save_locked()
        return True

    def finish_local_deletion(self, name: str, worker: str, request_token: str) -> bool:
        normalized = normalize_profile_name(name)
        worker_name = str(worker or "").strip().lower()
        token = str(request_token or "").strip()
        key = f"{normalized}:{worker_name}"
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            deletions = self._local_deletions_locked()
            current = deletions.get(key)
            if current is None or current.get("request_token") != token:
                return False
            deletions.pop(key, None)
            self._save_locked()
        return True

    def local_deletion_active(self, name: str, worker: str) -> bool:
        normalized = normalize_profile_name(name)
        worker_name = str(worker or "").strip().lower()
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            return f"{normalized}:{worker_name}" in self._local_deletions_locked()

    def recover_local_deletions(self, active_pairs: set[tuple[str, str]]) -> None:
        """Drop admission markers without a durable operation after a restart."""
        normalized_pairs = {
            (normalize_profile_name(profile), str(worker or "").strip().lower())
            for profile, worker in active_pairs
            if normalize_profile_name(profile) and str(worker or "").strip()
        }
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            deletions = self._local_deletions_locked()
            retained = {
                key: value
                for key, value in deletions.items()
                if (str(value.get("profile") or ""), str(value.get("worker") or ""))
                in normalized_pairs
            }
            if retained != deletions:
                self._save_local_deletions_locked(retained)

    def mark_identity_cleanup_pending(self, name: str, deleted_worker: str) -> None:
        normalized = normalize_profile_name(name)
        if not normalized:
            return
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            value = dict(self._profiles.get(normalized, {}))
            value["identity_cleanup"] = {
                "status": "pending_recheck",
                "deleted_worker": str(deleted_worker or "").strip().lower(),
                "updated_at": utc_now_iso(),
            }
            value["updated_at"] = utc_now_iso()
            self._profiles[normalized] = value
            self._save_locked()

    def pending_identity_cleanups(self) -> list[dict[str, str]]:
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            return [
                {
                    "profile": name,
                    "status": "pending_recheck",
                    "deleted_worker": str(value["identity_cleanup"].get("deleted_worker") or ""),
                    "updated_at": str(value["identity_cleanup"].get("updated_at") or value.get("updated_at") or ""),
                }
                for name, value in sorted(self._profiles.items())
                if isinstance(value.get("identity_cleanup"), dict)
                and value["identity_cleanup"].get("status") == "pending_recheck"
            ]

    def clear_identity_cleanup(self, name: str) -> None:
        normalized = normalize_profile_name(name)
        if not normalized:
            return
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            value = self._profiles.get(normalized)
            if value is None or "identity_cleanup" not in value:
                return
            value.pop("identity_cleanup", None)
            value["updated_at"] = utc_now_iso()
            self._save_locked()

    def remove_identity(self, name: str) -> bool:
        """Remove authorization mapping but retain the known profile name."""
        normalized = normalize_profile_name(name)
        if not normalized:
            return False
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            value = self._profiles.get(normalized)
            if value is None:
                return False
            existed = value.pop("telegram_user_id", None) is not None
            value.pop("identity_cleanup", None)
            value["updated_at"] = utc_now_iso()
            self._save_locked()
            return existed

    def _local_deletions_locked(self) -> dict[str, dict[str, Any]]:
        assert self._profiles is not None
        # Keep deletion locks beside the profile registry while preserving the
        # historic JSON shape for readers that only inspect ``profiles``.
        raw = getattr(self, "_local_deletions", None)
        if raw is not None:
            return raw
        self._local_deletions = {}
        if not self.path.exists():
            return self._local_deletions
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._local_deletions
        source = payload.get("local_deletions", {}) if isinstance(payload, dict) else {}
        if isinstance(source, dict):
            for raw_key, raw_value in source.items():
                if not isinstance(raw_value, dict):
                    continue
                profile = normalize_profile_name(str(raw_value.get("profile") or ""))
                worker = str(raw_value.get("worker") or "").strip().lower()
                token = str(raw_value.get("request_token") or "")
                if profile and worker and token and raw_key == f"{profile}:{worker}":
                    self._local_deletions[raw_key] = {
                        "profile": profile,
                        "worker": worker,
                        "request_token": token,
                        "started_at": str(raw_value.get("started_at") or ""),
                    }
        return self._local_deletions

    def _save_local_deletions_locked(self, deletions: dict[str, dict[str, Any]]) -> None:
        self._local_deletions = deletions
        write_json_atomic(
            self.path,
            {"profiles": self._profiles or {}, "local_deletions": deletions},
        )

    def register_discovered(self, name: str, telegram_user_id: int | None) -> bool:
        """Accept only new legacy metadata; do not let a worker rewrite identity."""
        normalized = normalize_profile_name(name)
        if not normalized:
            raise ValueError("Nama profile tidak valid.")
        with self._lock:
            self._load_locked()
            assert self._profiles is not None
            existing = self._profiles.get(normalized)
            if existing is not None and existing.get("telegram_user_id") is not None:
                return telegram_user_id is None or int(existing["telegram_user_id"]) == int(telegram_user_id)
            if telegram_user_id is not None:
                user_id = int(telegram_user_id)
                if any(
                    other_name != normalized and other.get("telegram_user_id") == user_id
                    for other_name, other in self._profiles.items()
                ):
                    return False
            value = dict(existing or {})
            if telegram_user_id is not None:
                value["telegram_user_id"] = int(telegram_user_id)
            value["updated_at"] = utc_now_iso()
            self._profiles[normalized] = value
            self._save_locked()
            return True

    def bootstrap_from_identities(self, profiles: dict[str, int | None]) -> None:
        """One-way migration for installations created before the registry."""
        for name, telegram_user_id in profiles.items():
            try:
                self.register(name, telegram_user_id)
            except ValueError:
                # Keep an existing gateway mapping authoritative on conflicts.
                continue

    def _load_locked(self) -> None:
        if self._profiles is not None:
            return
        self._profiles = {}
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        raw_profiles = payload.get("profiles", {}) if isinstance(payload, dict) else {}
        if not isinstance(raw_profiles, dict):
            return
        for raw_name, raw_value in raw_profiles.items():
            name = normalize_profile_name(str(raw_name))
            if not name or not isinstance(raw_value, dict):
                continue
            value: dict[str, Any] = {}
            raw_user_id = raw_value.get("telegram_user_id")
            try:
                if raw_user_id is not None:
                    value["telegram_user_id"] = int(raw_user_id)
            except (TypeError, ValueError):
                pass
            cleanup = raw_value.get("identity_cleanup")
            if isinstance(cleanup, dict) and cleanup.get("status") == "pending_recheck":
                value["identity_cleanup"] = {
                    "status": "pending_recheck",
                    "deleted_worker": str(cleanup.get("deleted_worker") or "").strip().lower(),
                    "updated_at": str(cleanup.get("updated_at") or utc_now_iso()),
                }
            value["updated_at"] = str(raw_value.get("updated_at") or utc_now_iso())
            self._profiles[name] = value

    def _save_locked(self) -> None:
        deletions = self._local_deletions_locked()
        write_json_atomic(
            self.path,
            {"profiles": self._profiles or {}, "local_deletions": deletions},
        )
