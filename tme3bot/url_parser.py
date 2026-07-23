from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse


class URLParseError(ValueError):
    """Raised when the inbound text is not a supported Telegram URL."""


@dataclass(frozen=True)
class ParsedTme3Url:
    original_url: str
    chat_ref: str
    bootstrap_message_id: int
    requested_label: str | None
    canonical_label: str


def slugify_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_value.strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-._")
    return cleaned or "download"


def parse_tme3_url(raw_url: str, expected_host: str) -> ParsedTme3Url:
    url = raw_url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise URLParseError("URL harus memakai http:// atau https://")

    host = (parsed.netloc or "").strip().lower()
    expected = expected_host.strip().lower()
    accepted_hosts = {expected, f"www.{expected}", "t.me", "www.t.me"}
    if host not in accepted_hosts:
        raise URLParseError(f"Hanya host {expected_host} atau t.me yang diterima.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[0] != "c":
        raise URLParseError(
            "Format wajib /c/<chat_ref>/<message_id> dengan label opsional untuk host t.me3."
        )

    chat_ref = parts[1].strip()
    if not chat_ref:
        raise URLParseError("chat_ref tidak boleh kosong.")

    try:
        message_id = int(parts[2])
    except ValueError as exc:
        raise URLParseError("message_id harus berupa angka.") from exc

    if message_id <= 0:
        raise URLParseError("message_id harus lebih besar dari 0.")

    requested_label = parts[3].strip() if len(parts) >= 4 and parts[3].strip() else None
    fallback_label = chat_ref.lstrip("@") or chat_ref
    canonical_label = slugify_label(requested_label or fallback_label)

    return ParsedTme3Url(
        original_url=url,
        chat_ref=chat_ref,
        bootstrap_message_id=message_id,
        requested_label=requested_label,
        canonical_label=canonical_label,
    )
