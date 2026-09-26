from __future__ import annotations

import re
from typing import Any

from fastapi import Depends, Query
from fastapi.responses import StreamingResponse

from tme3bot.api.schemas import JobResponse, TtsJobRequest
from tme3bot.domain.models import DomainError

_ARTIFACT_REF = re.compile(r"^[a-f0-9]{48}$")
_ACTIVE = {"queued", "dispatched", "running", "paused"}


def register_tts(app, context, *, current_actor, job_dict, require_internal, require_service):
    @app.post("/api/v1/tts/jobs", response_model=JobResponse)
    def submit_tts(body: TtsJobRequest, actor=Depends(current_actor)):
        title = body.title.strip()
        text = body.text.strip()
        if not title:
            raise DomainError("TTS_TITLE_REQUIRED", "Judul wajib diisi.", status_code=422)
        if not text:
            raise DomainError("TTS_TEXT_REQUIRED", "Teks wajib diisi.", status_code=422)
        readiness = getattr(context.control_plane.jobs, "tts_telegram_ready", None)
        if not callable(readiness) or not readiness():
            raise DomainError(
                "TTS_TELEGRAM_UNAVAILABLE",
                "Layanan Telegram TTS belum siap atau chat tujuan belum dikonfigurasi.",
                status_code=503,
            )
        job = context.control_plane.submit_job(
            actor,
            "tts",
            {"title": title, "text": text},
            profile=actor.profile,
        )
        return job_dict(job)

    @app.post("/api/v1/tts/jobs/{job_id}/retry", response_model=JobResponse)
    def retry_tts(job_id: str, actor=Depends(current_actor)):
        return job_dict(context.control_plane.retry_tts_job(actor, job_id))

    @app.post(
        "/internal/v1/tts/artifacts/ready",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def tts_artifacts_ready(body: dict[str, Any]):
        job_id = str(body.get("job_id") or "")
        job = context.control_plane.jobs.get(job_id)
        if job is None or job.kind != "tts":
            raise DomainError("TTS_JOB_NOT_FOUND", "Job TTS tidak ditemukan.", status_code=404)
        worker = str(body.get("worker") or "").strip().lower()
        if worker != job.worker.lower():
            raise DomainError("JOB_WORKER_MISMATCH", "Artifact berasal dari worker yang bukan pemilik job.", status_code=403)
        if job.status.terminal or job.status.value == "cancelled":
            raise DomainError("TTS_JOB_TERMINAL", "Job TTS sudah tidak menerima artifact.", status_code=409)
        parts = body.get("parts")
        if not isinstance(parts, list) or not parts or len(parts) > 10_000:
            raise DomainError("TTS_ARTIFACTS_INVALID", "Daftar artifact TTS tidak valid.", status_code=422)
        normalized = []
        total = len(parts)
        for expected_index, item in enumerate(parts, start=1):
            if not isinstance(item, dict):
                raise DomainError("TTS_ARTIFACTS_INVALID", "Metadata artifact TTS tidak valid.", status_code=422)
            ref = str(item.get("artifact_ref") or "")
            if not _ARTIFACT_REF.fullmatch(ref):
                raise DomainError("TTS_ARTIFACTS_INVALID", "Referensi artifact TTS tidak valid.", status_code=422)
            try:
                part_index = int(item.get("part_index"))
                total_parts = int(item.get("total_parts"))
                byte_size = int(item.get("byte_size"))
            except (TypeError, ValueError) as exc:
                raise DomainError("TTS_ARTIFACTS_INVALID", "Ukuran artifact TTS tidak valid.", status_code=422) from exc
            if part_index != expected_index or total_parts != total or not 0 < byte_size <= 48_000_000:
                raise DomainError("TTS_ARTIFACTS_INVALID", "Urutan atau ukuran artifact TTS tidak valid.", status_code=422)
            normalized.append({"artifact_ref": ref, "part_index": part_index, "total_parts": total, "byte_size": byte_size})
        count = context.control_plane.jobs.create_tts_deliveries(
            job.id,
            job.worker,
            str(job.payload.get("title") or "Audio TTS"),
            normalized,
        )
        return {"registered_parts": count}

    @app.get(
        "/internal/v1/tts/jobs/{job_id}/delivery",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def tts_delivery_state(job_id: str, worker: str = Query(..., min_length=1, max_length=48)):
        job = context.control_plane.jobs.get(job_id)
        if job is None or job.kind != "tts":
            raise DomainError("TTS_JOB_NOT_FOUND", "Job TTS tidak ditemukan.", status_code=404)
        if worker.strip().lower() != job.worker.lower():
            raise DomainError("JOB_WORKER_MISMATCH", "Worker bukan pemilik job TTS.", status_code=403)
        summary = context.control_plane.jobs.tts_delivery_summary(job_id)
        status = "pending"
        if job.status.value == "cancelled" or summary["cancelled_parts"]:
            status = "cancelled"
        elif job.status.value == "failed":
            status = "failed"
        elif summary["total_parts"] and summary["delivered_parts"] == summary["total_parts"]:
            status = "delivered"
        return {"status": status, **summary}

    @app.post(
        "/internal/v1/tts/jobs/{job_id}/cancel-delivery",
        include_in_schema=False,
        dependencies=[Depends(require_internal)],
    )
    def cancel_tts_delivery(job_id: str, body: dict[str, Any]):
        job = context.control_plane.jobs.get(job_id)
        if job is None or job.kind != "tts":
            raise DomainError("TTS_JOB_NOT_FOUND", "Job TTS tidak ditemukan.", status_code=404)
        if str(body.get("worker") or "").strip().lower() != job.worker.lower():
            raise DomainError("JOB_WORKER_MISMATCH", "Worker bukan pemilik job TTS.", status_code=403)
        context.control_plane.jobs.cancel_tts_deliveries(job_id)
        return {"cancelled": True}

    @app.get(
        "/internal/v1/tts/deliveries/pending",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def pending_tts_deliveries(limit: int = Query(10, ge=1, le=100)):
        return {"items": context.control_plane.jobs.claim_tts_deliveries(limit)}

    @app.post(
        "/internal/v1/tts/telegram-readiness",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def set_tts_telegram_readiness(body: dict[str, Any]):
        ready = body.get("ready")
        if type(ready) is not bool:
            raise DomainError("TTS_READINESS_INVALID", "Status readiness harus boolean.", status_code=422)
        context.control_plane.jobs.set_tts_telegram_ready(ready)
        return {"ready": ready}

    @app.get(
        "/internal/v1/tts/deliveries/{delivery_id}/audio",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def tts_delivery_audio(delivery_id: str):
        item = context.control_plane.jobs.get_tts_delivery(delivery_id)
        if item is None or item.get("status") != "claimed":
            raise DomainError("TTS_DELIVERY_NOT_CLAIMED", "Delivery TTS tidak aktif.", status_code=404)
        job = context.control_plane.jobs.get(str(item["job_id"]))
        if job is None or job.kind != "tts" or job.status.value in {"cancelled", "failed"}:
            raise DomainError("TTS_DELIVERY_CANCELLED", "Delivery TTS sudah dibatalkan.", status_code=409)
        opener = getattr(context.worker_dispatcher, "open_tts_artifact", None)
        if not callable(opener):
            raise DomainError("WORKER_INCOMPATIBLE", "Backend belum dapat mengambil audio dari worker.", status_code=409)
        try:
            upstream = opener(str(item["worker"]), job.id, str(item["artifact_ref"]))
        except Exception as exc:
            raise DomainError("TTS_ARTIFACT_UNAVAILABLE", "Audio TTS dari worker belum tersedia.", status_code=502) from exc

        def chunks():
            try:
                while True:
                    chunk = upstream.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                upstream.close()

        headers = {
            "Content-Length": str(int(item["byte_size"])),
            "Content-Disposition": f'attachment; filename="audio-{job.id[:8]}-{int(item["part_index"])}.mp3"',
            "Cache-Control": "no-store",
        }
        return StreamingResponse(chunks(), media_type="audio/mpeg", headers=headers)

    @app.patch(
        "/internal/v1/tts/deliveries/{delivery_id}",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def complete_tts_delivery(delivery_id: str, body: dict[str, Any]):
        delivered = body.get("delivered")
        if type(delivered) is not bool:
            raise DomainError("TTS_DELIVERY_RESULT_INVALID", "Hasil delivery harus boolean.", status_code=422)
        item = context.control_plane.jobs.get_tts_delivery(delivery_id)
        if item is None:
            raise DomainError("TTS_DELIVERY_NOT_FOUND", "Delivery TTS tidak ditemukan.", status_code=404)
        job = context.control_plane.jobs.get(str(item["job_id"]))
        if job is None or job.status.value == "cancelled":
            context.control_plane.jobs.cancel_tts_deliveries(str(item["job_id"]))
            return {"status": "cancelled"}
        updated = context.control_plane.jobs.complete_tts_delivery(delivery_id, delivered=delivered)
        return {"status": str(updated.get("status") if updated else "missing")}
