"""Read-only verification of a downloaded, cataloged worker backup."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from tme3bot.names import normalize_profile_name
from tme3bot.profile_diagnostics import PROFILE_TDL_DIAGNOSTIC_CODES


class _VerificationFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def verify_profile_backup(
    *,
    run_id: str,
    node_name: str,
    profile: str,
    parts_dir: Path,
    catalog_db: Path,
    settings_file: Path,
    tdl_diagnostics: Any | None = None,
    archive_factory: Callable[[Path, str], Any] | None = None,
) -> dict[str, Any]:
    """Verify part checksums, 7z password/integrity and profile session entries.

    The utility-settings password is held in process memory and is never included
    in the report. No member other than the manifest is extracted, and it is
    extracted only into an automatically removed private temporary directory.
    """
    normalized = normalize_profile_name(profile)
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    report: dict[str, Any] = {
        "worker": _safe_label(node_name),
        "profile": normalized or "invalid",
        "run_id": _safe_label(run_id),
        "checked_at": checked_at,
        "backup_started_at": None,
        "archive_created_at": None,
        "part_count": 0,
        "checksums_match": False,
        "integrity": "not_checked",
        "decryption": "not_checked",
        "sessions": [
            {"name": "root", "included": False},
            {"name": "user1", "included": False},
        ],
        "tdl_diagnostics": None,
        "canary_evidence_status": "tdl_not_attached",
        "status": "failed",
        "reason_codes": [],
    }
    if not normalized or not _valid_identifier(run_id) or not _valid_identifier(node_name):
        return _fail(report, "BACKUP_SELECTION_INVALID")
    if tdl_diagnostics is not None:
        try:
            report["tdl_diagnostics"] = _sanitize_tdl_diagnostics(
                tdl_diagnostics, node_name, normalized
            )
        except _VerificationFailure as exc:
            return _fail(report, exc.code)

    try:
        run, rows = _read_catalog(Path(catalog_db), run_id, node_name)
        report["backup_started_at"] = _safe_label(str(run.get("started_at") or "")) or None
        if str(run.get("status") or "") != "complete":
            raise _VerificationFailure("BACKUP_RUN_NOT_COMPLETE")
        parts = _validate_parts(Path(parts_dir), rows)
        report["part_count"] = len(parts)
        report["checksums_match"] = True
        password = _read_backup_password(Path(settings_file))
        factory = archive_factory or _load_py7zr_factory()

        with tempfile.TemporaryDirectory(prefix="profile-backup-verify-") as raw_temp:
            temp_root = Path(raw_temp)
            if os.name == "posix":
                temp_root.chmod(0o700)
            archive_path = _join_parts(parts, temp_root)
            archive_names: list[str] = []
            try:
                with factory(archive_path, password) as archive:
                    names = _archive_names(archive)
                    _validate_archive_names(archive, names)
                    archive_names = [_safe_archive_path(name) for name in names]
                    if "backup-manifest.json" not in names:
                        raise _VerificationFailure("BACKUP_MANIFEST_MISSING")
                    if not bool(archive.needs_password()):
                        raise _VerificationFailure("BACKUP_ARCHIVE_NOT_ENCRYPTED")
                    tested = archive.test()
                    if tested is not True:
                        report["integrity"] = "unverified"
                        raise _VerificationFailure("BACKUP_ARCHIVE_INTEGRITY_FAILED")
                    report["integrity"] = "verified"
                    report["decryption"] = "verified"
            except _VerificationFailure:
                raise
            except Exception as exc:
                raise _archive_failure(exc) from None

            manifest_dir = temp_root / "manifest"
            manifest_dir.mkdir(mode=0o700)
            try:
                with factory(archive_path, password) as archive:
                    archive.extract(path=manifest_dir, targets=["backup-manifest.json"])
            except Exception as exc:
                raise _archive_failure(exc) from None
            manifest_path = manifest_dir / "backup-manifest.json"
            if manifest_path.is_symlink() or not manifest_path.is_file():
                raise _VerificationFailure("BACKUP_MANIFEST_MISSING")
            if manifest_path.stat().st_size > 2 * 1024 * 1024:
                raise _VerificationFailure("BACKUP_MANIFEST_INVALID")
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise _VerificationFailure("BACKUP_MANIFEST_INVALID") from None
            _verify_manifest_selection(manifest, run_id, node_name)
            report["archive_created_at"] = str(manifest.get("created_at") or "")
            included = manifest.get("included")
            if not isinstance(included, list):
                raise _VerificationFailure("BACKUP_MANIFEST_INVALID")
            safe_entries = [_safe_archive_path(item) for item in included]
            expected_root, expected_user1 = _expected_session_prefixes(normalized)
            session_results = [
                {
                    "name": "root",
                    "included": _has_bolt_session(safe_entries, expected_root)
                    and _has_bolt_session(archive_names, expected_root),
                },
                {
                    "name": "user1",
                    "included": _has_bolt_session(safe_entries, expected_user1)
                    and _has_bolt_session(archive_names, expected_user1),
                },
            ]
            report["sessions"] = session_results
            if not all(item["included"] for item in session_results):
                raise _VerificationFailure("BACKUP_PROFILE_SESSIONS_INCOMPLETE")

        report["status"] = "verified"
        report["reason_codes"] = []
        if report["tdl_diagnostics"] is None:
            report["canary_evidence_status"] = "tdl_not_attached"
        elif not report["tdl_diagnostics"]["ready"]:
            report["canary_evidence_status"] = "tdl_failed"
        else:
            report["canary_evidence_status"] = "ready_for_operator_review"
        return report
    except _VerificationFailure as exc:
        return _fail(report, exc.code)
    except Exception:
        return _fail(report, "BACKUP_VERIFICATION_FAILED")


def _read_catalog(database: Path, run_id: str, node_name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if database.is_symlink() or not database.is_file():
        raise _VerificationFailure("BACKUP_CATALOG_UNAVAILABLE")
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            run_row = connection.execute(
                "SELECT run_id, node_name, started_at, status FROM backup_runs WHERE run_id=? AND node_name=?",
                (run_id, node_name),
            ).fetchone()
            rows = connection.execute(
                "SELECT part_name, file_size, sha256, status FROM backup_parts WHERE run_id=? AND node_name=? ORDER BY part_name",
                (run_id, node_name),
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        raise _VerificationFailure("BACKUP_CATALOG_UNAVAILABLE") from None
    if run_row is None or not rows:
        raise _VerificationFailure("BACKUP_CATALOG_ENTRY_MISSING")
    return dict(run_row), [dict(row) for row in rows]


def _validate_parts(parts_dir: Path, rows: list[dict[str, Any]]) -> list[Path]:
    if parts_dir.is_symlink() or not parts_dir.is_dir():
        raise _VerificationFailure("BACKUP_PARTS_DIRECTORY_INVALID")
    expected: list[tuple[str, int, str]] = []
    for row in rows:
        name = str(row.get("part_name") or "")
        size = row.get("file_size")
        digest = str(row.get("sha256") or "").lower()
        if not _safe_part_name(name) or not isinstance(size, int) or size < 1 or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise _VerificationFailure("BACKUP_CATALOG_CHECKSUM_MISSING")
        if str(row.get("status") or "") != "active":
            raise _VerificationFailure("BACKUP_PART_NOT_ACTIVE")
        expected.append((name, size, digest))
    expected.sort(key=lambda item: item[0])
    if len({item[0] for item in expected}) != len(expected):
        raise _VerificationFailure("BACKUP_CATALOG_INVALID")
    paths: list[Path] = []
    for name, expected_size, expected_digest in expected:
        path = parts_dir / name
        if path.is_symlink() or not path.is_file():
            raise _VerificationFailure("BACKUP_PART_MISSING")
        digest, size = _hash_file(path)
        if size != expected_size or digest != expected_digest:
            raise _VerificationFailure("BACKUP_PART_CHECKSUM_MISMATCH")
        paths.append(path)
    _validate_part_sequence(paths)
    return paths


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        raise _VerificationFailure("BACKUP_PART_UNREADABLE") from None
    return digest.hexdigest(), size


def _validate_part_sequence(paths: list[Path]) -> None:
    if len(paths) == 1 and paths[0].name.lower().endswith(".7z"):
        return
    first = paths[0].name
    match = re.fullmatch(r"(.+\.7z)\.(\d{3,4})", first, flags=re.IGNORECASE)
    if not match or int(match.group(2)) != 1:
        raise _VerificationFailure("BACKUP_PART_SEQUENCE_INVALID")
    base = match.group(1)
    width = len(match.group(2))
    for index, path in enumerate(paths, start=1):
        if path.name.lower() != f"{base}.{index:0{width}d}".lower():
            raise _VerificationFailure("BACKUP_PART_SEQUENCE_INVALID")


def _join_parts(parts: list[Path], temp_root: Path) -> Path:
    total_size = sum(path.stat().st_size for path in parts)
    if shutil.disk_usage(temp_root).free < total_size:
        raise _VerificationFailure("BACKUP_TEMP_SPACE_INSUFFICIENT")
    archive_path = temp_root / "selected-backup.7z"
    try:
        with archive_path.open("xb") as output:
            for part in parts:
                with part.open("rb") as source:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        if os.name == "posix":
            archive_path.chmod(0o600)
    except OSError:
        raise _VerificationFailure("BACKUP_PART_UNREADABLE") from None
    return archive_path


def _read_backup_password(settings_file: Path) -> str:
    if settings_file.is_symlink() or not settings_file.is_file():
        raise _VerificationFailure("BACKUP_PASSWORD_UNAVAILABLE")
    try:
        if os.name == "posix" and stat.S_IMODE(settings_file.stat().st_mode) & 0o077:
            raise _VerificationFailure("BACKUP_PASSWORD_STORE_NOT_PRIVATE")
        payload = json.loads(settings_file.read_text(encoding="utf-8"))
    except _VerificationFailure:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise _VerificationFailure("BACKUP_PASSWORD_UNAVAILABLE") from None
    password = str(payload.get("compress_password") or "") if isinstance(payload, dict) else ""
    if not password:
        raise _VerificationFailure("BACKUP_PASSWORD_UNAVAILABLE")
    return password


def _load_py7zr_factory() -> Callable[[Path, str], Any]:
    try:
        import py7zr
    except ImportError:
        raise _VerificationFailure("BACKUP_VERIFIER_DEPENDENCY_MISSING") from None
    return lambda path, password: py7zr.SevenZipFile(path, mode="r", password=password)


def _archive_names(archive: Any) -> list[str]:
    try:
        names = [str(name) for name in archive.getnames()]
        entries = archive.list()
    except Exception as exc:
        raise _archive_failure(exc) from None
    for entry in entries:
        if bool(getattr(entry, "is_symlink", False)) or bool(getattr(entry, "is_hardlink", False)):
            raise _VerificationFailure("BACKUP_ARCHIVE_UNSAFE_ENTRY")
    return names


def _validate_archive_names(archive: Any, names: list[str]) -> None:
    del archive
    seen: set[str] = set()
    try:
        for name in names:
            safe_name = _safe_archive_path(name)
            folded_name = safe_name.casefold()
            if folded_name in seen:
                raise _VerificationFailure("BACKUP_ARCHIVE_DUPLICATE_ENTRY")
            seen.add(folded_name)
    except _VerificationFailure:
        raise
    except Exception:
        raise _VerificationFailure("BACKUP_ARCHIVE_UNSAFE_ENTRY") from None


def _safe_archive_path(value: Any) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."} or "\x00" in value or "\\" in value:
        raise _VerificationFailure("BACKUP_ARCHIVE_UNSAFE_ENTRY")
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise _VerificationFailure("BACKUP_ARCHIVE_UNSAFE_ENTRY")
    if path.parts and ":" in path.parts[0]:
        raise _VerificationFailure("BACKUP_ARCHIVE_UNSAFE_ENTRY")
    return path.as_posix().rstrip("/")


def _verify_manifest_selection(manifest: Any, run_id: str, node_name: str) -> None:
    if not isinstance(manifest, dict):
        raise _VerificationFailure("BACKUP_MANIFEST_INVALID")
    if str(manifest.get("run_id") or "") != run_id or str(manifest.get("node_name") or "") != node_name:
        raise _VerificationFailure("BACKUP_MANIFEST_SELECTION_MISMATCH")
    created_at = str(manifest.get("created_at") or "")
    if not created_at or len(created_at) > 64:
        raise _VerificationFailure("BACKUP_MANIFEST_INVALID")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        raise _VerificationFailure("BACKUP_MANIFEST_INVALID") from None


def _expected_session_prefixes(profile: str) -> tuple[str, str]:
    if profile == "default":
        return "data/root/.tdl/data/", "data/user1/.tdl/data/"
    base = f"data/profiles/{profile}/"
    return base + "root/.tdl/data/", base + "user1/.tdl/data/"


def _sanitize_tdl_diagnostics(payload: Any, worker: str, profile: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _VerificationFailure("TDL_DIAGNOSTIC_INPUT_INVALID")
    if payload.get("worker") != worker or payload.get("profile") != profile:
        raise _VerificationFailure("TDL_DIAGNOSTIC_SELECTION_MISMATCH")
    checked_at = str(payload.get("checked_at") or "")
    try:
        if len(checked_at) > 64:
            raise ValueError
        datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError:
        raise _VerificationFailure("TDL_DIAGNOSTIC_INPUT_INVALID") from None
    raw_sessions = payload.get("sessions")
    if not isinstance(raw_sessions, list):
        raise _VerificationFailure("TDL_DIAGNOSTIC_INPUT_INVALID")
    sessions: dict[str, dict[str, Any]] = {}
    for item in raw_sessions:
        if not isinstance(item, dict) or item.get("name") not in {"root", "user1"}:
            raise _VerificationFailure("TDL_DIAGNOSTIC_INPUT_INVALID")
        name = str(item["name"])
        if name in sessions or type(item.get("ready")) is not bool:
            raise _VerificationFailure("TDL_DIAGNOSTIC_INPUT_INVALID")
        code = str(item.get("code") or "")
        if code not in PROFILE_TDL_DIAGNOSTIC_CODES or type(item.get("identity_matches_metadata")) is not bool:
            raise _VerificationFailure("TDL_DIAGNOSTIC_INPUT_INVALID")
        sessions[name] = {
            "name": name,
            "ready": item["ready"],
            "code": code,
            "identity_matches_metadata": item["identity_matches_metadata"],
        }
    if set(sessions) != {"root", "user1"}:
        raise _VerificationFailure("TDL_DIAGNOSTIC_INPUT_INVALID")
    reasons = payload.get("reason_codes")
    if not isinstance(reasons, list) or any(str(code) not in PROFILE_TDL_DIAGNOSTIC_CODES for code in reasons):
        raise _VerificationFailure("TDL_DIAGNOSTIC_INPUT_INVALID")
    if type(payload.get("ready")) is not bool or type(payload.get("identity_match")) is not bool:
        raise _VerificationFailure("TDL_DIAGNOSTIC_INPUT_INVALID")
    return {
        "worker": worker,
        "profile": profile,
        "checked_at": checked_at,
        "ready": payload["ready"],
        "identity_match": payload["identity_match"],
        "reason_codes": list(dict.fromkeys(str(code) for code in reasons)),
        "sessions": [sessions["root"], sessions["user1"]],
    }


def _has_bolt_session(entries: list[str], prefix: str) -> bool:
    return any(
        entry.startswith(prefix)
        and bool(entry[len(prefix):])
        and "/" not in entry[len(prefix):]
        for entry in entries
    )


def _archive_failure(exc: BaseException) -> _VerificationFailure:
    name = type(exc).__name__.lower()
    if "password" in name or "decrypt" in name:
        return _VerificationFailure("BACKUP_PASSWORD_INVALID")
    if name == "typeerror":
        # py7zr reports an invalid encrypted header as TypeError in some
        # versions, so avoid exposing internals or claiming corruption alone.
        return _VerificationFailure("BACKUP_PASSWORD_OR_HEADER_INVALID")
    if "path" in name or "symlink" in name:
        return _VerificationFailure("BACKUP_ARCHIVE_UNSAFE_ENTRY")
    return _VerificationFailure("BACKUP_ARCHIVE_INTEGRITY_FAILED")


def _valid_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", str(value or "")))


def _safe_part_name(value: str) -> bool:
    return (
        bool(value)
        and Path(value).name == value
        and bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", value))
        and ".7z" in value.lower()
    )


def _safe_label(value: str) -> str:
    return str(value or "")[:128]


def _fail(report: dict[str, Any], code: str) -> dict[str, Any]:
    report["status"] = "failed"
    report["reason_codes"] = [code]
    if code.startswith("BACKUP_PASSWORD"):
        report["decryption"] = "failed"
    elif code == "BACKUP_ARCHIVE_NOT_ENCRYPTED":
        report["decryption"] = "not_encrypted"
    elif code == "BACKUP_ARCHIVE_INTEGRITY_FAILED":
        report["integrity"] = "failed"
    if report.get("tdl_diagnostics") is None:
        report["canary_evidence_status"] = "tdl_not_attached"
    elif not report["tdl_diagnostics"].get("ready"):
        report["canary_evidence_status"] = "tdl_failed"
    else:
        report["canary_evidence_status"] = "backup_failed"
    return report
