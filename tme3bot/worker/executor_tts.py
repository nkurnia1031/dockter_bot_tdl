from __future__ import annotations

import logging
import re
import shutil
import threading
import time
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tme3bot.domain.models import utc_now
from tme3bot.infrastructure.http_client import request_json
from tme3bot.worker.tts_pipeline import TtsCancelled, TtsError, TtsPipeline

LOGGER = logging.getLogger(__name__)
_SAFE_JOB = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_SAFE_ARTIFACT = re.compile(r"^[a-f0-9]{48}$")
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _truncate_utf8(value: str, max_bytes: int) -> str:
    output: list[str] = []
    used = 0
    for char in value:
        size = len(char.encode("utf-8"))
        if used + size > max_bytes:
            break
        output.append(char)
        used += size
    return "".join(output)


def tts_delivery_filename(title: str, part_index: int, total_parts: int) -> str:
    """Build a portable audio filename from the user-visible TTS title."""
    stem = unicodedata.normalize("NFC", str(title or "")).strip()
    stem = _UNSAFE_FILENAME.sub("_", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    if stem.lower().endswith(".mp3"):
        stem = stem[:-4].rstrip(" .")
    part = f" ({int(part_index)} of {int(total_parts)})" if int(total_parts) > 1 else ""
    suffix = f"{part}.mp3"
    stem = _truncate_utf8(stem, 220 - len(suffix.encode("utf-8"))).rstrip(" .")
    if not stem:
        stem = "Audio TTS"
    if stem.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return f"{stem}{suffix}"


class TtsExecutorMixin:
    def _tts_pipeline(self) -> TtsPipeline:
        settings = self.runtime_settings.tts_settings()
        return TtsPipeline.from_config(SimpleNamespace(**settings))

    def tts_health(self) -> dict[str, Any]:
        pipeline = self._tts_pipeline()
        health = pipeline.diagnostics()
        available_profiles = self.available_storage_profiles()
        profile_sync = getattr(self, "profile_sync", None)
        sync_enabled = bool(getattr(profile_sync, "enabled", False))
        ready_profiles = available_profiles
        if sync_enabled:
            ready_profiles = [
                profile for profile in available_profiles
                if profile_sync.profile_ready(profile)
            ]
        helpers = health.get("helpers")
        helpers_ready = bool(health.get("helpers_ready")) and isinstance(helpers, list) and len(helpers) == 3 and all(
            isinstance(item, dict) and item.get("status") == "ready" for item in helpers
        )
        health["helpers_ready"] = helpers_ready
        health["available_profiles"] = available_profiles
        health["tts_profiles"] = ready_profiles
        health["profile_sync_enabled"] = sync_enabled
        health["ready"] = helpers_ready and bool(ready_profiles)
        return health

    def recover_tts_helper(self, slot: int) -> dict[str, Any]:
        return self._tts_pipeline().recover_helper(slot)

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

    @staticmethod
    def _prepare_tts_upload_file(
        artifact_path: Path, title: str, part_index: int, total_parts: int
    ) -> Path:
        """Keep the opaque artifact for retries, and upload a title-named copy."""
        outgoing = artifact_path.parent / "outgoing"
        outgoing.mkdir(parents=True, exist_ok=True)
        target = outgoing / tts_delivery_filename(title, part_index, total_parts)
        try:
            shutil.copyfile(artifact_path, target)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target

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
                        upload_path = self._prepare_tts_upload_file(
                            artifact_path, title, part_index, total_parts
                        )
                        try:
                            with runtime.export_operation_lock:
                                tdl_client.upload(
                                    upload_path,
                                    target_chat,
                                    caption,
                                )
                        finally:
                            upload_path.unlink(missing_ok=True)
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
