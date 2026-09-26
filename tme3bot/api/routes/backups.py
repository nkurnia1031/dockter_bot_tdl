from __future__ import annotations

from fastapi import Depends
from tme3bot.api.schemas import ItemListResponse, ObjectResponse
import uuid

def register_backups(app, context, *, current_actor, job_dict):

    @app.get("/api/v1/backups", response_model=ItemListResponse)
    def list_backups(actor=Depends(current_actor)):
        del actor
        return {"items": context.storage_catalog.backup_runs(limit=50)}

    @app.get("/api/v1/backups/status", response_model=ObjectResponse)
    def backup_status(actor=Depends(current_actor)):
        del actor
        return {
            "enabled": context.config.backup_enabled,
            "schedule": context.config.backup_schedule,
            "timezone": context.config.backup_timezone,
            "retention": context.config.backup_retention,
            "volume_size": context.config.backup_volume_size,
            "channel": context.config.backup_channel,
            "items": context.storage_catalog.backup_runs(limit=20),
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
