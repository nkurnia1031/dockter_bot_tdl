from __future__ import annotations

import copy
import json
import re
import threading
from pathlib import Path
from typing import Any

from tme3bot.names import normalize_profile_name
from tme3bot.persistence import utc_now_iso, write_json_atomic_private

_WORKER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_RUNTIME_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
_FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")
_PHASE_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_EXPORT_RUNTIME = "export"
_QUICK_MODE_RUNTIME = "quick_mode"
_RESOLVER_RUNTIME = "resolver"


class RuntimeReadinessStore:
    """Persist worker reachability and feature readiness evidence independently."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._snapshot: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            return copy.deepcopy(self._snapshot)

    def public_snapshot(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        cells = []
        for cell in snapshot["cells"]:
            safe_cell = {
                key: cell[key]
                for key in (
                    "worker", "profile", "runtime", "status",
                    "checked_at", "reason_code",
                )
            }
            attempt = _safe_last_attempt(
                cell.get("last_attempt"),
                worker=cell["worker"],
                profile=cell["profile"],
                runtime=cell["runtime"],
                checked_at=cell["checked_at"],
                ready=cell["status"] == "ready",
                reason_code=cell["reason_code"],
            )
            if attempt is not None:
                safe_cell["last_attempt"] = attempt
            cells.append(safe_cell)
        return {
            "checked_at": snapshot["checked_at"],
            "workers": copy.deepcopy(snapshot["workers"]),
            "cells": cells,
        }

    def worker(self, name: str) -> dict[str, Any] | None:
        normalized = str(name or "").strip().lower()
        for item in self.snapshot()["workers"]:
            if item["name"] == normalized:
                return item
        return None

    def cell(
        self, worker: str, profile: str | None, runtime: str = _EXPORT_RUNTIME
    ) -> dict[str, Any] | None:
        key = _cell_key(worker, profile, runtime)
        if key is None:
            return None
        for item in self.snapshot()["cells"]:
            if _cell_key(item["worker"], item["profile"], item["runtime"]) == key:
                return item
        return None

    def apply_export_scan(
        self,
        *,
        checked_at: str,
        workers: list[dict[str, Any]],
        profiles: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Apply the workers and Export profile cells observed by one scan.

        Only successful worker scans replace their own profile cells. A failed or
        disabled worker updates its reachability row without erasing the last
        known runtime evidence. Admission checks reachability separately.
        """
        when = str(checked_at or "")[:64] or utc_now_iso()
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            snapshot = copy.deepcopy(self._snapshot)
            worker_map = {item["name"]: item for item in snapshot["workers"]}
            cell_map = {
                _cell_key(item["worker"], item["profile"], item["runtime"]): item
                for item in snapshot["cells"]
            }

            for raw in workers:
                if not isinstance(raw, dict):
                    continue
                name = str(raw.get("worker") or raw.get("name") or "").strip().lower()
                status = str(raw.get("status") or "")
                if not _WORKER_RE.fullmatch(name) or status not in {"success", "failed", "disabled"}:
                    continue
                error_code = _reason(raw.get("error_code"), "WORKER_SCAN_FAILED")
                worker_map[name] = {
                    "name": name,
                    "status": status,
                    "checked_at": str(raw.get("checked_at") or when)[:64],
                    "reason_code": error_code if status == "failed" else ("WORKER_DISABLED" if status == "disabled" else ""),
                }
                if status != "success":
                    continue

                current_profiles = profiles.get(name, [])
                replacement: dict[tuple[str, str, str], dict[str, Any]] = {}
                for item in current_profiles if isinstance(current_profiles, list) else []:
                    cell = self._export_cell(name, item, when)
                    if cell is None:
                        continue
                    key = _cell_key(name, cell["profile"], _EXPORT_RUNTIME)
                    previous = cell_map.get(key)
                    if (
                        previous is not None
                        and "last_attempt" not in cell
                        and isinstance(previous.get("last_attempt"), dict)
                    ):
                        cell["last_attempt"] = previous["last_attempt"]
                    replacement[key] = cell
                for key in list(cell_map):
                    if key is not None and key[0] == name and key[2] == _EXPORT_RUNTIME:
                        del cell_map[key]
                cell_map.update(replacement)

            snapshot = {
                "checked_at": when,
                "workers": sorted(worker_map.values(), key=lambda item: item["name"]),
                "cells": sorted(
                    cell_map.values(),
                    key=lambda item: (
                        item["worker"], item["profile"] or "", item["runtime"]
                    ),
                ),
            }
            self._save_locked(snapshot)
            return copy.deepcopy(snapshot)

    def apply_profile_lane_scan(
        self,
        *,
        runtime: str,
        checked_at: str,
        workers: list[dict[str, Any]],
        profiles: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Replace one profile lane's cells for workers completed by a scan."""
        lane = str(runtime or "").strip().lower()
        if lane not in {"download", "upload"}:
            raise ValueError("Runtime lane scan harus Download atau Upload.")
        when = str(checked_at or "")[:64] or utc_now_iso()
        successful_workers: set[str] = set()
        for raw in workers:
            if not isinstance(raw, dict):
                continue
            worker = str(raw.get("worker") or raw.get("name") or "").strip().lower()
            if _WORKER_RE.fullmatch(worker) and raw.get("status") in {"success", "succeeded"}:
                successful_workers.add(worker)
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            snapshot = copy.deepcopy(self._snapshot)
            cells = {
                _cell_key(item["worker"], item["profile"], item["runtime"]): item
                for item in snapshot["cells"]
            }
            previous_cells = dict(cells)
            for key in list(cells):
                if key is not None and key[0] in successful_workers and key[2] == lane:
                    del cells[key]
            for worker in successful_workers:
                raw_cells = profiles.get(worker, [])
                for raw in raw_cells if isinstance(raw_cells, list) else []:
                    if not isinstance(raw, dict):
                        continue
                    key = _cell_key(worker, raw.get("profile"), lane)
                    if key is None or key[1] is None:
                        continue
                    fingerprint = _safe_fingerprint(raw.get("fingerprint"))
                    session_fingerprint = _safe_fingerprint(
                        raw.get("session_fingerprint")
                    )
                    ready = raw.get("ready") is True and bool(fingerprint)
                    reason = _reason(
                        raw.get("reason_code"),
                        "PROFILE_DOWNLOAD_LANE_UNAVAILABLE"
                        if lane == "download"
                        else "PROFILE_UPLOAD_LANE_UNAVAILABLE",
                    )
                    if raw.get("ready") is True and not ready:
                        reason = "PROFILE_LANE_EVIDENCE_INCOMPLETE"
                    cells[key] = {
                        "worker": worker,
                        "profile": key[1],
                        "runtime": lane,
                        "status": "ready" if ready else "not_ready",
                        "checked_at": str(raw.get("checked_at") or when)[:64],
                        "reason_code": "" if ready else reason,
                        "fingerprint": fingerprint if ready else "",
                        "session_fingerprint": session_fingerprint if ready else "",
                        "destination_fingerprint": "",
                    }
                    previous = previous_cells.get(key)
                    self._attach_last_attempt(cells[key], raw, previous, when)
            snapshot["cells"] = sorted(
                cells.values(),
                key=lambda item: (item["worker"], item["profile"] or "", item["runtime"]),
            )
            snapshot["checked_at"] = when
            self._save_locked(snapshot)
            return copy.deepcopy(snapshot)

    def mark_worker_failed(
        self,
        *,
        worker: str,
        reason_code: str,
        checked_at: str | None = None,
    ) -> bool:
        normalized_worker = str(worker or "").strip().lower()
        if not _WORKER_RE.fullmatch(normalized_worker):
            return False
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            snapshot = copy.deepcopy(self._snapshot)
            worker_map = {item["name"]: item for item in snapshot["workers"]}
            worker_map[normalized_worker] = {
                "name": normalized_worker,
                "status": "failed",
                "checked_at": str(checked_at or utc_now_iso())[:64],
                "reason_code": _reason(reason_code, "WORKER_UNAVAILABLE"),
            }
            snapshot["workers"] = sorted(
                worker_map.values(), key=lambda item: item["name"]
            )
            snapshot["checked_at"] = str(checked_at or utc_now_iso())[:64]
            self._save_locked(snapshot)
            return True

    def apply_tts_scan(
        self,
        *,
        checked_at: str,
        profiles: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Replace TTS cells for successfully scanned workers only."""
        when = str(checked_at or "")[:64] or utc_now_iso()
        successful_workers = {
            str(worker or "").strip().lower()
            for worker in profiles
            if _WORKER_RE.fullmatch(str(worker or "").strip().lower())
        }
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            snapshot = copy.deepcopy(self._snapshot)
            cells = {
                _cell_key(item["worker"], item["profile"], item["runtime"]): item
                for item in snapshot["cells"]
            }
            previous_cells = dict(cells)
            for key in list(cells):
                if key is not None and key[0] in successful_workers and key[2] == "tts":
                    del cells[key]
            for worker in successful_workers:
                raw_cells = profiles.get(worker, [])
                for raw in raw_cells if isinstance(raw_cells, list) else []:
                    if not isinstance(raw, dict):
                        continue
                    key = _cell_key(worker, raw.get("profile"), "tts")
                    if key is None:
                        continue
                    fingerprint = _safe_fingerprint(raw.get("fingerprint"))
                    ready = raw.get("ready") is True and bool(fingerprint)
                    cells[key] = {
                        "worker": worker,
                        "profile": key[1],
                        "runtime": "tts",
                        "status": "ready" if ready else "not_ready",
                        "checked_at": str(raw.get("checked_at") or when)[:64],
                        "reason_code": "" if ready else _reason(
                            raw.get("reason_code"), "TTS_RUNTIME_UNAVAILABLE"
                        ),
                        "fingerprint": fingerprint if ready else "",
                        "session_fingerprint": _safe_fingerprint(
                            raw.get("session_fingerprint")
                        ) if ready else "",
                        "destination_fingerprint": _safe_fingerprint(
                            raw.get("destination_fingerprint")
                        ) if ready else "",
                    }
                    self._attach_last_attempt(
                        cells[key], raw, previous_cells.get(key), when
                    )
            snapshot["cells"] = sorted(
                cells.values(),
                key=lambda item: (item["worker"], item["profile"] or "", item["runtime"]),
            )
            snapshot["checked_at"] = when
            self._save_locked(snapshot)
            return copy.deepcopy(snapshot)

    def apply_storage_scan(
        self,
        *,
        checked_at: str,
        profiles: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Replace Storage sender cells for workers scanned successfully."""
        when = str(checked_at or "")[:64] or utc_now_iso()
        successful_workers = {
            str(worker or "").strip().lower()
            for worker in profiles
            if _WORKER_RE.fullmatch(str(worker or "").strip().lower())
        }
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            snapshot = copy.deepcopy(self._snapshot)
            cells = {
                _cell_key(item["worker"], item["profile"], item["runtime"]): item
                for item in snapshot["cells"]
            }
            previous_cells = dict(cells)
            for key in list(cells):
                if key is not None and key[0] in successful_workers and key[2] == "storage":
                    del cells[key]
            for worker in successful_workers:
                raw_cells = profiles.get(worker, [])
                for raw in raw_cells if isinstance(raw_cells, list) else []:
                    if not isinstance(raw, dict):
                        continue
                    key = _cell_key(worker, raw.get("profile"), "storage")
                    if key is None or key[1] is None:
                        continue
                    fingerprint = _safe_fingerprint(raw.get("fingerprint"))
                    session_fingerprint = _safe_fingerprint(
                        raw.get("session_fingerprint")
                    )
                    destination_fingerprint = _safe_fingerprint(
                        raw.get("destination_fingerprint")
                    )
                    ready = bool(
                        raw.get("ready") is True
                        and fingerprint
                        and session_fingerprint
                        and destination_fingerprint
                    )
                    reason = _reason(raw.get("reason_code"), "STORAGE_RUNTIME_UNAVAILABLE")
                    if raw.get("ready") is True and not ready:
                        reason = "STORAGE_EVIDENCE_INCOMPLETE"
                    cells[key] = {
                        "worker": worker,
                        "profile": key[1],
                        "runtime": "storage",
                        "status": "ready" if ready else "not_ready",
                        "checked_at": str(raw.get("checked_at") or when)[:64],
                        "reason_code": "" if ready else reason,
                        "fingerprint": fingerprint if ready else "",
                        "session_fingerprint": session_fingerprint if ready else "",
                        "destination_fingerprint": destination_fingerprint if ready else "",
                    }
                    self._attach_last_attempt(
                        cells[key], raw, previous_cells.get(key), when
                    )
            snapshot["cells"] = sorted(
                cells.values(),
                key=lambda item: (item["worker"], item["profile"] or "", item["runtime"]),
            )
            snapshot["checked_at"] = when
            self._save_locked(snapshot)
            return copy.deepcopy(snapshot)

    def apply_resolver_scan(
        self,
        *,
        checked_at: str,
        workers: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace Resolver cells for workers whose profile scan succeeded."""
        when = str(checked_at or "")[:64] or utc_now_iso()
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            snapshot = copy.deepcopy(self._snapshot)
            cells = {
                _cell_key(item["worker"], item["profile"], item["runtime"]): item
                for item in snapshot["cells"]
            }
            for worker, raw in workers.items():
                if not isinstance(raw, dict):
                    continue
                key = _cell_key(worker, None, _RESOLVER_RUNTIME)
                if key is None:
                    continue
                fingerprint = _safe_fingerprint(raw.get("fingerprint"))
                ready = raw.get("ready") is True and bool(fingerprint)
                previous = cells.get(key)
                cells[key] = {
                    "worker": key[0],
                    "profile": None,
                    "runtime": _RESOLVER_RUNTIME,
                    "status": "ready" if ready else "not_ready",
                    "checked_at": str(raw.get("checked_at") or when)[:64],
                    "reason_code": "" if ready else _reason(
                        raw.get("reason_code"), "RESOLVER_RUNTIME_UNAVAILABLE"
                    ),
                    "fingerprint": fingerprint if ready else "",
                    "session_fingerprint": "",
                    "destination_fingerprint": "",
                }
                attempt = _safe_last_attempt(
                    raw.get("last_attempt"),
                    worker=key[0],
                    profile=None,
                    runtime=_RESOLVER_RUNTIME,
                    checked_at=str(raw.get("checked_at") or when)[:64],
                    ready=ready,
                    reason_code=cells[key]["reason_code"],
                )
                if attempt is not None:
                    cells[key]["last_attempt"] = attempt
                elif previous is not None and isinstance(previous.get("last_attempt"), dict):
                    cells[key]["last_attempt"] = previous["last_attempt"]
            snapshot["cells"] = sorted(
                cells.values(),
                key=lambda item: (item["worker"], item["profile"] or "", item["runtime"]),
            )
            snapshot["checked_at"] = when
            self._save_locked(snapshot)
            return copy.deepcopy(snapshot)

    def apply_quickmode_scan(
        self,
        *,
        checked_at: str,
        workers: list[dict[str, Any]],
        profiles: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Replace Quick Mode evidence for workers scanned successfully.

        Sender session fingerprints and destination hashes remain private in
        this store. Failed/disabled worker scans leave the last cell in place;
        the worker reachability row independently blocks admission.
        """
        when = str(checked_at or "")[:64] or utc_now_iso()
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            snapshot = copy.deepcopy(self._snapshot)
            worker_map = {item["name"]: item for item in snapshot["workers"]}
            cells = {
                _cell_key(item["worker"], item["profile"], item["runtime"]): item
                for item in snapshot["cells"]
            }
            previous_cells = dict(cells)
            successful_workers: set[str] = set()
            for raw in workers:
                if not isinstance(raw, dict):
                    continue
                worker = str(raw.get("worker") or raw.get("name") or "").strip().lower()
                status = str(raw.get("status") or "")
                if not _WORKER_RE.fullmatch(worker) or status not in {"success", "failed", "disabled"}:
                    continue
                error_code = _reason(raw.get("error_code"), "WORKER_SCAN_FAILED")
                worker_map[worker] = {
                    "name": worker,
                    "status": status,
                    "checked_at": str(raw.get("checked_at") or when)[:64],
                    "reason_code": error_code if status == "failed" else (
                        "WORKER_DISABLED" if status == "disabled" else ""
                    ),
                }
                if status == "success":
                    successful_workers.add(worker)

            for key in list(cells):
                if key is not None and key[0] in successful_workers and key[2] == _QUICK_MODE_RUNTIME:
                    del cells[key]
            for worker in successful_workers:
                raw_cells = profiles.get(worker, [])
                for raw in raw_cells if isinstance(raw_cells, list) else []:
                    if not isinstance(raw, dict):
                        continue
                    key = _cell_key(worker, raw.get("profile"), _QUICK_MODE_RUNTIME)
                    if key is None or key[1] is None:
                        continue
                    fingerprint = _safe_fingerprint(raw.get("fingerprint"))
                    sender_fingerprints = _safe_fingerprint_map(
                        raw.get("sender_session_fingerprints")
                    )
                    sender_profiles = _safe_profile_list(raw.get("sender_profiles"))
                    ready = (
                        raw.get("ready") is True
                        and bool(fingerprint)
                        and bool(sender_profiles)
                        and all(profile in sender_fingerprints for profile in sender_profiles)
                    )
                    session_fingerprint = _safe_fingerprint(raw.get("session_fingerprint"))
                    destination_fingerprint = _safe_fingerprint(
                        raw.get("destination_fingerprint")
                    )
                    rclone_fingerprint = _safe_fingerprint(
                        raw.get("rclone_destination_fingerprint")
                    )
                    ready = ready and bool(
                        session_fingerprint and destination_fingerprint and rclone_fingerprint
                    )
                    reason = _reason(raw.get("reason_code"), "QUICK_MODE_RUNTIME_UNAVAILABLE")
                    if raw.get("ready") is True and not ready:
                        reason = "QUICK_MODE_EVIDENCE_INCOMPLETE"
                    cells[key] = {
                        "worker": worker,
                        "profile": key[1],
                        "runtime": _QUICK_MODE_RUNTIME,
                        "status": "ready" if ready else "not_ready",
                        "checked_at": str(raw.get("checked_at") or when)[:64],
                        "reason_code": "" if ready else reason,
                        "fingerprint": fingerprint if ready else "",
                        "session_fingerprint": session_fingerprint if ready else "",
                        "destination_fingerprint": destination_fingerprint if ready else "",
                        "rclone_destination_fingerprint": rclone_fingerprint if ready else "",
                        "sender_profiles": sender_profiles if ready else [],
                        "sender_session_fingerprints": sender_fingerprints if ready else {},
                    }
                    self._attach_last_attempt(
                        cells[key], raw, previous_cells.get(key), when
                    )

            snapshot["workers"] = sorted(worker_map.values(), key=lambda item: item["name"])
            snapshot["cells"] = sorted(
                cells.values(),
                key=lambda item: (item["worker"], item["profile"] or "", item["runtime"]),
            )
            snapshot["checked_at"] = when
            self._save_locked(snapshot)
            return copy.deepcopy(snapshot)

    def upsert_cell(
        self,
        *,
        worker: str,
        profile: str | None,
        runtime: str,
        ready: bool,
        fingerprint: str = "",
        session_fingerprint: str = "",
        destination_fingerprint: str = "",
        reason_code: str = "",
        checked_at: str | None = None,
        last_attempt: dict[str, Any] | None = None,
    ) -> bool:
        """Store one runtime cell, including worker-scoped cells without a profile."""
        key = _cell_key(worker, profile, runtime)
        if key is None:
            return False
        when = str(checked_at or utc_now_iso())[:64]
        normalized_fingerprint = str(fingerprint or "").strip().lower()
        normalized_session_fingerprint = str(session_fingerprint or "").strip().lower()
        if normalized_session_fingerprint and not _FINGERPRINT_RE.fullmatch(
            normalized_session_fingerprint
        ):
            normalized_session_fingerprint = ""
        normalized_destination_fingerprint = _safe_fingerprint(
            destination_fingerprint
        )
        is_ready = bool(ready and _FINGERPRINT_RE.fullmatch(normalized_fingerprint))
        cell = {
            "worker": key[0],
            "profile": key[1],
            "runtime": key[2],
            "status": "ready" if is_ready else "not_ready",
            "checked_at": when,
            "reason_code": "" if is_ready else _reason(reason_code, "RUNTIME_NOT_READY"),
            "fingerprint": normalized_fingerprint if is_ready else "",
            "session_fingerprint": normalized_session_fingerprint if is_ready else "",
            "destination_fingerprint": (
                normalized_destination_fingerprint if is_ready else ""
            ),
        }
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            snapshot = copy.deepcopy(self._snapshot)
            cells = {
                _cell_key(item["worker"], item["profile"], item["runtime"]): item
                for item in snapshot["cells"]
            }
            previous = cells.get(key)
            attempt = _safe_last_attempt(
                last_attempt,
                worker=key[0],
                profile=key[1],
                runtime=key[2],
                checked_at=when,
                ready=is_ready,
                reason_code=cell["reason_code"],
            )
            if attempt is not None:
                cell["last_attempt"] = attempt
            elif previous is not None and isinstance(previous.get("last_attempt"), dict):
                cell["last_attempt"] = previous["last_attempt"]
            cells[key] = cell
            snapshot["cells"] = sorted(
                cells.values(),
                key=lambda item: (item["worker"], item["profile"] or "", item["runtime"]),
            )
            snapshot["checked_at"] = when
            self._save_locked(snapshot)
            return True

    def upsert_quick_mode_cell(
        self,
        *,
        worker: str,
        profile: str,
        ready: bool,
        fingerprint: str = "",
        session_fingerprint: str = "",
        destination_fingerprint: str = "",
        rclone_destination_fingerprint: str = "",
        sender_profiles: list[str] | None = None,
        sender_session_fingerprints: dict[str, str] | None = None,
        reason_code: str = "",
        checked_at: str | None = None,
        last_attempt: dict[str, Any] | None = None,
    ) -> bool:
        """Replace one derived Quick Mode cell without touching sibling profiles."""
        key = _cell_key(worker, profile, _QUICK_MODE_RUNTIME)
        if key is None or key[1] is None:
            return False
        when = str(checked_at or utc_now_iso())[:64]
        normalized_fingerprint = _safe_fingerprint(fingerprint)
        normalized_session = _safe_fingerprint(session_fingerprint)
        normalized_destination = _safe_fingerprint(destination_fingerprint)
        normalized_rclone = _safe_fingerprint(rclone_destination_fingerprint)
        safe_senders = _safe_profile_list(sender_profiles)
        safe_sender_fingerprints = _safe_fingerprint_map(sender_session_fingerprints)
        is_ready = bool(
            ready
            and normalized_fingerprint
            and normalized_session
            and normalized_destination
            and normalized_rclone
            and safe_senders
            and all(name in safe_sender_fingerprints for name in safe_senders)
        )
        cell = {
            "worker": key[0],
            "profile": key[1],
            "runtime": _QUICK_MODE_RUNTIME,
            "status": "ready" if is_ready else "not_ready",
            "checked_at": when,
            "reason_code": "" if is_ready else _reason(
                reason_code, "QUICK_MODE_EVIDENCE_INCOMPLETE"
            ),
            "fingerprint": normalized_fingerprint if is_ready else "",
            "session_fingerprint": normalized_session if is_ready else "",
            "destination_fingerprint": normalized_destination if is_ready else "",
            "rclone_destination_fingerprint": normalized_rclone if is_ready else "",
            "sender_profiles": safe_senders if is_ready else [],
            "sender_session_fingerprints": safe_sender_fingerprints if is_ready else {},
        }
        attempt = _safe_last_attempt(
            last_attempt,
            worker=key[0],
            profile=key[1],
            runtime=_QUICK_MODE_RUNTIME,
            checked_at=when,
            ready=is_ready,
            reason_code=cell["reason_code"],
        )
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            snapshot = copy.deepcopy(self._snapshot)
            cells = {
                _cell_key(item["worker"], item["profile"], item["runtime"]): item
                for item in snapshot["cells"]
            }
            previous = cells.get(key)
            if attempt is not None:
                cell["last_attempt"] = attempt
            elif previous is not None and isinstance(previous.get("last_attempt"), dict):
                cell["last_attempt"] = previous["last_attempt"]
            cells[key] = cell
            snapshot["cells"] = sorted(
                cells.values(),
                key=lambda item: (item["worker"], item["profile"] or "", item["runtime"]),
            )
            snapshot["checked_at"] = when
            self._save_locked(snapshot)
        return True

    def invalidate(
        self,
        *,
        worker: str,
        profile: str | None,
        runtime: str,
        reason_code: str,
        checked_at: str | None = None,
    ) -> bool:
        key = _cell_key(worker, profile, runtime)
        if key is None:
            return False
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            snapshot = copy.deepcopy(self._snapshot)
            for cell in snapshot["cells"]:
                if _cell_key(cell["worker"], cell["profile"], cell["runtime"]) != key:
                    continue
                cell["status"] = "not_ready"
                cell["checked_at"] = str(checked_at or utc_now_iso())[:64]
                cell["reason_code"] = _reason(reason_code, "RUNTIME_ACCESS_FAILED")
                cell["fingerprint"] = ""
                cell["session_fingerprint"] = ""
                cell["destination_fingerprint"] = ""
                cell.pop("rclone_destination_fingerprint", None)
                cell.pop("sender_profiles", None)
                cell.pop("sender_session_fingerprints", None)
                self._save_locked(snapshot)
                return True
            return False

    def invalidate_quick_mode_sender(
        self,
        *,
        worker: str,
        sender_profile: str,
        reason_code: str,
        checked_at: str | None = None,
    ) -> bool:
        """Invalidate cells whose pinned Upload evidence uses this profile."""
        normalized_worker = str(worker or "").strip().lower()
        normalized_sender = normalize_profile_name(str(sender_profile or ""))
        if not _WORKER_RE.fullmatch(normalized_worker) or not normalized_sender:
            return False
        changed = False
        with self._lock:
            self._load_locked()
            assert self._snapshot is not None
            snapshot = copy.deepcopy(self._snapshot)
            for cell in snapshot["cells"]:
                if (
                    cell.get("worker") != normalized_worker
                    or cell.get("runtime") != _QUICK_MODE_RUNTIME
                    or normalized_sender not in _safe_profile_list(cell.get("sender_profiles"))
                ):
                    continue
                cell.update(
                    status="not_ready",
                    checked_at=str(checked_at or utc_now_iso())[:64],
                    reason_code=_reason(reason_code, "RUNTIME_ACCESS_FAILED"),
                    fingerprint="",
                    session_fingerprint="",
                    destination_fingerprint="",
                    rclone_destination_fingerprint="",
                    sender_profiles=[],
                    sender_session_fingerprints={},
                )
                changed = True
            if changed:
                snapshot["checked_at"] = str(checked_at or utc_now_iso())[:64]
                self._save_locked(snapshot)
        return changed

    def _export_cell(
        self, worker: str, raw: dict[str, Any], checked_at: str
    ) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        profile = normalize_profile_name(str(raw.get("profile") or raw.get("name") or ""))
        if not profile:
            return None
        fingerprint = str(raw.get("fingerprint") or "").strip().lower()
        ready = raw.get("ready") is True and bool(_FINGERPRINT_RE.fullmatch(fingerprint))
        reason_code = "" if ready else _reason(raw.get("reason_code"), "PROFILE_SESSION_UNAVAILABLE")
        if raw.get("ready") is True and not fingerprint:
            reason_code = "PROFILE_FINGERPRINT_MISSING"
        cell = {
            "worker": worker,
            "profile": profile,
            "runtime": _EXPORT_RUNTIME,
            "status": "ready" if ready else "not_ready",
            "checked_at": str(raw.get("checked_at") or checked_at)[:64],
            "reason_code": reason_code,
            "fingerprint": fingerprint if ready else "",
            "session_fingerprint": "",
            "destination_fingerprint": "",
        }
        self._attach_last_attempt(cell, raw, None, checked_at)
        return cell

    @staticmethod
    def _attach_last_attempt(
        cell: dict[str, Any],
        raw: dict[str, Any],
        previous: dict[str, Any] | None,
        checked_at: str,
    ) -> None:
        attempt = _safe_last_attempt(
            raw.get("last_attempt"),
            worker=cell["worker"],
            profile=cell["profile"],
            runtime=cell["runtime"],
            checked_at=str(raw.get("checked_at") or checked_at)[:64],
            ready=cell["status"] == "ready",
            reason_code=cell["reason_code"],
        )
        if attempt is not None:
            cell["last_attempt"] = attempt
        elif previous is not None and isinstance(previous.get("last_attempt"), dict):
            cell["last_attempt"] = previous["last_attempt"]

    def _load_locked(self) -> None:
        if self._snapshot is not None:
            return
        if not self.path.exists():
            self._snapshot = _empty_snapshot()
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._snapshot = _empty_snapshot()
            return
        workers = payload.get("workers") if isinstance(payload, dict) else None
        cells = payload.get("cells") if isinstance(payload, dict) else None
        self._snapshot = _normalize_snapshot(
            checked_at=payload.get("checked_at", "") if isinstance(payload, dict) else "",
            workers=workers if isinstance(workers, list) else [],
            cells=cells if isinstance(cells, list) else [],
        )

    def _save_locked(self, snapshot: dict[str, Any]) -> None:
        normalized = _normalize_snapshot(
            checked_at=snapshot.get("checked_at", ""),
            workers=snapshot.get("workers", []),
            cells=snapshot.get("cells", []),
        )
        write_json_atomic_private(self.path, normalized)
        self._snapshot = normalized


def _normalize_snapshot(
    *, checked_at: Any, workers: list[Any], cells: list[Any]
) -> dict[str, Any]:
    safe_workers: dict[str, dict[str, str]] = {}
    for raw in workers:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip().lower()
        status = str(raw.get("status") or "")
        if not _WORKER_RE.fullmatch(name) or status not in {"success", "failed", "disabled"}:
            continue
        safe_workers[name] = {
            "name": name,
            "status": status,
            "checked_at": str(raw.get("checked_at") or "")[:64],
            "reason_code": _reason(raw.get("reason_code"), "WORKER_SCAN_FAILED") if status == "failed" else ("WORKER_DISABLED" if status == "disabled" else ""),
        }
    safe_cells: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    for raw in cells:
        if not isinstance(raw, dict):
            continue
        key = _cell_key(raw.get("worker"), raw.get("profile"), raw.get("runtime"))
        status = str(raw.get("status") or "")
        if key is None or status not in {"ready", "not_ready"}:
            continue
        ready = status == "ready"
        fingerprint = str(raw.get("fingerprint") or "").strip().lower()
        if ready and not _FINGERPRINT_RE.fullmatch(fingerprint):
            continue
        safe_cell = {
            "worker": key[0],
            "profile": key[1],
            "runtime": key[2],
            "status": status,
            "checked_at": str(raw.get("checked_at") or "")[:64],
            "reason_code": "" if ready else _reason(raw.get("reason_code"), "RUNTIME_NOT_READY"),
            "fingerprint": fingerprint if ready else "",
            "session_fingerprint": _safe_fingerprint(raw.get("session_fingerprint")) if ready else "",
            "destination_fingerprint": _safe_fingerprint(raw.get("destination_fingerprint")) if ready else "",
            **({
                "rclone_destination_fingerprint": _safe_fingerprint(
                    raw.get("rclone_destination_fingerprint")
                ) if ready else "",
                "sender_profiles": _safe_profile_list(raw.get("sender_profiles")) if ready else [],
                "sender_session_fingerprints": _safe_fingerprint_map(
                    raw.get("sender_session_fingerprints")
                ) if ready else {},
            } if key[2] == _QUICK_MODE_RUNTIME else {}),
        }
        attempt = _safe_last_attempt(
            raw.get("last_attempt"),
            worker=key[0],
            profile=key[1],
            runtime=key[2],
            checked_at=str(raw.get("checked_at") or "")[:64],
            ready=ready,
            reason_code=safe_cell["reason_code"],
        )
        if attempt is not None:
            safe_cell["last_attempt"] = attempt
        safe_cells[key] = safe_cell
    return {
        "checked_at": str(checked_at or "")[:64],
        "workers": sorted(safe_workers.values(), key=lambda item: item["name"]),
        "cells": sorted(
            safe_cells.values(),
            key=lambda item: (item["worker"], item["profile"] or "", item["runtime"]),
        ),
    }


def _cell_key(
    worker: Any, profile: Any, runtime: Any
) -> tuple[str, str | None, str] | None:
    normalized_worker = str(worker or "").strip().lower()
    normalized_profile = (
        normalize_profile_name(str(profile))
        if profile is not None and str(profile).strip()
        else None
    )
    normalized_runtime = str(runtime or "").strip().lower()
    if (
        not _WORKER_RE.fullmatch(normalized_worker)
        or not _RUNTIME_RE.fullmatch(normalized_runtime)
    ):
        return None
    return normalized_worker, normalized_profile, normalized_runtime


def _reason(value: Any, fallback: str) -> str:
    code = str(value or "").strip().upper()
    return code if _REASON_RE.fullmatch(code) else fallback


def _safe_fingerprint(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _FINGERPRINT_RE.fullmatch(text) else ""


def _safe_last_attempt(
    value: Any,
    *,
    worker: str,
    profile: str | None,
    runtime: str,
    checked_at: str,
    ready: bool,
    reason_code: str,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    phase = str(value.get("phase") or "runtime_probe")
    if not _PHASE_RE.fullmatch(phase):
        phase = "runtime_probe"
    checks = []
    raw_checks = value.get("checks")
    for raw in raw_checks[:12] if isinstance(raw_checks, list) else []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip().lower()
        status = str(raw.get("status") or "")
        if not _RUNTIME_RE.fullmatch(name) or status not in {"ready", "not_ready", "failed"}:
            continue
        code = str(raw.get("reason_code") or "")
        checks.append({
            "name": name,
            "status": status,
            "reason_code": code if _REASON_RE.fullmatch(code) else "",
        })
    dependencies = []
    raw_dependencies = value.get("dependencies")
    for item in raw_dependencies[:16] if isinstance(raw_dependencies, list) else []:
        name = str(item or "").strip().lower()
        if _RUNTIME_RE.fullmatch(name) and name not in dependencies:
            dependencies.append(name)
    raw_cleanup = value.get("cleanup")
    cleanup = raw_cleanup if isinstance(raw_cleanup, dict) else {}
    cleanup_status = str(cleanup.get("status") or "not_needed")
    if cleanup_status not in {"not_needed", "succeeded", "failed"}:
        cleanup_status = "failed"
    cleanup_code = str(cleanup.get("reason_code") or "")
    result_code = str(value.get("reason_code") or reason_code or "")
    return {
        "target": {"worker": worker, "profile": profile, "runtime": runtime},
        "checked_at": str(value.get("checked_at") or checked_at)[:64],
        "phase": phase,
        "checks": checks,
        "status": "ready" if ready else "not_ready",
        "reason_code": result_code if _REASON_RE.fullmatch(result_code) else "",
        "dependencies": dependencies,
        "cleanup": {
            "status": cleanup_status,
            "reason_code": cleanup_code if _REASON_RE.fullmatch(cleanup_code) else "",
        },
    }


def _safe_profile_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        profile = normalize_profile_name(str(item or ""))
        if profile and profile not in result:
            result.append(profile)
    return result


def _safe_fingerprint_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for raw_profile, raw_fingerprint in value.items():
        profile = normalize_profile_name(str(raw_profile or ""))
        fingerprint = _safe_fingerprint(raw_fingerprint)
        if profile and fingerprint:
            result[profile] = fingerprint
    return result


def _empty_snapshot() -> dict[str, Any]:
    return {"checked_at": "", "workers": [], "cells": []}
