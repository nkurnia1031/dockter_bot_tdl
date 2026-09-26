from __future__ import annotations

from fastapi import Depends
from tme3bot.api.schemas import BatchSourcesRequest, ExportRequest, ItemListResponse, JobResponse, LabelRequest, ObjectResponse, SourceListResponse, SourceResponse, SourceUpdateRequest
from tme3bot.domain.models import DomainError

def register_sources(app, context, *, _model_dict, current_actor, job_dict, verify_target):

    @app.get("/api/v1/sources", response_model=SourceListResponse)
    def list_sources(profile: str | None = None, actor=Depends(current_actor)):
        selected_profile = context.control_plane.require_profile(actor, profile)
        store = context.profile_manager.runtime(selected_profile).state_store
        return {
            "items": [
                {"chat_ref": chat_ref, **source.to_dict()}
                for chat_ref, source in store.list_sources()
            ]
        }

    @app.get("/api/v1/sources/{chat_ref:path}", response_model=SourceResponse)
    def get_source(chat_ref: str, profile: str | None = None, actor=Depends(current_actor)):
        selected_profile = context.control_plane.require_profile(actor, profile)
        source = context.profile_manager.runtime(selected_profile).state_store.get_source(chat_ref)
        if source is None:
            raise DomainError("SOURCE_NOT_FOUND", "Source tidak ditemukan.", status_code=404)
        return {"chat_ref": chat_ref, **source.to_dict()}

    @app.delete("/api/v1/sources/{chat_ref:path}", response_model=ObjectResponse)
    def delete_source(chat_ref: str, profile: str | None = None, actor=Depends(current_actor)):
        selected_profile = context.control_plane.require_profile(actor, profile)
        deleted = context.profile_manager.runtime(selected_profile).state_store.delete_source(chat_ref)
        return {"deleted": deleted}

    @app.patch("/api/v1/sources/{chat_ref:path}", response_model=SourceResponse)
    def update_source(
        chat_ref: str, body: SourceUpdateRequest, profile: str | None = None, actor=Depends(current_actor)
    ):
        selected_profile = context.control_plane.require_profile(actor, profile)
        store = context.profile_manager.runtime(selected_profile).state_store
        source = store.get_source(chat_ref)
        if source is None:
            raise DomainError(
                "SOURCE_NOT_FOUND", "Source tidak ditemukan.", status_code=404
            )
        updated = store.upsert_source(
            chat_ref,
            body.label,
            source.last_id,
            source.warmup_url,
            source.warmup_done,
        )
        return {"chat_ref": chat_ref, **updated.to_dict()}

    @app.post("/api/v1/sources/batch-delete", response_model=ObjectResponse)
    def batch_delete_sources(body: BatchSourcesRequest, profile: str | None = None, actor=Depends(current_actor)):
        selected_profile = context.control_plane.require_profile(actor, profile)
        deleted = context.profile_manager.runtime(selected_profile).state_store.delete_sources(body.chat_refs)
        return {"deleted": deleted}

    @app.post("/api/v1/exports", response_model=JobResponse)
    def submit_export(body: ExportRequest, actor=Depends(current_actor)):
        values = _model_dict(body)
        if not values.get("url") and not values.get("chat_ref"):
            raise DomainError(
                "EXPORT_REFERENCE_REQUIRED",
                "Isi URL lama atau chat_ref username/numeric ID.",
                status_code=422,
            )
        verify_target(
            actor,
            "export",
            values.get("profile"),
            values.get("worker"),
            quick_mode=bool(values.get("quick_mode")),
        )
        if bool(values.get("quick_mode")):
            # Snapshot settings at submission time. The password is retained
            # only in the internal worker command and redacted from the Job API.
            values["quick_settings"] = context.utility_settings.get()
            values["quick_settings"].setdefault(
                "rclone_destination", "googledrive:backup"
            )
        return job_dict(
            context.control_plane.submit_job(
                actor, "export", values, profile=values.get("profile"), worker=values.get("worker")
            )
        )

    @app.get("/api/v1/labels", response_model=ItemListResponse)
    def list_labels(actor=Depends(current_actor)):
        del actor
        if context.label_store is None:
            return {"items": []}
        return {
            "items": [
                {"label": item.label, "updated_at": item.updated_at}
                for item in context.label_store.list_labels(limit=100)
            ]
        }

    @app.post("/api/v1/labels", response_model=ObjectResponse)
    def add_label(body: LabelRequest, actor=Depends(current_actor)):
        del actor
        if context.label_store is None:
            raise DomainError(
                "LABEL_STORE_UNAVAILABLE",
                "Label store belum tersedia.",
                status_code=503,
            )
        return {"label": context.label_store.add(body.label)}

    @app.post("/api/v1/sources/leave", response_model=JobResponse)
    def submit_leave(body: BatchSourcesRequest, actor=Depends(current_actor)):
        return job_dict(
            context.control_plane.submit_job(
                actor, "leave", {"chat_refs": body.chat_refs}, profile=actor.profile
            )
        )
