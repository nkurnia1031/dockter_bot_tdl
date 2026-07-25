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
            value["updated_at"] = str(raw_value.get("updated_at") or utc_now_iso())
            self._profiles[name] = value

    def _save_locked(self) -> None:
        write_json_atomic(self.path, {"profiles": self._profiles or {}})
