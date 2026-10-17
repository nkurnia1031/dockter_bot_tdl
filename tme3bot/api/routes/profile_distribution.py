from __future__ import annotations

import re
from typing import Any

from fastapi import Depends, Header, Request

from tme3bot.domain.models import DomainError


_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_OPERATION_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_CODE_RE = re.compile(r"^[A-Z0-9_-]{1,64}$")
_PHASES = {
    "archive_download", "bundle_validation", "download_staging", "download_validation",
    "download_install", "export_staging", "export_validation", "export_install",
    "upload_staging", "upload_validation", "upload_install", "identity_install",
    "session_commit", "transaction_rollback", "completed", "failed",
}
_STATUSES = {"running", "waiting", "succeeded", "failed"}


def register_profile_distribution(
    app, context, *, current_actor, require_internal
) -> None:
    from fastapi import Body

    def store():
        value = getattr(context, "profile_distribution_store", None)
        if value is None:
            raise DomainError("PROFILE_DISTRIBUTION_UNAVAILABLE", "Distribusi profil belum tersedia.", status_code=503)
        return value

    def authenticated_worker(
        worker_name: str = Header(..., alias="X-Worker-Name", min_length=1, max_length=48),
        worker_token: str = Header(..., alias="X-Worker-Token", min_length=1, max_length=512),
    ) -> str:
        from tme3bot.api.routes.profile_sync import _worker_identity
        return _worker_identity(context, worker_name, worker_token)

    @app.post("/api/v1/profiles/{profile}/distributions", status_code=202)
    def start_distribution(
        profile: str,
        request: Request,
        actor=Depends(current_actor),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        normalized = str(profile or "").strip().lower()
        if not _PROFILE_RE.fullmatch(normalized):
            raise DomainError("PROFILE_NAME_INVALID", "Nama profil tidak valid.", status_code=422)
        context.control_plane.require_profile(actor, normalized)
        provisioner = getattr(context, "profile_provisioner", None)
        if provisioner is None:
            raise DomainError("PROFILE_VAULT_UNAVAILABLE", "Vault profil belum tersedia.", status_code=503)
        revision = provisioner.store.desired_revision(normalized)
        if revision is None:
            raise DomainError("PROFILE_NOT_VAULTED", "Profil belum memiliki revision aktif di Vault.", status_code=409)
        if provisioner.store.bundle_for_revision(normalized, int(revision["revision"])) is None:
            raise DomainError("PROFILE_REVISION_UNAVAILABLE", "Revision Vault tidak tersedia.", status_code=409)
        registry = getattr(context, "worker_registry", None)
        workers = sorted(set(registry.names())) if registry is not None else []
        if not workers:
            raise DomainError("WORKERS_UNAVAILABLE", "Tidak ada worker terdaftar untuk distribusi.", status_code=409)
        config = getattr(context, "config", None)
        if (
            int(getattr(config, "backup_channel_id", 0) or 0) == 0
            or not str(getattr(config, "backup_channel_ref", "") or "").strip()
            or not callable(getattr(getattr(context, "bot", None), "send_document", None))
        ):
            raise DomainError(
                "PROFILE_DISTRIBUTION_CHANNEL_UNAVAILABLE",
                "Kanal backup privat belum tersedia untuk distribusi profil.",
                status_code=503,
            )
        operation, created = store().create(
            actor_user_id=int(actor.telegram_user_id),
            idempotency_key=idempotency_key,
            profile=normalized,
            revision=int(revision["revision"]),
            bundle_sha256=str(revision["bundle_sha256"]),
            telegram_user_id=int(revision["telegram_user_id"]),
            target_workers=workers,
        )
        request.state.activity_operation_id = operation["id"]
        service = getattr(context, "profile_distribution_service", None)
        if created and service is not None:
            service.wake()
        return {**operation, "status_url": f"/api/v1/profile-distributions/{operation['id']}"}

    @app.get("/api/v1/profiles/{profile}/distributions")
    def list_distributions(profile: str, actor=Depends(current_actor)):
        normalized = str(profile or "").strip().lower()
        if not _PROFILE_RE.fullmatch(normalized):
            raise DomainError("PROFILE_NAME_INVALID", "Nama profil tidak valid.", status_code=422)
        context.control_plane.require_profile(actor, normalized)
        return {"items": store().list_for_profile(normalized)}

    @app.get("/api/v1/profile-distributions/{operation_id}")
    def read_distribution(operation_id: str, actor=Depends(current_actor)):
        if not _OPERATION_RE.fullmatch(str(operation_id or "")):
            raise DomainError("OPERATION_ID_INVALID", "ID operasi tidak valid.", status_code=422)
        operation = store().operation(operation_id, int(actor.telegram_user_id))
        if operation is None:
            raise DomainError("OPERATION_NOT_FOUND", "Operasi tidak ditemukan.", status_code=404)
        return operation

    @app.get("/api/v1/profile-distributions/{operation_id}/events")
    def read_distribution_events(
        operation_id: str,
        after_id: int = 0,
        limit: int = 100,
        actor=Depends(current_actor),
    ):
        operation = store().operation(operation_id, int(actor.telegram_user_id))
        if operation is None:
            raise DomainError("OPERATION_NOT_FOUND", "Operasi tidak ditemukan.", status_code=404)
        return store().events(operation_id, after_id=max(0, int(after_id)), limit=min(500, max(1, int(limit))))

    @app.post("/api/v1/profile-distributions/{operation_id}/workers/{worker}/retry", status_code=202)
    def retry_distribution_worker(
        operation_id: str,
        worker: str,
        actor=Depends(current_actor),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        operation = store().operation(operation_id, int(actor.telegram_user_id))
        if operation is None:
            raise DomainError("OPERATION_NOT_FOUND", "Operasi tidak ditemukan.", status_code=404)
        selected_worker = str(worker or "").strip().lower()
        if selected_worker not in operation["target_workers"]:
            raise DomainError("WORKER_NOT_IN_SNAPSHOT", "Worker bukan bagian dari snapshot operasi.", status_code=409)
        if not store().retry_worker(operation_id, selected_worker, idempotency_key):
            raise DomainError("PROFILE_DISTRIBUTION_NOT_RETRYABLE", "Target worker sudah siap atau tidak tersedia.", status_code=409)
        service = getattr(context, "profile_distribution_service", None)
        if service is not None:
            service.wake()
        return store().operation(operation_id, int(actor.telegram_user_id))

    @app.post(
        "/internal/v1/profile-distributions/{operation_id}/events",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def report_distribution_event(
        operation_id: str,
        body: dict[str, Any] = Body(...),
        worker: str = Depends(authenticated_worker),
    ):
        allowed = {"profile", "revision", "sequence", "phase", "status", "code"}
        if set(body) - allowed or not {"profile", "revision", "sequence", "phase", "status"}.issubset(body):
            raise DomainError("PROFILE_DISTRIBUTION_EVENT_INVALID", "Event distribusi tidak valid.", status_code=422)
        profile = str(body.get("profile") or "").strip().lower()
        revision = body.get("revision")
        sequence = body.get("sequence")
        phase = str(body.get("phase") or "")
        status = str(body.get("status") or "")
        code = str(body.get("code") or "")
        if (
            not _PROFILE_RE.fullmatch(profile)
            or type(revision) is not int or revision < 1
            or type(sequence) is not int or sequence < 1
            or phase not in _PHASES or status not in _STATUSES
            or (code and not _CODE_RE.fullmatch(code))
        ):
            raise DomainError("PROFILE_DISTRIBUTION_EVENT_INVALID", "Event distribusi tidak valid.", status_code=422)
        operation = store().operation(operation_id)
        if operation is None or operation["profile"] != profile or int(operation["revision"]) != revision:
            raise DomainError("PROFILE_DISTRIBUTION_NOT_FOUND", "Target distribusi tidak cocok.", status_code=404)
        if worker not in operation["target_workers"]:
            raise DomainError("WORKER_NOT_IN_SNAPSHOT", "Worker bukan bagian dari snapshot operasi.", status_code=403)
        accepted = store().event(operation_id, worker, phase, status, code, sequence=sequence)
        return {"accepted": True, "duplicate": not accepted}
