"""Helpers for the media thumbnail stage of Quick Mode exports."""

from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from tme3bot.export_catalog import inspect_export_json
from tme3bot.tdl import CommandCallback, ProcessStalledError, TDLClient
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
QUICK_MANIFEST_VERSION = 2
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
    values = _sanitize_manifest(values)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(values, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _sanitize_manifest(value):
    sensitive = {"password", "compress_password", "token", "credential", "secret"}
    if isinstance(value, dict):
        return {
            str(key): _sanitize_manifest(item)
            for key, item in value.items()
            if str(key).casefold() not in sensitive
        }
    if isinstance(value, list):
        return [_sanitize_manifest(item) for item in value]
    return value


def _safe_stage_file(path: Path, root: Path) -> bool:
    """Return whether *path* is a direct, non-symlink child of *root*."""
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return path.resolve().parent == root.resolve()
    except OSError:
        return False


def _archive_files(stage_root: Path, folder_name: str) -> list[Path]:
    prefix = f"{folder_name}.7z"
    return sorted(
        path
        for path in Path(stage_root).iterdir()
        if _safe_stage_file(path, Path(stage_root))
        and (path.name == prefix or path.name.startswith(prefix + "."))
    )


def _json_media_stats(path: Path) -> dict[str, object]:
    """Read only safe, derived counts from a raw export JSON."""
    try:
        return dict(inspect_export_json(path))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def scan_quick_stages(workspace: Path, *, worker: str | None = None) -> list[dict[str, object]]:
    """Scan Quick Mode staging without returning JSON, credentials, or TDL data."""
    workspace = Path(workspace).resolve()
    legacy_root = workspace / ".tme3bot-quick"
    if legacy_root.is_dir():
        for candidate in sorted(legacy_root.iterdir()):
            if candidate.is_dir() and not candidate.is_symlink():
                try:
                    migrate_legacy_quick_stage(workspace, candidate.name)
                except (OSError, QuickModeError):
                    # One damaged legacy folder must not hide all other stages.
                    continue
        try:
            legacy_root.rmdir()
        except OSError:
            pass

    root = workspace / "quickmode"
    if not root.is_dir():
        return []
    results: list[dict[str, object]] = []
    for stage in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not stage.is_dir() or stage.is_symlink() or not _STAGE_ID_RE.fullmatch(stage.name):
            continue
        manifest = read_quick_manifest(stage)
        manifest = manifest if isinstance(manifest, dict) else {}
        json_candidates = sorted(
            path for path in stage.glob("*.json")
            if path.name != "quickmode.json" and _safe_stage_file(path, stage)
        )
        json_path = None
        requested_json = Path(str(manifest.get("export_json_name") or "")).name
        if requested_json and requested_json != "." and _safe_stage_file(stage / requested_json, stage):
            json_path = stage / requested_json
        elif len(json_candidates) == 1:
            json_path = json_candidates[0]
        stats = _json_media_stats(json_path) if json_path else {}
        folder_name = Path(str(manifest.get("folder_name") or "")).name
        if not folder_name or folder_name == ".":
            child_dirs = [
                path for path in stage.iterdir()
                if path.is_dir() and path.name != ".tdl" and not path.is_symlink()
            ]
            archive_candidates = sorted(stage.glob("*.7z*"))
            folder_name = (
                quick_folder_name(json_path)
                if json_path
                else archive_candidates[0].name.split(".7z", 1)[0]
                if archive_candidates
                else child_dirs[0].name if len(child_dirs) == 1 else stage.name
            )
        media_root = stage / folder_name
        photos, videos = visual_media(media_root) if media_root.is_dir() else ([], [])
        actual_media_count = len(photos) + len(videos)
        try:
            expected_media_count = int(
                stats.get("media_count") or manifest.get("expected_media_count") or 0
            )
        except (TypeError, ValueError):
            expected_media_count = 0
        thumbnail_present = (stage / f"{folder_name}.png").is_file()
        archives = _archive_files(stage, folder_name)
        has_media = actual_media_count > 0
        if archives and thumbnail_present:
            phase = "uploading"
            resume_phase = "uploading"
        elif json_path and expected_media_count and actual_media_count >= expected_media_count and not thumbnail_present:
            phase = "thumbnailing"
            resume_phase = "thumbnailing"
        elif json_path and has_media and expected_media_count and actual_media_count >= expected_media_count and thumbnail_present and not archives:
            phase = "compressing"
            resume_phase = "compressing"
        elif json_path:
            phase = "downloading"
            resume_phase = "downloading"
        else:
            phase = str(manifest.get("phase") or "exporting").strip().lower()
            if phase not in QUICK_PHASES:
                phase = "exporting"
            resume_phase = phase
        tdl_root = stage / ".tdl"
        try:
            manifest_version = int(manifest.get("version") or 1)
        except (TypeError, ValueError):
            manifest_version = 1
        item: dict[str, object] = {
            "stage_job_id": stage.name,
            "quick_operation_id": str(manifest.get("quick_operation_id") or stage.name),
            "profile": str(manifest.get("profile") or ""),
            "worker": str(manifest.get("worker") or worker or ""),
            "folder_name": folder_name,
            "phase": phase,
            "resume_phase": resume_phase,
            "json_present": bool(json_path),
            "expected_media_count": expected_media_count,
            "actual_media_count": actual_media_count,
            "photo_count": len(photos),
            "video_count": len(videos),
            "archive_parts": len(archives),
            "archive_names": [path.name for path in archives],
            "thumbnail_present": thumbnail_present,
            "tdl_export_present": (tdl_root / "export-home" / ".tdl").is_dir(),
            "tdl_download_present": (tdl_root / "download-home" / ".tdl").is_dir(),
            "storage_folder": str(manifest.get("storage_folder") or f"ModeCepat/{quick_year()}"),
            "last_progress_at": manifest.get("last_progress_at"),
            "last_error": str(manifest.get("last_error") or "")[:1000],
            "staging_path": str(stage),
            "manifest_version": manifest_version,
            "rclone_destination": str(manifest.get("rclone_destination") or ""),
            "rclone_archive_names": [
                str(name)
                for name in (
                    manifest.get("rclone_result", {}).get("files", [])
                    if isinstance(manifest.get("rclone_result"), dict)
                    else manifest.get("rclone_archive_names", [])
                )
                if str(name)
            ],
            "telegram_uploaded_count": len(
                manifest.get("upload_result", {}).get("uploaded_items", [])
                if isinstance(manifest.get("upload_result"), dict)
                and isinstance(manifest.get("upload_result", {}).get("uploaded_items"), list)
                else []
            ),
            "cleanup_verification": (
                dict(manifest.get("cleanup_verification"))
                if isinstance(manifest.get("cleanup_verification"), dict)
                else None
            ),
        }
        # Only derived metadata is exposed.  In particular, do not return the
        # manifest itself, raw chat JSON, password settings, or session files.
        results.append(item)
    return results


def _clone_tree(source: Path, destination: Path) -> None:
    source = Path(source)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if source != Path(".") and source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)


