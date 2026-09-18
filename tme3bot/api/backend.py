from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tme3bot.api.schemas import (
    ActorResponse,
    ApproveChallengeRequest,
    BatchSourcesRequest,
    BrowserChallengeResponse,
    BrowserProfileRequest,
    BrowserSessionResponse,
    ChallengeExchangeResponse,
    ChallengeResponse,
    ChallengeTokenRequest,
    ContextVerifyRequest,
    DownloadBatchRequest,
    DownloadRequest,
    ErrorResponse,
    ExportRequest,
    ItemListResponse,
    JobEventListResponse,
    JobListResponse,
    JobResponse,
    LabelRequest,
    LogoutResponse,
    ObjectResponse,
    RefreshRequest,
    ServiceExchangeRequest,
    SettingRequest,
    SourceListResponse,
    SourceResponse,
    SourceUpdateRequest,
    StorageDeliveryRequest,
    StorageBulkActionRequest,
    StorageFolderRequest,
    StorageFolderUpdateRequest,
    StorageItemListResponse,
    StorageItemResponse,
    StorageSettingsResponse,
    TelegramStorageDeliveryRequest,
    StorageUpdateRequest,
    StorageUploadRequest,
    TokenPairResponse,
    UtilityFolderRequest,
    UtilityJobRequest,
    WorkerListResponse,
    WorkerEventRequest,
    WorkerEnabledRequest,
    WorkerRequest,
    WorkerRouteRequest,
    WorkerUpdateRequest,
)
from tme3bot.domain.models import Actor, DomainError, Job, JobEvent, JobStatus
from tme3bot.storage_catalog import build_storage_caption, storage_item_dict
from tme3bot.storage_links import sign_storage_item, verify_storage_item
from tme3bot.utility import utility_setting_specs

LOGGER = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


@dataclass
class BackendContext:
    config: Any
    control_plane: Any
    auth: Any
    profile_manager: Any
    storage_catalog: Any
    worker_registry: Any
    utility_folders: Any
    utility_settings: Any
    export_catalog: Any = None
    label_store: Any = None
    backup_coordinator: Any = None
    bot: Any = None
    worker_dispatcher: Any = None
    storage_maintenance: Any = None


def _model_dict(model) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _error(
    request: Request,
    code: str,
    message: str,
    *,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": getattr(request.state, "request_id", ""),
            }
        },
    )


