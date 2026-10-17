"""Worker-bound encryption for Vault artifacts transported through Telegram."""

from __future__ import annotations

import hashlib
import hmac
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_OPERATION_ID = re.compile(r"[0-9a-fA-F-]{36}\Z")
_PROFILE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
_WORKER = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")


def distribution_aad(operation_id: str, profile: str, revision: int, worker: str) -> bytes:
    if (
        not _OPERATION_ID.fullmatch(str(operation_id or ""))
        or not _PROFILE.fullmatch(str(profile or ""))
        or type(revision) is not int
        or revision < 1
        or not _WORKER.fullmatch(str(worker or ""))
    ):
        raise ValueError("PROFILE_DISTRIBUTION_METADATA_INVALID")
    return f"tme3-profile-distribution-v1\0{operation_id}\0{profile}\0{revision}\0{worker}".encode("ascii")


def _key(worker_token: str, aad: bytes) -> bytes:
    token = str(worker_token or "").encode("utf-8")
    if len(token) < 16:
        raise ValueError("PROFILE_DISTRIBUTION_KEY_UNAVAILABLE")
    return hmac.new(token, b"tme3-profile-distribution-key-v1\0" + aad, hashlib.sha256).digest()


def encrypt_distribution_bundle(
    bundle: bytes, *, worker_token: str, operation_id: str,
    profile: str, revision: int, worker: str,
) -> bytes:
    aad = distribution_aad(operation_id, profile, revision, worker)
    key = _key(worker_token, aad)
    # Each operation/worker tuple has its own derived key, so a stable nonce
    # makes artifact creation idempotent across backend retries.
    nonce = hashlib.sha256(b"tme3-profile-distribution-nonce-v1\0" + aad).digest()[:12]
    return nonce + AESGCM(key).encrypt(nonce, bytes(bundle), aad)


def decrypt_distribution_bundle(
    archive: bytes, *, worker_token: str, operation_id: str,
    profile: str, revision: int, worker: str,
) -> bytes:
    aad = distribution_aad(operation_id, profile, revision, worker)
    if len(archive) < 12 + 16:
        raise ValueError("PROFILE_DISTRIBUTION_ARCHIVE_INVALID")
    nonce, ciphertext = archive[:12], archive[12:]
    expected_nonce = hashlib.sha256(b"tme3-profile-distribution-nonce-v1\0" + aad).digest()[:12]
    if not hmac.compare_digest(nonce, expected_nonce):
        raise ValueError("PROFILE_DISTRIBUTION_BINDING_MISMATCH")
    try:
        return AESGCM(_key(worker_token, aad)).decrypt(nonce, ciphertext, aad)
    except Exception:
        raise ValueError("PROFILE_DISTRIBUTION_ARCHIVE_INVALID") from None
