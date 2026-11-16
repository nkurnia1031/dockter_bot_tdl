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


# Archive and container suffixes supported by the worker's 7z runtime. Compound
# suffixes come first so ``bundle.tar.gz`` gets the output name ``bundle``.
_ARCHIVE_SUFFIXES = (
    ".tar.bzip2", ".tar.bz2", ".tar.gzip", ".tar.gz", ".tar.lzma",
    ".tar.zstd", ".tar.zst", ".tar.xz", ".tar.z", ".tar",
    ".7z", ".zipx", ".zip", ".rar", ".arj", ".cab", ".chm",
    ".chi", ".chq", ".chw", ".cpio", ".cramfs", ".dmg", ".iso",
    ".lha", ".lzh", ".nsis", ".rpm", ".squashfs", ".udf", ".xar",
    ".pkg", ".xip", ".wim", ".swm", ".esd", ".ppkg", ".qcow2c",
    ".qcow2", ".qcow", ".vdi", ".avhdx", ".vhdx", ".vhd", ".vmdk",
    ".deb", ".udeb", ".ova", ".tgz", ".tpz", ".tbz2", ".tbz",
    ".txz", ".tzst", ".taz", ".gzip", ".bzip2", ".lzma86", ".lzma",
    ".bz2", ".zstd", ".zst", ".xz", ".gz", ".z", ".ar", ".lib",
    ".jar", ".xpi", ".odt", ".ods", ".docx", ".xlsx", ".pptx",
    ".epub", ".ipa", ".appx", ".msi", ".msp", ".msm", ".apk",
    ".doc", ".xls", ".ppt", ".aaf", ".apfs", ".b64", ".obj",
    ".elf", ".ext", ".ext2", ".ext3", ".ext4", ".fat", ".flv",
    ".gpt", ".hfs", ".hfsx", ".hxs", ".hxi", ".hxr", ".hxq",
    ".hxw", ".lit", ".img", ".lpimg", ".mbr", ".macho", ".mslz",
    ".mub", ".ntfs", ".exe", ".dll", ".sys", ".pmd", ".swf",
    ".simg", ".te", ".scap", ".uefif", ".ihex",
)
_PASSWORD_ARCHIVE_SUFFIXES = (".7z", ".zip", ".zipx", ".rar", ".arj")
_TAR_STREAM_SUFFIXES = {
    ".tar.gz": "GZip",
    ".tar.gzip": "GZip",
    ".tgz": "GZip",
    ".tpz": "GZip",
    ".tar.lzma": "Lzma",
    ".tar.bz2": "BZip2",
    ".tar.bzip2": "BZip2",
    ".tbz": "BZip2",
    ".tbz2": "BZip2",
    ".tar.xz": "Xz",
    ".txz": "Xz",
    ".tar.zst": "Zstd",
    ".tar.zstd": "Zstd",
    ".tzst": "Zstd",
    ".tar.z": "Z",
    ".taz": "Z",
}


def archive_suffix(filename: str) -> str | None:
    lower = filename.lower()
    return next((suffix for suffix in _ARCHIVE_SUFFIXES if lower.endswith(suffix)), None)


def _tar_stream_type(filename: str) -> str | None:
    lower = filename.lower()
    suffix = next(
        (candidate for candidate in _TAR_STREAM_SUFFIXES if lower.endswith(candidate)),
        None,
    )
    return _TAR_STREAM_SUFFIXES.get(suffix) if suffix else None


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

    split_numbered = re.match(r"(.+)\.001$", filename, re.IGNORECASE)
    if split_numbered:
        base = re.escape(split_numbered.group(1))
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
    return lower.endswith(".7z.001") or archive_suffix(filename) is not None


def is_main_archive(filepath: Path) -> bool:
    lower = filepath.name.lower()
    if lower.endswith(".001") and not lower.endswith(".7z.001"):
        next_volume = filepath.with_name(f"{filepath.name[:-4]}.002")
        return next_volume.is_file() and not next_volume.is_symlink()
    return is_main_part(filepath.name)


def get_extract_folder_name(filename: str) -> str:
    for pattern in (
        r"(.+)\.part\d+\.rar$",
        r"(.+)\.001$",
    ):
        match = re.match(pattern, filename, re.IGNORECASE)
        if match:
            return Path(match.group(1)).name
    suffix = archive_suffix(filename)
    if suffix:
        return Path(filename[: -len(suffix)]).name or Path(filename).stem
    return Path(filename).stem


