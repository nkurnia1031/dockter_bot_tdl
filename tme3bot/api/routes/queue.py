from __future__ import annotations

import re
from typing import Any

from fastapi import Body, Depends, HTTPException


_COMMAND_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_CLAIM = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def register_queue(app, context, *, require_internal) -> None:
    @app.post(
        "/internal/v1/queue/commands/{command_id}/advance",
        dependencies=[Depends(require_internal)],
    )
    def advance_queue_command(command_id: str, payload: dict[str, Any] = Body(...)):
        service = getattr(context, "queue_command_service", None)
        if service is None:
            raise HTTPException(status_code=503, detail="Queue command service is unavailable.")
        if not _COMMAND_ID.fullmatch(command_id):
            raise HTTPException(status_code=422, detail="Command ID is invalid.")
        claim = payload.get("lease_claim")
        if not isinstance(claim, str) or not _CLAIM.fullmatch(claim):
            raise HTTPException(status_code=422, detail="Queue lease claim is invalid.")
        return service.advance(command_id, claim, context.operation_service)

    @app.get("/healthz/queue")
    def queue_readiness():
        publisher = getattr(context, "queue_publisher", None)
        if publisher is None:
            return {"status": "disabled", "enabled": False, "ready": True}
        result = publisher.health_snapshot()
        if not result.get("ready"):
            raise HTTPException(status_code=503, detail=result)
        return {"status": result.get("status", "ready"), **result}
