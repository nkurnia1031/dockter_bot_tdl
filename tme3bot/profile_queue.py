from __future__ import annotations

import logging
import queue
import threading
import itertools
import heapq
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


class ResourceAwareQueue(Generic[JobT]):
    """Run jobs concurrently when their exclusive resources do not overlap.

    A job may reserve more than one resource, for example a logical kind lane
    and a TDL session lane.  The scheduler scans the pending heap instead of
    blocking behind its first item, so an export can run while a download is
    active while two exports remain serial.
    """

    def __init__(
        self,
        handler: Callable[[JobT, set[str]], None],
        *,
        error_handler: Callable[[JobT, Exception], None] | None = None,
        thread_name_prefix: str = "resource-worker",
    ) -> None:
        self._handler = handler
        self._error_handler = error_handler
        self._thread_name_prefix = thread_name_prefix
        self._condition = threading.Condition(threading.RLock())
        self._pending: list[tuple[int, int, JobT, frozenset[str]]] = []
        self._active_keys: set[str] = set()
        self._active_jobs: set[str] = set()
        self._active_resource_keys: dict[str, set[str]] = {}
        self._sequence = itertools.count()
        self._scheduler: threading.Thread | None = None
        self._started = False
        self._stopped = False

    def start(self) -> None:
        with self._condition:
            if self._started:
                return
            self._started = True
            self._scheduler = threading.Thread(
                target=self._dispatch_loop,
                daemon=True,
                name=f"{self._thread_name_prefix}-scheduler",
            )
            self._scheduler.start()
            self._condition.notify_all()

    def enqueue(
        self,
        resources: set[str] | frozenset[str] | list[str] | tuple[str, ...],
        job: JobT,
        *,
        priority: int = 100,
        job_id: str | None = None,
    ) -> int:
        keys = frozenset(str(item) for item in resources if str(item))
        if not keys:
            raise ValueError("ResourceAwareQueue memerlukan minimal satu resource.")
        with self._condition:
            sequence = next(self._sequence)
            heapq.heappush(self._pending, (int(priority), sequence, job, keys))
            position = self._position_for(keys, sequence)
            if job_id:
                self._active_jobs.discard(job_id)
            self._condition.notify_all()
            return position

    def queue_size(self, resources: set[str] | str | None = None) -> int:
        with self._condition:
            if resources is None:
                return len(self._pending)
            keys = {resources} if isinstance(resources, str) else set(resources)
            return sum(1 for _p, _s, _j, item_keys in self._pending if item_keys & keys)

    def active(self) -> int:
        with self._condition:
            return len(self._active_jobs)

    def cancel_pending(self, job_id: str) -> bool:
        """Remove a queued command without interrupting an active thread."""
        target = str(job_id)
        with self._condition:
            kept = []
            removed = False
            for item in self._pending:
                candidate = item[2]
                candidate_id = str(
                    getattr(candidate, "get", lambda _key, _default=None: _default)(
                        "job_id", ""
                    )
                )
                if candidate_id == target:
                    removed = True
                    continue
                kept.append(item)
            if removed:
                self._pending = kept
                heapq.heapify(self._pending)
                self._condition.notify_all()
            return removed

    def _position_for(self, keys: frozenset[str], sequence: int) -> int:
        position = 1
        for priority, item_sequence, _job, item_keys in self._pending:
            if item_sequence >= sequence:
                continue
            if item_keys & keys:
                position += 1
        if self._active_keys & keys:
            return position
        return 1

    def _dispatch_loop(self) -> None:
        while True:
            with self._condition:
                while not self._stopped and self._find_ready_index() is None:
                    self._condition.wait(timeout=1.0)
                if self._stopped:
                    return
                index = self._find_ready_index()
                if index is None:
                    continue
                priority, sequence, job, keys = self._pending.pop(index)
                heapq.heapify(self._pending)
                del priority, sequence
                job_id = str(getattr(job, "get", lambda _key, _default=None: _default)("job_id", ""))
                self._active_keys.update(keys)
                if job_id:
                    self._active_jobs.add(job_id)
                    self._active_resource_keys[job_id] = set(keys)
            threading.Thread(
                target=self._run,
                args=(job, keys, job_id),
                daemon=True,
                name=f"{self._thread_name_prefix}-{job_id[:8] or 'job'}",
            ).start()

    def _find_ready_index(self) -> int | None:
        candidates = [
            (index, item)
            for index, item in enumerate(self._pending)
            if not self._active_keys.intersection(item[3])
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda pair: (pair[1][0], pair[1][1]))[0]

    def release_resources(self, job_id: str, resources: set[str] | list[str] | tuple[str, ...]) -> bool:
        """Release a subset of an active job's resources.

        Long pipelines can change lanes without ending the worker thread.  A
        Quick Mode job releases its export session after ``json_ready`` while
        retaining its unique staging lock until cleanup.
        """
        target = str(job_id)
        requested = {str(item) for item in resources if str(item)}
        if not requested:
            return False
        with self._condition:
            owned = self._active_resource_keys.get(target)
            if owned is None:
                return False
            released = owned.intersection(requested)
            if not released:
                return False
            owned.difference_update(released)
            self._active_keys.difference_update(released)
            self._condition.notify_all()
            return True

    def _run(self, job: JobT, keys: frozenset[str], job_id: str) -> None:
        try:
            self._handler(job, set(keys))
        except Exception as exc:  # pragma: no cover - caller-specific guard
            if self._error_handler is None:
                LOGGER.exception("Unhandled resource queue failure for %s", job_id)
            else:
                try:
                    self._error_handler(job, exc)
                except Exception:  # pragma: no cover
                    LOGGER.exception("Resource queue error handler failed for %s", job_id)
        finally:
            with self._condition:
                owned = self._active_resource_keys.pop(job_id, set(keys))
                self._active_keys.difference_update(owned)
                if job_id:
                    self._active_jobs.discard(job_id)
                self._condition.notify_all()

    def stop(self) -> None:
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
