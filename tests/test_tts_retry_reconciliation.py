import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient

from tme3bot.api.worker import WorkerContext, create_worker_app
from tme3bot.domain.models import Job, JobStatus
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.worker.executor import WorkerJobExecutor


class _TtsPipeline:
    def __init__(self, parts=1):
        self.parts = parts

    def ready(self):
        return True

    def synthesize(self, job_id, text, root, **kwargs):
        del job_id, text, kwargs
        root.mkdir(parents=True, exist_ok=True)
        artifacts = []
        for index in range(1, self.parts + 1):
            artifact_ref = f"{index:048x}"
            (root / f"artifact-{artifact_ref}.mp3").write_bytes(b"audio")
            artifacts.append({
                "artifact_ref": artifact_ref,
                "part_index": index,
                "total_parts": self.parts,
                "byte_size": 5,
            })
        return {
            "character_count": 4,
            "part_count": self.parts,
            "artifacts": artifacts,
        }


class _FakeTdl:
    def __init__(self, message_id=None, lookup_error=None, upload_error=None):
        self.message_id = message_id
        self.lookup_error = lookup_error
        self.upload_error = upload_error
        self.lookups = []
        self.uploads = []

    def find_message_id_by_caption(self, chat_ref, caption, *, after_timestamp):
        self.lookups.append((chat_ref, caption, after_timestamp))
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.message_id

    def upload(self, path, chat_ref, caption):
        self.uploads.append((Path(path), chat_ref, caption))
        if self.upload_error is not None:
            raise self.upload_error
        return SimpleNamespace(message_id=123)


class _SqliteTtsOutboxAdapter:
    def __init__(self, jobs, job_id, chat_ref):
        self.jobs = jobs
        self.job_id = job_id
        self.chat_ref = chat_ref

    def __call__(self, *_args, **kwargs):
        method = str(_args[2]).upper()
        url = str(_args[3])
        body = _args[4] if len(_args) > 4 else kwargs.get("json")
        parsed = urlsplit(url)
        path = parsed.path
        if path == "/internal/v1/tts/artifacts/ready" and method == "POST":
            count = self.jobs.create_tts_deliveries(
                str(body["job_id"]),
                str(body["worker"]),
                str(body["title"]),
                list(body["parts"]),
            )
            return {"registered_parts": count, "chat_ref": self.chat_ref}
        if path == "/internal/v1/tts/deliveries/worker-pending" and method == "GET":
            query = parse_qs(parsed.query)
            return {
                "items": self.jobs.claim_tts_deliveries(
                    int(query.get("limit", ["1"])[0]),
                    worker=query["worker"][0],
                    job_id=query["job_id"][0],
                    include_artifact_ref=True,
                )
            }
        if path.startswith("/internal/v1/tts/deliveries/") and path.endswith("/worker-result"):
            delivery_id = path.split("/")[5]
            item = self.jobs.complete_tts_delivery(
                delivery_id,
                delivered=bool(body["delivered"]),
                reconciliation_required=bool(body.get("reconciliation_required", False)),
            )
            return {"status": item["status"]}
        if path == f"/internal/v1/tts/jobs/{self.job_id}/delivery" and method == "GET":
            summary = self.jobs.tts_delivery_summary(self.job_id)
            delivered = summary["total_parts"] == summary["delivered_parts"]
            return {"status": "delivered" if delivered else "pending", **summary}
        raise AssertionError(f"Unexpected fake TTS backend call: {method} {path}")


class _SynchronousWorkerExecutor(WorkerJobExecutor):
    def __init__(self, root, tdls):
        if not isinstance(tdls, dict):
            tdls = {"default": tdls}
        self.config = SimpleNamespace(
            tts_data_root=Path(root) / "tts",
            backup_node_name="local",
            backend_api_url="http://backend",
            backend_internal_token="internal",
            worker_api_token="worker-secret",
        )
        self.runtime_settings = SimpleNamespace(
            tts_settings=lambda: {},
            worker_token_matches=lambda token: token == "worker-secret",
        )
        self._lock = threading.RLock()
        self._pause_events = {}
        self._cancel_requested = set()
        self._cancel_observed = set()
        self._cancel_confirmed = set()
        self._finalizing = set()
        self._job_log = threading.local()
        self._job_log.secrets = []
        self.logs = []
        self.events = []
        self.publisher = SimpleNamespace(
            emit=lambda *args, **kwargs: self.events.append((args, kwargs))
        )
        self.profile_manager = SimpleNamespace(
            runtime=lambda profile: SimpleNamespace(
                name=profile,
                export_tdl_client=tdls[profile],
                export_operation_lock=threading.RLock(),
            )
        )

    def enqueue(self, command):
        try:
            self._execute(command)
        except Exception as exc:
            self._failed(command, exc)
        return 1

    def _append_job_log(self, line):
        self.logs.append(line)


