from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def probe_worker_health(
    checker: Callable[[str], dict[str, Any]], worker: str, *, attempts: int = 2
) -> dict[str, Any]:
    """Classify reachability from a bounded set of fresh lightweight probes."""
    name = str(worker or "").strip().lower()
    checked = failures = 0
    unknown = False
    for _ in range(max(1, min(int(attempts), 2))):
        checked += 1
        try:
            result = checker(name)
        except Exception:
            failures += 1
            continue
        if isinstance(result, dict) and result.get("healthy") is True:
            return {
                "worker": name,
                "status": "ready",
                "healthy": True,
                "health_probe_attempts": checked,
                "health_probe_failures": failures,
                "restart_probe_confirmed": False,
            }
        if isinstance(result, dict) and result.get("healthy") is False:
            failures += 1
        else:
            unknown = True
    confirmed_offline = failures >= 2 and not unknown
    return {
        "worker": name,
        "status": "offline" if confirmed_offline else "unknown",
        "healthy": False,
        "health_probe_attempts": checked,
        "health_probe_failures": failures,
        "restart_probe_confirmed": confirmed_offline,
    }


class WorkerHealthMonitor:
    """Background worker probes with a read-only, bounded-age snapshot."""

    def __init__(
        self,
        registry,
        checker: Callable[[str], dict[str, Any]],
        *,
        interval_seconds: float = 30,
        max_age_seconds: float = 60,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.registry = registry
        self.checker = checker
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.max_age_seconds = max(1.0, float(max_age_seconds))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._unresponsive: dict[str, dict[str, str]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def mark_unresponsive(self, worker: str, *, reason: str) -> None:
        name = str(worker or "").strip().lower()
        if not name:
            return
        with self._lock:
            self._unresponsive[name] = {
                "reason": str(reason or "worker_unresponsive")[:96],
                "marked_at": _aware(self.clock()).isoformat(),
            }

    def clear_unresponsive(self, worker: str) -> bool:
        name = str(worker or "").strip().lower()
        with self._lock:
            return self._unresponsive.pop(name, None) is not None

    def refresh_once(self) -> None:
        workers = self.registry.list()
        enabled = [
            name for name, record in workers.items()
            if bool(record.get("enabled", True))
        ]
        now = _aware(self.clock())
        results: dict[str, bool] = {}
        if enabled:
            with ThreadPoolExecutor(max_workers=min(8, len(enabled))) as pool:
                futures = {pool.submit(self.checker, name): name for name in enabled}
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        result = future.result()
                        results[name] = (
                            isinstance(result, dict)
                            and result.get("healthy") is True
                        )
                    except Exception:
                        results[name] = False

        snapshots = {}
        for name, record in workers.items():
            if not bool(record.get("enabled", True)):
                snapshots[name] = {
                    "status": "disabled",
                    "healthy": False,
                    "checked_at": now.isoformat(),
                }
                continue
            snapshots[name] = {
                "status": "ready" if results.get(name, False) else "offline",
                "healthy": results.get(name, False),
                "health_probe_attempts": 1,
                "health_probe_failures": 0 if results.get(name, False) else 1,
                "restart_probe_confirmed": False,
                "checked_at": now.isoformat(),
            }
        with self._lock:
            self._snapshots = snapshots

    def snapshot(self, worker: str) -> dict[str, Any]:
        name = str(worker or "").strip().lower()
        with self._lock:
            entry = dict(self._snapshots.get(name) or {})
            unresponsive = dict(self._unresponsive.get(name) or {})
        if not entry:
            status = "unknown"
            snapshot = {"worker": name, "status": status, "healthy": False}
            if unresponsive:
                return {
                    **snapshot,
                    "reason": unresponsive.get("reason"),
                    "cancellation_unconfirmed": True,
                }
            return snapshot
        try:
            checked = datetime.fromisoformat(str(entry["checked_at"]))
            age = max(0.0, (_aware(self.clock()) - _aware(checked)).total_seconds())
        except (KeyError, TypeError, ValueError):
            snapshot = {"worker": name, "status": "unknown", "healthy": False}
            if unresponsive:
                return {
                    **snapshot,
                    "reason": unresponsive.get("reason"),
                    "cancellation_unconfirmed": True,
                }
            return snapshot
        status = str(entry.get("status") or "unknown")
        if status in {"ready", "offline"} and age > self.max_age_seconds:
            status = "stale"
        snapshot = {
            "worker": name,
            "status": status,
            "healthy": status == "ready",
            "checked_at": entry.get("checked_at"),
            "age_seconds": int(age),
            "health_probe_attempts": int(entry.get("health_probe_attempts") or 0),
            "health_probe_failures": int(entry.get("health_probe_failures") or 0),
            "restart_probe_confirmed": bool(entry.get("restart_probe_confirmed")),
        }
        if unresponsive:
            return {
                **snapshot,
                "reason": unresponsive.get("reason"),
                "cancellation_unconfirmed": True,
            }
        return snapshot

    def probe_worker(self, worker: str) -> dict[str, Any]:
        """Confirm one worker on demand with at most two lightweight probes."""
        name = str(worker or "").strip().lower()
        record = self.registry.list().get(name)
        now = _aware(self.clock())
        if record is None:
            return {"worker": name, "status": "unknown", "healthy": False}
        if not bool(record.get("enabled", True)):
            with self._lock:
                self._snapshots[name] = {
                    "status": "disabled",
                    "healthy": False,
                    "checked_at": now.isoformat(),
                }
            return self.snapshot(name)

        result = probe_worker_health(self.checker, name)
        with self._lock:
            self._snapshots[name] = {**result, "checked_at": now.isoformat()}
        return self.snapshot(name)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()

        def run() -> None:
            while not self._stop.is_set():
                try:
                    self.refresh_once()
                except Exception:
                    # A failed refresh leaves the prior snapshot to age out.
                    pass
                self._stop.wait(self.interval_seconds)

        self._thread = threading.Thread(
            target=run, name="worker-health-monitor", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout)))
        self._thread = None
