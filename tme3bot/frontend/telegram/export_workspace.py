from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

EXPORT_WORKSPACE_TTL_SECONDS = 30 * 60


def normalize_chat_ref(chat_ref: str) -> str:
    """Match backend source canonicalization without importing its state store."""
    value = str(chat_ref or "").strip()
    if not value:
        return ""
    if value.lstrip("-").isdigit():
        return value
    return value.lstrip("@").casefold()


def short_text(value: Any, limit: int = 80) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def result_value(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") or {}
    if not isinstance(result, dict):
        return {}
    value = result.get("value", result)
    return value if isinstance(value, dict) else {}


def export_report(job: dict[str, Any]) -> dict[str, Any]:
    value = result_value(job)
    progress = job.get("progress") or {}
    artifact = value.get("artifact")
    artifact = artifact if isinstance(artifact, dict) else {}
    return {
        "status": job.get("status", "-"),
        "message_count": value.get("message_count", value.get("exported_count")),
        "media_count": value.get("media_count"),
        "photo_count": value.get("photo_count"),
        "video_count": value.get("video_count"),
        "latest_id": value.get("latest_id"),
        "filename": value.get("filename") or artifact.get("filename"),
        "artifact": value.get("artifact_key") or artifact.get("artifact_key"),
        "progress_message": progress.get("message"),
        "error": (job.get("error") or {}).get("message") if isinstance(job.get("error"), dict) else job.get("error"),
    }


@dataclass
class ExportWorkspaceState:
    source: dict[str, Any] | None = None
    chat_ref: str | None = None
    label: str | None = None
    start_id: int | None = None
    active_job_id: str | None = None
    terminal_notified_job_id: str | None = None
    source_page: int = 0
    label_page: int = 0
    touched_at: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.touched_at = time.monotonic()

    def select_source(self, source: dict[str, Any]) -> None:
        ref = normalize_chat_ref(str(source.get("chat_ref", "")))
        if not ref:
            raise ValueError("Source tidak valid.")
        self.source = dict(source)
        self.source["chat_ref"] = ref
        self.chat_ref = ref
        self.start_id = None
        self.source_page = 0
        self.touch()

    def select_chat_ref(self, chat_ref: str, source: dict[str, Any] | None = None) -> None:
        ref = normalize_chat_ref(chat_ref)
        if not ref:
            raise ValueError("Username atau numeric chat ID wajib diisi.")
        self.chat_ref = ref
        self.source = dict(source) if source is not None else None
        if self.source is not None:
            self.source["chat_ref"] = ref
        self.start_id = None
        self.source_page = 0
        self.touch()

    def set_label(self, label: str | None) -> None:
        value = str(label or "").strip()
        self.label = value or None
        self.touch()

    def set_start_id(self, value: str | int | None) -> None:
        if value is None or str(value).strip() == "":
            self.start_id = None
            self.touch()
            return
        parsed = int(str(value).strip())
        if parsed < 1:
            raise ValueError("Start ID harus berupa angka minimal 1.")
        self.start_id = parsed
        self.touch()

    @property
    def default_start_id(self) -> int:
        if self.source is None:
            return 1
        return max(1, int(self.source.get("last_id", 0)) + 1)

    @property
    def effective_start_id(self) -> int:
        return self.start_id if self.start_id is not None else self.default_start_id

    def payload(self) -> dict[str, Any]:
        if not self.chat_ref:
            raise ValueError("Pilih source terlebih dahulu.")
        payload: dict[str, Any] = {"chat_ref": normalize_chat_ref(self.chat_ref)}
        if self.label:
            payload["label"] = self.label
        if self.start_id is not None:
            payload["start_id"] = self.start_id
            # The worker builds the legacy URL from this value.  This flag tells
            # ExportService to honor the explicit message ID instead of the
            # persisted source last_id.
            payload["use_url_message_id"] = True
        else:
            payload["use_url_message_id"] = False
        return payload


class ExportWorkspaceStore:
    def __init__(self, ttl_seconds: int = EXPORT_WORKSPACE_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._values: dict[tuple[int, int], ExportWorkspaceState] = {}
        self._lock = threading.RLock()

    def get(self, chat_id: int, user_id: int) -> ExportWorkspaceState:
        key = (int(chat_id), int(user_id))
        with self._lock:
            current = self._values.get(key)
            if current is None or time.monotonic() - current.touched_at > self.ttl_seconds:
                current = ExportWorkspaceState()
                self._values[key] = current
            current.touch()
            return current

    def clear(self, chat_id: int, user_id: int) -> None:
        with self._lock:
            self._values.pop((int(chat_id), int(user_id)), None)
