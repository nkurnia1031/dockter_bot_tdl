from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tme3bot.infrastructure.source_store import (
    SourceRevisionConflict,
    SqliteProfileStateStore,
    SqliteSourceRepository,
)
from tme3bot.state import SourceState


class SqliteSourceRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "backend.db"
        self.repository = SqliteSourceRepository(self.db_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_feature_gate_defaults_off_and_is_persisted_as_backend_metadata(self):
        self.assertFalse(self.repository.is_enabled())
        self.repository.set_enabled(True)
        self.assertTrue(SqliteSourceRepository(self.db_path).is_enabled())
        self.repository.set_enabled(False)
        self.assertFalse(SqliteSourceRepository(self.db_path).is_enabled())

    def test_schema_reserves_peer_identity_and_revision_stays_internal(self):
        self.repository.upsert_source("default", "@iyear", None, 1)
        db = sqlite3.connect(str(self.db_path))
        try:
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(source_records)")
            }
        finally:
            db.close()

        source = self.repository.get_source("default", "iyear")
        self.assertTrue({"peer_type", "peer_id", "revision"}.issubset(columns))
        self.assertNotIn("revision", source.to_dict())

    def test_records_are_profile_scoped_and_chat_aliases_share_a_key(self):
        store = SqliteProfileStateStore(self.repository, "profile-one")
        store.upsert_source("https://t.me/IYear", "first label", 20, "warmup", False)
        updated = store.upsert_source("@iyear", None, 18)
        self.repository.upsert_source("profile-two", "iyear", None, 3)

        self.assertEqual(updated.last_id, 20)
        self.assertEqual(updated.label, "first label")
        self.assertEqual(updated.warmup_url, "warmup")
        self.assertFalse(updated.warmup_done)
        self.assertEqual([key for key, _ in store.list_sources()], ["iyear"])
        self.assertEqual(self.repository.get_source("profile-two", "@iyear").last_id, 3)

    def test_compare_and_swap_reports_revision_conflict_without_overwriting(self):
        source = self.repository.upsert_source("default", "12345", "initial", 10)
        current = self.repository.get_source("default", "12345")
        self.assertEqual(source.revision, 1)
        self.assertEqual(current.revision, 1)

        changed = self.repository.commit_source(
            "default",
            "12345",
            SourceState(15, "committed", "2026-10-05T00:00:00+00:00"),
            expected_revision=current.revision,
            peer_type="channel",
            peer_id="-10012345",
        )
        self.assertEqual(changed.revision, 2)
        self.assertEqual(changed.last_id, 15)

        with self.assertRaises(SourceRevisionConflict) as raised:
            self.repository.commit_source(
                "default",
                "12345",
                SourceState(30, "stale", "2026-10-05T00:00:00+00:00"),
                expected_revision=1,
            )
        self.assertEqual(
            raised.exception.details(),
            {"expected_revision": 1, "current_revision": 2},
        )
        self.assertEqual(self.repository.get_source("default", "12345").last_id, 15)

    def test_concurrent_worker_updates_do_not_lower_cursor_or_lose_revisions(self):
        stores = [SqliteSourceRepository(self.db_path) for _ in range(6)]
        stores[0].upsert_source("default", "@archive", "archive", 1)

        def write(index: int) -> None:
            stores[index % len(stores)].upsert_source(
                "default", "archive", None, index + 10
            )

        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(write, range(48)))

        source = self.repository.get_source("default", "archive")
        self.assertEqual(source.last_id, 57)
        self.assertEqual(source.label, "archive")
        self.assertEqual(source.revision, 49)

    def test_delete_ignores_empty_refs_and_only_deletes_requested_profile(self):
        self.repository.upsert_source("one", "chatone", None, 1)
        self.repository.upsert_source("two", "chattwo", None, 2)

        deleted = self.repository.delete_sources("one", ["", "@chatone", "missing"])

        self.assertEqual(deleted, ["chatone"])
        self.assertIsNone(self.repository.get_source("one", "chatone"))
        self.assertEqual(self.repository.get_source("two", "chattwo").last_id, 2)


if __name__ == "__main__":
    unittest.main()
