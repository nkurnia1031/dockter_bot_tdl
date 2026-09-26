"""Versioned wire contract shared by the backend and worker processes."""

from __future__ import annotations

from typing import Any, Iterable

from tme3bot.domain.models import DomainError


WORKER_API_CONTRACT_VERSION = 1

CAP_JOB_DISPATCH = "jobs.dispatch.v1"
CAP_JOB_EVENTS = "jobs.events.v1"
CAP_JOB_CONTROL = "jobs.control.v1"
CAP_JOB_LOG_SNAPSHOT = "jobs.log_snapshot.v1"
CAP_WORKSPACE_TREE = "workspace.tree.v1"
CAP_QUICKMODE_STAGING = "quickmode.staging.v1"
CAP_QUICKMODE_SCAN = "quickmode.scan.v1"
CAP_QUICKMODE_VERIFY = "quickmode.verify.v1"
CAP_QUICKMODE_DELETE = "quickmode.delete.v1"

WORKER_API_CAPABILITIES = frozenset(
    {
        CAP_JOB_DISPATCH,
        CAP_JOB_EVENTS,
        CAP_JOB_CONTROL,
        CAP_JOB_LOG_SNAPSHOT,
        CAP_WORKSPACE_TREE,
        CAP_QUICKMODE_STAGING,
        CAP_QUICKMODE_SCAN,
        CAP_QUICKMODE_VERIFY,
        CAP_QUICKMODE_DELETE,
    }
)
WORKER_JOB_CAPABILITIES = frozenset({CAP_JOB_DISPATCH, CAP_JOB_EVENTS})


def worker_contract_metadata() -> dict[str, Any]:
    """Return the non-secret version and feature set advertised by a worker."""
    return {
        "contract_version": WORKER_API_CONTRACT_VERSION,
        "capabilities": sorted(WORKER_API_CAPABILITIES),
    }


def require_worker_contract(
    response: dict[str, Any],
    worker: str,
    *,
    required_capabilities: Iterable[str] = WORKER_JOB_CAPABILITIES,
) -> dict[str, Any]:
    """Reject workers whose advertised API cannot satisfy a backend operation."""
    if not isinstance(response, dict):
        response = {}
    actual_version = response.get("contract_version")
    if type(actual_version) is not int or actual_version != WORKER_API_CONTRACT_VERSION:
        reported = actual_version if actual_version is not None else "tidak diketahui"
        raise DomainError(
            "WORKER_INCOMPATIBLE",
            f"Worker {worker} memakai kontrak API {reported}; backend memerlukan "
            f"kontrak {WORKER_API_CONTRACT_VERSION}. Deploy worker dengan release "
            "yang kompatibel sebelum mengirim job.",
            status_code=409,
            details={
                "worker": worker,
                "required_contract_version": WORKER_API_CONTRACT_VERSION,
                "actual_contract_version": actual_version,
            },
        )

    advertised = response.get("capabilities")
    if not isinstance(advertised, list) or any(
        not isinstance(item, str) for item in advertised
    ):
        advertised = []
    missing = sorted(set(required_capabilities) - set(advertised))
    if missing:
        raise DomainError(
            "WORKER_INCOMPATIBLE",
            f"Worker {worker} belum mendukung kontrak fitur yang dibutuhkan: "
            f"{', '.join(missing)}. Deploy worker dengan release yang kompatibel.",
            status_code=409,
            details={"worker": worker, "missing_capabilities": missing},
        )
    return response
