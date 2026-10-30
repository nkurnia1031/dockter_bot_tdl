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
    WorkerTtsHealthResponse,
    WorkerTtsRecoveryResponse,
    WorkerUpdateRequest,
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
                    quick_evidence = {"runtime": "quick-mode-readiness-v1", "worker": name, "profile": quickmode_cell["profile"], "export_session": quickmode_cell["session_fingerprint"], "quick_runtime": str(quick_runtime.get("fingerprint") or ""), "storage_destination": storage_destination_hash, "senders": storage_sender_fingerprints, "rclone_destination": rclone_destination_fingerprint}
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
                readiness = item.get("_runtime_readiness")
                if isinstance(readiness, dict):
                    readiness_profiles[name].append(readiness)
                quickmode_readiness = item.get("_quickmode_readiness")
                if isinstance(quickmode_readiness, dict):
                    readiness_quickmode[name].append(quickmode_readiness)
                safe_items.append({
                    key: value for key, value in item.items()
                    if key not in {
                        "_runtime_readiness", "_quickmode_readiness", "_storage_readiness",
                        "_download_readiness", "_upload_readiness",
                    }
                })
            inventories.append({
                "worker": name,
                "checked_at": inventory["checked_at"],
                "items": safe_items,
            })

        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
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
                    workers=readiness_resolver,
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

    profile_scan_store = getattr(context, "profile_scan_store", None)
    if callable(getattr(profile_scan_store, "create", None)):
        profile_scan_operations = ProfileScanOperations(
            profile_scan_store,
            lambda operation_id: _perform_profile_catalog_scan(
                getattr(context, "local_profile_catalog", None), operation_id
            ),
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
