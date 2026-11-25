from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tme3bot.application.control_plane import ControlPlane
from tme3bot.application.worker_health import WorkerHealthMonitor
from tme3bot.domain.models import DomainError, Job, JobStatus

from tme3bot.application.worker_restart import WorkerRestartCoordinator
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.infrastructure.worker_restart_store import SqliteWorkerRestartStore
from tme3bot.worker.supervisor_auth import derive_supervisor_token
from tme3bot.worker_registry import WorkerRegistry


class WorkerHealthEndpoint:
    """Fake only the remote worker health boundary."""

    def __init__(self, status="offline"):
        self.status = status
        self.calls = []

    def check(self, worker):
        self.calls.append(worker)
        return {"healthy": self.status == "ready"}


class WorkerRestartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        database_path = root / "gateway.sqlite3"
        self.store = SqliteWorkerRestartStore(database_path)
        self.registry = WorkerRegistry(root / "workers.json")
        self.registry.upsert("remote-1", "http://worker", "worker-secret")
        self.health_endpoint = WorkerHealthEndpoint()
        self.health = WorkerHealthMonitor(self.registry, self.health_endpoint.check)
        self.jobs = SqliteJobRepository(database_path)
        self.control = ControlPlane(
            self.jobs,
            object(),
            None,
            worker_registry=self.registry,
            worker_restart_store=self.store,
        )
        for job_id, status in (
            ("job-1", JobStatus.RUNNING),
            ("job-2", JobStatus.QUEUED),
        ):
            self.jobs.create(Job(
                id=job_id,
                kind="utility",
                profile="default",
                actor_user_id=42,
                worker="remote-1",
                status=status,
                payload={},
            ))
        self.coordinator = WorkerRestartCoordinator(
            self.store,
            self.registry,
            self.health,
            self.jobs,
            self.control,
            supervisor_max_age_seconds=30,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_restart_preflight_requires_two_failed_probes_and_live_supervisor(self):
        unavailable = self.coordinator.preflight("remote-1")
        self.assertFalse(unavailable["restart_available"])
        self.assertEqual(unavailable["reason_code"], "SUPERVISOR_OFFLINE")

        self.store.record_supervisor_heartbeat("remote-1")
        available = self.coordinator.preflight("remote-1")
        self.assertTrue(available["restart_available"])
        self.assertEqual(available["active_job_count"], 2)
        self.assertEqual(self.health_endpoint.calls, ["remote-1"] * 4)

    def test_restart_is_refused_when_worker_is_reachable(self):
        self.store.record_supervisor_heartbeat("remote-1")
        self.health_endpoint.status = "ready"
        result = self.coordinator.preflight("remote-1")
        self.assertFalse(result["restart_available"])
        self.assertEqual(result["reason_code"], "WORKER_REACHABLE")

    def test_request_is_idempotent_and_fences_one_worker(self):
        self.store.record_supervisor_heartbeat("remote-1")
        first = self.coordinator.request_restart("remote-1", actor_user_id=42)
        second = self.coordinator.request_restart("remote-1", actor_user_id=42)

        self.assertEqual(first["id"], second["id"])
        self.assertTrue(self.store.has_active_restart("remote-1"))
        self.assertEqual(first["active_job_count"], 2)

    def test_supervisor_result_is_rejected_until_command_is_claimed(self):
        self.store.record_supervisor_heartbeat("remote-1")
        operation = self.coordinator.request_restart("remote-1", actor_user_id=42)
        supervisor_token = derive_supervisor_token("remote-1", "worker-secret")
        self.assertNotEqual(supervisor_token, "worker-secret")
        with self.assertRaises(DomainError):
            self.coordinator.poll_supervisor("remote-1", "worker-secret")
        with self.assertRaises(DomainError) as raised:
            self.coordinator.report_supervisor_result(
                "remote-1",
                supervisor_token,
                operation["id"],
                {
                    "container_stopped": False,
                    "container_running": True,
                    "restart_succeeded": False,
                    "failure_code": "COMPOSE_STOP_FAILED",
                },
            )
        self.assertEqual(raised.exception.code, "WORKER_RESTART_NOT_CLAIMED")
        self.assertTrue(self.store.has_active_restart("remote-1"))

        command = self.coordinator.poll_supervisor("remote-1", supervisor_token)
        self.assertEqual(command["command"]["operation_id"], operation["id"])
        failed = self.coordinator.report_supervisor_result(
            "remote-1",
            supervisor_token,
            operation["id"],
            {
                "container_stopped": False,
                "container_running": True,
                "restart_succeeded": False,
                "failure_code": "COMPOSE_STOP_FAILED",
            },
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(self.jobs.get("job-1").status, JobStatus.RUNNING)
        self.assertEqual(self.jobs.get("job-2").status, JobStatus.QUEUED)

    def test_confirmed_restart_cancels_captured_active_jobs_once(self):
        self.store.record_supervisor_heartbeat("remote-1")
        operation = self.coordinator.request_restart("remote-1", actor_user_id=42)
        self.jobs.create(Job(
            id="job-created-after-request",
            kind="utility",
            profile="default",
            actor_user_id=42,
            worker="remote-1",
            status=JobStatus.RUNNING,
            payload={},
        ))
        supervisor_token = derive_supervisor_token("remote-1", "worker-secret")
        self.coordinator.poll_supervisor("remote-1", supervisor_token)

        result = self.coordinator.report_supervisor_result(
            "remote-1",
            supervisor_token,
            operation["id"],
            {
                "container_stopped": True,
                "container_running": True,
                "restart_succeeded": True,
            },
        )
        repeated = self.coordinator.report_supervisor_result(
            "remote-1",
            supervisor_token,
            operation["id"],
            {
                "container_stopped": True,
                "container_running": True,
                "restart_succeeded": True,
            },
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(repeated["status"], "succeeded")
        self.assertCountEqual(
            result["result"]["cancelled_job_ids"],
            ["job-1", "job-2", "job-created-after-request"],
        )
        self.assertTrue(all(
            self.jobs.get(job_id).status == JobStatus.CANCELLED
            for job_id in ("job-1", "job-2", "job-created-after-request")
        ))
        self.assertFalse(self.store.has_active_restart("remote-1"))


if __name__ == "__main__":
    unittest.main()
