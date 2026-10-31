from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from tme3bot.domain.models import DomainError

LOGGER = logging.getLogger(__name__)


class ProfileScanOperations:
    """Run durable full or targeted profile scans and expose safe progress."""

    def __init__(
        self,
        store,
        scan: Callable[[str], None],
        scan_worker_runtime: Callable[[str, str], dict] | None = None,
        scan_profile_runtime: Callable[..., dict] | None = None,
    ) -> None:
        self.store = store
        self.scan = scan
        self.scan_worker_runtime = scan_worker_runtime
        self.scan_profile_runtime = scan_profile_runtime
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="profile-scan")

    def start(self, actor_user_id: int) -> dict:
        operation, created = self.store.create(actor_user_id)
        if not created and operation.get("target") is not None:
            raise DomainError(
                "PROFILE_SCAN_BUSY",
                "Scan terpilih sedang berjalan. Tunggu sampai operasi selesai.",
                status_code=409,
            )
        if created:
            self.executor.submit(self._run, operation["id"])
        return operation

    def start_worker_runtime(
        self, actor_user_id: int, worker: str, runtime: str
    ) -> dict:
        if self.scan_worker_runtime is None:
            raise DomainError(
                "PROFILE_SCAN_UNAVAILABLE",
                "Scan runtime worker belum tersedia.",
                status_code=503,
            )
        target = {"kind": "worker_runtime", "worker": worker, "runtime": runtime}
        operation, created = self.store.create(actor_user_id, target=target)
        if not created:
            if operation.get("target") == target:
                return operation
            raise DomainError(
                "PROFILE_SCAN_BUSY",
                "Scan Profil lain sedang berjalan. Tunggu sampai operasi selesai.",
                status_code=409,
            )
        self.executor.submit(self._run_worker_runtime, operation["id"], worker, runtime)
        return operation

    def start_profile_runtime(
        self,
        actor_user_id: int,
        worker: str,
        profile: str,
        runtime: str,
    ) -> dict:
        if self.scan_profile_runtime is None:
            raise DomainError(
                "PROFILE_SCAN_UNAVAILABLE",
                "Scan layanan profil belum tersedia.",
                status_code=503,
            )
        target = {
            "kind": "profile_runtime",
            "worker": worker,
            "profile": profile,
            "runtime": runtime,
        }
        operation, created = self.store.create(actor_user_id, target=target)
        if not created:
            if operation.get("target") == target:
                return operation
            raise DomainError(
                "PROFILE_SCAN_BUSY",
                "Scan Profil lain sedang berjalan. Tunggu sampai operasi selesai.",
                status_code=409,
            )
        self.executor.submit(
            self._run_profile_runtime,
            operation["id"],
            worker,
            profile,
            runtime,
        )
        return operation

    def _run(self, operation_id: str) -> None:
        self.store.set_status(operation_id, "running")
        try:
            self.scan(operation_id)
        except Exception as exc:
            LOGGER.warning("Profile scan failed (%s).", type(exc).__name__)
            self.store.set_status(
                operation_id, "failed", error_code="PROFILE_SCAN_FAILED"
            )
            return
        self.store.set_status(operation_id, "succeeded")

    def _run_worker_runtime(
        self, operation_id: str, worker: str, runtime: str
    ) -> None:
        self.store.set_status(operation_id, "running")
        self.store.report_worker(
            operation_id,
            worker,
            "running",
            phase="runtime_probe",
            runtime=runtime,
        )
        try:
            result = self.scan_worker_runtime(worker, runtime)
            ready = isinstance(result, dict) and result.get("ready") is True
            reason_code = str(result.get("reason_code") or "") if isinstance(result, dict) else ""
            checks = {runtime: {"ready": ready, "reason_code": reason_code}}
        except Exception as exc:
            LOGGER.warning("Worker runtime scan failed (%s).", type(exc).__name__)
            self.store.report_worker(
                operation_id,
                worker,
                "failed",
                phase="failed",
                error_code="PROFILE_SCAN_FAILED",
                runtime=runtime,
            )
            self.store.set_status(
                operation_id, "failed", error_code="PROFILE_SCAN_FAILED"
            )
            return
        self.store.report_worker(
            operation_id,
            worker,
            "succeeded",
            phase="complete",
            runtime=runtime,
            checks=checks,
        )
        self.store.set_status(operation_id, "succeeded")

    def _run_profile_runtime(
        self,
        operation_id: str,
        worker: str,
        profile: str,
        runtime: str,
    ) -> None:
        self.store.set_status(operation_id, "running")
        self.store.report_worker(
            operation_id,
            worker,
            "running",
            phase="profile_probe",
            profiles=[profile],
        )

        def report(phase: str, checks: dict, cleanup: dict | None = None, dependencies=None):
            self.store.report_profile(
                operation_id,
                worker,
                profile,
                "running",
                phase=phase,
                checks=checks,
                cleanup=cleanup,
                dependencies=dependencies,
            )

        report("queued", {})
        try:
            result = self.scan_profile_runtime(worker, profile, runtime, report)
            ready = isinstance(result, dict) and result.get("ready") is True
            reason_code = (
                str(result.get("reason_code") or "")
                if isinstance(result, dict)
                else "PROFILE_SCAN_FAILED"
            )
            checks = result.get("checks") if isinstance(result, dict) else {}
            checks = checks if isinstance(checks, dict) else {}
            cleanup = result.get("cleanup") if isinstance(result, dict) else None
            dependencies = result.get("dependencies") if isinstance(result, dict) else []
            self.store.report_profile(
                operation_id,
                worker,
                profile,
                "succeeded",
                phase="complete",
                error_code="" if ready else reason_code,
                checks=checks,
                cleanup=cleanup,
                dependencies=dependencies if isinstance(dependencies, list) else [],
            )
        except Exception as exc:
            LOGGER.warning("Profile target scan failed (%s).", type(exc).__name__)
            self.store.report_profile(
                operation_id,
                worker,
                profile,
                "failed",
                phase="failed",
                error_code="PROFILE_SCAN_FAILED",
            )
            self.store.set_status(
                operation_id, "failed", error_code="PROFILE_SCAN_FAILED"
            )
            self.store.report_worker(
                operation_id,
                worker,
                "failed",
                phase="failed",
                error_code="PROFILE_SCAN_FAILED",
            )
            return
        self.store.report_worker(
            operation_id,
            worker,
            "succeeded",
            phase="complete",
        )
        self.store.set_status(operation_id, "succeeded")

    def get(self, operation_id: str) -> dict | None:
        return self.store.get(operation_id)

    def latest(self) -> dict | None:
        return self.store.latest()

    def report_worker(self, operation_id: str, worker: str, status: str, **details) -> None:
        self.store.report_worker(operation_id, worker, status, **details)

    def report_profile(
        self, operation_id: str, worker: str, profile: str, status: str, **details
    ) -> None:
        self.store.report_profile(operation_id, worker, profile, status, **details)

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
