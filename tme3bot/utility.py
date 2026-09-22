from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tme3bot.persistence import write_json_atomic
from tme3bot.tdl import CommandCallback, ProcessStalledError
from tme3bot.tdl_output import parse_tdl_progress_line

LOGGER = logging.getLogger(__name__)
UTILITY_NAMES = ("extract", "compress", "export", "pindah")
DEFAULT_UTILITY_FOLDERS = ("/workspace/biasa", "/workspace/pilihan", "/workspace/downloads")
DEFAULT_UTILITY_SETTINGS = {
    "move_size": "4g",
    "compress_size": "4g",
    "compress_password": "A1031@bokep@1031A",
    "rclone_destination": "googledrive:backup",
}
UTILITY_SETTING_SPECS = {
    "move_size": {
        "label": "Batas ukuran grup pindah",
        "description": "Ukuran maksimum setiap grup hasil operasi Pindah / group.",
        "format": "Angka positif dengan satuan B, K, M, G, atau T.",
        "examples": ("500m", "4g", "1.5g"),
        "secret": False,
    },
    "compress_size": {
        "label": "Ukuran volume arsip 7z",
        "description": "Ukuran maksimum setiap part arsip saat Compress 7z.",
        "format": "Angka positif dengan satuan B, K, M, G, atau T.",
        "examples": ("500m", "4g", "1.5g"),
        "secret": False,
    },
    "compress_password": {
        "label": "Password arsip dan backup",
        "description": "Dipakai untuk arsip 7z dan backup terenkripsi. Nilai lama tidak ditampilkan kembali.",
        "format": "8–128 karakter.",
        "examples": (),
        "secret": True,
    },
    "rclone_destination": {
        "label": "Tujuan Google Drive (rclone)",
        "description": "Remote dan path rclone untuk arsip Quick Mode atau upload Storage yang dicentang.",
        "format": "remote:path, misalnya googledrive:backup.",
        "examples": ("googledrive:backup",),
        "secret": False,
    },
}


class UtilityPathError(ValueError):
    pass


class UtilitySettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._settings: dict[str, str] | None = None

    def get(self) -> dict[str, str]:
        with self._lock:
            self._load()
            return dict(self._settings or DEFAULT_UTILITY_SETTINGS)

    def set(self, key: str, value: str) -> None:
        if key not in DEFAULT_UTILITY_SETTINGS:
            raise ValueError(f"Pengaturan utility tidak dikenal: {key}")
        value = value.strip()
        if not value:
            raise ValueError("Nilai pengaturan tidak boleh kosong.")
        if key == "compress_password":
            _validate_password(value)
        elif key == "rclone_destination":
            validate_rclone_destination(value)
        else:
            _validate_size(value)
        with self._lock:
            self._load()
            assert self._settings is not None
            self._settings[key] = value
            write_json_atomic(self.path, self._settings)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def _load(self) -> None:
        if self._settings is not None:
            return
        values: object = None
        if self.path.exists():
            try:
                values = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                LOGGER.warning("Utility settings tidak valid: %s", self.path)
        raw = values if isinstance(values, dict) else {}
        self._settings = dict(DEFAULT_UTILITY_SETTINGS)
        for key in DEFAULT_UTILITY_SETTINGS:
            candidate = str(raw.get(key, "")).strip()
            if not candidate:
                continue
            if key == "rclone_destination":
                try:
                    validate_rclone_destination(candidate)
                except ValueError:
                    LOGGER.warning("Tujuan rclone pada settings tidak valid; memakai default.")
                    continue
            self._settings[key] = candidate
        write_json_atomic(self.path, self._settings)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass


def _validate_size(value: str) -> None:
    if not re.fullmatch(r"[1-9][0-9]{0,5}(?:\.[0-9]{1,2})?(?:[kmgt]i?b?|b)", value.lower()):
        raise ValueError(
            "Ukuran harus berupa angka positif dengan satuan, misalnya 500m, 4g, atau 1.5g."
        )


def _validate_password(value: str) -> None:
    if not 8 <= len(value) <= 128:
        raise ValueError("Password compress harus terdiri dari 8 sampai 128 karakter.")


