from __future__ import annotations

import logging
import re
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tme3bot.domain.models import utc_now
from tme3bot.infrastructure.http_client import request_json
from tme3bot.worker.tts_pipeline import TtsCancelled, TtsError, TtsPipeline

LOGGER = logging.getLogger(__name__)
_SAFE_JOB = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_SAFE_ARTIFACT = re.compile(r"^[a-f0-9]{48}$")


class TtsExecutorMixin:
    def _tts_pipeline(self) -> TtsPipeline:
        settings = self.runtime_settings.tts_settings()
        return TtsPipeline.from_config(SimpleNamespace(**settings))

    def _tts_artifact_directory(self, job_id: str) -> Path:
        if not _SAFE_JOB.fullmatch(job_id):
            raise TtsError("ID job tidak valid")
        return Path(self.config.tts_data_root).resolve() / job_id

    def tts_artifact_path(self, job_id: str, artifact_ref: str) -> Path | None:
        if not _SAFE_ARTIFACT.fullmatch(str(artifact_ref)):
            return None
        root = Path(self.config.tts_data_root).resolve()
        candidate = (self._tts_artifact_directory(job_id) / f"artifact-{artifact_ref}.mp3").resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def delete_tts_artifacts(self, job_id: str) -> bool:
        root = self._tts_artifact_directory(job_id)
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        return not root.exists()

    def _tts(self, command: dict[str, Any]) -> dict[str, Any]:
        job_id = str(command["job_id"])
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        title = str(payload.get("title") or "Audio TTS").strip()[:200] or "Audio TTS"
        text = str(payload.get("text") or "")
        worker_name = str(command.get("worker") or self.config.backup_node_name)
        root = self._tts_artifact_directory(job_id)
        pipeline = self._tts_pipeline()
        if not pipeline.ready():
            raise TtsError("Tiga helper TTS dan tiga jalur Tor harus siap")
        pause_event = self._pause_events.setdefault(job_id, threading.Event())
        last_phase = {"value": "starting"}

        def emit(event: dict[str, Any]) -> None:
            phase = str(event.get("phase") or "synthesizing")
            current = int(event.get("current") or 0)
            total = int(event.get("total") or 0)
            progress = {
                "phase": phase,
                "message": {
                    "synthesizing": "Membuat audio",
                    "merging": "Menggabungkan audio",
                    "telegram_delivery": "Mengirim audio lewat TDL",
                }.get(phase, "Memproses TTS"),
                "character_count": len(text),
                "part_count": total,
                "parts_completed": current,
                "item": {
                    "index": int(event.get("part") or current),
                    "total": total,
                    "percent": round(current * 100 / total, 1) if total else 0,
                },
                "overall": {
                    "current": current,
                    "total": total,
                    "percent": round(current * 100 / total, 1) if total else 0,
                    "unit": "bagian",
                },
                "indeterminate": not bool(total),
            }
            changed = last_phase["value"] != phase
            last_phase["value"] = phase
            self.publisher.emit(
                job_id,
                "running",
                "tts.phase" if changed else "progress.snapshot",
                progress=progress,
                transient=not changed,
            )
            self._append_job_log(
                f"[TTS] fase={phase} bagian={current}/{total} karakter={len(text)}"
            )

        def publish_paused() -> None:
            phase = last_phase["value"]
            self.publisher.emit(
                job_id,
                "paused",
                "paused",
                progress={
                    "phase": phase,
                    "paused_phase": phase,
                    "pause_kind": "worker",
                    "character_count": len(text),
                    "message": "TTS dijeda setelah batch selesai",
                },
            )
            self._append_job_log("[TTS] pause aktif setelah batch selesai")

        try:
            emit({"phase": "synthesizing", "current": 0, "total": 0})
            result = pipeline.synthesize(
                job_id,
                text,
                root,
                on_progress=emit,
                pause_event=pause_event,
                is_cancelled=lambda: job_id in self._cancel_requested,
                on_paused=publish_paused,
            )
            self._append_job_log(
                f"[TTS] sintesis selesai bagian={result['part_count']} karakter={result['character_count']}"
            )
            registration = request_json(
                self.config.backend_api_url,
                self.config.backend_internal_token,
                "POST",
                "/internal/v1/tts/artifacts/ready",
                {
                    "job_id": job_id,
                    "title": title,
                    "worker": worker_name,
                    "parts": [
                        {
                            "artifact_ref": item["artifact_ref"],
                            "part_index": item["part_index"],
                            "total_parts": item["total_parts"],
                            "byte_size": item["byte_size"],
                        }
                        for item in result["artifacts"]
                    ],
                },
                timeout=30,
            )
            target_chat = str(registration.get("chat_ref") or "").strip()
            if not target_chat:
                raise TtsError("Chat tujuan TDL TTS belum dikonfigurasi")
            # The destination is an internal setting. Keep it available to
            # command-audit redaction without publishing it in progress/log
            # payloads.
            secrets = getattr(self._job_log, "secrets", None)
            if isinstance(secrets, list) and target_chat not in secrets:
                secrets.append(target_chat)
            runtime = self.profile_manager.runtime(str(command["profile"]))
            tdl_client = runtime.export_tdl_client
            self._append_job_log(
                f"[TTS] mengirim lewat TDL profile={runtime.name} parts={len(result['artifacts'])}"
            )
            while True:
                if job_id in self._cancel_requested:
                    request_json(
                        self.config.backend_api_url,
                        self.config.backend_internal_token,
                        "POST",
                        f"/internal/v1/tts/jobs/{job_id}/cancel-delivery",
                        {"worker": worker_name},
                        timeout=10,
                    )
                    raise TtsCancelled("Job TTS dibatalkan")
                if pause_event.is_set():
                    publish_paused()
                    self._wait_if_paused(job_id)
                pending = request_json(
                    self.config.backend_api_url,
                    self.config.backend_internal_token,
                    "GET",
                    f"/internal/v1/tts/deliveries/worker-pending?worker={worker_name}&job_id={job_id}&limit=1",
                    timeout=10,
                )
                items = pending.get("items") if isinstance(pending, dict) else []
                if isinstance(items, list) and items:
                    item = items[0] if isinstance(items[0], dict) else {}
                    delivery_id = str(item.get("id") or "")
                    artifact_ref = str(item.get("artifact_ref") or "")
                    artifact_path = self.tts_artifact_path(job_id, artifact_ref)
                    part_index = int(item.get("part_index") or 1)
                    total_parts = int(item.get("total_parts") or len(result["artifacts"]))
                    if not delivery_id or artifact_path is None:
                        if delivery_id:
                            request_json(
                                self.config.backend_api_url,
                                self.config.backend_internal_token,
                                "PATCH",
                                f"/internal/v1/tts/deliveries/{delivery_id}/worker-result",
                                {"worker": worker_name, "delivered": False},
                                timeout=10,
                            )
                        raise TtsError("Artifact TTS tidak tersedia untuk pengiriman")
                    if job_id in self._cancel_requested:
                        request_json(
                            self.config.backend_api_url,
                            self.config.backend_internal_token,
                            "POST",
                            f"/internal/v1/tts/jobs/{job_id}/cancel-delivery",
                            {"worker": worker_name},
                            timeout=10,
                        )
                        raise TtsCancelled("Job TTS dibatalkan")
                    caption = title if total_parts == 1 else f"{title} ({part_index}/{total_parts})"
                    try:
                        self._append_job_log(
                            f"[TTS] upload TDL bagian={part_index}/{total_parts}"
                        )
                        with runtime.export_operation_lock:
                            tdl_client.upload(
                                artifact_path,
                                target_chat,
                                caption,
                            )
                    except Exception as exc:
                        try:
                            request_json(
                                self.config.backend_api_url,
                                self.config.backend_internal_token,
                                "PATCH",
                                f"/internal/v1/tts/deliveries/{delivery_id}/worker-result",
                                {"worker": worker_name, "delivered": False},
                                timeout=10,
                            )
                        except Exception:
                            LOGGER.warning(
                                "Could not persist failed TDL delivery job=%s part=%s",
                                job_id[:8],
                                part_index,
                            )
                        raise TtsError(f"Pengiriman TDL gagal ({type(exc).__name__})") from None
                    request_json(
                        self.config.backend_api_url,
                        self.config.backend_internal_token,
                        "PATCH",
                        f"/internal/v1/tts/deliveries/{delivery_id}/worker-result",
                        {"worker": worker_name, "delivered": True},
                        timeout=10,
                    )
                    state = request_json(
                        self.config.backend_api_url,
                        self.config.backend_internal_token,
                        "GET",
                        f"/internal/v1/tts/jobs/{job_id}/delivery?worker={worker_name}",
                        timeout=10,
                    )
                    delivered = int(state.get("delivered_parts") or 0)
                    total = int(state.get("total_parts") or len(result["artifacts"]))
                    emit({"phase": "telegram_delivery", "current": delivered, "total": total})
                    if state.get("status") == "delivered":
                        self._append_job_log("[TTS] seluruh bagian terkirim lewat TDL")
                        self.delete_tts_artifacts(job_id)
                        return {
                            "title": title,
                            "character_count": result["character_count"],
                            "part_count": result["part_count"],
                            "delivered_parts": delivered,
                        }
                    continue
                state = request_json(
                    self.config.backend_api_url,
                    self.config.backend_internal_token,
                    "GET",
                    f"/internal/v1/tts/jobs/{job_id}/delivery?worker={worker_name}",
                    timeout=10,
                )
                if state.get("status") == "delivered":
                    self._append_job_log("[TTS] seluruh bagian terkirim lewat TDL")
                    self.delete_tts_artifacts(job_id)
                    return {
                        "title": title,
                        "character_count": result["character_count"],
                        "part_count": result["part_count"],
                        "delivered_parts": int(state.get("delivered_parts") or len(result["artifacts"])),
                    }
                if state.get("status") in {"cancelled", "failed"}:
                    raise TtsCancelled("Job TTS dibatalkan") if state.get("status") == "cancelled" else TtsError("Delivery TTS gagal")
                delivered = int(state.get("delivered_parts") or 0)
                total = int(state.get("total_parts") or len(result["artifacts"]))
                emit({"phase": "telegram_delivery", "current": delivered, "total": total})
                time.sleep(3.0)
        except TtsCancelled:
            self.delete_tts_artifacts(job_id)
            raise
        except TtsError:
            raise
        except Exception as exc:
            LOGGER.warning(
                "TTS job failed job=%s error_type=%s",
                job_id[:8],
                type(exc).__name__,
            )
            # Filesystem and transport exceptions can contain local paths or
            # response bodies; keep those details out of public job errors.
            raise TtsError(f"Proses TTS gagal ({type(exc).__name__})") from None
