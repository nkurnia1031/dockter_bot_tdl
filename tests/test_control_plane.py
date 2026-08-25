import tempfile
import unittest
from pathlib import Path

from tme3bot.application.control_plane import ControlPlane
from tme3bot.domain.models import Actor, JobEvent, JobStatus
from tme3bot.infrastructure.job_store import SqliteJobRepository


class FakeProfiles:
    def __init__(self):
        self.route = "local"

    def worker_route(self, profile):
        return self.route

    def set_worker_route(self, profile, route):
        self.route = route
        return route


class FakeDispatcher:
    def __init__(self):
        self.commands = []
        self.cancel_result = True

    def dispatch(self, worker, command):
        self.commands.append(command)

    def cancel(self, worker, job_id):
        return self.cancel_result


class FailingDispatcher(FakeDispatcher):
    def dispatch(self, worker, command):
        del worker, command
        raise RuntimeError("worker offline")


class ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs = SqliteJobRepository(Path(self.temp.name) / "jobs.db")
        self.profiles = FakeProfiles()
        self.dispatcher = FakeDispatcher()
        self.control = ControlPlane(self.jobs, self.dispatcher, self.profiles)
        self.actor = Actor(42, "default")

    def tearDown(self):
        self.temp.cleanup()

    def test_active_job_keeps_original_worker_when_route_changes(self):
        first_job = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/2"}
        )

        route = self.control.set_worker_route(self.actor, "remote-1")
        next_job = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/3"}
        )

        self.assertEqual(route, "remote-1")
        self.assertEqual(first_job.worker, "local")
        self.assertEqual(next_job.worker, "remote-1")

    def test_same_kind_is_admitted_serially_while_download_lane_can_run(self):
        first = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/2"}
        )
        second = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/3"}
        )
        download = self.control.submit_job(
            self.actor, "download", {"artifact_ids": []}
        )

        self.assertEqual(first.status.value, "dispatched")
        self.assertEqual(second.status.value, "queued")
        self.assertEqual(download.status.value, "dispatched")
        self.assertEqual(len(self.dispatcher.commands), 2)

    def test_same_kind_different_profiles_can_run_in_parallel(self):
        first = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/2"}, profile="default"
        )
        second = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/3"}, profile="archive"
        )

        self.assertEqual(first.status.value, "dispatched")
        self.assertEqual(second.status.value, "dispatched")
        self.assertEqual(len(self.dispatcher.commands), 2)

    def test_utility_sibling_paths_can_run_but_nested_path_waits(self):
        first = self.control.submit_job(
            self.actor, "utility", {"utility": "compress", "folders": ["/workspace/a"]}
        )
        sibling = self.control.submit_job(
            self.actor, "utility", {"utility": "compress", "folders": ["/workspace/b"]}
        )
        nested = self.control.submit_job(
            self.actor, "utility", {"utility": "compress", "folders": ["/workspace/a/nested"]}
        )

        self.assertEqual(first.status.value, "dispatched")
        self.assertEqual(sibling.status.value, "dispatched")
        self.assertEqual(nested.status.value, "queued")

    def test_terminal_event_releases_lane_and_dispatches_next_job(self):
        first = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/2"}
        )
        second = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/3"}
        )

        self.assertEqual(second.status.value, "queued")
        self.control.append_worker_event(
            JobEvent(
                job_id=first.id,
                sequence=2,
                status=JobStatus.RUNNING,
                event_type="started",
            )
        )
        self.control.append_worker_event(
            JobEvent(
                job_id=first.id,
                sequence=3,
                status=JobStatus.SUCCEEDED,
                event_type="completed",
                result={"value": {"exported_count": 0}},
            )
        )

        self.assertEqual(self.jobs.get(second.id).status.value, "dispatched")
        self.assertEqual(len(self.dispatcher.commands), 2)

    def test_nested_utility_secrets_are_not_persisted(self):
        job = self.control.submit_job(
            self.actor,
            "utility",
            {
                "utility": "compress",
                "password": "extract-secret",
                "settings": {
                    "compress_password": "archive-secret",
                    "compress_size": "45m",
                },
            },
        )

        persisted = self.jobs.get(job.id)
        self.assertEqual(persisted.payload["password"], "***")
        self.assertEqual(
            persisted.payload["settings"]["compress_password"], "***"
        )
        self.assertEqual(
            self.dispatcher.commands[0]["payload"]["password"],
            "extract-secret",
        )

    def test_terminate_waits_for_worker_terminal_event(self):
        job = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/2"}
        )

        returned = self.control.cancel_job(self.actor, job.id)

        self.assertEqual(returned.status.value, "dispatched")
        self.assertTrue(self.jobs.has_active("default"))
        self.assertFalse(any(event.status.value == "cancelled" for event in self.jobs.events(job.id)))

    def test_dispatch_failure_is_terminal_after_dispatched_event(self):
        control = ControlPlane(self.jobs, FailingDispatcher(), self.profiles)

        with self.assertRaisesRegex(Exception, "tidak dapat menerima job"):
            control.submit_job(self.actor, "export", {"url": "https://t.me/c/1/2"})

        jobs = self.jobs.list(profile="default", limit=10)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].status.value, "failed")
        self.assertEqual([event.sequence for event in self.jobs.events(jobs[0].id)], [1, 2])

    def test_terminate_all_force_cancels_stale_jobs(self):
        first = self.control.submit_job(self.actor, "export", {"url": "https://t.me/c/1/2"})
        second = self.control.submit_job(self.actor, "utility", {"utility": "pindah", "folders": []})
        self.dispatcher.cancel_result = False

        result = self.control.terminate_active_jobs(self.actor)

        self.assertEqual(result, {"total": 2, "interrupted": 0, "force_cancelled": 2})
        self.assertEqual(self.jobs.get(first.id).status.value, "cancelled")
        self.assertEqual(self.jobs.get(second.id).status.value, "cancelled")


if __name__ == "__main__":
    unittest.main()
