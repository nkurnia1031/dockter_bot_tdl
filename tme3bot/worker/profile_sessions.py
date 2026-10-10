from __future__ import annotations

import io
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

from tme3bot.names import normalize_profile_name
from tme3bot.profile_provisioning import (
    MAX_PROFILE_BUNDLE_BYTES,
    MAX_SESSION_ARCHIVE_BYTES,
    extract_single_session,
    validate_profile_bundle,
)
from tme3bot.profiles import build_profile_config


_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_LOGIN_TTL_SECONDS = 15 * 60
_PHONE_RE = re.compile(r"^[+0-9(). -]{4,32}$")


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
            self._chown_user1(directory)
            command = [
                "runuser", "-u", str(self.config.tdl_export_user), "--",
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
            self._chown_user1(directory)
            return self._whoami(session_root)

    def install_bundle(
        self,
        profile: str,
        telegram_user_id: int,
        bundle: bytes,
        operation_id: str,
        *,
        on_stage: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_profile_name(profile)
        if not normalized:
            raise ValueError("Nama profil tidak valid.")
        if len(bundle) > MAX_PROFILE_BUNDLE_BYTES:
            raise ValueError("Bundle profil melebihi batas.")
        entries = validate_profile_bundle(bundle)
        profile_config = build_profile_config(self.config, normalized)
        profile_root = Path(profile_config.profile_root)
        if profile_root.is_symlink():
            raise ValueError("Direktori profil tidak aman.")
        for session_parent in (profile_root / "root", profile_root / "user1"):
            if session_parent.is_symlink():
                raise ValueError("Direktori sesi profil tidak aman.")
        expected_identity = int(telegram_user_id)
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            try:
                identity = json.loads(archive.read("identity.json").decode("utf-8"))
                stored_id = int(identity.get("telegram_user_id", identity.get("tdl_user_id")))
            except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("Identity bundle profil tidak valid.") from exc
            if stored_id != expected_identity:
                raise ValueError("Identity bundle tidak cocok dengan profil.")
        if on_stage:
            on_stage("bundle_validation")

        operation_id = self._valid_operation_id(operation_id or "sync-" + normalized)
        # Keep staging and rollback data beside profile files on the same
        # filesystem. For default, this avoids creating directories under /.
        stage_root = profile_root / f".{normalized}.provision-{operation_id}"
        backup_root = self._backup_directory(normalized, operation_id)
        marker = profile_root / ".profile-provisioning.json"
        if marker.exists():
            try:
                state = json.loads(marker.read_text(encoding="utf-8"))
                if state.get("operation_id") != operation_id:
                    raise RuntimeError("Profil sedang menerima provisioning lain.")
            except json.JSONDecodeError as exc:
                raise RuntimeError("Marker provisioning profil rusak.") from exc
            original = state.get("original")
            if not isinstance(original, dict):
                # Markers created before the original-path manifest were
                # written only after all old files had been moved to backup.
                original = {
                    relative: (backup_root / relative).exists()
                    for relative in ("root/.tdl", "user1/.tdl")
                }
                original["identity.json"] = (backup_root / "identity.json").exists()
                state["original"] = original
                marker.write_text(json.dumps(state), encoding="utf-8")
        else:
            profile_root.mkdir(parents=True, exist_ok=True)
            backup_root.mkdir(parents=True, exist_ok=True)
            if os.name == "posix":
                backup_root.parent.mkdir(parents=True, exist_ok=True)
                backup_root.parent.chmod(0o700)
                backup_root.chmod(0o700)
            original = {
                relative: (profile_root / relative).exists()
                for relative in ("root/.tdl", "user1/.tdl")
            }
            original["identity.json"] = (profile_root / "identity.json").exists()
            state = {
                "operation_id": operation_id,
                "new_profile": not original["identity.json"],
                "original": original,
            }
            marker.write_text(json.dumps(state), encoding="utf-8")
        shutil.rmtree(stage_root, ignore_errors=True)
        stage_root.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            stage_root.chmod(0o700)
        try:
            # Complete any interrupted backup before replacing sessions. The
            # manifest lets rollback distinguish untouched originals from new
            # files installed by this operation.
            backup_root.mkdir(parents=True, exist_ok=True)
            for relative in ("root/.tdl", "user1/.tdl"):
                current = profile_root / relative
                saved = backup_root / relative
                if original.get(relative) and current.exists() and not saved.exists():
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(current, saved)
            identity = profile_root / "identity.json"
            saved_identity = backup_root / "identity.json"
            if original.get("identity.json") and identity.exists() and not saved_identity.exists():
                os.replace(identity, saved_identity)
            with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
                for info, parts in entries:
                    path = "/".join(parts)
                    if info.is_dir() or path in {"identity.json", "root", "user1", "root/.tdl", "user1/.tdl"}:
                        continue
                    target = stage_root.joinpath(*parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(info))
            self._set_private_tree(stage_root)
            for relative in ("root/.tdl", "user1/.tdl"):
                source = stage_root / relative
                database_files = list((source / "data").glob("*")) if source.exists() else []
                if not any(item.is_file() and item.stat().st_size for item in database_files):
                    raise ValueError(f"Bundle tidak memiliki database {relative} yang siap.")
                destination = profile_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.rmtree(destination, ignore_errors=True)
                os.replace(source, destination)
            identity_path = profile_root / "identity.json"
            identity_path.write_text(json.dumps({"telegram_user_id": expected_identity, "tdl_user_id": expected_identity}), encoding="utf-8")
            self._set_private_tree(profile_root / "root" / ".tdl")
            self._set_private_tree(profile_root / "user1" / ".tdl")
            try:
                identity_path.chmod(0o600)
            except OSError:
                pass
            self._chown_user1(profile_root / "user1")
            if on_stage:
                on_stage("session_validation")
            return {"profile": normalized, "ready": True}
        except Exception:
            shutil.rmtree(stage_root, ignore_errors=True)
            self.rollback_bundle(normalized, operation_id)
            raise
        finally:
            shutil.rmtree(stage_root, ignore_errors=True)

    def commit_bundle(self, profile: str, operation_id: str) -> bool:
        profile_root = Path(build_profile_config(self.config, profile).profile_root)
        marker = profile_root / ".profile-provisioning.json"
        try:
            state = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if state.get("operation_id") != operation_id:
            return False
        normalized = normalize_profile_name(profile)
        backup = self._backup_directory(normalized, operation_id)
        shutil.rmtree(backup.parent, ignore_errors=True)
        self._remove_empty_backup_root(profile_root)
        marker.unlink(missing_ok=True)
        return True

    def rollback_bundle(self, profile: str, operation_id: str) -> bool:
        profile_root = Path(build_profile_config(self.config, profile).profile_root)
        marker = profile_root / ".profile-provisioning.json"
        try:
            state = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if state.get("operation_id") != operation_id:
            return False
        normalized = normalize_profile_name(profile)
        backup = self._backup_directory(normalized, operation_id)
        original = state.get("original")
        if not isinstance(original, dict):
            original = {
                relative: (backup / relative).exists()
                for relative in ("root/.tdl", "user1/.tdl")
            }
            original["identity.json"] = (backup / "identity.json").exists()
        shutil.rmtree(profile_root / f".{normalized}.provision-{operation_id}", ignore_errors=True)
        for relative in ("root/.tdl", "user1/.tdl"):
            current = profile_root / relative
            saved = backup / relative
            if saved.exists():
                shutil.rmtree(current, ignore_errors=True)
                current.parent.mkdir(parents=True, exist_ok=True)
                os.replace(saved, current)
            elif not original.get(relative, state.get("new_profile", False)):
                shutil.rmtree(current, ignore_errors=True)
        identity = profile_root / "identity.json"
        saved_identity = backup / "identity.json"
        if saved_identity.exists():
            identity.unlink(missing_ok=True)
            os.replace(saved_identity, identity)
        elif not original.get("identity.json", state.get("new_profile", False)):
            identity.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        shutil.rmtree(backup.parent, ignore_errors=True)
        self._remove_empty_backup_root(profile_root)
        if normalized != normalize_profile_name(self.config.default_profile):
            try:
                profile_root.rmdir()
            except OSError:
                pass
        return True

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

    def verify_installed(self, profile: str, expected_user_id: int | None = None) -> int | bool:
        """Check identity and both private Bolt session trees without opening Bolt."""
        normalized = normalize_profile_name(profile)
        if not normalized:
            return False
        root = Path(build_profile_config(self.config, normalized).profile_root)
        if root.is_symlink():
            return False
        identity_path = root / "identity.json"
        if identity_path.is_symlink() or not identity_path.is_file():
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
        for relative in ("root/.tdl", "user1/.tdl"):
            session_root = root / relative
            session_parent = root / relative.split("/", 1)[0]
            data_root = session_root / "data"
            if (
                session_parent.is_symlink()
                or session_root.is_symlink()
                or not session_root.is_dir()
                or data_root.is_symlink()
                or not data_root.is_dir()
            ):
                return False
            try:
                files = {
                    (item.stat().st_dev, item.stat().st_ino)
                    for item in data_root.iterdir()
                    if item.is_file() and not item.is_symlink() and item.stat().st_size > 0
                }
            except OSError:
                return False
            if not files:
                return False
            session_files.append(files)
        if session_files[0] & session_files[1]:
            return False
        return user_id

    def remove_bundle(self, profile: str, operation_id: str) -> bool:
        return self.rollback_bundle(profile, operation_id)

    def _whoami(self, storage_root: Path) -> int:
        identity_file = storage_root.parent / "identity.json"
        helper = str(getattr(self.config, "leave_helper_binary", "/usr/local/bin/tdl-leave"))
        command = [
            "runuser", "-u", str(self.config.tdl_export_user), "--", helper,
            "--storage", str(storage_root / "data"),
            "--namespace", str(self.config.tdl_export_namespace),
            "--whoami", "--identity-file", str(identity_file),
        ]
        try:
            result = subprocess.run(
                command,
                cwd=str(self.config.tdl_export_home),
                env={**os.environ, "HOME": str(self.config.tdl_export_home)},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
                check=False,
            )
            if result.returncode != 0:
                raise ValueError("Sesi TDL tidak terautentikasi.")
            payload = json.loads(identity_file.read_text(encoding="utf-8"))
            return int(payload.get("telegram_user_id", payload.get("tdl_user_id")))
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Sesi TDL tidak valid atau belum login.") from exc

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
    def _write_files(root: Path, files: dict[str, bytes]) -> None:
        for relative, data in files.items():
            path = PurePosixPath(relative)
            if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
                raise ValueError("ZIP sesi berisi path yang tidak aman.")
            destination = root.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)

    @staticmethod
    def _chown_user1(path: Path) -> None:
        if os.name != "posix" or os.geteuid() != 0:
            return
        try:
            import pwd

            account = pwd.getpwnam("user1")
            for item in [path, *path.rglob("*")]:
                os.chown(item, account.pw_uid, account.pw_gid)
        except (KeyError, OSError):
            pass

    @staticmethod
    def _set_private_tree(path: Path) -> None:
        if os.name != "posix" or not path.exists():
            return
        try:
            for item in [path, *path.rglob("*")]:
                item.chmod(0o700 if item.is_dir() else 0o600)
        except OSError:
            pass
