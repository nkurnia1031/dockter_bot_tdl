from __future__ import annotations

import hashlib
import re
from typing import Any

from fastapi import Depends, Header, Request

from tme3bot.application.operations import PreparedOperation
from tme3bot.domain.models import DomainError
from tme3bot.domain.operations import OperationStatus
from tme3bot.infrastructure.http_client import JsonHttpError
from tme3bot.names import normalize_profile_name


_PROFILE_RE = re.compile(r"^[a-z0-9_-]{1,48}$")
_ACTIVE_JOB_STATUSES = ("queued", "dispatched", "running", "paused")
_SAFE_WORKER_ERRORS = {
    "PROFILE_DEFAULT_PROTECTED",
    "PROFILE_NAME_INVALID",
    "PROFILE_ROOT_UNSAFE",
    "PROFILE_SESSION_BUSY",
    "PROFILE_DELETE_FAILED",
    "WORKER_UPDATE_REQUIRED",
}


def _require_slug(value: Any) -> str:
    raw = str(value or "").strip().lower()
    normalized = normalize_profile_name(raw)
    if not normalized or raw != normalized or not _PROFILE_RE.fullmatch(raw):
        raise DomainError(
            "PROFILE_NAME_INVALID", "Nama profil lokal tidak valid.", status_code=422
        )
    return normalized


def _profile_registry(context):
    return getattr(context.profile_manager, "profile_registry", None)


def _inventory_names(dispatcher, worker: str) -> set[str]:
    inventory = dispatcher.profile_local_inventory(worker)
    # The worker's raw inventory contract returns only items; public routes add
    # the selected worker name when shaping the response for the Web UI.
    if not isinstance(inventory, dict) or (
        "worker" in inventory
        and str(inventory.get("worker") or "").strip().lower() != worker
    ):
        raise ValueError("inventory_worker_mismatch")
    items = inventory.get("items")
    if not isinstance(items, list):
        raise ValueError("inventory_items_missing")
    names: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("inventory_item_invalid")
        name = _require_slug(item.get("name"))
        if name in names:
            raise ValueError("inventory_duplicate_profile")
        names.add(name)
    return names


def _job_uses_profile(context, job, profile: str, worker: str) -> bool:
    if job.profile == profile:
        return True
    getter = getattr(context.control_plane.jobs, "execution_plan", None)
    plan = getter(job.id) if callable(getter) else None
    keys = plan.get("resource_keys", []) if isinstance(plan, dict) else []
    worker_prefix = f"profile:{profile}:worker:{worker}:"
    backup_keys = {
        f"profile:{profile}:tdl:export",
        f"profile:{profile}:tdl:download",
    }
    return any(
        isinstance(key, str)
        and (key.startswith(worker_prefix) or key in backup_keys)
        for key in keys
    )


def _active_sync_exists(context, profile: str, worker: str) -> bool:
    provisioner = getattr(context, "profile_provisioner", None)
    store = getattr(provisioner, "store", None)
    active_install = getattr(store, "distribution_install_active", None)
    if callable(active_install):
        try:
            if active_install(profile, worker):
                return True
        except (KeyError, TypeError, ValueError):
            return True
    list_requests = getattr(store, "sync_requests", None)
    if not callable(list_requests):
        return False
    try:
        return bool(list_requests(profile, worker))
    except (KeyError, TypeError, ValueError):
        return True


def _assert_no_active_profile_work(context, profile: str, worker: str) -> None:
    for status in _ACTIVE_JOB_STATUSES:
        jobs = context.control_plane.jobs.list(
            worker=worker, status=status, archived=False, offset=0, limit=200
        )
        for job in jobs:
            if _job_uses_profile(context, job, profile, worker):
                raise DomainError(
                    "PROFILE_JOB_ACTIVE",
                    f"Profil {profile} sedang dipakai job pada worker {worker}; tidak ada data yang dihapus.",
                    status_code=409,
                    details={"profile": profile, "worker": worker, "job_id": job.id},
                )
    if _active_sync_exists(context, profile, worker):
        raise DomainError(
            "PROFILE_SYNC_ACTIVE",
            f"Profil {profile} sedang disinkronkan ke worker {worker}; tidak ada data yang dihapus.",
            status_code=409,
            details={"profile": profile, "worker": worker},
        )


def _load_fresh_inventories(context, profile: str) -> tuple[bool, bool]:
    """Return (all_fresh, any_local_copy) using live calls to registered workers."""
    registry = context.worker_registry
    names = registry.names() if registry is not None else []
    if not names:
        return False, False
    dispatcher = context.worker_dispatcher
    found = False
    for worker in names:
        try:
            found = profile in _inventory_names(dispatcher, worker) or found
        except Exception:
            return False, found
    return True, found