def _chown_tree(path: Path, username: str | None) -> None:
    if not username or username == "root" or os.name == "nt":
        return
    try:
        import pwd

        info = pwd.getpwnam(username)
    except (ImportError, KeyError):
        return
    for current, directories, files in os.walk(path):
        for name in [current, *directories, *files]:
            try:
                os.chown(name, info.pw_uid, info.pw_gid)
            except OSError:
                continue


def ensure_quick_tdl_client(
    stage_root: Path,
    *,
    mode: str,
    source_storage: Path | None,
    source_home: Path | None,
    namespace: str,
    run_as_user: str | None,
    stall_timeout_seconds: int = 0,
    progress_callback=None,
    output_callback=None,
) -> TDLClient:
    """Create/reuse the isolated export or download TDL session for a stage."""
    if mode not in {"export", "download"}:
        raise QuickModeError("Mode TDL Quick Mode tidak valid.")
    mode_root = Path(stage_root) / ".tdl" / f"{mode}-home"
    storage_root = mode_root / ".tdl"
    if not storage_root.exists() or not any(storage_root.iterdir()):
        _clone_tree(Path(source_storage) if source_storage else Path(), storage_root)
    mode_root.mkdir(parents=True, exist_ok=True)
    _chown_tree(mode_root, run_as_user)
    return TDLClient(
        storage_root=storage_root,
        namespace=namespace,
        run_as_user=run_as_user,
        home=mode_root,
        log_prefix=f"tdl-quick-{mode}:{Path(stage_root).name}",
        stall_timeout_seconds=stall_timeout_seconds,
        progress_callback=progress_callback,
        output_callback=output_callback,
    )


