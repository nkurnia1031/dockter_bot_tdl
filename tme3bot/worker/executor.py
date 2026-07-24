from __future__ import annotations

import hashlib
import logging
import mimetypes
import threading
import time
import uuid
from contextlib import ExitStack
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from tme3bot.backup_service import BackupService, sha256_file
from tme3bot.export_catalog import inspect_export_json
from tme3bot.infrastructure.http_client import JsonHttpError, request_json
from tme3bot.profile_queue import SerialPerKeyQueue
from tme3bot.storage_catalog import build_storage_caption
from tme3bot.utility import UtilityRunner

LOGGER = logging.getLogger(__name__)


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
        self._known: set[str] = set()
        self._lock = threading.RLock()
        self._jobs = SerialPerKeyQueue[str, dict[str, Any]](
            self._run,
            error_handler=self._unhandled,
            thread_name_prefix="tme3-domain-worker",
        )

    def start(self) -> None:
        self._jobs.start()

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
        if active is None:
            return False
        profile, kind = active
        if kind != "download":
            return False
        runtime = self.profile_manager.runtime(profile)
        return bool(runtime.download_tdl_client.cancel_current())

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
        with self._lock:
            self._active[job_id] = (profile, kind)
        try:
            self.publisher.emit(
                job_id,
                "running",
                "started",
                progress={"message": f"{kind} mulai diproses"},
            )
            result = self._execute(command)
            self.publisher.emit(
                job_id, "succeeded", "completed", result={"value": json_value(result)}
            )
        except Exception as exc:
            LOGGER.exception("Job %s (%s) failed", job_id, kind)
            self._failed(command, exc)
        finally:
            with self._lock:
                self._active.pop(job_id, None)
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
        with runtime.export_operation_lock:
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
                [str(item) for item in command["payload"].get("chat_refs", [])]
            )
            deleted = runtime.state_store.delete_sources(result.succeeded)
        return {"succeeded": deleted, "failed": result.failed}

    def _download(self, command: dict[str, Any]) -> Any:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        stop = threading.Event()

        def publish_progress() -> None:
            while not stop.wait(2):
                snapshot = runtime.download_progress.snapshot()
                try:
                    self.publisher.emit(
                        str(command["job_id"]),
                        "running",
                        "progress",
                        progress=json_value(snapshot),
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
        folders = [self._workspace_path(item) for item in payload.get("folders", [])]
        if not folders:
            raise ValueError("Folder utility belum dipilih.")

        def log(line: str) -> None:
            compact = " ".join(line.replace("\r", " ").split())[-500:]
            if compact:
                self.publisher.emit(
                    str(command["job_id"]),
                    "running",
                    "progress",
                    progress={"message": compact},
                )

        runner = UtilityRunner(
            Path("/app/utility") if Path("/app/utility").exists() else Path("utility"),
            log,
        )
        return json_value(
            runner.run(
                str(payload["utility"]),
                [str(item) for item in folders],
                payload.get("password"),
                payload.get("settings") or {},
            )
        )

    def _storage_upload(self, command: dict[str, Any]) -> dict[str, Any]:
        payload = command["payload"]
        runtime = self.profile_manager.runtime(str(command["profile"]))
        root = self._workspace_path(str(payload["folder_path"]))
        if not root.is_dir():
            raise ValueError(f"Folder storage tidak ditemukan: {root}")
        files = sorted(path for path in root.rglob("*") if path.is_file())
        if not files:
            raise ValueError("Folder storage tidak berisi file.")
        failed, succeeded = [], 0
        with runtime.export_operation_lock:
            for index, path in enumerate(files, start=1):
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
                    result = runtime.export_tdl_client.upload(
                        path, runtime.config.storage_channel_ref, caption
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
                    self.publisher.emit(
                        str(command["job_id"]),
                        "running",
                        "storage.item_uploaded",
                        progress={"current": index, "total": len(files), "message": path.name},
                        result={"item": item},
                    )
                    succeeded += 1
                except Exception as exc:
                    LOGGER.exception("Storage upload failed for %s", path)
                    failed.append({"name": path.name, "error": str(exc)})
                    self.publisher.emit(
                        str(command["job_id"]),
                        "running",
                        "progress",
                        progress={
                            "current": index,
                            "total": len(files),
                            "message": path.name,
                            "failed": len(failed),
                        },
                    )
        return {"total": len(files), "succeeded": succeeded, "failed": failed}

    def _backup(self, command: dict[str, Any]) -> dict[str, Any]:
        payload = command["payload"]
        profiles = sorted(self.profile_manager.list_profiles())
        runtimes = [self.profile_manager.runtime(profile) for profile in profiles]
        with ExitStack() as locks:
            for runtime in runtimes:
                locks.enter_context(runtime.export_operation_lock)
                locks.enter_context(runtime.download_operation_lock)
            archive = BackupService(self.config).create_archive(
                str(payload["backup_run_id"]),
                str(payload["node_name"]),
                password=str(payload["password"]),
                volume_size=str(payload.get("volume_size") or self.config.backup_volume_size),
            )
        if not runtimes:
            raise RuntimeError("Tidak ada profile runtime untuk upload backup.")
        uploader = runtimes[0].export_tdl_client
        sent = 0
        for part in archive.parts:
            digest, size = sha256_file(part)
            caption = (
                f"#backup #node_{payload['node_name']} "
                f"#run_{str(payload['backup_run_id'])[:12]}\nPart: {part.name}"
            )
            result = uploader.upload(part, str(payload["channel_ref"]), caption)
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
            self.publisher.emit(
                str(command["job_id"]),
                "running",
                "backup.part_uploaded",
                progress={"current": sent + 1, "total": len(archive.parts), "message": part.name},
                result={"part": part_payload},
            )
            sent += 1
        for part in archive.parts:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("Could not remove backup staging %s", part)
        return {"parts": sent, "run_id": payload["backup_run_id"]}

    def _workspace_path(self, raw: str) -> Path:
        root = Path(self.config.utility_workspace_root).resolve()
        path = Path(raw)
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
