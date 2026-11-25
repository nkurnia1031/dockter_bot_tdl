import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tme3bot.domain.models import DomainError
from tme3bot.worker.command_runner import WorkerCommandRunner
from tme3bot.worker.command_store import WorkerCommandStore
from tme3bot.worker.executor_support import WorkerEventPublisher
from unittest.mock import patch


def job_envelope(command_id="command-1", job_id="job-1", attempt=1):
    return {
        "command_id": command_id,
        "operation_id": "operation-1",
        "job_id": job_id,
        "attempt": attempt,
        "dispatch_token": "dispatch-secret",
        "event_sequence_start": 3,
        "execution_plan": {"resource_keys": ["worker:local:export"]},
        "job": {
            "kind": "export",
            "profile": "default",
            "actor_user_id": 42,
            "worker": "local",
            "payload": {"url": "https://t.me/c/1/2", "private_value": "payload-secret"},
        },
    }


class WorkerCommandStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "worker-command-journal.sqlite3"
        self.store = WorkerCommandStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_accept_is_idempotent_and_public_snapshot_hides_private_payload(self):
        envelope = job_envelope()
        first, replayed = self.store.accept(envelope)
        second, replayed_again = self.store.accept(envelope)

        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(first["command_id"], second["command_id"])
        self.assertEqual(second["status"], "accepted")
        self.assertNotIn("dispatch_token", second)
        self.assertNotIn("payload", second)
        self.assertNotIn("dispatch-secret", str(second))
        self.assertNotIn("payload-secret", str(second))

    def test_job_progress_snapshots_return_latest_attempt_checkpoint_without_command_data(self):
        first = job_envelope("snapshot-command-1", "snapshot-job", attempt=1)
        self.store.accept(first)
        self.store.set_status("snapshot-command-1", "running")
        self.store.append_event(
            "snapshot-job",
            {
                "status": "running",
                "event_type": "progress.snapshot",
                "command_id": "snapshot-command-1",
                "attempt": 1,
                "dispatch_token": first["dispatch_token"],
                "progress": {"phase": "old-phase", "item": {"name": "old.bin"}},
            },
            transient=True,
        )

        latest = job_envelope("snapshot-command-2", "snapshot-job", attempt=2)
        self.store.accept(latest)
        self.store.set_status("snapshot-command-2", "running")
        self.store.append_event(
            "snapshot-job",
            {
                "status": "running",
                "event_type": "progress.snapshot",
                "command_id": "snapshot-command-2",
                "attempt": 2,
                "dispatch_token": latest["dispatch_token"],
                "progress": {
                    "phase": "uploading",
                    "item": {"name": "new.bin", "index": 2, "total": 4, "percent": 40},
                },
            },
            transient=True,
        )

        snapshots = self.store.progress_snapshots_for_jobs(
            ["snapshot-job", "missing-job", "snapshot-job"]
        )

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["job_id"], "snapshot-job")
        self.assertEqual(snapshots[0]["attempt"], 2)
        self.assertEqual(snapshots[0]["phase"], "uploading")
        self.assertEqual(snapshots[0]["progress"]["item"]["name"], "new.bin")
        self.assertNotIn("command_id", snapshots[0])
        self.assertNotIn("checkpoint", snapshots[0])
        self.assertNotIn("payload", snapshots[0])

    def _append_and_ack_terminal_command(
        self, envelope, *, status="succeeded", result=None, progress=None
    ):
        job_id = envelope["job_id"]
        command_id = envelope["command_id"]
        self.store.set_status(command_id, "running", only_from=("accepted",))
        sequence = self.store.append_event(
            job_id,
            {
                "status": status,
                "event_type": "command.completed",
                "command_id": command_id,
                "attempt": envelope["attempt"],
                "dispatch_token": envelope["dispatch_token"],
                "result": result,
                "progress": progress or {},
            },
            transient=False,
        )
        event = self.store.claim_event()
        self.assertEqual(event[2], sequence)
        self.assertTrue(
            self.store.acknowledge_event(event[0], event[4], accepted=True)
        )

    def test_acknowledged_terminal_job_compacts_details_but_keeps_replay_tombstone(self):
        envelope = job_envelope("compact-command", "compact-job")
        envelope["job"]["kind"] = "storage_upload"
        self.store.accept(envelope)
        self.store.record_storage_upload_item(
            "compact-command", "done.bin", file_name="done.bin",
            status="succeeded", attempt=1, message_id=77,
            result_item={"path": "done.bin", "status": "succeeded"},
        )

        self._append_and_ack_terminal_command(
            envelope,
            result={"value": {"items": [{"path": "done.bin", "status": "succeeded"}]}},
        )

        status = self.store.get("compact-command")
        self.assertEqual(status["status"], "succeeded")
        self.assertEqual(status["phase"], "terminal_tombstone")
        self.assertIsNone(status["checkpoint"])
        self.assertIsNone(status["ack"])
        self.assertEqual(self.store.storage_upload_items("compact-command"), [])
        self.assertIsNone(self.store.storage_upload_items_for_job("compact-job"))
        with self.store._db() as db:
            self.assertIsNone(db.execute(
                "SELECT 1 FROM worker_event_outbox "
                "WHERE json_extract(event_json,'$.command_id')='compact-command'"
            ).fetchone())

        replay, replayed = self.store.accept(envelope)
        self.assertTrue(replayed)
        self.assertEqual(replay["status"], "succeeded")
        self.assertIsNone(self.store.claim_next())
        changed_payload = job_envelope("compact-command", "compact-job")
        changed_payload["job"]["kind"] = "storage_upload"
        changed_payload["job"]["payload"]["url"] = "https://t.me/c/1/99"
        with self.assertRaises(DomainError) as conflict:
            self.store.accept(changed_payload)
        self.assertEqual(conflict.exception.code, "COMMAND_ID_CONFLICT")
        conflicting_attempt = job_envelope("new-command-same-attempt", "compact-job")
        with self.assertRaises(DomainError) as conflict:
            self.store.accept(conflicting_attempt)
        self.assertEqual(conflict.exception.code, "COMMAND_ATTEMPT_CONFLICT")

    def test_storage_detail_survives_ambiguous_terminal_until_final_reconciliation_ack(self):
        source = job_envelope("source-command", "source-job")
        source["job"]["kind"] = "storage_upload"
        self.store.accept(source)
        self.store.record_storage_upload_item(
            "source-command", "ambiguous.bin", file_name="ambiguous.bin",
            status="needs_reconciliation", attempt=1, retryable=False,
            result_item={"path": "ambiguous.bin", "status": "needs_reconciliation"},
        )
        self._append_and_ack_terminal_command(
            source,
            status="failed",
            result={"value": {"items": [{"path": "ambiguous.bin", "status": "needs_reconciliation"}]}},
            progress={"reconciliation_required": True},
        )
        self.assertIsNotNone(self.store.get("source-command"))
        self.assertEqual(
            self.store.storage_upload_items("source-command")[0]["status"],
            "needs_reconciliation",
        )

        reconcile = job_envelope("reconcile-command", "reconcile-job", attempt=1)
        reconcile["job"]["kind"] = "storage_reconcile"
        reconcile["job"]["payload"] = {
            "source_job_id": "source-job",
            "_storage_reconcile_final_for_source": True,
            "_storage_reconcile_items": [{"index": 0, "name": "ambiguous.bin"}],
        }
        self.store.accept(reconcile)
        self._append_and_ack_terminal_command(
            reconcile,
            result={"value": {
                "source_job_id": "source-job",
                "items": [{
                    "index": 0, "name": "ambiguous.bin", "status": "failed",
                    "match_count": 0, "retryable": True,
                }],
            }},
        )

        self.assertEqual(self.store.get("source-command")["status"], "failed")
        self.assertEqual(self.store.get("reconcile-command")["status"], "succeeded")
        self.assertIsNone(self.store.storage_upload_items_for_job("source-job"))

    def test_incomplete_final_reconciliation_keeps_source_details(self):
        source = job_envelope("incomplete-source-command", "incomplete-source-job")
        source["job"]["kind"] = "storage_upload"
        self.store.accept(source)
        self.store.record_storage_upload_item(
            "incomplete-source-command", "still-ambiguous.bin",
            file_name="still-ambiguous.bin", status="needs_reconciliation",
            attempt=1, retryable=False,
            result_item={"path": "still-ambiguous.bin", "status": "needs_reconciliation"},
        )
        self._append_and_ack_terminal_command(
            source,
            status="failed",
            result={"value": {"items": [{"path": "still-ambiguous.bin", "status": "needs_reconciliation"}]}},
            progress={"reconciliation_required": True},
        )

        reconcile = job_envelope("incomplete-reconcile-command", "incomplete-reconcile-job")
        reconcile["job"]["kind"] = "storage_reconcile"
        reconcile["job"]["payload"] = {
            "source_job_id": "incomplete-source-job",
            "_storage_reconcile_final_for_source": True,
            "_storage_reconcile_items": [{"index": 0, "name": "still-ambiguous.bin"}],
        }
        self.store.accept(reconcile)
        self._append_and_ack_terminal_command(
            reconcile,
            result={"value": {"source_job_id": "incomplete-source-job", "items": []}},
        )

        self.assertEqual(
            self.store.storage_upload_items_for_job("incomplete-source-job")["items"][0]["status"],
            "needs_reconciliation",
        )

    def test_final_reconciliation_rejects_mismatched_name_or_unsafe_absence(self):
        cases = [
            (
                "wrong-name", "telegram", {"index": 0, "name": "expected.bin"},
                {"index": 0, "name": "other.bin", "status": "failed", "match_count": 0, "retryable": True},
            ),
            (
                "unsafe-absence", "telegram", {"index": 0, "name": "expected.bin"},
                {"index": 0, "name": "expected.bin", "status": "failed", "match_count": 0, "retryable": False},
            ),
            (
                "wrong-rclone-target", "rclone",
                {"index": 0, "name": "expected.bin", "target_path": "remote/expected.bin"},
                {"index": 0, "name": "expected.bin", "target_path": "remote/other.bin", "status": "succeeded", "match_count": 1, "retryable": False},
            ),
        ]
        for suffix, provider, requested_item, evidence in cases:
            with self.subTest(suffix=suffix):
                source_job_id = f"{suffix}-source-job"
                source = job_envelope(f"{suffix}-source-command", source_job_id)
                source["operation_id"] = f"{suffix}-source-operation"
                source["job"]["kind"] = "storage_upload"
                source["job"]["payload"] = {"provider": provider}
                self.store.accept(source)
                uploaded_item = {
                    "path": "expected.bin", "name": "expected.bin",
                    "status": "needs_reconciliation", "provider": provider,
                }
                if provider == "rclone":
                    uploaded_item.update(
                        target_path="remote/expected.bin",
                        source_identity={"device": 1, "inode": 2, "size": 3, "mtime_ns": 4},
                    )
                self.store.record_storage_upload_item(
                    source["command_id"], "expected.bin", file_name="expected.bin",
                    status="needs_reconciliation", attempt=1, retryable=False,
                    result_item=uploaded_item,
                )
                self._append_and_ack_terminal_command(
                    source,
                    status="failed",
                    result={"value": {"items": [uploaded_item]}},
                    progress={"reconciliation_required": True},
                )

                reconcile = job_envelope(f"{suffix}-reconcile-command", f"{suffix}-reconcile-job")
                reconcile["operation_id"] = f"{suffix}-reconcile-operation"
                reconcile["job"]["kind"] = "storage_reconcile"
                reconcile["job"]["payload"] = {
                    "source_job_id": source_job_id,
                    "_storage_reconcile_final_for_source": True,
                    "_storage_reconcile_items": [requested_item],
                }
                self.store.accept(reconcile)
                self._append_and_ack_terminal_command(
                    reconcile,
                    result={"value": {
                        "source_job_id": source_job_id,
                        "items": [evidence],
                    }},
                )

                self.assertIsNotNone(self.store.storage_upload_items_for_job(source_job_id))

    def test_rejected_terminal_event_ack_keeps_worker_details(self):
        envelope = job_envelope("rejected-ack-command", "rejected-ack-job")
        envelope["job"]["kind"] = "storage_upload"
        self.store.accept(envelope)
        self.store.record_storage_upload_item(
            "rejected-ack-command", "unconfirmed.bin", file_name="unconfirmed.bin",
            status="succeeded", attempt=1,
            result_item={"path": "unconfirmed.bin", "status": "succeeded"},
        )
        self.store.set_status("rejected-ack-command", "running", only_from=("accepted",))
        self.store.append_event(
            "rejected-ack-job",
            {
                "status": "succeeded",
                "event_type": "command.completed",
                "command_id": "rejected-ack-command",
                "attempt": 1,
                "dispatch_token": "dispatch-secret",
                "result": {"items": [{"path": "unconfirmed.bin", "status": "succeeded"}]},
            },
            transient=False,
        )
        event = self.store.claim_event()

        self.assertTrue(
            self.store.acknowledge_event(event[0], event[4], accepted=False, reason="gateway rejected")
        )

        self.assertEqual(self.store.get("rejected-ack-command")["status"], "running")
        self.assertEqual(len(self.store.storage_upload_items("rejected-ack-command")), 1)

    def test_command_id_and_job_attempt_conflicts_are_rejected(self):
        self.store.accept(job_envelope())
        changed = job_envelope()
        changed["job"]["payload"]["url"] = "https://t.me/c/1/99"
        with self.assertRaises(DomainError) as conflict:
            self.store.accept(changed)
        self.assertEqual(conflict.exception.code, "COMMAND_ID_CONFLICT")

        same_attempt = job_envelope(command_id="command-2")
        with self.assertRaises(DomainError) as conflict:
            self.store.accept(same_attempt)
        self.assertEqual(conflict.exception.code, "COMMAND_ATTEMPT_CONFLICT")

    def test_cancel_request_is_scoped_to_the_requested_attempt(self):
        first = job_envelope("command-attempt-1", "retrying-job", attempt=1)
        self.store.accept(first)
        self.store.finish("command-attempt-1", "cancelled")
        second = job_envelope("command-attempt-2", "retrying-job", attempt=2)
        self.store.accept(second)

        self.assertIsNone(
            self.store.request_cancel_by_job("retrying-job", attempt=1)
        )
        self.assertEqual(self.store.get("command-attempt-2")["status"], "accepted")

        cancelled = self.store.request_cancel_by_job("retrying-job", attempt=2)
        self.assertEqual(cancelled["attempt"], 2)
        self.assertEqual(cancelled["status"], "cancelled")

    def test_jobless_operation_command_is_supported(self):
        envelope = {
            "command_id": "operation-command",
            "operation_id": "profile-distribution-1",
            "attempt": 1,
            "dispatch_token": "operation-token",
            "operation": {"kind": "profile.distribute", "profile": "default", "worker": "local"},
        }
        snapshot, replayed = self.store.accept(envelope)
        self.assertFalse(replayed)
        self.assertIsNone(snapshot["job_id"])
        self.assertEqual(snapshot["operation_id"], "profile-distribution-1")

    def test_startup_requeues_pre_spawn_work_and_marks_running_work_uncertain(self):
        self.store.accept(job_envelope("claimed-command", "job-claimed"))
        self.store.accept(job_envelope("running-command", "job-running", attempt=2))
        claimed = self.store.claim_next()
        self.assertEqual(claimed[0], "claimed-command")
        self.store.set_status("claimed-command", "queued", only_from=("claimed",))
        self.store.set_status("running-command", "running", only_from=("accepted",))

        recovered = WorkerCommandStore(self.path)
        report = recovered.recover_startup()
        self.assertEqual(report["requeued"], 1)
        self.assertEqual(report["needs_reconciliation"], 1)
        self.assertEqual(recovered.get("claimed-command")["status"], "accepted")
        self.assertEqual(recovered.get("running-command")["status"], "needs_reconciliation")
        self.assertFalse(recovered.get("running-command")["accepted"])

    def test_restart_recovery_lists_one_safe_job_record_and_is_idempotent(self):
        envelope = job_envelope("utility-command", "utility-job")
        envelope["job"]["kind"] = "utility"
        envelope["job"]["payload"] = {"utility": "compress", "password": "must-not-leak"}
        self.store.accept(envelope)
        self.store.set_status("utility-command", "running", only_from=("accepted",))
        self.store.append_event(
            "utility-job",
            {
                "status": "running",
                "event_type": "progress.snapshot",
                "progress": {"phase": "compressing"},
                "command_id": "utility-command",
                "attempt": 1,
                "dispatch_token": "dispatch-secret",
            },
            transient=False,
        )

        self.store.recover_startup()
        commands = self.store.list_recovery_commands()

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["kind"], "utility")
        self.assertEqual(commands[0]["job_id"], "utility-job")
        self.assertEqual(commands[0]["event_sequence_start"], 3)
        self.assertNotIn("payload", commands[0])
        self.assertTrue(self.store.mark_recovery_reported("utility-command"))
        self.assertEqual(self.store.list_recovery_commands(), [])

    def test_recovery_event_batch_and_report_fence_commit_atomically_once(self):
        envelope = job_envelope("recovery-command", "recovery-job")
        envelope["job"]["kind"] = "storage_upload"
        self.store.accept(envelope)
        self.store.set_status("recovery-command", "running", only_from=("accepted",))
        self.store.recover_startup()
        self.store.seed_sequence("recovery-job", 10)

        payloads = [
            {"status": "running", "event_type": "storage.recovery_batch", "transient": False},
            {"status": "failed", "event_type": "storage.batch_interrupted", "transient": False},
        ]
        sequences = self.store.append_recovery_events_once(
            "recovery-command",
            "recovery-job",
            payloads,
            reported_phase="reconciliation_reported",
        )
        replay = self.store.append_recovery_events_once(
            "recovery-command",
            "recovery-job",
            payloads,
            reported_phase="reconciliation_reported",
        )

        self.assertEqual(sequences, [11, 12])
        self.assertIsNone(replay)
        self.assertEqual(self.store.list_storage_reconciliation_commands(), [])
        with self.store._db() as db:
            events = db.execute(
                "SELECT sequence,event_json FROM worker_event_outbox WHERE job_id=? ORDER BY sequence",
                ("recovery-job",),
            ).fetchall()
            command = db.execute(
                "SELECT phase FROM worker_commands WHERE command_id=?",
                ("recovery-command",),
            ).fetchone()
        self.assertEqual([row["sequence"] for row in events], [11, 12])
        self.assertEqual(command["phase"], "reconciliation_reported")

    def test_startup_resumes_tts_synthesis_checkpoint_but_not_delivery(self):
        synthesis = job_envelope("tts-synthesis", "job-tts-synthesis")
        synthesis["job"]["kind"] = "tts"
        synthesis["job"]["payload"] = {"title": "Example", "text": "private text"}
        delivery = job_envelope("tts-delivery", "job-tts-delivery")
        delivery["job"]["kind"] = "tts"
        delivery["job"]["payload"] = {"title": "Example", "text": "private text"}
        self.store.accept(synthesis)
        self.store.accept(delivery)
        for envelope, phase in ((synthesis, "synthesizing"), (delivery, "telegram_delivery")):
            self.store.set_status(envelope["command_id"], "running", only_from=("accepted",))
            self.store.append_event(
                envelope["job_id"],
                {
                    "status": "running",
                    "event_type": "tts.phase",
                    "phase": phase,
                    "progress": {"phase": phase},
                    "command_id": envelope["command_id"],
                    "attempt": 1,
                    "dispatch_token": envelope["dispatch_token"],
                },
                transient=False,
            )

        WorkerCommandStore(self.path).recover_startup()
        self.assertEqual(self.store.get("tts-synthesis")["status"], "accepted")
        self.assertEqual(self.store.get("tts-synthesis")["phase"], "recovered")
        self.assertEqual(self.store.get("tts-delivery")["status"], "needs_reconciliation")

    def test_storage_upload_recovery_keeps_completed_and_pending_items_without_replaying_inflight(self):
        envelope = job_envelope("storage-command", "storage-job", attempt=3)
        envelope["job"]["kind"] = "storage_upload"
        self.store.accept(envelope)
        self.store.set_status("storage-command", "running", only_from=("accepted",))
        self.store.record_storage_upload_item(
            "storage-command", "ambiguous.txt", file_name="ambiguous.txt",
            status="sending", attempt=2, profile="archive",
            caption="storage/archive/ambiguous.txt",
        )
        self.store.record_storage_upload_item(
            "storage-command", "done.txt", file_name="done.txt",
            status="succeeded", attempt=1, profile="default", message_id=44,
            result_item={"upload_id": "upload-done", "channel_message_id": 44},
        )
        self.store.record_storage_upload_item(
            "storage-command", "waiting.txt", file_name="waiting.txt",
            status="pending", attempt=0, retryable=True,
        )

        recovered = WorkerCommandStore(self.path)
        report = recovered.recover_startup()
        items = {item["path"]: item for item in recovered.storage_upload_items("storage-command")}

        self.assertEqual(report["needs_reconciliation"], 1)
        self.assertEqual(items["ambiguous.txt"]["status"], "needs_reconciliation")
        self.assertFalse(items["ambiguous.txt"]["retryable"])
        self.assertEqual(items["ambiguous.txt"]["profile"], "archive")
        self.assertEqual(items["ambiguous.txt"]["attempt"], 2)
        self.assertEqual(items["ambiguous.txt"]["caption"], "storage/archive/ambiguous.txt")
        self.assertEqual(items["done.txt"]["status"], "succeeded")
        self.assertEqual(items["done.txt"]["uploaded_item"]["upload_id"], "upload-done")
        self.assertEqual(items["waiting.txt"]["status"], "pending")
        self.assertTrue(items["waiting.txt"]["retryable"])
        commands = recovered.list_storage_reconciliation_commands()
        self.assertEqual(commands[0]["job_id"], "storage-job")
        self.assertEqual(commands[0]["attempt"], 3)
        durable_job_items = recovered.storage_upload_items_for_job("storage-job")
        self.assertIsNotNone(durable_job_items)
        self.assertEqual(durable_job_items["items"][0]["caption"], "storage/archive/ambiguous.txt")
        self.assertTrue(recovered.mark_storage_reconciliation_reported("storage-command"))
        self.assertEqual(recovered.list_storage_reconciliation_commands(), [])

    def test_event_sequence_and_payload_survive_retry_and_restart(self):
        self.store.seed_sequence("job-event", 8)
        sequence = self.store.append_event(
            "job-event",
            {"status": "running", "event_type": "progress", "command_id": "cmd", "attempt": 2, "dispatch_token": "fence"},
            transient=False,
        )
        self.assertEqual(sequence, 9)
        claimed = self.store.claim_event()
        self.assertEqual(claimed[2], 9)
        self.assertEqual(claimed[3]["dispatch_token"], "fence")
        self.assertTrue(self.store.retry_event(claimed[0], claimed[4], "TimeoutError"))
        with self.store._db() as db:
            db.execute("UPDATE worker_event_outbox SET available_at='2000-01-01T00:00:00+00:00'")
        recovered = WorkerCommandStore(self.path)
        recovered.recover_startup()
        resent = recovered.claim_event()
        self.assertEqual(resent[2], 9)
        self.assertEqual(resent[3], claimed[3])
        self.assertTrue(
            recovered.acknowledge_event(resent[0], resent[4], accepted=True)
        )
        self.assertEqual(recovered.pending_event_count(), 0)

    def test_retry_write_surfaces_sqlite_busy_then_commits_after_lock_releases(self):
        self.store.append_event("busy-job", {"event_type": "progress"}, transient=False)
        claimed = self.store.claim_event()
        blocker = sqlite3.connect(self.path, timeout=0, isolation_level=None)
        try:
            blocker.execute("BEGIN IMMEDIATE")
            started = time.monotonic()
            with self.assertRaises(sqlite3.OperationalError):
                self.store.retry_event(claimed[0], claimed[4], "TimeoutError")
            self.assertLess(time.monotonic() - started, 2.0)
        finally:
            blocker.rollback()
            blocker.close()

        self.assertTrue(self.store.retry_event(claimed[0], claimed[4], "TimeoutError"))
        with self.store._db() as db:
            row = db.execute(
                "SELECT status,last_error,lease_token,lease_until FROM worker_event_outbox WHERE id=?",
                (claimed[0],),
            ).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["last_error"], "TimeoutError")
        self.assertIsNone(row["lease_token"])
        self.assertIsNone(row["lease_until"])

    def test_retry_after_ack_cannot_put_event_back_into_pending(self):
        self.store.append_event("ack-job", {"event_type": "completed"}, transient=False)
        claimed = self.store.claim_event()

        self.assertTrue(
            self.store.acknowledge_event(claimed[0], claimed[4], accepted=True)
        )
        self.assertFalse(
            self.store.retry_event(claimed[0], claimed[4], "TimeoutError")
        )
        with self.store._db() as db:
            row = db.execute(
                "SELECT status FROM worker_event_outbox WHERE id=?", (claimed[0],)
            ).fetchone()
        self.assertEqual(row["status"], "acked")

    def test_concurrent_event_retry_and_append_keep_sequences_and_state_consistent(self):
        self.store.append_event(
            "concurrent-job", {"event_type": "started"}, transient=False
        )
        claimed = self.store.claim_event()
        barrier = threading.Barrier(3)
        failures = []

        def retry():
            try:
                barrier.wait()
                self.store.retry_event(claimed[0], claimed[4], "TimeoutError")
            except Exception as exc:
                failures.append(exc)

        def append():
            try:
                barrier.wait()
                self.store.append_event(
                    "concurrent-job", {"event_type": "progress"}, transient=True
                )
            except Exception as exc:
                failures.append(exc)

        threads = [threading.Thread(target=retry), threading.Thread(target=append)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=2)

        self.assertFalse(failures)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        with self.store._db() as db:
            rows = db.execute(
                "SELECT sequence,status FROM worker_event_outbox WHERE job_id=? ORDER BY sequence",
                ("concurrent-job",),
            ).fetchall()
        self.assertEqual([row["sequence"] for row in rows], [2, 3])
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[1]["status"], "pending")

    def test_event_delivery_stats_are_aggregate_and_do_not_include_event_payload(self):
        self.store.append_event(
            "stats-job",
            {"event_type": "progress", "private_value": "must-not-appear"},
            transient=False,
        )
        claimed = self.store.claim_event()
        self.store.retry_event(claimed[0], claimed[4], "TimeoutError")

        stats = self.store.event_delivery_stats()

        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["sending"], 0)
        self.assertEqual(stats["retry_count"], 0)
        self.assertEqual(stats["last_error_type"], "TimeoutError")
        self.assertNotIn("private_value", str(stats))
        self.assertNotIn("must-not-appear", str(stats))

    def test_expired_event_lease_is_reclaimed_without_restart_and_fences_old_ack(self):
        self.store.append_event("lease-job", {"event_type": "started"}, transient=False)
        old_claim = self.store.claim_event()
        with self.store._db() as db:
            db.execute(
                "UPDATE worker_event_outbox SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?",
                (old_claim[0],),
            )

        new_claim = self.store.claim_event()
        self.assertIsNotNone(new_claim)
        self.assertEqual(new_claim[:4], old_claim[:4])
        self.assertNotEqual(new_claim[4], old_claim[4])
        self.assertFalse(
            self.store.acknowledge_event(old_claim[0], old_claim[4], accepted=True)
        )
        self.assertEqual(self.store.pending_event_count(), 1)
        self.assertTrue(
            self.store.acknowledge_event(new_claim[0], new_claim[4], accepted=True)
        )
        self.assertEqual(self.store.pending_event_count(), 0)

    def test_startup_recovers_event_in_flight_with_a_new_lease_token(self):
        self.store.append_event(
            "restart-job", {"event_type": "completed"}, transient=False
        )
        old_claim = self.store.claim_event()

        recovered = WorkerCommandStore(self.path)
        report = recovered.recover_startup()
        new_claim = recovered.claim_event()

        self.assertEqual(report["events_recovered"], 1)
        self.assertIsNotNone(new_claim)
        self.assertEqual(new_claim[2:4], old_claim[2:4])
        self.assertNotEqual(new_claim[4], old_claim[4])
        self.assertFalse(
            recovered.acknowledge_event(old_claim[0], old_claim[4], accepted=True)
        )

    def test_expired_predecessor_is_reclaimed_before_next_event_for_same_job(self):
        first = self.store.append_event(
            "ordered-job", {"event_type": "progress"}, transient=False
        )
        second = self.store.append_event(
            "ordered-job",
            {"event_type": "completed", "status": "succeeded"},
            transient=False,
        )
        first_claim = self.store.claim_event()
        with self.store._db() as db:
            db.execute(
                "UPDATE worker_event_outbox SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?",
                (first_claim[0],),
            )

        reclaimed = self.store.claim_event()
        self.assertEqual(reclaimed[2], first)
        self.assertNotEqual(reclaimed[2], second)
        self.assertTrue(
            self.store.acknowledge_event(reclaimed[0], reclaimed[4], accepted=True)
        )
        terminal = self.store.claim_event()
        self.assertEqual(terminal[2], second)
        self.assertTrue(
            self.store.acknowledge_event(terminal[0], terminal[4], accepted=True)
        )

    def test_same_outbox_delivers_events_for_distinct_worker_job_kinds(self):
        job_kinds = ("export", "storage_upload", "tts", "utility", "quickmode")
        for job_kind in job_kinds:
            self.store.append_event(
                f"{job_kind}-job",
                {"job_kind": job_kind, "event_type": "completed", "status": "succeeded"},
                transient=False,
            )

        delivered = []
        while (claimed := self.store.claim_event()) is not None:
            delivered.append(claimed[3]["job_kind"])
            self.assertTrue(
                self.store.acknowledge_event(claimed[0], claimed[4], accepted=True)
            )

        self.assertCountEqual(delivered, job_kinds)
        self.assertEqual(self.store.pending_event_count(), 0)

    def test_outbox_yields_to_other_jobs_while_one_job_has_a_large_backlog(self):
        for index in range(20):
            self.store.append_event(
                "large-recovery-job",
                {"event_type": f"recovery-{index}", "index": index},
                transient=False,
            )
        self.store.append_event(
            "interactive-job",
            {"event_type": "completed", "status": "succeeded"},
            transient=False,
        )

        first = self.store.claim_event()
        self.assertEqual(first[1], "large-recovery-job")
        self.assertTrue(
            self.store.acknowledge_event(first[0], first[4], accepted=True)
        )
        second = self.store.claim_event()

        self.assertEqual(second[1], "interactive-job")
        self.assertTrue(
            self.store.acknowledge_event(second[0], second[4], accepted=True)
        )
        remaining = self.store.claim_event()
        self.assertEqual(remaining[1], "large-recovery-job")

    def test_terminal_event_supersedes_backlog_and_keeps_latest_snapshots(self):
        job_id = "cancelled-job-with-event-backlog"
        for index in range(80):
            self.store.append_event(
                job_id,
                {
                    "event_type": "command.completed",
                    "status": "running",
                    "command_index": index,
                },
                transient=False,
            )
        side_effect_sequence = self.store.append_event(
            job_id,
            {
                "event_type": "storage.item_uploaded",
                "status": "running",
                "result": {"item": {"original_name": "already-uploaded.bin"}},
            },
            transient=False,
        )
        progress_sequence = self.store.append_event(
            job_id,
            {"event_type": "progress.snapshot", "status": "running", "progress": {"current": 7}},
            transient=True,
        )
        log_sequence = self.store.append_event(
            job_id,
            {"event_type": "log.snapshot", "status": "running", "progress": {"log_tail": "last output"}},
            transient=False,
        )
        terminal_sequence = self.store.append_event(
            job_id,
            {"event_type": "cancelled", "status": "cancelled", "progress": {"phase": "cancelled"}},
            transient=False,
        )

        delivered = []
        while (claimed := self.store.claim_event()) is not None:
            delivered.append((claimed[2], claimed[3]["event_type"]))
            self.assertTrue(
                self.store.acknowledge_event(claimed[0], claimed[4], accepted=True)
            )

        self.assertEqual(
            delivered,
            [
                (side_effect_sequence, "storage.item_uploaded"),
                (progress_sequence, "progress.snapshot"),
                (log_sequence, "log.snapshot"),
                (terminal_sequence, "cancelled"),
            ],
        )
        self.assertEqual(len(delivered), 4)

    def test_failed_terminal_event_supersedes_old_command_milestones(self):
        job_id = "failed-utility-with-event-backlog"
        for index in range(80):
            self.store.append_event(
                job_id,
                {
                    "event_type": "command.completed",
                    "status": "running",
                    "command_index": index,
                },
                transient=False,
            )
        side_effect_sequence = self.store.append_event(
            job_id,
            {
                "event_type": "storage.item_uploaded",
                "status": "running",
                "result": {"item": {"original_name": "already-uploaded.bin"}},
            },
            transient=False,
        )
        progress_sequence = self.store.append_event(
            job_id,
            {"event_type": "progress.snapshot", "status": "running", "progress": {"current": 7}},
            transient=True,
        )
        log_sequence = self.store.append_event(
            job_id,
            {"event_type": "log.snapshot", "status": "running", "progress": {"log_tail": "last output"}},
            transient=False,
        )
        terminal_sequence = self.store.append_event(
            job_id,
            {"event_type": "utility.completed", "status": "failed", "error": {"code": "UTILITY_FAILED"}},
            transient=False,
        )

        delivered = []
        while (claimed := self.store.claim_event()) is not None:
            delivered.append((claimed[2], claimed[3]["event_type"]))
            self.assertTrue(
                self.store.acknowledge_event(claimed[0], claimed[4], accepted=True)
            )

        self.assertEqual(
            delivered,
            [
                (side_effect_sequence, "storage.item_uploaded"),
                (progress_sequence, "progress.snapshot"),
                (log_sequence, "log.snapshot"),
                (terminal_sequence, "utility.completed"),
            ],
        )
        self.assertEqual(len(delivered), 4)

    def test_terminal_compaction_preserves_latest_command_result_per_runtime_profile(self):
        job_id = "terminal-command-results"
        latest_upload_result = None
        for index in range(80):
            latest_upload_result = self.store.append_event(
                job_id,
                {
                    "event_type": "command.completed",
                    "status": "running",
                    "result": {
                        "runtime": "upload",
                        "profile": "ruth2",
                        "returncode": 1 if index < 79 else 0,
                        "output_tail": [f"result-{index}"],
                    },
                },
                transient=False,
            )
        export_result = self.store.append_event(
            job_id,
            {
                "event_type": "command.completed",
                "status": "running",
                "result": {
                    "runtime": "export",
                    "profile": "default",
                    "returncode": 0,
                },
            },
            transient=False,
        )
        upload_result = self.store.append_event(
            job_id,
            {
                "event_type": "command.completed",
                "status": "running",
                "result": {
                    "runtime": "upload",
                    "profile": "irang",
                    "returncode": 0,
                },
            },
            transient=False,
        )
        progress_sequence = self.store.append_event(
            job_id,
            {"event_type": "progress.snapshot", "status": "running", "progress": {"current": 9}},
            transient=True,
        )
        terminal_sequence = self.store.append_event(
            job_id,
            {"event_type": "utility.completed", "status": "failed"},
            transient=False,
        )

        delivered = []
        while (claimed := self.store.claim_event()) is not None:
            payload = claimed[3]
            result = payload.get("result") or {}
            delivered.append((
                claimed[2],
                payload["event_type"],
                result.get("runtime"),
                result.get("profile"),
                (result.get("output_tail") or [None])[0],
            ))
            self.assertTrue(
                self.store.acknowledge_event(claimed[0], claimed[4], accepted=True)
            )

        self.assertEqual(
            delivered,
            [
                (latest_upload_result, "command.completed", "upload", "ruth2", "result-79"),
                (export_result, "command.completed", "export", "default", None),
                (upload_result, "command.completed", "upload", "irang", None),
                (progress_sequence, "progress.snapshot", None, None, None),
                (terminal_sequence, "utility.completed", None, None, None),
            ],
        )

    def test_startup_compacts_legacy_backlog_before_pending_failed_terminal(self):
        legacy_path = Path(self.temp.name) / "legacy-terminal-backlog.sqlite3"
        legacy_store = WorkerCommandStore(legacy_path)
        job_id = "legacy-failed-utility"
        for index in range(8):
            legacy_store.append_event(
                job_id,
                {"event_type": "command.completed", "status": "running", "command_index": index},
                transient=False,
            )
        side_effect_sequence = legacy_store.append_event(
            job_id,
            {"event_type": "storage.item_uploaded", "status": "running"},
            transient=False,
        )
        progress_sequence = legacy_store.append_event(
            job_id,
            {"event_type": "progress.snapshot", "status": "running", "progress": {"current": 7}},
            transient=True,
        )
        log_sequence = legacy_store.append_event(
            job_id,
            {"event_type": "log.snapshot", "status": "running", "progress": {"log_tail": "last output"}},
            transient=False,
        )
        terminal_sequence = legacy_store.append_event(
            job_id,
            {"event_type": "utility.completed", "status": "failed"},
            transient=False,
        )

        # Recreate the stuck rows written by the old implementation, where
        # failed terminal events did not compact command telemetry.
        with sqlite3.connect(legacy_path) as db:
            db.execute(
                "UPDATE worker_event_outbox SET status='pending',last_error=NULL "
                "WHERE job_id=? AND status='superseded'",
                (job_id,),
            )

        recovered = WorkerCommandStore(legacy_path)
        delivered = []
        while (claimed := recovered.claim_event()) is not None:
            delivered.append((claimed[2], claimed[3]["event_type"]))
            self.assertTrue(
                recovered.acknowledge_event(claimed[0], claimed[4], accepted=True)
            )

        self.assertEqual(
            delivered,
            [
                (side_effect_sequence, "storage.item_uploaded"),
                (progress_sequence, "progress.snapshot"),
                (log_sequence, "log.snapshot"),
                (terminal_sequence, "utility.completed"),
            ],
        )

    def test_cancel_request_supersedes_telemetry_but_preserves_side_effects(self):
        job_id = "cancel-request-with-event-backlog"
        for index in range(80):
            self.store.append_event(
                job_id,
                {
                    "event_type": "command.completed",
                    "status": "running",
                    "command_index": index,
                    "result": {
                        "runtime": "upload",
                        "profile": "ruth2",
                        "returncode": index,
                    },
                },
                transient=False,
            )
        latest_command_sequence = self.store.append_event(
            job_id,
            {
                "event_type": "command.completed",
                "status": "running",
                "result": {
                    "runtime": "upload",
                    "profile": "ruth2",
                    "returncode": 0,
                },
            },
            transient=False,
        )
        side_effect_sequence = self.store.append_event(
            job_id,
            {
                "event_type": "storage.item_uploaded",
                "status": "running",
                "result": {"item": {"original_name": "already-uploaded.bin"}},
            },
            transient=False,
        )
        in_flight = self.store.claim_event()
        self.assertEqual(in_flight[1], job_id)
        self.assertEqual(in_flight[3]["event_type"], "command.completed")
        other_job_sequence = self.store.append_event(
            "unrelated-job",
            {"event_type": "progress", "status": "running"},
            transient=False,
        )
        progress_sequence = self.store.append_event(
            job_id,
            {"event_type": "progress.snapshot", "status": "running", "progress": {"current": 7}},
            transient=True,
        )
        log_sequence = self.store.append_event(
            job_id,
            {"event_type": "log.snapshot", "status": "running", "progress": {"log_tail": "last output"}},
            transient=False,
        )
        cancel_sequence = self.store.append_event(
            job_id,
            {
                "event_type": "cancel.requested",
                "status": "running",
                "progress": {"cancel_request": {"status": "accepted"}},
            },
            transient=False,
        )

        delivered = []
        while (claimed := self.store.claim_event()) is not None:
            delivered.append((claimed[1], claimed[2], claimed[3]["event_type"]))
            self.assertTrue(
                self.store.acknowledge_event(claimed[0], claimed[4], accepted=True)
            )

        self.assertCountEqual(
            [(item[0], item[2]) for item in delivered],
            [
                (job_id, "storage.item_uploaded"),
                (job_id, "command.completed"),
                (job_id, "cancel.requested"),
                ("unrelated-job", "progress"),
            ],
        )
        command_result = next(
            item for item in delivered if item[2] == "command.completed"
        )
        self.assertEqual(command_result[1], latest_command_sequence)
        self.assertLess(
            next(index for index, item in enumerate(delivered) if item[2] == "command.completed"),
            next(index for index, item in enumerate(delivered) if item[2] == "cancel.requested"),
        )
        self.assertLess(progress_sequence, cancel_sequence)
        self.assertLess(log_sequence, cancel_sequence)
        self.assertFalse(
            self.store.acknowledge_event(
                in_flight[0], in_flight[4], accepted=True
            )
        )

    def test_active_event_predecessor_lookup_uses_a_dedicated_index(self):
        with sqlite3.connect(self.path) as db:
            plan = db.execute(
                "EXPLAIN QUERY PLAN SELECT 1 FROM worker_event_outbox p "
                "WHERE p.job_id=? AND p.sequence<? AND p.status IN ('pending','sending')",
                ("job-with-history", 100),
            ).fetchall()

        self.assertTrue(
            any("idx_worker_event_outbox_active_job_sequence" in row[3] for row in plan),
            plan,
        )

    def test_event_outbox_schema_migrates_legacy_sending_rows(self):
        legacy_path = Path(self.temp.name) / "legacy-worker-journal.sqlite3"
        db = sqlite3.connect(legacy_path)
        db.executescript(
            """
            CREATE TABLE worker_event_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_json TEXT NOT NULL,
                transient INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                available_at TEXT NOT NULL,
                last_error TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(job_id, sequence)
            );
            INSERT INTO worker_event_outbox(job_id,sequence,event_json,status,available_at,created_at)
            VALUES ('legacy-job',2,'{}','sending','2000-01-01T00:00:00+00:00','2000-01-01T00:00:00+00:00');
            """
        )
        db.close()

        migrated = WorkerCommandStore(legacy_path)
        reclaimed = migrated.claim_event()
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed[1], "legacy-job")
        self.assertEqual(reclaimed[2], 2)

    def test_terminal_event_ack_resolves_a_recovered_uncertain_command(self):
        self.store.accept(job_envelope())
        self.store.set_status("command-1", "running", only_from=("accepted",))
        self.store.recover_startup()
        self.assertEqual(self.store.get("command-1")["status"], "needs_reconciliation")
        sequence = self.store.append_event(
            "job-1",
            {
                "status": "succeeded",
                "event_type": "completed",
                "command_id": "command-1",
                "attempt": 1,
                "dispatch_token": "dispatch-secret",
            },
            transient=False,
        )
        event = self.store.claim_event()
        self.assertEqual(event[2], sequence)
        self.store.acknowledge_event(event[0], event[4], accepted=True)
        self.assertEqual(self.store.get("command-1")["status"], "succeeded")

    def test_publisher_persists_terminal_event_without_waiting_for_backend(self):
        publisher = WorkerEventPublisher("http://backend.invalid", "token")
        publisher.attach_outbox(self.store)
        publisher.bind_command("job-1", "command-1", 1, "dispatch-secret")
        with patch("tme3bot.worker.executor_support.request_json", side_effect=AssertionError("must not perform HTTP in emit")):
            publisher.emit("job-1", "succeeded", "completed", result={"ok": True})
        self.assertEqual(self.store.pending_event_count(), 1)
        event = self.store.claim_event()
        self.assertEqual(event[3]["sequence"], 2)
        self.assertEqual(event[3]["command_id"], "command-1")
        self.assertEqual(event[3]["dispatch_token"], "dispatch-secret")

    def test_sender_retries_lost_ack_with_the_same_sequence(self):
        publisher = WorkerEventPublisher("http://backend.invalid", "token")
        publisher.attach_outbox(self.store)
        publisher.emit("job-retry", "succeeded", "completed")
        second_request = threading.Event()
        sent_sequences = []

        def backend(*args, **kwargs):
            del kwargs
            sent_sequences.append(args[4]["sequence"])
            if len(sent_sequences) == 1:
                raise TimeoutError("ACK was lost")
            second_request.set()
            return {"ok": True, "accepted": True}

        with patch("tme3bot.worker.executor_support.request_json", side_effect=backend):
            publisher.start_sender()
            try:
                self.assertTrue(second_request.wait(4))
                deadline = time.monotonic() + 2
                while self.store.pending_event_count() and time.monotonic() < deadline:
                    time.sleep(0.01)
            finally:
                publisher.stop_sender()
        self.assertEqual(sent_sequences, [2, 2])
        self.assertEqual(self.store.pending_event_count(), 0)

    def test_sender_survives_retry_write_failure_and_reclaims_expired_lease(self):
        lease_store = WorkerCommandStore(
            Path(self.temp.name) / "short-lease.sqlite3", event_lease_seconds=1
        )
        publisher = WorkerEventPublisher("http://backend.invalid", "token")
        publisher.attach_outbox(lease_store)
        publisher.emit("job-retry-lock", "running", "progress.snapshot")
        delivered_after_reclaim = threading.Event()
        request_count = []
        retry_count = []
        original_retry = lease_store.retry_event

        def backend(*_args, **_kwargs):
            request_count.append(1)
            if len(request_count) == 1:
                raise TimeoutError("simulated backend timeout")
            delivered_after_reclaim.set()
            return {"ok": True, "accepted": True}

        def retry_with_one_transient_lock(event_id, lease_token, error_type):
            retry_count.append(1)
            if len(retry_count) == 1:
                raise sqlite3.OperationalError("database is locked")
            return original_retry(event_id, lease_token, error_type)

        with patch(
            "tme3bot.worker.executor_support.request_json", side_effect=backend
        ), patch.object(lease_store, "retry_event", side_effect=retry_with_one_transient_lock):
            publisher.start_sender()
            try:
                self.assertTrue(delivered_after_reclaim.wait(4))
                deadline = time.monotonic() + 1
                while lease_store.pending_event_count() and time.monotonic() < deadline:
                    time.sleep(0.01)
            finally:
                publisher.stop_sender()

        self.assertEqual(len(request_count), 2)
        self.assertEqual(len(retry_count), 1)
        self.assertEqual(lease_store.pending_event_count(), 0)

    def test_only_unsent_transient_progress_is_coalesced(self):
        first = self.store.append_event("job-progress", {"event_type": "p1"}, transient=True)
        milestone = self.store.append_event("job-progress", {"event_type": "started"}, transient=False)
        latest = self.store.append_event("job-progress", {"event_type": "p2"}, transient=True)
        with self.store._db() as db:
            statuses = {
                int(row["sequence"]): row["status"]
                for row in db.execute(
                    "SELECT sequence,status FROM worker_event_outbox WHERE job_id='job-progress'"
                )
            }
        self.assertEqual(statuses[first], "superseded")
        self.assertEqual(statuses[milestone], "pending")
        self.assertEqual(statuses[latest], "pending")
        claimed = self.store.claim_event()
        self.assertEqual(claimed[2], milestone)
        self.assertTrue(
            self.store.acknowledge_event(claimed[0], claimed[4], accepted=True)
        )

    def test_runner_admits_duplicate_submit_once_through_existing_executor_queue(self):
        entered = threading.Event()

        class FakeExecutor:
            def __init__(self):
                self.commands = []
                self._durable_admission_lock = threading.RLock()

            def enqueue(self, command):
                self.commands.append(command)
                entered.set()
                return 1

        executor = FakeExecutor()
        runner = WorkerCommandRunner(self.store, executor)
        runner.accept(job_envelope())
        runner.accept(job_envelope())
        runner.start()
        try:
            self.assertTrue(entered.wait(2))
            deadline = time.monotonic() + 2
            while self.store.get("command-1")["status"] == "claimed" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(executor.commands), 1)
            self.assertEqual(executor.commands[0]["dispatch_token"], "dispatch-secret")
            self.assertEqual(self.store.get("command-1")["status"], "queued")
        finally:
            runner.stop()

    def test_operation_runner_requires_a_registered_handler_and_records_completion(self):
        envelope = {
            "command_id": "operation-command",
            "operation_id": "operation-2",
            "attempt": 1,
            "dispatch_token": "token",
            "operation": {"kind": "test.operation"},
        }
        runner = WorkerCommandRunner(self.store, object())
        runner.accept(envelope)
        runner.register_operation_handler("test.operation", lambda _command: None)
        runner.start()
        try:
            deadline = time.monotonic() + 2
            while self.store.get("operation-command")["status"] not in {"succeeded", "failed"} and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(self.store.get("operation-command")["status"], "succeeded")
        finally:
            runner.stop()


if __name__ == "__main__":
    unittest.main()
