from __future__ import annotations

from fastapi import Depends, Header, Response

from tme3bot.api.schemas import SafelinkJobRequest
from tme3bot.domain.models import DomainError


def register_safelink(app, context, *, current_actor, job_dict) -> None:
    @app.post("/api/v1/safelink/jobs", status_code=202)
    def submit_safelink_job(
        body: SafelinkJobRequest,
        response: Response,
        actor=Depends(current_actor),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        operations = context.operation_service
        if operations is None:
            raise DomainError("OPERATIONS_UNAVAILABLE", "Antrean job background belum tersedia.", status_code=503)
        operation, _ = operations.submit(
            actor,
            kind="job.submit",
            target={"profile": actor.profile},
            input_data={"job_kind": "safelink_resolve", "payload": {"url": body.url}},
            idempotency_key=idempotency_key,
        )
        job = context.control_plane.jobs.get(str(operation.job_id or ""))
        if job is None:
            raise DomainError("JOB_NOT_FOUND", "Job resolver tidak ditemukan setelah diterima.", status_code=500)
        status_url = f"/api/v1/jobs/{job.id}"
        response.headers["Location"] = status_url
        response.headers["X-Operation-ID"] = operation.id
        return {**job_dict(job), "operation_id": operation.id, "status_url": status_url}

    @app.post("/api/v1/safelink/jobs/{job_id}/cancel", status_code=202)
    def cancel_safelink_job(
        job_id: str,
        actor=Depends(current_actor),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        job = context.control_plane.jobs.get(job_id)
        if job is None or job.kind != "safelink_resolve":
            raise DomainError("JOB_NOT_FOUND", "Job resolver tidak ditemukan.", status_code=404)
        context.control_plane.require_profile(actor, job.profile)
        operations = context.operation_service
        store = getattr(operations, "store", None)
        operation = store.get_by_job_id(job.id) if callable(getattr(store, "get_by_job_id", None)) else None
        if operation is None or operations is None:
            raise DomainError("OPERATION_NOT_FOUND", "Operation resolver tidak tersedia untuk pembatalan.", status_code=409)
        operations.cancel(actor, operation.id, idempotency_key)
        return job_dict(context.control_plane.jobs.get(job.id) or job)

    @app.post("/api/v1/safelink/jobs/{job_id}/retry", status_code=202)
    def retry_safelink_job(
        job_id: str,
        response: Response,
        actor=Depends(current_actor),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        job = context.control_plane.jobs.get(job_id)
        if job is None or job.kind != "safelink_resolve":
            raise DomainError("JOB_NOT_FOUND", "Job resolver tidak ditemukan.", status_code=404)
        context.control_plane.require_profile(actor, job.profile)
        operations = context.operation_service
        store = getattr(operations, "store", None)
        operation = store.get_by_job_id(job.id) if callable(getattr(store, "get_by_job_id", None)) else None
        if operation is None or operations is None:
            raise DomainError("OPERATION_NOT_FOUND", "Operation resolver tidak tersedia untuk retry.", status_code=409)
        retried, _ = operations.retry(actor, operation.id, idempotency_key)
        response.headers["X-Operation-ID"] = retried.id
        return job_dict(context.control_plane.jobs.get(job.id) or job)
