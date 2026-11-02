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
    def __init__(self, uploads, counter, *, fail_tts_verification=False):
        self.uploads = uploads
        self.counter = counter
        self.fail_tts_verification = fail_tts_verification
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
        self._emit_raw()
        path = Path(path)
        if last_count == 1:
            messages = [{"id": 99, "media": {"name": "backup.7z"}}]
        else:
            if self.fail_tts_verification and chat_ref == "tts-chat":
                raise RuntimeError("verification failed")
            message_id = int(end_id or start_id)
            marker = next((item["marker"] for item in self.uploads if item["id"] == message_id), "")
            messages = [{"id": message_id, "caption": marker}]
        path.write_text(json.dumps({"messages": messages}), encoding="utf-8")
        return ExportResult(
            export_path=path,
            messages=messages,
            exported_count=len(messages),
            max_message_id=max(item["id"] for item in messages),
            has_media=last_count == 1,
        )

    def upload(self, path, chat_ref, caption):
        self.counter[0] += 1
        message_id = self.counter[0]
        self.uploads.append({"id": message_id, "chat": chat_ref, "marker": caption})
        return UploadResult(message_id=message_id, output="")


class _DownloadClient:
    def __init__(self):
        self.progress_callback = None
        self.interrupted = threading.Event()

    def download(self, _export_path, download_dir):
        Path(download_dir).mkdir(parents=True, exist_ok=True)
        self.progress_callback(_Message(speed_bps=4096, speed="4KiB/s"))
        self.interrupted.wait(timeout=1)

    def interrupt_current(self):
        self.interrupted.set()
        return True


class ProfileReadinessCanaryTests(unittest.TestCase):
    def _run(self, *, fail_tts_verification=False, checks=None):
        uploads = []
        counter = [700]
        export = _ExportClient(uploads, counter, fail_tts_verification=fail_tts_verification)
        download = _DownloadClient()
        runtime = SimpleNamespace(
            export_operation_lock=threading.RLock(),
            download_operation_lock=threading.RLock(),
            upload_operation_lock=threading.RLock(),
            export_tdl_client=export,
            download_tdl_client=download,
            upload_tdl_client=_ExportClient(uploads, counter),
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

    def test_runs_export_download_upload_and_independent_channel_verifications(self):
        result, phases, _runtime, download = self._run()

        self.assertTrue(result["checks"]["export"]["ready"])
        self.assertTrue(result["checks"]["download"]["ready"])
        self.assertTrue(result["checks"]["upload"]["ready"])
        self.assertTrue(result["checks"]["storage"]["ready"])
        self.assertTrue(result["checks"]["tts"]["ready"])
        self.assertEqual(result["session_fingerprint"], "")
        self.assertEqual(result["upload_session_fingerprint"], "")
        self.assertEqual(self.diagnose_calls, [])
        self.assertEqual({item["target"] for item in result["messages"]}, {"storage", "tts"})
        self.assertIn("download_canary", phases)
        self.assertIn("verify_storage", phases)
        self.assertIn("verify_tts", phases)
        self.assertTrue(download.interrupted.wait(timeout=0.2))

    def test_tts_verification_failure_does_not_clear_storage_or_upload_readiness(self):
        result, _phases, _runtime, _download = self._run(fail_tts_verification=True)

        self.assertTrue(result["checks"]["upload"]["ready"])
        self.assertTrue(result["checks"]["storage"]["ready"])
        self.assertFalse(result["checks"]["tts"]["ready"])
        self.assertEqual(
            result["checks"]["tts"]["reason_code"],
            "PROFILE_CANARY_TTS_FAILED",
        )

    def test_selected_tts_canary_does_not_run_storage_or_download_canaries(self):
        result, phases, _runtime, download = self._run(checks=["tts"])

        self.assertTrue(result["checks"]["export"]["ready"])
        self.assertTrue(result["checks"]["tts"]["ready"])
        self.assertFalse(result["checks"]["upload"]["ready"])
        self.assertFalse(result["checks"]["storage"]["ready"])
        self.assertEqual([item["target"] for item in result["messages"]], ["tts"])
        self.assertNotIn("download_canary", phases)
        self.assertNotIn("upload_storage", phases)
        self.assertFalse(download.interrupted.is_set())

    def test_selected_storage_canary_does_not_run_tts_or_download_canaries(self):
        result, phases, _runtime, download = self._run(checks=["storage"])

        self.assertTrue(result["checks"]["export"]["ready"])
        self.assertTrue(result["checks"]["upload"]["ready"])
        self.assertTrue(result["checks"]["storage"]["ready"])
        self.assertEqual([item["target"] for item in result["messages"]], ["storage"])
        self.assertNotIn("download_canary", phases)
        self.assertNotIn("upload_tts", phases)
        self.assertFalse(download.interrupted.is_set())

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
