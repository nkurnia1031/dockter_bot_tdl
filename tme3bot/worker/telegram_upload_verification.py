from __future__ import annotations

import tempfile
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


_FILENAME_KEYS = {"file_name", "filename", "original_name"}
_CAPTION_KEYS = {"caption", "content", "message", "text"}
TELEGRAM_UPLOAD_VERIFICATION_METHOD = "tdl-time-window-filename-caption-v1"


@dataclass
class TelegramUploadVerification:
    """Verification state for one accepted Telegram upload."""

    profile: str
    chat_ref: str
    filename: str
    caption: str
    uploaded_at: float
    status: str = "pending"
    message_id: int | None = None
    error_code: str = ""


class TelegramUploadBatchVerifier:
    """Verify accepted uploads with the same profile's Export lane.

    Each accepted upload gets one immediate time-range export. If any upload
    remains unmatched, one final export is made for each affected
    ``(profile, chat)`` pair, covering the whole upload window for that pair.
    Exported messages are consumed at most once, so duplicate filenames in a
    batch require separate Telegram messages.
    """

    def __init__(
        self,
        export_messages: Callable[[str, str, int, int], Any],
        *,
        window_seconds: int = 60,
    ) -> None:
        self._export_messages = export_messages
        self._window_seconds = max(1, int(window_seconds))
        self._records: list[TelegramUploadVerification] = []
        # Message IDs are unique within a Telegram chat, even when a batch
        # sends its files through several profile sessions.
        self._used_message_ids: dict[str, set[int]] = {}
        self._lock = threading.RLock()

    @classmethod
    def for_profile_manager(
        cls,
        profile_manager: Any,
        *,
        capture_export: Callable[[str, Any], Any] | None = None,
    ) -> "TelegramUploadBatchVerifier":
        """Build an Export-lane adapter from worker profile runtimes."""
        def export_messages(profile: str, chat_ref: str, start: int, end: int):
            runtime = profile_manager.runtime(profile)
            client = getattr(runtime, "export_tdl_client", None)
            if client is None:
                raise RuntimeError("Profile Export lane is unavailable.")
            lock = getattr(runtime, "export_operation_lock", None)
            with lock if lock is not None else nullcontext():
                with tempfile.TemporaryDirectory(prefix="tme3bot-upload-verify-") as raw_dir:
                    export_path = Path(raw_dir) / "messages.json"
                    context = (
                        capture_export(profile, client)
                        if capture_export is not None
                        else nullcontext()
                    )
                    with context:
                        exported = client.export_messages_by_time(
                            chat_ref,
                            start,
                            end,
                            export_path,
                            with_content=True,
                        )
            return getattr(exported, "messages", None)

        return cls(export_messages)

    def record_upload(
        self,
        *,
        profile: str,
        chat_ref: str,
        filename: str,
        caption: str,
        uploaded_at: float | None = None,
    ) -> TelegramUploadVerification:
        profile = str(profile or "").strip().lower()
        chat_ref = str(chat_ref or "").strip()
        filename = str(filename or "")
        if not profile or not chat_ref or not filename:
            raise ValueError("Profile, chat, and filename are required for upload verification.")
        record = TelegramUploadVerification(
            profile=profile,
            chat_ref=chat_ref,
            filename=filename,
            caption=str(caption or ""),
            uploaded_at=float(uploaded_at if uploaded_at is not None else time.time()),
        )
        with self._lock:
            self._records.append(record)
        key = record.chat_ref
        try:
            messages = self._export_messages(
                record.profile,
                record.chat_ref,
                self._window_start(record.uploaded_at),
                self._window_end(record.uploaded_at),
            )
            self._match_records([record], messages, key)
        except Exception:
            # An export failure cannot prove absence. Keep the upload pending
            # for the single end-of-batch check.
            record.error_code = "TELEGRAM_UPLOAD_VERIFY_EXPORT_FAILED"
        return record

    def find_existing_upload(
        self,
        *,
        profile: str,
        chat_ref: str,
        filename: str,
        caption: str,
        start: int,
        end: int,
        reference_time: float | None = None,
    ) -> TelegramUploadVerification:
        """Search a caller-bounded export for an exact prior attachment/caption."""
        profile = str(profile or "").strip().lower()
        chat_ref = str(chat_ref or "").strip()
        filename = str(filename or "")
        if not profile or not chat_ref or not filename:
            raise ValueError("Profile, chat, and filename are required for upload verification.")
        record = TelegramUploadVerification(
            profile=profile,
            chat_ref=chat_ref,
            filename=filename,
            caption=str(caption or ""),
            uploaded_at=float(reference_time if reference_time is not None else time.time()),
        )
        messages = self._export_messages(profile, chat_ref, max(0, int(start)), int(end))
        self._match_records([record], messages, chat_ref)
        return record

    def finalize(self) -> list[TelegramUploadVerification]:
        """Run one batch-window export for every profile/chat with misses."""
        grouped: dict[tuple[str, str], list[TelegramUploadVerification]] = {}
        with self._lock:
            records = list(self._records)
        for record in records:
            if record.status == "pending":
                grouped.setdefault((record.profile, record.chat_ref), []).append(record)

        for key, pending in grouped.items():
            all_in_chat = [
                record for record in records
                if record.chat_ref == key[1]
            ]
            start = min(record.uploaded_at for record in all_in_chat)
            end = max(record.uploaded_at for record in all_in_chat)
            try:
                messages = self._export_messages(
                    key[0], key[1],
                    self._window_start(start),
                    self._window_end(end),
                )
                self._match_records(pending, messages, key[1])
            except Exception:
                for record in pending:
                    record.status = "unverified"
                    record.error_code = "TELEGRAM_UPLOAD_VERIFY_EXPORT_FAILED"
            for record in pending:
                if record.status == "pending":
                    record.status = "unverified"
                    record.error_code = "TELEGRAM_UPLOAD_NOT_FOUND"

        return records

    @property
    def records(self) -> list[TelegramUploadVerification]:
        with self._lock:
            return list(self._records)

    def _window_start(self, timestamp: float) -> int:
        return max(0, int(float(timestamp)) - self._window_seconds)

    def _window_end(self, timestamp: float) -> int:
        return int(float(timestamp)) + self._window_seconds

    def _match_records(
        self,
        records: list[TelegramUploadVerification],
        raw_messages: Any,
        chat_ref: str,
    ) -> None:
        with self._lock:
            messages = getattr(raw_messages, "messages", raw_messages)
            if not isinstance(messages, list):
                raise ValueError("TDL time-range export did not return a messages array.")
            candidates = [
                message for message in messages
                if isinstance(message, dict) and self._message_id(message) is not None
            ]
            candidates.sort(key=self._message_sort_key)
            used = self._used_message_ids.setdefault(chat_ref, set())

            # Earlier uploads get first choice among multiple matching messages.
            for record in sorted(records, key=lambda item: item.uploaded_at):
                if record.status == "verified":
                    continue
                expected_name = record.filename
                expected_caption = record.caption
                matching = [
                    message for message in candidates
                    if self._message_id(message) not in used
                    and expected_name in self._message_filenames(message)
                    and self._caption_matches(message, expected_caption)
                ]
                if not matching:
                    continue
                message = min(
                    matching,
                    key=lambda candidate: self._message_distance(candidate, record.uploaded_at),
                )
                message_id = self._message_id(message)
                if message_id is None:
                    continue
                used.add(message_id)
                record.status = "verified"
                record.message_id = message_id
                record.error_code = ""

    @classmethod
    def _message_filenames(cls, message: dict[str, Any]) -> set[str]:
        names: set[str] = set()

        def visit(value: Any, *, inside_file: bool = False) -> None:
            if isinstance(value, dict):
                for raw_key, child in value.items():
                    key = str(raw_key).lower()
                    if (
                        (key in _FILENAME_KEYS or (inside_file and key == "name"))
                        and isinstance(child, str)
                    ) or (key == "file" and isinstance(child, str)):
                        name = child.replace("\\", "/").rsplit("/", 1)[-1]
                        if name:
                            names.add(name)
                    if isinstance(child, (dict, list)):
                        visit(child, inside_file=inside_file or key == "file")
            elif isinstance(value, list):
                for child in value:
                    if isinstance(child, (dict, list)):
                        visit(child, inside_file=inside_file)

        visit(message)
        return names

    @classmethod
    def _caption_matches(cls, message: dict[str, Any], expected: str) -> bool:
        captions: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for raw_key, child in value.items():
                    if str(raw_key).lower() in _CAPTION_KEYS and isinstance(child, str):
                        captions.append(child)
                    elif isinstance(child, (dict, list)):
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    if isinstance(child, (dict, list)):
                        visit(child)

        visit(message)
        return any(expected == caption for caption in captions) or (not expected and not captions)

    @staticmethod
    def _message_id(message: dict[str, Any]) -> int | None:
        value = message.get("id")
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return None
        return value

    @classmethod
    def _message_timestamp(cls, message: dict[str, Any]) -> float | None:
        value = message.get("date", message.get("timestamp"))
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None

    @classmethod
    def _message_distance(cls, message: dict[str, Any], timestamp: float) -> tuple[float, int]:
        message_time = cls._message_timestamp(message)
        delta = abs(message_time - timestamp) if message_time is not None else float("inf")
        return delta, cls._message_id(message) or 0

    @classmethod
    def _message_sort_key(cls, message: dict[str, Any]) -> tuple[float, int]:
        message_time = cls._message_timestamp(message)
        return (
            message_time if message_time is not None else float("inf"),
            cls._message_id(message) or 0,
        )
