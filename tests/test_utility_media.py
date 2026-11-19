from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tme3bot.utility import (
    UtilityCancelledError,
    UtilityRunner,
    default_video_options,
    normalize_video_options,
)
from tme3bot.worker.executor_utility import UtilityExecutorMixin


class UtilityMediaJobTests(unittest.TestCase):
    def _fake_video_tools(self, root: Path, *, block: bool = False):
        bin_root = root / "bin"
        bin_root.mkdir()
        ffmpeg = bin_root / "ffmpeg"
        ffmpeg.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys, time\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "if '-f' in args and 'null' in args:\n"
            "    raise SystemExit(0)\n"
            "with open(os.environ['UTILITY_TEST_FFMPEG_CALLS'], 'a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(args) + '\\n')\n"
            "if os.environ.get('UTILITY_TEST_FFMPEG_BLOCK') == '1':\n"
            "    Path(os.environ['UTILITY_TEST_FFMPEG_STARTED']).touch()\n"
            "    while True:\n"
            "        time.sleep(0.05)\n"
            "output = Path(args[-1])\n"
            "if '-t' in args:\n"
            "    output.write_bytes(b'x' * int(os.environ.get('UTILITY_TEST_FFMPEG_SAMPLE_BYTES', '1')))\n"
            "    raise SystemExit(0)\n"
            "output.write_bytes(b'x' * 200000)\n"
            "for line in ['out_time_us=5000000', 'total_size=100000', 'progress=continue',\n"
            "             'out_time_us=10000000', 'total_size=200000', 'progress=end']:\n"
            "    print(line, flush=True)\n"
            "    if line.startswith('progress='):\n"
            "        time.sleep(float(os.environ.get('UTILITY_TEST_FFMPEG_PROGRESS_DELAY', '0')))\n",
            encoding="utf-8",
        )
        ffmpeg.chmod(0o755)
        ffprobe = bin_root / "ffprobe"
        ffprobe.write_text(
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            "args = sys.argv[1:]\n"
            "if any('format=duration' in arg for arg in args):\n"
            "    print(os.environ.get('UTILITY_TEST_VIDEO_DURATION', '10.0'))\n"
            "elif any('stream=codec_type' in arg for arg in args):\n"
            "    print('video')\n"
            "else:\n"
            "    raise SystemExit(1)\n",
            encoding="utf-8",
        )
        ffprobe.chmod(0o755)
        return bin_root

    def _fake_image_tools(self, bin_root: Path, *, block: bool = False):
        mogrify = bin_root / "mogrify"
        mogrify.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "import os, time\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "if args[:2] == ['-list', 'format']:\n"
            "    print('PNG* PNG rw+ Portable Network Graphics')\n"
            "    print('JPEG* JPEG rw+ Joint Photographic Experts Group')\n"
            "    raise SystemExit(0)\n"
            "if os.environ.get('UTILITY_TEST_MOGRIFY_BLOCK') == '1':\n"
            "    Path(os.environ['UTILITY_TEST_MOGRIFY_STARTED']).touch()\n"
            "    while True: time.sleep(0.05)\n"
            "Path(args[-1]).write_bytes(b'compressed image')\n",
            encoding="utf-8",
        )
        mogrify.chmod(0o755)
        identify = bin_root / "identify"
        identify.write_text(
            "#!/usr/bin/env python3\n"
            "print('100 50')\n",
            encoding="utf-8",
        )
        identify.chmod(0o755)

    def test_video_job_applies_per_job_encoder_options_and_verifies_before_removing_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "videos"
            folder.mkdir(parents=True)
            source = folder / "clip.mkv"
            source.write_bytes(b"video source")
            calls = root / "ffmpeg-calls.jsonl"
            bin_root = self._fake_video_tools(root)
            runner = UtilityRunner(Path("utility"), workspace_root=workspace)
            progress: list[dict[str, object]] = []
            runner.progress_callback = progress.append

            with self.assertLogs("tme3bot.utility", level="INFO") as command_logs:
                with patch.dict(os.environ, {
                    "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                    "UTILITY_TEST_FFMPEG_CALLS": str(calls),
                }):
                    result = runner.run(
                        "video_convert",
                        [str(folder)],
                        video_options={
                            "codec": "h264",
                            "resolution": "original",
                            "crf": 24,
                            "speed": "slow",
                        },
                    )

            output_log = "\n".join(command_logs.output)
            self.assertIn("utility-video-probe | 10.0", output_log)
            self.assertIn("utility-video-verify-probe | video", output_log)
            commands = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
            encode = commands[0]
            output = folder / "clip_recode.mp4"
            self.assertEqual(result.succeeded, [str(source)])
            self.assertTrue(output.is_file())
            self.assertFalse(source.exists())
            self.assertEqual(result.summary["files_total"], 1)
            self.assertEqual(result.summary["files_succeeded"], 1)
            self.assertEqual(encode[encode.index("-c:v") + 1], "libx264")
            self.assertEqual(encode[encode.index("-preset") + 1], "slow")
            self.assertEqual(encode[encode.index("-crf") + 1], "24")
            self.assertNotIn("-vf", encode)
            self.assertTrue(any(item.get("phase") == "item_progress" for item in progress))

    def test_video_preflight_skips_when_estimated_savings_do_not_exceed_40_percent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "videos"
            folder.mkdir(parents=True)
            source = folder / "clip.mkv"
            source.write_bytes(b"x" * 100_000)
            calls = root / "ffmpeg-calls.jsonl"
            bin_root = self._fake_video_tools(root)
            progress: list[dict[str, object]] = []
            runner = UtilityRunner(Path("utility"), workspace_root=workspace)
            runner.progress_callback = progress.append

            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                "UTILITY_TEST_FFMPEG_CALLS": str(calls),
                "UTILITY_TEST_FFMPEG_SAMPLE_BYTES": "16250",
            }):
                result = runner.run("video_convert", [str(folder)])

            commands = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(result.succeeded, [])
            self.assertEqual(result.summary["files_skipped"], 1)
            self.assertEqual(result.details[0]["status"], "skipped")
            self.assertEqual(result.details[0]["estimated_savings_percent"], 35.0)
            self.assertTrue(source.is_file())
            self.assertFalse((folder / "clip_recode.mp4").exists())
            self.assertTrue(commands)
            self.assertTrue(all("-t" in command for command in commands))
            self.assertTrue(any(item.get("phase") == "item_skipped" for item in progress))

    def test_video_preflight_skips_at_the_exact_40_percent_threshold(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "videos"
            folder.mkdir(parents=True)
            source = folder / "clip.mkv"
            source.write_bytes(b"x" * 100_000)
            calls = root / "ffmpeg-calls.jsonl"
            bin_root = self._fake_video_tools(root)
            runner = UtilityRunner(Path("utility"), workspace_root=workspace)

            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                "UTILITY_TEST_FFMPEG_CALLS": str(calls),
                "UTILITY_TEST_FFMPEG_SAMPLE_BYTES": "15000",
            }):
                result = runner.run("video_convert", [str(folder)])

            self.assertEqual(result.details[0]["estimated_savings_percent"], 40.0)
            self.assertEqual(result.summary["files_skipped"], 1)
            self.assertTrue(source.is_file())
            self.assertFalse((folder / "clip_recode.mp4").exists())

    def test_skipped_video_advances_overall_progress_before_the_next_preflight(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "videos"
            folder.mkdir(parents=True)
            (folder / "a.mkv").write_bytes(b"x" * 100_000)
            (folder / "b.mkv").write_bytes(b"x" * 100_000)
            bin_root = self._fake_video_tools(root)
            progress: list[dict[str, object]] = []
            runner = UtilityRunner(Path("utility"), workspace_root=workspace)
            runner.progress_callback = progress.append

            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                "UTILITY_TEST_FFMPEG_CALLS": str(root / "ffmpeg-calls.jsonl"),
                "UTILITY_TEST_FFMPEG_SAMPLE_BYTES": "16250",
            }):
                result = runner.run("video_convert", [str(folder)])

            self.assertEqual(result.summary["files_skipped"], 2)
            second_preflight = next(
                item for item in progress
                if item.get("phase") == "media_preflight_started" and item.get("index") == 2
            )
            self.assertEqual(second_preflight["overall"]["current"], 1)

    def test_long_video_preflight_samples_start_middle_and_end_before_full_encode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "videos"
            folder.mkdir(parents=True)
            source = folder / "clip.mkv"
            source.write_bytes(b"x" * 100_000)
            calls = root / "ffmpeg-calls.jsonl"
            bin_root = self._fake_video_tools(root)
            runner = UtilityRunner(Path("utility"), workspace_root=workspace)

            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                "UTILITY_TEST_FFMPEG_CALLS": str(calls),
                "UTILITY_TEST_VIDEO_DURATION": "120.0",
            }):
                result = runner.run("video_convert", [str(folder)])

            commands = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
            sample_commands = [command for command in commands if "-t" in command]
            encode_commands = [command for command in commands if "-t" not in command]
            sample_starts = {command[command.index("-ss") + 1] for command in sample_commands}
            self.assertEqual(result.outcome, "succeeded")
            self.assertEqual(len(sample_commands), 3)
            self.assertEqual(len(sample_starts), 3)
            self.assertEqual(len(encode_commands), 1)

    def test_video_resolution_filters_escape_expression_commas(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            bin_root = self._fake_video_tools(root)
            calls = root / "ffmpeg-calls.jsonl"
            resolutions = (("720p", 720), ("1080p", 1080))

            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                "UTILITY_TEST_FFMPEG_CALLS": str(calls),
            }):
                for resolution, expected_height in resolutions:
                    with self.subTest(resolution=resolution):
                        folder = workspace / resolution
                        folder.mkdir(parents=True)
                        (folder / "clip.mkv").write_bytes(b"video source")
                        runner = UtilityRunner(Path("utility"), workspace_root=workspace)
                        result = runner.run(
                            "video_convert",
                            [str(folder)],
                            video_options={
                                "codec": "h264",
                                "resolution": resolution,
                                "crf": 24,
                                "speed": "slow",
                            },
                        )
                        self.assertEqual(result.outcome, "succeeded")

            encode_commands = [
                json.loads(line)
                for line in calls.read_text(encoding="utf-8").splitlines()
                if "-t" not in json.loads(line)
            ]
            self.assertEqual(len(encode_commands), len(resolutions))
            for command, (resolution, expected_height) in zip(encode_commands, resolutions):
                with self.subTest(resolution=resolution):
                    filter_value = command[command.index("-vf") + 1]
                    self.assertEqual(filter_value, f"scale=-2:min({expected_height}\\,ih)")

    def test_worker_utility_job_publishes_file_count_and_carries_cancel_owner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "videos"
            folder.mkdir(parents=True)
            source = folder / "clip.mkv"
            source.write_bytes(b"video source")
            bin_root = self._fake_video_tools(root)

            class CapturingPublisher:
                def __init__(self):
                    self.events = []

                def emit(self, *args, **kwargs):
                    self.events.append((args, kwargs))

            class Executor(UtilityExecutorMixin):
                def __init__(self):
                    self.config = SimpleNamespace(
                        utility_workspace_root=str(workspace),
                        job_stall_timeout_seconds=0,
                    )
                    self.publisher = CapturingPublisher()
                    self._lock = threading.RLock()
                    self._utility_runners = {}

                def _workspace_path(self, raw, *, require_absolute=False):
                    path = Path(raw)
                    if require_absolute and not path.is_absolute():
                        raise ValueError("workspace path must be absolute")
                    resolved = path.resolve()
                    resolved.relative_to(workspace.resolve())
                    return resolved

                def _append_job_log(self, _line):
                    pass

                def _command_callback(self):
                    return None

            executor = Executor()
            runner_type = UtilityRunner
            owners = []

            def build_runner(*args, **kwargs):
                owners.append(kwargs.get("owner_job_id"))
                return runner_type(*args, workspace_root=workspace, **kwargs)

            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                "UTILITY_TEST_FFMPEG_CALLS": str(root / "ffmpeg-calls.jsonl"),
            }), patch(
                "tme3bot.worker.executor_utility.UtilityRunner",
                side_effect=build_runner,
            ):
                result = executor._utility({
                    "job_id": "media-job-17",
                    "payload": {
                        "utility": "video_convert",
                        "folders": [str(folder)],
                        "settings": {},
                        "video_options": {
                            "codec": "h265",
                            "resolution": "720p",
                            "crf": 30,
                            "speed": "veryfast",
                        },
                    },
                })

            self.assertEqual(owners, ["media-job-17"])
            self.assertEqual(result["summary"]["files_total"], 1)
            progress = [kwargs.get("progress") for _, kwargs in executor.publisher.events]
            self.assertTrue(any(
                isinstance(item, dict)
                and item.get("overall", {}).get("files_total") == 1
                and item.get("item", {}).get("name") == str(source)
                for item in progress
            ))

    def test_worker_utility_job_reports_preflight_skips_in_counters_and_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "videos"
            folder.mkdir(parents=True)
            source = folder / "clip.mkv"
            source.write_bytes(b"x" * 100_000)
            bin_root = self._fake_video_tools(root)

            class CapturingPublisher:
                def __init__(self):
                    self.events = []

                def emit(self, *args, **kwargs):
                    self.events.append((args, kwargs))

            class Executor(UtilityExecutorMixin):
                def __init__(self):
                    self.config = SimpleNamespace(
                        utility_workspace_root=str(workspace),
                        job_stall_timeout_seconds=0,
                    )
                    self.publisher = CapturingPublisher()
                    self._lock = threading.RLock()
                    self._utility_runners = {}

                def _workspace_path(self, raw, *, require_absolute=False):
                    path = Path(raw)
                    if require_absolute and not path.is_absolute():
                        raise ValueError("workspace path must be absolute")
                    resolved = path.resolve()
                    resolved.relative_to(workspace.resolve())
                    return resolved

                def _append_job_log(self, _line):
                    pass

                def _command_callback(self):
                    return None

            executor = Executor()
            def build_runner(*args, **kwargs):
                return UtilityRunner(*args, workspace_root=workspace, **kwargs)

            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                "UTILITY_TEST_FFMPEG_CALLS": str(root / "ffmpeg-calls.jsonl"),
                "UTILITY_TEST_FFMPEG_SAMPLE_BYTES": "16250",
            }), patch(
                "tme3bot.worker.executor_utility.UtilityRunner",
                side_effect=build_runner,
            ):
                result = executor._utility({
                    "job_id": "media-skip-job",
                    "payload": {
                        "utility": "video_convert",
                        "folders": [str(folder)],
                        "settings": {},
                        "video_options": {},
                    },
                })

            self.assertEqual(result["summary"]["files_skipped"], 1)
            self.assertEqual(result["summary"]["files_succeeded"], 0)
            self.assertTrue(source.is_file())
            progress = [kwargs.get("progress") for _, kwargs in executor.publisher.events]
            self.assertTrue(any(
                isinstance(item, dict)
                and item.get("phase") == "item_skipped"
                and item.get("counters", {}).get("skipped") == 1
                and item.get("item", {}).get("estimated_savings_percent") == 35.0
                for item in progress
            ))
            self.assertTrue(any(
                isinstance(item, dict)
                and item.get("phase") == "completed"
                and item.get("counters", {}).get("skipped") == 1
                and item.get("overall", {}).get("files_current") == 1
                for item in progress
            ))

    def test_ffmpeg_progress_keeps_active_encode_from_triggering_stall_watchdog(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "videos"
            folder.mkdir(parents=True)
            source = folder / "clip.mkv"
            source.write_bytes(b"video source")
            bin_root = self._fake_video_tools(root)
            runner = UtilityRunner(
                Path("utility"), workspace_root=workspace, stall_timeout_seconds=1
            )

            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                "UTILITY_TEST_FFMPEG_CALLS": str(root / "ffmpeg-calls.jsonl"),
                "UTILITY_TEST_FFMPEG_PROGRESS_DELAY": "0.7",
            }):
                result = runner.run("video_convert", [str(folder)])

            self.assertEqual(result.outcome, "succeeded")
            self.assertTrue((folder / "clip_recode.mp4").is_file())

    def test_codec_defaults_match_the_existing_conversion_profiles(self):
        self.assertEqual(
            default_video_options("h265").to_payload(),
            {"codec": "h265", "resolution": "720p", "crf": 30, "speed": "veryfast"},
        )
        self.assertEqual(
            default_video_options("h264").to_payload(),
            {"codec": "h264", "resolution": "1080p", "crf": 18, "speed": "veryfast"},
        )
        normalized_preset = normalize_video_options({
            "codec": None,
            "resolution": None,
            "crf": None,
            "speed": None,
            "preset": "slow",
        })
        self.assertEqual(normalized_preset.speed, "slow")

    def test_image_job_archives_verified_outputs_before_removing_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "images"
            folder.mkdir(parents=True)
            source = folder / "cover.png"
            source.write_bytes(b"original image")
            ignored = folder / "notes.txt"
            ignored.write_text("keep", encoding="utf-8")
            bin_root = self._fake_video_tools(root)
            self._fake_image_tools(bin_root)
            job_logs: list[str] = []
            runner = UtilityRunner(
                Path("utility"), workspace_root=workspace, log_callback=job_logs.append
            )

            with self.assertLogs("tme3bot.utility", level="INFO") as command_logs:
                with patch.dict(os.environ, {
                    "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                }):
                    result = runner.run("image_compress", [str(folder)])

            output_log = "\n".join(command_logs.output)
            self.assertIn("utility-image-formats | PNG* PNG rw+", output_log)
            self.assertIn("utility-image-verify | 100 50", output_log)
            self.assertFalse(any("PNG* PNG rw+" in line or "100 50" in line for line in job_logs))
            archive = folder / "images.zip"
            self.assertEqual(result.summary["files_succeeded"], 1)
            self.assertFalse(source.exists())
            self.assertTrue(ignored.exists())
            with zipfile.ZipFile(archive) as zipped:
                self.assertEqual(zipped.namelist(), ["cover_recode.png"])
                self.assertIsNone(zipped.testzip())

    def test_media_pipeline_converts_video_and_archives_images_in_one_job(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "media"
            folder.mkdir(parents=True)
            video = folder / "clip.mkv"
            image = folder / "cover.png"
            video.write_bytes(b"video source")
            image.write_bytes(b"image source")
            bin_root = self._fake_video_tools(root)
            self._fake_image_tools(bin_root)
            runner = UtilityRunner(Path("utility"), workspace_root=workspace)

            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                "UTILITY_TEST_FFMPEG_CALLS": str(root / "ffmpeg-calls.jsonl"),
            }):
                result = runner.run("media_pipeline", [str(folder)])

            self.assertEqual(result.summary["files_total"], 2)
            self.assertEqual(result.summary["files_succeeded"], 2)
            self.assertEqual(result.outcome, "succeeded")
            self.assertFalse(video.exists())
            self.assertFalse(image.exists())
            self.assertTrue((folder / "clip_recode.mp4").is_file())
            self.assertTrue(zipfile.is_zipfile(folder / "images.zip"))

    def test_video_cancel_preserves_source_and_removes_partial_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "videos"
            folder.mkdir(parents=True)
            source = folder / "clip.ts"
            source.write_bytes(b"video source")
            started = root / "ffmpeg-started"
            calls = root / "ffmpeg-calls.jsonl"
            bin_root = self._fake_video_tools(root, block=True)
            runner = UtilityRunner(
                Path("utility"), workspace_root=workspace, owner_job_id="media-job"
            )
            failure: list[BaseException] = []

            def run_job():
                try:
                    runner.run("video_convert", [str(folder)])
                except BaseException as exc:
                    failure.append(exc)

            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                "UTILITY_TEST_FFMPEG_CALLS": str(calls),
                "UTILITY_TEST_FFMPEG_BLOCK": "1",
                "UTILITY_TEST_FFMPEG_STARTED": str(started),
            }):
                thread = threading.Thread(target=run_job)
                thread.start()
                deadline = time.monotonic() + 5
                while not started.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(started.exists(), "fake FFmpeg did not start")
                self.assertFalse(runner.cancel_current("another-job"))
                self.assertTrue(runner.cancel_current("media-job"))
                thread.join(timeout=5)

            self.assertFalse(thread.is_alive())
            self.assertIsInstance(failure[0], UtilityCancelledError)
            self.assertTrue(source.exists())
            self.assertFalse((folder / "clip_recode.mp4").exists())
            self.assertFalse(list(folder.glob(".tme3-media-*")))

    def test_cancel_before_runner_starts_is_not_lost(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "videos"
            folder.mkdir(parents=True)
            source = folder / "clip.mkv"
            source.write_bytes(b"video source")
            runner = UtilityRunner(
                Path("utility"), workspace_root=workspace, owner_job_id="media-job"
            )

            self.assertTrue(runner.cancel_current("media-job"))
            with self.assertRaises(UtilityCancelledError):
                runner.run("video_convert", [str(folder)])
            self.assertTrue(source.exists())

            bin_root = self._fake_video_tools(root)
            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                "UTILITY_TEST_FFMPEG_CALLS": str(root / "ffmpeg-calls.jsonl"),
            }):
                result = runner.run("video_convert", [str(folder)])
            self.assertEqual(result.outcome, "succeeded")

    def test_cancel_while_paused_between_commands_unblocks_runner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "videos"
            folder.mkdir(parents=True)
            source = folder / "clip.mkv"
            source.write_bytes(b"video source")
            bin_root = self._fake_video_tools(root)
            waiting = threading.Event()
            failure: list[BaseException] = []

            class ObservedRunner(UtilityRunner):
                def _wait_until_resumed(self) -> None:
                    waiting.set()
                    super()._wait_until_resumed()

            runner = ObservedRunner(
                Path("utility"), workspace_root=workspace, owner_job_id="media-job"
            )
            self.assertTrue(runner.pause_current("media-job"))

            def run_job():
                try:
                    runner.run("video_convert", [str(folder)])
                except BaseException as exc:
                    failure.append(exc)

            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
            }):
                thread = threading.Thread(target=run_job)
                thread.start()
                self.assertTrue(waiting.wait(timeout=5), "runner did not reach paused command")
                self.assertTrue(runner.cancel_current("media-job"))
                thread.join(timeout=5)

            self.assertFalse(thread.is_alive())
            self.assertIsInstance(failure[0], UtilityCancelledError)
            self.assertTrue(source.exists())

    def test_image_cancel_preserves_source_and_removes_temporary_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            folder = workspace / "images"
            folder.mkdir(parents=True)
            source = folder / "cover.png"
            source.write_bytes(b"original image")
            started = root / "mogrify-started"
            bin_root = self._fake_video_tools(root)
            self._fake_image_tools(bin_root, block=True)
            runner = UtilityRunner(Path("utility"), workspace_root=workspace)
            failure: list[BaseException] = []

            def run_job():
                try:
                    runner.run("image_compress", [str(folder)])
                except BaseException as exc:
                    failure.append(exc)

            with patch.dict(os.environ, {
                "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
                "UTILITY_TEST_MOGRIFY_BLOCK": "1",
                "UTILITY_TEST_MOGRIFY_STARTED": str(started),
            }):
                thread = threading.Thread(target=run_job)
                thread.start()
                deadline = time.monotonic() + 5
                while not started.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(started.exists(), "fake mogrify did not start")
                self.assertTrue(runner.cancel_current())
                thread.join(timeout=5)

            self.assertFalse(thread.is_alive())
            self.assertIsInstance(failure[0], UtilityCancelledError)
            self.assertTrue(source.exists())
            self.assertFalse((folder / "images.zip").exists())
            self.assertFalse(list(folder.glob(".tme3-media-*")))


if __name__ == "__main__":
    unittest.main()
