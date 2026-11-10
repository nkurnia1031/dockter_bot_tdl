from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tme3bot.worker.executor import WorkerJobExecutor
from tme3bot.worker.quick_export import quick_stage_root, write_quick_manifest
from tme3bot.worker.telegram_upload_verification import TELEGRAM_UPLOAD_VERIFICATION_METHOD


class _RcloneRunner:
    def __init__(self, **_kwargs):
        pass

    def verify_files(self, files, *_args, **_kwargs):
        return {"found": len(files), "missing": [], "errors": []}


class QuickModeTelegramVerificationTests(unittest.TestCase):
    def _executor(self, workspace: Path) -> WorkerJobExecutor:
        executor = WorkerJobExecutor.__new__(WorkerJobExecutor)
        executor.config = SimpleNamespace(
            utility_workspace_root=str(workspace),
            database_root=str(workspace / "database"),
            rclone_config_path=str(workspace / "rclone.conf"),
            profile_root=str(workspace),
            job_stall_timeout_seconds=30,
        )
        executor._lock = threading.RLock()
        executor._quick_delete_active = set()
        executor._quick_stage_jobs = {}
        executor._quick_active = set()
        executor._quick_verify_active = set()
        executor._job_log = SimpleNamespace(secrets=[])
        executor._command_callback = lambda **_kwargs: None
        executor._write_quick_log_line = lambda *_args, **_kwargs: None
        return executor

    def _stage(self, workspace: Path, stage_id: str, *, verified: bool) -> Path:
        stage = quick_stage_root(workspace, stage_id)
        stage.mkdir(parents=True)
        archive = stage / "Episode.7z"
        thumbnail = stage / "Episode.png"
        archive.write_bytes(b"archive")
        thumbnail.write_bytes(b"png")
        upload_result = {
            "succeeded": 2,
            "uploaded_items": [
                {"original_name": archive.name, "channel_message_id": 101},
                {"original_name": thumbnail.name, "channel_message_id": 102},
            ],
        }
        if verified:
            upload_result["telegram_verification"] = TELEGRAM_UPLOAD_VERIFICATION_METHOD
        write_quick_manifest(stage, {
            "phase": "cleanup",
            "folder_name": "Episode",
            "caption": "Episode\n#ModeCepat #2026",
            "profile": "default",
            "rclone_destination": "drive:backup",
            "upload_result": upload_result,
        })
        return stage

    def test_cleanup_uses_per_file_upload_evidence_without_second_telegram_export(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            stage = self._stage(workspace, "quick-verified", verified=True)
            executor = self._executor(workspace)

            with (
                patch("tme3bot.worker.executor_quickmode.RcloneRunner", _RcloneRunner),
                patch("tme3bot.worker.executor_quickmode.cleanup_quick_tdl_sessions"),
            ):
                result = executor.quickmode_verify("quick-verified")

            self.assertEqual(result["status"], "verified")
            self.assertEqual(result["channel_found"], 2)
            self.assertFalse(stage.exists())

    def test_legacy_stage_without_upload_verification_evidence_is_retained(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            stage = self._stage(workspace, "quick-legacy", verified=False)
            executor = self._executor(workspace)

            with patch("tme3bot.worker.executor_quickmode.RcloneRunner", _RcloneRunner):
                result = executor.quickmode_verify("quick-legacy")

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["channel_found"], 0)
            self.assertTrue(stage.exists())


if __name__ == "__main__":
    unittest.main()
