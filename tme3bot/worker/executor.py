from __future__ import annotations

import hashlib
import logging
import mimetypes
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from tme3bot.backup_service import BackupService, sha256_file
from tme3bot.export_catalog import inspect_export_json
from tme3bot.infrastructure.http_client import JsonHttpError, request_json
from tme3bot.profile_queue import SerialPerKeyQueue
from tme3bot.progress_reporter import ProgressReporter
from tme3bot.storage_catalog import build_storage_caption
from tme3bot.utility import UtilityRunner

LOGGER = logging.getLogger(__name__)


def _utility_progress_message(utility: str, phase: str, item: str) -> str:
    labels = {
        "compressing": "Mengompres",
        "extracting": "Mengekstrak",
        "item_completed": "Selesai memproses",
        "item_failed": "Gagal memproses",
        "pindah_starting": "Menyiapkan pemindahan",
        "export_starting": "Menyiapkan organizer export",
    }
    action = labels.get(phase, f"Menjalankan {utility}")
    return f"{action} {item}".strip()


def _has_transfer_telemetry(progress) -> bool:
    return any(
        value is not None
        for value in (
            progress.percent,
            progress.speed_bps,
            progress.eta_seconds,
            progress.transferred_bytes,
        )
    )


class JobLogSnapshot:
    """Bounded raw command output retained with the persistent job history."""

    max_lines = 5_000
    max_characters = 1_000_000

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._characters = 0
        self.truncated = False

    def add(self, value: str) -> None:
        for raw_line in str(value).splitlines() or [str(value)]:
            line = raw_line.rstrip()
            if not line:
                continue
            if len(self._lines) >= self.max_lines or self._characters + len(line) + 1 > self.max_characters:
                self.truncated = True
                return
            self._lines.append(line)
            self._characters += len(line) + 1

    def value(self) -> dict[str, Any]:
        return {
            "lines": self._lines,
            "line_count": len(self._lines),
            "truncated": self.truncated,
        }


def json_value(value: Any) -> Any:
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)


