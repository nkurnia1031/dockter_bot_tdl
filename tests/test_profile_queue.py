import threading
import time
import unittest

from tme3bot.profile_queue import ResourceAwareQueue, SerialPerKeyQueue


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


class ResourceAwareQueueTests(unittest.TestCase):
    def test_disjoint_resources_run_concurrently(self) -> None:
        started = {name: threading.Event() for name in ("export", "download")}
        release = threading.Event()

        def handle(job: str, resources: set[str]) -> None:
            self.assertTrue(resources)
            started[job].set()
            if not release.wait(timeout=3):
                raise TimeoutError(job)

        worker = ResourceAwareQueue[str](handle)
        worker.start()
        worker.enqueue({"profile:default:tdl:export"}, "export")
        worker.enqueue({"profile:default:tdl:download"}, "download")
        try:
            self.assertTrue(started["export"].wait(timeout=1))
            self.assertTrue(started["download"].wait(timeout=1))
        finally:
            release.set()
            worker.stop()

    def test_overlapping_resources_remain_serial(self) -> None:
        first_started = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()

        def handle(job: str, resources: set[str]) -> None:
            del resources
            if job == "first":
                first_started.set()
                if not release_first.wait(timeout=3):
                    raise TimeoutError(job)
            else:
                second_started.set()

        worker = ResourceAwareQueue[str](handle)
        worker.start()
        worker.enqueue({"profile:default:tdl:export"}, "first")
        worker.enqueue({"profile:default:tdl:export"}, "second")
        try:
            self.assertTrue(first_started.wait(timeout=1))
            time.sleep(0.05)
            self.assertFalse(second_started.is_set())
            release_first.set()
            self.assertTrue(second_started.wait(timeout=1))
        finally:
            release_first.set()
            worker.stop()

    def test_active_job_can_release_one_lane_before_completion(self) -> None:
        first_started = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()

        def handle(job: dict, resources: set[str]) -> None:
            if job["job_id"] == "first":
                first_started.set()
                self.assertIn("stage", resources)
                if not release_first.wait(timeout=3):
                    raise TimeoutError(job)
            else:
                second_started.set()

        worker = ResourceAwareQueue[str](handle)
        worker.start()
        worker.enqueue({"export", "stage"}, {"job_id": "first"}, job_id="first")
        worker.enqueue({"export"}, {"job_id": "second"}, job_id="second")
        try:
            self.assertTrue(first_started.wait(timeout=1))
            self.assertTrue(worker.release_resources("first", {"export"}))
            self.assertTrue(second_started.wait(timeout=1))
        finally:
            release_first.set()
            worker.stop()

    def test_pending_job_can_pause_and_resume_without_losing_queue_entry(self) -> None:
        first_started = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()

        def handle(job: dict, resources: set[str]) -> None:
            del resources
            if job["job_id"] == "first":
                first_started.set()
                if not release_first.wait(timeout=3):
                    raise TimeoutError("first")
            else:
                second_started.set()

        worker = ResourceAwareQueue[dict](handle)
        worker.start()
        worker.enqueue({"tdl"}, {"job_id": "first"}, job_id="first")
        worker.enqueue({"tdl"}, {"job_id": "second"}, job_id="second")
        try:
            self.assertTrue(first_started.wait(timeout=1))
            self.assertTrue(worker.pause_pending("second"))
            self.assertEqual(worker.queue_size(), 0)
            self.assertFalse(second_started.is_set())
            self.assertTrue(worker.resume_pending("second", event_sequence_start=9))
            self.assertEqual(worker.queue_size(), 1)
            release_first.set()
            self.assertTrue(second_started.wait(timeout=1))
        finally:
            release_first.set()
            worker.stop()


if __name__ == "__main__":
    unittest.main()
