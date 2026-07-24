import unittest

from fastapi.testclient import TestClient

from tme3bot.api.worker import WorkerContext, create_worker_app


class FakeExecutor:
    def __init__(self):
        self.commands = []

    def enqueue(self, command):
        self.commands.append(command)
        return 1

    def cancel(self, job_id):
        return job_id == "known"


class WorkerApiTests(unittest.TestCase):
    def setUp(self):
        config = type("Config", (), {"worker_api_token": "worker-secret"})()
        self.executor = FakeExecutor()
        self.client = TestClient(
            create_worker_app(WorkerContext(config, self.executor))
        )

    def test_worker_requires_token_and_accepts_frontend_neutral_job(self):
        payload = {
            "job_id": "job-1",
            "kind": "export",
            "profile": "default",
            "actor_user_id": 42,
            "payload": {"url": "https://t.me/c/1/2"},
        }
        denied = self.client.post("/internal/v1/jobs", json=payload)
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(denied.json()["error"]["code"], "WORKER_UNAUTHORIZED")

        accepted = self.client.post(
            "/internal/v1/jobs",
            headers={"Authorization": "Bearer worker-secret"},
            json=payload,
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["position"], 1)
        self.assertEqual(self.executor.commands, [payload])

    def test_worker_has_no_openapi_surface(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
