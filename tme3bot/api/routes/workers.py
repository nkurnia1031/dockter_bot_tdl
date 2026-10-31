from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from fastapi import Depends
from tme3bot.api.schemas import (
    ObjectResponse,
    WorkerEnabledRequest,
    WorkerListResponse,
    WorkerRequest,
    WorkerRouteRequest,
    WorkerRuntimeSettingsRequest,
    WorkerRuntimeScanRequest,
    WorkerTtsHealthResponse,
    WorkerTtsRecoveryResponse,
    WorkerUpdateRequest,
    ProfileRuntimeScanRequest,
)
from tme3bot.domain.models import DomainError
from tme3bot.application.profile_scan import ProfileScanOperations
from tme3bot.infrastructure.http_client import JsonHttpError
from tme3bot.names import normalize_profile_name
from tme3bot.profile_diagnostics import (
    PROFILE_LOCAL_DIAGNOSTIC_CHECKS,
    PROFILE_LOCAL_DIAGNOSTIC_CODES,
    PROFILE_UPLOAD_LANE_CODES,
    PROFILE_UPLOAD_LANE_PHASES,
    PROFILE_UPLOAD_LANE_STATUSES,
)
from tme3bot.worker_registry import WORKER_NAME_RE

_WORKER_RUNTIME_SCAN_TARGETS = {
    "resolver",
    "tts_helper",
    "quick_mode_runtime",
    "rclone_storage",
}
_PROFILE_RUNTIME_SCAN_TARGETS = {"export", "download", "storage", "tts", "quick_mode"}


def _safe_local_profile_inventory(payload, *, worker: str) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise DomainError(
            "PROFILE_INVENTORY_INVALID",
            "Worker mengembalikan inventaris profil yang tidak valid.",
            status_code=502,
        )

    safe_items = []
    seen: set[str] = set()
    for raw in payload["items"]:
        if not isinstance(raw, dict):
            raise DomainError(
                "PROFILE_INVENTORY_INVALID",
                "Worker mengembalikan inventaris profil yang tidak valid.",
                status_code=502,
            )
        name = normalize_profile_name(str(raw.get("name") or ""))
        if not name or name in seen or not isinstance(raw.get("checks"), list):
            raise DomainError(
                "PROFILE_INVENTORY_INVALID",
                "Worker mengembalikan inventaris profil yang tidak valid.",
                status_code=502,
            )
        seen.add(name)

        checks_by_name = {}
        for check in raw["checks"]:
            if not isinstance(check, dict):
                continue
            check_name = str(check.get("name") or "")
            if (
                check_name not in PROFILE_LOCAL_DIAGNOSTIC_CHECKS
                or check_name in checks_by_name
                or type(check.get("ready")) is not bool
            ):
                continue
            raw_code = str(check.get("code") or "PROFILE_SESSION_UNAVAILABLE")
            code = raw_code if raw_code in PROFILE_LOCAL_DIAGNOSTIC_CODES else "PROFILE_SESSION_UNAVAILABLE"
            checks_by_name[check_name] = {
                "name": check_name,
                "ready": check["ready"],
                "code": code,
            }
        if set(checks_by_name) != PROFILE_LOCAL_DIAGNOSTIC_CHECKS:
            raise DomainError(
                "PROFILE_INVENTORY_INVALID",
                "Worker tidak mengembalikan pemeriksaan lengkap untuk setiap profil.",
                status_code=502,
            )

        checks = [checks_by_name[name] for name in ("identity", "root_session", "user1_session")]
        reason_codes = list(dict.fromkeys(
            str(item["code"]) for item in checks if not item["ready"]
        ))
        ready = raw.get("ready") is True and not reason_codes
        if not ready and not reason_codes:
            reason_codes.append("PROFILE_SESSION_UNAVAILABLE")
        raw_upload = raw.get("upload_lane")
        if raw_upload is None:
            upload_lane = {
                "status": "pending",
                "phase": "not_started",
                "progress": 0,
                "code": "WORKER_UPDATE_REQUIRED",
                "updated_at": "",
            }
        elif not isinstance(raw_upload, dict):
            raise DomainError(
                "PROFILE_INVENTORY_INVALID",
                "Worker mengembalikan status lane Upload yang tidak valid.",
                status_code=502,
            )
        else:
            status = str(raw_upload.get("status") or "pending")
            phase = str(raw_upload.get("phase") or "not_started")
            code = str(raw_upload.get("code") or "PROFILE_UPLOAD_PREPARATION_FAILED")
            progress = raw_upload.get("progress", 0)
            if (
                status not in PROFILE_UPLOAD_LANE_STATUSES
                or phase not in PROFILE_UPLOAD_LANE_PHASES
                or code not in PROFILE_UPLOAD_LANE_CODES
                or type(progress) is not int
            ):
                raise DomainError(
                    "PROFILE_INVENTORY_INVALID",
                    "Worker mengembalikan status lane Upload yang tidak valid.",
                    status_code=502,
                )
            upload_lane = {
                "status": status,
                "phase": phase,
                "progress": max(0, min(100, progress)),
                "code": code,
                "updated_at": str(raw_upload.get("updated_at") or "")[:40],
            }
        safe_items.append({
            "name": name,
            "ready": ready,
            "reason_codes": reason_codes,
            "checks": checks,
            "upload_lane": upload_lane,
        })

    return {
        "worker": worker,
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "items": safe_items,
    }


def _runtime_readiness_snapshot(context) -> dict:
    store = getattr(context, "runtime_readiness_store", None)
    public_snapshot = getattr(store, "public_snapshot", None)
    if not callable(public_snapshot):
        return {"checked_at": "", "workers": [], "cells": []}
    snapshot = public_snapshot()
    return snapshot if isinstance(snapshot, dict) else {"checked_at": "", "workers": [], "cells": []}


def _tts_runtime_evidence(payload) -> tuple[bool, str, str]:
    if not isinstance(payload, dict):
        return False, "TTS_HELPER_UNAVAILABLE", ""
    helpers = payload.get("helpers")
    safe_helpers = []
    for item in helpers if isinstance(helpers, list) else []:
        if not isinstance(item, dict):
            continue
        slot = item.get("slot")
        status = str(item.get("status") or "")
        if (
            isinstance(slot, bool)
            or not isinstance(slot, int)
            or slot < 1
            or slot > 3
            or status not in {"ready", "bootstrapping", "tor_unreachable", "helper_unreachable"}
        ):
            continue
        safe_helpers.append({"slot": slot, "status": status})
    safe_helpers.sort(key=lambda item: item["slot"])
    ready = (
        payload.get("helpers_ready") is True
        and len(safe_helpers) == 3
        and [item["slot"] for item in safe_helpers] == [1, 2, 3]
        and all(item["status"] == "ready" for item in safe_helpers)
    )
    if not ready:
        return False, "TTS_HELPER_UNAVAILABLE", ""
    fingerprint = hashlib.sha256(
        json.dumps(
            {"runtime": "tts-v1", "helpers": safe_helpers},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return True, "", fingerprint


def _read_profile_inventory(context, worker: str, *, start_upload_prep: bool) -> dict:
    method_name = "scan_local_profiles" if start_upload_prep else "profile_local_inventory"
    scan = getattr(context.worker_dispatcher, method_name, None)
    if not callable(scan):
        raise DomainError(
            "WORKER_UPDATE_REQUIRED",
            "Backend belum mendukung scan profil lokal worker.",
            status_code=409,
        )
    try:
        result = scan(worker)
    except JsonHttpError as exc:
        if exc.status == 404:
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                f"Worker {worker} perlu diperbarui untuk scan profil lokal.",
                status_code=409,
            ) from exc
        if exc.kind == "timeout" or exc.status == 504:
            raise DomainError(
                "WORKER_TIMEOUT",
                f"Scan profil pada worker {worker} melewati batas waktu. Coba Scan lagi.",
                status_code=504,
            ) from exc
        if exc.kind == "network":
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Worker {worker} sedang offline atau tidak dapat dijangkau.",
                status_code=503,
            ) from exc
        raise DomainError(
            "WORKER_SCAN_FAILED",
            f"Worker {worker} gagal memproses scan profil lokal. Periksa versi worker dan coba lagi.",
            status_code=502,
        ) from exc
    except RuntimeError as exc:
        if "hanya diizinkan melalui HTTPS" in str(exc):
            raise DomainError(
                "WORKER_TRANSPORT_INSECURE",
                "Scan worker remote memerlukan koneksi HTTPS.",
                status_code=409,
            ) from exc
        raise DomainError(
            "WORKER_SCAN_FAILED",
            f"Worker {worker} gagal memproses scan profil lokal. Coba lagi atau periksa log worker.",
            status_code=502,
        ) from None
    except Exception:
        raise DomainError(
            "WORKER_UNAVAILABLE",
            f"Worker {worker} tidak dapat dihubungi untuk scan profil lokal.",
            status_code=503,
        ) from None
    return _safe_local_profile_inventory(result, worker=worker)


def _ensure_unique_worker_token(context, *, name: str, token: str) -> None:
    for registered_name, record in context.worker_registry.list().items():
        if registered_name != name and str(record.get("token") or "") == token:
            raise DomainError(
                "WORKER_TOKEN_DUPLICATE",
                "Token API worker harus unik untuk setiap worker.",
                status_code=409,
            )

