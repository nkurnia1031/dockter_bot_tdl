"""Canonical chat references for TDL commands and Telegram Bot API targets."""

from __future__ import annotations

import re
from urllib.parse import urlparse


_USERNAME = re.compile(r"@?([A-Za-z0-9_]{5,32})\Z")
_NUMBER = re.compile(r"-?\d+\Z")
_PHONE = re.compile(r"\+\s*[0-9][0-9\s().-]*[0-9]\Z")


def normalize_tdl_chat_ref(raw: str) -> str:
    """Return a canonical TDL peer selector or raise for unsupported input.

    TDL accepts numeric IDs, usernames, public t.me links, and international
    phone numbers. Usernames and public links become a lowercase username;
    phone punctuation and whitespace are removed.
    """
    value = str(raw or "").strip()
    if not value:
        raise ValueError("Referensi chat wajib diisi.")

    if _NUMBER.fullmatch(value):
        return value

    if _PHONE.fullmatch(value):
        digits = re.sub(r"\D", "", value)
        if 7 <= len(digits) <= 15:
            return "+" + digits
        raise ValueError("Nomor telepon harus berisi 7 sampai 15 digit.")

    if value.lower().startswith(("http://", "https://")):
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() not in {"http", "https"} or host not in {"t.me", "www.t.me"}:
            raise ValueError("Link publik harus menggunakan https://t.me/<username>.")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0].lower() == "c" and parts[1].isdigit():
            return parts[1]
        if len(parts) == 2 and parts[1].isdigit() and _USERNAME.fullmatch(parts[0]):
            return parts[0].casefold()
        if len(parts) == 1 and _USERNAME.fullmatch(parts[0]):
            return parts[0].casefold()
        raise ValueError("Link chat harus berupa https://t.me/<username>.")

    match = _USERNAME.fullmatch(value)
    if match:
        return match.group(1).casefold()

    raise ValueError(
        "Gunakan @username, username, ID numeric, link https://t.me/<username>, "
        "atau nomor telepon internasional seperti +1 123456789."
    )


def normalize_bot_api_chat_ref(raw: str) -> str:
    """Return the Bot API chat_id representation for an ID or public username."""
    raw_value = str(raw or "").strip()
    value = normalize_tdl_chat_ref(raw_value)
    if value.startswith("+"):
        raise ValueError(
            "Telegram Bot API tidak dapat mengirim ke nomor telepon. "
            "Gunakan ID numeric atau username publik channel/grup."
        )
    if _NUMBER.fullmatch(value):
        parsed = urlparse(raw_value)
        parts = [part for part in parsed.path.split("/") if part] if parsed.scheme else []
        if len(parts) >= 2 and parts[0].lower() == "c" and parts[1].isdigit():
            return f"-100{parts[1]}"
        return value
    return f"@{value}"


def canonical_chat_key(raw: str) -> str:
    """Canonicalize aliases for source state while preserving legacy keys."""
    value = str(raw or "").strip()
    if not value:
        return ""
    try:
        return normalize_tdl_chat_ref(value)
    except ValueError:
        return value.lstrip("@").casefold()
