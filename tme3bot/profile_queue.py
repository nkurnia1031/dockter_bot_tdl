from __future__ import annotations

import logging
import queue
import threading
import itertools
from dataclasses import dataclass
from typing import Callable, Generic, Hashable, TypeVar

LOGGER = logging.getLogger(__name__)

KeyT = TypeVar("KeyT", bound=Hashable)
JobT = TypeVar("JobT")
JobHandler = Callable[[JobT, queue.Queue], None]
ErrorHandler = Callable[[KeyT, JobT, Exception], None]


@dataclass
class _WorkerSlot(Generic[JobT]):
    jobs: queue.PriorityQueue
    thread: threading.Thread | None = None


class SerialPerKeyQueue(Generic[KeyT, JobT]):
    """Runs different keys concurrently while keeping each key serial."""

    def __init__(
        self,
        handler: JobHandler[JobT],
        *,
        error_handler: ErrorHandler[KeyT, JobT] | None = None,
        thread_name_prefix: str = "key-worker",
    ) -> None:
        self._handler = handler
        self._error_handler = error_handler
        self._thread_name_prefix = thread_name_prefix
        self._lock = threading.RLock()
        self._slots: dict[KeyT, _WorkerSlot[JobT]] = {}
        self._started = False
        self._sequence = itertools.count()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            for key, slot in self._slots.items():
                self._start_slot(key, slot)

    def enqueue(self, key: KeyT, job: JobT, *, priority: int = 100) -> int:
        with self._lock:
            slot = self._slots.get(key)
            if slot is None:
                slot = _WorkerSlot(jobs=queue.PriorityQueue())
                self._slots[key] = slot
            slot.jobs.put((int(priority), next(self._sequence), job))
            position = max(1, slot.jobs.qsize())
            if self._started:
                self._start_slot(key, slot)
            return position

    def queue_size(self, key: KeyT) -> int:
        with self._lock:
            slot = self._slots.get(key)
            return slot.jobs.qsize() if slot is not None else 0

    def _start_slot(self, key: KeyT, slot: _WorkerSlot[JobT]) -> None:
        if slot.thread is not None and slot.thread.is_alive():
            return
        slot.thread = threading.Thread(
            target=self._run_slot,
            args=(key, slot.jobs),
            daemon=True,
            name=f"{self._thread_name_prefix}-{key}",
        )
        slot.thread.start()

    def _run_slot(self, key: KeyT, jobs: queue.PriorityQueue) -> None:
        while True:
            _priority, _sequence, job = jobs.get()
            try:
                self._handler(job, jobs)
            except Exception as exc:  # pragma: no cover - caller-specific guard
                if self._error_handler is None:
                    LOGGER.exception("Unhandled keyed queue failure for %s", key)
                else:
                    try:
                        self._error_handler(key, job, exc)
                    except Exception:  # pragma: no cover - defensive callback guard
                        LOGGER.exception("Keyed queue error handler failed for %s", key)
            finally:
                jobs.task_done()
