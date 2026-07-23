import tempfile
import unittest
from pathlib import Path

from tme3bot.config import AppConfig
from tme3bot.progress import DownloadProgressTracker
from tme3bot.service import (
    BatchDownloadService,
    ExportService,
    build_telegram_message_url,
)
from tme3bot.state import StateStore
from tme3bot.tdl import ExportResult, parse_tdl_progress_line


class FakeExportTDLClient:
    def __init__(self, result: ExportResult) -> None:
        self.result = result
        self.export_calls: list[tuple[str, int, Path]] = []

    def export_messages(
        self, chat_ref: str, start_id: int, export_path: Path
    ) -> ExportResult:
        self.export_calls.append((chat_ref, start_id, export_path))
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text('{"messages": []}', encoding="utf-8")
        return ExportResult(
            export_path=export_path,
            messages=self.result.messages,
            exported_count=self.result.exported_count,
            max_message_id=self.result.max_message_id,
            has_media=self.result.has_media,
        )


class FakeDownloadTDLClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.download_calls: list[tuple[Path, Path]] = []
        self.download_url_calls: list[tuple[str, Path]] = []

    def download(self, export_path: Path, download_dir: Path) -> None:
        self.download_calls.append((export_path, download_dir))
        if self.fail:
            from tme3bot.tdl import TDLCommandError

            raise TDLCommandError(["tdl", "dl"], 1, "", "download failed")

    def download_url(self, url: str, download_dir: Path) -> None:
        self.download_url_calls.append((url, download_dir))
        download_dir.mkdir(parents=True, exist_ok=True)
        (download_dir / "warmup.tmp").write_text("warmup", encoding="utf-8")


