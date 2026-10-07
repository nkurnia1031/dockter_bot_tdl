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


def register_profile_sync(app, context, *, require_internal) -> None:
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
    del input_data
    profile = str(target.get("profile") or "").strip().lower()
    worker = str(target.get("worker") or "").strip().lower()
    if set(target) - {"profile", "worker"} or not profile or not worker:
        raise DomainError("PROFILE_SYNC_TARGET_INVALID", "Target sinkronisasi profil tidak valid.", status_code=422)
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
    }
    return PreparedOperation(
        profile=profile,
        target=safe_target,
        private_payload={
            **safe_target,
            "actor_user_id": int(actor.telegram_user_id),
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
        )
    except (KeyError, ValueError):
        return {"status": "retry", "reason": "sync_target_changed"}
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
    return {"status": "accepted"}


def advance_profile_sync_cancel(command: dict[str, Any], context) -> dict[str, str]:
    payload = command.get("private_payload")
    if not isinstance(payload, dict):
        return {"status": "retry", "reason": "payload_missing"}
    operation_id = str(command.get("operation_id") or "")
    actor_user_id = int(payload.get("actor_user_id") or 0)
    provisioner = context.profile_provisioner
    if provisioner is not None:
        provisioner.store.cancel_sync_request(operation_id)
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
                safe_progress={"worker": operation.target.get("worker", "")},
            )
    return {"status": "terminal"}
