from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tme3bot.application.operations import OperationsService, PreparedOperation
from tme3bot.domain.models import Actor, DomainError, Job, JobStatus
from tme3bot.domain.operations import OperationStatus, ensure_operation_transition
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.infrastructure.operation_store import SqliteOperationStore


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "app.db"
        self.jobs = SqliteJobRepository(self.path)
        self.store = SqliteOperationStore(self.jobs)
        self.service = OperationsService(self.store)
        self.actor = Actor(42, "default")

    def register_simple(self):
        self.service.register_handler(
            "test.action",
            lambda actor, target, input_data: PreparedOperation(
                profile=actor.profile,
                target={"worker": "local"},
                private_payload={"secret": input_data.get("secret", "")},
            ),
        )

    def submit(self, key="key-submit-0001", secret="private"):
        self.register_simple()
        return self.service.submit(
            self.actor, kind="test.action", target={"worker": "ignored"},
            input_data={"secret": secret}, idempotency_key=key,
        )

    def test_submit_persists_private_payload_and_is_idempotent(self):
        operation, created = self.submit()
        duplicate, created_again = self.submit()
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(operation.id, duplicate.id)
        self.assertEqual(operation.status, OperationStatus.QUEUED)
        self.assertEqual(operation.revision, 1)
        self.assertEqual(self.store.get_private_payload(operation.id), {"secret": "private"})
        self.assertNotIn("secret", operation.to_public())
        with self.assertRaises(DomainError) as raised:
            self.submit(secret="changed")
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_KEY_REUSED")

    def test_unknown_handler_is_rejected_without_creating_operation(self):
        with self.assertRaises(DomainError) as raised:
            self.service.submit(
                self.actor, kind="arbitrary.command", target={}, input_data={},
                idempotency_key="key-unknown-0001",
            )
        self.assertEqual(raised.exception.code, "OPERATION_KIND_UNAVAILABLE")
        with self.jobs._db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 0)

    def test_job_plan_operation_and_outbox_share_one_atomic_transaction(self):
        def prepare(actor, target, input_data):
            job = Job(
                id="job-atomic-1", kind="export", profile=actor.profile,
                actor_user_id=actor.telegram_user_id, worker="local",
                status=JobStatus.QUEUED, payload={"phase": "queued"},
            )
            return PreparedOperation(
                profile=actor.profile, target={"worker": "local"},
                private_payload={"chat_ref": input_data["chat_ref"]},
                job=job,
                execution_plan={"resource_keys": ["export:default"], "queue_group": "export", "lane": "export"},
                command_payload={"chat_ref": input_data["chat_ref"]},
            )

        self.service.register_handler("test.export", prepare)
        operation, _ = self.service.submit(
            self.actor, kind="test.export", target={}, input_data={"chat_ref": "channel"},
            idempotency_key="key-job-atomic-0001",
        )
        self.assertEqual(self.jobs.get("job-atomic-1").status, JobStatus.QUEUED)
        self.assertEqual(self.jobs.execution_plan("job-atomic-1")["lane"], "export")
        self.assertEqual(self.jobs.command_payload("job-atomic-1"), {"chat_ref": "channel"})
        self.assertEqual(operation.job_id, "job-atomic-1")
        outbox = self.store.claim_outbox()
        self.assertEqual(outbox[0]["payload"], {"attempt": 1, "operation_id": operation.id})
        self.assertNotIn("chat_ref", outbox[0]["payload"])

    def test_failure_mid_bundle_rolls_back_operation_idempotency_payload_and_outbox(self):
        self.jobs.create(Job(
            id="job-duplicate", kind="export", profile="default", actor_user_id=42,
            worker="local", status=JobStatus.QUEUED, payload={},
        ))

        def prepare(actor, target, input_data):
            return PreparedOperation(
                profile="default", target={}, private_payload={"secret": "hidden"},
                job=Job(
                    id="job-duplicate", kind="export", profile="default", actor_user_id=42,
                    worker="local", status=JobStatus.QUEUED, payload={},
                ),
                execution_plan={"resource_keys": [], "queue_group": "", "lane": "export"},
                command_payload={},
            )

        self.service.register_handler("test.atomic-failure", prepare)
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.submit(
                self.actor, kind="test.atomic-failure", target={}, input_data={},
                idempotency_key="key-rollback-0001",
            )
        with self.jobs._db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM operation_payloads").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM operation_idempotency").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM operation_outbox").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_retry_reuses_operation_and_outbox_is_restart_safe(self):
        operation, _ = self.submit()
        failed = self.store.transition_from_job(
            operation.id, expected_revision=1, status=OperationStatus.FAILED,
            phase="failed", safe_progress={"job_status": "failed"},
        )
        self.assertEqual(failed.status, OperationStatus.FAILED)
        retried, created = self.service.retry(self.actor, operation.id, "key-retry-0001")
        self.assertTrue(created)
        self.assertEqual(retried.id, operation.id)
        self.assertEqual(retried.attempt, 2)
        duplicate, created_again = self.service.retry(self.actor, operation.id, "key-retry-0001")
        self.assertFalse(created_again)
        self.assertEqual(duplicate.attempt, 2)
        with self.assertRaises(DomainError) as raised:
            self.service.retry(self.actor, operation.id, "key-retry-0002")
        self.assertEqual(raised.exception.code, "OPERATION_NOT_RETRYABLE")

        # A submit emits operation.accepted first; acknowledge it before
        # checking that the retry event survives a store restart.
        accepted = self.store.claim_outbox(limit=1, lease_seconds=60)
        self.assertEqual(accepted[0]["topic"], "operation.accepted")
        self.assertTrue(self.store.acknowledge_outbox(accepted[0]["id"], accepted[0]["lease_token"]))
        claimed = self.store.claim_outbox(limit=1, lease_seconds=60)
        self.assertTrue(claimed)
        self.assertEqual(claimed[0]["topic"], "operation.retry")
        restarted_store = SqliteOperationStore(SqliteJobRepository(self.path))
        self.assertEqual(restarted_store.claim_outbox(limit=10), [])
        self.assertFalse(restarted_store.acknowledge_outbox(claimed[0]["id"], "wrong-token"))
        self.assertTrue(restarted_store.acknowledge_outbox(claimed[0]["id"], claimed[0]["lease_token"]))
        self.assertFalse(restarted_store.acknowledge_outbox(claimed[0]["id"], claimed[0]["lease_token"]))

    def test_visibility_is_per_actor_and_does_not_change_lifecycle_revision(self):
        operation, _ = self.submit()
        dismissed, _ = self.service.set_visibility(self.actor, operation.id, True, "key-hide-0001")
        self.assertTrue(dismissed.dismissed)
        self.assertEqual(dismissed.revision, operation.revision)
        other, next_cursor = self.service.list(Actor(43, "default"))
        self.assertEqual(other, [])
        self.assertIsNone(next_cursor)
        self.assertIsNone(self.store.get_for_actor(operation.id, 43))

    def test_revision_and_terminal_transition_rules(self):
        operation, _ = self.submit()
        updated = self.store.transition_from_job(
            operation.id, expected_revision=1, status=OperationStatus.RUNNING,
            phase="running", safe_progress={"job_status": "running"},
        )
        self.assertEqual(updated.revision, 2)
        self.assertIsNone(self.store.transition_from_job(
            operation.id, expected_revision=1, status=OperationStatus.FAILED,
            phase="failed", safe_progress={},
        ))
        failed = self.store.transition_from_job(
            operation.id, expected_revision=2, status=OperationStatus.FAILED,
            phase="failed", safe_progress={"job_status": "failed"},
        )
        self.assertEqual(failed.error, {"code": "JOB_FAILED", "message": "Pekerjaan gagal."})
        with self.assertRaises(DomainError):
            ensure_operation_transition(failed.status, OperationStatus.RUNNING)


if __name__ == "__main__":
    unittest.main()
