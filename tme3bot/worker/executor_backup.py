from __future__ import annotations

from contextlib import (
    ExitStack,
)
import time
from tme3bot.backup_service import (
    BackupService,
    sha256_file,
)
from tme3bot.progress_reporter import (
    ProgressReporter,
)
from typing import (
    Any,
)

from .executor_support import (
    LOGGER,
    _has_transfer_telemetry,
)
from .telegram_upload_verification import TelegramUploadBatchVerifier

class BackupExecutorMixin:

    def _backup(self, command: dict[str, Any]) -> dict[str, Any]:
        payload = command["payload"]
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        profiles = sorted(self.profile_manager.list_profiles())
        runtimes = [self.profile_manager.runtime(profile) for profile in profiles]

        def backup_progress(value: dict[str, Any]) -> None:
            percent = value.get("percent")
            reporter.report(
                phase=str(value.get("phase") or "staging"),
                message=str(value.get("message") or "Menyiapkan backup"),
                overall={
                    "current": value.get("files_current"),
                    "total": value.get("files_total"),
                    "percent": percent,
                    "unit": "files",
                    "bytes_total": value.get("bytes_total"),
                },
                transfer={
                    "eta_seconds": value.get("eta_seconds"),
                    "elapsed_seconds": value.get("elapsed_seconds"),
                },
                indeterminate=bool(value.get("indeterminate", percent is None)),
                force=str(value.get("phase")) == "staging" or percent == 100,
            )

        with ExitStack() as locks:
            for runtime in runtimes:
                locks.enter_context(runtime.export_operation_lock)
                locks.enter_context(runtime.download_operation_lock)
            backup_service = BackupService(
                self.config,
                progress_callback=backup_progress,
                command_callback=self._command_callback(
                    profile=profiles[0] if profiles else None,
                    runtime="backup_compress",
                ),
            )
            job_id = str(command["job_id"])
            with self._lock:
                self._backup_services[job_id] = backup_service
            try:
                archive = backup_service.create_archive(
                    str(payload["backup_run_id"]),
                    str(payload["node_name"]),
                    password=str(payload["password"]),
                    volume_size=str(payload.get("volume_size") or self.config.backup_volume_size),
                )
            finally:
                with self._lock:
                    if self._backup_services.get(job_id) is backup_service:
                        self._backup_services.pop(job_id, None)
        if not runtimes:
            raise RuntimeError("Tidak ada profile runtime untuk upload backup.")
        uploader = runtimes[0].export_tdl_client
        uploader_runtime = runtimes[0]
        uploader_profile = profiles[0]
        verifier_factory = getattr(self, "_telegram_upload_verifier", None)
        verifier = (
            verifier_factory(str(command["job_id"]))
            if callable(verifier_factory)
            else TelegramUploadBatchVerifier.for_profile_manager(self.profile_manager)
        )
        part_sizes = {part: part.stat().st_size for part in archive.parts}
        total_bytes = sum(part_sizes.values())
        completed_bytes = 0
        sent = 0
        pending_verifications: list[tuple[dict[str, Any], Any, int, int]] = []

        def publish_verified_part(part_payload: dict[str, Any], index: int, size: int) -> None:
            nonlocal sent, completed_bytes
            sent += 1
            completed_bytes += size
            progress_payload = reporter.report(
                phase="uploading_parts",
                message=f"{part_payload['part_name']} terverifikasi di Telegram",
                overall={
                    "current": sent,
                    "total": len(archive.parts),
                    "percent": completed_bytes * 100 / total_bytes if total_bytes else 100,
                    "unit": "parts",
                    "bytes_current": completed_bytes,
                    "bytes_total": total_bytes,
                },
                item={
                    "name": part_payload["part_name"],
                    "index": index,
                    "total": len(archive.parts),
                    "size_bytes": size,
                    "percent": 100,
                },
                counters={"succeeded": sent},
                force=True,
            )
            reporter.milestone(
                "backup.part_uploaded",
                progress=progress_payload,
                result={"part": part_payload},
            )

        with self._capture_tdl_output(uploader):
            for index, part in enumerate(archive.parts, start=1):
                size = part_sizes[part]
                upload_state = {"phase": "uploading"}
                reporter.reset_transfer()
                reporter.report(
                    phase="verifying",
                    message=f"Memverifikasi {part.name}",
                    overall={
                        "current": sent,
                        "total": len(archive.parts),
                        "unit": "parts",
                    },
                    item={
                        "name": part.name,
                        "index": index,
                        "total": len(archive.parts),
                        "size_bytes": size,
                    },
                    counters={"succeeded": sent},
                    indeterminate=True,
                    force=True,
                )
                digest, size = sha256_file(part)

                def part_progress(progress) -> None:
                    if (
                        upload_state["phase"] != "uploading"
                        or not _has_transfer_telemetry(progress)
                    ):
                        return
                    transfer = reporter.tdl_transfer(progress, total_bytes=size)
                    current_bytes = int(transfer.get("bytes_current") or 0)
                    overall_bytes = min(total_bytes, completed_bytes + current_bytes)
                    reporter.report(
                        phase="uploading_parts",
                        message=f"Mengupload {part.name}",
                        overall={
                            "current": sent,
                            "total": len(archive.parts),
                            "percent": (
                                overall_bytes * 100 / total_bytes
                                if total_bytes
                                else None
                            ),
                            "unit": "parts",
                            "bytes_current": overall_bytes,
                            "bytes_total": total_bytes,
                        },
                        item={
                            "name": part.name,
                            "index": index,
                            "total": len(archive.parts),
                            "size_bytes": size,
                            "percent": progress.percent,
                        },
                        transfer=transfer,
                        counters={"succeeded": sent},
                        indeterminate=progress.percent is None,
                    )

                def part_phase(phase: str) -> None:
                    upload_state["phase"] = phase

                caption = (
                    f"Backup node={payload['node_name']} "
                    f"run={str(payload['backup_run_id'])[:12]}\nPart: {part.name}"
                )
                with uploader_runtime.export_operation_lock:
                    with self._capture_tdl_progress(uploader, part_progress):
                        uploader.upload(
                            part,
                            str(payload["channel_ref"]),
                            caption,
                            status_callback=part_phase,
                        )
                uploaded_at = time.time()
                verification = verifier.record_upload(
                    profile=uploader_profile,
                    chat_ref=str(payload["channel_ref"]),
                    filename=part.name,
                    caption=caption,
                    uploaded_at=uploaded_at,
                )
                part_payload = {
                    "run_id": str(payload["backup_run_id"]),
                    "node_name": str(payload["node_name"]),
                    "part_name": part.name,
                    "channel_id": int(payload["channel_id"]),
                    "channel_message_id": verification.message_id,
                    "file_size": size,
                    "sha256": digest,
                    "uploaded_at": archive.created_at,
                    "status": "active",
                }
                if verification.status == "verified" and verification.message_id is not None:
                    publish_verified_part(part_payload, index, size)
                else:
                    part_payload.pop("channel_message_id", None)
                    pending_verifications.append((part_payload, verification, index, size))
                    reporter.report(
                        phase="verifying",
                        message=f"Menunggu verifikasi Telegram untuk {part.name}",
                        overall={
                            "current": sent,
                            "total": len(archive.parts),
                            "unit": "parts",
                        },
                        item={
                            "name": part.name,
                            "index": index,
                            "total": len(archive.parts),
                            "size_bytes": size,
                            "percent": 100,
                        },
                        counters={"succeeded": sent},
                        indeterminate=True,
                        force=True,
                    )
        if pending_verifications:
            verifier.finalize()
            unresolved: list[str] = []
            for part_payload, verification, index, size in pending_verifications:
                if verification.status == "verified" and verification.message_id is not None:
                    part_payload["channel_message_id"] = verification.message_id
                    publish_verified_part(part_payload, index, size)
                else:
                    unresolved.append(str(part_payload["part_name"]))
            if unresolved:
                reporter.report(
                    phase="needs_reconciliation",
                    message=f"{len(unresolved)} part backup belum terverifikasi; arsip lokal dipertahankan",
                    overall={
                        "current": sent + len(unresolved),
                        "total": len(archive.parts),
                        "unit": "parts",
                    },
                    counters={"succeeded": sent, "ambiguous": len(unresolved)},
                    force=True,
                )
                raise RuntimeError(
                    "Sebagian part backup belum ditemukan dengan nama lampiran dan caption yang sama pada ekspor waktu."
                )
        reporter.report(
            phase="completed",
            message=f"Backup selesai: {sent} part tersimpan",
            overall={
                "current": sent,
                "total": len(archive.parts),
                "percent": 100,
                "unit": "parts",
                "bytes_current": total_bytes,
                "bytes_total": total_bytes,
            },
            counters={"succeeded": sent},
            force=True,
        )
        for part in archive.parts:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("Could not remove backup staging %s", part)
        return {"parts": sent, "run_id": payload["backup_run_id"]}
