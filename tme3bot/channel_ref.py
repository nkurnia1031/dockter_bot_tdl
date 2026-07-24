"""Normalize Telegram private channel links and compact numeric references."""

from __future__ import annotations

import re


def compact_channel_ref(raw: str) -> str:
    value = str(raw or "").strip()
    match = re.search(r"t\.me/c/(\d+)", value, re.IGNORECASE)
    if match:
        return match.group(1)
    if value.startswith("-100") and value[4:].isdigit():
        return value[4:]
    return value


def channel_chat_id(raw: str) -> int:
    value = compact_channel_ref(raw)
    if value.isdigit():
        return -int("100" + value)
    if value.startswith("-") and value[1:].isdigit():
        return int(value)
    return 0


def channel_tdl_ref(raw: str) -> str:
    value = compact_channel_ref(raw)
    if value.isdigit():
        return str(channel_chat_id(value))
    return value
