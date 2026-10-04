from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit


class TrustedDeviceError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def canonical_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or "\r" in value
        or "\n" in value
    ):
        raise TrustedDeviceError("Origin harus berupa URL HTTPS tanpa path.")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = parsed.port
    return f"https://{host}{f':{port}' if port and port != 443 else ''}"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class WindowsDpapi:
    """Current-user DPAPI wrapper. Machine-scope protection is never requested."""

    @staticmethod
    def _blob(data: bytes):
        storage = ctypes.create_string_buffer(data, len(data))
        return _DataBlob(len(data), ctypes.cast(storage, ctypes.POINTER(ctypes.c_ubyte))), storage

    def _crypt(self, data: bytes, entropy: bytes, *, protect: bool) -> bytes:
        if os.name != "nt":
            raise TrustedDeviceError("DPAPI perangkat hanya tersedia di Windows.")
        source, source_buffer = self._blob(data)
        extra, entropy_buffer = self._blob(entropy)
        output = _DataBlob()
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if protect:
            function = crypt32.CryptProtectData
            function.argtypes = [
                ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.POINTER(_DataBlob),
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                ctypes.POINTER(_DataBlob),
            ]
            function.restype = ctypes.c_int
            ok = function(ctypes.byref(source), "tme3 trusted device", ctypes.byref(extra), None, None, 0, ctypes.byref(output))
        else:
            function = crypt32.CryptUnprotectData
            function.argtypes = [
                ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_wchar_p),
                ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_uint32, ctypes.POINTER(_DataBlob),
            ]
            function.restype = ctypes.c_int
            description = ctypes.c_wchar_p()
            ok = function(ctypes.byref(source), ctypes.byref(description), ctypes.byref(extra), None, None, 0, ctypes.byref(output))
            if description:
                kernel32.LocalFree(description)
        # Keep input buffers alive until DPAPI returns.
        _ = source_buffer, entropy_buffer
        if not ok:
            raise TrustedDeviceError("DPAPI menolak credential perangkat pada akun Windows ini.")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    def protect(self, data: bytes, entropy: bytes) -> bytes:
        return self._crypt(data, entropy, protect=True)

    def unprotect(self, data: bytes, entropy: bytes) -> bytes:
        return self._crypt(data, entropy, protect=False)


