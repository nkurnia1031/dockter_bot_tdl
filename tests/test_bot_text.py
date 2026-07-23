import unittest
from pathlib import Path

from tme3bot.bot_text import (
    compact_text,
    format_download_progress,
    format_export_result,
    progress_bar,
)
from tme3bot.progress import DownloadProgressSnapshot
from tme3bot.service import ExportJobResult


class BotTextTests(unittest.TestCase):
    def test_formats_export_result_without_telegram_dependency(self) -> None:
        result = ExportJobResult(
            status="exported",
            chat_ref="@bot",
            requested_label="sample",
            export_path=Path("/data/exports/sample.json"),
            start_id=11,
            latest_id=20,
            exported_count=4,
            has_media=True,
            warmup_required=False,
        )

        text = format_export_result(result, "default")

        self.assertIn("Profile: default", text)
        self.assertIn("Mulai ID: 11", text)
        self.assertIn("Last ID: 20", text)

    def test_formats_compact_realtime_download_snapshot(self) -> None:
        snapshot = DownloadProgressSnapshot(
            active=True,
            phase="downloading",
            mode="download",
            started_at=None,
            updated_at=None,
            total_json=2,
            current_json_index=1,
            current_json_name="first.json",
            current_media_total=7,
            success_count=0,
            failed_count=0,
            last_error=None,
            tdl_line="Chat(1):7 -> file.mp4",
            tdl_percent=50.0,
            tdl_speed="2.00 MB/s",
            tdl_fraction_current=3,
            tdl_fraction_total=7,
            tdl_file_name="file.mp4",
        )

        text = format_download_progress(snapshot, queue_size=1, profile_name="default")

        self.assertIn("Batch JSON: 1/2", text)
        self.assertIn("Media JSON: 3/7", text)
        self.assertIn("50.0% [#####-----]", text)
        self.assertIn("2.00 MB/s", text)

    def test_text_helpers_clamp_and_compact(self) -> None:
        self.assertEqual(progress_bar(120), "[##########]")
        self.assertEqual(compact_text("one   two   three", 11), "one two ...")


if __name__ == "__main__":
    unittest.main()
