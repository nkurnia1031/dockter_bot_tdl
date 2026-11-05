import json
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from tme3bot.tdl import ExportResult, UploadResult
from tme3bot.worker.profile_readiness import (
    ProfileReadinessCanary,
    ProfileReadinessCanaryOperations,
)


@dataclass
class _Message:
    speed_bps: int
    speed: str


class _ExportClient:
    def __init__(
        self,
        uploads,
        counter,
        *,
        empty_targets=(),
        failed_targets=(),
    ):
        self.uploads = uploads
        self.counter = counter
        self.empty_targets = set(empty_targets)
        self.failed_targets = set(failed_targets)
        self.export_calls = []
        self.raw_output_callback = None

    def _emit_raw(self):
        if not callable(self.raw_output_callback):
            return
        self.raw_output_callback({
            "type": "command",
            "stream": "system",
            "text": "tdl chat export --token=token-secret",
        })
        self.raw_output_callback({
            "type": "output",
            "stream": "stdout",
            "text": (
                "Authorization: Bearer bearer-secret /tmp/profile-canary "
                "chat=-1001234567890\r\n"
                "Cookie: sid=cookie-secret\r\n"
                "passphrase=phrase-secret session contents=session-secret\r\n"
                '{"session":"json-session-secret","cookie":"json-cookie-secret"}\r\n'
                "https://operator:proxy-secret@proxy.example.test\r\n"
                "\x1b[32mready\x1b[0m\r"
            ),
        })
        self.raw_output_callback({
            "type": "exit",
            "stream": "system",
            "text": "process exited with code 0",
            "exit_code": 0,
        })

    def export_messages(
        self, chat_ref, start_id, path, *, with_content=False,
        last_count=None, end_id=None,
    ):
        self.export_calls.append({
            "chat_ref": chat_ref,
            "start_id": start_id,
            "last_count": last_count,
            "with_content": with_content,
            "end_id": end_id,
        })
        self._emit_raw()
        if chat_ref in self.failed_targets:
            raise RuntimeError(f"export access failed for {chat_ref}")
        path = Path(path)
        if last_count == 1:
            messages = (
                [] if chat_ref in self.empty_targets else
                [{"id": 99, "media": {"name": "backup.7z"}}]
            )
        else:
            message_id = int(end_id or start_id)
            marker = next((item["marker"] for item in self.uploads if item["id"] == message_id), "")
            messages = [{"id": message_id, "caption": marker}]
        path.write_text(json.dumps({"messages": messages}), encoding="utf-8")
        return ExportResult(
            export_path=path,
            messages=messages,
            exported_count=len(messages),
            max_message_id=max((item["id"] for item in messages), default=0),
            has_media=any(item.get("media") for item in messages),
        )

    def upload(self, path, chat_ref, caption):
        self.counter[0] += 1
        message_id = self.counter[0]
        self.uploads.append({"id": message_id, "chat": chat_ref, "marker": caption})
        return UploadResult(message_id=message_id, output="")


class _DownloadClient:
    def __init__(
        self,
        *,
        emit_progress=True,
        progress_delay_seconds=0,
        before_command_start_delay_seconds=0,
    ):
        self.progress_callback = None
        self.interrupted = threading.Event()
        self.started = threading.Event()
        self.command_started_at = None
        self.interrupted_at = None
        self.emit_progress = emit_progress
        self.progress_delay_seconds = progress_delay_seconds
        self.before_command_start_delay_seconds = before_command_start_delay_seconds

    def download(self, _export_path, download_dir, *, process_started_callback=None):
        Path(download_dir).mkdir(parents=True, exist_ok=True)
        time.sleep(self.before_command_start_delay_seconds)
        self.command_started_at = time.monotonic()
        process_started_callback()
        self.started.set()
        if self.emit_progress:
            if not self.interrupted.wait(timeout=self.progress_delay_seconds):
                self.progress_callback(_Message(speed_bps=4096, speed="4KiB/s"))
        self.interrupted.wait(timeout=1)

    def interrupt_current(self):
        self.interrupted_at = time.monotonic()
        self.interrupted.set()
        return True


