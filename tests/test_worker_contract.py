import unittest
from unittest.mock import call, patch

from fastapi.testclient import TestClient

from tme3bot.api.schemas import WorkerEventRequest
from tme3bot.api.worker import WorkerContext, create_worker_app
from tme3bot.domain.models import DomainError
from tme3bot.domain.worker_contract import (
    CAP_QUICKMODE_DELETE,
    CAP_QUICKMODE_STAGING,
    WORKER_API_CAPABILITIES,
    WORKER_API_CONTRACT_VERSION,
    worker_contract_metadata,
)
from tme3bot.infrastructure.http_client import WorkerHttpDispatcher
from tme3bot.worker.executor_support import WorkerEventPublisher


class ContractWorkerExecutor:
    def __init__(self):
        self.commands = []

    def capabilities(self):
        return {"profiles": ["default"], "workspace": True}

    def enqueue(self, command):
        self.commands.append(command)
        return 1


class ContractWorkerRegistry:
    def get(self, name):
        if name != "remote":
            return None
        return {"url": "http://worker.test", "token": "worker-token"}


class WorkerContractTests(unittest.TestCase):
    def test_worker_capability_endpoint_advertises_versioned_wire_features(self):
        executor = ContractWorkerExecutor()
        app = create_worker_app(
            WorkerContext(
                type("Config", (), {"worker_api_token": "worker-token"})(),
                executor,
            )
        )
        response = TestClient(app).get(
            "/internal/v1/capabilities",
            headers={"Authorization": "Bearer worker-token"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["contract_version"], WORKER_API_CONTRACT_VERSION)
        self.assertEqual(set(body["capabilities"]), WORKER_API_CAPABILITIES)
        self.assertEqual(body["profiles"], ["default"])

    def test_worker_job_endpoint_accepts_dispatch_contract_payload(self):
        executor = ContractWorkerExecutor()
        app = create_worker_app(
            WorkerContext(
                type("Config", (), {"worker_api_token": "worker-token"})(),
                executor,
            )
        )
        payload = {
            "job_id": "job-contract",
            "kind": "export",
            "profile": "default",
            "actor_user_id": 42,
            "event_sequence_start": 17,
            "execution": {"lane": "export"},
            "payload": {"url": "https://t.me/c/1/2"},
        }

        response = TestClient(app).post(
            "/internal/v1/jobs",
            headers={"Authorization": "Bearer worker-token"},
            json=payload,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"position": 1, "job_id": "job-contract"})
        self.assertEqual(executor.commands, [payload])

    @patch("tme3bot.infrastructure.http_client.request_json")
    def test_dispatch_negotiates_contract_and_sends_stable_job_payload(self, request):
        request.side_effect = [
            worker_contract_metadata(),
            {"position": 1, "job_id": "job-1"},
        ]
        dispatcher = WorkerHttpDispatcher(ContractWorkerRegistry())
        payload = {
            "job_id": "job-1",
            "kind": "export",
            "profile": "default",
            "actor_user_id": 42,
            "event_sequence_start": 9,
            "execution": {"lane": "export"},
            "payload": {"url": "https://t.me/c/1/2"},
        }

        self.assertEqual(dispatcher.dispatch("remote", payload)["position"], 1)
        self.assertEqual(
            request.call_args_list,
            [
                call(
                    "http://worker.test",
                    "worker-token",
                    "GET",
                    "/internal/v1/capabilities",
                    timeout=15,
                ),
                call(
                    "http://worker.test",
                    "worker-token",
                    "POST",
                    "/internal/v1/jobs",
                    payload,
                ),
            ],
        )

    @patch("tme3bot.infrastructure.http_client.request_json")
    def test_dispatch_rejects_mismatched_contract_before_sending_job(self, request):
        request.return_value = {"contract_version": 0, "capabilities": []}
        dispatcher = WorkerHttpDispatcher(ContractWorkerRegistry())

        with self.assertRaises(DomainError) as raised:
            dispatcher.dispatch("remote", {"job_id": "job-2", "payload": {}})

        self.assertEqual(raised.exception.code, "WORKER_INCOMPATIBLE")
        self.assertEqual(request.call_count, 1)

    @patch("tme3bot.infrastructure.http_client.request_json")
    def test_quickmode_dispatch_requires_quickmode_stage_capability(self, request):
        capabilities = worker_contract_metadata()
        capabilities["capabilities"].remove(CAP_QUICKMODE_STAGING)
        request.return_value = capabilities
        dispatcher = WorkerHttpDispatcher(ContractWorkerRegistry())

        with self.assertRaises(DomainError) as raised:
            dispatcher.dispatch(
                "remote",
                {"job_id": "quick-1", "payload": {"quick_mode": True}},
            )

        self.assertEqual(raised.exception.code, "WORKER_INCOMPATIBLE")
        self.assertIn(CAP_QUICKMODE_STAGING, raised.exception.details["missing_capabilities"])
        self.assertEqual(request.call_count, 1)

    @patch("tme3bot.infrastructure.http_client.request_json")
    def test_quickmode_stage_delete_negotiates_delete_capability(self, request):
        request.side_effect = [worker_contract_metadata(), {"deleted": True}]
        dispatcher = WorkerHttpDispatcher(ContractWorkerRegistry())

        result = dispatcher.quickmode_delete("remote", "stage-delete")

        self.assertTrue(result["deleted"])
        self.assertEqual(request.call_args_list[1].args[2:4], (
            "DELETE",
            "/internal/v1/quickmode/staging/stage-delete",
        ))
        capabilities = worker_contract_metadata()
        capabilities["capabilities"].remove(CAP_QUICKMODE_DELETE)
        request.reset_mock()
        request.side_effect = None
        request.return_value = capabilities
        with self.assertRaises(DomainError) as raised:
            dispatcher.quickmode_delete("remote", "stage-delete")
        self.assertEqual(raised.exception.code, "WORKER_INCOMPATIBLE")
        self.assertIn(CAP_QUICKMODE_DELETE, raised.exception.details["missing_capabilities"])
        self.assertEqual(request.call_count, 1)

    @patch("tme3bot.worker.executor_support.request_json")
    def test_worker_progress_event_matches_backend_event_schema(self, request):
        request.return_value = {"accepted": True}
        publisher = WorkerEventPublisher("http://backend.test", "backend-token")
        publisher.begin("job-3", 40)
        publisher.emit(
            "job-3",
            "running",
            "progress.snapshot",
            transient=True,
            progress={"phase": "downloading", "percent": 25},
        )

        args, kwargs = request.call_args
        event_payload = args[4]
        event = (
            WorkerEventRequest.model_validate(event_payload)
            if hasattr(WorkerEventRequest, "model_validate")
            else WorkerEventRequest.parse_obj(event_payload)
        )
        self.assertEqual(args[3], "/internal/v1/jobs/job-3/events")
        self.assertEqual(event.sequence, 41)
        self.assertEqual(event.status, "running")
        self.assertTrue(event.transient)
        self.assertEqual(event.progress["percent"], 25)
        self.assertEqual(kwargs["timeout"], 5.0)

    @patch("tme3bot.worker.executor_support.request_json")
    def test_interleaved_job_events_keep_worker_and_sequence_ownership(self, request):
        request.return_value = {"accepted": True}
        publisher = WorkerEventPublisher("http://backend.test", "backend-token")
        publisher.begin("job-local", 10)
        publisher.bind_job_worker("job-local", "local")
        publisher.begin("job-remote", 30)
        publisher.bind_job_worker("job-remote", "remote-1")

        publisher.emit("job-local", "running", "progress.snapshot", transient=True)
        publisher.emit("job-remote", "running", "progress.snapshot", transient=True)

        local_call, remote_call = request.call_args_list
        self.assertEqual(local_call.args[3], "/internal/v1/jobs/job-local/events")
        self.assertEqual(local_call.args[4]["worker"], "local")
        self.assertEqual(local_call.args[4]["sequence"], 11)
        self.assertEqual(remote_call.args[3], "/internal/v1/jobs/job-remote/events")
        self.assertEqual(remote_call.args[4]["worker"], "remote-1")
        self.assertEqual(remote_call.args[4]["sequence"], 31)


if __name__ == "__main__":
    unittest.main()
