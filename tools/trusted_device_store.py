from __future__ import annotations

import base64
import ctypes
import getpass
import hashlib
import hmac
import json
import os
import platform
import secrets
import shutil
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


class TrustedDeviceError(RuntimeError):
    pass


ENROLLMENT_VERSION = 1


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


class LinuxPassphraseProtector:
    """Encrypt a device key with a passphrase that is never persisted by the helper."""

    _SCRYPT_N = 2**14
    _SCRYPT_R = 8
    _SCRYPT_P = 1

    @staticmethod
    def _read_passphrase(*, confirm: bool) -> bytes:
        if not sys.stdin.isatty():
            raise TrustedDeviceError(
                "Linux memerlukan terminal interaktif untuk passphrase trusted device."
            )
        try:
            first = getpass.getpass("Passphrase trusted device: ")
            if confirm:
                second = getpass.getpass("Ulangi passphrase trusted device: ")
                if not hmac.compare_digest(first, second):
                    raise TrustedDeviceError("Passphrase tidak cocok.")
            if len(first) < 12:
                raise TrustedDeviceError("Passphrase trusted device harus minimal 12 karakter.")
            return first.encode("utf-8")
        except (EOFError, OSError) as exc:
            raise TrustedDeviceError("Passphrase trusted device tidak dapat dibaca.") from exc

    @classmethod
    def _derive_key(cls, passphrase: bytes, salt: bytes) -> bytes:
        return Scrypt(
            salt=salt,
            length=32,
            n=cls._SCRYPT_N,
            r=cls._SCRYPT_R,
            p=cls._SCRYPT_P,
        ).derive(passphrase)

    def protect(self, data: bytes, entropy: bytes) -> bytes:
        passphrase = self._read_passphrase(confirm=True)
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._derive_key(passphrase, salt)).encrypt(nonce, data, entropy)
        envelope = {
            "version": 1,
            "kdf": "scrypt",
            "n": self._SCRYPT_N,
            "r": self._SCRYPT_R,
            "p": self._SCRYPT_P,
            "salt": _b64(salt),
            "nonce": _b64(nonce),
            "ciphertext": _b64(ciphertext),
        }
        return json.dumps(envelope, separators=(",", ":")).encode("utf-8")

    def unprotect(self, data: bytes, entropy: bytes) -> bytes:
        try:
            envelope = json.loads(data.decode("utf-8"))
            if (
                envelope.get("version") != 1
                or envelope.get("kdf") != "scrypt"
                or envelope.get("n") != self._SCRYPT_N
                or envelope.get("r") != self._SCRYPT_R
                or envelope.get("p") != self._SCRYPT_P
            ):
                raise ValueError("Unsupported key envelope")
            salt = _unb64(envelope["salt"])
            nonce = _unb64(envelope["nonce"])
            ciphertext = _unb64(envelope["ciphertext"])
            if len(salt) != 16 or len(nonce) != 12:
                raise ValueError("Invalid key envelope")
        except (AttributeError, KeyError, TypeError, UnicodeError, ValueError) as exc:
            raise TrustedDeviceError("Credential Linux rusak atau format enkripsinya tidak dikenal.") from exc

        passphrase = self._read_passphrase(confirm=False)
        try:
            return AESGCM(self._derive_key(passphrase, salt)).decrypt(nonce, ciphertext, entropy)
        except InvalidTag as exc:
            raise TrustedDeviceError("Passphrase salah atau credential Linux rusak.") from exc


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
            system = platform.system()
            if system == "Windows":
                local = os.environ.get("LOCALAPPDATA")
                if not local:
                    raise TrustedDeviceError("LOCALAPPDATA pengguna Windows tidak tersedia.")
                base_dir = Path(local) / "Tme3Bot" / "trusted-devices"
            elif system == "Linux":
                config_home = os.environ.get("XDG_CONFIG_HOME", "")
                config_root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
                if not config_root.is_absolute():
                    config_root = Path.home() / ".config"
                base_dir = config_root / "tme3bot" / "trusted-devices"
            else:
                raise TrustedDeviceError("Helper trusted device hanya tersedia di Windows dan Linux.")
        origin_key = hashlib.sha256(self.origin.encode("utf-8")).hexdigest()[:24]
        self.root = Path(base_dir) / origin_key
        self.credentials_path = self.root / "device.json"
        self.enrollment_path: Path | None = None
        self.states = self.root / "states"
        if protector is not None:
            self.protector = protector
        elif platform.system() == "Windows":
            self.protector = WindowsDpapi()
        elif platform.system() == "Linux":
            self.protector = LinuxPassphraseProtector()
        else:
            raise TrustedDeviceError("Helper trusted device hanya tersedia di Windows dan Linux.")
        if acl_applier is not None:
            self.acl_applier = acl_applier
        elif platform.system() == "Windows":
            self.acl_applier = self._apply_windows_acl
        else:
            self.acl_applier = self._apply_linux_permissions

    @staticmethod
    def _apply_linux_permissions(path: Path) -> None:
        if platform.system() != "Linux":
            raise TrustedDeviceError("Permission privat POSIX hanya didukung pada Linux.")
        root = path.resolve()
        targets = [path]
        if path.is_dir():
            targets.extend(sorted(path.rglob("*"), key=lambda item: len(item.parts)))
        for target in targets:
            try:
                info = target.lstat()
                resolved = target.resolve()
            except OSError as exc:
                raise TrustedDeviceError("Direktori credential Linux tidak dapat diperiksa.") from exc
            if (
                target.is_symlink()
                or (resolved != root and root not in resolved.parents)
                or info.st_uid != os.getuid()
                or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
            ):
                raise TrustedDeviceError("Path credential Linux harus berupa file/direktori milik user tanpa symlink.")
            try:
                os.chmod(target, 0o700 if stat.S_ISDIR(info.st_mode) else 0o600)
            except OSError as exc:
                raise TrustedDeviceError("Permission privat credential Linux tidak dapat diterapkan.") from exc

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
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.acl_applier(path)

    def _entropy(self) -> bytes:
        return hashlib.sha256(("tme3-device:" + self.origin).encode("utf-8")).digest()

    def has_credentials(self) -> bool:
        return self.credentials_path.is_file()

    def save_credentials(self, *, device_id: str, name: str, public_key: bytes, private_key: bytes) -> dict:
        self._prepare_private_dir(self.root)
        if self.credentials_path.exists():
            raise TrustedDeviceError("Credential sudah ada. Gunakan status atau forget-local dahulu.")
        protected = self.protector.protect(private_key, self._entropy())
        if platform.system() == "Windows":
            protection_field = "private_key_dpapi"
            version = 1
        else:
            protection_field = "private_key_scrypt"
            version = 2
        document = {
            "version": version,
            "origin": self.origin,
            "device_id": device_id,
            "name": name,
            "algorithm": "Ed25519",
            "public_key": _b64(public_key),
            "fingerprint": "SHA256:" + base64.b64encode(hashlib.sha256(public_key).digest()).decode("ascii").rstrip("="),
            protection_field: _b64(protected),
        }
        self._write_exclusive(self.credentials_path, json.dumps(document, separators=(",", ":")).encode("utf-8"))
        public_document = {
            key: value
            for key, value in document.items()
            if key not in {"private_key_dpapi", "private_key_scrypt"}
        }
        # The local credential's version describes its platform-specific key
        # protection format. Enrollment files always use the Web protocol v1.
        public_document["version"] = ENROLLMENT_VERSION
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
        if platform.system() == "Linux" and self.root.exists():
            self._apply_linux_permissions(self.root)
        if not self.credentials_path.is_file():
            raise TrustedDeviceError("Credential perangkat lokal belum dibuat.")
        try:
            document = json.loads(self.credentials_path.read_text(encoding="utf-8"))
            expected_version = 1 if platform.system() == "Windows" else 2
            protection_field = "private_key_dpapi" if platform.system() == "Windows" else "private_key_scrypt"
            if document.get("origin") != self.origin or document.get("version") != expected_version:
                raise ValueError("Credential origin/version tidak cocok.")
            encrypted = _unb64(document[protection_field])
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
        if self.root.is_symlink():
            raise TrustedDeviceError("Direktori credential tidak boleh berupa symlink.")
        if platform.system() == "Linux" and self.root.exists():
            self._apply_linux_permissions(self.root)
        if not self.states.exists():
            return
        expected_root = self.root.resolve()
        if self.states.is_symlink() or self.states.resolve().parent != expected_root:
            raise TrustedDeviceError("Direktori browser state harus berada di dalam direktori credential.")
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
    if platform.system() not in {"Windows", "Linux"}:
        raise TrustedDeviceError("Helper trusted device hanya tersedia di Windows dan Linux.")
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
