from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_EXPORT_RUNTIME = "export"
_QUICK_MODE_RUNTIME = "quick_mode"
_RESOLVER_RUNTIME = "resolver"
_RCLONE_STORAGE_RUNTIME = "rclone_storage"
_RCLONE_STORAGE_FAILURES = frozenset({"RCLONE_ACCESS_FAILED", "RCLONE_RUNTIME_UNAVAILABLE"})
_EXPORT_RUNTIME_FAILURES = frozenset({
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
    "TDL_SESSION_UNAUTHORIZED",
    "CHAT_WRITE_FORBIDDEN",
    "CHAT_ADMIN_REQUIRED",
    "USER_BANNED_IN_CHANNEL",
    "CHANNEL_PRIVATE",
    "CHAT_RESTRICTED",
    "USER_RESTRICTED",
})
_DOWNLOAD_RUNTIME_FAILURES = frozenset({
    *_EXPORT_RUNTIME_FAILURES,
    "TDL_SESSION_UNAUTHORIZED",
    "CHAT_WRITE_FORBIDDEN",
    "CHAT_ADMIN_REQUIRED",
    "USER_BANNED_IN_CHANNEL",
    "CHANNEL_PRIVATE",
    "CHAT_RESTRICTED",
    "USER_RESTRICTED",
})
_UPLOAD_RUNTIME_FAILURES = frozenset({
    *_STORAGE_RUNTIME_FAILURES,
    "PROFILE_UPLOAD_PREPARATION_FAILED",
})
_TTS_RUNTIME_FAILURES = frozenset({
    "TTS_HELPER_UNAVAILABLE",
    "TTS_RUNTIME_UNAVAILABLE",
    "TDL_SESSION_UNAUTHORIZED",
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
_QUICK_MODE_WORKER_FAILURES = frozenset({
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
    """Expose persisted readiness and record command outcomes."""

    def __init__(self, store) -> None:
        self.store = store

    def require_export(self, profile: str, worker: str) -> dict[str, Any]:
        return self.require(runtime=_EXPORT_RUNTIME, profile=profile, worker=worker)

    def record_command_result(
        self,
        *,
        worker: str,
        profile: str | None,
        runtime: str,
        succeeded: bool,
        reason_code: str = "",
        checked_at: str | None = None,
    ) -> bool:
        recorder = getattr(self.store, "record_command_result", None)
        if not callable(recorder):
            return False
        return bool(recorder(
            worker=worker,
            profile=profile,
            runtime=runtime,
            succeeded=succeeded,
            reason_code=reason_code,
            checked_at=checked_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        ))

    def require_quick_mode(self, profile: str, worker: str) -> dict[str, Any]:
        """Return the saved Quick Mode status without using it as admission."""
        normalized_worker = str(worker or "").strip().lower()
        normalized_profile = str(profile or "").strip().lower()
        cell = self.store.cell(normalized_worker, normalized_profile, _QUICK_MODE_RUNTIME)
        if cell is not None:
            return cell
        return {
            "worker": normalized_worker,
            "profile": normalized_profile,
            "runtime": _QUICK_MODE_RUNTIME,
            "status": "not_ready",
            "reason_code": "RUNTIME_NOT_SCANNED",
        }

    def require_tts(self, profile: str, worker: str) -> dict[str, Any]:
        """Require worker helper and profile sender canary evidence."""
        self.require(runtime="tts_helper", profile=None, worker=worker)
        return self.require(runtime="tts", profile=profile, worker=worker)

    def require_storage(self, profile: str, worker: str) -> dict[str, Any]:
        return self.require(runtime="storage", profile=profile, worker=worker)

    def require_download(self, profile: str, worker: str) -> dict[str, Any]:
        return self.require(runtime="download", profile=profile, worker=worker)

    def require_upload(self, profile: str, worker: str) -> dict[str, Any]:
        return self.require(runtime="upload", profile=profile, worker=worker)

    def require_resolver(self, worker: str) -> dict[str, Any]:
        """Return the saved Resolver status without using it as admission."""
        return self.require(runtime=_RESOLVER_RUNTIME, profile=None, worker=worker)

    def require_rclone_storage(
        self, worker: str, destination: str
    ) -> dict[str, Any]:
        """Return the saved rclone status; command execution validates access."""
        del destination
        normalized_worker = str(worker or "").strip().lower()
        cell = self.store.cell(normalized_worker, None, _RCLONE_STORAGE_RUNTIME)
        if cell is not None:
            return cell
        return {
            "worker": normalized_worker,
            "profile": None,
            "runtime": _RCLONE_STORAGE_RUNTIME,
            "status": "not_ready",
            "reason_code": "RUNTIME_NOT_SCANNED",
        }

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

    def record_rclone_storage_failure(self, *, worker: str, error_code: str) -> bool:
        code = str(error_code or "").strip().upper()
        if code not in _RCLONE_STORAGE_FAILURES:
            return False
        return bool(self.store.invalidate(
            worker=worker, profile=None, runtime=_RCLONE_STORAGE_RUNTIME,
            reason_code=code,
            checked_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        ))

    def require(
        self, *, runtime: str, profile: str | None, worker: str
    ) -> dict[str, Any]:
        normalized_worker = str(worker or "").strip().lower()
        normalized_profile = str(profile or "").strip().lower()
        cell = self.store.cell(normalized_worker, normalized_profile, runtime)
        if cell is not None:
            return cell
        return {
            "worker": normalized_worker,
            "profile": normalized_profile or None,
            "runtime": str(runtime or "").strip().lower(),
            "status": "not_ready",
            "reason_code": "RUNTIME_NOT_SCANNED",
        }

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
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if code in {"TTS_HELPER_UNAVAILABLE", "TTS_RUNTIME_UNAVAILABLE"}:
            return bool(
                self.store.invalidate(
                    worker=worker,
                    profile=None,
                    runtime="tts_helper",
                    reason_code=code,
                    checked_at=checked_at,
                )
            )
        return bool(
            self.store.invalidate(
                worker=worker,
                profile=profile,
                runtime="tts",
                reason_code=code,
                checked_at=checked_at,
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
        storage = self.store.invalidate(
                worker=worker,
                profile=profile,
                runtime="storage",
                reason_code=code,
                checked_at=datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
            )
        upload = self.store.invalidate(
            worker=worker,
            profile=profile,
            runtime="upload",
            reason_code=code,
            checked_at=datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        )
        return bool(storage or upload)

    def record_download_failure(
        self, *, worker: str, profile: str, error_code: str
    ) -> bool:
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
        if code not in _DOWNLOAD_RUNTIME_FAILURES:
            return False
        return bool(
            self.store.invalidate(
                worker=worker,
                profile=profile,
                runtime="download",
                reason_code=code,
                checked_at=datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
            )
        )

    def record_upload_failure(
        self, *, worker: str, profile: str, error_code: str
    ) -> bool:
        code = str(error_code or "").strip().upper()
        if code not in _UPLOAD_RUNTIME_FAILURES:
            return False
        upload = self.store.invalidate(
            worker=worker,
            profile=profile,
            runtime="upload",
            reason_code=code,
            checked_at=datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        )
        storage = self.store.invalidate(
            worker=worker,
            profile=profile,
            runtime="storage",
            reason_code=code,
            checked_at=datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        )
        return bool(upload or storage)

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
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if code in _QUICK_MODE_WORKER_FAILURES:
            return bool(
                self.store.invalidate(
                    worker=worker,
                    profile=None,
                    runtime="quick_mode_runtime",
                    reason_code=code,
                    checked_at=checked_at,
                )
            )
        return bool(
            self.store.invalidate(
                worker=worker,
                profile=profile,
                runtime=_QUICK_MODE_RUNTIME,
                reason_code=code,
                checked_at=checked_at,
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
        """Forget observations after a profile mutation without reporting failure."""
        del reason_code
        forget = getattr(self.store, "forget_profile", None)
        return bool(forget(worker=worker, profile=profile)) if callable(forget) else False
