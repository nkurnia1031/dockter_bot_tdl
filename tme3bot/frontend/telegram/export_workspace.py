from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

EXPORT_WORKSPACE_TTL_SECONDS = 30 * 60


def normalize_chat_ref(chat_ref: str) -> str:
    """Match backend source canonicalization without importing its state store."""
    value = str(chat_ref or "").strip()
    if not value:
        return ""
    if value.lstrip("-").isdigit():
        return value
    return value.lstrip("@").casefold()


def is_numeric_chat_ref(chat_ref: str | None) -> bool:
    value = normalize_chat_ref(str(chat_ref or ""))
    return bool(value) and value.lstrip("-").isdigit()


def short_text(value: Any, limit: int = 80) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_rate(value: Any) -> str:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return ""
    if rate < 1024:
        return f"{rate:.0f} B/dtk"
    units = ("KB/dtk", "MB/dtk", "GB/dtk")
    number = rate
    for unit in units:
        number /= 1024
        if number < 1024 or unit == units[-1]:
            return f"{number:.1f} {unit}"
    return ""


def result_value(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") or {}
    if not isinstance(result, dict):
        return {}
    value = result.get("value", result)
    return value if isinstance(value, dict) else {}


def export_report(job: dict[str, Any]) -> dict[str, Any]:
    value = result_value(job)
    progress = job.get("progress") or {}
    artifact = value.get("artifact")
    artifact = artifact if isinstance(artifact, dict) else {}
    return {
        "status": job.get("status", "-"),
        "message_count": value.get("message_count", value.get("exported_count")),
        "media_count": value.get("media_count"),
        "photo_count": value.get("photo_count"),
        "video_count": value.get("video_count"),
        "latest_id": value.get("latest_id"),
        "filename": value.get("filename") or artifact.get("filename"),
        "artifact": value.get("artifact_key") or artifact.get("artifact_key"),
        "artifact_deleted": value.get("artifact_deleted"),
        "artifact_delete_reason": value.get("artifact_delete_reason"),
        "artifact_delete_error": value.get("artifact_delete_error"),
        "progress_message": progress.get("message"),
        "error": (job.get("error") or {}).get("message") if isinstance(job.get("error"), dict) else job.get("error"),
    }


def format_export_job(job: dict[str, Any]) -> str:
    """Render job details without exposing raw dictionaries or empty counters."""
    progress = job.get("progress") or {}
    lines = [f"Status: {job.get('status', '-')}" ]
    if job.get("id"):
        lines.append(f"Job: {str(job['id'])[:12]}")
    profile = job.get("profile")
    worker = job.get("worker")
    if profile or worker:
        lines.append(
            "  •  ".join(
                value for value in (f"Profile: {profile}" if profile else "", f"Worker: {worker}" if worker else "") if value
            )
        )
    if job.get("queue_position") is not None:
        lines.append(f"Posisi antrean: {job['queue_position']}")
    if progress.get("blocked_reason"):
        lines.append(f"Menunggu: {short_text(progress['blocked_reason'], 140)}")
    if progress.get("message"):
        lines.append(f"Saat ini: {short_text(progress['message'], 160)}")
    batch = progress.get("batch")
    if isinstance(batch, dict) and batch.get("name"):
        position = ""
        if batch.get("index") is not None:
            position = f" ({batch.get('index')}/{batch.get('total', '?')})"
        lines.append(f"JSON: {short_text(batch['name'], 120)}{position}")
    item = progress.get("item")
    if isinstance(item, dict) and item.get("name"):
        position = ""
        if item.get("index") is not None:
            position = f" ({item.get('index')}/{item.get('total', '?')})"
        lines.append(f"File: {short_text(item['name'], 120)}{position}")
    transfer = progress.get("transfer")
    if isinstance(transfer, dict):
        speed = format_rate(transfer.get("speed_bps")) or short_text(
            transfer.get("speed_text"), 60
        )
        if speed:
            lines.append(f"Speed: {speed}")
        if transfer.get("eta_seconds") is not None:
            lines.append(f"ETA: {transfer['eta_seconds']} dtk")
    overall = progress.get("overall")
    if isinstance(overall, dict):
        current = overall.get("current", "?")
        total = overall.get("total", "?")
        percent = overall.get("percent")
        suffix = f" ({percent:.1f}%)" if isinstance(percent, (int, float)) else ""
        lines.append(f"Progress: {current}/{total}{suffix}")

    if job.get("status") in {"succeeded", "failed", "cancelled"}:
        report = export_report(job)
        for label, key in (
            ("Message", "message_count"),
            ("Media", "media_count"),
            ("Foto", "photo_count"),
            ("Video", "video_count"),
            ("Latest ID", "latest_id"),
        ):
            if report[key] is not None:
                lines.append(f"{label}: {report[key]}")
        if report["filename"] or report["artifact"]:
            lines.append(f"Artifact: {report['filename'] or report['artifact']}")
        elif report["artifact_deleted"]:
            lines.append("Artifact: JSON dihapus otomatis (tidak ada media)")
        if report["artifact_delete_error"]:
            lines.append(
                f"Peringatan cleanup: {short_text(report['artifact_delete_error'], 240)}"
            )
        if report["error"]:
            lines.append(f"Error: {short_text(report['error'], 240)}")
    return "\n".join(lines)


def format_export_status(job: dict[str, Any]) -> str:
    """Format the standalone status message without a Telegram keyboard."""
    status = str(job.get("status") or "queued")
    if status == "succeeded":
        heading = "✅ Export selesai"
    elif status == "failed":
        heading = "❌ Export gagal"
    elif status == "cancelled":
        heading = "⚠️ Export dibatalkan"
    elif status in {"queued", "dispatched"}:
        heading = "⏳ Export masuk antrean"
    else:
        heading = "⏳ Export sedang berjalan"
    return f"{heading}\n{format_export_job(job)}"


@dataclass
class ExportWorkspaceState:
    source: dict[str, Any] | None = None
    chat_ref: str | None = None
    label: str | None = None
    start_id: int | None = None
    overwrite_start_id: bool = False
    save_source: bool = False
    active_job_id: str | None = None
    job_snapshot: dict[str, Any] | None = None
    source_page: int = 0
    source_picker: bool = False
    source_query: str = ""
    label_page: int = 0
    touched_at: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.touched_at = time.monotonic()

    def select_source(self, source: dict[str, Any]) -> None:
        ref = normalize_chat_ref(str(source.get("chat_ref", "")))
        if not ref:
            raise ValueError("Source tidak valid.")
        self.source = dict(source)
        self.source["chat_ref"] = ref
        self.chat_ref = ref
        self.start_id = None
        self.overwrite_start_id = False
        self.save_source = is_numeric_chat_ref(ref)
        self.source_page = 0
        self.source_picker = False
        self.source_query = ""
        self.clear_job_view()
        self.touch()

    def select_chat_ref(self, chat_ref: str, source: dict[str, Any] | None = None) -> None:
        ref = normalize_chat_ref(chat_ref)
        if not ref:
            raise ValueError("Username atau numeric chat ID wajib diisi.")
        self.chat_ref = ref
        self.source = dict(source) if source is not None else None
        if self.source is not None:
            self.source["chat_ref"] = ref
        self.start_id = None
        self.overwrite_start_id = False
        self.save_source = source is not None and is_numeric_chat_ref(ref)
        self.source_page = 0
        self.source_picker = False
        self.source_query = ""
        self.clear_job_view()
        self.touch()

    def set_job(self, job: dict[str, Any]) -> None:
        self.active_job_id = str(job.get("id", "")) or None
        self.job_snapshot = dict(job)
        self.touch()

    def clear_job_view(self) -> None:
        self.active_job_id = None
        self.job_snapshot = None

    def set_label(self, label: str | None) -> None:
        value = str(label or "").strip()
        self.label = value or None
        self.touch()

    def set_start_id(self, value: str | int | None) -> None:
        if value is None or str(value).strip() == "":
            self.start_id = None
            self.overwrite_start_id = False
            self.touch()
            return
        parsed = int(str(value).strip())
        if parsed < 1:
            raise ValueError("Start ID harus berupa angka minimal 1.")
        self.start_id = parsed
        self.overwrite_start_id = True
        self.touch()

    def set_overwrite_start_id(self, enabled: bool) -> None:
        self.overwrite_start_id = bool(enabled)
        if not self.overwrite_start_id:
            self.start_id = None
        self.touch()

    def set_save_source(self, enabled: bool) -> None:
        self.save_source = bool(enabled)
        self.touch()

    @property
    def default_start_id(self) -> int:
        if self.source is None:
            return 1
        return max(1, int(self.source.get("last_id", 0)) + 1)

    @property
    def effective_start_id(self) -> int:
        if self.overwrite_start_id and self.start_id is not None:
            return self.start_id
        return self.default_start_id

    def payload(self) -> dict[str, Any]:
        if not self.chat_ref:
            raise ValueError("Pilih source terlebih dahulu.")
        payload: dict[str, Any] = {"chat_ref": normalize_chat_ref(self.chat_ref)}
        if self.label:
            payload["label"] = self.label
        if self.overwrite_start_id:
            if self.start_id is None:
                raise ValueError("Isi Start ID manual atau matikan overwrite.")
            payload["start_id"] = self.start_id
            # The worker builds the legacy URL from this value.  This flag tells
            # ExportService to honor the explicit message ID instead of the
            # persisted source last_id.
            payload["use_url_message_id"] = True
        else:
            payload["use_url_message_id"] = False
        if is_numeric_chat_ref(self.chat_ref):
            payload["save_source"] = self.save_source
        return payload


class ExportWorkspaceStore:
    def __init__(self, ttl_seconds: int = EXPORT_WORKSPACE_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._values: dict[tuple[int, int], ExportWorkspaceState] = {}
        self._lock = threading.RLock()

    def get(self, chat_id: int, user_id: int) -> ExportWorkspaceState:
        key = (int(chat_id), int(user_id))
        with self._lock:
            current = self._values.get(key)
            if current is None or time.monotonic() - current.touched_at > self.ttl_seconds:
                current = ExportWorkspaceState()
                self._values[key] = current
            current.touch()
            return current

    def clear(self, chat_id: int, user_id: int) -> None:
        with self._lock:
            self._values.pop((int(chat_id), int(user_id)), None)
