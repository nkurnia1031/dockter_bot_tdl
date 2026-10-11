from __future__ import annotations

import re
from datetime import datetime
import uuid

from fastapi import Depends
from tme3bot.api.schemas import BackupRuntimeSettingsRequest, ItemListResponse, ObjectResponse
from tme3bot.backend_runtime_settings import BackendRuntimeSettings
from tme3bot.domain.models import DomainError
from tme3bot.infrastructure.http_client import JsonHttpError
from tme3bot.names import normalize_profile_name
from tme3bot.profile_diagnostics import PROFILE_TDL_DIAGNOSTIC_CODES


_WORKER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


def _safe_tdl_diagnostics(payload, *, worker: str, profile: str) -> dict:
    if not isinstance(payload, dict):
        raise DomainError(
            "PROFILE_TDL_DIAGNOSTICS_INVALID",
            "Worker mengembalikan hasil diagnosis TDL yang tidak valid.",
            status_code=502,
        )
    reported_worker = str(payload.get("worker") or "")
    if reported_worker != worker:
        raise DomainError(
            "BACKUP_DIAGNOSTIC_WORKER_MISMATCH",
            f"Worker {worker} melaporkan nama node {reported_worker or 'kosong'}. Periksa BACKUP_NODE_NAME pada worker.",
            status_code=409,
            details={"expected_worker": worker, "reported_worker": reported_worker},
        )
    if payload.get("profile") != profile:
        raise DomainError(
            "BACKUP_DIAGNOSTIC_PROFILE_MISMATCH",
            "Worker mengembalikan diagnosis untuk profil yang berbeda.",
            status_code=409,
            details={"expected_profile": profile},
        )

    checked_at = str(payload.get("checked_at") or "")
    try:
        if len(checked_at) > 64:
            raise ValueError
        datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError:
        raise DomainError(
            "PROFILE_TDL_DIAGNOSTICS_INVALID",
            "Waktu hasil diagnosis TDL tidak valid.",
            status_code=502,
        ) from None

    raw_sessions = payload.get("sessions")
    sessions_by_name = {}
    if isinstance(raw_sessions, list):
        for item in raw_sessions:
            if not isinstance(item, dict) or item.get("name") not in {"root", "user1"}:
                continue
            name = str(item["name"])
            code = str(item.get("code") or "PROFILE_SESSION_UNAVAILABLE")
            if name in sessions_by_name or type(item.get("ready")) is not bool:
                continue
            if code not in PROFILE_TDL_DIAGNOSTIC_CODES or type(item.get("identity_matches_metadata")) is not bool:
                continue
            sessions_by_name[name] = {
                "name": name,
                "ready": item["ready"],
                "code": code,
                "identity_matches_metadata": item["identity_matches_metadata"],
            }
    if set(sessions_by_name) != {"root", "user1"}:
        raise DomainError(
            "PROFILE_TDL_DIAGNOSTICS_INVALID",
            "Worker tidak mengembalikan hasil diagnosis lengkap untuk root dan user1.",
            status_code=502,
        )
    reasons = payload.get("reason_codes")
    if (
        not isinstance(reasons, list)
        or any(str(code) not in PROFILE_TDL_DIAGNOSTIC_CODES for code in reasons)
        or type(payload.get("ready")) is not bool
        or type(payload.get("identity_match")) is not bool
    ):
        raise DomainError(
            "PROFILE_TDL_DIAGNOSTICS_INVALID",
            "Worker mengembalikan hasil diagnosis TDL yang tidak valid.",
            status_code=502,
        )
    return {
        "worker": worker,
        "profile": profile,
        "checked_at": checked_at,
        "ready": payload["ready"],
        "identity_match": payload["identity_match"],
        "reason_codes": list(dict.fromkeys(str(code) for code in reasons)),
        "sessions": [sessions_by_name["root"], sessions_by_name["user1"]],
    }

