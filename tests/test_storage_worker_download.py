import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tme3bot.worker.executor import WorkerJobExecutor
from tme3bot.rclone import RcloneError
from tme3bot.worker.executor_storage import StorageExecutorMixin
from tme3bot.worker.executor_workspace import WorkspaceExecutorMixin
from tme3bot.worker.public_download_links import PublicDownloadLinks


class FakePublisher:
    def __init__(self):
        self.events = []

    def emit(self, job_id, status, event_type, **values):
        self.events.append((job_id, status, event_type, values))


class FakeTdlClient:
    def __init__(self, cancel=None):
        self.output_callback = None
        self.command_callback = None
        self.progress_callback = None
        self.cancel = cancel
        self.exports = []

    def export_messages(self, chat, start_id, output_path, **kwargs):
        self.exports.append((chat, start_id, Path(output_path), kwargs))
        return SimpleNamespace(messages=[{"id": start_id, "document": True}])

    def download(self, export_path, output_dir):
        (Path(output_dir) / "telegram-media.bin").write_bytes(b"telegram bytes")
        if self.cancel:
            self.cancel()


class FakeProfileManager:
    def __init__(self, client):
        self._runtime = SimpleNamespace(
            download_tdl_client=client,
            download_operation_lock=threading.RLock(),
        )

    def tdl_session_available(self, profile, lane):
        return profile == "default" and lane == "download"

    def runtime(self, profile):
        if profile != "default":
            raise ValueError("unknown profile")
        return self._runtime


class FakeRcloneRunner:
    files = []

    def __init__(self, **kwargs):
        self.cancelled = False
        self.kwargs = kwargs

    def list_download_files(self, destination, sources, config_path, *, config_root):
        return list(self.files)

    def download_file(self, remote_path, destination_path, config_path, *, config_root):
        Path(destination_path).write_bytes(f"from:{remote_path}".encode())

    def cancel_current(self):
        self.cancelled = True
        return True


class StorageDownloadHarness(StorageExecutorMixin, WorkspaceExecutorMixin):
    def __init__(self, workspace: Path, client=None):
        self.workspace = workspace
        self.config = SimpleNamespace(
            utility_workspace_root=str(workspace),
            rclone_config_path=str(workspace / "rclone.conf"),
            profile_root=str(workspace),
            job_stall_timeout_seconds=60,
        )
        Path(self.config.rclone_config_path).write_text("", encoding="utf-8")
        self.publisher = FakePublisher()
        self.profile_manager = FakeProfileManager(client) if client else None
        self._lock = threading.RLock()
        self._cancel_requested = set()
        self._rclone_runners = {}
        self.links = PublicDownloadLinks(workspace.parent / "links.db", workspace)
        self.fail_links = False

    def _append_job_log(self, line):
        return None

    def _command_callback(self):
        return None

    @contextmanager
    def _capture_tdl_progress(self, client, callback):
        previous = client.progress_callback
        client.progress_callback = callback
        try:
            yield
        finally:
            client.progress_callback = previous

    def create_storage_download_link(self, file_path, **kwargs):
        if self.fail_links:
            raise RuntimeError("registry unavailable")
        return self.links.create(file_path, **kwargs)


class StorageWorkerDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.destination = self.workspace / "destination"
        self.destination.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_telegram_download_reports_conflicts_and_publishes_only_completed_file(self):
        conflict = self.destination / "album" / "conflict.bin"
        conflict.parent.mkdir()
        conflict.write_bytes(b"existing")
        client = FakeTdlClient()
        worker = StorageDownloadHarness(self.workspace, client)
        command = {
            "job_id": "telegram-job",
            "profile": "default",
            "payload": {
                "provider": "telegram",
                "destination_path": str(self.destination),
                "tdl_access_target": "-100123",
                "publish_public_links": True,
                "public_base_url": "https://worker.example.test",
                "files": [
                    {"channel_message_id": 11, "name": "ok.bin", "relative_path": "album/ok.bin", "file_size": 14},
                    {"channel_message_id": 12, "name": "conflict.bin", "relative_path": "album/conflict.bin", "file_size": 8},
                ],
            },
        }

        result = worker._storage_download(command)
        items = {item["name"]: item for item in result["items"]}

        self.assertEqual((result["succeeded"], result["failed"]), (1, 1))
        self.assertEqual(items["ok.bin"]["download_status"], "succeeded")
        self.assertEqual(items["ok.bin"]["link_status"], "succeeded")
        self.assertTrue(items["ok.bin"]["public_url"].startswith("https://worker.example.test/public/download/"))
        self.assertEqual(items["conflict.bin"]["error_code"], "STORAGE_DOWNLOAD_CONFLICT")
        self.assertEqual(items["conflict.bin"]["link_status"], "not_created")
        self.assertEqual(conflict.read_bytes(), b"existing")
        self.assertEqual((self.destination / "album" / "ok.bin").read_bytes(), b"telegram bytes")
        self.assertEqual(client.exports[0][0:2], ("-100123", 11))
        self.assertTrue(client.exports[0][3]["with_content"])
        self.assertFalse(list(self.destination.glob(".storage-download-*")))

    def test_rclone_download_preserves_folder_and_continues_after_conflict(self):
        conflict = self.destination / "archive" / "conflict.bin"
        conflict.parent.mkdir()
        conflict.write_bytes(b"keep")
        FakeRcloneRunner.files = [
            {"remote_path": "drive:backup/archive/conflict.bin", "relative_path": "archive/conflict.bin", "name": "conflict.bin", "size": 4},
            {"remote_path": "drive:backup/archive/nested/ok.bin", "relative_path": "archive/nested/ok.bin", "name": "ok.bin", "size": 5},
        ]
        worker = StorageDownloadHarness(self.workspace)
        command = {
            "job_id": "rclone-job",
            "payload": {
                "provider": "rclone",
                "destination_path": str(self.destination),
                "rclone_destination": "drive:backup",
                "rclone_sources": [{"path": "archive", "is_dir": True}],
                "publish_public_links": True,
                "public_base_url": "https://worker.example.test",
            },
        }

        with patch("tme3bot.worker.executor_storage.RcloneRunner", FakeRcloneRunner):
            result = worker._storage_download(command)
        items = {item["name"]: item for item in result["items"]}

        self.assertEqual((result["succeeded"], result["failed"]), (1, 1))
        self.assertEqual(items["conflict.bin"]["error_code"], "STORAGE_DOWNLOAD_CONFLICT")
        self.assertEqual((self.destination / "archive" / "conflict.bin").read_bytes(), b"keep")
        self.assertEqual(
            (self.destination / "archive" / "nested" / "ok.bin").read_bytes(),
            b"from:drive:backup/archive/nested/ok.bin",
        )
        self.assertEqual(items["ok.bin"]["link_status"], "succeeded")
        links = worker.links.active_links()
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["relative_path"], "destination/archive/nested/ok.bin")
        self.assertEqual(links[0]["provider"], "rclone")
        self.assertFalse(worker._rclone_runners)

    def test_rclone_publication_failure_keeps_downloaded_file(self):
        FakeRcloneRunner.files = [{
            "remote_path": "drive:backup/archive/ok.bin",
            "relative_path": "archive/ok.bin",
            "name": "ok.bin",
            "size": 5,
        }]
        worker = StorageDownloadHarness(self.workspace)
        worker.fail_links = True
        command = {
            "job_id": "rclone-link-failure-job",
            "payload": {
                "provider": "rclone",
                "destination_path": str(self.destination),
                "rclone_destination": "drive:backup",
                "rclone_sources": [{"path": "archive", "is_dir": True}],
                "publish_public_links": True,
                "public_base_url": "https://worker.example.test",
            },
        }

        with patch("tme3bot.worker.executor_storage.RcloneRunner", FakeRcloneRunner):
            result = worker._storage_download(command)

        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["public_links_failed"], 1)
        self.assertEqual(result["items"][0]["download_status"], "succeeded")
        self.assertEqual(result["items"][0]["link_status"], "failed")
        self.assertEqual(
            (self.destination / "archive" / "ok.bin").read_bytes(),
            b"from:drive:backup/archive/ok.bin",
        )

    def test_rclone_cancel_keeps_completed_file_and_link_and_discards_partial_file(self):
        worker_ref = {}
        FakeRcloneRunner.files = [
            {"remote_path": "drive:backup/archive/one.bin", "relative_path": "archive/one.bin", "name": "one.bin", "size": 3},
            {"remote_path": "drive:backup/archive/two.bin", "relative_path": "archive/two.bin", "name": "two.bin", "size": 3},
            {"remote_path": "drive:backup/archive/three.bin", "relative_path": "archive/three.bin", "name": "three.bin", "size": 5},
        ]

        class CancelOnSecondRcloneFile(FakeRcloneRunner):
            def download_file(self, remote_path, destination_path, config_path, *, config_root):
                Path(destination_path).write_bytes(b"partial" if remote_path.endswith("two.bin") else b"done")
                if remote_path.endswith("two.bin"):
                    worker_ref["worker"]._cancel_requested.add("rclone-cancel")

        worker = StorageDownloadHarness(self.workspace)
        worker_ref["worker"] = worker
        command = {
            "job_id": "rclone-cancel",
            "payload": {
                "provider": "rclone",
                "destination_path": str(self.destination),
                "rclone_destination": "drive:backup",
                "rclone_sources": [{"path": "archive", "is_dir": True}],
                "publish_public_links": True,
                "public_base_url": "https://worker.example.test",
            },
        }

        with patch("tme3bot.worker.executor_storage.RcloneRunner", CancelOnSecondRcloneFile):
            result = worker._storage_download(command)

        self.assertTrue(result["cancelled"])
        self.assertEqual(
            [item["download_status"] for item in result["items"]],
            ["succeeded", "cancelled", "cancelled"],
        )
        self.assertEqual(result["items"][0]["link_status"], "succeeded")
        self.assertTrue((self.destination / "archive" / "one.bin").is_file())
        self.assertFalse((self.destination / "archive" / "two.bin").exists())
        self.assertFalse((self.destination / "archive" / "three.bin").exists())
        self.assertEqual(len(worker.links.active_links()), 1)
        self.assertFalse(list(self.destination.glob(".storage-download-*")))

    def test_cancel_discards_partial_file_and_reports_current_and_remaining_items(self):
        worker_ref = {}
        client = FakeTdlClient(cancel=lambda: worker_ref["worker"]._cancel_requested.add("cancel-job"))
        worker = StorageDownloadHarness(self.workspace, client)
        worker_ref["worker"] = worker
        command = {
            "job_id": "cancel-job",
            "profile": "default",
            "payload": {
                "provider": "telegram",
                "destination_path": str(self.destination),
                "tdl_access_target": "-100123",
                "files": [
                    {"channel_message_id": 21, "name": "one.bin", "relative_path": "one.bin"},
                    {"channel_message_id": 22, "name": "two.bin", "relative_path": "two.bin"},
                ],
            },
        }

        result = worker._storage_download(command)

        self.assertTrue(result["cancelled"])
        self.assertEqual(result["cancelled_items"], 2)
        self.assertEqual([item["download_status"] for item in result["items"]], ["cancelled", "cancelled"])
        self.assertFalse((self.destination / "one.bin").exists())
        self.assertFalse((self.destination / "two.bin").exists())
        self.assertFalse(list(self.destination.glob(".storage-download-*")))

    def test_cancel_keeps_completed_file_and_link_and_cleans_current_staging(self):
        worker_ref = {}

        class CancelOnSecondExport(FakeTdlClient):
            def export_messages(self, chat, start_id, output_path, **kwargs):
                exported = super().export_messages(chat, start_id, output_path, **kwargs)
                if start_id == 42:
                    worker_ref["worker"]._cancel_requested.add("cancel-after-success")
                return exported

        client = CancelOnSecondExport()
        worker = StorageDownloadHarness(self.workspace, client)
        worker_ref["worker"] = worker
        command = {
            "job_id": "cancel-after-success",
            "profile": "default",
            "payload": {
                "provider": "telegram",
                "destination_path": str(self.destination),
                "tdl_access_target": "-100123",
                "publish_public_links": True,
                "public_base_url": "https://worker.example.test",
                "files": [
                    {"channel_message_id": 41, "name": "one.bin", "relative_path": "one.bin"},
                    {"channel_message_id": 42, "name": "two.bin", "relative_path": "two.bin"},
                    {"channel_message_id": 43, "name": "three.bin", "relative_path": "three.bin"},
                ],
            },
        }

        result = worker._storage_download(command)

        self.assertTrue(result["cancelled"])
        self.assertEqual(
            [item["download_status"] for item in result["items"]],
            ["succeeded", "cancelled", "cancelled"],
        )
        self.assertEqual(result["items"][0]["link_status"], "succeeded")
        self.assertEqual(len(worker.links.active_links()), 1)
        self.assertTrue((self.destination / "one.bin").is_file())
        self.assertFalse((self.destination / "two.bin").exists())
        self.assertFalse(list(self.destination.glob(".storage-download-*")))

    def test_publication_failure_keeps_completed_download_and_separates_status(self):
        worker = StorageDownloadHarness(self.workspace, FakeTdlClient())
        worker.fail_links = True
        command = {
            "job_id": "link-failure-job",
            "profile": "default",
            "payload": {
                "provider": "telegram",
                "destination_path": str(self.destination),
                "tdl_access_target": "-100123",
                "publish_public_links": True,
                "public_base_url": "https://worker.example.test",
                "files": [{"channel_message_id": 31, "name": "saved.bin", "relative_path": "saved.bin"}],
            },
        }

        result = worker._storage_download(command)

        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["public_links_failed"], 1)
        self.assertEqual(result["items"][0]["download_status"], "succeeded")
        self.assertEqual(result["items"][0]["link_status"], "failed")
        self.assertEqual((self.destination / "saved.bin").read_bytes(), b"telegram bytes")

    def test_worker_failure_keeps_runtime_reason_codes_for_readiness_invalidation(self):
        worker = StorageDownloadHarness(self.workspace)

        WorkerJobExecutor._failed(
            worker,
            {
                "job_id": "rclone-access-job",
                "kind": "storage_download",
                "payload": {"provider": "rclone"},
            },
            RcloneError("internal command details", code="RCLONE_ACCESS_FAILED"),
        )

        error = worker.publisher.events[-1][3]["error"]
        self.assertEqual(error["code"], "RCLONE_ACCESS_FAILED")
        self.assertNotIn("internal command details", error["message"])


if __name__ == "__main__":
    unittest.main()
