import tempfile
import threading
import time
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
