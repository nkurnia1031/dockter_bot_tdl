from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def emit_progress(**values: Any) -> None:
    print("TME3_PROGRESS " + json.dumps(values, ensure_ascii=True), flush=True)


def get_multipart_group(filepath: Path) -> list[Path]:
    folder = filepath.parent
    filename = filepath.name
    lower = filename.lower()

    part_rar = re.match(r"(.+)\.part\d+\.rar$", filename, re.IGNORECASE)
    if part_rar:
        base = re.escape(part_rar.group(1))
        pattern = re.compile(rf"^{base}(?:\.part\d+\.rar|\.r\d+)$", re.IGNORECASE)
        return sorted(path for path in folder.iterdir() if pattern.match(path.name))

    split_7z = re.match(r"(.+\.7z)\.\d+$", filename, re.IGNORECASE)
    if split_7z:
        base = re.escape(split_7z.group(1))
        pattern = re.compile(rf"^{base}\.\d+$", re.IGNORECASE)
        return sorted(path for path in folder.iterdir() if pattern.match(path.name))

    split_zip = re.match(r"(.+)\.zip$", filename, re.IGNORECASE)
    if split_zip:
        base = re.escape(split_zip.group(1))
        pattern = re.compile(rf"^{base}(?:\.zip|\.z\d+)$", re.IGNORECASE)
        parts = sorted(path for path in folder.iterdir() if pattern.match(path.name))
        return parts if len(parts) > 1 else [filepath]

    if lower.endswith(".rar"):
        base = re.escape(filename[:-4])
        pattern = re.compile(rf"^{base}(?:\.rar|\.r\d+)$", re.IGNORECASE)
        return sorted(path for path in folder.iterdir() if pattern.match(path.name))

    return [filepath]


def is_main_part(filename: str) -> bool:
    lower = filename.lower()
    if re.match(r".+\.part\d+\.rar$", lower):
        return bool(re.match(r".+\.part0*1\.rar$", lower))
    return lower.endswith((".7z", ".zip", ".rar", ".7z.001"))


def get_extract_folder_name(filename: str) -> str:
    for pattern in (
        r"(.+)\.part\d+\.rar$",
        r"(.+\.7z)\.\d+$",
    ):
        match = re.match(pattern, filename, re.IGNORECASE)
        if match:
            return Path(match.group(1)).name
    return Path(filename).stem


def archive_password_candidates(filepath: Path, supplied_password: str | None) -> list[str]:
    """Return the first-pass candidates without logging or exposing their values."""
    primary = supplied_password if supplied_password else filepath.parent.name
    candidates: list[str] = []
    if primary:
        candidates.append(primary)
    try:
        pass_file = filepath.parent / ".pass"
        stored = (
            pass_file.read_text(encoding="utf-8").strip()
            if pass_file.is_file() and not pass_file.is_symlink()
            else ""
        )
    except OSError:
        stored = ""
    if stored and stored not in candidates:
        candidates.append(stored)
    return candidates


