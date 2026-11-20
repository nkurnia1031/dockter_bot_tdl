from __future__ import annotations

from pathlib import (
    Path,
)
from tme3bot.progress_reporter import (
    ProgressReporter,
)
from tme3bot.utility import (
    MEDIA_UTILITIES,
    UtilityRunner,
)
from typing import (
    Any,
)

from .executor_support import (
    _utility_progress_message,
    json_value,
)

class UtilityExecutorMixin:

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
        media_mode = utility_name in MEDIA_UTILITIES
        counters = {"succeeded": 0, "failed": 0, "skipped": 0}
        media_counters: dict[str, Any] | None = None
        active_media_items: dict[str, set[str]] = {"video": set(), "image": set()}
        completed_media_items: set[tuple[str, str]] = set()

        def media_snapshot() -> dict[str, Any] | None:
            if media_counters is None:
                return None
            return {
                "scan_complete": bool(media_counters["scan_complete"]),
                "video": dict(media_counters["video"]),
                "image": dict(media_counters["image"]),
                "skipped": dict(media_counters["skipped"]),
            }

        def update_media_counters(value: dict[str, object], phase: str) -> None:
            nonlocal media_counters
            if phase == "media_scan_completed":
                totals = value.get("media_totals")
                totals = totals if isinstance(totals, dict) else {}
                media_counters = {
                    "scan_complete": True,
                    "video": {
                        "total": max(0, int(totals.get("video") or 0)),
                        "running": 0,
                        "succeeded": 0,
                        "failed": 0,
                        "skipped": 0,
                    },
                    "image": {
                        "total": max(0, int(totals.get("image") or 0)),
                        "running": 0,
                        "succeeded": 0,
                        "failed": 0,
                        "skipped": 0,
                    },
                    "skipped": {
                        "estimated_savings_below_threshold": 0,
                        "recode_output_exists": 0,
                    },
                }
                return

            if media_counters is None:
                return
            media_type = str(value.get("media_type") or "")
            if media_type not in {"video", "image"}:
                return
            name = str(value.get("name") or "")
            if not name:
                return
            terminal_phases = {
                "item_completed": "succeeded",
                "item_failed": "failed",
                "item_skipped": "skipped",
            }
            if phase in {"media_preflight_started", "item_started"}:
                if (media_type, name) not in completed_media_items:
                    active_media_items[media_type].add(name)
            elif phase in terminal_phases and (media_type, name) not in completed_media_items:
                completed_media_items.add((media_type, name))
                active_media_items[media_type].discard(name)
                outcome = terminal_phases[phase]
                media_counters[media_type][outcome] += 1
                if outcome == "skipped":
                    reason_code = str(value.get("reason_code") or "")
                    if reason_code == "VIDEO_ESTIMATED_SAVINGS_BELOW_THRESHOLD":
                        media_counters["skipped"]["estimated_savings_below_threshold"] += 1
                    elif reason_code in {"VIDEO_RECODE_OUTPUT_EXISTS", "IMAGE_RECODE_OUTPUT_EXISTS"}:
                        media_counters["skipped"]["recode_output_exists"] += 1
            media_counters[media_type]["running"] = len(active_media_items[media_type])

        def utility_progress(value: dict[str, object]) -> None:
            phase = str(value.get("phase") or utility_name)
            if media_mode:
                update_media_counters(value, phase)
            archive_phase = utility_name == "extract" and phase in {
                "archive_completed", "archive_failed"
            }
            if archive_phase and phase == "archive_completed":
                counters["succeeded"] += 1
            elif archive_phase and phase == "archive_failed":
                counters["failed"] += 1
            elif not archive_phase and phase in {
                "item_completed", f"{utility_name}_folder_completed"
            }:
                counters["succeeded"] += 1
            elif not archive_phase and phase in {
                "item_failed", f"{utility_name}_folder_failed"
            }:
                counters["failed"] += 1
            elif not archive_phase and phase == "item_skipped":
                counters["skipped"] += 1
            index = int(value.get("index") or value.get("folder_index") or 0)
            total = int(value.get("total") or value.get("folder_total") or len(folders))
            folder_index = int(value.get("folder_index") or 1)
            folder_total = int(value.get("folder_total") or len(folders))
            percent = value.get("percent")
            media_overall = value.get("overall") if media_mode else None
            if media_mode and isinstance(media_overall, dict):
                overall = dict(media_overall)
            elif media_mode:
                overall = {
                    "current": value.get("files_discovered", 0),
                    "total": None,
                    "percent": None,
                    "unit": "files",
                    "files_current": value.get("files_discovered", 0),
                }
            elif archive_phase:
                archive_fraction = (
                    index / total
                    if total and phase in {"archive_completed", "archive_failed"}
                    else 0.0
                )
                overall_current = max(0, folder_index - 1) + archive_fraction
                overall_percent = (
                    overall_current * 100 / folder_total if folder_total else None
                )
                overall = {
                    "current": overall_current,
                    "total": folder_total,
                    "percent": overall_percent,
                    "unit": "folders",
                }
            else:
                overall = {
                    "current": max(index - (0 if "completed" in phase else 1), 0),
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
                }
            item_name = str(
                value.get("name")
                or value.get("folder")
                or (folders[min(max(index - 1, 0), len(folders) - 1)] if folders else "")
            )
            progress_counters = dict(counters)
            media_snapshot_value = media_snapshot() if media_mode else None
            if media_snapshot_value is not None:
                progress_counters["media"] = media_snapshot_value
            progress_payload = reporter.report(
                phase=phase,
                message=_utility_progress_message(utility_name, phase, item_name),
                overall=overall,
                item={
                    "name": item_name,
                    "index": index or None,
                    "total": total or None,
                    "size_bytes": value.get("size_bytes"),
                    "percent": percent,
                    "pass_name": value.get("pass_name"),
                    "stage": value.get("stage"),
                    "codec": value.get("codec"),
                    "resolution": value.get("resolution"),
                    "estimated_savings_percent": value.get("estimated_savings_percent"),
                    "minimum_estimated_savings_percent": value.get("minimum_estimated_savings_percent"),
                    "reason": value.get("reason"),
                    "reason_code": value.get("reason_code"),
                    "media_type": value.get("media_type"),
                    "files_discovered": value.get("files_discovered"),
                },
                transfer=reporter.transfer_metrics(
                    speed_bps=value.get("speed_bps"),
                    current_bytes=value.get("bytes_current"),
                    total_bytes=value.get("size_bytes"),
                    eta_seconds=value.get("eta_seconds"),
                    elapsed_seconds=value.get("elapsed_seconds"),
                    percent=float(percent) if isinstance(percent, (int, float)) else None,
                ),
                counters=progress_counters,
                indeterminate=bool(value.get("indeterminate", percent is None)),
                force=phase.endswith("_starting") or phase in {
                    "item_completed", "item_failed", "item_skipped", "archive_completed", "archive_failed",
                    "media_archive_completed", "media_archive_failed",
                    "media_scan_completed", "media_preflight_started", "item_started",
                    "extract_folder_completed", "extract_folder_failed",
                    "flatten_preview_completed", "flatten_folder_completed",
                },
            )
            if phase in {
                "item_completed", "item_failed", "item_skipped", "archive_completed", "archive_failed"
            }:
                reporter.milestone(
                    phase,
                    progress=progress_payload,
                    error=(
                        {
                            "message": str(value.get("error") or "Arsip gagal setelah retry."),
                            "item": item_name,
                        }
                        if phase in {"item_failed", "archive_failed"}
                        else None
                    ),
                )

        job_id = str(command["job_id"])
        runner = UtilityRunner(
            Path("/app/utility") if Path("/app/utility").exists() else Path("utility"),
            log_callback=self._append_job_log,
            command_callback=self._command_callback(),
            stall_timeout_seconds=getattr(
                self.config, "job_stall_timeout_seconds", 600
            ),
            owner_job_id=job_id,
            progress_callback=utility_progress,
        )
        with self._lock:
            self._utility_runners[job_id] = runner
        try:
            result = json_value(
                runner.run(
                    utility_name,
                    [str(item) for item in folders],
                    payload.get("password"),
                    payload.get("settings") or {},
                    flatten_action=payload.get("flatten_action"),
                    flatten_fingerprints=payload.get("flatten_fingerprints"),
                    video_options=payload.get("video_options"),
                )
            )
            archive_mode = utility_name == "extract"
            media_summary = result.get("summary", {})
            media_failed = int(media_summary.get("files_failed", 0)) if media_mode else 0
            media_succeeded = int(media_summary.get("files_succeeded", 0)) if media_mode else 0
            media_skipped = int(media_summary.get("files_skipped", 0)) if media_mode else 0
            media_total = int(media_summary.get("files_total", 0)) if media_mode else 0
            archive_succeeded = int(result.get("summary", {}).get("archives_succeeded", 0))
            archive_partial = int(result.get("summary", {}).get("archives_partial", 0))
            archive_failed = int(result.get("summary", {}).get("archives_failed", 0))
            failed_outcome = result.get("outcome") in {"failed", "partial_failure"}
            final_phase = (
                "utility_failed"
                if media_mode and failed_outcome
                else "completed"
            )
            if archive_mode and failed_outcome:
                final_phase = "extract_failed"
            if media_mode:
                final_message = (
                    f"Konversi media selesai: {media_succeeded} file berhasil, "
                    f"{media_failed} gagal, {media_skipped} dilewati dari {media_total}."
                )
                final_overall = {
                    "current": media_succeeded + media_failed + media_skipped,
                    "total": media_total,
                    "percent": 100,
                    "unit": "files",
                    "files_current": media_succeeded + media_failed + media_skipped,
                    "files_total": media_total,
                }
                final_counters = {
                    "succeeded": media_succeeded,
                    "failed": media_failed,
                    "skipped": media_skipped,
                }
                if isinstance(media_summary.get("media"), dict):
                    final_counters["media"] = media_summary["media"]
            else:
                final_message = (
                    (
                        f"Extract selesai: {archive_succeeded} arsip berhasil"
                        + (f" ({archive_partial} parsial)" if archive_partial else "")
                        + ", "
                        f"{archive_failed} gagal"
                    )
                    if archive_mode
                    else (
                        f"Utility selesai: {len(result.get('succeeded', []))} folder berhasil, "
                        f"{len(result.get('failed', {}))} gagal"
                    )
                )
                final_overall = {
                    "current": archive_succeeded + archive_failed if archive_mode else len(folders),
                    "total": result.get("summary", {}).get("archives_processed", 0) if archive_mode else len(folders),
                    "percent": 100,
                    "unit": "archives" if archive_mode else "folders",
                }
                final_counters = {
                    "succeeded": archive_succeeded if archive_mode else len(result.get("succeeded", [])),
                    "failed": archive_failed if archive_mode else len(result.get("failed", {})),
                }
            reporter.report(
                phase=final_phase,
                message=final_message,
                overall=final_overall,
                counters=final_counters,
                force=True,
            )
            return result
        finally:
            with self._lock:
                self._utility_runners.pop(job_id, None)
