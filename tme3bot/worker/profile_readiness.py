from __future__ import annotations

import copy
import re
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from tme3bot.chat_refs import normalize_tdl_chat_ref
from tme3bot.persistence import utc_now_iso
from tme3bot.tdl import tdl_session_denial_code, tdl_write_denial_code
from tme3bot.tdl_output import parse_speed_bps


_PROFILE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
_RETAINED_CANARY_OPERATIONS = 32
_PROFILE_CHECKS = {"export", "download", "storage", "tts"}
_LOG_SECRET_PATTERNS = (
    re.compile(r"\b\d{5,15}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(?:https?|socks5h?)://[^\s/@:]+:[^\s/@]+(?=@)"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)((?:cookie|set-cookie)\s*:\s*)[^\r\n]+"),
    re.compile(
        r'''(?i)(["'](?:token|access[_-]?token|refresh[_-]?token|bot[_-]?token|'''
        r'''api[_-]?key|client[_-]?secret|secret|password|passwd|passphrase|'''
        r'''session(?:[_ -]?(?:key|token|data|contents|string))?|auth[_ -]?key|'''
        r'''private[_-]?key|cookie|set-cookie)["']\s*:\s*)(?:"[^"]*"|'[^']*'|[^\s,;}\]]+)'''
    ),
    re.compile(
        r"(?i)(\b(?:token|access[_-]?token|refresh[_-]?token|bot[_-]?token|api[_-]?key|client[_-]?secret|secret|password|passwd|passphrase|session(?:[_ -]?(?:key|token|data|contents|string))|auth[_ -]?key|private[_ -]?key)\b\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    ),
    re.compile(
        r"(?i)(--(?:token|api-key|client-secret|secret|password|passwd|passphrase|session)\s+)(?:\"[^\"]*\"|'[^']*'|[^\s]+)"
    ),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    ),
)


def _failure_code(exc: BaseException, fallback: str) -> str:
    return (
        tdl_session_denial_code(exc)
        or tdl_write_denial_code(exc)
        or fallback
    )


def _redact_scan_log_text(value: Any) -> str:
    text = str(value or "")
    for pattern in _LOG_SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


