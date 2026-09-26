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

    def test_reset_for_retry_reuses_id_and_preserves_event_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            store.create(self.make_job())
            store.append_event(JobEvent("job-1", 1, JobStatus.DISPATCHED, "dispatched"))
            store.append_event(JobEvent("job-1", 2, JobStatus.RUNNING, "started"))
            store.append_event(JobEvent("job-1", 3, JobStatus.FAILED, "failed"))
            notification = store.create_telegram_notification("job-1", 7, 7, "default")
            store.update_telegram_notification(
                notification["id"],
                {"status": "terminal", "terminal_notified_at": "2026-01-01T00:00:00+00:00"},
            )

            retry = store.reset_for_retry("job-1", {"url": "https://t.me/c/1/2", "retry": True})

            self.assertEqual(retry.id, "job-1")
            self.assertEqual(retry.status, JobStatus.QUEUED)
            self.assertEqual(retry.payload["retry"], True)
            self.assertEqual(len(store.events("job-1")), 3)
            self.assertEqual(store.pending_telegram_notifications()[0]["job_id"], "job-1")

    def test_tts_delivery_outbox_survives_restart_and_hides_artifact_ref_from_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.db"
            store = SqliteJobRepository(path)
            job = Job(
                id="tts-job-1",
                kind="tts",
                profile="default",
                actor_user_id=7,
                worker="tts-ready",
                status=JobStatus.QUEUED,
                payload={"title": "Judul", "character_count": 16},
            )
            store.create(job)
            store.append_event(JobEvent(job.id, 1, JobStatus.DISPATCHED, "dispatched"))
            store.append_event(JobEvent(job.id, 2, JobStatus.RUNNING, "started"))
            artifact_ref = "a" * 48
            store.create_tts_deliveries(
                job.id,
                job.worker,
                "Judul",
                [{"artifact_ref": artifact_ref, "part_index": 1, "total_parts": 1, "byte_size": 512}],
            )

            reopened = SqliteJobRepository(path)
            claimed = reopened.claim_tts_deliveries(limit=1)
            self.assertEqual(len(claimed), 1)
            self.assertEqual(claimed[0]["job_id"], job.id)
            self.assertNotIn("artifact_ref", claimed[0])
            self.assertEqual(reopened.get_tts_delivery(claimed[0]["id"])["artifact_ref"], artifact_ref)
            reopened.complete_tts_delivery(claimed[0]["id"], delivered=True)
            replacement_ref = "b" * 48
            reopened.create_tts_deliveries(
                job.id,
                job.worker,
                "Judul",
                [{"artifact_ref": replacement_ref, "part_index": 1, "total_parts": 1, "byte_size": 512}],
            )
            confirmed = reopened.get_tts_delivery(claimed[0]["id"])
            self.assertEqual(confirmed["status"], "delivered")
            self.assertEqual(confirmed["artifact_ref"], artifact_ref)
            self.assertEqual(
                reopened.tts_delivery_summary(job.id),
                {"total_parts": 1, "delivered_parts": 1, "cancelled_parts": 0},
            )

    def test_tts_telegram_readiness_expires_after_service_stops_heartbeating(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            self.assertFalse(store.tts_telegram_ready())
            store.set_tts_telegram_ready(True)
            self.assertTrue(store.tts_telegram_ready())

    def test_tts_delivery_retry_keeps_parts_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            job = Job(
                id="tts-order-1",
                kind="tts",
                profile="default",
                actor_user_id=7,
                worker="tts-ready",
                status=JobStatus.QUEUED,
                payload={"title": "Judul", "character_count": 16},
            )
            store.create(job)
            store.append_event(JobEvent(job.id, 1, JobStatus.DISPATCHED, "dispatched"))
            store.append_event(JobEvent(job.id, 2, JobStatus.RUNNING, "started"))
            store.create_tts_deliveries(
                job.id,
                job.worker,
                "Judul",
                [
                    {"artifact_ref": "a" * 48, "part_index": 1, "total_parts": 2, "byte_size": 512},
                    {"artifact_ref": "b" * 48, "part_index": 2, "total_parts": 2, "byte_size": 512},
                ],
            )
            first = store.claim_tts_deliveries(limit=1)[0]
            store.complete_tts_delivery(first["id"], delivered=False)
            self.assertEqual(store.claim_tts_deliveries(limit=1), [])

            with store._db() as db:
                db.execute(
                    "UPDATE job_tts_deliveries SET available_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), first["id"]),
                )
            retried = store.claim_tts_deliveries(limit=1)
            self.assertEqual(retried[0]["part_index"], 1)
            store.complete_tts_delivery(retried[0]["id"], delivered=True)
            second = store.claim_tts_deliveries(limit=1)
            self.assertEqual(second[0]["part_index"], 2)

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

    def test_progress_merge_preserves_lifecycle_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            store.create(self.make_job())
            store.append_event(
                JobEvent(
                    "job-1",
                    1,
                    JobStatus.RUNNING,
                    "started",
                    {"phase": "starting", "started_at": "2026-09-17T01:00:00+00:00"},
                )
            )
            current, updated = store.update_progress_snapshot(
                JobEvent(
                    "job-1",
                    2,
                    JobStatus.RUNNING,
                    "progress.snapshot",
                    {"phase": "downloading"},
                )
            )
            self.assertTrue(updated)
            self.assertEqual(current.progress["started_at"], "2026-09-17T01:00:00+00:00")

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

    def test_quick_mode_filter_only_returns_quick_export_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            store.create(self.make_job())
            store.create(
                Job(
                    id="job-quick",
                    kind="export",
                    profile="default",
                    actor_user_id=7,
                    worker="local",
                    status=JobStatus.QUEUED,
                    payload={"url": "https://t.me/c/1/3", "quick_mode": True},
                )
            )
            self.assertEqual([job.id for job in store.list(quick_mode=True)], ["job-quick"])
            self.assertEqual([job.id for job in store.list(quick_mode=False)], ["job-1"])
            self.assertEqual(store.count(kind="export", quick_mode=True), 1)

    def test_resumed_quick_jobs_receive_monotonic_fifo_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            now = datetime.now(timezone.utc)
            first = self.make_job()
            first = Job(**{**first.__dict__, "payload": {"quick_mode": True}})
            second = Job(
                id="job-2",
                kind="export",
                profile="archive",
                actor_user_id=7,
                worker="local",
                status=JobStatus.QUEUED,
                payload={"quick_mode": True},
            )
            for job in (first, second):
                store.create(job)
                store.save_execution_plan(
                    job.id,
                    {"resource_keys": [f"stage:{job.id}"], "queue_group": "quick", "lane": "quick"},
                    job.payload,
                )
                store.append_event(JobEvent(job.id, 1, JobStatus.PAUSED, "paused", created_at=now))
            store.append_event(JobEvent(first.id, 2, JobStatus.QUEUED, "resumed", created_at=now))
            store.append_event(JobEvent(second.id, 2, JobStatus.QUEUED, "resumed", created_at=now))

            self.assertLess(
                store.execution_plan(first.id)["queued_at"],
                store.execution_plan(second.id)["queued_at"],
            )

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
