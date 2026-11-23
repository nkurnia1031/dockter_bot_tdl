from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


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
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

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
                "checked_at": now.isoformat(),
            }
        with self._lock:
            self._snapshots = snapshots

    def snapshot(self, worker: str) -> dict[str, Any]:
        name = str(worker or "").strip().lower()
        with self._lock:
            entry = dict(self._snapshots.get(name) or {})
        if not entry:
            return {"worker": name, "status": "unknown", "healthy": False}
        try:
            checked = datetime.fromisoformat(str(entry["checked_at"]))
            age = max(0.0, (_aware(self.clock()) - _aware(checked)).total_seconds())
        except (KeyError, TypeError, ValueError):
            return {"worker": name, "status": "unknown", "healthy": False}
        status = str(entry.get("status") or "unknown")
        if status in {"ready", "offline"} and age > self.max_age_seconds:
            status = "stale"
        return {
            "worker": name,
            "status": status,
            "healthy": status == "ready",
            "checked_at": entry.get("checked_at"),
            "age_seconds": int(age),
        }

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
