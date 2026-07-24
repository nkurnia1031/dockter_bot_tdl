from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tme3bot.persistence import write_json_atomic

LOGGER = logging.getLogger(__name__)
UTILITY_NAMES = ("extract", "compress", "export", "pindah")
DEFAULT_UTILITY_FOLDERS = ("/workspace/biasa", "/workspace/pilihan", "/workspace/downloads")
DEFAULT_UTILITY_SETTINGS = {
    "move_size": "4g",
    "compress_size": "4g",
    "compress_password": "A1031@bokep@1031A",
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
            if str(raw.get(key, "")).strip():
                self._settings[key] = str(raw[key]).strip()
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
    def __init__(self, utility_root: Path, log_callback: Callable[[str], None] | None = None) -> None:
        self.root = utility_root
        self.log_callback = log_callback

    def run(self, utility: str, folders: list[str], password: str | None = None, settings: dict[str, str] | None = None) -> UtilityResult:
        succeeded: list[str] = []
        failed: dict[str, str] = {}
        details: list[dict[str, object]] = []
        for folder in folders:
            try:
                path = Path(folder)
                if not path.is_absolute():
                    raise UtilityPathError("Path utility harus absolut dan berasal dari folder pilihan workspace.")
                path = path.resolve()
                if not path.is_dir():
                    raise UtilityPathError(f"Folder utility tidak ditemukan: {path}")
                before = self._snapshot(path)
                self._run_folder(utility, path, password, settings or DEFAULT_UTILITY_SETTINGS)
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
                if utility == "export":
                    detail["organizer"] = self._organizer_log_summary(path)
                succeeded.append(str(path))
                details.append(detail)
            except Exception as exc:
                failed[folder] = str(exc)
                LOGGER.exception("Utility %s failed for %s", utility, folder)
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
        return UtilityResult(utility, succeeded, failed, details, summary)

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
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        if settings:
            env["UTILITY_MOVE_SIZE"] = settings.get("move_size", "4g")
            env["UTILITY_COMPRESS_SIZE"] = settings.get("compress_size", "4g")
            env["UTILITY_COMPRESS_PASSWORD"] = settings.get("compress_password", "")
        process = subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        assert process.stdout is not None
        lines: list[str] = []
        for line in process.stdout:
            clean = line.rstrip()
            lines.append(clean)
            LOGGER.info("%s | %s", prefix, clean)
            if self.log_callback:
                self.log_callback(clean)
        code = process.wait()
        if code != 0:
            raise RuntimeError(f"{prefix} exit code {code}: {' | '.join(lines[-5:])}")
