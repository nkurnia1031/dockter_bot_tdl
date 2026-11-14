from __future__ import annotations

import argparse
import json
import os
import re
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


_UNAR_MEMBER_RESULT = re.compile(
    r"^\s*(?P<member>.+)\s+\([^)]*\)\.\.\.\s+(?P<status>OK\.?|Failed!|This archive requires a password to unpack\.)(?:\s|$)",
    re.IGNORECASE,
)
_SEVEN_Z_MEMBER_ERROR = re.compile(
    # 7z prefixes member failures with an error description that may itself
    # contain a colon (e.g. "ERROR: Wrong password : file.zip"). Match the
    # final separator so the failed member path is not mistaken for a
    # successfully extracted file.
    r"^\s*ERROR:.*:\s*(?P<member>.+?)\s*$", re.IGNORECASE
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


def _member_files(members: list[str], output: Path, files: list[Path]) -> set[Path]:
    matched: set[Path] = set()
    for raw_member in members:
        member = raw_member.strip().strip("\"'").replace("\\", "/")
        while member.startswith("./"):
            member = member[2:]
        member = member.lstrip("/")
        if not member:
            continue
        matches = [
            path
            for path in files
            if (
                path.relative_to(output).as_posix() == member
                or path.relative_to(output).as_posix().endswith("/" + member)
            )
        ]
        if not matches:
            basename = member.rsplit("/", 1)[-1]
            matches = [path for path in files if path.name == basename]
        matched.update(matches)
    return matched


def _staged_file_results(
    command: list[str], tool_output: str, output: Path
) -> tuple[list[Path], int]:
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

    failed_files = _member_files(failed_members, output, files)
    # Partial success must be explicit in the extractor's per-member output.
    # Inferring success from files merely present in staging misclassifies
    # zero-byte placeholders left by bad passwords or corrupt archives.
    successful_files = _member_files(successful_members, output, files)
    successful_files.difference_update(failed_files)
    if tool in {"7z", "7zz"}:
        # With -bb1, 7z emits "- member" before attempting to write it. A
        # password prompt can therefore leave that line plus a zero-byte
        # placeholder even though no member was extracted. A non-empty file
        # without a matching ERROR is the smallest reliable partial-success
        # signal available from 7z's per-member output.
        successful_files = {
            path for path in successful_files if path.stat().st_size > 0
        }
    return sorted(successful_files), len(failed_members)


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
        successful_files, failed_files = _staged_file_results(
            command, run.output, staging
        )
        complete = (
            run.returncode == 0
            and staging.is_dir()
            and failed_files == 0
        )
        partial = not complete and bool(successful_files)
        if not complete and not partial:
            return ArchiveAttempt(succeeded=False, failed_files=failed_files)
        if partial and not _retain_only_staged_files(staging, successful_files):
            return ArchiveAttempt(succeeded=False, failed_files=failed_files)
        destination = _unique_output_directory(filepath)
        try:
            _publish_staging(staging, destination)
        except OSError:
            return ArchiveAttempt(succeeded=False, failed_files=failed_files)
        return ArchiveAttempt(
            succeeded=True,
            output=destination,
            partial=partial,
            files_extracted=(len(successful_files) if partial else len(_regular_output_files(destination))),
            failed_files=failed_files,
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
                }
            )

    failed = 0
    for item in pending:
        index = int(item["index"])
        filepath = Path(item["filepath"])
        tried = list(item["tried"])
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
            failed += 1
            record = _finalize_result(
                filepath,
                status="failed",
                pass_name="retry",
                attempts=int(item["attempt_count"]),
                output=None,
            )
            records.append(record)
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
