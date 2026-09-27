from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tme3bot.channel_ref import channel_chat_id, channel_tdl_ref, compact_channel_ref
from tme3bot.chat_refs import normalize_bot_api_chat_ref
from tme3bot.persistence import write_json_atomic_private


_SETTING_KEYS = {
    "backup_enabled",
    "backup_schedule",
    "backup_timezone",
    "backup_retention",
    "backup_volume_size",
    "backup_channel",
    "backup_channel_id",
    "storage_trash_retention_days",
    "job_stall_timeout_seconds",
    "job_cancel_grace_seconds",
    "bot_token",
    "telegram_tts_chat_id",
}


class BackendRuntimeSettings:
    """Persistent validated settings that can be applied to a live backend."""

    def __init__(self, path: Path, defaults: dict[str, Any]) -> None:
        self.path = Path(path)
        self.defaults = {key: defaults[key] for key in _SETTING_KEYS if key in defaults}
        self.values = self._normalize(dict(self.defaults))
        self._load()

    def get(self) -> dict[str, Any]:
        return dict(self.values)

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        unknown = set(values) - _SETTING_KEYS
        if unknown:
            raise ValueError("Ada pengaturan backend yang tidak dikenal.")
        candidate = self._normalize({**self.values, **values})
        self._validate(candidate)
        write_json_atomic_private(self.path, candidate)
        self.values = candidate
        return self.get()

    def _load(self) -> None:
        import json

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        try:
            candidate = self._normalize({**self.defaults, **{key: value for key, value in raw.items() if key in _SETTING_KEYS}})
            self._validate(candidate)
        except (TypeError, ValueError):
            return
        self.values = candidate

    @staticmethod
    def _normalize(values: dict[str, Any]) -> dict[str, Any]:
        result = dict(values)
        channel = str(result.get("backup_channel", "")).strip()
        if channel:
            bot_ref = normalize_bot_api_chat_ref(channel)
            result["backup_channel"] = compact_channel_ref(bot_ref)
        chat_id = str(result.get("telegram_tts_chat_id", "")).strip()
        if chat_id:
            result["telegram_tts_chat_id"] = normalize_bot_api_chat_ref(chat_id)
        if "backup_channel_id" not in result:
            result["backup_channel_id"] = channel_chat_id(
                str(result.get("backup_channel", ""))
            )
        return result

    @staticmethod
    def _validate(values: dict[str, Any]) -> None:
        if not isinstance(values.get("backup_enabled"), bool):
            raise ValueError("Status backup harus berupa pilihan aktif/nonaktif.")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(values.get("backup_schedule", ""))):
            raise ValueError("Jadwal backup harus berformat HH:MM.")
        try:
            ZoneInfo(str(values.get("backup_timezone", "")))
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError("Zona waktu backup tidak dikenal.") from exc
        for key in ("backup_retention", "storage_trash_retention_days"):
            value = values.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3650:
                raise ValueError("Retensi harus berada antara 1 dan 3650 hari.")
        for key, maximum in (("job_stall_timeout_seconds", 86400), ("job_cancel_grace_seconds", 3600)):
            value = values.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
                raise ValueError("Timeout backend di luar rentang yang diizinkan.")
        if not re.fullmatch(r"[1-9][0-9]{0,5}(?:\.[0-9]{1,2})?(?:[kmgt]i?b?|b)", str(values.get("backup_volume_size", "")).lower()):
            raise ValueError("Ukuran volume harus menggunakan format seperti 45m atau 1g.")
        channel = compact_channel_ref(str(values.get("backup_channel", "")).strip())
        if channel:
            normalize_bot_api_chat_ref(channel)
        channel_id = values.get("backup_channel_id", 0)
        if isinstance(channel_id, bool) or not isinstance(channel_id, int) or abs(channel_id) > 2**63 - 1:
            raise ValueError("ID channel backup harus berupa angka Telegram yang valid.")
        bot_token = str(values.get("bot_token", ""))
        if "bot_token" in values and (
            not bot_token
            or len(bot_token) > 256
            or ":" not in bot_token
            or any(ch.isspace() for ch in bot_token)
        ):
            raise ValueError("Token bot Telegram tidak valid.")
        chat_id = str(values.get("telegram_tts_chat_id", "")).strip()
        if chat_id:
            normalize_bot_api_chat_ref(chat_id)

    @staticmethod
    def apply_to(config, values: dict[str, Any]) -> None:
        """Update fields read by the live backend services without replacing config."""
        for key in _SETTING_KEYS - {"backup_channel", "backup_channel_id"}:
            if key in values:
                object.__setattr__(config, key, values[key])
        channel = compact_channel_ref(str(values.get("backup_channel", "")).strip())
        object.__setattr__(config, "backup_channel", channel)
        object.__setattr__(config, "backup_channel_ref", channel_tdl_ref(channel))
        object.__setattr__(
            config,
            "backup_channel_id",
            int(values.get("backup_channel_id") or channel_chat_id(channel) or 0),
        )
        bot_ref = normalize_bot_api_chat_ref(channel) if channel else ""
        object.__setattr__(config, "backup_channel_username", bot_ref.lstrip("@").strip() if bot_ref.startswith("@") else "")
        if "bot_token" in values:
            object.__setattr__(config, "bot_token", values["bot_token"])
        if "telegram_tts_chat_id" in values:
            object.__setattr__(config, "telegram_tts_chat_id", values["telegram_tts_chat_id"])
