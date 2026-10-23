from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tme3bot.domain.models import DomainError

_EXPORT_RUNTIME = "export"
_QUICK_MODE_RUNTIME = "quick_mode"
_RESOLVER_RUNTIME = "resolver"
_EXPORT_RUNTIME_FAILURES = frozenset({
    "PROFILE_SESSION_BUSY",
    "PROFILE_SESSION_DATABASE_MISSING",
    "PROFILE_ROOT_SESSION_DATABASE_MISSING",
    "PROFILE_USER1_SESSION_DATABASE_MISSING",
    "PROFILE_ROOT_SESSION_MISSING",
    "PROFILE_USER1_SESSION_MISSING",
    "PROFILE_ROOT_SESSION_TDL_INVALID",
    "PROFILE_USER1_SESSION_TDL_INVALID",
    "PROFILE_SESSION_TDL_INVALID",
    "PROFILE_SESSION_UNAVAILABLE",
    "PROFILE_SESSION_INVALID",
    "PROFILE_SESSION_UNREADABLE",
    "PROFILE_SESSION_UNSAFE",
    "PROFILE_SESSION_PERMISSION_INVALID",
    "PROFILE_SESSION_STORAGE_NOT_ISOLATED",
    "PROFILE_SESSION_IDENTITY_MISMATCH",
    "PROFILE_SESSION_METADATA_MISMATCH",
})
_WORKER_FAILURES = frozenset({"WORKER_OFFLINE", "WORKER_UNAVAILABLE"})
_UTILITY_RUNTIME_FAILURES = frozenset({
    "UTILITY_RUNTIME_UNAVAILABLE",
    "UTILITY_PROCESS_STALLED",
})
_RESOLVER_RUNTIME_FAILURES = frozenset({
    "RESOLVER_RUNTIME_UNAVAILABLE",
})
_STORAGE_RUNTIME_FAILURES = frozenset({
    *_EXPORT_RUNTIME_FAILURES,
    "PROFILE_UPLOAD_LANE_UNSAFE",
    "PROFILE_UPLOAD_SESSION_INVALID",
    "PROFILE_UPLOAD_IDENTITY_MISMATCH",
    "PROFILE_UPLOAD_SESSION_CHANGED",
    "TDL_ACCESS_NOT_VERIFIED",
    "TDL_SESSION_UNAUTHORIZED",
    "CHAT_WRITE_FORBIDDEN",
    "CHAT_ADMIN_REQUIRED",
    "USER_BANNED_IN_CHANNEL",
    "CHANNEL_PRIVATE",
    "CHAT_RESTRICTED",
    "USER_RESTRICTED",
})
_TTS_RUNTIME_FAILURES = frozenset({
    "TTS_HELPER_UNAVAILABLE",
    "TTS_RUNTIME_UNAVAILABLE",
    "TDL_SESSION_UNAUTHORIZED",
    "PROFILE_SESSION_BUSY",
    "PROFILE_SESSION_TDL_INVALID",
    "PROFILE_SESSION_UNAVAILABLE",
    "CHAT_WRITE_FORBIDDEN",
    "CHAT_ADMIN_REQUIRED",
    "USER_BANNED_IN_CHANNEL",
    "CHANNEL_PRIVATE",
    "CHAT_RESTRICTED",
    "USER_RESTRICTED",
})
_QUICK_MODE_RUNTIME_FAILURES = frozenset({
    *_EXPORT_RUNTIME_FAILURES,
    *(_TTS_RUNTIME_FAILURES - {"TTS_HELPER_UNAVAILABLE", "TTS_RUNTIME_UNAVAILABLE"}),
    "PROFILE_UPLOAD_LANE_UNSAFE",
    "PROFILE_UPLOAD_SESSION_INVALID",
    "PROFILE_UPLOAD_IDENTITY_MISMATCH",
    "TDL_ACCESS_NOT_VERIFIED",
    "TDL_ACCESS_TARGET_UNAVAILABLE",
    "UTILITY_COMMAND_MISSING",
    "UTILITY_SCRIPT_MISSING",
    "UTILITY_SCRIPT_UNREADABLE",
    "UTILITY_WORKSPACE_UNAVAILABLE",
    "UTILITY_RUNTIME_UNAVAILABLE",
    "UTILITY_PROCESS_STALLED",
    "QUICK_MODE_RUNTIME_UNAVAILABLE",
    "QUICKMODE_RUNTIME_UNAVAILABLE",
    "RCLONE_RUNTIME_UNAVAILABLE",
    "RCLONE_ACCESS_FAILED",
})


