from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


VIDEO_CONVERT = "video_convert"
IMAGE_COMPRESS = "image_compress"
MEDIA_PIPELINE = "media_pipeline"
MEDIA_UTILITIES = frozenset({VIDEO_CONVERT, IMAGE_COMPRESS, MEDIA_PIPELINE})
VIDEO_UTILITIES = frozenset({VIDEO_CONVERT, MEDIA_PIPELINE})
IMAGE_UTILITIES = frozenset({IMAGE_COMPRESS, MEDIA_PIPELINE})


@dataclass(frozen=True)
class VideoOptions:
    codec: str
    resolution: str
    crf: int
    speed: str

    def to_payload(self) -> dict[str, object]:
        return {
            "codec": self.codec,
            "resolution": self.resolution,
            "crf": self.crf,
            "speed": self.speed,
        }

VIDEO_PRESETS = (
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
)
VIDEO_RESOLUTIONS = frozenset({"720p", "1080p", "original"})
VIDEO_CODEC_DEFAULTS: dict[str, VideoOptions] = {
    "h265": VideoOptions("h265", "720p", 30, "veryfast"),
    "h264": VideoOptions("h264", "1080p", 18, "veryfast"),
}
VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".wmv", ".mkv", ".ts", ".m4v"})
MAX_IMAGE_WIDTH = 1200
IMAGE_QUALITY = "80%"
IMAGE_RECODE_MARKER = "_recode"
MIN_ESTIMATED_VIDEO_SAVINGS_PERCENT = 40.0

FORMAT_ROW_RE = re.compile(r"^\s*([A-Z0-9]+)\*?\s+([A-Z0-9]+)\s+([r-][w-][+-])(?:\s|$)")
NON_RASTER_CODERS = {
    "AI", "CGM", "DOT", "DXF", "EPDF", "EPS", "EPS2", "EPS3", "EPT",
    "FIG", "HPGL", "HTML", "MVG", "MSVG", "PCL", "PDF", "PLT", "POV",
    "PS", "PS2", "PS3", "SVG", "SVGZ", "VIDEO", "WMF", "WPG", "XPS",
}
PSEUDO_FORMATS = {
    "CANVAS", "CAPTION", "CLIPBOARD", "FD", "FILE", "GRADIENT", "LABEL",
    "MPR", "NULL", "PANGO", "PLASMA", "SCAN", "STREAM", "TILE", "XC",
}

CommandRunner = Callable[..., dict[str, object] | None]
ProgressCallback = Callable[[dict[str, object]], None]
CancelCheck = Callable[[], None]


def _is_utility_control_error(error: Exception) -> bool:
    from tme3bot.utility import ProcessStalledError, UtilityCancelledError, UtilityRuntimeError

    return isinstance(error, (ProcessStalledError, UtilityCancelledError, UtilityRuntimeError))


def default_video_options(codec: str = "h265") -> VideoOptions:
    selected = str(codec or "h265").strip().lower()
    selected = {"x265": "h265", "x264": "h264"}.get(selected, selected)
    try:
        defaults = VIDEO_CODEC_DEFAULTS[selected]
    except KeyError as exc:
        raise ValueError("Codec video harus H.265 atau H.264.") from exc
    return defaults


def normalize_video_options(value: object | None) -> VideoOptions:
    if isinstance(value, VideoOptions):
        value = value.to_payload()
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("Pengaturan konversi video tidak valid.")
    unknown = set(value) - {"codec", "resolution", "crf", "speed", "preset"}
    if unknown:
        raise ValueError("Pengaturan konversi video memuat opsi yang tidak dikenal.")
    selected = str(value.get("codec") or "h265").strip().lower()
    selected = {"x265": "h265", "x264": "h264"}.get(selected, selected)
    options = default_video_options(selected)
    resolution = value.get("resolution") or options.resolution
    if not isinstance(resolution, str) or resolution not in VIDEO_RESOLUTIONS:
        raise ValueError("Resolusi video harus 720p, 1080p, atau original.")
    crf = value.get("crf")
    if crf is None:
        crf = options.crf
    if type(crf) is not int or not 0 <= crf <= 51:
        raise ValueError("Kualitas video harus berada pada rentang CRF 0 sampai 51.")
    speed = value.get("speed") or value.get("preset") or options.speed
    if not isinstance(speed, str) or speed not in VIDEO_PRESETS:
        raise ValueError("Kecepatan encoder video tidak valid.")
    return VideoOptions(selected, resolution, crf, speed)


