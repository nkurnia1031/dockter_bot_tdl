from __future__ import annotations

from fastapi import Depends, Header, Query, Response

from tme3bot.api.schemas import OperationResponse, TdlAccessVerificationRequest
from tme3bot.domain.models import DomainError


def register_tdl_access(app, context, *, current_actor, require_internal) -> None:
    @app.get("/api/v1/tdl-access/verification")
    def get_tdl_access_verification(
        purpose: str = Query(..., pattern="^(tts|storage)$"),
        worker: str = Query(..., min_length=1, max_length=48),
        actor=Depends(current_actor),
    ):
        del actor
        return context.control_plane.tdl_access_verification_status(worker, purpose)

    @app.post(
        "/api/v1/tdl-access/verification",
        status_code=202,
        response_model=OperationResponse,
    )
    def submit_tdl_access_verification(
        body: TdlAccessVerificationRequest,
        response: Response,
        actor=Depends(current_actor),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        operations = context.operation_service
        if operations is None:
            raise DomainError(
                "OPERATIONS_UNAVAILABLE",
                "Antrean operation belum tersedia pada backend ini.",
                status_code=503,
            )
        operation, _ = operations.submit(
            actor,
            kind="job.submit",
            target={"profile": actor.profile, "worker": body.worker},
            input_data={"job_kind": "tdl_access_verify", "payload": {"purpose": body.purpose}},
            idempotency_key=idempotency_key,
        )
        status_url = f"/api/v1/operations/{operation.id}"
        response.headers["Location"] = status_url
        return operation.to_public(status_url=status_url)

    @app.get(
        "/internal/v1/tdl-access/jobs/{job_id}/target",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def get_tdl_access_target(
        job_id: str,
        worker: str = Query(..., min_length=1, max_length=48),
    ):
        job = context.control_plane.jobs.get(job_id)
        if job is None or job.kind != "tdl_access_verify":
            raise DomainError("TDL_ACCESS_JOB_NOT_FOUND", "Job verifikasi TDL tidak ditemukan.", status_code=404)
        if worker.strip().lower() != job.worker.lower():
            raise DomainError("JOB_WORKER_MISMATCH", "Worker bukan pemilik job verifikasi TDL.", status_code=403)
        if job.status.terminal:
            raise DomainError("TDL_ACCESS_JOB_TERMINAL", "Job verifikasi TDL sudah selesai.", status_code=409)
        target = context.control_plane.private_job_value(job.id, "tdl_access_target")
        command = context.control_plane.jobs.command_payload(job.id)
        payload = command.get("payload") if isinstance(command, dict) else None
        purpose = str(payload.get("purpose") or "") if isinstance(payload, dict) else ""
        if not target or purpose not in {"tts", "storage"}:
            raise DomainError("TDL_ACCESS_TARGET_UNAVAILABLE", "Tujuan privat verifikasi TDL tidak tersedia.", status_code=503)
        return {"purpose": purpose, "target": target}
