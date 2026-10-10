import tempfile
import unittest
from pathlib import Path

from tme3bot.application.control_plane import ControlPlane
from tme3bot.application.operations import OperationsService
from tme3bot.domain.models import Actor, DomainError, JobEvent, JobStatus
from tme3bot.domain.worker_contract import (
    CAP_DURABLE_COMMANDS_V1,
    CAP_TTS,
    WORKER_API_CAPABILITIES,
    WORKER_API_CONTRACT_VERSION,
)
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.infrastructure.operation_store import SqliteOperationStore
from tme3bot.infrastructure.settings_store import SqliteSettingsStore
from tme3bot.infrastructure.tdl_access_store import SqliteTdlAccessStore


class FakeProfiles:
    def list_profiles(self):
        return ["default", "archive"]

    def worker_route(self, profile):
        del profile
        return "local"


class FakeUtilitySettings:
    def get(self):
        return {
            "move_size": "4g",
            "compress_size": "4g",
            "compress_password": "server-only-password",
            "rclone_destination": "googledrive:backup",
        }


class FakeWorkerRegistry:
    def names(self):
        return ["local", "remote-2"]

    def get(self, name):
        return {"enabled": True} if name in self.names() else None


class FakeArtifactCatalog:
    def __init__(self, values):
        self.values = values

    def get(self, artifact_id):
        return self.values.get(str(artifact_id))


class FakeDispatcher:
    def __init__(self, *, durable=True):
        self.durable = durable
        self.commands = []
        self.legacy_commands = []
        self.cancel_calls = []
        self.cancel_result = True
        self.dispatch_results = []

    def capabilities(self, worker):
        del worker
        capabilities = set(WORKER_API_CAPABILITIES)
        if self.durable:
            capabilities.add(CAP_DURABLE_COMMANDS_V1)
        capabilities.add(CAP_TTS)
        return {
            "contract_version": WORKER_API_CONTRACT_VERSION,
            "capabilities": sorted(capabilities),
            "tts": True,
            "profiles": ["default", "archive"],
            "export_profiles": ["default", "archive"],
            "download_profiles": ["default", "archive"],
            "available_storage_profiles": ["default", "archive"],
            "tts_health": {
                "helpers_ready": True,
                "helpers": [
                    {"slot": slot, "status": "ready", "bootstrap_percent": 100}
                    for slot in range(1, 4)
                ],
            },
        }

    def dispatch(self, worker, command):
        self.legacy_commands.append((worker, command))

    def dispatch_command(self, worker, command):
        self.commands.append((worker, command))
        result = self.dispatch_results.pop(0) if self.dispatch_results else {"accepted": True}
        if isinstance(result, Exception):
            raise result
        return result

    def cancel(self, worker, job_id):
        self.cancel_calls.append((worker, job_id))
        return self.cancel_result


class DurableDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_file = Path(self.temp.name) / "jobs.db"
        self.jobs = SqliteJobRepository(self.db_file)
        self.settings = SqliteSettingsStore(
            self.db_file, Path(self.temp.name) / "runtime-settings" / "settings.key"
        )
        self.settings.update(
            "telegram", {"telegram_tts_chat_id": "123456789"}, expected_version=0
        )
        self.store = SqliteOperationStore(self.jobs)
        self.operations = OperationsService(self.store)
        self.dispatcher = FakeDispatcher()
        self.workers = FakeWorkerRegistry()
        self.tdl_access = SqliteTdlAccessStore(self.db_file)
        self.control = ControlPlane(
            self.jobs, self.dispatcher, FakeProfiles(),
            runtime_settings_store=self.settings,
            worker_registry=self.workers,
            tdl_access_store=self.tdl_access,
            tdl_access_target_resolver=lambda purpose: "123456789" if purpose == "tts" else "123",
        )
        inventory_hash = self.tdl_access.inventory_fingerprint(["default", "archive"])
        destination_hash = self.tdl_access.destination_fingerprint("123456789")
        for worker in self.workers.names():
            self.tdl_access.replace_results(
                worker, "tts", destination_hash, inventory_hash,
                [{"profile": profile, "ready": True} for profile in ("default", "archive")],
            )
        self.control.utility_settings = FakeUtilitySettings()
        self.control.add_event_observer(self.operations.on_job_event)
        self.operations.register_handler("job.submit", self.control.prepare_durable_job)
        self.actor = Actor(42, "default")

    def tearDown(self):
        self.temp.cleanup()

    def submit(self, job_kind="export", payload=None, worker="local"):
        return self.operations.submit(
            self.actor,
            kind="job.submit",
            target={"profile": "default", "worker": worker},
            input_data={
                "job_kind": job_kind,
                "payload": payload or {"url": "https://t.me/c/100/2"},
            },
            idempotency_key=f"submit-{job_kind}-{worker}-{self.jobs.count()}",
        )[0]

    @staticmethod
    def queue_command(operation):
        return {
            "operation_id": operation.id,
            "attempt": operation.attempt,
            "private_payload": {"job_id": operation.job_id},
        }

    def test_submit_persists_job_plan_and_private_payload_without_worker_io(self):
        operation = self.submit("tts", {"title": "Narasi", "text": "teks privat"})
        job = self.jobs.get(operation.job_id)
        command = self.jobs.command_payload(operation.job_id)

        self.assertEqual(operation.status.value, "queued")
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertEqual(job.payload, {
            "title": "Narasi", "character_count": 11, "sender_profile": "archive",
        })
        self.assertEqual(command["payload"]["text"], "teks privat")
        self.assertEqual(command["dispatch_mode"], "durable")
        self.assertEqual(command["attempt"], 1)
        self.assertFalse(command["dispatch_started"])
        self.assertEqual(
            self.jobs.execution_plan(job.id)["resource_keys"],
            [
                "profile:archive:worker:local:tdl:export",
                "profile:default:worker:local:tdl:export",
                "worker:local:kind:tts",
            ],
        )
        self.assertEqual(self.dispatcher.commands, [])
        self.assertEqual(self.dispatcher.legacy_commands, [])
        with self.jobs._db() as db:
            outbox = db.execute(
                "SELECT topic, status FROM operation_outbox WHERE operation_id=?",
                (operation.id,),
            ).fetchone()
        self.assertEqual(tuple(outbox), ("operation.accepted", "pending"))

    def test_job_pins_worker_settings_version_and_encrypts_tts_recipient(self):
        self.settings.update(
            "worker", {"tts_part_retries": 7}, expected_version=0, worker="local"
        )
        operation = self.submit("tts", {"title": "Narasi", "text": "teks privat"})
        job = self.jobs.get(operation.job_id)
        self.assertEqual(job.settings_version, 1)
        self.assertEqual(self.jobs.command_payload(job.id)["settings_version"], 1)
        encrypted = self.jobs.private_value(job.id, "telegram_tts_chat_id")
        self.assertIsNotNone(encrypted)
        self.assertNotIn(b"123456789", encrypted)
        self.assertEqual(
            self.settings.decrypt_job_secret(job.id, "telegram_tts_chat_id", encrypted),
            "123456789",
        )
        dispatched = self.control.advance_durable_job(self.queue_command(operation))
        self.assertEqual(dispatched["status"], "accepted")
        self.assertEqual(self.dispatcher.commands[-1][1]["settings_version"], 1)
        with self.jobs._db() as db:
            row = db.execute(
                "SELECT settings_version FROM jobs WHERE id=?", (job.id,)
            ).fetchone()
        self.assertEqual(int(row["settings_version"]), 1)

    def test_client_cannot_override_internal_settings_or_quickmode_checkpoint(self):
        with self.assertRaises(DomainError) as utility_error:
            self.submit(
                "utility",
                {
                    "utility": "compress",
                    "folders": ["/workspace/example"],
                    "settings": {"compress_password": "attacker"},
                },
            )
        self.assertEqual(utility_error.exception.code, "JOB_PAYLOAD_INVALID")

        with self.assertRaises(DomainError) as quick_error:
            self.submit(
                "export",
                {
                    "url": "https://t.me/c/100/2",
                    "quick_mode": True,
                    "quick_settings": {"rclone_destination": "attacker:dump"},
                },
            )
        self.assertEqual(quick_error.exception.code, "JOB_PAYLOAD_INVALID")

    def test_leave_operation_uses_requesting_actor_profile(self):
        prepared = self.control.prepare_durable_job(
            self.actor,
            {"profile": "archive", "worker": "local"},
            {"job_kind": "leave", "payload": {"chat_refs": ["@example"]}},
        )

        self.assertEqual(prepared.profile, "default")
        self.assertEqual(prepared.job.profile, "default")
        self.assertEqual(prepared.command_payload["profile"], "default")

    def test_utility_settings_are_snapshotted_privately_by_backend(self):
        operation = self.submit(
            "utility",
            {"utility": "compress", "folders": ["/workspace/example"]},
        )
        job = self.jobs.get(operation.job_id)
        command = self.jobs.command_payload(operation.job_id)

        self.assertEqual(command["payload"]["settings"]["compress_password"], "server-only-password")
        self.assertEqual(job.payload["settings"]["compress_password"], "***")

    def test_legacy_scheduler_skips_durable_job_and_old_worker_waits(self):
        operation = self.submit()
        self.control._dispatch_pending_jobs()
        self.assertEqual(self.dispatcher.legacy_commands, [])

        self.dispatcher.durable = False
        result = self.control.advance_durable_job(self.queue_command(operation))

        self.assertEqual(result["status"], "wait")
        self.assertEqual(self.dispatcher.commands, [])
        self.assertFalse(self.jobs.command_payload(operation.job_id)["dispatch_started"])
        self.assertEqual(self.jobs.get(operation.job_id).status, JobStatus.QUEUED)

    def test_unready_profile_sync_does_not_block_job_dispatch(self):
        self.control.profile_readiness = lambda profile, worker: False

        operation = self.submit()
        result = self.control.advance_durable_job(self.queue_command(operation))

        self.assertEqual(operation.status.value, "queued")
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(len(self.dispatcher.commands), 1)

    def test_download_payload_is_rebuilt_from_artifacts_pinned_to_target_origin(self):
        artifact = {
            "id": "artifact-1",
            "profile": "default",
            "worker": "local",
            "status": "pending",
            "available": 1,
            "artifact_key": "private-artifact-key",
        }
        self.control.export_catalog = FakeArtifactCatalog({"artifact-1": artifact})
        operation = self.submit("download", {"artifact_ids": ["artifact-1"]})
        command_payload = self.jobs.command_payload(operation.job_id)["payload"]

        self.assertEqual(command_payload["artifact_keys"], ["private-artifact-key"])
        self.assertNotIn("artifact_ids", command_payload)
        self.assertEqual(self.jobs.get(operation.job_id).worker, "local")

        artifact["worker"] = "remote-2"
        with self.assertRaises(DomainError) as raised:
            self.submit("download", {"artifact_ids": ["artifact-1"]})
        self.assertEqual(raised.exception.code, "ARTIFACT_ORIGIN_MIXED")

    def test_compatible_worker_receives_v2_envelope_once(self):
        operation = self.submit()
        command = self.queue_command(operation)

        first = self.control.advance_durable_job(command)
        second = self.control.advance_durable_job(command)

        self.assertEqual(first["status"], "accepted")
        self.assertEqual(second["status"], "accepted")
        self.assertEqual(len(self.dispatcher.commands), 1)
        envelope = self.dispatcher.commands[0][1]
        self.assertEqual(envelope["operation_id"], operation.id)
        self.assertEqual(envelope["job_id"], operation.job_id)
        self.assertEqual(envelope["attempt"], 1)
        self.assertTrue(envelope["dispatch_token"])
        self.assertEqual(envelope["profile_revision"], 0)
        self.assertEqual(envelope["settings_version"], 0)
        self.assertIn("resource_keys", envelope["execution_plan"])
        self.assertEqual(self.jobs.get(operation.job_id).status, JobStatus.DISPATCHED)

    def test_timeout_retry_reuses_same_command_identity_and_token(self):
        operation = self.submit()
        self.dispatcher.dispatch_results = [TimeoutError(), {"accepted": True}]
        command = self.queue_command(operation)

        self.assertEqual(self.control.advance_durable_job(command)["status"], "wait")
        self.assertEqual(self.control.advance_durable_job(command)["status"], "accepted")

        first = self.dispatcher.commands[0][1]
        second = self.dispatcher.commands[1][1]
        self.assertEqual(first["command_id"], second["command_id"])
        self.assertEqual(first["dispatch_token"], second["dispatch_token"])

    def test_cancel_waits_for_worker_after_dispatch_acceptance_is_ambiguous(self):
        operation = self.submit()
        self.dispatcher.dispatch_results = [TimeoutError()]
        submit_command = self.queue_command(operation)
        self.assertEqual(self.control.advance_durable_job(submit_command)["status"], "wait")

        self.operations.cancel(self.actor, operation.id, "cancel-1")
        cancel_command = self.queue_command(operation)
        first = self.control.advance_durable_cancel(cancel_command)
        job = self.jobs.get(operation.job_id)

        self.assertEqual(first["status"], "wait")
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertEqual(self.dispatcher.cancel_calls, [("local", operation.job_id)])

        sequence = max((event.sequence for event in self.jobs.events(operation.job_id)), default=0) + 1
        self.control.append_worker_event(
            JobEvent(
                job_id=operation.job_id,
                sequence=sequence,
                status=JobStatus.CANCELLED,
                event_type="cancelled",
                progress={"phase": "cancelled"},
            )
        )
        self.assertEqual(self.control.advance_durable_cancel(cancel_command)["status"], "accepted")
        self.assertEqual(self.operations.get(self.actor, operation.id).status.value, "cancelled")

    def test_cancel_before_dispatch_prevents_worker_side_effect(self):
        operation = self.submit()
        self.operations.cancel(self.actor, operation.id, "cancel-before-dispatch")

        advanced = self.control.advance_durable_job(self.queue_command(operation))
        cancelled = self.control.advance_durable_cancel(self.queue_command(operation))

        self.assertEqual(advanced["reason"], "dispatch_aborted")
        self.assertEqual(cancelled["status"], "accepted")
        self.assertEqual(self.dispatcher.commands, [])
        self.assertEqual(self.jobs.get(operation.job_id).status, JobStatus.CANCELLED)

    def test_retry_uses_new_command_identity_and_attempt(self):
        operation = self.submit()
        self.control.advance_durable_job(self.queue_command(operation))
        first_envelope = self.dispatcher.commands[-1][1]
        sequence = max(event.sequence for event in self.jobs.events(operation.job_id)) + 1
        self.control.append_worker_event(
            JobEvent(
                job_id=operation.job_id,
                sequence=sequence,
                status=JobStatus.FAILED,
                event_type="failed",
                error={"code": "FAILED", "message": "failed"},
            )
        )

        retried, _ = self.operations.retry(self.actor, operation.id, "retry-1")
        self.assertEqual(retried.attempt, 2)
        self.control.advance_durable_job(self.queue_command(retried))
        second_envelope = self.dispatcher.commands[-1][1]

        self.assertEqual(second_envelope["attempt"], 2)
        self.assertNotEqual(first_envelope["command_id"], second_envelope["command_id"])
        self.assertNotEqual(first_envelope["dispatch_token"], second_envelope["dispatch_token"])
        self.assertTrue(any(event.event_type == "retry_started" for event in self.jobs.events(operation.job_id)))

    def test_tts_lane_is_one_job_per_worker_but_workers_are_independent(self):
        first = self.submit("tts", {"title": "One", "text": "audio"}, worker="local")
        second = self.submit("tts", {"title": "Two", "text": "audio"}, worker="local")
        other_worker = self.submit("tts", {"title": "Three", "text": "audio"}, worker="remote-2")

        self.control.advance_durable_job(self.queue_command(first))
        blocked = self.control.advance_durable_job(self.queue_command(second))
        independent = self.control.advance_durable_job(self.queue_command(other_worker))

        self.assertEqual(blocked["status"], "wait")
        self.assertEqual(independent["status"], "accepted")
        self.assertEqual([worker for worker, _ in self.dispatcher.commands], ["local", "remote-2"])


if __name__ == "__main__":
    unittest.main()
