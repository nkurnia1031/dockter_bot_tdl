import tempfile
import unittest
from pathlib import Path

from tme3bot.application.control_plane import ControlPlane
from tme3bot.application.job_scheduler import build_execution_plan
from tme3bot.domain.models import Actor, DomainError, Job, JobEvent, JobStatus
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.worker_registry import WorkerRegistry


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

    def test_disabled_worker_rejects_new_jobs_and_routes(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "workers.json",
            {"local": "http://worker-local"},
            {"local": "worker-token"},
        )
        registry.set_enabled("local", False)
        self.control.worker_registry = registry

        with self.assertRaises(DomainError) as error:
            self.control.submit_job(self.actor, "export", {"url": "https://t.me/c/1/2"})
        self.assertEqual(error.exception.code, "WORKER_DISABLED")
        with self.assertRaises(DomainError) as route_error:
            self.control.set_worker_route(self.actor, "local")
        self.assertEqual(route_error.exception.code, "WORKER_DISABLED")

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

    def test_export_modes_queue_on_one_worker_but_run_on_different_workers(self):
        normal = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/2"}, worker="local"
        )
        quick_same_worker = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/3", "quick_mode": True},
            worker="local",
        )
        quick_other_worker = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/4", "quick_mode": True},
            worker="remote-1",
        )

        self.assertEqual(normal.status.value, "dispatched")
        self.assertEqual(quick_same_worker.status.value, "queued")
        self.assertEqual(quick_other_worker.status.value, "dispatched")
        self.assertEqual([command["worker"] for command in self.dispatcher.commands], ["local", "remote-1"])

    def test_quick_export_releases_export_lane_before_post_export_phases(self):
        plan = build_execution_plan(
            "export",
            "default",
            "local",
            {"quick_mode": True},
        )

        self.assertEqual(plan.lane, "tdl-quick-export")
        self.assertIn("profile:default:worker:local:tdl:export", plan.resource_keys)
        self.assertNotIn("profile:default:worker:local:tdl:download", plan.resource_keys)
        self.assertNotIn("worker:local:tdl:storage", plan.resource_keys)

        retry_plan = build_execution_plan(
            "export",
            "default",
            "local",
            {
                "quick_mode": True,
                "quick_retry": {"stage_job_id": "stage-1", "retry_phase": "downloading"},
            },
        )
        self.assertIn("worker:local:quick-stage:stage-1", retry_plan.resource_keys)
        self.assertNotIn("profile:default:worker:local:tdl:export", retry_plan.resource_keys)

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

    def test_terminate_quick_mode_filter_does_not_touch_normal_export(self):
        normal = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/2"}
        )
        quick = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/3", "quick_mode": True},
        )
        self.dispatcher.cancel_result = False

        result = self.control.terminate_active_jobs(
            self.actor, kind="export", quick_mode=True
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(self.jobs.get(quick.id).status.value, "cancelled")
        self.assertEqual(self.jobs.get(normal.id).status.value, "dispatched")

    def test_retry_quick_mode_creates_attempt_and_keeps_snapshot_and_stage(self):
        original = self.control.submit_job(
            self.actor,
            "export",
            {
                "url": "https://t.me/c/1/3",
                "quick_mode": True,
                "quick_settings": {
                    "compress_size": "45m",
                    "compress_password": "secret",
                },
            },
        )
        self.control.append_worker_event(
            JobEvent(
                job_id=original.id,
                sequence=2,
                status=JobStatus.RUNNING,
                event_type="progress",
                progress={"phase": "uploading", "message": "upload"},
            )
        )
        self.control.append_worker_event(
            JobEvent(
                job_id=original.id,
                sequence=3,
                status=JobStatus.FAILED,
                event_type="failed",
                error={"message": "storage offline"},
            )
        )

        retry = self.control.retry_job(self.actor, original.id)

        self.assertNotEqual(retry.id, original.id)
        self.assertEqual(retry.profile, original.profile)
        self.assertEqual(retry.worker, original.worker)
        self.assertEqual(retry.status.value, "dispatched")
        internal = self.jobs.command_payload(retry.id)
        self.assertEqual(internal["quick_settings"]["compress_size"], "45m")
        self.assertEqual(internal["quick_settings"]["compress_password"], "secret")
        self.assertEqual(internal["quick_retry"]["retry_of"], original.id)
        self.assertEqual(internal["quick_retry"]["retry_phase"], "uploading")
        self.assertEqual(internal["quick_retry"]["stage_job_id"], original.id)
        self.assertEqual(self.jobs.get(original.id).status.value, "failed")

    def test_retry_succeeded_starts_a_new_quick_operation_from_exporting(self):
        original = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/3", "quick_mode": True},
        )
        self.control.append_worker_event(
            JobEvent(
                job_id=original.id,
                sequence=2,
                status=JobStatus.RUNNING,
                event_type="started",
            )
        )
        self.control.append_worker_event(
            JobEvent(
                job_id=original.id,
                sequence=3,
                status=JobStatus.SUCCEEDED,
                event_type="completed",
            )
        )

        retry = self.control.retry_job(self.actor, original.id)
        internal = self.jobs.command_payload(retry.id)

        self.assertEqual(internal["quick_retry"]["retry_phase"], "exporting")
        self.assertEqual(internal["quick_retry"]["quick_operation_id"], original.id)

    def test_retry_normal_export_creates_a_new_attempt(self):
        original = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/8"}
        )
        self.control.append_worker_event(
            JobEvent(original.id, 2, JobStatus.FAILED, "failed", error={"message": "tdl"})
        )

        retry = self.control.retry_job(self.actor, original.id)

        self.assertNotEqual(retry.id, original.id)
        self.assertEqual(retry.status.value, "dispatched")
        internal = self.jobs.command_payload(retry.id)
        self.assertFalse(internal["quick_mode"])
        self.assertEqual(internal["export_retry"]["retry_of"], original.id)
        self.assertEqual(internal["export_retry"]["retry_phase"], "exporting")

    def test_legacy_normal_export_without_command_payload_can_be_retried(self):
        legacy = Job(
            id="legacy-export",
            kind="export",
            profile="default",
            actor_user_id=self.actor.telegram_user_id,
            worker="local",
            status=JobStatus.FAILED,
            payload={"url": "https://t.me/c/1/9"},
        )
        self.jobs.create(legacy)

        retry = self.control.retry_job(self.actor, legacy.id)

        self.assertEqual(retry.kind, "export")
        self.assertEqual(retry.worker, "local")
        self.assertEqual(self.jobs.command_payload(retry.id)["url"], "https://t.me/c/1/9")

    def test_retry_persists_message_id_range_for_reexport_without_json(self):
        original = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/100"},
        )
        self.control.append_worker_event(
            JobEvent(
                original.id,
                2,
                JobStatus.RUNNING,
                "export.json_ready",
                progress={
                    "phase": "json_ready",
                    "export_start_id": 100,
                    "export_end_id": 500,
                },
                result={
                    "json_name": "old.json",
                    "export_start_id": 100,
                    "export_end_id": 500,
                },
            )
        )
        self.control.append_worker_event(
            JobEvent(original.id, 3, JobStatus.FAILED, "failed", error={"message": "download"})
        )

        retry = self.control.retry_job(self.actor, original.id)
        metadata = self.jobs.command_payload(retry.id)["export_retry"]

        self.assertEqual(metadata["start_id"], 100)
        self.assertEqual(metadata["end_id"], 500)

    def test_quick_json_ready_releases_export_lane_for_next_quick_job(self):
        first = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/10", "quick_mode": True},
        )
        second = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/11", "quick_mode": True},
        )
        self.assertEqual(second.status.value, "queued")

        self.control.append_worker_event(
            JobEvent(
                first.id,
                2,
                JobStatus.RUNNING,
                "export.json_ready",
                progress={"phase": "json_ready"},
            )
        )

        self.assertEqual(self.jobs.get(second.id).status.value, "dispatched")
        self.assertEqual(len(self.dispatcher.commands), 2)


if __name__ == "__main__":
    unittest.main()
