"""Central cadence policy for gateway background services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class GatewayBackgroundSchedule:
    job_recovery_seconds: float
    queue_recovery_seconds: float
    queue_reconcile_seconds: float
    profile_distribution_seconds: float
    profile_provisioning_seconds: float
    storage_recovery_seconds: float
    storage_trash_seconds: float
    scheduled_backups_enabled: bool

    @classmethod
    def for_mode(
        cls,
        mode: str,
        *,
        recovery_seconds: float = 30,
        trash_seconds: float = 3600,
    ) -> "GatewayBackgroundSchedule":
        normalized = str(mode or "full").strip().lower()
        if normalized == "full":
            return cls(
                job_recovery_seconds=2,
                queue_recovery_seconds=2,
                queue_reconcile_seconds=20,
                profile_distribution_seconds=3,
                profile_provisioning_seconds=10,
                storage_recovery_seconds=60,
                storage_trash_seconds=60,
                scheduled_backups_enabled=True,
            )
        if normalized != "lite":
            raise ValueError("Gateway mode harus full atau lite.")
        recovery = max(10.0, float(recovery_seconds))
        trash = max(recovery, float(trash_seconds))
        return cls(
            job_recovery_seconds=recovery,
            queue_recovery_seconds=recovery,
            queue_reconcile_seconds=recovery,
            profile_distribution_seconds=recovery,
            profile_provisioning_seconds=recovery,
            storage_recovery_seconds=recovery,
            storage_trash_seconds=trash,
            scheduled_backups_enabled=False,
        )


def run_event_driven_loop(
    stop_event,
    wake_event,
    *,
    recovery_seconds: float,
    callback: Callable[[], None],
) -> None:
    """Run after a signal or recovery timeout until stop is requested."""
    timeout = max(0.1, float(recovery_seconds))
    while not stop_event.is_set():
        wake_event.wait(timeout)
        wake_event.clear()
        if stop_event.is_set():
            return
        callback()
