import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tme3bot.infrastructure.activity_journal import ActivityJournalStore


class ActivityJournalTests(unittest.TestCase):
    def test_existing_request_journal_schema_migrates_for_operation_events(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "app.db"
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    """CREATE TABLE api_activity (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        occurred_at TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        method TEXT NOT NULL,
                        route TEXT NOT NULL,
                        status_code INTEGER NOT NULL,
                        duration_ms INTEGER NOT NULL,
                        actor_user_id INTEGER,
                        profile TEXT NOT NULL DEFAULT '',
                        worker TEXT NOT NULL DEFAULT '',
                        operation_id TEXT NOT NULL DEFAULT '',
                        job_id TEXT NOT NULL DEFAULT '',
                        result_code TEXT NOT NULL DEFAULT '',
                        error_code TEXT NOT NULL DEFAULT ''
                    )"""
                )

            store = ActivityJournalStore(path)
            with closing(sqlite3.connect(path)) as db:
                columns = {row[1] for row in db.execute("PRAGMA table_info(api_activity)")}
            self.assertTrue(
                {"activity_type", "operation_kind", "operation_status", "event_key"}
                <= columns
            )
            store.record(
                occurred_at=datetime.now(timezone.utc).isoformat(),
                request_id=str(uuid.uuid4()),
                method="GET",
                route="/api/v1/me",
                status_code=200,
                duration_ms=1,
            )

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

    def test_operation_events_are_idempotent_metadata_and_filter_by_origin_request(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ActivityJournalStore(Path(temp) / "app.db")
            event = {
                "event_id": str(uuid.uuid4()),
                "request_id": str(uuid.uuid4()),
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "route": "/api/v1/profiles/local",
                "actor_user_id": 42,
                "profile": "crest",
                "worker": "remote-1",
                "operation_id": str(uuid.uuid4()),
                "job_id": str(uuid.uuid4()),
                "operation_kind": "profile.local_delete",
                "operation_status": "failed",
                "result_code": "PROFILE_DELETE_FAILED",
                "error_code": "PROFILE_DELETE_FAILED",
                "private_payload": "must never be persisted",
            }
            store.record_operation_event(event)
            store.record_operation_event(event)

            restarted = ActivityJournalStore(Path(temp) / "app.db")
            entries = restarted.list_entries(
                request_id=event["request_id"], operation_id=event["operation_id"]
            )["items"]
            self.assertEqual(len(entries), 1)
            item = entries[0]
            self.assertEqual(item["activity_type"], "operation")
            self.assertEqual(item["operation_kind"], "profile.local_delete")
            self.assertEqual(item["operation_status"], "failed")
            self.assertEqual(item["result_code"], "PROFILE_DELETE_FAILED")
            self.assertEqual(item["error_code"], "PROFILE_DELETE_FAILED")
            self.assertEqual(item["method"], "ASYNC")
            self.assertNotIn("private_payload", item)
            with closing(sqlite3.connect(restarted.path)) as db:
                stored = repr(db.execute("SELECT * FROM api_activity").fetchall())
            self.assertNotIn("must never be persisted", stored)


if __name__ == "__main__":
    unittest.main()