class ProfileReadinessCanaryTests(unittest.TestCase):
    def _run(
        self,
        *,
        empty_targets=(),
        failed_targets=(),
        checks=None,
        download_progress_timeout_seconds=0.1,
        progress_delay_seconds=0,
    ):
        uploads = []
        counter = [700]
        export = _ExportClient(
            uploads,
            counter,
            empty_targets=empty_targets,
            failed_targets=failed_targets,
        )
        download = _DownloadClient(progress_delay_seconds=progress_delay_seconds)
        runtime = SimpleNamespace(
            export_operation_lock=threading.RLock(),
            download_operation_lock=threading.RLock(),
            upload_operation_lock=threading.RLock(),
            export_tdl_client=export,
            download_tdl_client=download,
            upload_tdl_client=_ExportClient(
                uploads,
                counter,
                empty_targets=empty_targets,
                failed_targets=failed_targets,
            ),
        )
        manager = SimpleNamespace(runtime=lambda _profile: runtime)
        phases = []
        diagnose_calls = []
        with tempfile.TemporaryDirectory() as directory:
            canary = ProfileReadinessCanary(
                manager,
                lambda profile: diagnose_calls.append(profile) or {
                    "ready": False,
                    "reason_codes": ["PROFILE_SESSION_IDENTITY_MISMATCH"],
                    "fingerprint": "a" * 64,
                },
                Path(directory),
                upload_session_fingerprint=lambda _profile: "b" * 64,
                download_progress_timeout_seconds=download_progress_timeout_seconds,
            )
            result = canary.run(
                "default",
                "storage-chat",
                "tts-chat",
                lambda phase, _checks, _messages: phases.append(phase),
                checks=checks,
            )
        self.diagnose_calls = diagnose_calls
        return result, phases, runtime, download

    def test_checks_each_lane_with_export_and_never_sends_marker_uploads(self):
        result, phases, _runtime, download = self._run()

        self.assertTrue(result["checks"]["export"]["ready"])
        self.assertTrue(result["checks"]["download"]["ready"])
        self.assertTrue(result["checks"]["upload"]["ready"])
        self.assertTrue(result["checks"]["storage"]["ready"])
        self.assertTrue(result["checks"]["tts"]["ready"])
        self.assertEqual(result["session_fingerprint"], "")
        self.assertEqual(result["upload_session_fingerprint"], "")
        self.assertEqual(self.diagnose_calls, [])
        self.assertEqual(result["messages"], [])
        self.assertEqual(_runtime.export_tdl_client.uploads, [])
        self.assertEqual(_runtime.upload_tdl_client.uploads, [])
        self.assertEqual(
            [call["chat_ref"] for call in _runtime.upload_tdl_client.export_calls],
            ["storage-chat"],
        )
        self.assertEqual(
            [call["chat_ref"] for call in _runtime.export_tdl_client.export_calls],
            ["storage-chat", "tts-chat"],
        )
        self.assertEqual(
            [call["last_count"] for call in _runtime.export_tdl_client.export_calls],
            [1, 1],
        )
        self.assertEqual(
            _runtime.upload_tdl_client.export_calls[0]["last_count"], 1
        )
        self.assertIn("download_canary", phases)
        self.assertIn("storage_access_canary", phases)
        self.assertIn("tts_access_canary", phases)
        self.assertTrue(download.interrupted.wait(timeout=0.2))

    def test_empty_channel_export_proves_storage_and_tts_access(self):
        result, _phases, runtime, _download = self._run(
            empty_targets={"storage-chat", "tts-chat"},
            checks=["storage", "tts"],
        )

        self.assertTrue(result["checks"]["upload"]["ready"])
        self.assertTrue(result["checks"]["storage"]["ready"])
        self.assertTrue(result["checks"]["tts"]["ready"])
        self.assertFalse(result["checks"]["export"]["ready"])
        self.assertEqual(runtime.upload_tdl_client.export_calls[0]["chat_ref"], "storage-chat")
        self.assertEqual(runtime.export_tdl_client.export_calls[0]["chat_ref"], "tts-chat")
        self.assertEqual(result["messages"], [])

    def test_tts_access_failure_does_not_clear_storage_readiness(self):
        result, _phases, _runtime, _download = self._run(
            failed_targets={"tts-chat"},
            checks=["storage", "tts"],
        )

        self.assertTrue(result["checks"]["upload"]["ready"])
        self.assertTrue(result["checks"]["storage"]["ready"])
        self.assertFalse(result["checks"]["tts"]["ready"])
        self.assertEqual(result["checks"]["tts"]["reason_code"], "PROFILE_CANARY_TTS_FAILED")

    def test_selected_tts_canary_does_not_run_storage_or_download_canaries(self):
        result, phases, _runtime, download = self._run(checks=["tts"])

        self.assertFalse(result["checks"]["export"]["ready"])
        self.assertTrue(result["checks"]["tts"]["ready"])
        self.assertFalse(result["checks"]["upload"]["ready"])
        self.assertFalse(result["checks"]["storage"]["ready"])
        self.assertEqual(result["messages"], [])
        self.assertEqual(
            [call["chat_ref"] for call in _runtime.export_tdl_client.export_calls],
            ["tts-chat"],
        )
        self.assertEqual(_runtime.export_tdl_client.export_calls[0]["last_count"], 1)
        self.assertNotIn("download_canary", phases)
        self.assertNotIn("storage_access_canary", phases)
        self.assertFalse(download.interrupted.is_set())

    def test_selected_storage_canary_does_not_run_tts_or_download_canaries(self):
        result, phases, _runtime, download = self._run(checks=["storage"])

        self.assertFalse(result["checks"]["export"]["ready"])
        self.assertTrue(result["checks"]["upload"]["ready"])
        self.assertTrue(result["checks"]["storage"]["ready"])
        self.assertEqual(result["messages"], [])
        self.assertEqual(
            [call["chat_ref"] for call in _runtime.upload_tdl_client.export_calls],
            ["storage-chat"],
        )
        self.assertEqual(_runtime.upload_tdl_client.export_calls[0]["last_count"], 1)
        self.assertEqual(_runtime.export_tdl_client.export_calls, [])
        self.assertNotIn("download_canary", phases)
        self.assertNotIn("tts_access_canary", phases)
        self.assertFalse(download.interrupted.is_set())

    def test_download_lane_times_out_and_cancels_when_no_progress_appears(self):
        uploads = []
        counter = [700]
        runtime = SimpleNamespace(
            export_operation_lock=threading.RLock(),
            download_operation_lock=threading.RLock(),
            upload_operation_lock=threading.RLock(),
            export_tdl_client=_ExportClient(uploads, counter),
            download_tdl_client=_DownloadClient(
                emit_progress=False,
                before_command_start_delay_seconds=0.12,
            ),
            upload_tdl_client=_ExportClient(uploads, counter),
        )
        with tempfile.TemporaryDirectory() as directory:
            canary = ProfileReadinessCanary(
                SimpleNamespace(runtime=lambda _profile: runtime),
                lambda _profile: {"ready": True},
                Path(directory),
                download_progress_timeout_seconds=0.08,
            )
            started_at = time.monotonic()
            result = canary.run(
                "default", "storage-chat", "tts-chat", lambda *_args: None,
                checks=["download"],
            )

        self.assertLess(time.monotonic() - started_at, 0.8)
        self.assertTrue(runtime.download_tdl_client.started.is_set())
        self.assertTrue(runtime.download_tdl_client.interrupted.wait(timeout=0.2))
        self.assertGreaterEqual(
            runtime.download_tdl_client.interrupted_at
            - runtime.download_tdl_client.command_started_at,
            0.06,
        )
        self.assertFalse(result["checks"]["download"]["ready"])
        self.assertEqual(
            result["checks"]["download"]["reason_code"],
            "PROFILE_CANARY_DOWNLOAD_PROGRESS_TIMEOUT",
        )

    def test_download_lane_cancels_as_soon_as_progress_appears(self):
        started_at = time.monotonic()
        result, _phases, _runtime, download = self._run(
            checks=["download"],
            download_progress_timeout_seconds=2.0,
            progress_delay_seconds=0.02,
        )

        self.assertLess(time.monotonic() - started_at, 1.5)
        self.assertTrue(result["checks"]["download"]["ready"])
        self.assertTrue(download.interrupted.wait(timeout=0.2))

    def test_canary_operation_exposes_live_raw_tdl_logs_with_only_secrets_redacted(self):
        uploads = []
        counter = [700]
        runtime = SimpleNamespace(
            export_operation_lock=threading.RLock(),
            download_operation_lock=threading.RLock(),
            upload_operation_lock=threading.RLock(),
            export_tdl_client=_ExportClient(uploads, counter),
            download_tdl_client=_DownloadClient(),
            upload_tdl_client=_ExportClient(uploads, counter),
        )
        canary = ProfileReadinessCanary(
            SimpleNamespace(runtime=lambda _profile: runtime),
            lambda _profile: {"ready": True, "fingerprint": "a" * 64},
            Path(tempfile.gettempdir()),
            upload_session_fingerprint=lambda _profile: "b" * 64,
        )
        operations = ProfileReadinessCanaryOperations(canary)
        try:
            started = operations.start(
                "default", "123", "456", checks=["export"]
            )
            operation_id = started["id"]
            deadline = time.monotonic() + 3
            operation = started
            while time.monotonic() < deadline:
                operation = operations.get(operation_id)
                if operation and operation["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.01)

            self.assertEqual(operation["status"], "succeeded")
            logs = operation["logs"]
            self.assertEqual([event["type"] for event in logs], ["command", "output", "exit"])
            self.assertEqual(logs[0]["runtime"], "export")
            self.assertIn("[REDACTED]", logs[0]["text"])
            self.assertNotIn("token-secret", logs[0]["text"])
            self.assertIn("[REDACTED]", logs[1]["text"])
            self.assertNotIn("bearer-secret", logs[1]["text"])
            self.assertNotIn("cookie-secret", logs[1]["text"])
            self.assertNotIn("phrase-secret", logs[1]["text"])
            self.assertNotIn("session-secret", logs[1]["text"])
            self.assertNotIn("json-session-secret", logs[1]["text"])
            self.assertNotIn("json-cookie-secret", logs[1]["text"])
            self.assertNotIn("proxy-secret", logs[1]["text"])
            self.assertIn("/tmp/profile-canary", logs[1]["text"])
            self.assertIn("-1001234567890", logs[1]["text"])
            self.assertIn("\x1b[32mready\x1b[0m\r", logs[1]["text"])
            self.assertEqual(logs[-1]["exit_code"], 0)
        finally:
            operations.close()


if __name__ == "__main__":
    unittest.main()
