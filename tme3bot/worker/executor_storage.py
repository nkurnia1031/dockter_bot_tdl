from __future__ import annotations

import mimetypes
import os
import shutil
import tempfile
import threading
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import (
    Path,
    PurePosixPath,
)
from tme3bot.progress_reporter import (
    ProgressReporter,
)
from tme3bot.media import has_downloadable_media
from tme3bot.tdl import tdl_session_denial_code, tdl_write_denial_code
from tme3bot.rclone import (
    RcloneError,
    RcloneRunner,
)
from tme3bot.storage_catalog import (
    build_storage_caption,
)
from tme3bot.storage_sync import parse_storage_export
from tme3bot.worker.quick_export import (
    QuickModeError,
)
from typing import (
    Any,
)

from .executor_support import (
    LOGGER,
    JobOwnerCommandCallback,
    _has_transfer_telemetry,
    storage_logical_folder,
    storage_relative_folders,
)

class _StorageDownloadFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = str(code or "STORAGE_DOWNLOAD_FAILED").strip().upper()
        super().__init__(message)


def _storage_upload_target_path(root: Path, path: Path, preserve_structure: bool) -> str:
    """Return the destination-relative file path used for duplicate checks."""
    _, relative_parent = storage_logical_folder(root, path, "", preserve_structure)
    return PurePosixPath(relative_parent, path.name).as_posix()


