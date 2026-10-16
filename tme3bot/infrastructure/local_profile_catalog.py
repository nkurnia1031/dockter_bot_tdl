from __future__ import annotations

import copy
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from tme3bot.names import normalize_profile_name
from tme3bot.persistence import write_json_atomic

LOGGER = logging.getLogger(__name__)


class LocalProfileCatalog:
    """Persist the latest explicit, cross-worker local profile scan."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self.scan_lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            return copy.deepcopy(self._snapshot)

    def replace_scan(
        self,
        *,
        checked_at: str,
        workers: list[dict[str, Any]],
        inventories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace the whole snapshot; only successful workers retain inventories."""
        snapshot = self._build_snapshot(
            checked_at=checked_at,
            workers=workers,
            inventories=inventories,
        )
        with self._lock:
            write_json_atomic(self.path, snapshot)
            self._snapshot = snapshot
            return copy.deepcopy(snapshot)

    def _load_locked(self) -> None:
        if self._snapshot is not None:
            return
        if not self.path.exists():
            self._snapshot = self._empty_snapshot()
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Tidak bisa membaca katalog profil lokal: %s", self.path)
            self._snapshot = self._empty_snapshot()
            return
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("workers"), list)
            or not isinstance(payload.get("inventories"), list)
        ):
            self._snapshot = self._empty_snapshot()
            return
        # Reuse the write-side allowlist and exclude inventories for failed workers.
        self._snapshot = self._build_snapshot(
            checked_at=str(payload.get("checked_at") or ""),
            workers=payload["workers"],
            inventories=payload["inventories"],
        )

    def _build_snapshot(
        self,
        *,
        checked_at: str,
        workers: list[dict[str, Any]],
        inventories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        # Keep load and replace behavior identical, including dropping old failed data.
        safe_workers: list[dict[str, Any]] = []
        successful: set[str] = set()
        for raw in workers:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip().lower()
            status = str(raw.get("status") or "")
            if (
                not name
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", name)
                or status not in {"success", "failed", "disabled"}
            ):
                continue
            error_code = str(raw.get("error_code") or "")
            if status != "failed":
                error_code = ""
            elif not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", error_code):
                error_code = "WORKER_SCAN_FAILED"
            safe_workers.append({
                "name": name,
                "status": status,
                "checked_at": str(raw.get("checked_at") or "")[:40],
                "error_code": error_code[:80],
            })
            if status == "success":
                successful.add(name)
        safe_inventories: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in inventories:
            if not isinstance(raw, dict):
                continue
            worker = str(raw.get("worker") or "").strip().lower()
            items = raw.get("items")
            if worker not in successful or worker in seen or not isinstance(items, list):
                continue
            safe_inventories.append({
                "worker": worker,
                "checked_at": str(raw.get("checked_at") or "")[:40],
                "items": copy.deepcopy(items),
            })
            seen.add(worker)
        owners: dict[str, set[str]] = {}
        for inventory in safe_inventories:
            for item in inventory["items"]:
                if not isinstance(item, dict) or item.get("ready") is not True:
                    continue
                name = normalize_profile_name(str(item.get("name") or ""))
                if name:
                    owners.setdefault(name, set()).add(inventory["worker"])
        profiles = [
            {
                "name": name,
                "workers": sorted(profile_workers),
                "exclusive_worker": next(iter(profile_workers)) if len(profile_workers) == 1 else "",
            }
            for name, profile_workers in sorted(owners.items())
        ]
        return {
            "checked_at": str(checked_at or "")[:40],
            "workers": safe_workers,
            "inventories": safe_inventories,
            "profiles": profiles,
        }

    @staticmethod
    def _empty_snapshot() -> dict[str, Any]:
        return {"checked_at": "", "workers": [], "inventories": [], "profiles": []}
