"""Normalize Telegram private channel links and compact numeric references."""

from __future__ import annotations

import re

from tme3bot.chat_refs import normalize_tdl_chat_ref


def compact_channel_ref(raw: str) -> str:
    value = str(raw or "").strip()
    match = re.search(r"(?:https?://)?(?:www\.)?t\.me/c/(\d+)", value, re.IGNORECASE)
    if match:
        return match.group(1)
    if value.startswith("-100") and value[4:].isdigit():
        return value[4:]
    try:
        return normalize_tdl_chat_ref(value)
    except ValueError:
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
