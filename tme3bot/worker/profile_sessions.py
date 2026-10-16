from __future__ import annotations

import io
import hashlib
import json
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

try:
    import pty
except ImportError:  # pragma: no cover - TDL workers run on Linux.
    pty = None  # type: ignore[assignment]

from tme3bot.domain.models import DomainError
from tme3bot.names import normalize_profile_name
from tme3bot.profile_provisioning import (
    MAX_PROFILE_BUNDLE_BYTES,
    MAX_SESSION_ARCHIVE_BYTES,
    extract_single_session,
    validate_profile_bundle,
)
from tme3bot.persistence import write_json_atomic_private
from tme3bot.profiles import build_profile_config


_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_LOGIN_TTL_SECONDS = 15 * 60
_PHONE_RE = re.compile(r"^[+0-9(). -]{4,32}$")
_PROFILE_INSTALL_LANES = ("root/.tdl", "user1/.tdl", "upload")
_UPLOAD_LANE_MARKER = "upload-lane.json"
_PROFILE_INSTALL_RECEIPTS = ".profile-provisioning-commits.json"
_MAX_PROFILE_INSTALL_RECEIPTS = 100


class _ProfileInstallFailure(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class _LoginProcess:
    operation_id: str
    method: str
    directory: Path
    pid: int
    master_fd: int
    transcript: str = ""
    status: str = "running"
    error: str = ""
    telegram_user_id: int | None = None
    bundle_path: Path | None = None
    exit_code: int | None = None
    created_at: float = field(default_factory=time.monotonic)


class ProfileSessionManager:
    """Narrow TDL login bridge and safe profile session installer for workers."""

    def __init__(self, config: Any) -> None:
        self.config = config
        temp_root = getattr(config, "temp_root", None) or tempfile.gettempdir()
        self.root = Path(temp_root) / "profile-provisioning"
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            self._set_private_tree(self.root)
        self.login_root = self.root / "logins"
        self.login_root.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            self._set_private_tree(self.login_root)
        # Login processes cannot survive a worker restart. Remove only their
        # abandoned temporary sessions; installation rollback backups live in
        # a separate directory and must remain available to the backend.
        for child in self.login_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
        self._lock = threading.RLock()
        self._logins: dict[str, _LoginProcess] = {}

    def start(self, operation_id: str, method: str, phone: str = "") -> dict[str, Any]:
        if pty is None:
            raise RuntimeError("Login interaktif TDL memerlukan worker Linux.")
        method = str(method).strip().lower()
        if method not in {"qr", "code"}:
            raise ValueError("Metode login TDL tidak didukung.")
        phone = str(phone or "").strip()
        if method == "code" and not _PHONE_RE.fullmatch(phone):
            raise ValueError("Nomor telepon tidak valid untuk login kode.")
        operation_id = self._valid_operation_id(operation_id)
        with self._lock:
            for old_id, old in list(self._logins.items()):
                if old.status != "running" and time.monotonic() - old.created_at > _LOGIN_TTL_SECONDS:
                    self._logins.pop(old_id, None)
            existing = self._logins.get(operation_id)
            if existing is not None and existing.status in {"running", "ready"}:
                return self.state(operation_id)
            directory = self.login_root / operation_id
            if directory.exists():
                shutil.rmtree(directory)
            storage_root = directory / "session" / ".tdl"
            storage_root.mkdir(parents=True, exist_ok=True)
            self._set_private_tree(directory)
            command = [
                "tdl", "--storage", f"type=bolt,path={storage_root / 'data'}",
                "-n", str(self.config.tdl_export_namespace), "login", "-T", method,
            ]
            env = dict(os.environ)
            env.update({
                "HOME": str(self.config.tdl_export_home),
                "TERM": "xterm-256color",
                "COLUMNS": "160",
                "LINES": "42",
                "NO_COLOR": "1",
            })
            pid, master = pty.fork()
            if pid == 0:
                try:
                    os.execvpe(command[0], command, env)
                except BaseException:
                    os._exit(127)
            try:
                import termios

                attrs = termios.tcgetattr(master)
                attrs[3] &= ~(termios.ECHO | termios.ECHONL)
                termios.tcsetattr(master, termios.TCSANOW, attrs)
            except Exception:
                pass
            session = _LoginProcess(operation_id, method, directory, pid, master)
            self._logins[operation_id] = session
            if method == "code" and phone.strip():
                # Survey reads a complete line after showing its phone prompt.
                # The PTY has echo disabled so the private input is never echoed.
                time.sleep(0.1)
                os.write(master, phone.strip().encode("utf-8") + b"\n")
            return self.state(operation_id)

    def input(self, operation_id: str, field_name: str, value: str) -> dict[str, Any]:
        operation_id = self._valid_operation_id(operation_id)
        with self._lock:
            session = self._require(operation_id)
            if session.status != "running":
                raise ValueError("Proses login TDL tidak sedang menunggu input.")
            self._drain(session)
            step = self._step(session)
            field_name = str(field_name).strip().lower()
            expected = {"code": "code", "password": "password"}.get(step)
            if field_name != expected:
                raise ValueError("Langkah login sudah berubah; muat ulang status login.")
            value = str(value)
            if not value or len(value) > 256 or "\n" in value or "\r" in value:
                raise ValueError("Input login tidak valid.")
            os.write(session.master_fd, value.encode("utf-8") + b"\n")
            return self.state(operation_id)

    def state(self, operation_id: str) -> dict[str, Any]:
        operation_id = self._valid_operation_id(operation_id)
        with self._lock:
            session = self._require(operation_id)
            self._drain(session)
            self._finish_if_exited(session)
            now = time.monotonic()
            if session.status == "running" and now - session.created_at > _LOGIN_TTL_SECONDS:
                self._terminate(session)
                session.status = "expired"
                session.error = "Sesi login kedaluwarsa. Mulai proses login baru."
                shutil.rmtree(session.directory, ignore_errors=True)
            elif session.status == "ready" and now - session.created_at > _LOGIN_TTL_SECONDS:
                session.status = "expired"
                session.error = "Sesi login kedaluwarsa. Mulai proses login baru."
                shutil.rmtree(session.directory, ignore_errors=True)
            if session.status == "running":
                step = self._step(session)
                result: dict[str, Any] = {"status": "waiting_input", "step": step}
                if step == "qr":
                    result["qr_text"] = self._qr_text(session.transcript)
                return result
            result = {"status": session.status, "step": "", "error": session.error}
            if session.status == "ready" and session.telegram_user_id is not None:
                result["telegram_user_id"] = session.telegram_user_id
            return result

    def bundle_path(self, operation_id: str) -> Path | None:
        state = self.state(operation_id)
        if state.get("status") != "ready":
            return None
        with self._lock:
            return self._require(operation_id).bundle_path

    def cancel(self, operation_id: str) -> bool:
        operation_id = self._valid_operation_id(operation_id)
        with self._lock:
            session = self._logins.pop(operation_id, None)
            if session is None:
                return False
            if session.status == "running":
                self._terminate(session)
            else:
                try:
                    os.close(session.master_fd)
                except OSError:
                    pass
            shutil.rmtree(session.directory, ignore_errors=True)
            return True

    def validate_upload(self, archive_data: bytes) -> int:
        files = extract_single_session(archive_data)
        with tempfile.TemporaryDirectory(prefix="tdl-profile-validate-", dir=self.root) as temporary:
            directory = Path(temporary)
            session_root = directory / ".tdl"
            self._write_files(session_root, files)
            return self._whoami(session_root)

    def install_bundle(
        self,
        profile: str,
        telegram_user_id: int,
        bundle: bytes,
        operation_id: str,
        *,
        on_stage: Callable[[str, str, str], None] | None = None,
    ) -> dict[str, Any]:
        if len(bundle) > MAX_PROFILE_BUNDLE_BYTES:
            raise ValueError("Bundle profil melebihi batas.")
        entries = validate_profile_bundle(bundle)
        expected_identity = int(telegram_user_id)
        if expected_identity < 1:
            raise ValueError("Identity Telegram tidak valid.")
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            try:
                identity = json.loads(archive.read("identity.json").decode("utf-8"))
                if not isinstance(identity, dict):
                    raise TypeError("Identity bundle harus berupa object.")
                stored_id = int(identity.get("telegram_user_id", identity.get("tdl_user_id")))
            except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("Identity bundle profil tidak valid.") from exc
            if stored_id != expected_identity:
                raise ValueError("Identity bundle tidak cocok dengan profil.")

            with tempfile.TemporaryDirectory(
                prefix="profile-candidates-", dir=self.root
            ) as raw_root:
                candidate_root = Path(raw_root)
                download_candidate = candidate_root / "download" / ".tdl"
                export_candidate = candidate_root / "export" / ".tdl"
                download_candidate.mkdir(parents=True, exist_ok=True)
                export_candidate.mkdir(parents=True, exist_ok=True)
                for info, parts in entries:
                    if info.is_dir():
                        continue
                    path = "/".join(parts)
                    if path.startswith("root/.tdl/"):
                        destination_root = download_candidate
                        relative_parts = parts[2:]
                    elif path.startswith("user1/.tdl/"):
                        destination_root = export_candidate
                        relative_parts = parts[2:]
                    else:
                        continue
                    destination = destination_root.joinpath(*relative_parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(info))
                self._set_private_tree(download_candidate)
                self._set_private_tree(export_candidate)
                self._require_private_tree(download_candidate)
                self._require_private_tree(export_candidate)
                return self.install_candidates(
                    profile,
                    expected_identity,
                    operation_id,
                    download_candidate=download_candidate,
                    export_candidate=export_candidate,
                    on_stage=on_stage,
                )

    def install_candidates(
        self,
        profile: str,
        telegram_user_id: int,
        operation_id: str,
        *,
        download_candidate: Path | None = None,
        export_candidate: Path | None = None,
        on_stage: Callable[[str, str, str], None] | None = None,
    ) -> dict[str, Any]:
        def report(stage: str, status: str, code: str = "") -> None:
            if on_stage is not None:
                try:
                    on_stage(stage, status, code)
                except Exception:
                    # Progress delivery must not change the session transaction.
                    pass

        normalized = normalize_profile_name(profile)
        if not normalized:
            raise ValueError("Nama profil tidak valid.")
        if download_candidate is None and export_candidate is None:
            raise ValueError("Kandidat sesi profil tidak tersedia.")
        if download_candidate is None:
            download_candidate = export_candidate
        if export_candidate is None:
            export_candidate = download_candidate
        assert download_candidate is not None and export_candidate is not None
        download_candidate = Path(download_candidate)
        export_candidate = Path(export_candidate)
        profile_config = build_profile_config(self.config, normalized)
        profile_root = Path(profile_config.profile_root)
        if profile_root.is_symlink():
            raise ValueError("Direktori profil tidak aman.")
        operation_id = self._valid_operation_id(operation_id or "sync-" + normalized)
        expected_identity = int(telegram_user_id)
        if expected_identity < 1:
            raise ValueError("Identity Telegram tidak valid.")
        stage_root = profile_root / f".{normalized}.provision-{operation_id}"
        backup_root = self._backup_directory(normalized, operation_id)
        marker = profile_root / ".profile-provisioning.json"
        receipt_file = profile_root / _PROFILE_INSTALL_RECEIPTS
        for target in (
            profile_root / "root",
            profile_root / "user1",
            profile_root / "upload",
            profile_root / ".profile-provisioning-backups",
            backup_root.parent.parent,
            stage_root,
            backup_root.parent,
            backup_root,
            marker,
            profile_root / "identity.json",
            receipt_file,
        ):
            if target.is_symlink():
                raise ValueError("Direktori sesi profil tidak aman.")
        for relative in _PROFILE_INSTALL_LANES:
            self._assert_safe_tree(profile_root / relative)
        self._assert_safe_tree(profile_root / ".profile-provisioning-backups")
        self._assert_safe_tree(backup_root.parent)
        self._assert_safe_tree(backup_root)
        if marker.exists() and not marker.is_file():
            raise ValueError("Marker provisioning profil tidak aman.")
        self._assert_candidate_source(download_candidate)
        self._assert_candidate_source(export_candidate)
        download_fingerprint = self._session_tree_fingerprint(
            download_candidate, str(profile_config.tdl_download_namespace),
            allow_namespace_alias=True,
        )
        export_fingerprint = self._session_tree_fingerprint(
            export_candidate, str(profile_config.tdl_export_namespace),
            allow_namespace_alias=True,
        )
        bundle_digest_builder = hashlib.sha256()
        bundle_digest_builder.update(str(expected_identity).encode("ascii"))
        bundle_digest_builder.update(b"\0download\0" + download_fingerprint.encode("ascii"))
        bundle_digest_builder.update(b"\0export\0" + export_fingerprint.encode("ascii"))
        bundle_digest = bundle_digest_builder.hexdigest()
        report("bundle_validation", "succeeded")

        # Keep staging and rollback data beside profile files on the same
        # filesystem. For default, this avoids creating directories under /.
        receipts = self._read_install_receipts(profile_root)
        receipt = receipts["commits"].get(operation_id)
        if receipt is not None and (
            receipt.get("bundle_sha256") != bundle_digest
            or receipt.get("telegram_user_id") != expected_identity
        ):
            raise RuntimeError("ID provisioning sudah committed dengan konten lain.")
        if marker.exists():
            try:
                state = json.loads(marker.read_text(encoding="utf-8"))
                if not isinstance(state, dict) or state.get("operation_id") != operation_id:
                    raise RuntimeError("Profil sedang menerima provisioning lain.")
            except json.JSONDecodeError as exc:
                raise RuntimeError("Marker provisioning profil rusak.") from exc
            original = state.get("original")
            if not isinstance(original, dict):
                original = {
                    relative: (backup_root / relative).exists()
                    for relative in _PROFILE_INSTALL_LANES
                }
                original["identity.json"] = (backup_root / "identity.json").exists()
            # A marker from the previous two-lane installer did not touch
            # Upload. Capture its pre-transaction tree before upgrading it.
            if "upload" not in original:
                original["upload"] = (profile_root / "upload").exists() or (
                    backup_root / "upload"
                ).exists()
            original.setdefault("root/.tdl", False)
            original.setdefault("user1/.tdl", False)
            original.setdefault("identity.json", False)
            if any(type(original.get(key)) is not bool for key in (*_PROFILE_INSTALL_LANES, "identity.json")):
                raise RuntimeError("Snapshot provisioning profil tidak valid.")
            existing_digest = state.get("bundle_sha256")
            if existing_digest and existing_digest != bundle_digest:
                raise RuntimeError("ID provisioning sudah terikat ke bundle lain.")
            existing_identity = state.get("telegram_user_id")
            if existing_identity is not None and (
                type(existing_identity) is not int or existing_identity != expected_identity
            ):
                raise RuntimeError("ID provisioning sudah terikat ke identitas lain.")
            state["bundle_sha256"] = bundle_digest
            state["telegram_user_id"] = expected_identity
            state["original"] = original
            state["transaction_version"] = 2
            already_installed = state.get("installed") is True and self.verify_installed(
                normalized, expected_identity
            ) is not False
            state["installed"] = already_installed
            self._write_private_json(marker, state)
            if already_installed:
                report("installation_reused", "succeeded")
                return {"profile": normalized, "ready": True, "reused": True}
        else:
            receipt = receipts["commits"].get(operation_id)
            if receipt is not None:
                if receipt.get("bundle_sha256") != bundle_digest:
                    raise RuntimeError("ID provisioning sudah terikat ke bundle lain.")
                if receipts.get("last_operation_id") != operation_id:
                    raise RuntimeError("Operasi provisioning ini sudah digantikan.")
                if self.verify_installed(normalized, expected_identity) is False:
                    raise RuntimeError("Hasil provisioning committed sudah berubah.")
                self._remove_path(backup_root.parent)
                report("installation_reused", "succeeded")
                return {"profile": normalized, "ready": True, "reused": True}
            profile_root.mkdir(parents=True, exist_ok=True)
            # A missing marker means the previous operation committed. Any
            # remaining operation directory is only an interrupted cleanup.
            self._remove_path(backup_root.parent)
            backup_root.mkdir(parents=True, exist_ok=True)
            if os.name == "posix":
                self._set_private_tree(backup_root.parent.parent)
                self._set_private_tree(backup_root.parent)
                self._set_private_tree(backup_root)
            original = {
                relative: (profile_root / relative).exists()
                for relative in _PROFILE_INSTALL_LANES
            }
            original["identity.json"] = (profile_root / "identity.json").exists()
            state = {
                "operation_id": operation_id,
                "new_profile": not original["identity.json"],
                "transaction_version": 2,
                "bundle_sha256": bundle_digest,
                "telegram_user_id": expected_identity,
                "installed": False,
                "original": original,
            }
            self._write_private_json(marker, state)

        backup_root.mkdir(parents=True, exist_ok=True)
        self._set_private_tree(backup_root.parent)
        self._set_private_tree(backup_root)
        self._require_private_tree(backup_root.parent)
        self._require_private_tree(backup_root)

        self._remove_path(stage_root)
        try:
            stage_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._set_private_tree(stage_root)
            staging_specs = (
                (
                    "download", download_candidate, "root/.tdl",
                    str(profile_config.tdl_download_namespace),
                ),
                (
                    "export", export_candidate, "user1/.tdl",
                    str(profile_config.tdl_export_namespace),
                ),
            )
            for lane, candidate_source, relative, namespace in staging_specs:
                phase = f"{lane}_staging"
                report(phase, "running")
                try:
                    destination = stage_root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(candidate_source, destination, symlinks=True)
                    self._normalize_candidate_namespace(destination, namespace)
                    self._set_private_tree(destination)
                    self._require_private_tree(destination)
                except Exception as exc:
                    code = getattr(exc, "code", "PROFILE_SESSION_STAGING_FAILED")
                    if code not in {
                        "PROFILE_SESSION_UNSAFE", "PROFILE_SESSION_PERMISSION_INVALID",
                        "PROFILE_SESSION_STAGING_FAILED",
                    }:
                        code = "PROFILE_SESSION_STAGING_FAILED"
                    report(phase, "failed", code)
                    raise _ProfileInstallFailure(code) from None
                report(phase, "succeeded")
            identity_stage = stage_root / "identity.json"
            identity_stage.write_text(
                json.dumps({
                    "telegram_user_id": expected_identity,
                    "tdl_user_id": expected_identity,
                }),
                encoding="utf-8",
            )
            self._set_private_tree(stage_root)
            self._require_private_tree(stage_root)

            # Upload is a separate Bolt database copied from the Export
            # candidate. Never hard-link it: TDL opens each lane independently.
            report("upload_staging", "running")
            try:
                export_storage = stage_root / "user1" / ".tdl"
                upload_home = stage_root / "upload"
                upload_storage = upload_home / ".tdl"
                upload_home.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copytree(export_storage, upload_storage, symlinks=False)
                fingerprint = self._session_tree_fingerprint(
                    export_storage, str(profile_config.tdl_export_namespace)
                )
                self._write_private_json(upload_home / _UPLOAD_LANE_MARKER, {
                    "format": 1,
                    "source_fingerprint": fingerprint,
                })
                self._set_private_tree(upload_home)
                self._require_private_tree(upload_home)
                if self._trees_share_files(export_storage, upload_storage):
                    raise _ProfileInstallFailure("PROFILE_SESSION_STORAGE_NOT_ISOLATED")
            except Exception as exc:
                code = getattr(exc, "code", "PROFILE_SESSION_STAGING_FAILED")
                if code not in {
                    "PROFILE_SESSION_UNSAFE", "PROFILE_SESSION_PERMISSION_INVALID",
                    "PROFILE_SESSION_TDL_INVALID", "PROFILE_SESSION_DATABASE_MISSING",
                    "PROFILE_SESSION_STORAGE_NOT_ISOLATED", "PROFILE_SESSION_STAGING_FAILED",
                }:
                    code = "PROFILE_SESSION_STAGING_FAILED"
                report("upload_staging", "failed", code)
                raise _ProfileInstallFailure(code) from None
            report("upload_staging", "succeeded")

            validation_specs = (
                ("download", stage_root / "root" / ".tdl", str(profile_config.tdl_download_namespace)),
                ("export", export_storage, str(profile_config.tdl_export_namespace)),
                ("upload", upload_storage, str(profile_config.tdl_export_namespace)),
            )
            for lane, storage, namespace in validation_specs:
                phase = f"{lane}_validation"
                report(phase, "running")
                try:
                    self._require_candidate_database(storage, namespace)
                    actual_identity = self._run_whoami(
                        storage,
                        namespace=namespace,
                        home=storage.parent,
                    )
                    if actual_identity != expected_identity:
                        raise _ProfileInstallFailure("PROFILE_SESSION_IDENTITY_MISMATCH")
                except Exception as exc:
                    code = getattr(exc, "code", "PROFILE_SESSION_TDL_INVALID")
                    if code not in {
                        "PROFILE_SESSION_IDENTITY_MISMATCH",
                        "PROFILE_SESSION_DATABASE_MISSING",
                        "PROFILE_SESSION_TDL_INVALID",
                    }:
                        code = "PROFILE_SESSION_TDL_INVALID"
                    report(phase, "failed", code)
                    raise _ProfileInstallFailure(code) from None
                report(phase, "succeeded")

            # Complete any interrupted backup before replacing sessions. Keep
            # the original Upload home (including its fingerprint marker) with
            # the two source lanes and identity metadata.
            backup_root.mkdir(parents=True, exist_ok=True)
            for relative in _PROFILE_INSTALL_LANES:
                lane = "download" if relative == "root/.tdl" else "export" if relative == "user1/.tdl" else "upload"
                phase = f"{lane}_install"
                report(phase, "running")
                try:
                    current = profile_root / relative
                    saved = backup_root / relative
                    if original.get(relative) and current.exists() and not saved.exists():
                        self._set_private_tree(current)
                        self._require_private_tree(current)
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(current, saved)
                    if current.exists():
                        self._remove_path(current)
                    candidate = stage_root / relative
                    current.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(candidate, current)
                    self._set_private_tree(current)
                    self._require_private_tree(current)
                except Exception:
                    report(phase, "failed", "PROFILE_LANE_INSTALL_FAILED")
                    raise _ProfileInstallFailure("PROFILE_LANE_INSTALL_FAILED") from None
                report(phase, "succeeded")

            identity = profile_root / "identity.json"
            saved_identity = backup_root / "identity.json"
            if original.get("identity.json") and identity.exists() and not saved_identity.exists():
                try:
                    identity.chmod(0o600)
                except OSError:
                    pass
                self._require_private_file(identity)
                os.replace(identity, saved_identity)
            report("identity_install", "running")
            try:
                os.replace(identity_stage, identity)
                self._require_private_file(identity)
            except Exception:
                report("identity_install", "failed", "PROFILE_IDENTITY_INSTALL_FAILED")
                raise _ProfileInstallFailure("PROFILE_IDENTITY_INSTALL_FAILED") from None
            report("identity_install", "succeeded")
            if self.verify_installed(normalized, expected_identity) is False:
                raise _ProfileInstallFailure("PROFILE_INSTALL_VALIDATION_FAILED")
            state["installed"] = True
            self._write_private_json(marker, state)
            return {"profile": normalized, "ready": True}
        except Exception:
            self._remove_path(stage_root)
            report("transaction_rollback", "running")
            try:
                restored = self.rollback_bundle(normalized, operation_id)
            except Exception:
                restored = False
            report(
                "transaction_rollback",
                "succeeded" if restored else "failed",
                "" if restored else "PROFILE_INSTALL_ROLLBACK_FAILED",
            )
            if not restored:
                raise _ProfileInstallFailure("PROFILE_INSTALL_ROLLBACK_FAILED") from None
            raise
        finally:
            self._remove_path(stage_root)

    def commit_bundle(self, profile: str, operation_id: str) -> bool:
        normalized = normalize_profile_name(profile)
        if not normalized:
            return False
        try:
            operation_id = self._valid_operation_id(operation_id)
        except ValueError:
            return False
        profile_root = Path(build_profile_config(self.config, normalized).profile_root)
        marker = profile_root / ".profile-provisioning.json"
        backup_root = self._backup_directory(normalized, operation_id)
        receipt_file = profile_root / _PROFILE_INSTALL_RECEIPTS
        if (
            profile_root.is_symlink()
            or marker.is_symlink()
            or receipt_file.is_symlink()
            or backup_root.parent.is_symlink()
            or backup_root.parent.parent.is_symlink()
            or (profile_root / ".profile-provisioning-backups").is_symlink()
        ):
            return False
        if not marker.exists():
            try:
                receipts = self._read_install_receipts(profile_root)
            except (OSError, ValueError, json.JSONDecodeError):
                return False
            if operation_id not in receipts["commits"]:
                return False
            try:
                self._assert_safe_tree(backup_root.parent)
                self._remove_path(backup_root.parent)
                self._remove_empty_backup_root(profile_root)
            except (OSError, _ProfileInstallFailure):
                pass
            return True
        try:
            state = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(state, dict) or state.get("operation_id") != operation_id:
            return False
        bundle_digest = state.get("bundle_sha256")
        telegram_user_id = state.get("telegram_user_id")
        if (
            state.get("installed") is not True
            or not isinstance(bundle_digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", bundle_digest)
            or type(telegram_user_id) is not int
            or telegram_user_id < 1
        ):
            return False
        backup = self._backup_directory(normalized, operation_id)
        if backup.is_symlink() or not self._tree_is_safe(backup.parent):
            return False
        if self.verify_installed(normalized, telegram_user_id) is False:
            return False
        try:
            self._record_install_commit(
                profile_root,
                operation_id,
                bundle_digest=bundle_digest,
                telegram_user_id=telegram_user_id,
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        try:
            marker.unlink(missing_ok=True)
        except OSError:
            return False
        try:
            self._remove_path(backup.parent)
            self._remove_empty_backup_root(profile_root)
        except OSError:
            # The installation is already committed; a later retry can clean
            # this private, operation-scoped recovery directory.
            pass
        return True

    def rollback_bundle(self, profile: str, operation_id: str) -> bool:
        normalized = normalize_profile_name(profile)
        if not normalized:
            return False
        try:
            operation_id = self._valid_operation_id(operation_id)
        except ValueError:
            return False
        profile_root = Path(build_profile_config(self.config, normalized).profile_root)
        marker = profile_root / ".profile-provisioning.json"
        backup_root = self._backup_directory(normalized, operation_id)
        receipt_file = profile_root / _PROFILE_INSTALL_RECEIPTS
        if (
            profile_root.is_symlink()
            or marker.is_symlink()
            or receipt_file.is_symlink()
            or backup_root.parent.is_symlink()
            or backup_root.parent.parent.is_symlink()
            or (profile_root / ".profile-provisioning-backups").is_symlink()
        ):
            return False
        try:
            state = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(state, dict) or state.get("operation_id") != operation_id:
            return False
        backup = self._backup_directory(normalized, operation_id)
        try:
            self._assert_safe_tree(backup.parent)
        except _ProfileInstallFailure:
            return False
        if backup.is_symlink() or not self._tree_is_safe(backup.parent):
            return False
        original = state.get("original")
        if not isinstance(original, dict):
            original = {
                relative: (backup / relative).exists()
                for relative in ("root/.tdl", "user1/.tdl")
            }
            original["identity.json"] = (backup / "identity.json").exists()
        if any(
            relative in original and type(original[relative]) is not bool
            for relative in (*_PROFILE_INSTALL_LANES, "identity.json")
        ):
            return False
        for target in (
            profile_root / "root",
            profile_root / "user1",
            profile_root / "upload",
            profile_root / "identity.json",
        ):
            if target.is_symlink():
                return False
        for relative in _PROFILE_INSTALL_LANES:
            try:
                self._assert_safe_tree(profile_root / relative)
            except _ProfileInstallFailure:
                return False
        self._remove_path(profile_root / f".{normalized}.provision-{operation_id}")
        for relative in _PROFILE_INSTALL_LANES:
            # A two-lane transaction marker predates managed Upload state.
            # Leave that untouched lane alone if it has no saved snapshot.
            if relative not in original:
                continue
            current = profile_root / relative
            saved = backup / relative
            if saved.exists():
                self._remove_path(current)
                current.parent.mkdir(parents=True, exist_ok=True)
                os.replace(saved, current)
            elif not original.get(relative, state.get("new_profile", False)):
                self._remove_path(current)
        identity = profile_root / "identity.json"
        saved_identity = backup / "identity.json"
        if saved_identity.exists():
            identity.unlink(missing_ok=True)
            os.replace(saved_identity, identity)
        elif not original.get("identity.json", state.get("new_profile", False)):
            identity.unlink(missing_ok=True)
        try:
            self._forget_install_commit(profile_root, operation_id)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        marker.unlink(missing_ok=True)
        self._remove_path(backup.parent)
        self._remove_empty_backup_root(profile_root)
        if normalized != normalize_profile_name(self.config.default_profile):
            try:
                profile_root.rmdir()
            except OSError:
                pass
        return True

    def delete_local_profile(self, profile: str) -> dict[str, Any]:
        """Remove one non-default profile folder derived from its validated slug."""
        raw = str(profile or "").strip().lower()
        normalized = normalize_profile_name(raw)
        if not normalized or raw != normalized:
            raise DomainError(
                "PROFILE_NAME_INVALID",
                "Nama profil lokal tidak valid.",
                status_code=422,
            )
        if normalized == normalize_profile_name(self.config.default_profile):
            raise DomainError(
                "PROFILE_DEFAULT_PROTECTED",
                "Profil default tidak dapat dihapus.",
                status_code=409,
            )

        profiles_root = Path(self.config.profiles_root)
        if profiles_root.is_symlink():
            raise DomainError(
                "PROFILE_ROOT_UNSAFE",
                "Root profil worker tidak aman; tidak ada data yang dihapus.",
                status_code=409,
            )
        expected = profiles_root / normalized
        configured = Path(build_profile_config(self.config, normalized).profile_root)
        if configured != expected or expected.name != normalized:
            raise DomainError(
                "PROFILE_ROOT_UNSAFE",
                "Target profil worker tidak cocok dengan nama profil.",
                status_code=409,
            )
        if expected.is_symlink():
            raise DomainError(
                "PROFILE_ROOT_UNSAFE",
                "Direktori profil worker tidak aman; tidak ada data yang dihapus.",
                status_code=409,
            )
        if not expected.exists():
            return {"profile": normalized, "deleted": True, "already_absent": True}
        if not expected.is_dir() or expected.resolve().parent != profiles_root.resolve():
            raise DomainError(
                "PROFILE_ROOT_UNSAFE",
                "Direktori profil worker tidak aman; tidak ada data yang dihapus.",
                status_code=409,
            )

        # Do not let a profile tree redirect recursive deletion outside its root.
        try:
            for current, directories, files in os.walk(expected, followlinks=False):
                base = Path(current)
                if any((base / child).is_symlink() for child in (*directories, *files)):
                    raise DomainError(
                        "PROFILE_ROOT_UNSAFE",
                        "Direktori profil berisi link filesystem; tidak ada data yang dihapus.",
                        status_code=409,
                    )
        except OSError as exc:
            raise DomainError(
                "PROFILE_DELETE_FAILED",
                "Direktori profil worker tidak dapat diperiksa dengan aman.",
                status_code=409,
            ) from exc

        try:
            shutil.rmtree(expected)
        except OSError as exc:
            raise DomainError(
                "PROFILE_DELETE_FAILED",
                "Profil lokal gagal dihapus; periksa worker lalu coba Scan kembali.",
                status_code=409,
            ) from exc
        return {"profile": normalized, "deleted": True, "already_absent": False}

    def _backup_directory(self, profile: str, operation_id: str) -> Path:
        profile_root = Path(build_profile_config(self.config, profile).profile_root)
        current = profile_root / ".profile-provisioning-backups" / operation_id / profile
        legacy = self.root / "backups" / operation_id / profile
        # Let a worker upgraded during provisioning still commit or roll back
        # backups created by the prior layout.
        if legacy.exists() and not current.exists():
            return legacy
        return current

    @staticmethod
    def _remove_empty_backup_root(profile_root: Path) -> None:
        try:
            (profile_root / ".profile-provisioning-backups").rmdir()
        except OSError:
            pass

    def export_bundle(self, profile: str) -> tuple[int, bytes]:
        normalized = normalize_profile_name(profile)
        if not normalized:
            raise ValueError("PROFILE_NAME_INVALID")
        config = build_profile_config(self.config, normalized)
        root = Path(config.profile_root)
        diagnosis = self.diagnose_export_bundle(normalized)
        if not diagnosis["ready"]:
            raise ValueError(str(diagnosis["reason_codes"][0]))
        try:
            identity = json.loads((root / "identity.json").read_text(encoding="utf-8"))
            user_id = int(identity.get("telegram_user_id", identity.get("tdl_user_id")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("PROFILE_IDENTITY_MISSING") from exc
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative in ("root/.tdl", "user1/.tdl"):
                source = root / relative
                if not source.is_dir():
                    code = "PROFILE_ROOT_SESSION_MISSING" if relative.startswith("root/") else "PROFILE_USER1_SESSION_MISSING"
                    raise ValueError(code)
                for path in source.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(root).as_posix())
            archive.writestr("identity.json", json.dumps({"telegram_user_id": user_id, "tdl_user_id": user_id}))
        data = output.getvalue()
        validate_profile_bundle(data)
        return user_id, data

    def diagnose_export_bundle(self, profile: str) -> dict[str, Any]:
        """Check whether a legacy profile can be exported without reading session contents."""
        normalized = normalize_profile_name(profile)
        if not normalized:
            return {
                "ready": False,
                "reason_codes": ["PROFILE_NAME_INVALID"],
                "checks": [{"name": "profile_name", "ready": False, "code": "PROFILE_NAME_INVALID"}],
            }

        root = Path(build_profile_config(self.config, normalized).profile_root)
        checks: list[dict[str, Any]] = []

        identity_path = root / "identity.json"
        identity_ready = False
        if root.is_symlink() or identity_path.is_symlink():
            identity_code = "PROFILE_IDENTITY_UNSAFE"
        else:
            try:
                identity = json.loads(identity_path.read_text(encoding="utf-8"))
                if not isinstance(identity, dict):
                    raise TypeError("identity must be an object")
                identity_id = int(identity.get("telegram_user_id", identity.get("tdl_user_id")))
                identity_ready = identity_id > 0
                identity_code = "OK" if identity_ready else "PROFILE_IDENTITY_INVALID"
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                identity_code = "PROFILE_IDENTITY_MISSING"
        checks.append({"name": "identity", "ready": identity_ready, "code": identity_code})

        for key, relative in (("root_session", "root/.tdl"), ("user1_session", "user1/.tdl")):
            session_root = root / relative
            data_root = session_root / "data"
            code = "OK"
            ready = False
            if root.is_symlink() or session_root.is_symlink() or data_root.is_symlink():
                code = "PROFILE_SESSION_UNSAFE"
            elif not session_root.is_dir() or not data_root.is_dir():
                code = "PROFILE_ROOT_SESSION_MISSING" if key == "root_session" else "PROFILE_USER1_SESSION_MISSING"
            else:
                try:
                    entries = list(session_root.rglob("*"))
                    if any(item.is_symlink() for item in entries):
                        code = "PROFILE_SESSION_UNSAFE"
                    else:
                        ready = any(
                            item.is_file()
                            and not item.is_symlink()
                            and item.stat().st_size > 0
                            for item in data_root.iterdir()
                        )
                        if not ready:
                            code = "PROFILE_ROOT_SESSION_EMPTY" if key == "root_session" else "PROFILE_USER1_SESSION_EMPTY"
                except OSError:
                    code = "PROFILE_SESSION_UNREADABLE"
            checks.append({"name": key, "ready": ready, "code": code})

        reasons = [str(item["code"]) for item in checks if not item["ready"]]
        return {"ready": not reasons, "reason_codes": reasons, "checks": checks}

    def diagnose_tdl_sessions(self, profile: str, profile_config: Any | None = None) -> dict[str, Any]:
        """Run read-only authenticated identity checks on root and user1 separately."""
        normalized = normalize_profile_name(profile)
        if not normalized:
            return {
                "ready": False,
                "identity_match": False,
                "reason_codes": ["PROFILE_NAME_INVALID"],
                "sessions": [
                    {"name": name, "ready": False, "code": "PROFILE_NAME_INVALID", "identity_matches_metadata": False}
                    for name in ("root", "user1")
                ],
            }

        from tme3bot.profiles import build_profile_config

        resolved_config = profile_config or build_profile_config(self.config, normalized)
        profile_root = Path(resolved_config.profile_root)
        metadata_id, metadata_code = self._read_identity_metadata(profile_root)
        sessions: list[dict[str, Any]] = []
        identity_ids: list[int | None] = []
        specifications = (
            (
                "root",
                Path(resolved_config.tdl_download_storage),
                str(resolved_config.tdl_download_namespace),
                Path(resolved_config.tdl_download_home),
            ),
            (
                "user1",
                Path(resolved_config.tdl_export_storage),
                str(resolved_config.tdl_export_namespace),
                Path(resolved_config.tdl_export_home),
            ),
        )
        for name, storage_root, namespace, home in specifications:
            user_id, code = self._diagnose_one_tdl_session(
                profile_root, name, storage_root, namespace, home
            )
            identity_ids.append(user_id)
            matches_metadata = user_id is not None and metadata_id is not None and user_id == metadata_id
            if user_id is not None and metadata_id is not None and not matches_metadata:
                code = "PROFILE_SESSION_METADATA_MISMATCH"
            sessions.append({
                "name": name,
                "ready": user_id is not None and matches_metadata,
                "code": code if code != "OK" else ("OK" if matches_metadata else metadata_code),
                "identity_matches_metadata": bool(matches_metadata),
            })

        reasons = [str(item["code"]) for item in sessions if not item["ready"]]
        if identity_ids[0] is not None and identity_ids[1] is not None and identity_ids[0] != identity_ids[1]:
            reasons.append("PROFILE_SESSION_IDENTITY_MISMATCH")
        identity_match = (
            metadata_id is not None
            and identity_ids[0] is not None
            and identity_ids[1] is not None
            and identity_ids[0] == identity_ids[1] == metadata_id
        )
        reasons = list(dict.fromkeys(reasons))
        return {
            "ready": identity_match and not reasons,
            "identity_match": identity_match,
            "reason_codes": reasons,
            "sessions": sessions,
        }

    @staticmethod
    def _read_identity_metadata(profile_root: Path) -> tuple[int | None, str]:
        identity_path = profile_root / "identity.json"
        if profile_root.is_symlink() or identity_path.is_symlink():
            return None, "PROFILE_IDENTITY_UNSAFE"
        try:
            if not identity_path.is_file() or identity_path.stat().st_size > 64 * 1024:
                return None, "PROFILE_IDENTITY_MISSING"
            payload = json.loads(identity_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            value = int(payload.get("telegram_user_id", payload.get("tdl_user_id")))
            if value < 1:
                raise ValueError
            return value, "OK"
        except FileNotFoundError:
            return None, "PROFILE_IDENTITY_MISSING"
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return None, "PROFILE_IDENTITY_INVALID"

    def test_backup_session(self, storage_root: Path, lane: str, profile: str) -> int:
        """Run the TDL identity check against one extracted backup session."""
        normalized = normalize_profile_name(profile)
        if not normalized or lane not in {"root", "user1"}:
            raise ValueError("Backup session selection is invalid.")
        resolved = build_profile_config(self.config, normalized)
        if lane == "root":
            namespace = str(resolved.tdl_download_namespace)
            home = Path(resolved.tdl_download_home)
        else:
            namespace = str(resolved.tdl_export_namespace)
            home = Path(resolved.tdl_export_home)
        storage = Path(storage_root)
        data_root = storage / "data"
        database_file = data_root / namespace
        if (
            storage.is_symlink()
            or data_root.is_symlink()
            or database_file.is_symlink()
            or not storage.is_dir()
            or not data_root.is_dir()
            or not database_file.is_file()
            or database_file.stat().st_size <= 0
        ):
            raise ValueError("Extracted TDL session database is missing or unsafe.")
        return self._run_whoami(storage, namespace=namespace, home=home)

    def test_profile_session(
        self, storage_root: Path, *, namespace: str, home: Path
    ) -> int:
        """Validate one isolated profile lane without opening its live Bolt DB."""
        storage = Path(storage_root)
        data_root = storage / "data"
        database_file = data_root / str(namespace)
        if (
            storage.is_symlink()
            or data_root.is_symlink()
            or database_file.is_symlink()
            or not storage.is_dir()
            or not data_root.is_dir()
            or not database_file.is_file()
            or database_file.stat().st_size <= 0
        ):
            raise ValueError("TDL session database is missing or unsafe.")
        return self._run_whoami(
            storage, namespace=str(namespace), home=Path(home)
        )

    def _diagnose_one_tdl_session(
        self,
        profile_root: Path,
        name: str,
        storage_root: Path,
        namespace: str,
        home: Path,
    ) -> tuple[int | None, str]:
        session_parent = profile_root / name
        session_root = storage_root
        data_root = session_root / "data"
        database_file = data_root / namespace
        if (
            profile_root.is_symlink()
            or session_parent.is_symlink()
            or session_root.is_symlink()
            or data_root.is_symlink()
            or database_file.is_symlink()
        ):
            return None, "PROFILE_SESSION_UNSAFE"
        try:
            if not session_root.is_dir() or not data_root.is_dir():
                return None, f"PROFILE_{name.upper()}_SESSION_MISSING"
            # tdl-leave opens Bolt with create semantics. Require an existing,
            # nonempty database so a diagnostic can never create an empty one.
            if not database_file.is_file() or database_file.stat().st_size <= 0:
                return None, f"PROFILE_{name.upper()}_SESSION_DATABASE_MISSING"
        except OSError:
            return None, "PROFILE_SESSION_UNREADABLE"

        try:
            user_id = self._run_whoami(
                storage_root, namespace=namespace, home=home
            )
        except ValueError:
            return None, f"PROFILE_{name.upper()}_SESSION_TDL_INVALID"
        return user_id, "OK"

    def _run_whoami(
        self, storage_root: Path, *, namespace: str, home: Path
    ) -> int:
        helper = str(getattr(self.config, "leave_helper_binary", "/usr/local/bin/tdl-leave"))
        with tempfile.TemporaryDirectory(prefix="tdl-diagnostic-") as raw_directory:
            private_directory = Path(raw_directory)
            self._set_private_tree(private_directory)
            # tdl-leave opens Bolt for writes even in --whoami mode. Use a
            # private copy so the live session database remains untouched.
            snapshot_storage = private_directory / "session-data"
            snapshot_storage.mkdir(mode=0o700)
            self._set_private_tree(snapshot_storage)
            snapshot_database = snapshot_storage / namespace
            shutil.copyfile(storage_root / "data" / namespace, snapshot_database)
            try:
                snapshot_database.chmod(0o600)
            except OSError:
                pass
            identity_file = private_directory / "identity.json"
            command = [
                helper,
                "--storage", str(snapshot_storage),
                "--namespace", namespace,
                "--whoami", "--identity-file", str(identity_file),
            ]
            try:
                result = subprocess.run(
                    command,
                    cwd=str(home),
                    env={**os.environ, "HOME": str(home), "NO_COLOR": "1"},
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    check=False,
                )
                if result.returncode != 0:
                    raise ValueError("TDL identity check failed")
                payload = json.loads(identity_file.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("TDL identity output is invalid")
                value = int(payload.get("telegram_user_id", payload.get("tdl_user_id")))
                if value < 1:
                    raise ValueError("TDL identity output is invalid")
                return value
            except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("Sesi TDL tidak valid atau belum login.") from exc

    def verify_installed(self, profile: str, expected_user_id: int | None = None) -> int | bool:
        """Check identity and all three isolated Bolt session trees without opening Bolt."""
        normalized = normalize_profile_name(profile)
        if not normalized:
            return False
        profile_config = build_profile_config(self.config, normalized)
        root = Path(profile_config.profile_root)
        if root.is_symlink():
            return False
        identity_path = root / "identity.json"
        if (
            identity_path.is_symlink()
            or not identity_path.is_file()
            or not self._file_is_private(identity_path)
        ):
            return False
        try:
            payload = json.loads(identity_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return False
            user_id = int(payload.get("telegram_user_id", payload.get("tdl_user_id")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False
        if user_id < 1 or (expected_user_id is not None and user_id != int(expected_user_id)):
            return False
        session_files: list[set[tuple[int, int]]] = []
        specifications = (
            ("root/.tdl", str(profile_config.tdl_download_namespace)),
            ("user1/.tdl", str(profile_config.tdl_export_namespace)),
            ("upload/.tdl", str(profile_config.tdl_export_namespace)),
        )
        for relative, namespace in specifications:
            session_root = root / relative
            session_parent = root / relative.split("/", 1)[0]
            data_root = session_root / "data"
            if (
                session_parent.is_symlink()
                or not self._tree_is_safe(session_root)
                or not self._tree_is_private(session_root)
                or data_root.is_symlink()
                or not data_root.is_dir()
            ):
                return False
            try:
                files = {
                    (item.stat().st_dev, item.stat().st_ino)
                    for item in session_root.rglob("*")
                    if item.is_file() and not item.is_symlink() and item.stat().st_size > 0
                }
                database = data_root / namespace
            except OSError:
                return False
            if not files or database.is_symlink() or not database.is_file() or database.stat().st_size <= 0:
                return False
            session_files.append(files)
        if any(
            session_files[left] & session_files[right]
            for left in range(len(session_files))
            for right in range(left + 1, len(session_files))
        ):
            return False
        return user_id

    def remove_bundle(self, profile: str, operation_id: str) -> bool:
        return self.rollback_bundle(profile, operation_id)

    def _whoami(self, storage_root: Path) -> int:
        return self._run_whoami(
            storage_root,
            namespace=str(self.config.tdl_export_namespace),
            home=Path(self.config.tdl_export_home),
        )

    def _finish_if_exited(self, session: _LoginProcess) -> None:
        try:
            pid, status = os.waitpid(session.pid, os.WNOHANG)
        except ChildProcessError:
            pid, status = session.pid, 0
        if pid == 0:
            return
        session.exit_code = os.waitstatus_to_exitcode(status)
        try:
            os.close(session.master_fd)
        except OSError:
            pass
        if session.exit_code != 0:
            session.status = "failed"
            session.error = "TDL login gagal. Mulai ulang login atau periksa sesi worker."
            shutil.rmtree(session.directory, ignore_errors=True)
            return
        try:
            session_root = session.directory / "session" / ".tdl"
            session.telegram_user_id = self._whoami(session_root)
            output = session.directory / "session.zip"
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in session_root.rglob("*"):
                    if path.is_file():
                        archive.write(path, ".tdl/" + path.relative_to(session_root).as_posix())
            if os.name == "posix":
                os.chmod(output, 0o600)
            session.bundle_path = output
            session.status = "ready"
        except Exception:
            session.status = "failed"
            session.error = "Login selesai, tetapi identitas sesi TDL tidak dapat dibaca."
            shutil.rmtree(session.directory, ignore_errors=True)

    def _step(self, session: _LoginProcess) -> str:
        text = _ANSI_RE.sub("", session.transcript)
        lower = text.lower()
        if "enter 2fa password" in lower or "password:" in lower and "2fa" in lower:
            return "password"
        if "enter code" in lower or "code:" in lower:
            return "code"
        if session.method == "qr":
            return "qr"
        return "waiting"

    def _qr_text(self, transcript: str) -> str:
        text = _ANSI_RE.sub("", transcript).replace("\r", "\n")
        lines = [line for line in text.splitlines() if any(char in line for char in "█▀▄▌▐")]
        return "\n".join(lines[-34:])[-5000:]

    def _drain(self, session: _LoginProcess) -> None:
        while True:
            try:
                ready, _, _ = select.select([session.master_fd], [], [], 0)
                if not ready:
                    return
                raw = os.read(session.master_fd, 65536)
                if not raw:
                    return
                session.transcript = (session.transcript + raw.decode("utf-8", errors="replace"))[-24000:]
            except OSError:
                return

    def _terminate(self, session: _LoginProcess) -> None:
        try:
            os.killpg(session.pid, signal.SIGTERM)
            time.sleep(0.05)
            os.killpg(session.pid, signal.SIGKILL)
        except OSError:
            try:
                os.kill(session.pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            os.waitpid(session.pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass
        try:
            os.close(session.master_fd)
        except OSError:
            pass

    def _require(self, operation_id: str) -> _LoginProcess:
        session = self._logins.get(operation_id)
        if session is None:
            raise KeyError(operation_id)
        return session

    @staticmethod
    def _valid_operation_id(value: str) -> str:
        value = str(value)
        if len(value) > 64 or not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
            raise ValueError("ID provisioning tidak valid.")
        return value

    @staticmethod
    def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
        write_json_atomic_private(path, payload)

    def _read_install_receipts(self, profile_root: Path) -> dict[str, Any]:
        path = profile_root / _PROFILE_INSTALL_RECEIPTS
        if profile_root.is_symlink() or path.is_symlink():
            raise _ProfileInstallFailure("PROFILE_SESSION_UNSAFE")
        if not path.exists():
            return {"format": 1, "commits": {}, "last_operation_id": ""}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("format") != 1
            or not isinstance(payload.get("commits"), dict)
        ):
            raise ValueError("Profile install receipt store is invalid.")
        commits: dict[str, dict[str, int | str]] = {}
        for raw_id, raw_record in payload["commits"].items():
            operation_id = self._valid_operation_id(raw_id)
            if not isinstance(raw_record, dict):
                raise ValueError("Profile install receipt is invalid.")
            digest = raw_record.get("bundle_sha256")
            telegram_user_id = raw_record.get("telegram_user_id")
            committed_at = raw_record.get("committed_at")
            if (
                not isinstance(digest, str)
                or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or type(telegram_user_id) is not int
                or telegram_user_id < 1
                or type(committed_at) is not int
                or committed_at < 0
            ):
                raise ValueError("Profile install receipt is invalid.")
            commits[operation_id] = {
                "bundle_sha256": digest,
                "telegram_user_id": telegram_user_id,
                "committed_at": committed_at,
            }
        last_operation_id = payload.get("last_operation_id", "")
        if last_operation_id and last_operation_id not in commits:
            raise ValueError("Profile install receipt order is invalid.")
        return {
            "format": 1,
            "commits": commits,
            "last_operation_id": last_operation_id,
        }

    def _record_install_commit(
        self,
        profile_root: Path,
        operation_id: str,
        *,
        bundle_digest: str,
        telegram_user_id: int,
    ) -> None:
        receipts = self._read_install_receipts(profile_root)
        prior = receipts["commits"].get(operation_id)
        if prior is not None and (
            prior.get("bundle_sha256") != bundle_digest
            or prior.get("telegram_user_id") != telegram_user_id
        ):
            raise ValueError("Provisioning ID is already committed with different content.")
        commits = receipts["commits"]
        commits[operation_id] = {
            "bundle_sha256": bundle_digest,
            "telegram_user_id": telegram_user_id,
            "committed_at": int(time.time()),
        }
        while len(commits) > _MAX_PROFILE_INSTALL_RECEIPTS:
            oldest = min(
                commits,
                key=lambda item: int(commits[item]["committed_at"]),
            )
            if oldest == operation_id:
                break
            commits.pop(oldest, None)
        receipts["last_operation_id"] = operation_id
        self._write_private_json(profile_root / _PROFILE_INSTALL_RECEIPTS, receipts)

    def _forget_install_commit(self, profile_root: Path, operation_id: str) -> None:
        receipts = self._read_install_receipts(profile_root)
        if operation_id not in receipts["commits"]:
            return
        receipts["commits"].pop(operation_id, None)
        if not receipts["commits"]:
            (profile_root / _PROFILE_INSTALL_RECEIPTS).unlink(missing_ok=True)
            return
        if receipts.get("last_operation_id") == operation_id:
            receipts["last_operation_id"] = max(
                receipts["commits"],
                key=lambda item: int(receipts["commits"][item]["committed_at"]),
            )
        self._write_private_json(profile_root / _PROFILE_INSTALL_RECEIPTS, receipts)

    @staticmethod
    def _remove_path(path: Path) -> None:
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)

    @classmethod
    def _assert_safe_tree(cls, path: Path) -> None:
        if path.is_symlink():
            raise _ProfileInstallFailure("PROFILE_SESSION_UNSAFE")
        if not path.exists():
            return
        if not path.is_dir():
            raise _ProfileInstallFailure("PROFILE_SESSION_UNSAFE")
        try:
            for item in path.rglob("*"):
                if item.is_symlink() or not (item.is_dir() or item.is_file()):
                    raise _ProfileInstallFailure("PROFILE_SESSION_UNSAFE")
        except OSError:
            raise _ProfileInstallFailure("PROFILE_SESSION_UNSAFE") from None

    @classmethod
    def _tree_is_safe(cls, path: Path) -> bool:
        if not path.is_dir() or path.is_symlink():
            return False
        try:
            cls._assert_safe_tree(path)
            return True
        except _ProfileInstallFailure:
            return False

    @classmethod
    def _require_private_tree(cls, path: Path) -> None:
        if not cls._tree_is_safe(path):
            raise _ProfileInstallFailure("PROFILE_SESSION_UNSAFE")
        if os.name != "posix":
            return
        try:
            for item in (path, *path.rglob("*")):
                expected_mode = 0o700 if item.is_dir() else 0o600
                if stat.S_IMODE(item.stat().st_mode) != expected_mode:
                    raise _ProfileInstallFailure("PROFILE_SESSION_PERMISSION_INVALID")
        except OSError:
            raise _ProfileInstallFailure("PROFILE_SESSION_PERMISSION_INVALID") from None

    @classmethod
    def _tree_is_private(cls, path: Path) -> bool:
        if not cls._tree_is_safe(path):
            return False
        if os.name != "posix":
            return True
        try:
            return all(
                stat.S_IMODE(item.stat().st_mode) == (0o700 if item.is_dir() else 0o600)
                for item in (path, *path.rglob("*"))
            )
        except OSError:
            return False

    @staticmethod
    def _require_private_file(path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise _ProfileInstallFailure("PROFILE_SESSION_UNSAFE")
        if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise _ProfileInstallFailure("PROFILE_SESSION_PERMISSION_INVALID")

    @staticmethod
    def _file_is_private(path: Path) -> bool:
        try:
            return os.name != "posix" or stat.S_IMODE(path.stat().st_mode) == 0o600
        except OSError:
            return False

    @classmethod
    def _require_candidate_database(
        cls,
        storage: Path,
        namespace: str,
        *,
        allow_namespace_alias: bool = False,
    ) -> None:
        cls._assert_safe_tree(storage)
        data_root = storage / "data"
        database = storage / "data" / namespace
        if storage.is_symlink() or not storage.is_dir() or data_root.is_symlink() or not data_root.is_dir():
            raise _ProfileInstallFailure("PROFILE_SESSION_DATABASE_MISSING")
        if not database.is_symlink() and database.is_file() and database.stat().st_size > 0:
            return
        if allow_namespace_alias:
            candidates = [
                item for item in data_root.iterdir()
                if item.is_file() and not item.is_symlink() and item.stat().st_size > 0
            ]
            if len(candidates) == 1:
                return
        raise _ProfileInstallFailure("PROFILE_SESSION_DATABASE_MISSING")

    @classmethod
    def _session_tree_fingerprint(
        cls,
        storage: Path,
        namespace: str,
        *,
        allow_namespace_alias: bool = False,
    ) -> str:
        cls._require_candidate_database(
            storage, namespace, allow_namespace_alias=allow_namespace_alias
        )
        digest = hashlib.sha256()
        try:
            for path in sorted(
                storage.rglob("*"),
                key=lambda item: item.relative_to(storage).as_posix(),
            ):
                relative = path.relative_to(storage).as_posix().encode("utf-8")
                if path.is_dir():
                    digest.update(b"D\0" + relative + b"\0")
                    continue
                digest.update(b"F\0" + relative + b"\0")
                with path.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
        except OSError:
            raise _ProfileInstallFailure("PROFILE_SESSION_TDL_INVALID") from None
        return digest.hexdigest()

    @classmethod
    def _assert_candidate_source(cls, candidate: Path) -> None:
        absolute = Path(os.path.abspath(candidate))
        current = absolute
        while True:
            if current.is_symlink():
                raise _ProfileInstallFailure("PROFILE_SESSION_UNSAFE")
            if current.parent == current:
                break
            current = current.parent
        cls._assert_safe_tree(absolute)
        if not absolute.is_dir():
            raise _ProfileInstallFailure("PROFILE_SESSION_DATABASE_MISSING")

    @classmethod
    def _normalize_candidate_namespace(cls, storage: Path, namespace: str) -> None:
        data_root = storage / "data"
        expected = data_root / namespace
        if expected.is_file() and not expected.is_symlink() and expected.stat().st_size > 0:
            return
        if data_root.is_symlink() or not data_root.is_dir():
            raise _ProfileInstallFailure("PROFILE_SESSION_DATABASE_MISSING")
        candidates = [
            item for item in data_root.iterdir()
            if item.is_file() and not item.is_symlink() and item.stat().st_size > 0
        ]
        if len(candidates) != 1:
            raise _ProfileInstallFailure("PROFILE_SESSION_DATABASE_MISSING")
        if expected.exists() or expected.is_symlink():
            raise _ProfileInstallFailure("PROFILE_SESSION_UNSAFE")
        os.replace(candidates[0], expected)

    @staticmethod
    def _trees_share_files(left: Path, right: Path) -> bool:
        def identities(root: Path) -> set[tuple[int, int]]:
            return {
                (item.stat().st_dev, item.stat().st_ino)
                for item in root.rglob("*")
                if item.is_file() and not item.is_symlink()
            }

        try:
            return bool(identities(left) & identities(right))
        except OSError:
            raise _ProfileInstallFailure("PROFILE_SESSION_TDL_INVALID") from None

    @staticmethod
    def _write_files(root: Path, files: dict[str, bytes]) -> None:
        for relative, data in files.items():
            path = PurePosixPath(relative)
            if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
                raise ValueError("ZIP sesi berisi path yang tidak aman.")
            destination = root.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)

    @staticmethod
    def _set_private_tree(path: Path) -> None:
        if os.name != "posix" or not path.exists():
            return
        try:
            for item in [path, *path.rglob("*")]:
                item.chmod(0o700 if item.is_dir() else 0o600)
        except OSError:
            pass
