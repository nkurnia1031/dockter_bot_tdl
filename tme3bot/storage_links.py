"""Compact, stable HMAC tokens for Telegram storage deep links."""

from __future__ import annotations

import base64
import hashlib
import hmac

DOMAIN = b"tme3bot:storage-link:v1:"


def sign_storage_item(item_id: int, secret: str) -> str:
    value = str(int(item_id))
    digest = hmac.new(secret.encode(), DOMAIN + value.encode(), hashlib.sha256).digest()[:12]
    return f"{value}.{base64.urlsafe_b64encode(digest).decode().rstrip('=')}"


def verify_storage_item(token: str, secret: str) -> int:
    try:
        value, _signature = token.split(".", 1)
        item_id = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Token storage tidak valid.") from exc
    expected = sign_storage_item(item_id, secret)
    if not hmac.compare_digest(token, expected):
        raise ValueError("Signature storage tidak valid.")
    return item_id