class TtsRetryReconciliationTests(unittest.TestCase):
    def _prepare_job(self, root, job_id, *, parts=1):
        jobs = SqliteJobRepository(root / "outbox.sqlite3")
        jobs.create(Job(
            id=job_id,
            kind="tts",
            profile="default",
            actor_user_id=42,
            worker="local",
            status=JobStatus.RUNNING,
            payload={"title": "Bab 4", "text": "Teks"},
        ))
        jobs.create_tts_deliveries(job_id, "local", "Bab 4", [
            {
                "artifact_ref": f"{index:048x}",
                "part_index": index,
                "total_parts": parts,
                "byte_size": 5,
            }
            for index in range(1, parts + 1)
        ])
        return jobs

    def _dispatch_retry(self, root, jobs, job_id, tdls, profiles, *, parts=1):
        executor = _SynchronousWorkerExecutor(root, tdls)
        backend = _SqliteTtsOutboxAdapter(jobs, job_id, "-100123")
        client = TestClient(create_worker_app(WorkerContext(executor.config, executor)))
        command = {
            "job_id": job_id,
            "kind": "tts",
            "profile": "default",
            "actor_user_id": 42,
            "worker": "local",
            "payload": {
                "title": "Bab 4",
                "text": "Teks",
                "_tdl_sender_profiles": profiles,
                "_tts_reconcile_delivery": True,
            },
        }
        with patch.object(executor, "_tts_pipeline", return_value=_TtsPipeline(parts)), patch(
            "tme3bot.worker.executor_tts.request_json", side_effect=backend
        ):
            response = client.post(
                "/internal/v1/jobs",
                headers={"Authorization": "Bearer worker-secret"},
                json=command,
            )
        self.assertEqual(response.status_code, 200, response.text)
        return executor

    def _unconfirmed_delivery(self, jobs, job_id, *, part_index=1):
        claimed = jobs.claim_tts_deliveries(
            10, worker="local", job_id=job_id, include_artifact_ref=True
        )
        item = next(item for item in claimed if item["part_index"] == part_index)
        return jobs.complete_tts_delivery(
            item["id"], delivered=False, reconciliation_required=True
        )

    def test_worker_command_reconciles_existing_caption_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-existing"
            jobs = self._prepare_job(root, job_id)
            original = jobs.claim_tts_deliveries(
                1, worker="local", job_id=job_id, include_artifact_ref=True
            )
            prior_delivery = jobs.get_tts_delivery(original[0]["id"])
            jobs.complete_tts_delivery(
                original[0]["id"], delivered=False, reconciliation_required=True
            )

            tdl = _FakeTdl(message_id=777)
            self._dispatch_retry(root, jobs, job_id, tdl, ["default"])

            self.assertEqual(tdl.lookups, [("-100123", "Bab 4", prior_delivery["created_at"])])
            self.assertEqual(tdl.uploads, [])
            self.assertEqual(jobs.get_tts_delivery(original[0]["id"])["status"], "delivered")

    def test_successful_export_without_caption_uploads_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-absent"
            jobs = self._prepare_job(root, job_id)
            self._unconfirmed_delivery(jobs, job_id)
            tdl = _FakeTdl(message_id=None)

            self._dispatch_retry(root, jobs, job_id, tdl, ["default"])

            self.assertEqual(len(tdl.lookups), 1)
            self.assertEqual(len(tdl.uploads), 1)
            self.assertEqual(jobs.tts_delivery_summary(job_id)["delivered_parts"], 1)

    def test_explicit_access_denial_tries_next_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-fallback"
            jobs = self._prepare_job(root, job_id)
            self._unconfirmed_delivery(jobs, job_id)
            denied = _FakeTdl(lookup_error=RuntimeError("CHANNEL_PRIVATE"))
            accessible = _FakeTdl(message_id=None)

            self._dispatch_retry(
                root, jobs, job_id,
                {"default": denied, "irang": accessible},
                ["default", "irang"],
            )

            self.assertEqual(len(denied.lookups), 1)
            self.assertEqual(accessible.lookups[0][1], "Bab 4")
            self.assertEqual(denied.uploads, [])
            self.assertEqual(len(accessible.uploads), 1)

    def test_all_profiles_denied_keeps_delivery_unresolved_and_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-denied"
            jobs = self._prepare_job(root, job_id)
            item = self._unconfirmed_delivery(jobs, job_id)
            denied_default = _FakeTdl(lookup_error=RuntimeError("CHANNEL_PRIVATE"))
            denied_irang = _FakeTdl(lookup_error=RuntimeError("CHANNEL_PRIVATE"))

            executor = self._dispatch_retry(
                root,
                jobs,
                job_id,
                {"default": denied_default, "irang": denied_irang},
                ["default", "irang"],
            )

            self.assertEqual(denied_default.uploads, [])
            self.assertEqual(denied_irang.uploads, [])
            self.assertEqual(len(denied_default.lookups), 1)
            self.assertEqual(len(denied_irang.lookups), 1)
            self.assertEqual(jobs.get_tts_delivery(item["id"])["status"], "reconciliation_required")
            self.assertTrue(any(
                "TTS_CHANNEL_UNAVAILABLE" in str(kwargs.get("error", {}).get("message", ""))
                for _args, kwargs in executor.events
            ))

    def test_all_profiles_rejecting_upload_warns_channel_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-write-denied"
            jobs = self._prepare_job(root, job_id)
            item = self._unconfirmed_delivery(jobs, job_id)
            default = _FakeTdl(message_id=None, upload_error=RuntimeError("CHAT_WRITE_FORBIDDEN"))
            irang = _FakeTdl(message_id=None, upload_error=RuntimeError("CHAT_WRITE_FORBIDDEN"))

            executor = self._dispatch_retry(
                root,
                jobs,
                job_id,
                {"default": default, "irang": irang},
                ["default", "irang"],
            )

            self.assertEqual(len(default.lookups), 1)
            self.assertEqual(len(irang.lookups), 0)
            self.assertEqual(len(default.uploads), 1)
            self.assertEqual(len(irang.uploads), 1)
            self.assertEqual(
                jobs.get_tts_delivery(item["id"])["status"],
                "reconciliation_required",
            )
            self.assertTrue(any(
                "TTS_CHANNEL_UNAVAILABLE" in str(kwargs.get("error", {}).get("message", ""))
                for _args, kwargs in executor.events
            ))

    def test_failed_export_stays_ambiguous_without_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-incomplete"
            jobs = self._prepare_job(root, job_id)
            item = self._unconfirmed_delivery(jobs, job_id)
            tdl = _FakeTdl(lookup_error=RuntimeError("network timeout"))

            executor = self._dispatch_retry(root, jobs, job_id, tdl, ["default"])

            self.assertEqual(tdl.uploads, [])
            self.assertEqual(jobs.get_tts_delivery(item["id"])["status"], "reconciliation_required")
            self.assertTrue(any(
                "TTS_DELIVERY_RECONCILIATION_FAILED" in str(kwargs.get("error", {}).get("message", ""))
                for _args, kwargs in executor.events
            ))

    def test_retry_skips_confirmed_parts_and_reconciles_only_pending_part(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-partial"
            jobs = self._prepare_job(root, job_id, parts=2)
            first = jobs.claim_tts_deliveries(
                1, worker="local", job_id=job_id, include_artifact_ref=True
            )[0]
            jobs.complete_tts_delivery(first["id"], delivered=True)
            second = jobs.claim_tts_deliveries(
                1, worker="local", job_id=job_id, include_artifact_ref=True
            )[0]
            jobs.complete_tts_delivery(
                second["id"], delivered=False, reconciliation_required=True
            )
            tdl = _FakeTdl(message_id=None)

            self._dispatch_retry(root, jobs, job_id, tdl, ["default"], parts=2)

            self.assertEqual([lookup[1] for lookup in tdl.lookups], ["Bab 4 (2/2)"])
            self.assertEqual([upload[2] for upload in tdl.uploads], ["Bab 4 (2/2)"])
            self.assertEqual(jobs.get_tts_delivery(first["id"])["status"], "delivered")


if __name__ == "__main__":
    unittest.main()
