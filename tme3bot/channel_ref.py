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
    """Return the peer reference format expected by tdl.

    Bot API uses `-100<peer id>` for private channels, while tdl's upload
    command expects the compact numeric peer id without that prefix.
    """
    value = compact_channel_ref(raw)
    if value.isdigit():
        return value
    return value
