from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
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
from tme3bot.api.routes.devices import register_device_routes
from tme3bot.domain.models import Actor, DomainError, Job, JobEvent, JobStatus
from tme3bot.domain.worker_contract import CAP_SHARED_EXPORT_CURSOR, require_worker_contract
from tme3bot.chat_refs import normalize_tdl_chat_ref
from tme3bot.profile_provisioning import profile_transfer_is_secure
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
    runtime_settings: Any = None
    runtime_settings_store: Any = None
    backup_scheduler: Any = None
    profile_provisioner: Any = None
    device_auth: Any = None
    source_repository: Any = None
    operation_service: Any = None
    queue_command_service: Any = None
    queue_publisher: Any = None


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
        "settings_version": job.settings_version,
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
        errors = exc.errors()
        sensitive_request = (
            request.url.path == "/api/v1/tts/jobs"
            or request.url.path.startswith("/api/v1/operations")
            or request.url.path == "/api/v1/runtime/secrets"
            or request.url.path.startswith("/api/v1/workers/")
            and request.url.path.endswith("/settings")
            or request.url.path.startswith("/api/v1/profiles/provisionings")
            or request.url.path.startswith("/api/v1/auth/devices")
            or request.url.path.startswith("/api/v1/auth/device/")
        )
        if sensitive_request:
            # Pydantic versions that include rejected input in error details
            # must not echo novel text, tokens, or passwords to the caller.
            errors = [
                {key: value for key, value in error.items() if key != "input"}
                for error in errors
            ]
        return _error(
            request,
            "VALIDATION_ERROR",
            "Payload request tidak valid.",
            status_code=422,
            details={"errors": errors},
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

    from tme3bot.api.routes.runtime_settings import register_runtime_settings
    register_runtime_settings(
        app,
        context,
        current_actor=current_actor,
        require_service=require_service,
        require_internal=require_internal,
    )

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
            except DomainError as exc:
                if exc.code == "WORKER_INCOMPATIBLE":
                    raise
                raise DomainError(
                    "WORKER_OFFLINE",
                    f"Worker {selected_worker} tidak dapat diverifikasi: {exc}",
                    status_code=503,
                ) from exc
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
            "storage_profile": storage_profile if quick_mode else None,
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

    @app.get("/api/v1/profiles/management")
    def profile_management(actor=Depends(current_actor)):
        provisioner = context.profile_provisioner
        if provisioner is None:
            raise DomainError("PROFILE_PROVISIONING_UNAVAILABLE", "Provisioning profil belum aktif.", status_code=503)
        registered_workers = context.worker_registry.list()
        checker = getattr(context.worker_dispatcher, "check_worker_fast", None)
        if not callable(checker):
            checker = getattr(context.worker_dispatcher, "check_worker", None)

        def online_status(name: str) -> tuple[str, bool]:
            try:
                online = bool(checker(name).get("healthy", True)) if callable(checker) else False
            except Exception:
                online = False
            return name, online

        names = list(registered_workers)
        online_by_name: dict[str, bool] = {}
        if names:
            with ThreadPoolExecutor(max_workers=min(8, len(names))) as executor:
                online_by_name.update(executor.map(online_status, names))

        workers = []
        for name, item in registered_workers.items():
            secure = profile_transfer_is_secure(str(item.get("url") or ""))
            workers.append({
                "name": name,
                "enabled": bool(item.get("enabled", True)),
                "online": online_by_name.get(name, False),
                "secure": secure,
            })
        return {
            "items": provisioner.profiles(actor.telegram_user_id),
            "workers": workers,
        }

    @app.post("/api/v1/profiles/provisionings/upload")
    async def upload_profile_session(
        request: Request,
        name: str = Query(..., min_length=1, max_length=48),
        worker: str = Query(..., min_length=1, max_length=48),
        actor=Depends(current_actor),
    ):
        provisioner = context.profile_provisioner
        if provisioner is None:
            raise DomainError("PROFILE_PROVISIONING_UNAVAILABLE", "Provisioning profil belum aktif.", status_code=503)
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > 128 * 1024 * 1024:
                raise DomainError("PROFILE_ARCHIVE_TOO_LARGE", "ZIP sesi melebihi batas 128 MiB.", status_code=413)
            chunks.append(chunk)
        try:
            operation_id = provisioner.upload(name, worker, b"".join(chunks), actor.telegram_user_id)
        except FileExistsError as exc:
            raise DomainError("PROFILE_EXISTS", str(exc), status_code=409) from exc
        except KeyError as exc:
            raise DomainError("WORKER_NOT_FOUND", "Worker bootstrap tidak ditemukan.", status_code=404) from exc
        except ValueError as exc:
            raise DomainError("PROFILE_SESSION_INVALID", str(exc), status_code=422) from exc
        except Exception as exc:
            raise DomainError("PROFILE_PROVISIONING_FAILED", "Worker tidak dapat memvalidasi sesi profil.", status_code=503) from exc
        return {"id": operation_id, "status": "distributing"}

    @app.post("/api/v1/profiles/provisionings/login")
    def start_profile_login(request: Request, body: dict[str, Any], actor=Depends(current_actor)):
        provisioner = context.profile_provisioner
        if provisioner is None:
            raise DomainError("PROFILE_PROVISIONING_UNAVAILABLE", "Provisioning profil belum aktif.", status_code=503)
        try:
            operation_id = provisioner.start_login(
                str(body.get("name") or ""),
                str(body.get("worker") or ""),
                str(body.get("method") or ""),
                str(body.get("phone") or ""),
                actor.telegram_user_id,
            )
        except FileExistsError as exc:
            raise DomainError("PROFILE_EXISTS", str(exc), status_code=409) from exc
        except KeyError as exc:
            raise DomainError("WORKER_NOT_FOUND", "Worker bootstrap tidak ditemukan.", status_code=404) from exc
        except ValueError as exc:
            raise DomainError("PROFILE_LOGIN_INVALID", str(exc), status_code=422) from exc
        except Exception as exc:
            raise DomainError("PROFILE_WORKER_UNAVAILABLE", "Worker login TDL tidak dapat dihubungi.", status_code=503) from exc
        return {"id": operation_id, "status": "authenticating"}

    @app.get("/api/v1/profiles/provisionings/{operation_id}")
    def profile_provisioning_state(operation_id: str, actor=Depends(current_actor)):
        if context.profile_provisioner is None:
            raise DomainError("PROFILE_PROVISIONING_UNAVAILABLE", "Provisioning profil belum aktif.", status_code=503)
        try:
            return context.profile_provisioner.operation(operation_id, actor.telegram_user_id)
        except KeyError as exc:
            raise DomainError("PROFILE_PROVISIONING_NOT_FOUND", "Provisioning tidak ditemukan.", status_code=404) from exc
        except PermissionError as exc:
            raise DomainError("PROFILE_PROVISIONING_FORBIDDEN", "Provisioning dimiliki actor lain.", status_code=403) from exc
        except ValueError as exc:
            raise DomainError("PROFILE_PROVISIONING_FAILED", str(exc), status_code=409) from exc
        except Exception as exc:
            raise DomainError("PROFILE_WORKER_UNAVAILABLE", "Worker login belum dapat dihubungi.", status_code=503) from exc

    @app.get("/api/v1/profiles/provisionings/{operation_id}/logs")
    def profile_provisioning_logs(
        operation_id: str,
        limit: int = Query(500, ge=1, le=500),
        actor=Depends(current_actor),
    ):
        provisioner = context.profile_provisioner
        if provisioner is None:
            raise DomainError("PROFILE_PROVISIONING_UNAVAILABLE", "Log provisioning belum tersedia.", status_code=503)
        items = provisioner.store.provisioning_logs(operation_id, actor.telegram_user_id, limit)
        if items is None:
            raise DomainError("PROFILE_PROVISIONING_NOT_FOUND", "Provisioning tidak ditemukan.", status_code=404)
        return {"items": items}

    @app.get("/api/v1/diagnostics/profile-exports/logs")
    def profile_export_diagnostic_logs(
        limit: int = Query(100, ge=1, le=500), actor=Depends(current_actor)
    ):
        provisioner = context.profile_provisioner
        if provisioner is None:
            raise DomainError("DIAGNOSTIC_LOGS_UNAVAILABLE", "Log diagnosis belum tersedia.", status_code=503)
        return {"items": provisioner.store.diagnostic_logs(actor.telegram_user_id, "profile_export", limit)}

    @app.post("/api/v1/profiles/provisionings/{operation_id}/input")
    def profile_login_input(operation_id: str, body: dict[str, Any], actor=Depends(current_actor)):
        if context.profile_provisioner is None:
            raise DomainError("PROFILE_PROVISIONING_UNAVAILABLE", "Provisioning profil belum aktif.", status_code=503)
        try:
            return context.profile_provisioner.login_input(
                operation_id, actor.telegram_user_id,
                str(body.get("field") or ""), str(body.get("value") or ""),
            )
        except KeyError as exc:
            raise DomainError("PROFILE_PROVISIONING_NOT_FOUND", "Provisioning tidak ditemukan.", status_code=404) from exc
        except PermissionError as exc:
            raise DomainError("PROFILE_PROVISIONING_FORBIDDEN", "Provisioning dimiliki actor lain.", status_code=403) from exc
        except ValueError as exc:
            raise DomainError("PROFILE_LOGIN_INPUT_INVALID", str(exc), status_code=422) from exc
        except Exception as exc:
            raise DomainError("PROFILE_WORKER_UNAVAILABLE", "Worker login TDL tidak dapat dihubungi.", status_code=503) from exc

    @app.post("/api/v1/profiles/provisionings/{operation_id}/retry")
    def retry_profile_provisioning(
        operation_id: str, body: dict[str, Any] | None = None, actor=Depends(current_actor)
    ):
        if context.profile_provisioner is None:
            raise DomainError("PROFILE_PROVISIONING_UNAVAILABLE", "Provisioning profil belum aktif.", status_code=503)
        try:
            context.profile_provisioner.retry(
                operation_id,
                actor.telegram_user_id,
                str((body or {}).get("worker") or "") or None,
            )
        except KeyError as exc:
            raise DomainError("PROFILE_PROVISIONING_NOT_FOUND", "Provisioning tidak ditemukan.", status_code=404) from exc
        except PermissionError as exc:
            raise DomainError("PROFILE_PROVISIONING_FORBIDDEN", "Provisioning dimiliki actor lain.", status_code=403) from exc
        except ValueError as exc:
            raise DomainError("PROFILE_PROVISIONING_RETRY_INVALID", str(exc), status_code=409) from exc
        return {"retried": True}

    @app.delete("/api/v1/profiles/provisionings/{operation_id}")
    def cancel_profile_provisioning(operation_id: str, actor=Depends(current_actor)):
        if context.profile_provisioner is None:
            raise DomainError("PROFILE_PROVISIONING_UNAVAILABLE", "Provisioning profil belum aktif.", status_code=503)
        try:
            return context.profile_provisioner.cancel(operation_id, actor.telegram_user_id)
        except KeyError as exc:
            raise DomainError("PROFILE_PROVISIONING_NOT_FOUND", "Provisioning tidak ditemukan.", status_code=404) from exc
        except PermissionError as exc:
            raise DomainError("PROFILE_PROVISIONING_FORBIDDEN", "Provisioning dimiliki actor lain.", status_code=403) from exc
        except ValueError as exc:
            raise DomainError("PROFILE_CANNOT_CANCEL", str(exc), status_code=409) from exc

    @app.post("/api/v1/profiles/{profile}/adopt")
    def adopt_profile(profile: str, body: dict[str, Any], actor=Depends(current_actor)):
        provisioner = context.profile_provisioner
        if provisioner is None:
            raise DomainError("PROFILE_PROVISIONING_UNAVAILABLE", "Provisioning profil belum aktif.", status_code=503)
        try:
            operation_id = provisioner.adopt(profile, str(body.get("worker") or ""), actor.telegram_user_id)
        except FileExistsError as exc:
            raise DomainError("PROFILE_ALREADY_VAULTED", str(exc), status_code=409) from exc
        except KeyError as exc:
            raise DomainError("PROFILE_OR_WORKER_NOT_FOUND", "Profil atau worker sumber tidak ditemukan.", status_code=404) from exc
        except ValueError as exc:
            raise DomainError("PROFILE_ADOPTION_INVALID", str(exc), status_code=409) from exc
        except Exception as exc:
            raise DomainError("PROFILE_WORKER_UNAVAILABLE", "Worker sumber tidak dapat mengekspor sesi profil.", status_code=503) from exc
        return {"id": operation_id, "status": "validating"}

    @app.post("/api/v1/profiles/{profile}/adoption-diagnostics")
    def diagnose_profile_adoption(profile: str, body: dict[str, Any], actor=Depends(current_actor)):
        provisioner = context.profile_provisioner
        if provisioner is None:
            raise DomainError("PROFILE_PROVISIONING_UNAVAILABLE", "Provisioning profil belum aktif.", status_code=503)
        try:
            return provisioner.diagnose_adoption(
                profile,
                str(body.get("worker") or ""),
                actor.telegram_user_id,
            )
        except FileExistsError as exc:
            raise DomainError("PROFILE_ALREADY_VAULTED", str(exc), status_code=409) from exc
        except KeyError as exc:
            raise DomainError("PROFILE_OR_WORKER_NOT_FOUND", "Profil atau worker sumber tidak ditemukan.", status_code=404) from exc
        except ValueError as exc:
            raise DomainError("PROFILE_ADOPTION_INVALID", str(exc), status_code=409) from exc


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


    from tme3bot.api.routes.tts import register_tts
    register_tts(
        app,
        context,
        current_actor=current_actor,
        job_dict=job_dict,
        require_internal=require_internal,
        require_service=require_service,
    )

    from tme3bot.api.routes.tdl_access import register_tdl_access
    register_tdl_access(
        app,
        context,
        current_actor=current_actor,
        require_internal=require_internal,
    )


    from tme3bot.api.routes.safelink import register_safelink
    register_safelink(
        app,
        context,
        current_actor=current_actor,
        job_dict=job_dict,
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



    _add_internal_state_routes(
        app, context, require_internal, current_actor=current_actor
    )
    _add_management_routes(app, context, require_management)
    register_device_routes(
        app,
        context,
        current_actor=current_actor,
        set_session=_set_session,
        browser_actor_dict=browser_actor_dict,
    )
    from tme3bot.api.routes.operations import register_operations
    operations = context.operation_service
    if (
        operations is not None
        and context.queue_publisher is not None
        and context.queue_command_service is not None
    ):
        from tme3bot.api.routes.profile_sync import (
            advance_profile_sync_cancel,
            advance_profile_sync_command,
            prepare_profile_sync_operation,
        )

        def prepare_background_job(actor, target, input_data):
            job_kind = str(input_data.get("job_kind") or "").strip().lower()
            if job_kind == "tts":
                settings = (
                    context.runtime_settings.get()
                    if context.runtime_settings is not None
                    else {}
                )
                chat_ref = str(
                    settings.get("telegram_tts_chat_id")
                    if "telegram_tts_chat_id" in settings
                    else getattr(context.config, "telegram_tts_chat_id", "")
                ).strip()
                if not chat_ref:
                    raise DomainError(
                        "TTS_CHAT_UNAVAILABLE",
                        "Chat tujuan TTS belum dikonfigurasi.",
                        status_code=503,
                    )
            return context.control_plane.prepare_durable_job(
                actor, target, input_data
            )

        def advance_background_job(command):
            result = context.control_plane.advance_durable_job(command)
            if result.get("status") in {"wait", "retry"}:
                private = command.get("private_payload")
                if isinstance(private, dict) and private.get("job_id"):
                    operations.mark_waiting_worker_for_job(str(private["job_id"]))
            return result

        def advance_accepted_operation(command):
            if command.get("kind") == "profile.sync":
                return advance_profile_sync_command(command, context)
            return advance_background_job(command)

        def advance_retry_operation(command):
            if command.get("kind") == "profile.sync":
                return advance_profile_sync_command(command, context)
            return advance_background_job(command)

        def advance_cancel_operation(command):
            if command.get("kind") == "profile.sync":
                return advance_profile_sync_cancel(command, context)
            return context.control_plane.advance_durable_cancel(command)

        operations.register_handler("job.submit", prepare_background_job)
        operations.register_handler(
            "profile.sync",
            lambda actor, target, input_data: prepare_profile_sync_operation(
                context, actor, target, input_data
            ),
        )
        operations.register_command_handler(
            "operation.accepted", advance_accepted_operation
        )
        operations.register_command_handler(
            "operation.retry", advance_retry_operation
        )
        operations.register_command_handler(
            "operation.cancel", advance_cancel_operation
        )
    register_operations(
        app,
        operations,
        current_actor=current_actor,
    )
    from tme3bot.api.routes.queue import register_queue
    register_queue(app, context, require_internal=require_internal)
    # Queue advancement is an authenticated control-plane endpoint, not part
    # of the public API contract. Keep it out of the generated client schema.
    for route in app.routes:
        if getattr(route, "path", "") == "/internal/v1/queue/commands/{command_id}/advance":
            route.include_in_schema = False
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


def _add_internal_state_routes(
    app: FastAPI, context: BackendContext, require_internal, *, current_actor
):
    from tme3bot.api.routes.profile_sync import register_profile_sync

    register_profile_sync(
        app,
        context,
        require_internal=require_internal,
        current_actor=current_actor,
    )

    cursor_service = None
    if context.source_repository is not None:
        from tme3bot.application.export_cursor import ExportCursorService

        cursor_service = getattr(context.control_plane, "export_cursor_service", None)
        if cursor_service is None:
            cursor_service = ExportCursorService(
                context.source_repository,
                context.export_catalog,
                context.control_plane.jobs,
            )
            context.control_plane.export_cursor_service = cursor_service

    def require_cursor_service():
        if cursor_service is None:
            raise DomainError(
                "EXPORT_CURSOR_UNAVAILABLE",
                "Repository cursor export belum tersedia.",
                status_code=503,
            )
        if not cursor_service.enabled:
            raise DomainError(
                "EXPORT_CURSOR_DISABLED",
                "Shared export cursor belum diaktifkan untuk worker yang kompatibel.",
                status_code=409,
            )
        return cursor_service

    @app.get("/api/v1/peer-aliases/pending")
    def pending_peer_aliases(profile: str | None = None, actor=Depends(current_actor)):
        if context.source_repository is None:
            raise DomainError("EXPORT_CURSOR_UNAVAILABLE", "Repository cursor export belum tersedia.", status_code=503)
        selected_profile = context.control_plane.require_profile(actor, profile)
        return {
            "items": context.source_repository.list_peer_alias_candidates(selected_profile)
        }

    @app.post("/api/v1/peer-aliases/confirm")
    def confirm_peer_alias(body: dict[str, Any], actor=Depends(current_actor)):
        if set(body) - {"profile", "requested_ref", "peer_type", "peer_id"} or not {
            "requested_ref", "peer_type", "peer_id"
        }.issubset(body):
            raise DomainError("PEER_ALIAS_CONFIRMATION_INVALID", "Payload konfirmasi alias tidak valid.", status_code=422)
        if context.source_repository is None:
            raise DomainError("EXPORT_CURSOR_UNAVAILABLE", "Repository cursor export belum tersedia.", status_code=503)
        selected_profile = context.control_plane.require_profile(actor, body.get("profile"))
        try:
            return {
                "confirmed": True,
                **context.source_repository.confirm_peer_alias_candidate(
                    selected_profile,
                    str(body["requested_ref"]),
                    str(body["peer_type"]),
                    body["peer_id"],
                ),
            }
        except Exception as exc:
            from tme3bot.infrastructure.source_store import (
                PeerAliasCursorConflict,
                PeerAliasNotFound,
            )

            if isinstance(exc, PeerAliasCursorConflict):
                raise DomainError(
                    "PEER_ALIAS_CURSOR_RECONCILIATION_REQUIRED",
                    "Cursor lama berbeda; hentikan lane ini sampai cursor legacy direkonsiliasi.",
                    status_code=409,
                ) from exc
            if isinstance(exc, PeerAliasNotFound):
                raise DomainError("PEER_ALIAS_CANDIDATE_NOT_FOUND", str(exc), status_code=404) from exc
            raise

    def validate_cursor_job(
        body: dict[str, Any], *, needs_ref: bool, require_capability: bool = True
    ):
        service = require_cursor_service()
        job_id = str(body.get("job_id") or "").strip()
        job = context.control_plane.jobs.get(job_id)
        if job is None:
            raise DomainError("JOB_NOT_FOUND", "Job export tidak ditemukan.", status_code=404)
        if job.kind != "export" or job.status.terminal:
            raise DomainError("EXPORT_CURSOR_JOB_INVALID", "Job tidak aktif atau bukan job export.", status_code=409)
        worker = str(body.get("worker") or "").strip().lower()
        if not worker or worker != str(job.worker).strip().lower():
            raise DomainError(
                "JOB_WORKER_MISMATCH",
                "Worker bukan pemilik job export.",
                status_code=403,
            )
        profile = str(body.get("profile") or job.profile).strip()
        if profile != job.profile:
            raise DomainError("JOB_PROFILE_MISMATCH", "Profile bukan pemilik job export.", status_code=403)

        stored = context.control_plane.jobs.command_payload(job.id)
        if not isinstance(stored, dict):
            raise DomainError("JOB_PAYLOAD_UNAVAILABLE", "Payload internal job tidak tersedia.", status_code=409)
        if stored.get("dispatch_mode") == "durable":
            internal_payload = stored.get("payload") if isinstance(stored.get("payload"), dict) else {}
            expected_attempt = max(1, int(stored.get("attempt") or 1))
        else:
            internal_payload = stored
            expected_attempt = 1 + sum(
                1 for event in context.control_plane.jobs.events(job.id)
                if event.event_type == "retry_started"
            )
        attempt = body.get("attempt")
        if type(attempt) is not int or attempt != expected_attempt:
            raise DomainError("JOB_ATTEMPT_MISMATCH", "Attempt job export sudah tidak berlaku.", status_code=409)

        requested_ref = ""
        if needs_ref:
            try:
                requested_ref = normalize_tdl_chat_ref(str(body.get("requested_ref") or ""))
                expected_ref = str(internal_payload.get("chat_ref") or "").strip()
                if not expected_ref and internal_payload.get("url"):
                    from tme3bot.url_parser import parse_tme3_url

                    expected_ref = parse_tme3_url(
                        str(internal_payload["url"]), str(context.config.tme3_host)
                    ).chat_ref
                expected_ref = normalize_tdl_chat_ref(expected_ref)
            except (TypeError, ValueError) as exc:
                raise DomainError("EXPORT_REFERENCE_INVALID", "Referensi chat job tidak valid.", status_code=422) from exc
            if requested_ref != expected_ref:
                raise DomainError(
                    "EXPORT_REFERENCE_MISMATCH",
                    "Worker mengirim referensi chat yang berbeda dari job.",
                    status_code=403,
                )

        if require_capability:
            capabilities = getattr(context.worker_dispatcher, "capabilities", None)
            if not callable(capabilities):
                raise DomainError("WORKER_INCOMPATIBLE", "Capability worker export tidak dapat diverifikasi.", status_code=409)
            try:
                require_worker_contract(
                    capabilities(worker),
                    worker,
                    required_capabilities={CAP_SHARED_EXPORT_CURSOR},
                )
            except DomainError:
                raise
            except Exception as exc:
                raise DomainError("WORKER_OFFLINE", "Worker tidak dapat diverifikasi untuk cursor export.", status_code=503) from exc
        return service, job, profile, worker, attempt, requested_ref

    @app.post(
        "/internal/v1/export-cursor/resolve",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def resolve_export_peer(body: dict[str, Any]):
        required = {"job_id", "worker", "profile", "attempt", "requested_ref", "peer_type", "peer_id"}
        if set(body) != required:
            raise DomainError("EXPORT_CURSOR_INPUT_INVALID", "Payload resolve peer tidak valid.", status_code=422)
        service, _job, profile, _worker, _attempt, requested_ref = validate_cursor_job(body, needs_ref=True)
        try:
            return {
                "resolved": True,
                **service.resolve_alias(
                    profile,
                    requested_ref,
                    str(body["peer_type"]),
                    body["peer_id"],
                ),
            }
        except Exception as exc:
            from tme3bot.infrastructure.source_store import (
                PeerAliasConflict,
                PeerAliasCursorConflict,
            )

            if isinstance(exc, PeerAliasConflict):
                if isinstance(exc, PeerAliasCursorConflict):
                    raise DomainError(
                        "PEER_ALIAS_CURSOR_RECONCILIATION_REQUIRED",
                        "Cursor lama berbeda; hentikan lane ini sampai cursor legacy direkonsiliasi.",
                        status_code=409,
                    ) from exc
                raise DomainError(
                    "PEER_ALIAS_REMAP_CONFIRMATION_REQUIRED",
                    "Alias chat ini sudah terikat ke peer lain; konfirmasi pemetaan diperlukan.",
                    status_code=409,
                ) from exc
            raise

    @app.post(
        "/internal/v1/export-cursor/lease",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def acquire_export_cursor(body: dict[str, Any]):
        required = {"job_id", "worker", "profile", "attempt", "requested_ref"}
        if set(body) != required:
            raise DomainError("EXPORT_CURSOR_INPUT_INVALID", "Payload lease export tidak valid.", status_code=422)
        service, _job, profile, worker, attempt, requested_ref = validate_cursor_job(body, needs_ref=True)
        try:
            return service.acquire(
                profile=profile,
                requested_ref=requested_ref,
                job_id=str(body["job_id"]),
                worker=worker,
                attempt=attempt,
            )
        except Exception as exc:
            from tme3bot.infrastructure.source_store import ExportCursorBusy, PeerAliasNotFound

            if isinstance(exc, ExportCursorBusy):
                raise DomainError("EXPORT_CURSOR_BUSY", str(exc), status_code=409) from exc
            if isinstance(exc, PeerAliasNotFound):
                raise DomainError("EXPORT_PEER_NOT_RESOLVED", str(exc), status_code=409) from exc
            raise

    @app.post(
        "/internal/v1/export-cursor/heartbeat",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def heartbeat_export_cursor(body: dict[str, Any]):
        required = {"job_id", "worker", "attempt", "fencing_token"}
        if set(body) != required or type(body.get("attempt")) is not int or type(body.get("fencing_token")) is not int:
            raise DomainError("EXPORT_CURSOR_INPUT_INVALID", "Payload heartbeat lease tidak valid.", status_code=422)
        base = dict(body)
        lease = cursor_service.lease_for_job(str(body["job_id"])) if cursor_service else None
        if lease is None:
            raise DomainError("EXPORT_CURSOR_STALE", "Lease export tidak ditemukan.", status_code=409)
        base["profile"] = str(lease["profile"])
        service, _job, _profile, worker, attempt, _requested = validate_cursor_job(
            base, needs_ref=False, require_capability=False
        )
        try:
            return {"ok": service.heartbeat(
                job_id=str(body["job_id"]),
                worker=worker,
                attempt=attempt,
                fencing_token=int(body["fencing_token"]),
            )}
        except Exception as exc:
            from tme3bot.infrastructure.source_store import StaleExportLease

            if isinstance(exc, StaleExportLease):
                raise DomainError("EXPORT_CURSOR_STALE", str(exc), status_code=409) from exc
            raise

    @app.post(
        "/internal/v1/export-cursor/commit",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def commit_export_cursor(body: dict[str, Any]):
        required = {"job_id", "worker", "profile", "attempt", "fencing_token", "expected_revision", "last_id", "artifact"}
        integer_fields = {"attempt", "fencing_token", "expected_revision", "last_id"}
        if set(body) != required or any(type(body.get(key)) is not int for key in integer_fields) or not isinstance(body.get("artifact"), dict):
            raise DomainError("EXPORT_CURSOR_INPUT_INVALID", "Payload commit cursor tidak valid.", status_code=422)
        service, job, _profile, worker, attempt, _requested = validate_cursor_job(
            body, needs_ref=False, require_capability=False
        )
        try:
            completed = service.commit(
                job_id=job.id,
                attempt=attempt,
                worker=worker,
                fencing_token=int(body["fencing_token"]),
                expected_revision=int(body["expected_revision"]),
                last_id=int(body["last_id"]),
                artifact=body["artifact"],
            )
        except Exception as exc:
            from tme3bot.infrastructure.source_store import StaleExportLease

            if isinstance(exc, StaleExportLease):
                raise DomainError("EXPORT_CURSOR_STALE", str(exc), status_code=409) from exc
            raise
        context.control_plane.on_export_cursor_committed(job.id)
        return completed

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
        candidates: list[str] = []
        protected: list[str] = []
        for item in profiles:
            if not isinstance(item, dict):
                continue
            try:
                name = str(item.get("name", ""))
                raw_user_id = item.get("telegram_user_id")
                user_id = int(raw_user_id) if raw_user_id is not None else None
                vault = getattr(context.profile_provisioner, "store", None)
                if vault is not None and vault.is_vaulted(name):
                    protected.append(name)
                    continue
                if vault is not None and user_id is not None:
                    vault.record_legacy_discovery(name, user_id)
                    candidates.append(name)
                if registry.register_discovered(name, user_id):
                    synced.append(name)
            except (TypeError, ValueError) as exc:
                raise DomainError("PROFILE_SYNC_INVALID", str(exc), status_code=422) from exc
        return {
            "profiles": sorted(set(synced)),
            "adoption_candidates": sorted(set(candidates)),
            "vault_protected": sorted(set(protected)),
        }

    @app.get(
        prefix + "/sources",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def state_sources(profile: str):
        store = context.profile_manager.state_store(profile)
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
        source = context.profile_manager.state_store(profile).get_source(chat_ref)
        return {"source": source.to_dict() if source else None}

    @app.post(
        prefix + "/source",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    async def state_upsert(profile: str, request: Request):
        body = await request.json()
        source = context.profile_manager.state_store(profile).upsert_source(
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
        context.profile_manager.state_store(profile).mark_warmup_done(
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
        deleted = context.profile_manager.state_store(profile).delete_sources(
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