def register_backups(app, context, *, current_actor, job_dict):

    @app.post("/api/v1/backups/tdl-diagnostics")
    def backup_tdl_diagnostics(body: dict, actor=Depends(current_actor)):
        del actor
        worker = str(body.get("worker") or "").strip().lower()
        profile = normalize_profile_name(str(body.get("profile") or ""))
        if not _WORKER_NAME_RE.fullmatch(worker):
            raise DomainError("WORKER_NAME_INVALID", "Nama worker tidak valid.", status_code=422)
        if not profile:
            raise DomainError("PROFILE_NAME_INVALID", "Nama profil tidak valid.", status_code=422)
        if context.worker_registry.get(worker) is None:
            raise DomainError("WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404)
        diagnose = getattr(context.worker_dispatcher, "profile_tdl_diagnostics", None)
        if not callable(diagnose):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Backend belum mendukung diagnosis TDL dari halaman Backup.",
                status_code=409,
            )
        try:
            result = diagnose(worker, profile)
        except JsonHttpError as exc:
            if exc.status == 404:
                raise DomainError(
                    "WORKER_UPDATE_REQUIRED",
                    f"Worker {worker} perlu diperbarui agar diagnosis TDL tersedia.",
                    status_code=409,
                ) from exc
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Diagnosis TDL dari worker {worker} gagal. Periksa status worker dan coba lagi.",
                status_code=503 if exc.status >= 500 else 502,
            ) from exc
        except RuntimeError as exc:
            if "hanya diizinkan melalui HTTPS" in str(exc):
                raise DomainError(
                    "WORKER_TRANSPORT_INSECURE",
                    "Diagnosis worker remote memerlukan koneksi HTTPS.",
                    status_code=409,
                ) from exc
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Diagnosis TDL dari worker {worker} gagal. Periksa status worker dan coba lagi.",
                status_code=503,
            ) from None
        return _safe_tdl_diagnostics(result, worker=worker, profile=profile)

    @app.get("/api/v1/backups", response_model=ItemListResponse)
    def list_backups(actor=Depends(current_actor)):
        del actor
        return {"items": context.storage_catalog.backup_runs(limit=50)}

    @app.get("/api/v1/backups/status", response_model=ObjectResponse)
    def backup_status(actor=Depends(current_actor)):
        del actor
        values = context.runtime_settings.get() if context.runtime_settings is not None else {}
        return {
            "enabled": values.get("backup_enabled", context.config.backup_enabled),
            "schedule": values.get("backup_schedule", context.config.backup_schedule),
            "timezone": values.get("backup_timezone", context.config.backup_timezone),
            "retention": values.get("backup_retention", context.config.backup_retention),
            "volume_size": values.get("backup_volume_size", context.config.backup_volume_size),
            "channel": values.get("backup_channel", context.config.backup_channel),
            "storage_trash_retention_days": values.get(
                "storage_trash_retention_days", context.config.storage_trash_retention_days
            ),
            "job_stall_timeout_seconds": values.get(
                "job_stall_timeout_seconds", context.config.job_stall_timeout_seconds
            ),
            "job_cancel_grace_seconds": values.get(
                "job_cancel_grace_seconds", context.config.job_cancel_grace_seconds
            ),
            "items": context.storage_catalog.backup_runs(limit=20),
        }

    @app.put("/api/v1/backups/settings", response_model=ObjectResponse)
    def update_backup_settings(
        body: BackupRuntimeSettingsRequest, actor=Depends(current_actor)
    ):
        del actor
        if context.runtime_settings is None:
            raise DomainError(
                "RUNTIME_SETTINGS_UNAVAILABLE",
                "Pengaturan runtime backend belum tersedia.",
                status_code=503,
            )
        try:
            channel_id = 0
            if body.channel.strip():
                from tme3bot.chat_refs import normalize_bot_api_chat_ref
                from tme3bot.channel_ref import channel_chat_id

                bot_ref = normalize_bot_api_chat_ref(body.channel)
                if re.fullmatch(r"-?\d+", bot_ref):
                    channel_id = channel_chat_id(bot_ref)
                else:
                    if context.bot is None:
                        raise ValueError("Bot Telegram belum tersedia untuk memeriksa username channel.")
                    try:
                        chat = context.bot.get_chat(bot_ref)
                    except Exception as exc:
                        raise ValueError("Telegram tidak dapat menemukan channel dari username tersebut.") from exc
                    channel_id = int(getattr(chat, "id", 0))
                    if channel_id == 0:
                        raise ValueError("Telegram tidak menemukan channel dari username tersebut.")
            values = {
                "backup_enabled": body.enabled,
                "backup_schedule": body.schedule,
                "backup_timezone": body.timezone,
                "backup_retention": body.retention,
                "backup_volume_size": body.volume_size,
                "backup_channel": body.channel,
                "backup_channel_id": channel_id,
                "storage_trash_retention_days": body.storage_trash_retention_days,
                "job_stall_timeout_seconds": body.job_stall_timeout_seconds,
                "job_cancel_grace_seconds": body.job_cancel_grace_seconds,
            }
            saved = context.runtime_settings.update(values)
            BackendRuntimeSettings.apply_to(context.config, saved)
            if context.storage_maintenance is not None:
                context.storage_maintenance.retention_days = saved[
                    "storage_trash_retention_days"
                ]
            context.control_plane.job_stall_timeout_seconds = saved[
                "job_stall_timeout_seconds"
            ]
            context.control_plane.job_cancel_grace_seconds = saved[
                "job_cancel_grace_seconds"
            ]
            if context.backup_scheduler is not None:
                context.backup_scheduler.wake()
        except (TypeError, ValueError) as exc:
            raise DomainError(
                "INVALID_RUNTIME_SETTINGS", str(exc), status_code=422
            ) from exc
        return {
            "enabled": saved["backup_enabled"],
            "schedule": saved["backup_schedule"],
            "timezone": saved["backup_timezone"],
            "retention": saved["backup_retention"],
            "volume_size": saved["backup_volume_size"],
            "channel": saved["backup_channel"],
            "storage_trash_retention_days": saved["storage_trash_retention_days"],
            "job_stall_timeout_seconds": saved["job_stall_timeout_seconds"],
            "job_cancel_grace_seconds": saved["job_cancel_grace_seconds"],
        }

    @app.post("/api/v1/backups", response_model=ObjectResponse)
    def start_backup(actor=Depends(current_actor)):
        if context.backup_coordinator is not None:
            return {"run_id": context.backup_coordinator.start_now()}
        jobs = []
        password = context.utility_settings.get().get("compress_password", "")
        run_id = str(uuid.uuid4())
        for worker in context.worker_registry.names():
            jobs.append(
                job_dict(
                    context.control_plane.submit_job(
                        actor,
                        "backup_node",
                        {
                            "backup_run_id": run_id,
                            "node_name": worker,
                            "password": password,
                            "channel_ref": context.config.backup_channel_ref,
                            "channel_id": context.config.backup_channel_id,
                            "volume_size": context.config.backup_volume_size,
                        },
                        profile=actor.profile,
                        worker=worker,
                    )
                )
            )
        return {"run_id": run_id, "jobs": jobs}
