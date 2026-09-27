import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tme3bot.worker.executor_tts import TtsExecutorMixin


class _FakePipeline:
    def ready(self):
        return True

    def synthesize(self, job_id, text, root, **kwargs):
        del job_id, text, kwargs
        root.mkdir(parents=True, exist_ok=True)
        artifact_ref = "a" * 48
        (root / f"artifact-{artifact_ref}.mp3").write_bytes(b"audio")
        return {
            "character_count": 4,
            "part_count": 1,
            "artifacts": [{
                "artifact_ref": artifact_ref,
                "part_index": 1,
                "total_parts": 1,
                "byte_size": 5,
            }],
        }


class _FakeTdl:
    def __init__(self):
        self.uploads = []

    def upload(self, path, chat_ref, caption):
        self.uploads.append((Path(path), chat_ref, caption))


class _Executor(TtsExecutorMixin):
    def __init__(self, root):
        self.config = SimpleNamespace(
            tts_data_root=Path(root) / "tts",
            backup_node_name="local",
            backend_api_url="http://backend",
            backend_internal_token="internal",
        )
        self.runtime_settings = SimpleNamespace(tts_settings=lambda: {})
        self._pause_events = {}
        self._cancel_requested = set()
        self._job_log = threading.local()
        self._job_log.secrets = []
        self.logs = []
        self.events = []
        self.publisher = SimpleNamespace(emit=lambda *args, **kwargs: self.events.append((args, kwargs)))
        self.tdl = _FakeTdl()
        self.profile_manager = SimpleNamespace(
            runtime=lambda profile: SimpleNamespace(
                name=profile,
                export_tdl_client=self.tdl,
                export_operation_lock=threading.RLock(),
            )
        )

    def _append_job_log(self, line):
        self.logs.append(line)


class TtsExecutorTests(unittest.TestCase):
    def test_tts_uploads_each_part_with_active_profile_tdl_session(self):
        with tempfile.TemporaryDirectory() as directory:
            executor = _Executor(directory)
            responses = iter([
                {"registered_parts": 1, "chat_ref": "+1123456789"},
                {"items": [{
                    "id": "delivery-1",
                    "artifact_ref": "a" * 48,
                    "part_index": 1,
                    "total_parts": 1,
                }]},
                {"status": "delivered"},
                {"status": "delivered", "delivered_parts": 1, "total_parts": 1},
            ])

            def request(*args, **kwargs):
                del args, kwargs
                response = next(responses)
                if response.get("items"):
                    return response
                if response.get("registered_parts"):
                    return response
                return response

            command = {
                "job_id": "job-tts",
                "kind": "tts",
                "profile": "default",
                "worker": "local",
                "payload": {"title": "Bab 1", "text": "Isi"},
            }
            with patch.object(executor, "_tts_pipeline", return_value=_FakePipeline()), patch(
                "tme3bot.worker.executor_tts.request_json", side_effect=request
            ):
                result = executor._tts(command)

            self.assertEqual(result["delivered_parts"], 1)
            self.assertEqual(len(executor.tdl.uploads), 1)
            path, chat_ref, caption = executor.tdl.uploads[0]
            self.assertEqual(chat_ref, "+1123456789")
            self.assertEqual(caption, "Bab 1")
            self.assertTrue(path.name.startswith("artifact-"))


if __name__ == "__main__":
    unittest.main()
