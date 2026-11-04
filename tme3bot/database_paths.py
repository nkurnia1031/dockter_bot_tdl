"""Private, predictable locations for application database files."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Callable

from tme3bot.names import normalize_profile_name


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class DatabasePaths:
    """Resolve SQLite and TDL paths beneath one mounted database root."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _safe_join(self, *parts: str) -> Path:
        root = Path(os.path.abspath(self.root))
        candidate = root.joinpath(*parts)
        if _contains_symlink(candidate):
            raise ValueError("Database path must not cross a symlink.")
        try:
            candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        except ValueError as exc:
            raise ValueError("Database path resolves outside DATABASE_ROOT.") from exc
        return candidate

    def sqlite(self, name: str) -> Path:
        raw = str(name or "")
        if "\\" in raw:
            raise ValueError("Database path must use relative POSIX segments.")
        relative = PurePosixPath(raw)
        if relative.is_absolute() or not relative.parts:
            raise ValueError("Database path must be relative to DATABASE_ROOT.")
        if any(part in {"", ".", ".."} or not _SAFE_SEGMENT.fullmatch(part) for part in relative.parts):
            raise ValueError("Database path contains an unsafe segment.")
        return self._safe_join(*relative.parts)

    def tdl(self, profile: str, lane: str) -> Path:
        normalized = normalize_profile_name(str(profile or ""))
        if not normalized:
            raise ValueError("Invalid profile name for TDL database path.")
        lane_name = str(lane or "").strip().lower()
        if not _SAFE_SEGMENT.fullmatch(lane_name):
            raise ValueError("Invalid lane name for TDL database path.")
        return self._safe_join("tdl", normalized, lane_name, ".tdl")

    def tdl_staging(self, profile: str, lane: str, operation_id: str) -> Path:
        normalized = normalize_profile_name(str(profile or ""))
        lane_name = str(lane or "").strip().lower()
        operation = str(operation_id or "").strip()
        if not normalized or not _SAFE_SEGMENT.fullmatch(lane_name):
            raise ValueError("Invalid profile or lane for TDL staging path.")
        if not _SAFE_SEGMENT.fullmatch(operation):
            raise ValueError("Invalid operation ID for TDL staging path.")
        return self._safe_join("tdl-staging", normalized, lane_name, operation, ".tdl")


def set_private_file_creation_umask() -> int | None:
    """Make new SQLite/Bolt files private for the lifetime of this process."""

    if os.name != "posix":
        return None
    return os.umask(0o077)


def ensure_private_directory(path: Path | str) -> Path:
    directory = Path(path)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        directory.chmod(0o700)
    return directory


@dataclass(frozen=True)
class FilesystemIdentity:
    device: int
    mount_point: str | None


@dataclass(frozen=True)
class DatabaseRootValidation:
    path: Path
    physically_isolated: bool
    warnings: tuple[str, ...] = ()


def _nearest_existing_path(path: Path) -> Path:
    current = path
    while not current.exists() and not current.is_symlink() and current != current.parent:
        current = current.parent
    return current


def filesystem_identity(path: Path | str) -> FilesystemIdentity:
    """Return device and mount target for a path, even if its leaf is absent."""

    candidate = _nearest_existing_path(Path(path).expanduser().absolute())
    device = os.stat(candidate).st_dev
    mount_point: str | None = None
    try:
        result = subprocess.run(
            ["findmnt", "--noheadings", "--raw", "--output", "TARGET", "--target", str(candidate)],
            check=True,
            capture_output=True,
            text=True,
        )
        value = result.stdout.strip()
        if value:
            mount_point = os.path.realpath(value)
    except (OSError, subprocess.CalledProcessError):
        pass
    return FilesystemIdentity(device, mount_point)


def _same_filesystem(left: FilesystemIdentity, right: FilesystemIdentity) -> bool:
    # Device IDs identify the mounted filesystem. A bind mount of the same
    # root filesystem can have a different mountpoint while remaining on the
    # same underlying filesystem/device.
    return left.device == right.device


def _contains_symlink(path: Path) -> bool:
    current = Path(path.anchor)
    for segment in path.parts[1:]:
        current = current / segment
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError:
            continue
        if stat.S_ISLNK(mode):
            return True
    return False


def validate_database_root(
    database_root: Path | str,
    *,
    data_paths: list[Path] | tuple[Path, ...],
    workspace_paths: list[Path] | tuple[Path, ...],
    filesystem_identity: Callable[[Path | str], FilesystemIdentity] = filesystem_identity,
) -> DatabaseRootValidation:
    """Validate host DATABASE_ROOT against OS, data, and workspace filesystems."""

    raw_path = Path(database_root).expanduser()
    if not raw_path.is_absolute():
        raise ValueError("DATABASE_ROOT harus berupa absolute host path.")
    path = Path(os.path.abspath(raw_path))
    if _contains_symlink(path):
        raise ValueError("DATABASE_ROOT tidak boleh melewati symlink.")

    os_filesystem = filesystem_identity(Path("/"))
    database_filesystem = filesystem_identity(path)
    if not _same_filesystem(database_filesystem, os_filesystem):
        raise ValueError("DATABASE_ROOT harus berada pada filesystem root OS.")
    if (
        database_filesystem.mount_point
        and os_filesystem.mount_point
        and database_filesystem.mount_point != os_filesystem.mount_point
    ):
        raise ValueError(
            "DATABASE_ROOT tidak boleh berada pada mount tersarang; gunakan filesystem root OS langsung."
        )

    separate_storage: list[tuple[str, FilesystemIdentity]] = []
    for label, candidates in (("data", data_paths), ("workspace", workspace_paths)):
        for candidate in candidates:
            if not str(candidate).strip():
                continue
            identity = filesystem_identity(candidate)
            if not _same_filesystem(identity, os_filesystem):
                separate_storage.append((label, identity))

    if separate_storage:
        for label, identity in separate_storage:
            if _same_filesystem(database_filesystem, identity):
                raise ValueError(
                    f"DATABASE_ROOT tidak boleh berada pada filesystem {label}."
                )
        return DatabaseRootValidation(path, True)

    return DatabaseRootValidation(
        path,
        False,
        ("Host hanya memiliki satu filesystem untuk OS, data, dan workspace; isolasi database bersifat direktori saja.",),
    )
