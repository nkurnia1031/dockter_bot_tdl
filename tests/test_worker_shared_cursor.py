import json
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tme3bot.application.export_cursor import ExportCursorService
from tme3bot.service import ExportJobResult
from tme3bot.state import HttpStateStore, StateApiError
from tme3bot.worker.command_store import WorkerCommandStore
from tme3bot.worker.executor import WorkerJobExecutor
from tme3bot.url_parser import parse_tme3_url


class WorkerSharedCursorTests(unittest.TestCase):
    def test_transient_commit_failure_retries_without_reporting_success(self):
        class Publisher:
            def __init__(self):
                self.events = []

            def emit(self, *args, **kwargs):
                self.events.append((args, kwargs))

        executor = WorkerJobExecutor.__new__(WorkerJobExecutor)
        executor.publisher = Publisher()
        attempts = []

        def commit(**request):
            attempts.append(request)
            if len(attempts) == 1:
                raise StateApiError("temporary", status_code=503)
            return {"status": "applied"}

        with patch("tme3bot.worker.executor.time.sleep") as sleep:
            result = executor._submit_cursor_commit(
                {"job_id": "job-retry"}, commit, {"last_id": 33}
            )

        self.assertEqual(result, {"status": "applied"})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual(executor.publisher.events[0][0][2], "export.cursor_commit_pending")
        sleep.assert_called_once_with(1)

    def test_export_resolves_leases_and_commits_before_json_ready(self):
        order = []

        class FakeStateStore:
            def __init__(self):
                self.commits = []

            def resolve_export_peer(self, **values):
                order.append("resolve")
                self.resolved = values
                return {"resolved": True}

            def acquire_export_cursor(self, **values):
                order.append("lease")
                self.lease_request = values
                return {"last_id": 54, "revision": 2, "fencing_token": 7}

            def heartbeat_export_cursor(self, **values):
                order.append("heartbeat")
                return {"ok": True}

            def commit_export_cursor(self, **values):
                order.append("commit")
                self.commits.append(values)
                return {"status": "applied"}

        class FakeTdl:
            output_callback = None
            progress_callback = None

            def resolve_chat_peer(self, chat_ref):
                order.append("tdl_resolve")
                self.chat_ref = chat_ref
                return {"peer_type": "channel", "peer_id": "-100123"}

        class FakeExportService:
            def __init__(self, export_path):
                self.export_path = export_path
                self.calls = []

            def validate_url(self, url):
                return parse_tme3_url(url, "t.me3")

            def export_from_url(self, url, **kwargs):
                order.append("export")
                self.calls.append((url, kwargs))
                self.export_path.write_text(
                    json.dumps({
                        "messages": [{"id": 60, "type": "photo", "file": "p.jpg"}],
                        "tme3bot": {"chat_ref": "newsfeed", "label": None},
                    }),
                    encoding="utf-8",
                )
                return ExportJobResult(
                    status="exported", chat_ref="newsfeed", requested_label=None,
                    export_path=self.export_path, start_id=55, latest_id=54,
                    exported_count=1, has_media=True, warmup_required=False, end_id=60,
                )

        class Publisher:
            def emit(self, job_id, status, event_type, **kwargs):
                del job_id, status
                if event_type == "export.json_ready":
                    order.append("json_ready")
                self.last_event = (event_type, kwargs)

        with tempfile.TemporaryDirectory() as raw:
            export_path = Path(raw) / "export.json"
            state = FakeStateStore()
            tdl = FakeTdl()
            export_service = FakeExportService(export_path)
            runtime = SimpleNamespace(
                state_store=state,
                export_service=export_service,
                export_tdl_client=tdl,
                export_operation_lock=threading.RLock(),
            )
            publisher = Publisher()
            executor = WorkerJobExecutor.__new__(WorkerJobExecutor)
            executor.config = SimpleNamespace(backup_node_name="local")
            executor.profile_manager = SimpleNamespace(runtime=lambda _profile: runtime)
            executor.publisher = publisher
            executor._capture_tdl_output = lambda _client: nullcontext()
            executor._capture_tdl_progress = lambda _client, _callback: nullcontext()

            executor._export({
                "job_id": "job-cursor",
                "kind": "export",
                "profile": "default",
                "worker": "local",
                "attempt": 1,
                "payload": {
                    "url": "https://t.me3/c/@NewsFeed/1",
                    "_shared_export_cursor": True,
                },
            })

        self.assertEqual(order[:5], ["tdl_resolve", "resolve", "lease", "export", "commit"])
        self.assertLess(order.index("commit"), order.index("json_ready"))
        self.assertEqual(export_service.calls[0][1]["export_start_id"], 55)
        self.assertFalse(export_service.calls[0][1]["read_source"])
        self.assertFalse(export_service.calls[0][1]["save_source"])
        self.assertEqual(state.commits[0]["last_id"], 60)
        self.assertTrue(state.commits[0]["artifact"]["catalog"])

    def test_http_state_store_uses_authenticated_cursor_contract(self):
        class RecordingStore(HttpStateStore):
            def __init__(self):
                super().__init__("https://backend.test", "private-token", "default")
                self.calls = []

            def _request(self, method, path, payload=None):
                self.calls.append((method, path, payload))
                return {"ok": True}

        store = RecordingStore()
        store.resolve_export_peer(
            job_id="job-1", worker="local", attempt=1, requested_ref="@NewsFeed",
            peer_type="channel", peer_id="-10042",
        )
        store.acquire_export_cursor(
            job_id="job-1", worker="local", attempt=1, requested_ref="@NewsFeed"
        )
        store.heartbeat_export_cursor(
            job_id="job-1", worker="local", attempt=1, fencing_token=7
        )
        store.commit_export_cursor(
            job_id="job-1", worker="local", attempt=1, fencing_token=7,
            expected_revision=2, last_id=99,
            artifact={"artifact_kind": "empty_export", "catalog": False},
        )

        self.assertEqual(
            [call[1] for call in store.calls],
            [
                "/internal/v1/export-cursor/resolve",
                "/internal/v1/export-cursor/lease",
                "/internal/v1/export-cursor/heartbeat",
                "/internal/v1/export-cursor/commit",
            ],
        )
        self.assertEqual(store.calls[0][2]["requested_ref"], "newsfeed")
        self.assertEqual(store.calls[0][2]["profile"], "default")
        self.assertEqual(store.calls[3][2]["last_id"], 99)

    def test_empty_export_is_a_supported_non_catalog_cursor_completion(self):
        artifact = ExportCursorService._safe_artifact(
            {
                "artifact_kind": "empty_export",
                "catalog": False,
                "artifact_key": "empty.json",
                "filename": "empty.json",
                "chat_ref": "newsfeed",
                "message_count": 0,
                "media_count": 0,
            }
        )
        self.assertFalse(artifact["catalog"])
        self.assertEqual(artifact["artifact_kind"], "empty_export")

    def test_export_commit_checkpoint_is_replayed_after_worker_restart(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = WorkerCommandStore(root / "journal.sqlite3")
            envelope = {
                "command_id": "command-1",
                "attempt": 1,
                "dispatch_token": "dispatch-token",
                "job_id": "job-1",
                "job": {
                    "kind": "export",
                    "profile": "default",
                    "worker": "local",
                    "payload": {"url": "https://t.me/c/42/1"},
                },
            }
            store.accept(envelope)
            store.claim_next()
            store.mark_running("command-1")
            stored_commit = {
                "request": {"job_id": "job-1", "attempt": 1},
                "result": {
                    "status": "empty_export",
                    "chat_ref": "42",
                    "requested_label": None,
                    "export_path": str(root / "empty.json"),
                    "start_id": 1,
                    "latest_id": 9,
                    "exported_count": 0,
                    "has_media": False,
                    "warmup_required": False,
                    "warning": None,
                    "end_id": None,
                },
                "stats": {"media_count": 0},
            }
            store.set_status(
                "command-1", "running", phase="cursor_commit_pending",
                checkpoint={"cursor_commit": stored_commit},
            )
            store.append_event(
                "job-1",
                {
                    "command_id": "command-1",
                    "attempt": 1,
                    "dispatch_token": "dispatch-token",
                    "event_type": "progress",
                    "status": "running",
                    "progress": {"phase": "exporting"},
                },
                transient=True,
            )

            recovered = store.recover_startup()

            self.assertEqual(recovered["requeued"], 1)
            snapshot = store.get("command-1")
            self.assertEqual(snapshot["status"], "accepted")
            self.assertEqual(snapshot["checkpoint"]["cursor_commit"], stored_commit)

    def test_executor_persists_commit_before_call_and_replays_idempotently(self):
        class FakeCommandStore:
            def __init__(self):
                self.status = None

            def set_status(self, command_id, status, **kwargs):
                self.status = {"command_id": command_id, "status": status, **kwargs}

            def get(self, command_id):
                return self.status if self.status and self.status["command_id"] == command_id else None

        class FakeStateStore:
            def __init__(self):
                self.commits = []

            def commit_export_cursor(self, **request):
                self.commits.append(request)
                return {"status": "applied"}

        executor = WorkerJobExecutor.__new__(WorkerJobExecutor)
        executor.command_store = FakeCommandStore()
        executor.config = SimpleNamespace(backup_node_name="local")
        state = FakeStateStore()
        runtime = SimpleNamespace(state_store=state)
        result = ExportJobResult(
            status="empty_export", chat_ref="42", requested_label=None,
            export_path=Path("empty.json"), start_id=10, latest_id=9,
            exported_count=0, has_media=False, warmup_required=False,
        )
        stats = {"chat_ref": "42", "media_count": 0, "message_count": 0, "json_bytes": 0}
        command = {"job_id": "job-1", "command_id": "command-1", "worker": "local", "attempt": 1}
        lease = {"fencing_token": 5, "revision": 3, "last_id": 9}

        executor._commit_export_cursor(command, runtime, lease, result, stats, quick_mode=False)
        saved = executor.command_store.status["checkpoint"]["cursor_commit"]
        self.assertEqual(executor.command_store.status["phase"], "cursor_commit_pending")
        self.assertFalse(saved["request"]["artifact"]["catalog"])
        self.assertEqual(state.commits[-1]["last_id"], 9)

        restored = executor._replay_cursor_commit(command, runtime)
        self.assertEqual(restored[0].status, "empty_export")
        self.assertEqual(len(state.commits), 2)


if __name__ == "__main__":
    unittest.main()
