from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import uuid
from dataclasses import (
    asdict,
)
from pathlib import (
    Path,
)
from tme3bot.command_audit import (
    sanitize_text,
)
from tme3bot.domain.models import (
    DomainError,
    utc_now,
)
from tme3bot.export_catalog import (
    inspect_export_json,
)
from tme3bot.progress_reporter import (
    ProgressReporter,
)
from tme3bot.rclone import (
    RcloneRunner,
)
from tme3bot.service import (
    ExportJobResult,
)
from tme3bot.utility import (
    DEFAULT_UTILITY_SETTINGS,
    UtilityRunner,
)
from tme3bot.worker.quick_export import (
    QUICK_PHASES,
    QuickModeError,
    QuickThumbnailBuilder,
    delete_quick_stage,
    ensure_quick_stage_writable,
    ensure_quick_tdl_client,
    migrate_legacy_quick_stage,
    quick_folder_name,
    quick_stage_root,
    quick_storage_caption,
    quick_year,
    read_quick_manifest,
    scan_quick_stages,
    visual_media,
    write_quick_manifest,
)
from typing import (
    Any,
)

from .executor_support import (
    BAR_ONLY_PROGRESS_KEY,
    LOGGER,
    _is_named_progress_key,
    _quick_message_matches,
    jakarta_timestamp,
    json_value,
    progress_line_key,
)

