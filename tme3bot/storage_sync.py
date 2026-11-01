"""Parsing and completeness rules for Telegram Storage catalog sync."""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any


_STORAGE_MARKER = re.compile(r"(?<![\w])#storage(?![\w])", re.IGNORECASE)
_FIELDS = {
    "folder": re.compile(r"^\s*(?:📁\s*)?Folder:\s*(.*?)\s*$", re.IGNORECASE),
    "name": re.compile(r"^\s*(?:📄\s*)?Name:\s*(.*?)\s*$", re.IGNORECASE),
    "keywords": re.compile(r"^\s*(?:🔑\s*)?Keywords:\s*(.*?)\s*$", re.IGNORECASE),
}


@dataclass(frozen=True)
class ParsedStorageExport:
    message_ids: list[int]
    items: list[dict[str, Any]]


def _message_text(message: dict[str, Any]) -> str:
    candidates: list[str] = []
    for candidate in (message.get("text"), message.get("caption")):
        if isinstance(candidate, str):
            candidates.append(candidate)
    raw = message.get("raw")
    if isinstance(raw, dict):
        for key, value in raw.items():
            if str(key).casefold() in {"message", "text", "caption"} and isinstance(value, str):
                candidates.append(value)
    return next((value for value in candidates if _STORAGE_MARKER.search(value)), "")


def _caption_fields(caption: str) -> dict[str, str] | None:
    if not caption or not _STORAGE_MARKER.search(caption):
        return None
    values: dict[str, str] = {}
    for line in caption.splitlines():
        for field, pattern in _FIELDS.items():
            match = pattern.match(line)
            if match:
                values[field] = " ".join(match.group(1).split()).strip()
    if set(values) != set(_FIELDS):
        return None
    return values


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _file_name(message: dict[str, Any]) -> str:
    direct = message.get("file")
    if isinstance(direct, str) and direct.strip():
        candidate = PurePosixPath(direct.strip().replace("\\", "/")).name
        if candidate:
            return candidate[:300]
    for row in _walk_dicts(message.get("raw")):
        for key, value in row.items():
            if str(key).casefold() in {"file_name", "filename"} and isinstance(value, str) and value.strip():
                return PurePosixPath(value.strip().replace("\\", "/")).name[:300]
    return ""


def _file_size(message: dict[str, Any]) -> int | None:
    raw = message.get("raw")
    if isinstance(raw, dict):
        for row in _walk_dicts(raw):
            if str(row.get("_") or "").casefold() in {"document", "documentattributevideo"}:
                try:
                    size = int(row.get("size"))
                except (TypeError, ValueError):
                    continue
                if size >= 0:
                    return size
    values: list[int] = []
    for row in _walk_dicts(message):
        for key, value in row.items():
            if str(key).casefold() not in {"size", "file_size", "filesize"}:
                continue
            try:
                size = int(value)
            except (TypeError, ValueError):
                continue
            if not isinstance(value, bool) and size >= 0:
                values.append(size)
    return max(values) if values else None


def _mime_type(message: dict[str, Any], name: str) -> str:
    for row in _walk_dicts(message.get("raw")):
        for key, value in row.items():
            if str(key).casefold() in {"mime_type", "mimetype"} and isinstance(value, str) and value.strip():
                return value.strip()[:255]
    return mimetypes.guess_type(name)[0] or ""


def _uploaded_at(message: dict[str, Any]) -> str:
    value = message.get("date")
    if value is None:
        for row in _walk_dicts(message.get("raw")):
            if "date" in row:
                value = row.get("date")
                break
    try:
        timestamp = int(value)
        if timestamp > 0:
            return datetime.fromtimestamp(timestamp, timezone.utc).replace(microsecond=0).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    return ""


def _safe_folder(value: str) -> str | None:
    if value in {"", "-"}:
        return ""
    normalized = value.replace("\\", "/").strip("/")
    parts = normalized.split("/")
    if (
        len(normalized) > 2048
        or not normalized
        or any(not part or part in {".", ".."} for part in parts)
        or any(ord(character) < 32 for character in normalized)
    ):
        return None
    return "/".join(" ".join(part.split()).strip() for part in parts)


def parse_storage_export(messages: list[dict[str, Any]]) -> ParsedStorageExport:
    """Validate message IDs, retain unknown-caption IDs, and parse Storage rows."""
    if not isinstance(messages, list):
        raise ValueError("STORAGE_SYNC_MESSAGES_INVALID")
    message_ids: list[int] = []
    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("STORAGE_SYNC_MESSAGE_INVALID")
        raw_id = message.get("id")
        if isinstance(raw_id, bool):
            raise ValueError("STORAGE_SYNC_MESSAGE_ID_INVALID")
        try:
            message_id = int(raw_id)
        except (TypeError, ValueError):
            raise ValueError("STORAGE_SYNC_MESSAGE_ID_INVALID") from None
        if message_id < 1 or message_id in seen:
            raise ValueError("STORAGE_SYNC_MESSAGE_ID_INVALID")
        seen.add(message_id)
        message_ids.append(message_id)

        caption = _message_text(message)
        fields = _caption_fields(caption)
        if fields is None:
            continue
        folder = _safe_folder(fields["folder"] if fields["folder"] != "-" else "")
        if folder is None:
            continue
        source_name = _file_name(message)
        display_name = fields["name"] if fields["name"] != "-" else source_name
        if not display_name:
            continue
        original_name = source_name or display_name
        keywords = "" if fields["keywords"] == "-" else fields["keywords"][:600]
        items.append({
            "channel_message_id": message_id,
            "original_name": original_name[:300],
            "display_name": display_name[:300],
            "folder": folder,
            "keywords": keywords,
            "caption": caption[:1024],
            "file_size": _file_size(message),
            "mime_type": _mime_type(message, original_name),
            "sha256": "",
            "uploaded_at": _uploaded_at(message),
        })
    message_ids.sort()
    items.sort(key=lambda item: int(item["channel_message_id"]))
    return ParsedStorageExport(message_ids, items)


def full_history_proven(
    coverage: Any,
    *,
    message_ids: list[int],
    batch_count: int,
    reported_message_count: int,
    reported_batch_count: int,
) -> bool:
    """Validate an unbounded TDL export and stable high-water evidence."""
    if not isinstance(coverage, dict):
        return False
    coverage_keys = ("latest_before_id", "latest_after_id", "range_max_id")
    if any(type(coverage.get(key)) is not int for key in coverage_keys):
        return False
    if (
        type(batch_count) is not int
        or type(reported_message_count) is not int
        or type(reported_batch_count) is not int
        or any(type(item) is not int for item in message_ids)
    ):
        return False
    latest_before = coverage["latest_before_id"]
    latest_after = coverage["latest_after_id"]
    range_max = coverage["range_max_id"]
    if len(set(message_ids)) != len(message_ids):
        return False
    return bool(
        coverage.get("strategy") == "tdl_unbounded_export_v1"
        and coverage.get("export_mode") == "all_messages"
        and coverage.get("complete") is True
        and coverage.get("export_succeeded") is True
        and coverage.get("iterator_completed") is True
        and latest_before >= 0
        and latest_before == latest_after == range_max
        and len(message_ids) == reported_message_count
        and batch_count == reported_batch_count
        and all(1 <= item <= latest_before for item in message_ids)
        and (not message_ids if latest_before == 0 else max(message_ids, default=0) == latest_before)
    )
