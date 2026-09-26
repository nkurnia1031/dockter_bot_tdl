from __future__ import annotations

import mimetypes
import uuid
from pathlib import (
    Path,
)
from tme3bot.progress_reporter import (
    ProgressReporter,
)
from tme3bot.rclone import (
    RcloneRunner,
)
from tme3bot.storage_catalog import (
    build_storage_caption,
)
from tme3bot.worker.quick_export import (
    QuickModeError,
)
from typing import (
    Any,
)

from .executor_support import (
    LOGGER,
    _has_transfer_telemetry,
    storage_logical_folder,
    storage_relative_folders,
)

class StorageExecutorMixin:

    def _rclone_upload_files(
        self,
        command: dict[str, Any],
        files: list[Path],
        destination: str,
        reporter: ProgressReporter,
        remote_names: list[str] | None = None,
    ) -> dict[str, object]:
        """Upload workspace files through the worker-local rclone config."""
        job_id = str(command["job_id"])
        workspace = self._quick_workspace(self.config)
        config_path = Path(
            getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")
        ).resolve()
        config_root = Path(getattr(self.config, "profile_root", "/data")).resolve()

        def progress(index: int, total: int, name: str) -> None:
            # A telemetry outage must not turn an already completed remote
            # copy into a false physical upload failure.
            try:
                reporter.report(
                    phase="uploading",
                    message=f"Mengupload {name} ke Google Drive",
                    overall={
                        "current": index,
                        "total": total,
                        "percent": index * 100 / total if total else 100,
                        "unit": "files",
                    },
                    item={
                        "name": name,
                        "index": index,
                        "total": total,
                        "percent": 100,
                    },
                    counters={"succeeded": index, "failed": 0},
                    force=True,
                )
            except Exception:
                LOGGER.warning(
                    "Could not publish rclone progress for %s", job_id, exc_info=True
                )

        def cancelled() -> bool:
            with self._lock:
                return job_id in self._cancel_requested

        runner = RcloneRunner(
            log_callback=self._append_job_log,
            command_callback=self._command_callback(),
            progress_callback=progress,
            cancel_check=cancelled,
            stall_timeout_seconds=getattr(
                self.config, "job_stall_timeout_seconds", 600
            ),
        )
        with self._lock:
            self._rclone_runners[job_id] = runner
        try:
            kwargs = {"remote_names": remote_names} if remote_names is not None else {}
            return runner.copy_files(
                files,
                destination,
                config_path,
                workspace_root=workspace,
                config_root=config_root,
                **kwargs,
            )
        finally:
            with self._lock:
                self._rclone_runners.pop(job_id, None)

    def _storage_upload(
        self,
        command: dict[str, Any],
        *,
        upload_item_callback=None,
    ) -> dict[str, Any]:
        payload = command["payload"]
        storage_profile = getattr(self.config, "worker_storage_profile", "storage")
        if storage_profile not in self.profile_manager.list_profiles():
            raise ValueError(
                f"STORAGE_PROFILE_UNAVAILABLE: profile worker {storage_profile} belum memiliki sesi TDL."
            )
        runtime = self.profile_manager.runtime(storage_profile)
        if not Path(runtime.config.tdl_export_storage).exists():
            raise ValueError(
                f"STORAGE_PROFILE_UNAVAILABLE: sesi TDL {storage_profile} belum tersedia."
            )
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        reporter.report(
            phase="scanning",
            message="Memindai file dalam folder storage",
            indeterminate=True,
            force=True,
        )
        root = self._workspace_path(str(payload["folder_path"]))
        if not root.is_dir():
            raise ValueError(f"Folder storage tidak ditemukan: {root}")
        allowed_names = {
            str(item) for item in (payload.get("allowed_names") or []) if str(item)
        }
        photo_names = {
            str(item) for item in (payload.get("photo_names") or []) if str(item)
        }
        if bool(payload.get("root_files_only")):
            files = sorted(
                path
                for path in root.iterdir()
                if path.is_file() and (not allowed_names or path.name in allowed_names)
            )
        else:
            files = sorted(path for path in root.rglob("*") if path.is_file())
        preserve_structure = bool(payload.get("preserve_structure", True))
        if preserve_structure:
            for relative in storage_relative_folders(root):
                self.publisher.emit(
                    str(command["job_id"]),
                    "running",
                    "storage.folder_discovered",
                    result={
                        "destination_folder_id": payload.get("destination_folder_id"),
                        "relative_path": relative,
                        "owner_user_id": int(payload["owner_user_id"]),
                    },
                )
        if not files:
            reporter.report(
                phase="registering",
                message="Struktur folder kosong selesai dibuat",
                overall={"current": 0, "total": 0, "unit": "files", "percent": 100},
                counters={"succeeded": 0, "failed": 0},
                force=True,
            )
            return {
                "status": "uploaded",
                "batch_id": payload["batch_id"],
                "succeeded": 0,
                "failed": [],
                "total": 0,
                "rclone_upload": bool(payload.get("rclone_upload")),
                "rclone_uploaded": 0,
            }
        file_sizes = {path: path.stat().st_size for path in files}
        total_bytes = sum(file_sizes.values())
        failed, succeeded = [], 0
        uploaded_items: list[dict[str, Any]] = []
        completed_bytes = 0
        last_message_id: int | None = None
        rclone_result: dict[str, object] | None = None
        reporter.milestone(
            "phase_changed",
            progress=reporter.report(
                phase="uploading",
                message=f"Siap mengupload {len(files)} file",
                overall={
                    "current": 0,
                    "total": len(files),
                    "percent": 0,
                    "unit": "files",
                    "bytes_current": 0,
                    "bytes_total": total_bytes,
                },
                counters={"succeeded": 0, "failed": 0},
                force=True,
            ),
        )
        with runtime.export_operation_lock:
            with self._capture_tdl_output(runtime.export_tdl_client):
                for index, path in enumerate(files, start=1):
                    with self._lock:
                        if str(command["job_id"]) in self._cancel_requested:
                            raise QuickModeError("Upload dibatalkan oleh user.")
                    size = file_sizes[path]
                    upload_state = {"phase": "uploading"}
                    reporter.reset_transfer()

                    def upload_progress(progress) -> None:
                        if (
                            upload_state["phase"] != "uploading"
                            or not _has_transfer_telemetry(progress)
                        ):
                            return
                        transfer = reporter.tdl_transfer(progress, total_bytes=size)
                        current_bytes = int(transfer.get("bytes_current") or 0)
                        overall_bytes = min(total_bytes, completed_bytes + current_bytes)
                        reporter.report(
                            phase="uploading",
                            message=f"Mengupload {path.name}",
                            overall={
                                "current": index - 1,
                                "total": len(files),
                                "percent": (
                                    overall_bytes * 100 / total_bytes
                                    if total_bytes
                                    else None
                                ),
                                "unit": "files",
                                "bytes_current": overall_bytes,
                                "bytes_total": total_bytes,
                            },
                            item={
                                "name": path.name,
                                "index": index,
                                "total": len(files),
                                "size_bytes": size,
                                "percent": progress.percent,
                            },
                            transfer=transfer,
                            counters={
                                "succeeded": succeeded,
                                "failed": len(failed),
                            },
                            indeterminate=progress.percent is None,
                        )

                    def upload_phase(phase: str) -> None:
                        upload_state["phase"] = phase
                        if phase == "resolving_message":
                            reporter.report(
                                phase=phase,
                                message=f"Menunggu konfirmasi Telegram untuk {path.name}",
                                overall={
                                    "current": index - 1,
                                    "total": len(files),
                                    "unit": "files",
                                },
                                item={
                                    "name": path.name,
                                    "index": index,
                                    "total": len(files),
                                    "size_bytes": size,
                                    "percent": 100,
                                },
                                counters={
                                    "succeeded": succeeded,
                                    "failed": len(failed),
                                },
                                indeterminate=True,
                                force=True,
                            )

                    try:
                        physical_upload_succeeded = False
                        counted_success = False
                        base_folder = str(
                            payload.get("destination_folder_path")
                            or payload.get("folder")
                            or ""
                        )
                        logical_folder, relative_parent = storage_logical_folder(
                            root, path, base_folder, preserve_structure
                        )
                        upload_id = str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"tme3bot:{payload['batch_id']}:{path.relative_to(root)}",
                            )
                        )
                        caption_override = bool(payload.get("caption_override"))
                        caption = (
                            str(payload.get("caption") or "")
                            if caption_override
                            else build_storage_caption(
                                logical_folder, path.name, str(payload.get("keywords", ""))
                            )
                        )
                        if not caption:
                            caption = build_storage_caption(
                                logical_folder, path.name, str(payload.get("keywords", ""))
                            )
                        reporter.report(
                            phase="uploading",
                            message=f"Mengupload {path.name}",
                            overall={
                                "current": index - 1,
                                "total": len(files),
                                "unit": "files",
                            },
                            item={
                                "name": path.name,
                                "index": index,
                                "total": len(files),
                                "size_bytes": size,
                                "percent": 0,
                            },
                            counters={
                                "succeeded": succeeded,
                                "failed": len(failed),
                            },
                            force=True,
                        )
                        with self._capture_tdl_progress(
                            runtime.export_tdl_client, upload_progress
                        ):
                            upload_kwargs = {"status_callback": upload_phase}
                            if last_message_id is not None:
                                # TDL can finish an upload before it reports the
                                # channel message ID.  Quick Mode intentionally
                                # uses the same caption for every file, so the
                                # delayed resolver must start after the message
                                # uploaded immediately before this one.
                                upload_kwargs["resolve_after_id"] = last_message_id
                            if path.name in photo_names:
                                upload_kwargs["as_photo"] = True
                            result = runtime.export_tdl_client.upload(
                                path,
                                runtime.config.storage_channel_ref,
                                caption,
                                **upload_kwargs,
                            )
                        # Telegram has accepted the file.  Failures while
                        # hashing, publishing progress, or registering the
                        # catalog event must not turn that physical upload
                        # into a false failed file.
                        physical_upload_succeeded = True
                        last_message_id = int(result.message_id)
                        reporter.report(
                            phase="hashing",
                            message=f"Memverifikasi {path.name}",
                            overall={
                                "current": index - 1,
                                "total": len(files),
                                "unit": "files",
                            },
                            item={
                                "name": path.name,
                                "index": index,
                                "total": len(files),
                                "size_bytes": size,
                                "percent": 100,
                            },
                            counters={
                                "succeeded": succeeded,
                                "failed": len(failed),
                            },
                            indeterminate=True,
                            force=True,
                        )
                        digest, size = self._digest(path)
                        item = {
                            "upload_id": upload_id,
                            "owner_user_id": int(payload["owner_user_id"]),
                            "owner_profile": str(payload["owner_profile"]),
                            "channel_id": runtime.config.storage_channel_id,
                            "channel_message_id": result.message_id,
                            "original_name": path.name,
                            "display_name": path.name,
                            "folder": logical_folder,
                            "folder_id": payload.get("destination_folder_id"),
                            "relative_folder": relative_parent,
                            "keywords": str(payload.get("keywords", "")),
                            "caption": caption,
                            "caption_override": caption_override,
                            "file_size": size,
                            "mime_type": mimetypes.guess_type(path.name)[0] or "",
                            "sha256": digest,
                            "status": "active",
                            "uploaded_at": None,
                        }
                        uploaded_items.append(dict(item))
                        if upload_item_callback is not None:
                            try:
                                upload_item_callback(list(uploaded_items))
                            except Exception:
                                LOGGER.warning(
                                    "Storage upload evidence callback failed for %s",
                                    path,
                                    exc_info=True,
                                )
                        succeeded += 1
                        counted_success = True
                        completed_bytes += file_sizes[path]
                        progress_payload = reporter.report(
                            phase="registering",
                            message=f"{path.name} selesai diupload",
                            overall={
                                "current": index,
                                "total": len(files),
                                "percent": (
                                    completed_bytes * 100 / total_bytes
                                    if total_bytes
                                    else 100
                                ),
                                "unit": "files",
                                "bytes_current": completed_bytes,
                                "bytes_total": total_bytes,
                            },
                            item={
                                "name": path.name,
                                "index": index,
                                "total": len(files),
                                "size_bytes": size,
                                "percent": 100,
                            },
                            counters={
                                "succeeded": succeeded,
                                "failed": len(failed),
                            },
                            force=True,
                        )
                        reporter.milestone(
                            "storage.item_uploaded",
                            progress=progress_payload,
                            result={"item": item},
                        )
                    except Exception as exc:
                        with self._lock:
                            if str(command["job_id"]) in self._cancel_requested:
                                raise
                        if physical_upload_succeeded:
                            if not counted_success:
                                succeeded += 1
                                completed_bytes += file_sizes[path]
                            LOGGER.warning(
                                "Storage file %s uploaded but bookkeeping/telemetry failed; retaining success",
                                path,
                                exc_info=True,
                            )
                            continue
                        LOGGER.exception("Storage upload failed for %s", path)
                        failed.append({"name": path.name, "error": str(exc)})
                        completed_bytes += file_sizes[path]
                        progress_payload = reporter.report(
                            phase="uploading",
                            message=f"Upload gagal: {path.name}",
                            overall={
                                "current": index,
                                "total": len(files),
                                "percent": (
                                    completed_bytes * 100 / total_bytes
                                    if total_bytes
                                    else 100
                                ),
                                "unit": "files",
                                "bytes_current": completed_bytes,
                                "bytes_total": total_bytes,
                            },
                            item={
                                "name": path.name,
                                "index": index,
                                "total": len(files),
                                "size_bytes": file_sizes[path],
                            },
                            counters={
                                "succeeded": succeeded,
                                "failed": len(failed),
                            },
                            force=True,
                        )
                        reporter.milestone(
                            "item_failed",
                            progress=progress_payload,
                            error={"message": str(exc)[:500], "item": path.name},
                        )
        if payload.get("rclone_upload"):
            with self._lock:
                if str(command["job_id"]) in self._cancel_requested:
                    raise QuickModeError("Upload dibatalkan oleh user.")
            reporter.report(
                phase="uploading",
                message="Mengupload file ke Google Drive dengan rclone",
                overall={
                    "current": 0,
                    "total": len(files),
                    "percent": 0,
                    "unit": "files",
                },
                counters={"succeeded": 0, "failed": 0},
                indeterminate=True,
                force=True,
            )
            rclone_result = self._rclone_upload_files(
                command,
                files,
                str(payload.get("rclone_destination") or ""),
                reporter,
                remote_names=[
                    path.relative_to(root).as_posix()
                    if preserve_structure
                    else path.name
                    for path in files
                ],
            )

        reporter.report(
            phase="completed",
            message=f"Upload selesai: {succeeded} berhasil, {len(failed)} gagal",
            overall={
                "current": len(files),
                "total": len(files),
                "percent": 100,
                "unit": "files",
                "bytes_current": total_bytes,
                "bytes_total": total_bytes,
            },
            counters={"succeeded": succeeded, "failed": len(failed)},
            force=True,
        )
        return {
            "total": len(files),
            "succeeded": succeeded,
            "failed": failed,
            "rclone_upload": bool(payload.get("rclone_upload")),
            "rclone_destination": (
                rclone_result.get("destination") if rclone_result else None
            ),
            "rclone_uploaded": rclone_result.get("succeeded", 0) if rclone_result else 0,
            "rclone_files": rclone_result.get("files", []) if rclone_result else [],
            "uploaded_items": uploaded_items,
        }
