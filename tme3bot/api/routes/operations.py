from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, Query, Request, Response

from tme3bot.api.schemas import (
    OperationListResponse,
    OperationResponse,
    OperationSubmitRequest,
    OperationVisibilityRequest,
)
from tme3bot.domain.models import DomainError


def register_operations(
    app,
    operations,
    *,
    current_actor,
    profile_sync_store=None,
    retry_guard=None,
) -> None:
    def _require_operations():
        if operations is None:
            raise DomainError(
                "OPERATIONS_UNAVAILABLE",
                "Operation API belum tersedia pada backend ini.",
                status_code=503,
            )
        return operations

    def _public(operation, *, status_url: str | None = None) -> dict[str, Any]:
        return operation.to_public(status_url=status_url)

    @app.get("/api/v1/capabilities")
    def api_capabilities():
        service = _require_operations()
        return {
            "capabilities": ["operations_v1"],
            "operations": {"version": 1, "supported_kinds": service.supported_kinds()},
        }

    @app.post("/api/v1/operations", status_code=202, response_model=OperationResponse)
    def submit_operation(
        body: OperationSubmitRequest,
        request: Request,
        response: Response,
        actor=Depends(current_actor),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        service = _require_operations()
        operation, _ = service.submit(
            actor, kind=body.kind, target=body.target, input_data=body.input,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
            request_route=getattr(request.scope.get("route"), "path", ""),
        )
        if operation.kind == "profile.sync" and profile_sync_store is not None:
            profile = str(operation.target.get("profile") or "")
            worker = str(operation.target.get("worker") or "")
            revision = operation.target.get("desired_revision")
            details = {"desired_revision": revision} if type(revision) is int else None
            profile_sync_store.append_profile_sync_log(
                profile=profile,
                worker=worker,
                run_id=operation.id,
                revision=revision if type(revision) is int else None,
                phase="queued",
                status="queued",
                code="PROFILE_SYNC_QUEUED",
                details=details,
            )
            profile_sync_store.append_profile_sync_operation_event(
                operation_id=operation.id,
                profile=profile,
                worker=worker,
                run_id=operation.id,
                revision=revision if type(revision) is int else None,
                phase="queued",
                status="queued",
                code="PROFILE_SYNC_QUEUED",
                details=details,
            )
        request.state.activity_operation_id = operation.id
        status_url = f"/api/v1/operations/{operation.id}"
        response.headers["Location"] = status_url
        return _public(operation, status_url=status_url)

    @app.get("/api/v1/operations", response_model=OperationListResponse)
    def list_operations(
        status: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
        actor=Depends(current_actor),
    ):
        service = _require_operations()
        items, next_cursor = service.list(actor, status=status, cursor=cursor, limit=limit)
        return {"items": [_public(item) for item in items], "next_cursor": next_cursor}

    @app.get("/api/v1/operations/{operation_id}", response_model=OperationResponse)
    def get_operation(operation_id: str, actor=Depends(current_actor)):
        return _public(_require_operations().get(actor, operation_id))

    @app.get("/api/v1/operations/{operation_id}/events")
    def get_operation_events(
        operation_id: str,
        after_id: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        actor=Depends(current_actor),
    ):
        operation = _require_operations().get(actor, operation_id)
        if operation.kind != "profile.sync" or profile_sync_store is None:
            raise DomainError("OPERATION_EVENTS_UNAVAILABLE", "Riwayat event operasi ini tidak tersedia.", status_code=404)
        return profile_sync_store.profile_sync_operation_events(
            operation.id, after_id=after_id, limit=limit
        )

    @app.post("/api/v1/operations/{operation_id}/cancel", status_code=202, response_model=OperationResponse)
    def cancel_operation(
        operation_id: str,
        actor=Depends(current_actor),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        service = _require_operations()
        current = service.get(actor, operation_id)
        if current.kind == "profile.local_delete" and not current.status.terminal:
            raise DomainError(
                "PROFILE_DELETE_NOT_CANCELLABLE",
                "Penghapusan profil yang sudah tercatat tidak dapat dibatalkan dengan aman.",
                status_code=409,
            )
        operation, _ = service.cancel(actor, operation_id, idempotency_key)
        return _public(operation, status_url=f"/api/v1/operations/{operation_id}")

    @app.post("/api/v1/operations/{operation_id}/retry", status_code=202, response_model=OperationResponse)
    def retry_operation(
        operation_id: str,
        actor=Depends(current_actor),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        service = _require_operations()
        current = service.get(actor, operation_id)
        if callable(retry_guard):
            retry_guard(current)
        operation, _ = service.retry(actor, operation_id, idempotency_key)
        return _public(operation, status_url=f"/api/v1/operations/{operation_id}")

    @app.put("/api/v1/operations/{operation_id}/visibility", response_model=OperationResponse)
    def set_operation_visibility(
        operation_id: str,
        body: OperationVisibilityRequest,
        actor=Depends(current_actor),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        operation, _ = _require_operations().set_visibility(
            actor, operation_id, body.dismissed, idempotency_key
        )
        return _public(operation)
