"""Prepare an isolated Storage TDL lane from a local Export session."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tme3bot.names import normalize_profile_name
from tme3bot.persistence import write_json_atomic_private
from tme3bot.profile_diagnostics import (
    PROFILE_UPLOAD_LANE_CODES,
    PROFILE_UPLOAD_LANE_PHASES,
    PROFILE_UPLOAD_LANE_STATUSES,
)


LOGGER = logging.getLogger(__name__)
_FORMAT_VERSION = 1
_MARKER_NAME = "upload-lane.json"
_POLL_SECONDS = 0.5
_CODES = PROFILE_UPLOAD_LANE_CODES


class UploadLanePreparer:
    """Idempotently verify or replace each profile's derived Upload lane.

    Work runs in a background thread so worker startup and the Profiles scan
    endpoint can return a progress snapshot immediately. Export and Download
    locks keep the source databases idle while a consistent candidate is made.
    """

    def __init__(
        self,
        *,
        profile_manager: Any,
        session_checker: Callable[[Path, str, Path], int],
        state_path: Path,
    ) -> None:
        self.profile_manager = profile_manager
        self.session_checker = session_checker
        self.state_path = Path(state_path)
        self._lock = threading.RLock()
        self._active: set[str] = set()
        self._deleting: set[str] = set()
        self._records = self._load_records()

    def ensure(self, profile: str) -> dict[str, Any]:
        normalized = normalize_profile_name(profile)
        if not normalized:
            return self._snapshot({
                "status": "failed",
                "phase": "failed",
                "progress": 100,
                "code": "PROFILE_NAME_INVALID",
                "updated_at": self._now(),
            })
        with self._lock:
            current = self._records.get(normalized)
            if normalized in self._deleting:
                return self._snapshot({
                    "status": "pending",
                    "phase": "waiting_idle",
                    "progress": 0,
                    "code": "PROFILE_UPLOAD_PREPARATION_INTERRUPTED",
                    "updated_at": self._now(),
                })
            if normalized in self._active:
                return self._snapshot(current)
            record = {
                "status": "running",
                "phase": "queued",
                "progress": 1,
                "code": "OK",
                "updated_at": self._now(),
            }
            self._records[normalized] = record
            self._active.add(normalized)
            self._save_locked()
            thread = threading.Thread(
                target=self._prepare,
                args=(normalized,),
                daemon=True,
                name=f"worker-upload-lane-{normalized}",
            )
            thread.start()
            return self._snapshot(record)

    def status(self, profile: str) -> dict[str, Any]:
        normalized = normalize_profile_name(profile)
        if not normalized:
            return self._snapshot({
                "status": "failed",
                "phase": "failed",
                "progress": 100,
                "code": "PROFILE_NAME_INVALID",
                "updated_at": self._now(),
            })
        with self._lock:
            record = self._records.get(normalized)
            if record is None:
                return self._snapshot({
                    "status": "pending",
                    "phase": "not_started",
                    "progress": 0,
                    "code": "PROFILE_UPLOAD_PREPARATION_INTERRUPTED",
                    "updated_at": self._now(),
                })
            return self._snapshot(record)

    def forget_profile(self, profile: str) -> None:
        """Drop derived-lane status after the containing profile was removed."""
        normalized = normalize_profile_name(profile)
        if not normalized:
            return
        with self._lock:
            if self._records.pop(normalized, None) is not None:
                self._save_locked()

    def reserve_profile_deletion(self, profile: str) -> bool:
        normalized = normalize_profile_name(profile)
        if not normalized:
            return False
        with self._lock:
            if normalized in self._active or normalized in self._deleting:
                return False
            self._deleting.add(normalized)
            return True

    def release_profile_deletion(self, profile: str, *, deleted: bool = False) -> None:
        normalized = normalize_profile_name(profile)
        if not normalized:
            return
        with self._lock:
            self._deleting.discard(normalized)
            if deleted and self._records.pop(normalized, None) is not None:
                self._save_locked()

    def session_fingerprint(self, profile: str) -> str:
        """Return the stable source-session generation represented by a ready lane.

        The Upload Bolt database changes during normal sends, so its bytes are
        not a useful session identity. The private lane marker records the
        Export-session fingerprint from which this isolated Upload copy was
        installed; a later scan changes it only when that lane is replaced.
        """
        normalized = normalize_profile_name(profile)
        if not normalized or self.status(normalized).get("status") != "ready":
            return ""
        try:
            config = self.profile_manager.session_config(normalized)
            profile_root = Path(config.profile_root)
            upload_home = profile_root / "upload"
            if profile_root.is_symlink() or upload_home.is_symlink():
                return ""
            fingerprint = self._read_marker(upload_home)
            if (
                len(fingerprint) != 64
                or any(char not in "0123456789abcdef" for char in fingerprint)
                or not self._has_private_modes(upload_home)
            ):
                return ""
            return fingerprint
        except (_PreparationFailure, OSError, AttributeError, TypeError, ValueError):
            return ""

    def _prepare(self, profile: str) -> None:
        profile_root: Path | None = None
        candidate_home: Path | None = None
        held_locks: list[Any] = []
        try:
            config = self.profile_manager.session_config(profile)
            profile_root = Path(config.profile_root)
            source_storage = Path(config.tdl_export_storage)
            namespace = str(config.tdl_export_namespace)
            source_home = Path(config.tdl_export_home)
            upload_home = profile_root / "upload"
            upload_storage = upload_home / ".tdl"

            if profile_root.is_symlink() or not profile_root.is_dir():
                raise _PreparationFailure("PROFILE_UPLOAD_LANE_UNSAFE")

            self._set_progress(profile, "waiting_idle", 5)
            held_locks = self._acquire_profile_locks(profile)
            self._recover_interrupted_install(profile_root, upload_home)

            expected_id, identity_code = self._read_profile_identity(profile_root)
            if expected_id is None:
                raise _PreparationFailure(identity_code)

            self._set_progress(profile, "validating_source", 15)
            source_id = self._check_session(source_storage, namespace, source_home, "PROFILE_EXPORT_SESSION_INVALID")
            if source_id != expected_id:
                raise _PreparationFailure("PROFILE_EXPORT_IDENTITY_MISMATCH")
            fingerprint = self._fingerprint(source_storage, namespace)

            if upload_home.is_symlink() or (upload_home.exists() and not upload_home.is_dir()):
                raise _PreparationFailure("PROFILE_UPLOAD_LANE_UNSAFE")
            marker = self._read_marker(upload_home)
            if marker == fingerprint and self._has_private_modes(upload_home) and self._lane_matches_identity(
                upload_storage, namespace, upload_home, expected_id
            ):
                self._finish(profile, "ready", "ready", 100, "OK")
                return

            self._set_progress(profile, "copying", 35)
            candidate_home = profile_root / f".upload-candidate-{uuid.uuid4().hex}"
            candidate_storage = candidate_home / ".tdl"
            candidate_home.mkdir(mode=0o700)
            self._copy_session_tree(source_storage, candidate_storage)
            self._set_private_tree(candidate_home)

            self._set_progress(profile, "validating_upload", 70)
            candidate_id = self._check_session(
                candidate_storage,
                namespace,
                candidate_home,
                "PROFILE_UPLOAD_SESSION_INVALID",
            )
            if candidate_id != expected_id:
                raise _PreparationFailure("PROFILE_UPLOAD_IDENTITY_MISMATCH")
            write_json_atomic_private(candidate_home / _MARKER_NAME, {
                "format": _FORMAT_VERSION,
                "source_fingerprint": fingerprint,
            })
            self._set_private_tree(candidate_home)

            self._set_progress(profile, "installing", 90)
            self._install_candidate(profile_root, candidate_home, upload_home)
            candidate_home = None
            self._finish(profile, "ready", "ready", 100, "OK")
        except _PreparationFailure as exc:
            if candidate_home is not None:
                self._remove_tree(candidate_home)
                candidate_home = None
            self._finish(profile, "failed", "failed", 100, exc.code)
        except Exception:
            LOGGER.warning("Upload lane preparation failed for profile %s", profile)
            if candidate_home is not None:
                self._remove_tree(candidate_home)
                candidate_home = None
            self._finish(
                profile,
                "failed",
                "failed",
                100,
                "PROFILE_UPLOAD_PREPARATION_FAILED",
            )
        finally:
            if candidate_home is not None:
                self._remove_tree(candidate_home)
            for lock in reversed(held_locks):
                try:
                    lock.release()
                except RuntimeError:
                    pass
            with self._lock:
                self._active.discard(profile)

    def _acquire_profile_locks(self, profile: str) -> list[Any]:
        source_locks = self.profile_manager.profile_operation_locks(profile)
        upload_lock_method = getattr(self.profile_manager, "profile_upload_operation_lock", None)
        locks = [*source_locks]
        if callable(upload_lock_method):
            locks.append(upload_lock_method(profile))
        held: list[Any] = []
        while True:
            for lock in locks:
                if not lock.acquire(blocking=False):
                    for acquired in reversed(held):
                        acquired.release()
                    held.clear()
                    time.sleep(_POLL_SECONDS)
                    self._set_progress(profile, "waiting_idle", 5)
                    break
                held.append(lock)
            else:
                return held

    def _check_session(self, storage: Path, namespace: str, home: Path, code: str) -> int:
        database = storage / "data" / namespace
        if (
            storage.is_symlink()
            or (storage / "data").is_symlink()
            or database.is_symlink()
            or not storage.is_dir()
            or not (storage / "data").is_dir()
            or not database.is_file()
            or database.stat().st_size <= 0
        ):
            raise _PreparationFailure(code)
        try:
            return int(self.session_checker(storage, namespace, home))
        except Exception as exc:
            safe_code = str(getattr(exc, "code", "") or "")
            if safe_code in _CODES:
                raise _PreparationFailure(safe_code) from None
            raise _PreparationFailure(code) from None

    def _lane_matches_identity(
        self, storage: Path, namespace: str, home: Path, expected_id: int
    ) -> bool:
        try:
            self._fingerprint(storage, namespace)
            return self._check_session(
                storage, namespace, home, "PROFILE_UPLOAD_SESSION_INVALID"
            ) == expected_id
        except _PreparationFailure:
            return False

    @staticmethod
    def _read_profile_identity(profile_root: Path) -> tuple[int | None, str]:
        identity_path = profile_root / "identity.json"
        if profile_root.is_symlink() or identity_path.is_symlink():
            return None, "PROFILE_IDENTITY_UNSAFE"
        try:
            if not identity_path.is_file() or identity_path.stat().st_size > 64 * 1024:
                return None, "PROFILE_IDENTITY_MISSING"
            payload = json.loads(identity_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            user_id = int(payload.get("telegram_user_id", payload.get("tdl_user_id")))
            if user_id < 1:
                raise ValueError
            return user_id, "OK"
        except FileNotFoundError:
            return None, "PROFILE_IDENTITY_MISSING"
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return None, "PROFILE_IDENTITY_INVALID"

    @staticmethod
    def _fingerprint(storage: Path, namespace: str) -> str:
        if storage.is_symlink() or not storage.is_dir():
            raise _PreparationFailure("PROFILE_EXPORT_SESSION_MISSING")
        database = storage / "data" / namespace
        digest = hashlib.sha256()
        for path in sorted(storage.rglob("*"), key=lambda item: item.relative_to(storage).as_posix()):
            if path.is_symlink():
                raise _PreparationFailure("PROFILE_EXPORT_SESSION_UNSAFE")
            relative = path.relative_to(storage).as_posix().encode("utf-8")
            if path.is_dir():
                digest.update(b"D\0" + relative + b"\0")
                continue
            if not path.is_file():
                raise _PreparationFailure("PROFILE_EXPORT_SESSION_UNSAFE")
            digest.update(b"F\0" + relative + b"\0")
            try:
                with path.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
            except OSError:
                raise _PreparationFailure("PROFILE_EXPORT_SESSION_INVALID") from None
        if not database.is_file() or database.stat().st_size <= 0:
            raise _PreparationFailure("PROFILE_EXPORT_SESSION_MISSING")
        return digest.hexdigest()

    @staticmethod
    def _copy_session_tree(source: Path, destination: Path) -> None:
        if source.is_symlink() or not source.is_dir():
            raise _PreparationFailure("PROFILE_EXPORT_SESSION_MISSING")
        for item in source.rglob("*"):
            if item.is_symlink() or not (item.is_dir() or item.is_file()):
                raise _PreparationFailure("PROFILE_EXPORT_SESSION_UNSAFE")
        try:
            shutil.copytree(source, destination, symlinks=False)
        except OSError:
            raise _PreparationFailure("PROFILE_UPLOAD_PREPARATION_FAILED") from None
        for source_item in source.rglob("*"):
            if not source_item.is_file():
                continue
            copied_item = destination / source_item.relative_to(source)
            try:
                if source_item.stat().st_ino == copied_item.stat().st_ino and source_item.stat().st_dev == copied_item.stat().st_dev:
                    raise _PreparationFailure("PROFILE_UPLOAD_PREPARATION_FAILED")
            except OSError:
                raise _PreparationFailure("PROFILE_UPLOAD_PREPARATION_FAILED") from None

    @staticmethod
    def _set_private_tree(root: Path) -> None:
        if os.name != "posix":
            return
        try:
            for path in (root, *root.rglob("*")):
                if path.is_symlink():
                    raise _PreparationFailure("PROFILE_UPLOAD_LANE_UNSAFE")
                path.chmod(0o700 if path.is_dir() else 0o600)
                mode = stat.S_IMODE(path.stat().st_mode)
                if mode & 0o077:
                    raise _PreparationFailure("PROFILE_UPLOAD_PREPARATION_FAILED")
        except OSError:
            raise _PreparationFailure("PROFILE_UPLOAD_PREPARATION_FAILED") from None

    @staticmethod
    def _has_private_modes(root: Path) -> bool:
        if os.name != "posix":
            return True
        try:
            if root.is_symlink() or not root.is_dir():
                return False
            for path in (root, *root.rglob("*")):
                if path.is_symlink() or not (path.is_dir() or path.is_file()):
                    return False
                expected_mode = 0o700 if path.is_dir() else 0o600
                if stat.S_IMODE(path.stat().st_mode) != expected_mode:
                    return False
            return True
        except OSError:
            return False

    @staticmethod
    def _read_marker(upload_home: Path) -> str:
        marker = upload_home / _MARKER_NAME
        if upload_home.is_symlink() or marker.is_symlink():
            raise _PreparationFailure("PROFILE_UPLOAD_LANE_UNSAFE")
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("format") != _FORMAT_VERSION:
                return ""
            fingerprint = str(payload.get("source_fingerprint") or "")
            if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
                return ""
            return fingerprint
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ""

    def _install_candidate(self, profile_root: Path, candidate: Path, upload_home: Path) -> None:
        if upload_home.is_symlink() or (upload_home.exists() and not upload_home.is_dir()):
            raise _PreparationFailure("PROFILE_UPLOAD_LANE_UNSAFE")
        backup = profile_root / f".upload-backup-{uuid.uuid4().hex}"
        had_old = upload_home.exists()
        try:
            if had_old:
                os.replace(upload_home, backup)
            try:
                os.replace(candidate, upload_home)
            except OSError:
                if had_old and backup.exists() and not upload_home.exists():
                    os.replace(backup, upload_home)
                raise
        except _PreparationFailure:
            raise
        except OSError:
            raise _PreparationFailure("PROFILE_UPLOAD_PREPARATION_FAILED") from None
        if had_old:
            self._remove_tree(backup)

    def _recover_interrupted_install(self, profile_root: Path, upload_home: Path) -> None:
        backups = sorted(profile_root.glob(".upload-backup-*"), key=lambda path: path.name)
        candidates = list(profile_root.glob(".upload-candidate-*"))
        if upload_home.is_symlink():
            raise _PreparationFailure("PROFILE_UPLOAD_LANE_UNSAFE")
        if not upload_home.exists():
            valid_backups = [path for path in backups if path.is_dir() and not path.is_symlink()]
            if valid_backups:
                try:
                    os.replace(valid_backups[-1], upload_home)
                except OSError:
                    raise _PreparationFailure("PROFILE_UPLOAD_PREPARATION_FAILED") from None
                backups.remove(valid_backups[-1])
        for path in [*backups, *candidates]:
            self._remove_tree(path)

    @staticmethod
    def _remove_tree(path: Path) -> None:
        try:
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)
        except OSError:
            LOGGER.warning("Could not remove temporary Upload lane directory")

    def _set_progress(self, profile: str, phase: str, progress: int) -> None:
        with self._lock:
            record = self._records.setdefault(profile, {})
            updates = {
                "status": "running",
                "phase": phase,
                "progress": max(0, min(99, int(progress))),
                "code": "OK",
            }
            if any(record.get(key) != value for key, value in updates.items()):
                record.update(updates)
                record["updated_at"] = self._now()
                self._save_locked()

    def _finish(
        self,
        profile: str,
        status: str,
        phase: str,
        progress: int,
        code: str,
    ) -> None:
        code = code if code in _CODES else "PROFILE_UPLOAD_PREPARATION_FAILED"
        with self._lock:
            record = self._records.setdefault(profile, {})
            record.update({
                "status": status,
                "phase": phase,
                "progress": max(0, min(100, int(progress))),
                "code": code,
                "updated_at": self._now(),
            })
            self._save_locked()

    def _load_records(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        raw_profiles = payload.get("profiles", {}) if isinstance(payload, dict) else {}
        if not isinstance(raw_profiles, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for raw_name, raw_record in raw_profiles.items():
            name = normalize_profile_name(str(raw_name))
            if not name or not isinstance(raw_record, dict):
                continue
            record = dict(raw_record)
            if record.get("status") == "running":
                record.update({
                    "status": "pending",
                    "phase": "queued",
                    "progress": 0,
                    "code": "PROFILE_UPLOAD_PREPARATION_INTERRUPTED",
                    "updated_at": self._now(),
                })
            result[name] = record
        return result

    def _save_locked(self) -> None:
        try:
            write_json_atomic_private(self.state_path, {
                "version": _FORMAT_VERSION,
                "profiles": self._records,
            })
        except OSError:
            LOGGER.warning("Could not persist Upload lane preparation status")

    @staticmethod
    def _snapshot(record: dict[str, Any] | None) -> dict[str, Any]:
        record = record if isinstance(record, dict) else {}
        code = str(record.get("code") or "PROFILE_UPLOAD_PREPARATION_FAILED")
        if code not in _CODES:
            code = "PROFILE_UPLOAD_PREPARATION_FAILED"
        status = str(record.get("status") or "pending")
        if status not in PROFILE_UPLOAD_LANE_STATUSES:
            status = "pending"
        phase = str(record.get("phase") or "not_started")
        if phase not in PROFILE_UPLOAD_LANE_PHASES:
            phase = "not_started"
        try:
            progress = max(0, min(100, int(record.get("progress", 0))))
        except (TypeError, ValueError):
            progress = 0
        return {
            "status": status,
            "phase": phase,
            "progress": progress,
            "code": code,
            "updated_at": str(record.get("updated_at") or ""),
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class _PreparationFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code if code in _CODES else "PROFILE_UPLOAD_PREPARATION_FAILED"
        super().__init__(self.code)