def archive_password_candidates(filepath: Path, supplied_password: str | None) -> list[str]:
    """Return the first-pass candidates without logging or exposing their values."""
    if not filepath.name.lower().endswith(_PASSWORD_ARCHIVE_SUFFIXES):
        return []
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


def _create_unique_output_directory(filepath: Path) -> Path:
    base = filepath.parent / get_extract_folder_name(filepath.name)
    candidate = base
    suffix = 2
    while True:
        try:
            candidate.mkdir(mode=0o700)
            return candidate
        except FileExistsError:
            candidate = base.with_name(f"{base.name}_{suffix}")
            suffix += 1


def _command_for(
    filepath: Path,
    password: str | None,
    output: Path,
    *,
    skip_existing: bool = False,
) -> tuple[list[str], ...]:
    if _tar_stream_type(filepath.name):
        # Stream compressed tar data directly into the extractor so no
        # intermediate .tar file or staging copy is written to disk.
        decompress = ["7z", "x", "-so", "-bso0", "-bsp0", str(filepath)]
        extract = [
            "7z",
            "x",
            "-si",
            "-ttar",
            "-bb1",
            "-ssc-",
            "-xr!*.txt",
            "-xr!*.url",
        ]
        if skip_existing:
            extract.append("-aos")
        extract.extend(["-y", f"-o{output}", "-bsp0"])
        return (decompress, extract)

    if archive_suffix(filepath.name) is None and not filepath.name.lower().endswith(".001"):
        raise ValueError("Format arsip tidak didukung.")
    # Per-member output distinguishes real extracted files from placeholders
    # left after a password or corruption error. Write into the final directory.
    command = [
        "7z",
        "x",
        "-bb1",
        "-ssc-",
        "-xr!*.txt",
        "-xr!*.url",
    ]
    if skip_existing:
        command.append("-aos")
    if password is not None:
        command.append(f"-p{password}")
    command.extend(["-y", str(filepath), f"-o{output}", "-bsp0"])
    return (command,)


