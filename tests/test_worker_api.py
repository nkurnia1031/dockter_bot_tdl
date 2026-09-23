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

    def workspace_tree(self, path):
        return {"path": path, "items": [{"name": "biasa", "path": "/workspace/biasa", "kind": "directory"}]}

    def quickmode_scan(self):
        return {"worker": "local", "items": [{"stage_job_id": "stage-1", "phase": "uploading"}]}

    def quickmode_verify(self, stage_job_id, expected_phase="uploading"):
        return {
            "stage_job_id": stage_job_id,
            "status": "verified",
            "expected_phase": expected_phase,
            "staging_cleaned": True,
        }

    def job_log_snapshot(self, job_id):
        if job_id != "active":
            return None
        return {
            "lines": ["tdl download started", "50% 1 MB/s"],
            "line_count": 2,
            "truncated": False,
        }


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

    def test_worker_preserves_event_sequence_start_for_reused_job_ids(self):
        payload = {
            "job_id": "retry-job",
            "kind": "export",
            "profile": "default",
            "actor_user_id": 42,
            "event_sequence_start": 983,
            "payload": {"quick_mode": True},
        }
        response = self.client.post(
            "/internal/v1/jobs",
            headers={"Authorization": "Bearer worker-secret"},
            json=payload,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.executor.commands[-1]["event_sequence_start"], 983)

    def test_workspace_tree_requires_token(self):
        denied = self.client.get("/internal/v1/workspace/tree")
        self.assertEqual(denied.status_code, 401)
        accepted = self.client.get(
            "/internal/v1/workspace/tree?path=%2Fworkspace%2Fbiasa",
            headers={"Authorization": "Bearer worker-secret"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["path"], "/workspace/biasa")

    def test_quickmode_scan_requires_token_and_returns_derived_staging(self):
        denied = self.client.get("/internal/v1/quickmode/scan")
        self.assertEqual(denied.status_code, 401)
        accepted = self.client.get(
            "/internal/v1/quickmode/scan",
            headers={"Authorization": "Bearer worker-secret"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["items"][0]["stage_job_id"], "stage-1")

    def test_quickmode_verify_requires_token_and_returns_cleanup_result(self):
        denied = self.client.post(
            "/internal/v1/quickmode/verify",
            json={"stage_job_id": "stage-1", "expected_phase": "uploading"},
        )
        self.assertEqual(denied.status_code, 401)
        accepted = self.client.post(
            "/internal/v1/quickmode/verify",
            headers={"Authorization": "Bearer worker-secret"},
            json={"stage_job_id": "stage-1", "expected_phase": "uploading"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["status"], "verified")
        self.assertTrue(accepted.json()["staging_cleaned"])

    def test_active_job_log_snapshot_requires_token_and_handles_missing(self):
        denied = self.client.get("/internal/v1/jobs/active/log-snapshot")
        self.assertEqual(denied.status_code, 401)
        active = self.client.get(
            "/internal/v1/jobs/active/log-snapshot",
            headers={"Authorization": "Bearer worker-secret"},
        )
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()["log"]["line_count"], 2)
        missing = self.client.get(
            "/internal/v1/jobs/missing/log-snapshot",
            headers={"Authorization": "Bearer worker-secret"},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "JOB_LOG_NOT_ACTIVE")


if __name__ == "__main__":
    unittest.main()
