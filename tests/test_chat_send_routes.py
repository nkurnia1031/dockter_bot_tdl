from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tme3bot.api.routes.chat_send import register_chat_send


class FakeJobs:
    def __init__(self, original, retried):
        created = SimpleNamespace(
            id="new-job", kind="chat_send", profile="default", worker="remote-2",
            status=SimpleNamespace(terminal=False), payload={}, result={},
        )
        self.items = {original.id: original, retried.id: retried, created.id: created}

    def get(self, job_id):
        return self.items.get(job_id)


class FakeControlPlane:
    def __init__(self, jobs):
        self.jobs = jobs
        self.authorized_profiles = []

    def require_profile(self, actor, profile):
        self.authorized_profiles.append((actor.profile, profile))
        return profile


class FakeOperations:
    def __init__(self):
        self.submissions = []

    def submit(self, actor, **kwargs):
        self.submissions.append((actor, kwargs))
        job_id = "retry-job" if kwargs["input_data"].get("job_kind") == "chat_send" and "retry_paths" in kwargs["input_data"].get("payload", {}) else "new-job"
        return SimpleNamespace(id=f"operation-{len(self.submissions)}", job_id=job_id), False


class ChatSendRouteTests(unittest.TestCase):
    def setUp(self):
        status = SimpleNamespace(terminal=True)
        original = SimpleNamespace(
            id="original-job", kind="chat_send", profile="default", worker="remote-2",
            status=status,
            payload={
                "chat_ref": "destination", "folders": ["/workspace/books"],
                "profiles": ["default", "archive"], "transfer_mode": "move",
                "move_confirmed": True,
            },
            result={"value": {"items": [
                {"path": "books/retry.txt", "status": "failed", "retryable": True},
                {"path": "books/uncertain.txt", "status": "ambiguous", "retryable": False},
                {"path": "books/sent.txt", "status": "succeeded", "retryable": False},
            ]}},
        )
        retried = SimpleNamespace(
            id="retry-job", kind="chat_send", profile="default", worker="remote-2",
            status=SimpleNamespace(terminal=False), payload={}, result={},
        )
        self.actor = SimpleNamespace(profile="default", telegram_user_id=42)
        self.operations = FakeOperations()
        self.control_plane = FakeControlPlane(FakeJobs(original, retried))
        self.context = SimpleNamespace(
            operation_service=self.operations,
            control_plane=self.control_plane,
        )
        self.app = FastAPI()

        @self.app.middleware("http")
        async def add_request_id(request, call_next):
            request.state.request_id = "request-1"
            return await call_next(request)

        def current_actor():
            return self.actor

        self.app.dependency_overrides[current_actor] = lambda: self.actor
        self.current_actor = current_actor
        register_chat_send(
            self.app,
            self.context,
            current_actor=current_actor,
            job_dict=lambda job: {"id": job.id, "kind": job.kind, "worker": job.worker},
        )
        self.client = TestClient(self.app)

    def test_submit_uses_selected_worker_and_profiles_as_durable_job_input(self):
        response = self.client.post(
            "/api/v1/chat-send/jobs",
            headers={"Idempotency-Key": "chat-send-submit-1"},
            json={
                "worker": "remote-2", "chat_ref": "https://t.me/c/123456/9",
                "folders": ["/workspace/books"], "profiles": ["default", "archive"],
                "transfer_mode": "copy", "move_confirmed": False,
            },
        )

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.headers["location"], "/api/v1/jobs/new-job")
        _actor, submission = self.operations.submissions[0]
        self.assertEqual(submission["kind"], "job.submit")
        self.assertEqual(submission["target"], {"worker": "remote-2"})
        self.assertEqual(submission["idempotency_key"], "chat-send-submit-1")
        self.assertEqual(submission["input_data"]["job_kind"], "chat_send")
        self.assertEqual(
            submission["input_data"]["payload"]["profiles"], ["default", "archive"]
        )

    def test_retry_submits_only_confirmed_failed_files_and_preserves_move_settings(self):
        response = self.client.post(
            "/api/v1/chat-send/jobs/original-job/retry",
            headers={"Idempotency-Key": "chat-send-retry-1"},
        )

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.control_plane.authorized_profiles, [("default", "default")])
        _actor, submission = self.operations.submissions[0]
        self.assertEqual(submission["target"], {"worker": "remote-2"})
        self.assertEqual(submission["input_data"]["payload"], {
            "chat_ref": "destination", "folders": ["/workspace/books"],
            "profiles": ["default", "archive"], "transfer_mode": "move",
            "move_confirmed": True, "retry_paths": ["books/retry.txt"],
        })


if __name__ == "__main__":
    unittest.main()
