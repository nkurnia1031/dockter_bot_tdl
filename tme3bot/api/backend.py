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


def _newest_first_log_response(value: Any) -> dict[str, Any]:
    """Normalize current and legacy worker snapshots for the public API."""
    response = dict(value) if isinstance(value, dict) else {}
    raw_log = response.get("log")
    log = dict(raw_log) if isinstance(raw_log, dict) else {}
    lines = log.get("lines")
    if not isinstance(lines, list):
        lines = []
    if log.get("order") != "newest_first":
        lines = list(reversed(lines))
    log["lines"] = lines
    try:
        log["line_count"] = int(log.get("line_count") or len(lines))
    except (TypeError, ValueError):
        log["line_count"] = len(lines)
    log["truncated"] = bool(log.get("truncated"))
    log["order"] = "newest_first"
    response["log"] = log
    return response


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
        JobStatus.PAUSED,
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

    from tme3bot.api.routes.jobs import register_jobs
    register_jobs(
        app,
        context,
        _newest_first_log_response=_newest_first_log_response,
        _owned_job=_owned_job,
        current_actor=current_actor,
        event_dict=event_dict,
        job_dict=job_dict,
        require_internal=require_internal,
        require_service=require_service,
    )


    from tme3bot.api.routes.sources import register_sources
    register_sources(
        app,
        context,
        _model_dict=_model_dict,
        current_actor=current_actor,
        job_dict=job_dict,
        verify_target=verify_target,
    )


    from tme3bot.api.routes.downloads import register_downloads
    register_downloads(
        app,
        context,
        _model_dict=_model_dict,
        _profile_artifact=_profile_artifact,
        current_actor=current_actor,
        job_dict=job_dict,
    )


    from tme3bot.api.routes.utility import register_utility
    register_utility(
        app,
        context,
        _model_dict=_model_dict,
        current_actor=current_actor,
        job_dict=job_dict,
        verify_target=verify_target,
    )


    from tme3bot.api.routes.workers import register_workers
    register_workers(
        app,
        context,
        current_actor=current_actor,
    )


    from tme3bot.api.routes.storage import register_storage
    register_storage(
        app,
        context,
        _active_storage_item=_active_storage_item,
        _deliver_storage_telegram=_deliver_storage_telegram,
        _model_dict=_model_dict,
        _require_storage_folders_idle=_require_storage_folders_idle,
        _storage_item=_storage_item,
        current_actor=current_actor,
        job_dict=job_dict,
        require_service=require_service,
        verify_target=verify_target,
    )


    from tme3bot.api.routes.backups import register_backups
    register_backups(
        app,
        context,
        current_actor=current_actor,
        job_dict=job_dict,
    )



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
