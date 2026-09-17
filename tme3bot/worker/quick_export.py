"""Helpers for the media thumbnail stage of Quick Mode exports."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import signal
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from tme3bot.url_parser import slugify_label


class QuickModeError(RuntimeError):
    """A user-actionable error in the Quick Mode pipeline."""


QUICK_PHASES = (
    "exporting",
    "downloading",
    "thumbnailing",
    "compressing",
    "uploading",
    "cleanup",
)
_STAGE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


PHOTO_EXTENSIONS = frozenset({
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
})
VIDEO_EXTENSIONS = frozenset({
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
})


def quick_year(now: datetime | None = None) -> int:
    current = now or datetime.now(ZoneInfo("Asia/Jakarta"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Jakarta"))
    return current.astimezone(ZoneInfo("Asia/Jakarta")).year


def quick_folder_name(export_path: Path) -> str:
    """Return the deterministic folder name used by staging and Storage."""
    return slugify_label(Path(export_path).stem)[:120] or "tanpa-label"


def quick_storage_caption(folder_name: str, year: int) -> str:
    return f"{folder_name}\n#ModeCepat #{year}"


def quick_stage_root(workspace: Path, stage_job_id: str) -> Path:
    """Return the visible, validated staging root for one Quick Mode chain."""
    stage_id = str(stage_job_id).strip()
    if not _STAGE_ID_RE.fullmatch(stage_id):
        raise QuickModeError("ID staging Quick Mode tidak valid.")
    workspace = Path(workspace).resolve()
    root = (workspace / "quickmode" / stage_id).resolve()
    try:
        root.relative_to(workspace)
    except ValueError as exc:
        raise QuickModeError("Staging Quick Mode keluar dari workspace.") from exc
    return root


def migrate_legacy_quick_stage(workspace: Path, stage_job_id: str) -> Path:
    """Move the old hidden staging tree into the admin-visible location."""
    target = quick_stage_root(workspace, stage_job_id)
    legacy = (Path(workspace).resolve() / ".tme3bot-quick" / str(stage_job_id)).resolve()
    if legacy == target or not legacy.exists() or target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy), str(target))
    return target


def read_quick_manifest(stage_root: Path) -> dict[str, object]:
    path = Path(stage_root) / "quickmode.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_quick_manifest(stage_root: Path, values: dict[str, object]) -> None:
    """Persist non-secret phase metadata atomically for retry/recovery."""
    path = Path(stage_root) / "quickmode.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(values, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def visual_media(root: Path) -> tuple[list[Path], list[Path]]:
    """Find original visual media while ignoring generated thumbnails."""
    photos: list[Path] = []
    videos: list[Path] = []
    for path in sorted(
        (candidate for candidate in root.rglob("*") if candidate.is_file()),
        key=lambda item: item.as_posix().casefold(),
    ):
        suffix = path.suffix.casefold()
        if suffix in PHOTO_EXTENSIONS:
            stem = path.stem.casefold()
            if "thumb" not in stem and not stem.startswith(".video-contact-sheet-"):
                photos.append(path)
        elif suffix in VIDEO_EXTENSIONS:
            videos.append(path)
    return photos, videos


class QuickThumbnailBuilder:
    """Build a bounded, padded visual collage using ffmpeg/ffprobe.

    The process handle is retained so the worker can interrupt an active
    ffmpeg invocation when the enclosing job is cancelled.
    """

    def __init__(
        self,
        *,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.log_callback = log_callback
        self._process_lock = threading.RLock()
        self._current_process: subprocess.Popen[str] | None = None

    def cancel_current(self) -> bool:
        with self._process_lock:
            process = self._current_process
        if process is None or process.poll() is not None:
            return False
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(process.pid), signal.SIGINT)
            else:  # pragma: no cover - production workers run on Linux
                process.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, ProcessLookupError):
            return False
        return True

    def build(self, media_root: Path, output_path: Path) -> dict[str, object]:
        media_root = Path(media_root).resolve()
        output_path = Path(output_path).resolve()
        contact_sheets: list[Path] = []
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            photos, videos = visual_media(media_root)
            selected = photos[:4]
            for index, video in enumerate(videos[:4], start=1):
                contact_sheet = output_path.parent / f".video-contact-sheet-{index}.png"
                contact_sheets.append(contact_sheet)
                contact_sheet.unlink(missing_ok=True)
                self._video_contact_sheet(video, contact_sheet)
            selected.extend(contact_sheets)
            if not selected:
                raise QuickModeError(
                    "Quick Mode tidak menemukan foto atau video yang dapat dibuat thumbnail."
                )
            self._compose(selected, output_path)
        finally:
            for contact_sheet in contact_sheets:
                contact_sheet.unlink(missing_ok=True)
        return {
            "photos_used": min(len(photos), 4),
            "video_contact_sheet": bool(contact_sheets),
            "video_contact_sheets_used": len(contact_sheets),
            "thumbnail_name": output_path.name,
        }

    def _video_contact_sheet(self, video: Path, output_path: Path) -> None:
        duration_text = self._run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video),
            ]
        )
        try:
            duration = float(duration_text.strip())
        except (TypeError, ValueError):
            duration = 0.0
        if not math.isfinite(duration) or duration <= 0:
            duration = 1.0
        filter_value = (
            f"fps=16/{duration:.6f},"
            "scale=396:396:force_original_aspect_ratio=decrease,"
            "pad=396:396:(ow-iw)/2:(oh-ih)/2:color=black,"
            "tile=4x4:padding=4:margin=4:color=black"
        )
        self._run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(video),
                "-vf",
                filter_value,
                "-frames:v",
                "1",
                str(output_path),
            ]
        )

    def _compose(self, inputs: list[Path], output_path: Path) -> None:
        row_counts = {
            1: [1],
            2: [2],
            3: [3],
            4: [2, 2],
            5: [3, 2],
            6: [3, 3],
            7: [4, 3],
            8: [4, 4],
        }[len(inputs)]
        canvas_width = 1600
        row_height = 1600 if len(inputs) == 1 else 800
        filters = []
        layouts = []
        input_index = 0
        for row_index, column_count in enumerate(row_counts):
            base_width, remainder = divmod(canvas_width, column_count)
            x = 0
            for column_index in range(column_count):
                width = base_width + (1 if column_index >= column_count - remainder else 0)
                index = input_index
                filters.append(
                    f"[{index}:v]scale={width}:{row_height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{row_height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[v{index}]"
                )
                layouts.append(f"{x}_{row_index * row_height}")
                x += width
                input_index += 1
        streams = "".join(f"[v{index}]" for index in range(len(inputs)))
        filters.append(
            f"{streams}xstack=inputs={len(inputs)}:layout={'|'.join(layouts)}:fill=black[vout]"
        )
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        for path in inputs:
            command.extend(["-i", str(path)])
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-frames:v",
                "1",
                "-pix_fmt",
                "rgb24",
                str(output_path),
            ]
        )
        self._run(command)

    def _run(self, command: list[str]) -> str:
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name != "nt",
            creationflags=creationflags,
        )
        with self._process_lock:
            self._current_process = process
        try:
            stdout, stderr = process.communicate()
        finally:
            with self._process_lock:
                if self._current_process is process:
                    self._current_process = None
        if process.returncode:
            detail = (stderr or stdout or "ffmpeg gagal").strip()
            if self.log_callback:
                self.log_callback(detail[-2_000:])
            raise QuickModeError(f"Pemrosesan thumbnail gagal: {detail[-500:]}")
        return stdout or ""


def cleanup_quick_stage(stage_root: Path) -> None:
    shutil.rmtree(stage_root, ignore_errors=False)