class ProfileReadinessCanary:
    """Test profile lanes through bounded exports and download progress."""

    def __init__(
        self,
        profile_manager,
        diagnose_profile_tdl: Callable[[str], dict],
        temp_root: Path,
        upload_session_fingerprint: Callable[[str], str] | None = None,
        download_progress_timeout_seconds: float = 20.0,
    ):
        self.profile_manager = profile_manager
        self.diagnose_profile_tdl = diagnose_profile_tdl
        self.temp_root = Path(temp_root)
        self.upload_session_fingerprint = upload_session_fingerprint
        self.download_progress_timeout_seconds = max(
            0.0, float(download_progress_timeout_seconds)
        )

    def run(
        self,
        profile: str,
        storage_target: str,
        tts_target: str,
        report: Callable[[str, dict[str, Any], list[dict[str, Any]]], None],
        checks: list[str] | None = None,
        log_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        selected_checks = set(_PROFILE_CHECKS if checks is None else checks)
        if not selected_checks or not selected_checks.issubset(_PROFILE_CHECKS):
            raise ValueError("Cakupan canary profil tidak valid.")
        list_profiles = getattr(self.profile_manager, "list_profiles", None)
        if callable(list_profiles) and profile not in list_profiles():
            unavailable = {
                name: {"ready": False, "reason_code": "PROFILE_NOT_FOUND"}
                for name in ("export", "download", "upload", "storage", "tts")
            }
            report("complete", unavailable, [])
            return {
                "checks": unavailable,
                "messages": [],
                "session_fingerprint": "",
                "upload_session_fingerprint": "",
            }
        runtime = self.profile_manager.runtime(profile)
        locks = []
        if selected_checks.intersection({"export", "download", "tts"}):
            locks.append(runtime.export_operation_lock)
        if "download" in selected_checks:
            locks.append(runtime.download_operation_lock)
        if "storage" in selected_checks:
            locks.append(runtime.upload_operation_lock)
        held = []
        checks = {
            name: {"ready": False, "reason_code": "PROFILE_CANARY_NOT_RUN"}
            for name in ("export", "download", "upload", "storage", "tts")
        }
        messages: list[dict[str, Any]] = []

        def emit(phase: str) -> None:
            report(phase, copy.deepcopy(checks), copy.deepcopy(messages))

        def run_tdl(runtime_name: str, client: Any, action: Callable[[], Any]) -> Any:
            if not callable(log_callback):
                return action()
            had_callback = hasattr(client, "raw_output_callback")
            previous_callback = getattr(client, "raw_output_callback", None)

            def capture(event: dict[str, Any]) -> None:
                if not isinstance(event, dict):
                    return
                safe_event = {
                    "runtime": runtime_name,
                    "type": str(event.get("type") or "output"),
                    "stream": str(event.get("stream") or "system"),
                    "text": _redact_scan_log_text(event.get("text")),
                }
                code = event.get("exit_code")
                if isinstance(code, int) and not isinstance(code, bool):
                    safe_event["exit_code"] = code
                try:
                    log_callback(safe_event)
                except Exception:
                    LOGGER.warning("Profile scan raw-log reporter failed", exc_info=True)

            client.raw_output_callback = capture
            try:
                return action()
            finally:
                if had_callback:
                    client.raw_output_callback = previous_callback
                else:
                    try:
                        delattr(client, "raw_output_callback")
                    except AttributeError:
                        pass

        try:
            for lock in locks:
                if not lock.acquire(blocking=False):
                    for check in checks.values():
                        check["reason_code"] = "PROFILE_SESSION_BUSY"
                    emit("complete")
                    return {
                        "checks": checks,
                        "messages": messages,
                        "session_fingerprint": "",
                        "upload_session_fingerprint": "",
                    }
                held.append(lock)

            # A session diagnostic or generation fingerprint is not evidence
            # that the selected TDL operation can or cannot run. The actual
            # canary commands below are the authority for each lane.
            fingerprint = ""
            upload_fingerprint = ""

            if not storage_target:
                if "export" in selected_checks or "download" in selected_checks:
                    checks["export"]["reason_code"] = "TDL_ACCESS_TARGET_UNAVAILABLE"
                if "download" in selected_checks:
                    checks["download"]["reason_code"] = "TDL_ACCESS_TARGET_UNAVAILABLE"
                if "storage" in selected_checks:
                    checks["upload"]["reason_code"] = "TDL_ACCESS_TARGET_UNAVAILABLE"
                    checks["storage"]["reason_code"] = "TDL_ACCESS_TARGET_UNAVAILABLE"
            if not tts_target and "tts" in selected_checks:
                checks["tts"]["reason_code"] = "TTS_CHAT_UNAVAILABLE"

            self.temp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="profile-readiness-", dir=self.temp_root) as raw_root:
                root = Path(raw_root)
                export_json = root / "canary.json"
                media_dir = root / "download"
                export_client = runtime.export_tdl_client
                export_ready = False

                if selected_checks.intersection({"export", "download"}) and storage_target:
                    emit("export_canary")
                    try:
                        exported = run_tdl(
                            "export",
                            export_client,
                            lambda: export_client.export_messages(
                                storage_target,
                                1,
                                export_json,
                                last_count=1,
                            ),
                        )
                        if exported.exported_count < 1 or not export_json.is_file():
                            checks["export"]["reason_code"] = "PROFILE_CANARY_EXPORT_EMPTY"
                        else:
                            checks["export"] = {"ready": True, "reason_code": ""}
                            export_ready = True
                    except Exception as exc:
                        checks["export"]["reason_code"] = _failure_code(
                            exc, "PROFILE_CANARY_EXPORT_FAILED"
                        )
                if not export_ready:
                    if "download" in selected_checks:
                        export_reason = checks["export"]["reason_code"]
                        if export_reason == "PROFILE_CANARY_NOT_RUN":
                            export_reason = "TDL_ACCESS_TARGET_UNAVAILABLE"
                        checks["download"]["reason_code"] = (
                            export_reason or "PROFILE_CANARY_EXPORT_FAILED"
                        )

                if "download" in selected_checks and export_ready and exported.has_media:
                    emit("download_canary")
                    download_client = runtime.download_tdl_client
                    previous_progress = getattr(download_client, "progress_callback", None)
                    progress_seen = threading.Event()
                    timeout_elapsed = threading.Event()
                    command_finished = threading.Event()
                    cancel_started = threading.Event()
                    cancel_lock = threading.Lock()
                    progress_deadline: list[float | None] = [None]
                    timeout: threading.Timer | None = None

                    def cancel_download(reason: str) -> None:
                        with cancel_lock:
                            if command_finished.is_set() or cancel_started.is_set():
                                return
                            cancel_started.set()
                            if reason == "timeout":
                                timeout_elapsed.set()
                        threading.Thread(
                            target=download_client.interrupt_current,
                            name="profile-readiness-download-cancel",
                            daemon=True,
                        ).start()

                    def on_download_progress(progress) -> None:
                        if previous_progress is not None:
                            previous_progress(progress)
                        speed_bps = getattr(progress, "speed_bps", None)
                        if speed_bps is None:
                            speed_bps = parse_speed_bps(
                                str(getattr(progress, "speed", "") or "")
                            )
                        try:
                            has_speed = float(speed_bps) > 0
                        except (TypeError, ValueError):
                            has_speed = False
                        try:
                            has_bytes = float(
                                getattr(progress, "transferred_bytes", None) or 0
                            ) > 0
                            has_fraction = float(
                                getattr(progress, "fraction_current", None) or 0
                            ) > 0
                            has_percent = float(
                                getattr(progress, "percent", None) or 0
                            ) > 0
                        except (TypeError, ValueError):
                            has_bytes = has_fraction = has_percent = False
                        deadline = progress_deadline[0]
                        within_deadline = (
                            deadline is not None and time.monotonic() <= deadline
                        )
                        if (
                            (has_speed or has_bytes or has_fraction or has_percent)
                            and within_deadline
                            and not timeout_elapsed.is_set()
                        ):
                            progress_seen.set()
                            cancel_download("progress")

                    def on_download_command_started() -> None:
                        nonlocal timeout
                        progress_deadline[0] = (
                            time.monotonic() + self.download_progress_timeout_seconds
                        )
                        timeout = threading.Timer(
                            self.download_progress_timeout_seconds,
                            lambda: cancel_download("timeout"),
                        )
                        timeout.daemon = True
                        timeout.start()

                    try:
                        download_client.progress_callback = on_download_progress
                        try:
                            run_tdl(
                                "download",
                                download_client,
                                lambda: download_client.download(
                                    export_json,
                                    media_dir,
                                    process_started_callback=on_download_command_started,
                                ),
                            )
                        except Exception as exc:
                            if not progress_seen.is_set() and not timeout_elapsed.is_set():
                                raise exc
                        if progress_seen.is_set():
                            checks["download"] = {"ready": True, "reason_code": ""}
                        elif timeout_elapsed.is_set():
                            checks["download"]["reason_code"] = (
                                "PROFILE_CANARY_DOWNLOAD_PROGRESS_TIMEOUT"
                            )
                        else:
                            checks["download"]["reason_code"] = (
                                "PROFILE_CANARY_DOWNLOAD_PROGRESS_MISSING"
                            )
                    except Exception as exc:
                        checks["download"]["reason_code"] = _failure_code(
                            exc, "PROFILE_CANARY_DOWNLOAD_FAILED"
                        )
                    finally:
                        command_finished.set()
                        if timeout is not None:
                            timeout.cancel()
                        download_client.progress_callback = previous_progress
                elif "download" in selected_checks and export_ready:
                    checks["download"]["reason_code"] = "PROFILE_CANARY_MEDIA_UNAVAILABLE"

                if "storage" in selected_checks and storage_target:
                    emit("storage_access_canary")
                    upload_client = runtime.upload_tdl_client
                    try:
                        run_tdl(
                            "upload",
                            upload_client,
                            lambda: upload_client.export_messages(
                                storage_target,
                                1,
                                root / "verify-storage-access.json",
                                last_count=1,
                            ),
                        )
                        checks["upload"] = {"ready": True, "reason_code": ""}
                        checks["storage"] = {"ready": True, "reason_code": ""}
                    except Exception as exc:
                        checks["upload"]["reason_code"] = _failure_code(
                            exc, "PROFILE_CANARY_UPLOAD_FAILED"
                        )
                        checks["storage"]["reason_code"] = checks["upload"]["reason_code"]

                if "tts" in selected_checks and tts_target:
                    emit("tts_access_canary")
                    try:
                        run_tdl(
                            "tts",
                            export_client,
                            lambda: export_client.export_messages(
                                tts_target,
                                1,
                                root / "verify-tts-access.json",
                                last_count=1,
                            ),
                        )
                        checks["tts"] = {"ready": True, "reason_code": ""}
                    except Exception as exc:
                        checks["tts"]["reason_code"] = _failure_code(
                            exc, "PROFILE_CANARY_TTS_FAILED"
                        )

            emit("complete")
            return {
                "checks": checks,
                "messages": messages,
                "session_fingerprint": fingerprint,
                "upload_session_fingerprint": upload_fingerprint,
            }
        finally:
            for lock in reversed(held):
                lock.release()


