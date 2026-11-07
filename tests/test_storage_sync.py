import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from tme3bot.application.control_plane import ControlPlane
from tme3bot.domain.models import Job, JobEvent, JobStatus
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.storage_catalog import StorageCatalog, build_storage_caption
from tme3bot.storage_sync import full_history_proven, parse_storage_export
from tme3bot.tdl import StorageHistoryExport
from tme3bot.worker.executor_storage import StorageExecutorMixin


def storage_message(message_id, *, folder="", name="report.pdf", keywords=""):
    return {
        "id": message_id,
        "type": "message",
        "file": name,
        "date": 1790000000,
        "text": build_storage_caption(folder, name, keywords),
        "raw": {
            "message": build_storage_caption(folder, name, keywords),
            "media": {"document": {"size": 1234, "mime_type": "application/pdf"}},
        },
    }


def complete_coverage(latest_message_id):
    return {
        "strategy": "tdl_unbounded_export_v1", "export_mode": "all_messages",
        "range_max_id": latest_message_id,
        "latest_before_id": latest_message_id, "latest_after_id": latest_message_id,
        "export_succeeded": True, "iterator_completed": True,
        "pagination_verified": True, "complete": True,
    }


class StorageExportParsingTests(unittest.TestCase):
    def test_collects_every_message_id_but_only_recognized_storage_captions(self):
        parsed = parse_storage_export([
            storage_message(10, folder="Docs/2026", name="report.pdf", keywords="finance"),
            {"id": 11, "type": "message", "file": "ignored.txt", "text": "ordinary caption"},
        ])

        self.assertEqual(parsed.message_ids, [10, 11])
        self.assertEqual(len(parsed.items), 1)
        self.assertEqual(parsed.items[0]["channel_message_id"], 10)
        self.assertEqual(parsed.items[0]["folder"], "Docs/2026")
        self.assertEqual(parsed.items[0]["display_name"], "report.pdf")
        self.assertEqual(parsed.items[0]["file_size"], 1234)
        self.assertEqual(parsed.items[0]["mime_type"], "application/pdf")
        self.assertEqual(parsed.items[0]["sha256"], "")

    def test_rejects_duplicate_or_invalid_message_ids_before_catalog_changes(self):
        for messages in ([{"id": 1}, {"id": 1}], [{"id": "bad"}]):
            with self.subTest(messages=messages):
                with self.assertRaises(ValueError):
                    parse_storage_export(messages)

    def test_complete_history_requires_stable_unbounded_export_proof(self):
        coverage = {
            "strategy": "tdl_unbounded_export_v1", "export_mode": "all_messages",
            "range_max_id": 8, "latest_before_id": 8, "latest_after_id": 8,
            "export_succeeded": True, "iterator_completed": True,
            "pagination_verified": True, "complete": True,
        }
        self.assertTrue(full_history_proven(
            coverage, message_ids=[3, 8], batch_count=1,
            reported_message_count=2, reported_batch_count=1,
        ))
        self.assertFalse(full_history_proven(
            {**coverage, "latest_after_id": 9}, message_ids=[3, 8], batch_count=1,
            reported_message_count=2, reported_batch_count=1,
        ))
        self.assertFalse(full_history_proven(
            {key: value for key, value in coverage.items() if key != "complete"},
            message_ids=[3, 8], batch_count=1,
            reported_message_count=2, reported_batch_count=1,
        ))
        self.assertFalse(full_history_proven(
            {**coverage, "strategy": "tdl_id_range"},
            message_ids=[3, 8], batch_count=1,
            reported_message_count=2, reported_batch_count=1,
        ))
        self.assertFalse(full_history_proven(
            {**coverage, "iterator_completed": False},
            message_ids=[3, 8], batch_count=1,
            reported_message_count=2, reported_batch_count=1,
        ))
        self.assertFalse(full_history_proven(
            {**coverage, "pagination_verified": False},
            message_ids=[3, 8], batch_count=1,
            reported_message_count=2, reported_batch_count=1,
        ))


