from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Header, HTTPException

from tme3bot.api.routes.queue import register_queue
from tme3bot.application.operations import OperationsService, PreparedOperation
from tme3bot.config import AppConfig
from tme3bot.domain.models import Actor
from tme3bot.domain.operations import OperationStatus
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.infrastructure.operation_store import SqliteOperationStore
from tme3bot.infrastructure.queue_transport import (
    QueueCommandService,
    QueueOutboxPublisher,
    SqliteQueueState,
)


class _FakeConnection:
    def ping(self):
        return True

    def close(self):
        return None


class _FakeJob:
    def __init__(self, job_id: str, args=(), status: str = "queued") -> None:
        self.id = job_id
        self.args = args
        self.status = status
        self.meta = {}
        self.deleted = False

    def delete(self):
        self.deleted = True


class _FakeQueue:
    def __init__(self, *, fail_enqueue: bool = False) -> None:
        self.connection = _FakeConnection()
        self.jobs: dict[str, _FakeJob] = {}
        self.enqueued: list[tuple[object, tuple, dict]] = []
        self.fail_enqueue = fail_enqueue

    def enqueue(self, func, *args, **kwargs):
        self.enqueued.append((func, args, kwargs))
        if self.fail_enqueue:
            raise OSError("simulated redis outage")
        job_id = kwargs["job_id"]
        if kwargs.get("unique") and job_id in self.jobs:
            return self.jobs[job_id]
        job = _FakeJob(job_id, args)
        self.jobs[job_id] = job
        return job

    def fetch_job(self, job_id: str):
        job = self.jobs.get(job_id)
        return None if job and job.deleted else job


class QueueTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "operations.db"
        self.jobs = SqliteJobRepository(self.path)
        self.store = SqliteOperationStore(self.jobs)
        self.operations = OperationsService(self.store)
        self.actor = Actor(7001, "default")
        self.operations.register_handler(
            "test.queue",
            lambda actor, target, input_data: PreparedOperation(
                profile=actor.profile,
                target={"worker": "local"},
                private_payload={"private": input_data.get("private")},
            ),
        )
        self.operation, _ = self.operations.submit(
            self.actor,
            kind="test.queue",
            target={},
            input_data={"private": "must-not-enter-redis"},
            idempotency_key="queue-op-0001",
        )
        with self.jobs._db() as db:
            self.command_id = db.execute(
                "SELECT id FROM operation_outbox WHERE operation_id=? ORDER BY created_at LIMIT 1",
                (self.operation.id,),
            ).fetchone()[0]
        self.queue = _FakeQueue()
        self.publisher = QueueOutboxPublisher(
            self.store,
            "redis://secret@redis.invalid/0",
            operations=self.operations,
            queue=self.queue,
        )

    def _outbox(self):
        with self.jobs._db() as db:
            return dict(db.execute(
                "SELECT * FROM operation_outbox WHERE id=?", (self.command_id,)
            ).fetchone())

    def test_publisher_enqueues_only_identifier_and_acknowledges_after_publish(self):
        self.assertEqual(self.publisher.publish_once(), 1)
        self.assertEqual(len(self.queue.enqueued), 1)
        _, args, options = self.queue.enqueued[0]
        self.assertEqual(args, (self.command_id,))
        self.assertEqual(options["job_id"], self.command_id)
        self.assertTrue(options["unique"])
        self.assertEqual(self._outbox()["status"], "delivered")
        self.assertNotIn("must-not-enter-redis", repr(self.queue.enqueued))

    def test_duplicate_publish_after_receipt_crash_uses_unique_rq_job(self):
        acknowledge = self.store.acknowledge_outbox
        with patch.object(self.store, "acknowledge_outbox", return_value=False):
            self.assertEqual(self.publisher.publish_once(), 0)
        self.assertEqual(len(self.queue.jobs), 1)
        with self.jobs._db() as db:
            db.execute(
                "UPDATE operation_outbox SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?",
                (self.command_id,),
            )
        with patch.object(self.store, "acknowledge_outbox", wraps=acknowledge):
            self.assertEqual(self.publisher.publish_once(), 1)
        self.assertEqual(len(self.queue.jobs), 1)
        self.assertEqual(self._outbox()["status"], "delivered")

    def test_missing_redis_job_is_rebuilt_from_sqlite_outbox(self):
        self.publisher.publish_once()
        self.queue.jobs.clear()  # Simulate Redis losing its volatile queue data.
        self.assertEqual(self.publisher.reconcile_once(), 1)
        self.assertEqual(self._outbox()["status"], "pending")
        self.assertEqual(self.publisher.publish_once(), 1)
        self.assertIn(self.command_id, self.queue.jobs)
        self.assertEqual(self._outbox()["status"], "delivered")

    @unittest.skipUnless(shutil.which("redis-server"), "redis-server binary is not installed")
    def test_disposable_redis_flush_is_rebuilt_from_sqlite(self):
        from redis import Redis

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        process = subprocess.Popen(
            [
                shutil.which("redis-server"),
                "--bind", "127.0.0.1",
                "--port", str(port),
                "--save", "",
                "--appendonly", "no",
                "--dir", self.temp.name,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(process.terminate)
        connection = Redis.from_url(f"redis://127.0.0.1:{port}/0", socket_connect_timeout=1)
        self.addCleanup(connection.close)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                connection.ping()
                break
            except Exception:
                time.sleep(0.1)
        else:
            self.fail("Disposable Redis did not become ready")

        publisher = QueueOutboxPublisher(
            self.store,
            f"redis://127.0.0.1:{port}/0",
            operations=self.operations,
        )
        self.addCleanup(publisher.stop)
        self.assertEqual(publisher.publish_once(), 1)
        queue = publisher._get_queue()
        self.assertIsNotNone(queue.fetch_job(self.command_id))
        connection.flushdb()
        self.assertEqual(publisher.reconcile_once(), 1)
        self.assertEqual(publisher.publish_once(), 1)
        self.assertIsNotNone(queue.fetch_job(self.command_id))

    def test_redis_publish_failure_keeps_operation_durable_and_sets_backoff(self):
        broken = QueueOutboxPublisher(
            self.store,
            "redis://secret@redis.invalid/0",
            operations=self.operations,
            queue=_FakeQueue(fail_enqueue=True),
        )
        self.assertEqual(broken.publish_once(), 0)
        row = self._outbox()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["last_error_code"], "QUEUE_PUBLISH_FAILED")
        self.assertGreater(row["attempts"], 0)
        self.assertEqual(self.store.get_for_actor(self.operation.id, self.actor.telegram_user_id).status, OperationStatus.QUEUED)

    def test_command_lease_fences_concurrent_claims_and_not_ready_has_no_side_effect(self):
        self.publisher.publish_once()
        state = SqliteQueueState(self.store)
        first = state.claim_command(self.command_id, "a" * 32)
        self.assertEqual(first["status"], "claimed")
        self.assertEqual(first["command"]["revision"], 1)
        self.assertEqual(first["command"]["private_payload"], {"private": "must-not-enter-redis"})
        self.assertGreater(first["command"]["transport_attempt"], 0)
        second = state.claim_command(self.command_id, "b" * 32)
        self.assertEqual(second, {"status": "wait", "reason": "command_claimed"})
        self.assertTrue(state.finish_command(self.command_id, "a" * 32, "wait"))

        result = QueueCommandService(self.store).advance(
            self.command_id, "c" * 32, self.operations
        )
        self.assertEqual(result, {"status": "wait", "reason": "not_ready"})
        self.assertEqual(self._outbox()["status"], "delivered")
        self.assertIsNone(self._outbox()["lease_token"])

    def test_registered_handler_consumes_receipt_only_for_matching_lease(self):
        self.publisher.publish_once()
        seen = []
        self.operations.register_command_handler(
            "operation.accepted",
            lambda command: seen.append(command["operation_id"]) or {"status": "accepted"},
        )
        result = QueueCommandService(self.store).advance(
            self.command_id, "d" * 32, self.operations
        )
        self.assertEqual(result, {"status": "accepted"})
        self.assertEqual(seen, [self.operation.id])
        self.assertEqual(self._outbox()["status"], "consumed")

    def test_stale_attempt_is_consumed_without_running_handler(self):
        self.publisher.publish_once()
        failed = self.store.transition_from_job(
            self.operation.id,
            expected_revision=1,
            status=OperationStatus.FAILED,
            phase="failed",
            safe_progress={},
        )
        self.assertEqual(failed.status, OperationStatus.FAILED)
        self.operations.retry(self.actor, self.operation.id, "queue-op-retry-0001")
        result = QueueCommandService(self.store).advance(
            self.command_id, "e" * 32, self.operations
        )
        self.assertEqual(result["status"], "terminal")
        self.assertEqual(self._outbox()["status"], "consumed")

    def test_internal_endpoint_requires_service_auth_and_valid_lease(self):
        app = FastAPI()

        def require_internal(authorization: str | None = Header(default=None)):
            if authorization != "Bearer internal-test-token":
                raise HTTPException(status_code=401, detail="Unauthorized")

        app.state.context = None
        context = SimpleNamespace(
            queue_command_service=SimpleNamespace(
                advance=lambda command_id, lease_claim, operations: {
                    "status": "wait", "reason": "not_ready"
                }
            ),
            operation_service=self.operations,
            queue_publisher=None,
        )
        register_queue(app, context, require_internal=require_internal)

        async def call(method: str, path: str, **kwargs):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

        missing_auth = asyncio.run(call(
            "POST",
            f"/internal/v1/queue/commands/{self.command_id}/advance",
            json={"lease_claim": "f" * 32},
        ))
        self.assertEqual(missing_auth.status_code, 401)
        invalid_claim = asyncio.run(call(
            "POST",
            f"/internal/v1/queue/commands/{self.command_id}/advance",
            headers={"Authorization": "Bearer internal-test-token"},
            json={"lease_claim": "short"},
        ))
        self.assertEqual(invalid_claim.status_code, 422)
        invalid_id = asyncio.run(call(
            "POST",
            "/internal/v1/queue/commands/not.allowed/advance",
            headers={"Authorization": "Bearer internal-test-token"},
            json={"lease_claim": "f" * 32},
        ))
        self.assertEqual(invalid_id.status_code, 422)

    def test_rq_retry_policy_is_bounded(self):
        policy = self.publisher._retry_policy()
        self.assertEqual(policy.max, 5)
        self.assertEqual(len(policy.intervals), 5)
        self.assertEqual(policy.intervals, sorted(policy.intervals))
        for value, expected in zip(policy.intervals, (5, 15, 30, 60, 120)):
            self.assertGreaterEqual(value, int(expected * 0.8))
            self.assertLessEqual(value, int(expected * 1.2))

    def test_backend_queue_role_requires_only_backend_and_redis_bootstrap(self):
        environment = {
            "APP_ROLE": "backend-queue",
            "BOT_TOKEN": "",
            "BACKEND_API_URL": "http://backend:8080",
            "BACKEND_INTERNAL_TOKEN": "internal-test-token",
            "REDIS_URL": "redis://redis:6379/0",
        }
        with patch.dict(os.environ, environment, clear=True):
            config = AppConfig.from_env()
            config.validate_runtime()
            self.assertEqual(config.app_role, "backend-queue")
            self.assertEqual(config.redis_url, "redis://redis:6379/0")


if __name__ == "__main__":
    unittest.main()
