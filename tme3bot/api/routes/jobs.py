from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Query
from tme3bot.api.schemas import JobEventListResponse, JobListResponse, JobResponse, ObjectResponse, WorkerEventRequest
from tme3bot.domain.models import DomainError, Job, JobEvent, JobStatus, utc_now
from typing import Any

def register_jobs(app, context, *, _newest_first_log_response, _owned_job, current_actor, event_dict, job_dict, require_internal, require_service):

    @app.get("/api/v1/jobs", response_model=JobListResponse)
    def list_jobs(
        kind: str | None = None,
        status: str | None = None,
        worker: str | None = None,
        profile: str | None = None,
        quick_mode: bool | None = None,
        scope: str = Query("current", pattern="^(current|global)$"),
        archived: bool | None = False,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        selected_profile = None if scope == "global" else context.control_plane.require_profile(actor, profile)
        if profile and scope == "global":
            selected_profile = context.control_plane.require_profile(actor, profile)
        # The monitor needs one request for all active lifecycle states while
        # the repository intentionally keeps its indexed status filter scalar.
        # Accepting a comma-separated value here keeps the public API backward
        # compatible with the existing single-status query.
        status_values = [
            value.strip().lower()
            for value in str(status or "").split(",")
            if value.strip()
        ]
        if len(status_values) <= 1:
            items = context.control_plane.jobs.list(
                profile=selected_profile,
                kind=kind,
                status=status_values[0] if status_values else None,
                worker=worker,
                quick_mode=quick_mode,
                archived=archived,
                offset=offset,
                limit=limit,
            )
            total = context.control_plane.jobs.count(
                profile=selected_profile,
                kind=kind,
                status=status_values[0] if status_values else None,
                worker=worker,
                quick_mode=quick_mode,
                archived=archived,
            )
        else:
            matching: list[Job] = []
            total = 0
            for status_value in dict.fromkeys(status_values):
                matching.extend(
                    context.control_plane.jobs.list(
                        profile=selected_profile,
                        kind=kind,
                        status=status_value,
                        worker=worker,
                        quick_mode=quick_mode,
                        archived=archived,
                        offset=0,
                        limit=200,
                    )
                )
                total += context.control_plane.jobs.count(
                    profile=selected_profile,
                    kind=kind,
                    status=status_value,
                    worker=worker,
                    quick_mode=quick_mode,
                    archived=archived,
                )
            matching.sort(key=lambda item: item.updated_at, reverse=True)
            items = matching[offset : offset + limit]
        return {
            "items": [job_dict(item) for item in items],
            "total": total,
            "next_offset": offset + len(items) if offset + len(items) < total else None,
        }

    @app.get("/api/v1/jobs/metrics", response_model=ObjectResponse)
    def job_metrics(
        scope: str = Query("current", pattern="^(current|global)$"),
        profile: str | None = None,
        worker: str | None = None,
        actor=Depends(current_actor),
    ):
        selected_profile = (
            context.control_plane.require_profile(actor, profile)
            if profile
            else None
            if scope == "global"
            else context.control_plane.require_profile(actor, None)
        )
        registry = context.worker_registry.list() if context.worker_registry is not None else {}
        worker_names = sorted(registry)
        if worker:
            worker_names = [name for name in worker_names if name == worker]
        snapshot = context.control_plane.jobs.monitor_metrics(
            profile=selected_profile,
            worker=worker,
        )
        by_worker = {item["worker"]: item for item in snapshot["workers"]}
        now = datetime.now(timezone.utc)
        for name in worker_names:
            item = by_worker.setdefault(
                name,
                {
                    "worker": name,
                    "queued_jobs": 0,
                    "dispatched_jobs": 0,
                    "running_jobs": 0,
                    "paused_jobs": 0,
                    "quickmode_queued": 0,
                    "quickmode_active": 0,
                    "quickmode_paused": 0,
                    "average_queue_wait_seconds": None,
                    "event_latency": {"count": 0, "average_ms": None},
                    "phase_seconds": {},
                    "last_seen_at": None,
                },
            )
            record = registry.get(name) or {}
            item["enabled"] = bool(record.get("enabled", True))
            active_count = int(item["dispatched_jobs"]) + int(item["running_jobs"])
            last_seen = item.get("last_seen_at")
            age_seconds = None
            if last_seen:
                try:
                    last_seen_at = datetime.fromisoformat(str(last_seen))
                    if last_seen_at.tzinfo is None:
                        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
                    age_seconds = max(0.0, (now - last_seen_at).total_seconds())
                except ValueError:
                    age_seconds = None
            if not item["enabled"]:
                item["status"] = "disabled"
            elif active_count:
                item["status"] = "stale" if age_seconds is None or age_seconds > 45 else "busy"
            elif item["paused_jobs"]:
                item["status"] = "paused"
            elif item["queued_jobs"]:
                item["status"] = "queued"
            else:
                item["status"] = "idle"
            item["active_jobs"] = active_count
            item["last_seen_age_seconds"] = (
                round(age_seconds, 1) if age_seconds is not None else None
            )
        limits = {
            item["worker"]: item
            for item in context.control_plane.jobs.quickmode_limits(worker_names)
        }
        workers = []
        for name in worker_names:
            item = dict(by_worker[name])
            item.update(
                {
                    "quickmode_limit": limits.get(name, {}).get("max_concurrent", 2),
                    "quickmode_slots": limits.get(name, {}).get("active", 0),
                    "quickmode_queued": limits.get(name, {}).get(
                        "queued", item["quickmode_queued"]
                    ),
                }
            )
            workers.append(item)
        snapshot["workers"] = workers
        snapshot["active_jobs"] = snapshot["dispatched_jobs"] + snapshot["running_jobs"]
        return snapshot

    @app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str, actor=Depends(current_actor)):
        job = _owned_job(context, actor, job_id)
        return job_dict(job)

    @app.get("/api/v1/quick-mode/staging", response_model=ObjectResponse)
    def quick_mode_staging(actor=Depends(current_actor)):
        """Merge persisted Quick Mode jobs with physical worker staging."""
        del actor
        jobs = context.control_plane.jobs.list(
            kind="export",
            quick_mode=True,
            archived=False,
            offset=0,
            limit=1000,
        )
        by_stage: dict[tuple[str, str], dict[str, Any]] = {}
        for job in jobs:
            retry = job.payload.get("quick_retry")
            retry = retry if isinstance(retry, dict) else {}
            result_value = job.result.get("value", job.result) if isinstance(job.result, dict) else {}
            result_value = result_value if isinstance(result_value, dict) else {}
            stage_id = str(
                retry.get("stage_job_id")
                or result_value.get("stage_job_id")
                or job.id
            )
            # Keep the newest attempt as the linked backend row, while the
            # response still includes the stable stage identity.
            key = (str(job.worker), stage_id)
            if key not in by_stage:
                by_stage[key] = {
                    "id": stage_id,
                    "job": job_dict(job),
                    "backend_job_id": job.id,
                }

        items: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        dispatcher = context.worker_dispatcher
        worker_names = context.worker_registry.names() if context.worker_registry is not None else []
        scanner = getattr(dispatcher, "quickmode_scan", None) if dispatcher is not None else None
        for worker in worker_names:
            try:
                response = scanner(worker) if callable(scanner) else {"worker": worker, "items": []}
                scanned = response.get("items", []) if isinstance(response, dict) else []
                if not isinstance(scanned, list):
                    scanned = []
                for raw in scanned:
                    if not isinstance(raw, dict):
                        continue
                    item = dict(raw)
                    stage_id = str(item.get("stage_job_id") or "")
                    if not stage_id:
                        continue
                    linked = by_stage.get((worker, stage_id))
                    item["worker"] = str(item.get("worker") or worker)
                    item["backend_job"] = linked["job"] if linked else None
                    item["backend_job_id"] = linked["backend_job_id"] if linked else None
                    item["orphan"] = linked is None
                    linked_status = str(linked["job"].get("status") or "") if linked else ""
                    verifier = getattr(dispatcher, "quickmode_verify", None) if dispatcher is not None else None
                    if (
                        str(item.get("phase") or "") in {"uploading", "cleanup"}
                        and linked_status not in {"queued", "dispatched", "running", "paused"}
                        and callable(verifier)
                    ):
                        try:
                            verification = verifier(
                                worker,
                                stage_id,
                                str(item.get("phase") or "uploading"),
                            )
                            if isinstance(verification, dict):
                                item["cleanup_verification"] = verification
                                item["staging_cleaned"] = bool(verification.get("staging_cleaned"))
                        except Exception as exc:
                            item["cleanup_verification"] = {
                                "status": "failed",
                                "reason": str(exc)[:500],
                                "staging_cleaned": False,
                            }
                    items.append(item)
            except Exception as exc:
                # One remote worker being offline must not hide staging from
                # the remaining workers.
                errors.append({"worker": worker, "error": str(exc)[:500]})

        return {"items": items, "errors": errors}

    @app.delete(
        "/api/v1/quick-mode/staging/{worker}/{stage_job_id}",
        response_model=ObjectResponse,
    )
    def delete_quick_mode_staging(
        worker: str,
        stage_job_id: str,
        actor=Depends(current_actor),
    ):
        """Delete one inactive physical stage while preserving job history."""
        del actor
        worker = str(worker or "").strip().lower()
        stage_job_id = str(stage_job_id or "").strip()
        if not worker or not stage_job_id:
            raise DomainError(
                "STAGING_TARGET_REQUIRED",
                "Worker dan stage_job_id wajib diisi.",
                status_code=422,
            )
        if context.worker_registry is None or context.worker_registry.get(worker) is None:
            raise DomainError("WORKER_NOT_FOUND", "Worker staging tidak ditemukan.", status_code=404)

        # A job can be queued at the gateway before its command reaches the
        # worker. Check every active lifecycle state here, then let the worker
        # perform the same check against its own queue to close the dispatch race.
        for status in ("queued", "dispatched", "running", "paused"):
            offset = 0
            while True:
                candidates = context.control_plane.jobs.list(
                    kind="export",
                    status=status,
                    worker=worker,
                    quick_mode=True,
                    archived=None,
                    offset=offset,
                    limit=200,
                )
                for candidate in candidates:
                    retry = candidate.payload.get("quick_retry")
                    retry = retry if isinstance(retry, dict) else {}
                    result_value = (
                        candidate.result.get("value", candidate.result)
                        if isinstance(candidate.result, dict)
                        else {}
                    )
                    result_value = result_value if isinstance(result_value, dict) else {}
                    candidate_stage = str(
                        retry.get("stage_job_id")
                        or result_value.get("stage_job_id")
                        or candidate.id
                    )
                    if candidate_stage == stage_job_id:
                        raise DomainError(
                            "QUICKMODE_STAGE_BUSY",
                            f"Folder staging sedang dipakai job #{candidate.id[:8]}.",
                            details={"job_id": candidate.id, "status": status},
                            status_code=409,
                        )
                if len(candidates) < 200:
                    break
                offset += len(candidates)

        deleter = getattr(context.worker_dispatcher, "quickmode_delete", None)
        if not callable(deleter):
            raise DomainError(
                "WORKER_INCOMPATIBLE",
                "Worker belum mendukung penghapusan staging Quick Mode. Deploy worker dengan release terbaru.",
                details={"worker": worker},
                status_code=409,
            )
        try:
            result = deleter(worker, stage_job_id)
        except DomainError:
            raise
        except Exception as exc:
            worker_status = getattr(exc, "status", None)
            payload = getattr(exc, "payload", {})
            error = payload.get("error") if isinstance(payload, dict) else None
            if worker_status in {404, 409, 422}:
                raise DomainError(
                    str(error.get("code") or "QUICKMODE_STAGE_DELETE_FAILED")
                    if isinstance(error, dict)
                    else "QUICKMODE_STAGE_DELETE_FAILED",
                    str(error.get("message") or exc)
                    if isinstance(error, dict)
                    else str(exc),
                    status_code=int(worker_status),
                ) from exc
            raise DomainError(
                "QUICKMODE_WORKER_UNAVAILABLE",
                f"Worker {worker} tidak dapat menghapus staging: {exc}",
                details={"worker": worker},
                status_code=502,
            ) from exc
        return {
            "worker": worker,
            "stage_job_id": stage_job_id,
            **(result if isinstance(result, dict) else {"deleted": bool(result)}),
        }

    @app.get("/api/v1/quick-mode/limits", response_model=ObjectResponse)
    def quick_mode_limits(actor=Depends(current_actor)):
        del actor
        workers = context.worker_registry.names() if context.worker_registry is not None else []
        return {"items": context.control_plane.jobs.quickmode_limits(workers)}

    @app.put("/api/v1/quick-mode/limits/{worker}", response_model=ObjectResponse)
    def update_quick_mode_limit(worker: str, body: dict[str, Any], actor=Depends(current_actor)):
        del actor
        names = context.worker_registry.names() if context.worker_registry is not None else []
        if worker not in names:
            raise DomainError("WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404)
        try:
            limit = int(body.get("max_concurrent"))
        except (TypeError, ValueError) as exc:
            raise DomainError("INVALID_QUICKMODE_LIMIT", "max_concurrent harus berupa angka 1 sampai 32.", status_code=422) from exc
        if not 1 <= limit <= 32:
            raise DomainError("INVALID_QUICKMODE_LIMIT", "Batas Quick Mode harus antara 1 sampai 32.", status_code=422)
        item = context.control_plane.set_quickmode_limit(worker, limit)
        return item

    @app.post("/api/v1/quick-mode/recover", response_model=ObjectResponse)
    def recover_quick_mode(body: dict[str, Any], actor=Depends(current_actor)):
        worker = str(body.get("worker") or "").strip().lower()
        stage_id = str(body.get("stage_job_id") or "").strip()
        resume_phase = str(body.get("resume_phase") or "").strip().lower() or None
        if resume_phase not in {None, "auto", "exporting", "downloading", "thumbnailing", "compressing", "uploading", "cleanup"}:
            raise DomainError(
                "INVALID_QUICK_PHASE",
                "Fase recovery Quick Mode tidak dikenal.",
                status_code=422,
            )
        if not worker or not stage_id:
            raise DomainError(
                "RECOVERY_TARGET_REQUIRED",
                "Worker dan stage_job_id wajib diisi.",
                status_code=422,
            )
        if context.worker_registry is not None and context.worker_registry.get(worker) is None:
            raise DomainError("WORKER_NOT_FOUND", "Worker recovery tidak ditemukan.", status_code=404)
        jobs = context.control_plane.jobs.list(
            kind="export", quick_mode=True, archived=False, offset=0, limit=1000
        )
        linked = None
        for candidate in jobs:
            retry = candidate.payload.get("quick_retry")
            retry = retry if isinstance(retry, dict) else {}
            candidate_stage = str(
                retry.get("stage_job_id")
                or candidate.id
            ).strip()
            if candidate_stage == stage_id and candidate.worker == worker:
                linked = candidate
                break
        if linked is not None:
            if not linked.status.terminal:
                raise DomainError(
                    "JOB_NOT_TERMINAL",
                    "Folder Quick Mode sudah memiliki job aktif.",
                    details={"job_id": linked.id, "message": f"Folder Quick Mode sedang diproses oleh job #{linked.id[:8]}."},
                    status_code=409,
                )
            return {
                "job": job_dict(
                    context.control_plane.retry_job(
                        actor,
                        linked.id,
                        resume_phase=resume_phase,
                        single_phase=bool(body.get("single_phase")),
                    )
                ),
                "imported": False,
            }

        scanner = getattr(context.worker_dispatcher, "quickmode_scan", None)
        try:
            response = scanner(worker) if callable(scanner) else {"items": []}
        except Exception as exc:
            raise DomainError("WORKER_OFFLINE", f"Worker recovery tidak tersedia: {exc}", status_code=503) from exc
        item = next(
            (value for value in response.get("items", []) if isinstance(value, dict) and str(value.get("stage_job_id")) == stage_id),
            None,
        )
        if item is None:
            raise DomainError("STAGING_NOT_FOUND", "Folder staging Quick Mode tidak ditemukan.", status_code=404)
        profile = str(body.get("profile") or item.get("profile") or "").strip()
        if not profile:
            raise DomainError("PROFILE_REQUIRED", "Profile wajib dipilih untuk folder recovery ini.", status_code=422)
        context.control_plane.require_profile(actor, profile)
        has_upload_assets = bool(item.get("archive_parts", 0)) and bool(item.get("thumbnail_present"))
        payload: dict[str, Any] = {
            "quick_mode": True,
            "quick_phase": resume_phase or "auto",
            "quick_settings": context.utility_settings.get(),
            "quick_retry": {
                "retry_phase": resume_phase or "auto",
                "resume_phase": resume_phase or "auto",
                "single_phase": bool(body.get("single_phase")) and resume_phase not in {None, "", "auto", "exporting"},
                "stage_job_id": stage_id,
                "quick_operation_id": str(item.get("quick_operation_id") or stage_id),
            },
        }
        for key in ("url", "chat_ref", "start_id", "label", "save_source", "use_url_message_id"):
            if body.get(key) is not None:
                payload[key] = body[key]
        if (
            not item.get("json_present")
            and not item.get("actual_media_count")
            and not has_upload_assets
            and not payload.get("url")
            and not payload.get("chat_ref")
        ):
            raise DomainError(
                "RECOVERY_SOURCE_REQUIRED",
                "Folder tidak memiliki JSON atau hasil upload lengkap. Berikan URL/chat ID untuk export ulang.",
                status_code=422,
            )
        job = context.control_plane.submit_job(
            actor,
            "export",
            payload,
            profile=profile,
            worker=worker,
        )
        return {"job": job_dict(job), "imported": True}

    @app.post(
        "/internal/v1/jobs/{job_id}/telegram-notifications",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def create_telegram_notification(job_id: str, body: dict[str, Any]):
        job = context.control_plane.jobs.get(job_id)
        if job is None:
            raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
        user_id = int(body.get("telegram_user_id") or 0)
        chat_id = int(body.get("telegram_chat_id") or 0)
        if user_id <= 0 or chat_id != user_id or user_id != job.actor_user_id:
            raise DomainError(
                "TELEGRAM_NOTIFICATION_FORBIDDEN",
                "Notifikasi hanya dapat didaftarkan oleh actor pembuat job pada private chat.",
                status_code=403,
            )
        notification = context.control_plane.jobs.create_telegram_notification(
            job.id, user_id, chat_id, job.profile
        )
        return {"notification": notification, "job": job_dict(job)}

    @app.get(
        "/internal/v1/telegram-notifications/pending",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def pending_telegram_notifications(limit: int = Query(100, ge=1, le=500)):
        items = []
        for notification in context.control_plane.jobs.pending_telegram_notifications(limit):
            job = context.control_plane.jobs.get(str(notification["job_id"]))
            if job is not None:
                items.append({"notification": notification, "job": job_dict(job)})
        return {"items": items}

    @app.patch(
        "/internal/v1/telegram-notifications/{notification_id}",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def update_telegram_notification(notification_id: int, body: dict[str, Any]):
        if str(body.get("status") or "") not in {
            "",
            "pending",
            "terminal",
            "deleted",
            "failed",
        }:
            raise DomainError(
                "INVALID_NOTIFICATION_STATUS",
                "Status notifikasi tidak valid.",
                status_code=422,
            )
        notification = context.control_plane.jobs.update_telegram_notification(
            notification_id, body
        )
        if notification is None:
            raise DomainError(
                "NOTIFICATION_NOT_FOUND",
                "Subscription notifikasi tidak ditemukan.",
                status_code=404,
            )
        return {"notification": notification}

    @app.get("/api/v1/jobs/{job_id}/events", response_model=JobEventListResponse)
    def get_job_events(
        job_id: str,
        after_sequence: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        _owned_job(context, actor, job_id)
        return {
            "items": [
                event_dict(item)
                for item in context.control_plane.jobs.events(
                    job_id, after_sequence=after_sequence
                )
            ]
        }

    @app.get("/api/v1/jobs/{job_id}/log-snapshot", response_model=ObjectResponse)
    def get_job_log_snapshot(job_id: str, actor=Depends(current_actor)):
        job = _owned_job(context, actor, job_id)
        if context.worker_dispatcher is not None:
            try:
                worker_log = _newest_first_log_response(
                    context.worker_dispatcher.job_log(job.worker, job.id)
                )
                return {
                    **worker_log,
                    "source": "worker",
                }
            except Exception:
                if job.status.value in {"queued", "dispatched", "running", "paused"}:
                    raise DomainError(
                        "JOB_LOG_UNAVAILABLE",
                        "Snapshot log worker belum tersedia.",
                        status_code=503,
                    )
        for event in reversed(context.control_plane.jobs.events(job.id)):
            if (
                event.event_type == "log.snapshot"
                and isinstance(event.result, dict)
                and isinstance(event.result.get("log"), dict)
            ):
                return {
                    **_newest_first_log_response({"log": event.result["log"]}),
                    "source": "history",
                }
        return {
            "log": {
                "lines": [],
                "line_count": 0,
                "truncated": False,
                "order": "newest_first",
            },
            "source": "empty",
        }

    @app.post("/api/v1/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel_job(job_id: str, actor=Depends(current_actor)):
        return job_dict(context.control_plane.cancel_job(actor, job_id))

    @app.post("/api/v1/jobs/{job_id}/pause", response_model=JobResponse)
    def pause_job(job_id: str, actor=Depends(current_actor)):
        return job_dict(context.control_plane.pause_job(actor, job_id))

    @app.post("/api/v1/jobs/{job_id}/resume", response_model=JobResponse)
    def resume_job(job_id: str, actor=Depends(current_actor)):
        return job_dict(context.control_plane.resume_job(actor, job_id))

    @app.post("/api/v1/jobs/terminate-active", response_model=ObjectResponse)
    def terminate_active_jobs(
        scope: str = Query("current", pattern="^(current|global)$"),
        profile: str | None = None,
        kind: str | None = None,
        quick_mode: bool | None = None,
        actor=Depends(current_actor),
    ):
        selected_profile = None if scope == "global" else profile
        return context.control_plane.terminate_active_jobs(
            actor,
            profile=selected_profile,
            kind=kind,
            quick_mode=quick_mode,
        )

    @app.post("/api/v1/jobs/{job_id}/retry", response_model=JobResponse)
    def retry_job(job_id: str, actor=Depends(current_actor)):
        return job_dict(context.control_plane.retry_job(actor, job_id))

    @app.post("/api/v1/jobs/{job_id}/archive", response_model=JobResponse)
    def archive_job(job_id: str, actor=Depends(current_actor)):
        _owned_job(context, actor, job_id)
        return job_dict(context.control_plane.jobs.set_archived(job_id, True))

    @app.post("/api/v1/jobs/{job_id}/restore", response_model=JobResponse)
    def restore_job(job_id: str, actor=Depends(current_actor)):
        _owned_job(context, actor, job_id)
        return job_dict(context.control_plane.jobs.set_archived(job_id, False))

    @app.delete("/api/v1/jobs/{job_id}", response_model=ObjectResponse)
    def purge_job(job_id: str, actor=Depends(current_actor)):
        _owned_job(context, actor, job_id)
        return {"purged": context.control_plane.jobs.purge(job_id)}

    @app.post(
        "/internal/v1/jobs/{job_id}/events",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def worker_event(job_id: str, body: WorkerEventRequest):
        current = context.control_plane.jobs.get(job_id)
        if current is None:
            raise DomainError("JOB_NOT_FOUND", "Job tidak ditemukan.", status_code=404)
        if body.worker and str(body.worker).strip().lower() != current.worker.lower():
            raise DomainError(
                "JOB_WORKER_MISMATCH",
                "Event progress berasal dari worker yang bukan pemilik job.",
                status_code=403,
                details={"job_id": job_id, "worker": current.worker},
            )
        try:
            status = JobStatus(body.status)
        except ValueError as exc:
            raise DomainError(
                "INVALID_JOB_STATUS", "Status job tidak valid.", status_code=422
            ) from exc
        received_at = utc_now()
        progress = dict(body.progress or {})
        latency_ms = None
        if body.sent_at is not None:
            sent_at = body.sent_at
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            latency_ms = max(0.0, (received_at - sent_at).total_seconds() * 1000.0)
        progress["backend_telemetry"] = {
            "worker_sent_at": body.sent_at.isoformat() if body.sent_at else None,
            "backend_received_at": received_at.isoformat(),
            "event_latency_ms": round(latency_ms, 3) if latency_ms is not None else None,
        }
        event = JobEvent(
            job_id=job_id,
            sequence=body.sequence,
            status=status,
            event_type=body.event_type,
            progress=progress,
            result=body.result,
            error=body.error,
            created_at=received_at,
        )
        if body.transient:
            job, accepted = context.control_plane.update_worker_progress_result(event)
        else:
            before = len(context.control_plane.jobs.events(job_id))
            job = context.control_plane.append_worker_event(event)
            accepted = len(context.control_plane.jobs.events(job_id)) > before
        return {"ok": True, "accepted": bool(accepted), "job": job_dict(job)}
