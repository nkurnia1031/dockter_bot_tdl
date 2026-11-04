from __future__ import annotations

import hmac

from tme3bot.domain.models import DomainError


def authenticated_worker_identity(context, worker_name: str, worker_token: str) -> str:
    name = str(worker_name or "").strip().lower()
    registry = getattr(context, "worker_registry", None)
    record = registry.get(name) if registry is not None else None
    if not record or not worker_token:
        raise DomainError("WORKER_UNAUTHORIZED", "Identitas worker tidak valid.", status_code=401)
    matches = [
        registered_name
        for registered_name, item in registry.list().items()
        if hmac.compare_digest(str(item.get("token") or ""), str(worker_token))
    ]
    if len(matches) != 1 or matches[0] != name or not hmac.compare_digest(
        str(record.get("token") or ""), str(worker_token)
    ):
        raise DomainError(
            "WORKER_IDENTITY_AMBIGUOUS",
            "Token worker harus unik untuk mengonfirmasi profil.",
            status_code=409,
        )
    return name
