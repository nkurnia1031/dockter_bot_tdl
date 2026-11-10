import tempfile
import threading
import time
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


class _FakeClock:
    def __init__(self, current):
        self.current = float(current)

    def time(self):
        return self.current

    def sleep(self, seconds):
        self.current += float(seconds)


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
    def __init__(
        self,
        message_id=None,
        lookup_error=None,
        upload_error=None,
        *,
        visible_after_exports=0,
        upload_error_after_accept=None,
    ):
        self.message_id = message_id
        self.lookup_error = lookup_error
        self.upload_error = upload_error
        self.lookups = []
        self.uploads = []
        self.messages = ([{
            "id": message_id,
            "date": time.time(),
            "file_name": "Bab 4.mp3",
            "caption": "Bab 4",
        }] if message_id is not None else [])
        self.time_exports = []
        self.visible_after_exports = int(visible_after_exports)
        self.on_upload = None
        self.upload_error_after_accept = upload_error_after_accept
        self.clock = None
        self.upload_duration_seconds = 0.0

    def find_message_id_by_caption(self, chat_ref, caption, *, after_timestamp):
        self.lookups.append((chat_ref, caption, after_timestamp))
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.message_id

    def upload(self, path, chat_ref, caption):
        self.uploads.append((Path(path), chat_ref, caption))
        if self.upload_error is not None:
            raise self.upload_error
        if self.on_upload is not None:
            self.on_upload()
        if self.clock is not None:
            self.clock.current += self.upload_duration_seconds
            sent_at = self.clock.time()
        else:
            sent_at = time.time()
        self.messages.append({
            "id": 900 + len(self.messages),
            "date": sent_at,
            "file_name": Path(path).name,
            "caption": caption,
        })
        if self.upload_error_after_accept is not None:
            raise self.upload_error_after_accept
        return SimpleNamespace(message_id=123)

    def export_messages_by_time(self, chat_ref, start, end, _path, *, with_content):
        self.time_exports.append((chat_ref, start, end, with_content))
        if self.lookup_error is not None:
            raise self.lookup_error
        if len(self.time_exports) < self.visible_after_exports:
            messages = []
        else:
            messages = [
                message for message in self.messages
                if start <= message["date"] <= end
            ]
        return SimpleNamespace(messages=messages)


