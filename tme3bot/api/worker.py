from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI, Header, Path as ApiPath, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tme3bot.api.schemas import WorkerJobRequest, WorkerRuntimeSettingsRequest
from tme3bot.domain.models import DomainError
from tme3bot.domain.worker_contract import (
    CAP_DURABLE_COMMANDS_V1,
    CAP_SAFELINK_RESOLVE,
    CAP_TTS,
    worker_contract_metadata,
)
from tme3bot.profile_provisioning import MAX_PROFILE_BUNDLE_BYTES, MAX_SESSION_ARCHIVE_BYTES

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

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, exc: RequestValidationError):
        del exc
        return _error(
            request,
            "VALIDATION_ERROR",
            "Payload runtime worker tidak valid.",
            422,
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        LOGGER.exception("Worker API failed")
        return _error(request, "INTERNAL_ERROR", "Worker gagal memproses request.", 500)

    def authorize(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        token = credentials.credentials if credentials is not None else ""
        matcher = getattr(context.executor, "worker_token_matches", None)
        valid = (
            matcher(token)
            if callable(matcher)
            else bool(context.config.worker_api_token)
            and token == context.config.worker_api_token
        )
        if not valid:
            raise DomainError(
                "WORKER_UNAUTHORIZED", "Worker token tidak valid.", status_code=401
            )

    def profile_operation(callback, code: str, message: str):
        try:
            return callback()
        except DomainError:
            raise
        except ValueError as exc:
            raise DomainError("PROFILE_SESSION_INVALID", str(exc), status_code=422) from exc
        except KeyError as exc:
            raise DomainError("PROFILE_LOGIN_NOT_FOUND", "Sesi login worker tidak ditemukan.", status_code=404) from exc
        except Exception:
            # Do not log the exception text or traceback: filesystem errors can
            # include local paths, while login errors may include private TDL output.
            LOGGER.warning("Worker profile operation failed (%s)", code)
            raise DomainError(code, message, status_code=503) from None

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "role": "worker"}

    @app.get("/internal/v1/capabilities", dependencies=[Depends(authorize)])
    def capabilities():
        details = context.executor.capabilities()
        contract = worker_contract_metadata()
        capabilities = list(contract["capabilities"])
        capabilities.append(CAP_DURABLE_COMMANDS_V1)
        if details.get("tts"):
            capabilities.append(CAP_TTS)
        if details.get("safelink_resolver"):
            capabilities.append(CAP_SAFELINK_RESOLVE)
        contract["capabilities"] = sorted(set(capabilities))
        return {**details, **contract}

    @app.get("/internal/v1/tts/health", dependencies=[Depends(authorize)])
    def tts_health():
        return context.executor.tts_health()

    @app.post("/internal/v1/tts/helpers/{slot}/recover", dependencies=[Depends(authorize)])
    def recover_tts_helper(slot: int = ApiPath(ge=1, le=3)):
        try:
            result = context.executor.recover_tts_helper(slot)
        except Exception as exc:
            status = getattr(exc, "status", None)
            code = str(getattr(exc, "code", "TTS_HELPER_UNAVAILABLE"))
            allowed = {
                "TTS_HELPER_BUSY", "TTS_HELPER_ALREADY_READY", "TTS_RECOVERY_COOLDOWN",
                "TTS_HELPER_RECOVERING", "TTS_HELPER_UNAVAILABLE", "TTS_HELPER_SLOT_INVALID",
                "TTS_RECOVERY_REJECTED",
            }
            if code not in allowed:
                code = "TTS_HELPER_UNAVAILABLE"
            details = {}
            retry_after = getattr(exc, "retry_after_seconds", None)
            if code == "TTS_RECOVERY_COOLDOWN" and isinstance(retry_after, int):
                details["retry_after_seconds"] = retry_after
            raise DomainError(
                code,
                {
                    "TTS_HELPER_BUSY": "Helper sedang memproses sintesis.",
                    "TTS_HELPER_ALREADY_READY": "Helper sudah siap.",
                    "TTS_RECOVERY_COOLDOWN": "Tunggu sebelum meminta pemulihan lagi.",
                    "TTS_HELPER_RECOVERING": "Pemulihan helper sedang berlangsung.",
                    "TTS_HELPER_SLOT_INVALID": "Slot helper tidak valid.",
                    "TTS_RECOVERY_REJECTED": "Helper menolak permintaan pemulihan.",
                }.get(code, "Helper TTS tidak dapat dihubungi."),
                status_code=int(status) if isinstance(status, int) and 400 <= status <= 599 else 503,
                details=details,
            ) from None
        return {"accepted": True, "status": str(result.get("status") or "restarting")}

    @app.post("/internal/v1/profiles/validate", dependencies=[Depends(authorize)])
    async def validate_profile_session(request: Request):
        data = await request.body()
        if len(data) > MAX_SESSION_ARCHIVE_BYTES:
            raise DomainError("PROFILE_ARCHIVE_TOO_LARGE", "ZIP sesi melebihi batas 128 MiB.", status_code=413)
        return profile_operation(
            lambda: context.executor.validate_profile_session(data),
            "PROFILE_VALIDATION_FAILED",
            "Worker tidak dapat memvalidasi sesi TDL.",
        )

    @app.post("/internal/v1/profiles/login/{operation_id}", dependencies=[Depends(authorize)])
    def start_profile_login(operation_id: str, body: dict[str, Any]):
        method = str(body.get("method") or "")
        phone = str(body.get("phone") or "")
        return profile_operation(
            lambda: context.executor.start_profile_login(operation_id, method, phone),
            "PROFILE_LOGIN_FAILED",
            "Worker tidak dapat memulai login TDL.",
        )

    @app.post("/internal/v1/profiles/login/{operation_id}/input", dependencies=[Depends(authorize)])
    def profile_login_input(operation_id: str, body: dict[str, Any]):
        return profile_operation(
            lambda: context.executor.profile_login_input(
                operation_id, str(body.get("field") or ""), str(body.get("value") or "")
            ),
            "PROFILE_LOGIN_INPUT_FAILED",
            "Worker tidak dapat menerima input login.",
        )

    @app.get("/internal/v1/profiles/login/{operation_id}", dependencies=[Depends(authorize)])
    def profile_login_state(operation_id: str):
        state = dict(profile_operation(
            lambda: context.executor.profile_login_state(operation_id),
            "PROFILE_LOGIN_STATUS_FAILED",
            "Worker tidak dapat membaca status login.",
        ))
        # The account identifier is returned separately by the validation
        # endpoint after the web flow completes, never in the login poll.
        state.pop("telegram_user_id", None)
        return state

    @app.get("/internal/v1/profiles/login/{operation_id}/bundle", dependencies=[Depends(authorize)])
    def profile_login_bundle(operation_id: str):
        state = profile_operation(
            lambda: context.executor.profile_login_state(operation_id),
            "PROFILE_LOGIN_STATUS_FAILED",
            "Worker tidak dapat membaca status login.",
        )
        path = profile_operation(
            lambda: context.executor.profile_login_bundle_path(operation_id),
            "PROFILE_LOGIN_BUNDLE_FAILED",
            "Worker tidak dapat mengambil sesi login.",
        )
        if path is None or not path.is_file():
            raise DomainError("PROFILE_LOGIN_NOT_READY", "Sesi login belum siap.", status_code=409)
        headers = {}
        if state.get("telegram_user_id") is not None:
            headers["X-Telegram-User-ID"] = str(int(state["telegram_user_id"]))
        data = profile_operation(
            path.read_bytes,
            "PROFILE_LOGIN_BUNDLE_FAILED",
            "Worker tidak dapat mengambil sesi login.",
        )
        return Response(data, media_type="application/zip", headers=headers)

    @app.delete("/internal/v1/profiles/login/{operation_id}", dependencies=[Depends(authorize)])
    def cancel_profile_login(operation_id: str):
        return {"cancelled": context.executor.cancel_profile_login(operation_id)}

    @app.put("/internal/v1/profiles/{profile}/session", dependencies=[Depends(authorize)])
    async def install_profile_bundle(
        profile: str,
        request: Request,
        telegram_user_id: int = Header(alias="X-Telegram-User-ID"),
        provisioning_id: str = Header(default="", alias="X-Provisioning-ID"),
    ):
        data = await request.body()
        if len(data) > MAX_PROFILE_BUNDLE_BYTES:
            raise DomainError("PROFILE_ARCHIVE_TOO_LARGE", "Bundle profil melebihi batas.", status_code=413)
        return profile_operation(
            lambda: context.executor.install_profile_bundle(
                profile, telegram_user_id, data, provisioning_id
            ),
            "PROFILE_INSTALL_FAILED",
            "Worker tidak dapat memasang sesi profil.",
        )

    @app.get("/internal/v1/profiles/{profile}/session", dependencies=[Depends(authorize)])
    def export_profile_bundle(profile: str):
        try:
            user_id, data = profile_operation(
                lambda: context.executor.export_profile_bundle(profile),
                "PROFILE_EXPORT_FAILED",
                "Worker tidak dapat mengekspor sesi profil.",
            )
        except DomainError as exc:
            if exc.code == "PROFILE_SESSION_INVALID":
                raise DomainError("PROFILE_SESSION_UNAVAILABLE", exc.message, status_code=409) from exc
            raise
        return Response(
            data,
            media_type="application/zip",
            headers={"X-Telegram-User-ID": str(user_id)},
        )

    @app.post("/internal/v1/profiles/{profile}/session/commit", dependencies=[Depends(authorize)])
    def commit_profile_bundle(profile: str, body: dict[str, Any]):
        return {"committed": context.executor.commit_profile_bundle(profile, str(body.get("operation_id") or ""))}

    @app.delete("/internal/v1/profiles/{profile}/session", dependencies=[Depends(authorize)])
    def rollback_profile_bundle(profile: str, operation_id: str = Query(..., min_length=1, max_length=64)):
        return {"rolled_back": context.executor.rollback_profile_bundle(profile, operation_id)}

    @app.get("/internal/v1/runtime-settings", dependencies=[Depends(authorize)])
    def runtime_settings():
        return context.executor.worker_settings()

    @app.put("/internal/v1/runtime-settings", dependencies=[Depends(authorize)])
    def update_runtime_settings(body: WorkerRuntimeSettingsRequest):
        values = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
        return context.executor.update_worker_settings(values)

    @app.get(
        "/internal/v1/tts/artifacts/{job_id}/{artifact_ref}",
        dependencies=[Depends(authorize)],
        include_in_schema=False,
    )
    def tts_artifact(job_id: str, artifact_ref: str):
        path = context.executor.tts_artifact_path(job_id, artifact_ref)
        if path is None:
            raise DomainError("TTS_ARTIFACT_NOT_FOUND", "Audio artifact tidak ditemukan.", status_code=404)
        return FileResponse(path, media_type="audio/mpeg", filename=path.name)

    @app.get("/internal/v1/workspace/tree", dependencies=[Depends(authorize)])
    def workspace_tree(path: str = Query("/workspace", min_length=1, max_length=4096)):
        return context.executor.workspace_tree(path)

    @app.get("/internal/v1/quickmode/scan", dependencies=[Depends(authorize)])
    def quickmode_scan():
        return context.executor.quickmode_scan()

    @app.post("/internal/v1/quickmode/verify", dependencies=[Depends(authorize)])
    def quickmode_verify(body: dict[str, Any]):
        stage_job_id = str(body.get("stage_job_id") or "").strip()
        if not stage_job_id:
            raise DomainError(
                "STAGE_JOB_ID_REQUIRED",
                "stage_job_id wajib diisi.",
                status_code=422,
            )
        return context.executor.quickmode_verify(
            stage_job_id,
            str(body.get("expected_phase") or "uploading"),
        )

    @app.delete(
        "/internal/v1/quickmode/staging/{stage_job_id}",
        dependencies=[Depends(authorize)],
    )
    def quickmode_delete_stage(stage_job_id: str):
        return context.executor.quickmode_delete(stage_job_id)

    @app.post("/internal/v1/jobs", dependencies=[Depends(authorize)])
    def submit_job(body: WorkerJobRequest):
        payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        if not payload.get("execution"):
            payload.pop("execution", None)
        if payload.get("event_sequence_start") is None:
            payload.pop("event_sequence_start", None)
        if payload.get("worker") is None:
            payload.pop("worker", None)
        return {"position": context.executor.enqueue(payload), "job_id": body.job_id}

    @app.post(
        "/internal/v1/jobs/{job_id}/cancel", dependencies=[Depends(authorize)]
    )
    def cancel_job(job_id: str):
        return {"cancelled": context.executor.cancel(job_id)}

    @app.post(
        "/internal/v1/jobs/{job_id}/pause", dependencies=[Depends(authorize)]
    )
    def pause_job(job_id: str):
        return {"paused": context.executor.pause(job_id)}

    @app.post(
        "/internal/v1/jobs/{job_id}/resume", dependencies=[Depends(authorize)]
    )
    def resume_job(job_id: str, body: dict[str, Any]):
        return {
            "resumed": context.executor.resume(
                job_id, body.get("event_sequence_start")
            )
        }

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