class ProfileReadinessCanaryOperations:
    """Keep a worker canary operation pollable while TDL commands run."""

    def __init__(self, canary: ProfileReadinessCanary) -> None:
        self.canary = canary
        self._lock = threading.RLock()
        self._operations: dict[str, dict[str, Any]] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="profile-canary")

    def start(
        self,
        profile: str,
        storage_target: str,
        tts_target: str,
        checks: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_profile = str(profile or "").strip().lower()
        if not _PROFILE_RE.fullmatch(normalized_profile):
            raise ValueError("Nama profil canary tidak valid.")
        try:
            storage = normalize_tdl_chat_ref(storage_target) if storage_target else ""
            tts = normalize_tdl_chat_ref(tts_target) if tts_target else ""
        except ValueError:
            raise ValueError("Tujuan chat canary tidak valid.") from None
        selected_checks = sorted(set(_PROFILE_CHECKS if checks is None else checks))
        if not selected_checks or not set(selected_checks).issubset(_PROFILE_CHECKS):
            raise ValueError("Cakupan canary profil tidak valid.")
        operation_id = str(uuid.uuid4())
        operation = {
            "id": operation_id,
            "profile": normalized_profile,
            "status": "queued",
            "phase": "queued",
            "checks": {},
            "messages": [],
            "logs": [],
            "log_sequence": 0,
            "session_fingerprint": "",
            "upload_session_fingerprint": "",
            "error_code": "",
        }
        with self._lock:
            self._operations[operation_id] = operation
        self._executor.submit(
            self._run, operation_id, normalized_profile, storage, tts, selected_checks
        )
        return self.get(operation_id) or operation

    def _report(self, operation_id: str, phase: str, checks: dict, messages: list) -> None:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is not None:
                operation.update(
                    status="running",
                    phase=str(phase),
                    checks=copy.deepcopy(checks),
                    messages=copy.deepcopy(messages),
                )

    def _append_log(self, operation_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                return
            sequence = int(operation.get("log_sequence") or 0) + 1
            operation["log_sequence"] = sequence
            operation.setdefault("logs", []).append({
                "sequence": sequence,
                "worker": "",
                "profile": str(operation.get("profile") or ""),
                "runtime": str(event.get("runtime") or ""),
                "type": str(event.get("type") or "output"),
                "stream": str(event.get("stream") or "system"),
                "text": str(event.get("text") or ""),
                "exit_code": event.get("exit_code"),
            })
            operation["updated_at"] = utc_now_iso()

    def _run(
        self,
        operation_id: str,
        profile: str,
        storage: str,
        tts: str,
        checks: list[str],
    ) -> None:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                return
            operation.update(status="running", phase="session_probe")
        try:
            result = self.canary.run(
                profile,
                storage,
                tts,
                lambda phase, checks, messages: self._report(
                    operation_id, phase, checks, messages
                ),
                checks=checks,
                log_callback=lambda event: self._append_log(operation_id, event),
            )
        except Exception:
            result = {
                "checks": {},
                "messages": [],
                "session_fingerprint": "",
                "upload_session_fingerprint": "",
                "error_code": "PROFILE_CANARY_FAILED",
            }
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is not None:
                operation.update(
                    status="failed" if result.get("error_code") else "succeeded",
                    phase="complete",
                    checks=copy.deepcopy(result.get("checks") or {}),
                    messages=copy.deepcopy(result.get("messages") or []),
                    session_fingerprint=str(result.get("session_fingerprint") or ""),
                    upload_session_fingerprint=str(
                        result.get("upload_session_fingerprint") or ""
                    ),
                    error_code=str(result.get("error_code") or ""),
                )
                completed = [
                    key for key, value in self._operations.items()
                    if value.get("status") in {"succeeded", "failed"}
                ]
                for stale_id in completed[:-_RETAINED_CANARY_OPERATIONS]:
                    self._operations.pop(stale_id, None)

    def get(self, operation_id: str) -> dict[str, Any] | None:
        with self._lock:
            operation = self._operations.get(str(operation_id))
            return copy.deepcopy(operation) if operation is not None else None

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