class StorageSyncWorkerTests(unittest.TestCase):
    def test_exports_selected_profile_channel_and_publishes_message_batches(self):
        messages = [
            storage_message(20, folder="Docs", name="report.pdf"),
            {"id": 21, "type": "message", "text": "unrelated"},
        ]

        class FakeTdlClient:
            command_callback = object()

            def export_storage_history(
                self, target, path, *, expected_channel_id,
                candidate_message_ids, verification_callback,
            ):
                self.target = target
                self.expected_channel_id = expected_channel_id
                self.export_path = path
                self.candidate_message_ids = candidate_message_ids
                self.verification_callback = verification_callback
                verification_callback(1, 1, 22)
                return StorageHistoryExport(
                    channel_id=123, peer_id=123, messages=messages,
                    latest_message_id=21, history_complete=False,
                    coverage={"strategy": "tdl_id_range", "complete": False},
                    confirmed_missing_message_ids=[22],
                    verification_failed_message_ids=[],
                )

        class FakePublisher:
            def __init__(self):
                self.events = []

            def emit(self, *args, **kwargs):
                self.events.append((args, kwargs))

        class FakeExecutor(StorageExecutorMixin):
            def __init__(self):
                self.client = FakeTdlClient()
                self.profile_manager = SimpleNamespace(runtime=lambda _profile: SimpleNamespace(
                    config=SimpleNamespace(storage_channel_id=123, storage_channel_ref="-100123"),
                    upload_tdl_client=self.client,
                    upload_operation_lock=threading.Lock(),
                ))
                self.publisher = FakePublisher()

            def available_storage_profiles(self):
                return ["default"]

            def available_storage_session_fingerprints(self, profiles):
                self.asserted_profiles = profiles
                return {"default": "a" * 64}

            def _job_cancelled(self, _job_id):
                return False

        executor = FakeExecutor()
        result = executor._storage_sync({
            "job_id": "storage-sync-worker-test",
            "profile": "default",
            "payload": {
                "channel_id": 123,
                "tdl_access_target": "-100123",
                "_tdl_sender_session_fingerprint": "a" * 64,
                "_storage_sync_candidate_message_ids": [22],
            },
        })

        self.assertEqual(executor.client.target, "-100123")
        self.assertEqual(executor.client.expected_channel_id, 123)
        self.assertEqual(executor.client.candidate_message_ids, [22])
        self.assertTrue(any(
            kwargs["progress"].get("phase") == "verifying_missing"
            for _args, kwargs in executor.publisher.events
            if isinstance(kwargs.get("progress"), dict)
        ))
        self.assertEqual(result["messages_scanned"], 2)
        self.assertEqual(result["items_recognized"], 1)
        self.assertEqual(result["confirmed_missing_message_ids"], [22])
        self.assertNotIn("skipped_unrecognized", result)
        progress_counters = [
            kwargs["progress"].get("counters", {})
            for _args, kwargs in executor.publisher.events
            if isinstance(kwargs.get("progress"), dict)
        ]
        self.assertTrue(all(counters.get("skipped", 0) == 0 for counters in progress_counters))
        self.assertTrue(any(
            kwargs["progress"].get("phase") == "completed"
            and "dikonfirmasi hilang" in kwargs["progress"].get("message", "")
            for _args, kwargs in executor.publisher.events
            if isinstance(kwargs.get("progress"), dict)
        ))
        batches = [kwargs["result"] for args, kwargs in executor.publisher.events if args[2] == "storage.sync_batch"]
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["message_ids"], [20, 21])
        self.assertEqual(batches[0]["items"][0]["channel_message_id"], 20)


