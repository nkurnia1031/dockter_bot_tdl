from __future__ import annotations

import hmac
import re
from datetime import datetime, timezone
from typing import Any

from tme3bot.domain.models import DomainError, JobStatus
from tme3bot.application.worker_health import probe_worker_health
from tme3bot.worker.supervisor_auth import derive_supervisor_token


_FAILURE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_ACTIVE_STATUSES = (
    JobStatus.QUEUED.value,
    JobStatus.DISPATCHED.value,
    JobStatus.RUNNING.value,
    JobStatus.PAUSED.value,
)


def _parse_time(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


class WorkerRestartCoordinator:
    """Authorizes fixed-target host restarts and terminalizes interrupted jobs."""

    def __init__(
        self,
        store,
        registry,
        health_monitor,
        jobs,
        control_plane,
        *,
        dispatcher=None,
        supervisor_max_age_seconds: int = 45,
        clock=None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.health_monitor = health_monitor
        self.jobs = jobs
        self.control_plane = control_plane
        self.dispatcher = dispatcher
        self.supervisor_max_age_seconds = max(10, int(supervisor_max_age_seconds))
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _fresh_probe(self, worker: str) -> dict[str, Any]:
        probe = getattr(self.health_monitor, "probe_worker", None)
        if callable(probe):
            try:
                result = probe(worker)
            except Exception:
                result = None
            if isinstance(result, dict):
                return result
        checker = getattr(self.dispatcher, "check_worker_fast", None)
        if callable(checker):
            return probe_worker_health(checker, worker)
        return {
            "worker": worker,
            "status": "unknown",
            "healthy": False,
            "health_probe_attempts": 0,
            "health_probe_failures": 0,
            "restart_probe_confirmed": False,
        }

    def _supervisor_online(self, worker: str) -> tuple[bool, str | None]:
        seen_at = self.store.supervisor_seen_at(worker)
        seen = _parse_time(seen_at)
        if seen is None:
            return False, seen_at
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        age = max(0.0, (now - seen).total_seconds())
        return age <= self.supervisor_max_age_seconds, seen_at

    def worker_status(self, worker: str) -> dict[str, Any]:
        """Return the public supervisor/restart summary for a worker."""
        name = str(worker or "").strip().lower()
        supervisor_online, supervisor_seen_at = self._supervisor_online(name)
        operation = self.store.active(name)
        return {
            "supervisor_online": supervisor_online,
            "supervisor_seen_at": supervisor_seen_at,
            "restart_operation_id": str(operation.get("id")) if operation else None,
            "restart_status": str(operation.get("status")) if operation else None,
            "restart_active_job_count": (
                int(operation.get("active_job_count") or 0) if operation else 0
            ),
        }

    def _active_job_ids(self, worker: str) -> list[str]:
        found: list[str] = []
        offset = 0
        while True:
            batch = self.jobs.list(
                worker=worker,
                statuses=_ACTIVE_STATUSES,
                archived=False,
                offset=offset,
                limit=200,
            )
            batch = [job for job in batch if not job.status.terminal]
            found.extend(str(job.id) for job in batch)
            if len(batch) < 200:
                break
            offset += 200
        return list(dict.fromkeys(found))

    def preflight(self, worker: str) -> dict[str, Any]:
        name = str(worker or "").strip().lower()
        record = self.registry.get(name)
        if record is None:
            raise DomainError("WORKER_NOT_FOUND", "Worker tidak terdaftar.", status_code=404)
        if not bool(record.get("enabled", True)):
            raise DomainError("WORKER_DISABLED", "Worker dinonaktifkan; restart melalui UI tidak tersedia.", status_code=409)
        health = self._fresh_probe(name)
        supervisor_online, supervisor_seen_at = self._supervisor_online(name)
        confirmed = (
            health.get("status") == "offline"
            and health.get("healthy") is False
            and health.get("restart_probe_confirmed") is True
            and int(health.get("health_probe_failures") or 0) >= 2
        )
        if health.get("status") == "ready" and health.get("healthy") is True:
            reason = "WORKER_REACHABLE"
        elif not confirmed:
            reason = "WORKER_HEALTH_UNCONFIRMED"
        elif not supervisor_online:
            reason = "SUPERVISOR_OFFLINE"
        else:
            reason = ""
        return {
            "worker": name,
            "health_status": str(health.get("status") or "unknown"),
            "health_probe_attempts": int(health.get("health_probe_attempts") or 0),
            "health_probe_failures": int(health.get("health_probe_failures") or 0),
            "restart_probe_confirmed": confirmed,
            "supervisor_online": supervisor_online,
            "supervisor_seen_at": supervisor_seen_at,
            "active_job_count": len(self._active_job_ids(name)),
            "restart_available": bool(confirmed and supervisor_online),
            "reason_code": reason,
        }

    def request_restart(self, worker: str, *, actor_user_id: int) -> dict[str, Any]:
        name = str(worker or "").strip().lower()
        preflight = self.preflight(name)
        if not preflight["restart_probe_confirmed"]:
            raise DomainError(
                str(preflight["reason_code"] or "WORKER_REACHABLE"),
                "Restart ditolak karena dua probe baru belum memastikan worker tidak dapat dijangkau.",
                status_code=409,
                details={"worker": name, "health_status": preflight["health_status"]},
            )
        if not preflight["supervisor_online"]:
            raise DomainError(
                "SUPERVISOR_OFFLINE",
                "Supervisor host tidak terhubung; worker tidak direstart.",
                status_code=503,
                details={"worker": name},
            )
        operation, created = self.store.create(
            name,
            int(actor_user_id),
            self._active_job_ids(name),
        )
        operation = dict(operation)
        operation.pop("actor_user_id", None)
        operation.pop("active_job_ids", None)
        operation["created"] = created
        return operation

    def _authorized_worker(self, worker: str, token: str) -> str:
        name = str(worker or "").strip().lower()
        record = self.registry.get(name)
        worker_token = str(record.get("token") or "") if isinstance(record, dict) else ""
        expected = derive_supervisor_token(name, worker_token)
        if not expected or not token or not hmac.compare_digest(expected, str(token)):
            raise DomainError("SUPERVISOR_UNAUTHORIZED", "Kredensial supervisor tidak valid.", status_code=401)
        return name

    def poll_supervisor(self, worker: str, token: str) -> dict[str, Any]:
        name = self._authorized_worker(worker, token)
        operation = self.store.claim_next(name)
        command = None
        if operation is not None:
            command = {
                "operation_id": operation["id"],
                "idempotency_key": operation["id"],
                "action": "restart_worker",
            }
        return {"worker": name, "command": command}

    def report_supervisor_result(
        self,
        worker: str,
        token: str,
        operation_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        name = self._authorized_worker(worker, token)
        operation = self.store.get(operation_id, worker=name)
        if operation is None:
            raise DomainError("WORKER_RESTART_NOT_FOUND", "Operasi restart tidak ditemukan.", status_code=404)
        if operation["status"] in {"succeeded", "failed"}:
            return operation
        if operation["status"] != "restarting":
            raise DomainError(
                "WORKER_RESTART_NOT_CLAIMED",
                "Supervisor belum mengambil perintah restart ini.",
                status_code=409,
            )
        if not isinstance(payload, dict) or set(payload) - {
            "container_stopped", "container_running", "restart_succeeded", "failure_code"
        }:
            raise DomainError("WORKER_RESTART_RESULT_INVALID", "Hasil restart tidak valid.", status_code=422)
        for field in ("container_stopped", "container_running", "restart_succeeded"):
            if type(payload.get(field)) is not bool:
                raise DomainError("WORKER_RESTART_RESULT_INVALID", "Status Docker supervisor tidak valid.", status_code=422)
        failure_code = str(payload.get("failure_code") or "").strip().upper()
        if failure_code and not _FAILURE_CODE_RE.fullmatch(failure_code):
            raise DomainError("WORKER_RESTART_RESULT_INVALID", "Kode hasil restart tidak valid.", status_code=422)

        cancelled_job_ids: list[str] = []
        if payload["container_stopped"]:
            cancel = getattr(self.control_plane, "cancel_worker_jobs_after_restart", None)
            if callable(cancel):
                cancelled_job_ids = cancel(
                    name,
                    operation["active_job_ids"],
                    operation_id=str(operation_id),
                )
        success = payload["restart_succeeded"] and payload["container_running"]
        safe_result = {
            "container_stopped": payload["container_stopped"],
            "container_running": payload["container_running"],
            "restart_succeeded": payload["restart_succeeded"],
            "failure_code": failure_code,
            "cancelled_job_ids": list(cancelled_job_ids),
        }
        finished = self.store.finish(
            operation_id,
            name,
            status="succeeded" if success else "failed",
            result=safe_result,
        )
        if finished is None:
            raise DomainError("WORKER_RESTART_NOT_FOUND", "Operasi restart tidak ditemukan.", status_code=404)
        wake = getattr(self.control_plane, "wake_scheduler", None)
        if callable(wake):
            wake()
        return finished

    def operation(self, worker: str, operation_id: str) -> dict[str, Any]:
        name = str(worker or "").strip().lower()
        result = self.store.get(operation_id, worker=name)
        if result is None:
            raise DomainError("WORKER_RESTART_NOT_FOUND", "Operasi restart tidak ditemukan.", status_code=404)
        result.pop("actor_user_id", None)
        result.pop("active_job_ids", None)
        return result
