import threading
import time
import unittest

from tme3bot.application.job_scheduler import build_execution_plan
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

    def test_shared_folder_copies_overlap_but_move_waits_and_blocks_later_copies(self) -> None:
        started = {name: threading.Event() for name in ("telegram", "rclone", "move", "late-copy")}
        finished = {name: threading.Event() for name in started}
        releases = {name: threading.Event() for name in started}

        def handle(job: str, resources: set[str]) -> None:
            del resources
            started[job].set()
            try:
                if not releases[job].wait(timeout=3):
                    raise TimeoutError(job)
            finally:
                finished[job].set()

        telegram_copy = build_execution_plan(
            "storage_upload",
            "default",
            "local",
            {
                "provider": "telegram",
                "folder_path": "/workspace/shared",
                "transfer_mode": "copy",
            },
        )
        rclone_copy = build_execution_plan(
            "storage_upload",
            "default",
            "local",
            {
                "provider": "rclone",
                "folder_path": "/workspace/shared",
                "transfer_mode": "copy",
            },
        )
        telegram_move = build_execution_plan(
            "storage_upload",
            "default",
            "local",
            {
                "provider": "telegram",
                "folder_path": "/workspace/shared",
                "transfer_mode": "move",
            },
        )
        worker = ResourceAwareQueue[str](handle)
        worker.start()
        worker.enqueue(telegram_copy.resource_keys, "telegram")
        worker.enqueue(rclone_copy.resource_keys, "rclone")
        try:
            self.assertTrue(started["telegram"].wait(timeout=1))
            self.assertTrue(started["rclone"].wait(timeout=1))

            worker.enqueue(telegram_move.resource_keys, "move")
            time.sleep(0.05)
            self.assertFalse(started["move"].is_set())

            worker.enqueue(rclone_copy.resource_keys, "late-copy")
            releases["telegram"].set()
            self.assertTrue(finished["telegram"].wait(timeout=1))
            time.sleep(0.05)
            self.assertFalse(started["move"].is_set())
            self.assertFalse(started["late-copy"].is_set())

            releases["rclone"].set()
            self.assertTrue(finished["rclone"].wait(timeout=1))
            self.assertTrue(started["move"].wait(timeout=1))

            self.assertFalse(started["late-copy"].is_set())
            releases["move"].set()
            self.assertTrue(started["late-copy"].wait(timeout=1))
        finally:
            for release in releases.values():
                release.set()
            worker.stop()

    def test_move_folder_lock_blocks_descendants_but_not_siblings(self) -> None:
        started = {name: threading.Event() for name in ("move", "descendant-copy", "sibling-copy")}
        release_move = threading.Event()
        release_copies = threading.Event()

        def handle(job: str, resources: set[str]) -> None:
            del resources
            started[job].set()
            release = release_move if job == "move" else release_copies
            if not release.wait(timeout=3):
                raise TimeoutError(job)

        worker = ResourceAwareQueue[str](handle)
        worker.start()
        worker.enqueue({"exclusive:worker:local:workspace:/workspace/shared"}, "move")
        try:
            self.assertTrue(started["move"].wait(timeout=1))
            worker.enqueue({"shared:worker:local:workspace:/workspace/shared/nested"}, "descendant-copy")
            worker.enqueue({"shared:worker:local:workspace:/workspace/other"}, "sibling-copy")
            self.assertTrue(started["sibling-copy"].wait(timeout=1))
            time.sleep(0.05)
            self.assertFalse(started["descendant-copy"].is_set())
            release_move.set()
            self.assertTrue(started["descendant-copy"].wait(timeout=1))
        finally:
            release_move.set()
            release_copies.set()
            worker.stop()

    def test_shared_copy_lock_conflicts_with_existing_workspace_writer(self) -> None:
        writer_started = threading.Event()
        copy_started = threading.Event()
        release_writer = threading.Event()

        def handle(job: str, resources: set[str]) -> None:
            del resources
            if job == "writer":
                writer_started.set()
                if not release_writer.wait(timeout=3):
                    raise TimeoutError(job)
            else:
                copy_started.set()

        workspace = "worker:local:workspace:/workspace/shared"
        worker = ResourceAwareQueue[str](handle)
        worker.start()
        worker.enqueue({workspace}, "writer")
        try:
            self.assertTrue(writer_started.wait(timeout=1))
            worker.enqueue({f"shared:{workspace}"}, "copy")
            time.sleep(0.05)
            self.assertFalse(copy_started.is_set())
            release_writer.set()
            self.assertTrue(copy_started.wait(timeout=1))
        finally:
            release_writer.set()
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
