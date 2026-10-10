from __future__ import annotations

import hmac
import re
from typing import Any

from fastapi import Depends, Header, Request
from fastapi.responses import StreamingResponse

from tme3bot.application.operations import PreparedOperation
from tme3bot.domain.models import DomainError
from tme3bot.domain.operations import OperationStatus


_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_ERROR_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_SYNC_PHASES = {
    "queued", "manifest_fetch", "revision_compare", "bundle_download",
    "bundle_validation", "session_validation", "session_install", "session_commit", "acknowledgement",
    "worker_unreachable", "completed", "cancelled",
}
_SYNC_STATUSES = {"queued", "running", "succeeded", "failed", "waiting", "cancelled"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "backend", "worker-local", "testserver"}


def _worker_transport_is_secure(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    return str(request.url.hostname or "").lower() in _LOCAL_HOSTS


def _worker_identity(context, worker_name: str, worker_token: str) -> str:
    name = str(worker_name or "").strip().lower()
    registry = context.worker_registry
    record = registry.get(name) if registry is not None else None
    if not record or not worker_token:
        raise DomainError("WORKER_UNAUTHORIZED", "Identitas worker tidak valid.", status_code=401)
    matches = [
        registered_name
        for registered_name, item in registry.list().items()
        if hmac.compare_digest(str(item.get("token") or ""), str(worker_token))
    ]
    # A shared worker token cannot prove which worker is making this request.
    if len(matches) != 1 or matches[0] != name or not hmac.compare_digest(
        str(record.get("token") or ""), str(worker_token)
    ):
        raise DomainError(
            "WORKER_IDENTITY_AMBIGUOUS",
            "Token worker harus unik untuk mengonfirmasi profil.",
            status_code=409,
        )
    return name


def _complete_sync_operation(context, request: dict[str, Any], *, succeeded: bool, revision: int) -> None:
    service = context.operation_service
    if service is None:
        return
    store = service.store
    operation = store.get_for_actor(
        str(request["operation_id"]), int(request["actor_user_id"])
    )
    if operation is None or operation.status.terminal:
        return
    if operation.status == OperationStatus.WAITING_WORKER:
        operation = store.transition_from_job(
            operation.id,
            expected_revision=operation.revision,
            status=OperationStatus.RUNNING,
            phase="install_confirmed",
            safe_progress={"worker": operation.target.get("worker", "")},
        )
        if operation is None:
            return
    target_status = OperationStatus.SUCCEEDED if succeeded else OperationStatus.FAILED
    store.transition_from_job(
        operation.id,
        expected_revision=operation.revision,
        status=target_status,
        phase="installed" if succeeded else "install_failed",
        safe_progress={"worker": operation.target.get("worker", ""), "installed_revision": int(revision)},
    )


def register_profile_sync(app, context, *, require_internal, current_actor) -> None:
    def authenticated_worker(
        request: Request,
        worker_name: str = Header(..., alias="X-Worker-Name", min_length=1, max_length=48),
        worker_token: str = Header(..., alias="X-Worker-Token", min_length=1, max_length=512),
    ) -> str:
        if not _worker_transport_is_secure(request):
            raise DomainError(
                "PROFILE_TRANSFER_REQUIRES_HTTPS",
                "Sinkronisasi profil worker remote wajib memakai HTTPS.",
                status_code=426,
            )
        return _worker_identity(context, worker_name, worker_token)

    @app.get(
        "/internal/v1/profile-manifest",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def profile_manifest(worker: str = Depends(authenticated_worker)):
        provisioner = context.profile_provisioner
        if provisioner is None:
            raise DomainError("PROFILE_VAULT_UNAVAILABLE", "Vault profil belum tersedia.", status_code=503)
        return {"profiles": provisioner.store.profile_manifest(worker)}

    @app.post(
        "/internal/v1/profile-sync/events",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def report_profile_sync_event(
        body: dict[str, Any], worker: str = Depends(authenticated_worker)
    ):
        provisioner = context.profile_provisioner
        if provisioner is None:
            raise DomainError("PROFILE_VAULT_UNAVAILABLE", "Vault profil belum tersedia.", status_code=503)
        allowed = {"profile", "run_id", "sequence", "revision", "phase", "status", "code", "details"}
        required = {"profile", "run_id", "sequence", "revision", "phase", "status"}
        if set(body) - allowed or not required.issubset(body):
            raise DomainError("PROFILE_SYNC_EVENT_INVALID", "Event sinkronisasi profil tidak valid.", status_code=422)
        profile = str(body.get("profile") or "").strip().lower()
        run_id = str(body.get("run_id") or "")
        sequence = body.get("sequence")
        revision = body.get("revision")
        phase = str(body.get("phase") or "")
        status = str(body.get("status") or "")
        if (
            not profile
            or len(profile) > 48
            or not _RUN_ID_RE.fullmatch(run_id)
            or type(sequence) is not int
            or sequence < 1
            or type(revision) is not int
            or revision < 1
            or phase not in _SYNC_PHASES
            or status not in _SYNC_STATUSES
        ):
            raise DomainError("PROFILE_SYNC_EVENT_INVALID", "Event sinkronisasi profil tidak valid.", status_code=422)
        assigned = any(
            str(item.get("profile") or "") == profile
            for item in provisioner.store.profile_manifest(worker)
        )
        if not assigned:
            raise DomainError("PROFILE_SYNC_NOT_ASSIGNED", "Profil tidak ditugaskan ke worker ini.", status_code=403)
        code = str(body.get("code") or "")
        if code and not _ERROR_CODE_RE.fullmatch(code):
            raise DomainError("PROFILE_SYNC_EVENT_INVALID", "Kode event sinkronisasi tidak valid.", status_code=422)
        details = body.get("details")
        if details is not None and not isinstance(details, dict):
            raise DomainError("PROFILE_SYNC_EVENT_INVALID", "Detail event sinkronisasi tidak valid.", status_code=422)
        row_id = provisioner.store.append_profile_sync_log(
            profile=profile,
            worker=worker,
            run_id=run_id,
            sequence=sequence,
            revision=revision,
            phase=phase,
            status=status,
            code=code,
            details=details,
        )
        desired = provisioner.store.desired_revision(profile)
        if (
            status == "failed"
            and phase == "completed"
            and desired is not None
            and int(desired["revision"]) == revision
        ):
            provisioner.store.update_distribution(
                profile,
                worker,
                "failed",
                code or "PROFILE_SYNC_FAILED",
            )
            for sync_request in provisioner.store.finish_sync_requests(
                profile, worker, revision, "failed"
            ):
                _complete_sync_operation(
                    context,
                    sync_request,
                    succeeded=False,
                    revision=revision,
                )
        return {"accepted": True, "duplicate": row_id is None}

    @app.get("/api/v1/profiles/{profile}/workers/{worker}/sync-logs")
    def read_profile_sync_logs(
        profile: str,
        worker: str,
        after_id: int = 0,
        limit: int = 100,
        actor=Depends(current_actor),
    ):
        normalized = str(profile or "").strip().lower()
        worker_name = str(worker or "").strip().lower()
        if not normalized or len(normalized) > 48 or not worker_name or len(worker_name) > 48:
            raise DomainError("PROFILE_SYNC_TARGET_INVALID", "Target sinkronisasi profil tidak valid.", status_code=422)
        context.control_plane.require_profile(actor, normalized)
        provisioner = context.profile_provisioner
        if provisioner is None or provisioner.store.desired_revision(normalized) is None:
            raise DomainError("PROFILE_NOT_VAULTED", "Profil belum memiliki revision di vault.", status_code=404)
        if context.worker_registry is None or context.worker_registry.get(worker_name) is None:
            raise DomainError("WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404)
        return provisioner.store.profile_sync_logs(
            normalized, worker_name, after_id=max(0, int(after_id)), limit=min(500, max(1, int(limit)))
        )

    @app.get(
        "/internal/v1/profiles/{profile}/bundles/{revision}",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def profile_bundle(
        profile: str,
        revision: int,
        worker: str = Depends(authenticated_worker),
    ):
        provisioner = context.profile_provisioner
        if provisioner is None:
            raise DomainError("PROFILE_VAULT_UNAVAILABLE", "Vault profil belum tersedia.", status_code=503)
        item = provisioner.store.bundle_for_worker(profile, revision, worker)
        if item is None:
            raise DomainError("PROFILE_BUNDLE_NOT_ASSIGNED", "Revision profil tidak ditugaskan ke worker ini.", status_code=404)
        data = item["bundle"]

        def chunks():
            for offset in range(0, len(data), 64 * 1024):
                yield data[offset : offset + 64 * 1024]

        return StreamingResponse(
            chunks(),
            media_type="application/zip",
            headers={
                "Cache-Control": "no-store",
                "Content-Length": str(len(data)),
                "ETag": '"' + str(item["bundle_sha256"]) + '"',
                "X-Profile-Revision": str(item["revision"]),
                "X-Profile-Format-Version": str(item["format_version"]),
            },
        )

    @app.post(
        "/internal/v1/profiles/{profile}/ack",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def acknowledge_profile_bundle(
        profile: str,
        body: dict[str, Any],
        worker: str = Depends(authenticated_worker),
    ):
        provisioner = context.profile_provisioner
        if provisioner is None:
            raise DomainError("PROFILE_VAULT_UNAVAILABLE", "Vault profil belum tersedia.", status_code=503)
        allowed = {"revision", "bundle_sha256", "telegram_user_id", "error_code"}
        if set(body) - allowed or not {"revision", "bundle_sha256", "telegram_user_id"}.issubset(body):
            raise DomainError("PROFILE_ACK_INVALID", "Payload ACK profil tidak valid.", status_code=422)
        digest = str(body.get("bundle_sha256") or "")
        if not _SHA256_RE.fullmatch(digest):
            raise DomainError("PROFILE_ACK_INVALID", "Hash bundle tidak valid.", status_code=422)
        error_code = body.get("error_code")
        if error_code is not None and not _ERROR_CODE_RE.fullmatch(str(error_code)):
            raise DomainError("PROFILE_ACK_INVALID", "Kode error worker tidak valid.", status_code=422)
        revision_value = body["revision"]
        identity_value = body["telegram_user_id"]
        if (
            type(revision_value) is not int
            or type(identity_value) is not int
            or revision_value < 1
            or identity_value < 1
        ):
            raise DomainError("PROFILE_ACK_INVALID", "Revision atau identity worker tidak valid.", status_code=422)
        revision = revision_value
        telegram_user_id = identity_value

        result = provisioner.store.acknowledge_bundle(
            profile,
            worker,
            revision,
            digest.lower(),
            telegram_user_id,
            error_code=str(error_code) if error_code is not None else None,
        )
        if result["reason"] == "not_assigned":
            raise DomainError("PROFILE_ACK_NOT_ASSIGNED", "Worker tidak ditugaskan ke profil ini.", status_code=403)
        if result["accepted"]:
            provisioning_id = provisioner.store.distribution_provisioning_id(profile, worker)
            info = provisioner.store.provisioning(provisioning_id) if provisioning_id else None
            if info is not None and info["status"] == "distributing":
                profile_name, telegram_user_id = provisioner.store.mark_active(provisioning_id)
                activated = provisioner.store.provisioning(provisioning_id)
                if activated is not None and activated["status"] == "active":
                    registry = getattr(
                        getattr(provisioner, "profile_manager", None),
                        "profile_registry",
                        None,
                    )
                    if registry is not None:
                        registry.register_vaulted(profile_name, telegram_user_id)
        if result["reason"] != "stale_revision":
            terminal_status = "succeeded" if result["accepted"] else "failed"
            requests = provisioner.store.finish_sync_requests(
                profile, worker, revision, terminal_status
            )
            for sync_request in requests:
                _complete_sync_operation(
                    context,
                    sync_request,
                    succeeded=bool(result["accepted"]),
                    revision=revision,
                )
        return result


def prepare_profile_sync_operation(context, actor, target, input_data) -> PreparedOperation:
    profile = str(target.get("profile") or "").strip().lower()
    worker = str(target.get("worker") or "").strip().lower()
    mode = str((input_data or {}).get("mode") or "check").strip().lower()
    if set(target) - {"profile", "worker"} or not profile or not worker:
        raise DomainError("PROFILE_SYNC_TARGET_INVALID", "Target sinkronisasi profil tidak valid.", status_code=422)
    if set(input_data or {}) - {"mode"} or mode not in {"check", "repair"}:
        raise DomainError("PROFILE_SYNC_MODE_INVALID", "Mode pemulihan profil tidak valid.", status_code=422)
    context.control_plane.require_profile(actor, profile)
    provisioner = context.profile_provisioner
    if provisioner is None or provisioner.store.desired_revision(profile) is None:
        raise DomainError("PROFILE_NOT_VAULTED", "Profil belum memiliki revision di vault.", status_code=409)
    if context.worker_registry is None or context.worker_registry.get(worker) is None:
        raise DomainError("WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404)
    provisioner.store.add_worker_for_active_profiles(worker)
    revision = provisioner.store.desired_revision(profile)
    if revision is None:
        raise DomainError("PROFILE_NOT_VAULTED", "Profil belum memiliki revision di vault.", status_code=409)
    safe_target = {
        "profile": profile,
        "worker": worker,
        "desired_revision": int(revision["revision"]),
        "mode": mode,
    }
    return PreparedOperation(
        profile=profile,
        target=safe_target,
        private_payload={
            **safe_target,
            "actor_user_id": int(actor.telegram_user_id),
            "mode": mode,
        },
        phase="queued",
    )


def advance_profile_sync_command(command: dict[str, Any], context) -> dict[str, str]:
    payload = command.get("private_payload")
    if not isinstance(payload, dict):
        return {"status": "retry", "reason": "payload_missing"}
    operation_id = str(command.get("operation_id") or "")
    profile = str(payload.get("profile") or "")
    worker = str(payload.get("worker") or "")
    mode = str(payload.get("mode") or "check")
    actor_user_id = int(payload.get("actor_user_id") or 0)
    provisioner = context.profile_provisioner
    revision = provisioner.store.desired_revision(profile) if provisioner else None
    if not operation_id or not profile or not worker or not actor_user_id or revision is None:
        return {"status": "terminal", "reason": "profile_unavailable"}
    try:
        provisioner.store.add_worker_for_active_profiles(worker)
        provisioner.store.request_sync(
            operation_id,
            actor_user_id,
            profile,
            worker,
            int(revision["revision"]),
            mode=mode,
        )
    except (KeyError, ValueError):
        return {"status": "retry", "reason": "sync_target_changed"}
    run_id = operation_id if _RUN_ID_RE.fullmatch(operation_id) else re.sub(r"[^A-Za-z0-9_-]", "", operation_id)[:64]
    provisioner.store.append_profile_sync_log(
        profile=profile,
        worker=worker,
        run_id=run_id,
        revision=int(revision["revision"]),
        phase="queued",
        status="queued",
        code="PROFILE_SYNC_QUEUED",
        details={"desired_revision": int(revision["revision"])},
    )
    service = context.operation_service
    operation_store = service.store if service is not None else None
    if operation_store is not None:
        operation = operation_store.get_for_actor(operation_id, actor_user_id)
        if operation is not None and not operation.status.terminal:
            operation_store.transition_from_job(
                operation.id,
                expected_revision=operation.revision,
                status=OperationStatus.WAITING_WORKER,
                phase="waiting_worker",
                safe_progress={"worker": worker, "desired_revision": int(revision["revision"])},
            )
    request_worker_sync = getattr(context.worker_dispatcher, "request_profile_sync", None)
    if callable(request_worker_sync):
        try:
            request_worker_sync(worker, profile=profile, mode=mode)
        except Exception:
            provisioner.store.append_profile_sync_log(
                profile=profile,
                worker=worker,
                run_id=run_id,
                revision=int(revision["revision"]),
                phase="worker_unreachable",
                status="waiting",
                code="WORKER_UNAVAILABLE",
            )
            # Keep the durable operation waiting. The outbox retries this
            # command, and the Web can show the worker's current diagnostic.
            return {"status": "retry", "reason": "worker_sync_unavailable"}
        provisioner.store.append_profile_sync_log(
            profile=profile,
            worker=worker,
            run_id=run_id,
            revision=int(revision["revision"]),
            phase="queued",
            status="running",
            code="WORKER_SYNC_REQUESTED",
        )
    return {"status": "accepted"}


def advance_profile_sync_cancel(command: dict[str, Any], context) -> dict[str, str]:
    payload = command.get("private_payload")
    if not isinstance(payload, dict):
        return {"status": "retry", "reason": "payload_missing"}
    operation_id = str(command.get("operation_id") or "")
    actor_user_id = int(payload.get("actor_user_id") or 0)
    provisioner = context.profile_provisioner
    sync_request = None
    worker_cancel_status = "already_finished"
    if provisioner is not None:
        sync_request = provisioner.store.cancel_sync_request(operation_id)
    if provisioner is not None and sync_request is not None:
        provisioner.store.append_profile_sync_log(
            profile=str(sync_request["profile"]),
            worker=str(sync_request["worker"]),
            run_id=operation_id if _RUN_ID_RE.fullmatch(operation_id) else re.sub(r"[^A-Za-z0-9_-]", "", operation_id)[:64],
            revision=int(sync_request["desired_revision"]),
            phase="cancelled",
            status="cancelled",
            code="PROFILE_SYNC_CANCELLED",
        )
        remaining = provisioner.store.sync_requests(
            sync_request["profile"],
            sync_request["worker"],
        )
        cancel_worker_sync = getattr(context.worker_dispatcher, "cancel_profile_sync", None)
        if remaining:
            worker_cancel_status = "other_requests_pending"
        elif callable(cancel_worker_sync):
            try:
                result = cancel_worker_sync(
                    sync_request["worker"],
                    sync_request["profile"],
                    mode=str(sync_request.get("mode") or "check"),
                )
                status = str(result.get("status") or "unknown") if isinstance(result, dict) else "unknown"
                worker_cancel_status = status if status in {"cancelled", "cancelling", "not_found"} else "unknown"
            except Exception:
                # The operation is still cancelled while an offline worker's
                # process state remains unconfirmed.
                worker_cancel_status = "worker_unavailable"
        else:
            worker_cancel_status = "unsupported"
    service = context.operation_service
    operation_store = service.store if service is not None else None
    if operation_store is not None:
        operation = operation_store.get_for_actor(operation_id, actor_user_id)
        if operation is not None and operation.status == OperationStatus.CANCELLING:
            operation_store.transition_from_job(
                operation.id,
                expected_revision=operation.revision,
                status=OperationStatus.CANCELLED,
                phase="cancelled",
                safe_progress={
                    "worker": operation.target.get("worker", ""),
                    "worker_sync_cancel": worker_cancel_status,
                },
            )
    return {"status": "terminal", "worker_sync_cancel": worker_cancel_status}
