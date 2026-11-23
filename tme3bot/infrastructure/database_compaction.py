from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

LOGGER = logging.getLogger(__name__)


class DatabaseCompactionService:
    """Periodically return retained SQLite free pages to the host filesystem."""

    def __init__(
        self,
        jobs,
        *,
        min_free_bytes: int = 64 * 1024 * 1024,
        interval_seconds: int = 6 * 60 * 60,
    ) -> None:
        self.jobs = jobs
        self.min_free_bytes = max(0, int(min_free_bytes))
        self.interval_seconds = max(60, int(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._compaction_active = False
        self._active_database_activities = 0
        self._cancel_requested = threading.Event()
        self._last_checked_at: str | None = None
        self._last_result: dict[str, object] = {"outcome": "not_run"}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="database-compaction",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.begin_database_activity()
        self.end_database_activity()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)

    def begin_database_activity(self) -> None:
        """Reserve a writer window or cancel compaction already in progress."""
        with self._status_lock:
            self._active_database_activities += 1
            active = self._compaction_active
            if active:
                self._cancel_requested.set()
        interrupt = getattr(self.jobs, "interrupt_database_compaction", None)
        if active and callable(interrupt):
            interrupt()

    def end_database_activity(self) -> None:
        with self._status_lock:
            self._active_database_activities = max(
                0, self._active_database_activities - 1
            )

    @contextmanager
    def database_activity(self):
        self.begin_database_activity()
        try:
            yield
        finally:
            self.end_database_activity()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                LOGGER.warning(
                    "Database compaction maintenance failed (%s)", type(exc).__name__
                )
            self._stop.wait(self.interval_seconds)

    def tick(self) -> dict[str, object]:
        if not self._tick_lock.acquire(blocking=False):
            result: dict[str, object] = {
                "outcome": "deferred_locked",
                "reason": "maintenance_busy",
                "threshold_bytes": self.min_free_bytes,
            }
        else:
            with self._status_lock:
                if self._active_database_activities:
                    active_database_activities = self._active_database_activities
                    can_compact = False
                else:
                    active_database_activities = 0
                    self._cancel_requested.clear()
                    self._compaction_active = True
                    can_compact = True
            if not can_compact:
                result = {
                    "outcome": "deferred_active_activity",
                    "active_database_activities": active_database_activities,
                    "threshold_bytes": self.min_free_bytes,
                }
                self._tick_lock.release()
            else:
                try:
                    result = self.jobs.compact_database_if_idle(
                        self.min_free_bytes,
                        cancel_event=self._cancel_requested,
                    )
                except Exception as exc:
                    LOGGER.warning(
                        "Database compaction maintenance failed (%s)", type(exc).__name__
                    )
                    result = {
                        "outcome": "failed",
                        "error_type": type(exc).__name__,
                        "threshold_bytes": self.min_free_bytes,
                    }
                finally:
                    with self._status_lock:
                        self._compaction_active = False
                    self._tick_lock.release()
        checked_at = datetime.now(timezone.utc).isoformat()
        result = {**result, "checked_at": checked_at}
        with self._status_lock:
            self._last_checked_at = checked_at
            self._last_result = dict(result)
        return dict(result)

    def status(self) -> dict[str, object]:
        with self._status_lock:
            last_result = dict(self._last_result)
            last_checked_at = self._last_checked_at
            compaction_active = self._compaction_active
            active_database_activities = self._active_database_activities
        thread = self._thread
        return {
            "enabled": True,
            "threshold_bytes": self.min_free_bytes,
            "interval_seconds": self.interval_seconds,
            "running": bool(thread and thread.is_alive()),
            "compaction_active": compaction_active,
            "active_database_activities": active_database_activities,
            "last_checked_at": last_checked_at,
            "last_result": last_result,
        }
