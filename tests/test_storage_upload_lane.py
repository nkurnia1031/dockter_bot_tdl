import hashlib
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from tme3bot.worker.executor_storage import StorageExecutorMixin


class _FakeTdlClient:
    def __init__(self, *, denied=False, error=None, message_id=10):
        self.denied = denied
        self.error = error
        self.message_id = message_id
        self.uploads = []

    def upload(self, path, target, caption, **_kwargs):
        self.uploads.append((Path(path), target, caption))
        if self.denied:
            raise RuntimeError("CHAT_WRITE_FORBIDDEN")
        if self.error:
            raise RuntimeError(self.error)
        return SimpleNamespace(message_id=self.message_id)


class _StorageUploader(StorageExecutorMixin):
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._lock = threading.RLock()
        self._cancel_requested = set()
        self.events = []
        self.logs = []
        self.config = SimpleNamespace(
            utility_workspace_root=workspace,
            profile_root=workspace,
        )
        self.publisher = SimpleNamespace(emit=lambda *args, **kwargs: self.events.append((args, kwargs)))
        self.runtimes = {
            "default": self._runtime("default", denied=True, message_id=10),
            "archive": self._runtime("archive", denied=False, message_id=20),
        }
        self.profile_manager = SimpleNamespace(
            list_profiles=lambda: list(self.runtimes),
            runtime=lambda profile: self.runtimes[profile],
        )
        self.session_fingerprints = {"default": "a" * 64, "archive": "b" * 64}

    @staticmethod
    def _runtime(name: str, *, denied: bool, message_id: int):
        return SimpleNamespace(
            config=SimpleNamespace(
                storage_channel_ref="-100123",
                storage_channel_id=1000 + message_id,
            ),
            export_tdl_client=_FakeTdlClient(message_id=message_id),
            upload_tdl_client=_FakeTdlClient(denied=denied, message_id=message_id),
            export_operation_lock=threading.RLock(),
            upload_operation_lock=threading.RLock(),
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

    def _append_job_log(self, message):
        self.logs.append(message)

    @staticmethod
    def _digest(path: Path):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest, path.stat().st_size

    @contextmanager
    def _capture_tdl_output(self, _client):
        yield

    @contextmanager
    def _capture_tdl_progress(self, _client, _callback):
        yield

    def _command_callback(self):
        return None

    @staticmethod
    def _command(workspace: Path, *, senders=None):
        return {
            "job_id": "job-1",
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
                "_tdl_sender_profiles": senders or ["default", "archive"],
                "_tdl_sender_session_fingerprints": {"default": "a" * 64, "archive": "b" * 64},
            },
        }


class StorageUploadLaneTests(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
        workspace = root / "folder"
        workspace.mkdir()
        (workspace / "example.txt").write_text("file body", encoding="utf-8")
        return workspace

    def test_storage_upload_uses_upload_lanes_for_primary_and_permission_fallback(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            workspace = self._workspace(root)
            executor = _StorageUploader(workspace)

            result = executor._storage_upload(executor._command(workspace))

            self.assertEqual(result["succeeded"], 1)
            self.assertEqual(result["failed"], [])
            self.assertEqual(len(executor.runtimes["default"].upload_tdl_client.uploads), 1)
            self.assertEqual(len(executor.runtimes["archive"].upload_tdl_client.uploads), 1)
            self.assertFalse(any(
                runtime.export_tdl_client.uploads for runtime in executor.runtimes.values()
            ))
            self.assertEqual(result["uploaded_items"][0]["channel_id"], 1020)
            denied_events = [
                kwargs["result"]
                for args, kwargs in executor.events
                if len(args) > 2 and args[2] == "tdl_access.profile_denied"
            ]
            self.assertEqual(denied_events, [{"profile": "default", "error_code": "CHAT_WRITE_FORBIDDEN"}])

    def test_storage_network_failure_does_not_invalidate_access_proof(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            workspace = self._workspace(root)
            executor = _StorageUploader(workspace)
            client = executor.runtimes["default"].upload_tdl_client
            client.denied = False
            client.error = "connection reset"

            result = executor._storage_upload(
                executor._command(workspace, senders=["default"])
            )

            self.assertEqual(len(result["failed"]), 1)
            self.assertFalse(any(
                len(args) > 2 and args[2] == "tdl_access.profile_denied"
                for args, _kwargs in executor.events
            ))

    def test_storage_skips_a_lane_whose_session_changed_after_dispatch(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            workspace = self._workspace(root)
            executor = _StorageUploader(workspace)
            executor.session_fingerprints["default"] = "c" * 64

            result = executor._storage_upload(executor._command(workspace))

            self.assertEqual(result["succeeded"], 1)
            self.assertFalse(executor.runtimes["default"].upload_tdl_client.uploads)
            self.assertEqual(len(executor.runtimes["archive"].upload_tdl_client.uploads), 1)

    def test_storage_session_denial_revokes_lane_and_uses_another_verified_profile(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            workspace = self._workspace(root)
            executor = _StorageUploader(workspace)
            client = executor.runtimes["default"].upload_tdl_client
            client.denied = False
            client.error = "AUTH_KEY_UNREGISTERED"

            result = executor._storage_upload(executor._command(workspace))

            self.assertEqual(result["succeeded"], 1)
            denial_events = [
                kwargs["result"]
                for args, kwargs in executor.events
                if len(args) > 2 and args[2] == "tdl_access.profile_denied"
            ]
            self.assertEqual(
                denial_events,
                [{"profile": "default", "error_code": "TDL_SESSION_UNAUTHORIZED"}],
            )
            self.assertEqual(len(executor.runtimes["archive"].upload_tdl_client.uploads), 1)

    def test_storage_upload_does_not_wait_for_the_export_lane_lock(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            workspace = self._workspace(root)
            executor = _StorageUploader(workspace)
            runtime = executor.runtimes["default"]
            runtime.upload_tdl_client.denied = False
            finished = threading.Event()
            result = []
            runtime.export_operation_lock.acquire()
            try:
                thread = threading.Thread(
                    target=lambda: (result.append(
                        executor._storage_upload(
                            executor._command(workspace, senders=["default"])
                        )
                    ), finished.set()),
                    daemon=True,
                )
                thread.start()
                completed_while_export_locked = finished.wait(2)
            finally:
                runtime.export_operation_lock.release()
            thread.join(timeout=2)

            self.assertTrue(completed_while_export_locked)
            self.assertEqual(result[0]["succeeded"], 1)
            self.assertEqual(len(runtime.upload_tdl_client.uploads), 1)
            self.assertFalse(runtime.export_tdl_client.uploads)

    def test_storage_upload_rejects_an_unready_upload_lane_without_export_fallback(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            workspace = self._workspace(root)
            executor = _StorageUploader(workspace)
            executor.available_storage_profiles = lambda: ["archive"]

            with self.assertRaisesRegex(ValueError, "STORAGE_PROFILE_UNAVAILABLE"):
                executor._storage_upload(executor._command(workspace))

            self.assertFalse(any(
                runtime.upload_tdl_client.uploads or runtime.export_tdl_client.uploads
                for runtime in executor.runtimes.values()
            ))


if __name__ == "__main__":
    unittest.main()
