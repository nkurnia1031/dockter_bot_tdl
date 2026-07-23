from __future__ import annotations

from typing import Any


MEDIA_KEYS = {
    "animation",
    "audio",
    "document",
    "file",
    "file_name",
    "FileName",
    "media",
    "media_type",
    "mime",
    "mime_type",
    "photo",
    "sticker",
    "thumbnail",
    "video",
    "video_note",
    "voice",
}
MEDIA_TYPES = {
    "animation",
    "audio",
    "document",
    "file",
    "photo",
    "sticker",
    "video",
    "video_file",
    "video_note",
    "voice",
}
IMAGE_MARKERS = (".jpg", ".jpeg", ".png", "image/jpeg", "image/png", "photo")


def has_downloadable_media(message: dict[str, Any]) -> bool:
    if any(message.get(key) for key in MEDIA_KEYS):
        return True
    return str(message.get("type") or "").lower() in MEDIA_TYPES


def is_image_message(message: dict[str, Any]) -> bool:
    values = (
        message.get("file_name"),
        message.get("FileName"),
        message.get("name"),
        message.get("mime_type"),
        message.get("mime"),
        message.get("type"),
        message.get("media_type"),
    )
    searchable = " ".join(str(value).lower() for value in values if value)
    return any(marker in searchable for marker in IMAGE_MARKERS)
