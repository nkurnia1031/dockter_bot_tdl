import json
import statistics
import sqlite3
import tempfile
import time
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tme3bot.application.job_scheduler import build_execution_plan
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

    @staticmethod
    def create_storage_upload(
        store: SqliteJobRepository,
        job_id: str,
        provider: str,
        transfer_mode: str,
        created_at: datetime | None = None,
    ) -> Job:
        payload = {
            "provider": provider,
            "folder_path": "/workspace/best",
            "transfer_mode": transfer_mode,
        }
        queued_at = created_at or datetime.now(timezone.utc)
        job = Job(
            id=job_id,
            kind="storage_upload",
            profile="default",
            actor_user_id=7,
            worker="local",
            status=JobStatus.QUEUED,
            payload=payload,
            created_at=queued_at,
            updated_at=queued_at,
        )
        plan = build_execution_plan(
            job.kind, job.profile, job.worker, payload
        ).as_dict()
        plan["queued_at"] = queued_at.isoformat()
        store.create_with_private_values(
            job,
            {},
            execution_plan=plan,
            command_payload={"dispatch_mode": "durable"},
        )
        return job

    def test_storage_copy_uploads_from_telegram_and_rclone_share_a_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            telegram = self.create_storage_upload(
                store,
                "telegram-copy",
                "telegram",
                "copy",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            rclone = self.create_storage_upload(
                store,
                "rclone-copy",
                "rclone",
                "copy",
                datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
            )
            move = self.create_storage_upload(
                store,
                "move-after-copies",
                "rclone",
                "move",
                datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
            )

            self.assertTrue(store.try_acquire_execution(telegram.id)["admitted"])
            store.append_event(
                JobEvent(telegram.id, 1, JobStatus.DISPATCHED, "dispatched")
            )
            self.assertTrue(store.try_acquire_execution(rclone.id)["admitted"])
            store.append_event(
                JobEvent(rclone.id, 1, JobStatus.DISPATCHED, "dispatched")
            )
            self.assertFalse(store.try_acquire_execution(move.id)["admitted"])

            store.release_execution(telegram.id)
            store.append_event(JobEvent(telegram.id, 2, JobStatus.RUNNING, "started"))
            store.append_event(JobEvent(telegram.id, 3, JobStatus.SUCCEEDED, "completed"))
            self.assertFalse(store.try_acquire_execution(move.id)["admitted"])

            store.release_execution(rclone.id)
            store.append_event(JobEvent(rclone.id, 2, JobStatus.RUNNING, "started"))
            store.append_event(JobEvent(rclone.id, 3, JobStatus.SUCCEEDED, "completed"))
            self.assertTrue(store.try_acquire_execution(move.id)["admitted"])

    def test_storage_move_waits_for_copies_and_later_copy_does_not_overtake(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            first_created = datetime(2026, 1, 1, tzinfo=timezone.utc)
            first_copy = self.create_storage_upload(
                store, "first-copy", "telegram", "copy", first_created
            )
            move = self.create_storage_upload(
                store,
                "move",
                "rclone",
                "move",
                first_created + timedelta(seconds=1),
            )
            later_copy = self.create_storage_upload(
                store,
                "later-copy",
                "rclone",
                "copy",
                first_created + timedelta(seconds=2),
            )

            self.assertTrue(store.try_acquire_execution(first_copy.id)["admitted"])
            store.append_event(
                JobEvent(first_copy.id, 1, JobStatus.DISPATCHED, "dispatched")
            )
            self.assertFalse(store.try_acquire_execution(move.id)["admitted"])
            self.assertFalse(store.try_acquire_execution(later_copy.id)["admitted"])

            store.release_execution(first_copy.id)
            store.append_event(JobEvent(first_copy.id, 2, JobStatus.RUNNING, "started"))
            store.append_event(
                JobEvent(first_copy.id, 3, JobStatus.SUCCEEDED, "completed")
            )
            self.assertTrue(store.try_acquire_execution(move.id)["admitted"])
            store.append_event(
                JobEvent(move.id, 1, JobStatus.DISPATCHED, "dispatched")
            )
            self.assertFalse(store.try_acquire_execution(later_copy.id)["admitted"])

            store.release_execution(move.id)
            store.append_event(JobEvent(move.id, 2, JobStatus.RUNNING, "started"))
            store.append_event(JobEvent(move.id, 3, JobStatus.SUCCEEDED, "completed"))
            self.assertTrue(store.try_acquire_execution(later_copy.id)["admitted"])

    def test_terminal_retention_keeps_latest_twenty_and_protects_active_and_reconciliation(self) -> None:
        from tme3bot.infrastructure.activity_journal import ActivityJournalStore

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.db"
            store = SqliteJobRepository(path)
            journal = ActivityJournalStore(path)
            base = datetime(2026, 1, 1, tzinfo=timezone.utc)
            job_ids = []
            for index in range(23):
                job_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"terminal-{index:02d}"))
                job_ids.append(job_id)
                store.create(replace(
                    self.make_job(), id=job_id, status=JobStatus.SUCCEEDED,
                    created_at=base + timedelta(minutes=index),
                    updated_at=base + timedelta(minutes=index),
                ))
                with store._db() as db:
                    db.execute(
                        "UPDATE jobs SET terminal_at=? WHERE id=?",
                        ((base + timedelta(minutes=index)).isoformat(), job_id),
                    )
                    db.execute(
                        "INSERT INTO job_events(job_id,sequence,status,event_type,created_at) VALUES(?,?,?,?,?)",
                        (job_id, 1, "succeeded", "completed", base.isoformat()),
                    )
                journal.record(
                    occurred_at=(base + timedelta(minutes=index)).isoformat(),
                    request_id=f"00000000-0000-0000-0000-{index + 1:012d}",
                    method="GET", route="/api/v1/jobs/{job_id}", status_code=200,
                    duration_ms=1, job_id=job_id,
                )

            store.create(replace(self.make_job(), id="active-job"))
            store.create(replace(
                self.make_job(), id="reconciliation-job", status=JobStatus.FAILED,
                result={"error": "uncertain external effect"},
                progress={"outcome_uncertain": True, "reconciliation_required": True},
            ))
            old_terminal_at = base - timedelta(days=1)
            store.create(replace(
                self.make_job(), id="outcome-uncertain-only-job", status=JobStatus.FAILED,
                result={"outcome": "failed"},
                progress={"outcome_uncertain": True},
                created_at=old_terminal_at,
                updated_at=old_terminal_at,
            ))
            with store._db() as db:
                db.execute("CREATE TABLE operational_sentinel (value TEXT)")
                db.execute("INSERT INTO operational_sentinel VALUES('keep')")

            pruned = store.prune_terminal_history()

            self.assertEqual(pruned, 3)
            self.assertEqual(store.count(statuses=("succeeded",)), 20)
            self.assertIsNone(store.get(job_ids[0]))
            self.assertIsNotNone(store.get(job_ids[-1]))
            self.assertIsNotNone(store.get("active-job"))
            self.assertIsNotNone(store.get("reconciliation-job"))
            self.assertIsNotNone(store.get("outcome-uncertain-only-job"))
            with store._db() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM job_events WHERE job_id=?", (job_ids[0],)).fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM api_activity WHERE job_id=?", (job_ids[0],)).fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT value FROM operational_sentinel").fetchone()[0], "keep")

    def test_terminal_retention_preserves_tts_delivery_reconciliation_evidence(self) -> None:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            job_ids = []
            for index in range(22):
                job_id = f"tts-terminal-{index:02d}"
                job_ids.append(job_id)
                store.create(replace(
                    self.make_job(), id=job_id, kind="tts",
                    status=JobStatus.RUNNING if index == 0 else JobStatus.FAILED,
                    created_at=base + timedelta(minutes=index),
                    updated_at=base + timedelta(minutes=index),
                    result={"error": "TTS_DELIVERY_NOT_VERIFIED"},
                ))
                with store._db() as db:
                    db.execute(
                        "UPDATE jobs SET terminal_at=? WHERE id=?",
                        ((base + timedelta(minutes=index)).isoformat(), job_id),
                    )

            store.create_tts_deliveries(job_ids[0], "local", "Judul", [{
                "artifact_ref": "a" * 48, "part_index": 1, "total_parts": 1,
                "byte_size": 5,
            }])
            delivery = store.claim_tts_deliveries(
                1, worker="local", job_id=job_ids[0]
            )[0]
            store.complete_tts_delivery(
                delivery["id"], delivered=False, reconciliation_required=True,
                uploaded_at=1_700_000_000, sender_profile="default",
            )
            with store._db() as db:
                db.execute(
                    "UPDATE jobs SET status='failed', terminal_at=?, result=? WHERE id=?",
                    ((base.isoformat()), '{"error":"TTS_DELIVERY_NOT_VERIFIED"}', job_ids[0]),
                )

            pruned = store.prune_terminal_history()

            self.assertEqual(pruned, 1)
            self.assertIsNotNone(store.get(job_ids[0]))
            self.assertEqual(
                store.get_tts_delivery(delivery["id"])["status"],
                "reconciliation_required",
            )
            self.assertIsNone(store.get(job_ids[1]))

    def test_terminal_timestamp_migration_uses_terminal_event_not_archive_update_time(self) -> None:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.db"
            store = SqliteJobRepository(path)
            job_ids = []
            for index in range(21):
                job_id = f"legacy-terminal-{index:02d}"
                job_ids.append(job_id)
                terminal_at = base + timedelta(minutes=index)
                store.create(replace(
                    self.make_job(), id=job_id, status=JobStatus.SUCCEEDED,
                    created_at=terminal_at, updated_at=terminal_at,
                ))
                archived_updated_at = base + timedelta(days=100 + (20 - index))
                with store._db() as db:
                    db.execute(
                        "UPDATE jobs SET terminal_at=NULL, updated_at=?, archived_at=? WHERE id=?",
                        (archived_updated_at.isoformat(), archived_updated_at.isoformat(), job_id),
                    )
                    db.execute(
                        "INSERT INTO job_events(job_id,sequence,status,event_type,created_at) VALUES(?,?,?,?,?)",
                        (job_id, 1, "succeeded", "completed", terminal_at.isoformat()),
                    )

            SqliteJobRepository(path)

            self.assertIsNone(store.get(job_ids[0]))
            self.assertTrue(all(store.get(job_id) is not None for job_id in job_ids[1:]))

    def test_retry_terminal_time_moves_job_into_latest_twenty(self) -> None:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            for index in range(21):
                job_id = f"terminal-{index:02d}"
                store.create(replace(
                    self.make_job(), id=job_id, status=JobStatus.SUCCEEDED,
                    created_at=base + timedelta(minutes=index),
                    updated_at=base + timedelta(minutes=index),
                ))
                with store._db() as db:
                    db.execute(
                        "UPDATE jobs SET terminal_at=? WHERE id=?",
                        ((base + timedelta(minutes=index)).isoformat(), job_id),
                    )

            retried = store.reset_for_retry("terminal-00", {"retry": True})
            self.assertEqual(retried.status, JobStatus.QUEUED)
            completed_at = base + timedelta(days=1)
            store.append_event(JobEvent(
                job_id="terminal-00", sequence=1, status=JobStatus.RUNNING,
                event_type="started", created_at=completed_at - timedelta(seconds=1),
            ))
            store.append_event(JobEvent(
                job_id="terminal-00", sequence=2, status=JobStatus.SUCCEEDED,
                event_type="completed", created_at=completed_at,
            ))

            self.assertIsNotNone(store.get("terminal-00"))
            self.assertIsNone(store.get("terminal-01"))

    def test_existing_resource_lease_table_migrates_to_allow_shared_holders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.db"
            store = SqliteJobRepository(path)
            store.create(self.make_job())
            with store._db() as db:
                db.execute("DROP TABLE job_resource_leases")
                db.execute(
                    """
                    CREATE TABLE job_resource_leases (
                        resource_key TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL,
                        acquired_at TEXT NOT NULL,
                        worker TEXT NOT NULL,
                        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO job_resource_leases(
                        resource_key, job_id, acquired_at, worker
                    ) VALUES(?, ?, ?, ?)
                    """,
                    (
                        "shared:worker:local:workspace:/workspace/best",
                        "job-1",
                        "2026-11-03T00:00:00+00:00",
                        "local",
                    ),
                )

            migrated = SqliteJobRepository(path)
            move = self.create_storage_upload(
                migrated, "move-after-migration", "rclone", "move"
            )
            self.assertFalse(migrated.try_acquire_execution(move.id)["admitted"])
            migrated.release_execution("job-1")
            self.assertTrue(migrated.try_acquire_execution(move.id)["admitted"])

    def test_multi_status_listing_paginates_globally_with_stable_ties(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            statuses = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)
            timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
            expected_ids = []

            for status in statuses:
                for index in range(205):
                    job_id = f"{status}-{index:03d}"
                    expected_ids.append(job_id)
                    store.create(
                        Job(
                            id=job_id,
                            kind="export",
                            profile="default",
                            actor_user_id=7,
                            worker="local",
                            status=JobStatus(status),
                            payload={},
                            created_at=timestamp,
                            updated_at=timestamp,
                        )
                    )

            page = store.list(statuses=statuses, offset=200, limit=10)

            self.assertEqual(store.count(statuses=statuses), 410)
            self.assertEqual(
                [job.id for job in page],
                sorted(expected_ids, reverse=True)[200:210],
            )

    def test_monitor_metrics_reports_fixed_window_and_ci_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.db"
            store = SqliteJobRepository(path)
            now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
            old = (now - timedelta(hours=48)).isoformat()
            recent = (now - timedelta(hours=1)).isoformat()
            progress = json.dumps(
                {
                    "observability": {
                        "last_event_at": recent,
                        "event_latency": {"count": 1, "total_ms": 17.0},
                        "phase_durations_seconds": {"exporting": 1.5},
                        "phase": "exporting",
                        "phase_elapsed_seconds": 2.0,
                    }
                },
                separators=(",", ":"),
            )
            payload_true = json.dumps({"quick_mode": True}, separators=(",", ":"))
            payload_false = json.dumps({"quick_mode": False}, separators=(",", ":"))
            rows = []

            def add_job(
                job_id: str,
                status: str,
                *,
                profile: str = "default",
                created_at: str,
                updated_at: str,
                archived_at: str | None = None,
                quick_mode: bool = False,
            ) -> None:
                rows.append(
                    (
                        job_id,
                        "export",
                        profile,
                        7,
                        "local",
                        status,
                        payload_true if quick_mode else payload_false,
                        progress,
                        created_at,
                        updated_at,
                        archived_at,
                    )
                )

            for index in range(10_000):
                add_job(
                    f"old-{index:05d}",
                    "succeeded",
                    created_at=old,
                    updated_at=old,
                )
            for index in range(200):
                add_job(
                    f"recent-success-{index:03d}",
                    "succeeded",
                    created_at=recent,
                    updated_at=recent,
                    quick_mode=index % 2 == 0,
                )
                add_job(
                    f"recent-failure-{index:03d}",
                    "failed",
                    created_at=recent,
                    updated_at=recent,
                    quick_mode=index % 2 == 0,
                )
            active_counts = {
                "queued": 4,
                "dispatched": 3,
                "running": 3,
                "paused": 2,
            }
            active_index = 0
            for status, count in active_counts.items():
                for index in range(count):
                    add_job(
                        f"active-{active_index:03d}",
                        status,
                        created_at=old,
                        updated_at=recent,
                        quick_mode=index % 2 == 0,
                    )
                    active_index += 1
            for index in range(40):
                add_job(
                    f"archived-{index:03d}",
                    "succeeded",
                    created_at=recent,
                    updated_at=recent,
                    archived_at=recent,
                )
            for index in range(500):
                add_job(
                    f"other-profile-{index:03d}",
                    "succeeded",
                    profile="archive",
                    created_at=recent,
                    updated_at=recent,
                )

            with sqlite3.connect(path) as db:
                db.executemany(
                    """INSERT INTO jobs(
                        id, kind, profile, actor_user_id, worker, status,
                        payload, progress, created_at, updated_at, archived_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )

            started = time.perf_counter()
            snapshot = store.monitor_metrics(profile="default", now=now)
            first_ms = (time.perf_counter() - started) * 1000
            samples = []
            for _ in range(15):
                started = time.perf_counter()
                snapshot = store.monitor_metrics(profile="default", now=now)
                samples.append((time.perf_counter() - started) * 1000)

            self.assertEqual(snapshot["window_hours"], 24)
            self.assertEqual(snapshot["queued_jobs"], 4)
            self.assertEqual(snapshot["dispatched_jobs"], 3)
            self.assertEqual(snapshot["running_jobs"], 3)
            self.assertEqual(snapshot["paused_jobs"], 2)
            self.assertEqual(snapshot["event_latency"]["count"], 412)
            print(
                "MONITOR_METRICS_BASELINE "
                f"total_rows={len(rows)} selected_rows=412 iterations={len(samples)} "
                f"first_ms={first_ms:.3f} median_warm_ms={statistics.median(samples):.3f}",
                flush=True,
            )

    def test_quickmode_limits_returns_all_counters_with_one_select(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            class TracedJobRepository(SqliteJobRepository):
                def __init__(self, path: Path) -> None:
                    self.read_statements: list[str] = []
                    super().__init__(path)

                def _connect(self):
                    db = super()._connect()
                    db.set_trace_callback(self._record_statement)
                    return db

                def _record_statement(self, statement: str) -> None:
                    if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                        self.read_statements.append(statement)

            path = Path(temp_dir) / "app.db"
            store = TracedJobRepository(path)
            store.read_statements.clear()
            now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc).isoformat()
            jobs = [
                ("local-queued-1", "local", "queued", True),
                ("local-queued-2", "local", "queued", True),
                ("local-queued-normal", "local", "queued", False),
                ("local-active-1", "local", "running", True),
                ("local-active-2", "local", "dispatched", True),
                ("remote-queued-1", "remote-1", "queued", True),
                ("remote-active-1", "remote-1", "running", True),
            ]
            with sqlite3.connect(path) as db:
                db.executemany(
                    """INSERT INTO jobs(
                        id, kind, profile, actor_user_id, worker, status,
                        payload, progress, created_at, updated_at
                    ) VALUES (?, 'export', 'default', 7, ?, ?, ?, '{}', ?, ?)""",
                    [
                        (
                            job_id,
                            worker,
                            status,
                            json.dumps({"quick_mode": quick_mode}),
                            now,
                            now,
                        )
                        for job_id, worker, status, quick_mode in jobs
                    ],
                )
                db.executemany(
                    "INSERT INTO job_quickmode_slots(job_id, worker, acquired_at) VALUES (?, ?, ?)",
                    [
                        (job_id, worker, now)
                        for job_id, worker, status, _ in jobs
                        if status in {"running", "dispatched"}
                    ],
                )
                db.execute(
                    "INSERT INTO quickmode_worker_limits(worker, max_concurrent, updated_at) VALUES (?, ?, ?)",
                    ("local", 3, now),
                )

            result = store.quickmode_limits(["remote-1", "local", "missing", "local"])

            self.assertEqual(
                result,
                [
                    {"worker": "local", "max_concurrent": 3, "active": 2, "queued": 2},
                    {"worker": "missing", "max_concurrent": 2, "active": 0, "queued": 0},
                    {"worker": "remote-1", "max_concurrent": 2, "active": 1, "queued": 1},
                ],
            )
            self.assertEqual(len(store.read_statements), 1)

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

    def test_unit_of_work_rolls_back_all_writes_on_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            with self.assertRaises(RuntimeError):
                with store.unit_of_work() as db:
                    SqliteJobRepository.insert_prepared_job(
                        db,
                        self.make_job(),
                        {"resource_keys": ["export:default"], "queue_group": "export", "lane": "export"},
                        {"private": "command"},
                    )
                    raise RuntimeError("simulate failure before transaction commit")
            self.assertIsNone(store.get("job-1"))
            self.assertIsNone(store.execution_plan("job-1"))
            self.assertIsNone(store.command_payload("job-1"))

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
                {
                    "total_parts": 1,
                    "delivered_parts": 1,
                    "cancelled_parts": 0,
                    "verification_pending_parts": 0,
                    "unverified_uploaded_parts": 0,
                },
            )

    def test_tts_verification_lease_unlocks_next_part_and_recovers_without_resend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            job = Job(
                id="tts-verify-order",
                kind="tts",
                profile="default",
                actor_user_id=7,
                worker="local",
                status=JobStatus.RUNNING,
                payload={"title": "Judul"},
            )
            store.create(job)
            store.create_tts_deliveries(job.id, job.worker, "Judul", [
                {"artifact_ref": "a" * 48, "part_index": 1, "total_parts": 2, "byte_size": 5},
                {"artifact_ref": "b" * 48, "part_index": 2, "total_parts": 2, "byte_size": 5},
            ])

            first = store.claim_tts_deliveries(1, worker="local", job_id=job.id, include_artifact_ref=True)[0]
            store.complete_tts_delivery(
                first["id"],
                delivered=False,
                verification_pending=True,
                uploaded_at=1_700_000_000,
                sender_profile="irang",
            )
            second = store.claim_tts_deliveries(1, worker="local", job_id=job.id, include_artifact_ref=True)[0]
            self.assertEqual(second["part_index"], 2)
            store.complete_tts_delivery(second["id"], delivered=True)

            with store._db() as db:
                db.execute(
                    "UPDATE job_tts_deliveries SET lease_until = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), first["id"]),
                )

            recovered = store.claim_tts_deliveries(1, worker="local", job_id=job.id, include_artifact_ref=True)[0]
            self.assertEqual(recovered["id"], first["id"])
            self.assertTrue(recovered["verification_pending"])
            self.assertEqual(recovered["uploaded_at"], 1_700_000_000)
            self.assertEqual(recovered["sender_profile"], "irang")
            store.complete_tts_delivery(recovered["id"], delivered=True)

            self.assertEqual(store.tts_delivery_summary(job.id)["delivered_parts"], 2)

    def test_tts_cancel_preserves_sent_parts_waiting_for_export_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            job = Job(
                id="tts-cancel-verify",
                kind="tts",
                profile="default",
                actor_user_id=7,
                worker="local",
                status=JobStatus.RUNNING,
                payload={"title": "Judul"},
            )
            store.create(job)
            store.create_tts_deliveries(job.id, job.worker, "Judul", [
                {"artifact_ref": "a" * 48, "part_index": 1, "total_parts": 2, "byte_size": 5},
                {"artifact_ref": "b" * 48, "part_index": 2, "total_parts": 2, "byte_size": 5},
            ])

            sent = store.claim_tts_deliveries(1, worker="local", job_id=job.id)[0]
            store.complete_tts_delivery(
                sent["id"],
                delivered=False,
                verification_pending=True,
                uploaded_at=1_700_000_000,
                sender_profile="default",
            )
            unsent = store.claim_tts_deliveries(1, worker="local", job_id=job.id)[0]

            store.cancel_tts_deliveries(job.id)

            self.assertEqual(store.get_tts_delivery(sent["id"])["status"], "claimed")
            self.assertEqual(store.get_tts_delivery(sent["id"])["uploaded_at"], 1_700_000_000)
            self.assertEqual(store.get_tts_delivery(unsent["id"])["status"], "cancelled")

    def test_tts_retry_keeps_upload_time_and_profile_for_exact_export_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteJobRepository(Path(temp_dir) / "app.db")
            job = Job(
                id="tts-retry-window",
                kind="tts",
                profile="default",
                actor_user_id=7,
                worker="local",
                status=JobStatus.RUNNING,
                payload={"title": "Judul"},
            )
            store.create(job)
            parts = [{
                "artifact_ref": "a" * 48,
                "part_index": 1,
                "total_parts": 1,
                "byte_size": 5,
            }]
            store.create_tts_deliveries(job.id, job.worker, "Judul", parts)
            sent = store.claim_tts_deliveries(
                1, worker="local", job_id=job.id, include_artifact_ref=True
            )[0]
            store.complete_tts_delivery(
                sent["id"],
                delivered=False,
                reconciliation_required=True,
                uploaded_at=1_700_000_000,
                sender_profile="irang",
            )

            store.create_tts_deliveries(job.id, job.worker, "Judul", [
                {**parts[0], "artifact_ref": "b" * 48},
            ])
            retry = store.claim_tts_deliveries(
                1, worker="local", job_id=job.id, include_artifact_ref=True
            )[0]

            self.assertTrue(retry["reconciliation_pending"])
            self.assertEqual(retry["uploaded_at"], 1_700_000_000)
            self.assertEqual(retry["sender_profile"], "irang")
            self.assertEqual(retry["artifact_ref"], "a" * 48)

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