class StorageExecutorMixin:

    def _job_cancelled(self, job_id: str) -> bool:
        """Fallback for focused mixin harnesses; the full executor adds fencing."""
        requested = getattr(self, "_cancel_requested", set())
        lock = getattr(self, "_lock", None)
        if lock is None:
            return str(job_id) in requested
        with lock:
            return str(job_id) in requested

    @staticmethod
    def _storage_reconcile_has_content(message: dict[str, Any]) -> bool:
        """Check that a time-range export row contains enough message data."""
        content_keys = {
            "caption", "content", "file_name", "filename", "original_name",
            "message", "text",
        }
        found = False

        def visit(value: Any) -> None:
            nonlocal found
            if isinstance(value, dict):
                for key, child in value.items():
                    if str(key).lower() in content_keys:
                        found = True
                        if isinstance(child, (dict, list)):
                            visit(child)
                    elif isinstance(child, (dict, list)):
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    if isinstance(child, (dict, list)):
                        visit(child)

        visit(message)
        return found

    @staticmethod
    def _storage_reconcile_file_names(message: dict[str, Any]) -> list[str]:
        """Return exact Telegram filenames from a time-range export row."""
        name_keys = {"file_name", "filename", "original_name"}
        caption_keys = {"caption", "content", "message", "text"}
        names: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    selected_key = str(key).lower()
                    if selected_key in name_keys and isinstance(child, str):
                        normalized = child.strip().replace("\\", "/").rsplit("/", 1)[-1]
                        if normalized:
                            names.append(normalized)
                    elif selected_key in caption_keys and isinstance(child, str):
                        for line in child.splitlines():
                            prefix = "📄 Name:"
                            if line.strip().startswith(prefix):
                                normalized = line.strip()[len(prefix):].strip()
                                if normalized and normalized != "-":
                                    names.append(normalized)
                    if isinstance(child, (dict, list)):
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    if isinstance(child, (dict, list)):
                        visit(child)

        visit(message)
        return names

    def _storage_reconcile(
        self,
        command: dict[str, Any],
        *,
        upload_item_callback=None,
    ) -> dict[str, Any]:
        """Check ambiguous upload filenames in the job's time range."""
        del upload_item_callback
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        source_job_id = str(payload.get("source_job_id") or "").strip()
        raw_items = payload.get("_storage_reconcile_items")
        submitted_items = raw_items if isinstance(raw_items, list) else []
        store = getattr(self, "command_store", None)
        load_source = getattr(store, "storage_upload_items_for_job", None)
        source = load_source(source_job_id) if callable(load_source) else None
        source_items = source.get("items") if isinstance(source, dict) else None
        source_by_path = {
            str(item.get("path") or ""): item
            for item in source_items or []
            if isinstance(item, dict)
        }
        provider = str(
            payload.get("_storage_reconcile_provider") or payload.get("provider") or "telegram"
        ).strip().lower()
        if provider not in {"telegram", "rclone"}:
            raise ValueError("STORAGE_RECONCILIATION_PROVIDER_INVALID")
        try:
            start_timestamp = int(payload.get("start_timestamp"))
            end_timestamp = int(payload.get("end_timestamp"))
        except (TypeError, ValueError):
            raise ValueError("STORAGE_RECONCILIATION_RANGE_INVALID") from None
        if start_timestamp < 0 or end_timestamp < start_timestamp:
            raise ValueError("STORAGE_RECONCILIATION_RANGE_INVALID")

        candidates: list[dict[str, Any]] = []
        outputs: dict[int, dict[str, Any]] = {}
        for raw in submitted_items:
            if not isinstance(raw, dict):
                continue
            try:
                index = int(raw.get("index"))
            except (TypeError, ValueError):
                continue
            path = str(raw.get("path") or "").replace("\\", "/").strip()
            checkpoint = source_by_path.get(path)
            profile = str(raw.get("profile") or "").strip().lower()
            name = str(raw.get("name") or (checkpoint or {}).get("name") or "File")[:255]
            target_path = ""
            if provider == "rclone":
                saved_upload = (
                    checkpoint.get("uploaded_item")
                    if isinstance(checkpoint, dict)
                    else None
                )
                saved_upload = saved_upload if isinstance(saved_upload, dict) else {}
                target_path = str(saved_upload.get("target_path") or "").replace("\\", "/").strip()
                requested_target = str(raw.get("target_path") or "").replace("\\", "/").strip()
                remote_parts = PurePosixPath(target_path)
                identity = saved_upload.get("source_identity")
                if (
                    checkpoint is None
                    or saved_upload.get("provider") != "rclone"
                    or not isinstance(identity, dict)
                    or set(identity) != {"device", "inode", "size", "mtime_ns"}
                    or not target_path
                    or remote_parts.is_absolute()
                    or any(part in {"", ".", ".."} for part in remote_parts.parts)
                    or remote_parts.as_posix() != target_path
                    or (requested_target and requested_target != target_path)
                ):
                    target_path = ""
            if (
                not source_job_id
                or not path
                or (checkpoint or {}).get("status") != "needs_reconciliation"
                or not name.strip()
                or name == "File"
                or (provider == "rclone" and not target_path)
            ):
                outputs[index] = {
                    "index": index,
                    "name": name,
                    "profile": profile,
                    "status": "needs_reconciliation",
                    "match_count": 0,
                    "retryable": False,
                    "error_code": "STORAGE_RECONCILIATION_CHECKPOINT_UNAVAILABLE",
                    "error": "Nama file upload tidak tersedia pada checkpoint; hasil tetap ambigu.",
                }
                continue
            candidate = {
                "index": index,
                "path": path,
                "name": name,
                "profile": profile,
            }
            if provider == "rclone":
                candidate["target_path"] = target_path
                candidate["source_identity"] = saved_upload["source_identity"]
                candidate["source_command_id"] = str(source.get("command_id") or "")
                candidate["source_attempt"] = int(checkpoint.get("attempt") or 0)
                candidate["source_item"] = checkpoint
            candidates.append(candidate)

        requested_profiles = payload.get("_tdl_sender_profiles")
        requested_profiles = {
            str(item).strip().lower()
            for item in requested_profiles
            if str(item).strip()
        } if isinstance(requested_profiles, list) else set()
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        reporter.report(
            phase="reconciling",
            message=(
                "Memeriksa nama file pada rentang waktu job"
                if provider == "telegram"
                else "Menyiapkan pemeriksaan file pada tujuan rclone"
            ),
            overall={"current": 0, "total": len(submitted_items), "unit": "files"},
            counters={"succeeded": 0, "retryable": 0, "ambiguous": len(submitted_items)},
            force=True,
        )
        candidate_profiles = list(dict.fromkeys(
            [item["profile"] for item in candidates]
            + [str(item).strip().lower() for item in requested_profiles]
        ))
        if provider == "rclone":
            return self._storage_reconcile_rclone(
                command,
                payload,
                candidates,
                outputs,
                submitted_items,
            )
        target_chat = str(payload.get("tdl_access_target") or "").strip()
        if not target_chat:
            raise ValueError("TDL_ACCESS_TARGET_UNAVAILABLE")
        messages = None
        error_code = "STORAGE_RECONCILIATION_SESSION_UNAVAILABLE"
        for profile in candidate_profiles:
            if self._job_cancelled(str(command.get("job_id") or "")):
                break
            try:
                runtime = self.profile_manager.runtime(profile)
                client = runtime.upload_tdl_client
                with runtime.upload_operation_lock:
                    with tempfile.TemporaryDirectory(prefix="storage-reconcile-") as raw_dir:
                        export_path = Path(raw_dir) / "messages.json"
                        callback = getattr(client, "command_callback", None)
                        try:
                            # The job result contains a safe summary only;
                            # suppress command snapshots that include the temp path.
                            if hasattr(client, "command_callback"):
                                client.command_callback = JobOwnerCommandCallback(
                                    str(command.get("job_id") or "")
                                )
                            exported = client.export_messages_by_time(
                                target_chat,
                                start_timestamp,
                                end_timestamp,
                                export_path,
                                with_content=True,
                            )
                        finally:
                            if hasattr(client, "command_callback"):
                                client.command_callback = callback
                candidate_messages = getattr(exported, "messages", None)
                if not isinstance(candidate_messages, list) or any(
                    not isinstance(message, dict)
                    or not self._storage_reconcile_has_content(message)
                    or (
                        has_downloadable_media(message)
                        and not self._storage_reconcile_file_names(message)
                    )
                    for message in candidate_messages
                ):
                    raise ValueError("incomplete export")
                messages = candidate_messages
                error_code = ""
                break
            except Exception:
                # A failed, timed-out, or incomplete export cannot prove
                # absence, so continue to another verified lane if available.
                error_code = "STORAGE_RECONCILIATION_EXPORT_INCOMPLETE"

        if messages is None:
            message_text = {
                "STORAGE_RECONCILIATION_SESSION_CHANGED":
                    "Sesi lane Upload berubah sejak job dibuat; hasil tetap ambigu.",
                "STORAGE_RECONCILIATION_SESSION_UNAVAILABLE":
                    "Lane Upload tidak memiliki snapshot sesi yang dapat diverifikasi.",
                "STORAGE_RECONCILIATION_EXPORT_INCOMPLETE":
                    "Ekspor waktu tidak lengkap atau gagal; hasil tetap ambigu.",
            }.get(error_code, "Hasil tetap ambigu dan tidak aman untuk Retry.")
            for item in candidates:
                outputs[item["index"]] = {
                    "index": item["index"], "name": item["name"],
                    "profile": item["profile"], "status": "needs_reconciliation",
                    "match_count": 0, "retryable": False,
                    "error_code": error_code, "error": message_text,
                }
        else:
            filename_counts: dict[str, int] = {}
            for message in messages:
                for value in set(self._storage_reconcile_file_names(message)):
                    filename_counts[value] = filename_counts.get(value, 0) + 1
            grouped_candidates: dict[str, list[dict[str, Any]]] = {}
            for item in candidates:
                grouped_candidates.setdefault(item["name"], []).append(item)
            for file_name, matching_items in grouped_candidates.items():
                match_count = filename_counts.get(file_name, 0)
                if match_count == 0:
                    status, retryable = "failed", True
                    code = "STORAGE_UPLOAD_NOT_FOUND"
                    error = "Nama file tidak ditemukan pada rentang waktu job; file aman untuk Retry."
                elif match_count == len(matching_items):
                    status, retryable = "succeeded", False
                    code = ""
                    error = "Nama file ditemukan pada rentang waktu job; file tidak akan dikirim ulang."
                else:
                    status, retryable = "needs_reconciliation", False
                    code = "STORAGE_UPLOAD_DUPLICATE_FILENAME_AMBIGUOUS"
                    error = "Jumlah nama file cocok tidak sama dengan jumlah file ambigu pada job."
                for item in matching_items:
                    outputs[item["index"]] = {
                        "index": item["index"], "name": item["name"],
                        "profile": item["profile"], "status": status,
                        "match_count": match_count, "retryable": retryable,
                        "error_code": code, "error": error,
                    }

        for raw in submitted_items:
            if not isinstance(raw, dict):
                continue
            try:
                index = int(raw.get("index"))
            except (TypeError, ValueError):
                continue
            if index not in outputs:
                outputs[index] = {
                    "index": index,
                    "name": str(raw.get("name") or "File")[:255],
                    "profile": str(raw.get("profile") or "").strip().lower(),
                    "status": "needs_reconciliation",
                    "match_count": 0,
                    "retryable": False,
                    "error_code": "STORAGE_RECONCILIATION_INTERRUPTED",
                    "error": "Pemeriksaan terhenti sebelum file dapat dipastikan.",
                }
        results = [outputs[key] for key in sorted(outputs)]
        resolved = all(item["status"] in {"succeeded", "failed"} for item in results)
        succeeded = sum(item["status"] == "succeeded" for item in results)
        retryable = sum(item["retryable"] is True for item in results)
        unresolved = sum(item["status"] == "needs_reconciliation" for item in results)
        outcome = "succeeded" if resolved else "needs_reconciliation"
        reporter.report(
            phase=outcome,
            message="Pemeriksaan nama file selesai" if resolved else "Sebagian file tetap ambigu",
            overall={"current": len(results), "total": len(submitted_items), "unit": "files"},
            counters={"succeeded": succeeded, "retryable": retryable, "ambiguous": unresolved},
            force=True,
        )
        return {
            "outcome": outcome,
            "source_job_id": source_job_id,
            "total": len(results),
            "succeeded": succeeded,
            "retryable": retryable,
            "ambiguous": unresolved,
            "items": results,
        }

    def _storage_reconcile_rclone(
        self,
        command: dict[str, Any],
        payload: dict[str, Any],
        candidates: list[dict[str, Any]],
        outputs: dict[int, dict[str, Any]],
        submitted_items: list[Any],
    ) -> dict[str, Any]:
        """Verify ambiguous Rclone targets by exact path and size, never re-upload."""
        job_id = str(command.get("job_id") or "")
        source_job_id = str(payload.get("source_job_id") or "").strip()
        preparation_error = False
        reporter = ProgressReporter(self.publisher, job_id)
        reporter.report(
            phase="reconciling",
            message="Memeriksa ukuran file pada tujuan rclone tanpa mengunggah ulang",
            overall={"current": 0, "total": len(submitted_items), "unit": "files"},
            counters={"succeeded": 0, "retryable": 0, "ambiguous": len(submitted_items)},
            force=True,
        )
        try:
            root = self._workspace_path(str(payload.get("folder_path") or ""))
            workspace = self._quick_workspace(self.config).resolve()
            root = root.resolve()
            root.relative_to(workspace)
            destination = str(payload.get("rclone_destination") or "").strip()
            config_path = Path(
                getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")
            ).resolve()
            config_root = Path(getattr(self.config, "profile_root", "/data")).resolve()
        except (OSError, TypeError, ValueError):
            preparation_error = True
            root = None
            workspace = None
            destination = ""
            config_path = Path("/nonexistent/rclone.conf")
            config_root = Path("/nonexistent")

        valid: list[dict[str, Any]] = []
        paths: list[Path] = []
        remote_names: list[str] = []
        if root is not None and workspace is not None and root.is_dir() and destination:
            for item in candidates:
                relative = str(item.get("path") or "")
                parts = relative.split("/")
                source = root.joinpath(*parts)
                try:
                    source.resolve(strict=True).relative_to(root)
                    source.resolve(strict=True).relative_to(workspace)
                except (OSError, ValueError):
                    source = None
                identity = item.get("source_identity")
                if (
                    source is None
                    or source.is_symlink()
                    or not source.is_file()
                    or not isinstance(identity, dict)
                    or not self._same_storage_source(source, identity)
                ):
                    outputs[int(item["index"])] = {
                        "index": int(item["index"]),
                        "name": str(item["name"]),
                        "target_path": str(item["target_path"]),
                        "profile": str(item.get("profile") or ""),
                        "status": "needs_reconciliation",
                        "match_count": 0,
                        "retryable": False,
                        "error_code": "STORAGE_SOURCE_CHANGED",
                        "error": "File sumber berubah atau tidak tersedia; tujuan tidak dapat dicocokkan dengan aman.",
                    }
                    continue
                valid.append(item)
                paths.append(source)
                remote_names.append(str(item["target_path"]))
        else:
            preparation_error = True
            for item in candidates:
                outputs[int(item["index"])] = {
                    "index": int(item["index"]),
                    "name": str(item["name"]),
                    "target_path": str(item["target_path"]),
                    "profile": str(item.get("profile") or ""),
                    "status": "needs_reconciliation",
                    "match_count": 0,
                    "retryable": False,
                    "error_code": "RCLONE_VERIFY_UNAVAILABLE",
                    "error": "Worker tidak dapat menyiapkan pemeriksaan tujuan rclone; sumber dipertahankan.",
                }

        verification: dict[str, Any] = {"files": [], "missing": [], "errors": []}
        verification_error = preparation_error
        if valid:
            try:
                runner = RcloneRunner(
                    log_callback=self._append_job_log,
                    command_callback=self._command_callback(runtime="rclone_storage_reconcile"),
                    stall_timeout_seconds=getattr(self.config, "job_stall_timeout_seconds", 600),
                )
                verification = runner.verify_files(
                    paths,
                    destination,
                    config_path,
                    workspace_root=workspace,
                    config_root=config_root,
                    remote_names=remote_names,
                )
            except Exception:
                LOGGER.warning("Could not verify rclone Storage reconciliation for %s", job_id, exc_info=True)
                verification_error = True

        if not isinstance(verification, dict):
            verification = {"files": [], "missing": [], "errors": []}
            verification_error = True

        found = {
            str(item).replace("\\", "/").strip("/")
            for item in verification.get("files", [])
        } if isinstance(verification, dict) else set()
        missing_by_name = {
            str(item.get("name") or "").replace("\\", "/").strip("/"): str(item.get("error") or "")
            for item in verification.get("missing", [])
            if isinstance(item, dict)
        } if isinstance(verification, dict) else {}
        error_names = {
            str(item.get("name") or "").replace("\\", "/").strip("/")
            for item in verification.get("errors", [])
            if isinstance(item, dict)
        } if isinstance(verification, dict) else set()

        for item in valid:
            index = int(item["index"])
            target_path = str(item["target_path"])
            if not verification_error and target_path in found:
                state = "succeeded"
                retryable = False
                code = ""
                message = "Nama dan ukuran file cocok di tujuan rclone; upload tidak diulang."
                match_count = 1
            elif not verification_error and target_path in missing_by_name and "belum ditemukan" in missing_by_name[target_path].casefold():
                state = "failed"
                retryable = True
                code = "RCLONE_UPLOAD_NOT_FOUND"
                message = "File tidak ditemukan pada path tujuan rclone; file aman untuk Retry."
                match_count = 0
            else:
                state = "needs_reconciliation"
                retryable = False
                code = (
                    "RCLONE_VERIFY_UNAVAILABLE"
                    if verification_error or target_path in error_names
                    else "RCLONE_UPLOAD_SIZE_MISMATCH"
                )
                message = (
                    "Rclone belum dapat membuktikan file di tujuan; sumber dipertahankan."
                    if code == "RCLONE_VERIFY_UNAVAILABLE"
                    else "Path ditemukan dengan ukuran berbeda atau hasil tidak lengkap; sumber dipertahankan."
                )
                match_count = 0
            outputs[index] = {
                "index": index,
                "name": str(item["name"]),
                "target_path": target_path,
                "profile": str(item.get("profile") or ""),
                "status": state,
                "match_count": match_count,
                "retryable": retryable,
                "error_code": code,
                "error": message,
            }
            if state == "succeeded":
                store = getattr(self, "command_store", None)
                persist = getattr(store, "record_storage_upload_item", None)
                source_command_id = str(item.get("source_command_id") or "")
                source_item = item.get("source_item")
                saved_upload = (
                    source_item.get("uploaded_item")
                    if isinstance(source_item, dict)
                    else None
                )
                if callable(persist) and source_command_id and isinstance(saved_upload, dict):
                    transfer_mode = str(
                        payload.get("transfer_mode")
                        or saved_upload.get("transfer_mode")
                        or "copy"
                    ).strip().lower()
                    updated_upload = {
                        **saved_upload,
                        "status": "succeeded",
                        "upload_status": "succeeded",
                        "error_code": "",
                        "error": "",
                        "cleanup_status": (
                            "retained_ambiguous" if transfer_mode == "move" else "not_requested"
                        ),
                    }
                    try:
                        persist(
                            source_command_id,
                            str(item.get("path") or ""),
                            file_name=str(item.get("name") or "File"),
                            status="succeeded",
                            attempt=int(item.get("source_attempt") or 0),
                            retryable=False,
                            result_item=updated_upload,
                        )
                    except Exception:
                        LOGGER.warning(
                            "Could not persist rclone reconciliation checkpoint for %s",
                            job_id,
                            exc_info=True,
                        )

        for raw in submitted_items:
            if not isinstance(raw, dict):
                continue
            try:
                index = int(raw.get("index"))
            except (TypeError, ValueError):
                continue
            if index not in outputs:
                outputs[index] = {
                    "index": index,
                    "name": str(raw.get("name") or "File")[:255],
                    "target_path": str(raw.get("target_path") or ""),
                    "status": "needs_reconciliation",
                    "match_count": 0,
                    "retryable": False,
                    "error_code": "STORAGE_RECONCILIATION_INTERRUPTED",
                    "error": "Pemeriksaan terhenti sebelum file dapat dipastikan.",
                }
        results = [outputs[key] for key in sorted(outputs)]
        resolved = all(item["status"] in {"succeeded", "failed"} for item in results)
        succeeded = sum(item["status"] == "succeeded" for item in results)
        retryable = sum(item["retryable"] is True for item in results)
        unresolved = sum(item["status"] == "needs_reconciliation" for item in results)
        outcome = "succeeded" if resolved else "needs_reconciliation"
        reporter.report(
            phase=outcome,
            message="Pemeriksaan rclone selesai" if resolved else "Sebagian file tetap ambigu",
            overall={"current": len(results), "total": len(submitted_items), "unit": "files"},
            counters={"succeeded": succeeded, "retryable": retryable, "ambiguous": unresolved},
            force=True,
        )
        return {
            "outcome": outcome,
            "provider": "rclone",
            "source_job_id": source_job_id,
            "total": len(results),
            "succeeded": succeeded,
            "retryable": retryable,
            "ambiguous": unresolved,
            "items": results,
        }

    @contextmanager
    def _storage_upload_lane_locks(self, runtimes):
        """Hold every fallback Upload lane in a stable order for one batch."""
        with ExitStack() as stack:
            for profile in sorted(runtimes):
                stack.enter_context(runtimes[profile].upload_operation_lock)
            yield

    @contextmanager
    def _capture_storage_upload_output(self, runtimes):
        """Capture TDL output from every eligible sender lane during fallback."""
        with ExitStack() as stack:
            for profile in sorted(runtimes):
                stack.enter_context(
                    self._capture_tdl_output(
                        runtimes[profile].upload_tdl_client,
                        command_callback=self._command_callback(
                            profile=profile, runtime="upload"
                        ),
                    )
                )
            yield

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
        try:
            file_sizes = [int(path.stat().st_size) for path in files]
        except OSError:
            file_sizes = []
        total_bytes = sum(file_sizes) if len(file_sizes) == len(files) else None
        completed_bytes = 0

        def report_transfer(index: int, name: str, transfer: dict[str, object]) -> None:
            size = file_sizes[index - 1] if len(file_sizes) == len(files) else None
            try:
                current = max(0, int(transfer.get("bytes_current") or 0))
            except (TypeError, ValueError):
                current = 0
            try:
                percent = float(transfer["percent"]) if transfer.get("percent") is not None else None
            except (TypeError, ValueError):
                percent = None
            batch_bytes = completed_bytes + current
            reporter.report(
                phase="uploading",
                message=f"Mengupload {name} ke rclone",
                overall={
                    "current": index - 1,
                    "total": len(files),
                    "percent": (
                        min(100.0, batch_bytes * 100 / total_bytes)
                        if total_bytes
                        else ((index - 1) + (percent or 0) / 100) * 100 / len(files)
                        if files
                        else 100,
                    ),
                    "unit": "files",
                    "files_current": index - 1,
                    "files_total": len(files),
                    "bytes_current": batch_bytes,
                    "bytes_total": total_bytes,
                },
                item={"name": name, "index": index, "total": len(files), "percent": percent, "size_bytes": size},
                transfer=reporter.transfer_metrics(
                    speed_bps=transfer.get("speed_bps"),
                    current_bytes=current,
                    total_bytes=size,
                    eta_seconds=transfer.get("eta_seconds"),
                    percent=percent,
                ),
                counters={"succeeded": index - 1, "failed": 0},
            )

        def progress(index: int, total: int, name: str) -> None:
            nonlocal completed_bytes
            if len(file_sizes) == len(files):
                completed_bytes += file_sizes[index - 1]
            size = file_sizes[index - 1] if len(file_sizes) == len(files) else None
            # A telemetry outage must not turn an already completed remote
            # copy into a false physical upload failure.
            try:
                reporter.report(
                    phase="uploading",
                    message=f"Mengupload {name} ke rclone",
                    overall={
                        "current": index,
                        "total": total,
                        "percent": (
                            completed_bytes * 100 / total_bytes
                            if total_bytes
                            else index * 100 / total if total else 100
                        ),
                        "unit": "files",
                        "files_current": index,
                        "files_total": total,
                        "bytes_current": completed_bytes,
                        "bytes_total": total_bytes,
                    },
                    item={
                        "name": name,
                        "index": index,
                        "total": total,
                        "percent": 100,
                        "size_bytes": size,
                    },
                    transfer=reporter.transfer_metrics(
                        current_bytes=size,
                        total_bytes=size,
                        percent=100,
                    ),
                    counters={"succeeded": index, "failed": 0},
                    force=True,
                )
                reporter.reset_transfer()
            except Exception:
                LOGGER.warning(
                    "Could not publish rclone progress for %s", job_id, exc_info=True
                )

        def cancelled() -> bool:
            return self._job_cancelled(job_id)

        runner = RcloneRunner(
            log_callback=self._append_job_log,
            command_callback=self._command_callback(runtime="rclone_storage"),
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
            runner.transfer_callback = lambda value: report_transfer(
                max(1, int(value.get("index") or 1)),
                str(value.get("name") or "File"), value,
            )
            try:
                return runner.copy_files(
                    files,
                    destination,
                    config_path,
                    workspace_root=workspace,
                    config_root=config_root,
                    **kwargs,
                )
            except RcloneError as exc:
                raise QuickModeError(str(exc), code=exc.code) from exc
        finally:
            with self._lock:
                self._rclone_runners.pop(job_id, None)

    def rclone_storage_runtime_readiness(
        self, destination: str
    ) -> dict[str, object]:
        """Probe the selected rclone root using a read-only worker command."""
        config_path = Path(
            getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")
        ).resolve()
        config_root = Path(getattr(self.config, "profile_root", "/data")).resolve()
        runner = RcloneRunner(stall_timeout_seconds=30)
        return runner.probe_access(
            str(destination or ""), config_path, config_root=config_root
        )

    def rclone_storage_browse(
        self, destination: str, relative_path: str = "", *, query: str = "",
        sort: str = "name", order: str = "asc", limit: int = 100, offset: int = 0,
    ) -> dict[str, object]:
        """Read one directory below the configured rclone root."""
        config_path = Path(
            getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")
        ).resolve()
        config_root = Path(getattr(self.config, "profile_root", "/data")).resolve()
        runner = RcloneRunner(stall_timeout_seconds=30)
        return runner.list_directory(
            destination, relative_path, config_path, config_root=config_root,
            query=query, sort=sort, order=order, limit=limit, offset=offset,
        )

    def rclone_storage_folder_summaries(
        self, destination: str, relative_path: str = ""
    ) -> dict[str, object]:
        """Summarize current folder children from one metadata-only inventory."""
        config_path = Path(
            getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")
        ).resolve()
        config_root = Path(getattr(self.config, "profile_root", "/data")).resolve()
        runner = RcloneRunner(stall_timeout_seconds=120)
        return runner.list_directory_summaries(
            destination, relative_path, config_path, config_root=config_root,
        )

    def rclone_storage_mutate(
        self, destination: str, action: str, path: str, name: str
    ) -> dict[str, object]:
        """Create one remote folder or rename one remote entry."""
        config_path = Path(
            getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")
        ).resolve()
        config_root = Path(getattr(self.config, "profile_root", "/data")).resolve()
        runner = RcloneRunner(
            stall_timeout_seconds=30,
            command_callback=self._command_callback(runtime="rclone_storage"),
        )
        with self._rclone_storage_lock:
            if action == "create_folder":
                return runner.create_directory(
                    destination, path, name, config_path, config_root=config_root
                )
            if action == "rename":
                return runner.rename_path(
                    destination, path, name, config_path, config_root=config_root
                )
            raise RcloneError(
                "Operasi Storage rclone tidak didukung.",
                code="RCLONE_ACTION_INVALID",
            )

    def rclone_storage_trash(
        self, destination: str, *, limit: int = 100, offset: int = 0
    ) -> dict[str, object]:
        config_path = Path(
            getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")
        ).resolve()
        config_root = Path(getattr(self.config, "profile_root", "/data")).resolve()
        runner = RcloneRunner(stall_timeout_seconds=120)
        return runner.list_trash(
            destination, config_path, config_root=config_root,
            limit=limit, offset=offset,
        )

    def _storage_rclone_manage(self, command: dict[str, Any]) -> dict[str, Any]:
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        job_id = str(command.get("job_id") or "")
        destination = str(payload.get("rclone_destination") or "").strip()
        action = str(payload.get("action") or "").strip().lower()
        raw_sources = payload.get("sources")
        sources = [item for item in raw_sources if isinstance(item, dict)] if isinstance(raw_sources, list) else []
        destination_path = str(payload.get("destination_path") or "")
        trashed = payload.get("trashed") is True
        if action not in {"copy", "move", "trash", "restore", "purge"}:
            raise RcloneError("Operasi Storage rclone tidak didukung.", code="RCLONE_ACTION_INVALID")
        if not destination or not sources or len(sources) > 200:
            raise RcloneError("Pilihan Storage rclone tidak valid.", code="RCLONE_ACTION_REQUEST_INVALID")

        config_path = Path(
            getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")
        ).resolve()
        config_root = Path(getattr(self.config, "profile_root", "/data")).resolve()
        reporter = ProgressReporter(self.publisher, job_id)
        runner = RcloneRunner(
            log_callback=self._append_job_log,
            command_callback=self._command_callback(runtime="rclone_storage"),
            stall_timeout_seconds=getattr(self.config, "job_stall_timeout_seconds", 600),
            cancel_check=lambda: self._storage_download_cancelled(job_id),
        )
        with self._lock:
            self._rclone_runners[job_id] = runner

        deduplicated: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source in sources:
            path = str(source.get("path") or "").replace("\\", "/").strip("/")
            item_id = str(source.get("id") or "").strip()[:256]
            parts = path.split("/") if path else []
            if (
                not path or len(path) > 2048
                or any(not part or part in {".", ".."} or ":" in part for part in parts)
                or any(ord(char) < 32 for char in path)
            ):
                raise RcloneError("Path sumber rclone tidak valid.", code="RCLONE_BROWSER_PATH_INVALID")
            if path in seen:
                continue
            seen.add(path)
            deduplicated.append({
                "path": path,
                "is_dir": source.get("is_dir") is True,
                "id": item_id,
            })
        # Parent selections subsume their children, avoiding duplicate writes.
        ordered = sorted(deduplicated, key=lambda item: (str(item["path"]).count("/"), str(item["path"])))
        sources = []
        selected_roots: list[str] = []
        for item in ordered:
            path = str(item["path"])
            if any(path.startswith(parent + "/") for parent in selected_roots):
                continue
            selected_roots.append(path)
            sources.append(item)

        items: list[dict[str, Any]] = []
        succeeded = failed = skipped = 0
        total = len(sources)
        reporter.report(
            phase="queued",
            message=f"Menyiapkan {total} operasi rclone",
            overall={"current": 0, "total": total, "unit": "items"},
            counters={"succeeded": 0, "failed": 0, "skipped": 0},
            force=True,
        )
        for index, source in enumerate(sources, start=1):
            path = str(source["path"])
            is_dir = source["is_dir"] is True
            if self._storage_download_cancelled(job_id):
                items.append({"path": path, "status": "cancelled", "error_code": "JOB_TERMINATED"})
                skipped += 1
                continue
            source_name = path.rsplit("/", 1)[-1]
            transfer_latest: dict[str, Any] = {}

            def report_transfer(transfer: dict[str, object]) -> None:
                transfer_latest.update(transfer)
                reporter.report(
                    phase=action,
                    message=f"{action.capitalize()} {source_name}",
                    overall={"current": index - 1, "total": total, "unit": "items"},
                    item={"name": source_name, "path": path, "index": index, "total": total,
                          "percent": transfer.get("percent"), "size_bytes": transfer.get("bytes_total")},
                    transfer=reporter.transfer_metrics(
                        speed_bps=transfer.get("speed_bps"),
                        current_bytes=transfer.get("bytes_current"),
                        total_bytes=transfer.get("bytes_total"),
                        eta_seconds=transfer.get("eta_seconds"),
                        percent=transfer.get("percent"),
                    ),
                    counters={"succeeded": succeeded, "failed": failed, "skipped": skipped},
                )

            try:
                result = runner.manage_storage_item(
                    destination,
                    action=action,
                    path=path,
                    is_dir=is_dir,
                    config_path=config_path,
                    config_root=config_root,
                    destination_path=destination_path,
                    trashed=trashed,
                    item_id=str(source.get("id") or ""),
                    selected_restore_sources=sources if action == "restore" else None,
                    progress_callback=report_transfer,
                )
                item = {"path": path, "is_dir": is_dir, **result}
                status = str(item.get("status") or "succeeded")
                if status == "succeeded":
                    succeeded += 1
                elif status == "partial":
                    failed += 1
                items.append(item)
            except RcloneError as exc:
                failed += 1
                items.append({
                    "path": path,
                    "is_dir": is_dir,
                    "status": "failed",
                    "error_code": exc.code or "RCLONE_OPERATION_FAILED",
                    "error": str(exc),
                    "transfer": transfer_latest or None,
                })
            except Exception as exc:
                failed += 1
                items.append({
                    "path": path,
                    "is_dir": is_dir,
                    "status": "failed",
                    "error_code": "RCLONE_OPERATION_FAILED",
                    "error": "rclone gagal menjalankan operasi ini.",
                    "failure_type": type(exc).__name__,
                    "transfer": transfer_latest or None,
                })
            reporter.report(
                phase=action,
                message=f"{action.capitalize()} {source_name} selesai",
                overall={"current": index, "total": total, "unit": "items"},
                item={"name": source_name, "path": path, "index": index, "total": total, "status": items[-1]["status"]},
                counters={"succeeded": succeeded, "failed": failed, "skipped": skipped},
                force=True,
            )
        outcome = "succeeded" if failed == 0 and skipped == 0 else "partial_failure" if succeeded else "failed"
        reporter.report(
            phase=outcome,
            message=f"Operasi rclone selesai: {succeeded} berhasil, {failed} gagal, {skipped} dibatalkan",
            overall={"current": succeeded + failed + skipped, "total": total, "unit": "items"},
            counters={"succeeded": succeeded, "failed": failed, "skipped": skipped},
            force=True,
        )
        return {"outcome": outcome, "action": action, "total": total,
                "succeeded": succeeded, "failed": failed, "skipped": skipped, "items": items}

    @staticmethod
    def _storage_source_identity(path: Path) -> dict[str, int]:
        info = path.stat(follow_symlinks=False)
        return {
            "device": int(info.st_dev), "inode": int(info.st_ino),
            "size": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
        }

    @staticmethod
    def _same_storage_source(path: Path, expected: dict[str, Any]) -> bool:
        try:
            current = StorageExecutorMixin._storage_source_identity(path)
        except OSError:
            return False
        return all(current.get(key) == expected.get(key) for key in ("device", "inode", "size", "mtime_ns"))

    def _storage_move_cleanup(
        self, path: Path, root: Path, expected: dict[str, Any]
    ) -> str:
        """Delete one unchanged source after a confirmed remote upload."""
        try:
            path.resolve(strict=False).relative_to(root.resolve())
        except ValueError:
            return "retained_unsafe_path"
        if not path.exists():
            return "deleted"
        if not self._same_storage_source(path, expected):
            return "skipped_source_changed"
        try:
            path.unlink()
        except OSError:
            return "cleanup_failed"
        parent = path.parent
        root = root.resolve()
        while parent != root:
            try:
                parent.resolve().relative_to(root)
                parent.rmdir()
            except (OSError, ValueError):
                break
            parent = parent.parent
        return "deleted"

    def reconcile_rclone_storage_recovery(
        self,
        command_id: str,
        folder_path: str,
        destination: str,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Verify interrupted rclone sends without resending them."""
        store = getattr(self, "command_store", None)
        persist = getattr(store, "record_storage_upload_item", None)
        read_items = getattr(store, "storage_upload_items", None)
        if not callable(persist) or not callable(read_items):
            return items
        try:
            root = self._workspace_path(str(folder_path or ""))
            workspace = self._quick_workspace(self.config)
            config_path = Path(
                getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")
            ).resolve()
            config_root = Path(getattr(self.config, "profile_root", "/data")).resolve()
        except Exception:
            LOGGER.warning("Could not prepare rclone Storage recovery for %s", command_id)
            return items
        runner = RcloneRunner(
            log_callback=self._append_job_log,
            command_callback=self._command_callback(runtime="rclone_storage"),
            stall_timeout_seconds=getattr(self.config, "job_stall_timeout_seconds", 600),
        )
        for checkpoint in items:
            if not isinstance(checkpoint, dict) or checkpoint.get("status") != "needs_reconciliation":
                continue
            uploaded = checkpoint.get("uploaded_item")
            if not isinstance(uploaded, dict) or uploaded.get("provider") != "rclone":
                continue
            relative = str(checkpoint.get("path") or "").replace("\\", "/")
            parts = relative.split("/")
            if not relative or relative.startswith("/") or any(part in {"", ".", ".."} for part in parts):
                continue
            source = root.joinpath(*parts)
            target_path = str(uploaded.get("target_path") or "")
            identity = uploaded.get("source_identity")
            if (
                not target_path
                or not isinstance(identity, dict)
                or not self._same_storage_source(source, identity)
            ):
                continue
            try:
                source.resolve(strict=True).relative_to(root.resolve())
                evidence = runner.verify_complete_files(
                    [source],
                    str(destination or ""),
                    config_path,
                    workspace_root=workspace,
                    config_root=config_root,
                    remote_names=[target_path],
                )
            except Exception:
                LOGGER.warning("Could not verify interrupted rclone Storage item for %s", command_id)
                evidence = {"complete": False, "reason_code": "RCLONE_VERIFY_UNAVAILABLE"}
            if evidence.get("complete") is True:
                updated = {
                    **uploaded,
                    "status": "succeeded",
                    "upload_status": "succeeded",
                    "verified_full_content": True,
                    "error_code": "",
                    "error": "",
                    "cleanup_status": "pending" if uploaded.get("transfer_mode") == "move" else "not_requested",
                }
                if updated.get("transfer_mode") == "move":
                    updated["cleanup_status"] = self._storage_move_cleanup(source, root, identity)
                persist(
                    command_id,
                    relative,
                    file_name=str(checkpoint.get("name") or source.name),
                    status="succeeded",
                    attempt=int(checkpoint.get("attempt") or 0),
                    retryable=False,
                    result_item=updated,
                )
            else:
                updated = {
                    **uploaded,
                    "status": "needs_reconciliation",
                    "upload_status": "needs_reconciliation",
                    "cleanup_status": "retained_ambiguous" if uploaded.get("transfer_mode") == "move" else "not_requested",
                    "error_code": str(evidence.get("reason_code") or "RCLONE_UPLOAD_AMBIGUOUS"),
                    "error": "Upload rclone belum dapat dibuktikan lengkap; file sumber dipertahankan.",
                }
                persist(
                    command_id,
                    relative,
                    file_name=str(checkpoint.get("name") or source.name),
                    status="needs_reconciliation",
                    attempt=int(checkpoint.get("attempt") or 0),
                    retryable=False,
                    error_code=updated["error_code"],
                    error_message=updated["error"],
                    result_item=updated,
                )
        return read_items(command_id)

    def storage_move_cleanup_reconciled(
        self, source_job_id: str, folder_path: str, relative_path: str
    ) -> dict[str, str]:
        """Cleanup using worker-private metadata after gateway reconciliation confirms delivery."""
        raw = str(relative_path or "").replace("\\", "/")
        parts = raw.split("/")
        if not raw or raw.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("STORAGE_MOVE_PATH_INVALID")
        store = getattr(self, "command_store", None)
        load_source = getattr(store, "storage_upload_items_for_job", None)
        source = load_source(source_job_id) if callable(load_source) else None
        matches = [
            item for item in source.get("items", [])
            if isinstance(item, dict) and str(item.get("path") or "") == raw
        ] if isinstance(source, dict) else []
        if not matches:
            return {"cleanup_status": "retained_unverified"}
        checkpoint = matches[0]
        saved = checkpoint.get("uploaded_item")
        identity = saved.get("source_identity") if isinstance(saved, dict) else None
        if not isinstance(identity, dict) or set(identity) != {"device", "inode", "size", "mtime_ns"}:
            return {"cleanup_status": "retained_unverified"}
        try:
            expected = {key: int(identity[key]) for key in ("device", "inode", "size", "mtime_ns")}
            root = self._workspace_path(str(folder_path or ""))
        except (TypeError, ValueError, OSError):
            return {"cleanup_status": "retained_unverified"}
        candidate = root.joinpath(*parts)
        cleanup_status = str(saved.get("cleanup_status") or "") if isinstance(saved, dict) else ""
        if cleanup_status not in {"", "pending", "retained_ambiguous"}:
            return {"cleanup_status": cleanup_status}
        cleanup_status = self._storage_move_cleanup(candidate, root, expected)
        updated = {**saved, "upload_status": "succeeded", "cleanup_status": cleanup_status}
        persist = getattr(store, "record_storage_upload_item", None)
        if callable(persist):
            persist(
                str(source.get("command_id") or ""), raw,
                file_name=str(checkpoint.get("name") or Path(raw).name),
                status="succeeded", attempt=int(checkpoint.get("attempt") or 0),
                retryable=False, result_item=updated,
            )
        return {"cleanup_status": cleanup_status}

    def _storage_upload_rclone(
        self, command: dict[str, Any], payload: dict[str, Any], *, upload_item_callback=None
    ) -> dict[str, Any]:
        """Durable, one-provider rclone upload with collision and Move safeguards."""
        del upload_item_callback
        command_id = str(command.get("command_id") or "").strip()
        job_id = str(command.get("job_id") or "").strip()
        if not command_id or not job_id:
            raise RuntimeError("STORAGE_CHECKPOINT_UNAVAILABLE: rclone upload requires a durable command.")
        store = getattr(self, "command_store", None)
        persist = getattr(store, "record_storage_upload_item", None)
        read_items = getattr(store, "storage_upload_items", None)
        if not callable(persist) or not callable(read_items):
            raise RuntimeError("STORAGE_CHECKPOINT_UNAVAILABLE: worker tidak dapat menyimpan hasil per file.")
        root = self._workspace_path(str(payload.get("folder_path") or ""))
        if not root.is_dir():
            raise ValueError("STORAGE_SOURCE_INVALID: folder Workspace tidak ditemukan.")
        preserve = payload.get("preserve_structure", True) is True
        transfer_mode = "move" if payload.get("transfer_mode") == "move" else "copy"
        rclone_path = str(payload.get("rclone_path") or "").replace("\\", "/")
        if rclone_path.startswith("/"):
            raise ValueError("RCLONE_BROWSER_PATH_INVALID: tujuan harus berada di bawah root rclone.")
        rclone_path = rclone_path.strip("/")
        parts = rclone_path.split("/") if rclone_path else []
        if any(not item or item in {".", ".."} or ":" in item for item in parts):
            raise ValueError("RCLONE_BROWSER_PATH_INVALID: tujuan harus berada di bawah root rclone.")
        files = sorted(path for path in root.rglob("*") if path.is_file() and not path.is_symlink())
        allowed = {str(item) for item in (payload.get("allowed_names") or []) if str(item)}
        if allowed:
            files = [path for path in files if path.name in allowed]
        retry_paths = payload.get("_storage_retry_paths")
        if isinstance(retry_paths, list):
            selected = {str(item).replace("\\", "/").strip() for item in retry_paths}
            files = [path for path in files if path.relative_to(root).as_posix() in selected]

        workspace = self._quick_workspace(self.config)
        config_path = Path(getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")).resolve()
        config_root = Path(getattr(self.config, "profile_root", "/data")).resolve()
        previous = {str(item.get("path") or ""): item for item in read_items(command_id) if isinstance(item, dict)}
        for path in files:
            relative = path.relative_to(root).as_posix()
            if relative in previous:
                continue
            try:
                identity = self._storage_source_identity(path)
            except OSError:
                identity = {}
            remote_name = "/".join(part for part in (rclone_path, relative if preserve else path.name) if part)
            pending_item = {
                "path": relative, "name": path.name, "provider": "rclone",
                "target_path": remote_name, "status": "pending", "upload_status": "pending",
                "cleanup_status": "pending" if transfer_mode == "move" else "not_requested",
                "source_identity": identity, "transfer_mode": transfer_mode,
            }
            persist(
                command_id, relative, file_name=path.name, status="pending", attempt=0,
                retryable=False, result_item=pending_item,
            )

        completed = 0
        successes = 0
        skipped = 0
        failures: list[dict[str, Any]] = []
        skipped_items: list[dict[str, Any]] = []
        output_items: list[dict[str, Any]] = []
        previous = {str(item.get("path") or ""): item for item in read_items(command_id) if isinstance(item, dict)}
        file_sizes: list[int | None] = []
        for path in files:
            try:
                file_sizes.append(max(0, int(path.stat().st_size)))
            except OSError:
                file_sizes.append(None)
        total_bytes = (
            sum(size for size in file_sizes if size is not None)
            if all(size is not None for size in file_sizes)
            else None
        )
        completed_bytes: int | None = 0 if total_bytes is not None else None
        reporter = ProgressReporter(self.publisher, job_id)
        reporter.report(phase="uploading", message=f"Menyiapkan {len(files)} file untuk rclone",
                        overall={"current": 0, "total": len(files), "percent": 0, "unit": "files", "bytes_total": total_bytes},
                        counters={"succeeded": 0, "failed": 0, "skipped": 0}, force=True)
        active_file_index = 1

        def cancelled() -> bool:
            return self._job_cancelled(job_id)

        def progress(index: int, total: int, name: str) -> None:
            del index, total
            current_size = file_sizes[active_file_index - 1] if len(file_sizes) == len(files) else None
            batch_bytes = (
                completed_bytes + current_size
                if completed_bytes is not None and current_size is not None
                else None
            )
            percent = (
                batch_bytes * 100 / total_bytes
                if batch_bytes is not None and total_bytes
                else active_file_index * 100 / len(files) if files else 100
            )
            reporter.report(phase="uploading", message=f"Mengupload {name} ke rclone",
                            overall={"current": active_file_index, "total": len(files), "percent": percent,
                                     "unit": "files", "files_current": active_file_index, "files_total": len(files),
                                     "bytes_current": batch_bytes, "bytes_total": total_bytes},
                            item={"name": name, "target_path": name, "index": active_file_index, "total": len(files),
                                  "percent": 100, "size_bytes": current_size},
                            transfer=reporter.transfer_metrics(
                                current_bytes=current_size, total_bytes=current_size, percent=100,
                            ),
                            counters={"succeeded": successes, "failed": len(failures), "skipped": skipped}, force=True)

        def transfer_progress(index: int, path: Path, value: dict[str, object]) -> None:
            current_size = file_sizes[index - 1] if len(file_sizes) == len(files) else None
            try:
                current = max(0, int(value.get("bytes_current") or 0))
            except (TypeError, ValueError):
                current = 0
            try:
                percent = float(value["percent"]) if value.get("percent") is not None else None
            except (TypeError, ValueError):
                percent = None
            batch_bytes = completed_bytes + current if completed_bytes is not None else None
            batch_percent = (
                min(100.0, batch_bytes * 100 / total_bytes)
                if isinstance(batch_bytes, int) and total_bytes
                else ((index - 1) + (percent or 0) / 100) * 100 / len(files)
                if files
                else 100
            )
            reporter.report(
                phase="uploading",
                message=f"Mengupload {path.name} ke rclone",
                overall={
                    "current": index - 1,
                    "total": len(files),
                    "percent": batch_percent,
                    "unit": "files",
                    "files_current": index - 1,
                    "files_total": len(files),
                    "bytes_current": batch_bytes,
                    "bytes_total": total_bytes,
                },
                item={
                    "name": path.name,
                    "target_path": str(value.get("name") or path.name),
                    "index": index,
                    "total": len(files),
                    "percent": percent,
                    "size_bytes": current_size,
                },
                transfer=reporter.transfer_metrics(
                    speed_bps=value.get("speed_bps"),
                    current_bytes=current,
                    total_bytes=current_size,
                    eta_seconds=value.get("eta_seconds"),
                    percent=percent,
                ),
                counters={"succeeded": successes, "failed": len(failures), "skipped": skipped},
            )

        runner = RcloneRunner(log_callback=self._append_job_log, command_callback=self._command_callback(runtime="rclone_storage"),
                              progress_callback=progress, cancel_check=cancelled,
                              stall_timeout_seconds=getattr(self.config, "job_stall_timeout_seconds", 600))
        with self._lock:
            self._rclone_runners[job_id] = runner
        try:
            for index, path in enumerate(files, start=1):
                if cancelled():
                    raise QuickModeError("Upload dibatalkan oleh user.")
                active_file_index = index
                reporter.reset_transfer()
                relative = path.relative_to(root).as_posix()
                remote_name = "/".join(part for part in (rclone_path, relative if preserve else path.name) if part)
                prior = previous.get(relative, {})
                try:
                    attempt = max(1, int(prior.get("attempt") or 0) + 1)
                except (TypeError, ValueError):
                    attempt = 1
                try:
                    identity = self._storage_source_identity(path)
                except OSError:
                    identity = {}
                prior_result = prior.get("uploaded_item") if isinstance(prior.get("uploaded_item"), dict) else {}
                saved_identity = prior_result.get("source_identity") if isinstance(prior_result, dict) else None
                if isinstance(saved_identity, dict):
                    identity = saved_identity

                item = {
                    "path": relative, "name": path.name, "provider": "rclone",
                    "target_path": remote_name, "status": "pending", "upload_status": "pending",
                    "cleanup_status": "pending" if transfer_mode == "move" else "not_requested",
                    "source_identity": identity, "transfer_mode": transfer_mode,
                }

                if prior.get("status") == "succeeded":
                    item.update(prior_result)
                    if transfer_mode == "move" and item.get("cleanup_status") == "pending":
                        item["cleanup_status"] = self._storage_move_cleanup(path, root, identity)
                        persist(command_id, relative, file_name=path.name, status="succeeded", attempt=int(prior.get("attempt") or attempt), retryable=False, result_item=item)
                    successes += 1
                    if completed_bytes is not None and file_sizes[index - 1] is not None:
                        completed_bytes += file_sizes[index - 1]
                    else:
                        completed_bytes = None
                    output_items.append(item)
                    completed += 1
                    continue

                must_verify_only = prior.get("status") in {"sending", "needs_reconciliation"}
                try:
                    target_exists = False if must_verify_only else runner.target_file_exists(
                        str(payload.get("rclone_destination") or ""), remote_name,
                        config_path, config_root=config_root
                    )
                except Exception:
                    target_exists = None
                if target_exists is None:
                    item.update(status="failed", upload_status="failed", cleanup_status="retained_unverified" if transfer_mode == "move" else "not_requested",
                                error_code="RCLONE_ACCESS_FAILED", error="Worker tidak dapat memeriksa tujuan rclone.")
                    persist(command_id, relative, file_name=path.name, status="failed", attempt=attempt,
                            retryable=False, error_code=item["error_code"], error_message=item["error"], result_item=item)
                    failures.append(item); output_items.append(item); completed += 1
                    continue
                if target_exists:
                    item.update(
                        status="skipped",
                        upload_status="skipped",
                        cleanup_status="retained_existing_target" if transfer_mode == "move" else "not_requested",
                        reason_code="STORAGE_TARGET_EXISTS",
                        reason="File dengan nama ini sudah ada di tujuan; file dilewati tanpa menimpa.",
                    )
                    persist(
                        command_id, relative, file_name=path.name, status="skipped",
                        attempt=attempt, retryable=False, result_item=item,
                    )
                    skipped += 1
                    skipped_items.append(item)
                    output_items.append(item)
                    completed += 1
                    reporter.report(
                        phase="uploading",
                        message=f"Melewati {path.name} — sudah ada di tujuan",
                        overall={
                            "current": completed,
                            "total": len(files),
                            "percent": completed * 100 / len(files) if files else 100,
                            "unit": "files",
                            "files_current": completed,
                            "files_total": len(files),
                            "bytes_current": completed_bytes,
                            "bytes_total": total_bytes,
                        },
                        item={
                            "name": path.name,
                            "target_path": remote_name,
                            "index": index,
                            "total": len(files),
                            "status": "skipped",
                        },
                        counters={"succeeded": successes, "failed": len(failures), "skipped": skipped},
                        force=True,
                    )
                    continue

                if not must_verify_only:
                    item.update(status="sending", upload_status="sending")
                    persist(command_id, relative, file_name=path.name, status="sending", attempt=attempt, retryable=False, result_item=item)
                    try:
                        runner.transfer_callback = lambda value, selected_index=index, selected_path=path: transfer_progress(
                            selected_index, selected_path, value
                        )
                        runner.copy_files([path], str(payload.get("rclone_destination") or ""), config_path,
                                          workspace_root=workspace, config_root=config_root,
                                          remote_names=[remote_name], ignore_existing=True)
                        transfer_ok = True
                        transfer_error_code = ""
                        definite_failure = False
                    except RcloneError as exc:
                        transfer_ok = False
                        transfer_error_code = str(exc.code or "")
                        definite_failure = transfer_error_code == "RCLONE_RUNTIME_UNAVAILABLE"
                    except Exception:
                        transfer_ok = False
                        transfer_error_code = ""
                        definite_failure = False
                else:
                    transfer_ok = False
                    transfer_error_code = ""
                    definite_failure = False

                if definite_failure:
                    item.update(
                        status="failed", upload_status="failed",
                        cleanup_status="retained_upload_failed" if transfer_mode == "move" else "not_requested",
                        error_code=transfer_error_code,
                        error="Worker tidak dapat memulai proses rclone; file sumber dipertahankan.",
                    )
                    persist(
                        command_id, relative, file_name=path.name, status="failed",
                        attempt=attempt, retryable=False, error_code=item["error_code"],
                        error_message=item["error"], result_item=item,
                    )
                    failures.append(item)
                    output_items.append(item)
                    completed += 1
                    continue

                if transfer_ok and transfer_mode == "copy" and not must_verify_only:
                    verified = {"complete": True, "verified": [remote_name], "reason_code": ""}
                    confirmed = True
                else:
                    verified = runner.verify_complete_files([path], str(payload.get("rclone_destination") or ""),
                                                            config_path, workspace_root=workspace, config_root=config_root,
                                                            remote_names=[remote_name])
                    confirmed = verified.get("complete") is True

                if confirmed:
                    item.update(status="succeeded", upload_status="succeeded", cleanup_status="pending" if transfer_mode == "move" else "not_requested",
                                verified_full_content=True, error_code="", error="")
                    persist(command_id, relative, file_name=path.name, status="succeeded", attempt=attempt, retryable=False, result_item=item)
                    if transfer_mode == "move":
                        item["cleanup_status"] = self._storage_move_cleanup(path, root, identity)
                        persist(command_id, relative, file_name=path.name, status="succeeded", attempt=attempt, retryable=False, result_item=item)
                    successes += 1
                    if completed_bytes is not None and file_sizes[index - 1] is not None:
                        completed_bytes += file_sizes[index - 1]
                    else:
                        completed_bytes = None
                else:
                    item.update(status="needs_reconciliation", upload_status="needs_reconciliation", cleanup_status="retained_ambiguous" if transfer_mode == "move" else "not_requested",
                                error_code=str(verified.get("reason_code") or "RCLONE_UPLOAD_AMBIGUOUS"),
                                error="Hasil rclone belum dapat dipastikan; file sumber dipertahankan.")
                    persist(command_id, relative, file_name=path.name, status="needs_reconciliation", attempt=attempt,
                            retryable=False, error_code=item["error_code"], error_message=item["error"], result_item=item)
                    failures.append(item)
                output_items.append(item)
                completed += 1
                try:
                    reporter.report(phase="uploading", message=f"Memproses file {completed}/{len(files)}",
                                    overall={"current": completed, "total": len(files), "percent": completed * 100 / len(files) if files else 100,
                                             "unit": "files", "bytes_current": completed_bytes,
                                             "bytes_total": total_bytes},
                                    item={"name": path.name, "target_path": remote_name, "index": index, "total": len(files), "status": item["upload_status"],
                                          "cleanup_status": item["cleanup_status"]},
                                    counters={"succeeded": successes, "failed": len(failures), "skipped": skipped}, force=True)
                except Exception:
                    LOGGER.warning("Could not publish rclone Storage progress for %s", job_id, exc_info=True)
            ambiguous = any(item.get("status") == "needs_reconciliation" or item.get("upload_status") == "needs_reconciliation" for item in failures)
            outcome = "succeeded" if not failures else "partial_failure" if successes or skipped else "needs_reconciliation" if ambiguous else "failed"
            reporter.report(phase=outcome, message=f"rclone selesai: {successes} berhasil, {skipped} dilewati, {len(failures)} belum terkonfirmasi",
                            overall={"current": len(files), "total": len(files), "percent": 100 if files else 100, "unit": "files"},
                            counters={"succeeded": successes, "failed": len(failures), "skipped": skipped}, force=True)
            return {"outcome": outcome, "provider": "rclone", "transfer_mode": transfer_mode,
                    "target_path": rclone_path, "total": len(files), "succeeded": successes,
                    "skipped": skipped, "skipped_items": skipped_items,
                    "failed": failures, "items": output_items, "retryable": False}
        finally:
            with self._lock:
                self._rclone_runners.pop(job_id, None)

    def _storage_sync(self, command: dict[str, Any]) -> dict[str, Any]:
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        profile = str(command.get("profile") or "").strip().lower()
        job_id = str(command.get("job_id") or "")
        try:
            channel_id = int(payload.get("channel_id") or 0)
        except (TypeError, ValueError):
            raise RuntimeError("STORAGE_SYNC_CHANNEL_INVALID") from None
        if not profile or not job_id or channel_id == 0:
            raise RuntimeError("STORAGE_SYNC_REQUEST_INVALID")
        candidate_message_ids = payload.get("_storage_sync_candidate_message_ids", [])
        if not isinstance(candidate_message_ids, list):
            raise RuntimeError("STORAGE_SYNC_CANDIDATES_INVALID")
        runtime = self.profile_manager.runtime(profile)
        runtime_channel_id = int(getattr(runtime.config, "storage_channel_id", 0) or 0)
        if runtime_channel_id != channel_id:
            raise RuntimeError("STORAGE_SYNC_CHANNEL_MISMATCH")
        target = str(
            payload.get("tdl_access_target")
            or getattr(runtime.config, "storage_channel_ref", "")
            or ""
        ).strip()
        if not target:
            raise RuntimeError("TDL_ACCESS_TARGET_UNAVAILABLE")
        client = getattr(runtime, "upload_tdl_client", None)
        exporter = getattr(client, "export_storage_history", None)
        if not callable(exporter):
            raise RuntimeError("WORKER_UPDATE_REQUIRED: TDL Storage sync export belum tersedia.")

        reporter = ProgressReporter(self.publisher, job_id)
        reporter.report(
            phase="exporting",
            message="Mengekspor seluruh riwayat channel Storage",
            indeterminate=True,
            force=True,
        )
        callback = getattr(client, "command_callback", None)

        def report_targeted_verification(current: int, total: int, _message_id: int) -> None:
            if self._job_cancelled(job_id):
                raise RuntimeError("JOB_TERMINATED: Storage sync dibatalkan saat verifikasi pesan.")
            reporter.report(
                phase="verifying_missing",
                message=f"Verifikasi ulang {current} dari {total} pesan katalog yang tidak ditemukan",
                overall={"current": current, "total": total, "unit": "catalog messages"},
                indeterminate=total == 0,
                force=current == 1 or current == total,
            )

        with runtime.upload_operation_lock:
            with tempfile.TemporaryDirectory(prefix="storage-sync-") as temp_dir:
                export_path = Path(temp_dir) / "storage-history.json"
                try:
                    if hasattr(client, "command_callback"):
                        client.command_callback = JobOwnerCommandCallback(job_id)
                    exported = exporter(
                        target,
                        export_path,
                        expected_channel_id=channel_id,
                        candidate_message_ids=candidate_message_ids,
                        verification_callback=report_targeted_verification,
                    )
                finally:
                    if hasattr(client, "command_callback"):
                        client.command_callback = callback

        if int(getattr(exported, "channel_id", 0) or 0) != channel_id:
            raise RuntimeError("STORAGE_SYNC_CHANNEL_MISMATCH")
        parsed = parse_storage_export(getattr(exported, "messages", None))
        total_messages = len(parsed.message_ids)
        batch_size = 250
        batch_count = 0
        if self._job_cancelled(job_id):
            raise RuntimeError("JOB_TERMINATED: Storage sync dibatalkan sebelum apply.")
        recognized_so_far = 0
        for offset in range(0, total_messages, batch_size):
            if self._job_cancelled(job_id):
                raise RuntimeError("JOB_TERMINATED: Storage sync dibatalkan sebelum apply.")
            batch_ids = parsed.message_ids[offset : offset + batch_size]
            id_set = set(batch_ids)
            batch_items = [
                item for item in parsed.items
                if int(item["channel_message_id"]) in id_set
            ]
            recognized_so_far += len(batch_items)
            batch_count += 1
            current = min(offset + len(batch_ids), total_messages)
            self.publisher.emit(
                job_id,
                "running",
                "storage.sync_batch",
                progress={
                    "phase": "applying",
                    "message": "Mencocokkan pesan Telegram dengan katalog Storage",
                    "overall": {"current": current, "total": total_messages, "unit": "messages"},
                },
                result={
                    "channel_id": channel_id,
                    "message_ids": batch_ids,
                    "items": batch_items,
                },
            )
            reporter.report(
                phase="applying",
                message=f"Memproses {current} dari {total_messages} pesan",
                overall={"current": current, "total": total_messages, "unit": "messages"},
                counters={"recognized": recognized_so_far},
                force=True,
            )
        if self._job_cancelled(job_id):
            raise RuntimeError("JOB_TERMINATED: Storage sync dibatalkan sebelum apply.")
        coverage = getattr(exported, "coverage", {})
        history_complete = bool(getattr(exported, "history_complete", False))
        confirmed_missing = list(
            getattr(exported, "confirmed_missing_message_ids", []) or []
        )
        verification_failed = list(
            getattr(exported, "verification_failed_message_ids", []) or []
        )
        reporter.report(
            phase="completed",
            message=(
                "Riwayat channel Storage terbukti lengkap"
                if history_complete
                else (
                    f"Pemeriksaan selesai; {len(confirmed_missing)} pesan dikonfirmasi hilang, "
                    f"{len(verification_failed)} gagal diverifikasi dan row-nya dipertahankan"
                )
            ),
            overall={"current": total_messages, "total": total_messages, "unit": "messages"},
            counters={"recognized": len(parsed.items)},
            force=True,
        )
        return {
            "channel_id": channel_id,
            "messages_scanned": total_messages,
            "items_recognized": len(parsed.items),
            "batch_count": batch_count,
            "history_complete": history_complete,
            "history_coverage": coverage if isinstance(coverage, dict) else {},
            "confirmed_missing_message_ids": confirmed_missing,
            "verification_failed_message_ids": verification_failed,
            "deleted": 0,
            "deletion_held": 0,
        }

    def _storage_upload(
        self,
        command: dict[str, Any],
        *,
        upload_item_callback=None,
    ) -> dict[str, Any]:
        payload = command["payload"]
        if str(payload.get("provider") or "telegram").strip().lower() == "rclone":
            return self._storage_upload_rclone(command, payload, upload_item_callback=upload_item_callback)
        storage_profile = str(command.get("profile") or self.storage_profile()).strip().lower()
        durable_batch = (
            str(command.get("kind") or "") == "storage_upload"
            and bool(command.get("command_id"))
        )
        local_profiles = {
            str(item).strip().lower()
            for item in self.profile_manager.list_profiles()
            if str(item).strip()
        }
        raw_sender_profiles = payload.get("_tdl_sender_profiles")
        preferred_profiles = [
            str(item).strip().lower()
            for item in raw_sender_profiles
            if str(item).strip()
        ] if isinstance(raw_sender_profiles, list) else []
        sender_profiles = list(dict.fromkeys(
            [profile for profile in preferred_profiles if profile in local_profiles]
            + sorted(local_profiles - set(preferred_profiles))
        ))
        if not sender_profiles:
            raise ValueError("PROFILE_SESSION_UNAVAILABLE: worker tidak memiliki profil lokal untuk upload TDL.")
        if storage_profile not in sender_profiles:
            storage_profile = sender_profiles[0]
        sender_runtimes = {
            profile: self.profile_manager.runtime(profile)
            for profile in sender_profiles
        }
        runtime = sender_runtimes.get(storage_profile)
        target_chat = str(
            payload.get("tdl_access_target")
            or (runtime.config.storage_channel_ref if runtime is not None else "")
        ).strip()
        if not target_chat:
            raise ValueError("TDL_ACCESS_TARGET_UNAVAILABLE: tujuan TDL Storage tidak tersedia.")
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
                if path.is_file() and not path.is_symlink()
                and (not allowed_names or path.name in allowed_names)
            )
        else:
            files = sorted(path for path in root.rglob("*") if path.is_file() and not path.is_symlink())
        retry_paths_raw = payload.get("_storage_retry_paths")
        if isinstance(retry_paths_raw, list):
            retry_paths = {
                str(item).replace("\\", "/").strip()
                for item in retry_paths_raw
                if isinstance(item, str) and str(item).strip()
            }
            files = [
                path
                for path in files
                if path.relative_to(root).as_posix() in retry_paths
            ]
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
                "provider": "telegram",
            }
        file_sizes = {path: path.stat().st_size for path in files}
        total_bytes = sum(file_sizes.values())
        failed, succeeded = [], 0
        skipped_items: list[dict[str, Any]] = []
        occupied_targets = {
            str(item).replace("\\", "/").strip("/")
            for item in payload.get("_existing_storage_target_paths", [])
            if isinstance(item, str) and str(item).strip()
        }
        uploaded_items: list[dict[str, Any]] = []
        completed_bytes = 0
        last_message_id: int | None = None
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
        if durable_batch:
            return self._storage_upload_round_robin(
                command,
                payload=payload,
                files=files,
                file_sizes=file_sizes,
                total_bytes=total_bytes,
                root=root,
                preserve_structure=preserve_structure,
                photo_names=photo_names,
                sender_profiles=sender_profiles,
                sender_runtimes=sender_runtimes,
                storage_profile=storage_profile,
                target_chat=target_chat,
                reporter=reporter,
                upload_item_callback=upload_item_callback,
            )
        with self._storage_upload_lane_locks(sender_runtimes):
            if storage_profile not in sender_profiles:
                storage_profile = sender_profiles[0]
                runtime = sender_runtimes[storage_profile]
            with self._capture_storage_upload_output(sender_runtimes):
                for index, path in enumerate(files, start=1):
                    if self._job_cancelled(str(command["job_id"])):
                        raise QuickModeError("Upload dibatalkan oleh user.")
                    size = file_sizes[path]
                    target_path = _storage_upload_target_path(
                        root, path, preserve_structure
                    )
                    if target_path in occupied_targets:
                        completed_bytes += size
                        skipped_item = {
                            "path": path.relative_to(root).as_posix(),
                            "name": path.name,
                            "provider": "telegram",
                            "upload_status": "skipped",
                            "target_path": target_path,
                            "cleanup_status": (
                                "retained_existing_target"
                                if payload.get("transfer_mode") == "move"
                                else "not_requested"
                            ),
                            "reason_code": "STORAGE_TARGET_EXISTS",
                            "reason": "File dengan nama ini sudah ada di folder tujuan; file dilewati tanpa menimpa.",
                        }
                        skipped_items.append(skipped_item)
                        progress_payload = reporter.report(
                            phase="uploading",
                            message=f"Melewati {path.name} — sudah ada di tujuan",
                            overall={
                                "current": index,
                                "total": len(files),
                                "percent": completed_bytes * 100 / total_bytes if total_bytes else 100,
                                "unit": "files",
                                "bytes_current": completed_bytes,
                                "bytes_total": total_bytes,
                            },
                            item={
                                "name": path.name,
                                "path": skipped_item["path"],
                                "target_path": target_path,
                                "index": index,
                                "total": len(files),
                                "size_bytes": size,
                            },
                            counters={
                                "succeeded": succeeded,
                                "failed": len(failed),
                                "skipped": len(skipped_items),
                            },
                            force=True,
                        )
                        reporter.milestone(
                            "storage.item_skipped",
                            progress=progress_payload,
                            result={"item": skipped_item},
                        )
                        continue
                    occupied_targets.add(target_path)
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
                        upload_kwargs = {"status_callback": upload_phase}
                        if last_message_id is not None:
                            # Do not resolve the previous message until this
                            # upload was accepted by Telegram.
                            upload_kwargs["resolve_after_id"] = last_message_id
                        if path.name in photo_names:
                            upload_kwargs["as_photo"] = True
                        result = None
                        for sender_index, sender_profile in enumerate(sender_profiles):
                            sender_runtime = sender_runtimes[sender_profile]
                            try:
                                with self._capture_tdl_progress(
                                    sender_runtime.upload_tdl_client, upload_progress
                                ):
                                    result = sender_runtime.upload_tdl_client.upload(
                                        path,
                                        target_chat,
                                        caption,
                                        **upload_kwargs,
                                    )
                                if sender_profile != storage_profile:
                                    self._append_job_log(
                                        f"[Storage] memakai profil pengirim cadangan={sender_profile} setelah penolakan izin eksplisit"
                                    )
                                    storage_profile = sender_profile
                                    runtime = sender_runtime
                                break
                            except Exception as send_error:
                                denial = tdl_write_denial_code(send_error)
                                session_denial = tdl_session_denial_code(send_error)
                                access_denial = denial or session_denial
                                if access_denial:
                                    self.publisher.emit(
                                        str(command["job_id"]),
                                        "running",
                                        "tdl_access.profile_denied",
                                        result={
                                            "profile": sender_profile,
                                            "error_code": access_denial,
                                        },
                                    )
                                if access_denial and sender_index + 1 < len(sender_profiles):
                                    self._append_job_log(
                                        f"[Storage] profil pengirim ditolak={sender_profile} code={access_denial}; mencoba profil berikutnya"
                                    )
                                    continue
                                code = access_denial or "TDL_UPLOAD_FAILED"
                                raise RuntimeError(
                                    f"{code}: upload Storage tidak berhasil."
                                ) from None
                        if result is None:
                            raise RuntimeError("TDL_WRITE_FORBIDDEN: tidak ada profil yang dapat mengirim.")
                        # Telegram has accepted the file. Failures while
                        # publishing progress or registering the catalog event
                        # must not turn that physical upload into a false failure.
                        physical_upload_succeeded = True
                        last_message_id = int(result.message_id)
                        reporter.report(
                            phase="registering",
                            message=f"Mencatat {path.name}",
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
                        size = int(file_sizes.get(path, 0))
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
                            "sha256": "",
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
                        if self._job_cancelled(str(command["job_id"])):
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
        reporter.report(
            phase="completed",
            message=f"Upload selesai: {succeeded} berhasil, {len(skipped_items)} dilewati, {len(failed)} gagal",
            overall={
                "current": len(files),
                "total": len(files),
                "percent": 100,
                "unit": "files",
                "bytes_current": total_bytes,
                "bytes_total": total_bytes,
            },
            counters={"succeeded": succeeded, "failed": len(failed), "skipped": len(skipped_items)},
            force=True,
        )
        return {
            "total": len(files),
            "succeeded": succeeded,
            "skipped": len(skipped_items),
            "skipped_items": skipped_items,
            "failed": failed,
            "provider": "telegram",
            "uploaded_items": uploaded_items,
        }

    def _storage_download(self, command: dict[str, Any]) -> dict[str, Any]:
        """Download a selected Telegram or rclone batch into Workspace safely."""
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        job_id = str(command.get("job_id") or "")
        provider = str(payload.get("provider") or "").strip().lower()
        if provider not in {"telegram", "rclone"}:
            raise _StorageDownloadFailure("STORAGE_PROVIDER_INVALID", "Sumber unduhan tidak valid.")

        try:
            destination = self._workspace_path(
                str(payload.get("destination_path") or ""), require_absolute=True
            )
        except (OSError, ValueError) as exc:
            raise _StorageDownloadFailure(
                "STORAGE_DOWNLOAD_DESTINATION_INVALID", "Folder tujuan Workspace tidak valid."
            ) from exc
        if not destination.is_dir() or destination.is_symlink():
            raise _StorageDownloadFailure(
                "STORAGE_DOWNLOAD_DESTINATION_INVALID", "Folder tujuan Workspace tidak tersedia."
            )

        if provider == "telegram":
            profile = str(command.get("profile") or "").strip().lower()
            if not profile:
                raise _StorageDownloadFailure("PROFILE_REQUIRED", "Profil Telegram belum dipilih.")
            try:
                runtime = self.profile_manager.runtime(profile)
            except Exception as exc:
                raise _StorageDownloadFailure(
                    "PROFILE_SESSION_UNAVAILABLE", "Lane Download profil tidak tersedia pada worker."
                ) from exc
            target_chat = str(payload.get("tdl_access_target") or "").strip()
            if not target_chat:
                raise _StorageDownloadFailure(
                    "TDL_ACCESS_TARGET_UNAVAILABLE", "Tujuan Telegram Storage tidak tersedia."
                )
            raw_files = payload.get("files")
            files = [item for item in raw_files if isinstance(item, dict)] if isinstance(raw_files, list) else []
            if not files:
                raise _StorageDownloadFailure("STORAGE_SELECTION_EMPTY", "Pilihan tidak berisi file.")
            client = runtime.download_tdl_client
            config_path = None
            config_root = None
        else:
            profile = ""
            runtime = None
            client = None
            raw_sources = payload.get("rclone_sources")
            sources = [item for item in raw_sources if isinstance(item, dict)] if isinstance(raw_sources, list) else []
            if not sources:
                raise _StorageDownloadFailure("STORAGE_SELECTION_EMPTY", "Pilih file atau folder rclone.")
            config_path = Path(
                getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")
            ).resolve()
            config_root = Path(getattr(self.config, "profile_root", "/data")).resolve()
            rclone_destination = str(payload.get("rclone_destination") or "").strip()
            if not rclone_destination:
                raise RcloneError("Root rclone tidak tersedia.", code="RCLONE_RUNTIME_UNAVAILABLE")
            files = []

        reporter = ProgressReporter(self.publisher, job_id)
        rclone_transfer_state: dict[str, Any] = {}

        def report_rclone_transfer(transfer: dict[str, object]) -> None:
            if not rclone_transfer_state:
                return
            index = int(rclone_transfer_state.get("index") or 1)
            transfer_total = int(rclone_transfer_state.get("total") or 1)
            file_name = str(rclone_transfer_state.get("name") or transfer.get("name") or "File")
            size = rclone_transfer_state.get("size")
            try:
                current = max(0, int(transfer.get("bytes_current") or 0))
            except (TypeError, ValueError):
                current = 0
            try:
                percent = float(transfer["percent"]) if transfer.get("percent") is not None else None
            except (TypeError, ValueError):
                percent = None
            completed = int(rclone_transfer_state.get("completed_bytes") or 0)
            batch_bytes = completed + current
            batch_total = rclone_transfer_state.get("total_bytes")
            batch_percent = (
                min(100.0, batch_bytes * 100 / int(batch_total))
                if isinstance(batch_total, int) and batch_total > 0
                else ((index - 1) + (percent or 0) / 100) * 100 / transfer_total
            )
            reporter.report(
                phase="downloading",
                message=f"Mengunduh {file_name} dari rclone",
                overall={
                    "current": index - 1,
                    "total": transfer_total,
                    "percent": batch_percent,
                    "unit": "files",
                    "files_current": index - 1,
                    "files_total": transfer_total,
                    "bytes_current": batch_bytes,
                    "bytes_total": batch_total,
                },
                item={"name": file_name, "index": index, "total": transfer_total, "percent": percent, "size_bytes": size},
                transfer=reporter.transfer_metrics(
                    speed_bps=transfer.get("speed_bps"),
                    current_bytes=current,
                    total_bytes=size if isinstance(size, int) else None,
                    eta_seconds=transfer.get("eta_seconds"),
                    percent=percent,
                ),
                counters={
                    "succeeded": int(rclone_transfer_state.get("succeeded") or 0),
                    "failed": int(rclone_transfer_state.get("failed") or 0),
                },
            )

        if provider == "rclone":
            reporter.report(
                phase="listing",
                message="Membaca file pilihan dari rclone",
                indeterminate=True,
                force=True,
            )
            runner = RcloneRunner(
                log_callback=self._append_job_log,
                command_callback=self._command_callback(runtime="rclone_storage"),
                stall_timeout_seconds=getattr(self.config, "job_stall_timeout_seconds", 600),
                cancel_check=lambda: self._storage_download_cancelled(job_id),
                transfer_callback=report_rclone_transfer,
            )
            with self._lock:
                self._rclone_runners[job_id] = runner
            try:
                files = runner.list_download_files(
                    rclone_destination,
                    sources,
                    config_path,
                    config_root=config_root,
                )
            except RcloneError:
                raise
            except Exception as exc:
                raise RcloneError(
                    "Worker tidak dapat membaca pilihan rclone.", code="RCLONE_ACCESS_FAILED"
                ) from exc
            if not files:
                raise _StorageDownloadFailure(
                    "STORAGE_SELECTION_EMPTY", "Pilihan rclone tidak berisi file."
                )

        if len(files) > 2000:
            raise _StorageDownloadFailure(
                "STORAGE_SELECTION_TOO_LARGE", "Pilihan melebihi batas 2000 file."
            )

        total = len(files)
        file_sizes: list[int | None] = []
        for item in files:
            raw_size = item.get("file_size", item.get("size"))
            file_sizes.append(
                raw_size
                if isinstance(raw_size, int) and not isinstance(raw_size, bool) and raw_size >= 0
                else None
            )
        total_bytes = (
            sum(size for size in file_sizes if size is not None)
            if all(size is not None for size in file_sizes)
            else None
        )
        succeeded = 0
        failed: list[dict[str, Any]] = []
        public_links_failed = 0
        results: list[dict[str, Any]] = []
        processed_indexes: set[int] = set()
        publish_links = payload.get("publish_public_links") is True
        public_base_url = str(payload.get("public_base_url") or "").strip()
        completed_bytes = 0

        reporter.report(
            phase="downloading",
            message=f"Menyiapkan {total} file untuk diunduh",
            overall={"current": 0, "total": total, "percent": 0, "unit": "files", "files_current": 0, "files_total": total, "bytes_total": total_bytes},
            counters={"succeeded": 0, "failed": 0},
            force=True,
        )

        with tempfile.TemporaryDirectory(prefix=".storage-download-", dir=destination) as raw_staging:
            staging_root = Path(raw_staging)
            tdl_lock = runtime.download_operation_lock if provider == "telegram" else None
            lock_held = False
            if tdl_lock is not None:
                tdl_lock.acquire()
                lock_held = True
            previous_callbacks: tuple[Any, Any] | None = None
            if client is not None:
                previous_callbacks = (
                    getattr(client, "output_callback", None),
                    getattr(client, "command_callback", None),
                )
                client.output_callback = None
                client.command_callback = JobOwnerCommandCallback(job_id)
            try:
                for index, item in enumerate(files, start=1):
                    if self._storage_download_cancelled(job_id):
                        break
                    name = str(item.get("name") or "File")[:255]
                    relative = str(item.get("relative_path") or name).replace("\\", "/")
                    raw_parts = relative.split("/")
                    relative_path = PurePosixPath(relative)
                    if (
                        not relative
                        or relative_path.is_absolute()
                        or any(part in {"", ".", ".."} or ":" in part for part in raw_parts)
                        or "\\" in str(item.get("relative_path") or "")
                        or any(ord(char) < 32 for char in relative)
                    ):
                        failed.append({
                            "name": name,
                            "relative_path": relative[:512],
                            "download_status": "failed",
                            "link_status": "not_requested" if not publish_links else "not_created",
                            "error_code": "STORAGE_DOWNLOAD_PATH_INVALID",
                        })
                        results.append(failed[-1])
                        processed_indexes.add(index)
                        continue

                    target = destination.joinpath(*relative_path.parts)
                    stage = staging_root / f"{index:05d}"
                    stage.mkdir(parents=True, exist_ok=True)
                    stage_file: Path | None = None
                    item_error_code = "STORAGE_DOWNLOAD_FILE_FAILED"
                    item_error_message = "File tidak dapat diunduh dari sumber."
                    cancelled_current = False
                    file_size = file_sizes[index - 1]
                    if provider == "rclone":
                        rclone_transfer_state.update(
                            index=index,
                            total=total,
                            name=name,
                            size=file_size,
                            total_bytes=total_bytes,
                            completed_bytes=completed_bytes,
                            succeeded=succeeded,
                            failed=len(failed),
                        )
                        reporter.reset_transfer()
                    reporter.report(
                        phase="downloading",
                        message=f"Mengunduh {name}",
                        overall={
                            "current": index - 1,
                            "total": total,
                            "percent": (index - 1) * 100 / total if total else 100,
                            "unit": "files",
                            "bytes_current": completed_bytes,
                            "bytes_total": total_bytes,
                            "files_current": index - 1,
                            "files_total": total,
                        },
                        item={"name": name, "index": index, "total": total, "percent": None},
                        counters={"succeeded": succeeded, "failed": len(failed)},
                        indeterminate=True,
                        force=True,
                    )
                    try:
                        if provider == "telegram":
                            message_id = int(item.get("channel_message_id") or 0)
                            if message_id < 1:
                                raise _StorageDownloadFailure(
                                    "STORAGE_MESSAGE_ID_INVALID", "ID pesan Telegram katalog tidak valid."
                                )
                            export_path = stage / "selected-message.json"
                            exported = client.export_messages(
                                target_chat,
                                message_id,
                                export_path,
                                with_content=True,
                                end_id=message_id,
                            )
                            message_rows = getattr(exported, "messages", None)
                            if not isinstance(message_rows, list) or not any(
                                isinstance(row, dict)
                                and int(row.get("id") or 0) == message_id
                                and has_downloadable_media(row)
                                for row in message_rows
                            ):
                                raise _StorageDownloadFailure(
                                    "STORAGE_MESSAGE_MEDIA_MISSING", "Pesan Telegram tidak berisi file yang dapat diunduh."
                                )

                            def tdl_progress(progress) -> None:
                                try:
                                    transfer = reporter.tdl_transfer(
                                        progress,
                                        total_bytes=int(item.get("file_size") or 0) or None,
                                    )
                                    reporter.report(
                                        phase="downloading",
                                        message=f"Mengunduh {name}",
                                        overall={
                                            "current": index - 1,
                                            "total": total,
                                            "percent": (index - 1) * 100 / total if total else 100,
                                            "unit": "files",
                                            "bytes_current": completed_bytes,
                                            "bytes_total": total_bytes,
                                        },
                                        item={
                                            "name": name,
                                            "index": index,
                                            "total": total,
                                            "percent": getattr(progress, "percent", None),
                                        },
                                        transfer=transfer,
                                        counters={"succeeded": succeeded, "failed": len(failed)},
                                    )
                                except Exception:
                                    LOGGER.warning("Could not publish Storage download progress for %s", job_id, exc_info=True)

                            with self._capture_tdl_progress(client, tdl_progress):
                                client.download(export_path, stage)
                            media_files = [
                                path for path in stage.iterdir()
                                if path.is_file() and not path.is_symlink() and path.name != export_path.name
                            ]
                            if len(media_files) != 1:
                                raise _StorageDownloadFailure(
                                    "STORAGE_DOWNLOAD_OUTPUT_INVALID", "TDL tidak menghasilkan tepat satu file untuk item ini."
                                )
                            stage_file = media_files[0]
                        else:
                            remote_path = str(item.get("remote_path") or "").strip()
                            if not remote_path:
                                raise RcloneError("Path rclone tidak valid.", code="RCLONE_DOWNLOAD_FAILED")
                            stage_file = stage / "download.part"
                            runner.download_file(
                                remote_path,
                                stage_file,
                                config_path,
                                config_root=config_root,
                                file_name=name,
                                total_bytes=file_size,
                            )
                            if not stage_file.is_file() or stage_file.is_symlink():
                                raise RcloneError("rclone tidak menghasilkan file lokal.", code="RCLONE_DOWNLOAD_FAILED")

                        if self._storage_download_cancelled(job_id):
                            raise _StorageDownloadFailure(
                                "JOB_CANCELLED", "Unduhan dihentikan oleh operator."
                            )
                        current_parent = destination
                        for part in relative_path.parts[:-1]:
                            current_parent = current_parent / part
                            if current_parent.is_symlink():
                                raise _StorageDownloadFailure(
                                    "STORAGE_DOWNLOAD_PATH_UNSAFE", "Folder tujuan berisi symbolic link."
                                )
                            current_parent.mkdir(exist_ok=True)
                            if not current_parent.is_dir():
                                raise _StorageDownloadFailure(
                                    "STORAGE_DOWNLOAD_PATH_UNSAFE", "Path tujuan bukan folder."
                                )
                        if target.is_symlink() or target.exists():
                            raise FileExistsError
                        try:
                            os.link(stage_file, target)
                        except FileExistsError:
                            raise
                        except OSError:
                            # Exclusive creation is a safe fallback on filesystems
                            # that do not support hard links.
                            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                            try:
                                with os.fdopen(descriptor, "wb") as output, stage_file.open("rb") as source:
                                    shutil.copyfileobj(source, output, length=1024 * 1024)
                            except Exception:
                                target.unlink(missing_ok=True)
                                raise
                        actual_size = target.stat().st_size
                        completed_bytes += actual_size
                        succeeded += 1
                        if provider == "rclone":
                            rclone_transfer_state.update(
                                completed_bytes=completed_bytes,
                                succeeded=succeeded,
                                failed=len(failed),
                            )
                            reporter.report(
                                phase="downloading",
                                message=f"File {name} selesai diunduh",
                                overall={
                                    "current": index,
                                    "total": total,
                                    "percent": (
                                        completed_bytes * 100 / total_bytes
                                        if total_bytes
                                        else index * 100 / total if total else 100
                                    ),
                                    "unit": "files",
                                    "files_current": index,
                                    "files_total": total,
                                    "bytes_current": completed_bytes,
                                    "bytes_total": total_bytes,
                                },
                                item={"name": name, "index": index, "total": total, "percent": 100, "size_bytes": file_size},
                                transfer=reporter.transfer_metrics(
                                    current_bytes=actual_size,
                                    total_bytes=file_size,
                                    percent=100,
                                ),
                                counters={"succeeded": succeeded, "failed": len(failed)},
                                force=True,
                            )
                        record: dict[str, Any] = {
                            "name": name,
                            "relative_path": relative_path.as_posix(),
                            "download_status": "succeeded",
                            "size": actual_size,
                            "link_status": "not_requested" if not publish_links else "failed",
                        }
                        if publish_links:
                            try:
                                link = self.create_storage_download_link(
                                    str(target),
                                    public_base_url=public_base_url,
                                    job_id=job_id,
                                    provider=provider,
                                )
                                record.update(
                                    link_status="succeeded",
                                    public_url=f"{str(link['public_base_url']).rstrip('/')}/public/download/{link['token']}",
                                    public_link_id=str(link["id"]),
                                )
                            except Exception:
                                public_links_failed += 1
                                record.update(
                                    link_status="failed",
                                    link_error_code="PUBLIC_DOWNLOAD_CREATE_FAILED",
                                )
                        results.append(record)
                    except FileExistsError:
                        if self._storage_download_cancelled(job_id):
                            cancelled_current = True
                        else:
                            item_error_code = "STORAGE_DOWNLOAD_CONFLICT"
                            item_error_message = "File tujuan sudah ada; file tidak ditimpa."
                    except RcloneError as exc:
                        if self._storage_download_cancelled(job_id):
                            cancelled_current = True
                        else:
                            item_error_code = exc.code or "RCLONE_DOWNLOAD_FAILED"
                            item_error_message = "File gagal diunduh dari rclone."
                            if item_error_code in {"RCLONE_RUNTIME_UNAVAILABLE", "RCLONE_ACCESS_FAILED"}:
                                raise
                    except _StorageDownloadFailure as exc:
                        if self._storage_download_cancelled(job_id):
                            cancelled_current = True
                        else:
                            item_error_code = exc.code
                            item_error_message = str(exc)
                            if item_error_code in {
                                "PROFILE_SESSION_UNAVAILABLE",
                                "TDL_ACCESS_TARGET_UNAVAILABLE",
                            }:
                                raise
                    except Exception as exc:
                        if self._storage_download_cancelled(job_id):
                            cancelled_current = True
                        else:
                            item_error_code = (
                                tdl_session_denial_code(exc)
                                or "STORAGE_DOWNLOAD_FILE_FAILED"
                            )
                            if item_error_code != "STORAGE_DOWNLOAD_FILE_FAILED":
                                raise _StorageDownloadFailure(
                                    item_error_code,
                                    "Sesi Telegram atau akses channel tidak lagi siap.",
                                ) from exc
                    else:
                        processed_indexes.add(index)
                        reporter.milestone(
                            "storage.download_item_completed",
                            progress={
                                "phase": "downloading",
                                "overall": {"current": index, "total": total, "unit": "files"},
                                "item": {"name": name, "index": index, "total": total, "percent": 100},
                                "counters": {"succeeded": succeeded, "failed": len(failed)},
                            },
                            result={"name": name, "download_status": "succeeded"},
                        )
                        continue

                    if cancelled_current:
                        results.append({
                            "name": name,
                            "relative_path": relative_path.as_posix(),
                            "download_status": "cancelled",
                            "link_status": "not_created" if publish_links else "not_requested",
                        })
                        processed_indexes.add(index)
                        break

                    failed_item = {
                        "name": name,
                        "relative_path": relative_path.as_posix(),
                        "download_status": "failed",
                        "link_status": "not_created" if publish_links else "not_requested",
                        "error_code": item_error_code,
                        "error": item_error_message,
                    }
                    failed.append(failed_item)
                    results.append(failed_item)
                    processed_indexes.add(index)
                    reporter.milestone(
                        "storage.download_item_failed",
                        progress={
                            "phase": "downloading",
                            "overall": {"current": index, "total": total, "unit": "files"},
                            "item": {"name": name, "index": index, "total": total},
                            "counters": {"succeeded": succeeded, "failed": len(failed)},
                        },
                        error={"code": item_error_code, "message": item_error_message},
                    )
            finally:
                if client is not None and previous_callbacks is not None:
                    client.output_callback, client.command_callback = previous_callbacks
                if lock_held:
                    tdl_lock.release()

        cancelled = self._storage_download_cancelled(job_id)
        if cancelled:
            for index, item in enumerate(files, start=1):
                if index in processed_indexes:
                    continue
                name = str(item.get("name") or "File")[:255]
                relative = str(item.get("relative_path") or name).replace("\\", "/")
                results.append({
                    "name": name,
                    "relative_path": relative[:512],
                    "download_status": "cancelled",
                    "link_status": "not_created" if publish_links else "not_requested",
                })
        cancelled_items = sum(
            1 for item in results if item.get("download_status") == "cancelled"
        )
        if provider == "rclone":
            with self._lock:
                self._rclone_runners.pop(job_id, None)
        outcome = (
            "partial_failure" if failed and succeeded
            else "failed" if failed
            else "succeeded"
        )
        reporter.report(
            phase="cancelled" if cancelled else "completed",
            message=(
                f"Dibatalkan: {succeeded} file selesai, {len(failed)} gagal"
                if cancelled
                else f"Unduhan selesai: {succeeded} berhasil, {len(failed)} gagal"
            ),
            overall={
                "current": succeeded + len(failed) + cancelled_items,
                "total": total,
                "percent": (succeeded + len(failed) + cancelled_items) * 100 / total if total else 100,
                "unit": "files",
                "bytes_current": completed_bytes,
                "bytes_total": total_bytes,
            },
            counters={"succeeded": succeeded, "failed": len(failed), "cancelled": cancelled_items},
            force=True,
        )
        return {
            "outcome": outcome,
            "provider": provider,
            "total": total,
            "succeeded": succeeded,
            "failed": len(failed),
            "cancelled_items": cancelled_items,
            "public_links_failed": public_links_failed,
            "cancelled": cancelled,
            "items": results,
        }

    def _storage_download_cancelled(self, job_id: str) -> bool:
        return self._job_cancelled(job_id)

    def _storage_upload_round_robin(
        self,
        command: dict[str, Any],
        *,
        payload: dict[str, Any],
        files: list[Path],
        file_sizes: dict[Path, int],
        total_bytes: int,
        root: Path,
        preserve_structure: bool,
        photo_names: set[str],
        sender_profiles: list[str],
        sender_runtimes: dict[str, Any],
        storage_profile: str,
        target_chat: str,
        reporter: ProgressReporter,
        upload_item_callback=None,
    ) -> dict[str, Any]:
        """Run one durable file at a time and rotate through Upload profiles."""
        job_id = str(command["job_id"])
        command_id = str(command["command_id"])
        command_store = getattr(self, "command_store", None)
        persist_item = getattr(command_store, "record_storage_upload_item", None)
        read_items = getattr(command_store, "storage_upload_items", None)
        if not callable(persist_item) or not callable(read_items):
            raise RuntimeError("STORAGE_CHECKPOINT_UNAVAILABLE: worker tidak dapat menyimpan hasil per file.")

        raw_attempts = payload.get("_storage_file_attempts")
        raw_attempts = raw_attempts if isinstance(raw_attempts, dict) else {}
        base_attempts: dict[str, int] = {}
        for path in files:
            relative = path.relative_to(root).as_posix()
            try:
                base_attempts[relative] = max(0, int(raw_attempts.get(relative) or 0))
            except (TypeError, ValueError):
                base_attempts[relative] = 0
        metadata: dict[str, int] = {}
        source_identities: dict[str, dict[str, int]] = {}
        results_lock = threading.RLock()
        progress_lock = threading.RLock()
        checkpoint_lock = threading.RLock()
        lanes_lock = threading.RLock()
        outcomes: dict[str, dict[str, Any]] = {}
        uploaded_by_path: dict[str, dict[str, Any]] = {}
        active_lanes = set(sender_profiles)
        last_message_id_by_profile: dict[str, int] = {}
        active_bytes: dict[str, int] = {}
        file_indexes = {
            path.relative_to(root).as_posix(): index
            for index, path in enumerate(files, start=1)
        }
        file_paths_by_relative = {
            path.relative_to(root).as_posix(): path for path in files
        }
        completed_bytes = 0
        completed_files = 0
        succeeded = 0
        failed_count = 0
        skipped_count = 0
        in_flight = 0
        active_items: dict[str, dict[str, Any]] = {}
        next_sender: str | None = sender_profiles[0] if sender_profiles else None
        priority_task: dict[str, Any] | None = None
        lane_condition = threading.Condition(lanes_lock)

        def next_active_sender(profile: str) -> str | None:
            if not active_lanes:
                return None
            try:
                start = sender_profiles.index(profile)
            except ValueError:
                start = -1
            for offset in range(1, len(sender_profiles) + 1):
                candidate = sender_profiles[(start + offset) % len(sender_profiles)]
                if candidate in active_lanes:
                    return candidate
            return None

        def persist(
            path: str,
            name: str,
            *,
            status: str,
            attempt: int,
            profile: str = "",
            retryable: bool = False,
            error_code: str = "",
            error_message: str = "",
            message_id: int | None = None,
            caption: str | None = None,
            result_item: dict[str, Any] | None = None,
        ) -> None:
            persist_item(
                command_id,
                path,
                file_name=name,
                status=status,
                attempt=attempt,
                profile=profile,
                retryable=retryable,
                error_code=error_code,
                error_message=error_message,
                message_id=message_id,
                caption=caption,
                result_item=result_item,
            )

        # Capture only filesystem metadata before sending. TDL streams file
        # contents; pre-hashing the whole batch delays every upload.
        tasks: deque[dict[str, Any]] = deque()
        skipped_tasks: list[dict[str, Any]] = []
        occupied_targets = {
            str(item).replace("\\", "/").strip("/")
            for item in payload.get("_existing_storage_target_paths", [])
            if isinstance(item, str) and str(item).strip()
        }
        for path in files:
            relative = path.relative_to(root).as_posix()
            base_attempt = base_attempts[relative]
            persist(
                relative,
                path.name,
                status="pending",
                attempt=base_attempt,
                retryable=True,
            )
            try:
                identity = self._storage_source_identity(path)
                size = identity["size"]
                metadata[relative] = size
                source_identities[relative] = identity
                file_sizes[path] = size
                target_path = _storage_upload_target_path(
                    root, path, preserve_structure
                )
                task = {
                    "path": path,
                    "relative": relative,
                    "target_path": target_path,
                    "attempt": base_attempt + 1,
                }
                if target_path in occupied_targets:
                    task["attempt"] = base_attempt
                    skipped_tasks.append(task)
                else:
                    occupied_targets.add(target_path)
                    tasks.append(task)
            except Exception:
                persist(
                    relative,
                    path.name,
                    status="failed",
                    attempt=base_attempt,
                    retryable=True,
                    error_code="STORAGE_FILE_UNREADABLE",
                    error_message="File tidak dapat dibaca sebelum dikirim.",
                )
                with results_lock:
                    completed_files += 1
                    completed_bytes += int(file_sizes.get(path, 0))
                    failed_count += 1
                    outcomes[relative] = {
                        "path": relative,
                        "name": path.name,
                        "status": "failed",
                        "attempt": base_attempt,
                        "profile": "",
                        "retryable": True,
                        "error_code": "STORAGE_FILE_UNREADABLE",
                        "error": "File tidak dapat dibaca sebelum dikirim.",
                        "attempts": [],
                    }

        def report_progress(
            *,
            phase: str,
            message: str,
            relative: str | None = None,
            name: str | None = None,
            profile: str | None = None,
            attempt: int | None = None,
            item_percent: float | None = None,
            transfer: dict[str, Any] | None = None,
            force: bool = False,
        ) -> dict[str, Any]:
            item: dict[str, Any] = {}
            if name is not None:
                item["name"] = name
            if relative is not None:
                item["path"] = relative
            if profile is not None:
                item["lane"] = profile
            if attempt is not None:
                item["attempt"] = attempt
            if item_percent is not None:
                item["percent"] = item_percent
            if relative is not None:
                selected_path = file_paths_by_relative.get(relative)
                item["index"] = file_indexes.get(relative, 0)
                item["total"] = len(files)
                item["size_bytes"] = file_sizes.get(selected_path, 0) if selected_path else 0
            with progress_lock:
                with results_lock:
                    active_item = active_items.get(relative) if relative is not None else None
                    if active_item is not None:
                        if name is not None:
                            active_item["name"] = name
                        if profile is not None:
                            active_item["profile"] = profile
                        if attempt is not None:
                            active_item["attempt"] = attempt
                        active_item["phase"] = phase
                        if item_percent is not None:
                            active_item["percent"] = item_percent
                        if transfer is not None:
                            for key in ("bytes_current", "bytes_total", "speed_bps", "eta_seconds"):
                                value = transfer.get(key)
                                if value is not None:
                                    active_item[key] = value
                    current = completed_files
                    current_bytes = completed_bytes + sum(active_bytes.values())
                    success_count = succeeded
                    failure_count = failed_count
                    skipped_total = skipped_count
                    active_items_snapshot = sorted(
                        (dict(active) for active in active_items.values()),
                        key=lambda active: (
                            str(active.get("profile") or ""),
                            str(active.get("name") or ""),
                        ),
                    )
                overall = {
                    "current": current,
                    "total": len(files),
                    "percent": current_bytes * 100 / total_bytes if total_bytes else 100,
                    "unit": "files",
                    "bytes_current": min(total_bytes, current_bytes),
                    "bytes_total": total_bytes,
                }
                return reporter.report(
                    phase=phase,
                    message=message,
                    overall=overall,
                    item=item,
                    transfer=transfer,
                    counters={
                        "succeeded": success_count,
                        "failed": failure_count,
                        "skipped": skipped_total,
                    },
                    extra={"active_items": active_items_snapshot},
                    force=force,
                    indeterminate=item_percent is None and phase in {"sending", "resolving_message"},
                )

        def finish_item(
            task: dict[str, Any],
            *,
            status: str,
            profile: str,
            retryable: bool,
            error_code: str = "",
            error_message: str = "",
            message_id: int | None = None,
            uploaded_item: dict[str, Any] | None = None,
        ) -> None:
            nonlocal completed_bytes, completed_files, succeeded, failed_count, skipped_count
            path = task["path"]
            relative = task["relative"]
            attempt = int(task.get("attempt") or 0)
            if status == "skipped":
                cleanup_status = (
                    "retained_existing_target"
                    if payload.get("transfer_mode") == "move"
                    else "not_requested"
                )
                uploaded_item = {
                    "path": relative,
                    "name": path.name,
                    "provider": "telegram",
                    "upload_status": "skipped",
                    "target_path": str(task.get("target_path") or relative),
                    "cleanup_status": cleanup_status,
                    "reason_code": error_code or "STORAGE_TARGET_EXISTS",
                    "reason": error_message or "File dengan nama ini sudah ada di folder tujuan; file dilewati tanpa menimpa.",
                    "source_identity": source_identities.get(relative, {}),
                }
            elif status == "succeeded" and uploaded_item is not None:
                uploaded_item = {
                    **uploaded_item, "provider": "telegram", "upload_status": "succeeded",
                    "cleanup_status": "pending" if payload.get("transfer_mode") == "move" else "not_requested",
                    "source_identity": source_identities.get(relative, {}),
                }
            elif payload.get("transfer_mode") == "move":
                uploaded_item = {
                    "path": relative, "name": path.name, "provider": "telegram",
                    "upload_status": status,
                    "cleanup_status": "retained_ambiguous" if status == "needs_reconciliation" else "retained_upload_failed",
                    "source_identity": source_identities.get(relative, {}),
                }
            persist(
                relative,
                path.name,
                status=status,
                attempt=attempt,
                profile=profile,
                retryable=retryable,
                error_code=error_code,
                error_message=error_message,
                message_id=message_id,
                result_item=uploaded_item,
            )
            cleanup_status = "not_requested"
            if status == "skipped" and isinstance(uploaded_item, dict):
                cleanup_status = str(uploaded_item.get("cleanup_status") or cleanup_status)
            if status == "succeeded" and payload.get("transfer_mode") == "move" and uploaded_item is not None:
                cleanup_status = self._storage_move_cleanup(
                    path, root, source_identities.get(relative, {})
                )
                uploaded_item = {**uploaded_item, "cleanup_status": cleanup_status}
                persist(
                    relative, path.name, status=status, attempt=attempt, profile=profile,
                    retryable=retryable, message_id=message_id, result_item=uploaded_item,
                )
            with results_lock:
                active_bytes.pop(relative, None)
                active_items.pop(relative, None)
                completed_files += 1
                completed_bytes += int(file_sizes.get(path, 0))
                if status == "succeeded":
                    succeeded += 1
                elif status == "skipped":
                    skipped_count += 1
                else:
                    failed_count += 1
                outcome: dict[str, Any] = {
                    "path": relative,
                    "name": path.name,
                    "status": status,
                    "attempt": attempt,
                    "profile": profile,
                    "retryable": bool(retryable),
                    "error_code": error_code,
                    "error": error_message,
                    "reason_code": error_code if status == "skipped" else "",
                    "reason": error_message if status == "skipped" else "",
                    "message_id": message_id,
                    "attempts": [],
                    "upload_status": status,
                    "cleanup_status": cleanup_status if status in {"succeeded", "skipped"} else (
                        "retained_ambiguous" if status == "needs_reconciliation" and payload.get("transfer_mode") == "move"
                        else "retained_upload_failed" if payload.get("transfer_mode") == "move"
                        else "not_requested"
                    ),
                    "source_identity": source_identities.get(relative, {}),
                }
                outcomes[relative] = outcome
                if status == "succeeded" and uploaded_item is not None:
                    uploaded_by_path[relative] = dict(uploaded_item)
            if status == "skipped" and isinstance(uploaded_item, dict):
                try:
                    self.publisher.emit(
                        job_id,
                        "running",
                        "storage.item_skipped",
                        result={"item": uploaded_item, "file": outcome},
                    )
                except Exception:
                    LOGGER.warning(
                        "Storage file %s was skipped but its item event could not be queued",
                        path.name,
                        exc_info=True,
                    )

        for task in skipped_tasks:
            finish_item(
                task,
                status="skipped",
                profile="",
                retryable=False,
                error_code="STORAGE_TARGET_EXISTS",
                error_message="File dengan nama ini sudah ada di folder tujuan; file dilewati tanpa menimpa.",
            )

        def worker_for_lane(profile: str) -> None:
            nonlocal in_flight, next_sender, priority_task
            runtime = sender_runtimes[profile]
            client = runtime.upload_tdl_client
            while True:
                with lane_condition:
                    while True:
                        if profile not in active_lanes:
                            return
                        if in_flight == 0 and priority_task is None and not tasks:
                            return
                        if in_flight == 0 and profile == next_sender:
                            if priority_task is not None:
                                task = priority_task
                                priority_task = None
                            else:
                                task = tasks.popleft()
                            in_flight += 1
                            break
                        lane_condition.wait()
                path = task["path"]
                relative = task["relative"]
                attempt = int(task["attempt"])
                try:
                    if self._job_cancelled(job_id):
                        return
                    with lane_condition:
                        if profile not in active_lanes:
                            tasks.appendleft(task)
                            lane_condition.notify_all()
                            return
                    size = metadata[relative]
                    base_folder = str(
                        payload.get("destination_folder_path") or payload.get("folder") or ""
                    )
                    logical_folder, relative_parent = storage_logical_folder(
                        root, path, base_folder, preserve_structure
                    )
                    upload_id = str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"tme3bot:{payload['batch_id']}:{relative}",
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
                    persist(
                        relative,
                        path.name,
                        status="sending",
                        attempt=attempt,
                        profile=profile,
                        retryable=False,
                        caption=caption,
                    )
                    with results_lock:
                        active_items[relative] = {
                            "name": path.name,
                            "profile": profile,
                            "attempt": attempt,
                            "phase": "uploading",
                            "percent": 0,
                            "size_bytes": size,
                            "bytes_current": 0,
                        }
                    progress = report_progress(
                        phase="uploading",
                        message=f"Mengupload {path.name} melalui lane Upload {profile}",
                        relative=relative,
                        name=path.name,
                        profile=profile,
                        attempt=attempt,
                        item_percent=0,
                        force=True,
                    )
                    with progress_lock:
                        reporter.milestone(
                            "storage.item_started",
                            progress=progress,
                            result={
                                "item": {
                                    "path": relative,
                                    "name": path.name,
                                    "profile": profile,
                                    "attempt": attempt,
                                }
                            },
                        )
                    phase_state = {"value": "preparing"}

                    def status_callback(phase: str) -> None:
                        mapped = {
                            "uploading": "sending",
                            "resolving_message": "resolving",
                            "uploaded": "accepted",
                        }.get(str(phase), "sending")
                        phase_state["value"] = mapped
                        persist(
                            relative,
                            path.name,
                            status=mapped,
                            attempt=attempt,
                            profile=profile,
                            retryable=False,
                        )
                        if mapped == "resolving":
                            report_progress(
                                phase="resolving_message",
                                message=f"Menunggu konfirmasi Telegram untuk {path.name}",
                                relative=relative,
                                name=path.name,
                                profile=profile,
                                attempt=attempt,
                                force=True,
                            )

                    def transfer_progress(progress_value) -> None:
                        if not _has_transfer_telemetry(progress_value):
                            return
                        with progress_lock:
                            transfer = reporter.tdl_transfer(progress_value, total_bytes=size)
                        current_bytes = int(transfer.get("bytes_current") or 0)
                        with results_lock:
                            active_bytes[relative] = current_bytes
                        report_progress(
                            phase="uploading",
                            message=f"Mengupload {path.name} melalui lane Upload {profile}",
                            relative=relative,
                            name=path.name,
                            profile=profile,
                            attempt=attempt,
                            item_percent=progress_value.percent,
                            transfer=transfer,
                        )

                    upload_kwargs: dict[str, Any] = {"status_callback": status_callback}
                    if path.name in photo_names:
                        upload_kwargs["as_photo"] = True
                    resolve_after_id = last_message_id_by_profile.get(profile)
                    if resolve_after_id is not None:
                        upload_kwargs["resolve_after_id"] = resolve_after_id
                    try:
                        with runtime.upload_operation_lock:
                            with self._capture_tdl_output(
                                client,
                                command_callback=self._command_callback(
                                    profile=profile, runtime="upload"
                                ),
                            ):
                                with self._capture_tdl_progress(client, transfer_progress):
                                    uploaded = client.upload(
                                        path,
                                        target_chat,
                                        caption,
                                        **upload_kwargs,
                                    )
                    except Exception as send_error:
                        denial = tdl_write_denial_code(send_error)
                        session_denial = tdl_session_denial_code(send_error)
                        access_denial = denial or session_denial
                        if access_denial:
                            try:
                                self.publisher.emit(
                                    job_id,
                                    "running",
                                    "tdl_access.profile_denied",
                                    result={
                                        "profile": profile,
                                        "error_code": access_denial,
                                    },
                                )
                            except Exception:
                                LOGGER.warning(
                                    "Could not publish Storage lane denial for %s",
                                    profile,
                                    exc_info=True,
                                )
                            denied_message = "Telegram menolak izin atau sesi lane Upload ini."
                            persist(
                                relative,
                                path.name,
                                status="failed",
                                attempt=attempt,
                                profile=profile,
                                retryable=True,
                                error_code=access_denial,
                                error_message=denied_message,
                            )
                            with lane_condition:
                                active_lanes.discard(profile)
                                has_alternative = bool(active_lanes)
                                if has_alternative:
                                    priority_task = {**task, "attempt": attempt + 1}
                                    next_sender = next_active_sender(profile)
                                else:
                                    next_sender = None
                                lane_condition.notify_all()
                            if has_alternative:
                                persist(
                                    relative,
                                    path.name,
                                    status="pending",
                                    attempt=attempt + 1,
                                    retryable=True,
                                    error_code=access_denial,
                                    error_message=denied_message,
                                )
                                with results_lock:
                                    active_items.pop(relative, None)
                                    active_bytes.pop(relative, None)
                                report_progress(
                                    phase="uploading",
                                    message=f"Memindahkan {path.name} ke lane Upload lain",
                                    force=True,
                                )
                            else:
                                finish_item(
                                    task,
                                    status="failed",
                                    profile=profile,
                                    retryable=True,
                                    error_code=access_denial,
                                    error_message=denied_message,
                                )
                            return
                        # TDLDataError can also mean Telegram accepted the upload
                        # but TDL could not resolve its message ID. Only a failure
                        # before TDL signals that upload has started is safe to retry.
                        definitely_not_sent = phase_state["value"] == "preparing"
                        status = "failed" if definitely_not_sent else "needs_reconciliation"
                        code = "TDL_UPLOAD_FAILED" if definitely_not_sent else "STORAGE_UPLOAD_AMBIGUOUS"
                        message = (
                            "Upload gagal sebelum Telegram menerima file."
                            if definitely_not_sent
                            else "Hasil kirim belum dapat dipastikan; file perlu rekonsiliasi sebelum Retry."
                        )
                        finish_item(
                            task,
                            status=status,
                            profile=profile,
                            retryable=definitely_not_sent,
                            error_code=code,
                            error_message=message,
                        )
                        progress = report_progress(
                            phase=status,
                            message=f"Upload {path.name} perlu ditinjau",
                            relative=relative,
                            name=path.name,
                            profile=profile,
                            attempt=attempt,
                            force=True,
                        )
                        with progress_lock:
                            reporter.milestone(
                                "storage.item_failed",
                                progress=progress,
                                error={
                                    "code": code,
                                    "message": message,
                                    "item": path.name,
                                },
                                result={
                                    "item": {
                                        "path": relative,
                                        "name": path.name,
                                        "status": status,
                                        "attempt": attempt,
                                        "profile": profile,
                                        "retryable": definitely_not_sent,
                                    }
                                },
                            )
                        continue

                    message_id = int(uploaded.message_id)
                    last_message_id_by_profile[profile] = message_id
                    item = {
                        "upload_id": upload_id,
                        "owner_user_id": int(payload["owner_user_id"]),
                        "owner_profile": str(payload["owner_profile"]),
                        "channel_id": runtime.config.storage_channel_id,
                        "channel_message_id": message_id,
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
                        "sha256": "",
                        "status": "active",
                        "uploaded_at": None,
                    }
                    finish_item(
                        task,
                        status="succeeded",
                        profile=profile,
                        retryable=False,
                        message_id=message_id,
                        uploaded_item=item,
                    )
                    if callable(upload_item_callback):
                        # Quick Mode uses this hook to persist physical Telegram
                        # evidence after each accepted file before the next item.
                        with checkpoint_lock:
                            with results_lock:
                                checkpoint_items = [
                                    dict(uploaded_by_path[relative_path])
                                    for relative_path in sorted(uploaded_by_path)
                                ]
                            try:
                                upload_item_callback(checkpoint_items)
                            except Exception:
                                LOGGER.warning(
                                    "Could not checkpoint Storage upload item for %s",
                                    path.name,
                                    exc_info=True,
                                )
                    progress = report_progress(
                        phase="registering",
                        message=f"{path.name} selesai diupload",
                        relative=relative,
                        name=path.name,
                        profile=profile,
                        attempt=attempt,
                        item_percent=100,
                        force=True,
                    )
                    try:
                        self.publisher.emit(
                            job_id,
                            "running",
                            "storage.item_uploaded",
                            progress=progress,
                            result={"item": item, "file": outcomes.get(relative)},
                        )
                    except Exception:
                        LOGGER.warning(
                            "Storage upload succeeded but its item event could not be queued for %s",
                            path.name,
                            exc_info=True,
                        )
                finally:
                    with lane_condition:
                        in_flight -= 1
                        next_sender = next_active_sender(profile)
                        lane_condition.notify_all()

        with ThreadPoolExecutor(
            max_workers=max(1, len(sender_profiles)),
            thread_name_prefix=f"storage-{job_id[:8]}",
        ) as pool:
            futures = [pool.submit(worker_for_lane, profile) for profile in sender_profiles]
            for future in futures:
                future.result()

        # If every verified lane was rejected or rotated, the files still in
        # the FIFO are known not to have been attempted and can be retried.
        while priority_task is not None or tasks:
            task = priority_task if priority_task is not None else tasks.popleft()
            priority_task = None
            path = task["path"]
            relative = task["relative"]
            attempt = int(task["attempt"])
            finish_item(
                task,
                status="failed",
                profile="",
                retryable=True,
                error_code="STORAGE_UPLOAD_NO_LANE_AVAILABLE",
                error_message="Tidak ada lane Upload siap untuk file ini; Telegram belum menerima file.",
            )

        result_items_raw = read_items(command_id)
        result_items = []
        for item in result_items_raw:
            result_item = {
                key: item.get(key)
                for key in (
                    "path", "name", "status", "attempt", "profile", "retryable",
                    "error_code", "error", "message_id", "attempts",
                )
            }
            uploaded_item = item.get("uploaded_item")
            if item.get("status") == "skipped" and isinstance(uploaded_item, dict):
                result_item.update({
                    "reason_code": str(item.get("error_code") or "STORAGE_TARGET_EXISTS"),
                    "reason": str(item.get("error") or "File sudah ada di folder tujuan."),
                    "target_path": uploaded_item.get("target_path"),
                    "cleanup_status": uploaded_item.get("cleanup_status"),
                })
            result_items.append(result_item)
        result_items.sort(key=lambda item: str(item.get("path") or ""))
        uploaded_items = [
            uploaded_by_path[relative]
            for relative in sorted(uploaded_by_path)
        ]
        file_succeeded = sum(item.get("status") == "succeeded" for item in result_items)
        file_skipped = sum(item.get("status") == "skipped" for item in result_items)
        failure_items = [
            item
            for item in result_items
            if item.get("status") in {"failed", "needs_reconciliation"}
        ]
        has_ambiguous = any(item.get("status") == "needs_reconciliation" for item in failure_items)
        retryable = any(
            item.get("retryable") is True and item.get("status") in {"pending", "failed"}
            for item in result_items
        )
        if not failure_items:
            outcome = "succeeded"
        elif file_succeeded:
            outcome = "partial_failure"
        elif has_ambiguous:
            outcome = "needs_reconciliation"
        else:
            outcome = "failed"

        reporter.report(
            phase=outcome,
            message=f"Upload selesai: {file_succeeded} berhasil, {file_skipped} dilewati, {len(failure_items)} belum berhasil",
            overall={
                "current": len(result_items),
                "total": len(files),
                "percent": 100,
                "unit": "files",
                "bytes_current": total_bytes,
                "bytes_total": total_bytes,
            },
            counters={"succeeded": file_succeeded, "failed": len(failure_items), "skipped": file_skipped},
            force=True,
        )
        return {
            "outcome": outcome,
            "total": len(result_items),
            "succeeded": file_succeeded,
            "skipped": file_skipped,
            "failed": failure_items,
            "items": result_items,
            "retryable": retryable,
            "provider": "telegram",
            "uploaded_items": uploaded_items,
        }
