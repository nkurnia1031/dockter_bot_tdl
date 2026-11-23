import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from tme3bot.domain.models import Job, JobStatus
from tme3bot.infrastructure.database_compaction import DatabaseCompactionService
from tme3bot.infrastructure.job_store import SqliteJobRepository


class DatabaseCompactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "gateway.db"
        self.jobs = SqliteJobRepository(self.path)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def make_job(job_id="active-job"):
        return Job(
            id=job_id,
            kind="export",
            profile="default",
            actor_user_id=7,
            worker="remote-1",
            status=JobStatus.QUEUED,
            payload={"url": "https://t.me/c/1/2"},
        )

    def test_below_threshold_does_not_vacuum_and_reports_threshold(self):
        service = DatabaseCompactionService(
            self.jobs, min_free_bytes=64 * 1024 * 1024
        )
        before = self.path.stat().st_size

        result = service.tick()

        self.assertEqual(result["outcome"], "below_threshold")
        self.assertEqual(self.path.stat().st_size, before)
        status = service.status()
        self.assertEqual(status["threshold_bytes"], 64 * 1024 * 1024)
        self.assertEqual(status["last_result"]["outcome"], "below_threshold")
        self.assertNotIn("database_path", status)

    def test_active_job_defers_compaction(self):
        self.jobs.create(self.make_job())
        service = DatabaseCompactionService(self.jobs, min_free_bytes=0)

        result = service.tick()

        self.assertEqual(result["outcome"], "deferred_active_jobs")
        self.assertIsNotNone(self.jobs.get("active-job"))

    def test_active_durable_operation_defers_compaction(self):
        with sqlite3.connect(str(self.path)) as db:
            db.execute("CREATE TABLE operations (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
            db.execute("INSERT INTO operations VALUES('operation-1', 'running')")
        service = DatabaseCompactionService(self.jobs, min_free_bytes=0)

        result = service.tick()

        self.assertEqual(result["outcome"], "deferred_active_jobs")
        self.assertTrue(result["active_operations"])

    def test_completed_profile_statuses_do_not_block_compaction(self):
        with sqlite3.connect(str(self.path)) as db:
            db.execute(
                "CREATE TABLE profile_provisionings (id TEXT PRIMARY KEY, status TEXT NOT NULL)"
            )
            db.executemany(
                "INSERT INTO profile_provisionings VALUES(?, ?)",
                [("active-profile", "active"), ("stored-profile", "stored")],
            )
        service = DatabaseCompactionService(self.jobs, min_free_bytes=0)

        result = service.tick()

        self.assertNotEqual(result["outcome"], "deferred_active_jobs")
        self.assertFalse(result["active_operations"])

    def test_pending_local_profile_staging_blocks_startup_compaction(self):
        with sqlite3.connect(str(self.path)) as db:
            db.executescript(
                """
                CREATE TABLE profile_provisionings (
                    id TEXT PRIMARY KEY, profile TEXT NOT NULL, source TEXT NOT NULL,
                    status TEXT NOT NULL, bootstrap_worker TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE profile_sessions (
                    profile TEXT PRIMARY KEY, source TEXT NOT NULL,
                    source_worker TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                INSERT INTO profile_provisionings
                    VALUES('local-provisioning', 'archive', 'local_upload', 'active', 'local', 'same-time');
                INSERT INTO profile_sessions
                    VALUES('archive', 'local_upload', 'local', 'same-time');
                """
            )
        service = DatabaseCompactionService(self.jobs, min_free_bytes=0)

        result = service.tick()

        self.assertEqual(result["outcome"], "deferred_active_jobs")
        self.assertTrue(result["active_operations"])

    def test_activity_arriving_before_tick_prevents_compaction_admission(self):
        service = DatabaseCompactionService(self.jobs, min_free_bytes=0)

        with service.database_activity():
            result = service.tick()

        self.assertEqual(result["outcome"], "deferred_active_activity")
        self.assertFalse(service.status()["compaction_active"])
        self.assertEqual(service.status()["active_database_activities"], 0)

    def test_database_writer_lock_defers_without_blocking_job_work(self):
        with sqlite3.connect(str(self.path)) as db:
            db.execute("CREATE TABLE disposable_payload (value BLOB)")
            db.execute("INSERT INTO disposable_payload VALUES(?)", (b"x" * 2_000_000,))
            db.execute("DELETE FROM disposable_payload")
        writer = sqlite3.connect(str(self.path), timeout=0)
        writer.execute("BEGIN IMMEDIATE")
        service = DatabaseCompactionService(self.jobs, min_free_bytes=0)
        try:
            result = service.tick()
        finally:
            writer.rollback()
            writer.close()

        self.assertEqual(result["outcome"], "deferred_locked")
        self.jobs.create(self.make_job("after-lock-job"))
        self.assertIsNotNone(self.jobs.get("after-lock-job"))

    def test_store_lock_defers_without_waiting(self):
        locked = threading.Event()
        release = threading.Event()

        def hold_job_store_lock():
            with self.jobs._lock:
                locked.set()
                release.wait(2)

        thread = threading.Thread(target=hold_job_store_lock)
        thread.start()
        self.assertTrue(locked.wait(1))
        service = DatabaseCompactionService(self.jobs, min_free_bytes=0)
        try:
            result = service.tick()
        finally:
            release.set()
            thread.join(timeout=2)

        self.assertEqual(result["outcome"], "deferred_locked")

    def test_api_work_interrupts_vacuum_and_job_write_proceeds(self):
        with sqlite3.connect(str(self.path)) as db:
            db.execute("CREATE TABLE disposable_payload (value BLOB)")
            db.execute("INSERT INTO disposable_payload VALUES(?)", (b"x" * 16_000_000,))
            db.execute("DELETE FROM disposable_payload")
        service = DatabaseCompactionService(self.jobs, min_free_bytes=1)
        results = []
        progress_entered = threading.Event()
        continue_vacuum = threading.Event()
        connect = sqlite3.connect

        class ControlledProgressConnection:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def set_progress_handler(self, callback, instructions):
                if callback is None:
                    return self.connection.set_progress_handler(None, 0)

                def controlled_callback():
                    progress_entered.set()
                    if not continue_vacuum.wait(3):
                        return 1
                    return callback()

                return self.connection.set_progress_handler(
                    controlled_callback, min(1, instructions)
                )

        thread = threading.Thread(target=lambda: results.append(service.tick()))
        with patch(
            "tme3bot.infrastructure.job_store.sqlite3.connect",
            side_effect=lambda *args, **kwargs: ControlledProgressConnection(
                connect(*args, **kwargs)
            ),
        ):
            thread.start()
            try:
                self.assertTrue(
                    progress_entered.wait(2),
                    "VACUUM did not reach the controlled progress callback",
                )
                service.begin_database_activity()
                continue_vacuum.set()
                self.jobs.create(self.make_job("during-maintenance"))
            finally:
                continue_vacuum.set()
                service.end_database_activity()
                thread.join(timeout=3)

        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]["outcome"], "deferred_activity")
        self.assertIsNotNone(self.jobs.get("during-maintenance"))

    def test_idle_database_with_enough_free_pages_is_compacted(self):
        with sqlite3.connect(str(self.path)) as db:
            db.execute("CREATE TABLE disposable_payload (value BLOB)")
            db.execute("INSERT INTO disposable_payload VALUES(?)", (b"x" * 2_000_000,))
            db.execute("DELETE FROM disposable_payload")
            before_pages = int(db.execute("PRAGMA page_count").fetchone()[0])
            free_pages = int(db.execute("PRAGMA freelist_count").fetchone()[0])
            page_size = int(db.execute("PRAGMA page_size").fetchone()[0])
        self.assertGreater(free_pages * page_size, 1)
        service = DatabaseCompactionService(self.jobs, min_free_bytes=1)
        before_size = self.jobs._database_file_size()

        result = service.tick()

        self.assertEqual(result["outcome"], "compacted")
        self.assertGreater(result["free_bytes_before"], 1)
        self.assertLess(self.jobs._database_file_size(), before_size)
        with sqlite3.connect(str(self.path)) as db:
            self.assertLess(int(db.execute("PRAGMA page_count").fetchone()[0]), before_pages)
            self.assertEqual(int(db.execute("PRAGMA freelist_count").fetchone()[0]), 0)

    def test_checkpoint_interruption_is_reported_as_deferred_activity(self):
        with sqlite3.connect(str(self.path)) as db:
            db.execute("CREATE TABLE disposable_payload (value BLOB)")
            db.execute("INSERT INTO disposable_payload VALUES(?)", (b"x" * 2_000_000,))
            db.execute("DELETE FROM disposable_payload")
        cancel_event = threading.Event()
        connect = sqlite3.connect

        class CheckpointInterruptedConnection:
            def __init__(self, connection):
                self.connection = connection

            @property
            def row_factory(self):
                return self.connection.row_factory

            @row_factory.setter
            def row_factory(self, value):
                self.connection.row_factory = value

            def execute(self, statement, *args):
                if statement == "PRAGMA wal_checkpoint(TRUNCATE)":
                    cancel_event.set()
                    raise sqlite3.OperationalError("interrupted")
                return self.connection.execute(statement, *args)

            def set_progress_handler(self, callback, instructions):
                return self.connection.set_progress_handler(callback, instructions)

            def close(self):
                self.connection.close()

        with patch(
            "tme3bot.infrastructure.job_store.sqlite3.connect",
            side_effect=lambda *args, **kwargs: CheckpointInterruptedConnection(
                connect(*args, **kwargs)
            ),
        ):
            result = self.jobs.compact_database_if_idle(1, cancel_event=cancel_event)

        self.assertEqual(result["outcome"], "deferred_activity")
        self.assertEqual(result["reason"], "database_activity")


if __name__ == "__main__":
    unittest.main()
