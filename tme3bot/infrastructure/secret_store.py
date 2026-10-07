from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class AesGcmSecretStore:
    """Encrypt setting values with a persistent owner-only AES-256 key."""

    def __init__(self, key_path: Path, *, require_existing_key: bool = False) -> None:
        self.key_path = Path(key_path)
        self.require_existing_key = bool(require_existing_key)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(self.key_path.parent, 0o700)
        self._key = self._load_or_create_key()

    def encrypt(self, value: str, associated_data: bytes) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + AESGCM(self._key).encrypt(
            nonce, str(value).encode("utf-8"), associated_data
        )

    def decrypt(self, ciphertext: bytes, associated_data: bytes) -> str:
        encrypted = bytes(ciphertext or b"")
        if len(encrypted) < 13:
            raise RuntimeError("Ciphertext runtime settings tidak valid.")
        plain = AESGCM(self._key).decrypt(
            encrypted[:12], encrypted[12:], associated_data
        )
        return plain.decode("utf-8")

    def _load_or_create_key(self) -> bytes:
        try:
            key = self.key_path.read_bytes()
            if len(key) != 32:
                raise RuntimeError("Kunci runtime settings tidak valid.")
            if os.name == "posix":
                os.chmod(self.key_path, 0o600)
            return key
        except FileNotFoundError:
            if self.require_existing_key:
                raise RuntimeError(
                    "Kunci runtime settings hilang; secret terenkripsi tidak dapat dibuka."
                )
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            key = AESGCM.generate_key(bit_length=256)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            try:
                descriptor = os.open(str(self.key_path), flags, 0o600)
            except FileExistsError:
                key = self.key_path.read_bytes()
                if len(key) != 32:
                    raise RuntimeError("Kunci runtime settings tidak valid.")
                return key
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(key)
                    handle.flush()
                    os.fsync(handle.fileno())
                if os.name == "posix":
                    os.chmod(self.key_path, 0o600)
            except Exception:
                self.key_path.unlink(missing_ok=True)
                raise
            return key
