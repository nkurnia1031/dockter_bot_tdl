from __future__ import annotations

import copy
import re
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from tme3bot.chat_refs import normalize_tdl_chat_ref
from tme3bot.tdl import tdl_session_denial_code, tdl_write_denial_code
from tme3bot.tdl_output import parse_speed_bps


_PROFILE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
_FINGERPRINT_RE = re.compile(r"[a-f0-9]{64}\Z")
_RETAINED_CANARY_OPERATIONS = 128
_PROFILE_CHECKS = {"export", "download", "storage", "tts"}


def _failure_code(exc: BaseException, fallback: str) -> str:
    return (
        tdl_session_denial_code(exc)
        or tdl_write_denial_code(exc)
        or fallback
    )


def _contains_marker(value: Any, marker: str) -> bool:
    if isinstance(value, str):
        return marker in value
    if isinstance(value, dict):
        return any(_contains_marker(item, marker) for item in value.values())
    if isinstance(value, list):
        return any(_contains_marker(item, marker) for item in value)
    return False


class ProfileReadinessCanary:
    """Exercise one profile's Export, Download, and Upload Telegram lanes."""

    def __init__(
        self,
        profile_manager,
        diagnose_profile_tdl: Callable[[str], dict],
        temp_root: Path,
        upload_session_fingerprint: Callable[[str], str] | None = None,
    ):
        self.profile_manager = profile_manager
        self.diagnose_profile_tdl = diagnose_profile_tdl
        self.temp_root = Path(temp_root)
        self.upload_session_fingerprint = upload_session_fingerprint

    def run(
        self,
        profile: str,
        storage_target: str,
        tts_target: str,
        report: Callable[[str, dict[str, Any], list[dict[str, Any]]], None],
        checks: list[str] | None = None,
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
        locks = [runtime.export_operation_lock]
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

            diagnostic = self.diagnose_profile_tdl(profile)
            fingerprint = str(diagnostic.get("fingerprint") or "").strip().lower()
            if diagnostic.get("ready") is not True or not _FINGERPRINT_RE.fullmatch(fingerprint):
                reasons = diagnostic.get("reason_codes")
                reason = next((str(code) for code in reasons if isinstance(code, str)), "PROFILE_SESSION_UNAVAILABLE") if isinstance(reasons, list) else "PROFILE_SESSION_UNAVAILABLE"
                for check in checks.values():
                    check["reason_code"] = reason
                emit("complete")
                return {
                    "checks": checks,
                    "messages": messages,
                    "session_fingerprint": "",
                    "upload_session_fingerprint": "",
                }

            upload_fingerprint = ""
            if callable(self.upload_session_fingerprint):
                try:
                    upload_fingerprint = str(
                        self.upload_session_fingerprint(profile) or ""
                    ).strip().lower()
                except Exception:
                    upload_fingerprint = ""
            if not _FINGERPRINT_RE.fullmatch(upload_fingerprint):
                upload_fingerprint = ""

            if not storage_target:
                for key in selected_checks.intersection({"export", "download", "storage"}):
                    target_check = "upload" if key == "storage" else key
                    checks[target_check]["reason_code"] = "TDL_ACCESS_TARGET_UNAVAILABLE"
                if "storage" in selected_checks:
                    checks["storage"]["reason_code"] = "TDL_ACCESS_TARGET_UNAVAILABLE"
            if not tts_target and "tts" in selected_checks:
                checks["tts"]["reason_code"] = "TTS_CHAT_UNAVAILABLE"

            self.temp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="profile-readiness-", dir=self.temp_root) as raw_root:
                root = Path(raw_root)
                export_json = root / "canary.json"
                media_dir = root / "download"
                export_client = runtime.export_tdl_client
                needs_export = bool(selected_checks.intersection({"export", "download", "storage", "tts"}))
                export_ready = False

                if needs_export and storage_target:
                    emit("export_canary")
                    try:
                        exported = export_client.export_messages(
                            storage_target,
                            1,
                            export_json,
                            last_count=1,
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
                    export_reason = checks["export"]["reason_code"]
                    if export_reason == "PROFILE_CANARY_NOT_RUN":
                        export_reason = "TDL_ACCESS_TARGET_UNAVAILABLE"
                    for dependent in selected_checks.intersection({"download", "storage", "tts"}):
                        checks[dependent]["reason_code"] = export_reason or "PROFILE_CANARY_EXPORT_FAILED"
                    if "storage" in selected_checks:
                        checks["upload"]["reason_code"] = export_reason or "PROFILE_CANARY_EXPORT_FAILED"

                if "download" in selected_checks and export_ready and exported.has_media:
                    emit("download_canary")
                    download_client = runtime.download_tdl_client
                    previous_progress = getattr(download_client, "progress_callback", None)
                    speed_seen = threading.Event()
                    cancel_started = threading.Event()

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
                        if has_speed and not speed_seen.is_set():
                            speed_seen.set()
                            if cancel_started.is_set():
                                return
                            cancel_started.set()
                            threading.Thread(
                                target=download_client.interrupt_current,
                                name="profile-readiness-download-cancel",
                                daemon=True,
                            ).start()

                    try:
                        download_client.progress_callback = on_download_progress
                        try:
                            download_client.download(export_json, media_dir)
                        except Exception as exc:
                            if not speed_seen.is_set():
                                raise exc
                        if speed_seen.is_set():
                            checks["download"] = {"ready": True, "reason_code": ""}
                        else:
                            checks["download"]["reason_code"] = "PROFILE_CANARY_DOWNLOAD_SPEED_MISSING"
                    except Exception as exc:
                        checks["download"]["reason_code"] = _failure_code(
                            exc, "PROFILE_CANARY_DOWNLOAD_FAILED"
                        )
                    finally:
                        download_client.progress_callback = previous_progress
                elif "download" in selected_checks and export_ready:
                    checks["download"]["reason_code"] = "PROFILE_CANARY_MEDIA_UNAVAILABLE"

                if "storage" in selected_checks and export_ready:
                    marker = f"[TME3BOT PROFILE SCAN {uuid.uuid4()}]"
                    emit("upload_storage")
                    upload_client = runtime.upload_tdl_client
                    try:
                        uploaded = upload_client.upload(export_json, storage_target, marker)
                        storage_message_id = int(uploaded.message_id)
                        checks["upload"] = {"ready": True, "reason_code": ""}
                        messages.append({"target": "storage", "message_id": storage_message_id})
                        emit("verify_storage")
                    except Exception as exc:
                        checks["upload"]["reason_code"] = _failure_code(
                            exc, "PROFILE_CANARY_UPLOAD_FAILED"
                        )
                        checks["storage"]["reason_code"] = checks["upload"]["reason_code"]
                    else:
                        try:
                            verified = export_client.export_messages(
                                storage_target,
                                storage_message_id,
                                root / "verify-storage.json",
                                with_content=True,
                                end_id=storage_message_id,
                            )
                            found = any(
                                int(item.get("id") or 0) == storage_message_id
                                and _contains_marker(item, marker)
                                for item in verified.messages
                            )
                            if found:
                                checks["storage"] = {"ready": True, "reason_code": ""}
                            else:
                                checks["storage"]["reason_code"] = "PROFILE_CANARY_STORAGE_VERIFY_FAILED"
                        except Exception as exc:
                            checks["storage"]["reason_code"] = _failure_code(
                                exc, "PROFILE_CANARY_STORAGE_VERIFY_FAILED"
                            )

                if "tts" in selected_checks and export_ready and tts_target:
                    marker = f"[TME3BOT PROFILE SCAN {uuid.uuid4()}]"
                    emit("upload_tts")
                    try:
                        uploaded = export_client.upload(export_json, tts_target, marker)
                        tts_message_id = int(uploaded.message_id)
                        messages.append({"target": "tts", "message_id": tts_message_id})
                        emit("verify_tts")
                        verified = export_client.export_messages(
                            tts_target,
                            tts_message_id,
                            root / "verify-tts.json",
                            with_content=True,
                            end_id=tts_message_id,
                        )
                        found = any(
                            int(item.get("id") or 0) == tts_message_id
                            and _contains_marker(item, marker)
                            for item in verified.messages
                        )
                        checks["tts"] = (
                            {"ready": True, "reason_code": ""}
                            if found
                            else {"ready": False, "reason_code": "PROFILE_CANARY_TTS_VERIFY_FAILED"}
                        )
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
