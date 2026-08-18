import unittest

from tme3bot.frontend.telegram.job_notifications import (
    JobNotificationRegistry,
    format_job_status,
)


class JobNotificationFormatterTests(unittest.TestCase):
    def test_registry_keeps_one_message_per_job(self) -> None:
        registry = JobNotificationRegistry()
        message = object()
        registry.set("job-1", message)
        self.assertIs(registry.get("job-1"), message)
        self.assertIs(registry.pop("job-1"), message)
        self.assertIsNone(registry.get("job-1"))

    def test_download_message_contains_batch_item_transfer_and_counters(self) -> None:
        text = format_job_status(
            {
                "kind": "download",
                "status": "running",
                "id": "job-1234567890",
                "profile": "default",
                "worker": "local",
                "progress": {
                    "batch": {"name": "archive.json", "index": 1, "total": 2},
                    "item": {"name": "video.mp4", "index": 22, "total": 50},
                    "overall": {"current": 1, "total": 2, "percent": 50},
                    "transfer": {"speed_bps": 1048576, "eta_seconds": 12},
                    "counters": {"succeeded": 3, "failed": 1, "skipped": 2},
                },
            }
        )

        self.assertIn("JSON: archive.json (1/2)", text)
        self.assertIn("File: video.mp4 (22/50)", text)
        self.assertIn("Speed: 1.0 MB/dtk", text)
        self.assertIn("ETA: 12 dtk", text)
        self.assertIn("Berhasil: 3", text)
        self.assertNotIn("{'", text)

    def test_terminal_report_does_not_render_missing_fields_as_zero(self) -> None:
        text = format_job_status(
            {
                "kind": "utility",
                "status": "succeeded",
                "result": {"value": {"groups_created": 4}},
            }
        )

        self.assertIn("Group dibuat: 4", text)
        self.assertNotIn("Message: 0", text)
        self.assertNotIn("[object", text)


if __name__ == "__main__":
    unittest.main()