def ensure_quick_stage_writable(stage_root: Path, username: str | None) -> None:
    Path(stage_root).mkdir(parents=True, exist_ok=True)
    _chown_tree(Path(stage_root), username)


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
            if (
                "thumb" not in stem
                and not stem.startswith(".video-contact-sheet-")
                and not stem.startswith(".video-frame-")
            ):
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
        stall_timeout_seconds: int = 0,
        command_callback: CommandCallback | None = None,
    ) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.log_callback = log_callback
        self.stall_timeout_seconds = max(0, int(stall_timeout_seconds))
        self.command_callback = command_callback
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
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._terminate_process(process)
        return True

    def build(self, media_root: Path, output_path: Path) -> dict[str, object]:
        media_root = Path(media_root).resolve()
        output_path = Path(output_path).resolve()
        frame_files: list[Path] = []
        skipped_media: list[dict[str, str]] = []
        output_path.parent.mkdir(parents=True, exist_ok=True)

        def skip_media(path: Path, error: Exception) -> None:
            detail = str(error).strip() or error.__class__.__name__
            detail = detail[-500:]
            skipped_media.append({"name": path.name, "error": detail})
            if self.log_callback:
                self.log_callback(
                    f"Thumbnail melewati media rusak {path.name}: {detail}"
                )

        try:
            photos, videos = visual_media(media_root)
            photos_to_use = min(len(photos), 4 if videos else 8)
            selected = list(photos[:photos_to_use])
            video_quota = 8 - len(selected)

            if videos and video_quota > 0:
                valid_videos: list[tuple[Path, float]] = []
                next_video_index = 0
                target_video_count = min(len(videos), video_quota)

                def probe_next_video() -> bool:
                    nonlocal next_video_index
                    while next_video_index < len(videos):
                        video = videos[next_video_index]
                        next_video_index += 1
                        try:
                            valid_videos.append((video, self._video_duration(video)))
                            return True
                        except ProcessStalledError:
                            raise
                        except Exception as exc:
                            skip_media(video, exc)
                    return False

                while len(valid_videos) < target_video_count and probe_next_video():
                    pass

                remaining = video_quota
                frame_idx = 0
                candidate_index = 0
                while remaining > 0:
                    if candidate_index >= len(valid_videos):
                        if not probe_next_video():
                            break
                        continue
                    video, duration = valid_videos[candidate_index]
                    candidate_index += 1
                    candidates_left = (
                        len(valid_videos) - candidate_index
                        + len(videos) - next_video_index
                    )
                    count = min(
                        remaining,
                        max(1, math.ceil(remaining / max(1, candidates_left + 1))),
                    )
                    timestamps = self._sample_timestamps(duration, count)
                    extracted = 0
                    for ts in timestamps:
                        frame_idx += 1
                        frame_path = output_path.parent / f".video-frame-{frame_idx}.png"
                        frame_files.append(frame_path)
                        frame_path.unlink(missing_ok=True)
                        try:
                            self._extract_video_frame(video, ts, frame_path)
                        except ProcessStalledError:
                            raise
                        except Exception as exc:
                            frame_path.unlink(missing_ok=True)
                            skip_media(video, exc)
                            # One failed frame is enough to discard this
                            # video; use the next candidate instead of
                            # repeatedly invoking ffmpeg on a broken input.
                            break
                        selected.append(frame_path)
                        extracted += 1
                    remaining -= extracted

            if not selected:
                detail = ""
                if skipped_media:
                    detail = f" Detail: {skipped_media[0]['name']} dilewati."
                raise QuickModeError(
                    "Quick Mode tidak menemukan foto atau video yang dapat dibuat thumbnail."
                    + detail
                )
            self._compose(selected, output_path)
        finally:
            for frame_path in frame_files:
                frame_path.unlink(missing_ok=True)
        return {
            "photos_used": len(selected) - len(frame_files),
            "video_contact_sheet": bool(frame_files),
            "video_contact_sheets_used": len(frame_files),
            "video_frames_used": len(frame_files),
            "skipped_media": skipped_media,
            "thumbnail_name": output_path.name,
        }

    def _video_duration(self, video: Path) -> float:
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
        return duration

    @staticmethod
    def _sample_timestamps(duration: float, count: int) -> list[float]:
        if count <= 0:
            return []
        if duration <= 1.0:
            return [round(duration / 2.0, 3)] * count
        margin = min(1.0, duration * 0.05)
        start = margin
        end = max(start + 0.1, duration - margin)
        span = end - start
        step = span / count
        timestamps: list[float] = []
        for i in range(count):
            seg_start = start + i * step
            seg_end = start + (i + 1) * step
            timestamps.append(round(random.uniform(seg_start, seg_end), 3))
        return sorted(timestamps)

    def _extract_video_frame(self, video: Path, timestamp: float, output_path: Path) -> None:
        self._run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(video),
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
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=os.name != "nt",
                creationflags=creationflags,
            )
        except OSError as exc:
            if self.command_callback is not None:
                try:
                    self.command_callback(command, -1, str(exc), 0.0, "quick-thumbnail")
                except Exception:
                    pass
            raise
        with self._process_lock:
            self._current_process = process
        stalled = threading.Event()
        watchdog_stop = threading.Event()
        started_at = time.monotonic()

        def watchdog() -> None:
            if self.stall_timeout_seconds <= 0:
                return
            while not watchdog_stop.wait(1.0):
                if time.monotonic() - started_at <= self.stall_timeout_seconds:
                    continue
                stalled.set()
                self._terminate_process(process)
                return

        watchdog_thread = threading.Thread(
            target=watchdog,
            daemon=True,
            name="quick-thumbnail-watchdog",
        )
        watchdog_thread.start()
        stdout = ""
        stderr = ""
        try:
            stdout, stderr = process.communicate()
        finally:
            watchdog_stop.set()
            watchdog_thread.join(timeout=2)
            with self._process_lock:
                if self._current_process is process:
                    self._current_process = None
            if self.command_callback is not None:
                try:
                    self.command_callback(
                        command,
                        int(process.returncode if process.returncode is not None else -1),
                        f"{stdout}\n{stderr}",
                        max(0.0, time.monotonic() - started_at),
                        "quick-thumbnail",
                    )
                except Exception:
                    pass
        if stalled.is_set():
            raise ProcessStalledError(
                f"thumbnail process stalled for {self.stall_timeout_seconds}s",
                self.stall_timeout_seconds,
            )
        if process.returncode:
            detail = (stderr or stdout or "ffmpeg gagal").strip()
            if self.log_callback:
                self.log_callback(detail[-2_000:])
            raise QuickModeError(f"Pemrosesan thumbnail gagal: {detail[-500:]}")
        return stdout or ""

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name != "nt":
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except ProcessLookupError:
                return
        else:  # pragma: no cover - production workers run on Linux
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    return
            else:  # pragma: no cover - production workers run on Linux
                process.kill()


def cleanup_quick_stage(stage_root: Path) -> None:
    shutil.rmtree(stage_root, ignore_errors=False)