class ServiceTests(unittest.TestCase):
    def make_config(self, root: Path) -> AppConfig:
        return AppConfig(
            bot_token="token",
            profile_root=str(root),
            profiles_root=root / "profiles",
            default_profile="default",
            tme3_host="t.me3",
            download_root=root / "download",
            export_pending_dir=root / "exports" / "pending",
            export_processing_dir=root / "exports" / "processing",
            export_done_dir=root / "exports" / "done",
            export_failed_dir=root / "exports" / "failed",
            state_file=root / "state.json",
            legacy_max_json=root / "max.json",
            tdl_export_user="user1",
            tdl_download_user="root",
            tdl_export_home=root / "user1",
            tdl_download_home=root / "root",
            tdl_export_storage=root / "user1" / ".tdl",
            tdl_download_storage=root / "root" / ".tdl",
            tdl_export_namespace="default",
            tdl_download_namespace="default",
            tdl_export_stall_timeout_seconds=300,
            tdl_download_stall_timeout_seconds=1800,
            temp_root=root / "tmp",
            log_level="INFO",
        )

    def test_input_creates_label_timestamp_chat_export_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            store = StateStore(config.state_file, config.legacy_max_json)
            client = FakeExportTDLClient(
                ExportResult(
                    export_path=root / "ignored.json",
                    messages=[
                        {"id": 9, "type": "document", "file_name": "a.txt"},
                        {
                            "id": 8,
                            "type": "document",
                            "file_name": "cover.jpg",
                            "mime_type": "image/jpeg",
                        },
                    ],
                    exported_count=2,
                    max_message_id=9,
                    has_media=True,
                )
            )
            service = ExportService(config, store, client)

            result = service.export_from_url("https://t.me3/c/@bot/3/1langs")

            self.assertEqual(result.status, "exported")
            self.assertEqual(client.export_calls[0][0:2], ("@bot", 3))
            self.assertTrue(result.export_path.exists())
            self.assertEqual(result.export_path.parent, config.export_pending_dir)
            self.assertRegex(
                result.export_path.name, r"^1langs_\d{8}T\d{6}Z_bot\.json$"
            )
            self.assertEqual(store.get_source("@bot").last_id, 9)
            self.assertEqual(store.get_source("@bot").label, "1langs")
            self.assertFalse(store.get_source("@bot").warmup_done)
            self.assertEqual(store.get_source("@bot").warmup_url, "https://t.me/bot/8")

    def test_builds_correct_warmup_url_for_private_numeric_chat(self) -> None:
        self.assertEqual(
            build_telegram_message_url("3954783687", 10315),
            "https://t.me/c/3954783687/10315",
        )
        self.assertEqual(
            build_telegram_message_url("-1003954783687", 10315),
            "https://t.me/c/3954783687/10315",
        )
        self.assertEqual(build_telegram_message_url("@tdl", 1), "https://t.me/tdl/1")

    def test_input_without_label_uses_timestamp_chat_filename_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            store = StateStore(config.state_file, config.legacy_max_json)
            client = FakeExportTDLClient(
                ExportResult(
                    export_path=root / "ignored.json",
                    messages=[{"id": 5}],
                    exported_count=1,
                    max_message_id=5,
                    has_media=False,
                )
            )
            service = ExportService(config, store, client)

            result = service.export_from_url("https://t.me3/c/@bot/3")

            self.assertRegex(result.export_path.name, r"^\d{8}T\d{6}Z_bot\.json$")
            self.assertIsNone(store.get_source("@bot").label)
            self.assertTrue(store.get_source("@bot").warmup_done)
            self.assertIsNone(store.get_source("@bot").warmup_url)

    def test_known_chat_uses_global_last_id_but_accepts_new_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            store = StateStore(config.state_file, config.legacy_max_json)
            store.load()
            store.upsert_source("@bot", "saved-label", 20)
            client = FakeExportTDLClient(
                ExportResult(
                    export_path=root / "ignored.json",
                    messages=[{"id": 24}],
                    exported_count=1,
                    max_message_id=24,
                    has_media=False,
                )
            )
            service = ExportService(config, store, client)

            result = service.export_from_url("https://t.me3/c/@bot/3/new-label")

            self.assertEqual(client.export_calls[0][0:2], ("@bot", 21))
            self.assertIsNone(result.warning)
            self.assertRegex(
                result.export_path.name, r"^new-label_\d{8}T\d{6}Z_bot\.json$"
            )
            self.assertEqual(store.get_source("@bot").label, "new-label")
            self.assertEqual(store.get_source("@bot").last_id, 24)

    def test_direct_url_can_override_start_id_without_moving_state_backward(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            store = StateStore(config.state_file, config.legacy_max_json)
            store.upsert_source("4429689667", None, 20)
            client = FakeExportTDLClient(
                ExportResult(
                    export_path=root / "ignored.json",
                    messages=[{"id": 11}],
                    exported_count=1,
                    max_message_id=11,
                    has_media=False,
                )
            )
            service = ExportService(config, store, client)

            result = service.export_from_url(
                "https://t.me/c/4429689667/11", use_url_message_id=True
            )

            self.assertEqual(result.start_id, 11)
            self.assertEqual(result.latest_id, 20)
            self.assertEqual(client.export_calls[0][0:2], ("4429689667", 11))
            self.assertEqual(store.get_source("4429689667").last_id, 20)

    def test_download_warmups_new_chat_before_batch_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            store = StateStore(config.state_file, config.legacy_max_json)
            export_client = FakeExportTDLClient(
                ExportResult(
                    export_path=root / "ignored.json",
                    messages=[{"id": 9, "type": "document"}],
                    exported_count=1,
                    max_message_id=9,
                    has_media=True,
                )
            )
            ExportService(config, store, export_client).export_from_url(
                "https://t.me3/c/@bot/3/1langs"
            )
            download_client = FakeDownloadTDLClient()
            service = BatchDownloadService(config, store, download_client)

            result = service.download_pending_exports()

            self.assertEqual(result.success_count, 1)
            self.assertEqual(
                download_client.download_url_calls[0][0], "https://t.me/bot/9"
            )
            self.assertEqual(
                download_client.download_calls[0][1],
                config.download_root
                / "berlabel"
                / download_client.download_calls[0][0].stem,
            )
            self.assertEqual(list(config.download_root.glob("**/__warmup")), [])
            self.assertTrue(store.get_source("@bot").warmup_done)

    def test_progress_tracker_maps_descending_tdl_message_id_to_forward_media_position(
        self,
    ) -> None:
        tracker = DownloadProgressTracker()
        tracker.start_batch("download", 1)
        tracker.start_json(1, 1, "batch.json", [15562, 15566])

        tracker.update_tdl_progress(
            parse_tdl_progress_line(
                "Up Talent / Alter(3714353316):15566 -> ... done! [48.34 MB in 19.313s, 2.50 MB/s]",
                "stdout",
            )
        )
        self.assertEqual(tracker.snapshot().tdl_fraction_current, 1)
        self.assertEqual(tracker.snapshot().tdl_fraction_total, 2)

        tracker.update_tdl_progress(
            parse_tdl_progress_line(
                "Up Talent / Alter(3714353316):15562 -> ... done! [54.32 MB in 18.005s, 3.02 MB/s]",
                "stdout",
            )
        )
        self.assertEqual(tracker.snapshot().tdl_fraction_current, 2)
        self.assertEqual(tracker.snapshot().tdl_fraction_total, 2)

    def test_download_moves_pending_to_done_and_downloads_each_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            config.export_pending_dir.mkdir(parents=True)
            first = config.export_pending_dir / "first.json"
            second = config.export_pending_dir / "second.json"
            first.write_text("{}", encoding="utf-8")
            second.write_text("{}", encoding="utf-8")
            store = StateStore(config.state_file, config.legacy_max_json)
            client = FakeDownloadTDLClient()
            service = BatchDownloadService(config, store, client)

            result = service.download_pending_exports()

            self.assertEqual(result.moved_count, 2)
            self.assertEqual(result.success_count, 2)
            self.assertEqual(result.failed_count, 0)
            self.assertFalse(first.exists())
            self.assertFalse((config.export_processing_dir / "first.json").exists())
            self.assertFalse((config.export_done_dir / "first.json").exists())
            self.assertEqual(
                client.download_calls[0][1], config.download_root / "biasa" / "first"
            )

    def test_retry_failed_reprocesses_failed_json_and_clear_fail_removes_remaining(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            config.export_failed_dir.mkdir(parents=True)
            failed = config.export_failed_dir / "failed.json"
            failed.write_text("{}", encoding="utf-8")
            store = StateStore(config.state_file, config.legacy_max_json)
            client = FakeDownloadTDLClient()
            service = BatchDownloadService(config, store, client)

            result = service.retry_failed_exports()

            self.assertEqual(result.success_count, 1)
            self.assertFalse(failed.exists())
            self.assertEqual(service.clear_failed_exports(), 0)


if __name__ == "__main__":
    unittest.main()
