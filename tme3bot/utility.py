from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tme3bot.persistence import write_json_atomic

LOGGER = logging.getLogger(__name__)
UTILITY_NAMES = ("extract", "compress", "export", "pindah")
DEFAULT_UTILITY_FOLDERS = ("/workspace/biasa", "/workspace/pilihan", "/workspace/downloads")


class UtilityPathError(ValueError):
    pass


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


class UtilityRunner:
    def __init__(self, utility_root: Path, log_callback: Callable[[str], None] | None = None) -> None:
        self.root = utility_root
        self.log_callback = log_callback

    def run(self, utility: str, folders: list[str], password: str | None = None) -> UtilityResult:
        succeeded: list[str] = []
        failed: dict[str, str] = {}
        for folder in folders:
            try:
                self._run_folder(utility, Path(folder), password)
                succeeded.append(folder)
            except Exception as exc:
                failed[folder] = str(exc)
                LOGGER.exception("Utility %s failed for %s", utility, folder)
        return UtilityResult(utility, succeeded, failed)

    def _run_folder(self, utility: str, folder: Path, password: str | None) -> None:
        if utility == "extract":
            command = ["python3", str(self.root / "extract" / "extract.py"), str(folder), "--no-prompt", "--password", password or folder.name]
            self._command(command, folder, "utility-extract")
        elif utility == "compress":
            self._command(["bash", str(self.root / "compress" / "compress.sh")], folder, "utility-compress")
        elif utility == "export":
            self._command(["python3", str(self.root / "export" / "telegram_messages_to_json.py")], folder, "utility-export-convert")
            self._command(["python3", str(self.root / "export" / "organize_media_from_json.py"), "--base-dir", str(folder)], folder, "utility-export-organize")
        elif utility == "pindah":
            self._command(["bash", str(self.root / "pindah" / "pindah.sh"), str(folder)], folder, "utility-pindah")
        else:
            raise ValueError(f"Utility tidak dikenal: {utility}")

    def _command(self, command: list[str], cwd: Path, prefix: str) -> None:
        LOGGER.info("%s start folder=%s", prefix, cwd)
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
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
