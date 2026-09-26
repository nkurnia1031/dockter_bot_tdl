from __future__ import annotations

import uuid
from dataclasses import (
    asdict,
)
from pathlib import (
    Path,
)
from tme3bot.export_catalog import (
    discard_export_without_media,
    inspect_export_json,
)
from tme3bot.progress_reporter import (
    ProgressReporter,
)
from typing import (
    Any,
)

from .executor_support import (
    LOGGER,
)

class DownloadExecutorMixin:

    def _download(self, command: dict[str, Any]) -> Any:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        payload = command["payload"]
        artifact_refs = [
            {
                "key": str(item.get("key") or ""),
                "status": str(item.get("status") or "pending"),
            }
            for item in payload.get("artifacts", [])
            if isinstance(item, dict)
        ]
        if not artifact_refs:
            artifact_refs = [
                {"key": str(item), "status": "pending"}
                for item in payload.get("artifact_keys", [])
            ]
        existing_refs: list[dict[str, str]] = []
        missing_keys: list[str] = []
        if artifact_refs:
            roots = {
                "pending": runtime.config.export_pending_dir.resolve(),
                "failed": runtime.config.export_failed_dir.resolve(),
            }
            for artifact in artifact_refs:
                key = artifact["key"]
                source_root = roots.get(artifact["status"])
                candidate = (
                    (source_root / key).resolve()
                    if source_root is not None
                    else Path("")
                )
                if (
                    source_root is not None
                    and Path(key).name == key
                    and key.lower().endswith(".json")
                    and candidate.parent == source_root
                    and candidate.is_file()
                ):
                    existing_refs.append(artifact)
                    continue
                missing_keys.append(key)
                self._append_job_log(f"[artifact missing: {key}]")
                self.publisher.emit(
                    str(command["job_id"]),
                    "running",
                    "artifact.missing",
                    result={
                        "artifact": {
                            "profile": str(command["profile"]),
                            "worker": str(command.get("worker") or self.config.backup_node_name),
                            "artifact_key": key,
                        }
                    },
                )

        def report_snapshot(snapshot, *, force: bool = False) -> dict[str, Any]:
            total_json = max(0, snapshot.total_json)
            json_done = max(
                snapshot.success_count + snapshot.failed_count,
                snapshot.current_json_index - 1,
            )
            item_percent = snapshot.tdl_percent
            overall_percent = None
            if total_json:
                partial = (
                    item_percent / 100
                    if item_percent is not None and snapshot.current_json_index
                    else 0
                )
                overall_percent = min(
                    100.0, (json_done + partial) * 100 / total_json
                )
            return reporter.report(
                phase=snapshot.phase,
                message=(
                    f"Memproses {snapshot.current_json_name}"
                    if snapshot.current_json_name
                    else "Menyiapkan antrean download"
                ),
                batch={
                    "name": snapshot.current_json_name,
                    "index": snapshot.current_json_index or None,
                    "total": total_json or None,
                    "unit": "json",
                },
                overall={
                    "current": json_done,
                    "total": total_json,
                    "percent": overall_percent,
                    "unit": "json",
                },
                item={
                    "name": snapshot.tdl_file_name,
                    "index": snapshot.tdl_fraction_current,
                    "total": (
                        snapshot.tdl_fraction_total
                        or snapshot.current_media_total
                    ),
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
                    "skipped": len(missing_keys),
                },
                indeterminate=item_percent is None and snapshot.active,
                force=force,
            )

        def progress_event(event_type: str, snapshot) -> None:
            progress = report_snapshot(
                snapshot, force=event_type != "progress"
            )
            milestones = {
                "json_started": "download.json_started",
                "json_completed": "download.json_completed",
                "json_failed": "download.json_failed",
            }
            milestone = milestones.get(event_type)
            if milestone:
                details = {
                    "json_name": snapshot.current_json_name,
                    "json_index": snapshot.current_json_index,
                    "json_total": snapshot.total_json,
                    "media_total": snapshot.current_media_total,
                }
                reporter.milestone(
                    milestone,
                    progress=progress,
                    result=details if event_type != "json_failed" else None,
                    error=(
                        {"message": snapshot.last_error or "Download JSON gagal."}
                        if event_type == "json_failed"
                        else None
                    ),
                )

        with self._download_progress_operation(runtime, progress_event):
            with self._capture_tdl_output(runtime.download_tdl_client):
                if payload.get("retry_failed") and not artifact_refs:
                    result = runtime.download_service.retry_failed_exports()
                elif artifact_refs:
                    if not existing_refs:
                        progress = reporter.report(
                            phase="completed",
                            message=(
                                f"Tidak ada JSON tersedia; "
                                f"{len(missing_keys)} dilewati"
                            ),
                            overall={
                                "current": 0,
                                "total": 0,
                                "percent": 100,
                                "unit": "json",
                            },
                            counters={"skipped": len(missing_keys)},
                            force=True,
                        )
                        reporter.milestone(
                            "download.completed",
                            progress=progress,
                            result={
                                "success_count": 0,
                                "failed_count": 0,
                                "skipped_missing": len(missing_keys),
                            },
                        )
                        return {
                            "moved_count": 0,
                            "success_count": 0,
                            "failed_count": 0,
                            "skipped_missing": len(missing_keys),
                            "results": [],
                        }
                    result = runtime.download_service.download_selected_artifacts(
                        existing_refs
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
                            "worker": str(command.get("worker") or self.config.backup_node_name),
                            "artifact_key": item.json_path.name,
                            "status": "downloaded" if item.status == "success" else "failed",
                            "download_directory": str(item.download_dir),
                            "error": item.error,
                            "available": True,
                        }
                    },
                )
            progress = reporter.report(
                phase="completed",
                message=(
                    f"Download selesai: {result.success_count} JSON berhasil, "
                    f"{result.failed_count} gagal, {len(missing_keys)} dilewati"
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
                    "skipped": len(missing_keys),
                },
                force=True,
            )
            summary = {
                **asdict(result),
                "skipped_missing": len(missing_keys),
            }
            reporter.milestone(
                "download.completed",
                progress=progress,
                result={
                    "success_count": result.success_count,
                    "failed_count": result.failed_count,
                    "skipped_missing": len(missing_keys),
                },
            )
            return summary

    def _download_clear_failed(self, command: dict[str, Any]) -> dict[str, int]:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        return {"deleted": runtime.download_service.clear_failed_exports()}

    def _artifact_inventory(self, command: dict[str, Any]) -> dict[str, Any]:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        inventory_id = str(
            command.get("payload", {}).get("inventory_id") or uuid.uuid4()
        )
        locations = (
            ("pending", runtime.config.export_pending_dir),
            ("processing", runtime.config.export_processing_dir),
            ("downloaded", runtime.config.export_done_dir),
            ("failed", runtime.config.export_failed_dir),
        )
        discovered = 0
        inventory_batch: list[dict[str, Any]] = []
        profile_name = str(command["profile"])
        seen_cache_keys: set[tuple[str, str]] = set()

        def publish_inventory_batch() -> None:
            if not inventory_batch:
                return
            self.publisher.emit(
                str(command["job_id"]),
                "running",
                "artifact.inventory_batch",
                result={"artifacts": list(inventory_batch)},
            )
            inventory_batch.clear()

        for status, root in locations:
            for path in sorted(root.glob("*.json")):
                cache_key = (profile_name, str(path))
                try:
                    file_stat = path.stat()
                    fingerprint = (
                        int(getattr(file_stat, "st_ino", 0)),
                        int(file_stat.st_size),
                        int(file_stat.st_mtime_ns),
                    )
                except OSError as exc:
                    LOGGER.warning("Artifact inventory skipped %s: %s", path, exc)
                    continue
                seen_cache_keys.add(cache_key)
                with self._lock:
                    cached = self._inventory_cache.get(cache_key)
                if cached is not None and cached[0] == fingerprint:
                    stats = dict(cached[1])
                else:
                    try:
                        stats = inspect_export_json(path)
                    except (OSError, ValueError) as exc:
                        with self._lock:
                            self._inventory_cache.pop(cache_key, None)
                        LOGGER.warning("Artifact inventory skipped %s: %s", path, exc)
                        continue
                    with self._lock:
                        self._inventory_cache[cache_key] = (fingerprint, dict(stats))
                if stats.get("media_count") == 0:
                    try:
                        discard_export_without_media(path, stats)
                    except OSError as exc:
                        LOGGER.warning(
                            "Could not remove media-less export during inventory %s: %s",
                            path,
                            exc,
                        )
                    with self._lock:
                        self._inventory_cache.pop(cache_key, None)
                    # Do not publish an artifact for an empty export. Existing
                    # catalog rows are intentionally left to inventory
                    # completion, which marks files no longer present as
                    # unavailable for audit/history.
                    continue
                inventory_batch.append(
                    {
                        **stats,
                        "profile": profile_name,
                        "worker": str(command.get("worker") or self.config.backup_node_name),
                        "filename": path.name,
                        "artifact_key": path.name,
                        "status": status,
                        "available": True,
                        "last_seen_inventory_id": inventory_id,
                    }
                )
                discovered += 1
                if len(inventory_batch) >= 100:
                    publish_inventory_batch()
        with self._lock:
            stale_keys = [
                key
                for key in self._inventory_cache
                if key[0] == profile_name and key not in seen_cache_keys
            ]
            for key in stale_keys:
                self._inventory_cache.pop(key, None)
        publish_inventory_batch()
        inventory = {
            "inventory_id": inventory_id,
            "profile": str(command["profile"]),
            "worker": str(command.get("worker") or self.config.backup_node_name),
            "discovered": discovered,
        }
        self.publisher.emit(
            str(command["job_id"]),
            "running",
            "artifact.inventory_completed",
            result={"inventory": inventory},
        )
        return {"discovered": discovered, "inventory_id": inventory_id}

    def _artifact_delete(self, command: dict[str, Any]) -> dict[str, Any]:
        runtime = self.profile_manager.runtime(str(command["profile"]))
        payload = command["payload"]
        keys = payload.get("artifact_keys") or []
        if not keys and payload.get("artifact_key"):
            keys = [payload["artifact_key"]]
        if not isinstance(keys, (list, tuple, set)):
            keys = [keys]
        deleted: list[str] = []
        missing: list[str] = []
        for raw_key in keys:
            key = str(raw_key)
            if Path(key).name != key or not key.lower().endswith(".json"):
                raise ValueError("Artifact key tidak valid.")
            found = False
            for root in (runtime.config.export_pending_dir, runtime.config.export_failed_dir):
                candidate = (root.resolve() / key).resolve()
                try:
                    candidate.relative_to(root.resolve())
                except ValueError:
                    continue
                if candidate.is_file():
                    candidate.unlink()
                    deleted.append(key)
                    found = True
                    break
            if not found:
                missing.append(key)
        return {"deleted": deleted, "missing": missing}