class WorkerEventPublisher:
    def __init__(self, backend_url: str, token: str) -> None:
        self.backend_url = backend_url
        self.token = token
        self._sequences: dict[str, int] = {}
        self._lock = threading.RLock()

    def emit(
        self,
        job_id: str,
        status: str,
        event_type: str,
        *,
        transient: bool = False,
        progress: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            sequence = self._sequences.get(job_id, 1) + 1
            self._sequences[job_id] = sequence
        payload = {
            "sequence": sequence,
            "status": status,
            "event_type": event_type,
            "transient": transient,
            "progress": json_value(progress or {}),
            "result": json_value(result) if result is not None else None,
            "error": json_value(error) if error is not None else None,
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                request_json(
                    self.backend_url,
                    self.token,
                    "POST",
                    f"/internal/v1/jobs/{job_id}/events",
                    payload,
                    timeout=30,
                )
                return
            except Exception as exc:
                if isinstance(exc, JsonHttpError) and exc.status == 409 and event_type == "queue":
                    LOGGER.info("Ignoring stale queue event for completed job %s", job_id)
                    return
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def forget(self, job_id: str) -> None:
        with self._lock:
            self._sequences.pop(job_id, None)


class WorkerJobExecutor:
    """Executes domain jobs and publishes JSON events; no UI dependency."""

    def __init__(self, config, profile_manager, publisher: WorkerEventPublisher) -> None:
        self.config = config
        self.profile_manager = profile_manager
        self.publisher = publisher
        self._active: dict[str, tuple[str, str]] = {}
        self._utility_runners: dict[str, UtilityRunner] = {}
        self._cancel_requested: set[str] = set()
        self._known: set[str] = set()
        self._lock = threading.RLock()
        self._job_log = threading.local()
        self._jobs = SerialPerKeyQueue[str, dict[str, Any]](
            self._run,
            error_handler=self._unhandled,
            thread_name_prefix="tme3-domain-worker",
        )

    def start(self) -> None:
        self.sync_profiles()
        self._jobs.start()

    def sync_profiles(self) -> None:
        """Publish only profile metadata; .tdl files remain on this worker."""
        try:
            request_json(
                self.config.backend_api_url,
                self.config.backend_internal_token,
                "POST",
                "/internal/v1/profiles/sync",
                {"profiles": self.profile_manager.local_profile_identities()},
                timeout=15,
            )
        except Exception as exc:
            # The worker can still expose its API while the backend restarts;
            # the next worker restart will retry registration.
            LOGGER.warning("Could not sync worker profile metadata to backend: %s", exc)

    def enqueue(self, command: dict[str, Any]) -> int:
        job_id = str(command["job_id"])
        with self._lock:
            if job_id in self._known:
                return self._jobs.queue_size(str(command["profile"]))
            self._known.add(job_id)
        position = self._jobs.enqueue(
            str(command["profile"]),
            command,
            priority=0 if command.get("payload", {}).get("priority") == "next" else 100,
        )
        try:
            self.publisher.emit(
                job_id,
                "dispatched",
                "queue",
                progress={"position": position, "worker": self.config.backup_node_name},
            )
        except Exception:
            LOGGER.exception("Could not publish queue position for %s", job_id)
        return position

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            active = self._active.get(job_id)
            utility_runner = self._utility_runners.get(job_id)
        if active is None:
            return False
        profile, kind = active
        runtime = self.profile_manager.runtime(profile)
        if kind == "download":
            cancelled = runtime.download_tdl_client.interrupt_current()
        elif kind in {"export", "storage_upload", "backup_node"}:
            cancelled = runtime.export_tdl_client.interrupt_current()
        elif kind == "leave":
            cancelled = runtime.leave_service.runner.interrupt_current()
        elif kind == "utility" and utility_runner is not None:
            cancelled = utility_runner.cancel_current()
        else:
            cancelled = False
        if cancelled:
            with self._lock:
                self._cancel_requested.add(job_id)
        return cancelled

    def queue_size(self, profile: str) -> int:
        return self._jobs.queue_size(profile)

    def _unhandled(self, profile: str, command: dict[str, Any], exc: Exception) -> None:
        LOGGER.exception("Worker queue failed for profile %s", profile)
        self._failed(command, exc)

    def _run(self, command: dict[str, Any], profile_jobs) -> None:
        del profile_jobs
        job_id = str(command["job_id"])
        profile = str(command["profile"])
        kind = str(command["kind"])
        snapshot = JobLogSnapshot()
        snapshot.add(f"[job {job_id} started: {kind}]")
        self._job_log.snapshot = snapshot
        with self._lock:
            self._active[job_id] = (profile, kind)
        try:
            self.publisher.emit(
                job_id,
                "running",
                "started",
                progress={
                    "phase": "starting",
                    "message": f"{kind} mulai diproses",
                    "overall": {},
                    "item": {},
                    "transfer": {},
                    "counters": {"succeeded": 0, "failed": 0, "skipped": 0},
                    "indeterminate": True,
                },
            )
            result = self._execute(command)
            with self._lock:
                cancelled = job_id in self._cancel_requested
            snapshot.add("[job terminated]" if cancelled else "[job completed]")
            self._publish_log_snapshot(job_id, snapshot)
            if cancelled:
                self.publisher.emit(
                    job_id,
                    "cancelled",
                    "cancelled",
                    error={"code": "JOB_TERMINATED", "message": "Job dihentikan oleh user (Ctrl+C)."},
                )
            else:
                self.publisher.emit(
                    job_id, "succeeded", "completed", result={"value": json_value(result)}
                )
        except Exception as exc:
            LOGGER.exception("Job %s (%s) failed", job_id, kind)
            snapshot.add(f"[job failed: {exc}]")
            self._publish_log_snapshot(job_id, snapshot)
            with self._lock:
                cancelled = job_id in self._cancel_requested
            if cancelled:
                self.publisher.emit(
                    job_id,
                    "cancelled",
                    "cancelled",
                    error={"code": "JOB_TERMINATED", "message": "Job dihentikan oleh user (Ctrl+C)."},
                )
            else:
                self._failed(command, exc)
        finally:
            del self._job_log.snapshot
            with self._lock:
                self._active.pop(job_id, None)
                self._utility_runners.pop(job_id, None)
                self._cancel_requested.discard(job_id)
            self.publisher.forget(job_id)

    def _failed(self, command: dict[str, Any], exc: Exception) -> None:
        try:
            self.publisher.emit(
                str(command["job_id"]),
                "failed",
                "failed",
                error={
                    "code": "WORKER_JOB_FAILED",
                    "message": str(exc)[:1000],
                },
            )
        except Exception:
            LOGGER.exception("Could not publish failure for job %s", command.get("job_id"))

    def _append_job_log(self, line: str) -> None:
        snapshot = getattr(self._job_log, "snapshot", None)
        if snapshot is not None:
            snapshot.add(line)

    def _publish_log_snapshot(self, job_id: str, snapshot: JobLogSnapshot) -> None:
        self.publisher.emit(
            job_id,
            "running",
            "log.snapshot",
            result={"log": snapshot.value()},
        )

    @contextmanager
    def _capture_tdl_output(self, client):
        previous = client.output_callback

        def capture(line: str) -> None:
            self._append_job_log(line)
            if previous is not None:
                previous(line)

        client.output_callback = capture
        try:
            yield
        finally:
            client.output_callback = previous

    @contextmanager
    def _capture_tdl_progress(self, client, callback):
        previous = client.progress_callback

        def capture(progress) -> None:
            callback(progress)
            if previous is not None:
                previous(progress)

        client.progress_callback = capture
        try:
            yield
        finally:
            client.progress_callback = previous

    def _execute(self, command: dict[str, Any]) -> Any:
        kind = str(command["kind"])
        handlers = {
            "export": self._export,
            "leave": self._leave,
            "download": self._download,
            "download_clear_failed": self._download_clear_failed,
            "artifact_inventory": self._artifact_inventory,
            "artifact_delete": self._artifact_delete,
            "utility": self._utility,
            "storage_upload": self._storage_upload,
            "backup_node": self._backup,
        }
        handler = handlers.get(kind)
        if handler is None:
            raise ValueError(f"Jenis job tidak dikenal: {kind}.")
        return handler(command)

    def _export(self, command: dict[str, Any]) -> Any:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        payload = command["payload"]
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        url = payload.get("url")
        if not url:
            from urllib.parse import quote

            chat_ref = str(payload["chat_ref"]).strip()
            if not chat_ref.lstrip("-").isdigit() and not chat_ref.startswith("@"):
                chat_ref = f"@{chat_ref}"
            start_id = max(1, int(payload.get("start_id") or 1))
            label = str(payload.get("label") or "").strip()
            url = f"https://{runtime.config.tme3_host}/c/{quote(chat_ref, safe='@-')}/{start_id}"
            if label:
                url += f"/{quote(label, safe='')}"
        reporter.report(
            phase="connecting",
            message="Menghubungkan sesi Telegram untuk export",
            item={"name": str(payload.get("chat_ref") or url)},
            indeterminate=True,
            force=True,
        )

        def export_progress(progress) -> None:
            if not _has_transfer_telemetry(progress):
                return
            reporter.report(
                phase="exporting",
                message=f"Export {progress.file_name or payload.get('chat_ref') or 'chat'}",
                item={
                    "name": progress.file_name or str(payload.get("chat_ref") or url),
                    "index": progress.fraction_current,
                    "total": progress.fraction_total,
                    "percent": progress.percent,
                },
                transfer=reporter.tdl_transfer(progress),
                indeterminate=progress.percent is None,
            )

        with runtime.export_operation_lock:
            with self._capture_tdl_output(runtime.export_tdl_client):
                with self._capture_tdl_progress(
                    runtime.export_tdl_client, export_progress
                ):
                    result = runtime.export_service.export_from_url(
                        str(url),
                        use_url_message_id=bool(payload.get("use_url_message_id", False)),
                    )
        stats = inspect_export_json(result.export_path)
        artifact = {
            **stats,
            "profile": str(command["profile"]),
            "worker": self.config.backup_node_name,
            "export_job_id": str(command["job_id"]),
            "filename": result.export_path.name,
            "artifact_key": result.export_path.name,
            "status": "pending",
        }
        reporter.report(
            phase="completed",
            message=(
                f"Export selesai: {result.exported_count} message"
                + (" dengan media" if result.has_media else "")
            ),
            overall={
                "current": result.exported_count,
                "total": result.exported_count,
                "percent": 100,
                "unit": "messages",
            },
            counters={"succeeded": result.exported_count},
            force=True,
        )
        self.publisher.emit(
            str(command["job_id"]),
            "running",
            "artifact.discovered",
            result={"artifact": artifact},
        )
        return result

    def _leave(self, command: dict[str, Any]) -> dict[str, Any]:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        with runtime.export_operation_lock:
            result = runtime.leave_service.leave(
                [str(item) for item in command["payload"].get("chat_refs", [])],
                output_callback=self._append_job_log,
            )
            deleted = runtime.state_store.delete_sources(result.succeeded)
        return {"succeeded": deleted, "failed": result.failed}

    def _download(self, command: dict[str, Any]) -> Any:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        stop = threading.Event()
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))

        def publish_progress() -> None:
            while not stop.wait(1):
                snapshot = runtime.download_progress.snapshot()
                try:
                    total_json = max(0, snapshot.total_json)
                    json_done = max(
                        snapshot.success_count + snapshot.failed_count,
                        snapshot.current_json_index - 1,
                    )
                    item_percent = snapshot.tdl_percent
                    reporter.report(
                        phase=snapshot.phase,
                        message=(
                            f"Download {snapshot.tdl_file_name}"
                            if snapshot.tdl_file_name
                            else f"Memproses {snapshot.current_json_name or 'antrean download'}"
                        ),
                        overall={
                            "current": json_done,
                            "total": total_json,
                            "percent": (
                                json_done * 100 / total_json if total_json else None
                            ),
                            "unit": "json",
                        },
                        item={
                            "name": snapshot.tdl_file_name or snapshot.current_json_name,
                            "index": snapshot.tdl_fraction_current,
                            "total": snapshot.tdl_fraction_total or snapshot.current_media_total,
                            "percent": item_percent,
                        },
                        transfer={
                            "bytes_current": snapshot.tdl_bytes_current,
                            "speed_bps": snapshot.tdl_speed_bps,
                            "eta_seconds": snapshot.tdl_eta_seconds,
                            "elapsed_seconds": snapshot.tdl_elapsed_seconds,
                        },
                        counters={
                            "succeeded": snapshot.success_count,
                            "failed": snapshot.failed_count,
                        },
                        indeterminate=item_percent is None,
                    )
                except Exception:
                    LOGGER.exception("Could not publish download progress")

        monitor = threading.Thread(
            target=publish_progress,
            daemon=True,
            name=f"download-events-{command['job_id']}",
        )
        monitor.start()
        try:
            with runtime.download_operation_lock:
                with self._capture_tdl_output(runtime.download_tdl_client):
                    if command["payload"].get("retry_failed"):
                        result = runtime.download_service.retry_failed_exports()
                    elif command["payload"].get("artifact_keys"):
                        result = runtime.download_service.download_selected_exports(
                            [str(item) for item in command["payload"]["artifact_keys"]]
                        )
                    else:
                        result = runtime.download_service.download_pending_exports()
            for item in result.results:
                self.publisher.emit(
                    str(command["job_id"]),
                    "running",
                    "artifact.downloaded" if item.status == "success" else "artifact.failed",
                    result={
                        "artifact": {
                            "profile": str(command["profile"]),
                            "worker": self.config.backup_node_name,
                            "artifact_key": item.json_path.name,
                            "status": "downloaded" if item.status == "success" else "failed",
                            "download_directory": str(item.download_dir),
                            "error": item.error,
                        }
                    },
                )
            reporter.report(
                phase="completed",
                message=(
                    f"Download selesai: {result.success_count} JSON berhasil, "
                    f"{result.failed_count} gagal"
                ),
                overall={
                    "current": result.moved_count,
                    "total": result.moved_count,
                    "percent": 100,
                    "unit": "json",
                },
                counters={
                    "succeeded": result.success_count,
                    "failed": result.failed_count,
                },
                force=True,
            )
            return result
        finally:
            stop.set()
            monitor.join(timeout=3)

    def _download_clear_failed(self, command: dict[str, Any]) -> dict[str, int]:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        return {"deleted": runtime.download_service.clear_failed_exports()}

    def _artifact_inventory(self, command: dict[str, Any]) -> dict[str, int]:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        locations = (
            ("pending", runtime.config.export_pending_dir),
            ("processing", runtime.config.export_processing_dir),
            ("downloaded", runtime.config.export_done_dir),
            ("failed", runtime.config.export_failed_dir),
        )
        discovered = 0
        for status, root in locations:
            for path in sorted(root.glob("*.json")):
                try:
                    stats = inspect_export_json(path)
                except (OSError, ValueError) as exc:
                    LOGGER.warning("Artifact inventory skipped %s: %s", path, exc)
                    continue
                self.publisher.emit(
                    str(command["job_id"]),
                    "running",
                    "artifact.discovered",
                    result={
                        "artifact": {
                            **stats,
                            "profile": str(command["profile"]),
                            "worker": self.config.backup_node_name,
                            "filename": path.name,
                            "artifact_key": path.name,
                            "status": status,
                        }
                    },
                )
                discovered += 1
        return {"discovered": discovered}

    def _artifact_delete(self, command: dict[str, Any]) -> dict[str, Any]:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        key = str(command["payload"]["artifact_key"])
        if Path(key).name != key or not key.lower().endswith(".json"):
            raise ValueError("Artifact key tidak valid.")
        for root in (
            runtime.config.export_pending_dir,
            runtime.config.export_failed_dir,
        ):
            candidate = (root.resolve() / key).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                continue
            if candidate.is_file():
                candidate.unlink()
                return {"deleted": True, "artifact_key": key}
        raise FileNotFoundError(f"Artifact tidak ditemukan: {key}")

    def _utility(self, command: dict[str, Any]) -> dict[str, Any]:
        payload = command["payload"]
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        folders = [
            self._workspace_path(item, require_absolute=True)
            for item in payload.get("folders", [])
        ]
        if not folders:
            raise ValueError("Folder utility belum dipilih.")
        missing = [str(folder) for folder in folders if not folder.is_dir()]
        if missing:
            raise ValueError(f"Folder utility tidak ditemukan: {', '.join(missing)}")
        utility_name = str(payload["utility"])
        counters = {"succeeded": 0, "failed": 0, "skipped": 0}

        def utility_progress(value: dict[str, object]) -> None:
            phase = str(value.get("phase") or utility_name)
            if phase in {"item_completed", f"{utility_name}_folder_completed"}:
                counters["succeeded"] += 1
            elif phase in {"item_failed", f"{utility_name}_folder_failed"}:
                counters["failed"] += 1
            index = int(value.get("index") or value.get("folder_index") or 0)
            total = int(value.get("total") or value.get("folder_total") or len(folders))
            percent = value.get("percent")
            item_name = str(
                value.get("name")
                or value.get("folder")
                or (folders[min(max(index - 1, 0), len(folders) - 1)] if folders else "")
            )
            progress_payload = reporter.report(
                phase=phase,
                message=_utility_progress_message(utility_name, phase, item_name),
                overall={
                    "current": max(0, index - (0 if "completed" in phase else 1)),
                    "total": total,
                    "percent": (
                        float(percent)
                        if total <= 1 and isinstance(percent, (int, float))
                        else (
                            ((max(index - 1, 0) + float(percent) / 100) * 100 / total)
                            if total and isinstance(percent, (int, float))
                            else None
                        )
                    ),
                    "unit": "folders",
                },
                item={
                    "name": item_name,
                    "index": index or None,
                    "total": total or None,
                    "size_bytes": value.get("size_bytes"),
                    "percent": percent,
                },
                transfer=reporter.transfer_metrics(
                    speed_bps=value.get("speed_bps"),
                    current_bytes=value.get("bytes_current"),
                    total_bytes=value.get("size_bytes"),
                    eta_seconds=value.get("eta_seconds"),
                    elapsed_seconds=value.get("elapsed_seconds"),
                    percent=float(percent) if isinstance(percent, (int, float)) else None,
                ),
                counters=counters,
                indeterminate=bool(value.get("indeterminate", percent is None)),
                force=phase.endswith("_starting") or phase in {"item_completed", "item_failed"},
            )
            if phase in {"item_completed", "item_failed"}:
                reporter.milestone(
                    phase,
                    progress=progress_payload,
                    error=(
                        {"message": str(value.get("error")), "item": item_name}
                        if phase == "item_failed"
                        else None
                    ),
                )

        runner = UtilityRunner(
            Path("/app/utility") if Path("/app/utility").exists() else Path("utility"),
            log_callback=self._append_job_log,
            progress_callback=utility_progress,
        )
        job_id = str(command["job_id"])
        with self._lock:
            self._utility_runners[job_id] = runner
        try:
            result = json_value(
                runner.run(
                    utility_name,
                    [str(item) for item in folders],
                    payload.get("password"),
                    payload.get("settings") or {},
                )
            )
            reporter.report(
                phase="completed",
                message=(
                    f"Utility selesai: {len(result.get('succeeded', []))} folder berhasil, "
                    f"{len(result.get('failed', {}))} gagal"
                ),
                overall={
                    "current": len(folders),
                    "total": len(folders),
                    "percent": 100,
                    "unit": "folders",
                },
                counters={
                    "succeeded": len(result.get("succeeded", [])),
                    "failed": len(result.get("failed", {})),
                },
                force=True,
            )
            return result
        finally:
            with self._lock:
                self._utility_runners.pop(job_id, None)

    def _storage_upload(self, command: dict[str, Any]) -> dict[str, Any]:
        payload = command["payload"]
        runtime = self.profile_manager.runtime(str(command["profile"]))
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
        files = sorted(path for path in root.rglob("*") if path.is_file())
        if not files:
            raise ValueError("Folder storage tidak berisi file.")
        file_sizes = {path: path.stat().st_size for path in files}
        total_bytes = sum(file_sizes.values())
        failed, succeeded = [], 0
        completed_bytes = 0
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
                        upload_id = str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"tme3bot:{payload['batch_id']}:{path.relative_to(root)}",
                            )
                        )
                        caption = build_storage_caption(
                            str(payload["folder"]), path.name, str(payload.get("keywords", ""))
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
                            result = runtime.export_tdl_client.upload(
                                path,
                                runtime.config.storage_channel_ref,
                                caption,
                                status_callback=upload_phase,
                            )
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
                            "folder": str(payload["folder"]),
                            "keywords": str(payload.get("keywords", "")),
                            "caption": caption,
                            "file_size": size,
                            "mime_type": mimetypes.guess_type(path.name)[0] or "",
                            "sha256": digest,
                            "status": "active",
                            "uploaded_at": None,
                        }
                        succeeded += 1
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
        return {"total": len(files), "succeeded": succeeded, "failed": failed}

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
            archive = BackupService(
                self.config, progress_callback=backup_progress
            ).create_archive(
                str(payload["backup_run_id"]),
                str(payload["node_name"]),
                password=str(payload["password"]),
                volume_size=str(payload.get("volume_size") or self.config.backup_volume_size),
            )
        if not runtimes:
            raise RuntimeError("Tidak ada profile runtime untuk upload backup.")
        uploader = runtimes[0].export_tdl_client
        part_sizes = {part: part.stat().st_size for part in archive.parts}
        total_bytes = sum(part_sizes.values())
        completed_bytes = 0
        sent = 0
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
                    if phase == "resolving_message":
                        reporter.report(
                            phase=phase,
                            message=f"Menunggu konfirmasi Telegram untuk {part.name}",
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

                caption = (
                    f"Backup node={payload['node_name']} "
                    f"run={str(payload['backup_run_id'])[:12]}\nPart: {part.name}"
                )
                with self._capture_tdl_progress(uploader, part_progress):
                    result = uploader.upload(
                        part,
                        str(payload["channel_ref"]),
                        caption,
                        status_callback=part_phase,
                    )
                part_payload = {
                    "run_id": str(payload["backup_run_id"]),
                    "node_name": str(payload["node_name"]),
                    "part_name": part.name,
                    "channel_id": int(payload["channel_id"]),
                    "channel_message_id": result.message_id,
                    "file_size": size,
                    "sha256": digest,
                    "uploaded_at": archive.created_at,
                    "status": "active",
                }
                sent += 1
                completed_bytes += part_sizes[part]
                progress_payload = reporter.report(
                    phase="uploading_parts",
                    message=f"{part.name} selesai diupload",
                    overall={
                        "current": sent,
                        "total": len(archive.parts),
                        "percent": (
                            completed_bytes * 100 / total_bytes
                            if total_bytes
                            else 100
                        ),
                        "unit": "parts",
                        "bytes_current": completed_bytes,
                        "bytes_total": total_bytes,
                    },
                    item={
                        "name": part.name,
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

    def _workspace_path(self, raw: str, *, require_absolute: bool = False) -> Path:
        root = Path(self.config.utility_workspace_root).resolve()
        path = Path(raw)
        if require_absolute and not path.is_absolute():
            raise ValueError("Path utility harus absolut dan berasal dari pilihan workspace.")
        if not path.is_absolute():
            path = root / path
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("Path harus berada di dalam workspace.") from exc
        return resolved

    def workspace_tree(self, raw: str = "/workspace") -> dict[str, Any]:
        """Return a safe, shallow directory listing for the active workspace."""
        root = Path(self.config.utility_workspace_root).resolve()
        current = self._workspace_path(raw or str(root))
        if not current.is_dir():
            raise ValueError("Folder workspace tidak ditemukan.")
        relative = current.relative_to(root)
        display_path = "/workspace" if not relative.parts else "/workspace/" + "/".join(relative.parts)
        items: list[dict[str, Any]] = []
        for entry in sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if entry.is_symlink():
                continue
            item_path = display_path.rstrip("/") + "/" + entry.name
            if entry.is_dir():
                try:
                    children = list(entry.iterdir())
                    files = sum(1 for child in children if child.is_file())
                    directories = sum(1 for child in children if child.is_dir())
                except OSError:
                    files, directories = 0, 0
                items.append({
                    "name": entry.name,
                    "path": item_path,
                    "kind": "directory",
                    "files": files,
                    "directories": directories,
                    "has_children": bool(files or directories),
                })
            elif entry.is_file():
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = None
                items.append({"name": entry.name, "path": item_path, "kind": "file", "size": size})
        return {"path": display_path, "items": items}

    @staticmethod
    def _digest(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size
