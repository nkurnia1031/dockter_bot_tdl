import hashlib
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from tme3bot.application.job_scheduler import build_execution_plan
from tme3bot.worker.command_store import WorkerCommandStore
from tme3bot.worker.executor import WorkerJobExecutor
from tme3bot.worker.executor_storage import StorageExecutorMixin


class _UploadMetrics:
    def __init__(self, parallel=False):
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(2) if parallel else None
        self.active = {}
        self.maximum = {}
        self.total_active = 0
        self.maximum_total = 0
        self.next_message_id = 100


class _UploadClient:
    def __init__(self, profile, metrics, behavior=None):
        self.profile = profile
        self.metrics = metrics
        self.behavior = behavior or {}
        self.uploads = []
        self.captions = {}
        self.export_messages = []
        self.export_calls = []

    def upload(self, path, _target, _caption, *, status_callback=None, **_kwargs):
        path = Path(path)
        self.uploads.append(path.name)
        self.captions[path.name] = _caption
        action = self.behavior.get(path.name)
        if action == "pre_send_failure":
            raise RuntimeError("failure before tdl starts upload")
        if status_callback:
            status_callback("uploading")
        with self.metrics.lock:
            self.metrics.active[self.profile] = self.metrics.active.get(self.profile, 0) + 1
            self.metrics.maximum[self.profile] = max(
                self.metrics.maximum.get(self.profile, 0),
                self.metrics.active[self.profile],
            )
            self.metrics.total_active += 1
            self.metrics.maximum_total = max(
                self.metrics.maximum_total, self.metrics.total_active
            )
            message_id = self.metrics.next_message_id
            self.metrics.next_message_id += 1
        try:
            if self.metrics.barrier is not None:
                self.metrics.barrier.wait(timeout=3)
            if action == "ambiguous_failure":
                raise RuntimeError("connection lost after upload started")
            time.sleep(0.02)
            if status_callback:
                status_callback("uploaded")
            return SimpleNamespace(message_id=message_id)
        finally:
            with self.metrics.lock:
                self.metrics.active[self.profile] -= 1
                self.metrics.total_active -= 1

    def export_messages_by_time(self, target, start, end, export_path, *, with_content=True):
        self.export_calls.append((target, start, end, with_content, Path(export_path).name))
        if self.behavior.get("reconcile_export") == "failure":
            raise RuntimeError("private runner failure detail")
        return SimpleNamespace(messages=self.export_messages)


class _BatchUploader(StorageExecutorMixin):
    def __init__(self, workspace, command_store, *, parallel=False, behavior=None):
        self.workspace = workspace
        self.command_store = command_store
        self._lock = threading.RLock()
        self._cancel_requested = set()
        self.events = []
        self.metrics = _UploadMetrics(parallel=parallel)
        self.session_fingerprints = {"default": "a" * 64, "archive": "b" * 64}
        self.config = SimpleNamespace(
            utility_workspace_root=workspace.parent,
            profile_root=workspace.parent,
        )
        self.runtimes = {}
        for profile, message_id in (("default", 10), ("archive", 20)):
            client = _UploadClient(profile, self.metrics, behavior)
            self.runtimes[profile] = SimpleNamespace(
                config=SimpleNamespace(
                    storage_channel_ref="-100123",
                    storage_channel_id=1000 + message_id,
                ),
                upload_tdl_client=client,
                upload_operation_lock=threading.RLock(),
            )
        self.profile_manager = SimpleNamespace(
            list_profiles=lambda: list(self.runtimes),
            runtime=lambda profile: self.runtimes[profile],
        )
        self.publisher = SimpleNamespace(
            emit=lambda *args, **kwargs: self.events.append((args, kwargs))
        )

    def available_storage_profiles(self):
        return list(self.runtimes)

    def available_storage_session_fingerprints(self, profiles=None):
        selected = profiles if profiles is not None else self.available_storage_profiles()
        return {
            profile: self.session_fingerprints[profile]
            for profile in selected
            if profile in self.session_fingerprints
        }

    def _workspace_path(self, raw):
        return Path(raw)

    @staticmethod
    def _digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size

    @staticmethod
    @contextmanager
    def _capture_tdl_output(_client):
        yield

    @staticmethod
    @contextmanager
    def _capture_tdl_progress(_client, _callback):
        yield

    def _append_job_log(self, _message):
        return None

    def command(self, workspace, command_id="storage-command"):
        envelope = {
            "command_id": command_id,
            "operation_id": "storage-operation",
            "job_id": "storage-job",
            "attempt": 1,
            "dispatch_token": "dispatch-token",
            "execution_plan": {"resource_keys": ["worker:local:kind:storage_upload"]},
            "job": {
                "kind": "storage_upload",
                "profile": "default",
                "actor_user_id": 42,
                "worker": "local",
                "payload": {},
            },
        }
        self.command_store.accept(envelope)
        self.command_store.set_status(command_id, "running", only_from=("accepted",))
        return {
            "job_id": "storage-job",
            "command_id": command_id,
            "kind": "storage_upload",
            "profile": "default",
            "payload": {
                "batch_id": "batch-1",
                "folder_path": str(workspace),
                "destination_folder_id": "folder-1",
                "destination_folder_path": "",
                "owner_user_id": 42,
                "owner_profile": "default",
                "keywords": "",
                "preserve_structure": False,
                "root_files_only": False,
                "allowed_names": [],
                "photo_names": [],
                "rclone_upload": False,
                "tdl_access_target": "-100123",
                "_tdl_sender_profiles": ["default", "archive"],
                "_tdl_sender_session_fingerprints": dict(self.session_fingerprints),
            },
        }


class StorageUploadBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "source"
        self.workspace.mkdir()
        self.store = WorkerCommandStore(self.root / "worker.sqlite3")
        self.reconcile_scenario = 0

    def tearDown(self):
        self.temp.cleanup()

    def _add_files(self, *names):
        for name in names:
            (self.workspace / name).write_text(f"body:{name}", encoding="utf-8")

    def test_storage_batches_share_worker_lock_without_reserving_export_or_download(self):
        sender_profiles = ["default", "archive"]
        first = build_execution_plan(
            "storage_upload", "default", "local",
            {"_tdl_sender_profiles": sender_profiles, "priority": "next"},
        )
        second = build_execution_plan(
            "storage_upload", "archive", "local",
            {"_tdl_sender_profiles": sender_profiles},
        )
        export = build_execution_plan("export", "default", "local", {})
        download = build_execution_plan("download", "default", "local", {})

        self.assertTrue(first.resource_keys & second.resource_keys)
        self.assertFalse(first.resource_keys & export.resource_keys)
        self.assertFalse(first.resource_keys & download.resource_keys)
        self.assertEqual(first.lane, "tdl-storage")
        self.assertEqual(first.priority, 100)
        self.assertEqual(second.priority, 100)

    def test_durable_batch_runs_fifo_files_in_parallel_with_one_file_per_upload_lane(self):
        self._add_files("one.txt", "two.txt", "three.txt", "four.txt")
        uploader = _BatchUploader(self.workspace, self.store, parallel=True)

        result = uploader._storage_upload(uploader.command(self.workspace))

        self.assertEqual(result["outcome"], "succeeded")
        self.assertEqual(result["succeeded"], 4)
        self.assertGreaterEqual(uploader.metrics.maximum_total, 2)
        self.assertEqual(uploader.metrics.maximum, {"default": 1, "archive": 1})
        progress_snapshots = [
            kwargs.get("progress", {})
            for args, kwargs in uploader.events
            if len(args) > 2 and args[2] == "progress.snapshot"
        ]
        overlapping_items = next(
            (
                snapshot.get("active_items")
                for snapshot in progress_snapshots
                if len(snapshot.get("active_items") or []) >= 2
            ),
            None,
        )
        self.assertIsNotNone(overlapping_items)
        self.assertEqual(
            {item["profile"] for item in overlapping_items},
            {"default", "archive"},
        )
        self.assertEqual(len({item["name"] for item in overlapping_items}), 2)
        items = self.store.storage_upload_items("storage-command")
        self.assertEqual([item["name"] for item in items], ["four.txt", "one.txt", "three.txt", "two.txt"])
        self.assertTrue(all(item["status"] == "succeeded" for item in items))
        self.assertTrue(all(len(item["attempts"]) == 1 for item in items))
        self.assertEqual(
            {item["profile"] for item in items},
            {"default", "archive"},
        )

    def test_durable_batch_checkpoints_successful_files_through_callback(self):
        self._add_files("one.txt", "two.txt")
        uploader = _BatchUploader(self.workspace, self.store, parallel=True)
        checkpoints = []

        result = uploader._storage_upload(
            uploader.command(self.workspace),
            upload_item_callback=lambda items: checkpoints.append(
                [item["original_name"] for item in items]
            ),
        )

        self.assertEqual(result["outcome"], "succeeded")
        self.assertEqual(len(checkpoints), 2)
        self.assertEqual(set(checkpoints[-1]), {"one.txt", "two.txt"})
        for previous, current in zip(checkpoints, checkpoints[1:]):
            self.assertTrue(set(previous).issubset(current))

    def test_batch_reports_partial_failure_and_marks_only_pre_send_failure_retryable(self):
        self._add_files("safe.txt", "ambiguous.txt", "success.txt")
        uploader = _BatchUploader(
            self.workspace,
            self.store,
            behavior={
                "safe.txt": "pre_send_failure",
                "ambiguous.txt": "ambiguous_failure",
            },
        )

        result = uploader._storage_upload(uploader.command(self.workspace))

        self.assertEqual(result["outcome"], "partial_failure", result)
        self.assertEqual(result["succeeded"], 1)
        items = {item["name"]: item for item in result["items"]}
        self.assertEqual(items["safe.txt"]["status"], "failed")
        self.assertTrue(items["safe.txt"]["retryable"])
        self.assertEqual(items["ambiguous.txt"]["status"], "needs_reconciliation")
        self.assertFalse(items["ambiguous.txt"]["retryable"])
        self.assertEqual(items["success.txt"]["status"], "succeeded")
        persisted = {item["name"]: item for item in self.store.storage_upload_items("storage-command")}
        self.assertEqual(persisted["ambiguous.txt"]["status"], "needs_reconciliation")
        self.assertFalse(persisted["ambiguous.txt"]["retryable"])

    def test_all_failed_batch_reports_reconciliation_and_keeps_safe_retry_available(self):
        self._add_files("safe.txt", "ambiguous.txt")
        uploader = _BatchUploader(
            self.workspace,
            self.store,
            behavior={
                "safe.txt": "pre_send_failure",
                "ambiguous.txt": "ambiguous_failure",
            },
        )

        result = uploader._storage_upload(uploader.command(self.workspace))

        self.assertEqual(result["outcome"], "needs_reconciliation")
        self.assertEqual(result["succeeded"], 0)
        self.assertTrue(result["retryable"])
        statuses = {item["name"]: item["status"] for item in result["items"]}
        self.assertEqual(statuses, {
            "ambiguous.txt": "needs_reconciliation",
            "safe.txt": "failed",
        })

    def test_changed_upload_session_is_recorded_as_safe_without_sending(self):
        self._add_files("safe.txt")
        uploader = _BatchUploader(self.workspace, self.store)
        uploader.session_fingerprints["default"] = "c" * 64
        command = uploader.command(self.workspace)
        command["payload"]["_tdl_sender_profiles"] = ["default"]
        command["payload"]["_tdl_sender_session_fingerprints"] = {"default": "a" * 64}

        result = uploader._storage_upload(command)

        self.assertEqual(result["outcome"], "failed")
        self.assertTrue(result["items"][0]["retryable"])
        self.assertEqual(uploader.runtimes["default"].upload_tdl_client.uploads, [])

    def test_missing_verified_lane_keeps_every_file_safe_to_retry(self):
        self._add_files("one.txt", "two.txt")
        uploader = _BatchUploader(self.workspace, self.store)
        uploader.available_storage_profiles = lambda: []

        result = uploader._storage_upload(uploader.command(self.workspace))

        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["succeeded"], 0)
        self.assertTrue(all(item["retryable"] for item in result["items"]))
        self.assertTrue(all(item["profile"] == "" for item in result["items"]))

    def test_restart_reports_completed_and_pending_files_without_replaying_ambiguous_file(self):
        command_id = "recover-storage"
        self.store.accept({
            "command_id": command_id,
            "operation_id": "storage-operation",
            "job_id": "storage-job-recover",
            "attempt": 1,
            "dispatch_token": "dispatch-token",
            "execution_plan": {"resource_keys": ["worker:local:kind:storage_upload"]},
            "job": {
                "kind": "storage_upload",
                "profile": "default",
                "actor_user_id": 42,
                "worker": "local",
                "payload": {},
            },
        })
        self.store.set_status(command_id, "running", only_from=("accepted",))
        self.store.record_storage_upload_item(
            command_id,
            "done.txt",
            file_name="done.txt",
            status="succeeded",
            attempt=1,
            profile="default",
            message_id=44,
            result_item={"upload_id": "done-upload", "channel_message_id": 44},
        )
        self.store.record_storage_upload_item(
            command_id,
            "waiting.txt",
            file_name="waiting.txt",
            status="pending",
            attempt=0,
            retryable=True,
        )
        self.store.record_storage_upload_item(
            command_id,
            "uncertain.txt",
            file_name="uncertain.txt",
            status="sending",
            attempt=1,
            profile="archive",
        )
        self.store.recover_startup()
        emitted = []
        publisher = SimpleNamespace(
            bind_command=lambda *args: emitted.append(("bind_command", args)),
            bind_job_worker=lambda *args: emitted.append(("bind_job_worker", args)),
            emit=lambda *args, **kwargs: emitted.append(("emit", args, kwargs)),
        )
        executor = object.__new__(WorkerJobExecutor)
        executor.command_store = self.store
        executor.publisher = publisher

        executor._publish_storage_upload_recoveries()
        executor._publish_storage_upload_recoveries()

        item_events = [
            (event[1], event[2])
            for event in emitted
            if event[0] == "emit"
            and len(event[1]) > 2
            and event[1][2] == "storage.item_uploaded"
        ]
        terminal_events = [
            (event[1], event[2])
            for event in emitted
            if event[0] == "emit"
            and len(event[1]) > 2
            and event[1][2] == "storage.batch_interrupted"
        ]
        self.assertEqual(len(item_events), 1)
        self.assertEqual(len(terminal_events), 1)
        result_items = terminal_events[0][1]["result"]["value"]["items"]
        item_status = {item["name"]: item for item in result_items}
        self.assertEqual(item_status["done.txt"]["status"], "succeeded")
        self.assertEqual(item_status["waiting.txt"]["status"], "pending")
        self.assertTrue(item_status["waiting.txt"]["retryable"])
        self.assertEqual(item_status["uncertain.txt"]["status"], "needs_reconciliation")
        self.assertFalse(item_status["uncertain.txt"]["retryable"])
        self.assertEqual(self.store.list_storage_reconciliation_commands(), [])

    def _prepare_reconcile(self, names, messages, *, caption_override=False, export_failure=False):
        self.reconcile_scenario += 1
        scenario_root = self.root / f"reconcile-{self.reconcile_scenario}"
        workspace = scenario_root / "source"
        workspace.mkdir(parents=True)
        store = WorkerCommandStore(scenario_root / "worker.sqlite3")
        for name in names:
            (workspace / name).write_text(f"body:{name}", encoding="utf-8")
        behavior = {name: "ambiguous_failure" for name in names}
        if export_failure:
            behavior["reconcile_export"] = "failure"
        uploader = _BatchUploader(workspace, store, behavior=behavior)
        command = uploader.command(workspace)
        if caption_override:
            command["payload"].update(
                caption_override=True,
                caption="same exact caption",
            )
        upload_result = uploader._storage_upload(command)
        source_items = store.storage_upload_items_for_job("storage-job")["items"]
        for runtime in uploader.runtimes.values():
            runtime.upload_tdl_client.export_messages = messages
        reconcile_command = {
            "job_id": "reconcile-job",
            "kind": "storage_reconcile",
            "profile": "default",
            "payload": {
                "source_job_id": "storage-job",
                "start_timestamp": 100,
                "end_timestamp": 200,
                "tdl_access_target": "-100123",
                "_tdl_sender_profiles": ["default", "archive"],
                "_tdl_sender_session_fingerprints": dict(uploader.session_fingerprints),
                "_storage_reconcile_items": [
                    {
                        "index": index,
                        "path": item["path"],
                        "name": item["name"],
                        "profile": item["profile"],
                    }
                    for index, item in enumerate(upload_result["items"])
                ],
            },
        }
        return uploader, upload_result, source_items, reconcile_command, store

    def test_reconciliation_marks_zero_and_one_exact_caption_safely(self):
        uploader, upload_result, source_items, command, _store = self._prepare_reconcile(
            ["one.txt"], []
        )
        result = uploader._storage_reconcile(command)
        self.assertEqual(result["outcome"], "succeeded")
        self.assertEqual(result["items"][0]["status"], "failed")
        self.assertTrue(result["items"][0]["retryable"])
        self.assertNotIn("path", result["items"][0])
        self.assertNotIn(source_items[0]["caption"], repr(result))
        profile = upload_result["items"][0]["profile"]
        self.assertEqual(
            uploader.runtimes[profile].upload_tdl_client.export_calls[0][:4],
            ("-100123", 100, 200, True),
        )

        caption = source_items[0]["caption"]
        uploader, _upload_result, _source_items, command, _store = self._prepare_reconcile(
            ["one.txt"], [{"id": 7, "caption": caption}]
        )
        result = uploader._storage_reconcile(command)
        self.assertEqual(result["items"][0]["status"], "succeeded")
        self.assertFalse(result["items"][0]["retryable"])
        self.assertEqual(result["items"][0]["match_count"], 1)

    def test_reconciliation_duplicate_captions_require_enough_exact_matches(self):
        uploader, _upload_result, _source_items, command, _store = self._prepare_reconcile(
            ["one.txt", "two.txt"],
            [{"id": 7, "caption": "same exact caption"}],
            caption_override=True,
        )
        result = uploader._storage_reconcile(command)
        self.assertTrue(all(item["status"] == "needs_reconciliation" for item in result["items"]))
        self.assertTrue(all(not item["retryable"] for item in result["items"]))

        uploader, _upload_result, _source_items, command, _store = self._prepare_reconcile(
            ["one.txt", "two.txt"],
            [
                {"id": 7, "caption": "same exact caption"},
                {"id": 8, "caption": "same exact caption"},
            ],
            caption_override=True,
        )
        result = uploader._storage_reconcile(command)
        self.assertTrue(all(item["status"] == "succeeded" for item in result["items"]))
        self.assertTrue(all(item["match_count"] == 2 for item in result["items"]))

    def test_reconciliation_export_failure_and_incomplete_restart_stay_ambiguous(self):
        uploader, _upload_result, _source_items, command, store = self._prepare_reconcile(
            ["one.txt"], [{"id": 7, "file_name": "one.txt"}]
        )
        reopened = WorkerCommandStore(store.path)
        reopened.recover_startup()
        uploader.command_store = reopened
        result = uploader._storage_reconcile(command)
        self.assertEqual(result["items"][0]["status"], "needs_reconciliation")
        self.assertFalse(result["items"][0]["retryable"])

        uploader, _upload_result, source_items, command, _store = self._prepare_reconcile(
            ["one.txt"],
            [{"id": 7, "caption": "unrelated"}],
            export_failure=True,
        )
        result = uploader._storage_reconcile(command)
        self.assertEqual(result["items"][0]["status"], "needs_reconciliation")
        self.assertFalse(result["items"][0]["retryable"])
        self.assertNotIn("private runner failure detail", repr(result))
        self.assertNotIn(source_items[0]["caption"], repr(result))


if __name__ == "__main__":
    unittest.main()