class StorageSyncControlPlaneTests(unittest.TestCase):
    def test_pre_stall_batch_retry_is_not_reconciled_twice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = StorageCatalog(root / "storage.db")
            jobs = SqliteJobRepository(root / "jobs.db")
            jobs.create(Job(
                id="storage-sync-pre-stall-replay", kind="storage_sync",
                profile="default", actor_user_id=42, worker="local",
                status=JobStatus.QUEUED, payload={"channel_id": 123},
            ))
            control = ControlPlane(jobs, object(), object(), storage_catalog=catalog)
            batch = JobEvent(
                job_id="storage-sync-pre-stall-replay", sequence=1,
                status=JobStatus.RUNNING, event_type="storage.sync_batch",
                result={"channel_id": 123, "message_ids": [9], "items": []},
            )
            control.append_worker_event(batch)
            jobs.append_event(JobEvent(
                job_id="storage-sync-pre-stall-replay", sequence=2,
                status=JobStatus.FAILED, event_type="backend_stall_unconfirmed",
                progress={"outcome_uncertain": True, "reconciliation_required": True},
                error={"code": "JOB_STALLED", "message": "Worker tidak merespons."},
            ))

            replayed = control.append_worker_event(batch)
            terminal = control.append_worker_event(JobEvent(
                job_id="storage-sync-pre-stall-replay", sequence=3,
                status=JobStatus.SUCCEEDED, event_type="completed",
                result={"value": {
                    "channel_id": 123,
                    "messages_scanned": 1,
                    "batch_count": 1,
                    "history_complete": True,
                    "history_coverage": complete_coverage(9),
                }},
            ))

            self.assertEqual(replayed.status, JobStatus.FAILED)
            self.assertEqual(
                len([event for event in jobs.events("storage-sync-pre-stall-replay")
                     if event.event_type == "storage.sync_batch"]),
                1,
            )
            self.assertEqual(
                jobs.late_worker_events(
                    "storage-sync-pre-stall-replay", event_type="storage.sync_batch"
                ),
                [],
            )
            self.assertEqual(
                terminal.result["late_worker_reconciliation"]["status"],
                JobStatus.SUCCEEDED.value,
            )

    def test_late_storage_sync_batch_is_used_when_stalled_job_completes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = StorageCatalog(root / "storage.db")
            jobs = SqliteJobRepository(root / "jobs.db")
            jobs.create(Job(
                id="storage-sync-late", kind="storage_sync", profile="default",
                actor_user_id=42, worker="local", status=JobStatus.QUEUED,
                payload={"channel_id": 123},
            ))
            control = ControlPlane(jobs, object(), object(), storage_catalog=catalog)
            jobs.append_event(JobEvent(
                job_id="storage-sync-late", sequence=1, status=JobStatus.FAILED,
                event_type="backend_stall_unconfirmed",
                error={"code": "JOB_STALLED", "message": "Worker tidak merespons."},
            ))

            control.append_worker_event(JobEvent(
                job_id="storage-sync-late", sequence=2, status=JobStatus.RUNNING,
                event_type="storage.sync_batch", result={
                    "channel_id": 123,
                    "message_ids": [9],
                    "items": [{
                        "channel_message_id": 9,
                        "original_name": "late.txt",
                        "display_name": "late.txt",
                        "folder": "Recovered",
                        "keywords": "",
                        "caption": build_storage_caption("Recovered", "late.txt"),
                        "file_size": 10,
                        "mime_type": "text/plain",
                        "uploaded_at": "",
                    }],
                },
            ))
            terminal = control.append_worker_event(JobEvent(
                job_id="storage-sync-late", sequence=3, status=JobStatus.SUCCEEDED,
                event_type="completed", result={"value": {
                    "channel_id": 123,
                    "messages_scanned": 1,
                    "batch_count": 1,
                    "history_complete": True,
                    "history_coverage": complete_coverage(9),
                }},
            ))

            recovered = catalog.get_by_channel_message(123, 9)
            self.assertIsNotNone(recovered)
            self.assertEqual(terminal.status, JobStatus.FAILED)
            self.assertEqual(
                terminal.result["late_worker_reconciliation"]["status"],
                JobStatus.SUCCEEDED.value,
            )
            self.assertTrue(
                terminal.result["late_worker_reconciliation"]["result"]["value"]["history_complete"]
            )

    def test_stalled_storage_sync_retains_batches_beyond_job_result_cap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = StorageCatalog(root / "storage.db")
            jobs = SqliteJobRepository(root / "jobs.db")
            jobs.create(Job(
                id="storage-sync-late-many", kind="storage_sync", profile="default",
                actor_user_id=42, worker="local", status=JobStatus.QUEUED,
                payload={"channel_id": 123},
            ))
            control = ControlPlane(jobs, object(), object(), storage_catalog=catalog)
            jobs.append_event(JobEvent(
                job_id="storage-sync-late-many", sequence=1, status=JobStatus.FAILED,
                event_type="backend_stall_unconfirmed",
                error={"code": "JOB_STALLED", "message": "Worker tidak merespons."},
            ))

            batch_total = 257
            for index in range(batch_total):
                message_id = index + 1
                control.append_worker_event(JobEvent(
                    job_id="storage-sync-late-many",
                    sequence=index + 2,
                    status=JobStatus.RUNNING,
                    event_type="storage.sync_batch",
                    result={
                        "channel_id": 123,
                        "message_ids": [message_id],
                        "items": [],
                    },
                ))

            terminal = control.append_worker_event(JobEvent(
                job_id="storage-sync-late-many",
                sequence=batch_total + 2,
                status=JobStatus.SUCCEEDED,
                event_type="completed",
                result={"value": {
                    "channel_id": 123,
                    "messages_scanned": batch_total,
                    "batch_count": batch_total,
                    "history_complete": True,
                    "history_coverage": complete_coverage(batch_total),
                }},
            ))

            self.assertEqual(len(terminal.result["late_worker_events"]), 256)
            self.assertEqual(
                len(jobs.late_worker_events(
                    "storage-sync-late-many", event_type="storage.sync_batch"
                )),
                batch_total,
            )
            self.assertTrue(
                terminal.result["late_worker_reconciliation"]["result"]["value"]["history_complete"]
            )

    def test_storage_sync_terminal_retry_matches_sanitized_applied_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = StorageCatalog(root / "storage.db")
            absent = catalog.insert_item(
                upload_id="sync-retry-old", owner_user_id=5, owner_profile="default",
                channel_id=123, channel_message_id=8, original_name="old.txt",
                display_name="old.txt", folder="", keywords="", caption="",
                file_size=1, mime_type="text/plain", sha256="",
            )
            jobs = SqliteJobRepository(root / "jobs.db")
            jobs.create_with_private_values(
                Job(
                    id="storage-sync-terminal-retry", kind="storage_sync",
                    profile="default", actor_user_id=42, worker="local",
                    status=JobStatus.QUEUED, payload={"channel_id": 123},
                ),
                {},
                execution_plan={},
                command_payload={"_storage_sync_candidate_message_ids": [8]},
            )
            control = ControlPlane(jobs, object(), object(), storage_catalog=catalog)
            control.append_worker_event(JobEvent(
                job_id="storage-sync-terminal-retry", sequence=1,
                status=JobStatus.RUNNING, event_type="storage.sync_batch",
                result={"channel_id": 123, "message_ids": [9], "items": []},
            ))
            terminal_event = JobEvent(
                job_id="storage-sync-terminal-retry", sequence=2,
                status=JobStatus.SUCCEEDED, event_type="completed",
                result={"value": {
                    "channel_id": 123,
                    "messages_scanned": 1,
                    "batch_count": 1,
                    "history_complete": True,
                    "confirmed_missing_message_ids": [8],
                    "verification_failed_message_ids": [],
                    "history_coverage": complete_coverage(9),
                }},
            )
            observed = []
            control.add_event_observer(observed.append)

            first = control.append_worker_event(terminal_event)
            replayed = control.append_worker_event(terminal_event)

            self.assertEqual(first.status, JobStatus.SUCCEEDED)
            self.assertEqual(replayed.status, JobStatus.SUCCEEDED)
            self.assertIsNone(catalog.get_by_channel_message(123, absent.channel_message_id))
            self.assertEqual(len(observed), 2)

    def test_terminal_sync_applies_findings_but_unproven_history_cannot_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = StorageCatalog(root / "storage.db")
            absent = catalog.insert_item(
                upload_id="old-upload", owner_user_id=5, owner_profile="default",
                channel_id=123, channel_message_id=8, original_name="old.txt",
                display_name="old.txt", folder="", keywords="", caption="",
                file_size=1, mime_type="text/plain", sha256="",
            )
            jobs = SqliteJobRepository(root / "jobs.db")
            jobs.create(Job(
                id="storage-sync-control-test", kind="storage_sync", profile="default",
                actor_user_id=42, worker="local", status=JobStatus.QUEUED,
                payload={"channel_id": 123},
            ))
            control = ControlPlane(jobs, object(), object(), storage_catalog=catalog)
            control.append_worker_event(JobEvent(
                job_id="storage-sync-control-test", sequence=1, status=JobStatus.RUNNING,
                event_type="storage.sync_batch", result={
                    "channel_id": 123, "message_ids": [9],
                    "items": [{
                        "channel_message_id": 9, "original_name": "new.txt",
                        "display_name": "new.txt", "folder": "Recovered",
                        "keywords": "", "caption": build_storage_caption("Recovered", "new.txt"),
                        "file_size": 10, "mime_type": "text/plain", "uploaded_at": "",
                    }],
                },
            ))
            control.append_worker_event(JobEvent(
                job_id="storage-sync-control-test", sequence=2, status=JobStatus.SUCCEEDED,
                event_type="completed", result={"value": {
                    "channel_id": 123, "messages_scanned": 1, "batch_count": 1,
                    "history_complete": True,
                    "history_coverage": {
                        "strategy": "tdl_id_range", "range_start_id": 1,
                        "range_end_id": 9, "range_max_id": 9,
                        "latest_before_id": 9, "latest_after_id": 10,
                        "export_succeeded": True, "pagination_finished": True,
                        "complete": True,
                    },
                }},
            ))

            self.assertIsNotNone(catalog.get_by_channel_message(123, 9))
            self.assertIsNotNone(catalog.get_by_channel_message(123, 8))
            job = jobs.get("storage-sync-control-test")
            self.assertFalse(job.result["value"]["history_complete"])
            self.assertEqual(job.result["value"]["catalog"]["deletion_held"], 1)
            self.assertEqual(job.result["value"]["catalog"]["deleted"], 0)
            self.assertEqual(absent.channel_message_id, 8)

            jobs.create(Job(
                id="storage-sync-control-complete", kind="storage_sync", profile="default",
                actor_user_id=42, worker="local", status=JobStatus.QUEUED,
                payload={"channel_id": 123},
            ))
            control.append_worker_event(JobEvent(
                job_id="storage-sync-control-complete", sequence=1, status=JobStatus.RUNNING,
                event_type="storage.sync_batch", result={
                    "channel_id": 123, "message_ids": [9], "items": [],
                },
            ))
            control.append_worker_event(JobEvent(
                job_id="storage-sync-control-complete", sequence=2, status=JobStatus.SUCCEEDED,
                event_type="completed", result={"value": {
                    "channel_id": 123, "messages_scanned": 1, "batch_count": 1,
                    "history_complete": True,
                    "history_coverage": complete_coverage(9),
                }},
            ))

            complete_job = jobs.get("storage-sync-control-complete")
            self.assertTrue(complete_job.result["value"]["history_complete"])
            self.assertEqual(complete_job.result["value"]["catalog"]["deleted"], 0)
            self.assertIsNotNone(catalog.get_by_channel_message(123, 8))

    def test_targeted_confirmation_deletes_only_confirmed_catalog_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = StorageCatalog(root / "storage.db")
            for message_id in (8, 9, 10):
                catalog.insert_item(
                    upload_id=f"targeted-{message_id}", owner_user_id=5,
                    owner_profile="default", channel_id=123,
                    channel_message_id=message_id, original_name=f"{message_id}.txt",
                    display_name=f"{message_id}.txt", folder="", keywords="",
                    caption="", file_size=1, mime_type="text/plain", sha256="",
                )
            jobs = SqliteJobRepository(root / "jobs.db")
            jobs.create_with_private_values(Job(
                id="storage-sync-targeted", kind="storage_sync", profile="default",
                actor_user_id=42, worker="local", status=JobStatus.QUEUED,
                payload={"channel_id": 123},
            ), {}, execution_plan={}, command_payload={
                "channel_id": 123,
                "_storage_sync_candidate_message_ids": [8, 10],
            })
            control = ControlPlane(jobs, object(), object(), storage_catalog=catalog)
            control.append_worker_event(JobEvent(
                job_id="storage-sync-targeted", sequence=1, status=JobStatus.RUNNING,
                event_type="storage.sync_batch", result={
                    "channel_id": 123, "message_ids": [9], "items": [],
                },
            ))
            control.append_worker_event(JobEvent(
                job_id="storage-sync-targeted", sequence=2, status=JobStatus.SUCCEEDED,
                event_type="completed", result={"value": {
                    "channel_id": 123, "messages_scanned": 1, "batch_count": 1,
                    "history_complete": False,
                    "confirmed_missing_message_ids": [8],
                    "verification_failed_message_ids": [10],
                    "history_coverage": {"complete": False},
                }},
            ))

            self.assertIsNone(catalog.get_by_channel_message(123, 8))
            self.assertIsNotNone(catalog.get_by_channel_message(123, 9))
            self.assertIsNotNone(catalog.get_by_channel_message(123, 10))
            result = jobs.get("storage-sync-targeted").result["value"]
            self.assertEqual(result["catalog"]["deleted"], 1)
            self.assertEqual(result["catalog"]["deletion_held"], 1)
            self.assertEqual(result["confirmed_missing_count"], 1)
            self.assertEqual(result["verification_failed_count"], 1)
            self.assertNotIn("confirmed_missing_message_ids", result)