class _SqliteTtsOutboxAdapter:
    def __init__(self, jobs, job_id, chat_ref):
        self.jobs = jobs
        self.job_id = job_id
        self.chat_ref = chat_ref
        self.fail_delivered_once = False

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
            if body.get("delivered") is True and self.fail_delivered_once:
                self.fail_delivered_once = False
                raise RuntimeError("simulated result persistence failure")
            item = self.jobs.complete_tts_delivery(
                delivery_id,
                delivered=bool(body["delivered"]),
                reconciliation_required=bool(body.get("reconciliation_required", False)),
                verification_pending=bool(body.get("verification_pending", False)),
                upload_in_progress=bool(body.get("upload_in_progress", False)),
                uploaded_at=body.get("uploaded_at"),
                sender_profile=body.get("sender_profile"),
            )
            return {"status": item["status"]}
        if path == f"/internal/v1/tts/jobs/{self.job_id}/cancel-delivery" and method == "POST":
            self.jobs.cancel_tts_deliveries(self.job_id)
            return {"status": "cancelled"}
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

    def _dispatch_retry(
        self,
        root,
        jobs,
        job_id,
        tdls,
        profiles,
        *,
        parts=1,
        cancel_on_upload=False,
        cancel_before_worker=False,
        fail_delivered_once=False,
    ):
        executor = _SynchronousWorkerExecutor(root, tdls)
        if cancel_before_worker:
            executor._cancel_requested.add(job_id)
        if cancel_on_upload:
            for tdl in (tdls.values() if isinstance(tdls, dict) else [tdls]):
                tdl.on_upload = lambda: executor._cancel_requested.add(job_id)
        backend = _SqliteTtsOutboxAdapter(jobs, job_id, "-100123")
        backend.fail_delivered_once = fail_delivered_once
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
            item["id"],
            delivered=False,
            reconciliation_required=True,
            uploaded_at=time.time(),
            sender_profile="default",
        )

    def _legacy_unconfirmed_delivery(self, jobs, job_id, *, part_index=1):
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
            uploaded_at = time.time()
            jobs.complete_tts_delivery(
                original[0]["id"],
                delivered=False,
                reconciliation_required=True,
                uploaded_at=uploaded_at,
                sender_profile="default",
            )

            tdl = _FakeTdl(message_id=777)
            tdl.messages[0]["date"] = uploaded_at
            self._dispatch_retry(root, jobs, job_id, tdl, ["default"])

            self.assertEqual(len(tdl.time_exports), 1)
            self.assertEqual(tdl.time_exports[0][0], "-100123")
            self.assertEqual(tdl.time_exports[0][3], True)
            self.assertEqual(tdl.uploads, [])
            self.assertEqual(jobs.get_tts_delivery(original[0]["id"])["status"], "delivered")

    def test_tts_retry_uses_persisted_upload_time_and_sender_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-persisted-window"
            jobs = self._prepare_job(root, job_id)
            claimed = jobs.claim_tts_deliveries(
                1, worker="local", job_id=job_id, include_artifact_ref=True
            )[0]
            uploaded_at = 1_700_000_000
            jobs.complete_tts_delivery(
                claimed["id"],
                delivered=False,
                reconciliation_required=True,
                uploaded_at=uploaded_at,
                sender_profile="irang",
            )
            tdl = _FakeTdl(message_id=777)
            tdl.messages[0]["date"] = uploaded_at
            self._dispatch_retry(root, jobs, job_id, {"default": _FakeTdl(), "irang": tdl}, ["default", "irang"])

            self.assertEqual(tdl.uploads, [])
            self.assertEqual(tdl.time_exports[0][1:3], (uploaded_at - 60, uploaded_at + 60))
            self.assertEqual(jobs.get_tts_delivery(claimed["id"])["status"], "delivered")

    def test_tts_retry_does_not_change_profile_when_saved_export_lane_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-same-profile"
            jobs = self._prepare_job(root, job_id)
            claimed = jobs.claim_tts_deliveries(
                1, worker="local", job_id=job_id, include_artifact_ref=True
            )[0]
            jobs.complete_tts_delivery(
                claimed["id"],
                delivered=False,
                reconciliation_required=True,
                uploaded_at=1_700_000_000,
                sender_profile="irang",
            )
            default = _FakeTdl(message_id=None)
            irang = _FakeTdl(lookup_error=RuntimeError("CHANNEL_PRIVATE"))

            executor = self._dispatch_retry(
                root, jobs, job_id,
                {"default": default, "irang": irang},
                ["default", "irang"],
            )

            self.assertEqual(len(irang.time_exports), 1)
            self.assertEqual(default.time_exports, [])
            self.assertEqual(default.uploads, [])
            self.assertEqual(irang.uploads, [])
            self.assertTrue(any(
                "TTS_CHANNEL_UNAVAILABLE" in str(kwargs.get("error", {}).get("message", ""))
                for _args, kwargs in executor.events
            ))

    def test_tts_retry_requires_exact_attachment_and_caption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-exact-match"
            jobs = self._prepare_job(root, job_id)
            claimed = jobs.claim_tts_deliveries(
                1, worker="local", job_id=job_id, include_artifact_ref=True
            )[0]
            item = jobs.complete_tts_delivery(
                claimed["id"],
                delivered=False,
                reconciliation_required=True,
                uploaded_at=time.time(),
                sender_profile="default",
            )
            tdl = _FakeTdl(message_id=None)
            tdl.messages = []
            tdl.messages.append({
                "id": 778,
                "date": time.time(),
                "file_name": "different.mp3",
                "caption": "Bab 4",
            })

            self._dispatch_retry(root, jobs, job_id, tdl, ["default"])

            self.assertEqual(len(tdl.uploads), 1)
            self.assertEqual(jobs.get_tts_delivery(item["id"])["status"], "delivered")

    def test_successful_export_without_caption_uploads_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-absent"
            jobs = self._prepare_job(root, job_id)
            self._unconfirmed_delivery(jobs, job_id)
            with jobs._db() as db:
                db.execute(
                    "UPDATE job_tts_deliveries SET artifact_ref = ? WHERE job_id = ?",
                    ("b" * 48, job_id),
                )
            tdl = _FakeTdl(message_id=None)

            self._dispatch_retry(root, jobs, job_id, tdl, ["default"])

            self.assertEqual(len(tdl.time_exports), 2)
            self.assertEqual(len(tdl.uploads), 1)
            self.assertEqual(jobs.tts_delivery_summary(job_id)["delivered_parts"], 1)

    def test_explicit_upload_denial_falls_back_after_exact_export_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-fallback"
            jobs = self._prepare_job(root, job_id)
            self._unconfirmed_delivery(jobs, job_id)
            denied = _FakeTdl(upload_error=RuntimeError("CHAT_WRITE_FORBIDDEN"))
            denied.messages = []
            accessible = _FakeTdl(message_id=None)

            self._dispatch_retry(
                root, jobs, job_id,
                {"default": denied, "irang": accessible},
                ["default", "irang"],
            )

            self.assertEqual(len(denied.time_exports), 1)
            self.assertEqual(len(accessible.time_exports), 1)
            self.assertEqual(len(denied.uploads), 1)
            self.assertEqual(len(accessible.uploads), 1)
            self.assertEqual(jobs.tts_delivery_summary(job_id)["delivered_parts"], 1)

    def test_retry_after_explicit_tdl_denial_sends_known_unsent_part(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-known-unsent"
            jobs = self._prepare_job(root, job_id)
            denied = _FakeTdl(upload_error=RuntimeError("CHAT_WRITE_FORBIDDEN"))

            first_executor = self._dispatch_retry(root, jobs, job_id, denied, ["default"])

            self.assertEqual(len(denied.uploads), 1)
            with jobs._db() as db:
                row = db.execute(
                    "SELECT status, last_error_code, uploaded_at FROM job_tts_deliveries WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["last_error_code"], "TELEGRAM_SEND_FAILED")
            self.assertIsNone(row["uploaded_at"])
            self.assertTrue(any(
                "TTS_CHANNEL_UNAVAILABLE" in str(kwargs.get("error", {}).get("message", ""))
                for _args, kwargs in first_executor.events
            ))

            accessible = _FakeTdl(message_id=None)
            self._dispatch_retry(root, jobs, job_id, accessible, ["default"])

            self.assertEqual(len(accessible.time_exports), 1)
            self.assertEqual(len(accessible.uploads), 1)
            self.assertEqual(jobs.tts_delivery_summary(job_id)["delivered_parts"], 1)

    def test_retry_reconciles_if_tdl_accepts_then_raises_transport_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-accepted-timeout"
            jobs = self._prepare_job(root, job_id)
            clock = _FakeClock(1_700_000_000)
            tdl = _FakeTdl(upload_error_after_accept=RuntimeError("transport timeout"))
            tdl.clock = clock
            tdl.upload_duration_seconds = 75

            with patch("tme3bot.worker.executor_tts.time", clock):
                self._dispatch_retry(root, jobs, job_id, tdl, ["default"])

            self.assertEqual(len(tdl.uploads), 1)
            with jobs._db() as db:
                row = db.execute(
                    "SELECT status, uploaded_at, sender_profile, last_error_code FROM job_tts_deliveries WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
            self.assertEqual(row["status"], "reconciliation_required")
            self.assertEqual(row["uploaded_at"], 1_700_000_000)
            self.assertEqual(row["sender_profile"], "default")
            self.assertEqual(row["last_error_code"], "TDL_UPLOAD_IN_PROGRESS")

            tdl.upload_error_after_accept = None
            with patch("tme3bot.worker.executor_tts.time", clock):
                self._dispatch_retry(root, jobs, job_id, tdl, ["default"])

            self.assertEqual(len(tdl.uploads), 1)
            self.assertEqual(
                tdl.time_exports[-1][1:3],
                (1_699_999_940, 1_700_000_135),
            )
            self.assertEqual(jobs.tts_delivery_summary(job_id)["delivered_parts"], 1)

    def test_retry_recovers_when_immediate_verified_result_write_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-result-write"
            jobs = self._prepare_job(root, job_id)
            tdl = _FakeTdl(message_id=None)

            self._dispatch_retry(
                root,
                jobs,
                job_id,
                tdl,
                ["default"],
                fail_delivered_once=True,
            )

            self.assertEqual(len(tdl.uploads), 1)
            with jobs._db() as db:
                row = db.execute(
                    "SELECT id, status, uploaded_at, sender_profile FROM job_tts_deliveries WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                db.execute(
                    "UPDATE job_tts_deliveries SET lease_until = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                    (row["id"],),
                )
            self.assertEqual(row["status"], "claimed")
            self.assertIsNotNone(row["uploaded_at"])
            self.assertEqual(row["sender_profile"], "default")

            self._dispatch_retry(root, jobs, job_id, tdl, ["default"])

            self.assertEqual(len(tdl.uploads), 1)
            self.assertEqual(jobs.tts_delivery_summary(job_id)["delivered_parts"], 1)

    def test_slow_upload_verification_window_uses_success_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-slow-upload-window"
            jobs = self._prepare_job(root, job_id)
            clock = _FakeClock(1_700_000_000)
            tdl = _FakeTdl(message_id=None)
            tdl.clock = clock
            tdl.upload_duration_seconds = 75

            with patch("tme3bot.worker.executor_tts.time", clock):
                self._dispatch_retry(root, jobs, job_id, tdl, ["default"])

            self.assertEqual(len(tdl.uploads), 1)
            self.assertEqual(
                tdl.time_exports[-1][1:3],
                (1_700_000_015, 1_700_000_135),
            )
            self.assertEqual(jobs.tts_delivery_summary(job_id)["delivered_parts"], 1)

    def test_legacy_delivery_without_sender_or_time_stays_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-retry-denied"
            jobs = self._prepare_job(root, job_id)
            item = self._legacy_unconfirmed_delivery(jobs, job_id)
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
            self.assertEqual(len(denied_default.time_exports), 0)
            self.assertEqual(len(denied_irang.time_exports), 0)
            self.assertEqual(jobs.get_tts_delivery(item["id"])["status"], "reconciliation_required")
            self.assertTrue(any(
                "TTS_DELIVERY_RECONCILIATION_FAILED" in str(kwargs.get("error", {}).get("message", ""))
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

            self.assertEqual(len(default.time_exports), 1)
            self.assertEqual(len(irang.time_exports), 0)
            self.assertEqual(len(default.uploads), 1)
            self.assertEqual(len(irang.uploads), 1)
            self.assertEqual(
                jobs.get_tts_delivery(item["id"])["status"],
                "pending",
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
                second["id"],
                delivered=False,
                reconciliation_required=True,
                uploaded_at=time.time(),
                sender_profile="default",
            )
            tdl = _FakeTdl(message_id=None)

            self._dispatch_retry(root, jobs, job_id, tdl, ["default"], parts=2)

            self.assertEqual(len(tdl.time_exports), 2)
            self.assertEqual([upload[2] for upload in tdl.uploads], ["Bab 4 (2/2)"])
            self.assertEqual(jobs.get_tts_delivery(first["id"])["status"], "delivered")

    def test_each_tts_upload_is_verified_then_batch_export_resolves_delayed_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-batch-window"
            jobs = self._prepare_job(root, job_id, parts=2)
            self._unconfirmed_delivery(jobs, job_id)
            tdl = _FakeTdl(message_id=None, visible_after_exports=4)

            self._dispatch_retry(root, jobs, job_id, tdl, ["default"], parts=2)

            self.assertEqual(len(tdl.uploads), 2)
            self.assertEqual(len(tdl.time_exports), 4)  # One retry check, two immediate checks, one batch check.
            self.assertEqual(jobs.tts_delivery_summary(job_id)["delivered_parts"], 2)
            self.assertEqual(jobs.tts_delivery_summary(job_id)["verification_pending_parts"], 0)

    def test_tts_upload_absent_from_both_exports_stays_ambiguous_without_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-batch-unverified"
            jobs = self._prepare_job(root, job_id)
            item = self._unconfirmed_delivery(jobs, job_id)
            tdl = _FakeTdl(message_id=None, visible_after_exports=999)

            executor = self._dispatch_retry(root, jobs, job_id, tdl, ["default"])

            self.assertEqual(len(tdl.uploads), 1)
            self.assertEqual(len(tdl.time_exports), 3)
            self.assertEqual(jobs.get_tts_delivery(item["id"])["status"], "reconciliation_required")
            self.assertEqual(jobs.tts_delivery_summary(job_id)["delivered_parts"], 0)
            self.assertTrue(any(
                "TTS_DELIVERY_NOT_VERIFIED" in str(kwargs.get("error", {}).get("message", ""))
                for _args, kwargs in executor.events
            ))

    def test_cancel_preserves_audio_artifact_when_upload_verification_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-cancel-unverified"
            jobs = self._prepare_job(root, job_id)
            tdl = _FakeTdl(message_id=None, visible_after_exports=999)

            self._dispatch_retry(
                root,
                jobs,
                job_id,
                tdl,
                ["default"],
                cancel_on_upload=True,
            )

            artifact_path = root / "tts" / job_id / f"artifact-{1:048x}.mp3"
            with jobs._db() as db:
                delivery = dict(db.execute(
                    "SELECT * FROM job_tts_deliveries WHERE job_id = ?",
                    (job_id,),
                ).fetchone())
            self.assertTrue(artifact_path.is_file())
            self.assertEqual(delivery["status"], "reconciliation_required")
            self.assertIsNotNone(delivery["uploaded_at"])
            self.assertEqual(delivery["sender_profile"], "default")

    def test_cancel_preserves_persisted_verification_artifact_before_item_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "tts-cancel-persisted-unverified"
            jobs = self._prepare_job(root, job_id)
            claimed = jobs.claim_tts_deliveries(
                1, worker="local", job_id=job_id, include_artifact_ref=True
            )[0]
            jobs.complete_tts_delivery(
                claimed["id"],
                delivered=False,
                verification_pending=True,
                uploaded_at=time.time(),
                sender_profile="default",
            )
            tdl = _FakeTdl(message_id=None)

            self._dispatch_retry(
                root,
                jobs,
                job_id,
                tdl,
                ["default"],
                cancel_before_worker=True,
            )

            artifact_path = root / "tts" / job_id / f"artifact-{1:048x}.mp3"
            delivery = jobs.get_tts_delivery(claimed["id"])
            self.assertTrue(artifact_path.is_file())
            self.assertEqual(delivery["status"], "claimed")
            self.assertIsNotNone(delivery["uploaded_at"])
            self.assertEqual(delivery["sender_profile"], "default")


if __name__ == "__main__":
    unittest.main()
