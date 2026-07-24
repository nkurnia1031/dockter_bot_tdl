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


if __name__ == "__main__":
    unittest.main()
