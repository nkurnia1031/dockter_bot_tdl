from __future__ import annotations

import mimetypes
import tempfile
import queue
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import (
    Path,
)
from tme3bot.progress_reporter import (
    ProgressReporter,
)
from tme3bot.media import has_downloadable_media
from tme3bot.tdl import tdl_session_denial_code, tdl_write_denial_code
from tme3bot.tdl_access_fingerprint import normalize_session_fingerprints
from tme3bot.rclone import (
    RcloneError,
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
            if (
                not source_job_id
                or not path
                or (checkpoint or {}).get("status") != "needs_reconciliation"
                or not name.strip()
                or name == "File"
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
            candidates.append({
                "index": index,
                "path": path,
                "name": name,
                "profile": profile,
            })

        fingerprints = normalize_session_fingerprints(
            payload.get("_tdl_sender_session_fingerprints")
        )
        requested_profiles = payload.get("_tdl_sender_profiles")
        requested_profiles = {
            str(item).strip().lower()
            for item in requested_profiles
            if str(item).strip()
        } if isinstance(requested_profiles, list) else set()
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        reporter.report(
            phase="reconciling",
            message="Memeriksa nama file pada rentang waktu job",
            overall={"current": 0, "total": len(submitted_items), "unit": "files"},
            counters={"succeeded": 0, "retryable": 0, "ambiguous": len(submitted_items)},
            force=True,
        )
        target_chat = str(payload.get("tdl_access_target") or "").strip()
        if not target_chat:
            raise ValueError("TDL_ACCESS_TARGET_UNAVAILABLE")

        candidate_profiles = list(dict.fromkeys(
            [item["profile"] for item in candidates]
            + [str(item).strip().lower() for item in requested_profiles]
        ))
        available_profiles = set(self.available_storage_profiles())
        messages = None
        error_code = "STORAGE_RECONCILIATION_SESSION_UNAVAILABLE"
        for profile in candidate_profiles:
            with self._lock:
                if str(command.get("job_id") or "") in self._cancel_requested:
                    break
            if profile not in requested_profiles or not fingerprints.get(profile):
                continue
            if profile not in available_profiles:
                error_code = "STORAGE_RECONCILIATION_SESSION_UNAVAILABLE"
                continue
            current_fingerprints = normalize_session_fingerprints(
                self.available_storage_session_fingerprints([profile])
            )
            if current_fingerprints.get(profile) != fingerprints.get(profile):
                error_code = "STORAGE_RECONCILIATION_SESSION_CHANGED"
                continue
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
                                client.command_callback = None
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
                    self._capture_tdl_output(runtimes[profile].upload_tdl_client)
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
            command_callback=self._command_callback(),
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
        updated = {**saved, "provider": "telegram", "upload_status": "succeeded", "cleanup_status": cleanup_status}
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
        failures: list[dict[str, Any]] = []
        output_items: list[dict[str, Any]] = []
        previous = {str(item.get("path") or ""): item for item in read_items(command_id) if isinstance(item, dict)}
        total_bytes = sum(path.stat().st_size for path in files if path.exists())
        reporter = ProgressReporter(self.publisher, job_id)
        reporter.report(phase="uploading", message=f"Menyiapkan {len(files)} file untuk rclone",
                        overall={"current": 0, "total": len(files), "percent": 0, "unit": "files", "bytes_total": total_bytes},
                        counters={"succeeded": 0, "failed": 0}, force=True)

        def cancelled() -> bool:
            with self._lock:
                return job_id in self._cancel_requested

        def progress(index: int, total: int, name: str) -> None:
            reporter.report(phase="uploading", message=f"Mengupload {name} ke rclone",
                            overall={"current": index, "total": total, "percent": index * 100 / total if total else 100, "unit": "files"},
                            item={"name": name, "target_path": name, "index": index, "total": total, "percent": 100},
                            counters={"succeeded": successes, "failed": len(failures)}, force=True)

        runner = RcloneRunner(log_callback=self._append_job_log, command_callback=self._command_callback(),
                              progress_callback=progress, cancel_check=cancelled,
                              stall_timeout_seconds=getattr(self.config, "job_stall_timeout_seconds", 600))
        with self._lock:
            self._rclone_runners[job_id] = runner
        try:
            for index, path in enumerate(files, start=1):
                if cancelled():
                    raise QuickModeError("Upload dibatalkan oleh user.")
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
                    item.update(status="failed", upload_status="failed", cleanup_status="retained_conflict" if transfer_mode == "move" else "not_requested",
                                error_code="STORAGE_TARGET_CONFLICT", error="File dengan nama ini sudah ada di tujuan.")
                    persist(command_id, relative, file_name=path.name, status="failed", attempt=attempt, retryable=False,
                            error_code="STORAGE_TARGET_CONFLICT", error_message=item["error"], result_item=item)
                    failures.append(item); output_items.append(item); completed += 1
                    continue

                if not must_verify_only:
                    item.update(status="sending", upload_status="sending")
                    persist(command_id, relative, file_name=path.name, status="sending", attempt=attempt, retryable=False, result_item=item)
                    try:
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
                                             "unit": "files", "bytes_current": sum(int(output.get("source_identity", {}).get("size", 0)) for output in output_items),
                                             "bytes_total": total_bytes},
                                    item={"name": path.name, "target_path": remote_name, "index": index, "total": len(files), "status": item["upload_status"],
                                          "cleanup_status": item["cleanup_status"]},
                                    counters={"succeeded": successes, "failed": len(failures)}, force=True)
                except Exception:
                    LOGGER.warning("Could not publish rclone Storage progress for %s", job_id, exc_info=True)
            ambiguous = any(item.get("status") == "needs_reconciliation" or item.get("upload_status") == "needs_reconciliation" for item in failures)
            outcome = "succeeded" if not failures else "partial_failure" if successes else "needs_reconciliation" if ambiguous else "failed"
            reporter.report(phase=outcome, message=f"rclone selesai: {successes} berhasil, {len(failures)} belum terkonfirmasi",
                            overall={"current": len(files), "total": len(files), "percent": 100 if files else 100, "unit": "files"},
                            counters={"succeeded": successes, "failed": len(failures)}, force=True)
            return {"outcome": outcome, "provider": "rclone", "transfer_mode": transfer_mode,
                    "target_path": rclone_path, "total": len(files), "succeeded": successes,
                    "failed": failures, "items": output_items, "retryable": False}
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
        if str(payload.get("provider") or "telegram").strip().lower() == "rclone":
            return self._storage_upload_rclone(command, payload, upload_item_callback=upload_item_callback)
        storage_profile = str(command.get("profile") or self.storage_profile()).strip().lower()
        durable_batch = (
            str(command.get("kind") or "") == "storage_upload"
            and bool(command.get("command_id"))
        )
        local_profiles = set(self.profile_manager.list_profiles())
        if not durable_batch and storage_profile not in local_profiles:
            raise ValueError(
                f"STORAGE_PROFILE_UNAVAILABLE: profile worker {storage_profile} belum memiliki sesi TDL."
            )
        available_profiles = set(self.available_storage_profiles())
        if not durable_batch and storage_profile not in available_profiles:
            raise ValueError(
                f"STORAGE_PROFILE_UNAVAILABLE: lane Upload {storage_profile} belum siap. Jalankan scan profil lalu coba lagi."
            )
        raw_sender_profiles = payload.get("_tdl_sender_profiles")
        sender_profiles = [
            str(item).strip().lower()
            for item in raw_sender_profiles
            if str(item).strip()
        ] if isinstance(raw_sender_profiles, list) else []
        if storage_profile not in sender_profiles:
            sender_profiles.insert(0, storage_profile)
        sender_profiles = [
            profile
            for profile in dict.fromkeys(sender_profiles)
            if profile in local_profiles and profile in available_profiles
        ]
        expected_fingerprints = normalize_session_fingerprints(
            payload.get("_tdl_sender_session_fingerprints")
        )
        fingerprint_method = getattr(self, "available_storage_session_fingerprints", None)
        current_fingerprints = normalize_session_fingerprints(
            fingerprint_method(sender_profiles) if callable(fingerprint_method) else {}
        )
        sender_profiles = [
            profile
            for profile in sender_profiles
            if expected_fingerprints.get(profile)
            and (
                durable_batch
                or expected_fingerprints.get(profile) == current_fingerprints.get(profile)
            )
        ]
        if not sender_profiles and not durable_batch:
            raise ValueError(
                "TDL_ACCESS_NOT_VERIFIED: bukti akses lane Upload sudah tidak cocok. Verifikasi akses Storage lagi."
            )
        if sender_profiles and storage_profile not in sender_profiles:
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
            return self._storage_upload_parallel(
                command,
                payload=payload,
                files=files,
                file_sizes=file_sizes,
                total_bytes=total_bytes,
                root=root,
                preserve_structure=preserve_structure,
                photo_names=photo_names,
                sender_profiles=sender_profiles,
                expected_fingerprints=expected_fingerprints,
                sender_runtimes=sender_runtimes,
                storage_profile=storage_profile,
                target_chat=target_chat,
                reporter=reporter,
                upload_item_callback=upload_item_callback,
            )
        with self._storage_upload_lane_locks(sender_runtimes):
            current_fingerprints = normalize_session_fingerprints(
                fingerprint_method(sender_profiles) if callable(fingerprint_method) else {}
            )
            sender_profiles = [
                profile
                for profile in sender_profiles
                if expected_fingerprints.get(profile)
                and expected_fingerprints.get(profile) == current_fingerprints.get(profile)
            ]
            if not sender_profiles:
                raise ValueError(
                    "TDL_ACCESS_NOT_VERIFIED: sesi lane Upload berubah sebelum pengiriman. Verifikasi akses Storage lagi."
                )
            if storage_profile not in sender_profiles:
                storage_profile = sender_profiles[0]
                runtime = sender_runtimes[storage_profile]
            with self._capture_storage_upload_output(sender_runtimes):
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
            "provider": "telegram",
            "uploaded_items": uploaded_items,
        }

    def _storage_upload_parallel(
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
        expected_fingerprints: dict[str, str],
        sender_runtimes: dict[str, Any],
        storage_profile: str,
        target_chat: str,
        reporter: ProgressReporter,
        upload_item_callback=None,
    ) -> dict[str, Any]:
        """Run one file at a time per Upload lane and keep durable item outcomes."""
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
        in_flight = 0
        active_items: dict[str, dict[str, Any]] = {}
        lane_condition = threading.Condition(lanes_lock)

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
        tasks: queue.Queue[dict[str, Any]] = queue.Queue()
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
                tasks.put(
                    {
                        "path": path,
                        "relative": relative,
                        "attempt": base_attempt + 1,
                    }
                )
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
                    counters={"succeeded": success_count, "failed": failure_count},
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
            nonlocal completed_bytes, completed_files, succeeded, failed_count
            path = task["path"]
            relative = task["relative"]
            attempt = int(task.get("attempt") or 0)
            if status == "succeeded" and uploaded_item is not None:
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
                    "message_id": message_id,
                    "attempts": [],
                    "upload_status": status,
                    "cleanup_status": cleanup_status if status == "succeeded" else (
                        "retained_ambiguous" if status == "needs_reconciliation" and payload.get("transfer_mode") == "move"
                        else "retained_upload_failed" if payload.get("transfer_mode") == "move"
                        else "not_requested"
                    ),
                    "source_identity": source_identities.get(relative, {}),
                }
                outcomes[relative] = outcome
                if uploaded_item is not None:
                    uploaded_by_path[relative] = dict(uploaded_item)

        def worker_for_lane(profile: str) -> None:
            runtime = sender_runtimes[profile]
            client = runtime.upload_tdl_client
            while True:
                nonlocal in_flight
                with lane_condition:
                    while True:
                        if profile not in active_lanes:
                            return
                        try:
                            task = tasks.get_nowait()
                            in_flight += 1
                            break
                        except queue.Empty:
                            if in_flight == 0 and tasks.empty():
                                return
                            lane_condition.wait(timeout=0.05)
                path = task["path"]
                relative = task["relative"]
                attempt = int(task["attempt"])
                try:
                    with self._lock:
                        if job_id in self._cancel_requested:
                            return
                    current = normalize_session_fingerprints(
                        self.available_storage_session_fingerprints([profile])
                    )
                    if current.get(profile) != expected_fingerprints.get(profile):
                        with lanes_lock:
                            active_lanes.discard(profile)
                            has_alternative = bool(active_lanes)
                        persist(
                            relative,
                            path.name,
                            status="failed",
                            attempt=attempt,
                            profile=profile,
                            retryable=True,
                            error_code="PROFILE_UPLOAD_SESSION_CHANGED",
                            error_message="Sesi Upload berubah sebelum file dikirim.",
                        )
                        if has_alternative:
                            persist(
                                relative,
                                path.name,
                                status="pending",
                                attempt=attempt + 1,
                                retryable=True,
                                error_code="PROFILE_UPLOAD_SESSION_CHANGED",
                                error_message="Sesi Upload berubah sebelum file dikirim.",
                            )
                            with lane_condition:
                                tasks.put({**task, "attempt": attempt + 1})
                                lane_condition.notify_all()
                        else:
                            finish_item(
                                task,
                                status="failed",
                                profile=profile,
                                retryable=True,
                                error_code="PROFILE_UPLOAD_SESSION_CHANGED",
                                error_message="Sesi Upload berubah sebelum file dikirim.",
                            )
                        continue

                    with lanes_lock:
                        if profile not in active_lanes:
                            with lane_condition:
                                tasks.put(task)
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
                            with self._capture_tdl_output(client):
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
                            with lanes_lock:
                                active_lanes.discard(profile)
                                has_alternative = bool(active_lanes)
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
                                with lane_condition:
                                    tasks.put({**task, "attempt": attempt + 1})
                                    lane_condition.notify_all()
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
                        # evidence to its staging manifest after each accepted
                        # file, even though the upload is running in parallel.
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
                        lane_condition.notify_all()
                    tasks.task_done()

        with ThreadPoolExecutor(
            max_workers=max(1, len(sender_profiles)),
            thread_name_prefix=f"storage-{job_id[:8]}",
        ) as pool:
            futures = [pool.submit(worker_for_lane, profile) for profile in sender_profiles]
            for future in futures:
                future.result()

        # If every verified lane was rejected or rotated, the files still in
        # the FIFO are known not to have been attempted and can be retried.
        while True:
            try:
                task = tasks.get_nowait()
            except queue.Empty:
                break
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
            result_items.append(
                {
                    key: item.get(key)
                    for key in (
                        "path", "name", "status", "attempt", "profile", "retryable",
                        "error_code", "error", "message_id", "attempts",
                    )
                }
            )
        result_items.sort(key=lambda item: str(item.get("path") or ""))
        uploaded_items = [
            uploaded_by_path[relative]
            for relative in sorted(uploaded_by_path)
        ]
        file_succeeded = sum(item.get("status") == "succeeded" for item in result_items)
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
            message=f"Upload selesai: {file_succeeded} berhasil, {len(failure_items)} belum berhasil",
            overall={
                "current": len(result_items),
                "total": len(files),
                "percent": 100,
                "unit": "files",
                "bytes_current": total_bytes,
                "bytes_total": total_bytes,
            },
            counters={"succeeded": file_succeeded, "failed": len(failure_items)},
            force=True,
        )
        return {
            "outcome": outcome,
            "total": len(result_items),
            "succeeded": file_succeeded,
            "failed": failure_items,
            "items": result_items,
            "retryable": retryable,
            "provider": "telegram",
            "uploaded_items": uploaded_items,
        }
