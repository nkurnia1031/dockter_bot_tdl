import shutil
import tempfile
import threading
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from tme3bot.progress import DownloadProgressTracker
from tme3bot.progress_reporter import ProgressReporter
from tme3bot.service import ExportJobResult, DownloadedJsonResult
from tme3bot.utility import UtilityResult
from tme3bot.worker.executor import (
    CommandMilestoneRecorder,
    JobLogSnapshot,
    WorkerEventPublisher,
    WorkerJobExecutor,
)
from tme3bot.worker.quick_export import (
    QuickModeError,
    QuickThumbnailBuilder,
    migrate_legacy_quick_stage,
    quick_folder_name,
    quick_stage_root,
    quick_storage_caption,
    visual_media,
    scan_quick_stages,
    write_quick_manifest,
)


class QuickThumbnailTests(unittest.TestCase):
    def make_media(self, root: Path, names: list[str]) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for name in names:
            (root / name).write_bytes(b"media")

    def test_job_log_keeps_newest_tail_and_returns_newest_first(self) -> None:
        snapshot = JobLogSnapshot()
        snapshot.max_lines = 3
        for value in ("old", "middle", "new", "newest"):
            snapshot.add(value)
        self.assertEqual(snapshot.value()["lines"], ["newest", "new", "middle"])
        self.assertTrue(snapshot.value()["truncated"])
        self.assertEqual(snapshot.value()["order"], "newest_first")

    def test_job_log_keeps_only_the_latest_progress_bar_per_transfer(self) -> None:
        snapshot = JobLogSnapshot()
        snapshot.add("archive.7z.001 -> channel ... 10.0% [#####........................................] [1s; 1 MB/s]")
        snapshot.add("[#####................................................................................................................] [1s; 1 MB/s]")
        snapshot.add("message after progress")
        snapshot.add("archive.7z.001 -> channel ... 20.0% [##########.................................] [2s; 2 MB/s]")
        snapshot.add("[##########........................................................................................................] [2s; 2 MB/s]")

        lines = snapshot.value()["lines"]
        progress = [line for line in lines if "archive.7z.001 -> channel" in line]
        self.assertEqual(len(progress), 1)
        self.assertIn("20.0%", progress[0])
        self.assertEqual(sum("[" in line and "/s]" in line for line in lines), 1)

    def test_job_log_keeps_only_the_latest_runtime_statistics(self) -> None:
        snapshot = JobLogSnapshot()
        snapshot.add("CPU: 2.03% Memory: 52.32 MB Goroutines: 46")
        snapshot.add("CPU: 0.00% Memory: 52.32 MB Goroutines: 46")

        lines = snapshot.value()["lines"]
        runtime = [line for line in lines if line.startswith("CPU:")]
        self.assertEqual(runtime, ["CPU: 0.00% Memory: 52.32 MB Goroutines: 46"])

    def test_worker_event_audit_records_delivery_without_payload_secrets(self) -> None:
        events: list[str] = []
        publisher = WorkerEventPublisher("http://backend", "internal-token")
        publisher.register_audit_callback("job-audit", events.append)
        with patch("tme3bot.worker.executor_support.request_json", return_value={}):
            publisher.begin("job-audit", 10)
            publisher.emit(
                "job-audit",
                "running",
                "progress.snapshot",
                transient=True,
                progress={"message": "safe"},
            )

        self.assertTrue(any("send sequence=11" in line for line in events))
        self.assertTrue(any("delivered sequence=11" in line for line in events))
        self.assertNotIn("internal-token", "\n".join(events))

    def test_worker_file_log_compacts_redraws_but_keeps_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "worker.log"
            path.write_text(
                "\n".join(
                    [
                        "[2026-09-23T01:00:00+07:00] $ tdl up archive.7z.001",
                        "[2026-09-23T01:00:01+07:00] archive.7z.001 -> channel ... 1.0% [#...............................................] [1s; 1 MB/s]",
                        "[2026-09-23T01:00:02+07:00] [#................................................................................] [1s; 1 MB/s]",
                        "[2026-09-23T01:00:03+07:00] archive.7z.001 -> channel ... 2.0% [##..............................................] [2s; 2 MB/s]",
                        "[2026-09-23T01:00:04+07:00] [##...............................................................................] [2s; 2 MB/s]",
                        "[2026-09-23T01:00:05+07:00] CPU: 2.03% Memory: 52.32 MB Goroutines: 46",
                        "[2026-09-23T01:00:06+07:00] CPU: 0.00% Memory: 52.32 MB Goroutines: 46",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            WorkerJobExecutor._compact_quick_log(path)
            content = path.read_text(encoding="utf-8")
            self.assertEqual(content.count("archive.7z.001 -> channel"), 1)
            self.assertIn("2.0%", content)
            self.assertIn("$ tdl up archive.7z.001", content)
            self.assertNotIn("[##................................................................", content)
            self.assertEqual(content.count("CPU:"), 1)
            self.assertIn("CPU: 0.00% Memory: 52.32 MB Goroutines: 46", content)

    def test_command_milestone_is_bounded_and_redacts_secret(self) -> None:
        events = []

        class Publisher:
            def emit(self, *args, **kwargs):
                events.append((args, kwargs))

        recorder = CommandMilestoneRecorder(Publisher(), "job-1", ["secret-value"])
        recorder(
            ["utility", "--password", "secret-value"],
            1,
            "\n".join([f"line-{index}" for index in range(100)]) + "\nsecret-value",
            1.25,
            "utility-test",
        )
        result = events[0][1]["result"]
        self.assertEqual(events[0][0][2], "command.completed")
        self.assertEqual(result["command"], ["utility", "--password", "[redacted]"])
        self.assertLessEqual(len(result["output_tail"]), 40)
        self.assertLessEqual(
            sum(len(line.encode("utf-8")) + 1 for line in result["output_tail"]),
            8 * 1024,
        )
        self.assertTrue(result["output_truncated"])
        self.assertNotIn("secret-value", str(result))

    def test_command_milestone_is_started_then_completed_with_same_id(self) -> None:
        events = []

        class Publisher:
            def emit(self, *args, **kwargs):
                events.append((args, kwargs))

        recorder = CommandMilestoneRecorder(Publisher(), "job-1", [])
        command_id = recorder.command_started(["ffmpeg", "-i", "input.mp4"], "thumbnail")
        recorder.command_completed(
            ["ffmpeg", "-i", "input.mp4"],
            0,
            "frame=1\n",
            0.5,
            "thumbnail",
            command_id,
        )

        self.assertEqual([event[0][2] for event in events], ["command.started", "command.completed"])
        self.assertEqual(events[0][1]["result"]["command_id"], command_id)
        self.assertEqual(events[1][1]["result"]["command_id"], command_id)

    def test_quickmode_worker_log_is_persistent_and_heartbeat_is_best_effort(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            events = []

            class Publisher:
                def emit(self, *args, **kwargs):
                    events.append((args, kwargs))

            executor = WorkerJobExecutor(
                SimpleNamespace(utility_workspace_root=workspace),
                SimpleNamespace(),
                Publisher(),
            )
            stage = quick_stage_root(workspace, "log-stage")
            stage.mkdir(parents=True)
            executor._job_log.snapshot = JobLogSnapshot()
            executor._job_log.job_id = "log-job"
            executor._job_log.file_path = stage / "worker.log"
            executor._job_log.secrets = ["secret-value"]
            executor._job_log.heartbeat_at = 0.0
            try:
                executor._append_job_log("progress secret-value")
            finally:
                del executor._job_log.snapshot
                del executor._job_log.job_id
                del executor._job_log.file_path
                del executor._job_log.secrets
                del executor._job_log.heartbeat_at

            content = (stage / "worker.log").read_text(encoding="utf-8")
            self.assertIn("progress [redacted]", content)
            self.assertNotIn("secret-value", content)
            self.assertIn("+07:00", content)
            self.assertTrue(any(event[0][2] == "progress.snapshot" for event in events))

    def test_quick_stage_cleanup_detaches_heartbeat_log_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            stage = quick_stage_root(workspace, "cleanup-stage")
            stage.mkdir(parents=True)
            log_path = stage / "worker.log"
            log_path.write_text("before cleanup\n", encoding="utf-8")

            class Publisher:
                def __init__(self):
                    self.audit_callbacks = {}

                def register_audit_callback(self, job_id, callback):
                    self.audit_callbacks[job_id] = callback

                def unregister_audit_callback(self, job_id):
                    self.audit_callbacks.pop(job_id, None)

            publisher = Publisher()
            executor = WorkerJobExecutor(
                SimpleNamespace(utility_workspace_root=workspace),
                SimpleNamespace(),
                publisher,
            )
            executor._job_log.job_id = "cleanup-job"
            executor._job_log.file_path = log_path
            executor._register_quick_log("cleanup-job", log_path)
            stale_callback = publisher.audit_callbacks["cleanup-job"]
            rmtree = shutil.rmtree

            def rmtree_with_heartbeat(path):
                # Simulate a heartbeat that already captured the callback when
                # cleanup began. It must not recreate worker.log in the stage.
                stale_callback("[telemetry] delivered heartbeat")
                self.assertEqual(log_path.read_text(encoding="utf-8"), "before cleanup\n")
                rmtree(path)

            try:
                with patch("tme3bot.worker.executor_quickmode.shutil.rmtree", side_effect=rmtree_with_heartbeat):
                    executor._cleanup_quick_stage("cleanup-job", stage)

                self.assertFalse(stage.exists())
                self.assertNotIn("cleanup-job", publisher.audit_callbacks)
                self.assertIsNone(executor._job_log.file_path)
            finally:
                del executor._job_log.job_id
                del executor._job_log.file_path

    def test_download_progress_callbacks_follow_the_download_lock_owner(self) -> None:
        tracker = DownloadProgressTracker()
        runtime = SimpleNamespace(
            download_progress=tracker,
            download_operation_lock=threading.Lock(),
        )
        executor = WorkerJobExecutor(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
        events: list[tuple[str, str]] = []
        first_entered = threading.Event()
        second_attempting = threading.Event()
        first_ready_to_release = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()

        def first_callback(event_type, snapshot):
            events.append(("first", snapshot.phase))

        def second_callback(event_type, snapshot):
            events.append(("second", snapshot.phase))

        def first_download():
            with executor._download_progress_operation(runtime, first_callback):
                tracker.set_phase("first-running")
                first_entered.set()
                second_attempting.wait(timeout=2)
                tracker.set_phase("first-still-running")
                first_ready_to_release.set()
                release_first.wait(timeout=2)

        def second_download():
            first_entered.wait(timeout=2)
            second_attempting.set()
            with executor._download_progress_operation(runtime, second_callback):
                second_entered.set()
                tracker.set_phase("second-running")

        first_thread = threading.Thread(target=first_download)
        second_thread = threading.Thread(target=second_download)
        first_thread.start()
        second_thread.start()
        try:
            self.assertTrue(first_ready_to_release.wait(timeout=2))
            self.assertFalse(second_entered.is_set())
        finally:
            release_first.set()
            first_thread.join(timeout=2)
            second_thread.join(timeout=2)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(
            events,
            [
                ("first", "first-running"),
                ("first", "first-still-running"),
                ("second", "second-running"),
            ],
        )

    def test_quickmode_verify_requires_channel_and_drive_before_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            stage = quick_stage_root(workspace, "verify-stage")
            stage.mkdir(parents=True)
            (stage / "batch.7z.001").write_bytes(b"archive")
            (stage / "batch.png").write_bytes(b"thumbnail")
            config_path = workspace / ".config" / "rclone.conf"
            config_path.parent.mkdir()
            config_path.write_text("[googledrive]\n", encoding="utf-8")
            caption = "batch\n#ModeCepat #2026"
            write_quick_manifest(
                stage,
                {
                    "stage_job_id": "verify-stage",
                    "folder_name": "batch",
                    "phase": "uploading",
                    "caption": caption,
                    "rclone_destination": "googledrive:backup",
                    "upload_result": {
                        "uploaded_items": [
                            {"original_name": "batch.7z.001", "channel_message_id": 101},
                            {"original_name": "batch.png", "channel_message_id": 102},
                        ]
                    },
                },
            )

            class StorageClient:
                output_callback = None
                run_as_user = "storage-user"

                def export_messages(self, channel, start_id, target, **kwargs):
                    name = "photo-without-original-name.jpg" if int(start_id) == 102 else "batch.7z.001"
                    return SimpleNamespace(
                        messages=[
                            {
                                "id": int(start_id),
                                "caption": caption,
                                "file": {"name": name},
                            }
                        ]
                    )

            storage_config = SimpleNamespace(storage_channel_ref="-100123")
            storage_runtime = SimpleNamespace(
                config=storage_config,
                export_tdl_client=StorageClient(),
                export_operation_lock=threading.RLock(),
            )

            class Profiles:
                def list_profiles(self):
                    return ["storage"]

                def runtime(self, profile):
                    if profile != "storage":
                        raise AssertionError(profile)
                    return storage_runtime

            class VerifyRclone:
                def __init__(self, **kwargs):
                    del kwargs

                def verify_files(self, files, destination, config, **kwargs):
                    del kwargs
                    names = [path.name for path in files]
                    if destination != "googledrive:backup":
                        raise AssertionError(destination)
                    if config != config_path.resolve():
                        raise AssertionError(config)
                    return {
                        "destination": destination,
                        "expected": len(names),
                        "found": len(names),
                        "files": names,
                        "missing": [],
                    }

            config = SimpleNamespace(
                utility_workspace_root=workspace,
                worker_storage_profile="storage",
                rclone_config_path=config_path,
                profile_root=workspace,
                job_stall_timeout_seconds=30,
            )
            publisher = SimpleNamespace(emit=lambda *args, **kwargs: None)
            executor = WorkerJobExecutor(config, Profiles(), publisher)
            with patch("tme3bot.worker.executor_quickmode.RcloneRunner", VerifyRclone), patch(
                "tme3bot.worker.executor_quickmode.ensure_quick_stage_writable"
            ) as ensure_writable:
                result = executor.quickmode_verify("verify-stage")

            self.assertEqual(result["status"], "verified")
            self.assertEqual(result["channel_found"], 2)
            self.assertEqual(result["drive_found"], 1)
            self.assertTrue(result["staging_cleaned"])
            self.assertFalse(stage.exists())
            ensure_writable.assert_called_once_with(stage / ".quickmode-verify", "storage-user")

    def test_four_photos_without_videos_do_not_invoke_video_processing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.make_media(root, ["01.jpg", "02.png", "03.webp", "04.jpeg"])
            builder = QuickThumbnailBuilder()
            commands: list[list[str]] = []

            def fake_run(command: list[str]) -> str:
                commands.append(command)
                Path(command[-1]).write_bytes(b"png")
                return ""

            builder._run = fake_run  # type: ignore[method-assign]
            details = builder.build(root, root / "result.png")

            self.assertEqual(details["photos_used"], 4)
            self.assertFalse(details["video_contact_sheet"])
            self.assertEqual(len(commands), 1)
            self.assertTrue((root / "result.png").exists())

    def test_three_photos_are_collaged_without_an_empty_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.make_media(root, ["01.jpg", "02.png", "03.webp"])
            builder = QuickThumbnailBuilder()
            commands: list[list[str]] = []

            def fake_run(command: list[str]) -> str:
                commands.append(command)
                Path(command[-1]).write_bytes(b"png")
                return ""

            builder._run = fake_run  # type: ignore[method-assign]
            details = builder.build(root, root / "result.png")

            compose = next(command for command in commands if "-filter_complex" in command)
            filter_value = compose[compose.index("-filter_complex") + 1]
            self.assertEqual(details["photos_used"], 3)
            self.assertFalse(details["video_contact_sheet"])
            self.assertIn("xstack=inputs=3", filter_value)
            self.assertIn("layout=0_0|533_0|1066_0", filter_value)

    def test_four_photos_and_four_videos_create_eight_collage_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.make_media(
                root,
                [
                    "01.jpg",
                    "02.png",
                    "03.webp",
                    "04.jpeg",
                    "clip-1.mp4",
                    "clip-2.mp4",
                    "clip-3.mp4",
                    "clip-4.mp4",
                    "clip-5.mp4",
                ],
            )
            builder = QuickThumbnailBuilder()
            commands: list[list[str]] = []

            def fake_run(command: list[str]) -> str:
                commands.append(command)
                if command[0] == "ffprobe":
                    return "32"
                Path(command[-1]).write_bytes(b"png")
                return ""

            builder._run = fake_run  # type: ignore[method-assign]
            details = builder.build(root, root / "result.png")

            self.assertEqual(details["photos_used"], 4)
            self.assertTrue(details["video_contact_sheet"])
            self.assertEqual(details["video_contact_sheets_used"], 4)
            self.assertEqual(details["video_frames_used"], 4)
            self.assertEqual(sum(command[0] == "ffprobe" for command in commands), 4)
            # Verify fast seeking with -ss is used instead of slow tile decoding
            self.assertEqual(
                sum("-ss" in command for command in commands),
                4,
            )
            compose = next(command for command in commands if "-filter_complex" in command)
            filter_value = compose[compose.index("-filter_complex") + 1]
            self.assertIn("xstack=inputs=8", filter_value)
            self.assertNotIn("804", filter_value)
            self.assertFalse(any(path.exists() for path in root.glob(".video-frame-*.png")))

    def test_single_long_video_fulfills_quota_eight_with_fast_sampling(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.make_media(root, ["long_movie.mp4"])
            builder = QuickThumbnailBuilder()
            commands: list[list[str]] = []

            def fake_run(command: list[str]) -> str:
                commands.append(command)
                if command[0] == "ffprobe":
                    return "7200.0"  # 2 hours duration
                Path(command[-1]).write_bytes(b"png")
                return ""

            builder._run = fake_run  # type: ignore[method-assign]
            details = builder.build(root, root / "result.png")

            self.assertEqual(details["photos_used"], 0)
            self.assertTrue(details["video_contact_sheet"])
            self.assertEqual(details["video_frames_used"], 8)
            # 1 ffprobe duration check + 8 frame extractions + 1 compose
            self.assertEqual(sum(command[0] == "ffprobe" for command in commands), 1)
            frame_extractions = [cmd for cmd in commands if "-ss" in cmd]
            self.assertEqual(len(frame_extractions), 8)
            # Ensure extracted timestamps are across the 7200s duration and sorted
            timestamps = [float(cmd[cmd.index("-ss") + 1]) for cmd in frame_extractions]
            self.assertEqual(len(timestamps), 8)
            self.assertEqual(timestamps, sorted(timestamps))
            self.assertGreater(timestamps[0], 0.0)
            self.assertLess(timestamps[-1], 7200.0)
            compose = next(command for command in commands if "-filter_complex" in command)
            filter_value = compose[compose.index("-filter_complex") + 1]
            self.assertIn("xstack=inputs=8", filter_value)
            self.assertFalse(any(path.exists() for path in root.glob(".video-frame-*.png")))

    def test_corrupt_video_is_skipped_and_next_video_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.make_media(root, ["broken.mp4", "healthy.mp4"])
            builder = QuickThumbnailBuilder()
            commands: list[list[str]] = []

            def fake_run(command: list[str]) -> str:
                commands.append(command)
                if command[0] == "ffprobe" and "broken.mp4" in command[-1]:
                    raise QuickModeError("moov atom not found")
                if command[0] == "ffprobe":
                    return "30"
                Path(command[-1]).write_bytes(b"png")
                return ""

            builder._run = fake_run  # type: ignore[method-assign]
            details = builder.build(root, root / "result.png")

            self.assertTrue((root / "result.png").exists())
            self.assertEqual(details["video_frames_used"], 8)
            self.assertEqual(details["skipped_media"][0]["name"], "broken.mp4")
            self.assertTrue(
                any("healthy.mp4" in " ".join(command) for command in commands if "-i" in command)
            )

    def test_no_visual_media_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.make_media(root, ["document.pdf"])
            with self.assertRaises(QuickModeError):
                QuickThumbnailBuilder().build(root, root / "result.png")

    def test_quick_folder_and_caption_are_deterministic(self) -> None:
        self.assertEqual(quick_folder_name(Path("/tmp/My Folder!.json")), "my-folder")
        self.assertEqual(
            quick_storage_caption("my-folder", 2026),
            "my-folder\n#ModeCepat #2026",
        )

    def test_visual_media_ignores_generated_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.make_media(
                root,
                [
                    "photo.jpg",
                    "photo_thumb.jpg",
                    ".video-contact-sheet-1.png",
                    ".video-frame-1.png",
                    "clip.mp4",
                ],
            )
            photos, videos = visual_media(root)
            self.assertEqual([path.name for path in photos], ["photo.jpg"])
            self.assertEqual([path.name for path in videos], ["clip.mp4"])

    def test_scan_classifies_json_only_and_incomplete_media(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            stage = workspace / "quickmode" / "json-job"
            stage.mkdir(parents=True)
            (stage / "export.json").write_text(
                '{"messages":[{"id":1,"type":"photo","file":"a.jpg"},'
                '{"id":2,"type":"video","file":"b.mp4"}]}',
                encoding="utf-8",
            )
            item = scan_quick_stages(workspace, worker="remote-1")[0]
            self.assertEqual(item["phase"], "downloading")
            self.assertEqual(item["expected_media_count"], 2)
            self.assertEqual(item["actual_media_count"], 0)
            media = stage / "export"
            media.mkdir()
            (media / "a.jpg").write_bytes(b"photo")
            item = scan_quick_stages(workspace, worker="remote-1")[0]
            self.assertEqual(item["phase"], "downloading")
            self.assertEqual(item["actual_media_count"], 1)

    def test_scan_archive_and_png_is_upload_only_without_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            stage = workspace / "quickmode" / "upload-job"
            stage.mkdir(parents=True)
            (stage / "upload.7z.001").write_bytes(b"archive")
            (stage / "upload.png").write_bytes(b"png")
            item = scan_quick_stages(workspace, worker="local")[0]
            self.assertEqual(item["phase"], "uploading")
            self.assertFalse(item["json_present"])
            self.assertEqual(item["archive_parts"], 1)

    def test_scan_does_not_return_manifest_secrets_or_tdl_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            stage = workspace / "quickmode" / "safe-job"
            (stage / ".tdl" / "export-home" / ".tdl").mkdir(parents=True)
            (stage / "quickmode.json").write_text(
                '{"profile":"default","compress_password":"do-not-return",'
                '"quick_operation_id":"op-1","phase":"uploading"}',
                encoding="utf-8",
            )
            item = scan_quick_stages(workspace)[0]
            self.assertNotIn("compress_password", item)
            self.assertNotIn("quickmode.json", str(item))
            self.assertTrue(item["tdl_export_present"])

    def test_legacy_stage_is_migrated_to_visible_quickmode_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            legacy = workspace / ".tme3bot-quick" / "old-job"
            legacy.mkdir(parents=True)
            (legacy / "quickmode.json").write_text('{"phase":"uploading"}', encoding="utf-8")
            (legacy / "batch.7z.001").write_bytes(b"archive")

            target = migrate_legacy_quick_stage(workspace, "old-job")

            self.assertEqual(target, quick_stage_root(workspace, "old-job"))
            self.assertTrue((workspace / "quickmode" / "old-job" / "batch.7z.001").exists())
            self.assertFalse(legacy.exists())

    def test_retained_export_json_rebuilds_quick_manifest_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stage = Path(temp_dir) / "workspace" / "quickmode" / "job-1"
            stage.mkdir(parents=True)
            export_json = stage / "label_source.json"
            export_json.write_text(
                '{"messages":[{"id":100,"type":"photo","file":"a.jpg"}],'
                '"tme3bot":{"chat_ref":"@source","label":"label"}}',
                encoding="utf-8",
            )
            executor = WorkerJobExecutor(
                SimpleNamespace(), SimpleNamespace(), SimpleNamespace()
            )

            manifest = executor._hydrate_quick_manifest_from_stage(stage, {})

            self.assertEqual(manifest["export_json_name"], "label_source.json")
            self.assertEqual(manifest["folder_name"], "label_source")
            self.assertTrue(manifest["export_json_retained"])
            self.assertEqual(manifest["export_result"]["chat_ref"], "@source")
            self.assertEqual(manifest["stats"]["media_count"], 1)


class ExportMilestoneTests(unittest.TestCase):
    def test_export_publishes_json_ready_milestone_before_post_export_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export_path = root / "exports" / "batch.json"
            export_path.parent.mkdir(parents=True)
            export_path.write_text('{"messages":[{"id":1,"type":"text"}]}', encoding="utf-8")

            class Publisher:
                def __init__(self):
                    self.events = []

                def emit(self, *args, **kwargs):
                    self.events.append({"event_type": args[2], **kwargs})

            class ExportService:
                calls = []

                def export_from_url(self, url, **kwargs):
                    self.calls.append((url, kwargs))
                    return ExportJobResult(
                        status="exported",
                        chat_ref="@source",
                        requested_label=None,
                        export_path=export_path,
                        start_id=1,
                        latest_id=1,
                        exported_count=1,
                        has_media=False,
                        warmup_required=False,
                    )

            runtime = SimpleNamespace(
                export_service=ExportService(),
                export_operation_lock=threading.RLock(),
                export_tdl_client=SimpleNamespace(output_callback=None, progress_callback=None),
            )
            profiles = SimpleNamespace(runtime=lambda profile: runtime)
            publisher = Publisher()
            executor = WorkerJobExecutor(SimpleNamespace(), profiles, publisher)

            executor._export(
                {
                    "job_id": "export-job",
                    "profile": "default",
                    "payload": {"url": "https://t.me/c/1/2"},
                }
            )

        milestone = next(event for event in publisher.events if event["event_type"] == "export.json_ready")
        self.assertEqual(milestone["progress"]["phase"], "json_ready")
        self.assertEqual(milestone["result"]["json_name"], "batch.json")

    def test_export_retry_passes_message_id_range_to_export_service(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export_path = root / "exports" / "batch.json"
            export_path.parent.mkdir(parents=True)
            export_path.write_text('{"messages":[{"id":500,"type":"text"}]}', encoding="utf-8")

            class Publisher:
                def emit(self, *args, **kwargs):
                    del args, kwargs

            class ExportService:
                def __init__(self):
                    self.calls = []

                def export_from_url(self, url, **kwargs):
                    self.calls.append((url, kwargs))
                    return ExportJobResult(
                        status="exported",
                        chat_ref="@source",
                        requested_label=None,
                        export_path=export_path,
                        start_id=100,
                        latest_id=500,
                        exported_count=1,
                        has_media=False,
                        warmup_required=False,
                        end_id=500,
                    )

            export_service = ExportService()
            runtime = SimpleNamespace(
                export_service=export_service,
                export_operation_lock=threading.RLock(),
                export_tdl_client=SimpleNamespace(output_callback=None, progress_callback=None),
            )
            profiles = SimpleNamespace(runtime=lambda profile: runtime)
            executor = WorkerJobExecutor(SimpleNamespace(), profiles, Publisher())

            executor._export(
                {
                    "job_id": "retry-export-job",
                    "profile": "default",
                    "payload": {
                        "url": "https://t.me/c/1/100",
                        "export_retry": {"start_id": 100, "end_id": 500},
                    },
                }
            )

        self.assertEqual(export_service.calls[0][1]["export_start_id"], 100)
        self.assertEqual(export_service.calls[0][1]["export_end_id"], 500)


class QuickPipelineTests(unittest.TestCase):
    def test_export_entrypoint_honors_thumbnail_phase_without_calling_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            stage = workspace / "quickmode" / "stage-thumbnail"
            media = stage / "batch"
            media.mkdir(parents=True)
            (media / "photo.jpg").write_bytes(b"photo")
            (stage / "quickmode.json").write_text(
                '{"version":2,"stage_job_id":"stage-thumbnail",'
                '"quick_operation_id":"operation-thumbnail",'
                '"folder_name":"batch","phase":"thumbnailing"}',
                encoding="utf-8",
            )

            class Publisher:
                def emit(self, *args, **kwargs):
                    del args, kwargs

            class ExportService:
                def export_from_url(self, *args, **kwargs):
                    raise AssertionError("Thumbnail recovery must not export JSON again")

            runtime = SimpleNamespace(
                config=SimpleNamespace(),
                export_service=ExportService(),
            )
            profiles = SimpleNamespace(runtime=lambda profile: runtime)
            executor = WorkerJobExecutor(
                SimpleNamespace(
                    utility_workspace_root=workspace,
                    backup_node_name="local",
                ),
                profiles,
                Publisher(),
            )
            observed: dict[str, object] = {}

            def fake_pipeline(command, runtime_value, export_result, stats, reporter, **kwargs):
                del command, runtime_value, export_result, stats, reporter
                observed.update(kwargs)
                return {"quick_mode_status": "phase_completed"}

            command = {
                "job_id": "retry-thumbnail",
                "kind": "export",
                "profile": "default",
                "worker": "local",
                "payload": {
                    "quick_mode": True,
                    "quick_phase": "thumbnailing",
                    "quick_retry": {
                        "stage_job_id": "stage-thumbnail",
                        "quick_operation_id": "operation-thumbnail",
                        "resume_phase": "thumbnailing",
                        "retry_phase": "thumbnailing",
                        "single_phase": True,
                    },
                },
            }
            with patch.object(executor, "_release_quick_export_lane"), patch.object(
                executor, "_quick_export_pipeline", side_effect=fake_pipeline
            ):
                result = executor._export(command)

            self.assertEqual(result["quick_mode_status"], "phase_completed")
            self.assertEqual(observed["resume_phase"], "thumbnailing")

    def test_targeted_thumbnail_phase_does_not_start_compress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            stage = workspace / "quickmode" / "stage-1"
            media = stage / "batch"
            media.mkdir(parents=True)
            (media / "photo.jpg").write_bytes(b"photo")

            class Publisher:
                def emit(self, *args, **kwargs):
                    del args, kwargs

            class FakeThumbnailBuilder:
                def __init__(self, **kwargs):
                    del kwargs

                def build(self, media_root, output_path):
                    self.media_root = media_root
                    output_path.write_bytes(b"thumbnail")
                    return {"photos_used": 1, "video_contact_sheet": False, "thumbnail_name": output_path.name}

            executor = WorkerJobExecutor(
                SimpleNamespace(utility_workspace_root=workspace, backup_node_name="local"),
                SimpleNamespace(),
                Publisher(),
            )
            command = {
                "job_id": "phase-job",
                "profile": "default",
                "worker": "local",
                "payload": {
                    "quick_mode": True,
                    "quick_retry": {
                        "stage_job_id": "stage-1",
                        "quick_operation_id": "operation-1",
                        "single_phase": True,
                    },
                },
            }
            with patch("tme3bot.worker.executor_quickmode.QuickThumbnailBuilder", FakeThumbnailBuilder), patch(
                "tme3bot.worker.executor_quickmode.UtilityRunner",
                side_effect=AssertionError("compress must not run for thumbnail-only action"),
            ):
                result = executor._quick_export_pipeline(
                    command,
                    SimpleNamespace(),
                    None,
                    {"media_count": 1, "photo_count": 1, "video_count": 0},
                    ProgressReporter(Publisher(), "phase-job"),
                    stage_root=stage,
                    manifest={
                        "version": 2,
                        "stage_job_id": "stage-1",
                        "quick_operation_id": "operation-1",
                        "folder_name": "batch",
                    },
                    resume_phase="thumbnailing",
                )

            self.assertEqual(result["quick_phase"], "thumbnailing")
            self.assertTrue((stage / "batch.png").exists())
            self.assertFalse(list(stage.glob("*.7z*")))
            self.assertTrue(stage.exists())

    def test_targeted_upload_phase_does_not_cleanup_or_reprocess(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            stage = workspace / "quickmode" / "stage-2"
            stage.mkdir(parents=True)
            (stage / "batch.7z.001").write_bytes(b"archive")
            (stage / "batch.png").write_bytes(b"thumbnail")

            class Publisher:
                def emit(self, *args, **kwargs):
                    del args, kwargs

            executor = WorkerJobExecutor(
                SimpleNamespace(utility_workspace_root=workspace, backup_node_name="local"),
                SimpleNamespace(),
                Publisher(),
            )
            executor._storage_upload = lambda command, **kwargs: {"total": 2, "succeeded": 2, "failed": []}
            command = {
                "job_id": "upload-phase-job",
                "profile": "default",
                "worker": "local",
                "actor_user_id": 42,
                "payload": {
                    "quick_mode": True,
                    "quick_retry": {
                        "stage_job_id": "stage-2",
                        "quick_operation_id": "operation-2",
                        "single_phase": True,
                    },
                },
            }
            with patch.object(
                executor,
                "_rclone_upload_files",
                return_value={"destination": "googledrive:backup", "succeeded": 1, "files": ["batch.7z.001"]},
            ):
                result = executor._quick_export_pipeline(
                    command,
                    SimpleNamespace(),
                    None,
                    {},
                    ProgressReporter(Publisher(), "upload-phase-job"),
                    stage_root=stage,
                    manifest={
                        "version": 2,
                        "stage_job_id": "stage-2",
                        "quick_operation_id": "operation-2",
                        "folder_name": "batch",
                    },
                    resume_phase="uploading",
                )

            self.assertEqual(result["quick_phase"], "uploading")
            self.assertEqual(result["uploaded_count"], 2)
            self.assertTrue(stage.exists())

    def test_quick_cancel_is_best_effort_when_some_runtimes_are_already_gone(self):
        calls: list[str] = []

        class Client:
            def __init__(self, name: str, result: bool = False, error: bool = False):
                self.name = name
                self.result = result
                self.error = error

            def interrupt_current(self):
                calls.append(self.name)
                if self.error:
                    raise RuntimeError(f"{self.name} already stopped")
                return self.result

        class Runner:
            def cancel_current(self):
                calls.append("utility")
                raise RuntimeError("utility already stopped")

        class Profiles:
            def runtime(self, profile):
                return storage_runtime if profile == "storage" else export_runtime

        export_runtime = SimpleNamespace(
            export_tdl_client=Client("export", error=True),
            download_tdl_client=Client("download", result=True),
        )
        storage_runtime = SimpleNamespace(export_tdl_client=Client("storage", error=True))
        config = SimpleNamespace(worker_storage_profile="storage", backup_node_name="local")
        executor = WorkerJobExecutor(config, Profiles(), SimpleNamespace())
        executor._active["quick-cancel"] = ("default", "export")
        executor._quick_active.add("quick-cancel")
        executor._quick_thumbnail_builders["quick-cancel"] = Runner()
        executor._utility_runners["quick-cancel"] = Runner()

        self.assertTrue(executor.cancel("quick-cancel"))
        self.assertEqual(calls, ["export", "download", "storage", "utility", "utility"])
        self.assertIn("quick-cancel", executor._cancel_requested)

    def test_pipeline_passes_compress_settings_uploads_both_files_and_cleans_stage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            pending = root / "exports" / "pending"
            processing = root / "exports" / "processing"
            pending.mkdir(parents=True)
            processing.mkdir(parents=True)
            export_json = pending / "batch.json"
            export_json.write_text('{"messages":[]}', encoding="utf-8")
            storage_session = root / "storage.tdl"
            storage_session.write_text("session", encoding="utf-8")

            class Publisher:
                def __init__(self):
                    self.events = []

                def emit(self, *args, **kwargs):
                    self.events.append((args, kwargs))

                def forget(self, job_id):
                    del job_id

            class DownloadService:
                def download_export_to(self, export_path, download_dir, **kwargs):
                    self.path = export_path
                    self.settings = kwargs
                    download_dir.mkdir(parents=True, exist_ok=True)
                    (download_dir / "photo.jpg").write_bytes(b"photo")
                    export_path.unlink()
                    return DownloadedJsonResult(
                        json_path=export_path,
                        download_dir=download_dir,
                        status="success_deleted",
                    )

            class UploadClient:
                def __init__(self):
                    self.calls = []
                    self.output_callback = None
                    self.progress_callback = None

                def upload(
                    self,
                    path,
                    channel,
                    caption,
                    resolve_after_id=None,
                    status_callback=None,
                    as_photo=False,
                ):
                    self.calls.append(
                        {
                            "path": path,
                            "channel": channel,
                            "caption": caption,
                            "resolve_after_id": resolve_after_id,
                            "as_photo": as_photo,
                        }
                    )
                    return SimpleNamespace(message_id=100 + len(self.calls))

            publisher = Publisher()
            download_service = DownloadService()
            upload_client = UploadClient()
            runtime_config = SimpleNamespace(
                tdl_export_storage=str(storage_session),
                storage_channel_ref="-100123",
                storage_channel_id=-100123,
                export_processing_dir=processing,
            )
            export_client = SimpleNamespace(
                output_callback=None,
                progress_callback=None,
                interrupt_current=lambda: False,
            )
            download_client = SimpleNamespace(
                output_callback=None,
                progress_callback=None,
                interrupt_current=lambda: False,
            )
            export_runtime = SimpleNamespace(
                config=runtime_config,
                download_progress=DownloadProgressTracker(),
                download_service=download_service,
                download_tdl_client=download_client,
                export_tdl_client=export_client,
                export_operation_lock=threading.RLock(),
                download_operation_lock=threading.RLock(),
            )
            storage_runtime = SimpleNamespace(
                config=runtime_config,
                export_tdl_client=upload_client,
                export_operation_lock=threading.RLock(),
            )

            class Profiles:
                def list_profiles(self):
                    return ["default", "storage"]

                def runtime(self, profile):
                    return storage_runtime if profile == "storage" else export_runtime

            config = SimpleNamespace(
                utility_workspace_root=workspace,
                backup_node_name="local",
                worker_storage_profile="storage",
            )
            executor = WorkerJobExecutor(config, Profiles(), publisher)
            export_result = ExportJobResult(
                status="exported",
                chat_ref="@source",
                requested_label=None,
                export_path=export_json,
                start_id=1,
                latest_id=2,
                exported_count=2,
                has_media=True,
                warmup_required=False,
            )
            command = {
                "job_id": "quick-job",
                "profile": "default",
                "worker": "local",
                "actor_user_id": 42,
                "payload": {
                    "quick_mode": True,
                    "quick_settings": {
                        "compress_size": "55m",
                        "compress_password": "snapshot-secret",
                        "rclone_destination": "googledrive:backup",
                    },
                },
            }

            class FakeThumbnailBuilder:
                def __init__(self, **kwargs):
                    del kwargs

                def build(self, media_root, output_path):
                    self.media_root = media_root
                    output_path.write_bytes(b"thumbnail")
                    return {"photos_used": 1, "video_contact_sheet": False, "thumbnail_name": output_path.name}

                def cancel_current(self):
                    return False

            class FakeUtilityRunner:
                instances = []

                def __init__(self, *args, **kwargs):
                    del args, kwargs
                    self.settings = None
                    self.__class__.instances.append(self)

                def run(self, utility, folders, settings=None):
                    self.settings = settings
                    stage = Path(folders[0])
                    folder = next(path for path in stage.iterdir() if path.is_dir())
                    (stage / f"{folder.name}.7z.001").write_bytes(b"archive")
                    return UtilityResult(utility, [str(stage)], {}, [], {})

                def cancel_current(self):
                    return False

            class FakeRcloneRunner:
                instances = []

                def __init__(self, **kwargs):
                    self.kwargs = kwargs
                    self.__class__.instances.append(self)

                def copy_files(self, files, destination, config_path, *, workspace_root, config_root=None):
                    self.files = list(files)
                    self.destination = destination
                    self.config_path = config_path
                    self.workspace_root = workspace_root
                    self.config_root = config_root
                    return {
                        "destination": destination,
                        "total": len(self.files),
                        "succeeded": len(self.files),
                        "files": [path.name for path in self.files],
                    }

                def cancel_current(self):
                    return False

            with patch("tme3bot.worker.executor_quickmode.QuickThumbnailBuilder", FakeThumbnailBuilder), patch(
                "tme3bot.worker.executor_quickmode.UtilityRunner", FakeUtilityRunner
            ), patch("tme3bot.worker.executor_storage.RcloneRunner", FakeRcloneRunner), patch(
                "tme3bot.worker.executor_quickmode.quick_year", return_value=2026
            ):
                result = executor._quick_export_pipeline(
                    command,
                    export_runtime,
                    export_result,
                    {"media_count": 1, "photo_count": 1, "video_count": 0},
                    ProgressReporter(publisher, "quick-job"),
                )

            self.assertEqual(FakeUtilityRunner.instances[0].settings["compress_size"], "55m")
            self.assertEqual(FakeUtilityRunner.instances[0].settings["compress_password"], "snapshot-secret")
            self.assertEqual(
                [path.name for path in FakeRcloneRunner.instances[0].files],
                ["batch.7z.001"],
            )
            self.assertEqual(FakeRcloneRunner.instances[0].destination, "googledrive:backup")
            self.assertEqual(len(upload_client.calls), 2)
            self.assertEqual(
                {call["path"].name for call in upload_client.calls},
                {"batch.7z.001", "batch.png"},
            )
            self.assertTrue(
                all(call["caption"] == "batch\n#ModeCepat #2026" for call in upload_client.calls)
            )
            self.assertEqual(
                {call["path"].name: call["as_photo"] for call in upload_client.calls},
                {"batch.7z.001": False, "batch.png": True},
            )
            self.assertEqual(upload_client.calls[0]["resolve_after_id"], None)
            self.assertEqual(upload_client.calls[1]["resolve_after_id"], 101)
            self.assertEqual(result["storage_folder"], "ModeCepat/2026")
            self.assertTrue(result["thumbnail_uploaded_as_photo"])
            self.assertTrue(result["staging_cleaned"])
            self.assertFalse((workspace / ".tme3bot-quick" / "quick-job").exists())
