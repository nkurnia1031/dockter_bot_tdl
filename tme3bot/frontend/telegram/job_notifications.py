from __future__ import annotations

import threading
from typing import Any


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class JobNotificationRegistry:
    """Thread-safe lifecycle registry for transient Telegram status messages."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._lock = threading.RLock()

    def get(self, job_id: str) -> Any | None:
        with self._lock:
            return self._values.get(str(job_id))

    def set(self, job_id: str, message: Any) -> None:
        with self._lock:
            self._values[str(job_id)] = message

    def pop(self, job_id: str) -> Any | None:
        with self._lock:
            return self._values.pop(str(job_id), None)

    def __contains__(self, job_id: str) -> bool:
        with self._lock:
            return str(job_id) in self._values


def _value(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") or {}
    if not isinstance(result, dict):
        return {}
    value = result.get("value", result)
    return value if isinstance(value, dict) else {}


def _short(value: Any, limit: int = 180) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _rate(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    units = ("B/dtk", "KB/dtk", "MB/dtk", "GB/dtk")
    index = 0
    while number >= 1024 and index < len(units) - 1:
        number /= 1024
        index += 1
    return f"{number:.1f} {units[index]}"


def _kind_label(kind: str) -> str:
    return {
        "export": "Export",
        "download": "Download",
        "utility": "Utility",
        "storage_upload": "Storage upload",
        "backup_node": "Backup",
        "leave": "Leave source",
        "artifact_inventory": "Inventory artifact",
        "artifact_delete": "Hapus artifact",
    }.get(kind, kind.replace("_", " ").title())


def format_job_status(job: dict[str, Any]) -> str:
    """Format a status-only Telegram message without raw object output."""
    status = str(job.get("status") or "queued")
    kind = str(job.get("kind") or "job")
    if status == "succeeded":
        icon, verb = "✅", "selesai"
    elif status == "failed":
        icon, verb = "❌", "gagal"
    elif status == "cancelled":
        icon, verb = "⚠️", "dibatalkan"
    elif status in {"queued", "dispatched"}:
        icon, verb = "⏳", "masuk antrean"
    else:
        icon, verb = "⏳", "berjalan"

    lines = [f"{icon} {_kind_label(kind)} {verb}"]
    profile = job.get("profile")
    worker = job.get("worker")
    if profile or worker:
        lines.append(
            "Profile: " + str(profile or "-") + " · Worker: " + str(worker or "-")
        )
    if job.get("id"):
        lines.append(f"Job: {str(job['id'])[:16]}")

    progress = job.get("progress") or {}
    if isinstance(progress, dict):
        position = job.get("queue_position", progress.get("position"))
        if position is not None and status in {"queued", "dispatched"}:
            lines.append(f"Posisi antrean: {position}")
        if progress.get("blocked_reason") and status == "queued":
            lines.append(f"Menunggu: {_short(progress['blocked_reason'], 140)}")
        if progress.get("phase"):
            lines.append(f"Fase: {_short(progress['phase'], 80)}")
        if progress.get("message"):
            lines.append(f"Saat ini: {_short(progress['message'])}")
        batch = progress.get("batch")
        if isinstance(batch, dict) and batch.get("name"):
            lines.append(
                f"JSON: {_short(batch['name'], 100)} "
                f"({batch.get('index', '?')}/{batch.get('total', '?')})"
            )
        item = progress.get("item")
        if isinstance(item, dict) and item.get("name"):
            lines.append(
                f"File: {_short(item['name'], 100)} "
                f"({item.get('index', '?')}/{item.get('total', '?')})"
            )
        overall = progress.get("overall")
        if isinstance(overall, dict) and not progress.get("indeterminate"):
            percent = overall.get("percent")
            suffix = f" ({float(percent):.1f}%)" if isinstance(percent, (int, float)) else ""
            lines.append(
                f"Progress: {overall.get('current', '?')}/{overall.get('total', '?')}{suffix}"
            )
        transfer = progress.get("transfer")
        if isinstance(transfer, dict):
            speed = _rate(transfer.get("speed_bps"))
            if speed:
                lines.append(f"Speed: {speed}")
            if transfer.get("eta_seconds") is not None:
                lines.append(f"ETA: {transfer['eta_seconds']} dtk")
        counters = progress.get("counters")
        if isinstance(counters, dict):
            values = []
            for key, label in (("succeeded", "Berhasil"), ("failed", "Gagal"), ("skipped", "Skipped")):
                if counters.get(key) is not None:
                    values.append(f"{label}: {counters[key]}")
            if values:
                lines.append(" · ".join(values))

    if status in TERMINAL_STATUSES:
        value = _value(job)
        fields = (
            ("Message", value.get("message_count", value.get("exported_count"))),
            ("Media", value.get("media_count")),
            ("Foto", value.get("photo_count")),
            ("Video", value.get("video_count")),
            ("Latest ID", value.get("latest_id")),
            ("Group dibuat", value.get("groups_created")),
            ("Item dipindah", value.get("moved_count")),
            ("Part", value.get("part_count", value.get("parts"))),
        )
        for label, field_value in fields:
            if field_value is not None:
                lines.append(f"{label}: {field_value}")
        artifact = value.get("filename") or value.get("artifact_key")
        if isinstance(value.get("artifact"), dict):
            artifact = artifact or value["artifact"].get("filename")
        if artifact:
            lines.append(f"Artifact: {_short(artifact, 160)}")
        error = job.get("error")
        if isinstance(error, dict):
            error = error.get("message")
        if error:
            lines.append(f"Error: {_short(error, 240)}")
    return "\n".join(lines)
