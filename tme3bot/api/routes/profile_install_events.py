from __future__ import annotations

import re
from typing import Any

from fastapi import Body, Depends, Header

from tme3bot.domain.models import DomainError
from tme3bot.api.worker_auth import authenticated_worker_identity


_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_CODE_RE = re.compile(r"^[A-Z0-9_-]{1,64}$")
_PHASES = {
    "queued", "archive_download",
    "bundle_validation", "session_validation", "session_install", "session_commit",
    "worker_unreachable", "completed", "cancelled",
    "download_staging", "download_validation", "download_install",
    "export_staging", "export_validation", "export_install", "upload_staging",
    "upload_validation", "upload_install", "identity_install", "transaction_rollback",
    "installation_reused", "failed",
}
_STATUSES = {"queued", "running", "succeeded", "failed", "waiting", "cancelled"}


def register_profile_install_events(app, context, *, require_internal) -> None:
    def authenticated_worker(
        worker_name: str = Header(..., alias="X-Worker-Name", min_length=1, max_length=48),
        worker_token: str = Header(..., alias="X-Worker-Token", min_length=1, max_length=512),
    ) -> str:
        return authenticated_worker_identity(context, worker_name, worker_token)

    @app.post(
        "/internal/v1/profile-install/events",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def report_profile_install_event(
        body: dict[str, Any] = Body(...),
        worker: str = Depends(authenticated_worker),
    ):
        provisioner = getattr(context, "profile_provisioner", None)
        if provisioner is None:
            raise DomainError("PROFILE_VAULT_UNAVAILABLE", "Vault profil belum tersedia.", status_code=503)
        allowed = {"profile", "run_id", "sequence", "revision", "phase", "status", "code", "details"}
        required = {"profile", "run_id", "sequence", "revision", "phase", "status"}
        if set(body) - allowed or not required.issubset(body):
            raise DomainError("PROFILE_INSTALL_EVENT_INVALID", "Event pemasangan profil tidak valid.", status_code=422)
        profile = str(body.get("profile") or "").strip().lower()
        run_id = str(body.get("run_id") or "")
        sequence, revision = body.get("sequence"), body.get("revision")
        phase, status = str(body.get("phase") or ""), str(body.get("status") or "")
        code = str(body.get("code") or "")
        details = body.get("details")
        if (
            not _PROFILE_RE.fullmatch(profile)
            or not _RUN_ID_RE.fullmatch(run_id)
            or type(sequence) is not int or sequence < 1
            or type(revision) is not int or revision < 1
            or phase not in _PHASES or status not in _STATUSES
            or (code and not _CODE_RE.fullmatch(code))
            or (details is not None and not isinstance(details, dict))
        ):
            raise DomainError("PROFILE_INSTALL_EVENT_INVALID", "Event pemasangan profil tidak valid.", status_code=422)
        store = provisioner.store
        if not store.distribution_provisioning_id(profile, worker):
            raise DomainError("PROFILE_INSTALL_NOT_ASSIGNED", "Profil tidak ditugaskan ke worker ini.", status_code=403)
        row_id = store.append_profile_install_event(
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
        return {"accepted": True, "duplicate": row_id is None}
