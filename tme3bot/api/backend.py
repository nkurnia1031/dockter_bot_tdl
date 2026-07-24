from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tme3bot.api.schemas import (
    ActorResponse,
    ApproveChallengeRequest,
    BatchSourcesRequest,
    ChallengeExchangeResponse,
    ChallengeResponse,
    ChallengeTokenRequest,
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
    StorageItemListResponse,
    StorageItemResponse,
    StorageSettingsResponse,
    StorageUpdateRequest,
    StorageUploadRequest,
    TokenPairResponse,
    UtilityFolderRequest,
    UtilityJobRequest,
    WorkerListResponse,
    WorkerEventRequest,
    WorkerRequest,
    WorkerRouteRequest,
    WorkerUpdateRequest,
)
from tme3bot.domain.models import Actor, DomainError, Job, JobEvent, JobStatus
from tme3bot.storage_catalog import build_storage_caption, storage_item_dict
from tme3bot.storage_links import sign_storage_item, verify_storage_item

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

    def raw_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> str:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise DomainError("TOKEN_REQUIRED", "Bearer token wajib diisi.", status_code=401)
        return credentials.credentials

    def current_actor(
        token: str = Depends(raw_token),
        x_profile: str | None = Header(default=None, alias="X-Profile"),
    ):
        payload = context.auth.decode_access(token)
        actor = context.control_plane.actor(int(payload["telegram_user_id"]))
        if x_profile:
            if x_profile not in context.profile_manager.list_profiles():
                raise DomainError(
                    "PROFILE_NOT_FOUND", "Profile tidak ditemukan.", status_code=404
                )
            return Actor(actor.telegram_user_id, x_profile)
        return actor

    def require_service(token: str = Depends(raw_token)) -> None:
        if not context.config.frontend_service_token or token != context.config.frontend_service_token:
            raise DomainError("SERVICE_UNAUTHORIZED", "Service token tidak valid.", status_code=401)

    def require_internal(token: str = Depends(raw_token)) -> None:
        if not context.config.backend_internal_token or token != context.config.backend_internal_token:
            raise DomainError("INTERNAL_UNAUTHORIZED", "Internal token tidak valid.", status_code=401)

    def require_management(token: str = Depends(raw_token)) -> None:
        if not context.config.management_api_token or token != context.config.management_api_token:
            raise DomainError("MANAGEMENT_UNAUTHORIZED", "Management token tidak valid.", status_code=401)

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
        archived: bool | None = False,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        items = context.control_plane.jobs.list(
            profile=actor.profile,
            kind=kind,
            status=status,
            worker=worker,
            archived=archived,
            offset=offset,
            limit=limit,
        )
        total = context.control_plane.jobs.count(
            profile=actor.profile, kind=kind, status=status, archived=archived
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

    @app.post("/api/v1/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel_job(job_id: str, actor=Depends(current_actor)):
        return job_dict(context.control_plane.cancel_job(actor, job_id))

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
    def list_sources(actor=Depends(current_actor)):
        store = context.profile_manager.runtime(actor.profile).state_store
        return {
            "items": [
                {"chat_ref": chat_ref, **source.to_dict()}
                for chat_ref, source in store.list_sources()
            ]
        }

    @app.get("/api/v1/sources/{chat_ref:path}", response_model=SourceResponse)
    def get_source(chat_ref: str, actor=Depends(current_actor)):
        source = context.profile_manager.runtime(actor.profile).state_store.get_source(chat_ref)
        if source is None:
            raise DomainError("SOURCE_NOT_FOUND", "Source tidak ditemukan.", status_code=404)
        return {"chat_ref": chat_ref, **source.to_dict()}

    @app.delete("/api/v1/sources/{chat_ref:path}", response_model=ObjectResponse)
    def delete_source(chat_ref: str, actor=Depends(current_actor)):
        deleted = context.profile_manager.runtime(actor.profile).state_store.delete_source(chat_ref)
        return {"deleted": deleted}

    @app.patch("/api/v1/sources/{chat_ref:path}", response_model=SourceResponse)
    def update_source(
        chat_ref: str, body: SourceUpdateRequest, actor=Depends(current_actor)
    ):
        store = context.profile_manager.runtime(actor.profile).state_store
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
    def batch_delete_sources(body: BatchSourcesRequest, actor=Depends(current_actor)):
        deleted = context.profile_manager.runtime(actor.profile).state_store.delete_sources(body.chat_refs)
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
        return job_dict(
            context.control_plane.submit_job(
                actor, "export", values, profile=actor.profile
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
        artifact_keys: list[str] = []
        for artifact_id in artifact_ids:
            artifact = context.export_catalog.get(str(artifact_id))
            if artifact is None or artifact["profile"] != actor.profile:
                raise DomainError(
                    "ARTIFACT_NOT_FOUND", "Artifact tidak ditemukan.", status_code=404
                )
            if artifact["status"] not in {"pending", "failed"}:
                raise DomainError(
                    "ARTIFACT_NOT_PENDING",
                    "Artifact tidak berada pada antrean yang dapat dijalankan.",
                    status_code=409,
                )
            if worker is not None and worker != artifact["worker"]:
                raise DomainError(
                    "ARTIFACT_WORKER_MISMATCH",
                    "Pilih artifact dari worker yang sama untuk satu request.",
                    status_code=409,
                )
            worker = str(artifact["worker"])
            artifact_keys.append(str(artifact["artifact_key"]))
        return job_dict(
            context.control_plane.submit_job(
                actor,
                "download",
                {
                    "retry_failed": retry_failed,
                    "artifact_keys": artifact_keys,
                    "priority": values.get("priority", "normal"),
                },
                profile=actor.profile,
                worker=worker,
            )
        )

    @app.get("/api/v1/downloads/artifacts", response_model=ObjectResponse)
    def list_artifacts(
        status: str | None = None,
        archived: bool | None = False,
        worker: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        items, total = context.export_catalog.list(
            profile=actor.profile,
            status=status,
            archived=archived,
            worker=worker,
            limit=limit,
            offset=offset,
        )
        return {"items": items, "total": total}

    @app.post("/api/v1/downloads/artifacts/reconcile", response_model=JobResponse)
    def reconcile_artifacts(actor=Depends(current_actor)):
        return job_dict(
            context.control_plane.submit_job(
                actor, "artifact_inventory", {}, profile=actor.profile
            )
        )

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
                profile=actor.profile,
                worker=str(artifact["worker"]),
            )
        )

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

    @app.post("/api/v1/downloads/clear-failed", response_model=JobResponse)
    def clear_failed(actor=Depends(current_actor)):
        return job_dict(
            context.control_plane.submit_job(
                actor, "download_clear_failed", {}, profile=actor.profile
            )
        )

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
    def utility_tree(path: str = "/workspace", actor=Depends(current_actor)):
        worker = context.profile_manager.worker_route(actor.profile)
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
        return context.utility_settings.get()

    @app.put("/api/v1/utility/settings/{key}", response_model=ObjectResponse)
    def set_utility_setting(key: str, body: SettingRequest, actor=Depends(current_actor)):
        del actor
        context.utility_settings.set(key, body.value)
        return context.utility_settings.get()

    @app.post("/api/v1/utility/jobs", response_model=JobResponse)
    def submit_utility(body: UtilityJobRequest, actor=Depends(current_actor)):
        settings = context.utility_settings.get()
        payload = _model_dict(body)
        payload["settings"] = settings
        return job_dict(
            context.control_plane.submit_job(
                actor, "utility", payload, profile=actor.profile
            )
        )

    @app.get("/api/v1/workers", response_model=WorkerListResponse)
    def list_workers(actor=Depends(current_actor)):
        return {
            "items": [
                {
                    "name": name,
                    "url": value["url"],
                    "selected": name
                    == context.profile_manager.worker_route(actor.profile),
                }
                for name, value in context.worker_registry.list().items()
            ]
        }

    @app.post("/api/v1/workers", response_model=ObjectResponse)
    def add_worker(body: WorkerRequest, actor=Depends(current_actor)):
        del actor
        name = context.worker_registry.upsert(body.name, body.url, body.token)
        return {"name": name}

    @app.put("/api/v1/workers/{name}", response_model=ObjectResponse)
    def update_worker(
        name: str, body: WorkerUpdateRequest, actor=Depends(current_actor)
    ):
        del actor
        if context.worker_registry.get(name) is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        return {
            "name": context.worker_registry.upsert(name, body.url, body.token)
        }

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
        payload.update(
            {
                "batch_id": str(uuid.uuid4()),
                "owner_user_id": actor.telegram_user_id,
                "owner_profile": actor.profile,
            }
        )
        return job_dict(
            context.control_plane.submit_job(
                actor, "storage_upload", payload, profile=actor.profile
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
        changes_owned_metadata = (
            values.get("folder") is not None
            or values.get("keywords") is not None
        )
        if (
            changes_owned_metadata
            and int(item.owner_user_id) != int(actor.telegram_user_id)
        ):
            raise DomainError(
                "STORAGE_OWNER_REQUIRED",
                "Folder dan keyword hanya dapat diubah oleh pemilik file.",
                status_code=403,
            )
        if values.get("display_name") is not None:
            item = context.storage_catalog.rename(item_id, values["display_name"])
        if changes_owned_metadata:
            item = context.storage_catalog.update_metadata(
                item_id,
                actor.telegram_user_id,
                folder=values.get("folder"),
                keywords=values.get("keywords"),
            )
        caption = build_storage_caption(item.folder, item.display_name, item.keywords)
        if context.bot is not None and context.config.storage_channel_id:
            try:
                context.bot.edit_message_caption(
                    chat_id=context.config.storage_channel_id,
                    message_id=item.channel_message_id,
                    caption=caption,
                )
            except Exception:
                LOGGER.warning(
                    "Metadata storage tersimpan tetapi caption Telegram gagal "
                    "diperbarui item=%s",
                    item_id,
                    exc_info=True,
                )
        return storage_item_dict(item)

    @app.delete(
        "/api/v1/storage/items/{item_id}",
        response_model=StorageItemResponse,
    )
    def delete_storage_item(item_id: int, actor=Depends(current_actor)):
        item = _storage_item(context, item_id)
        if int(item.owner_user_id) != int(actor.telegram_user_id):
            raise DomainError(
                "STORAGE_OWNER_REQUIRED",
                "File storage hanya dapat dihapus oleh pemiliknya.",
                status_code=403,
            )
        try:
            if context.bot is None:
                raise RuntimeError("Telegram storage adapter belum aktif.")
            context.bot.delete_message(
                chat_id=item.channel_id, message_id=item.channel_message_id
            )
            item = context.storage_catalog.mark_deleted(
                item_id, actor.telegram_user_id
            )
        except PermissionError:
            raise
        except Exception as exc:
            context.storage_catalog.mark_deleted(
                item_id, actor.telegram_user_id, failed=True
            )
            raise DomainError(
                "STORAGE_DELETE_FAILED", str(exc), status_code=502
            ) from exc
        return storage_item_dict(item)

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
        item = _storage_item(context, item_id)
        if context.bot is None:
            raise DomainError(
                "DELIVERY_UNAVAILABLE",
                "Telegram delivery adapter belum aktif.",
                status_code=503,
            )
        message = context.bot.copy_message(
            chat_id=actor.telegram_user_id,
            from_chat_id=item.channel_id,
            message_id=item.channel_message_id,
        )
        return {
            "method": "telegram",
            "destination": actor.telegram_user_id,
            "message_id": getattr(message, "message_id", None),
            "display_name": item.display_name,
        }

    @app.get(
        "/api/v1/storage/items/{item_id}/deep-link",
        response_model=ObjectResponse,
    )
    def storage_deep_link(item_id: int, actor=Depends(current_actor)):
        del actor
        _storage_item(context, item_id)
        token = sign_storage_item(item_id, context.config.auth_jwt_secret)
        return {
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
        item = _storage_item(context, item_id)
        if context.bot is None:
            raise DomainError(
                "DELIVERY_UNAVAILABLE",
                "Telegram delivery adapter belum aktif.",
                status_code=503,
            )
        message = context.bot.copy_message(
            chat_id=actor.telegram_user_id,
            from_chat_id=item.channel_id,
            message_id=item.channel_message_id,
        )
        return {
            "method": "telegram",
            "destination": actor.telegram_user_id,
            "message_id": getattr(message, "message_id", None),
            "display_name": item.display_name,
        }

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
        job = context.control_plane.append_worker_event(
            JobEvent(
                job_id=job_id,
                sequence=body.sequence,
                status=status,
                event_type=body.event_type,
                progress=body.progress,
                result=body.result,
                error=body.error,
            )
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


def _profile_artifact(context: BackendContext, actor, artifact_id: str):
    if context.export_catalog is None:
        raise DomainError(
            "ARTIFACT_CATALOG_UNAVAILABLE",
            "Katalog export belum tersedia.",
            status_code=503,
        )
    item = context.export_catalog.get(artifact_id)
    if item is None or str(item["profile"]) != actor.profile:
        raise DomainError(
            "ARTIFACT_NOT_FOUND", "Artifact tidak ditemukan.", status_code=404
        )
    return item


def _add_internal_state_routes(app: FastAPI, context: BackendContext, require_internal):
    prefix = "/internal/v1/profiles/{profile}/state"

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
            "name": context.worker_registry.upsert(body.name, body.url, body.token)
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