def validate_rclone_destination(value: str) -> None:
    """Validate a remote destination before it reaches a worker command."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*:[^\x00-\x1f]+", value):
        raise ValueError(
            "Tujuan rclone harus berupa remote:path, misalnya googledrive:backup."
        )


def utility_setting_specs() -> list[dict[str, object]]:
    """Public metadata for clients; never contains a setting value or secret."""
    return [
        {"key": key, **spec, "examples": list(spec["examples"])}
        for key, spec in UTILITY_SETTING_SPECS.items()
    ]


class UtilityFolderStore:
    def __init__(self, path: Path, workspace: Path) -> None:
        self.path = path
        self.workspace = workspace.resolve()
        self._lock = threading.RLock()
        self._folders: list[str] | None = None

    def list(self) -> list[str]:
        with self._lock:
            self._load()
            return list(self._folders or [])

    def add(self, raw_path: str) -> str:
        path = self.validate(raw_path)
        with self._lock:
            self._load()
            assert self._folders is not None
            value = str(path)
            if value not in self._folders:
                self._folders.append(value)
                self._save()
            return value

    def remove(self, raw_path: str) -> bool:
        path = str(self.validate(raw_path))
        with self._lock:
            self._load()
            assert self._folders is not None
            if path not in self._folders:
                return False
            self._folders.remove(path)
            self._save()
            return True

    def validate(self, raw_path: str) -> Path:
        candidate = Path(str(raw_path).strip())
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise UtilityPathError("Folder harus berada di dalam workspace /workspace.") from exc
        if not resolved.exists() or not resolved.is_dir():
            raise UtilityPathError(f"Folder tidak ditemukan: {resolved}")
        return resolved

    def _load(self) -> None:
        if self._folders is not None:
            return
        values: object = None
        if self.path.exists():
            try:
                values = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                LOGGER.warning("Utility folder store tidak valid: %s", self.path)
        has_store = self.path.exists() and isinstance(values, dict)
        raw = values.get("folders", []) if has_store else list(DEFAULT_UTILITY_FOLDERS)
        folders: list[str] = []
        raw_items = raw if isinstance(raw, list) else []
        for item in raw_items:
            if str(item) in DEFAULT_UTILITY_FOLDERS:
                try:
                    Path(str(item)).mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass
            try:
                value = str(self.validate(str(item)))
            except UtilityPathError:
                continue
            if value not in folders:
                folders.append(value)
        self._folders = folders
        self._save()

    def _save(self) -> None:
        write_json_atomic(self.path, {"folders": self._folders or []})


@dataclass(frozen=True)
class UtilityResult:
    utility: str
    succeeded: list[str]
    failed: dict[str, str]
    details: list[dict[str, object]]
    summary: dict[str, object] = field(default_factory=dict)


class UtilityRunner:
    def __init__(
        self,
        utility_root: Path,
        log_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
        stall_timeout_seconds: int = 0,
        command_callback: CommandCallback | None = None,
    ) -> None:
        self.root = utility_root
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.stall_timeout_seconds = max(0, int(stall_timeout_seconds))
        self.command_callback = command_callback
        self._process_lock = threading.RLock()
        self._current_process: subprocess.Popen[str] | None = None

    def cancel_current(self) -> bool:
        with self._process_lock:
            process = self._current_process
        if process is None or process.poll() is not None:
            return False
        if os.name != "nt":
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGINT)
            except ProcessLookupError:
                return False
        else:  # pragma: no cover - production workers run on Linux
            process.send_signal(signal.CTRL_BREAK_EVENT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._terminate_process(process)
        return True

    def run(self, utility: str, folders: list[str], password: str | None = None, settings: dict[str, str] | None = None) -> UtilityResult:
        succeeded: list[str] = []
        failed: dict[str, str] = {}
        details: list[dict[str, object]] = []
        for folder_index, folder in enumerate(folders, start=1):
            try:
                path = Path(folder)
                if not path.is_absolute():
                    raise UtilityPathError("Path utility harus absolut dan berasal dari folder pilihan workspace.")
                path = path.resolve()
                if not path.is_dir():
                    raise UtilityPathError(f"Folder utility tidak ditemukan: {path}")
                self._progress(
                    {
                        "phase": f"{utility}_starting",
                        "folder": str(path),
                        "folder_index": folder_index,
                        "folder_total": len(folders),
                        "indeterminate": True,
                    }
                )
                before = self._snapshot(path)
                self._run_folder(utility, path, password, settings or DEFAULT_UTILITY_SETTINGS)
                temporary_json_removed = 0
                if utility == "pindah":
                    temporary_json_removed = self._cleanup_pindah_outputs(path)
                after = self._snapshot(path)
                detail: dict[str, object] = {
                    "folder": folder,
                    "files_before": before["files"],
                    "files_after": after["files"],
                    "bytes_before": before["bytes"],
                    "bytes_after": after["bytes"],
                    "groups": after["directories"],
                    "archives": after["archives"],
                }
                if utility == "pindah":
                    detail["temporary_json_removed"] = temporary_json_removed
                if utility == "export":
                    detail["organizer"] = self._organizer_log_summary(path)
                succeeded.append(str(path))
                details.append(detail)
                self._progress(
                    {
                        "phase": f"{utility}_folder_completed",
                        "folder": str(path),
                        "folder_index": folder_index,
                        "folder_total": len(folders),
                        "percent": 100,
                        "indeterminate": False,
                    }
                )
            except Exception as exc:
                failed[folder] = str(exc)
                self._progress(
                    {
                        "phase": f"{utility}_folder_failed",
                        "folder": folder,
                        "folder_index": folder_index,
                        "folder_total": len(folders),
                        "error": str(exc)[:500],
                        "indeterminate": False,
                    }
                )
                LOGGER.exception("Utility %s failed for %s", utility, folder)
                if isinstance(exc, ProcessStalledError):
                    raise
        summary: dict[str, object] = {
            "folders_processed": len(succeeded),
            "folders_failed": len(failed),
            "files_before": sum(int(item["files_before"]) for item in details),
            "files_after": sum(int(item["files_after"]) for item in details),
            "bytes_before": sum(int(item["bytes_before"]) for item in details),
            "bytes_after": sum(int(item["bytes_after"]) for item in details),
        }
        if utility == "export":
            organizer = [item.get("organizer", {}) for item in details]
            summary.update(
                {
                    "groups_created": sum(int(item.get("groups_created", 0)) for item in organizer),
                    "items_moved": sum(int(item.get("items_moved", 0)) for item in organizer),
                    "unresolved_groups": sum(int(item.get("unresolved_groups", 0)) for item in organizer),
                }
            )
        if utility == "pindah":
            summary["temporary_json_removed"] = sum(
                int(item.get("temporary_json_removed", 0)) for item in details
            )
        return UtilityResult(utility, succeeded, failed, details, summary)

    def _progress(self, value: dict[str, object]) -> None:
        if self.progress_callback is not None:
            self.progress_callback(value)

    @staticmethod
    def _organizer_log_summary(folder: Path) -> dict[str, int | str]:
        log_path = folder / "log.txt"
        if not log_path.is_file():
            return {"groups_created": 0, "items_moved": 0, "unresolved_groups": 0, "log_lines": 0}
        groups = moved = unresolved = lines_count = 0
        moved_pattern = re.compile(r"\|\s*moved\s+(\d+)\s+items?\s*$", re.IGNORECASE)
        for raw_line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lines_count += 1
            if "| start |" in line:
                groups += 1
                if "unresolved-" in line.lower():
                    unresolved += 1
            match = moved_pattern.search(line)
            if match:
                moved += int(match.group(1))
        return {
            "groups_created": groups,
            "items_moved": moved,
            "unresolved_groups": unresolved,
            "log_lines": lines_count,
        }

    @staticmethod
    def _cleanup_pindah_outputs(folder: Path) -> int:
        """Remove the two intermediate JSON files produced by ``pindah``.

        ``pindah4.py`` creates ``output.json`` and ``pindah.py`` transforms it
        into ``new_output.json`` for ``pindah2.py``. They are implementation
        artifacts, not user deliverables, and are safe to remove only after
        the complete shell pipeline returned successfully.
        """
        removed = 0
        for name in ("output.json", "new_output.json"):
            path = folder / name
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                LOGGER.warning("Could not remove Pindah temporary JSON: %s", path)
                continue
            removed += 1
        return removed

    @staticmethod
    def _snapshot(folder: Path) -> dict[str, int]:
        files = [path for path in folder.rglob("*") if path.is_file()]
        return {
            "files": len(files),
            "bytes": sum(path.stat().st_size for path in files),
            "directories": sum(1 for path in folder.iterdir() if path.is_dir()),
            "archives": sum(
                1
                for path in files
                if path.suffix.lower() in {".7z", ".zip", ".rar", ".001"}
            ),
        }

    def _run_folder(self, utility: str, folder: Path, password: str | None, settings: dict[str, str]) -> None:
        if utility == "extract":
            command = ["python3", str(self.root / "extract" / "extract.py"), str(folder), "--no-prompt", "--password", password or folder.name]
            self._command(command, folder, "utility-extract")
        elif utility == "compress":
            self._command(["bash", str(self.root / "compress" / "compress.sh")], folder, "utility-compress", settings)
        elif utility == "export":
            self._command(
                [
                    "python3",
                    str(self.root / "export" / "telegram_messages_to_json.py"),
                    "--base-dir",
                    str(folder),
                ],
                folder,
                "utility-export-convert",
            )
            self._command(["python3", str(self.root / "export" / "organize_media_from_json.py"), "--base-dir", str(folder)], folder, "utility-export-organize")
        elif utility == "pindah":
            self._command(["bash", str(self.root / "pindah" / "pindah.sh"), str(folder)], folder, "utility-pindah", settings)
        else:
            raise ValueError(f"Utility tidak dikenal: {utility}")

    def _command(self, command: list[str], cwd: Path, prefix: str, settings: dict[str, str] | None = None) -> None:
        LOGGER.info("%s start folder=%s", prefix, cwd)
        started_at = time.monotonic()
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        if settings:
            env["UTILITY_MOVE_SIZE"] = settings.get("move_size", "4g")
            env["UTILITY_COMPRESS_SIZE"] = settings.get("compress_size", "4g")
            env["UTILITY_COMPRESS_PASSWORD"] = settings.get("compress_password", "")
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                start_new_session=os.name != "nt",
            )
        except OSError as exc:
            if self.command_callback is not None:
                try:
                    self.command_callback(command, -1, str(exc), time.monotonic() - started_at, prefix)
                except Exception:
                    LOGGER.exception("Command callback failed for %s", prefix)
            raise
        with self._process_lock:
            self._current_process = process
        assert process.stdout is not None
        lines: list[str] = []
        marker: dict[str, object] = {}
        last_progress_at = time.monotonic()
        last_progress_signature: object = None
        stalled = threading.Event()
        watchdog_stop = threading.Event()

        def watchdog() -> None:
            if self.stall_timeout_seconds <= 0:
                return
            while not watchdog_stop.wait(1.0):
                if time.monotonic() - last_progress_at <= self.stall_timeout_seconds:
                    continue
                stalled.set()
                LOGGER.error(
                    "%s stalled for %ss; terminating process",
                    prefix,
                    self.stall_timeout_seconds,
                )
                self._terminate_process(process)
                return

        watchdog_thread = threading.Thread(
            target=watchdog,
            daemon=True,
            name=f"utility-watchdog-{prefix}",
        )
        watchdog_thread.start()

        def consume_line(raw_line: str) -> None:
            nonlocal marker, last_progress_at, last_progress_signature
            clean = raw_line.strip()
            if not clean:
                return
            lines.append(clean)
            LOGGER.info("%s | %s", prefix, clean)
            if self.log_callback:
                self.log_callback(clean)
            if clean.startswith("TME3_PROGRESS "):
                try:
                    decoded = json.loads(clean.removeprefix("TME3_PROGRESS "))
                    if isinstance(decoded, dict):
                        marker = decoded
                        signature = json.dumps(decoded, sort_keys=True, default=str)
                        if signature != last_progress_signature:
                            last_progress_signature = signature
                            last_progress_at = time.monotonic()
                        self._progress({"command": prefix, **decoded})
                except json.JSONDecodeError:
                    LOGGER.warning("Invalid utility progress marker: %s", clean)
                return
            parsed = parse_tdl_progress_line(clean, "stdout")
            if (
                parsed.percent is not None
                or parsed.speed_bps is not None
                or parsed.eta_seconds is not None
            ):
                signature = (
                    parsed.percent,
                    parsed.transferred_bytes,
                    parsed.file_name,
                )
                if signature != last_progress_signature:
                    last_progress_signature = signature
                    last_progress_at = time.monotonic()
                self._progress(
                    {
                        "command": prefix,
                        **marker,
                        "percent": parsed.percent,
                        "speed_bps": parsed.speed_bps,
                        "eta_seconds": parsed.eta_seconds,
                        "elapsed_seconds": parsed.elapsed_seconds,
                        "bytes_current": parsed.transferred_bytes,
                        "indeterminate": parsed.percent is None,
                    }
                )

        code = -1
        try:
            buffer: list[str] = []
            while True:
                char = process.stdout.read(1)
                if not char:
                    break
                if char in {"\r", "\n"}:
                    if buffer:
                        consume_line("".join(buffer))
                        buffer = []
                else:
                    buffer.append(char)
            if buffer:
                consume_line("".join(buffer))
            code = process.wait()
        finally:
            watchdog_stop.set()
            watchdog_thread.join(timeout=2)
            process.stdout.close()
            with self._process_lock:
                if self._current_process is process:
                    self._current_process = None
        if self.command_callback is not None:
            try:
                self.command_callback(
                    command,
                    int(code),
                    "\n".join(lines),
                    time.monotonic() - started_at,
                    prefix,
                )
            except Exception:
                LOGGER.exception("Command callback failed for %s", prefix)
        if stalled.is_set():
            raise ProcessStalledError(
                f"{prefix} stalled for {self.stall_timeout_seconds}s",
                self.stall_timeout_seconds,
            )
        if code != 0:
            raise RuntimeError(f"{prefix} exit code {code}: {' | '.join(lines[-5:])}")

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name != "nt":
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except ProcessLookupError:
                return
        else:  # pragma: no cover - production workers run on Linux
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    return
            else:  # pragma: no cover - production workers run on Linux
                process.kill()