def job_dict(job: Job) -> dict[str, Any]:
    retry_meta = job.payload.get("quick_retry")
    if not isinstance(retry_meta, dict):
        retry_meta = job.payload.get("export_retry")
    if not isinstance(retry_meta, dict):
        retry_meta = {}
    result_value = job.result.get("value", job.result) if isinstance(job.result, dict) else {}
    if not isinstance(result_value, dict):
        result_value = {}
    export_start_id = job.progress.get("export_start_id")
    if export_start_id is None:
        export_start_id = result_value.get("export_start_id", result_value.get("start_id"))
    export_end_id = job.progress.get("export_end_id")
    if export_end_id is None:
        export_end_id = result_value.get(
            "export_end_id",
            result_value.get("end_id", result_value.get("max_message_id", result_value.get("latest_id"))),
        )
    # Legacy rows did not have explicit phase timestamps. Their persisted
    # lifecycle timestamps are the best available audit boundary, while new
    # worker events provide precise values in progress.
    started_at = job.progress.get("started_at")
    if not started_at and job.status in {
        JobStatus.DISPATCHED,
        JobStatus.RUNNING,
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }:
        started_at = job.created_at.isoformat()
    finished_at = job.progress.get("finished_at")
    if not finished_at and job.status.terminal:
        finished_at = job.updated_at.isoformat()
    return {
        "id": job.id,
        "kind": job.kind,
        "profile": job.profile,
        "actor_user_id": job.actor_user_id,
        "worker": job.worker,
        "status": job.status.value,
        "payload": job.payload,
        "progress": job.progress,
        "result": job.result,
        "error": job.error,
        "archived_at": job.archived_at.isoformat() if job.archived_at else None,
        "queue_position": job.progress.get("position"),
        "retryable": job.kind == "export" and job.status.terminal,
        "retry_of": retry_meta.get("retry_of"),
        "retry_phase": retry_meta.get("retry_phase"),
        "export_start_id": export_start_id,
        "export_end_id": export_end_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def event_dict(event: JobEvent) -> dict[str, Any]:
    return {
        "job_id": event.job_id,
        "sequence": event.sequence,
        "status": event.status.value,
        "event_type": event.event_type,
        "progress": event.progress,
        "result": event.result,
        "error": event.error,
        "created_at": event.created_at.isoformat(),
    }


def create_backend_app(context: BackendContext) -> FastAPI:
    app = FastAPI(
        title="tme3bot Backend API",
        version="1.0.0",
        description="Frontend-neutral control plane for Telegram and future web clients.",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid request"},
            401: {"model": ErrorResponse, "description": "Authentication failed"},
            403: {"model": ErrorResponse, "description": "Action is forbidden"},
            404: {"model": ErrorResponse, "description": "Resource not found"},
            409: {"model": ErrorResponse, "description": "State conflict"},
            500: {"model": ErrorResponse, "description": "Internal failure"},
        },
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return _error(
            request,
            exc.code,
            exc.message,
            status_code=exc.status_code,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return _error(
            request,
            "VALIDATION_ERROR",
            "Payload request tidak valid.",
            status_code=422,
            details={"errors": exc.errors()},
        )

    @app.exception_handler(PermissionError)
    async def permission_error_handler(request: Request, exc: PermissionError):
        return _error(
            request,
            "FORBIDDEN",
            str(exc) or "Aksi tidak diizinkan.",
            status_code=403,
        )

    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError):
        return _error(
            request,
            "NOT_FOUND",
            str(exc).strip("'") or "Data tidak ditemukan.",
            status_code=404,
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return _error(
            request,
            "INVALID_VALUE",
            str(exc) or "Nilai tidak valid.",
            status_code=400,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        LOGGER.exception("Unhandled backend API failure")
        return _error(
            request,
            "INTERNAL_ERROR",
            "Backend gagal memproses request.",
            status_code=500,
        )

    cookie_secret = (
        getattr(context.config, "web_cookie_secret", "")
        or getattr(context.config, "auth_jwt_secret", "")
    )
    cookie_secure = bool(getattr(context.config, "web_cookie_secure", True))
    configured_origin = str(
        getattr(context.config, "web_public_origin", "") or ""
    ).rstrip("/")

    def _cookie_options(*, max_age: int | None = None, http_only: bool = True) -> dict[str, Any]:
        return {
            "max_age": max_age,
            "httponly": http_only,
            "secure": cookie_secure,
            "samesite": "lax",
            "path": "/",
        }

    def _set_cookie(response: Response, name: str, value: str, *, max_age: int | None = None, http_only: bool = True) -> None:
        response.set_cookie(name, value, **_cookie_options(max_age=max_age, http_only=http_only))

    def _clear_cookie(response: Response, name: str, *, http_only: bool = True) -> None:
        _set_cookie(response, name, "", max_age=0, http_only=http_only)

    def _profile_cookie(profile: str) -> str:
        if not cookie_secret:
            raise DomainError("WEB_COOKIE_SECRET_REQUIRED", "WEB_COOKIE_SECRET belum dikonfigurasi.", status_code=500)
        value = base64.urlsafe_b64encode(profile.encode("utf-8")).decode("ascii").rstrip("=")
        signature = hmac.new(cookie_secret.encode("utf-8"), f"profile:{value}".encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{value}.{signature}"

    def _read_profile_cookie(value: str | None) -> str | None:
        if not value or not cookie_secret or "." not in value:
            return None
        encoded, signature = value.rsplit(".", 1)
        expected = hmac.new(cookie_secret.encode("utf-8"), f"profile:{encoded}".encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return None

    def _valid_browser_mutation(request: Request) -> bool:
        origin = request.headers.get("origin", "").rstrip("/")
        if configured_origin:
            if origin != configured_origin:
                return False
        elif origin and origin != f"{request.url.scheme}://{request.headers.get('host', '')}":
            return False
        csrf_cookie = request.cookies.get("tme3_csrf", "")
        csrf_header = request.headers.get("x-csrf-token", "")
        return bool(csrf_cookie and csrf_header and hmac.compare_digest(csrf_cookie, csrf_header))

    def _set_session(response: Response, pair: Any) -> None:
        _set_cookie(response, "tme3_access", str(pair.access_token), max_age=int(pair.expires_in))
        _set_cookie(response, "tme3_refresh", str(pair.refresh_token), max_age=int(getattr(context.auth, "refresh_days", 30)) * 86400)
        _set_cookie(response, "tme3_csrf", secrets.token_urlsafe(24), max_age=int(getattr(context.auth, "refresh_days", 30)) * 86400, http_only=False)

    def _clear_session(response: Response) -> None:
        for name in ("tme3_access", "tme3_refresh", "tme3_profile", "tme3_challenge", "tme3_poll"):
            _clear_cookie(response, name)
        _clear_cookie(response, "tme3_csrf", http_only=False)

    def raw_token(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> str:
        if credentials is not None and credentials.scheme.lower() == "bearer":
            request.state.cookie_auth = False
            return credentials.credentials
        token = request.cookies.get("tme3_access", "")
        if not token:
            raise DomainError("TOKEN_REQUIRED", "Bearer token atau sesi browser wajib diisi.", status_code=401)
        request.state.cookie_auth = True
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and not _valid_browser_mutation(request):
            raise DomainError("CSRF_INVALID", "Request browser ditolak karena CSRF atau Origin tidak valid.", status_code=403)
        return token

    def current_actor(
        request: Request,
        token: str = Depends(raw_token),
        x_profile: str | None = Header(default=None, alias="X-Profile"),
    ):
        payload = context.auth.decode_access(token)
        actor = context.control_plane.actor(int(payload["telegram_user_id"]))
        selected_profile = x_profile
        if getattr(request.state, "cookie_auth", False):
            selected_profile = _read_profile_cookie(request.cookies.get("tme3_profile")) or selected_profile
        if selected_profile:
            if selected_profile not in context.profile_manager.list_profiles():
                raise DomainError(
                    "PROFILE_NOT_FOUND", "Profile tidak ditemukan.", status_code=404
                )
            return Actor(actor.telegram_user_id, selected_profile)
        return actor

    def browser_actor_dict(actor: Actor) -> dict[str, Any]:
        return {
            "telegram_user_id": actor.telegram_user_id,
            "profile": actor.profile,
            "authorized": actor.authorized,
            "worker_route": context.profile_manager.worker_route(actor.profile),
            "download_mode": context.profile_manager.download_mode(actor.profile),
        }

    def require_service(token: str = Depends(raw_token)) -> None:
        if not context.config.frontend_service_token or token != context.config.frontend_service_token:
            raise DomainError("SERVICE_UNAUTHORIZED", "Service token tidak valid.", status_code=401)

    def require_internal(token: str = Depends(raw_token)) -> None:
        if not context.config.backend_internal_token or token != context.config.backend_internal_token:
            raise DomainError("INTERNAL_UNAUTHORIZED", "Internal token tidak valid.", status_code=401)

    def require_management(token: str = Depends(raw_token)) -> None:
        if not context.config.management_api_token or token != context.config.management_api_token:
            raise DomainError("MANAGEMENT_UNAUTHORIZED", "Management token tidak valid.", status_code=401)

    def verify_target(
        actor: Actor,
        purpose: str,
        profile: str | None,
        worker: str | None,
        quick_mode: bool = False,
    ) -> dict[str, Any]:
        purpose = str(purpose or "").strip().lower()
        if purpose not in {"export", "utility", "storage"}:
            raise DomainError("TARGET_PURPOSE_INVALID", "Purpose target tidak valid.", status_code=422)
        selected_profile, selected_worker = context.control_plane.resolve_target(
            actor, profile=profile if purpose == "export" else None, worker=worker
        )
        health = "healthy"
        capabilities: dict[str, Any] = {}
        checker = getattr(context.worker_dispatcher, "check_worker", None)
        if callable(checker):
            try:
                capabilities = checker(selected_worker) or {}
            except Exception as exc:
                raise DomainError(
                    "WORKER_OFFLINE",
                    f"Worker {selected_worker} tidak dapat diverifikasi: {exc}",
                    status_code=503,
                ) from exc
        if capabilities.get("healthy") is False:
            raise DomainError(
                "WORKER_OFFLINE",
                f"Worker {selected_worker} tidak sehat.",
                status_code=503,
            )
        health = "healthy" if capabilities.get("healthy", True) else "unknown"
        available_profiles = capabilities.get("profiles")
        if purpose == "export" and isinstance(available_profiles, list) and selected_profile not in available_profiles:
            raise DomainError(
                "PROFILE_SESSION_UNAVAILABLE",
                f"Profile {selected_profile} belum tersedia pada worker {selected_worker}.",
                status_code=409,
            )
        storage_profile = str(capabilities.get("storage_profile") or getattr(context.config, "worker_storage_profile", "storage"))
        if purpose == "storage" and capabilities and not bool(capabilities.get("storage_profile_available")):
            raise DomainError(
                "STORAGE_PROFILE_UNAVAILABLE",
                f"Sesi Storage {storage_profile} belum tersedia pada worker {selected_worker}.",
                status_code=409,
            )
        if purpose == "export" and quick_mode and (
            not callable(checker) or not bool(capabilities.get("storage_profile_available"))
        ):
            raise DomainError(
                "STORAGE_PROFILE_UNAVAILABLE",
                f"Sesi Storage {storage_profile} belum tersedia pada worker {selected_worker} untuk Quick Mode.",
                status_code=409,
            )
        if purpose == "utility" and capabilities and capabilities.get("workspace") is False:
            raise DomainError("WORKSPACE_UNAVAILABLE", "Workspace worker tidak tersedia.", status_code=409)
        return {
            "verified": True,
            "purpose": purpose,
            "profile": selected_profile if purpose == "export" else None,
            "worker": selected_worker,
            "worker_health": health,
            "storage_profile": storage_profile if purpose == "storage" or quick_mode else None,
            "quick_mode": bool(quick_mode),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    @app.post("/api/v1/context/verify", response_model=ObjectResponse)
    def verify_context(body: ContextVerifyRequest, actor=Depends(current_actor)):
        return verify_target(
            actor, body.purpose, body.profile, body.worker, quick_mode=body.quick_mode
        )

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True, "role": "backend"}

    @app.post(
        "/api/v1/auth/telegram/challenges",
        response_model=ChallengeResponse,
    )
    def create_challenge():
        return context.auth.create_challenge()

    @app.post(
        "/api/v1/auth/telegram/challenges/{challenge_id}/token",
        response_model=ChallengeExchangeResponse,
    )
    def exchange_challenge(challenge_id: str, body: ChallengeTokenRequest):
        pair = context.auth.exchange_challenge(challenge_id, body.poll_token)
        if pair is None:
            return JSONResponse(status_code=202, content={"status": "pending"})
        return asdict(pair)

    @app.post("/api/v1/auth/refresh", response_model=TokenPairResponse)
    def refresh(body: RefreshRequest):
        return asdict(context.auth.refresh(body.refresh_token))

    @app.post("/api/v1/auth/logout", response_model=LogoutResponse)
    def logout(body: RefreshRequest):
        return {"revoked": context.auth.logout(body.refresh_token)}

    @app.post(
        "/api/v1/auth/browser/challenge",
        response_model=BrowserChallengeResponse,
    )
    def browser_challenge(response: Response):
        """Start a Telegram login without exposing the poll credential to JS."""
        challenge = context.auth.create_challenge()
        _set_cookie(response, "tme3_challenge", str(challenge["challenge_id"]), max_age=300)
        _set_cookie(response, "tme3_poll", str(challenge["poll_token"]), max_age=300)
        if not response.headers.get("set-cookie") or "tme3_csrf" not in response.headers.get("set-cookie", ""):
            _set_cookie(response, "tme3_csrf", secrets.token_urlsafe(24), max_age=300, http_only=False)
        return {
            "challenge_id": challenge["challenge_id"],
            "verification_uri": challenge["verification_uri"],
            "expires_at": challenge["expires_at"],
            "interval": challenge["interval"],
        }

    @app.get(
        "/api/v1/auth/browser/challenge",
        response_model=BrowserSessionResponse,
    )
    def browser_challenge_status(request: Request, response: Response):
        challenge_id = request.cookies.get("tme3_challenge", "")
        poll_token = request.cookies.get("tme3_poll", "")
        if not challenge_id or not poll_token:
            raise DomainError("CHALLENGE_COOKIE_REQUIRED", "Mulai login lagi dari browser ini.", status_code=401)
        pair = context.auth.exchange_challenge(challenge_id, poll_token)
        if pair is None:
            return {"authenticated": False, "profiles": []}
        _set_session(response, pair)
        _clear_cookie(response, "tme3_challenge")
        _clear_cookie(response, "tme3_poll")
        payload = context.auth.decode_access(pair.access_token)
        actor = context.control_plane.actor(int(payload["telegram_user_id"]))
        return {
            "authenticated": True,
            "actor": browser_actor_dict(actor),
            "profiles": context.profile_manager.list_profiles(),
        }

    @app.get("/api/v1/auth/browser/session", response_model=BrowserSessionResponse)
    def browser_session(request: Request, actor: Actor = Depends(current_actor)):
        if not getattr(request.state, "cookie_auth", False):
            raise DomainError("BROWSER_SESSION_REQUIRED", "Sesi browser wajib digunakan.", status_code=401)
        return {
            "authenticated": True,
            "actor": browser_actor_dict(actor),
            "profiles": context.profile_manager.list_profiles(),
        }

    @app.post("/api/v1/auth/browser/refresh", response_model=BrowserSessionResponse)
    def browser_refresh(request: Request, response: Response):
        if not _valid_browser_mutation(request):
            raise DomainError("CSRF_INVALID", "Request browser tidak valid.", status_code=403)
        refresh_token = request.cookies.get("tme3_refresh", "")
        if not refresh_token:
            raise DomainError("REFRESH_REQUIRED", "Sesi browser sudah berakhir.", status_code=401)
        pair = context.auth.refresh(refresh_token)
        _set_session(response, pair)
        payload = context.auth.decode_access(pair.access_token)
        actor = context.control_plane.actor(int(payload["telegram_user_id"]))
        selected = _read_profile_cookie(request.cookies.get("tme3_profile"))
        if selected in context.profile_manager.list_profiles():
            actor = Actor(actor.telegram_user_id, selected)
        return {"authenticated": True, "actor": browser_actor_dict(actor), "profiles": context.profile_manager.list_profiles()}

    @app.post("/api/v1/auth/browser/logout", response_model=LogoutResponse)
    def browser_logout(request: Request, response: Response):
        if not _valid_browser_mutation(request):
            raise DomainError("CSRF_INVALID", "Request browser tidak valid.", status_code=403)
        refresh_token = request.cookies.get("tme3_refresh", "")
        revoked = context.auth.logout(refresh_token) if refresh_token else False
        _clear_session(response)
        return {"revoked": revoked}

    @app.put("/api/v1/auth/browser/profile", response_model=BrowserSessionResponse)
    def browser_profile(
        request: Request,
        response: Response,
        body: BrowserProfileRequest,
        actor: Actor = Depends(current_actor),
    ):
        if not getattr(request.state, "cookie_auth", False):
            raise DomainError("BROWSER_SESSION_REQUIRED", "Sesi browser wajib digunakan.", status_code=401)
        profiles = context.profile_manager.list_profiles()
        if body.profile not in profiles:
            raise DomainError("PROFILE_NOT_FOUND", "Profile tidak ditemukan.", status_code=404)
        _set_cookie(response, "tme3_profile", _profile_cookie(body.profile), max_age=int(getattr(context.auth, "refresh_days", 30)) * 86400)
        return {"authenticated": True, "actor": browser_actor_dict(Actor(actor.telegram_user_id, body.profile)), "profiles": profiles}

    @app.post(
        "/internal/v1/auth/telegram/challenges/{code}/approve",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def approve_challenge(code: str, body: ApproveChallengeRequest):
        return context.auth.approve(code, body.telegram_user_id)

    @app.post(
        "/internal/v1/auth/telegram/exchange",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def service_exchange(body: ServiceExchangeRequest):
        return context.auth.service_exchange(body.telegram_user_id)

    @app.get("/api/v1/me", response_model=ActorResponse)
    def me(actor=Depends(current_actor)):
        return {
            "telegram_user_id": actor.telegram_user_id,
            "profile": actor.profile,
            "authorized": actor.authorized,
            "worker_route": context.profile_manager.worker_route(actor.profile),
            "download_mode": context.profile_manager.download_mode(actor.profile),
        }

    @app.get("/api/v1/profiles", response_model=ItemListResponse)
    def profiles(actor=Depends(current_actor)):
        return {
            "items": [
                {
                    "name": name,
                    "selected": name == actor.profile,
                    "worker_route": context.profile_manager.worker_route(name),
                    "download_mode": context.profile_manager.download_mode(name),
                }
                for name in context.profile_manager.list_profiles()
            ]
        }

    @app.get("/api/v1/jobs", response_model=JobListResponse)
    def list_jobs(
        kind: str | None = None,
        status: str | None = None,
        worker: str | None = None,
        profile: str | None = None,
        quick_mode: bool | None = None,
        scope: str = Query("current", pattern="^(current|global)$"),
        archived: bool | None = False,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        selected_profile = None if scope == "global" else context.control_plane.require_profile(actor, profile)
        if profile and scope == "global":
            selected_profile = context.control_plane.require_profile(actor, profile)
        items = context.control_plane.jobs.list(
            profile=selected_profile,
            kind=kind,
            status=status,
            worker=worker,
            quick_mode=quick_mode,
            archived=archived,
            offset=offset,
            limit=limit,
        )
        total = context.control_plane.jobs.count(
            profile=selected_profile,
            kind=kind,
            status=status,
            worker=worker,
            quick_mode=quick_mode,
            archived=archived,
        )
        return {
            "items": [job_dict(item) for item in items],
            "total": total,
            "next_offset": offset + len(items) if offset + len(items) < total else None,
        }

    @app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str, actor=Depends(current_actor)):
        job = _owned_job(context, actor, job_id)
        return job_dict(job)

    @app.get("/api/v1/quick-mode/staging", response_model=ObjectResponse)
    def quick_mode_staging(actor=Depends(current_actor)):
        """Merge persisted Quick Mode jobs with physical worker staging."""
        del actor
        jobs = context.control_plane.jobs.list(
            kind="export",
            quick_mode=True,
            archived=False,
            offset=0,
            limit=1000,
        )
        by_stage: dict[tuple[str, str], dict[str, Any]] = {}
        for job in jobs:
            retry = job.payload.get("quick_retry")
            retry = retry if isinstance(retry, dict) else {}
            result_value = job.result.get("value", job.result) if isinstance(job.result, dict) else {}
            result_value = result_value if isinstance(result_value, dict) else {}
            stage_id = str(
                retry.get("stage_job_id")
                or result_value.get("stage_job_id")
                or job.id
            )
            # Keep the newest attempt as the linked backend row, while the
            # response still includes the stable stage identity.
            by_stage[(str(job.worker), stage_id)] = {
                "id": stage_id,
                "job": job_dict(job),
                "backend_job_id": job.id,
            }

        items: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        dispatcher = context.worker_dispatcher
        worker_names = context.worker_registry.names() if context.worker_registry is not None else []
        scanner = getattr(dispatcher, "quickmode_scan", None) if dispatcher is not None else None
        for worker in worker_names:
            try:
                response = scanner(worker) if callable(scanner) else {"worker": worker, "items": []}
                scanned = response.get("items", []) if isinstance(response, dict) else []
                if not isinstance(scanned, list):
                    scanned = []
                for raw in scanned:
                    if not isinstance(raw, dict):
                        continue
                    item = dict(raw)
                    stage_id = str(item.get("stage_job_id") or "")
                    if not stage_id:
                        continue
                    linked = by_stage.get((worker, stage_id))
                    item["worker"] = str(item.get("worker") or worker)
                    item["backend_job"] = linked["job"] if linked else None
                    item["backend_job_id"] = linked["backend_job_id"] if linked else None
                    item["orphan"] = linked is None
                    items.append(item)
            except Exception as exc:
                # One remote worker being offline must not hide staging from
                # the remaining workers.
                errors.append({"worker": worker, "error": str(exc)[:500]})

        # A backend row without a physical scan is retained as a diagnosis
        # entry, rather than silently disappearing from the manager.
        scanned_ids = {
            (str(item.get("worker") or ""), str(item.get("stage_job_id") or ""))
            for item in items
        }
        for (job_worker, stage_id), linked in by_stage.items():
            if (job_worker, stage_id) in scanned_ids:
                continue
            job = linked["job"]
            items.append(
                {
                    "stage_job_id": stage_id,
                    "quick_operation_id": stage_id,
                    "profile": job.get("profile") or "",
                    "worker": job_worker,
                    "folder_name": "",
                    "phase": job.get("progress", {}).get("phase") or job.get("status"),
                    "resume_phase": job.get("retry_phase") or "auto",
                    "json_present": False,
                    "expected_media_count": 0,
                    "actual_media_count": 0,
                    "archive_parts": 0,
                    "thumbnail_present": False,
                    "tdl_export_present": False,
                    "tdl_download_present": False,
                    "staging_path": job.get("progress", {}).get("staging_path"),
                    "backend_job": job,
                    "backend_job_id": linked["backend_job_id"],
                    "orphan": False,
                    "scan_missing": True,
                }
            )
        return {"items": items, "errors": errors}

    @app.post("/api/v1/quick-mode/recover", response_model=ObjectResponse)
    def recover_quick_mode(body: dict[str, Any], actor=Depends(current_actor)):
        worker = str(body.get("worker") or "").strip().lower()
        stage_id = str(body.get("stage_job_id") or "").strip()
        if not worker or not stage_id:
            raise DomainError(
                "RECOVERY_TARGET_REQUIRED",
                "Worker dan stage_job_id wajib diisi.",
                status_code=422,
            )
        if context.worker_registry is not None and context.worker_registry.get(worker) is None:
            raise DomainError("WORKER_NOT_FOUND", "Worker recovery tidak ditemukan.", status_code=404)
        jobs = context.control_plane.jobs.list(
            kind="export", quick_mode=True, archived=False, offset=0, limit=1000
        )
        linked = None
        for candidate in jobs:
            retry = candidate.payload.get("quick_retry")
            retry = retry if isinstance(retry, dict) else {}
            if str(retry.get("stage_job_id") or candidate.id) == stage_id and candidate.worker == worker:
                linked = candidate
        if linked is not None:
            if not linked.status.terminal:
                raise DomainError(
                    "JOB_NOT_TERMINAL",
                    "Folder Quick Mode sudah memiliki job aktif.",
                    status_code=409,
                )
            return {"job": job_dict(context.control_plane.retry_job(actor, linked.id)), "imported": False}

        scanner = getattr(context.worker_dispatcher, "quickmode_scan", None)
        try:
            response = scanner(worker) if callable(scanner) else {"items": []}
        except Exception as exc:
            raise DomainError("WORKER_OFFLINE", f"Worker recovery tidak tersedia: {exc}", status_code=503) from exc
        item = next(
            (value for value in response.get("items", []) if isinstance(value, dict) and str(value.get("stage_job_id")) == stage_id),
            None,
        )
        if item is None:
            raise DomainError("STAGING_NOT_FOUND", "Folder staging Quick Mode tidak ditemukan.", status_code=404)
        profile = str(body.get("profile") or item.get("profile") or "").strip()
        if not profile:
            raise DomainError("PROFILE_REQUIRED", "Profile wajib dipilih untuk folder recovery ini.", status_code=422)
        context.control_plane.require_profile(actor, profile)
        has_upload_assets = bool(item.get("archive_parts", 0)) and bool(item.get("thumbnail_present"))
        payload: dict[str, Any] = {
            "quick_mode": True,
            "quick_settings": context.utility_settings.get(),
            "quick_retry": {
                "retry_phase": "auto",
                "resume_phase": "auto",
                "stage_job_id": stage_id,
                "quick_operation_id": str(item.get("quick_operation_id") or stage_id),
            },
        }
        for key in ("url", "chat_ref", "start_id", "label", "save_source", "use_url_message_id"):
            if body.get(key) is not None:
                payload[key] = body[key]
        if not item.get("json_present") and not has_upload_assets and not payload.get("url") and not payload.get("chat_ref"):
            raise DomainError(
                "RECOVERY_SOURCE_REQUIRED",
                "Folder tidak memiliki JSON atau hasil upload lengkap. Berikan URL/chat ID untuk export ulang.",
                status_code=422,
            )
        job = context.control_plane.submit_job(
            actor,
            "export",
            payload,
            profile=profile,
            worker=worker,
        )
        return {"job": job_dict(job), "imported": True}

    @app.post(
        "/internal/v1/jobs/{job_id}/telegram-notifications",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def create_telegram_notification(job_id: str, body: dict[str, Any]):
        job = context.control_plane.jobs.get(job_id)
        if job is None:
            raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
        user_id = int(body.get("telegram_user_id") or 0)
        chat_id = int(body.get("telegram_chat_id") or 0)
        if user_id <= 0 or chat_id != user_id or user_id != job.actor_user_id:
            raise DomainError(
                "TELEGRAM_NOTIFICATION_FORBIDDEN",
                "Notifikasi hanya dapat didaftarkan oleh actor pembuat job pada private chat.",
                status_code=403,
            )
        notification = context.control_plane.jobs.create_telegram_notification(
            job.id, user_id, chat_id, job.profile
        )
        return {"notification": notification, "job": job_dict(job)}

    @app.get(
        "/internal/v1/telegram-notifications/pending",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def pending_telegram_notifications(limit: int = Query(100, ge=1, le=500)):
        items = []
        for notification in context.control_plane.jobs.pending_telegram_notifications(limit):
            job = context.control_plane.jobs.get(str(notification["job_id"]))
            if job is not None:
                items.append({"notification": notification, "job": job_dict(job)})
        return {"items": items}

    @app.patch(
        "/internal/v1/telegram-notifications/{notification_id}",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def update_telegram_notification(notification_id: int, body: dict[str, Any]):
        if str(body.get("status") or "") not in {
            "",
            "pending",
            "terminal",
            "deleted",
            "failed",
        }:
            raise DomainError(
                "INVALID_NOTIFICATION_STATUS",
                "Status notifikasi tidak valid.",
                status_code=422,
            )
        notification = context.control_plane.jobs.update_telegram_notification(
            notification_id, body
        )
        if notification is None:
            raise DomainError(
                "NOTIFICATION_NOT_FOUND",
                "Subscription notifikasi tidak ditemukan.",
                status_code=404,
            )
        return {"notification": notification}

    @app.get("/api/v1/jobs/{job_id}/events", response_model=JobEventListResponse)
    def get_job_events(
        job_id: str,
        after_sequence: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        _owned_job(context, actor, job_id)
        return {
            "items": [
                event_dict(item)
                for item in context.control_plane.jobs.events(
                    job_id, after_sequence=after_sequence
                )
            ]
        }

    @app.get("/api/v1/jobs/{job_id}/log-snapshot", response_model=ObjectResponse)
    def get_job_log_snapshot(job_id: str, actor=Depends(current_actor)):
        job = _owned_job(context, actor, job_id)
        if context.worker_dispatcher is not None:
            try:
                return {
                    **context.worker_dispatcher.job_log(job.worker, job.id),
                    "source": "worker",
                }
            except Exception:
                if job.status.value in {"queued", "dispatched", "running"}:
                    raise DomainError(
                        "JOB_LOG_UNAVAILABLE",
                        "Snapshot log worker belum tersedia.",
                        status_code=503,
                    )
        for event in reversed(context.control_plane.jobs.events(job.id)):
            if (
                event.event_type == "log.snapshot"
                and isinstance(event.result, dict)
                and isinstance(event.result.get("log"), dict)
            ):
                return {"log": event.result["log"], "source": "history"}
        return {
            "log": {"lines": [], "line_count": 0, "truncated": False},
            "source": "empty",
        }

    @app.post("/api/v1/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel_job(job_id: str, actor=Depends(current_actor)):
        return job_dict(context.control_plane.cancel_job(actor, job_id))

    @app.post("/api/v1/jobs/terminate-active", response_model=ObjectResponse)
    def terminate_active_jobs(
        scope: str = Query("current", pattern="^(current|global)$"),
        profile: str | None = None,
        kind: str | None = None,
        quick_mode: bool | None = None,
        actor=Depends(current_actor),
    ):
        selected_profile = None if scope == "global" else profile
        return context.control_plane.terminate_active_jobs(
            actor,
            profile=selected_profile,
            kind=kind,
            quick_mode=quick_mode,
        )

    @app.post("/api/v1/jobs/{job_id}/retry", response_model=JobResponse)
    def retry_job(job_id: str, actor=Depends(current_actor)):
        return job_dict(context.control_plane.retry_job(actor, job_id))

    @app.post("/api/v1/jobs/{job_id}/archive", response_model=JobResponse)
    def archive_job(job_id: str, actor=Depends(current_actor)):
        _owned_job(context, actor, job_id)
        return job_dict(context.control_plane.jobs.set_archived(job_id, True))

    @app.post("/api/v1/jobs/{job_id}/restore", response_model=JobResponse)
    def restore_job(job_id: str, actor=Depends(current_actor)):
        _owned_job(context, actor, job_id)
        return job_dict(context.control_plane.jobs.set_archived(job_id, False))

    @app.delete("/api/v1/jobs/{job_id}", response_model=ObjectResponse)
    def purge_job(job_id: str, actor=Depends(current_actor)):
        _owned_job(context, actor, job_id)
        return {"purged": context.control_plane.jobs.purge(job_id)}

    @app.get("/api/v1/sources", response_model=SourceListResponse)
    def list_sources(profile: str | None = None, actor=Depends(current_actor)):
        selected_profile = context.control_plane.require_profile(actor, profile)
        store = context.profile_manager.runtime(selected_profile).state_store
        return {
            "items": [
                {"chat_ref": chat_ref, **source.to_dict()}
                for chat_ref, source in store.list_sources()
            ]
        }

    @app.get("/api/v1/sources/{chat_ref:path}", response_model=SourceResponse)
    def get_source(chat_ref: str, profile: str | None = None, actor=Depends(current_actor)):
        selected_profile = context.control_plane.require_profile(actor, profile)
        source = context.profile_manager.runtime(selected_profile).state_store.get_source(chat_ref)
        if source is None:
            raise DomainError("SOURCE_NOT_FOUND", "Source tidak ditemukan.", status_code=404)
        return {"chat_ref": chat_ref, **source.to_dict()}

    @app.delete("/api/v1/sources/{chat_ref:path}", response_model=ObjectResponse)
    def delete_source(chat_ref: str, profile: str | None = None, actor=Depends(current_actor)):
        selected_profile = context.control_plane.require_profile(actor, profile)
        deleted = context.profile_manager.runtime(selected_profile).state_store.delete_source(chat_ref)
        return {"deleted": deleted}

    @app.patch("/api/v1/sources/{chat_ref:path}", response_model=SourceResponse)
    def update_source(
        chat_ref: str, body: SourceUpdateRequest, profile: str | None = None, actor=Depends(current_actor)
    ):
        selected_profile = context.control_plane.require_profile(actor, profile)
        store = context.profile_manager.runtime(selected_profile).state_store
        source = store.get_source(chat_ref)
        if source is None:
            raise DomainError(
                "SOURCE_NOT_FOUND", "Source tidak ditemukan.", status_code=404
            )
        updated = store.upsert_source(
            chat_ref,
            body.label,
            source.last_id,
            source.warmup_url,
            source.warmup_done,
        )
        return {"chat_ref": chat_ref, **updated.to_dict()}

    @app.post("/api/v1/sources/batch-delete", response_model=ObjectResponse)
    def batch_delete_sources(body: BatchSourcesRequest, profile: str | None = None, actor=Depends(current_actor)):
        selected_profile = context.control_plane.require_profile(actor, profile)
        deleted = context.profile_manager.runtime(selected_profile).state_store.delete_sources(body.chat_refs)
        return {"deleted": deleted}

    @app.post("/api/v1/exports", response_model=JobResponse)
    def submit_export(body: ExportRequest, actor=Depends(current_actor)):
        values = _model_dict(body)
        if not values.get("url") and not values.get("chat_ref"):
            raise DomainError(
                "EXPORT_REFERENCE_REQUIRED",
                "Isi URL lama atau chat_ref username/numeric ID.",
                status_code=422,
            )
        verify_target(
            actor,
            "export",
            values.get("profile"),
            values.get("worker"),
            quick_mode=bool(values.get("quick_mode")),
        )
        if bool(values.get("quick_mode")):
            # Snapshot settings at submission time. The password is retained
            # only in the internal worker command and redacted from the Job API.
            values["quick_settings"] = context.utility_settings.get()
            values["quick_settings"].setdefault(
                "rclone_destination", "googledrive:backup"
            )
        return job_dict(
            context.control_plane.submit_job(
                actor, "export", values, profile=values.get("profile"), worker=values.get("worker")
            )
        )

    @app.get("/api/v1/labels", response_model=ItemListResponse)
    def list_labels(actor=Depends(current_actor)):
        del actor
        if context.label_store is None:
            return {"items": []}
        return {
            "items": [
                {"label": item.label, "updated_at": item.updated_at}
                for item in context.label_store.list_labels(limit=100)
            ]
        }

    @app.post("/api/v1/labels", response_model=ObjectResponse)
    def add_label(body: LabelRequest, actor=Depends(current_actor)):
        del actor
        if context.label_store is None:
            raise DomainError(
                "LABEL_STORE_UNAVAILABLE",
                "Label store belum tersedia.",
                status_code=503,
            )
        return {"label": context.label_store.add(body.label)}

    @app.post("/api/v1/sources/leave", response_model=JobResponse)
    def submit_leave(body: BatchSourcesRequest, actor=Depends(current_actor)):
        return job_dict(
            context.control_plane.submit_job(
                actor, "leave", {"chat_refs": body.chat_refs}, profile=actor.profile
            )
        )

    @app.post("/api/v1/downloads", response_model=JobResponse)
    def submit_download(
        body: DownloadRequest | None = None,
        retry_failed: bool = False,
        actor=Depends(current_actor),
    ):
        values = _model_dict(body) if body is not None else {}
        artifact_ids = values.get("artifact_ids") or []
        worker = None
        selected_profile = None
        artifact_keys: list[str] = []
        artifact_refs: list[dict[str, str]] = []
        for artifact_id in artifact_ids:
            artifact = context.export_catalog.get(str(artifact_id))
            if artifact is None:
                raise DomainError("ARTIFACT_NOT_FOUND", "Artifact tidak ditemukan.", status_code=404)
            context.control_plane.require_profile(actor, str(artifact["profile"]))
            # Validate the pinned origin before creating a download job.
            context.control_plane.resolve_target(
                actor,
                profile=str(artifact["profile"]),
                worker=str(artifact["worker"]),
            )
            if artifact["status"] not in {"pending", "failed"}:
                raise DomainError(
                    "ARTIFACT_NOT_PENDING",
                    "Artifact tidak berada pada antrean yang dapat dijalankan.",
                    status_code=409,
                )
            if not bool(artifact.get("available", 1)):
                raise DomainError(
                    "ARTIFACT_UNAVAILABLE",
                    "File artifact sudah tidak tersedia pada worker.",
                    status_code=409,
                )
            if selected_profile is not None and selected_profile != artifact["profile"]:
                raise DomainError(
                    "ARTIFACT_ORIGIN_MIXED",
                    "Gunakan endpoint batch untuk artifact dari origin berbeda.",
                    status_code=409,
                )
            if worker is not None and worker != artifact["worker"]:
                raise DomainError("ARTIFACT_ORIGIN_MIXED", "Gunakan endpoint batch untuk artifact dari origin berbeda.", status_code=409)
            selected_profile = str(artifact["profile"])
            worker = str(artifact["worker"])
            artifact_keys.append(str(artifact["artifact_key"]))
            artifact_refs.append(
                {
                    "key": str(artifact["artifact_key"]),
                    "status": str(artifact["status"]),
                }
            )
        return job_dict(
            context.control_plane.submit_job(
                actor,
                "download",
                {
                    "retry_failed": retry_failed,
                    "artifact_keys": artifact_keys,
                    "artifacts": artifact_refs,
                    "priority": values.get("priority", "normal"),
                },
                profile=selected_profile or actor.profile,
                worker=worker,
            )
        )

    @app.post("/api/v1/downloads/batch", response_model=ObjectResponse)
    def submit_download_batch(body: DownloadBatchRequest, actor=Depends(current_actor)):
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for artifact_id in body.artifact_ids:
            artifact = context.export_catalog.get(str(artifact_id))
            if artifact is None:
                raise DomainError("ARTIFACT_NOT_FOUND", "Artifact tidak ditemukan.", status_code=404)
            context.control_plane.require_profile(actor, str(artifact["profile"]))
            # Validate all origins before dispatching any group so a disabled
            # worker cannot leave a partially-created batch behind.
            context.control_plane.resolve_target(
                actor,
                profile=str(artifact["profile"]),
                worker=str(artifact["worker"]),
            )
            if artifact["status"] not in {"pending", "failed"}:
                raise DomainError("ARTIFACT_NOT_PENDING", "Artifact tidak berada pada antrean yang dapat dijalankan.", status_code=409)
            if not bool(artifact.get("available", 1)):
                raise DomainError("ARTIFACT_UNAVAILABLE", "File artifact sudah tidak tersedia pada worker.", status_code=409)
            key = (str(artifact["profile"]), str(artifact["worker"]))
            groups.setdefault(key, []).append(artifact)
        jobs, response_groups = [], []
        for (profile, worker), items in groups.items():
            job = context.control_plane.submit_job(
                actor,
                "download",
                {
                    "retry_failed": any(item["status"] == "failed" for item in items),
                    "artifact_keys": [str(item["artifact_key"]) for item in items],
                    "artifacts": [{"key": str(item["artifact_key"]), "status": str(item["status"])} for item in items],
                    "priority": body.priority,
                },
                profile=profile,
                worker=worker,
            )
            jobs.append(job_dict(job))
            response_groups.append({"profile": profile, "worker": worker, "artifact_ids": [str(item["id"]) for item in items], "job_id": job.id})
        return {"jobs": jobs, "groups": response_groups}

    @app.get("/api/v1/downloads/artifacts", response_model=ObjectResponse)
    def list_artifacts(
        scope: str = Query("current", pattern="^(current|global)$"),
        profile: str | None = None,
        status: str | None = None,
        archived: bool | None = False,
        worker: str | None = None,
        label: str | None = None,
        chat_ref: str | None = None,
        available: bool | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        selected_profile = None if scope == "global" else context.control_plane.require_profile(actor, profile)
        if profile:
            selected_profile = context.control_plane.require_profile(actor, profile)
        items, total = context.export_catalog.list(
            profile=selected_profile,
            status=status,
            archived=archived,
            worker=worker,
            label=label,
            chat_ref=chat_ref,
            available=available,
            limit=limit,
            offset=offset,
        )
        return {"items": items, "total": total}

    @app.post("/api/v1/downloads/artifacts/reconcile", response_model=ObjectResponse)
    def reconcile_artifacts(
        scope: str = Query("current", pattern="^(current|global)$"),
        profile: str | None = None,
        worker: str | None = None,
        actor=Depends(current_actor),
    ):
        pairs: list[tuple[str, str]] = []
        if scope == "global":
            if profile:
                context.control_plane.require_profile(actor, profile)
            pairs = list(context.export_catalog.origins()) if context.export_catalog is not None else []
            if profile:
                pairs = [pair for pair in pairs if pair[0] == profile]
            if worker:
                pairs = [pair for pair in pairs if pair[1] == worker]
        else:
            selected_profile = context.control_plane.require_profile(actor, profile)
            _, selected_worker = context.control_plane.resolve_target(actor, profile=selected_profile, worker=worker)
            pairs = [(selected_profile, selected_worker)]
        jobs = []
        for selected_profile, selected_worker in pairs:
            inventory_id = str(uuid.uuid4())
            jobs.append(job_dict(context.control_plane.submit_job(
                actor, "artifact_inventory", {"inventory_id": inventory_id},
                profile=selected_profile, worker=selected_worker,
            )))
        return {"jobs": jobs, "items": jobs}

    @app.post("/api/v1/downloads/artifacts/{artifact_id}/delete-file", response_model=JobResponse)
    def delete_artifact_file(artifact_id: str, actor=Depends(current_actor)):
        artifact = _profile_artifact(context, actor, artifact_id)
        if artifact["status"] not in {"pending", "failed"}:
            raise DomainError(
                "ARTIFACT_ACTIVE",
                "Artifact aktif atau sudah selesai tidak dapat dihapus.",
                status_code=409,
            )
        context.export_catalog.update_status(artifact_id, "deleted")
        return job_dict(
            context.control_plane.submit_job(
                actor,
                "artifact_delete",
                {"artifact_key": artifact["artifact_key"]},
                profile=str(artifact["profile"]),
                worker=str(artifact["worker"]),
            )
        )

    @app.post("/api/v1/downloads/artifacts/actions/delete", response_model=ObjectResponse)
    def delete_artifacts_batch(body: DownloadBatchRequest, actor=Depends(current_actor)):
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for artifact_id in body.artifact_ids:
            artifact = context.export_catalog.get(str(artifact_id))
            if artifact is None:
                raise DomainError("ARTIFACT_NOT_FOUND", "Artifact tidak ditemukan.", status_code=404)
            context.control_plane.require_profile(actor, str(artifact["profile"]))
            if artifact["status"] not in {"pending", "failed"}:
                raise DomainError("ARTIFACT_ACTIVE", "Artifact aktif atau selesai tidak dapat dihapus sebagai file pending.", status_code=409)
            groups.setdefault((str(artifact["profile"]), str(artifact["worker"])), []).append(artifact)
        jobs, deleted = [], []
        for (profile, worker), items in groups.items():
            for item in items:
                context.export_catalog.update_status(str(item["id"]), "deleted")
                deleted.append(str(item["id"]))
            jobs.append(job_dict(context.control_plane.submit_job(
                actor, "artifact_delete",
                {"artifact_keys": [str(item["artifact_key"]) for item in items]},
                profile=profile, worker=worker,
            )))
        return {"deleted": deleted, "jobs": jobs}

    @app.post("/api/v1/downloads/artifacts/{artifact_id}/archive", response_model=ObjectResponse)
    def archive_artifact(artifact_id: str, actor=Depends(current_actor)):
        _profile_artifact(context, actor, artifact_id)
        return context.export_catalog.archive(artifact_id)

    @app.post("/api/v1/downloads/artifacts/{artifact_id}/restore", response_model=ObjectResponse)
    def restore_artifact(artifact_id: str, actor=Depends(current_actor)):
        _profile_artifact(context, actor, artifact_id)
        return context.export_catalog.restore(artifact_id)

    @app.delete("/api/v1/downloads/artifacts/{artifact_id}", response_model=ObjectResponse)
    def purge_artifact(artifact_id: str, actor=Depends(current_actor)):
        _profile_artifact(context, actor, artifact_id)
        return {"purged": context.export_catalog.purge(artifact_id)}

    @app.get("/api/v1/dashboard/summary", response_model=ObjectResponse)
    def dashboard_summary(actor=Depends(current_actor)):
        jobs = context.control_plane.jobs
        active = sum(
            jobs.count(profile=actor.profile, status=status, archived=False)
            for status in ("queued", "dispatched", "running")
        )
        artifact_counts = context.export_catalog.summary(actor.profile)
        storage_items = context.storage_catalog.search("", limit=1, offset=0)
        backups = context.storage_catalog.backup_runs(limit=1)
        return {
            "profile": actor.profile,
            "worker": context.profile_manager.worker_route(actor.profile),
            "jobs": {
                "active": active,
                "failed": jobs.count(
                    profile=actor.profile, status="failed", archived=False
                ),
            },
            "artifacts": artifact_counts,
            "storage": {"has_items": bool(storage_items)},
            "last_backup": backups[0] if backups else None,
        }

    @app.post("/api/v1/downloads/clear-failed", response_model=ObjectResponse)
    def clear_failed(
        scope: str = Query("current", pattern="^(current|global)$"),
        profile: str | None = None,
        worker: str | None = None,
        actor=Depends(current_actor),
    ):
        if scope == "global":
            if profile:
                context.control_plane.require_profile(actor, profile)
            pairs = list(context.export_catalog.origins()) if context.export_catalog is not None else []
            if profile:
                pairs = [pair for pair in pairs if pair[0] == profile]
            if worker:
                pairs = [pair for pair in pairs if pair[1] == worker]
            jobs = [
                context.control_plane.submit_job(
                    actor, "download_clear_failed", {}, profile=selected_profile, worker=selected_worker
                )
                for selected_profile, selected_worker in pairs
            ]
            return {"jobs": [job_dict(job) for job in jobs]}
        selected_profile, selected_worker = context.control_plane.resolve_target(
            actor, profile=profile, worker=worker
        )
        return {"job": job_dict(context.control_plane.submit_job(
            actor, "download_clear_failed", {}, profile=selected_profile, worker=selected_worker
        ))}

    @app.put("/api/v1/downloads/mode/{mode}", response_model=ObjectResponse)
    def set_download_mode(mode: str, actor=Depends(current_actor)):
        if context.control_plane.jobs.has_active(actor.profile):
            raise DomainError(
                "PROFILE_BUSY", "Profile masih memiliki job aktif.", status_code=409
            )
        return {
            "mode": context.profile_manager.set_download_mode(actor.profile, mode)
        }

    @app.get("/api/v1/utility/folders", response_model=ItemListResponse)
    def utility_folders(actor=Depends(current_actor)):
        del actor
        return {"items": context.utility_folders.list()}

    @app.get("/api/v1/utility/tree", response_model=ObjectResponse)
    def utility_tree(path: str = "/workspace", worker: str | None = None, actor=Depends(current_actor)):
        _, worker = context.control_plane.resolve_target(actor, worker=worker)
        if context.worker_dispatcher is None:
            raise DomainError(
                "WORKER_INVENTORY_UNAVAILABLE",
                "Inventory workspace worker belum tersedia.",
                status_code=503,
            )
        return context.worker_dispatcher.workspace_tree(worker, path)

    @app.post("/api/v1/utility/folders", response_model=ObjectResponse)
    def add_utility_folder(body: UtilityFolderRequest, actor=Depends(current_actor)):
        del actor
        return {"path": context.utility_folders.add(body.path)}

    @app.delete("/api/v1/utility/folders", response_model=ObjectResponse)
    def remove_utility_folder(path: str, actor=Depends(current_actor)):
        del actor
        return {"removed": context.utility_folders.remove(path)}

    @app.get("/api/v1/utility/settings", response_model=ObjectResponse)
    def utility_settings(actor=Depends(current_actor)):
        del actor
        values = context.utility_settings.get()
        # The dashboard only needs to know whether a password exists. Never
        # return the actual archive/backup password to a browser.
        return {
            "move_size": values["move_size"],
            "compress_size": values["compress_size"],
            "rclone_destination": values.get("rclone_destination", "googledrive:backup"),
            "compress_password_configured": bool(values.get("compress_password")),
        }

    @app.get("/api/v1/utility/settings/meta", response_model=ItemListResponse)
    def utility_settings_meta(actor=Depends(current_actor)):
        del actor
        return {"items": utility_setting_specs()}

    @app.put("/api/v1/utility/settings/{key}", response_model=ObjectResponse)
    def set_utility_setting(key: str, body: SettingRequest, actor=Depends(current_actor)):
        del actor
        context.utility_settings.set(key, body.value)
        values = context.utility_settings.get()
        return {
            "move_size": values["move_size"],
            "compress_size": values["compress_size"],
            "rclone_destination": values.get("rclone_destination", "googledrive:backup"),
            "compress_password_configured": bool(values.get("compress_password")),
        }

    @app.post("/api/v1/utility/jobs", response_model=JobResponse)
    def submit_utility(body: UtilityJobRequest, actor=Depends(current_actor)):
        settings = context.utility_settings.get()
        payload = _model_dict(body)
        payload["settings"] = settings
        verify_target(actor, "utility", None, payload.get("worker"))
        return job_dict(
            context.control_plane.submit_job(
                actor, "utility", payload, profile=actor.profile, worker=payload.get("worker")
            )
        )

    @app.get("/api/v1/workers", response_model=WorkerListResponse)
    def list_workers(actor=Depends(current_actor)):
        return {
            "items": [
                {
                    "name": name,
                    "url": value["url"],
                    "enabled": bool(value.get("enabled", True)),
                    "selected": name
                    == context.profile_manager.worker_route(actor.profile),
                }
                for name, value in context.worker_registry.list().items()
            ]
        }

    @app.post("/api/v1/workers", response_model=ObjectResponse)
    def add_worker(body: WorkerRequest, actor=Depends(current_actor)):
        del actor
        name = context.worker_registry.upsert(
            body.name, body.url, body.token, enabled=body.enabled
        )
        return {"name": name}

    @app.put("/api/v1/workers/{name}", response_model=ObjectResponse)
    def update_worker(
        name: str, body: WorkerUpdateRequest, actor=Depends(current_actor)
    ):
        del actor
        current = context.worker_registry.get(name)
        if current is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        token = str(body.token or current.get("token") or "")
        return {
            "name": context.worker_registry.upsert(
                name, body.url, token, enabled=body.enabled
            )
        }

    @app.patch("/api/v1/workers/{name}", response_model=ObjectResponse)
    def set_worker_enabled(
        name: str, body: WorkerEnabledRequest, actor=Depends(current_actor)
    ):
        del actor
        if context.worker_registry.get(name) is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        context.worker_registry.set_enabled(name, body.enabled)
        return {"name": name, "enabled": bool(body.enabled)}

    @app.delete("/api/v1/workers/{name}", response_model=ObjectResponse)
    def remove_worker(name: str, actor=Depends(current_actor)):
        del actor
        if any(
            context.profile_manager.worker_route(profile) == name
            for profile in context.profile_manager.list_profiles()
        ):
            raise DomainError(
                "WORKER_IN_USE",
                "Worker masih digunakan oleh profile.",
                status_code=409,
            )
        return {"removed": context.worker_registry.remove(name)}

    @app.put("/api/v1/me/worker-route", response_model=ObjectResponse)
    def set_worker_route(body: WorkerRouteRequest, actor=Depends(current_actor)):
        return {"route": context.control_plane.set_worker_route(actor, body.route)}

    @app.get("/api/v1/storage/items", response_model=StorageItemListResponse)
    def search_storage(
        q: str = "",
        mine: bool = False,
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        owner = actor.telegram_user_id if mine else None
        items = [
                storage_item_dict(item)
                for item in context.storage_catalog.search(
                    q, owner_user_id=owner, limit=limit, offset=offset
                )
            ]
        return {"items": items, "total": context.storage_catalog.count(q, owner_user_id=owner)}

    @app.get("/api/v1/storage/browser", response_model=ObjectResponse)
    def storage_browser(
        folder_id: str = "root",
        scope: str = Query("current", pattern="^(current|global|recent|trash)$"),
        q: str = "",
        sort: str = Query("name", pattern="^(name|updated_at|size|type)$"),
        order: str = Query("asc", pattern="^(asc|desc)$"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        del actor
        try:
            parsed = None if folder_id in {"", "root", "null"} else int(folder_id)
            return context.storage_catalog.browser(
                parsed, scope=scope, query=q, sort=sort, order=order,
                limit=limit, offset=offset,
                retention_days=getattr(
                    context.config, "storage_trash_retention_days", 30
                ),
            )
        except (ValueError, KeyError) as exc:
            raise DomainError("STORAGE_FOLDER_INVALID", str(exc), status_code=400) from exc

    @app.get("/api/v1/storage/folders/tree", response_model=ItemListResponse)
    def storage_folder_tree(include_trash: bool = False, actor=Depends(current_actor)):
        del actor
        return {"items": context.storage_catalog.folder_tree(include_trash=include_trash)}

    @app.post("/api/v1/storage/folders", response_model=ObjectResponse)
    def create_storage_folder(body: StorageFolderRequest, actor=Depends(current_actor)):
        try:
            folder = context.storage_catalog.create_folder(
                body.name, actor.telegram_user_id, body.parent_id
            )
            return asdict(folder)
        except (ValueError, KeyError) as exc:
            raise DomainError("STORAGE_FOLDER_INVALID", str(exc), status_code=409) from exc

    @app.patch("/api/v1/storage/folders/{folder_id}", response_model=ObjectResponse)
    def update_storage_folder(
        folder_id: int, body: StorageFolderUpdateRequest, actor=Depends(current_actor)
    ):
        del actor
        try:
            values = _model_dict(body)
            folder = context.storage_catalog.move_folder(
                folder_id,
                values.get("parent_id"),
                name=values.get("name"),
                keep_parent="parent_id" not in getattr(body, "model_fields_set", getattr(body, "__fields_set__", set())),
            )
            return asdict(folder)
        except (ValueError, KeyError) as exc:
            raise DomainError("STORAGE_FOLDER_INVALID", str(exc), status_code=409) from exc

    @app.delete("/api/v1/storage/folders/{folder_id}", response_model=ObjectResponse)
    def trash_storage_folder(folder_id: int, actor=Depends(current_actor)):
        _require_storage_folders_idle(context, [folder_id])
        return {"folders": [asdict(item) for item in context.storage_catalog.trash_folders([folder_id], actor.telegram_user_id)]}

    @app.post("/api/v1/storage/folders/{folder_id}/restore", response_model=ObjectResponse)
    def restore_storage_folder(folder_id: int, actor=Depends(current_actor)):
        del actor
        return {"folders": [asdict(item) for item in context.storage_catalog.restore_folders([folder_id])]}

    @app.delete("/api/v1/storage/folders/{folder_id}/purge", response_model=ObjectResponse)
    def purge_storage_folder(folder_id: int, actor=Depends(current_actor)):
        del actor
        _require_storage_folders_idle(context, [folder_id])
        if context.storage_maintenance is None:
            raise DomainError("STORAGE_PURGE_UNAVAILABLE", "Layanan purge belum aktif.", status_code=503)
        return context.storage_maintenance.purge_folders([folder_id])

    @app.post("/api/v1/storage/actions/move", response_model=ObjectResponse)
    def move_storage_entries(body: StorageBulkActionRequest, actor=Depends(current_actor)):
        del actor
        try:
            items = context.storage_catalog.move_items(body.item_ids, body.destination_folder_id)
            folders = [
                context.storage_catalog.move_folder(folder_id, body.destination_folder_id)
                for folder_id in body.folder_ids
            ]
            return {"items": [storage_item_dict(item) for item in items], "folders": [asdict(folder) for folder in folders]}
        except (ValueError, KeyError) as exc:
            raise DomainError("STORAGE_MOVE_INVALID", str(exc), status_code=409) from exc

    @app.post("/api/v1/storage/actions/trash", response_model=ObjectResponse)
    def trash_storage_entries(body: StorageBulkActionRequest, actor=Depends(current_actor)):
        _require_storage_folders_idle(context, body.folder_ids)
        return {
            "items": [storage_item_dict(item) for item in context.storage_catalog.trash_items(body.item_ids, actor.telegram_user_id)],
            "folders": [asdict(folder) for folder in context.storage_catalog.trash_folders(body.folder_ids, actor.telegram_user_id)],
        }

    @app.post("/api/v1/storage/actions/restore", response_model=ObjectResponse)
    def restore_storage_entries(body: StorageBulkActionRequest, actor=Depends(current_actor)):
        del actor
        return {
            "items": [storage_item_dict(item) for item in context.storage_catalog.restore_items(body.item_ids)],
            "folders": [asdict(folder) for folder in context.storage_catalog.restore_folders(body.folder_ids)],
        }

    @app.post("/api/v1/storage/actions/purge", response_model=ObjectResponse)
    def purge_storage_entries(body: StorageBulkActionRequest, actor=Depends(current_actor)):
        del actor
        _require_storage_folders_idle(context, body.folder_ids)
        if context.storage_maintenance is None:
            raise DomainError("STORAGE_PURGE_UNAVAILABLE", "Layanan purge belum aktif.", status_code=503)
        return context.storage_maintenance.purge(body.item_ids, body.folder_ids)

    @app.get("/api/v1/storage/settings", response_model=StorageSettingsResponse)
    def storage_settings(actor=Depends(current_actor)):
        del actor
        title = "-"
        if context.bot is not None and context.config.storage_channel_id:
            try:
                chat = context.bot.get_chat(context.config.storage_channel_id)
                title = str(
                    getattr(chat, "title", None)
                    or getattr(chat, "username", None)
                    or context.config.storage_channel_id
                )
            except Exception:
                title = str(context.config.storage_channel_id)
        return {
            "channel": context.config.storage_channel,
            "channel_id": context.config.storage_channel_id,
            "title": title,
        }

    @app.get("/api/v1/storage/items/{item_id}", response_model=StorageItemResponse)
    def get_storage_item(item_id: int, actor=Depends(current_actor)):
        del actor
        return storage_item_dict(_storage_item(context, item_id))

    @app.post("/api/v1/storage/uploads", response_model=JobResponse)
    def submit_storage_upload(body: StorageUploadRequest, actor=Depends(current_actor)):
        payload = _model_dict(body)
        if payload.get("rclone_upload"):
            # Snapshot the destination at enqueue time. The rclone config is
            # never sent through the browser or persisted in the API payload.
            payload["rclone_destination"] = context.utility_settings.get().get(
                "rclone_destination", "googledrive:backup"
            )
        verify_target(actor, "storage", None, payload.get("worker"))
        if payload.get("destination_folder_id") is None and payload.get("folder"):
            folder = context.storage_catalog.ensure_path(
                str(payload["folder"]), actor.telegram_user_id
            )
            payload["destination_folder_id"] = folder.id if folder else None
        destination = payload.get("destination_folder_id")
        if destination is not None:
            selected = context.storage_catalog.get_folder(int(destination))
            if selected is None or selected.status != "active":
                raise DomainError("STORAGE_FOLDER_INVALID", "Folder tujuan tidak aktif.", status_code=409)
        payload["destination_folder_path"] = context.storage_catalog.folder_path(destination)
        _, selected_worker = context.control_plane.resolve_target(actor, worker=payload.get("worker"))
        payload.update(
            {
                "batch_id": str(uuid.uuid4()),
                "owner_user_id": actor.telegram_user_id,
                "owner_profile": actor.profile,
            }
        )
        return job_dict(
            context.control_plane.submit_job(
                actor, "storage_upload", payload, profile=actor.profile, worker=selected_worker
            )
        )

    @app.patch(
        "/api/v1/storage/items/{item_id}",
        response_model=StorageItemResponse,
    )
    def update_storage_item(
        item_id: int, body: StorageUpdateRequest, actor=Depends(current_actor)
    ):
        values = _model_dict(body)
        item = _storage_item(context, item_id)
        changes_owned_metadata = values.get("folder") is not None or values.get("keywords") is not None
        if values.get("display_name") is not None:
            item = context.storage_catalog.rename(item_id, values["display_name"])
        if changes_owned_metadata:
            item = context.storage_catalog.update_metadata(
                item_id,
                item.owner_user_id,
                folder=values.get("folder"),
                keywords=values.get("keywords"),
            )
        caption = build_storage_caption(item.folder, item.display_name, item.keywords)
        context.storage_catalog.enqueue_caption(item.id, caption)
        return storage_item_dict(item)

    @app.delete(
        "/api/v1/storage/items/{item_id}",
        response_model=StorageItemResponse,
    )
    def delete_storage_item(item_id: int, actor=Depends(current_actor)):
        _storage_item(context, item_id)
        return storage_item_dict(
            context.storage_catalog.trash_items([item_id], actor.telegram_user_id)[0]
        )

    @app.post("/api/v1/storage/items/{item_id}/restore", response_model=StorageItemResponse)
    def restore_storage_item(item_id: int, actor=Depends(current_actor)):
        del actor
        items = context.storage_catalog.restore_items([item_id])
        if not items:
            raise DomainError("STORAGE_ITEM_NOT_FOUND", "Item Trash tidak ditemukan.", status_code=404)
        return storage_item_dict(items[0])

    @app.delete("/api/v1/storage/items/{item_id}/purge", response_model=ObjectResponse)
    def purge_storage_item(item_id: int, actor=Depends(current_actor)):
        del actor
        if context.storage_maintenance is None:
            raise DomainError("STORAGE_PURGE_UNAVAILABLE", "Layanan purge belum aktif.", status_code=503)
        return context.storage_maintenance.purge([item_id], [])

    @app.post(
        "/api/v1/storage/items/{item_id}/deliveries",
        response_model=ObjectResponse,
    )
    def deliver_storage_item(
        item_id: int, body: StorageDeliveryRequest, actor=Depends(current_actor)
    ):
        if body.method != "telegram":
            raise DomainError(
                "DELIVERY_UNSUPPORTED",
                "Metode delivery belum didukung.",
                status_code=400,
            )
        item = _active_storage_item(context, item_id)
        return _deliver_storage_telegram(context, item, actor.telegram_user_id)

    @app.get(
        "/api/v1/storage/items/{item_id}/deep-link",
        response_model=ObjectResponse,
    )
    def storage_deep_link(item_id: int, actor=Depends(current_actor)):
        del actor
        _active_storage_item(context, item_id)
        token = sign_storage_item(item_id, context.config.auth_jwt_secret)
        return {
            "code": token,
            "url": f"https://t.me/{context.config.bot_username}?start=storage_{token}"
        }

    @app.post(
        "/api/v1/storage/deep-links/{token}/deliver",
        response_model=ObjectResponse,
    )
    def deliver_storage_deep_link(token: str, actor=Depends(current_actor)):
        try:
            item_id = verify_storage_item(token, context.config.auth_jwt_secret)
        except ValueError as exc:
            raise DomainError(
                "STORAGE_LINK_INVALID", str(exc), status_code=400
            ) from exc
        item = _active_storage_item(context, item_id)
        return _deliver_storage_telegram(context, item, actor.telegram_user_id)

    @app.post(
        "/internal/v1/storage/deep-links/{token}/deliver",
        include_in_schema=False,
        response_model=ObjectResponse,
        dependencies=[Depends(require_service)],
    )
    def deliver_public_storage_deep_link(
        token: str, body: TelegramStorageDeliveryRequest
    ):
        """Capability-link delivery; does not grant an application actor."""
        try:
            item_id = verify_storage_item(token, context.config.auth_jwt_secret)
        except ValueError as exc:
            raise DomainError(
                "STORAGE_LINK_INVALID", str(exc), status_code=400
            ) from exc
        item = _active_storage_item(context, item_id)
        return _deliver_storage_telegram(context, item, body.telegram_user_id)

    @app.get("/api/v1/backups", response_model=ItemListResponse)
    def list_backups(actor=Depends(current_actor)):
        del actor
        return {"items": context.storage_catalog.backup_runs(limit=50)}

    @app.get("/api/v1/backups/status", response_model=ObjectResponse)
    def backup_status(actor=Depends(current_actor)):
        del actor
        return {
            "enabled": context.config.backup_enabled,
            "schedule": context.config.backup_schedule,
            "timezone": context.config.backup_timezone,
            "retention": context.config.backup_retention,
            "volume_size": context.config.backup_volume_size,
            "channel": context.config.backup_channel,
            "items": context.storage_catalog.backup_runs(limit=20),
        }

    @app.post("/api/v1/backups", response_model=ObjectResponse)
    def start_backup(actor=Depends(current_actor)):
        if context.backup_coordinator is not None:
            return {"run_id": context.backup_coordinator.start_now()}
        jobs = []
        password = context.utility_settings.get().get("compress_password", "")
        run_id = str(uuid.uuid4())
        for worker in context.worker_registry.names():
            jobs.append(
                job_dict(
                    context.control_plane.submit_job(
                        actor,
                        "backup_node",
                        {
                            "backup_run_id": run_id,
                            "node_name": worker,
                            "password": password,
                            "channel_ref": context.config.backup_channel_ref,
                            "channel_id": context.config.backup_channel_id,
                            "volume_size": context.config.backup_volume_size,
                        },
                        profile=actor.profile,
                        worker=worker,
                    )
                )
            )
        return {"run_id": run_id, "jobs": jobs}

    @app.post(
        "/internal/v1/jobs/{job_id}/events",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def worker_event(job_id: str, body: WorkerEventRequest):
        try:
            status = JobStatus(body.status)
        except ValueError as exc:
            raise DomainError(
                "INVALID_JOB_STATUS", "Status job tidak valid.", status_code=422
            ) from exc
        event = JobEvent(
            job_id=job_id,
            sequence=body.sequence,
            status=status,
            event_type=body.event_type,
            progress=body.progress,
            result=body.result,
            error=body.error,
        )
        job = (
            context.control_plane.update_worker_progress(event)
            if body.transient
            else context.control_plane.append_worker_event(event)
        )
        return {"ok": True, "job": job_dict(job)}

    _add_internal_state_routes(app, context, require_internal)
    _add_management_routes(app, context, require_management)
    return app


def _owned_job(context: BackendContext, actor, job_id: str) -> Job:
    job = context.control_plane.jobs.get(job_id)
    if job is None:
        raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
    context.control_plane.require_profile(actor, job.profile)
    return job


def _storage_item(context: BackendContext, item_id: int):
    item = context.storage_catalog.get(item_id)
    if item is None:
        raise DomainError(
            "STORAGE_ITEM_NOT_FOUND", "File storage tidak ditemukan.", status_code=404
        )
    return item


def _active_storage_item(context: BackendContext, item_id: int):
    item = _storage_item(context, item_id)
    if str(getattr(item, "status", "")) != "active" or getattr(
        item, "trashed_at", None
    ):
        raise DomainError(
            "STORAGE_ITEM_UNAVAILABLE",
            "File storage tidak lagi tersedia untuk dikirim.",
            status_code=410,
        )
    return item


def _deliver_storage_telegram(context: BackendContext, item, telegram_user_id: int):
    if context.bot is None:
        raise DomainError(
            "DELIVERY_UNAVAILABLE",
            "Telegram delivery adapter belum aktif.",
            status_code=503,
        )
    try:
        message = context.bot.copy_message(
            chat_id=int(telegram_user_id),
            from_chat_id=item.channel_id,
            message_id=item.channel_message_id,
        )
    except Exception as exc:
        raise DomainError(
            "STORAGE_DELIVERY_FAILED",
            "File Telegram tidak dapat dikirim. Pesan channel mungkin sudah tidak tersedia.",
            status_code=502,
        ) from exc
    return {
        "method": "telegram",
        "destination": int(telegram_user_id),
        "message_id": getattr(message, "message_id", None),
        "display_name": item.display_name,
    }


def _require_storage_folders_idle(context: BackendContext, folder_ids: list[int]) -> None:
    if not folder_ids:
        return
    for status in ("queued", "dispatched", "running"):
        for job in context.control_plane.jobs.list(
            kind="storage_upload", status=status, limit=200
        ):
            destination = job.payload.get("destination_folder_id")
            if destination is None:
                continue
            if any(
                context.storage_catalog.is_ancestor(folder_id, int(destination))
                for folder_id in folder_ids
            ):
                raise DomainError(
                    "FOLDER_BUSY",
                    "Folder sedang menjadi tujuan upload aktif.",
                    status_code=409,
                )


def _profile_artifact(context: BackendContext, actor, artifact_id: str):
    if context.export_catalog is None:
        raise DomainError(
            "ARTIFACT_CATALOG_UNAVAILABLE",
            "Katalog export belum tersedia.",
            status_code=503,
        )
    item = context.export_catalog.get(artifact_id)
    if item is None:
        raise DomainError(
            "ARTIFACT_NOT_FOUND", "Artifact tidak ditemukan.", status_code=404
        )
    context.control_plane.require_profile(actor, str(item["profile"]))
    return item


def _add_internal_state_routes(app: FastAPI, context: BackendContext, require_internal):
    prefix = "/internal/v1/profiles/{profile}/state"

    @app.post(
        "/internal/v1/profiles/sync",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    async def sync_profiles(request: Request):
        body = await request.json()
        profiles = body.get("profiles", []) if isinstance(body, dict) else []
        registry = getattr(context.profile_manager, "profile_registry", None)
        if registry is None:
            raise DomainError("PROFILE_REGISTRY_UNAVAILABLE", "Registry profile backend tidak tersedia.", status_code=503)
        synced: list[str] = []
        for item in profiles:
            if not isinstance(item, dict):
                continue
            try:
                synced.append(registry.register(item.get("name", ""), item.get("telegram_user_id")))
            except (TypeError, ValueError) as exc:
                raise DomainError("PROFILE_SYNC_INVALID", str(exc), status_code=422) from exc
        return {"profiles": sorted(set(synced))}

    @app.get(
        prefix + "/sources",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def state_sources(profile: str):
        store = context.profile_manager.runtime(profile).state_store
        return {
            "sources": {
                key: value.to_dict() for key, value in store.list_sources()
            }
        }

    @app.get(
        prefix + "/source",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def state_source(profile: str, chat_ref: str):
        source = context.profile_manager.runtime(profile).state_store.get_source(chat_ref)
        return {"source": source.to_dict() if source else None}

    @app.post(
        prefix + "/source",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    async def state_upsert(profile: str, request: Request):
        body = await request.json()
        source = context.profile_manager.runtime(profile).state_store.upsert_source(
            body["chat_ref"],
            body.get("label"),
            int(body["last_id"]),
            body.get("warmup_url"),
            body.get("warmup_done"),
        )
        return {"source": source.to_dict()}

    @app.post(
        prefix + "/warmup",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    async def state_warmup(profile: str, request: Request):
        body = await request.json()
        context.profile_manager.runtime(profile).state_store.mark_warmup_done(
            body["chat_ref"]
        )
        return {"ok": True}

    @app.post(
        prefix + "/delete",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    async def state_delete(profile: str, request: Request):
        body = await request.json()
        deleted = context.profile_manager.runtime(profile).state_store.delete_sources(
            body.get("chat_refs", [])
        )
        return {"deleted": deleted}


def _add_management_routes(
    app: FastAPI, context: BackendContext, require_management
):
    @app.get(
        "/internal/v1/management/workers",
        include_in_schema=False,
        dependencies=[Depends(require_management)],
    )
    def management_workers():
        return {
            "items": [
                {"name": name, **value}
                for name, value in context.worker_registry.list().items()
            ]
        }

    @app.post(
        "/internal/v1/management/workers",
        include_in_schema=False,
        dependencies=[Depends(require_management)],
    )
    def management_add_worker(body: WorkerRequest):
        return {
            "name": context.worker_registry.upsert(
                body.name, body.url, body.token, enabled=body.enabled
            )
        }

    @app.delete(
        "/internal/v1/management/workers/{name}",
        include_in_schema=False,
        dependencies=[Depends(require_management)],
    )
    def management_remove_worker(name: str):
        return {"removed": context.worker_registry.remove(name)}

    @app.post(
        "/internal/v1/management/backups",
        include_in_schema=False,
        dependencies=[Depends(require_management)],
    )
    def management_start_backup():
        if context.backup_coordinator is None:
            raise DomainError(
                "BACKUP_UNAVAILABLE",
                "Backup coordinator belum memiliki identity.",
                status_code=503,
            )
        return {"run_id": context.backup_coordinator.start_now()}

    @app.get(
        "/internal/v1/management/backups",
        include_in_schema=False,
        dependencies=[Depends(require_management)],
    )
    def management_list_backups():
        return {"items": context.storage_catalog.backup_runs(limit=100)}

    @app.get(
        "/internal/v1/management/backups/status",
        include_in_schema=False,
        dependencies=[Depends(require_management)],
    )
    def management_backup_status():
        return {
            "items": context.storage_catalog.backup_runs(limit=20),
            "enabled": context.config.backup_enabled,
            "schedule": context.config.backup_schedule,
            "timezone": context.config.backup_timezone,
        }
