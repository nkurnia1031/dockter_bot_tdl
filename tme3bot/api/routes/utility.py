from __future__ import annotations

from fastapi import Depends
from tme3bot.api.schemas import ItemListResponse, JobResponse, ObjectResponse, SettingRequest, UtilityFolderRequest, UtilityJobRequest
from tme3bot.domain.models import DomainError
from tme3bot.utility import utility_setting_specs

def register_utility(app, context, *, _model_dict, current_actor, job_dict, verify_target):

    @app.get("/api/v1/utility/folders", response_model=ItemListResponse)
    def utility_folders(actor=Depends(current_actor)):
        del actor
        return {"items": context.utility_folders.list()}

    @app.get("/api/v1/utility/tree", response_model=ObjectResponse)
    def utility_tree(path: str = "/workspace", worker: str | None = None, actor=Depends(current_actor)):
        _, worker = context.control_plane.resolve_target(actor, worker=worker)
        if context.worker_dispatcher is None:
            raise DomainError(
                "WORKER_INVENTORY_UNAVAILABLE",
                "Inventory workspace worker belum tersedia.",
                status_code=503,
            )
        return context.worker_dispatcher.workspace_tree(worker, path)

    @app.post("/api/v1/utility/folders", response_model=ObjectResponse)
    def add_utility_folder(body: UtilityFolderRequest, actor=Depends(current_actor)):
        del actor
        return {"path": context.utility_folders.add(body.path)}

    @app.delete("/api/v1/utility/folders", response_model=ObjectResponse)
    def remove_utility_folder(path: str, actor=Depends(current_actor)):
        del actor
        return {"removed": context.utility_folders.remove(path)}

    @app.get("/api/v1/utility/settings", response_model=ObjectResponse)
    def utility_settings(actor=Depends(current_actor)):
        del actor
        values = context.utility_settings.get()
        # The dashboard only needs to know whether a password exists. Never
        # return the actual archive/backup password to a browser.
        return {
            "move_size": values["move_size"],
            "compress_size": values["compress_size"],
            "rclone_destination": values.get("rclone_destination", "googledrive:backup"),
            "compress_password_configured": bool(values.get("compress_password")),
        }

    @app.get("/api/v1/utility/settings/meta", response_model=ItemListResponse)
    def utility_settings_meta(actor=Depends(current_actor)):
        del actor
        return {"items": utility_setting_specs()}

    @app.put("/api/v1/utility/settings/{key}", response_model=ObjectResponse)
    def set_utility_setting(key: str, body: SettingRequest, actor=Depends(current_actor)):
        del actor
        context.utility_settings.set(key, body.value)
        values = context.utility_settings.get()
        return {
            "move_size": values["move_size"],
            "compress_size": values["compress_size"],
            "rclone_destination": values.get("rclone_destination", "googledrive:backup"),
            "compress_password_configured": bool(values.get("compress_password")),
        }

    @app.post("/api/v1/utility/jobs", response_model=JobResponse)
    def submit_utility(body: UtilityJobRequest, actor=Depends(current_actor)):
        settings = context.utility_settings.get()
        payload = _model_dict(body)
        payload["settings"] = settings
        verify_target(actor, "utility", None, payload.get("worker"))
        return job_dict(
            context.control_plane.submit_job(
                actor, "utility", payload, profile=actor.profile, worker=payload.get("worker")
            )
        )
