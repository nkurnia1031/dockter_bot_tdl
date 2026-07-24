from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from tme3bot.persistence import write_json_atomic


WORKER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


def normalize_worker_name(value: str) -> str:
    return value.strip().lower()


class WorkerRegistry:
    """Persistent gateway-owned worker endpoints, editable without a rebuild."""

    def __init__(self, path: Path, bootstrap_endpoints=None, bootstrap_tokens=None) -> None:
        self.path = path
        self.bootstrap_endpoints = bootstrap_endpoints or {}
        self.bootstrap_tokens = bootstrap_tokens or {}
        self._lock = threading.RLock()

    def list(self) -> dict[str, dict[str, str]]:
        with self._lock:
            workers = self._read_locked()
            return {name: dict(value) for name, value in workers.items()}

    def names(self) -> list[str]:
        return list(self.list())

    def get(self, name: str) -> dict[str, str] | None:
        return self.list().get(normalize_worker_name(name))

    def upsert(self, name: str, url: str, token: str) -> str:
        name = normalize_worker_name(name)
        url, token = url.strip().rstrip("/"), token.strip()
        if not WORKER_NAME_RE.fullmatch(name):
            raise ValueError("Nama worker hanya boleh berisi a-z, 0-9, '-' atau '_'.")
        if not url.startswith(("http://", "https://")):
            raise ValueError("URL worker harus dimulai http:// atau https://.")
        if not token:
            raise ValueError("Token worker wajib diisi.")
        with self._lock:
            workers = self._read_locked()
            workers[name] = {"url": url, "token": token}
            self._write_locked(workers)
        return name

    def remove(self, name: str) -> bool:
        name = normalize_worker_name(name)
        with self._lock:
            workers = self._read_locked()
            if name not in workers:
                return False
            del workers[name]
            self._write_locked(workers)
            return True

    def _read_locked(self) -> dict[str, dict[str, str]]:
        if not self.path.exists():
            workers = {
                normalize_worker_name(name): {
                    "url": str(url).rstrip("/"),
                    "token": str(self.bootstrap_tokens.get(name, "")),
                }
                for name, url in self.bootstrap_endpoints.items()
                if str(url).strip()
            }
            if workers:
                self._write_locked(workers)
            return workers
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        raw = payload.get("workers", {}) if isinstance(payload, dict) else {}
        if not isinstance(raw, dict):
            return {}
        workers = {
            normalize_worker_name(str(name)): {
                "url": str(value.get("url", "")).strip().rstrip("/"),
                "token": str(value.get("token", "")).strip(),
            }
            for name, value in raw.items()
            if isinstance(value, dict) and str(value.get("url", "")).strip()
        }
        changed = False
        for name, url in self.bootstrap_endpoints.items():
            normalized = normalize_worker_name(name)
            if normalized not in workers and str(url).strip():
                workers[normalized] = {
                    "url": str(url).strip().rstrip("/"),
                    "token": str(self.bootstrap_tokens.get(name, "")),
                }
                changed = True
        if changed:
            self._write_locked(workers)
        return workers

    def _write_locked(self, workers: dict[str, dict[str, str]]) -> None:
        write_json_atomic(self.path, {"workers": workers})
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
