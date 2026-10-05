import tempfile
import threading
import time
import urllib.error
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from tme3bot.worker.tts_pipeline import TTS_PART_CHARS, TtsCancelled, TtsError, TtsPipeline, split_text

try:
    from tme3bot.worker import tts_helper
except ModuleNotFoundError:
    tts_helper = None


def make_pipeline(**kwargs):
    return TtsPipeline(
        ["http://helper-1", "http://helper-2", "http://helper-3"],
        ["tor-1", "tor-2", "tor-3"],
        [9051, 9051, 9051],
        **kwargs,
    )


class TtsPipelineTests(unittest.TestCase):
    def test_diagnostics_reports_fixed_helper_slots_without_urls(self):
        states = {
            "http://helper-1": {"status": "ready", "bootstrap_percent": 100},
            "http://helper-2": {"status": "bootstrapping", "bootstrap_percent": 63},
            "http://helper-3": {"status": "helper_unreachable", "bootstrap_percent": None},
        }
        pipeline = make_pipeline(diagnostic_probe=lambda url: states[url])

        result = pipeline.diagnostics()

        self.assertFalse(result["helpers_ready"])
        self.assertEqual([helper["status"] for helper in result["helpers"]], [
            "ready", "bootstrapping", "helper_unreachable",
        ])
        self.assertEqual(result["helpers"][1]["bootstrap_percent"], 63)
        self.assertNotIn("url", str(result))

    def test_diagnostics_marks_missing_slots_and_requires_all_three_ready(self):
        pipeline = TtsPipeline(["http://private-helper"], "tor", [9051])
        with patch.object(pipeline, "_diagnostic_probe", return_value={"status": "ready", "bootstrap_percent": 100}):
            result = pipeline.diagnostics()
        self.assertFalse(result["helpers_ready"])
        self.assertEqual([helper["status"] for helper in result["helpers"]], [
            "ready", "helper_unreachable", "helper_unreachable",
        ])

    def test_diagnostics_preserves_tor_unreachable_and_requires_ready_quorum(self):
        pipeline = make_pipeline(diagnostic_probe=lambda _url: {
            "status": "tor_unreachable", "bootstrap_percent": None,
        })
        result = pipeline.diagnostics()
        self.assertFalse(result["helpers_ready"])
        self.assertEqual([helper["status"] for helper in result["helpers"]], [
            "tor_unreachable", "tor_unreachable", "tor_unreachable",
        ])

    def test_helper_recovery_posts_only_to_configured_slot(self):
        class Response:
            status = 202
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"accepted": true, "status": "restarting"}'

        pipeline = make_pipeline()
        with patch("tme3bot.worker.tts_pipeline.urllib.request.urlopen", return_value=Response()) as opened:
            result = pipeline.recover_helper(2)
        self.assertEqual(result, {"accepted": True, "status": "restarting"})
        self.assertEqual(opened.call_args.args[0].full_url, "http://helper-2/recover-tor")
        self.assertEqual(opened.call_args.args[0].method, "POST")
        with self.assertRaises(TtsError) as invalid:
            pipeline.recover_helper(4)
        self.assertEqual(invalid.exception.code, "TTS_HELPER_SLOT_INVALID")

    def test_helper_recovery_preserves_busy_and_cooldown_errors(self):
        pipeline = make_pipeline()
        busy = urllib.error.HTTPError(
            "http://helper-1/recover-tor", 409, "Conflict", {},
            io.BytesIO(b'{"error":"TTS_HELPER_BUSY"}'),
        )
        with patch("tme3bot.worker.tts_pipeline.urllib.request.urlopen", side_effect=busy):
            with self.assertRaises(TtsError) as raised:
                pipeline.recover_helper(1)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.code, "TTS_HELPER_BUSY")
        cooldown = urllib.error.HTTPError(
            "http://helper-1/recover-tor", 429, "Too Many Requests", {},
            io.BytesIO(b'{"error":"TTS_RECOVERY_COOLDOWN","retry_after_seconds":42}'),
        )
        with patch("tme3bot.worker.tts_pipeline.urllib.request.urlopen", side_effect=cooldown):
            with self.assertRaises(TtsError) as raised:
                pipeline.recover_helper(1)
        self.assertEqual(raised.exception.code, "TTS_RECOVERY_COOLDOWN")
        self.assertEqual(raised.exception.retry_after_seconds, 42)

    def test_helper_recovery_timeout_is_reported_as_unavailable(self):
        pipeline = make_pipeline()
        with patch(
            "tme3bot.worker.tts_pipeline.urllib.request.urlopen",
            side_effect=urllib.error.URLError(TimeoutError("timed out")),
        ):
            with self.assertRaises(TtsError) as raised:
                pipeline.recover_helper(1)
        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(raised.exception.code, "TTS_HELPER_UNAVAILABLE")

    def test_split_text_enforces_90_characters_even_for_long_words(self):
        value = "word " * 100 + "z" * 205
        parts = split_text(value)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= TTS_PART_CHARS for part in parts))
        self.assertEqual(sum(len(part.replace(" ", "")) for part in parts), 605)

    def test_split_text_handles_maximum_input_without_oversized_parts(self):
        parts = split_text("novel " * 16_666)
        self.assertGreater(len(parts), 1_000)
        self.assertTrue(all(0 < len(part) <= TTS_PART_CHARS for part in parts))

    @unittest.skipIf(tts_helper is None, "TTS helper runtime dependencies are optional in the test environment")
    def test_helper_accepts_only_90_character_parts_without_logging_text(self):
        class FakeGtts:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def write_to_fp(self, output):
                output.write(b"fake-mp3")

        client = tts_helper.app.test_client()
        text = "rahasia " * 11 + "x"
        self.assertEqual(len(text), 89)
        with patch.object(tts_helper, "gTTS", FakeGtts):
            accepted = client.post(
                "/synthesize-part",
                json={"text": text, "job_id": "job-safe", "part_index": 1},
            )
            rejected = client.post(
                "/synthesize-part", json={"text": text + "xx"}
            )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.data, b"fake-mp3")
        self.assertEqual(rejected.status_code, 422)

        class FailingGtts(FakeGtts):
            def write_to_fp(self, output):
                raise RuntimeError(text)

        with patch.object(tts_helper, "gTTS", FailingGtts):
            with self.assertLogs(tts_helper.LOGGER, level="WARNING") as captured:
                failed = client.post(
                    "/synthesize-part",
                    json={"text": text, "job_id": "job-safe", "part_index": 1},
                )
        self.assertEqual(failed.status_code, 502)
        self.assertNotIn(text, "\n".join(captured.output))

    @unittest.skipIf(tts_helper is None, "TTS helper runtime dependencies are optional in the test environment")
    def test_helper_diagnosis_and_recovery_are_async_coalesced_and_cooldown_limited(self):
        client = tts_helper.app.test_client()
        original = (
            tts_helper._RECOVERY_RUNNING,
            tts_helper._ACTIVE_SYNTHESIS,
            tts_helper._RECOVERY_LAST_STARTED,
            tts_helper._TOR_PROCESS,
        )
        try:
            tts_helper._TOR_PROCESS = None
            tts_helper._RECOVERY_RUNNING = False
            tts_helper._ACTIVE_SYNTHESIS = 0
            tts_helper._RECOVERY_LAST_STARTED = 0
            with patch.object(tts_helper, "_tor_diagnostics", return_value=("bootstrapping", 47)):
                diagnosis = client.get("/diagnostics")
            self.assertEqual(diagnosis.json, {"status": "bootstrapping", "bootstrap_percent": 47})

            with patch.object(tts_helper, "_tor_diagnostics", return_value=("ready", 100)):
                already_ready = client.post("/recover-tor")
            self.assertEqual(already_ready.status_code, 409)
            self.assertEqual(already_ready.json["error"], "TTS_HELPER_ALREADY_READY")

            tts_helper._ACTIVE_SYNTHESIS = 1
            with patch.object(tts_helper, "_tor_diagnostics", return_value=("tor_unreachable", None)):
                busy = client.post("/recover-tor")
            self.assertEqual(busy.status_code, 409)
            self.assertEqual(busy.json["error"], "TTS_HELPER_BUSY")

            tts_helper._ACTIVE_SYNTHESIS = 0
            class FakeThread:
                def __init__(self, **kwargs): self.kwargs = kwargs
                def start(self): pass
            with patch.object(tts_helper.threading, "Thread", FakeThread), patch.object(
                tts_helper, "_tor_diagnostics", return_value=("tor_unreachable", None)
            ):
                accepted = client.post("/recover-tor")
                duplicate = client.post("/recover-tor")
            self.assertEqual(accepted.status_code, 202)
            self.assertEqual(duplicate.status_code, 202)
            self.assertTrue(duplicate.json["accepted"])

            tts_helper._RECOVERY_RUNNING = False
            tts_helper._RECOVERY_LAST_STARTED = 0
            class BrokenThread(FakeThread):
                def start(self): raise RuntimeError("thread pool unavailable")
            with patch.object(tts_helper.threading, "Thread", BrokenThread), patch.object(
                tts_helper, "_tor_diagnostics", return_value=("tor_unreachable", None)
            ):
                failed_to_start = client.post("/recover-tor")
            self.assertEqual(failed_to_start.status_code, 503)
            self.assertFalse(tts_helper._RECOVERY_RUNNING)

            tts_helper._RECOVERY_RUNNING = False
            tts_helper._RECOVERY_LAST_STARTED = time.monotonic()
            with patch.object(tts_helper, "_tor_diagnostics", return_value=("tor_unreachable", None)):
                limited = client.post("/recover-tor")
            self.assertEqual(limited.status_code, 429)
            self.assertEqual(limited.json["error"], "TTS_RECOVERY_COOLDOWN")
        finally:
            (
                tts_helper._RECOVERY_RUNNING,
                tts_helper._ACTIVE_SYNTHESIS,
                tts_helper._RECOVERY_LAST_STARTED,
                tts_helper._TOR_PROCESS,
            ) = original

    @unittest.skipIf(tts_helper is None, "TTS helper runtime dependencies are optional in the test environment")
    def test_recovery_refuses_while_real_synthesis_request_is_active(self):
        client = tts_helper.app.test_client()
        entered = threading.Event()
        release = threading.Event()
        result = {}

        class BlockingGtts:
            def __init__(self, **kwargs):
                del kwargs
            def write_to_fp(self, output):
                entered.set()
                self.assert_release()
                output.write(b"fake-mp3")
            @staticmethod
            def assert_release():
                if not release.wait(3):
                    raise RuntimeError("test timeout")

        def synthesize():
            with tts_helper.app.test_client() as local_client:
                result["response"] = local_client.post(
                    "/synthesize-part", json={"text": "active request"}
                )

        try:
            with patch.object(tts_helper, "gTTS", BlockingGtts):
                thread = threading.Thread(target=synthesize)
                thread.start()
                self.assertTrue(entered.wait(2))
                refused = client.post("/recover-tor")
                self.assertEqual(refused.status_code, 409)
                self.assertEqual(refused.json["error"], "TTS_HELPER_BUSY")
                release.set()
                thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result["response"].status_code, 200)
        finally:
            release.set()

    @unittest.skipIf(tts_helper is None, "TTS helper runtime dependencies are optional in the test environment")
    def test_tor_recovery_restarts_only_the_child_process(self):
        class FakeProcess:
            def __init__(self):
                self.terminated = False
                self.killed = False
            def poll(self): return None
            def terminate(self): self.terminated = True
            def wait(self, timeout):
                del timeout
                return 0
            def kill(self): self.killed = True

        previous = tts_helper._TOR_PROCESS
        old_process = FakeProcess()
        try:
            tts_helper._TOR_PROCESS = old_process
            with patch.object(tts_helper, "_start_tor") as start_tor:
                tts_helper._restart_tor()
            self.assertTrue(old_process.terminated)
            self.assertFalse(old_process.killed)
            start_tor.assert_called_once_with()
        finally:
            tts_helper._TOR_PROCESS = previous

    def test_three_requests_run_concurrently_and_batches_wait_200ms(self):
        lock = threading.Lock()
        active = 0
        maximum = 0
        calls = []

        def request_part(text, job_id, index, total, route, attempt, directory):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
                calls.append((index, route, attempt))
            time.sleep(0.01)
            path = directory / f"part-{index:05d}.mp3"
            path.write_bytes(bytes([index % 255 or 1]))
            with lock:
                active -= 1
            return path

        sleeps = []
        pipeline = make_pipeline(request_part=request_part, sleep=sleeps.append)
        with tempfile.TemporaryDirectory() as temp:
            result = pipeline.synthesize("job-123", "ab " * 300, Path(temp))
        self.assertEqual(maximum, 3)
        self.assertEqual(len(calls), result["part_count"])
        self.assertEqual(sleeps.count(0.2), (result["part_count"] - 1) // 3)
        self.assertLessEqual(maximum, 3)

    def test_route_rotation_uses_helper_http_endpoint(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"renewed": true}'

        pipeline = make_pipeline()
        with patch("tme3bot.worker.tts_pipeline.urllib.request.urlopen", return_value=Response()) as opened:
            self.assertTrue(pipeline._renew_tor_route(1))
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "http://helper-2/newnym")
        self.assertEqual(request.method, "POST")

    def test_merge_keeps_part_order_and_large_output_splits_at_part_boundaries(self):
        def request_part(text, job_id, index, total, route, attempt, directory):
            path = directory / f"part-{index:05d}.mp3"
            path.write_bytes(bytes([index]) * 6)
            return path

        pipeline = make_pipeline(
            request_part=request_part,
            sleep=lambda _: None,
            telegram_audio_safe_bytes=10,
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = pipeline.synthesize("job-123", "word " * 80, root)
            self.assertGreater(result["part_count"], 1)
            self.assertEqual(len(result["artifacts"]), result["part_count"])
            for item in result["artifacts"]:
                self.assertLessEqual(item["byte_size"], 10)
                self.assertEqual(
                    (root / f"artifact-{item['artifact_ref']}.mp3").read_bytes(),
                    bytes([item["source_part_index"]]) * 6,
                )

    def test_rate_limit_rotates_route_renews_previous_route_and_retries(self):
        calls = []
        renewed = []
        sleeps = []

        def request_part(text, job_id, index, total, route, attempt, directory):
            calls.append((index, route, attempt))
            if index == 1 and attempt == 1:
                raise TtsError("rate limited", status=429)
            path = directory / f"part-{index:05d}.mp3"
            path.write_bytes(b"mp3")
            return path

        pipeline = make_pipeline(
            request_part=request_part,
            renew_route=renewed.append,
            sleep=sleeps.append,
        )
        with tempfile.TemporaryDirectory() as temp:
            pipeline.synthesize("job-123", "small text", Path(temp))
        self.assertIn((1, 0, 1), calls)
        self.assertIn((1, 1, 2), calls)
        self.assertEqual(renewed, [0])
        self.assertIn(2.0, sleeps)

    def test_checkpoint_skips_parts_already_synthesized(self):
        calls = []

        def request_part(text, job_id, index, total, route, attempt, directory):
            calls.append(index)
            path = directory / f"part-{index:05d}.mp3"
            path.write_bytes(b"mp3")
            return path

        pipeline = make_pipeline(request_part=request_part, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = pipeline.synthesize("job-123", "word " * 20, root)
            count = len(calls)
            second = pipeline.synthesize("job-123", "word " * 20, root)
        self.assertGreater(count, 0)
        self.assertEqual(len(calls), count)
        self.assertEqual(first["part_count"], second["part_count"])

    def test_pause_waits_until_current_batch_finishes_and_cancel_stops_after_batch(self):
        pause_event = threading.Event()
        pause_notified = threading.Event()
        completed = []

        def request_part(text, job_id, index, total, route, attempt, directory):
            completed.append(index)
            if index == 3:
                pause_event.set()
            path = directory / f"part-{index:05d}.mp3"
            path.write_bytes(b"mp3")
            return path

        pipeline = make_pipeline(request_part=request_part, sleep=lambda _: None)
        errors = []
        with tempfile.TemporaryDirectory() as temp:
            def run():
                try:
                    pipeline.synthesize(
                        "job-123",
                        "word " * 100,
                        Path(temp),
                        pause_event=pause_event,
                        on_paused=pause_notified.set,
                    )
                except Exception as exc:  # surfaced in the assertion below
                    errors.append(exc)

            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(pause_notified.wait(3))
            self.assertEqual(len(completed), 3)
            pause_event.clear()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors)

        cancelled_parts = []

        def request_cancelled(text, job_id, index, total, route, attempt, directory):
            cancelled_parts.append(index)
            path = directory / f"part-{index:05d}.mp3"
            path.write_bytes(b"mp3")
            return path

        cancel_pipeline = make_pipeline(request_part=request_cancelled, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(TtsCancelled):
                cancel_pipeline.synthesize(
                    "job-123",
                    "word " * 100,
                    Path(temp),
                    is_cancelled=lambda: len(cancelled_parts) >= 3,
                )
        self.assertEqual(len(cancelled_parts), 3)


if __name__ == "__main__":
    unittest.main()