class UtilityMediaProcessor:
    """Run media jobs through a UtilityRunner-owned process and progress seam."""

    def __init__(
        self,
        workspace: Path,
        command_runner: CommandRunner,
        progress_callback: ProgressCallback | None,
        cancel_check: CancelCheck,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.command_runner = command_runner
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self._overall_total = 0
        self._overall_done = 0

    def run(
        self,
        utility: str,
        folders: list[Path],
        video_options: object | None = None,
    ) -> dict[str, object]:
        self.cancel_check()
        options = normalize_video_options(video_options) if utility in VIDEO_UTILITIES else None
        image_extensions = self._image_extensions() if utility in IMAGE_UTILITIES else set()
        wanted_extensions = set()
        if utility in VIDEO_UTILITIES:
            wanted_extensions.update(VIDEO_EXTENSIONS)
        if utility in IMAGE_UTILITIES:
            wanted_extensions.update(image_extensions)
        media_files = self._find_files(folders, wanted_extensions)
        video_files = [path for path in media_files if path.suffix.casefold() in VIDEO_EXTENSIONS]
        image_files = [path for path in media_files if path.suffix.casefold() in image_extensions]
        video_files.sort(key=self._workspace_path_sort_key)
        image_files.sort(key=self._workspace_path_sort_key)
        self._overall_total = len(video_files) + len(image_files)
        self._progress({
            "phase": "media_scan_completed",
            "files_discovered": self._overall_total,
            "media_totals": {"video": len(video_files), "image": len(image_files)},
            "overall": {
                "current": 0,
                "total": self._overall_total,
                "percent": 0 if self._overall_total else 100,
                "unit": "files",
                "files_current": 0,
                "files_total": self._overall_total,
            },
        })

        succeeded: list[str] = []
        failed: dict[str, str] = {}
        details: list[dict[str, object]] = []
        archives: list[dict[str, object]] = []
        if options is not None:
            for index, source in enumerate(video_files, start=1):
                self.cancel_check()
                try:
                    detail = self._convert_video(source, index, options)
                except Exception as exc:
                    if _is_utility_control_error(exc):
                        raise
                    failed[str(source)] = str(exc)[:500]
                    detail = {
                        "file": str(source),
                        "media_type": "video",
                        "status": "failed",
                        "error": failed[str(source)],
                    }
                    self._item_progress("item_failed", source, index, detail.get("error"))
                details.append(detail)
                if detail.get("status") == "succeeded":
                    succeeded.append(str(source))

        if utility in IMAGE_UTILITIES:
            image_succeeded, image_failed, image_details, image_archives = self._compress_images(
                image_files,
                start_index=len(video_files),
            )
            succeeded.extend(image_succeeded)
            failed.update(image_failed)
            details.extend(image_details)
            archives.extend(image_archives)

        total = self._overall_total
        succeeded_count = len(succeeded)
        failed_count = len(failed)
        skipped_count = sum(item.get("status") == "skipped" for item in details)
        outcome = "partial_failure" if failed_count and succeeded_count else "failed" if failed_count else "succeeded"
        return {
            "utility": utility,
            "succeeded": succeeded,
            "failed": failed,
            "details": details,
            "summary": {
                "files_total": total,
                "files_succeeded": succeeded_count,
                "files_failed": failed_count,
                "files_skipped": skipped_count,
                "media": self._media_summary(video_files, image_files, details),
                "archives_created": sum(item.get("status") == "succeeded" for item in archives),
                "archives_failed": sum(item.get("status") == "failed" for item in archives),
                "archives": archives,
            },
            "outcome": outcome,
        }

    def _workspace_path_sort_key(self, path: Path) -> tuple[str, str]:
        relative = path.relative_to(self.workspace).as_posix()
        return relative.casefold(), relative

    @staticmethod
    def _media_summary(
        video_files: list[Path],
        image_files: list[Path],
        details: list[dict[str, object]],
    ) -> dict[str, object]:
        by_type: dict[str, list[dict[str, object]]] = {
            "video": [item for item in details if item.get("media_type") == "video"],
            "image": [item for item in details if item.get("media_type") == "image"],
        }
        result: dict[str, object] = {"scan_complete": True}
        for media_type, files in (("video", video_files), ("image", image_files)):
            outcomes = by_type[media_type]
            result[media_type] = {
                "total": len(files),
                "running": 0,
                "succeeded": sum(item.get("status") == "succeeded" for item in outcomes),
                "failed": sum(item.get("status") == "failed" for item in outcomes),
                "skipped": sum(item.get("status") == "skipped" for item in outcomes),
            }
        result["skipped"] = {
            "estimated_savings_below_threshold": sum(
                item.get("reason_code") == "VIDEO_ESTIMATED_SAVINGS_BELOW_THRESHOLD"
                for item in details
            ),
            "recode_output_exists": sum(
                item.get("reason_code") in {
                    "VIDEO_RECODE_OUTPUT_EXISTS",
                    "IMAGE_RECODE_OUTPUT_EXISTS",
                }
                for item in details
            ),
        }
        return result

    @staticmethod
    def _media_type(source: Path) -> str:
        return "video" if source.suffix.casefold() in VIDEO_EXTENSIONS else "image"

    @staticmethod
    def _image_recode_path(source: Path) -> Path:
        return source.with_name(f"{source.stem}{IMAGE_RECODE_MARKER}{source.suffix}")

    def _skip_existing_recode_output(
        self,
        source: Path,
        index: int,
        output: Path,
        media_type: str,
        reason_code: str,
    ) -> dict[str, object]:
        reason = f"Hasil _recode sudah ada; sumber dipertahankan: {output.name}"
        detail = {
            "file": str(source),
            "media_type": media_type,
            "status": "skipped",
            "output": str(output),
            "reason_code": reason_code,
            "reason": reason,
        }
        self._item_progress(
            "item_skipped",
            source,
            index,
            percent=100,
            reason=reason,
            reason_code=reason_code,
        )
        return detail

    def _find_files(self, folders: list[Path], extensions: set[str] | frozenset[str]) -> list[Path]:
        selected: list[Path] = []
        seen: set[Path] = set()
        last_progress = time.monotonic()
        for folder in folders:
            self.cancel_check()
            for root, dirs, names in os.walk(folder, followlinks=False):
                current = Path(root)
                dirs[:] = sorted(name for name in dirs if not (current / name).is_symlink())
                for name in sorted(names):
                    path = current / name
                    if (
                        path.is_symlink()
                        or path.suffix.casefold() not in extensions
                        or IMAGE_RECODE_MARKER in path.stem.casefold()
                    ):
                        continue
                    if path.stem.casefold().endswith(IMAGE_RECODE_MARKER):
                        continue
                    try:
                        resolved = path.resolve(strict=True)
                        resolved.relative_to(self.workspace)
                        if not resolved.is_file() or resolved in seen:
                            continue
                    except (OSError, RuntimeError, ValueError):
                        continue
                    seen.add(resolved)
                    selected.append(resolved)
                    now = time.monotonic()
                    if len(selected) % 100 == 0 or now - last_progress >= 1.0:
                        self._progress({
                            "phase": "media_scanning",
                            "name": str(resolved),
                            "files_discovered": len(selected),
                            "indeterminate": True,
                        })
                        last_progress = now
        return selected

    def _image_extensions(self) -> set[str]:
        result = self.command_runner(
            ["mogrify", "-list", "format"],
            self.workspace,
            "utility-image-formats",
            capture_output=True,
            capture_log=True,
            capture_job_log=False,
        )
        if not isinstance(result, dict):
            raise RuntimeError("ImageMagick tidak dapat membaca format gambar.")
        extensions: set[str] = set()
        for line in str(result.get("stdout") or "").splitlines():
            match = FORMAT_ROW_RE.match(line)
            if not match:
                continue
            alias, coder, mode = match.groups()
            if mode[0] != "r" or mode[1] != "w":
                continue
            if (coder in NON_RASTER_CODERS and alias != "APNG") or alias in PSEUDO_FORMATS:
                continue
            extensions.add(f".{alias.lower()}")
        return extensions

    def _convert_video(
        self,
        source: Path,
        index: int,
        options: VideoOptions,
    ) -> dict[str, object]:
        final_path = source.with_name(f"{source.stem}{IMAGE_RECODE_MARKER}.mp4")
        source_identity = self._identity(source)
        if final_path.is_file():
            return self._skip_existing_recode_output(
                source,
                index,
                final_path,
                "video",
                "VIDEO_RECODE_OUTPUT_EXISTS",
            )
        codec = options.codec
        resolution = options.resolution
        self._item_progress(
            "media_preflight_started",
            source,
            index,
            stage="probe",
            minimum_estimated_savings_percent=MIN_ESTIMATED_VIDEO_SAVINGS_PERCENT,
        )
        duration = self._video_duration(source)
        estimated_savings_percent = self._estimate_video_savings(
            source,
            duration,
            source_identity[2],
            index,
            options,
        )
        if self._identity(source) != source_identity:
            raise RuntimeError("Sumber berubah saat estimasi; sumber dipertahankan.")
        if estimated_savings_percent <= MIN_ESTIMATED_VIDEO_SAVINGS_PERCENT:
            reason = (
                f"Perkiraan penghematan {estimated_savings_percent:.1f}% tidak melewati "
                f"ambang {MIN_ESTIMATED_VIDEO_SAVINGS_PERCENT:.0f}%."
            )
            detail = {
                "file": str(source),
                "media_type": "video",
                "status": "skipped",
                "reason_code": "VIDEO_ESTIMATED_SAVINGS_BELOW_THRESHOLD",
                "reason": reason,
                "estimated_savings_percent": estimated_savings_percent,
                "minimum_estimated_savings_percent": MIN_ESTIMATED_VIDEO_SAVINGS_PERCENT,
            }
            self._item_progress(
                "item_skipped",
                source,
                index,
                percent=100,
                reason=reason,
                reason_code=detail["reason_code"],
                estimated_savings_percent=estimated_savings_percent,
                minimum_estimated_savings_percent=MIN_ESTIMATED_VIDEO_SAVINGS_PERCENT,
            )
            return detail

        stage_path = self._temporary_path(source.parent, ".tme3-media-video-", ".mp4")
        try:
            command = [
                "ffmpeg", "-hide_banner", "-nostdin", "-y",
                "-progress", "pipe:1", "-nostats", "-fflags", "+genpts",
                "-threads", "1", "-i", str(source),
            ]
            command.extend(self._video_encoder_args(options))
            command.append(str(stage_path))

            self._item_progress(
                "item_started",
                source,
                index,
                stage="encode",
                estimated_savings_percent=estimated_savings_percent,
            )
            progress_parser = self._ffmpeg_progress(source, index, duration)
            self.command_runner(
                command,
                source.parent,
                "utility-video-encode",
                line_progress=progress_parser,
                cpu_quota_percent=80,
                cpu_threads=1,
                lower_priority=True,
            )
            self.cancel_check()
            if not stage_path.is_file() or stage_path.stat().st_size == 0:
                raise RuntimeError("FFmpeg tidak menghasilkan video.")
            self._item_progress("item_verifying", source, index, stage="verify")
            self._verify_video(stage_path, source.parent)
            self.cancel_check()
            if self._identity(source) != source_identity:
                raise RuntimeError("Sumber berubah selama konversi; sumber dipertahankan.")
            try:
                os.link(stage_path, final_path)
            except FileExistsError as exc:
                if final_path.is_file():
                    return self._skip_existing_recode_output(
                        source,
                        index,
                        final_path,
                        "video",
                        "VIDEO_RECODE_OUTPUT_EXISTS",
                    )
                raise FileExistsError(f"Hasil muncul saat proses; sumber dipertahankan: {final_path.name}") from exc
            final_identity = self._identity(final_path)
            stage_path.unlink()
            if self._identity(source) != source_identity:
                self._unlink_if_unchanged(final_path, final_identity)
                raise RuntimeError("Sumber berubah selama konversi; sumber dipertahankan.")
            try:
                source.unlink()
            except OSError:
                self._unlink_if_unchanged(final_path, final_identity)
                raise
            detail = {
                "file": str(source),
                "media_type": "video",
                "status": "succeeded",
                "output": str(final_path),
                "codec": codec,
                "resolution": resolution,
                "crf": options.crf,
                "speed": options.speed,
                "estimated_savings_percent": estimated_savings_percent,
            }
            self._item_progress("item_completed", source, index, percent=100, stage="complete")
            return detail
        finally:
            try:
                stage_path.unlink()
            except FileNotFoundError:
                pass

    def _estimate_video_savings(
        self,
        source: Path,
        duration: float,
        source_size: int,
        index: int,
        options: VideoOptions,
    ) -> float:
        if source_size <= 0:
            raise RuntimeError("Ukuran sumber video tidak valid untuk estimasi.")

        windows = self._video_sample_windows(duration)
        sampled_bytes = 0
        sampled_seconds = 0.0
        with tempfile.TemporaryDirectory(prefix="tme3-media-video-sample-") as temporary:
            sample_root = Path(temporary)
            for sample_index, (start, sample_duration) in enumerate(windows, start=1):
                self.cancel_check()
                sample_path = sample_root / f"sample-{sample_index}.mp4"
                command = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-fflags", "+genpts",
                    "-threads", "1", "-ss", self._format_seconds(start),
                    "-i", str(source), "-t", self._format_seconds(sample_duration),
                ]
                command.extend(self._video_encoder_args(options))
                command.append(str(sample_path))
                self.command_runner(
                    command,
                    source.parent,
                    "utility-video-preflight",
                    cpu_quota_percent=80,
                    cpu_threads=1,
                    lower_priority=True,
                )
                self.cancel_check()
                if not sample_path.is_file() or sample_path.stat().st_size <= 0:
                    raise RuntimeError("FFmpeg tidak menghasilkan sampel estimasi video.")
                sampled_bytes += sample_path.stat().st_size
                sampled_seconds += sample_duration

        estimated_output_size = sampled_bytes / sampled_seconds * duration
        estimated_savings_percent = (source_size - estimated_output_size) * 100 / source_size
        return round(estimated_savings_percent, 1)

    @staticmethod
    def _video_sample_windows(duration: float) -> list[tuple[float, float]]:
        if duration >= 36.0:
            sample_duration = min(5.0, duration / 12.0)
            centers = (0.1, 0.5, 0.9)
        else:
            sample_duration = min(5.0, duration / 4.0)
            centers = (0.5,)
        return [
            (
                max(0.0, min(duration - sample_duration, center * duration - sample_duration / 2)),
                sample_duration,
            )
            for center in centers
        ]

    @staticmethod
    def _format_seconds(value: float) -> str:
        return f"{value:.3f}".rstrip("0").rstrip(".") or "0"

    @staticmethod
    def _video_encoder_args(options: VideoOptions) -> list[str]:
        encoder = "libx265" if options.codec == "h265" else "libx264"
        command = ["-c:v", encoder, "-preset", options.speed]
        if options.resolution != "original":
            maximum_height = 720 if options.resolution == "720p" else 1080
            command.extend(["-vf", f"scale=-2:min({maximum_height}\\,ih)"])
        command.extend(["-crf", str(options.crf)])
        if options.codec == "h265":
            command.extend([
                "-x265-params", "pools=1:frame-threads=1:log-level=error",
                "-c:a", "aac",
            ])
        else:
            command.extend(["-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart"])
        return command

    def _video_duration(self, source: Path) -> float:
        result = self.command_runner(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(source),
            ],
            source.parent,
            "utility-video-probe",
            capture_output=True,
            capture_log=True,
            capture_job_log=False,
            lower_priority=True,
        )
        if not isinstance(result, dict):
            raise RuntimeError("ffprobe tidak menghasilkan durasi video.")
        try:
            duration = float(str(result.get("stdout") or "").strip().splitlines()[0])
        except (IndexError, ValueError) as exc:
            raise RuntimeError("Durasi video tidak dapat dibaca oleh ffprobe.") from exc
        if duration <= 0:
            raise RuntimeError("Durasi video tidak valid.")
        return duration

    def _verify_video(self, output: Path, cwd: Path) -> None:
        probe = self.command_runner(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(output),
            ],
            cwd,
            "utility-video-verify-probe",
            capture_output=True,
            capture_log=True,
            capture_job_log=False,
            lower_priority=True,
        )
        if not isinstance(probe, dict) or "video" not in str(probe.get("stdout") or "").splitlines():
            raise RuntimeError("Verifikasi gagal: stream video tidak ditemukan.")
        self.command_runner(
            [
                "ffmpeg", "-v", "error", "-xerror", "-nostdin", "-threads", "1",
                "-i", str(output), "-f", "null", "-",
            ],
            cwd,
            "utility-video-verify-decode",
            lower_priority=True,
        )

    def _ffmpeg_progress(
        self,
        source: Path,
        index: int,
        duration: float,
    ) -> Callable[[str], dict[str, object] | None]:
        state: dict[str, str] = {}
        started = time.monotonic()

        def parse(line: str) -> dict[str, object] | None:
            key, separator, value = line.partition("=")
            if not separator:
                return None
            state[key] = value
            if key != "progress":
                return None
            try:
                micros = int(state.get("out_time_us") or state.get("out_time_ms") or 0)
            except ValueError:
                micros = 0
            try:
                bytes_written = int(state.get("total_size") or 0)
            except ValueError:
                bytes_written = 0
            elapsed = max(0.0, time.monotonic() - started)
            percent = min(99.9, max(0.0, micros / 1_000_000 / duration * 100))
            speed = bytes_written / elapsed if elapsed > 0 and bytes_written > 0 else None
            eta = elapsed * (100 / percent - 1) if percent > 0 else None
            return self._progress_value(
                "item_progress",
                source,
                index,
                percent=percent,
                stage="encode",
                bytes_current=bytes_written,
                speed_bps=speed,
                eta_seconds=eta,
                elapsed_seconds=elapsed,
            )

        return parse

    def _compress_images(
        self,
        image_files: list[Path],
        *,
        start_index: int,
    ) -> tuple[list[str], dict[str, str], list[dict[str, object]], list[dict[str, object]]]:
        staged_by_folder: dict[Path, list[tuple[Path, Path, tuple[int, int, int, int]]]] = defaultdict(list)
        succeeded: list[str] = []
        failed: dict[str, str] = {}
        details: list[dict[str, object]] = []
        archives: list[dict[str, object]] = []
        index_by_source = {
            source: start_index + index
            for index, source in enumerate(image_files, start=1)
        }

        try:
            for source in image_files:
                index = index_by_source[source]
                self.cancel_check()
                temp_path: Path | None = None
                try:
                    source_identity = self._identity(source)
                    recoded_existing = self._image_recode_path(source)
                    if recoded_existing.is_file():
                        details.append(self._skip_existing_recode_output(
                            source,
                            index,
                            recoded_existing,
                            "image",
                            "IMAGE_RECODE_OUTPUT_EXISTS",
                        ))
                        continue
                    temp_path = self._temporary_path(
                        source.parent, ".tme3-media-image-", source.suffix
                    )
                    self._item_progress("item_started", source, index, stage="compress")
                    self._copy_file(source, temp_path)
                    dimensions = self._image_dimensions(source)
                    self.command_runner(
                        ["mogrify", "-resize", f"{MAX_IMAGE_WIDTH}x>", "-quality", IMAGE_QUALITY, str(temp_path)],
                        source.parent,
                        "utility-image-compress",
                    )
                    compressed_dimensions = self._image_dimensions(temp_path)
                    self._verify_image_dimensions(dimensions, compressed_dimensions)
                    if self._identity(source) != source_identity:
                        raise RuntimeError("Sumber berubah selama kompresi; sumber dipertahankan.")
                    staged_by_folder[source.parent].append((source, temp_path, source_identity))
                    temp_path = None
                except Exception as exc:
                    if _is_utility_control_error(exc):
                        raise
                    failed[str(source)] = str(exc)[:500]
                    details.append({"file": str(source), "media_type": "image", "status": "failed", "error": failed[str(source)]})
                    self._item_progress("item_failed", source, index, failed[str(source)])
                finally:
                    if temp_path is not None:
                        temp_path.unlink(missing_ok=True)

            for folder, staged in staged_by_folder.items():
                self.cancel_check()
                publishable: list[tuple[Path, Path, tuple[int, int, int, int]]] = []
                for source, temp_path, identity in staged:
                    recoded_existing = self._image_recode_path(source)
                    if recoded_existing.is_file():
                        details.append(self._skip_existing_recode_output(
                            source,
                            index_by_source[source],
                            recoded_existing,
                            "image",
                            "IMAGE_RECODE_OUTPUT_EXISTS",
                        ))
                    else:
                        publishable.append((source, temp_path, identity))

                if not publishable:
                    continue
                archive = self._archive_images(folder, publishable)
                archives.append(archive)
                if archive["status"] != "succeeded":
                    message = str(archive.get("error") or "Arsip gambar gagal diverifikasi.")
                    for source, _, _ in publishable:
                        recoded_existing = self._image_recode_path(source)
                        if recoded_existing.is_file():
                            details.append(self._skip_existing_recode_output(
                                source,
                                index_by_source[source],
                                recoded_existing,
                                "image",
                                "IMAGE_RECODE_OUTPUT_EXISTS",
                            ))
                            continue
                        failed[str(source)] = message
                        details.append({"file": str(source), "media_type": "image", "status": "failed", "error": message})
                        self._item_progress("item_failed", source, index_by_source[source], message)
                    continue

                for source, _, identity in publishable:
                    self.cancel_check()
                    index = index_by_source[source]
                    recoded_existing = self._image_recode_path(source)
                    if recoded_existing.is_file():
                        details.append(self._skip_existing_recode_output(
                            source,
                            index,
                            recoded_existing,
                            "image",
                            "IMAGE_RECODE_OUTPUT_EXISTS",
                        ))
                        continue
                    if self._identity(source) != identity:
                        error = "Sumber berubah sebelum dihapus; hasil ZIP tersimpan dan sumber dipertahankan."
                        failed[str(source)] = error
                        details.append({"file": str(source), "media_type": "image", "status": "failed", "output": archive["path"], "error": error})
                        self._item_progress("item_failed", source, index, error)
                    else:
                        try:
                            source.unlink()
                        except OSError as exc:
                            error = f"Hasil ZIP tersimpan, tetapi sumber gagal dihapus: {exc}"
                            failed[str(source)] = error
                            details.append({"file": str(source), "media_type": "image", "status": "failed", "output": archive["path"], "error": error})
                            self._item_progress("item_failed", source, index, error)
                        else:
                            succeeded.append(str(source))
                            details.append({
                                "file": str(source),
                                "media_type": "image",
                                "status": "succeeded",
                                "output": archive["path"],
                            })
                            self._item_progress("item_completed", source, index, percent=100, stage="archive")
        finally:
            for staged in staged_by_folder.values():
                for _, temp_path, _ in staged:
                    temp_path.unlink(missing_ok=True)
        return succeeded, failed, details, archives

    def _archive_images(
        self,
        folder: Path,
        staged: list[tuple[Path, Path, tuple[int, int, int, int]]],
    ) -> dict[str, object]:
        temp_archive: Path | None = None
        try:
            temp_archive = self._temporary_path(folder, ".tme3-media-archive-", ".zip")
            self._progress_value("media_archive_started", folder, 0, stage="archive")
            expected = [f"{source.stem}{IMAGE_RECODE_MARKER}{source.suffix}" for source, _, _ in staged]
            with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
                for (_, staged_path, _), name in zip(staged, expected):
                    self.cancel_check()
                    with staged_path.open("rb") as source_stream, output.open(name, "w") as target_stream:
                        while True:
                            self.cancel_check()
                            chunk = source_stream.read(1024 * 1024)
                            if not chunk:
                                break
                            target_stream.write(chunk)
            with zipfile.ZipFile(temp_archive, "r") as archived:
                if archived.namelist() != expected:
                    raise RuntimeError("Daftar nama ZIP tidak sesuai dengan file yang diproses.")
                for name in expected:
                    self.cancel_check()
                    with archived.open(name, "r") as stream:
                        while stream.read(1024 * 1024):
                            self.cancel_check()
            final_path = self._link_archive_without_overwrite(temp_archive, folder)
            self._progress_value("media_archive_completed", folder, 0, stage="archive", output=str(final_path))
            return {"folder": str(folder), "path": str(final_path), "count": len(expected), "status": "succeeded"}
        except Exception as exc:
            if _is_utility_control_error(exc):
                raise
            self._progress_value("media_archive_failed", folder, 0, stage="archive", error=str(exc)[:500])
            return {"folder": str(folder), "count": len(staged), "status": "failed", "error": str(exc)[:500]}
        finally:
            if temp_archive is not None:
                try:
                    temp_archive.unlink()
                except FileNotFoundError:
                    pass

    def _link_archive_without_overwrite(self, temp_archive: Path, folder: Path) -> Path:
        suffix = 1
        while True:
            name = "images.zip" if suffix == 1 else f"images_{suffix}.zip"
            destination = folder / name
            try:
                os.link(temp_archive, destination)
                return destination
            except FileExistsError:
                suffix += 1

    def _image_dimensions(self, path: Path) -> list[tuple[int, int]]:
        result = self.command_runner(
            ["identify", "-regard-warnings", "-format", "%w %h\\n", str(path)],
            path.parent,
            "utility-image-verify",
            capture_output=True,
            capture_log=True,
            capture_job_log=False,
        )
        if not isinstance(result, dict) or int(result.get("returncode", 0)) != 0:
            raise RuntimeError("Verifikasi dimensi gambar gagal.")
        dimensions: list[tuple[int, int]] = []
        for line in str(result.get("stdout") or "").splitlines():
            parts = line.split()
            if len(parts) != 2:
                raise RuntimeError("Ukuran gambar tidak dapat dibaca.")
            dimensions.append((int(parts[0]), int(parts[1])))
        if not dimensions:
            raise RuntimeError("ImageMagick tidak menemukan frame gambar.")
        return dimensions

    @staticmethod
    def _verify_image_dimensions(
        original: list[tuple[int, int]],
        compressed: list[tuple[int, int]],
    ) -> None:
        if len(original) != len(compressed):
            raise RuntimeError("Jumlah frame gambar berubah setelah diproses.")
        for (source_width, source_height), (width, height) in zip(original, compressed):
            if width > min(source_width, MAX_IMAGE_WIDTH) or height > source_height:
                raise RuntimeError("Dimensi hasil kompresi melampaui ukuran sumber.")

    def _copy_file(self, source: Path, destination: Path) -> None:
        with source.open("rb") as reader, destination.open("wb") as writer:
            while True:
                self.cancel_check()
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                writer.write(chunk)

    @staticmethod
    def _identity(path: Path) -> tuple[int, int, int, int]:
        stat = path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    @classmethod
    def _unlink_if_unchanged(
        cls, path: Path, identity: tuple[int, int, int, int]
    ) -> None:
        try:
            if cls._identity(path) == identity:
                path.unlink()
        except OSError:
            pass

    @staticmethod
    def _temporary_path(folder: Path, prefix: str, suffix: str) -> Path:
        descriptor, raw_path = tempfile.mkstemp(prefix=prefix + uuid.uuid4().hex + "-", suffix=suffix, dir=folder)
        os.close(descriptor)
        path = Path(raw_path)
        path.unlink()
        return path

    def _item_progress(
        self,
        phase: str,
        source: Path,
        index: int,
        error: str | None = None,
        **extra: object,
    ) -> None:
        percent = extra.pop("percent", None)
        payload = self._progress_value(
            phase,
            source,
            index,
            percent=percent,
            media_type=self._media_type(source),
            **extra,
        )
        if error:
            payload["error"] = error
        self._progress(payload)
        if phase in {"item_completed", "item_failed", "item_skipped"}:
            self._overall_done += 1

    def _progress_value(
        self,
        phase: str,
        name: Path,
        index: int,
        *,
        percent: float | int | None = None,
        **extra: object,
    ) -> dict[str, object]:
        total = self._overall_total
        current = min(total, self._overall_done + (float(percent) / 100 if percent is not None else 0))
        overall_percent = current * 100 / total if total else 100.0
        return {
            "phase": phase,
            "name": str(name),
            "index": index,
            "total": total,
            "percent": percent,
            "overall": {
                "current": current,
                "total": total,
                "percent": overall_percent,
                "unit": "files",
                "files_current": current,
                "files_total": total,
            },
            **extra,
        }

    def _progress(self, value: dict[str, object]) -> None:
        if self.progress_callback is not None:
            self.progress_callback(value)
