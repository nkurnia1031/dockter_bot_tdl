from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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
    CAP_SHARED_EXPORT_CURSOR,
    CAP_TTS,
    worker_contract_metadata,
)
from tme3bot.profile_diagnostics import PROFILE_TDL_DIAGNOSTIC_CODES
from tme3bot.profile_provisioning import MAX_PROFILE_BUNDLE_BYTES, MAX_SESSION_ARCHIVE_BYTES
from tme3bot.rclone import RcloneError
from tme3bot.names import normalize_profile_name

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
    canary_operations = getattr(context.executor, "profile_readiness_canaries", None)
    close_canaries = getattr(canary_operations, "close", None)
    if callable(close_canaries):
        app.add_event_handler("shutdown", close_canaries)

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
        snapshot = getattr(context.executor, "profile_sync_status", None)
        profile_sync = snapshot() if callable(snapshot) else {"status": "disabled"}
        status = str(profile_sync.get("status") or "disabled")
        return {
            "ok": True,
            "role": "worker",
            "profiles_ready": status in {"ready", "disabled"},
            "profile_sync_status": status,
        }

    @app.get("/internal/v1/capabilities", dependencies=[Depends(authorize)])
    def capabilities():
        details = context.executor.capabilities()
        contract = worker_contract_metadata()
        capabilities = list(contract["capabilities"])
        durable_ready = getattr(context.executor, "durable_commands_ready", None)
        if callable(durable_ready) and durable_ready():
            capabilities.append(CAP_DURABLE_COMMANDS_V1)
        if details.get("tts"):
            capabilities.append(CAP_TTS)
        if details.get("safelink_resolver"):
            capabilities.append(CAP_SAFELINK_RESOLVE)
        cursor_ready = getattr(context.executor, "shared_export_cursor_ready", None)
        if callable(cursor_ready) and cursor_ready():
            capabilities.append(CAP_SHARED_EXPORT_CURSOR)
        contract["capabilities"] = sorted(set(capabilities))
        return {**details, **contract}

    @app.get("/internal/v1/utility/runtime-readiness", dependencies=[Depends(authorize)])
    def utility_runtime_readiness():
        probe = getattr(context.executor, "utility_runtime_readiness", None)
        if not callable(probe):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung pemeriksaan runtime Utility.",
                status_code=404,
            )
        return probe()

    @app.post("/internal/v1/quickmode/runtime-readiness", dependencies=[Depends(authorize)])
    def quickmode_runtime_readiness(body: dict[str, Any]):
        if set(body) != {"rclone_destination"} or not isinstance(
            body.get("rclone_destination"), str
        ):
            raise DomainError(
                "QUICK_MODE_READINESS_REQUEST_INVALID",
                "Tujuan rclone Quick Mode tidak valid.",
                status_code=422,
            )
        probe = getattr(context.executor, "quickmode_runtime_readiness", None)
        if not callable(probe):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung pemeriksaan runtime Quick Mode.",
                status_code=404,
            )
        return probe(body["rclone_destination"])

    @app.post("/internal/v1/storage/rclone-runtime-readiness", dependencies=[Depends(authorize)])
    def rclone_storage_runtime_readiness(body: dict[str, Any]):
        if set(body) != {"rclone_destination"} or not isinstance(
            body.get("rclone_destination"), str
        ):
            raise DomainError(
                "RCLONE_READINESS_REQUEST_INVALID",
                "Tujuan rclone Storage tidak valid.",
                status_code=422,
            )
        probe = getattr(context.executor, "rclone_storage_runtime_readiness", None)
        if not callable(probe):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung pemeriksaan akses Storage rclone.",
                status_code=404,
            )
        return probe(body["rclone_destination"])

    @app.post("/internal/v1/storage/rclone-browser", dependencies=[Depends(authorize)])
    def rclone_storage_browser(body: dict[str, Any]):
        allowed = {"rclone_destination", "path", "q", "sort", "order", "limit", "offset"}
        if set(body) - allowed or not isinstance(body.get("rclone_destination"), str):
            raise DomainError("RCLONE_BROWSER_REQUEST_INVALID", "Permintaan browser rclone tidak valid.", status_code=422)
        for key in ("path", "q", "sort", "order"):
            if key in body and not isinstance(body[key], str):
                raise DomainError("RCLONE_BROWSER_REQUEST_INVALID", "Permintaan browser rclone tidak valid.", status_code=422)
        for key, minimum, maximum in (("limit", 1, 200), ("offset", 0, 2_000_000)):
            value = body.get(key, 100 if key == "limit" else 0)
            if type(value) is not int or not minimum <= value <= maximum:
                raise DomainError("RCLONE_BROWSER_REQUEST_INVALID", "Permintaan browser rclone tidak valid.", status_code=422)
        browse = getattr(context.executor, "rclone_storage_browse", None)
        if not callable(browse):
            raise DomainError("WORKER_UPDATE_REQUIRED", "Worker belum mendukung browser rclone Storage.", status_code=404)
        try:
            return browse(
                body["rclone_destination"], body.get("path", ""), query=body.get("q", ""),
                sort=body.get("sort", "name"), order=body.get("order", "asc"),
                limit=body.get("limit", 100), offset=body.get("offset", 0),
            )
        except RcloneError as exc:
            status = 422 if "PATH" in exc.code or "path" in str(exc).casefold() else 503
            code = "RCLONE_BROWSER_PATH_INVALID" if status == 422 else (exc.code or "RCLONE_BROWSER_FAILED")
            raise DomainError(code, "Path rclone tidak valid." if status == 422 else "Worker tidak dapat membaca folder rclone.", status_code=status) from exc

    @app.post("/internal/v1/storage/move-cleanup", dependencies=[Depends(authorize)])
    def storage_move_cleanup(body: dict[str, Any]):
        if set(body) != {"source_job_id", "folder_path", "relative_path"}:
            raise DomainError("STORAGE_MOVE_CLEANUP_INVALID", "Permintaan cleanup Move tidak valid.", status_code=422)
        if any(not isinstance(body.get(key), str) for key in ("source_job_id", "folder_path", "relative_path")):
            raise DomainError("STORAGE_MOVE_CLEANUP_INVALID", "Permintaan cleanup Move tidak valid.", status_code=422)
        cleanup = getattr(context.executor, "storage_move_cleanup_reconciled", None)
        if not callable(cleanup):
            raise DomainError("WORKER_UPDATE_REQUIRED", "Worker belum mendukung cleanup Move Storage.", status_code=404)
        try:
            return cleanup(body["source_job_id"], body["folder_path"], body["relative_path"])
        except ValueError as exc:
            raise DomainError("STORAGE_MOVE_PATH_INVALID", "Path sumber Move tidak valid.", status_code=422) from exc

    @app.get("/internal/v1/safelink/runtime-readiness", dependencies=[Depends(authorize)])
    def safelink_runtime_readiness():
        probe = getattr(context.executor, "safelink_runtime_readiness", None)
        if not callable(probe):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung pemeriksaan runtime Resolver.",
                status_code=404,
            )
        return probe()

    @app.get("/internal/v1/profile-sync", dependencies=[Depends(authorize)])
    def profile_sync_status():
        snapshot = getattr(context.executor, "profile_sync_status", None)
        if not callable(snapshot):
            return {"status": "disabled", "backend_available": None, "profiles": {}}
        return snapshot()

    @app.get("/internal/v1/profiles/local", dependencies=[Depends(authorize)])
    def local_profile_inventory():
        inventory = getattr(context.executor, "local_profile_inventory", None)
        if not callable(inventory):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung scan profil lokal.",
                status_code=404,
            )
        return profile_operation(
            inventory,
            "PROFILE_INVENTORY_FAILED",
            "Worker tidak dapat membaca inventaris profil lokal.",
        )

    @app.post(
        "/internal/v1/profiles/readiness-canaries",
        status_code=202,
        dependencies=[Depends(authorize)],
    )
    def start_profile_readiness_canary(body: dict[str, Any]):
        required = {"profile", "storage_target", "tts_target"}
        if not required.issubset(body) or set(body) - (required | {"checks"}) or any(
            not isinstance(body.get(key), str)
            for key in required
        ):
            raise DomainError(
                "PROFILE_CANARY_REQUEST_INVALID",
                "Target canary profil tidak valid.",
                status_code=422,
            )
        checks = body.get("checks")
        if checks is not None and (
            not isinstance(checks, list)
            or not checks
            or any(
                not isinstance(item, str)
                or item not in {"export", "download", "storage", "tts"}
                for item in checks
            )
        ):
            raise DomainError(
                "PROFILE_CANARY_REQUEST_INVALID",
                "Cakupan canary profil tidak valid.",
                status_code=422,
            )
        start = getattr(context.executor, "start_profile_readiness_canary", None)
        if not callable(start):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung canary kesiapan profil.",
                status_code=404,
            )
        try:
            if checks is None:
                return start(
                    body["profile"], body["storage_target"], body["tts_target"]
                )
            return start(
                body["profile"], body["storage_target"], body["tts_target"], checks
            )
        except ValueError:
            raise DomainError(
                "PROFILE_CANARY_REQUEST_INVALID",
                "Target canary profil tidak valid.",
                status_code=422,
            ) from None

    @app.get(
        "/internal/v1/profiles/readiness-canaries/{operation_id}",
        dependencies=[Depends(authorize)],
    )
    def get_profile_readiness_canary(operation_id: str):
        if not re.fullmatch(r"[0-9a-f-]{36}", operation_id):
            raise DomainError(
                "PROFILE_CANARY_NOT_FOUND",
                "Canary kesiapan profil tidak ditemukan.",
                status_code=404,
            )
        get_operation = getattr(context.executor, "profile_readiness_canary", None)
        if not callable(get_operation):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung canary kesiapan profil.",
                status_code=404,
            )
        operation = get_operation(operation_id)
        if operation is None:
            raise DomainError(
                "PROFILE_CANARY_NOT_FOUND",
                "Canary kesiapan profil tidak ditemukan.",
                status_code=404,
            )
        return operation

    @app.post("/internal/v1/profiles/local/scan", dependencies=[Depends(authorize)])
    def scan_local_profiles():
        inventory = getattr(context.executor, "local_profile_inventory", None)
        if not callable(inventory):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung scan profil lokal.",
                status_code=404,
            )
        return profile_operation(
            lambda: inventory(prepare_upload=True),
            "PROFILE_INVENTORY_FAILED",
            "Worker tidak dapat memulai pemeriksaan profil lokal.",
        )

    @app.delete(
        "/internal/v1/profiles/{profile}/local",
        dependencies=[Depends(authorize)],
    )
    def delete_local_profile(profile: str):
        raw = str(profile or "").strip().lower()
        normalized = normalize_profile_name(raw)
        if not normalized or raw != normalized:
            raise DomainError(
                "PROFILE_NAME_INVALID", "Nama profil lokal tidak valid.", status_code=422
            )
        delete = getattr(context.executor, "delete_local_profile", None)
        if not callable(delete):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung penghapusan profil lokal.",
                status_code=409,
            )
        return profile_operation(
            lambda: delete(normalized),
            "PROFILE_DELETE_FAILED",
            "Worker gagal menghapus profil lokal.",
        )

    @app.post("/internal/v1/profile-sync", dependencies=[Depends(authorize)])
    def request_profile_sync(body: dict[str, Any]):
        if set(body) - {"profile", "mode"}:
            raise DomainError(
                "PROFILE_SYNC_REQUEST_INVALID",
                "Payload sinkronisasi profil tidak valid.",
                status_code=422,
            )
        profile = body.get("profile")
        if profile is not None and (not isinstance(profile, str) or len(profile) > 48):
            raise DomainError(
                "PROFILE_SYNC_REQUEST_INVALID",
                "Nama profil sinkronisasi tidak valid.",
                status_code=422,
            )
        mode = str(body.get("mode") or "check").strip().lower()
        if mode not in {"check", "repair"}:
            raise DomainError(
                "PROFILE_SYNC_REQUEST_INVALID",
                "Mode sinkronisasi harus check atau repair.",
                status_code=422,
            )
        request_sync = getattr(context.executor, "request_profile_sync", None)
        if not callable(request_sync):
            raise DomainError(
                "PROFILE_SYNC_UNAVAILABLE",
                "Worker belum mendukung sinkronisasi profil.",
                status_code=503,
            )
        try:
            return request_sync(profile=profile, mode=mode)
        except ValueError as exc:
            raise DomainError(
                "PROFILE_SYNC_REQUEST_INVALID", str(exc), status_code=422
            ) from exc
        except RuntimeError as exc:
            raise DomainError(
                "PROFILE_SYNC_UNAVAILABLE",
                "Sinkronisasi profil backend belum dikonfigurasi pada worker.",
                status_code=503,
            ) from exc

    @app.delete("/internal/v1/profile-sync", dependencies=[Depends(authorize)])
    def cancel_profile_sync(body: dict[str, Any]):
        if set(body) - {"profile", "mode"} or not isinstance(body.get("profile"), str):
            raise DomainError(
                "PROFILE_SYNC_REQUEST_INVALID",
                "Target pembatalan sinkronisasi profil tidak valid.",
                status_code=422,
            )
        profile = body["profile"]
        if len(profile) > 48:
            raise DomainError(
                "PROFILE_SYNC_REQUEST_INVALID",
                "Nama profil sinkronisasi tidak valid.",
                status_code=422,
            )
        mode = str(body.get("mode") or "check").strip().lower()
        if mode not in {"check", "repair"}:
            raise DomainError(
                "PROFILE_SYNC_REQUEST_INVALID",
                "Mode sinkronisasi harus check atau repair.",
                status_code=422,
            )
        cancel_sync = getattr(context.executor, "cancel_profile_sync", None)
        if not callable(cancel_sync):
            raise DomainError(
                "PROFILE_SYNC_UNAVAILABLE",
                "Worker belum mendukung pembatalan sinkronisasi profil.",
                status_code=503,
            )
        try:
            return cancel_sync(profile=profile, mode=mode)
        except ValueError as exc:
            raise DomainError(
                "PROFILE_SYNC_REQUEST_INVALID", str(exc), status_code=422
            ) from exc

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
        sync_run_id: str = Header(default="", alias="X-Profile-Sync-Run-ID"),
        sync_revision: int = Header(default=0, alias="X-Profile-Sync-Revision"),
    ):
        data = await request.body()
        if len(data) > MAX_PROFILE_BUNDLE_BYTES:
            raise DomainError("PROFILE_ARCHIVE_TOO_LARGE", "Bundle profil melebihi batas.", status_code=413)
        sync_kwargs = {}
        if sync_run_id and sync_revision > 0:
            sync_kwargs = {"sync_run_id": sync_run_id, "sync_revision": sync_revision}
        return profile_operation(
            lambda: context.executor.install_profile_bundle(
                profile,
                telegram_user_id,
                data,
                provisioning_id,
                **sync_kwargs,
            ),
            "PROFILE_INSTALL_FAILED",
            "Worker tidak dapat memasang sesi profil.",
        )

    @app.post(
        "/internal/v1/profiles/distributions/{operation_id}",
        dependencies=[Depends(authorize)],
    )
    def distribute_vault_profile(operation_id: str, body: dict[str, Any]):
        allowed = {
            "worker", "profile", "revision", "telegram_user_id", "message_ids",
            "archive_sha256", "bundle_sha256",
            "event_sequence_start",
            "channel_ref",
        }
        if (
            set(body) != allowed
            or not re.fullmatch(r"[0-9a-fA-F-]{36}", operation_id)
            or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", str(body.get("worker") or ""))
            or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", str(body.get("profile") or ""))
            or type(body.get("revision")) is not int or int(body["revision"]) < 1
            or type(body.get("telegram_user_id")) is not int or int(body["telegram_user_id"]) < 1
            or not isinstance(body.get("message_ids"), list) or not body["message_ids"]
            or len(body["message_ids"]) > 100
            or any(type(message_id) is not int or message_id < 1 for message_id in body["message_ids"])
            or len(set(body["message_ids"])) != len(body["message_ids"])
            or not re.fullmatch(r"[a-f0-9]{64}", str(body.get("archive_sha256") or ""))
            or not re.fullmatch(r"[a-f0-9]{64}", str(body.get("bundle_sha256") or ""))
            or type(body.get("event_sequence_start")) is not int or int(body["event_sequence_start"]) < 0
            or not isinstance(body.get("channel_ref"), str) or not body["channel_ref"].strip() or len(body["channel_ref"]) > 200
        ):
            raise DomainError(
                "PROFILE_DISTRIBUTION_METADATA_INVALID",
                "Metadata distribusi profil tidak valid.",
                status_code=422,
            )
        expected_worker = str(getattr(context.config, "backup_node_name", "") or "").strip().lower()
        if str(body["worker"]) != expected_worker:
            raise DomainError(
                "PROFILE_DISTRIBUTION_WORKER_MISMATCH",
                "Operasi ini ditujukan ke worker lain.",
                status_code=403,
            )
        distribute = getattr(context.executor, "distribute_profile_bundle", None)
        if not callable(distribute):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung distribusi Vault.",
                status_code=409,
            )
        try:
            result = distribute(operation_id, body)
        except Exception as exc:
            raw = str(getattr(exc, "code", "") or str(exc))
            code = raw if re.fullmatch(r"PROFILE_[A-Z0-9_-]{1,56}", raw) else "PROFILE_DISTRIBUTION_FAILED"
            raise DomainError(
                code,
                "Worker gagal memasang revision Vault secara aman.",
                status_code=409,
            ) from None
        if not isinstance(result, dict) or result.get("ready") is not True:
            raise DomainError(
                "PROFILE_DISTRIBUTION_NOT_CONFIRMED",
                "Worker tidak mengonfirmasi pemasangan revision Vault.",
                status_code=409,
            )
        return result

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

    @app.get("/internal/v1/profiles/{profile}/session/diagnostics", dependencies=[Depends(authorize)])
    def diagnose_profile_export(profile: str):
        diagnose = getattr(context.executor, "diagnose_profile_export", None)
        if not callable(diagnose):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung diagnosis sesi profil.",
                status_code=404,
            )
        try:
            result = diagnose(profile)
        except ValueError as exc:
            known_codes = {
                "PROFILE_IDENTITY_MISSING", "PROFILE_IDENTITY_INVALID", "PROFILE_IDENTITY_UNSAFE",
                "PROFILE_ROOT_SESSION_MISSING", "PROFILE_USER1_SESSION_MISSING",
                "PROFILE_ROOT_SESSION_EMPTY", "PROFILE_USER1_SESSION_EMPTY",
                "PROFILE_SESSION_UNSAFE", "PROFILE_SESSION_UNREADABLE", "PROFILE_SESSION_BUSY",
                "PROFILE_SESSION_UNAVAILABLE",
            }
            code = str(exc) if str(exc) in known_codes else "PROFILE_SESSION_UNAVAILABLE"
            return {
                "ready": False,
                "reason_codes": [code],
                "checks": [{"name": "profile_session", "ready": False, "code": code}],
            }
        except Exception:
            LOGGER.warning("Worker profile diagnosis failed")
            raise DomainError(
                "PROFILE_DIAGNOSTICS_FAILED",
                "Worker tidak dapat memeriksa sesi profil.",
                status_code=503,
            ) from None
        if not isinstance(result, dict):
            raise DomainError(
                "PROFILE_DIAGNOSTICS_FAILED",
                "Worker tidak dapat memeriksa sesi profil.",
                status_code=503,
            )
        return result

    @app.get("/internal/v1/profiles/{profile}/tdl-diagnostics", dependencies=[Depends(authorize)])
    def diagnose_profile_tdl(profile: str):
        normalized = normalize_profile_name(profile)
        if not normalized:
            raise DomainError("PROFILE_NAME_INVALID", "Nama profil tidak valid.", status_code=422)
        diagnose = getattr(context.executor, "diagnose_profile_tdl", None)
        if not callable(diagnose):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung diagnosis TDL.",
                status_code=404,
            )
        try:
            result = diagnose(normalized)
        except Exception:
            LOGGER.warning("Worker TDL profile diagnosis failed")
            raise DomainError(
                "PROFILE_TDL_DIAGNOSTICS_FAILED",
                "Worker tidak dapat memeriksa sesi TDL.",
                status_code=503,
            ) from None
        if not isinstance(result, dict):
            raise DomainError(
                "PROFILE_TDL_DIAGNOSTICS_FAILED",
                "Worker tidak dapat memeriksa sesi TDL.",
                status_code=503,
            )
        allowed_codes = PROFILE_TDL_DIAGNOSTIC_CODES
        sessions = []
        raw_sessions = result.get("sessions")
        if isinstance(raw_sessions, list):
            for item in raw_sessions:
                if not isinstance(item, dict) or item.get("name") not in {"root", "user1"}:
                    continue
                raw_code = str(item.get("code") or "PROFILE_SESSION_UNAVAILABLE")
                code = raw_code if raw_code in allowed_codes else "PROFILE_SESSION_UNAVAILABLE"
                sessions.append({
                    "name": item["name"],
                    "ready": bool(item.get("ready")),
                    "code": code,
                    "identity_matches_metadata": bool(item.get("identity_matches_metadata")),
                })
        reasons = result.get("reason_codes")
        safe_reasons = [
            str(code) for code in reasons
            if isinstance(reasons, list) and str(code) in allowed_codes
        ] if isinstance(reasons, list) else []
        raw_worker_name = str(getattr(context.config, "backup_node_name", "worker") or "worker")
        worker_name = raw_worker_name if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", raw_worker_name) else "worker"
        fingerprint = str(result.get("fingerprint") or "").strip().lower()
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            fingerprint = ""
        return {
            "worker": worker_name[:64],
            "profile": normalized,
            "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "ready": bool(result.get("ready")),
            "identity_match": bool(result.get("identity_match")),
            "reason_codes": safe_reasons,
            "sessions": sessions,
            "fingerprint": fingerprint,
        }

    @app.post("/internal/v1/profiles/{profile}/session/commit", dependencies=[Depends(authorize)])
    def commit_profile_bundle(profile: str, body: dict[str, Any]):
        sync_kwargs = {}
        if body.get("sync_run_id") and type(body.get("revision")) is int and body.get("revision", 0) > 0:
            sync_kwargs = {
                "sync_run_id": str(body["sync_run_id"]),
                "sync_revision": int(body["revision"]),
            }
        return {
            "committed": context.executor.commit_profile_bundle(
                profile,
                str(body.get("operation_id") or ""),
                **sync_kwargs,
            )
        }

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

    @app.post("/internal/v1/commands", dependencies=[Depends(authorize)])
    def accept_command(body: dict[str, Any]):
        accept = getattr(context.executor, "accept_durable_command", None)
        if not callable(accept):
            raise DomainError(
                "DURABLE_COMMANDS_NOT_READY",
                "Jurnal command worker belum siap.",
                status_code=503,
            )
        return accept(body)

    @app.get(
        "/internal/v1/commands/{command_id}", dependencies=[Depends(authorize)]
    )
    def durable_command_status(
        command_id: str = ApiPath(min_length=1, max_length=160),
    ):
        lookup = getattr(context.executor, "durable_command_status", None)
        snapshot = lookup(command_id) if callable(lookup) else None
        if snapshot is None:
            raise DomainError(
                "WORKER_COMMAND_NOT_FOUND",
                "Command worker tidak ditemukan.",
                status_code=404,
            )
        return snapshot

    @app.post("/internal/v1/jobs", dependencies=[Depends(authorize)])
    def submit_job(body: WorkerJobRequest):
        payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        if not payload.get("execution"):
            payload.pop("execution", None)
        if payload.get("event_sequence_start") is None:
            payload.pop("event_sequence_start", None)
        if payload.get("attempt") is None:
            payload.pop("attempt", None)
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