def run_extract(
    commands: tuple[list[str], ...],
    *,
    filepath: Path,
    output: Path,
    pass_name: str,
    index: int,
    total: int,
    attempt: int,
) -> "ExtractorRun":
    """Run one extractor or a decompressor→extractor streaming pipeline."""
    started = time.monotonic()
    with tempfile.TemporaryFile() as tool_log:
        processes: list[subprocess.Popen[bytes]] = []
        try:
            if len(commands) == 1:
                processes.append(
                    subprocess.Popen(
                        commands[0],
                        cwd=str(filepath.parent),
                        stdin=subprocess.DEVNULL,
                        stdout=tool_log,
                        stderr=subprocess.STDOUT,
                        start_new_session=False,
                    )
                )
            elif len(commands) == 2:
                decompressor = subprocess.Popen(
                    commands[0],
                    cwd=str(filepath.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=tool_log,
                    start_new_session=False,
                )
                processes.append(decompressor)
                assert decompressor.stdout is not None
                try:
                    extractor = subprocess.Popen(
                        commands[1],
                        cwd=str(filepath.parent),
                        stdin=decompressor.stdout,
                        stdout=tool_log,
                        stderr=subprocess.STDOUT,
                        start_new_session=False,
                    )
                except OSError:
                    decompressor.stdout.close()
                    decompressor.terminate()
                    decompressor.wait()
                    raise
                processes.append(extractor)
                decompressor.stdout.close()
            else:
                raise ValueError("Pipeline extractor tidak valid.")
        except OSError:
            return ExtractorRun(returncode=None, output="")

        while any(process.poll() is None for process in processes):
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
    returncode = next(
        (process.returncode for process in processes if process.returncode != 0),
        0,
    )
    return ExtractorRun(returncode=returncode, output=tool_output)


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


def _extracted_file_results(
    commands: tuple[list[str], ...],
    tool_output: str,
    output: Path,
    returncode: int | None,
) -> tuple[list[Path], tuple[str, ...], bool]:
    files = _regular_output_files(output)
    successful_members: list[str] = []
    failed_members: list[str] = []
    has_unclassified_error = False
    tool = Path(commands[-1][0]).name.lower()
    for line in tool_output.replace("\x08", "").splitlines():
        if tool in {"7z", "7zz"}:
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
    # Inferring success from files merely present in output misclassifies
    # zero-byte placeholders left by bad passwords or corrupt archives.
    successful_files = _member_files(successful_members, output, files)
    successful_files.difference_update(failed_files)
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


def _retain_only_verified_files(output: Path, keep: list[Path]) -> bool:
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
    workspace_root: Path,
    previous: ArchiveAttempt | None = None,
) -> ArchiveAttempt:
    if previous and previous.output:
        output = previous.output
        try:
            resolved_parent = filepath.parent.resolve(strict=True)
            resolved_parent.relative_to(workspace_root)
            resolved_output = output.resolve(strict=True)
            expected_prefix = get_extract_folder_name(filepath.name)
            if (
                output.is_symlink()
                or resolved_output.parent != resolved_parent
                or not re.fullmatch(
                    rf"{re.escape(expected_prefix)}(?:_[2-9]|_[1-9]\d+)?",
                    resolved_output.name,
                )
            ):
                return previous
            output.chmod(0o700)
        except (OSError, ValueError):
            return previous
    else:
        try:
            filepath.parent.resolve(strict=True).relative_to(workspace_root)
            output = _create_unique_output_directory(filepath)
        except (OSError, ValueError):
            return ArchiveAttempt(succeeded=False)

    try:
        commands = _command_for(
            filepath,
            password,
            output,
            skip_existing=bool(previous and previous.successful_members),
        )
    except ValueError:
        if previous is None:
            _discard_partial_output(filepath, output, workspace_root)
        return previous or ArchiveAttempt(succeeded=False)

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
        commands,
        filepath=filepath,
        output=output,
        pass_name=pass_name,
        index=index,
        total=total,
        attempt=attempt,
    )
    current_successes, current_failures, current_unclassified = _extracted_file_results(
        commands, run.output, output, run.returncode
    )
    existing_files = _regular_output_files(output)
    retained_files = (
        _member_files(
            list(previous.successful_members),
            output,
            existing_files,
            allow_basename_fallback=False,
        )
        if previous is not None
        else set()
    )
    verified_files = retained_files.union(current_successes)
    if run.returncode == 0 and not current_failures and not current_unclassified:
        verified_files.update(existing_files)
    if not _retain_only_verified_files(output, sorted(verified_files)):
        if previous is None:
            _discard_partial_output(filepath, output, workspace_root)
            return ArchiveAttempt(succeeded=False)
        return previous

    files = _regular_output_files(output)
    current_member_names = {
        path.relative_to(output).as_posix() for path in current_successes
    }
    observed_members = set(previous.successful_members if previous else ())
    observed_members.update(previous.failed_members if previous else ())
    observed_members.update(current_member_names)
    observed_members.update(current_failures)
    found_members = {
        path.relative_to(output).as_posix() for path in files
    }
    unresolved_members = {
        member for member in observed_members if member not in found_members
    }
    unclassified_failure = bool(
        (previous and previous.unclassified_failure)
        or current_unclassified
    )
    failed_file_count = max(
        len(unresolved_members),
        int(unclassified_failure),
    )
    complete = (
        run.returncode == 0
        and not failed_file_count
        and not unresolved_members
        and not unclassified_failure
    )
    if complete:
        output.chmod(0o755)
        return ArchiveAttempt(
            succeeded=True,
            output=output,
            partial=False,
            files_extracted=len(files),
            successful_members=tuple(sorted(found_members)),
        )
    if not files:
        _discard_partial_output(filepath, output, workspace_root)
        return ArchiveAttempt(
            succeeded=False,
            failed_files=failed_file_count,
            failed_members=tuple(sorted(unresolved_members)),
            unclassified_failure=unclassified_failure,
        )
    output.chmod(0o755)
    return ArchiveAttempt(
        succeeded=True,
        output=output,
        partial=True,
        files_extracted=len(files),
        failed_files=failed_file_count,
        successful_members=tuple(sorted(found_members)),
        failed_members=tuple(sorted(unresolved_members)),
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
            if path.is_file() and not path.is_symlink() and is_main_archive(path)
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
                workspace_root=base_dir,
                previous=partial_attempt,
            )
            failed_file_count = max(failed_file_count, attempt_result.failed_files)
            if attempt_result.succeeded and attempt_result.partial:
                partial_attempt = attempt_result
                continue
            if attempt_result.succeeded:
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
                workspace_root=base_dir,
                previous=partial_attempt,
            )
            item["failed_files"] = max(
                int(item.get("failed_files", 0)), attempt_result.failed_files
            )
            if attempt_result.succeeded and attempt_result.partial:
                partial_attempt = attempt_result
                partial_pass_name = "retry"
                continue
            if attempt_result.succeeded:
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
