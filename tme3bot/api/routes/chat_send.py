from __future__ import annotations

from fastapi import Depends, Header, Request, Response

from tme3bot.api.schemas import ChatSendJobRequest
from tme3bot.domain.models import DomainError
from tme3bot.chat_send import safe_chat_send_retry_paths


def register_chat_send(app, context, *, current_actor, job_dict) -> None:
    @app.post("/api/v1/chat-send/jobs", status_code=202)
    def submit_chat_send(
        body: ChatSendJobRequest,
        request: Request,
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
            target={"worker": body.worker},
            input_data={
                "job_kind": "chat_send",
                "payload": {
                    "chat_ref": body.chat_ref,
                    "folders": body.folders,
                    "profiles": body.profiles,
                    "transfer_mode": body.transfer_mode,
                    "move_confirmed": body.move_confirmed,
                },
            },
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
            request_route=getattr(request.scope.get("route"), "path", ""),
        )
        request.state.activity_operation_id = operation.id
        job = context.control_plane.jobs.get(str(operation.job_id or ""))
        if job is None:
            raise DomainError("JOB_NOT_FOUND", "Job Kirim ke Chat tidak ditemukan setelah diterima.", status_code=500)
        status_url = f"/api/v1/jobs/{job.id}"
        response.headers["Location"] = status_url
        response.headers["X-Operation-ID"] = operation.id
        return {**job_dict(job), "operation_id": operation.id, "status_url": status_url}

    @app.post("/api/v1/chat-send/jobs/{job_id}/retry", status_code=202)
    def retry_chat_send(
        job_id: str,
        request: Request,
        response: Response,
        actor=Depends(current_actor),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        job = context.control_plane.jobs.get(job_id)
        if job is None or job.kind != "chat_send":
            raise DomainError("CHAT_SEND_JOB_NOT_FOUND", "Job Kirim ke Chat tidak ditemukan.", status_code=404)
        context.control_plane.require_profile(actor, job.profile)
        if not job.status.terminal:
            raise DomainError("CHAT_SEND_JOB_NOT_TERMINAL", "Job Kirim ke Chat masih aktif.", status_code=409)
        retry_paths = safe_chat_send_retry_paths(job)
        if not retry_paths:
            raise DomainError(
                "CHAT_SEND_RETRY_UNAVAILABLE",
                "Tidak ada file yang dipastikan gagal sebelum terkirim. File ambigu tidak diulang otomatis.",
                status_code=409,
            )
        payload = job.payload if isinstance(job.payload, dict) else {}
        operations = context.operation_service
        if operations is None:
            raise DomainError("OPERATIONS_UNAVAILABLE", "Antrean job background belum tersedia.", status_code=503)
        operation, _ = operations.submit(
            actor,
            kind="job.submit",
            target={"worker": job.worker},
            input_data={
                "job_kind": "chat_send",
                "payload": {
                    "chat_ref": payload.get("chat_ref"),
                    "folders": payload.get("folders"),
                    "profiles": payload.get("profiles"),
                    "transfer_mode": payload.get("transfer_mode", "copy"),
                    "move_confirmed": payload.get("move_confirmed") is True,
                    "retry_paths": retry_paths,
                },
            },
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
            request_route=getattr(request.scope.get("route"), "path", ""),
        )
        request.state.activity_operation_id = operation.id
        retried_job = context.control_plane.jobs.get(str(operation.job_id or ""))
        if retried_job is None:
            raise DomainError("JOB_NOT_FOUND", "Job Retry Kirim ke Chat tidak ditemukan setelah diterima.", status_code=500)
        status_url = f"/api/v1/jobs/{retried_job.id}"
        response.headers["Location"] = status_url
        response.headers["X-Operation-ID"] = operation.id
        return {**job_dict(retried_job), "operation_id": operation.id, "status_url": status_url}
