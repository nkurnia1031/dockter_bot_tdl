from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from tme3bot.persistence import write_json_atomic_private

LOGGER = logging.getLogger(__name__)


class WorkerRuntimeSettings:
    """Persistent allowlisted worker options that can be changed through Web."""

    def __init__(
        self,
        path: Path,
        *,
        default_storage_profile: str,
        default_tts_settings: dict[str, Any] | None = None,
        default_worker_api_token: str = "",
        default_operational_settings: dict[str, Any] | None = None,
    ) -> None:
        self.path = Path(path)
        self.default_storage_profile = str(default_storage_profile or "storage")
        self.default_tts_settings = {
            key: value
            for key, value in dict(default_tts_settings or {}).items()
            if key not in {"tts_tor_control_password", "clear_tts_tor_control_password"}
        }
        self.default_worker_api_token = str(default_worker_api_token or "")
        self.default_operational_settings = dict(default_operational_settings or {})
        self._lock = threading.RLock()
        self._values: dict[str, Any] = {}
        self._load()

    def storage_profile(self) -> str:
        with self._lock:
            selected = self._values.get("storage_profile")
            return str(selected or self.default_storage_profile)

    def set_storage_profile(self, profile: str) -> None:
        selected = str(profile).strip()
        if not selected:
            raise ValueError("Profil Storage wajib dipilih.")
        with self._lock:
            self._values["storage_profile"] = selected
            self._save_locked()

    def tts_settings(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self.default_tts_settings,
                **{
                    key: value
                    for key, value in self._values.items()
                    if key.startswith("tts_")
                },
            }

    def set_tts_settings(self, values: dict[str, Any]) -> None:
        with self._lock:
            self._values.update(values)
            self._save_locked()

    def operational_settings(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self.default_operational_settings,
                **{
                    key: value
                    for key, value in self._values.items()
                    if key in self.default_operational_settings
                },
            }

    def set_operational_settings(self, values: dict[str, Any]) -> None:
        with self._lock:
            self._values.update(values)
            self._save_locked()

    def worker_api_token(self) -> str:
        with self._lock:
            return str(self._values.get("worker_api_token") or self.default_worker_api_token)

    def worker_api_token_candidates(self) -> tuple[str, ...]:
        with self._lock:
            current = self.worker_api_token()
            previous = str(self._values.get("worker_api_token_previous") or "")
            expires_at = float(self._values.get("worker_api_token_previous_expires_at") or 0)
            if previous and expires_at > time.time():
                return tuple(value for value in (current, previous) if value)
            if previous:
                self._values.pop("worker_api_token_previous", None)
                self._values.pop("worker_api_token_previous_expires_at", None)
                self._save_locked()
            return (current,) if current else ()

    def set_worker_api_token(self, token: str, *, overlap_seconds: int = 300) -> None:
        selected = str(token).strip()
        if not selected or len(selected) > 512 or any(ch.isspace() for ch in selected):
            raise ValueError("Token API worker tidak valid.")
        with self._lock:
            current = self.worker_api_token()
            if selected != current:
                self._values["worker_api_token_previous"] = current
                self._values["worker_api_token_previous_expires_at"] = time.time() + max(
                    30, int(overlap_seconds)
                )
            self._values["worker_api_token"] = selected
            self._save_locked()

    def worker_token_matches(self, candidate: str) -> bool:
        with self._lock:
            supplied = str(candidate or "")
            current = self.worker_api_token()
            if supplied and current and supplied == current:
                if self._values.get("worker_api_token_previous"):
                    self._values.pop("worker_api_token_previous", None)
                    self._values.pop("worker_api_token_previous_expires_at", None)
                    self._save_locked()
                return True
            return supplied in self.worker_api_token_candidates()

    def _save_locked(self) -> None:
        write_json_atomic_private(self.path, self._values)

    def _load(self) -> None:
        try:
            payload: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Tidak bisa membaca pengaturan runtime worker: %s", self.path)
            return
        if isinstance(payload, dict):
            self._values = payload
            # Older worker volumes may contain the removed Tor control
            # password.  Do not retain it after upgrading to helper-local
            # control and HTTP /newnym rotation.
            removed = False
            for key in ("tts_tor_control_password", "clear_tts_tor_control_password"):
                if key in self._values:
                    self._values.pop(key, None)
                    removed = True
            if removed:
                self._save_locked()