class RuntimeReadinessGate:
    """Admit work from persisted readiness evidence without probing workers."""

    def __init__(self, store) -> None:
        self.store = store

    def require_export(self, profile: str, worker: str) -> dict[str, Any]:
        return self.require(runtime=_EXPORT_RUNTIME, profile=profile, worker=worker)

    def require_quick_mode(self, profile: str, worker: str) -> dict[str, Any]:
        cell = self.require(
            runtime=_QUICK_MODE_RUNTIME, profile=profile, worker=worker
        )
        if not (
            cell.get("session_fingerprint")
            and cell.get("destination_fingerprint")
            and cell.get("rclone_destination_fingerprint")
            and cell.get("sender_profiles")
            and cell.get("sender_session_fingerprints")
        ):
            raise DomainError(
                "RUNTIME_NOT_READY",
                f"Runtime Quick Mode profil {profile} pada worker {worker} belum memiliki snapshot lengkap. Jalankan Scan Profil.",
                status_code=409,
                details={
                    "worker": str(worker or "").strip().lower(),
                    "profile": str(profile or "").strip().lower(),
                    "runtime": _QUICK_MODE_RUNTIME,
                    "reason_code": "QUICK_MODE_EVIDENCE_INCOMPLETE",
                },
            )
        return cell

    def require_storage(self, profile: str, worker: str) -> dict[str, Any]:
        return self.require(runtime="storage", profile=profile, worker=worker)

    def require_resolver(self, worker: str) -> dict[str, Any]:
        """Require persisted worker-only Resolver evidence.

        Enabled state is checked by the caller against the live worker registry;
        a previous scan's disabled marker must not prevent a re-enabled worker
        from reusing its last successful Resolver snapshot.
        """
        normalized_worker = str(worker or "").strip().lower()
        worker_status = self.store.worker(normalized_worker)
        if worker_status is None:
            raise DomainError(
                "RUNTIME_NOT_READY",
                f"Runtime resolver pada worker {normalized_worker} belum dipindai. Jalankan Scan Profil.",
                status_code=409,
                details={
                    "worker": normalized_worker,
                    "profile": None,
                    "runtime": _RESOLVER_RUNTIME,
                    "reason_code": "WORKER_NOT_SCANNED",
                },
            )
        if worker_status is not None and worker_status["status"] == "failed":
            raise DomainError(
                "WORKER_OFFLINE",
                f"Worker {normalized_worker} gagal dipindai. Jalankan Scan Profil setelah worker tersedia.",
                status_code=503,
                details={"worker": normalized_worker, "reason_code": worker_status["reason_code"]},
            )
        cell = self.store.cell(normalized_worker, None, _RESOLVER_RUNTIME)
        if cell is None or cell["status"] != "ready" or not cell["fingerprint"]:
            reason = cell["reason_code"] if cell is not None else "RUNTIME_NOT_SCANNED"
            raise DomainError(
                "RUNTIME_NOT_READY",
                f"Runtime resolver pada worker {normalized_worker} belum siap. Jalankan Scan Profil.",
                status_code=409,
                details={
                    "worker": normalized_worker,
                    "profile": None,
                    "runtime": _RESOLVER_RUNTIME,
                    "reason_code": reason,
                },
            )
        return cell

    def record_resolver_failure(self, *, worker: str, error_code: str) -> bool:
        """Invalidate only a Resolver cell after a known addon runtime failure."""
        code = str(error_code or "").strip().upper()
        if code not in _RESOLVER_RUNTIME_FAILURES:
            return False
        return bool(
            self.store.invalidate(
                worker=worker,
                profile=None,
                runtime=_RESOLVER_RUNTIME,
                reason_code=code,
                checked_at=datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
            )
        )

    def require(
        self, *, runtime: str, profile: str | None, worker: str
    ) -> dict[str, Any]:
        normalized_worker = str(worker or "").strip().lower()
        normalized_profile = str(profile or "").strip().lower()
        target = f"profil {normalized_profile} " if normalized_profile else ""
        worker_status = self.store.worker(normalized_worker)
        if worker_status is not None and worker_status["status"] == "disabled":
            raise DomainError(
                "WORKER_DISABLED",
                f"Worker {normalized_worker} sedang dinonaktifkan dan tidak menerima job baru.",
                status_code=409,
                details={"worker": normalized_worker},
            )
        if worker_status is not None and worker_status["status"] == "failed":
            raise DomainError(
                "WORKER_OFFLINE",
                f"Worker {normalized_worker} gagal dipindai. Jalankan Scan Profil setelah worker tersedia.",
                status_code=503,
                details={"worker": normalized_worker, "reason_code": worker_status["reason_code"]},
            )
        if worker_status is None:
            raise DomainError(
                "RUNTIME_NOT_READY",
                f"Runtime {runtime} {target}pada worker {normalized_worker} belum dipindai. Jalankan Scan Profil.",
                status_code=409,
                details={
                    "worker": normalized_worker,
                    "profile": normalized_profile or None,
                    "runtime": runtime,
                    "reason_code": "WORKER_NOT_SCANNED",
                },
            )

        cell = self.store.cell(normalized_worker, normalized_profile, runtime)
        if cell is None or cell["status"] != "ready" or not cell["fingerprint"]:
            reason = cell["reason_code"] if cell is not None else "RUNTIME_NOT_SCANNED"
            raise DomainError(
                "RUNTIME_NOT_READY",
                f"Runtime {runtime} {target}pada worker {normalized_worker} belum siap. Jalankan Scan Profil.",
                status_code=409,
                details={
                    "worker": normalized_worker,
                    "profile": normalized_profile or None,
                    "runtime": runtime,
                    "reason_code": reason,
                },
            )
        return cell

    def invalidate_export_failure(
        self, *, worker: str, profile: str, error_code: str
    ) -> bool:
        """Invalidate only known Export access/session failures."""
        code = str(error_code or "").strip().upper()
        if code not in _EXPORT_RUNTIME_FAILURES:
            return False
        return bool(
            self.store.invalidate(
                worker=worker,
                profile=profile,
                runtime=_EXPORT_RUNTIME,
                reason_code=code,
                checked_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            )
        )

    def record_export_failure(
        self, *, worker: str, profile: str, error_code: str
    ) -> bool:
        """Update worker reachability or the affected Export cell after failure."""
        code = str(error_code or "").strip().upper()
        if code in _WORKER_FAILURES:
            return bool(
                self.store.mark_worker_failed(
                    worker=worker,
                    reason_code=code,
                    checked_at=datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                )
            )
        return self.invalidate_export_failure(
            worker=worker, profile=profile, error_code=code
        )

    def record_utility_failure(self, *, worker: str, error_code: str) -> bool:
        """Update worker reachability or invalidate its Utility runtime cell."""
        code = str(error_code or "").strip().upper()
        if code in _WORKER_FAILURES:
            return bool(
                self.store.mark_worker_failed(
                    worker=worker,
                    reason_code=code,
                    checked_at=datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                )
            )
        if code not in _UTILITY_RUNTIME_FAILURES:
            return False
        return bool(
            self.store.invalidate(
                worker=worker,
                profile=None,
                runtime="utility",
                reason_code=code,
                checked_at=datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
            )
        )

    def record_tts_failure(
        self, *, worker: str, profile: str, error_code: str
    ) -> bool:
        """Update worker reachability or invalidate one TTS sender cell."""
        code = str(error_code or "").strip().upper()
        if code in _WORKER_FAILURES:
            return bool(
                self.store.mark_worker_failed(
                    worker=worker,
                    reason_code=code,
                    checked_at=datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                )
            )
        if code not in _TTS_RUNTIME_FAILURES:
            return False
        return bool(
            self.store.invalidate(
                worker=worker,
                profile=profile,
                runtime="tts",
                reason_code=code,
                checked_at=datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
            )
        )

    def record_storage_failure(
        self, *, worker: str, profile: str, error_code: str
    ) -> bool:
        """Update worker reachability or invalidate one Storage sender cell."""
        code = str(error_code or "").strip().upper()
        if code in _WORKER_FAILURES:
            return bool(
                self.store.mark_worker_failed(
                    worker=worker,
                    reason_code=code,
                    checked_at=datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                )
            )
        if code not in _STORAGE_RUNTIME_FAILURES:
            return False
        return bool(
            self.store.invalidate(
                worker=worker,
                profile=profile,
                runtime="storage",
                reason_code=code,
                checked_at=datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
            )
        )

    def record_quick_mode_failure(
        self, *, worker: str, profile: str, error_code: str
    ) -> bool:
        """Update reachability or invalidate only this Quick Mode cell."""
        code = str(error_code or "").strip().upper()
        if code in _WORKER_FAILURES:
            return bool(
                self.store.mark_worker_failed(
                    worker=worker,
                    reason_code=code,
                    checked_at=datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                )
            )
        if code not in _QUICK_MODE_RUNTIME_FAILURES:
            return False
        return bool(
            self.store.invalidate(
                worker=worker,
                profile=profile,
                runtime=_QUICK_MODE_RUNTIME,
                reason_code=code,
                checked_at=datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
            )
        )

    def invalidate_quick_mode_sender(
        self, *, worker: str, sender_profile: str, reason_code: str
    ) -> bool:
        """Invalidate Quick Mode snapshots that depend on a failed sender proof."""
        invalidate_sender = getattr(self.store, "invalidate_quick_mode_sender", None)
        if not callable(invalidate_sender):
            return False
        return bool(
            invalidate_sender(
                worker=worker,
                sender_profile=sender_profile,
                reason_code=reason_code,
                checked_at=datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
            )
        )

    def invalidate_profile_mutation(
        self,
        *,
        worker: str,
        profile: str,
        reason_code: str = "PROFILE_SESSION_CHANGED",
    ) -> bool:
        """Invalidate runtime cells after a profile session mutation."""
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        export_invalidated = self.store.invalidate(
            worker=worker,
            profile=profile,
            runtime=_EXPORT_RUNTIME,
            reason_code=reason_code,
            checked_at=checked_at,
        )
        tts_invalidated = self.store.invalidate(
            worker=worker,
            profile=profile,
            runtime="tts",
            reason_code=reason_code,
            checked_at=checked_at,
        )
        storage_invalidated = self.store.invalidate(
            worker=worker,
            profile=profile,
            runtime="storage",
            reason_code=reason_code,
            checked_at=checked_at,
        )
        quick_target_invalidated = self.store.invalidate(
            worker=worker,
            profile=profile,
            runtime=_QUICK_MODE_RUNTIME,
            reason_code=reason_code,
            checked_at=checked_at,
        )
        invalidate_sender = getattr(self.store, "invalidate_quick_mode_sender", None)
        quick_sender_invalidated = (
            invalidate_sender(
                worker=worker,
                sender_profile=profile,
                reason_code=reason_code,
                checked_at=checked_at,
            )
            if callable(invalidate_sender)
            else False
        )
        return bool(
            export_invalidated
            or tts_invalidated
            or storage_invalidated
            or quick_target_invalidated
            or quick_sender_invalidated
        )
