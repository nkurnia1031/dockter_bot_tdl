import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tme3bot.infrastructure.activity_journal import ActivityJournalStore


class ActivityJournalTests(unittest.TestCase):
    def test_pagination_filters_and_restart_are_stable_and_metadata_only(self):
        with tempfile.TemporaryDirectory() as temp:
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            store = ActivityJournalStore(Path(temp) / "app.db", clock=lambda: now)
            first_id = str(uuid.uuid4())
            second_id = str(uuid.uuid4())
            operation_id = str(uuid.uuid4())
            store.record(
                occurred_at=now.isoformat(),
                request_id=first_id,
                method="GET",
                route="/api/v1/me",
                status_code=200,
                duration_ms=12,
                actor_user_id=42,
                profile="default",
            )
            now += timedelta(seconds=1)
            store.record(
                occurred_at=now.isoformat(),
                request_id=second_id,
                method="GET",
                route="/api/v1/workers/{name}/tts/health",
                status_code=503,
                duration_ms=41,
                actor_user_id=42,
                profile="default",
                worker="local",
                operation_id=operation_id,
                error_code="WORKER_UNAVAILABLE",
            )

            restarted = ActivityJournalStore(Path(temp) / "app.db", clock=lambda: now)
            first_page = restarted.list_entries(limit=1)
            self.assertEqual(first_page["items"][0]["request_id"], second_id)
            self.assertTrue(first_page["next_cursor"])
            self.assertEqual(first_page["items"][0]["error_code"], "WORKER_UNAVAILABLE")
            self.assertNotIn("headers", first_page["items"][0])
            self.assertNotIn("body", first_page["items"][0])

            next_page = restarted.list_entries(limit=1, cursor=first_page["next_cursor"])
            self.assertEqual([item["request_id"] for item in next_page["items"]], [first_id])
            filtered = restarted.list_entries(status_code=503, worker="local")
            self.assertEqual([item["request_id"] for item in filtered["items"]], [second_id])
            metadata_filtered = restarted.list_entries(
                actor_user_id=42,
                profile="default",
                request_id=second_id,
                operation_id=operation_id,
                since="2026-01-01T00:00:01+00:00",
                until="2026-01-01T00:00:02+00:00",
            )
            self.assertEqual(
                [item["operation_id"] for item in metadata_filtered["items"]],
                [operation_id],
            )

    def test_expired_entries_are_removed_automatically_after_ninety_days(self):
        with tempfile.TemporaryDirectory() as temp:
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            store = ActivityJournalStore(Path(temp) / "app.db", clock=lambda: now)
            store.record(
                occurred_at=now.isoformat(),
                request_id=str(uuid.uuid4()),
                method="GET",
                route="/api/v1/me",
                status_code=200,
                duration_ms=1,
            )
            now += timedelta(days=91)
            store.record(
                occurred_at=now.isoformat(),
                request_id=str(uuid.uuid4()),
                method="GET",
                route="/api/v1/workers",
                status_code=200,
                duration_ms=1,
            )

            result = store.list_entries()
            self.assertEqual(len(result["items"]), 1)
            self.assertEqual(result["items"][0]["route"], "/api/v1/workers")


if __name__ == "__main__":
    unittest.main()
