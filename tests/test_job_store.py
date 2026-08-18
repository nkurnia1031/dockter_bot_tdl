import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tme3bot.domain.models import DomainError, Job, JobEvent, JobStatus
from tme3bot.infrastructure.job_store import SqliteJobRepository


class JobStoreTests(unittest.TestCase):
    def make_job(self) -> Job:
        return Job(
            id="job-1",
            kind="export",
            profile="default",
            actor_user_id=7,
            worker="local",
            status=JobStatus.QUEUED,
            payload={"url": "https://t.me/c/1/2"},
        )

    def test_events_are_idempotent_and_persist_job_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            store.create(self.make_job())
            event = JobEvent(
                "job-1",
                1,
                JobStatus.DISPATCHED,
                "dispatched",
                {"worker": "local"},
            )
            first, inserted = store.append_event(event)
            duplicate, inserted_again = store.append_event(event)

            self.assertTrue(inserted)
            self.assertFalse(inserted_again)
            self.assertEqual(first.status, JobStatus.DISPATCHED)
            self.assertEqual(duplicate.status, JobStatus.DISPATCHED)
            self.assertEqual(len(store.events("job-1")), 1)
            self.assertTrue(store.has_active("default"))

            store.append_event(
                JobEvent(
                    "job-1", 2, JobStatus.RUNNING, "started"
                )
            )
            store.append_event(
                JobEvent(
                    "job-1",
                    3,
                    JobStatus.SUCCEEDED,
                    "completed",
                    result={"ok": True},
                )
            )
            self.assertFalse(store.has_active("default"))
            self.assertEqual(store.get("job-1").result, {"ok": True})

    def test_invalid_transition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            store.create(self.make_job())
            store.append_event(
                JobEvent("job-1", 1, JobStatus.FAILED, "failed")
            )
            with self.assertRaises(DomainError):
                store.append_event(
                    JobEvent("job-1", 2, JobStatus.RUNNING, "started")
                )

    def test_transient_progress_keeps_only_latest_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            store.create(self.make_job())
            store.append_event(
                JobEvent("job-1", 1, JobStatus.DISPATCHED, "dispatched")
            )
            store.append_event(JobEvent("job-1", 2, JobStatus.RUNNING, "started"))
            current, updated = store.update_progress_snapshot(
                JobEvent(
                    "job-1",
                    3,
                    JobStatus.RUNNING,
                    "progress.snapshot",
                    {"phase": "uploading", "item": {"percent": 25}},
                )
            )
            stale, stale_updated = store.update_progress_snapshot(
                JobEvent(
                    "job-1",
                    2,
                    JobStatus.RUNNING,
                    "progress.snapshot",
                    {"phase": "uploading", "item": {"percent": 5}},
                )
            )

            self.assertTrue(updated)
            self.assertFalse(stale_updated)
            self.assertEqual(current.progress["item"]["percent"], 25)
            self.assertEqual(stale.progress["item"]["percent"], 25)
            self.assertEqual(len(store.events("job-1")), 2)
            store.append_event(
                JobEvent(
                    "job-1",
                    4,
                    JobStatus.RUNNING,
                    "item_completed",
                    {"phase": "uploading", "item": {"percent": 100}},
                )
            )
            self.assertEqual(len(store.events("job-1")), 3)

    def test_filters_archive_restore_and_purge_terminal_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            store.create(self.make_job())
            store.append_event(JobEvent("job-1", 1, JobStatus.FAILED, "failed"))
            self.assertEqual(
                len(store.list(profile="default", status="failed", archived=False)),
                1,
            )
            archived = store.set_archived("job-1", True)
            self.assertIsNotNone(archived.archived_at)
            self.assertEqual(len(store.list(profile="default", archived=False)), 0)
            self.assertEqual(len(store.list(profile="default", archived=True)), 1)
            store.set_archived("job-1", False)
            store.set_archived("job-1", True)
            self.assertTrue(store.purge("job-1"))

    def test_telegram_notification_is_idempotent_and_terminal_stamp_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            store.create(self.make_job())
            first = store.create_telegram_notification("job-1", 7, 7, "default")
            duplicate = store.create_telegram_notification("job-1", 7, 7, "default")

            self.assertEqual(first["id"], duplicate["id"])
            store.update_telegram_notification(
                first["id"],
                {"status": "terminal", "terminal_notified_at": "2026-01-01T00:00:00+00:00"},
            )
            stable = store.update_telegram_notification(
                first["id"],
                {"terminal_notified_at": "2026-01-02T00:00:00+00:00"},
            )
            self.assertEqual(stable["terminal_notified_at"], "2026-01-01T00:00:00+00:00")
            self.assertEqual(len(store.pending_telegram_notifications()), 0)


if __name__ == "__main__":
    unittest.main()
