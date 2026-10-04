from __future__ import annotations

import base64
import hashlib
import re
import sqlite3
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from tme3bot.domain.models import DomainError
from tme3bot.infrastructure.auth import BotAuthService, SqliteAuthRepository, _hash_secret


_PROTOCOL = "tme3-device-auth-v1"
_PURPOSE = "browser-session"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode_b64url(value: str, *, expected_length: int | None = None) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Encoding base64url tidak valid.")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if expected_length is not None and len(raw) != expected_length:
        raise ValueError("Panjang key atau signature tidak valid.")
    return raw


def _canonical_origin(value: str) -> str:
    parsed = urlsplit(str(value).strip())
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or "\r" in value
        or "\n" in value
    ):
        raise ValueError("Origin harus berupa origin HTTPS tanpa path.")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = parsed.port
    suffix = f":{port}" if port and port != 443 else ""
    return f"https://{host}{suffix}"


def challenge_payload(
    *, origin: str, device_id: str, challenge_id: str, nonce: str, expires_unix: int
) -> bytes:
    fields = (_PROTOCOL, _PURPOSE, origin, device_id, challenge_id, nonce, str(expires_unix))
    if any("\r" in field or "\n" in field for field in fields):
        raise ValueError("Field challenge tidak valid.")
    return "\n".join(fields).encode("utf-8")


