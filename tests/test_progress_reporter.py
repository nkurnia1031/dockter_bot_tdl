import unittest

from tme3bot.progress_reporter import ProgressReporter
from tme3bot.tdl_output import parse_tdl_progress_line


class FakePublisher:
    def __init__(self):
        self.events = []

    def emit(self, job_id, status, event_type, **values):
        self.events.append(
            {
                "job_id": job_id,
                "status": status,
                "event_type": event_type,
                **values,
            }
        )


class ProgressReporterTests(unittest.TestCase):
    def test_telemetry_is_transient_and_throttled_by_percent(self):
        publisher = FakePublisher()
        reporter = ProgressReporter(
            publisher, "job-1", min_interval_seconds=60, min_percent_delta=1
        )
        reporter.report(
            phase="uploading",
            message="a.7z",
            item={"percent": 10},
        )
        reporter.report(
            phase="uploading",
            message="a.7z",
            item={"percent": 10.5},
        )
        reporter.report(
            phase="uploading",
            message="a.7z",
            item={"percent": 12},
        )

        self.assertEqual(len(publisher.events), 2)
        self.assertTrue(publisher.events[0]["transient"])
        self.assertEqual(publisher.events[-1]["progress"]["item"]["percent"], 12)

    def test_transfer_uses_numeric_speed_and_eta(self):
        reporter = ProgressReporter(FakePublisher(), "job-1")
        parsed = parse_tdl_progress_line(
            "Upload File:1 -> a.7z ... 50% [50 MB in 10s; ~ETA: 10s; 5 MB/s]",
            "stdout",
        )
        transfer = reporter.tdl_transfer(parsed, total_bytes=100 * 1024 * 1024)
        self.assertEqual(transfer["bytes_current"], 50 * 1024 * 1024)
        self.assertEqual(transfer["speed_bps"], 5 * 1024 * 1024)
        self.assertEqual(transfer["eta_seconds"], 10)


if __name__ == "__main__":
    unittest.main()
