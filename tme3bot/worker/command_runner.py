"""Admit durable worker commands into the existing resource-aware queue."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from tme3bot.domain.models import DomainError
from tme3bot.worker.command_store import WorkerCommandStore


LOGGER = logging.getLogger(__name__)


class WorkerCommandRunner:
    def __init__(self, store: WorkerCommandStore, executor: Any) -> None:
        self.store = store
        self.executor = executor
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._operation_handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def register_operation_handler(
        self, kind: str, handler: Callable[[dict[str, Any]], Any]
    ) -> None:
        self._operation_handlers[str(kind)] = handler

    @property
    def ready(self) -> bool:
        return self._ready.is_set() and self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.ready:
            return
        self.store.recover_startup()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="worker-command-runner",
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, timeout))
        self._ready.clear()

    def accept(self, envelope: dict[str, Any]) -> dict[str, Any]:
        snapshot, replayed = self.store.accept(envelope)
        return {**snapshot, "replayed": replayed}

    def status(self, command_id: str) -> dict[str, Any] | None:
        return self.store.get(command_id)

    def _run(self) -> None:
        self._ready.set()
        while not self._stop.is_set():
            try:
                claimed = self.store.claim_next()
                if claimed is None:
                    self._stop.wait(0.2)
                    continue
                command_id, envelope = claimed
                if isinstance(envelope.get("job"), dict):
                    self._queue_job(command_id, envelope)
                else:
                    self._run_operation(command_id, envelope)
            except Exception as exc:
                LOGGER.warning(
                    "Durable worker command runner iteration failed (%s)",
                    type(exc).__name__,
                )
                self._stop.wait(0.5)
        self._ready.clear()

    def _queue_job(self, command_id: str, envelope: dict[str, Any]) -> None:
        job = dict(envelope["job"])
        job_id = str(envelope.get("job_id") or "")
        command = {
            "job_id": job_id,
            "kind": str(job.get("kind") or ""),
            "profile": str(job.get("profile") or ""),
            "actor_user_id": job.get("actor_user_id"),
            "worker": str(job.get("worker") or ""),
            "payload": dict(job.get("payload") or {}),
            "execution": dict(envelope.get("execution_plan") or {}),
            "event_sequence_start": envelope.get("event_sequence_start"),
            "command_id": command_id,
            "operation_id": str(envelope.get("operation_id") or ""),
            "attempt": int(envelope.get("attempt") or 1),
            "dispatch_token": str(envelope.get("dispatch_token") or ""),
            "profile_revision": int(envelope.get("profile_revision") or 0),
            "settings_version": int(envelope.get("settings_version") or 0),
        }
        admission_lock = getattr(self.executor, "_durable_admission_lock", None)
        guard = admission_lock if admission_lock is not None else threading.RLock()
        with guard:
            current = self.store.get(command_id)
            if current is None or current["status"] != "claimed":
                return
            try:
                self.executor.enqueue(command)
            except Exception as exc:
                self.store.release_claim(command_id)
                LOGGER.warning(
                    "Durable command admission failed (%s)", type(exc).__name__
                )
                return
            # _run may start immediately and advance the row to running. The
            # conditional update never regresses that status back to queued.
            self.store.set_status(
                command_id,
                "queued",
                phase="queue",
                only_from=("claimed",),
            )

    def _run_operation(self, command_id: str, envelope: dict[str, Any]) -> None:
        operation = envelope.get("operation")
        operation = operation if isinstance(operation, dict) else {}
        kind = str(operation.get("kind") or operation.get("type") or "")
        handler = self._operation_handlers.get(kind)
        if handler is None:
            self.store.finish(
                command_id,
                "failed",
                ack={"error_code": "UNSUPPORTED_WORKER_OPERATION"},
            )
            return
        self.store.mark_running(command_id)
        try:
            handler(envelope)
        except Exception as exc:
            LOGGER.warning(
                "Durable worker operation failed (%s)", type(exc).__name__
            )
            self.store.finish(
                command_id,
                "failed",
                ack={"error_code": "WORKER_OPERATION_FAILED"},
            )
            return
        self.store.finish(command_id, "succeeded", ack={"completed": True})


__all__ = ["WorkerCommandRunner"]