class DeviceAuthService:
    """Approved public-key devices that can mint ordinary Web sessions."""

    def __init__(
        self,
        repository: SqliteAuthRepository,
        auth: BotAuthService,
        configured_origin: str,
    ) -> None:
        self.repository = repository
        self.auth = auth
        try:
            self.origin = _canonical_origin(configured_origin)
        except (TypeError, ValueError):
            self.origin = ""

    def _require_origin(self) -> str:
        if not self.origin:
            raise DomainError(
                "DEVICE_AUTH_UNAVAILABLE",
                "Autentikasi perangkat belum dikonfigurasi untuk origin HTTPS.",
                status_code=503,
            )
        return self.origin

    @staticmethod
    def _metadata(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "algorithm": "Ed25519",
            "fingerprint": str(row["fingerprint"]),
            "origin": str(row["origin"]),
            "created_at": str(row["created_at"]),
            "last_used_at": row.get("last_used_at"),
            "revoked_at": row.get("revoked_at"),
            "status": "revoked" if row.get("revoked_at") else "active",
        }

    def register(
        self,
        telegram_user_id: int,
        *,
        device_id: str,
        name: str,
        algorithm: str,
        public_key: str,
        origin: str,
    ) -> tuple[dict[str, Any], bool]:
        expected_origin = self._require_origin()
        try:
            normalized_origin = _canonical_origin(origin)
            if str(uuid.UUID(device_id)) != device_id:
                raise ValueError("ID perangkat tidak valid.")
            key = _decode_b64url(public_key, expected_length=32)
        except (TypeError, ValueError, UnicodeError) as exc:
            raise DomainError("DEVICE_ENROLLMENT_INVALID", "Data pendaftaran perangkat tidak valid.", status_code=422) from exc
        clean_name = str(name).strip()
        if algorithm != "Ed25519" or normalized_origin != expected_origin:
            raise DomainError("DEVICE_ENROLLMENT_INVALID", "Algoritme atau origin perangkat tidak cocok.", status_code=422)
        if not clean_name or len(clean_name) > 80 or "\r" in clean_name or "\n" in clean_name:
            raise DomainError("DEVICE_NAME_INVALID", "Nama perangkat harus 1–80 karakter.", status_code=422)
        fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key).digest()).decode("ascii").rstrip("=")
        try:
            row, result = self.repository.register_device(
                device_id=device_id,
                telegram_user_id=int(telegram_user_id),
                name=clean_name,
                public_key=key,
                fingerprint=fingerprint,
                origin=expected_origin,
                now=_now().isoformat(),
            )
        except sqlite3.IntegrityError as exc:
            # Do not expose SQLite constraint text or stored key material.
            raise DomainError("DEVICE_ENROLLMENT_CONFLICT", "Perangkat atau key sudah terdaftar.", status_code=409) from exc
        if result == "conflict" or row is None:
            raise DomainError("DEVICE_ENROLLMENT_CONFLICT", "Perangkat atau key sudah terdaftar.", status_code=409)
        return self._metadata(row), result == "created"

    def list_for_actor(self, telegram_user_id: int) -> list[dict[str, Any]]:
        return [self._metadata(row) for row in self.repository.list_devices(telegram_user_id)]

    def rename(self, telegram_user_id: int, device_id: str, name: str) -> dict[str, Any]:
        clean_name = str(name).strip()
        if not clean_name or len(clean_name) > 80 or "\r" in clean_name or "\n" in clean_name:
            raise DomainError("DEVICE_NAME_INVALID", "Nama perangkat harus 1–80 karakter.", status_code=422)
        if not self.repository.rename_device(device_id, telegram_user_id, clean_name, _now().isoformat()):
            raise DomainError("DEVICE_NOT_FOUND", "Perangkat aktif tidak ditemukan.", status_code=404)
        row = self.repository.get_device(device_id)
        return self._metadata(row) if row else {}

    def revoke(self, telegram_user_id: int, device_id: str) -> bool:
        if not self.repository.revoke_device(device_id, telegram_user_id, _now().isoformat()):
            raise DomainError("DEVICE_NOT_FOUND", "Perangkat tidak ditemukan.", status_code=404)
        return True

    def create_challenge(self, device_id: str, remote_key: str) -> dict[str, Any]:
        origin = self._require_origin()
        challenge_id = str(uuid.uuid4())
        nonce = _b64url(secrets.token_bytes(32))
        expires = _now() + timedelta(seconds=120)
        expires_unix = int(expires.timestamp())
        payload = challenge_payload(
            origin=origin,
            device_id=device_id,
            challenge_id=challenge_id,
            nonce=nonce,
            expires_unix=expires_unix,
        )
        created_at = _now()
        row, result = self.repository.create_device_challenge(
            device_id=device_id,
            challenge_id=challenge_id,
            origin=origin,
            nonce=nonce,
            signed_payload=payload,
            created_at=created_at.isoformat(),
            expires_at=expires.isoformat(),
            now_epoch=int(created_at.timestamp()),
            remote_key=hashlib.sha256(remote_key.encode("utf-8")).hexdigest(),
        )
        if result == "rate_limited":
            raise DomainError("DEVICE_RATE_LIMITED", "Terlalu banyak percobaan autentikasi perangkat.", status_code=429)
        if row is None:
            raise DomainError("DEVICE_AUTH_INVALID", "Perangkat tidak dapat diautentikasi.", status_code=401)
        return {
            "challenge_id": challenge_id,
            "device_id": device_id,
            "nonce": nonce,
            "origin": origin,
            "protocol_version": _PROTOCOL,
            "expires_at": expires.isoformat(),
            "expires_unix": expires_unix,
        }

    def exchange(self, device_id: str, challenge_id: str, signature: str, remote_key: str):
        origin = self._require_origin()
        row, result = self.repository.begin_device_exchange(
            device_id=device_id,
            challenge_id=challenge_id,
            now_epoch=int(_now().timestamp()),
            remote_key=hashlib.sha256(remote_key.encode("utf-8")).hexdigest(),
        )
        if result == "rate_limited":
            raise DomainError("DEVICE_RATE_LIMITED", "Terlalu banyak percobaan autentikasi perangkat.", status_code=429)
        if row is None:
            raise DomainError("DEVICE_AUTH_INVALID", "Challenge perangkat tidak valid.", status_code=401)
        try:
            signature_bytes = _decode_b64url(signature, expected_length=64)
            key = Ed25519PublicKey.from_public_bytes(bytes(row["public_key"]))
            key.verify(signature_bytes, bytes(row["signed_payload"]))
        except (ValueError, InvalidSignature) as exc:
            raise DomainError("DEVICE_AUTH_INVALID", "Challenge perangkat tidak valid.", status_code=401) from exc
        if row["origin"] != origin or row["device_origin"] != origin:
            raise DomainError("DEVICE_AUTH_INVALID", "Challenge perangkat tidak valid.", status_code=401)
        now = _now()
        if datetime.fromisoformat(str(row["expires_at"])) <= now:
            raise DomainError("DEVICE_CHALLENGE_EXPIRED", "Challenge perangkat telah kedaluwarsa.", status_code=410)
        actor = self.auth.actor_resolver(int(row["telegram_user_id"]))
        if not getattr(actor, "authorized", True):
            raise DomainError("UNAUTHORIZED_ACTOR", "Actor tidak lagi diizinkan.", status_code=403)
        refresh_token = secrets.token_urlsafe(48)
        session_id, user_id, result = self.repository.complete_device_exchange(
            device_id=device_id,
            challenge_id=challenge_id,
            origin=origin,
            signed_payload=bytes(row["signed_payload"]),
            now=now.isoformat(),
            refresh_token_hash=_hash_secret(refresh_token),
            session_expires_at=(now + timedelta(days=self.auth.refresh_days)).isoformat(),
        )
        if result == "expired":
            raise DomainError("DEVICE_CHALLENGE_EXPIRED", "Challenge perangkat telah kedaluwarsa.", status_code=410)
        if result != "created" or session_id is None or user_id is None:
            raise DomainError("DEVICE_AUTH_INVALID", "Challenge perangkat tidak valid atau sudah digunakan.", status_code=401)
        pair = self.auth.new_device_web_session(user_id, device_id, session_id, refresh_token)
        return pair
