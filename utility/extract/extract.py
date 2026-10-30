from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
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


def _command_for(filepath: Path, password: str, output: Path) -> list[str]:
    lower = filepath.name.lower()
    if lower.endswith((".7z", ".7z.001", ".zip")):
        return ["7z", "x", f"-p{password}", "-y", str(filepath), f"-o{output}", "-bsp0"]
    if lower.endswith(".rar"):
        return [
            "unar",
            "-force-overwrite",
            "-no-directory",
            "-password",
            password,
            "-output-directory",
            str(output),
            str(filepath),
        ]
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
) -> bool:
    """Run one isolated extraction attempt and keep the job heartbeat alive."""
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            cwd=str(filepath.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=False,
        )
    except OSError:
        return False

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
    return process.returncode == 0 and output.is_dir()


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
    password: str,
    *,
    index: int,
    total: int,
    pass_name: str,
    attempt: int,
) -> tuple[bool, Path | None]:
    with tempfile.TemporaryDirectory(
        prefix=".extract-attempt-", dir=str(filepath.parent)
    ) as temporary:
        staging = Path(temporary) / "output"
        try:
            command = _command_for(filepath, password, staging)
        except ValueError:
            return False, None
        emit_progress(
            phase="archive_attempt",
            pass_name=pass_name,
            index=index,
            total=total,
            name=filepath.name,
            attempt=attempt,
            indeterminate=True,
        )
        if not run_extract(
            command,
            filepath=filepath,
            output=staging,
            pass_name=pass_name,
            index=index,
            total=total,
            attempt=attempt,
        ):
            return False, None
        destination = _unique_output_directory(filepath)
        try:
            _publish_staging(staging, destination)
        except OSError:
            return False, None
        return True, destination


def _finalize_result(
    filepath: Path,
    *,
    status: str,
    pass_name: str,
    attempts: int,
    output: Path | None,
) -> dict[str, Any]:
    cleanup_status = _remove_archive_parts(filepath) if status == "succeeded" else "retained_failed"
    return {
        "name": filepath.name,
        "path": str(filepath),
        "status": status,
        "pass": "retry" if pass_name == "retry" else "first",
        "attempt_count": attempts,
        "output": str(output) if output is not None else None,
        "cleanup_status": cleanup_status,
        "error": (
            "Semua kandidat password gagal atau arsip tidak dapat diekstrak."
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
        tried: list[str] = []
        output: Path | None = None
        candidates = archive_password_candidates(filepath, supplied_password)
        for candidate in candidates:
            if candidate not in password_pool:
                password_pool.append(candidate)
        for attempt, candidate in enumerate(candidates, start=1):
            tried.append(candidate)
            ok, output = _attempt_archive(
                filepath,
                candidate,
                index=index,
                total=total,
                pass_name="first_pass",
                attempt=attempt,
            )
            if ok:
                record = _finalize_result(
                    filepath,
                    status="succeeded",
                    pass_name="first_pass",
                    attempts=len(tried),
                    output=output,
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
        output = None
        for candidate in password_pool:
            if candidate in tried:
                continue
            tried.append(candidate)
            item["attempt_count"] = int(item["attempt_count"]) + 1
            ok, output = _attempt_archive(
                filepath,
                candidate,
                index=index,
                total=total,
                pass_name="retry",
                attempt=int(item["attempt_count"]),
            )
            if ok:
                record = _finalize_result(
                    filepath,
                    status="succeeded",
                    pass_name="retry",
                    attempts=int(item["attempt_count"]),
                    output=output,
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
