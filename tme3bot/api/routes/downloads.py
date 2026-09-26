from __future__ import annotations

from fastapi import Depends, Query
from tme3bot.api.schemas import DownloadBatchRequest, DownloadRequest, JobResponse, ObjectResponse
from tme3bot.domain.models import DomainError
from typing import Any
import uuid

def register_downloads(app, context, *, _model_dict, _profile_artifact, current_actor, job_dict):

    @app.post("/api/v1/downloads", response_model=JobResponse)
    def submit_download(
        body: DownloadRequest | None = None,
        retry_failed: bool = False,
        actor=Depends(current_actor),
    ):
        values = _model_dict(body) if body is not None else {}
        artifact_ids = values.get("artifact_ids") or []
        worker = None
        selected_profile = None
        artifact_keys: list[str] = []
        artifact_refs: list[dict[str, str]] = []
        for artifact_id in artifact_ids:
            artifact = context.export_catalog.get(str(artifact_id))
            if artifact is None:
                raise DomainError("ARTIFACT_NOT_FOUND", "Artifact tidak ditemukan.", status_code=404)
            context.control_plane.require_profile(actor, str(artifact["profile"]))
            # Validate the pinned origin before creating a download job.
            context.control_plane.resolve_target(
                actor,
                profile=str(artifact["profile"]),
                worker=str(artifact["worker"]),
            )
            if artifact["status"] not in {"pending", "failed"}:
                raise DomainError(
                    "ARTIFACT_NOT_PENDING",
                    "Artifact tidak berada pada antrean yang dapat dijalankan.",
                    status_code=409,
                )
            if not bool(artifact.get("available", 1)):
                raise DomainError(
                    "ARTIFACT_UNAVAILABLE",
                    "File artifact sudah tidak tersedia pada worker.",
                    status_code=409,
                )
            if selected_profile is not None and selected_profile != artifact["profile"]:
                raise DomainError(
                    "ARTIFACT_ORIGIN_MIXED",
                    "Gunakan endpoint batch untuk artifact dari origin berbeda.",
                    status_code=409,
                )
            if worker is not None and worker != artifact["worker"]:
                raise DomainError("ARTIFACT_ORIGIN_MIXED", "Gunakan endpoint batch untuk artifact dari origin berbeda.", status_code=409)
            selected_profile = str(artifact["profile"])
            worker = str(artifact["worker"])
            artifact_keys.append(str(artifact["artifact_key"]))
            artifact_refs.append(
                {
                    "key": str(artifact["artifact_key"]),
                    "status": str(artifact["status"]),
                }
            )
        return job_dict(
            context.control_plane.submit_job(
                actor,
                "download",
                {
                    "retry_failed": retry_failed,
                    "artifact_keys": artifact_keys,
                    "artifacts": artifact_refs,
                    "priority": values.get("priority", "normal"),
                },
                profile=selected_profile or actor.profile,
                worker=worker,
            )
        )

    @app.post("/api/v1/downloads/batch", response_model=ObjectResponse)
    def submit_download_batch(body: DownloadBatchRequest, actor=Depends(current_actor)):
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for artifact_id in body.artifact_ids:
            artifact = context.export_catalog.get(str(artifact_id))
            if artifact is None:
                raise DomainError("ARTIFACT_NOT_FOUND", "Artifact tidak ditemukan.", status_code=404)
            context.control_plane.require_profile(actor, str(artifact["profile"]))
            # Validate all origins before dispatching any group so a disabled
            # worker cannot leave a partially-created batch behind.
            context.control_plane.resolve_target(
                actor,
                profile=str(artifact["profile"]),
                worker=str(artifact["worker"]),
            )
            if artifact["status"] not in {"pending", "failed"}:
                raise DomainError("ARTIFACT_NOT_PENDING", "Artifact tidak berada pada antrean yang dapat dijalankan.", status_code=409)
            if not bool(artifact.get("available", 1)):
                raise DomainError("ARTIFACT_UNAVAILABLE", "File artifact sudah tidak tersedia pada worker.", status_code=409)
            key = (str(artifact["profile"]), str(artifact["worker"]))
            groups.setdefault(key, []).append(artifact)
        jobs, response_groups = [], []
        for (profile, worker), items in groups.items():
            job = context.control_plane.submit_job(
                actor,
                "download",
                {
                    "retry_failed": any(item["status"] == "failed" for item in items),
                    "artifact_keys": [str(item["artifact_key"]) for item in items],
                    "artifacts": [{"key": str(item["artifact_key"]), "status": str(item["status"])} for item in items],
                    "priority": body.priority,
                },
                profile=profile,
                worker=worker,
            )
            jobs.append(job_dict(job))
            response_groups.append({"profile": profile, "worker": worker, "artifact_ids": [str(item["id"]) for item in items], "job_id": job.id})
        return {"jobs": jobs, "groups": response_groups}

    @app.get("/api/v1/downloads/artifacts", response_model=ObjectResponse)
    def list_artifacts(
        scope: str = Query("current", pattern="^(current|global)$"),
        profile: str | None = None,
        status: str | None = None,
        archived: bool | None = False,
        worker: str | None = None,
        label: str | None = None,
        chat_ref: str | None = None,
        available: bool | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        selected_profile = None if scope == "global" else context.control_plane.require_profile(actor, profile)
        if profile:
            selected_profile = context.control_plane.require_profile(actor, profile)
        items, total = context.export_catalog.list(
            profile=selected_profile,
            status=status,
            archived=archived,
            worker=worker,
            label=label,
            chat_ref=chat_ref,
            available=available,
            limit=limit,
            offset=offset,
        )
        return {"items": items, "total": total}

    @app.post("/api/v1/downloads/artifacts/reconcile", response_model=ObjectResponse)
    def reconcile_artifacts(
        scope: str = Query("current", pattern="^(current|global)$"),
        profile: str | None = None,
        worker: str | None = None,
        actor=Depends(current_actor),
    ):
        pairs: list[tuple[str, str]] = []
        if scope == "global":
            if profile:
                context.control_plane.require_profile(actor, profile)
            pairs = list(context.export_catalog.origins()) if context.export_catalog is not None else []
            if profile:
                pairs = [pair for pair in pairs if pair[0] == profile]
            if worker:
                pairs = [pair for pair in pairs if pair[1] == worker]
        else:
            selected_profile = context.control_plane.require_profile(actor, profile)
            _, selected_worker = context.control_plane.resolve_target(actor, profile=selected_profile, worker=worker)
            pairs = [(selected_profile, selected_worker)]
        jobs = []
        for selected_profile, selected_worker in pairs:
            inventory_id = str(uuid.uuid4())
            jobs.append(job_dict(context.control_plane.submit_job(
                actor, "artifact_inventory", {"inventory_id": inventory_id},
                profile=selected_profile, worker=selected_worker,
            )))
        return {"jobs": jobs, "items": jobs}

    @app.post("/api/v1/downloads/artifacts/{artifact_id}/delete-file", response_model=JobResponse)
    def delete_artifact_file(artifact_id: str, actor=Depends(current_actor)):
        artifact = _profile_artifact(context, actor, artifact_id)
        if artifact["status"] not in {"pending", "failed"}:
            raise DomainError(
                "ARTIFACT_ACTIVE",
                "Artifact aktif atau sudah selesai tidak dapat dihapus.",
                status_code=409,
            )
        context.export_catalog.update_status(artifact_id, "deleted")
        return job_dict(
            context.control_plane.submit_job(
                actor,
                "artifact_delete",
                {"artifact_key": artifact["artifact_key"]},
                profile=str(artifact["profile"]),
                worker=str(artifact["worker"]),
            )
        )

    @app.post("/api/v1/downloads/artifacts/actions/delete", response_model=ObjectResponse)
    def delete_artifacts_batch(body: DownloadBatchRequest, actor=Depends(current_actor)):
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for artifact_id in body.artifact_ids:
            artifact = context.export_catalog.get(str(artifact_id))
            if artifact is None:
                raise DomainError("ARTIFACT_NOT_FOUND", "Artifact tidak ditemukan.", status_code=404)
            context.control_plane.require_profile(actor, str(artifact["profile"]))
            if artifact["status"] not in {"pending", "failed"}:
                raise DomainError("ARTIFACT_ACTIVE", "Artifact aktif atau selesai tidak dapat dihapus sebagai file pending.", status_code=409)
            groups.setdefault((str(artifact["profile"]), str(artifact["worker"])), []).append(artifact)
        jobs, deleted = [], []
        for (profile, worker), items in groups.items():
            for item in items:
                context.export_catalog.update_status(str(item["id"]), "deleted")
                deleted.append(str(item["id"]))
            jobs.append(job_dict(context.control_plane.submit_job(
                actor, "artifact_delete",
                {"artifact_keys": [str(item["artifact_key"]) for item in items]},
                profile=profile, worker=worker,
            )))
        return {"deleted": deleted, "jobs": jobs}

    @app.post("/api/v1/downloads/artifacts/{artifact_id}/archive", response_model=ObjectResponse)
    def archive_artifact(artifact_id: str, actor=Depends(current_actor)):
        _profile_artifact(context, actor, artifact_id)
        return context.export_catalog.archive(artifact_id)

    @app.post("/api/v1/downloads/artifacts/{artifact_id}/restore", response_model=ObjectResponse)
    def restore_artifact(artifact_id: str, actor=Depends(current_actor)):
        _profile_artifact(context, actor, artifact_id)
        return context.export_catalog.restore(artifact_id)

    @app.delete("/api/v1/downloads/artifacts/{artifact_id}", response_model=ObjectResponse)
    def purge_artifact(artifact_id: str, actor=Depends(current_actor)):
        _profile_artifact(context, actor, artifact_id)
        return {"purged": context.export_catalog.purge(artifact_id)}

    @app.get("/api/v1/dashboard/summary", response_model=ObjectResponse)
    def dashboard_summary(actor=Depends(current_actor)):
        jobs = context.control_plane.jobs
        active = sum(
            jobs.count(profile=actor.profile, status=status, archived=False)
            for status in ("queued", "dispatched", "running", "paused")
        )
        artifact_counts = context.export_catalog.summary(actor.profile)
        storage_items = context.storage_catalog.search("", limit=1, offset=0)
        backups = context.storage_catalog.backup_runs(limit=1)
        return {
            "profile": actor.profile,
            "worker": context.profile_manager.worker_route(actor.profile),
            "jobs": {
                "active": active,
                "failed": jobs.count(
                    profile=actor.profile, status="failed", archived=False
                ),
            },
            "artifacts": artifact_counts,
            "storage": {"has_items": bool(storage_items)},
            "last_backup": backups[0] if backups else None,
        }

    @app.post("/api/v1/downloads/clear-failed", response_model=ObjectResponse)
    def clear_failed(
        scope: str = Query("current", pattern="^(current|global)$"),
        profile: str | None = None,
        worker: str | None = None,
        actor=Depends(current_actor),
    ):
        if scope == "global":
            if profile:
                context.control_plane.require_profile(actor, profile)
            pairs = list(context.export_catalog.origins()) if context.export_catalog is not None else []
            if profile:
                pairs = [pair for pair in pairs if pair[0] == profile]
            if worker:
                pairs = [pair for pair in pairs if pair[1] == worker]
            jobs = [
                context.control_plane.submit_job(
                    actor, "download_clear_failed", {}, profile=selected_profile, worker=selected_worker
                )
                for selected_profile, selected_worker in pairs
            ]
            return {"jobs": [job_dict(job) for job in jobs]}
        selected_profile, selected_worker = context.control_plane.resolve_target(
            actor, profile=profile, worker=worker
        )
        return {"job": job_dict(context.control_plane.submit_job(
            actor, "download_clear_failed", {}, profile=selected_profile, worker=selected_worker
        ))}

    @app.put("/api/v1/downloads/mode/{mode}", response_model=ObjectResponse)
    def set_download_mode(mode: str, actor=Depends(current_actor)):
        if context.control_plane.jobs.has_active(actor.profile):
            raise DomainError(
                "PROFILE_BUSY", "Profile masih memiliki job aktif.", status_code=409
            )
        return {
            "mode": context.profile_manager.set_download_mode(actor.profile, mode)
        }