class StorageCatalogSyncTests(unittest.TestCase):
    def test_partial_sync_updates_matches_restores_trash_and_adds_recovered_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            existing = catalog.insert_item(
                upload_id="original-upload",
                owner_user_id=5,
                owner_profile="old-profile",
                channel_id=-100123,
                channel_message_id=10,
                original_name="old.pdf",
                display_name="Old.pdf",
                folder="Old",
                keywords="old",
                caption="old caption",
                file_size=100,
                mime_type="application/old",
                sha256="existing-hash",
            )
            catalog.enqueue_caption(existing.id, "stale local caption")
            trashed = catalog.insert_item(
                upload_id="trashed-upload",
                owner_user_id=5,
                owner_profile="old-profile",
                channel_id=-100123,
                channel_message_id=12,
                original_name="trashed.txt",
                display_name="trashed.txt",
                folder="",
                keywords="",
                caption="old caption",
                file_size=None,
                mime_type="",
                sha256="",
            )
            catalog.trash_items([trashed.id], 5)
            catalog.insert_item(
                upload_id="missing-upload",
                owner_user_id=5,
                owner_profile="old-profile",
                channel_id=-100123,
                channel_message_id=9,
                original_name="missing.txt",
                display_name="missing.txt",
                folder="",
                keywords="",
                caption="old caption",
                file_size=None,
                mime_type="",
                sha256="",
            )

            result = catalog.apply_channel_sync(
                job_id="sync-partial",
                channel_id=-100123,
                message_ids=[10, 11, 12, 13],
                items=[
                    {
                        "channel_message_id": 10,
                        "original_name": "renamed.pdf",
                        "display_name": "Report 2026.pdf",
                        "folder": "Docs/2026",
                        "keywords": "finance",
                        "caption": build_storage_caption("Docs/2026", "Report 2026.pdf", "finance"),
                        "file_size": 1234,
                        "mime_type": "application/pdf",
                        "uploaded_at": "2026-10-30T00:00:00+00:00",
                    },
                    {
                        "channel_message_id": 12,
                        "original_name": "trashed.txt",
                        "display_name": "Recovered.txt",
                        "folder": "",
                        "keywords": "restored",
                        "caption": build_storage_caption("", "Recovered.txt", "restored"),
                        "file_size": 25,
                        "mime_type": "text/plain",
                        "uploaded_at": "2026-10-30T00:00:01+00:00",
                    },
                    {
                        "channel_message_id": 13,
                        "original_name": "new.pdf",
                        "display_name": "new.pdf",
                        "folder": "Docs",
                        "keywords": "new",
                        "caption": build_storage_caption("Docs", "new.pdf", "new"),
                        "file_size": 88,
                        "mime_type": "application/pdf",
                        "uploaded_at": "2026-10-30T00:00:02+00:00",
                    },
                ],
                actor_user_id=99,
                profile="recoverer",
                history_coverage=None,
                reported_history_complete=False,
                reported_message_count=4,
                batch_count=1,
                reported_batch_count=1,
            )

            updated = catalog.get(existing.id, include_deleted=True)
            restored = catalog.get(trashed.id, include_deleted=True)
            recovered = catalog.get_by_channel_message(-100123, 13)
            self.assertEqual(updated.display_name, "Report 2026.pdf")
            self.assertEqual(updated.folder, "Docs/2026")
            self.assertEqual(updated.sha256, "existing-hash")
            self.assertEqual(updated.caption_sync_status, "synced")
            self.assertNotIn(existing.id, {item["item_id"] for item in catalog.pending_captions()})
            self.assertEqual(restored.status, "active")
            self.assertIsNone(restored.trashed_at)
            self.assertEqual(recovered.recovered_by_user_id, 99)
            self.assertEqual(recovered.recovered_from_profile, "recoverer")
            self.assertEqual(recovered.sha256, "")
            self.assertEqual(catalog.get_by_channel_message(-100123, 11), None)
            self.assertEqual(result["recovered"], 1)
            self.assertEqual(result["restored"], 1)
            self.assertGreaterEqual(result["deletion_held"], 1)

    def test_full_history_proof_alone_does_not_delete_without_targeted_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            for message_id in (20, 21):
                catalog.insert_item(
                    upload_id=f"upload-{message_id}",
                    owner_user_id=5,
                    owner_profile="default",
                    channel_id=-100123,
                    channel_message_id=message_id,
                    original_name=f"{message_id}.txt",
                    display_name=f"{message_id}.txt",
                    folder="",
                    keywords="",
                    caption="caption",
                    file_size=None,
                    mime_type="",
                    sha256="",
                )

            partial = catalog.apply_channel_sync(
                job_id="sync-no-proof", channel_id=-100123, message_ids=[20], items=[],
                actor_user_id=99, profile="default", history_coverage=None,
                reported_history_complete=False, reported_message_count=1,
                batch_count=1, reported_batch_count=1,
            )
            self.assertIsNotNone(catalog.get_by_channel_message(-100123, 21))
            self.assertEqual(partial["deleted"], 0)

            complete = catalog.apply_channel_sync(
                job_id="sync-with-proof", channel_id=-100123, message_ids=[20], items=[],
                actor_user_id=99, profile="default", history_coverage=complete_coverage(20),
                reported_history_complete=True, reported_message_count=1,
                batch_count=1, reported_batch_count=1,
            )
            self.assertIsNotNone(catalog.get_by_channel_message(-100123, 21))
            self.assertEqual(complete["history_complete"], True)
            self.assertEqual(complete["deleted"], 0)
            self.assertEqual(complete["deletion_held"], 1)

    def test_targeted_missing_confirmation_deletes_only_explicit_absent_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            for message_id in (30, 31):
                catalog.insert_item(
                    upload_id=f"confirm-{message_id}", owner_user_id=7,
                    owner_profile="default", channel_id=-100123,
                    channel_message_id=message_id, original_name=f"{message_id}.txt",
                    display_name=f"{message_id}.txt", folder="", keywords="",
                    caption="", file_size=1, mime_type="text/plain", sha256="",
                )

            result = catalog.apply_channel_sync(
                job_id="sync-targeted-confirmation", channel_id=-100123,
                message_ids=[], items=[], confirmed_missing_message_ids=[30],
                actor_user_id=99, profile="default", history_coverage=None,
                reported_history_complete=False, reported_message_count=0,
                batch_count=0, reported_batch_count=0,
            )

            self.assertIsNone(catalog.get_by_channel_message(-100123, 30))
            self.assertIsNotNone(catalog.get_by_channel_message(-100123, 31))
            self.assertEqual(result["confirmed_missing"], 1)
            self.assertEqual(result["deleted"], 1)
            self.assertEqual(result["deletion_held"], 1)

    def test_sync_keeps_channel_names_even_when_duplicate_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            items = [
                {
                    "channel_message_id": message_id,
                    "original_name": "report.pdf",
                    "display_name": "report.pdf",
                    "folder": "Docs",
                    "keywords": "",
                    "caption": build_storage_caption("Docs", "report.pdf"),
                    "file_size": 1234,
                    "mime_type": "application/pdf",
                    "uploaded_at": "2026-10-21T00:00:00+00:00",
                }
                for message_id in (20, 21)
            ]
            first = catalog.apply_channel_sync(
                job_id="duplicate-sync-1", channel_id=123, message_ids=[20, 21], items=items,
                actor_user_id=42, profile="default", history_coverage=None,
                reported_history_complete=False, reported_message_count=2,
                batch_count=1, reported_batch_count=1,
            )
            self.assertEqual(first["recovered"], 2)
            recovered = [
                catalog.get_by_channel_message(123, message_id)
                for message_id in (20, 21)
            ]
            self.assertEqual(
                [item.display_name for item in recovered],
                ["report.pdf", "report.pdf"],
            )
            updated_at = [item.updated_at for item in recovered]

            second = catalog.apply_channel_sync(
                job_id="duplicate-sync-2", channel_id=123, message_ids=[20, 21], items=items,
                actor_user_id=42, profile="default", history_coverage=None,
                reported_history_complete=False, reported_message_count=2,
                batch_count=1, reported_batch_count=1,
            )

            self.assertEqual(second["updated"], 0)
            self.assertEqual(
                [
                    catalog.get_by_channel_message(123, message_id).updated_at
                    for message_id in (20, 21)
                ],
                updated_at,
            )


if __name__ == "__main__":
    unittest.main()