class TrustedDeviceStore:
    def __init__(
        self,
        origin: str,
        *,
        base_dir: Path | None = None,
        protector=None,
        acl_applier: Callable[[Path], None] | None = None,
    ) -> None:
        self.origin = canonical_origin(origin)
        if base_dir is None:
            local = os.environ.get("LOCALAPPDATA")
            if not local:
                raise TrustedDeviceError("LOCALAPPDATA pengguna Windows tidak tersedia.")
            base_dir = Path(local) / "Tme3Bot" / "trusted-devices"
        origin_key = hashlib.sha256(self.origin.encode("utf-8")).hexdigest()[:24]
        self.root = Path(base_dir) / origin_key
        self.credentials_path = self.root / "device.json"
        self.enrollment_path: Path | None = None
        self.states = self.root / "states"
        self.protector = protector or WindowsDpapi()
        self.acl_applier = acl_applier or self._apply_windows_acl

    @staticmethod
    def _apply_windows_acl(path: Path) -> None:
        if os.name != "nt":
            raise TrustedDeviceError("ACL DPAPI hanya didukung pada Windows.")
        identity = subprocess.run(
            ["whoami"], capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()
        if not identity:
            raise TrustedDeviceError("Identitas akun Windows tidak dapat diperiksa.")
        root = path.resolve()
        targets = [path]
        if path.is_dir():
            targets.extend(sorted(path.rglob("*"), key=lambda item: len(item.parts)))
        for target in targets:
            resolved = target.resolve()
            if target.is_symlink() or (resolved != root and root not in resolved.parents):
                raise TrustedDeviceError("Path ACL keluar dari direktori credential.")
            if target.is_dir():
                grants = [f"{identity}:(OI)(CI)F", "SYSTEM:(OI)(CI)F"]
            else:
                grants = [f"{identity}:F", "SYSTEM:F"]
            subprocess.run(
                ["icacls", str(target), "/inheritance:r", "/grant:r", *grants],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=20,
            )

    def _prepare_private_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.acl_applier(path)

    def _entropy(self) -> bytes:
        return hashlib.sha256(("tme3-device:" + self.origin).encode("utf-8")).digest()

    def has_credentials(self) -> bool:
        return self.credentials_path.is_file()

    def save_credentials(self, *, device_id: str, name: str, public_key: bytes, private_key: bytes) -> dict:
        self._prepare_private_dir(self.root)
        if self.credentials_path.exists():
            raise TrustedDeviceError("Credential sudah ada. Gunakan status atau forget-local dahulu.")
        encrypted = self.protector.protect(private_key, self._entropy())
        document = {
            "version": 1,
            "origin": self.origin,
            "device_id": device_id,
            "name": name,
            "algorithm": "Ed25519",
            "public_key": _b64(public_key),
            "fingerprint": "SHA256:" + base64.b64encode(hashlib.sha256(public_key).digest()).decode("ascii").rstrip("="),
            "private_key_dpapi": _b64(encrypted),
        }
        self._write_exclusive(self.credentials_path, json.dumps(document, separators=(",", ":")).encode("utf-8"))
        public_document = {key: value for key, value in document.items() if key != "private_key_dpapi"}
        self.enrollment_path = self.root / f"enrollment-{device_id}.json"
        self._write_exclusive(self.enrollment_path, json.dumps(public_document, indent=2).encode("utf-8"))
        return public_document

    @staticmethod
    def _write_exclusive(path: Path, payload: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def credentials(self) -> tuple[dict, bytes]:
        if not self.credentials_path.is_file():
            raise TrustedDeviceError("Credential perangkat lokal belum dibuat.")
        try:
            document = json.loads(self.credentials_path.read_text(encoding="utf-8"))
            if document.get("origin") != self.origin or document.get("version") != 1:
                raise ValueError("Credential origin/version tidak cocok.")
            encrypted = _unb64(document["private_key_dpapi"])
            private_key = self.protector.unprotect(encrypted, self._entropy())
            if len(private_key) != 32:
                raise ValueError("Panjang private key tidak valid.")
            return document, private_key
        except TrustedDeviceError:
            raise
        except Exception as exc:
            raise TrustedDeviceError("Credential perangkat rusak atau origin tidak cocok.") from exc

    def new_browser_state_path(self) -> Path:
        self._prepare_private_dir(self.root)
        self._prepare_private_dir(self.states)
        return self.states / f"browser-{uuid.uuid4()}.json"

    def write_browser_state(self, path: Path, document: dict) -> None:
        states_root = self.states.resolve()
        if path.parent.resolve() != states_root or not path.name.startswith("browser-") or path.suffix != ".json":
            raise TrustedDeviceError("Lokasi browser state di luar direktori aplikasi.")
        self._write_exclusive(path, json.dumps(document, separators=(",", ":")).encode("utf-8"))

    def clean_stale_states(self, *, now: float | None = None) -> None:
        if not self.states.exists():
            return
        current = datetime.now(timezone.utc).timestamp() if now is None else now
        root = self.states.resolve()
        for path in self.states.glob("browser-*.json"):
            try:
                info = path.lstat()
                if stat.S_ISREG(info.st_mode) and path.resolve().parent == root and current - info.st_mtime > 300:
                    path.unlink()
            except OSError:
                continue

    def status(self) -> dict:
        document, _ = self.credentials()
        return {
            "device_id": str(document["device_id"]),
            "name": str(document["name"]),
            "origin": self.origin,
            "fingerprint": str(document["fingerprint"]),
            "credential_configured": True,
        }

    def forget_local(self) -> None:
        if self.root.exists():
            # The path is derived from a fixed app directory and a hash of the pinned origin.
            expected_base = self.root.parent.resolve()
            if self.root.resolve().parent != expected_base:
                raise TrustedDeviceError("Direktori credential tidak sesuai.")
            shutil.rmtree(self.root)


def create_device_keypair() -> tuple[str, bytes, bytes]:
    if platform.system() != "Windows":
        raise TrustedDeviceError("Helper trusted device hanya tersedia di Windows.")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return str(uuid.uuid4()), public, raw_private