def reconcile_pending_identity_cleanups(context) -> list[dict[str, str]]:
    registry = _profile_registry(context)
    pending = getattr(registry, "pending_identity_cleanups", None)
    clear = getattr(registry, "clear_identity_cleanup", None)
    remove_identity = getattr(registry, "remove_identity", None)
    if not callable(pending) or not callable(clear) or not callable(remove_identity):
        return []
    for item in pending():
        profile = str(item.get("profile") or "")
        all_fresh, any_copy = _load_fresh_inventories(context, profile)
        if not all_fresh:
            continue
        if any_copy:
            clear(profile)
        else:
            remove_identity(profile)
    return pending()


def prepare_profile_local_delete(context, actor, target, input_data) -> PreparedOperation:
    profile = _require_slug(target.get("profile"))
    worker = str(target.get("worker") or "").strip().lower()
    if set(target) != {"profile", "worker"} or not worker:
        raise DomainError(
            "PROFILE_DELETE_TARGET_INVALID", "Target hapus profil tidak valid.", status_code=422
        )
    if set(input_data) != {"request_token"}:
        raise DomainError(
            "PROFILE_DELETE_INPUT_INVALID", "Input hapus profil tidak valid.", status_code=422
        )
    request_token = str(input_data.get("request_token") or "")
    if not re.fullmatch(r"[a-f0-9]{64}", request_token):
        raise DomainError(
            "PROFILE_DELETE_INPUT_INVALID", "Kunci operasi hapus profil tidak valid.", status_code=422
        )
    context.control_plane.require_profile(actor, profile)
    default_profile = normalize_profile_name(
        str(getattr(context.profile_manager, "default_profile", "default") or "default")
    )
    if profile == default_profile:
        raise DomainError(
            "PROFILE_DEFAULT_PROTECTED", "Profil default tidak dapat dihapus.", status_code=409
        )
    if context.worker_registry is None or context.worker_registry.get(worker) is None:
        raise DomainError("WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404)
    dispatcher = context.worker_dispatcher
    inventory = getattr(dispatcher, "profile_local_inventory", None)
    if not callable(inventory):
        raise DomainError(
            "WORKER_UPDATE_REQUIRED",
            f"Worker {worker} belum mendukung scan profil lokal.",
            status_code=409,
        )
    try:
        names = _inventory_names(dispatcher, worker)
    except Exception as exc:
        if isinstance(exc, DomainError):
            raise
        raise DomainError(
            "WORKER_UNAVAILABLE",
            f"Inventaris profil worker {worker} tidak dapat dipastikan; tidak ada data yang dihapus.",
            status_code=503,
        ) from None
    if profile not in names:
        raise DomainError(
            "PROFILE_NOT_IN_LOCAL_SCAN",
            f"Profil {profile} tidak ditemukan pada hasil scan terbaru worker {worker}.",
            status_code=404,
        )
    _assert_no_active_profile_work(context, profile, worker)

    registry = _profile_registry(context)
    reserve = getattr(registry, "begin_local_deletion", None)
    if not callable(reserve) or not reserve(profile, worker, request_token):
        raise DomainError(
            "PROFILE_DELETION_IN_PROGRESS",
            f"Penghapusan profil {profile} pada worker {worker} sudah berlangsung.",
            status_code=409,
        )
    return PreparedOperation(
        profile=profile,
        target={"profile": profile, "worker": worker},
        private_payload={
            "profile": profile,
            "worker": worker,
            "request_token": request_token,
            "actor_user_id": int(actor.telegram_user_id),
        },
        phase="queued",
    )


def _transition(context, operation, *, status, phase: str, progress: dict[str, Any]):
    service = getattr(context, "operation_service", None)
    store = getattr(service, "store", None)
    if store is None:
        return None
    return store.transition_from_job(
        operation.id,
        expected_revision=operation.revision,
        status=status,
        phase=phase,
        safe_progress=progress,
    )


def _finish_marker(context, payload: dict[str, Any]) -> None:
    registry = _profile_registry(context)
    finish = getattr(registry, "finish_local_deletion", None)
    if callable(finish):
        finish(
            str(payload.get("profile") or ""),
            str(payload.get("worker") or ""),
            str(payload.get("request_token") or ""),
        )


def _mapping_status_after_delete(context, profile: str, deleted_worker: str) -> str:
    registry = _profile_registry(context)
    all_fresh, any_copy = _load_fresh_inventories(context, profile)
    if not all_fresh:
        mark_pending = getattr(registry, "mark_identity_cleanup_pending", None)
        if callable(mark_pending):
            mark_pending(profile, deleted_worker)
        return "pending_recheck"
    clear = getattr(registry, "clear_identity_cleanup", None)
    if any_copy:
        if callable(clear):
            clear(profile)
        return "local_copy_remaining"
    remove_identity = getattr(registry, "remove_identity", None)
    if callable(remove_identity):
        remove_identity(profile)
    return "removed"


def _mark_distribution_removed(context, profile: str, worker: str) -> None:
    provisioner = getattr(context, "profile_provisioner", None)
    store = getattr(provisioner, "store", None)
    mark_removed = getattr(store, "mark_local_profile_deleted", None)
    if callable(mark_removed):
        mark_removed(profile, worker)


def advance_profile_local_delete_command(command: dict[str, Any], context) -> dict[str, str]:
    payload = command.get("private_payload")
    if not isinstance(payload, dict):
        return {"status": "retry", "reason": "payload_missing"}
    operation_id = str(command.get("operation_id") or "")
    profile = str(payload.get("profile") or "")
    worker = str(payload.get("worker") or "")
    actor_user_id = int(payload.get("actor_user_id") or 0)
    service = getattr(context, "operation_service", None)
    store = getattr(service, "store", None)
    operation = store.get_for_actor(operation_id, actor_user_id) if store is not None else None
    if operation is None:
        _finish_marker(context, payload)
        return {"status": "terminal", "reason": "operation_missing"}
    if operation.status.terminal:
        _finish_marker(context, payload)
        return {"status": "terminal", "reason": "operation_terminal"}
    if operation.status == OperationStatus.CANCELLING:
        _transition(
            context, operation, status=OperationStatus.CANCELLED,
            phase="cancelled", progress={"profile": profile, "worker": worker},
        )
        _finish_marker(context, payload)
        return {"status": "terminal", "reason": "cancelled_before_worker_request"}
    registry = _profile_registry(context)
    reserve = getattr(registry, "begin_local_deletion", None)
    if not callable(reserve) or not reserve(
        profile, worker, str(payload.get("request_token") or "")
    ):
        _transition(
            context, operation, status=OperationStatus.FAILED,
            phase="failed",
            progress={
                "profile": profile,
                "worker": worker,
                "result": "failed",
                "reason_code": "PROFILE_DELETION_IN_PROGRESS",
            },
        )
        return {"status": "terminal", "reason": "deletion_already_active"}
    try:
        _assert_no_active_profile_work(context, profile, worker)
    except DomainError as exc:
        _transition(
            context, operation, status=OperationStatus.FAILED,
            phase="failed",
            progress={
                "profile": profile,
                "worker": worker,
                "result": "failed",
                "reason_code": exc.code,
            },
        )
        _finish_marker(context, payload)
        return {"status": "terminal", "reason": exc.code.lower()}
    if operation.status != OperationStatus.RUNNING:
        operation = _transition(
            context, operation, status=OperationStatus.RUNNING,
            phase="worker_delete", progress={"profile": profile, "worker": worker},
        ) or operation

    delete = getattr(context.worker_dispatcher, "delete_local_profile", None)
    if not callable(delete):
        _transition(
            context, operation, status=OperationStatus.FAILED,
            phase="failed", progress={"profile": profile, "worker": worker, "result": "failed"},
        )
        _finish_marker(context, payload)
        return {"status": "terminal", "reason": "worker_delete_unavailable"}
    try:
        result = delete(worker, profile)
        if (
            not isinstance(result, dict)
            or str(result.get("profile") or "") != profile
            or result.get("deleted") is not True
        ):
            raise JsonHttpError(502, "Worker delete response invalid.", kind="protocol")
    except JsonHttpError as exc:
        if exc.kind in {"network", "timeout"} or exc.status in {502, 503, 504}:
            _transition(
                context, operation, status=OperationStatus.WAITING_WORKER,
                phase="waiting_worker",
                progress={"profile": profile, "worker": worker, "result": "waiting_worker"},
            )
            return {"status": "retry", "reason": "worker_unavailable"}
        payload_error = exc.payload.get("error") if isinstance(exc.payload, dict) else None
        code = str(payload_error.get("code") or "") if isinstance(payload_error, dict) else ""
        safe_code = code if code in _SAFE_WORKER_ERRORS else "PROFILE_DELETE_FAILED"
        _transition(
            context, operation, status=OperationStatus.FAILED,
            phase="failed",
            progress={"profile": profile, "worker": worker, "result": "failed", "reason_code": safe_code},
        )
        _finish_marker(context, payload)
        return {"status": "terminal", "reason": safe_code.lower()}
    except Exception:
        _transition(
            context, operation, status=OperationStatus.FAILED,
            phase="failed",
            progress={"profile": profile, "worker": worker, "result": "failed", "reason_code": "PROFILE_DELETE_FAILED"},
        )
        _finish_marker(context, payload)
        return {"status": "terminal", "reason": "worker_delete_failed"}

    gate = getattr(
        getattr(context, "control_plane", None), "runtime_readiness_gate", None
    )
    invalidate = getattr(gate, "invalidate_profile_mutation", None)
    if callable(invalidate):
        invalidate(
            profile=profile,
            worker=worker,
            reason_code="PROFILE_SESSION_MISSING",
        )

    try:
        _mark_distribution_removed(context, profile, worker)
    except Exception:
        # The worker deletion already succeeded. Keep admission closed and
        # retry durably until the distribution ledger also records the delete.
        _transition(
            context, operation, status=OperationStatus.WAITING_WORKER,
            phase="waiting_worker",
            progress={"profile": profile, "worker": worker, "result": "waiting_worker"},
        )
        return {"status": "retry", "reason": "distribution_ledger_unavailable"}

    mapping_status = _mapping_status_after_delete(context, profile, worker)
    _transition(
        context, operation, status=OperationStatus.SUCCEEDED,
        phase="completed",
        progress={
            "profile": profile,
            "worker": worker,
            "result": "deleted",
            "identity_mapping_status": mapping_status,
        },
    )
    _finish_marker(context, payload)
    return {"status": "accepted"}


def advance_profile_local_delete_cancel(command: dict[str, Any], context) -> dict[str, str]:
    payload = command.get("private_payload")
    if not isinstance(payload, dict):
        return {"status": "retry", "reason": "payload_missing"}
    service = getattr(context, "operation_service", None)
    store = getattr(service, "store", None)
    operation_id = str(command.get("operation_id") or "")
    actor_user_id = int(payload.get("actor_user_id") or 0)
    operation = store.get_for_actor(operation_id, actor_user_id) if store is not None else None
    if operation is None or operation.status.terminal:
        _finish_marker(context, payload)
        return {"status": "terminal", "reason": "operation_terminal"}
    if operation.status == OperationStatus.CANCELLING:
        _transition(
            context, operation, status=OperationStatus.CANCELLED,
            phase="cancelled", progress={
                "profile": str(payload.get("profile") or ""),
                "worker": str(payload.get("worker") or ""),
            },
        )
        _finish_marker(context, payload)
    return {"status": "terminal", "reason": "cancelled"}


def register_profile_local_delete(app, context, *, current_actor) -> None:
    from tme3bot.api.schemas import OperationResponse

    @app.delete(
        "/api/v1/workers/{worker}/profiles/local/{profile}",
        status_code=202,
        response_model=OperationResponse,
    )
    def delete_local_profile(
        worker: str,
        profile: str,
        request: Request,
        actor=Depends(current_actor),
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=1, max_length=200
        ),
    ):
        operations = getattr(context, "operation_service", None)
        if operations is None:
            raise DomainError(
                "OPERATIONS_UNAVAILABLE", "Operasi durable belum tersedia.", status_code=503
            )
        if "profile.local_delete" not in operations.supported_kinds():
            raise DomainError(
                "PROFILE_DELETE_UNAVAILABLE",
                "Worker queue belum tersedia untuk penghapusan profil yang dapat dipulihkan.",
                status_code=503,
            )
        worker_name = str(worker or "").strip().lower()
        selected_profile = _require_slug(profile)
        token = hashlib.sha256(idempotency_key.strip().encode("utf-8")).hexdigest()
        registry = _profile_registry(context)
        try:
            operation, _ = operations.submit(
                actor,
                kind="profile.local_delete",
                target={"profile": selected_profile, "worker": worker_name},
                input_data={"request_token": token},
                idempotency_key=idempotency_key,
                request_id=request.state.request_id,
                request_route=getattr(request.scope.get("route"), "path", ""),
            )
        except Exception:
            # The reservation is token-scoped, so a failed first submission
            # cannot release a different delete already in progress.
            finish = getattr(registry, "finish_local_deletion", None)
            if callable(finish):
                finish(selected_profile, worker_name, token)
            raise
        request.state.activity_operation_id = operation.id
        return operation.to_public(status_url=f"/api/v1/operations/{operation.id}")
