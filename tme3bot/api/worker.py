from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tme3bot.api.schemas import WorkerJobRequest
from tme3bot.domain.models import DomainError

LOGGER = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


@dataclass
class WorkerContext:
    config: Any
    executor: Any


def create_worker_app(context: WorkerContext) -> FastAPI:
    app = FastAPI(
        title="tme3bot Worker API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return _error(request, exc.code, exc.message, exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        LOGGER.exception("Worker API failed")
        return _error(request, "INTERNAL_ERROR", "Worker gagal memproses request.", 500)

    def authorize(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        token = credentials.credentials if credentials is not None else ""
        if not context.config.worker_api_token or token != context.config.worker_api_token:
            raise DomainError(
                "WORKER_UNAUTHORIZED", "Worker token tidak valid.", status_code=401
            )

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "role": "worker"}

    @app.get("/internal/v1/capabilities", dependencies=[Depends(authorize)])
    def capabilities():
        return context.executor.capabilities()

    @app.get("/internal/v1/workspace/tree", dependencies=[Depends(authorize)])
    def workspace_tree(path: str = Query("/workspace", min_length=1, max_length=4096)):
        return context.executor.workspace_tree(path)

    @app.post("/internal/v1/jobs", dependencies=[Depends(authorize)])
    def submit_job(body: WorkerJobRequest):
        payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        if not payload.get("execution"):
            payload.pop("execution", None)
        return {"position": context.executor.enqueue(payload), "job_id": body.job_id}

    @app.post(
        "/internal/v1/jobs/{job_id}/cancel", dependencies=[Depends(authorize)]
    )
    def cancel_job(job_id: str):
        return {"cancelled": context.executor.cancel(job_id)}

    @app.get(
        "/internal/v1/jobs/{job_id}/log-snapshot",
        dependencies=[Depends(authorize)],
    )
    def job_log_snapshot(job_id: str):
        snapshot = context.executor.job_log_snapshot(job_id)
        if snapshot is None:
            raise DomainError(
                "JOB_LOG_NOT_ACTIVE",
                "Snapshot log aktif tidak ditemukan.",
                status_code=404,
            )
        return {"log": snapshot}

    return app


def _error(
    request: Request, code: str, message: str, status_code: int
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": {},
                "request_id": getattr(request.state, "request_id", ""),
            }
        },
    )
