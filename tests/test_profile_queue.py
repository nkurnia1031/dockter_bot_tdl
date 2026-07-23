import threading
import time
import unittest

from tme3bot.profile_queue import SerialPerKeyQueue


class SerialPerKeyQueueTests(unittest.TestCase):
    def test_different_keys_run_concurrently(self) -> None:
        first_started = threading.Event()
        second_started = threading.Event()
        first_release = threading.Event()
        second_release = threading.Event()
        controls = {
            "first": (first_started, first_release),
            "second": (second_started, second_release),
        }

        def handle(job: str, jobs) -> None:
            del jobs
            started, release = controls[job]
            started.set()
            if not release.wait(timeout=3):
                raise TimeoutError(f"{job} was not released")

        worker = SerialPerKeyQueue[str, str](handle)
        worker.start()
        worker.enqueue("first", "first")
        worker.enqueue("second", "second")
        try:
            self.assertTrue(first_started.wait(timeout=1))
            self.assertTrue(second_started.wait(timeout=1))
        finally:
            first_release.set()
            second_release.set()

    def test_same_key_remains_serial(self) -> None:
        first_started = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()

        def handle(job: str, jobs) -> None:
            del jobs
            if job == "first":
                first_started.set()
                if not release_first.wait(timeout=3):
                    raise TimeoutError("first was not released")
            else:
                second_started.set()

        worker = SerialPerKeyQueue[str, str](handle)
        worker.start()
        worker.enqueue("same", "first")
        worker.enqueue("same", "second")
        try:
            self.assertTrue(first_started.wait(timeout=1))
            time.sleep(0.05)
            self.assertFalse(second_started.is_set())
            release_first.set()
            self.assertTrue(second_started.wait(timeout=1))
        finally:
            release_first.set()


if __name__ == "__main__":
    unittest.main()
