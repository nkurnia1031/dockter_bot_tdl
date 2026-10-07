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

    def test_jobless_operation_command_is_supported(self):
        envelope = {
            "command_id": "operation-command",
            "operation_id": "profile-sync-1",
            "attempt": 1,
            "dispatch_token": "operation-token",
            "operation": {"kind": "profile.sync", "profile": "default", "worker": "local"},
        }
        snapshot, replayed = self.store.accept(envelope)
        self.assertFalse(replayed)
        self.assertIsNone(snapshot["job_id"])
        self.assertEqual(snapshot["operation_id"], "profile-sync-1")

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
        self.store.retry_event(claimed[0], "TimeoutError")
        with self.store._db() as db:
            db.execute("UPDATE worker_event_outbox SET available_at='2000-01-01T00:00:00+00:00'")
        recovered = WorkerCommandStore(self.path)
        recovered.recover_startup()
        resent = recovered.claim_event()
        self.assertEqual(resent[2], 9)
        self.assertEqual(resent[3], claimed[3])
        recovered.acknowledge_event(resent[0], accepted=True)
        self.assertEqual(recovered.pending_event_count(), 0)

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
        self.store.acknowledge_event(event[0], accepted=True)
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
        self.assertEqual(self.store.claim_event()[2], milestone)

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
