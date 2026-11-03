import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tme3bot.rclone import RcloneError
from tme3bot.worker.executor import WorkerJobExecutor
from tme3bot.worker.executor_storage import StorageExecutorMixin


class _Publisher:
    def __init__(self):
        self.events = []

    def emit(self, *args, **kwargs):
        self.events.append((args, kwargs))


class _RcloneManageExecutor(StorageExecutorMixin):
    def __init__(self, root: Path):
        self.config = SimpleNamespace(
            profile_root=root,
            rclone_config_path=root / "rclone.conf",
            job_stall_timeout_seconds=30,
        )
        self.publisher = _Publisher()
        self._lock = threading.RLock()
        self._cancel_requested = set()
        self._rclone_runners = {}

    def _storage_download_cancelled(self, job_id):
        return job_id in self._cancel_requested

    @staticmethod
    def _append_job_log(_line):
        return None

    @staticmethod
    def _command_callback(*, runtime=None):
        return None


class StorageRcloneManageJobTests(unittest.TestCase):
    def test_job_reports_each_item_and_continues_after_item_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executor = _RcloneManageExecutor(Path(temp_dir))

            class FakeRcloneRunner:
                calls = []

                def __init__(self, **kwargs):
                    self.cancel_check = kwargs["cancel_check"]

                def manage_storage_item(self, _destination, *, action, path, progress_callback, **kwargs):
                    del kwargs
                    self.calls.append((action, path))
                    progress_callback({
                        "bytes_current": 5,
                        "bytes_total": 10,
                        "speed_bps": 100,
                        "eta_seconds": 1,
                        "percent": 50,
                    })
                    if path == "bad.zip":
                        raise RcloneError("collision", code="RCLONE_TARGET_EXISTS")
                    return {"action": action, "path": path, "status": "succeeded"}

            with patch("tme3bot.worker.executor_storage.RcloneRunner", FakeRcloneRunner):
                result = executor._storage_rclone_manage({
                    "job_id": "manage-job",
                    "payload": {
                        "rclone_destination": "remote:root",
                        "action": "copy",
                        "destination_path": "archive",
                        "sources": [
                            {"path": "docs", "is_dir": True},
                            {"path": "docs/inside.zip", "is_dir": False},
                            {"path": "bad.zip", "is_dir": False},
                        ],
                    },
                })

        self.assertEqual(result["outcome"], "partial_failure")
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual([item["path"] for item in result["items"]], ["bad.zip", "docs"])
        self.assertEqual(result["items"][0]["error_code"], "RCLONE_TARGET_EXISTS")
        self.assertEqual(FakeRcloneRunner.calls, [("copy", "bad.zip"), ("copy", "docs")])
        progress = [
            values["progress"]
            for args, values in executor.publisher.events
            if len(args) > 2 and args[2] == "progress.snapshot"
            and values.get("progress", {}).get("transfer")
        ]
        self.assertTrue(progress)
        self.assertEqual(progress[0]["transfer"]["bytes_current"], 5)
        self.assertEqual(progress[0]["transfer"]["speed_bps"], 100)

    def test_cancel_keeps_completed_item_and_marks_remaining_items_cancelled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executor = _RcloneManageExecutor(Path(temp_dir))

            class FakeRcloneRunner:
                def __init__(self, **kwargs):
                    del kwargs

                def manage_storage_item(self, _destination, *, action, path, **kwargs):
                    del kwargs
                    executor._cancel_requested.add("cancel-job")
                    return {"action": action, "path": path, "status": "succeeded"}

            with patch("tme3bot.worker.executor_storage.RcloneRunner", FakeRcloneRunner):
                result = executor._storage_rclone_manage({
                    "job_id": "cancel-job",
                    "payload": {
                        "rclone_destination": "remote:root",
                        "action": "trash",
                        "sources": [
                            {"path": "one.zip", "is_dir": False},
                            {"path": "two.zip", "is_dir": False},
                        ],
                    },
                })

        self.assertEqual(result["outcome"], "partial_failure")
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["items"][0]["status"], "succeeded")
        self.assertEqual(result["items"][1]["status"], "cancelled")


class SharedRcloneStorageLockTests(unittest.TestCase):
    def test_direct_mutation_serializes_with_rclone_jobs(self):
        entered_mutation = threading.Event()
        release_mutation = threading.Event()
        entered_job = threading.Event()

        class FakeRcloneRunner:
            def __init__(self, **kwargs):
                del kwargs

            def create_directory(self, *_args, **_kwargs):
                self_test.assertTrue(executor._rclone_storage_lock._is_owned())
                entered_mutation.set()
                release_mutation.wait(2)
                return {"action": "create_folder", "path": "docs/new", "created": True}

        executor = object.__new__(WorkerJobExecutor)
        executor._rclone_storage_lock = threading.RLock()
        executor.config = SimpleNamespace(
            profile_root=Path("/workspace"),
            rclone_config_path=Path("/workspace/rclone.conf"),
        )
        executor._command_callback = lambda **_kwargs: None
        self_test = self

        def run_job():
            WorkerJobExecutor._execute(executor, {
                "kind": "storage_download",
                "payload": {"provider": "rclone"},
            })

        executor._execute_unlocked = lambda _command: entered_job.set()
        with patch("tme3bot.worker.executor_storage.RcloneRunner", FakeRcloneRunner):
            mutation = threading.Thread(
                target=executor.rclone_storage_mutate,
                args=("remote:root", "create_folder", "docs", "new"),
            )
            mutation.start()
            self.assertTrue(entered_mutation.wait(1))

            job = threading.Thread(target=run_job)
            job.start()
            self.assertFalse(entered_job.wait(0.05))

            release_mutation.set()
            mutation.join(1)
            job.join(1)

        self.assertFalse(mutation.is_alive())
        self.assertFalse(job.is_alive())
        self.assertTrue(entered_job.is_set())
