from __future__ import annotations

import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

from tme3bot.domain.models import utc_now
from tme3bot.infrastructure.http_client import request_json
from tme3bot.worker.tts_pipeline import TtsCancelled, TtsError, TtsPipeline

LOGGER = logging.getLogger(__name__)
_SAFE_JOB = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_SAFE_ARTIFACT = re.compile(r"^[a-f0-9]{48}$")


class TtsExecutorMixin:
    def _tts_pipeline(self) -> TtsPipeline:
        return TtsPipeline.from_config(self.config)

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
                    "telegram_delivery": "Mengirim audio ke Telegram",
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
            request_json(
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
            self._append_job_log(f"[TTS] menunggu konfirmasi delivery parts={len(result['artifacts'])}")
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
                state = request_json(
                    self.config.backend_api_url,
                    self.config.backend_internal_token,
                    "GET",
                    f"/internal/v1/tts/jobs/{job_id}/delivery?worker={worker_name}",
                    timeout=10,
                )
                if state.get("status") == "delivered":
                    self._append_job_log("[TTS] seluruh bagian diterima Telegram")
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