class QuickModeExecutorMixin:

    def _release_quick_export_lane(self, command: dict[str, Any]) -> None:
        """Free the worker's export lane after Quick JSON is ready."""
        execution = command.get("execution") or {}
        keys = set(execution.get("resource_keys") or self._resource_keys_for_command(command))
        export_keys = {
            key
            for key in keys
            if ":kind:export" in str(key) or ":tdl:export" in str(key)
        }
        if export_keys:
            self._jobs.release_resources(str(command["job_id"]), export_keys)

    def _quick_terminal_phase(self, command: dict[str, Any], fallback: str) -> str:
        """Read the last persisted Quick phase for failed/cancelled retries."""
        payload = command.get("payload") or {}
        if not bool(payload.get("quick_mode")):
            return fallback
        retry = payload.get("quick_retry") or {}
        retry = retry if isinstance(retry, dict) else {}
        stage_id = str(retry.get("stage_job_id") or command.get("job_id") or "")
        try:
            stage = migrate_legacy_quick_stage(self._quick_workspace(self.config), stage_id)
            phase = str(read_quick_manifest(stage).get("phase") or "").strip().lower()
        except Exception:
            phase = ""
        return phase if phase in {"exporting", "downloading", "thumbnailing", "compressing", "uploading", "cleanup"} else fallback

    def _quick_staging_path(self, command: dict[str, Any]) -> str | None:
        payload = command.get("payload") or {}
        if not bool(payload.get("quick_mode")):
            return None
        retry = payload.get("quick_retry") or {}
        retry = retry if isinstance(retry, dict) else {}
        stage_id = str(retry.get("stage_job_id") or command.get("job_id") or "")
        try:
            stage = migrate_legacy_quick_stage(self._quick_workspace(self.config), stage_id)
        except Exception:
            return None
        return str(stage) if stage.exists() else None

    def _quick_log_path(self, command: dict[str, Any]) -> Path | None:
        """Create the persistent, redacted worker log inside Quick staging."""
        payload = command.get("payload") or {}
        if not bool(payload.get("quick_mode")):
            return None
        retry = payload.get("quick_retry") or {}
        retry = retry if isinstance(retry, dict) else {}
        stage_id = str(retry.get("stage_job_id") or command.get("job_id") or "")
        if not stage_id:
            return None
        stage = migrate_legacy_quick_stage(self._quick_workspace(self.config), stage_id)
        stage.mkdir(parents=True, exist_ok=True)
        path = (stage / "worker.log").resolve()
        try:
            path.parent.relative_to(stage.resolve())
        except ValueError as exc:
            raise QuickModeError("File log Quick Mode keluar dari staging.") from exc
        return path

    def _register_quick_log(self, job_id: str, file_path: Path) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with self._quick_log_state_lock:
            self._quick_log_paths[str(job_id)] = file_path
            self._quick_log_locks[str(job_id)] = threading.RLock()
            self._quick_log_named_progress[str(job_id)] = False
        self.publisher.register_audit_callback(
            str(job_id),
            lambda message, current_job=str(job_id): self._write_quick_log_line(
                current_job, message
            ),
        )

    def _write_quick_log_line(
        self,
        job_id: str,
        line: str,
        secrets: list[str] | None = None,
        fallback_path: Path | None = None,
    ) -> None:
        with self._quick_log_state_lock:
            file_path = self._quick_log_paths.get(str(job_id)) or fallback_path
            lock = self._quick_log_locks.get(str(job_id)) or self._quick_log_state_lock
        if file_path is None or lock is None:
            return
        safe_line = sanitize_text(str(line), secrets or "").rstrip()
        if not safe_line:
            return
        progress_key = progress_line_key(safe_line)
        with self._quick_log_state_lock:
            if progress_key == BAR_ONLY_PROGRESS_KEY:
                if self._quick_log_named_progress.get(str(job_id), False):
                    return
            elif _is_named_progress_key(progress_key):
                self._quick_log_named_progress[str(job_id)] = True
            elif safe_line.startswith("$ ") or "process exited with code" in safe_line:
                self._quick_log_named_progress[str(job_id)] = False
        try:
            with lock:
                # Cleanup can detach this job's log while an audit callback is
                # waiting for the same lock. Skip a stale path after that.
                with self._quick_log_state_lock:
                    registered_path = self._quick_log_paths.get(str(job_id))
                    if registered_path is None and fallback_path is None:
                        return
                    if registered_path is not None and registered_path != file_path:
                        return
                with file_path.open("a", encoding="utf-8") as stream:
                    stream.write(f"[{jakarta_timestamp()}] {safe_line}\n")
        except OSError:
            LOGGER.warning(
                "Could not append Quick Mode worker log %s", file_path, exc_info=True
            )

    def _cleanup_quick_stage(self, job_id: str, stage_root: Path) -> None:
        """Remove a completed stage without racing heartbeat audit writes."""
        job_id = str(job_id)
        unregister = getattr(self.publisher, "unregister_audit_callback", None)
        if callable(unregister):
            unregister(job_id)

        with self._quick_log_state_lock:
            log_lock = self._quick_log_locks.get(job_id)
        if log_lock is not None:
            log_lock.acquire()

        with self._quick_log_state_lock:
            log_path = self._quick_log_paths.pop(job_id, None)
        try:
            try:
                shutil.rmtree(stage_root)
            except OSError:
                # Retain the stage and its diagnostics if deletion fails.
                if log_path is not None:
                    with self._quick_log_state_lock:
                        self._quick_log_paths[job_id] = log_path
                raise

            active_log_path = getattr(self._job_log, "file_path", None)
            if isinstance(active_log_path, Path):
                try:
                    if active_log_path.parent.resolve() == Path(stage_root).resolve():
                        self._job_log.file_path = None
                except OSError:
                    self._job_log.file_path = None
        finally:
            if log_lock is not None:
                log_lock.release()

    @staticmethod
    def _compact_quick_log(file_path: Path) -> None:
        """Remove stale progress redraws while retaining diagnostic lines."""
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return
        compacted: list[str] = []
        positions: dict[str, int] = {}
        for line in lines:
            body = re.sub(r"^\[[^]]+\]\s*", "", line, count=1)
            key = progress_line_key(body)
            if key is None and body.startswith("$ "):
                compacted = [
                    existing
                    for existing in compacted
                    if progress_line_key(
                        re.sub(r"^\[[^]]+\]\s*", "", existing, count=1)
                    )
                    is None
                ]
                positions.clear()
            if _is_named_progress_key(key) and BAR_ONLY_PROGRESS_KEY in positions:
                bar_index = positions.pop(BAR_ONLY_PROGRESS_KEY)
                compacted.pop(bar_index)
                positions = {
                    name: index - 1 if index > bar_index else index
                    for name, index in positions.items()
                }
            if key == BAR_ONLY_PROGRESS_KEY and any(
                _is_named_progress_key(name) for name in positions
            ):
                continue
            if key is None:
                compacted.append(line)
                continue
            old_index = positions.get(key)
            if old_index is not None:
                compacted.pop(old_index)
                positions = {
                    name: index - 1 if index > old_index else index
                    for name, index in positions.items()
                    if name != key
                }
            positions[key] = len(compacted)
            compacted.append(line)
        if len(compacted) == len(lines):
            return
        temporary = file_path.with_name(f".{file_path.name}.compact.tmp")
        try:
            temporary.write_text("\n".join(compacted) + ("\n" if compacted else ""), encoding="utf-8")
            temporary.replace(file_path)
        except OSError:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _quick_workspace(config) -> Path:
        return Path(getattr(config, "utility_workspace_root", "/workspace")).resolve()

    def _quick_isolated_client(self, runtime, stage_root: Path, mode: str):
        """Return a per-stage TDL client, with a test/runtime fallback.

        Production profile runtimes always expose the source Bolt directory.
        Lightweight test doubles from older integrations do not, so those
        continue using their supplied client rather than copying the current
        working directory into staging.
        """
        config = getattr(runtime, "config", None)
        if config is None:
            return getattr(runtime, f"{mode}_tdl_client")
        source_storage = getattr(config, f"tdl_{mode}_storage", None)
        source_home = getattr(config, f"tdl_{mode}_home", None)
        if not source_storage or not Path(source_storage).is_dir():
            return getattr(runtime, f"{mode}_tdl_client")
        return ensure_quick_tdl_client(
            stage_root,
            mode=mode,
            source_storage=Path(source_storage),
            source_home=Path(source_home) if source_home else None,
            namespace=str(getattr(config, f"tdl_{mode}_namespace", "default")),
            run_as_user=getattr(config, f"tdl_{mode}_user", None),
            stall_timeout_seconds=int(
                getattr(config, f"tdl_{mode}_stall_timeout_seconds", 0)
            ),
            progress_callback=getattr(
                getattr(runtime, f"{mode}_tdl_client", None), "progress_callback", None
            ),
            output_callback=getattr(
                getattr(runtime, f"{mode}_tdl_client", None), "output_callback", None
            ),
        )

    def _prepare_quick_stage(
        self, command: dict[str, Any], runtime
    ) -> tuple[Path, dict[str, Any], str, str]:
        payload = command.get("payload") or {}
        retry = payload.get("quick_retry") or {}
        retry = retry if isinstance(retry, dict) else {}
        job_id = str(command["job_id"])
        stage_job_id = str(retry.get("stage_job_id") or job_id)
        workspace = self._quick_workspace(self.config)
        stage_root = migrate_legacy_quick_stage(workspace, stage_job_id)
        stage_root.mkdir(parents=True, exist_ok=True)
        ensure_quick_stage_writable(
            stage_root,
            getattr(getattr(runtime, "config", None), "tdl_export_user", None),
        )
        requested_phase = str(
            retry.get("resume_phase")
            or payload.get("quick_phase")
            or retry.get("retry_phase")
            or "exporting"
        ).strip().lower()
        if requested_phase not in {"auto", *QUICK_PHASES}:
            requested_phase = "exporting"
        operation_id = str(retry.get("quick_operation_id") or stage_job_id)
        manifest = read_quick_manifest(stage_root)
        if requested_phase == "exporting":
            if retry:
                self._clear_quick_stage(stage_root)
            manifest = {
                "version": 2,
                "stage_job_id": stage_job_id,
                "quick_operation_id": operation_id,
                "profile": str(command.get("profile") or ""),
                "worker": str(command.get("worker") or self.config.backup_node_name),
                "phase": "exporting",
                "retry_of": retry.get("retry_of"),
            }
        else:
            manifest.setdefault("version", 2)
            manifest.setdefault("stage_job_id", stage_job_id)
            manifest.setdefault("quick_operation_id", operation_id)
            manifest.setdefault("profile", str(command.get("profile") or ""))
            manifest.setdefault("worker", str(command.get("worker") or self.config.backup_node_name))
            manifest.setdefault("retry_of", retry.get("retry_of"))
        write_quick_manifest(stage_root, manifest)
        effective_phase = self._resolve_quick_retry_phase(
            "auto" if requested_phase == "auto" else requested_phase,
            stage_root,
            manifest,
            runtime,
        )
        if effective_phase != "exporting":
            # ``resume_phase=auto`` conservatively reserves the export lane
            # until the physical folder proves that export is unnecessary.
            # Release it before download/thumbnail/compress/upload so another
            # stage on the same profile-worker can export concurrently.
            self._release_quick_export_lane(command)
        # _resolve_quick_retry_phase may reconstruct the manifest from the
        # retained raw export JSON. Persist that reconstruction before the
        # worker starts the resumed phase so a second retry has the same
        # source of truth even when the backend record is incomplete.
        write_quick_manifest(stage_root, manifest)
        return stage_root, manifest, effective_phase, stage_job_id

    @staticmethod
    def _clear_quick_stage(stage_root: Path) -> None:
        for child in Path(stage_root).iterdir():
            if child.name in {"quickmode.json", "worker.log"}:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

    @staticmethod
    def _quick_manifest_export(
        manifest: dict[str, Any],
    ) -> tuple[ExportJobResult, dict[str, Any]] | None:
        raw_result = manifest.get("export_result")
        raw_stats = manifest.get("stats")
        if not isinstance(raw_result, dict) or not isinstance(raw_stats, dict):
            return None
        try:
            result = ExportJobResult(
                status=str(raw_result.get("status") or "exported"),
                chat_ref=str(raw_result.get("chat_ref") or ""),
                requested_label=(
                    str(raw_result["requested_label"])
                    if raw_result.get("requested_label") is not None
                    else None
                ),
                export_path=Path(str(raw_result.get("export_path") or "")),
                start_id=int(raw_result.get("start_id") or 1),
                latest_id=(
                    int(raw_result["latest_id"])
                    if raw_result.get("latest_id") is not None
                    else None
                ),
                exported_count=int(raw_result.get("exported_count") or 0),
                has_media=bool(raw_result.get("has_media")),
                warmup_required=bool(raw_result.get("warmup_required")),
                warning=(
                    str(raw_result["warning"])
                    if raw_result.get("warning") is not None
                    else None
                ),
                end_id=(
                    int(raw_result["end_id"])
                    if raw_result.get("end_id") is not None
                    else None
                ),
            )
        except (TypeError, ValueError):
            return None
        return result, dict(raw_stats)

    @staticmethod
    def _quick_export_from_json(
        export_json: Path,
    ) -> tuple[ExportJobResult, dict[str, Any]] | None:
        """Reconstruct Quick Mode metadata when the backend manifest is gone."""
        try:
            payload = json.loads(Path(export_json).read_text(encoding="utf-8"))
            messages = payload.get("messages", []) if isinstance(payload, dict) else []
            if not isinstance(messages, list):
                messages = []
            message_ids = []
            for message in messages:
                if not isinstance(message, dict):
                    continue
                try:
                    message_ids.append(int(message["id"]))
                except (KeyError, TypeError, ValueError):
                    continue
            stats = inspect_export_json(Path(export_json))
            metadata = payload.get("tme3bot", {}) if isinstance(payload, dict) else {}
            metadata = metadata if isinstance(metadata, dict) else {}
            latest_id = max(message_ids) if message_ids else None
            result = ExportJobResult(
                status="exported" if messages else "empty_export",
                chat_ref=str(metadata.get("chat_ref") or stats.get("chat_ref") or ""),
                requested_label=(
                    str(metadata["label"])
                    if metadata.get("label") is not None
                    else None
                ),
                export_path=Path(export_json).resolve(),
                start_id=min(message_ids) if message_ids else 1,
                latest_id=latest_id,
                exported_count=len(messages),
                has_media=int(stats.get("media_count") or 0) > 0,
                warmup_required=bool(metadata.get("warmup_required")),
                warning=None,
                end_id=latest_id,
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return result, stats

    @staticmethod
    def _quick_stage_json_path(
        stage_root: Path, manifest: dict[str, Any]
    ) -> Path | None:
        name = Path(str(manifest.get("export_json_name") or "")).name
        if not name or name != str(manifest.get("export_json_name") or ""):
            return None
        candidate = Path(stage_root) / name
        return candidate if candidate.is_file() else None

    @staticmethod
    def _ensure_quick_export_json(
        export_path: Path,
        stage_root: Path,
        manifest: dict[str, Any],
        name: str | None = None,
    ) -> Path:
        """Keep a recovery copy of the raw TDL export in Quick Mode staging."""
        name = str(name or Path(export_path).name)
        if not name or Path(name).name != name or not name.lower().endswith(".json"):
            raise QuickModeError("Nama JSON export Quick Mode tidak valid.")
        target = Path(stage_root) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            try:
                shutil.copy2(export_path, target)
            except OSError as exc:
                raise QuickModeError(
                    f"JSON export Quick Mode tidak dapat disimpan ke staging: {exc}"
                ) from exc
        manifest["export_json_name"] = name
        manifest["export_json_retained"] = True
        return target

    @staticmethod
    def _materialize_quick_json(staged_json: Path) -> Path:
        """Create a temporary workspace-only input for the download service."""
        # Keep both the download input and any temporary state inside the
        # Quick Mode workspace.  The normal /data export queues belong to the
        # Download Manager and must not receive Quick Mode leftovers.
        stage_root = Path(staged_json).parent.resolve()
        processing_root = (stage_root.parent / f".quick-processing-{stage_root.name}").resolve()
        processing_root.mkdir(parents=True, exist_ok=True)
        target = processing_root / staged_json.name
        if target.exists():
            target = processing_root / (
                f"{staged_json.stem}.quick-recovery-{uuid.uuid4().hex[:8]}.json"
            )
        shutil.copy2(staged_json, target)
        return target

    def _hydrate_quick_manifest_from_stage(
        self, stage_root: Path, manifest: dict[str, Any]
    ) -> dict[str, Any]:
        """Recover phase metadata from a retained raw export JSON."""
        candidate = self._quick_stage_json_path(stage_root, manifest)
        if candidate is None:
            candidates = sorted(
                path
                for path in Path(stage_root).glob("*.json")
                if path.name != "quickmode.json" and path.is_file()
            )
            candidate = candidates[0] if len(candidates) == 1 else None
        if candidate is None:
            return manifest
        inferred = self._quick_export_from_json(candidate)
        if inferred is None:
            return manifest
        result, stats = inferred
        manifest.setdefault("export_json_name", candidate.name)
        manifest.setdefault("folder_name", quick_folder_name(candidate))
        manifest["export_result"] = json_value(asdict(result))
        manifest["stats"] = json_value(stats)
        manifest.setdefault("phase", "downloading")
        manifest.setdefault("json_deleted", True)
        manifest["export_json_retained"] = True
        return manifest

    @staticmethod
    def _export_retry_range(payload: dict[str, Any]) -> tuple[int | None, int | None]:
        """Return a persisted message-ID range for export recovery.

        Retry metadata is intentionally kept in the internal command payload,
        because the original JSON may already have been downloaded/deleted.
        Older jobs may only have ``start_id``/``latest_id`` in their terminal
        result, which is handled by the control plane when it creates a retry.
        """
        for key in ("export_retry", "quick_retry"):
            metadata = payload.get(key)
            if not isinstance(metadata, dict):
                continue
            start = metadata.get("start_id")
            end = metadata.get("end_id")
            try:
                parsed_start = max(1, int(start)) if start is not None else None
            except (TypeError, ValueError):
                parsed_start = None
            try:
                parsed_end = max(1, int(end)) if end is not None else None
            except (TypeError, ValueError):
                parsed_end = None
            if parsed_start is not None or parsed_end is not None:
                if parsed_start is not None and parsed_end is not None:
                    parsed_end = max(parsed_start, parsed_end)
                return parsed_start, parsed_end
        return None, None

    @staticmethod
    def _quick_json_path(
        runtime, manifest: dict[str, Any], stage_root: Path | None = None
    ) -> Path | None:
        name = Path(str(manifest.get("export_json_name") or "")).name
        if not name or name != str(manifest.get("export_json_name") or ""):
            return None
        if stage_root is not None:
            staged = Path(stage_root) / name
            if staged.is_file():
                return staged
            # Quick Mode must never resume a download from the normal
            # /data exports queue.  A missing staging JSON is a safe boundary
            # that falls back to re-exporting into the workspace.
            return None
        for root in (
            getattr(runtime.config, "export_processing_dir", None),
            getattr(runtime.config, "export_failed_dir", None),
            getattr(runtime.config, "export_pending_dir", None),
        ):
            if root is None:
                continue
            candidate = Path(root) / name
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _quick_media_root(stage_root: Path, manifest: dict[str, Any]) -> Path | None:
        folder_name = Path(str(manifest.get("folder_name") or "")).name
        if not folder_name or folder_name != str(manifest.get("folder_name") or ""):
            return None
        return Path(stage_root) / folder_name

    def _resolve_quick_retry_phase(
        self,
        requested: str,
        stage_root: Path,
        manifest: dict[str, Any],
        runtime,
    ) -> str:
        if requested == "exporting":
            return requested
        hydrated = self._hydrate_quick_manifest_from_stage(stage_root, manifest)
        manifest.clear()
        manifest.update(hydrated)
        folder_name = Path(str(manifest.get("folder_name") or "")).name
        if not folder_name or folder_name == ".":
            archive_candidates = sorted(stage_root.glob("*.7z*"))
            if archive_candidates:
                folder_name = archive_candidates[0].name.split(".7z", 1)[0]
                manifest["folder_name"] = folder_name
            else:
                child_dirs = [
                    path
                    for path in stage_root.iterdir()
                    if path.is_dir() and path.name != ".tdl" and not path.is_symlink()
                ]
                if len(child_dirs) == 1:
                    folder_name = child_dirs[0].name
                    manifest["folder_name"] = folder_name
        media_root = self._quick_media_root(stage_root, manifest)
        has_media = bool(media_root and media_root.is_dir() and visual_media(media_root)[0:2] != ([], []))
        thumbnail = stage_root / f"{folder_name}.png" if folder_name else stage_root / ".missing.png"
        archives = (
            list(stage_root.glob("*.7z"))
            + list(stage_root.glob("*.7z.*"))
        )
        has_json = bool(self._quick_json_path(runtime, manifest, stage_root))
        raw_export = self._quick_manifest_export(manifest)
        # An orphan with a complete archive and PNG does not need its JSON or
        # ExportJobResult.  It can safely continue at upload and cleanup.
        if requested == "auto" and archives and thumbnail.is_file():
            return "uploading"
        if requested == "auto":
            if archives and thumbnail.is_file():
                return "uploading"
            if raw_export is None:
                return "downloading" if has_json else ("thumbnailing" if has_media else "exporting")
            if has_media and thumbnail.is_file() and not archives:
                return "compressing"
            if has_media and not thumbnail.is_file():
                return "thumbnailing"
            return "downloading" if has_json else "exporting"
        if requested == "downloading":
            # A cancellation can arrive just after TDL has deleted the JSON
            # but before the phase checkpoint is written.  Existing media is
            # then the safe dependency boundary: continue with thumbnailing
            # instead of exporting the chat a second time.
            if has_json:
                return "downloading"
            if has_media:
                return "thumbnailing"
            raise QuickModeError(
                "Resume Download tidak dapat dimulai: JSON dan media staging tidak tersedia."
            )
        if requested == "thumbnailing":
            if has_media:
                return "thumbnailing"
            if has_json:
                return "downloading"
            raise QuickModeError(
                "Thumbnail tidak dapat dibuat: media staging tidak tersedia. Gunakan Resume Download."
            )
        if requested == "compressing":
            if has_media and thumbnail.is_file():
                return "compressing"
            if has_media:
                return "thumbnailing"
            if has_json:
                return "downloading"
            raise QuickModeError(
                "Compress tidak dapat dimulai: media staging tidak tersedia."
            )
        if requested == "uploading":
            if archives and thumbnail.is_file():
                return "uploading"
            if has_media and thumbnail.is_file():
                return "compressing"
            if has_media:
                return "thumbnailing"
            if has_json:
                return "downloading"
            raise QuickModeError(
                "Upload tidak dapat dimulai: arsip atau thumbnail belum tersedia."
            )
        return "cleanup" if requested == "cleanup" else "exporting"

    def _quick_export_pipeline(
        self,
        command: dict[str, Any],
        runtime,
        export_result: ExportJobResult | None,
        stats: dict[str, Any],
        reporter: ProgressReporter,
        *,
        stage_root: Path | None = None,
        manifest: dict[str, Any] | None = None,
        resume_phase: str = "downloading",
    ) -> dict[str, Any]:
        """Run the post-export Quick Mode stages while retaining staging on error."""
        job_id = str(command["job_id"])
        payload = command["payload"]
        if stage_root is None:
            stage_root, prepared_manifest, _, _ = self._prepare_quick_stage(command, runtime)
            manifest = manifest or prepared_manifest
        stage_root = Path(stage_root).resolve()
        workspace = self._quick_workspace(self.config)
        try:
            stage_root.relative_to(workspace)
        except ValueError as exc:
            raise QuickModeError(
                "Staging Quick Mode harus berada di dalam workspace."
            ) from exc
        manifest = dict(manifest or read_quick_manifest(stage_root))
        operation_id = str(manifest.get("quick_operation_id") or stage_root.name)
        retry = payload.get("quick_retry") or {}
        retry = retry if isinstance(retry, dict) else {}
        single_phase = bool(retry.get("single_phase"))
        export_json_name = str(manifest.get("export_json_name") or "")
        if not export_json_name and export_result is not None:
            export_json_name = Path(export_result.export_path).name
        folder_name = str(manifest.get("folder_name") or "")
        if not folder_name and export_result is not None:
            folder_name = quick_folder_name(export_result.export_path)
        if not folder_name:
            archive_candidate = sorted(stage_root.glob("*.7z*"))
            if archive_candidate:
                folder_name = archive_candidate[0].name.split(".7z", 1)[0]
        if not folder_name:
            raise QuickModeError("Folder staging Quick Mode tidak dapat ditentukan.")
        if export_result is not None:
            self._ensure_quick_export_json(
                export_result.export_path,
                stage_root,
                manifest,
                name=export_json_name,
            )
        manifest["phase"] = resume_phase
        manifest["folder_name"] = folder_name
        if export_json_name:
            manifest["export_json_name"] = export_json_name
        if export_result is not None:
            manifest["export_result"] = json_value(asdict(export_result))
            manifest["stats"] = json_value(stats)
        media_root = stage_root / folder_name
        thumbnail_path = stage_root / f"{folder_name}.png"
        thumbnail = manifest.get("thumbnail")
        thumbnail = dict(thumbnail) if isinstance(thumbnail, dict) else {}
        storage_folder = str(manifest.get("storage_folder") or f"ModeCepat/{quick_year()}")
        caption = str(manifest.get("caption") or quick_storage_caption(folder_name, quick_year()))
        archive_names = manifest.get("archive_names")
        archive_names = archive_names if isinstance(archive_names, list) else []
        if not archive_names:
            archive_names = [path.name for path in sorted(stage_root.glob("*.7z*"))]
        archive_files: list[Path] = [
            stage_root / Path(str(name)).name
            for name in archive_names
            if str(name) and Path(str(name)).name == str(name)
        ]
        upload_result = manifest.get("upload_result")
        upload_result = dict(upload_result) if isinstance(upload_result, dict) else {"succeeded": 0}
        rclone_result = manifest.get("rclone_result")
        rclone_result = dict(rclone_result) if isinstance(rclone_result, dict) else None

        def ensure_not_cancelled() -> None:
            with self._lock:
                if job_id in self._cancel_requested:
                    raise QuickModeError("Quick Mode dibatalkan oleh user.")

        def save_manifest(**updates: Any) -> None:
            error_value = updates.get("last_error")
            if error_value:
                safe_error = str(error_value)
                settings = payload.get("quick_settings")
                if isinstance(settings, dict):
                    password = str(settings.get("compress_password") or "")
                    if password:
                        safe_error = safe_error.replace(password, "[redacted]")
                updates["last_error"] = safe_error[:1000]
            manifest.update(updates)
            manifest["last_progress_at"] = utc_now().isoformat()
            write_quick_manifest(stage_root, manifest)

        def phase_result(completed_phase: str, next_phase: str) -> dict[str, Any]:
            """Return a successful targeted-phase result without deleting staging."""
            save_manifest(phase=next_phase, last_error=None)
            return {
                **(asdict(export_result) if export_result is not None else {}),
                **stats,
                **thumbnail,
                "quick_mode": True,
                "quick_mode_status": "phase_completed",
                "quick_phase": completed_phase,
                "folder_name": folder_name,
                "storage_folder": storage_folder,
                "caption": caption,
                "archive_names": [path.name for path in archive_files],
                "thumbnail_uploaded_as_photo": completed_phase == "uploading",
                "uploaded_count": upload_result.get("succeeded", 0),
                "rclone_destination": (
                    rclone_result.get("destination")
                    if isinstance(rclone_result, dict)
                    else None
                ),
                "rclone_uploaded_count": (
                    rclone_result.get("succeeded", 0)
                    if isinstance(rclone_result, dict)
                    else 0
                ),
                "rclone_archive_names": (
                    rclone_result.get("files", [])
                    if isinstance(rclone_result, dict)
                    else []
                ),
                "stage_job_id": manifest.get("stage_job_id") or stage_root.name,
                "quick_operation_id": operation_id,
                "staging_path": str(stage_root),
                "staging_cleaned": False,
                "json_deleted": bool(manifest.get("json_deleted")),
            }

        try:
            stage_root.mkdir(parents=True, exist_ok=True)
            save_manifest(
                phase=resume_phase,
                folder_name=folder_name,
                storage_folder=storage_folder,
                caption=caption,
            )
            if export_result is not None:
                save_manifest(
                    export_json_name=export_json_name,
                    export_result=json_value(asdict(export_result)),
                    stats=json_value(stats),
                )
            phase = resume_phase
            if phase == "downloading":
                ensure_not_cancelled()
                save_manifest(phase="downloading", last_error=None)
                shutil.rmtree(media_root, ignore_errors=True)
                media_root.mkdir(parents=True, exist_ok=True)

                reporter.report(
                    phase="downloading",
                    message=f"Mengunduh media ke staging {folder_name}",
                    overall={"current": 0, "total": 1, "percent": 0, "unit": "phase"},
                    force=True,
                )

                def download_progress(event_type: str, snapshot) -> None:
                    if event_type == "progress" and not snapshot.tdl_percent and snapshot.tdl_file_name is None:
                        return
                    reporter.report(
                        phase="downloading",
                        message=(
                            f"Mengunduh {snapshot.tdl_file_name}"
                            if snapshot.tdl_file_name
                            else "Mengunduh media"
                        ),
                        batch={
                            "name": snapshot.current_json_name,
                            "index": snapshot.current_json_index or 1,
                            "total": snapshot.total_json or 1,
                            "unit": "json",
                        },
                        item={
                            "name": snapshot.tdl_file_name,
                            "index": snapshot.tdl_fraction_current,
                            "total": snapshot.tdl_fraction_total or snapshot.current_media_total,
                            "percent": snapshot.tdl_percent,
                        },
                        transfer={
                            "bytes_current": snapshot.tdl_bytes_current,
                            "speed_bps": snapshot.tdl_speed_bps,
                            "eta_seconds": snapshot.tdl_eta_seconds,
                        },
                        counters={
                            "succeeded": snapshot.success_count,
                            "failed": snapshot.failed_count,
                        },
                        indeterminate=snapshot.tdl_percent is None and snapshot.active,
                        force=event_type != "progress",
                    )

                json_path = self._quick_json_path(runtime, manifest, stage_root)
                if json_path is None and export_result is not None:
                    json_path = export_result.export_path
                if json_path is None:
                    raise QuickModeError(
                        "JSON export Quick Mode tidak tersedia untuk fase download."
                    )
                staged_json = self._quick_stage_json_path(stage_root, manifest)
                temporary_json_dir: Path | None = None
                if staged_json is not None and json_path == staged_json:
                    json_path = self._materialize_quick_json(staged_json)
                    temporary_json_dir = json_path.parent
                download_client = self._quick_isolated_client(runtime, stage_root, "download")
                with self._lock:
                    self._quick_download_clients[job_id] = download_client
                try:
                    try:
                        with self._download_progress_operation(runtime, download_progress):
                            with self._capture_tdl_output(download_client):
                                download_result = runtime.download_service.download_export_to(
                                    json_path,
                                    media_root,
                                    delete_json_on_success=True,
                                    workspace_root=workspace,
                                    tdl_client=download_client,
                                )
                    finally:
                        if temporary_json_dir is not None:
                            shutil.rmtree(temporary_json_dir, ignore_errors=True)
                finally:
                    with self._lock:
                        self._quick_download_clients.pop(job_id, None)
                if download_result.status != "success_deleted":
                    save_manifest(
                        phase="downloading",
                        export_json_name=download_result.json_path.name,
                        last_error=download_result.error or download_result.status,
                    )
                    raise QuickModeError(
                        f"Download Quick Mode gagal: {download_result.error or download_result.status}"
                    )
                save_manifest(phase="thumbnailing", json_deleted=True, last_error=None)
                phase = "thumbnailing"
                if single_phase:
                    return phase_result("downloading", "thumbnailing")

            if phase == "thumbnailing":
                ensure_not_cancelled()
                save_manifest(phase="thumbnailing", last_error=None)
                reporter.report(
                    phase="thumbnailing",
                    message="Membuat thumbnail Quick Mode",
                    overall={"current": 0, "total": 1, "percent": 0, "unit": "phase"},
                    force=True,
                )
                builder = QuickThumbnailBuilder(
                    log_callback=self._append_job_log,
                    command_callback=self._command_callback(),
                    stall_timeout_seconds=getattr(
                        self.config, "job_stall_timeout_seconds", 600
                    ),
                )
                with self._lock:
                    self._quick_thumbnail_builders[job_id] = builder
                try:
                    thumbnail = builder.build(media_root, thumbnail_path)
                finally:
                    with self._lock:
                        self._quick_thumbnail_builders.pop(job_id, None)
                save_manifest(phase="compressing", thumbnail=thumbnail, last_error=None)
                phase = "compressing"
                if single_phase:
                    return phase_result("thumbnailing", "compressing")

            if phase == "compressing":
                ensure_not_cancelled()
                save_manifest(phase="compressing", last_error=None)
                reporter.report(
                    phase="compressing",
                    message="Mengompres hasil download",
                    overall={"current": 0, "total": 1, "percent": 0, "unit": "phase"},
                    force=True,
                )
                for archive in stage_root.iterdir():
                    if archive.is_file() and (
                        archive.name == f"{folder_name}.7z"
                        or archive.name.startswith(f"{folder_name}.7z.")
                    ):
                        archive.unlink(missing_ok=True)
                settings = dict(payload.get("quick_settings") or DEFAULT_UTILITY_SETTINGS)
                utility_root = Path("/app/utility") if Path("/app/utility").exists() else Path("utility")
                runner = UtilityRunner(
                    utility_root,
                    log_callback=self._append_job_log,
                    command_callback=self._command_callback(),
                    stall_timeout_seconds=getattr(
                        self.config, "job_stall_timeout_seconds", 600
                    ),
                    progress_callback=lambda value: reporter.report(
                        phase="compressing",
                        message="Mengompres hasil download",
                        item={"name": folder_name},
                        overall={"current": 0, "total": 1, "unit": "phase"},
                        indeterminate=True,
                        force=True,
                    ),
                )
                with self._lock:
                    self._utility_runners[job_id] = runner
                try:
                    compress_result = runner.run("compress", [str(stage_root)], settings=settings)
                finally:
                    with self._lock:
                        self._utility_runners.pop(job_id, None)
                if compress_result.failed:
                    detail = next(iter(compress_result.failed.values()))
                    raise QuickModeError(f"Compress Quick Mode gagal: {detail}")
                ensure_not_cancelled()
                archive_files = sorted(
                    path
                    for path in stage_root.iterdir()
                    if path.is_file()
                    and (path.name == f"{folder_name}.7z" or path.name.startswith(f"{folder_name}.7z."))
                )
                if not archive_files:
                    raise QuickModeError("Compress Quick Mode tidak menghasilkan file arsip.")
                save_manifest(
                    phase="uploading",
                    archive_names=[path.name for path in archive_files],
                    last_error=None,
                )
                phase = "uploading"
                if single_phase:
                    return phase_result("compressing", "uploading")

            if phase == "uploading":
                ensure_not_cancelled()
                archive_files = sorted(
                    path
                    for path in stage_root.iterdir()
                    if path.is_file()
                    and (path.name == f"{folder_name}.7z" or path.name.startswith(f"{folder_name}.7z."))
                )
                if not archive_files:
                    raise QuickModeError("Arsip Quick Mode tidak ditemukan untuk upload.")
                if not thumbnail_path.is_file():
                    raise QuickModeError("Thumbnail Quick Mode tidak ditemukan untuk upload.")
                year = quick_year()
                storage_folder = str(manifest.get("storage_folder") or f"ModeCepat/{year}")
                caption = str(manifest.get("caption") or quick_storage_caption(folder_name, year))
                reporter.report(
                    phase="uploading",
                    message="Mengupload arsip dan thumbnail ke storage",
                    overall={"current": 0, "total": len(archive_files) + 1, "percent": 0, "unit": "files"},
                    force=True,
                )
                upload_command = {
                    **command,
                    "kind": "storage_upload",
                    "payload": {
                        "folder_path": str(stage_root),
                        "destination_folder_path": storage_folder,
                        "preserve_structure": False,
                        "root_files_only": True,
                        "allowed_names": [path.name for path in archive_files] + [thumbnail_path.name],
                        "photo_names": [thumbnail_path.name],
                        "owner_user_id": int(command["actor_user_id"]),
                        "owner_profile": str(command["profile"]),
                        "batch_id": f"{operation_id}:quick",
                        "caption": caption,
                        "caption_override": True,
                        "keywords": "",
                    },
                }
                quick_settings = payload.get("quick_settings") or {}
                rclone_destination = (
                    quick_settings.get("rclone_destination", "googledrive:backup")
                    if isinstance(quick_settings, dict)
                    else "googledrive:backup"
                )

                def persist_uploaded_items(items: list[dict[str, Any]]) -> None:
                    try:
                        save_manifest(
                            phase="uploading",
                            upload_result={
                                "total": len(archive_files) + 1,
                                "succeeded": len(items),
                                "failed": [],
                                "uploaded_items": list(items),
                            },
                            rclone_destination=rclone_destination,
                            storage_folder=storage_folder,
                            caption=caption,
                            last_error=None,
                        )
                    except Exception:
                        # Physical Telegram success must remain recoverable even
                        # when a transient manifest write fails.
                        LOGGER.warning(
                            "Could not persist Quick Mode upload evidence for %s",
                            job_id,
                            exc_info=True,
                        )

                upload_result = self._storage_upload(
                    upload_command,
                    upload_item_callback=persist_uploaded_items,
                )
                # Persist Telegram's physical upload evidence immediately. The
                # next rclone call or telemetry callback may fail, but recovery
                # must still know which channel messages already exist.
                persist_uploaded_items(upload_result.get("uploaded_items", []))
                if upload_result.get("failed") or int(upload_result.get("succeeded", 0)) != len(archive_files) + 1:
                    failures = str(upload_result)
                    save_manifest(phase="uploading", last_error=failures[:500])
                    raise QuickModeError(
                        f"Upload Quick Mode gagal ({failures[:500]}); staging dipertahankan di {stage_root}."
                    )
                # Legacy commands without the new snapshot use the documented
                # default, so every Quick Mode result still reaches Drive.
                rclone_result = self._rclone_upload_files(
                    command,
                    archive_files,
                    str(rclone_destination),
                    reporter,
                )
                save_manifest(
                    phase="cleanup",
                    upload_result=upload_result,
                    rclone_destination=rclone_destination,
                    rclone_result=rclone_result,
                    storage_folder=storage_folder,
                    caption=caption,
                    last_error=None,
                )
                phase = "cleanup"
                if single_phase:
                    return phase_result("uploading", "cleanup")

            if phase == "cleanup":
                ensure_not_cancelled()
                reporter.report(
                    phase="cleanup",
                    message="Membersihkan staging Quick Mode",
                    overall={"current": 1, "total": 1, "percent": 100, "unit": "phase"},
                    force=True,
                )
                self._cleanup_quick_stage(str(command["job_id"]), stage_root)
                return {
                    **(asdict(export_result) if export_result is not None else {}),
                    **stats,
                    **thumbnail,
                    "quick_mode": True,
                    "quick_mode_status": "completed",
                    "folder_name": folder_name,
                    "storage_folder": storage_folder,
                    "caption": caption,
                    "archive_names": [path.name for path in archive_files],
                    "thumbnail_uploaded_as_photo": True,
                    "uploaded_count": upload_result.get("succeeded", 0),
                    "rclone_destination": (
                        rclone_result.get("destination")
                        if isinstance(rclone_result, dict)
                        else None
                    ),
                    "rclone_uploaded_count": (
                        rclone_result.get("succeeded", 0)
                        if isinstance(rclone_result, dict)
                        else 0
                    ),
                    "rclone_archive_names": (
                        rclone_result.get("files", [])
                        if isinstance(rclone_result, dict)
                        else []
                    ),
                    "stage_job_id": manifest.get("stage_job_id") or stage_root.name,
                    "quick_operation_id": operation_id,
                    "staging_path": str(stage_root),
                    "staging_cleaned": True,
                    "json_deleted": True,
                }
            raise QuickModeError(f"Fase Quick Mode tidak dikenal: {phase}")
        except Exception as exc:
            if stage_root.exists():
                try:
                    save_manifest(phase=locals().get("phase", resume_phase), last_error=str(exc)[:1000])
                except Exception:
                    LOGGER.warning("Could not persist Quick Mode manifest at %s", stage_root, exc_info=True)
            if isinstance(exc, QuickModeError) and "staging dipertahankan di" in str(exc):
                raise
            raise QuickModeError(
                f"{exc}; staging dipertahankan di {stage_root}."
            ) from exc

    def quickmode_verify(self, stage_job_id: str, expected_phase: str = "uploading") -> dict[str, Any]:
        """Verify completed Quick Mode uploads before deleting retained staging."""
        stage_job_id = str(stage_job_id).strip()
        with self._lock:
            if stage_job_id in self._quick_delete_active:
                return {
                    "stage_job_id": stage_job_id,
                    "status": "deferred_active",
                    "staging_cleaned": False,
                    "reason": "Folder staging Quick Mode sedang dihapus.",
                }
        workspace = self._quick_workspace(self.config)
        stage_root = migrate_legacy_quick_stage(workspace, stage_job_id)
        if not stage_root.is_dir():
            return {
                "stage_job_id": str(stage_job_id),
                "status": "missing",
                "staging_cleaned": False,
            }
        stage_root = stage_root.resolve()
        try:
            stage_root.relative_to(workspace)
        except ValueError:
            return {
                "stage_job_id": str(stage_job_id),
                "status": "failed",
                "staging_cleaned": False,
                "reason": "Staging berada di luar workspace.",
            }
        with self._lock:
            if stage_job_id in self._quick_delete_active:
                return {
                    "stage_job_id": stage_job_id,
                    "status": "deferred_active",
                    "staging_cleaned": False,
                    "reason": "Folder staging Quick Mode sedang dihapus.",
                }
            if stage_job_id in self._quick_stage_jobs.values():
                return {
                    "stage_job_id": stage_job_id,
                    "status": "deferred_active",
                    "staging_cleaned": False,
                    "reason": "Job Quick Mode masih aktif atau berada dalam antrean.",
                }
            if str(stage_job_id) in self._quick_active:
                return {
                    "stage_job_id": str(stage_job_id),
                    "status": "deferred_active",
                    "staging_cleaned": False,
                    "reason": "Job Quick Mode masih aktif.",
                }
            if str(stage_job_id) in self._quick_verify_active:
                return {
                    "stage_job_id": str(stage_job_id),
                    "status": "deferred_active",
                    "staging_cleaned": False,
                    "reason": "Verifikasi staging sedang berjalan.",
                }
            self._quick_verify_active.add(str(stage_job_id))

        try:
            manifest = read_quick_manifest(stage_root)
            manifest = manifest if isinstance(manifest, dict) else {}
            phase = str(manifest.get("phase") or expected_phase).strip().lower()
            if phase not in {"uploading", "cleanup"}:
                return {
                    "stage_job_id": str(stage_job_id),
                    "status": "pending",
                    "staging_cleaned": False,
                    "reason": f"Fase fisik {phase} belum siap diverifikasi.",
                }
            folder_name = Path(str(manifest.get("folder_name") or "")).name
            if not folder_name or folder_name == ".":
                archives = sorted(stage_root.glob("*.7z*"))
                folder_name = archives[0].name.split(".7z", 1)[0] if archives else ""
            archive_files = sorted(
                path
                for path in stage_root.iterdir()
                if path.is_file()
                and (path.name == f"{folder_name}.7z" or path.name.startswith(f"{folder_name}.7z."))
            ) if folder_name else []
            thumbnail_path = stage_root / f"{folder_name}.png" if folder_name else Path("")
            if not archive_files or not thumbnail_path.is_file():
                return {
                    "stage_job_id": str(stage_job_id),
                    "status": "pending",
                    "staging_cleaned": False,
                    "reason": "Archive atau thumbnail belum lengkap di staging.",
                    "channel_expected": len(archive_files) + (1 if thumbnail_path.is_file() else 0),
                    "drive_expected": len(archive_files),
                }

            upload_result = manifest.get("upload_result")
            upload_result = upload_result if isinstance(upload_result, dict) else {}
            uploaded_items = upload_result.get("uploaded_items")
            uploaded_items = uploaded_items if isinstance(uploaded_items, list) else []
            caption = str(manifest.get("caption") or quick_storage_caption(folder_name, quick_year()))
            expected_names = [path.name for path in archive_files] + [thumbnail_path.name]
            known_items = {
                str(item.get("original_name") or item.get("display_name") or ""): item
                for item in uploaded_items
                if isinstance(item, dict)
            }

            channel_found = 0
            channel_reason = ""
            worker_log = stage_root / "worker.log"

            def verify_log(line: str) -> None:
                self._write_quick_log_line(
                    str(stage_job_id),
                    line,
                    fallback_path=worker_log,
                )

            storage_profile = str(getattr(self.config, "worker_storage_profile", "storage"))
            verify_root: Path | None = None
            try:
                if storage_profile not in self.profile_manager.list_profiles():
                    raise QuickModeError("Profile storage worker tidak tersedia.")
                storage_runtime = self.profile_manager.runtime(storage_profile)
                client = storage_runtime.export_tdl_client
                channel_ref = str(getattr(storage_runtime.config, "storage_channel_ref", "") or "")
                if not channel_ref:
                    raise QuickModeError("Storage channel belum dikonfigurasi.")
                verify_root = stage_root / ".quickmode-verify"
                verify_root.mkdir(mode=0o770, parents=True, exist_ok=True)
                storage_user = getattr(client, "run_as_user", None) or getattr(
                    storage_runtime.config, "tdl_export_user", None
                )
                # The executor may run as root while TDL storage runs as
                # user1. Make only this disposable directory writable by the
                # TDL user; never chown the stage's cloned sessions.
                ensure_quick_stage_writable(verify_root, storage_user)
                try:
                    verify_root.chmod(0o770)
                except OSError:
                    LOGGER.warning(
                        "Could not chmod Quick Mode verification directory %s",
                        verify_root,
                        exc_info=True,
                    )
                fallback_messages: list[dict[str, Any]] | None = None
                with storage_runtime.export_operation_lock:
                    with self._capture_tdl_output(client, log_callback=verify_log):
                        for name in expected_names:
                            item = known_items.get(name)
                            raw_id = item.get("channel_message_id") if isinstance(item, dict) else None
                            try:
                                message_id = int(raw_id) if raw_id is not None else None
                            except (TypeError, ValueError):
                                message_id = None
                            if message_id is not None:
                                target = verify_root / f"channel-{message_id}.json"
                                exported = client.export_messages(
                                    channel_ref,
                                    message_id,
                                    target,
                                    with_content=True,
                                    end_id=message_id,
                                )
                                matches = any(
                                    _quick_message_matches(message, name, caption, message_id)
                                    for message in exported.messages
                                )
                            else:
                                if fallback_messages is None:
                                    target = verify_root / "channel-recent.json"
                                    fallback_messages = client.export_messages(
                                        channel_ref,
                                        1,
                                        target,
                                        with_content=True,
                                        last_count=1000,
                                    ).messages
                                matches = any(
                                    _quick_message_matches(message, name, caption)
                                    for message in fallback_messages
                                )
                            if matches:
                                channel_found += 1
            except Exception as exc:
                channel_reason = str(exc)[:500]
            finally:
                if verify_root is not None:
                    shutil.rmtree(verify_root, ignore_errors=True)

            drive_found = 0
            drive_reason = ""
            destination = str(
                manifest.get("rclone_destination")
                or (
                    manifest.get("rclone_result", {}).get("destination", "")
                    if isinstance(manifest.get("rclone_result"), dict)
                    else ""
                )
                or "googledrive:backup"
            )
            try:
                verify_runner = RcloneRunner(
                    log_callback=verify_log,
                    command_callback=self._command_callback(),
                    stall_timeout_seconds=getattr(self.config, "job_stall_timeout_seconds", 600),
                )
                drive_result = verify_runner.verify_files(
                    archive_files,
                    destination,
                    Path(getattr(self.config, "rclone_config_path", "/data/.config/rclone.conf")),
                    workspace_root=workspace,
                    config_root=Path(getattr(self.config, "profile_root", "/data")),
                )
                drive_found = int(drive_result.get("found", 0))
                drive_errors = drive_result.get("errors")
                if drive_errors:
                    drive_reason = (
                        "Rclone gagal memverifikasi Google Drive. Periksa file konfigurasi "
                        f"{getattr(self.config, 'rclone_config_path', '/data/.config/rclone.conf')}: "
                        f"{str(drive_errors)[:500]}"
                    )
                elif drive_found < len(archive_files):
                    drive_reason = str(drive_result.get("missing") or "Archive belum lengkap di Google Drive.")[:500]
            except Exception as exc:
                drive_reason = str(exc)[:500]

            channel_expected = len(expected_names)
            drive_expected = len(archive_files)
            if channel_found == channel_expected and drive_found == drive_expected and not channel_reason and not drive_reason:
                try:
                    shutil.rmtree(stage_root)
                except OSError as exc:
                    verification = {
                        "status": "failed",
                        "channel_expected": channel_expected,
                        "channel_found": channel_found,
                        "drive_expected": drive_expected,
                        "drive_found": drive_found,
                        "checked_at": utc_now().isoformat(),
                        "reason": f"Cleanup staging gagal: {str(exc)[:400]}",
                    }
                    if stage_root.exists():
                        try:
                            write_quick_manifest(
                                stage_root,
                                {**manifest, "cleanup_verification": verification},
                            )
                        except OSError:
                            LOGGER.warning(
                                "Could not persist Quick Mode cleanup failure for %s",
                                stage_job_id,
                                exc_info=True,
                            )
                    return {
                        "stage_job_id": str(stage_job_id),
                        **verification,
                        "staging_cleaned": False,
                    }
                return {
                    "stage_job_id": str(stage_job_id),
                    "status": "verified",
                    "staging_cleaned": True,
                    "channel_expected": channel_expected,
                    "channel_found": channel_found,
                    "drive_expected": drive_expected,
                    "drive_found": drive_found,
                    "checked_at": utc_now().isoformat(),
                }

            status = "failed" if channel_reason or drive_reason else "pending"
            verification = {
                "status": status,
                "channel_expected": channel_expected,
                "channel_found": channel_found,
                "drive_expected": drive_expected,
                "drive_found": drive_found,
                "checked_at": utc_now().isoformat(),
                "reason": "; ".join(value for value in (channel_reason, drive_reason) if value)
                or "Sebagian file belum terdeteksi.",
            }
            write_quick_manifest(stage_root, {**manifest, "cleanup_verification": verification})
            return {
                "stage_job_id": str(stage_job_id),
                **verification,
                "staging_cleaned": False,
            }
        finally:
            with self._lock:
                self._quick_verify_active.discard(str(stage_job_id))

    def quickmode_delete(self, stage_job_id: str) -> dict[str, Any]:
        """Delete a retained stage only after confirming no worker operation owns it."""
        stage_job_id = str(stage_job_id).strip()
        workspace = self._quick_workspace(self.config)
        try:
            quick_stage_root(workspace, stage_job_id)
        except QuickModeError as exc:
            raise DomainError(
                "INVALID_STAGE_JOB_ID",
                str(exc),
                status_code=422,
            ) from exc

        with self._lock:
            if (
                stage_job_id in self._quick_delete_active
                or stage_job_id in self._quick_verify_active
                or stage_job_id in self._quick_stage_jobs.values()
            ):
                raise DomainError(
                    "QUICKMODE_STAGE_BUSY",
                    "Folder staging Quick Mode sedang dipakai job atau verifikasi worker.",
                    status_code=409,
                )
            self._quick_delete_active.add(stage_job_id)

        try:
            try:
                deleted = delete_quick_stage(workspace, stage_job_id)
            except QuickModeError as exc:
                raise DomainError(
                    "QUICKMODE_STAGE_UNSAFE",
                    str(exc),
                    status_code=409,
                ) from exc
            except OSError as exc:
                raise DomainError(
                    "QUICKMODE_STAGE_DELETE_FAILED",
                    f"Folder staging Quick Mode gagal dihapus: {exc}",
                    status_code=500,
                ) from exc
            return {
                "stage_job_id": stage_job_id,
                "deleted": bool(deleted),
            }
        finally:
            with self._lock:
                self._quick_delete_active.discard(stage_job_id)

    def quickmode_scan(self) -> dict[str, Any]:
        """Return derived Quick Mode staging state for the manager UI."""
        workspace = self._quick_workspace(self.config)
        return {
            "worker": str(getattr(self.config, "backup_node_name", "local")),
            "items": scan_quick_stages(
                workspace,
                worker=str(getattr(self.config, "backup_node_name", "local")),
            ),
        }

    @staticmethod
    def _digest(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size
