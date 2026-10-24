from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

LOGGER = logging.getLogger(__name__)


class ProfileScanOperations:
    """Run one durable cross-worker profile scan and expose safe progress."""

    def __init__(self, store, scan: Callable[[str], None]) -> None:
        self.store = store
        self.scan = scan
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="profile-scan")

    def start(self, actor_user_id: int) -> dict:
        operation, created = self.store.create(actor_user_id)
        if created:
            self.executor.submit(self._run, operation["id"])
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
