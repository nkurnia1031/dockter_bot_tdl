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
from tme3bot.worker.executor import WorkerJobExecutor
from tme3bot.worker.quick_export import (
    QuickModeError,
    QuickThumbnailBuilder,
    migrate_legacy_quick_stage,
    quick_folder_name,
    quick_stage_root,
    quick_storage_caption,
    visual_media,
)


class QuickThumbnailTests(unittest.TestCase):
    def make_media(self, root: Path, names: list[str]) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for name in names:
            (root / name).write_bytes(b"media")

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
            self.assertEqual(sum(command[0] == "ffprobe" for command in commands), 4)
            self.assertEqual(
                sum("tile=4x4" in " ".join(command) for command in commands),
                4,
            )
            compose = next(command for command in commands if "-filter_complex" in command)
            filter_value = compose[compose.index("-filter_complex") + 1]
            self.assertIn("xstack=inputs=8", filter_value)
            self.assertNotIn("804", filter_value)
            self.assertFalse(any(path.exists() for path in root.glob(".video-contact-sheet-*.png")))

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
                ["photo.jpg", "photo_thumb.jpg", ".video-contact-sheet-1.png", "clip.mp4"],
            )
            photos, videos = visual_media(root)
            self.assertEqual([path.name for path in photos], ["photo.jpg"])
            self.assertEqual([path.name for path in videos], ["clip.mp4"])

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
            pending.mkdir(parents=True)
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

            with patch("tme3bot.worker.executor.QuickThumbnailBuilder", FakeThumbnailBuilder), patch(
                "tme3bot.worker.executor.UtilityRunner", FakeUtilityRunner
            ), patch("tme3bot.worker.executor.quick_year", return_value=2026):
                result = executor._quick_export_pipeline(
                    command,
                    export_runtime,
                    export_result,
                    {"media_count": 1, "photo_count": 1, "video_count": 0},
                    ProgressReporter(publisher, "quick-job"),
                )

            self.assertEqual(FakeUtilityRunner.instances[0].settings["compress_size"], "55m")
            self.assertEqual(FakeUtilityRunner.instances[0].settings["compress_password"], "snapshot-secret")
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