def register_workers(app, context, *, current_actor):
    profile_scan_operations = None

    def _report_scan_worker(operation_id: str, worker: str, status: str, **details) -> None:
        if profile_scan_operations is not None:
            profile_scan_operations.report_worker(operation_id, worker, status, **details)

    def _report_scan_profile(
        operation_id: str, worker: str, profile: str, status: str, **details
    ) -> None:
        if profile_scan_operations is not None:
            profile_scan_operations.report_profile(
                operation_id, worker, profile, status, **details
            )

    def _profile_catalog_response(snapshot: dict) -> dict:
        raw_workers = snapshot.get("workers") if isinstance(snapshot, dict) else None
        raw_inventories = snapshot.get("inventories") if isinstance(snapshot, dict) else None
        if not isinstance(raw_workers, list) or not isinstance(raw_inventories, list):
            return {"checked_at": "", "workers": [], "inventories": []}
        workers = []
        successful: set[str] = set()
        for raw in raw_workers:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip().lower()
            status = str(raw.get("status") or "")
            if not WORKER_NAME_RE.fullmatch(name) or status not in {"success", "failed", "disabled"}:
                continue
            error_code = str(raw.get("error_code") or "")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", error_code):
                error_code = ""
            workers.append({
                "name": name,
                "status": status,
                "checked_at": str(raw.get("checked_at") or "")[:40],
                "error_code": error_code if status == "failed" else "",
            })
            if status == "success":
                successful.add(name)

        default_profile = str(
            getattr(context.profile_manager, "default_profile", "default") or "default"
        )
        inventories = []
        seen = set()
        profile_workers: dict[str, set[str]] = {}
        for raw in raw_inventories:
            if not isinstance(raw, dict):
                continue
            worker = str(raw.get("worker") or "").strip().lower()
            if worker not in successful or worker in seen:
                continue
            safe = _safe_local_profile_inventory({"items": raw.get("items")}, worker=worker)
            safe["checked_at"] = str(raw.get("checked_at") or "")[:40]
            for item in safe["items"]:
                item["deletable"] = item.get("name") != default_profile
                if item.get("ready") is True:
                    profile_workers.setdefault(item["name"], set()).add(worker)
            inventories.append(safe)
            seen.add(worker)
        profiles = [
            {
                "name": name,
                "workers": sorted(owners),
                "exclusive_worker": next(iter(owners)) if len(owners) == 1 else "",
            }
            for name, owners in sorted(profile_workers.items())
        ]
        return {
            "checked_at": str(snapshot.get("checked_at") or "")[:40],
            "workers": workers,
            "inventories": inventories,
            "profiles": profiles,
            "runtime_readiness": _runtime_readiness_snapshot(context),
        }

    def _scan_profile_worker(
        name: str,
        operation_id: str = "",
        *,
        storage_target_override: str | None = None,
        tts_target_override: str | None = None,
    ) -> tuple[str, dict | None, str, dict, dict, list[dict], list[dict], dict, dict, list[dict], list[dict]]:
        try:
            if operation_id:
                _report_scan_worker(
                    operation_id, name, "running", phase="inventory"
                )
            inventory = _read_profile_inventory(
                context, name, start_upload_prep=False
            )
            if operation_id:
                _report_scan_worker(
                    operation_id,
                    name,
                    "running",
                    phase="runtime_probe",
                    profiles=[
                        str(item.get("name") or "")
                        for item in inventory.get("items", [])
                        if isinstance(item, dict)
                    ],
                )
            resolver_readiness = {
                "ready": False,
                "reason_code": "WORKER_UPDATE_REQUIRED",
                "fingerprint": "",
            }
            resolver_probe = getattr(
                context.worker_dispatcher, "safelink_runtime_readiness", None
            )
            if callable(resolver_probe):
                try:
                    raw_resolver = resolver_probe(name)
                    if isinstance(raw_resolver, dict) and type(raw_resolver.get("ready")) is bool:
                        fingerprint = str(raw_resolver.get("fingerprint") or "").strip().lower()
                        has_fingerprint = bool(re.fullmatch(r"[a-f0-9]{64}", fingerprint))
                        reason_code = str(
                            raw_resolver.get("reason_code") or "RESOLVER_RUNTIME_UNAVAILABLE"
                        )
                        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", reason_code):
                            reason_code = "RESOLVER_RUNTIME_UNAVAILABLE"
                        ready = raw_resolver["ready"] is True and has_fingerprint
                        resolver_readiness = {
                            "ready": ready,
                            "reason_code": "" if ready else (
                                "RESOLVER_FINGERPRINT_MISSING"
                                if raw_resolver["ready"] is True and not has_fingerprint
                                else reason_code
                            ),
                            "fingerprint": fingerprint if ready else "",
                        }
                    else:
                        resolver_readiness["reason_code"] = "RESOLVER_RUNTIME_UNAVAILABLE"
                except JsonHttpError as exc:
                    resolver_readiness["reason_code"] = (
                        "WORKER_UPDATE_REQUIRED" if exc.status == 404
                        else "RESOLVER_RUNTIME_UNAVAILABLE"
                    )
                except Exception:
                    resolver_readiness["reason_code"] = "RESOLVER_RUNTIME_UNAVAILABLE"
            tts_readiness = {"ready": False, "reason_code": "WORKER_UPDATE_REQUIRED", "fingerprint": ""}
            tts_probe = getattr(context.worker_dispatcher, "tts_health", None)
            if callable(tts_probe):
                try:
                    raw_tts_health = tts_probe(name)
                    tts_ready, tts_reason, tts_fingerprint = _tts_runtime_evidence(raw_tts_health)
                    tts_readiness = {
                        "ready": tts_ready,
                        "reason_code": tts_reason,
                        "fingerprint": tts_fingerprint,
                    }
                except JsonHttpError as exc:
                    tts_readiness["reason_code"] = (
                        "WORKER_UPDATE_REQUIRED" if exc.status == 404
                        else "TTS_RUNTIME_UNAVAILABLE"
                    )
                except Exception:
                    tts_readiness["reason_code"] = "TTS_RUNTIME_UNAVAILABLE"
            control = getattr(context, "control_plane", None)
            target_resolver = getattr(control, "_tdl_access_target", None)
            if storage_target_override is not None:
                storage_target = storage_target_override
            else:
                storage_target = (
                    str(target_resolver("storage") or "").strip()
                    if callable(target_resolver)
                    else ""
                )
            if tts_target_override is not None:
                tts_target = tts_target_override
            else:
                tts_target = (
                    str(target_resolver("tts") or "").strip()
                    if callable(target_resolver)
                    else ""
                )
            access_store = getattr(control, "tdl_access_store", None)
            storage_destination_hash = (
                access_store.destination_fingerprint(storage_target)
                if storage_target and callable(getattr(access_store, "destination_fingerprint", None))
                else hashlib.sha256(storage_target.encode("utf-8")).hexdigest() if storage_target else ""
            )
            tts_destination_hash = (
                access_store.destination_fingerprint(tts_target)
                if tts_target and callable(getattr(access_store, "destination_fingerprint", None))
                else hashlib.sha256(tts_target.encode("utf-8")).hexdigest() if tts_target else ""
            )
            quick_runtime = {
                "ready": False,
                "reason_code": "WORKER_UPDATE_REQUIRED",
                "fingerprint": "",
            }
            quick_probe = getattr(context.worker_dispatcher, "quickmode_runtime_readiness", None)
            utility_settings = getattr(context, "utility_settings", None)
            settings_getter = getattr(utility_settings, "get", None)
            quick_settings = settings_getter() if callable(settings_getter) else {}
            quick_settings = quick_settings if isinstance(quick_settings, dict) else {}
            rclone_destination = str(quick_settings.get("rclone_destination") or "googledrive:backup").strip()
            rclone_destination_fingerprint = hashlib.sha256(rclone_destination.encode("utf-8")).hexdigest()
            if callable(quick_probe):
                try:
                    raw_quick = quick_probe(name, rclone_destination)
                    if isinstance(raw_quick, dict) and type(raw_quick.get("ready")) is bool:
                        raw_fingerprint = str(raw_quick.get("fingerprint") or "").strip().lower()
                        quick_reason = str(raw_quick.get("reason_code") or "QUICK_MODE_RUNTIME_UNAVAILABLE")
                        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", quick_reason):
                            quick_reason = "QUICK_MODE_RUNTIME_UNAVAILABLE"
                        has_fingerprint = bool(re.fullmatch(r"[a-f0-9]{64}", raw_fingerprint))
                        quick_runtime = {
                            "ready": raw_quick["ready"] is True and has_fingerprint,
                            "reason_code": "" if raw_quick["ready"] is True and has_fingerprint else (
                                "QUICK_MODE_FINGERPRINT_MISSING"
                                if raw_quick["ready"] is True and not has_fingerprint else quick_reason
                            ),
                            "fingerprint": raw_fingerprint if has_fingerprint else "",
                        }
                    else:
                        quick_runtime["reason_code"] = "QUICK_MODE_RUNTIME_UNAVAILABLE"
                except JsonHttpError as exc:
                    quick_runtime["reason_code"] = "WORKER_UPDATE_REQUIRED" if exc.status == 404 else "QUICK_MODE_RUNTIME_UNAVAILABLE"
                except Exception:
                    quick_runtime["reason_code"] = "QUICK_MODE_RUNTIME_UNAVAILABLE"

            rclone_storage_readiness = {
                "ready": False,
                "reason_code": "WORKER_UPDATE_REQUIRED",
                "fingerprint": "",
                "destination_fingerprint": "",
            }
            rclone_storage_probe = getattr(
                context.worker_dispatcher,
                "rclone_storage_runtime_readiness",
                None,
            )
            if callable(rclone_storage_probe):
                try:
                    raw_rclone_storage = rclone_storage_probe(name, rclone_destination)
                    if (
                        isinstance(raw_rclone_storage, dict)
                        and type(raw_rclone_storage.get("ready")) is bool
                    ):
                        raw_fingerprint = str(
                            raw_rclone_storage.get("fingerprint") or ""
                        ).strip().lower()
                        reason_code = str(
                            raw_rclone_storage.get("reason_code")
                            or "RCLONE_ACCESS_FAILED"
                        )
                        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", reason_code):
                            reason_code = "RCLONE_ACCESS_FAILED"
                        has_fingerprint = bool(
                            re.fullmatch(r"[a-f0-9]{64}", raw_fingerprint)
                        )
                        ready = raw_rclone_storage["ready"] is True and has_fingerprint
                        rclone_storage_readiness = {
                            "ready": ready,
                            "reason_code": "" if ready else (
                                "RCLONE_FINGERPRINT_MISSING"
                                if raw_rclone_storage["ready"] is True
                                and not has_fingerprint
                                else reason_code
                            ),
                            "fingerprint": raw_fingerprint if ready else "",
                            "destination_fingerprint": (
                                rclone_destination_fingerprint if ready else ""
                            ),
                        }
                    else:
                        rclone_storage_readiness["reason_code"] = (
                            "RCLONE_ACCESS_FAILED"
                        )
                except JsonHttpError as exc:
                    rclone_storage_readiness["reason_code"] = (
                        "WORKER_UPDATE_REQUIRED"
                        if exc.status == 404
                        else "RCLONE_ACCESS_FAILED"
                    )
                except Exception:
                    rclone_storage_readiness["reason_code"] = "RCLONE_ACCESS_FAILED"

            start_canary = getattr(context.worker_dispatcher, "start_profile_readiness_canary", None)
            poll_canary = getattr(context.worker_dispatcher, "profile_readiness_canary", None)
            export_cells: list[dict] = []
            download_cells: list[dict] = []
            upload_cells: list[dict] = []
            storage_cells: list[dict] = []
            tts_cells: list[dict] = []
            quickmode_cells: list[tuple[dict, dict]] = []

            def safe_checks(raw_checks: object) -> dict[str, dict]:
                result = {}
                for key in ("export", "download", "upload", "storage", "tts"):
                    raw = raw_checks.get(key) if isinstance(raw_checks, dict) else None
                    raw = raw if isinstance(raw, dict) else {}
                    code = str(raw.get("reason_code") or "PROFILE_CANARY_NOT_RUN")
                    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code):
                        code = "PROFILE_CANARY_FAILED"
                    result[key] = {"ready": raw.get("ready") is True, "reason_code": "" if raw.get("ready") is True else code}
                return result

            def cleanup_canary_messages(raw_messages: object) -> dict:
                messages = raw_messages if isinstance(raw_messages, list) else []
                items = []
                bot = getattr(context, "bot", None)
                targets = {"storage": storage_target, "tts": tts_target}
                for raw in messages[:8]:
                    if not isinstance(raw, dict):
                        continue
                    target_name = str(raw.get("target") or "")
                    message_id = raw.get("message_id")
                    target_chat = targets.get(target_name)
                    if target_chat is None or isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0:
                        continue
                    if bot is None:
                        items.append({"target": target_name, "message_id": message_id, "status": "failed", "error_code": "BOT_API_UNAVAILABLE"})
                        continue
                    try:
                        bot.delete_message(chat_id=target_chat, message_id=message_id)
                        items.append({"target": target_name, "message_id": message_id, "status": "succeeded", "error_code": ""})
                    except Exception:
                        items.append({"target": target_name, "message_id": message_id, "status": "failed", "error_code": "CANARY_CLEANUP_FAILED"})
                return {"status": "not_needed" if not items else "succeeded" if all(item["status"] == "succeeded" for item in items) else "failed", "items": items}

            for item in inventory.get("items", []):
                profile = str(item.get("name") or "")
                if operation_id:
                    _report_scan_profile(operation_id, name, profile, "running", phase="session_probe")
                inventory_ready = item.get("ready") is True
                raw_reasons = item.get("reason_codes")
                reason_code = (
                    next(
                        (
                            str(code)
                            for code in (raw_reasons if isinstance(raw_reasons, list) else [])
                            if isinstance(code, str)
                            and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code)
                        ),
                        "PROFILE_SESSION_UNAVAILABLE",
                    )
                    if not inventory_ready
                    else ""
                )
                ready = False
                fingerprint = ""
                checks = {
                    key: {"ready": False, "reason_code": reason_code or "PROFILE_CANARY_NOT_RUN"}
                    for key in ("export", "download", "upload", "storage", "tts")
                }
                canary_state = {}
                upload_fingerprint = ""
                if inventory_ready and storage_target and callable(start_canary) and callable(poll_canary):
                    try:
                        canary_state = start_canary(name, profile, storage_target, tts_target)
                        canary_id = str(canary_state.get("id") or "") if isinstance(canary_state, dict) else ""
                        if not re.fullmatch(r"[0-9a-f-]{36}", canary_id):
                            canary_state = {"status": "failed", "error_code": "PROFILE_CANARY_REQUEST_INVALID", "checks": {}, "messages": []}
                        else:
                            deadline = time.monotonic() + 900
                            while True:
                                phase = str(canary_state.get("phase") or "canary_running")
                                checks = safe_checks(canary_state.get("checks"))
                                if operation_id:
                                    _report_scan_profile(operation_id, name, profile, "running", phase=phase, checks=checks)
                                status = str(canary_state.get("status") or "")
                                if status in {"succeeded", "failed"}:
                                    break
                                if time.monotonic() >= deadline:
                                    canary_state = {**canary_state, "status": "failed", "error_code": "PROFILE_CANARY_TIMEOUT"}
                                    break
                                time.sleep(1)
                                canary_state = poll_canary(name, canary_id)
                                if not isinstance(canary_state, dict):
                                    canary_state = {"status": "failed", "error_code": "PROFILE_CANARY_FAILED", "checks": {}, "messages": []}
                    except JsonHttpError as exc:
                        code = "WORKER_UPDATE_REQUIRED" if exc.status == 404 else "PROFILE_CANARY_FAILED"
                        canary_state = {"status": "failed", "error_code": code, "checks": {}, "messages": []}
                    except Exception:
                        canary_state = {"status": "failed", "error_code": "PROFILE_CANARY_FAILED", "checks": {}, "messages": []}
                    checks = safe_checks(canary_state.get("checks"))
                    canary_error = str(canary_state.get("error_code") or "")
                    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", canary_error):
                        canary_error = "PROFILE_CANARY_FAILED"
                    for check in checks.values():
                        if not check["ready"] and check["reason_code"] == "PROFILE_CANARY_NOT_RUN":
                            check["reason_code"] = canary_error
                    fingerprint = str(canary_state.get("session_fingerprint") or "").strip().lower()
                    ready = bool(re.fullmatch(r"[a-f0-9]{64}", fingerprint))
                    if not ready:
                        canary_reason = next(
                            (
                                check["reason_code"]
                                for check in checks.values()
                                if check["reason_code"]
                                and check["reason_code"] != "PROFILE_CANARY_NOT_RUN"
                            ),
                            canary_error,
                        )
                        if any(check["ready"] for check in checks.values()):
                            reason_code = "PROFILE_FINGERPRINT_MISSING"
                            checks = {
                                key: {"ready": False, "reason_code": reason_code}
                                for key in checks
                            }
                        else:
                            reason_code = canary_reason or "PROFILE_SESSION_UNAVAILABLE"
                    upload_fingerprint = str(
                        canary_state.get("upload_session_fingerprint") or ""
                    ).strip().lower()
                    if not re.fullmatch(r"[a-f0-9]{64}", upload_fingerprint):
                        upload_fingerprint = ""
                        if checks["upload"]["ready"]:
                            checks["upload"] = {
                                "ready": False,
                                "reason_code": "PROFILE_UPLOAD_SESSION_INVALID",
                            }
                elif inventory_ready:
                    reason_code = (
                        "TDL_ACCESS_TARGET_UNAVAILABLE"
                        if not storage_target
                        else "WORKER_UPDATE_REQUIRED"
                    )
                    checks = {
                        key: {"ready": False, "reason_code": reason_code}
                        for key in checks
                    }

                if operation_id:
                    _report_scan_profile(
                        operation_id,
                        name,
                        profile,
                        "running",
                        phase="cleanup",
                        checks=checks,
                    )
                cleanup = cleanup_canary_messages(canary_state.get("messages"))
                item["_profile_scan_checks"] = checks
                item["_profile_scan_cleanup"] = cleanup
                export_ready = ready and checks["export"]["ready"]
                download_ready = ready and checks["download"]["ready"]
                upload_ready = ready and checks["upload"]["ready"] and bool(upload_fingerprint)
                storage_ready = ready and upload_ready and checks["storage"]["ready"] and bool(storage_destination_hash)
                tts_ready = ready and tts_readiness.get("ready") is True and checks["tts"]["ready"] and bool(tts_destination_hash)

                export_cells.append({"profile": profile, "ready": export_ready, "reason_code": "" if export_ready else (checks["export"]["reason_code"] or reason_code or "PROFILE_CANARY_EXPORT_FAILED"), "fingerprint": fingerprint if export_ready else ""})
                download_evidence = {"runtime": "download-canary-v1", "worker": name, "profile": profile, "session": fingerprint, "storage": storage_destination_hash}
                download_fingerprint = hashlib.sha256(json.dumps(download_evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                download_cells.append({"profile": profile, "ready": download_ready, "reason_code": "" if download_ready else (checks["download"]["reason_code"] or reason_code or "PROFILE_CANARY_DOWNLOAD_FAILED"), "fingerprint": download_fingerprint if download_ready else "", "session_fingerprint": fingerprint if download_ready else ""})
                upload_evidence = {"runtime": "upload-canary-v1", "worker": name, "profile": profile, "session": upload_fingerprint, "storage": storage_destination_hash}
                upload_fingerprint = hashlib.sha256(json.dumps(upload_evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                upload_session_fingerprint = str(canary_state.get("upload_session_fingerprint") or "").strip().lower()
                upload_cells.append({"profile": profile, "ready": upload_ready, "reason_code": "" if upload_ready else (checks["upload"]["reason_code"] or reason_code or "PROFILE_CANARY_UPLOAD_FAILED"), "fingerprint": upload_fingerprint if upload_ready else "", "session_fingerprint": upload_session_fingerprint if upload_ready else ""})

                storage_evidence = {"runtime": "storage-canary-v1", "worker": name, "profile": profile, "session": upload_session_fingerprint, "destination": storage_destination_hash, "upload_fingerprint": upload_fingerprint}
                storage_fingerprint = hashlib.sha256(json.dumps(storage_evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                storage_cell = {"profile": profile, "ready": storage_ready, "reason_code": "" if storage_ready else (checks["storage"]["reason_code"] or checks["upload"]["reason_code"] or reason_code or "PROFILE_CANARY_STORAGE_VERIFY_FAILED"), "fingerprint": storage_fingerprint if storage_ready else "", "session_fingerprint": upload_session_fingerprint if storage_ready else "", "destination_fingerprint": storage_destination_hash if storage_ready else ""}
                storage_cells.append(storage_cell)
                item["_storage_readiness"] = storage_cell

                tts_evidence = {"runtime": "tts-canary-v1", "worker": name, "profile": profile, "session": fingerprint, "destination": tts_destination_hash, "helpers": str(tts_readiness.get("fingerprint") or "")}
                tts_fingerprint = hashlib.sha256(json.dumps(tts_evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                tts_reason = "" if tts_ready else (checks["tts"]["reason_code"] or str(tts_readiness.get("reason_code") or "TTS_HELPER_UNAVAILABLE"))
                tts_cells.append({"profile": profile, "ready": tts_ready, "reason_code": tts_reason, "fingerprint": tts_fingerprint if tts_ready else "", "session_fingerprint": fingerprint if tts_ready else "", "destination_fingerprint": tts_destination_hash if tts_ready else ""})

                quick_reason = ""
                if not quick_runtime.get("ready"):
                    quick_reason = str(quick_runtime.get("reason_code") or "QUICK_MODE_RUNTIME_UNAVAILABLE")
                elif not export_ready:
                    quick_reason = checks["export"]["reason_code"] or "PROFILE_CANARY_EXPORT_FAILED"
                elif not download_ready:
                    quick_reason = checks["download"]["reason_code"] or "PROFILE_CANARY_DOWNLOAD_FAILED"
                elif not rclone_storage_readiness.get("ready"):
                    quick_reason = str(
                        rclone_storage_readiness.get("reason_code")
                        or "RCLONE_ACCESS_FAILED"
                    )
                elif not storage_ready:
                    quick_reason = checks["storage"]["reason_code"] or checks["upload"]["reason_code"] or "PROFILE_CANARY_STORAGE_VERIFY_FAILED"
                quickmode_cells.append((item, {"profile": profile, "ready": not quick_reason, "reason_code": quick_reason, "session_fingerprint": fingerprint, "destination_fingerprint": storage_destination_hash, "rclone_destination_fingerprint": rclone_destination_fingerprint}))
                item["_runtime_readiness"] = {"profile": profile, "ready": export_ready, "reason_code": "" if export_ready else export_cells[-1]["reason_code"], "fingerprint": fingerprint if export_ready else ""}
                item["_download_readiness"] = download_cells[-1]
                item["_upload_readiness"] = upload_cells[-1]
                if operation_id:
                    _report_scan_profile(operation_id, name, profile, "succeeded", phase="complete", checks=checks, cleanup=cleanup)

            storage_sender_fingerprints = {cell["profile"]: cell["session_fingerprint"] for cell in storage_cells if cell.get("ready") is True and cell.get("session_fingerprint")}
            storage_sender_profiles = sorted(storage_sender_fingerprints)
            for item, quickmode_cell in quickmode_cells:
                quickmode_cell["sender_profiles"] = storage_sender_profiles if quickmode_cell["ready"] else []
                quickmode_cell["sender_session_fingerprints"] = storage_sender_fingerprints if quickmode_cell["ready"] else {}
                if quickmode_cell["ready"] and not storage_sender_profiles:
                    quickmode_cell.update(ready=False, reason_code="TDL_ACCESS_NOT_VERIFIED")
                if quickmode_cell["ready"]:
                    quick_evidence = {"runtime": "quick-mode-readiness-v1", "worker": name, "profile": quickmode_cell["profile"], "export_session": quickmode_cell["session_fingerprint"], "quick_runtime": str(quick_runtime.get("fingerprint") or ""), "rclone_runtime": str(rclone_storage_readiness.get("fingerprint") or ""), "storage_destination": storage_destination_hash, "senders": storage_sender_fingerprints, "rclone_destination": rclone_destination_fingerprint}
                    quick_fingerprint = hashlib.sha256(json.dumps(quick_evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                    quickmode_cell["fingerprint"] = quick_fingerprint
                else:
                    quickmode_cell["fingerprint"] = ""
                item["_quickmode_readiness"] = quickmode_cell

            return (
                name, inventory, "", tts_readiness, quick_runtime, tts_cells,
                storage_cells, resolver_readiness, rclone_storage_readiness,
                download_cells, upload_cells,
            )
        except DomainError as exc:
            code = exc.code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", exc.code) else "WORKER_SCAN_FAILED"
            if operation_id:
                _report_scan_worker(
                    operation_id, name, "failed", phase="failed", error_code=code
                )
            return name, None, code, {}, {}, [], [], {}, {}, [], []
        except Exception:
            if operation_id:
                _report_scan_worker(
                    operation_id,
                    name,
                    "failed",
                    phase="failed",
                    error_code="WORKER_UNAVAILABLE",
                )
            return name, None, "WORKER_UNAVAILABLE", {}, {}, [], [], {}, {}, [], []

    def _perform_profile_catalog_scan(store, operation_id: str = "") -> dict:
        revision_getter = getattr(store, "revision", None)
        scan_revision = revision_getter() if callable(revision_getter) else None
        control = getattr(context, "control_plane", None)
        target_resolver = getattr(control, "_tdl_access_target", None)
        scan_storage_target = (
            str(target_resolver("storage") or "").strip()
            if callable(target_resolver)
            else ""
        )
        scan_tts_target = (
            str(target_resolver("tts") or "").strip()
            if callable(target_resolver)
            else ""
        )
        records = context.worker_registry.list()
        workers = []
        scan_names = []
        for raw_name, record in sorted(records.items()):
            name = str(raw_name or "").strip().lower()
            if not WORKER_NAME_RE.fullmatch(name):
                continue
            if not bool(record.get("enabled", True)):
                workers.append({
                    "name": name,
                    "status": "disabled",
                    "checked_at": "",
                    "error_code": "",
                })
            else:
                scan_names.append(name)

        if operation_id:
            for item in workers:
                _report_scan_worker(
                    operation_id,
                    item["name"],
                    "disabled",
                    phase="not_scanned",
                )
            for name in scan_names:
                _report_scan_worker(
                    operation_id, name, "queued", phase="queued"
                )

        results = {}
        if scan_names:
            with ThreadPoolExecutor(max_workers=min(8, len(scan_names))) as executor:
                futures = {
                    executor.submit(
                        _scan_profile_worker,
                        name,
                        operation_id,
                        storage_target_override=scan_storage_target,
                        tts_target_override=scan_tts_target,
                    ): name
                    for name in scan_names
                }
                for future in as_completed(futures):
                    (
                        name, inventory, error_code, tts_readiness, quick_runtime,
                        tts_cells, storage_cells, resolver_readiness,
                        rclone_storage_readiness, download_cells, upload_cells,
                    ) = future.result()
                    results[name] = (
                        inventory, error_code, tts_readiness, quick_runtime,
                        tts_cells, storage_cells, resolver_readiness,
                        rclone_storage_readiness,
                        download_cells, upload_cells,
                    )
                    if operation_id:
                        _report_scan_worker(
                            operation_id,
                            name,
                            "succeeded" if inventory is not None else "failed",
                            phase="complete" if inventory is not None else "failed",
                            error_code=error_code,
                        )

        inventories = []
        readiness_profiles: dict[str, list[dict]] = {}
        readiness_tts: dict[str, list[dict]] = {}
        readiness_tts_workers: dict[str, dict] = {}
        readiness_quickmode_workers: dict[str, dict] = {}
        readiness_quickmode: dict[str, list[dict]] = {}
        readiness_storage: dict[str, list[dict]] = {}
        readiness_resolver: dict[str, dict] = {}
        readiness_rclone_storage: dict[str, dict] = {}
        readiness_download: dict[str, list[dict]] = {}
        readiness_upload: dict[str, list[dict]] = {}
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        def profile_attempt(
            worker: str,
            profile: str,
            runtime: str,
            checks: dict,
            dependencies: list[str],
            cleanup: dict,
            *,
            phase: str = "complete",
            extra_checks: list[dict] | None = None,
        ) -> dict:
            return _profile_readiness_attempt(
                worker,
                profile,
                runtime,
                checked_at,
                phase,
                checks,
                dependencies,
                cleanup,
                extra_checks=extra_checks,
            )

        for name in scan_names:
            (
                inventory, error_code, tts_worker, quickmode_worker, tts_cells,
                storage_cells, resolver_readiness, rclone_storage_readiness,
                download_cells, upload_cells,
            ) = results[name]
            if inventory is None:
                workers.append({
                    "name": name,
                    "status": "failed",
                    "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "error_code": error_code or "WORKER_SCAN_FAILED",
                })
                continue
            workers.append({
                "name": name,
                "status": "success",
                "checked_at": inventory["checked_at"],
                "error_code": "",
            })
            readiness_tts[name] = tts_cells
            readiness_tts_workers[name] = tts_worker
            readiness_quickmode_workers[name] = quickmode_worker
            readiness_quickmode[name] = []
            readiness_storage[name] = storage_cells
            readiness_resolver[name] = resolver_readiness
            readiness_rclone_storage[name] = rclone_storage_readiness
            readiness_download[name] = download_cells
            readiness_upload[name] = upload_cells
            safe_items = []
            readiness_profiles[name] = []
            for item in inventory.get("items", []):
                profile = str(item.get("name") or "")
                checks = item.get("_profile_scan_checks")
                checks = checks if isinstance(checks, dict) else {}
                cleanup = item.get("_profile_scan_cleanup")
                cleanup = cleanup if isinstance(cleanup, dict) else {
                    "status": "not_needed", "items": []
                }

                def selected_checks(*names: str) -> dict:
                    return {
                        check_name: checks.get(
                            check_name,
                            {"ready": False, "reason_code": "PROFILE_CANARY_NOT_RUN"},
                        )
                        for check_name in names
                    }

                readiness = item.get("_runtime_readiness")
                if isinstance(readiness, dict):
                    readiness["last_attempt"] = profile_attempt(
                        name, profile, "export", selected_checks("export"), [], cleanup
                    )
                    readiness_profiles[name].append(readiness)
                download_readiness = item.get("_download_readiness")
                if isinstance(download_readiness, dict):
                    download_readiness["last_attempt"] = profile_attempt(
                        name,
                        profile,
                        "download",
                        selected_checks("export", "download"),
                        ["export"],
                        cleanup,
                    )
                upload_readiness = item.get("_upload_readiness")
                if isinstance(upload_readiness, dict):
                    upload_readiness["last_attempt"] = profile_attempt(
                        name,
                        profile,
                        "upload",
                        selected_checks("upload"),
                        ["export"],
                        cleanup,
                    )
                storage_readiness = item.get("_storage_readiness")
                if isinstance(storage_readiness, dict):
                    storage_readiness["last_attempt"] = profile_attempt(
                        name,
                        profile,
                        "storage",
                        selected_checks("export", "upload", "storage"),
                        ["export", "upload"],
                        cleanup,
                    )
                tts_readiness = next(
                    (
                        cell for cell in readiness_tts.get(name, [])
                        if cell.get("profile") == profile
                    ),
                    None,
                )
                if tts_readiness is not None:
                    tts_checks = selected_checks("export", "tts")
                    helper = readiness_tts_workers.get(name, {})
                    helper_ready = helper.get("ready") is True
                    tts_checks["tts_helper"] = {
                        "ready": helper_ready,
                        "reason_code": "" if helper_ready else str(
                            helper.get("reason_code") or "TTS_HELPER_UNAVAILABLE"
                        ),
                    }
                    tts_readiness["last_attempt"] = profile_attempt(
                        name,
                        profile,
                        "tts",
                        tts_checks,
                        ["export", "tts_helper"],
                        cleanup,
                    )
                quickmode_readiness = item.get("_quickmode_readiness")
                if isinstance(quickmode_readiness, dict):
                    quick_runtime_ready = quickmode_worker.get("ready") is True
                    rclone_ready = rclone_storage_readiness.get("ready") is True
                    quick_checks = [
                        {
                            "name": "quick_mode_runtime",
                            "status": "ready" if quick_runtime_ready else "not_ready",
                            "reason_code": "" if quick_runtime_ready else str(
                                quickmode_worker.get("reason_code")
                                or "QUICK_MODE_RUNTIME_UNAVAILABLE"
                            ),
                        },
                        {
                            "name": "rclone_storage",
                            "status": "ready" if rclone_ready else "not_ready",
                            "reason_code": "" if rclone_ready else str(
                                rclone_storage_readiness.get("reason_code")
                                or "RCLONE_ACCESS_FAILED"
                            ),
                        },
                    ]
                    for dependency_name in ("export", "download", "upload", "storage"):
                        dependency = checks.get(dependency_name, {})
                        quick_checks.append({
                            "name": dependency_name,
                            "status": "ready" if dependency.get("ready") is True else "not_ready",
                            "reason_code": str(
                                dependency.get("reason_code") or "PROFILE_CANARY_NOT_RUN"
                            ),
                        })
                    quick_ready = quickmode_readiness.get("ready") is True
                    quick_checks.append({
                        "name": "quick_mode",
                        "status": "ready" if quick_ready else "not_ready",
                        "reason_code": "" if quick_ready else str(
                            quickmode_readiness.get("reason_code")
                            or "QUICK_MODE_EVIDENCE_INCOMPLETE"
                        ),
                    })
                    quickmode_readiness["last_attempt"] = profile_attempt(
                        name,
                        profile,
                        "quick_mode",
                        {},
                        [
                            "quick_mode_runtime", "rclone_storage", "export",
                            "download", "upload", "storage",
                        ],
                        cleanup,
                        phase="derived_readiness",
                        extra_checks=quick_checks,
                    )
                    readiness_quickmode[name].append(quickmode_readiness)
                safe_items.append({
                    key: value for key, value in item.items()
                    if key not in {
                        "_runtime_readiness", "_quickmode_readiness", "_storage_readiness",
                        "_download_readiness", "_upload_readiness", "_profile_scan_checks",
                        "_profile_scan_cleanup",
                    }
                })
            inventories.append({
                "worker": name,
                "checked_at": inventory["checked_at"],
                "items": safe_items,
            })

        def runtime_attempt(worker: str, runtime: str, readiness: dict) -> dict:
            ready = readiness.get("ready") is True
            reason = str(readiness.get("reason_code") or "")
            return {
                "target": {"worker": worker, "profile": None, "runtime": runtime},
                "checked_at": checked_at,
                "phase": "runtime_probe",
                "checks": [{
                    "name": runtime,
                    "status": "ready" if ready else "not_ready",
                    "reason_code": "" if ready else reason,
                }],
                "reason_code": "" if ready else reason,
                "dependencies": [],
                "cleanup": {"status": "not_needed", "reason_code": ""},
            }

        def apply_committed_scan(_snapshot: dict) -> None:
            # Keep every persisted scan result behind the same revision check.
            # A confirmed delete cannot interleave and then be overwritten by
            # readiness or sender-proof data from an older inventory.
            storage_target = scan_storage_target
            access_store = getattr(control, "tdl_access_store", None)
            destination_fingerprint = getattr(
                access_store, "destination_fingerprint", None
            )
            replace_access = getattr(access_store, "replace_results", None)
            inventory_fingerprint = getattr(
                access_store, "inventory_fingerprint", None
            )
            if (
                storage_target
                and callable(destination_fingerprint)
                and callable(replace_access)
                and callable(inventory_fingerprint)
            ):
                storage_destination_hash = destination_fingerprint(storage_target)
                for name, cells in readiness_storage.items():
                    sender_fingerprints = {
                        cell["profile"]: cell["session_fingerprint"]
                        for cell in cells
                        if cell.get("ready") is True
                        and cell.get("session_fingerprint")
                    }
                    sender_profiles = sorted(sender_fingerprints)
                    inventory_hash = inventory_fingerprint(
                        sender_profiles, sender_fingerprints
                    )
                    try:
                        replace_access(
                            name,
                            "storage",
                            storage_destination_hash,
                            inventory_hash,
                            [
                                {
                                    "profile": cell["profile"],
                                    "ready": cell["ready"],
                                    "error_code": cell.get("reason_code"),
                                }
                                for cell in cells
                            ],
                            session_fingerprints=sender_fingerprints,
                        )
                    except Exception:
                        logging.getLogger(__name__).exception(
                            "Could not persist Storage scan proof for worker %s",
                            name,
                        )

            runtime_store = getattr(context, "runtime_readiness_store", None)
            apply_scan = getattr(runtime_store, "apply_export_scan", None)
            if not callable(apply_scan):
                return
            apply_scan(
                checked_at=checked_at,
                workers=[
                    {
                        "worker": item["name"],
                        "status": item["status"],
                        "error_code": item.get("error_code"),
                        "checked_at": item.get("checked_at"),
                    }
                    for item in workers
                ],
                profiles=readiness_profiles,
            )
            apply_lane_scan = getattr(runtime_store, "apply_profile_lane_scan", None)
            worker_states = [
                {
                    "worker": item["name"],
                    "status": item["status"],
                    "error_code": item.get("error_code"),
                    "checked_at": item.get("checked_at"),
                }
                for item in workers
            ]
            if callable(apply_lane_scan):
                apply_lane_scan(
                    runtime="download",
                    checked_at=checked_at,
                    workers=worker_states,
                    profiles=readiness_download,
                )
                apply_lane_scan(
                    runtime="upload",
                    checked_at=checked_at,
                    workers=worker_states,
                    profiles=readiness_upload,
                )
            for name, readiness in readiness_tts_workers.items():
                runtime_store.upsert_cell(
                    worker=name,
                    profile=None,
                    runtime="tts_helper",
                    ready=readiness.get("ready") is True,
                    fingerprint=str(readiness.get("fingerprint") or ""),
                    reason_code=str(readiness.get("reason_code") or "TTS_HELPER_UNAVAILABLE"),
                    checked_at=checked_at,
                    last_attempt=runtime_attempt(name, "tts_helper", readiness),
                )
            for name, readiness in readiness_quickmode_workers.items():
                runtime_store.upsert_cell(
                    worker=name,
                    profile=None,
                    runtime="quick_mode_runtime",
                    ready=readiness.get("ready") is True,
                    fingerprint=str(readiness.get("fingerprint") or ""),
                    reason_code=str(readiness.get("reason_code") or "QUICK_MODE_RUNTIME_UNAVAILABLE"),
                    checked_at=checked_at,
                    last_attempt=runtime_attempt(name, "quick_mode_runtime", readiness),
                )
            apply_tts_scan = getattr(runtime_store, "apply_tts_scan", None)
            if callable(apply_tts_scan):
                apply_tts_scan(checked_at=checked_at, profiles=readiness_tts)
            apply_quickmode_scan = getattr(runtime_store, "apply_quickmode_scan", None)
            if callable(apply_quickmode_scan):
                apply_quickmode_scan(
                    checked_at=checked_at,
                    workers=worker_states,
                    profiles=readiness_quickmode,
                )
            apply_storage_scan = getattr(runtime_store, "apply_storage_scan", None)
            if callable(apply_storage_scan):
                apply_storage_scan(
                    checked_at=checked_at,
                    profiles=readiness_storage,
                )
            apply_resolver_scan = getattr(runtime_store, "apply_resolver_scan", None)
            if callable(apply_resolver_scan):
                apply_resolver_scan(
                    checked_at=checked_at,
                    workers={
                        name: {
                            **readiness,
                            "last_attempt": runtime_attempt(name, "resolver", readiness),
                        }
                        for name, readiness in readiness_resolver.items()
                    },
                )
            for name, readiness in readiness_rclone_storage.items():
                runtime_store.upsert_cell(
                    worker=name,
                    profile=None,
                    runtime="rclone_storage",
                    ready=readiness.get("ready") is True,
                    fingerprint=str(readiness.get("fingerprint") or ""),
                    destination_fingerprint=str(
                        readiness.get("destination_fingerprint") or ""
                    ),
                    reason_code=str(
                        readiness.get("reason_code") or "RCLONE_ACCESS_FAILED"
                    ),
                    checked_at=checked_at,
                    last_attempt=runtime_attempt(name, "rclone_storage", readiness),
                )

        snapshot = store.replace_scan(
            checked_at=checked_at,
            workers=sorted(workers, key=lambda item: item["name"]),
            inventories=inventories,
            expected_revision=scan_revision,
            after_commit=apply_committed_scan,
        )
        if snapshot is None:
            raise RuntimeError("profile scan superseded by a profile mutation")
        return _profile_catalog_response(snapshot)

    def _scan_worker_runtime(worker: str, runtime: str) -> dict:
        defaults = {
            "resolver": "RESOLVER_RUNTIME_UNAVAILABLE",
            "tts_helper": "TTS_HELPER_UNAVAILABLE",
            "quick_mode_runtime": "QUICK_MODE_RUNTIME_UNAVAILABLE",
            "rclone_storage": "RCLONE_ACCESS_FAILED",
        }
        reason = defaults[runtime]
        ready = False
        fingerprint = ""
        destination_fingerprint = ""
        dispatcher = context.worker_dispatcher
        utility_settings = getattr(context, "utility_settings", None)
        settings_getter = getattr(utility_settings, "get", None)
        settings = settings_getter() if callable(settings_getter) else {}
        settings = settings if isinstance(settings, dict) else {}
        rclone_destination = str(
            settings.get("rclone_destination") or "googledrive:backup"
        ).strip()

        try:
            if runtime == "resolver":
                probe = getattr(dispatcher, "safelink_runtime_readiness", None)
                if not callable(probe):
                    reason = "WORKER_UPDATE_REQUIRED"
                else:
                    raw = probe(worker)
                    raw_fingerprint = str(raw.get("fingerprint") or "").strip().lower() if isinstance(raw, dict) else ""
                    raw_reason = str(raw.get("reason_code") or reason) if isinstance(raw, dict) else reason
                    if isinstance(raw, dict) and type(raw.get("ready")) is bool:
                        ready = raw["ready"] is True and bool(re.fullmatch(r"[a-f0-9]{64}", raw_fingerprint))
                        fingerprint = raw_fingerprint if ready else ""
                        reason = "" if ready else (
                            "RESOLVER_FINGERPRINT_MISSING"
                            if raw.get("ready") is True and not fingerprint
                            else raw_reason
                        )
            elif runtime == "tts_helper":
                probe = getattr(dispatcher, "tts_health", None)
                if not callable(probe):
                    reason = "WORKER_UPDATE_REQUIRED"
                else:
                    ready, reason, fingerprint = _tts_runtime_evidence(probe(worker))
            elif runtime == "quick_mode_runtime":
                probe = getattr(dispatcher, "quickmode_runtime_readiness", None)
                if not callable(probe):
                    reason = "WORKER_UPDATE_REQUIRED"
                else:
                    raw = probe(worker, rclone_destination)
                    raw_fingerprint = str(raw.get("fingerprint") or "").strip().lower() if isinstance(raw, dict) else ""
                    raw_reason = str(raw.get("reason_code") or reason) if isinstance(raw, dict) else reason
                    if isinstance(raw, dict) and type(raw.get("ready")) is bool:
                        has_fingerprint = bool(re.fullmatch(r"[a-f0-9]{64}", raw_fingerprint))
                        ready = raw["ready"] is True and has_fingerprint
                        fingerprint = raw_fingerprint if ready else ""
                        reason = "" if ready else (
                            "QUICK_MODE_FINGERPRINT_MISSING"
                            if raw.get("ready") is True and not has_fingerprint
                            else raw_reason
                        )
            elif runtime == "rclone_storage":
                probe = getattr(dispatcher, "rclone_storage_runtime_readiness", None)
                if not callable(probe):
                    reason = "WORKER_UPDATE_REQUIRED"
                else:
                    raw = probe(worker, rclone_destination)
                    raw_fingerprint = str(raw.get("fingerprint") or "").strip().lower() if isinstance(raw, dict) else ""
                    raw_reason = str(raw.get("reason_code") or reason) if isinstance(raw, dict) else reason
                    if isinstance(raw, dict) and type(raw.get("ready")) is bool:
                        has_fingerprint = bool(re.fullmatch(r"[a-f0-9]{64}", raw_fingerprint))
                        ready = raw["ready"] is True and has_fingerprint
                        fingerprint = raw_fingerprint if ready else ""
                        destination_fingerprint = (
                            hashlib.sha256(rclone_destination.encode("utf-8")).hexdigest()
                            if ready else ""
                        )
                        reason = "" if ready else (
                            "RCLONE_FINGERPRINT_MISSING"
                            if raw.get("ready") is True and not has_fingerprint
                            else raw_reason
                        )
        except JsonHttpError as exc:
            reason = "WORKER_UPDATE_REQUIRED" if exc.status == 404 else defaults[runtime]
        except Exception:
            reason = defaults[runtime]

        if reason and not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", reason):
            reason = defaults[runtime]
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        attempt = {
            "target": {"worker": worker, "profile": None, "runtime": runtime},
            "checked_at": checked_at,
            "phase": "runtime_probe",
            "checks": [{
                "name": runtime,
                "status": "ready" if ready else "not_ready",
                "reason_code": "" if ready else reason,
            }],
            "reason_code": "" if ready else reason,
            "dependencies": [],
            "cleanup": {"status": "not_needed", "reason_code": ""},
        }
        store = getattr(context, "runtime_readiness_store", None)
        upsert = getattr(store, "upsert_cell", None)
        if not callable(upsert):
            raise RuntimeError("Runtime readiness store tidak tersedia.")
        upsert(
            worker=worker,
            profile=None,
            runtime=runtime,
            ready=ready,
            fingerprint=fingerprint,
            destination_fingerprint=destination_fingerprint,
            reason_code=reason,
            checked_at=checked_at,
            last_attempt=attempt,
        )
        return {"ready": ready, "reason_code": "" if ready else reason}

    def _scan_profile_runtime(
        worker: str, profile: str, runtime: str, report
    ) -> dict:
        """Probe one profile service and persist only its result cells."""
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        readiness_store = getattr(context, "runtime_readiness_store", None)
        if not callable(getattr(readiness_store, "upsert_cell", None)):
            raise RuntimeError("Runtime readiness store tidak tersedia.")
        if runtime == "quick_mode":
            report(
                "derived_readiness",
                {},
                dependencies=[
                    "quick_mode_runtime", "rclone_storage", "export", "download",
                    "upload", "storage",
                ],
            )
            return _recalculate_quick_mode(worker, profile, checked_at)

        control = getattr(context, "control_plane", None)
        target_resolver = getattr(control, "_tdl_access_target", None)
        storage_target = (
            str(target_resolver("storage") or "").strip()
            if callable(target_resolver)
            else ""
        )
        tts_target = (
            str(target_resolver("tts") or "").strip()
            if callable(target_resolver)
            else ""
        )
        access_store = getattr(control, "tdl_access_store", None)

        def destination_fingerprint(target: str) -> str:
            if not target:
                return ""
            method = getattr(access_store, "destination_fingerprint", None)
            return (
                str(method(target) or "")
                if callable(method)
                else hashlib.sha256(target.encode("utf-8")).hexdigest()
            )

        dependencies = {
            "export": [],
            "download": ["export"],
            "storage": ["export", "upload"],
            "tts": ["export", "tts_helper"],
        }[runtime]
        relevant_check_names = {
            "export": ("export",),
            "download": ("export", "download"),
            "storage": ("export", "upload", "storage"),
            "tts": ("export", "tts"),
        }[runtime]
        report("session_probe", {}, dependencies=dependencies)
        checks: dict[str, dict] = {}
        cleanup = {"status": "not_needed", "items": []}
        canary_state: dict = {}
        helper_ready = True
        helper_reason = ""
        helper_fingerprint = ""
        dispatcher = context.worker_dispatcher

        if runtime == "tts":
            tts_probe = getattr(dispatcher, "tts_health", None)
            try:
                if not callable(tts_probe):
                    helper_ready, helper_reason = False, "WORKER_UPDATE_REQUIRED"
                else:
                    helper_ready, helper_reason, helper_fingerprint = _tts_runtime_evidence(
                        tts_probe(worker)
                    )
            except JsonHttpError as exc:
                helper_ready = False
                helper_reason = "WORKER_UPDATE_REQUIRED" if exc.status == 404 else "TTS_RUNTIME_UNAVAILABLE"
            except Exception:
                helper_ready, helper_reason = False, "TTS_RUNTIME_UNAVAILABLE"
            helper_attempt = {
                "target": {"worker": worker, "profile": None, "runtime": "tts_helper"},
                "checked_at": checked_at,
                "phase": "runtime_probe",
                "checks": [{
                    "name": "tts_helper",
                    "status": "ready" if helper_ready else "not_ready",
                    "reason_code": "" if helper_ready else (helper_reason or "TTS_HELPER_UNAVAILABLE"),
                }],
                "reason_code": "" if helper_ready else (helper_reason or "TTS_HELPER_UNAVAILABLE"),
                "dependencies": [],
                "cleanup": {"status": "not_needed", "reason_code": ""},
            }
            readiness_store.upsert_cell(
                worker=worker,
                profile=None,
                runtime="tts_helper",
                ready=helper_ready,
                fingerprint=helper_fingerprint,
                reason_code="" if helper_ready else (helper_reason or "TTS_HELPER_UNAVAILABLE"),
                checked_at=checked_at,
                last_attempt=helper_attempt,
            )
            report(
                "tts_helper_probe",
                {"tts": {"ready": helper_ready, "reason_code": helper_reason}},
                dependencies=dependencies,
            )

        canary_scope = {"export": "export", "download": "download", "storage": "storage", "tts": "tts"}[runtime]
        canary_target = tts_target if runtime == "tts" else storage_target
        if not canary_target:
            reason = "TTS_CHAT_UNAVAILABLE" if runtime == "tts" else "TDL_ACCESS_TARGET_UNAVAILABLE"
            checks = {runtime: {"ready": False, "reason_code": reason}}
            if runtime == "storage":
                checks["upload"] = {"ready": False, "reason_code": reason}
        else:
            start_canary = getattr(dispatcher, "start_profile_readiness_canary", None)
            poll_canary = getattr(dispatcher, "profile_readiness_canary", None)
            if not callable(start_canary) or not callable(poll_canary):
                checks = {runtime: {"ready": False, "reason_code": "WORKER_UPDATE_REQUIRED"}}
                if runtime == "storage":
                    checks["upload"] = {"ready": False, "reason_code": "WORKER_UPDATE_REQUIRED"}
            else:
                try:
                    canary_state = start_canary(
                        worker,
                        profile,
                        storage_target,
                        tts_target,
                        checks=[canary_scope],
                    )
                    canary_id = str(canary_state.get("id") or "") if isinstance(canary_state, dict) else ""
                    if not re.fullmatch(r"[0-9a-f-]{36}", canary_id):
                        canary_state = {"status": "failed", "error_code": "PROFILE_CANARY_REQUEST_INVALID", "checks": {}, "messages": []}
                    else:
                        deadline = time.monotonic() + 900
                        while True:
                            phase = str(canary_state.get("phase") or "canary_running")
                            raw_checks = _safe_profile_scan_checks(canary_state.get("checks"))
                            checks = {key: raw_checks[key] for key in relevant_check_names}
                            report(phase, checks, dependencies=dependencies)
                            if str(canary_state.get("status") or "") in {"succeeded", "failed"}:
                                break
                            if time.monotonic() >= deadline:
                                canary_state = {
                                    **canary_state,
                                    "status": "failed",
                                    "error_code": "PROFILE_CANARY_TIMEOUT",
                                }
                                break
                            time.sleep(1)
                            canary_state = poll_canary(worker, canary_id)
                            if not isinstance(canary_state, dict):
                                canary_state = {"status": "failed", "error_code": "PROFILE_CANARY_FAILED", "checks": {}, "messages": []}
                except JsonHttpError as exc:
                    error_code = "WORKER_UPDATE_REQUIRED" if exc.status == 404 else "PROFILE_CANARY_FAILED"
                    canary_state = {"status": "failed", "error_code": error_code, "checks": {}, "messages": []}
                except Exception:
                    canary_state = {"status": "failed", "error_code": "PROFILE_CANARY_FAILED", "checks": {}, "messages": []}
                raw_checks = _safe_profile_scan_checks(canary_state.get("checks"))
                checks = {key: raw_checks[key] for key in relevant_check_names}
                canary_error = str(canary_state.get("error_code") or "PROFILE_CANARY_FAILED")
                if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", canary_error):
                    canary_error = "PROFILE_CANARY_FAILED"
                for key, check in checks.items():
                    if not check["ready"] and check["reason_code"] == "PROFILE_CANARY_NOT_RUN":
                        check["reason_code"] = canary_error
                raw_messages = canary_state.get("messages")
                cleanup = _cleanup_profile_canary_messages(
                    context,
                    raw_messages,
                    {"storage": storage_target, "tts": tts_target},
                )

        raw_session = str(canary_state.get("session_fingerprint") or "").strip().lower()
        session_fingerprint = raw_session if re.fullmatch(r"[a-f0-9]{64}", raw_session) else ""
        if checks.get("export", {}).get("ready") and not session_fingerprint:
            checks["export"] = {"ready": False, "reason_code": "PROFILE_FINGERPRINT_MISSING"}
            if runtime in {"download", "storage", "tts"}:
                checks[runtime] = {"ready": False, "reason_code": "PROFILE_FINGERPRINT_MISSING"}
        raw_upload_session = str(canary_state.get("upload_session_fingerprint") or "").strip().lower()
        upload_session_fingerprint = raw_upload_session if re.fullmatch(r"[a-f0-9]{64}", raw_upload_session) else ""
        if checks.get("upload", {}).get("ready") and not upload_session_fingerprint:
            checks["upload"] = {"ready": False, "reason_code": "PROFILE_UPLOAD_SESSION_INVALID"}
            checks["storage"] = {"ready": False, "reason_code": "PROFILE_UPLOAD_SESSION_INVALID"}

        selected_check = "storage" if runtime == "storage" else runtime
        selected = checks.get(selected_check, {"ready": False, "reason_code": "PROFILE_CANARY_NOT_RUN"})
        ready = selected.get("ready") is True
        reason = str(selected.get("reason_code") or "")
        fingerprint = ""
        current_session = session_fingerprint
        destination_hash = destination_fingerprint(tts_target if runtime == "tts" else storage_target)
        if runtime == "export" and ready:
            fingerprint = session_fingerprint
        elif runtime == "download" and ready:
            fingerprint = _readiness_evidence_fingerprint(
                runtime, worker, profile, session_fingerprint, destination_hash
            )
        elif runtime == "storage":
            upload_check = checks.get("upload", {})
            upload_ready = upload_check.get("ready") is True and bool(upload_session_fingerprint)
            upload_reason = str(upload_check.get("reason_code") or "PROFILE_CANARY_UPLOAD_FAILED")
            upload_fingerprint = _readiness_evidence_fingerprint(
                "upload", worker, profile, upload_session_fingerprint, destination_fingerprint(storage_target)
            ) if upload_ready else ""
            storage_ready = ready and upload_ready and bool(destination_hash)
            if not upload_ready:
                reason = upload_reason
            elif ready and not destination_hash:
                storage_ready = False
                reason = "TDL_ACCESS_TARGET_UNAVAILABLE"
            checks["upload"] = {"ready": upload_ready, "reason_code": "" if upload_ready else upload_reason}
            checks["storage"] = {"ready": storage_ready, "reason_code": "" if storage_ready else (reason or "PROFILE_CANARY_STORAGE_VERIFY_FAILED")}
            upload_attempt = _profile_readiness_attempt(
                worker, profile, "upload", checked_at, "complete",
                {"upload": checks.get("upload", {"ready": False, "reason_code": upload_reason})},
                ["export"], cleanup,
            )
            readiness_store.upsert_cell(
                worker=worker,
                profile=profile,
                runtime="upload",
                ready=upload_ready,
                fingerprint=upload_fingerprint,
                session_fingerprint=upload_session_fingerprint,
                reason_code=upload_reason,
                checked_at=checked_at,
                last_attempt=upload_attempt,
            )
            ready = storage_ready
            reason = "" if storage_ready else checks["storage"]["reason_code"]
            fingerprint = _readiness_evidence_fingerprint(
                "storage", worker, profile, upload_session_fingerprint,
                destination_hash, upload_fingerprint,
            ) if storage_ready else ""
            current_session = upload_session_fingerprint
        elif runtime == "tts":
            ready = ready and helper_ready and bool(session_fingerprint) and bool(destination_hash)
            if not helper_ready:
                reason = helper_reason or "TTS_HELPER_UNAVAILABLE"
            elif selected.get("ready") is True and not session_fingerprint:
                reason = "PROFILE_FINGERPRINT_MISSING"
            elif selected.get("ready") is True and not destination_hash:
                reason = "TTS_CHAT_UNAVAILABLE"
            if ready:
                fingerprint = _readiness_evidence_fingerprint(
                    "tts", worker, profile, session_fingerprint,
                    destination_hash, helper_fingerprint,
                )
            checks["tts_helper"] = {
                "ready": helper_ready,
                "reason_code": "" if helper_ready else (helper_reason or "TTS_HELPER_UNAVAILABLE"),
            }
        readiness_store.upsert_cell(
            worker=worker,
            profile=profile,
            runtime=runtime,
            ready=ready,
            fingerprint=fingerprint,
            session_fingerprint=current_session if ready else "",
            destination_fingerprint=destination_hash if ready and runtime in {"storage", "tts"} else "",
            reason_code="" if ready else (reason or "PROFILE_CANARY_FAILED"),
            checked_at=checked_at,
            last_attempt=_profile_readiness_attempt(
                worker, profile, runtime, checked_at,
                "complete", checks, dependencies, cleanup,
            ),
        )
        report("complete", checks, cleanup, dependencies)
        return {
            "ready": ready,
            "reason_code": "" if ready else (reason or "PROFILE_CANARY_FAILED"),
            "checks": checks,
            "cleanup": cleanup,
            "dependencies": dependencies,
        }

    def _recalculate_quick_mode(worker: str, profile: str, checked_at: str) -> dict:
        store = getattr(context, "runtime_readiness_store", None)
        snapshot = store.snapshot() if callable(getattr(store, "snapshot", None)) else {"cells": []}
        cells = {
            (str(item.get("worker") or ""), item.get("profile"), str(item.get("runtime") or "")): item
            for item in snapshot.get("cells", []) if isinstance(item, dict)
        }
        worker_cells = {
            key[2]: cells.get((worker, None, key[2]))
            for key in ((worker, None, "quick_mode_runtime"), (worker, None, "rclone_storage"))
        }
        profile_cells = {
            runtime: cells.get((worker, profile, runtime))
            for runtime in ("export", "download", "upload", "storage")
        }
        utility_settings = getattr(context, "utility_settings", None)
        settings_getter = getattr(utility_settings, "get", None)
        settings = settings_getter() if callable(settings_getter) else {}
        settings = settings if isinstance(settings, dict) else {}
        rclone_destination = str(settings.get("rclone_destination") or "googledrive:backup").strip()
        rclone_hash = hashlib.sha256(rclone_destination.encode("utf-8")).hexdigest()
        control = getattr(context, "control_plane", None)
        target_resolver = getattr(control, "_tdl_access_target", None)
        storage_target = str(target_resolver("storage") or "").strip() if callable(target_resolver) else ""
        access_store = getattr(control, "tdl_access_store", None)
        storage_hash_fn = getattr(access_store, "destination_fingerprint", None)
        storage_hash = str(storage_hash_fn(storage_target) or "") if storage_target and callable(storage_hash_fn) else (hashlib.sha256(storage_target.encode("utf-8")).hexdigest() if storage_target else "")
        sender_fingerprints = {}
        for (cell_worker, cell_profile, cell_runtime), cell in cells.items():
            if cell_worker != worker or cell_runtime != "storage" or not cell_profile or cell.get("status") != "ready":
                continue
            upload_cell = cells.get((worker, cell_profile, "upload"))
            if not upload_cell or upload_cell.get("status") != "ready":
                continue
            session = str(cell.get("session_fingerprint") or "")
            if session and session == str(upload_cell.get("session_fingerprint") or "") and cell.get("destination_fingerprint") == storage_hash:
                sender_fingerprints[cell_profile] = session

        checks = []
        dependencies = ["quick_mode_runtime", "rclone_storage", "export", "download", "upload", "storage"]
        reason = ""
        quick_runtime = worker_cells.get("quick_mode_runtime")
        rclone = worker_cells.get("rclone_storage")
        export_cell = profile_cells.get("export")
        for name, cell in (("quick_mode_runtime", quick_runtime), ("rclone_storage", rclone), *profile_cells.items()):
            ready = bool(cell and cell.get("status") == "ready" and cell.get("fingerprint"))
            code = str(cell.get("reason_code") or "RUNTIME_NOT_SCANNED") if not ready else ""
            if name == "rclone_storage" and ready and rclone.get("destination_fingerprint") != rclone_hash:
                ready, code = False, "QUICK_MODE_SETTINGS_CHANGED"
            if name == "download" and ready:
                export_fingerprint = str(export_cell.get("fingerprint") or "") if export_cell else ""
                if not export_fingerprint or cell.get("session_fingerprint") != export_fingerprint:
                    ready, code = False, "PROFILE_SESSION_CHANGED"
            if name == "storage" and ready and cell.get("destination_fingerprint") != storage_hash:
                ready, code = False, "STORAGE_SETTINGS_CHANGED"
            if name == "storage" and ready:
                upload_cell = profile_cells.get("upload")
                if not upload_cell or cell.get("session_fingerprint") != upload_cell.get("session_fingerprint"):
                    ready, code = False, "PROFILE_UPLOAD_SESSION_CHANGED"
            checks.append({"name": name, "status": "ready" if ready else "not_ready", "reason_code": code})
            if not ready and not reason:
                reason = code or "QUICK_MODE_EVIDENCE_INCOMPLETE"

        ready_senders = sorted(sender_fingerprints)
        if not ready_senders and not reason:
            reason = "TDL_ACCESS_NOT_VERIFIED"
        if not storage_hash and not reason:
            reason = "TDL_ACCESS_TARGET_UNAVAILABLE"
        if not rclone_hash and not reason:
            reason = "RCLONE_ACCESS_FAILED"
        if export_cell is None or export_cell.get("status") != "ready":
            session_fingerprint = ""
        else:
            session_fingerprint = str(export_cell.get("fingerprint") or "")
        worker_state = next(
            (item for item in snapshot.get("workers", []) if item.get("name") == worker),
            None,
        )
        if worker_state and worker_state.get("status") == "failed" and not reason:
            reason = str(worker_state.get("reason_code") or "WORKER_UNAVAILABLE")
        is_ready = not reason and bool(session_fingerprint)
        if not session_fingerprint and not reason:
            reason = "PROFILE_FINGERPRINT_MISSING"
        evidence = {
            "worker": worker,
            "profile": profile,
            "runtime_fingerprints": [
                str(cell.get("fingerprint") or "")
                for cell in (quick_runtime, rclone, *profile_cells.values()) if cell
            ],
            "storage_destination": storage_hash,
            "rclone_destination": rclone_hash,
            "senders": sender_fingerprints,
        }
        fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest() if is_ready else ""
        attempt = _profile_readiness_attempt(
            worker, profile, "quick_mode", checked_at, "derived_readiness",
            {"quick_mode": {"ready": is_ready, "reason_code": "" if is_ready else reason}},
            dependencies, {"status": "not_needed", "items": []},
            extra_checks=checks,
        )
        store.upsert_quick_mode_cell(
            worker=worker,
            profile=profile,
            ready=is_ready,
            fingerprint=fingerprint,
            session_fingerprint=session_fingerprint,
            destination_fingerprint=storage_hash,
            rclone_destination_fingerprint=rclone_hash,
            sender_profiles=ready_senders,
            sender_session_fingerprints=sender_fingerprints,
            reason_code=reason or "QUICK_MODE_EVIDENCE_INCOMPLETE",
            checked_at=checked_at,
            last_attempt=attempt,
        )
        return {
            "ready": is_ready,
            "reason_code": "" if is_ready else reason,
            "checks": {"quick_mode": {"ready": is_ready, "reason_code": "" if is_ready else reason}},
            "dependencies": dependencies,
            "cleanup": {"status": "not_needed", "items": []},
        }

    def _store_profile_probe_failure(store, worker, profile, runtime, reason, checked_at):
        attempt = _profile_readiness_attempt(
            worker,
            profile,
            runtime,
            checked_at,
            "session_probe",
            {runtime: {"ready": False, "reason_code": reason}},
            [],
            {"status": "not_needed", "items": []},
        )
        store.upsert_cell(
            worker=worker,
            profile=profile,
            runtime=runtime,
            ready=False,
            reason_code=reason,
            checked_at=checked_at,
            last_attempt=attempt,
        )
        return {
            "ready": False,
            "reason_code": reason,
            "checks": {runtime: {"ready": False, "reason_code": reason}},
            "dependencies": [],
            "cleanup": {"status": "not_needed", "items": []},
        }

    def _safe_profile_scan_checks(raw_checks):
        result = {}
        for key in ("export", "download", "upload", "storage", "tts"):
            raw = raw_checks.get(key) if isinstance(raw_checks, dict) else None
            raw = raw if isinstance(raw, dict) else {}
            code = str(raw.get("reason_code") or "PROFILE_CANARY_NOT_RUN")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code):
                code = "PROFILE_CANARY_FAILED"
            result[key] = {"ready": raw.get("ready") is True, "reason_code": "" if raw.get("ready") is True else code}
        return result

    def _profile_readiness_attempt(
        worker, profile, runtime, checked_at, phase, checks, dependencies, cleanup,
        *, extra_checks=None,
    ):
        combined = dict(checks or {})
        if extra_checks:
            for item in extra_checks:
                if isinstance(item, dict):
                    combined[str(item.get("name") or "unknown")] = {
                        "ready": item.get("status") == "ready",
                        "reason_code": str(item.get("reason_code") or ""),
                    }
        safe_checks = []
        for name, raw in combined.items():
            if not isinstance(raw, dict):
                continue
            safe_checks.append({
                "name": name,
                "status": "ready" if raw.get("ready") is True else "not_ready",
                "reason_code": str(raw.get("reason_code") or ""),
            })
        ready = bool(safe_checks) and all(item["status"] == "ready" for item in safe_checks)
        cleanup_items = cleanup.get("items", []) if isinstance(cleanup, dict) else []
        cleanup_failed = any(
            isinstance(item, dict) and item.get("status") == "failed"
            for item in cleanup_items
        )
        return {
            "target": {"worker": worker, "profile": profile, "runtime": runtime},
            "checked_at": checked_at,
            "phase": phase,
            "checks": safe_checks,
            "reason_code": "" if ready else next((item["reason_code"] for item in safe_checks if item["reason_code"]), "RUNTIME_NOT_READY"),
            "dependencies": list(dependencies or []),
            "cleanup": {
                "status": "not_needed" if not cleanup_items else "failed" if cleanup_failed else "succeeded",
                "reason_code": "CANARY_CLEANUP_FAILED" if cleanup_failed else "",
            },
        }

    def _readiness_evidence_fingerprint(*parts) -> str:
        evidence = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(evidence.encode("utf-8")).hexdigest()

    def _cleanup_profile_canary_messages(context, raw_messages, targets):
        messages = raw_messages if isinstance(raw_messages, list) else []
        items = []
        bot = getattr(context, "bot", None)
        for raw in messages[:8]:
            if not isinstance(raw, dict):
                continue
            target = str(raw.get("target") or "")
            message_id = raw.get("message_id")
            chat = targets.get(target)
            if not chat or isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0:
                continue
            if bot is None:
                items.append({"target": target, "message_id": message_id, "status": "failed", "error_code": "BOT_API_UNAVAILABLE"})
                continue
            try:
                bot.delete_message(chat_id=chat, message_id=message_id)
                items.append({"target": target, "message_id": message_id, "status": "succeeded", "error_code": ""})
            except Exception:
                items.append({"target": target, "message_id": message_id, "status": "failed", "error_code": "CANARY_CLEANUP_FAILED"})
        status = "not_needed" if not items else "succeeded" if all(item["status"] == "succeeded" for item in items) else "failed"
        return {"status": status, "items": items}

    profile_scan_store = getattr(context, "profile_scan_store", None)
    if callable(getattr(profile_scan_store, "create", None)):
        profile_scan_operations = ProfileScanOperations(
            profile_scan_store,
            lambda operation_id: _perform_profile_catalog_scan(
                getattr(context, "local_profile_catalog", None), operation_id
            ),
            scan_worker_runtime=_scan_worker_runtime,
            scan_profile_runtime=_scan_profile_runtime,
        )
        app.add_event_handler("shutdown", profile_scan_operations.close)

    @app.get("/api/v1/workers", response_model=WorkerListResponse)
    def list_workers(actor=Depends(current_actor)):
        return {
            "items": [
                {
                    "name": name,
                    "url": value["url"],
                    "enabled": bool(value.get("enabled", True)),
                    "selected": name
                    == context.profile_manager.worker_route(actor.profile),
                }
                for name, value in context.worker_registry.list().items()
            ]
        }

    @app.get("/api/v1/profiles/local")
    def local_profile_catalog(actor=Depends(current_actor)):
        del actor
        store = getattr(context, "local_profile_catalog", None)
        if store is None or not callable(getattr(store, "snapshot", None)):
            raise DomainError(
                "PROFILE_CATALOG_UNAVAILABLE",
                "Katalog profil lokal belum tersedia.",
                status_code=503,
            )
        return _profile_catalog_response(store.snapshot())

    @app.get("/api/v1/profiles/local/scan")
    def latest_profile_scan(actor=Depends(current_actor)):
        del actor
        if profile_scan_operations is None:
            raise DomainError(
                "PROFILE_SCAN_UNAVAILABLE",
                "Operation Scan Profil belum tersedia.",
                status_code=503,
            )
        return {"operation": profile_scan_operations.latest()}

    @app.get("/api/v1/profiles/local/scan/{operation_id}")
    def get_profile_scan(operation_id: str, actor=Depends(current_actor)):
        del actor
        if profile_scan_operations is None:
            raise DomainError(
                "PROFILE_SCAN_UNAVAILABLE",
                "Operation Scan Profil belum tersedia.",
                status_code=503,
            )
        operation = profile_scan_operations.get(operation_id)
        if operation is None:
            raise DomainError(
                "PROFILE_SCAN_NOT_FOUND",
                "Operation Scan Profil tidak ditemukan.",
                status_code=404,
            )
        return operation

    @app.post("/api/v1/profiles/local/scan", status_code=202)
    def scan_all_local_profiles(actor=Depends(current_actor)):
        store = getattr(context, "local_profile_catalog", None)
        if (
            profile_scan_operations is None
            or not callable(getattr(store, "replace_scan", None))
        ):
            raise DomainError(
                "PROFILE_CATALOG_UNAVAILABLE",
                "Katalog atau operation Scan Profil belum tersedia.",
                status_code=503,
            )
        return profile_scan_operations.start(
            int(getattr(actor, "telegram_user_id", 0))
        )

    @app.post("/api/v1/profiles/local/scan/runtime", status_code=202)
    def scan_worker_runtime(
        body: WorkerRuntimeScanRequest, actor=Depends(current_actor)
    ):
        worker = str(body.worker or "").strip().lower()
        runtime = str(body.runtime or "").strip().lower()
        if not WORKER_NAME_RE.fullmatch(worker) or runtime not in _WORKER_RUNTIME_SCAN_TARGETS:
            raise DomainError(
                "PROFILE_SCAN_TARGET_INVALID",
                "Target scan runtime worker tidak valid.",
                status_code=422,
            )
        record = context.worker_registry.get(worker)
        if record is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        if not bool(record.get("enabled", True)):
            raise DomainError(
                "WORKER_DISABLED",
                "Worker nonaktif tidak dapat dipindai untuk job baru.",
                status_code=409,
            )
        runtime_store = getattr(context, "runtime_readiness_store", None)
        if not callable(getattr(runtime_store, "upsert_cell", None)):
            raise DomainError(
                "PROFILE_SCAN_UNAVAILABLE",
                "Penyimpanan readiness runtime belum tersedia.",
                status_code=503,
            )
        if profile_scan_operations is None:
            raise DomainError(
                "PROFILE_SCAN_UNAVAILABLE",
                "Operation Scan Profil belum tersedia.",
                status_code=503,
            )
        return profile_scan_operations.start_worker_runtime(
            int(getattr(actor, "telegram_user_id", 0)), worker, runtime
        )

    @app.post("/api/v1/profiles/local/scan/service", status_code=202)
    def scan_profile_runtime(
        body: ProfileRuntimeScanRequest, actor=Depends(current_actor)
    ):
        worker = str(body.worker or "").strip().lower()
        profile = normalize_profile_name(str(body.profile or ""))
        runtime = str(body.runtime or "").strip().lower()
        if (
            not WORKER_NAME_RE.fullmatch(worker)
            or not profile
            or runtime not in _PROFILE_RUNTIME_SCAN_TARGETS
        ):
            raise DomainError(
                "PROFILE_SCAN_TARGET_INVALID",
                "Target scan layanan profil tidak valid.",
                status_code=422,
            )
        record = context.worker_registry.get(worker)
        if record is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        if not bool(record.get("enabled", True)):
            raise DomainError(
                "WORKER_DISABLED",
                "Worker nonaktif tidak dapat dipindai untuk job baru.",
                status_code=409,
            )
        catalog = getattr(context, "local_profile_catalog", None)
        snapshot = catalog.snapshot() if callable(getattr(catalog, "snapshot", None)) else {}
        inventory = next(
            (
                item for item in snapshot.get("inventories", [])
                if isinstance(item, dict) and item.get("worker") == worker
            ),
            None,
        )
        if not inventory or not any(
            isinstance(item, dict)
            and str(item.get("name") or "").strip().lower() == profile
            for item in inventory.get("items", [])
        ):
            raise DomainError(
                "PROFILE_NOT_FOUND",
                "Profil belum tercatat pada hasil Scan Profil.",
                status_code=404,
            )
        if profile_scan_operations is None:
            raise DomainError(
                "PROFILE_SCAN_UNAVAILABLE",
                "Operation Scan Profil belum tersedia.",
                status_code=503,
            )
        return profile_scan_operations.start_profile_runtime(
            int(getattr(actor, "telegram_user_id", 0)),
            worker,
            profile,
            runtime,
        )

    def _local_profiles_for_worker(name: str, actor, *, start_upload_prep: bool):
        del actor
        worker = str(name or "").strip().lower()
        if not WORKER_NAME_RE.fullmatch(worker):
            raise DomainError("WORKER_NAME_INVALID", "Nama worker tidak valid.", status_code=422)
        if context.worker_registry.get(worker) is None:
            raise DomainError("WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404)
        inventory = _read_profile_inventory(
            context, worker, start_upload_prep=start_upload_prep
        )
        default_profile = str(
            getattr(context.profile_manager, "default_profile", "default") or "default"
        )
        for item in inventory.get("items", []):
            item["deletable"] = item.get("name") != default_profile
        if start_upload_prep:
            from tme3bot.api.routes.profile_local_delete import (
                reconcile_pending_identity_cleanups,
            )

            reconcile_pending_identity_cleanups(context)
        profile_registry = getattr(context.profile_manager, "profile_registry", None)
        pending = getattr(profile_registry, "pending_identity_cleanups", None)
        inventory["pending_identity_cleanup"] = pending() if callable(pending) else []
        return inventory

    @app.post("/api/v1/workers/{name}/profiles/scan")
    def scan_local_profiles(name: str, actor=Depends(current_actor)):
        return _local_profiles_for_worker(name, actor, start_upload_prep=True)

    @app.get("/api/v1/workers/{name}/profiles/local")
    def local_profiles_status(name: str, actor=Depends(current_actor)):
        return _local_profiles_for_worker(name, actor, start_upload_prep=False)

    @app.post("/api/v1/workers", response_model=ObjectResponse)
    def add_worker(body: WorkerRequest, actor=Depends(current_actor)):
        del actor
        _ensure_unique_worker_token(context, name=body.name.strip().lower(), token=body.token)
        name = context.worker_registry.upsert(
            body.name, body.url, body.token, enabled=body.enabled
        )
        return {"name": name}

    @app.put("/api/v1/workers/{name}", response_model=ObjectResponse)
    def update_worker(
        name: str, body: WorkerUpdateRequest, actor=Depends(current_actor)
    ):
        del actor
        current = context.worker_registry.get(name)
        if current is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        new_token = str(body.token or "").strip()
        if new_token:
            _ensure_unique_worker_token(context, name=str(name).strip().lower(), token=new_token)
        same_endpoint = body.url.rstrip("/") == str(current.get("url") or "").rstrip("/")
        rotated_token = bool(
            new_token and same_endpoint and new_token != str(current.get("token") or "")
        )
        if rotated_token:
            update_settings = getattr(context.worker_dispatcher, "update_worker_settings", None)
            if not callable(update_settings):
                raise DomainError(
                    "WORKER_TOKEN_ROTATION_UNAVAILABLE",
                    "Worker belum mendukung rotasi token langsung; perbarui worker terlebih dahulu.",
                    status_code=409,
                )
            try:
                update_settings(name, {"worker_api_token": new_token})
            except JsonHttpError as exc:
                if exc.status == 404:
                    raise DomainError(
                        "WORKER_UPDATE_REQUIRED",
                        "Perbarui aplikasi worker agar token dapat dirotasi dari Web.",
                        status_code=409,
                    ) from exc
                raise DomainError(
                    "WORKER_TOKEN_ROTATION_FAILED",
                    "Worker menolak rotasi token. Token gateway belum diubah.",
                    status_code=502,
                ) from exc
            except Exception as exc:
                raise DomainError(
                    "WORKER_UNAVAILABLE",
                    "Worker tidak dapat dihubungi; token gateway belum diubah.",
                    status_code=502,
                ) from exc
        token = new_token or str(current.get("token") or "")
        updated_name = context.worker_registry.upsert(
            name, body.url, token, enabled=body.enabled
        )
        if rotated_token:
            # The worker's vault client must recheck its manifest using the
            # newly rotated runtime token after the registry commit.
            request_profile_sync = getattr(context.worker_dispatcher, "request_profile_sync", None)
            if callable(request_profile_sync):
                try:
                    request_profile_sync(updated_name, mode="check")
                except Exception:
                    # Token rotation is already committed. The worker's own
                    # retry loop will refresh the vault status if this nudge fails.
                    pass
        return {"name": updated_name}

    @app.patch("/api/v1/workers/{name}", response_model=ObjectResponse)
    def set_worker_enabled(
        name: str, body: WorkerEnabledRequest, actor=Depends(current_actor)
    ):
        del actor
        if context.worker_registry.get(name) is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        context.worker_registry.set_enabled(name, body.enabled)
        return {"name": name, "enabled": bool(body.enabled)}

    @app.get("/api/v1/workers/{name}/profile-sync", response_model=ObjectResponse)
    def worker_profile_sync_status(name: str, actor=Depends(current_actor)):
        del actor
        if context.worker_registry.get(name) is None:
            raise DomainError("WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404)
        read_status = getattr(context.worker_dispatcher, "profile_sync_status", None)
        if not callable(read_status):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Backend belum dapat membaca diagnosis sinkronisasi profil worker.",
                status_code=409,
            )
        try:
            snapshot = read_status(name)
        except JsonHttpError as exc:
            if exc.status == 404:
                raise DomainError(
                    "WORKER_UPDATE_REQUIRED",
                    f"Worker {name} perlu diperbarui untuk menampilkan diagnosis sinkronisasi profil.",
                    status_code=409,
                ) from exc
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Worker {name} tidak dapat dihubungi untuk membaca status sinkronisasi profil.",
                status_code=503,
            ) from exc
        except Exception:
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Worker {name} tidak dapat dihubungi untuk membaca status sinkronisasi profil.",
                status_code=503,
            ) from None

        allowed_statuses = {"disabled", "ready", "sync_pending", "waiting_worker"}
        status = str(snapshot.get("status") or "waiting_worker")
        if status not in allowed_statuses:
            status = "waiting_worker"
        profiles = {}
        raw_profiles = snapshot.get("profiles")
        backend_error_code = str(snapshot.get("backend_error_code") or "")
        if not re.fullmatch(r"[A-Z0-9_-]{1,64}", backend_error_code):
            backend_error_code = ""
        for profile, raw in raw_profiles.items() if isinstance(raw_profiles, dict) else []:
            profile_name = str(profile).strip().lower()
            if not re.fullmatch(r"[a-z0-9_-]{1,48}", profile_name) or not isinstance(raw, dict):
                continue
            item_status = str(raw.get("status") or "sync_pending")
            if item_status not in {"ready", "sync_pending", "waiting_worker", "not_assigned"}:
                item_status = "sync_pending"
            error_code = str(raw.get("error_code") or "")
            profiles[profile_name] = {
                "status": item_status,
                "error_code": error_code if re.fullmatch(r"[A-Z0-9_-]{1,64}", error_code) else "",
                "desired_revision": raw.get("desired_revision") if type(raw.get("desired_revision")) is int else None,
                "installed_revision": raw.get("installed_revision") if type(raw.get("installed_revision")) is int else None,
                "updated_at": str(raw.get("updated_at") or "")[:64],
            }
        return {
            "worker": name,
            "status": status,
            "backend_available": snapshot.get("backend_available") if isinstance(snapshot.get("backend_available"), bool) else None,
            "backend_error_code": backend_error_code,
            "startup_checked": snapshot.get("startup_checked") if isinstance(snapshot.get("startup_checked"), bool) else None,
            "last_checked_at": str(snapshot.get("last_checked_at") or "")[:64],
            "profiles": profiles,
        }

    def tts_worker_error(name: str, exc: Exception) -> DomainError:
        if isinstance(exc, JsonHttpError):
            if exc.status == 404:
                return DomainError(
                    "WORKER_UPDATE_REQUIRED",
                    "Perbarui worker agar diagnosis dan pemulihan TTS tersedia.",
                    status_code=409,
                    details={"worker": name},
                )
            error_payload = exc.payload.get("error")
            error = error_payload if isinstance(error_payload, dict) else {}
            code = str(error.get("code") or "")
            safe_codes = {
                "TTS_HELPER_BUSY", "TTS_HELPER_ALREADY_READY", "TTS_RECOVERY_COOLDOWN",
                "TTS_HELPER_RECOVERING", "TTS_HELPER_UNAVAILABLE", "TTS_HELPER_SLOT_INVALID",
                "TTS_RECOVERY_REJECTED",
            }
            if code in safe_codes and 400 <= exc.status < 500:
                messages = {
                    "TTS_HELPER_BUSY": "Helper sedang memproses sintesis; coba lagi setelah selesai.",
                    "TTS_HELPER_ALREADY_READY": "Helper TTS sudah siap.",
                    "TTS_RECOVERY_COOLDOWN": "Tunggu sebentar sebelum meminta pemulihan lagi.",
                    "TTS_HELPER_RECOVERING": "Pemulihan helper TTS sedang berlangsung.",
                    "TTS_HELPER_UNAVAILABLE": "Helper TTS tidak dapat dihubungi.",
                    "TTS_HELPER_SLOT_INVALID": "Slot helper TTS tidak valid.",
                    "TTS_RECOVERY_REJECTED": "Helper TTS menolak permintaan pemulihan.",
                }
                return DomainError(
                    code,
                    messages.get(code, "Permintaan pemulihan TTS ditolak."),
                    status_code=exc.status,
                    details={
                        key: value for key, value in dict(error.get("details") or {}).items()
                        if key == "retry_after_seconds" and isinstance(value, int)
                    },
                )
            return DomainError(
                "WORKER_UNAVAILABLE",
                f"Worker {name} tidak dapat dihubungi untuk diagnosis TTS.",
                status_code=503 if exc.status >= 500 else 502,
                details={"worker": name},
            )
        return DomainError(
            "WORKER_UNAVAILABLE",
            f"Worker {name} tidak dapat dihubungi untuk diagnosis TTS.",
            status_code=503,
            details={"worker": name},
        )

    @app.get("/api/v1/workers/{name}/tts/health", response_model=WorkerTtsHealthResponse)
    def worker_tts_health(name: str, actor=Depends(current_actor)):
        if context.worker_registry.get(name) is None:
            raise DomainError("WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404)
        diagnostics = context.control_plane.tts_worker_diagnostics(profile=actor.profile, worker=name)
        item = diagnostics[0] if diagnostics else {}
        safe_helpers = item.get("helpers") if isinstance(item.get("helpers"), list) else []
        provisioner = context.profile_provisioner
        if provisioner is not None:
            provisioner.store.append_diagnostic_log(
                category="tts",
                actor_user_id=actor.telegram_user_id,
                profile=actor.profile,
                worker=name,
                event_type="worker_health_check",
                code=str(item.get("reason_code") or "worker_unavailable"),
                details=item,
            )
        return {
            "worker": name,
            "ready": bool(item.get("ready")),
            "helpers_ready": bool(item.get("helpers_ready")),
            "capability_ready": bool(item.get("capability_ready")),
            "profile_session_ready": bool(item.get("profile_session_ready")),
            "profile_sync_ready": bool(item.get("profile_sync_ready")),
            "reason_code": str(item.get("reason_code") or "worker_unavailable"),
            "helpers": safe_helpers,
        }

    @app.post(
        "/api/v1/workers/{name}/tts/helpers/{slot}/recover",
        response_model=WorkerTtsRecoveryResponse,
        status_code=202,
    )
    def recover_worker_tts_helper(name: str, slot: int, actor=Depends(current_actor)):
        del actor
        if slot < 1 or slot > 3:
            raise DomainError("TTS_HELPER_SLOT_INVALID", "Slot helper TTS harus 1, 2, atau 3.", status_code=422)
        if context.worker_registry.get(name) is None:
            raise DomainError("WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404)
        recover = getattr(context.worker_dispatcher, "recover_tts_helper", None)
        if not callable(recover):
            raise DomainError("WORKER_UPDATE_REQUIRED", "Backend belum mendukung pemulihan helper TTS.", status_code=409)
        try:
            result = recover(name, slot)
        except Exception as exc:
            raise tts_worker_error(name, exc) from None
        return {"worker": name, "slot": slot, "accepted": bool(result.get("accepted", True)), "status": str(result.get("status") or "restarting")}

    @app.get("/api/v1/workers/{name}/settings", response_model=ObjectResponse)
    def worker_settings(name: str, actor=Depends(current_actor)):
        del actor
        if context.worker_registry.get(name) is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        get_settings = getattr(context.worker_dispatcher, "worker_settings", None)
        if not callable(get_settings):
            raise DomainError(
                "WORKER_SETTINGS_UNAVAILABLE",
                "Backend belum mendukung pengaturan runtime worker.",
                status_code=503,
            )
        try:
            values = get_settings(name)
            settings_store = getattr(context, "runtime_settings_store", None)
            if settings_store is not None:
                try:
                    settings_store.seed_worker_once(
                        name, values, source="legacy-worker-settings"
                    )
                    snapshot = settings_store.snapshot("worker", worker=name)
                    return {
                        "worker": name,
                        **values,
                        "desired_version": snapshot["desired_version"],
                        "applied_version": snapshot["applied_version"],
                        "settings_status": snapshot["status"],
                    }
                except (TypeError, ValueError):
                    # Keep the old endpoint readable if a legacy worker reports
                    # a setting that no longer passes the current registry.
                    pass
            return {"worker": name, **values}
        except JsonHttpError as exc:
            if exc.status == 404:
                raise DomainError(
                    "WORKER_UPDATE_REQUIRED",
                    "Perbarui aplikasi worker agar pengaturan lewat Web tersedia.",
                    status_code=409,
                    details={"worker": name},
                ) from exc
            if 400 <= exc.status < 500:
                error_payload = exc.payload.get("error")
                error = error_payload if isinstance(error_payload, dict) else {}
                raise DomainError(
                    str(error.get("code") or "WORKER_SETTINGS_REJECTED"),
                    str(error.get("message") or "Worker menolak permintaan pengaturan."),
                    status_code=exc.status,
                    details={"worker": name},
                ) from exc
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Worker {name} tidak dapat dihubungi.",
                status_code=502,
                details={"worker": name},
            ) from exc
        except Exception as exc:
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Pengaturan worker {name} gagal dimuat.",
                status_code=502,
                details={"worker": name},
            ) from exc

    @app.put("/api/v1/workers/{name}/settings", response_model=ObjectResponse)
    def update_worker_settings(
        name: str, body: WorkerRuntimeSettingsRequest, actor=Depends(current_actor)
    ):
        if context.worker_registry.get(name) is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        update_settings = getattr(context.worker_dispatcher, "update_worker_settings", None)
        if not callable(update_settings):
            raise DomainError(
                "WORKER_SETTINGS_UNAVAILABLE",
                "Backend belum mendukung pengaturan runtime worker.",
                status_code=503,
            )
        try:
            payload = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
            applied = update_settings(name, payload)
            settings_store = getattr(context, "runtime_settings_store", None)
            if settings_store is not None:
                desired = {
                    key: value for key, value in payload.items()
                    if key in {
                        "job_stall_timeout_seconds", "tdl_export_stall_timeout_seconds",
                        "tdl_download_stall_timeout_seconds", "storage_profile", "tts_helper_urls",
                        "tts_tor_control_hosts", "tts_tor_control_ports", "tts_part_retries",
                        "tts_retry_base_seconds", "tts_newnym_after_retries",
                    }
                }
                if desired:
                    if "job_stall_timeout_seconds" in desired:
                        desired["worker_job_stall_timeout_seconds"] = desired.pop(
                            "job_stall_timeout_seconds"
                        )
                    snapshot = settings_store.snapshot("worker", worker=name)
                    saved = settings_store.update(
                        "worker", desired,
                        expected_version=int(snapshot["desired_version"]),
                        worker=name,
                        actor_user_id=int(actor.telegram_user_id),
                        source="legacy-worker-settings",
                    )
                    saved = settings_store.acknowledge(
                        "worker", name, int(saved["desired_version"])
                    )
                    applied.update({
                        "desired_version": saved["desired_version"],
                        "applied_version": saved["applied_version"],
                        "settings_status": saved["status"],
                    })
            return {"worker": name, **applied}
        except JsonHttpError as exc:
            if exc.status == 404:
                raise DomainError(
                    "WORKER_UPDATE_REQUIRED",
                    "Perbarui aplikasi worker agar pengaturan lewat Web tersedia.",
                    status_code=409,
                    details={"worker": name},
                ) from exc
            if 400 <= exc.status < 500:
                error_payload = exc.payload.get("error")
                error = error_payload if isinstance(error_payload, dict) else {}
                raise DomainError(
                    str(error.get("code") or "WORKER_SETTINGS_REJECTED"),
                    str(error.get("message") or "Worker menolak pengaturan tersebut."),
                    status_code=exc.status,
                    details={"worker": name},
                ) from exc
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Worker {name} tidak dapat dihubungi.",
                status_code=502,
                details={"worker": name},
            ) from exc
        except Exception as exc:
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Pengaturan worker {name} gagal disimpan.",
                status_code=502,
                details={"worker": name},
            ) from exc

    @app.delete("/api/v1/workers/{name}", response_model=ObjectResponse)
    def remove_worker(name: str, actor=Depends(current_actor)):
        del actor
        if any(
            context.profile_manager.worker_route(profile) == name
            for profile in context.profile_manager.list_profiles()
        ):
            raise DomainError(
                "WORKER_IN_USE",
                "Worker masih digunakan oleh profile.",
                status_code=409,
            )
        return {"removed": context.worker_registry.remove(name)}

    @app.put("/api/v1/me/worker-route", response_model=ObjectResponse)
    def set_worker_route(body: WorkerRouteRequest, actor=Depends(current_actor)):
        return {"route": context.control_plane.set_worker_route(actor, body.route)}