def _unique_output_directory(filepath: Path) -> Path:
    base = filepath.parent / get_extract_folder_name(filepath.name)
    if not base.exists() and not base.is_symlink():
        return base
    suffix = 2
    while True:
        candidate = base.with_name(f"{base.name}_{suffix}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        suffix += 1


def _command_for(
    filepath: Path, password: str | None, output: Path
) -> list[str]:
    lower = filepath.name.lower()
    if lower.endswith((".7z", ".7z.001", ".zip")):
        # Per-member output is needed to distinguish a genuine partial extract
        # from zero-byte files left behind after a password prompt/error.
        command = ["7z", "x", "-bb1"]
        if password is not None:
            command.append(f"-p{password}")
        command.extend(["-y", str(filepath), f"-o{output}", "-bsp0"])
        return command
    if lower.endswith(".rar"):
        command = ["unar", "-force-overwrite", "-no-directory"]
        if password is not None:
            command.extend(["-password", password])
        command.extend(["-output-directory", str(output), str(filepath)])
        return command
    raise ValueError("Format arsip tidak didukung.")


def run_extract(
    command: list[str],
    *,
    filepath: Path,
    output: Path,
    pass_name: str,
    index: int,
    total: int,
    attempt: int,
) -> "ExtractorRun":
    """Run one isolated extraction attempt and keep the job heartbeat alive."""
    started = time.monotonic()
    with tempfile.TemporaryFile() as tool_log:
        try:
            process = subprocess.Popen(
                command,
                cwd=str(filepath.parent),
                stdin=subprocess.DEVNULL,
                stdout=tool_log,
                stderr=subprocess.STDOUT,
                start_new_session=False,
            )
        except OSError:
            return ExtractorRun(returncode=None, output="")

        while process.poll() is None:
            time.sleep(2)
            elapsed = time.monotonic() - started
            emit_progress(
                phase="archive_extracting",
                pass_name=pass_name,
                index=index,
                total=total,
                name=filepath.name,
                attempt=attempt,
                elapsed_seconds=round(elapsed, 1),
                indeterminate=True,
            )
        tool_log.seek(0)
        tool_output = tool_log.read().decode("utf-8", errors="replace")
    return ExtractorRun(returncode=process.returncode, output=tool_output)


@dataclass(frozen=True)
class ExtractorRun:
    returncode: int | None
    output: str


@dataclass(frozen=True)
class ArchiveAttempt:
    succeeded: bool
    output: Path | None = None
    partial: bool = False
    files_extracted: int = 0
    failed_files: int = 0
    successful_members: tuple[str, ...] = ()
    failed_members: tuple[str, ...] = ()
    unclassified_failure: bool = False


_UNAR_MEMBER_RESULT = re.compile(
    r"^\s*(?P<member>.+)\s+\([^)]*\)\.\.\.\s+(?P<status>OK\.?|Failed!|This archive requires a password to unpack\.)(?:\s|$)",
    re.IGNORECASE,
)
_SEVEN_Z_MEMBER_ERROR = re.compile(
    # 7z separates the error description from the member with " : ". Match
    # that first spaced separator so colons inside a member filename survive.
    r"^\s*ERROR:.*?\s+:\s+(?P<member>.+?)\s*$", re.IGNORECASE
)
_SEVEN_Z_MEMBER_SUCCESS = re.compile(r"^\s*-\s+(?P<member>.+?)\s*$")


def _regular_output_files(output: Path) -> list[Path]:
    if not output.is_dir() or output.is_symlink():
        return []
    files: list[Path] = []
    for path in output.rglob("*"):
        try:
            if not path.is_symlink() and path.is_file():
                files.append(path)
        except OSError:
            continue
    return files


def _normalize_member_name(raw_member: str) -> str:
    member = raw_member.strip().strip("\"'").replace("\\", "/")
    while member.startswith("./"):
        member = member[2:]
    return member.lstrip("/")


def _member_name_relative_to_output(raw_member: str, output: Path) -> str:
    member = _normalize_member_name(raw_member)
    output_prefix = output.as_posix().lstrip("/") + "/"
    if member.startswith(output_prefix):
        member = member[len(output_prefix) :]
    return member


def _member_files(
    members: list[str],
    output: Path,
    files: list[Path],
    *,
    allow_basename_fallback: bool = True,
) -> set[Path]:
    matched: set[Path] = set()
    for raw_member in members:
        member = _member_name_relative_to_output(raw_member, output)
        if not member:
            continue
        matches = [
            path
            for path in files
            if (
                path.relative_to(output).as_posix() == member
                or (
                    "/" in member
                    and path.relative_to(output).as_posix().endswith("/" + member)
                )
            )
        ]
        if not matches and allow_basename_fallback and "/" not in member:
            basename = member.rsplit("/", 1)[-1]
            matches = [path for path in files if path.name == basename]
        matched.update(matches)
    return matched


def _staged_file_results(
    command: list[str], tool_output: str, output: Path, returncode: int | None
) -> tuple[list[Path], tuple[str, ...], bool]:
    files = _regular_output_files(output)
    successful_members: list[str] = []
    failed_members: list[str] = []
    tool = Path(command[0]).name.lower()
    for line in tool_output.splitlines():
        if tool == "unar":
            match = _UNAR_MEMBER_RESULT.match(line)
            if not match:
                continue
            status = match.group("status").lower()
            if status.startswith("failed") or status.startswith(
                "this archive requires a password"
            ):
                failed_members.append(match.group("member"))
            else:
                successful_members.append(match.group("member"))
        elif tool in {"7z", "7zz"}:
            failed_match = _SEVEN_Z_MEMBER_ERROR.match(line)
            if failed_match:
                failed_members.append(failed_match.group("member"))
                continue
            successful_match = _SEVEN_Z_MEMBER_SUCCESS.match(line)
            if successful_match:
                successful_members.append(successful_match.group("member"))

    failed_member_matches = [_member_files([member], output, files) for member in failed_members]
    failed_files = set().union(*failed_member_matches) if failed_member_matches else set()
    # Partial success must be explicit in the extractor's per-member output.
    # Inferring success from files merely present in staging misclassifies
    # zero-byte placeholders left by bad passwords or corrupt archives.
    successful_files = _member_files(successful_members, output, files)
    successful_files.difference_update(failed_files)
    has_unclassified_error = False
    if tool in {"7z", "7zz"}:
        # With -bb1, 7z emits "- member" before attempting to write it. A
        # password prompt can therefore leave that line plus a zero-byte
        # placeholder. A non-zero exit without identifiable per-member errors
        # (or with a generic error) cannot distinguish that placeholder from a
        # genuine empty file. When 7z names a specific failed member, other
        # listed members can still be accepted, including successful empty
        # files; matching failed paths were removed above.
        has_unclassified_error = any(
            line.lstrip().upper().startswith("ERROR:")
            and _SEVEN_Z_MEMBER_ERROR.match(line) is None
            for line in tool_output.splitlines()
        )
        if returncode not in (None, 0) and (
            not failed_members or has_unclassified_error
        ):
            successful_files = set()
    normalized_failures = {
        _member_name_relative_to_output(member, output) for member in failed_members
    }
    return sorted(successful_files), tuple(sorted(normalized_failures)), has_unclassified_error


def _retain_only_staged_files(output: Path, keep: list[Path]) -> bool:
    kept_files = set(keep)
    entries = sorted(output.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    try:
        for path in entries:
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                if not any(path.iterdir()):
                    path.rmdir()
            elif path not in kept_files:
                path.unlink()
    except OSError:
        return False
    return True


def _publish_staging(staging: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Folder output sudah ada: {destination.name}")
    staging.rename(destination)


def _open_directory_no_follow(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(os.path.sep, flags)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError:
        os.close(current_fd)
        raise


def _open_relative_directory(root_fd: int, parts: tuple[str, ...], *, create: bool) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.dup(root_fd)
    try:
        for component in parts:
            if component in {"", ".", ".."}:
                raise ValueError("Arsip berisi path anggota yang tidak valid.")
            if create:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=current_fd)
                except FileExistsError:
                    pass
            next_fd = os.open(component, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except (OSError, ValueError):
        os.close(current_fd)
        raise


def _copy_partial_member_no_follow(
    source_root: Path, destination_root: Path, relative: Path
) -> bool:
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return False
    source_root_fd = destination_root_fd = source_parent_fd = None
    destination_parent_fd = source_fd = temporary_fd = None
    temporary_name: str | None = None
    temporary_identity: tuple[int, int] | None = None
    try:
        source_root_fd = _open_directory_no_follow(source_root)
        destination_root_fd = _open_directory_no_follow(destination_root)
        source_parent_fd = _open_relative_directory(
            source_root_fd, parts[:-1], create=False
        )
        destination_parent_fd = _open_relative_directory(
            destination_root_fd, parts[:-1], create=True
        )
        source_name = parts[-1]
        source_fd = os.open(
            source_name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=source_parent_fd,
        )
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode):
            return False
        try:
            os.stat(source_name, dir_fd=destination_parent_fd, follow_symlinks=False)
            return False
        except FileNotFoundError:
            pass

        temporary_name = f".extract-merge-{os.urandom(12).hex()}.tmp"
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=destination_parent_fd,
        )
        temporary_stat = os.fstat(temporary_fd)
        temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                written = os.write(temporary_fd, view)
                if written <= 0:
                    raise OSError("Gagal menulis hasil merge sementara.")
                view = view[written:]
        final_source_stat = os.fstat(source_fd)
        if (
            final_source_stat.st_dev != source_stat.st_dev
            or final_source_stat.st_ino != source_stat.st_ino
            or final_source_stat.st_size != source_stat.st_size
            or final_source_stat.st_mtime_ns != source_stat.st_mtime_ns
        ):
            raise OSError("File hasil percobaan berubah saat merge.")
        os.fchmod(temporary_fd, stat.S_IMODE(source_stat.st_mode))
        os.fsync(temporary_fd)
        temporary_entry = os.stat(
            temporary_name,
            dir_fd=destination_parent_fd,
            follow_symlinks=False,
        )
        if (temporary_entry.st_dev, temporary_entry.st_ino) != temporary_identity:
            raise OSError("File merge sementara berubah sebelum publikasi.")
        os.link(
            temporary_name,
            source_name,
            src_dir_fd=destination_parent_fd,
            dst_dir_fd=destination_parent_fd,
            follow_symlinks=False,
        )
        published_stat = os.stat(
            source_name,
            dir_fd=destination_parent_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(published_stat.st_mode)
            or (published_stat.st_dev, published_stat.st_ino) != temporary_identity
        ):
            raise OSError("File merge yang dipublikasikan tidak cocok.")
        return True
    except (OSError, ValueError):
        return False
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        if temporary_name is not None and destination_parent_fd is not None:
            try:
                temporary_entry = os.stat(
                    temporary_name,
                    dir_fd=destination_parent_fd,
                    follow_symlinks=False,
                )
                if (
                    temporary_identity is not None
                    and (temporary_entry.st_dev, temporary_entry.st_ino)
                    == temporary_identity
                ):
                    os.unlink(temporary_name, dir_fd=destination_parent_fd)
            except (FileNotFoundError, OSError):
                pass
        for descriptor in (
            source_fd,
            source_parent_fd,
            destination_parent_fd,
            source_root_fd,
            destination_root_fd,
        ):
            if descriptor is not None:
                os.close(descriptor)


def _discard_partial_output(
    filepath: Path, output: Path | None, workspace_root: Path
) -> bool:
    if output is None:
        return True
    try:
        if output.is_symlink():
            return False
        source_parent = filepath.parent.resolve(strict=True)
        source_parent.relative_to(workspace_root)
        output_path = output.resolve(strict=True)
        output_name = re.escape(get_extract_folder_name(filepath.name))
        if (
            output_path.parent != source_parent
            or not output_path.is_dir()
            or not re.fullmatch(rf"{output_name}(?:_[2-9]|_[1-9]\d+)?", output_path.name)
        ):
            return False
        parent_fd = _open_directory_no_follow(source_parent)
        try:
            root_stat = os.stat(output.name, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISDIR(root_stat.st_mode):
                return False
            return _remove_tree_at(
                parent_fd,
                output.name,
                expected_identity=(root_stat.st_dev, root_stat.st_ino),
            )
        finally:
            os.close(parent_fd)
    except (OSError, ValueError):
        return False


def _remove_tree_at(
    parent_fd: int,
    name: str,
    *,
    expected_identity: tuple[int, int] | None = None,
) -> bool:
    try:
        entry_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        identity = (entry_stat.st_dev, entry_stat.st_ino)
        if expected_identity is not None and identity != expected_identity:
            return False
        if not stat.S_ISDIR(entry_stat.st_mode):
            os.unlink(name, dir_fd=parent_fd)
            return True

        child_fd = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        try:
            opened_stat = os.fstat(child_fd)
            if (opened_stat.st_dev, opened_stat.st_ino) != identity:
                return False
            for child_name in os.listdir(child_fd):
                if not _remove_tree_at(child_fd, child_name):
                    return False
            current_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (current_stat.st_dev, current_stat.st_ino) != identity:
                return False
            os.rmdir(name, dir_fd=parent_fd)
        finally:
            os.close(child_fd)
    except OSError:
        return False
    return True


def _merge_partial_attempts(
    filepath: Path,
    current: ArchiveAttempt | None,
    candidate: ArchiveAttempt,
    workspace_root: Path,
) -> ArchiveAttempt:
    if current is None:
        return candidate
    if current.output is None or candidate.output is None:
        _discard_partial_output(filepath, candidate.output, workspace_root)
        return current
    try:
        source_parent = filepath.parent.resolve(strict=True)
        source_parent.relative_to(workspace_root)
        output_root = current.output.resolve(strict=True)
        candidate_root = candidate.output.resolve(strict=True)
        if (
            current.output.is_symlink()
            or candidate.output.is_symlink()
            or output_root.parent != source_parent
            or candidate_root.parent != source_parent
        ):
            _discard_partial_output(filepath, candidate.output, workspace_root)
            return current
        for source in _regular_output_files(candidate_root):
            relative = source.relative_to(candidate_root)
            destination = output_root / relative
            if destination.exists() or destination.is_symlink():
                continue
            _copy_partial_member_no_follow(candidate_root, output_root, relative)
    except (OSError, ValueError):
        _discard_partial_output(filepath, candidate.output, workspace_root)
        return current

    files = _regular_output_files(output_root)
    observed_members = set(current.successful_members)
    observed_members.update(candidate.successful_members)
    observed_members.update(current.failed_members)
    observed_members.update(candidate.failed_members)
    unresolved_members = {
        member
        for member in observed_members
        if not _member_files(
            [member], output_root, files, allow_basename_fallback=False
        )
    }
    unclassified_failure = (
        current.unclassified_failure or candidate.unclassified_failure
    )
    partial = bool(unresolved_members) or unclassified_failure
    merged = ArchiveAttempt(
        succeeded=True,
        output=current.output,
        partial=partial,
        files_extracted=len(files),
        failed_files=max(len(unresolved_members), int(unclassified_failure)),
        successful_members=tuple(
            sorted(path.relative_to(output_root).as_posix() for path in files)
        ),
        failed_members=tuple(sorted(unresolved_members)),
        unclassified_failure=unclassified_failure,
    )
    _discard_partial_output(filepath, candidate.output, workspace_root)
    return merged


def _remove_archive_parts(filepath: Path) -> str:
    cleanup_status = "deleted"
    for part in get_multipart_group(filepath):
        try:
            part.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            cleanup_status = "failed"
    return cleanup_status


def _attempt_archive(
    filepath: Path,
    password: str | None,
    *,
    index: int,
    total: int,
    pass_name: str,
    attempt: int,
) -> ArchiveAttempt:
    with tempfile.TemporaryDirectory(
        prefix=".extract-attempt-", dir=str(filepath.parent)
    ) as temporary:
        staging = Path(temporary) / "output"
        try:
            command = _command_for(filepath, password, staging)
        except ValueError:
            return ArchiveAttempt(succeeded=False)
        emit_progress(
            phase="archive_attempt",
            pass_name=pass_name,
            index=index,
            total=total,
            name=filepath.name,
            attempt=attempt,
            indeterminate=True,
        )
        run = run_extract(
            command,
            filepath=filepath,
            output=staging,
            pass_name=pass_name,
            index=index,
            total=total,
            attempt=attempt,
        )
        successful_files, failed_members, unclassified_failure = _staged_file_results(
            command, run.output, staging, run.returncode
        )
        failed_file_count = len(failed_members)
        if (
            Path(command[0]).name.lower() in {"7z", "7zz"}
            and run.returncode not in (None, 0)
            and not failed_members
        ):
            failed_file_count = 1
        complete = (
            run.returncode == 0
            and staging.is_dir()
            and failed_file_count == 0
        )
        partial = not complete and bool(successful_files)
        if not complete and not partial:
            return ArchiveAttempt(
                succeeded=False,
                failed_files=failed_file_count,
                failed_members=failed_members,
                unclassified_failure=unclassified_failure,
            )
        if partial and not _retain_only_staged_files(staging, successful_files):
            return ArchiveAttempt(
                succeeded=False,
                failed_files=failed_file_count,
                failed_members=failed_members,
                unclassified_failure=unclassified_failure,
            )
        destination = _unique_output_directory(filepath)
        try:
            _publish_staging(staging, destination)
        except OSError:
            return ArchiveAttempt(
                succeeded=False,
                failed_files=failed_file_count,
                failed_members=failed_members,
                unclassified_failure=unclassified_failure,
            )
        successful_members = tuple(
            sorted(path.relative_to(staging).as_posix() for path in successful_files)
        )
        return ArchiveAttempt(
            succeeded=True,
            output=destination,
            partial=partial,
            files_extracted=(len(successful_files) if partial else len(_regular_output_files(destination))),
            failed_files=failed_file_count,
            successful_members=successful_members,
            failed_members=failed_members,
            unclassified_failure=unclassified_failure,
        )


def _finalize_result(
    filepath: Path,
    *,
    status: str,
    pass_name: str,
    attempts: int,
    output: Path | None,
    partial: bool = False,
    files_extracted: int = 0,
    failed_files: int = 0,
) -> dict[str, Any]:
    cleanup_status = (
        "retained_partial"
        if status == "succeeded" and partial
        else (_remove_archive_parts(filepath) if status == "succeeded" else "retained_failed")
    )
    return {
        "name": filepath.name,
        "path": str(filepath),
        "status": status,
        "pass": "retry" if pass_name == "retry" else "first",
        "attempt_count": attempts,
        "output": str(output) if output is not None else None,
        "partial": partial,
        "files_extracted": files_extracted,
        "failed_files": failed_files,
        "cleanup_status": cleanup_status,
        "warning": (
            "Sebagian file arsip gagal diekstrak; hasil yang berhasil dipublikasikan dan arsip sumber dipertahankan."
            if partial
            else None
        ),
        "error": (
            "Ekstraksi tanpa password maupun dengan kandidat yang tersedia gagal."
            if status == "failed"
            else None
        ),
    }


def scan_directory(base_dir: Path, supplied_password: str | None) -> dict[str, Any]:
    base_dir = base_dir.resolve()
    archives = sorted(
        (
            path
            for path in base_dir.rglob("*")
            if path.is_file() and not path.is_symlink() and is_main_part(path.name)
        ),
        key=lambda path: str(path).casefold(),
    )
    total = len(archives)
    password_pool: list[str] = []
    records: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    succeeded = 0

    for index, filepath in enumerate(archives, start=1):
        tried: list[str | None] = []
        partial_attempt: ArchiveAttempt | None = None
        failed_file_count = 0
        candidates = archive_password_candidates(filepath, supplied_password)
        for candidate in candidates:
            if candidate not in password_pool:
                password_pool.append(candidate)
        # Some archive tools reject an unrelated explicit password even when
        # the archive is not encrypted. Try the established candidates first,
        # then run once without any password option.
        first_pass_candidates: list[str | None] = [*candidates, None]
        for attempt, candidate in enumerate(first_pass_candidates, start=1):
            tried.append(candidate)
            attempt_result = _attempt_archive(
                filepath,
                candidate,
                index=index,
                total=total,
                pass_name="first_pass",
                attempt=attempt,
            )
            failed_file_count = max(failed_file_count, attempt_result.failed_files)
            if attempt_result.succeeded and attempt_result.partial:
                partial_attempt = _merge_partial_attempts(
                    filepath, partial_attempt, attempt_result, base_dir
                )
                if partial_attempt.partial:
                    continue
                attempt_result = partial_attempt
            if attempt_result.succeeded:
                if (
                    partial_attempt is not None
                    and attempt_result.output != partial_attempt.output
                ):
                    _discard_partial_output(filepath, partial_attempt.output, base_dir)
                record = _finalize_result(
                    filepath,
                    status="succeeded",
                    pass_name="first_pass",
                    attempts=len(tried),
                    output=attempt_result.output,
                    partial=attempt_result.partial,
                    files_extracted=attempt_result.files_extracted,
                    failed_files=attempt_result.failed_files,
                )
                records.append(record)
                succeeded += 1
                emit_progress(
                    phase="archive_completed",
                    pass_name="first_pass",
                    index=index,
                    total=total,
                    name=filepath.name,
                    attempt_count=len(tried),
                    succeeded=succeeded,
                    failed=0,
                    partial=attempt_result.partial,
                    files_extracted=attempt_result.files_extracted,
                    failed_files=attempt_result.failed_files,
                    percent=100,
                    indeterminate=False,
                )
                break
        else:
            pending.append(
                {
                    "index": index,
                    "filepath": filepath,
                    "tried": tried,
                    "attempt_count": len(tried),
                    "partial_attempt": partial_attempt,
                    "partial_pass_name": "first_pass",
                    "failed_files": failed_file_count,
                }
            )

    failed = 0
    for item in pending:
        index = int(item["index"])
        filepath = Path(item["filepath"])
        tried = list(item["tried"])
        partial_attempt = item["partial_attempt"]
        partial_pass_name = str(item["partial_pass_name"])
        emit_progress(
            phase="archive_retrying",
            pass_name="retry",
            index=index,
            total=total,
            name=filepath.name,
            attempt_count=int(item["attempt_count"]),
            succeeded=succeeded,
            failed=failed,
            indeterminate=True,
        )
        for candidate in password_pool:
            if candidate in tried:
                continue
            tried.append(candidate)
            item["attempt_count"] = int(item["attempt_count"]) + 1
            attempt_result = _attempt_archive(
                filepath,
                candidate,
                index=index,
                total=total,
                pass_name="retry",
                attempt=int(item["attempt_count"]),
            )
            item["failed_files"] = max(
                int(item.get("failed_files", 0)), attempt_result.failed_files
            )
            if attempt_result.succeeded and attempt_result.partial:
                partial_attempt = _merge_partial_attempts(
                    filepath, partial_attempt, attempt_result, base_dir
                )
                partial_pass_name = "retry"
                if partial_attempt.partial:
                    continue
                attempt_result = partial_attempt
            if attempt_result.succeeded:
                if (
                    partial_attempt is not None
                    and attempt_result.output != partial_attempt.output
                ):
                    _discard_partial_output(filepath, partial_attempt.output, base_dir)
                record = _finalize_result(
                    filepath,
                    status="succeeded",
                    pass_name="retry",
                    attempts=int(item["attempt_count"]),
                    output=attempt_result.output,
                    partial=attempt_result.partial,
                    files_extracted=attempt_result.files_extracted,
                    failed_files=attempt_result.failed_files,
                )
                records.append(record)
                succeeded += 1
                emit_progress(
                    phase="archive_completed",
                    pass_name="retry",
                    index=index,
                    total=total,
                    name=filepath.name,
                    attempt_count=int(item["attempt_count"]),
                    succeeded=succeeded,
                    failed=failed,
                    partial=attempt_result.partial,
                    files_extracted=attempt_result.files_extracted,
                    failed_files=attempt_result.failed_files,
                    percent=100,
                    indeterminate=False,
                )
                break
        else:
            if partial_attempt is not None:
                succeeded += 1
                record = _finalize_result(
                    filepath,
                    status="succeeded",
                    pass_name=partial_pass_name,
                    attempts=int(item["attempt_count"]),
                    output=partial_attempt.output,
                    partial=True,
                    files_extracted=partial_attempt.files_extracted,
                    failed_files=partial_attempt.failed_files,
                )
                emit_progress(
                    phase="archive_completed",
                    pass_name=partial_pass_name,
                    index=index,
                    total=total,
                    name=filepath.name,
                    attempt_count=int(item["attempt_count"]),
                    succeeded=succeeded,
                    failed=failed,
                    partial=True,
                    files_extracted=partial_attempt.files_extracted,
                    failed_files=partial_attempt.failed_files,
                    percent=100,
                    indeterminate=False,
                )
            else:
                failed += 1
                record = _finalize_result(
                    filepath,
                    status="failed",
                    pass_name="retry",
                    attempts=int(item["attempt_count"]),
                    output=None,
                    failed_files=int(item.get("failed_files", 0)),
                )
                emit_progress(
                    phase="archive_failed",
                    pass_name="retry",
                    index=index,
                    total=total,
                    name=filepath.name,
                    attempt_count=int(item["attempt_count"]),
                    succeeded=succeeded,
                    failed=failed,
                    indeterminate=False,
                )
            records.append(record)

    records.sort(key=lambda item: str(item["path"]).casefold())
    outcome = "succeeded" if failed == 0 else ("partial_failure" if succeeded else "failed")
    return {
        "archive_results": records,
        "failed_archives": [item for item in records if item["status"] == "failed"],
        "summary": {
            "archives_processed": len(records),
            "archives_succeeded": succeeded,
            "archives_partial": sum(bool(item.get("partial")) for item in records),
            "archives_failed": failed,
        },
        "outcome": outcome,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract archives without interactive prompts")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--password")
    args = parser.parse_args()
    try:
        result = scan_directory(args.directory, args.password)
    except Exception:
        print("[!] Extract gagal karena worker tidak dapat membaca arsip atau folder.", file=sys.stderr)
        return 1
    print("TME3_RESULT " + json.dumps(result, ensure_ascii=True), flush=True)
    return 1 if result["outcome"] != "succeeded" else 0


if __name__ == "__main__":
    raise SystemExit(main())
