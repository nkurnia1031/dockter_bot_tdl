from __future__ import annotations

import tempfile
import threading
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tme3bot.tdl import TDLTransferStalledError
from tme3bot.worker.executor import WorkerJobExecutor


class _BackupUploadClient:
    def __init__(self, *, visible_after_exports: int = 0):
        self.visible_after_exports = visible_after_exports
        self.messages: list[dict] = []
        self.exports: list[tuple] = []
        self.uploads: list[tuple] = []
        self.output_callback = None
        self.command_callback = None
        self.outcomes = []

    def upload(self, path, chat_ref, caption, *, status_callback=None):
        self.uploads.append((Path(path), chat_ref, caption))
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                if getattr(outcome, "telegram_message", False):
                    self.messages.append({
                        "id": len(self.messages) + 1,
                        "date": time.time(),
                        "file_name": Path(path).name,
                        "caption": caption,
                    })
                raise outcome
        self.messages.append({
            "id": len(self.messages) + 1,
            "date": time.time(),
            "file_name": Path(path).name,
            "caption": caption,
        })
        return SimpleNamespace(message_id=None)

    def export_messages_by_time(self, chat_ref, start, end, _path, *, with_content):
        self.exports.append((chat_ref, start, end, with_content))
        messages = self.messages if len(self.exports) >= self.visible_after_exports else []
        return SimpleNamespace(messages=[
            item for item in messages if start <= item["date"] <= end
        ])


class BackupUploadVerificationTests(unittest.TestCase):
    def _run_backup(self, root: Path, client: _BackupUploadClient):
        part = root / "backup.7z.001"
        part.write_bytes(b"backup-part")
        clients = client if isinstance(client, dict) else {"default": client}
        runtimes = {
            profile: SimpleNamespace(
                export_tdl_client=profile_client,
                export_operation_lock=threading.RLock(),
                download_operation_lock=threading.RLock(),
            )
            for profile, profile_client in clients.items()
        }
        executor = WorkerJobExecutor.__new__(WorkerJobExecutor)
        executor.config = SimpleNamespace(
            backup_node_name="local",
            backup_volume_size="1g",
        )
        executor.profile_manager = SimpleNamespace(
            list_profiles=lambda: list(runtimes),
            runtime=lambda profile: runtimes[profile],
        )
        executor.publisher = SimpleNamespace(emit=lambda *_args, **_kwargs: None)
        executor._lock = threading.RLock()
        executor._backup_services = {}
        executor._job_log = threading.local()
        executor._job_log.secrets = []
        executor._command_callback = lambda **_kwargs: None
        executor._capture_tdl_output = lambda *_args, **_kwargs: nullcontext()
        executor._capture_tdl_progress = lambda *_args, **_kwargs: nullcontext()
        executor._append_job_log = lambda *_args, **_kwargs: None
        archive = SimpleNamespace(parts=[part], created_at="2026-11-10T00:00:00+00:00")
        fake_backup_service = SimpleNamespace(create_archive=lambda *_args, **_kwargs: archive)
        command = {
            "job_id": "backup-verify-1",
            "payload": {
                "backup_run_id": "run-1",
                "node_name": "local",
                "channel_ref": "-1001",
                "channel_id": 1001,
                "password": "unused-test-password",
            },
        }
        with patch("tme3bot.worker.executor_backup.BackupService", return_value=fake_backup_service):
            result = executor._backup(command)
        return result, part

    def test_backup_part_is_registered_only_after_exact_time_export_match(self):
        with tempfile.TemporaryDirectory() as raw:
            client = _BackupUploadClient()
            result, part = self._run_backup(Path(raw), client)

            self.assertEqual(result["parts"], 1)
            self.assertEqual(len(client.uploads), 1)
            self.assertEqual(len(client.exports), 1)
            self.assertFalse(part.exists())

    def test_unverified_backup_part_is_not_registered_or_deleted(self):
        with tempfile.TemporaryDirectory() as raw:
            client = _BackupUploadClient(visible_after_exports=99)

            with self.assertRaisesRegex(RuntimeError, "belum ditemukan"):
                self._run_backup(Path(raw), client)

            self.assertEqual(len(client.uploads), 1)
            self.assertEqual(len(client.exports), 2)
            self.assertTrue((Path(raw) / "backup.7z.001").exists())

    def test_backup_tries_next_profile_after_no_byte_progress_timeout(self):
        with tempfile.TemporaryDirectory() as raw:
            default = _BackupUploadClient()
            archive = _BackupUploadClient()
            archive.outcomes.append(TDLTransferStalledError([], -15, "", "", 60, 0))

            result, part = self._run_backup(
                Path(raw), {"default": default, "archive": archive}
            )

            self.assertEqual(result["parts"], 1)
            self.assertEqual(len(archive.uploads), 1)
            self.assertEqual(len(default.uploads), 1)
            self.assertFalse(part.exists())

    def test_backup_does_not_reverify_partial_attempt_after_all_profiles_stall(self):
        with tempfile.TemporaryDirectory() as raw:
            archive = _BackupUploadClient()
            default = _BackupUploadClient()
            archive.outcomes.append(
                TDLTransferStalledError([], -15, "", "", 60, 128)
            )
            default.outcomes.append(
                TDLTransferStalledError([], -15, "", "", 60, 0)
            )

            with self.assertRaisesRegex(RuntimeError, "dicoba pada semua profil"):
                self._run_backup(Path(raw), {"default": default, "archive": archive})

            self.assertEqual(len(archive.uploads), 1)
            self.assertEqual(len(default.uploads), 1)
            self.assertEqual(len(archive.exports), 1)
            self.assertEqual(len(default.exports), 0)
            self.assertTrue((Path(raw) / "backup.7z.001").exists())


if __name__ == "__main__":
    unittest.main()
