from __future__ import annotations

from fastapi import Depends
from tme3bot.api.schemas import BackupRuntimeSettingsRequest, ItemListResponse, ObjectResponse
from tme3bot.backend_runtime_settings import BackendRuntimeSettings
from tme3bot.domain.models import DomainError
import uuid
import re

def register_backups(app, context, *, current_actor, job_dict):

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
