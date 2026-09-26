from __future__ import annotations

from pathlib import (
    Path,
)
from tme3bot.progress_reporter import (
    ProgressReporter,
)
from tme3bot.utility import (
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
            command_callback=self._command_callback(),
            stall_timeout_seconds=getattr(
                self.config, "job_stall_timeout_seconds", 600
            ),
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
