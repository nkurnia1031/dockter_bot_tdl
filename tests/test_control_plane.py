import hashlib
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from tme3bot.api.backend import job_dict
from tme3bot.application.control_plane import ControlPlane
from tme3bot.application.job_scheduler import build_execution_plan
from tme3bot.domain.models import Actor, DomainError, Job, JobEvent, JobStatus, utc_now
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.application.runtime_readiness import RuntimeReadinessGate
from tme3bot.infrastructure.runtime_readiness_store import RuntimeReadinessStore
from tme3bot.infrastructure.tdl_access_store import SqliteTdlAccessStore
from tme3bot.domain.worker_contract import CAP_SHARED_EXPORT_CURSOR
from tme3bot.worker_registry import WorkerRegistry


class FakeProfiles:
    def __init__(self):
        self.route = "local"

    def worker_route(self, profile):
        return self.route

    def set_worker_route(self, profile, route):
        self.route = route
        return route

    def list_profiles(self):
        return ["default", "archive", "other"]


class FakeJobSecretStore:
    def encrypt_job_secret(self, job_id, key, value):
        del job_id, key
        return value.encode("utf-8")

    def decrypt_job_secret(self, job_id, key, ciphertext):
        del job_id, key
        return bytes(ciphertext).decode("utf-8")


class FakeDispatcher:
    def __init__(self):
        self.commands = []
        self.durable_commands = []
        self.cancel_result = True
        self.resume_result = False

    def dispatch(self, worker, command):
        self.commands.append(command)

    def dispatch_command(self, worker, envelope):
        self.durable_commands.append(envelope)
        job = envelope["job"]
        self.dispatch(worker, {
            "job_id": envelope["job_id"],
            "attempt": envelope["attempt"],
            "kind": job["kind"],
            "profile": job["profile"],
            "actor_user_id": job["actor_user_id"],
            "worker": job["worker"],
            "payload": job["payload"],
            "execution": envelope["execution_plan"],
            "event_sequence_start": envelope["event_sequence_start"],
        })
        return {"accepted": True}

    def cancel(self, worker, job_id):
        return self.cancel_result

    def resume(self, worker, job_id, event_sequence_start):
        del worker, job_id, event_sequence_start
        return self.resume_result

    def capabilities(self, worker):
        fingerprints = {
            "default": "a" * 64,
            "archive": "b" * 64,
            "other": "c" * 64,
        }
        return {
            "tts": worker == "tts-ready",
            "capabilities": ["tts"] if worker == "tts-ready" else [],
            "profiles": list(fingerprints),
            "export_profiles": list(fingerprints),
            "available_storage_profiles": list(fingerprints),
            "storage_upload_fingerprints": fingerprints,
        }


class FakeBackupCatalog:
    def __init__(self, run_status="complete", *, node="remote-2"):
        self.run = {"run_id": "run-abc", "node_name": node, "started_at": "2026-10-11T01:00:00+00:00", "status": run_status}

    def backup_runs(self, node_name=None, limit=50):
        del limit
        return [self.run] if node_name == self.run["node_name"] else []

    def backup_parts(self, run_id, node_name):
        if run_id != self.run["run_id"] or node_name != self.run["node_name"]:
            return []
        return [{
            "part_name": "backup-remote.7z.001",
            "channel_id": -100123456,
            "channel_message_id": 733,
            "file_size": 1024,
            "sha256": "a" * 64,
            "status": "active",
        }]


class FailingDispatcher(FakeDispatcher):
    def dispatch(self, worker, command):
        del worker, command
        raise RuntimeError("worker offline")


class IncompatibleDispatcher(FakeDispatcher):
    def dispatch(self, worker, command):
        del worker, command
        raise DomainError(
            "WORKER_INCOMPATIBLE", "Worker perlu diperbarui.", status_code=409
        )


class FakeExportCursorGate:
    def __init__(self):
        self.enabled = False
        self.leases = set()
        self.committed = set()

    def lease_for_job(self, job_id):
        return {"lease_attempt": 1} if job_id in self.leases else None

    def job_has_active_lease(self, job_id):
        return job_id in self.leases

    def completion_applied(self, job_id, attempt=None):
        del attempt
        return job_id in self.committed

    def finish_job(self, job_id, **kwargs):
        del kwargs
        self.leases.discard(job_id)
        return True


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

    def attach_resolver_readiness(self, control, workers):
        store = RuntimeReadinessStore(
            Path(self.temp.name) / f"resolver-readiness-{id(control)}.json"
        )
        store.apply_export_scan(
            checked_at="2026-10-23T10:00:00Z",
            workers=[{"worker": name, "status": "success"} for name in workers],
            profiles={},
        )
        store.apply_resolver_scan(
            checked_at="2026-10-23T10:00:00Z",
            workers=workers,
        )
        control.runtime_readiness_gate = RuntimeReadinessGate(store)
        return store

    def authorize_quick_mode_storage(
        self, control=None, dispatcher=None, workers=("local",)
    ):
        control = control or self.control
        dispatcher = dispatcher or self.dispatcher
        store = SqliteTdlAccessStore(
            Path(self.temp.name) / f"quick-storage-access-{id(control)}.db"
        )
        control.tdl_access_store = store
        control.tdl_access_target_resolver = lambda purpose: (
            "-100123" if purpose == "storage" else ""
        )
        control.runtime_settings_store = FakeJobSecretStore()
        for worker in workers:
            capabilities = dispatcher.capabilities(worker)
            fingerprints = capabilities["storage_upload_fingerprints"]
            inventory_hash = store.inventory_fingerprint(
                capabilities["available_storage_profiles"], fingerprints
            )
            store.replace_results(
                worker,
                "storage",
                store.destination_fingerprint("-100123"),
                inventory_hash,
                [
                    {"profile": profile, "ready": True}
                    for profile in capabilities["available_storage_profiles"]
                ],
                session_fingerprints=fingerprints,
            )

    def attach_storage_readiness(self, *, profiles=("default", "archive", "other")):
        runtime_store = RuntimeReadinessStore(
            Path(self.temp.name) / f"storage-readiness-{id(self.control)}.json"
        )
        capabilities = self.dispatcher.capabilities("local")
        fingerprints = capabilities["storage_upload_fingerprints"]
        runtime_store.apply_export_scan(
            checked_at="2026-10-23T10:00:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [
                {"profile": profile, "ready": True, "fingerprint": fingerprints[profile]}
                for profile in fingerprints
            ]},
        )
        destination_hash = self.control.tdl_access_store.destination_fingerprint("-100123")
        runtime_store.apply_storage_scan(
            checked_at="2026-10-23T10:05:00Z",
            profiles={"local": [
                {
                    "profile": profile,
                    "ready": True,
                    "fingerprint": hashlib.sha256(profile.encode()).hexdigest(),
                    "session_fingerprint": fingerprints[profile],
                    "destination_fingerprint": destination_hash,
                }
                for profile in profiles
            ]},
        )
        self.control.runtime_readiness_gate = RuntimeReadinessGate(runtime_store)
        return runtime_store

    def test_quick_mode_pins_verified_storage_target_and_hides_fingerprints(self):
        self.authorize_quick_mode_storage()

        job = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/3", "quick_mode": True},
        )

        worker_payload = self.dispatcher.commands[-1]["payload"]
        self.assertEqual(worker_payload["_quick_storage_tdl_access_target"], "-100123")
        self.assertEqual(
            worker_payload["_quick_storage_sender_profiles"],
            ["archive", "default", "other"],
        )
        self.assertEqual(
            worker_payload["_quick_storage_sender_session_fingerprints"]["default"],
            "a" * 64,
        )
        self.assertNotIn("tdl_sender_session_fingerprints", str(job.payload))
        self.assertNotIn("-100123", str(job.payload))

    def test_quick_mode_requires_scanned_cell_without_live_capability_probe(self):
        self.authorize_quick_mode_storage()
        store = RuntimeReadinessStore(Path(self.temp.name) / "quick-readiness.json")
        store.apply_export_scan(
            checked_at="2026-10-23T10:00:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [{"profile": "default", "ready": True, "fingerprint": "a" * 64}]},
        )
        self.control.runtime_readiness_gate = RuntimeReadinessGate(store)

        def fail_if_probed(_worker):
            raise AssertionError("submit must use the Profile scan snapshot")

        self.dispatcher.capabilities = fail_if_probed
        with self.assertRaises(DomainError) as raised:
            self.control.submit_job(
                self.actor,
                "export",
                {"url": "https://t.me/c/1/3", "quick_mode": True},
            )

        self.assertEqual(raised.exception.code, "RUNTIME_NOT_READY")
        self.assertEqual(self.jobs.list(profile="default", limit=20), [])

        export_job = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/4"}
        )
        self.assertEqual(export_job.payload["url"], "https://t.me/c/1/4")

    def test_storage_upload_uses_saved_readiness_without_live_capability_probe(self):
        self.authorize_quick_mode_storage()
        runtime_store = self.attach_storage_readiness()

        def fail_if_probed(_worker):
            raise AssertionError("Storage submit must use the Profile scan snapshot")

        self.dispatcher.capabilities = fail_if_probed
        job = self.control.submit_job(
            self.actor,
            "storage_upload",
            {"folder_path": "/workspace/biasa", "batch_id": "storage-readiness-batch"},
        )

        self.assertEqual(job.profile, "default")
        self.assertEqual(job.worker, "local")
        self.assertEqual(runtime_store.cell("local", "archive", "storage")["status"], "ready")
        payload = self.dispatcher.commands[-1]["payload"]
        self.assertEqual(payload["_tdl_sender_profile"], "archive")
        self.assertEqual(
            payload["_tdl_sender_session_fingerprints"],
            {"archive": "b" * 64, "default": "a" * 64, "other": "c" * 64},
        )
        self.assertNotIn("tdl_sender_session_fingerprints", str(job.payload))

    def test_storage_upload_dispatches_durable_command_with_every_ready_sender_profile(self):
        self.authorize_quick_mode_storage()
        self.attach_storage_readiness()

        job = self.control.submit_job(
            self.actor,
            "storage_upload",
            {"folder_path": "/workspace/biasa", "batch_id": "storage-parallel"},
        )

        self.assertEqual(job.status, JobStatus.DISPATCHED)
        self.assertEqual(len(self.dispatcher.durable_commands), 1)
        envelope = self.dispatcher.durable_commands[0]
        self.assertEqual(envelope["job"]["kind"], "storage_upload")
        self.assertEqual(
            set(envelope["job"]["payload"]["_tdl_sender_profiles"]),
            {"default", "archive", "other"},
        )
        self.assertNotIn(
            "_storage_durable_dispatch", envelope["job"]["payload"]
        )
        stored_payload = self.jobs.command_payload(job.id)
        dispatch_data = stored_payload["_storage_durable_dispatch"]
        self.assertEqual(envelope["command_id"], dispatch_data["command_id"])
        self.assertEqual(envelope["dispatch_token"], dispatch_data["dispatch_token"])
        self.assertNotIn("_storage_durable_dispatch", self.dispatcher.commands[-1]["payload"])

    def test_storage_upload_rejects_without_storage_cell_before_creating_job(self):
        self.authorize_quick_mode_storage()
        runtime_store = RuntimeReadinessStore(
            Path(self.temp.name) / "storage-no-cell-readiness.json"
        )
        runtime_store.apply_export_scan(
            checked_at="2026-10-23T10:00:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [{"profile": "default", "ready": True, "fingerprint": "a" * 64}]},
        )
        self.control.runtime_readiness_gate = RuntimeReadinessGate(runtime_store)

        def fail_if_probed(_worker):
            raise AssertionError("Storage submit must not check worker capabilities")

        self.dispatcher.capabilities = fail_if_probed
        with self.assertRaises(DomainError) as raised:
            self.control.submit_job(
                self.actor,
                "storage_upload",
                {"folder_path": "/workspace/biasa", "batch_id": "storage-no-cell"},
            )

        self.assertEqual(raised.exception.code, "RUNTIME_NOT_READY")
        self.assertEqual(self.jobs.list(profile="default", limit=20), [])

    def test_storage_upload_rejects_when_saved_access_proof_is_stale(self):
        self.authorize_quick_mode_storage()
        runtime_store = self.attach_storage_readiness(profiles=("default",))
        capabilities = self.dispatcher.capabilities("local")
        fingerprints = capabilities["storage_upload_fingerprints"]
        access_store = self.control.tdl_access_store
        destination_hash = access_store.destination_fingerprint("-100123")
        inventory_hash = access_store.inventory_fingerprint(["default"], fingerprints)
        access_store.replace_results(
            "local",
            "storage",
            destination_hash,
            inventory_hash,
            [{"profile": "default", "ready": False}],
            session_fingerprints={"default": fingerprints["default"]},
        )

        def fail_if_probed(_worker):
            raise AssertionError("Storage submit must not refresh access proof online")

        self.dispatcher.capabilities = fail_if_probed
        with self.assertRaises(DomainError) as raised:
            self.control.submit_job(
                self.actor,
                "storage_upload",
                {"folder_path": "/workspace/biasa", "batch_id": "storage-stale-proof"},
            )

        self.assertEqual(raised.exception.code, "RUNTIME_NOT_READY")
        self.assertEqual(runtime_store.cell("local", "default", "storage")["status"], "not_ready")
        self.assertEqual(self.jobs.list(profile="default", limit=20), [])

    def test_storage_access_failure_invalidates_only_the_sender_profile(self):
        self.authorize_quick_mode_storage()
        runtime_store = self.attach_storage_readiness()
        job = self.control.submit_job(
            self.actor,
            "storage_upload",
            {"folder_path": "/workspace/biasa", "batch_id": "storage-denied-batch"},
        )
        sender_profile = self.dispatcher.commands[-1]["payload"]["_tdl_sender_profile"]
        sequence = max(event.sequence for event in self.jobs.events(job.id)) + 1

        self.control.append_worker_event(JobEvent(
            job_id=job.id,
            sequence=sequence,
            status=JobStatus.FAILED,
            event_type="failed",
            error={"code": "CHAT_WRITE_FORBIDDEN", "message": "write access denied"},
        ))

        self.assertEqual(runtime_store.cell("local", sender_profile, "storage")["status"], "not_ready")
        for profile in {"default", "archive", "other"} - {sender_profile}:
            self.assertEqual(runtime_store.cell("local", profile, "storage")["status"], "ready")
        self.assertEqual(runtime_store.cell("local", sender_profile, "export")["status"], "ready")

    def test_storage_dispatch_failure_marks_worker_offline_without_clearing_profile_cells(self):
        self.authorize_quick_mode_storage()
        runtime_store = self.attach_storage_readiness()

        def fail_dispatch(_worker, _command):
            raise RuntimeError("worker offline")

        self.dispatcher.dispatch = fail_dispatch
        with self.assertRaises(DomainError):
            self.control.submit_job(
                self.actor,
                "storage_upload",
                {"folder_path": "/workspace/biasa", "batch_id": "storage-dispatch-failure"},
            )

        self.assertEqual(runtime_store.worker("local")["status"], "failed")
        self.assertEqual(runtime_store.cell("local", "archive", "storage")["status"], "ready")

    def test_storage_item_session_change_invalidates_the_reported_profile(self):
        self.authorize_quick_mode_storage()
        runtime_store = self.attach_storage_readiness()
        job = self.control.submit_job(
            self.actor,
            "storage_upload",
            {"folder_path": "/workspace/biasa", "batch_id": "storage-session-change"},
        )
        sender_profile = self.dispatcher.commands[-1]["payload"]["_tdl_sender_profile"]
        sequence = max(event.sequence for event in self.jobs.events(job.id)) + 1

        self.control.append_worker_event(JobEvent(
            job_id=job.id,
            sequence=sequence,
            status=JobStatus.FAILED,
            event_type="storage.batch_completed",
            result={"value": {"items": [{
                "profile": sender_profile,
                "status": "failed",
                "error_code": "PROFILE_UPLOAD_SESSION_CHANGED",
            }]}},
            error={"code": "STORAGE_UPLOAD_FAILED", "message": "All files failed."},
        ))

        self.assertEqual(runtime_store.cell("local", sender_profile, "storage")["status"], "not_ready")
        for profile in {"default", "archive", "other"} - {sender_profile}:
            self.assertEqual(runtime_store.cell("local", profile, "storage")["status"], "ready")

    def test_quick_mode_profile_denied_invalidates_quick_cell_and_storage_proof_on_running_event(self):
        self.authorize_quick_mode_storage()
        job = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/8", "quick_mode": True},
        )
        store = RuntimeReadinessStore(Path(self.temp.name) / "quick-denial-readiness.json")
        store.apply_export_scan(
            checked_at="2026-10-23T10:00:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [
                {"profile": "default", "ready": True, "fingerprint": "a" * 64},
                {"profile": "archive", "ready": True, "fingerprint": "b" * 64},
            ]},
        )
        store.apply_quickmode_scan(
            checked_at="2026-10-23T10:05:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [
                {
                    "profile": "default", "ready": True, "fingerprint": "1" * 64,
                    "session_fingerprint": "a" * 64,
                    "destination_fingerprint": "2" * 64,
                    "rclone_destination_fingerprint": "3" * 64,
                    "sender_profiles": ["default", "archive", "other"],
                    "sender_session_fingerprints": {"default": "a" * 64, "archive": "b" * 64, "other": "c" * 64},
                },
                {
                    "profile": "archive", "ready": True, "fingerprint": "4" * 64,
                    "session_fingerprint": "b" * 64,
                    "destination_fingerprint": "2" * 64,
                    "rclone_destination_fingerprint": "3" * 64,
                    "sender_profiles": ["default", "archive", "other"],
                    "sender_session_fingerprints": {"default": "a" * 64, "archive": "b" * 64, "other": "c" * 64},
                },
                {
                    "profile": "other", "ready": True, "fingerprint": "5" * 64,
                    "session_fingerprint": "c" * 64,
                    "destination_fingerprint": "2" * 64,
                    "rclone_destination_fingerprint": "3" * 64,
                    "sender_profiles": ["archive", "other"],
                    "sender_session_fingerprints": {"archive": "b" * 64, "other": "c" * 64},
                },
            ]},
        )
        store.apply_storage_scan(
            checked_at="2026-10-23T10:05:00Z",
            profiles={"local": [
                {
                    "profile": profile, "ready": True,
                    "fingerprint": str(index) * 64,
                    "session_fingerprint": session,
                    "destination_fingerprint": "2" * 64,
                }
                for index, (profile, session) in enumerate((
                    ("default", "a" * 64),
                    ("archive", "b" * 64),
                    ("other", "c" * 64),
                ), start=1)
            ]},
        )
        self.control.runtime_readiness_gate = RuntimeReadinessGate(store)

        self.control.append_worker_event(JobEvent(
            job_id=job.id,
            sequence=max((item.sequence for item in self.jobs.events(job.id)), default=0) + 1,
            status=JobStatus.RUNNING,
            event_type="tdl_access.profile_denied",
            result={"profile": "default", "error_code": "CHAT_WRITE_FORBIDDEN"},
        ))

        self.assertEqual(store.cell("local", "default", "quick_mode")["status"], "not_ready")
        self.assertEqual(store.cell("local", "archive", "quick_mode")["status"], "not_ready")
        self.assertEqual(store.cell("local", "other", "quick_mode")["status"], "ready")
        self.assertEqual(store.cell("local", "default", "storage")["status"], "not_ready")
        self.assertEqual(store.cell("local", "archive", "storage")["status"], "ready")
        self.assertEqual(store.cell("local", "default", "export")["status"], "ready")
        status = self.control.tdl_access_verification_status("local", "storage")
        self.assertNotIn("default", status["verified_profiles"])
        self.assertIn("archive", status["verified_profiles"])

    def test_quick_mode_terminal_runtime_failure_is_scoped_and_input_cancel_keep_cell(self):
        store = RuntimeReadinessStore(Path(self.temp.name) / "quick-terminal-readiness.json")
        store.apply_export_scan(
            checked_at="2026-10-23T10:00:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [
                {"profile": "default", "ready": True, "fingerprint": "a" * 64},
                {"profile": "archive", "ready": True, "fingerprint": "b" * 64},
            ]},
        )
        quick_cells = [{
            "profile": profile,
            "ready": True,
            "fingerprint": fingerprint,
            "session_fingerprint": session,
            "destination_fingerprint": "c" * 64,
            "rclone_destination_fingerprint": "d" * 64,
            "sender_profiles": [profile],
            "sender_session_fingerprints": {profile: session},
        } for profile, fingerprint, session in (
            ("default", "1" * 64, "a" * 64),
            ("archive", "2" * 64, "b" * 64),
        )]
        store.apply_quickmode_scan(
            checked_at="2026-10-23T10:05:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": quick_cells},
        )
        self.control.runtime_readiness_gate = RuntimeReadinessGate(store)
        job = Job(
            id="quick-terminal-failure",
            kind="export",
            profile="default",
            actor_user_id=42,
            worker="local",
            status=JobStatus.DISPATCHED,
            payload={"quick_mode": True},
        )
        self.jobs.create(job)

        self.control._invalidate_runtime_readiness_from_event(JobEvent(
            job_id=job.id,
            sequence=1,
            status=JobStatus.FAILED,
            event_type="failed",
            error={
                "code": "WORKER_JOB_FAILED",
                "message": "UTILITY_PROCESS_STALLED: compression stopped",
            },
        ))
        self.assertEqual(store.cell("local", "default", "quick_mode")["status"], "not_ready")
        self.assertEqual(store.cell("local", "archive", "quick_mode")["status"], "ready")
        self.assertEqual(store.cell("local", "default", "export")["status"], "ready")

        store.apply_quickmode_scan(
            checked_at="2026-10-23T11:00:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": quick_cells},
        )
        self.control._invalidate_runtime_readiness_from_event(JobEvent(
            job_id=job.id,
            sequence=2,
            status=JobStatus.FAILED,
            event_type="failed",
            error={
                "code": "WORKER_JOB_FAILED",
                "message": "INVALID_EXPORT_INPUT: file manifest is missing",
            },
        ))
        self.control._invalidate_runtime_readiness_from_event(JobEvent(
            job_id=job.id,
            sequence=3,
            status=JobStatus.CANCELLED,
            event_type="cancelled",
            error={"code": "JOB_TERMINATED", "message": "cancelled by user"},
        ))
        self.assertEqual(store.cell("local", "default", "quick_mode")["status"], "ready")

    def configure_tdl_access(self, control, dispatcher, registry, purposes=("tts", "storage")):
        store = SqliteTdlAccessStore(Path(self.temp.name) / f"tdl-access-{id(control)}.db")
        control.tdl_access_store = store
        control.tdl_access_target_resolver = lambda _purpose: "123456789"
        control.runtime_settings_store = FakeJobSecretStore()
        tts_cells = {}
        worker_rows = []
        for worker in registry.names():
            response = dispatcher.capabilities(worker)
            worker_rows.append({"worker": worker, "status": "success"})
            for purpose in purposes:
                if purpose == "storage":
                    profiles = response.get("available_storage_profiles") or []
                    fingerprints = response.get("storage_upload_fingerprints") or {}
                else:
                    profiles = response.get("export_profiles") or response.get("profiles") or []
                    fingerprints = {
                        profile: f"{(ord(profile[0]) % 16):x}" * 64
                        for profile in profiles if purpose == "tts"
                    }
                destination_hash = store.destination_fingerprint("123456789")
                inventory_hash = store.inventory_fingerprint(
                    profiles,
                    fingerprints if purpose == "storage" else None,
                )
                store.replace_results(
                    worker,
                    purpose,
                    destination_hash,
                    inventory_hash,
                    [{"profile": profile, "ready": True} for profile in profiles],
                    session_fingerprints=fingerprints,
                )
                if purpose == "tts":
                    tts_cells[worker] = [
                        {
                            "profile": profile,
                            "ready": bool(response.get("tts")),
                            "reason_code": "TTS_HELPER_UNAVAILABLE",
                            "fingerprint": "c" * 64,
                            "session_fingerprint": fingerprints[profile],
                            "destination_fingerprint": destination_hash,
                        }
                        for profile in profiles
                    ]
        if "tts" in purposes:
            readiness = RuntimeReadinessStore(
                Path(self.temp.name) / f"runtime-readiness-{id(control)}.json"
            )
            readiness.apply_export_scan(
                checked_at="2026-10-23T00:00:00Z",
                workers=worker_rows,
                profiles={
                    worker: [
                        {
                            "profile": cell["profile"],
                            "ready": True,
                            "fingerprint": cell["session_fingerprint"],
                        }
                        for cell in cells
                    ]
                    for worker, cells in tts_cells.items()
                },
            )
            readiness.apply_tts_scan(
                checked_at="2026-10-23T00:00:00Z",
                profiles=tts_cells,
            )
            control.runtime_readiness_gate = RuntimeReadinessGate(readiness)
        return store

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

    def test_backup_verification_payload_is_bound_to_selected_worker_and_run(self):
        control = object.__new__(ControlPlane)
        control.storage_catalog = FakeBackupCatalog()
        payload = control._prepare_durable_payload(
            self.actor, "backup_verify", {"run_id": "run-abc"}, "default", "remote-2"
        )

        self.assertEqual(payload["node_name"], "remote-2")
        self.assertEqual(payload["profile"], "default")
        self.assertEqual(payload["channel_ref"], "123456")
        self.assertEqual(payload["parts"], [])
        public = control._redacted_payload("backup_verify", payload)
        self.assertEqual(public, {
            "run_id": "run-abc",
            "node_name": "remote-2",
            "part_discovery": "tdl_channel_caption_scan",
        })

    def test_backup_verification_can_recover_part_ids_from_channel_when_catalog_metadata_is_incomplete(self):
        control = object.__new__(ControlPlane)
        control.storage_catalog = FakeBackupCatalog()
        control.storage_catalog.backup_parts = lambda run_id, node_name: [{
            "part_name": "backup-remote-2-2026-10-11T072127+0000.7z.001",
            "channel_id": -100123456,
            "channel_message_id": None,
            "file_size": None,
            "sha256": "",
            "status": "metadata_missing",
        }]

        payload = control._prepare_durable_payload(
            self.actor, "backup_verify", {"run_id": "run-abc"}, "default", "remote-2"
        )

        self.assertEqual(payload["channel_ref"], "123456")
        self.assertEqual(payload["parts"], [])

    def test_backup_verification_can_use_configured_channel_without_catalog_part_rows(self):
        class RuntimeSettings:
            def get_values(self, scope, *, include_secrets=False):
                del include_secrets
                return {"backup_channel": "123456"} if scope == "backend" else {}

        control = object.__new__(ControlPlane)
        control.storage_catalog = FakeBackupCatalog()
        control.storage_catalog.backup_parts = lambda _run_id, _node_name: []
        control.runtime_settings_store = RuntimeSettings()

        payload = control._prepare_durable_payload(
            self.actor, "backup_verify", {"run_id": "run-abc"}, "default", "remote-2"
        )

        self.assertEqual(payload["channel_ref"], "123456")
        self.assertEqual(payload["parts"], [])

    def test_backup_verification_rejects_incomplete_run(self):
        control = object.__new__(ControlPlane)
        control.storage_catalog = FakeBackupCatalog(run_status="running")
        with self.assertRaises(DomainError) as raised:
            control._prepare_durable_payload(
                self.actor, "backup_verify", {"run_id": "run-abc"}, "default", "remote-2"
            )
        self.assertEqual(raised.exception.code, "BACKUP_RUN_NOT_COMPLETE")

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

    def test_tts_routes_to_least_loaded_capable_worker_and_round_robins_ties(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "tts-workers.json",
            {
                "tts-ready": "http://worker-a",
                "remote": "http://worker-b",
                "tts-off": "http://worker-c",
            },
            {"tts-ready": "a", "remote": "b", "tts-off": "c"},
        )
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda worker: {
            "tts": worker in {"tts-ready", "remote"},
            "capabilities": ["tts"] if worker in {"tts-ready", "remote"} else [],
            "tts_profiles": ["default", "archive"] if worker in {"tts-ready", "remote"} else [],
            "export_profiles": ["default", "archive"] if worker in {"tts-ready", "remote"} else [],
            "tts_health": {
                "helpers_ready": worker in {"tts-ready", "remote"},
                "helpers": [
                    {"slot": slot, "status": "ready" if worker in {"tts-ready", "remote"} else "helper_unreachable"}
                    for slot in range(1, 4)
                ],
            },
        }
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        self.configure_tdl_access(control, dispatcher, registry)
        dispatcher.capabilities = lambda _worker: self.fail(
            "TTS submission must use the stored readiness snapshot"
        )

        jobs = [
            control.submit_job(self.actor, "tts", {"title": "A", "text": "private text"}),
            control.submit_job(self.actor, "tts", {"title": "B", "text": "private text"}),
            control.submit_job(self.actor, "tts", {"title": "C", "text": "private text"}),
        ]

        self.assertEqual([job.worker for job in jobs], ["remote", "tts-ready", "remote"])
        self.assertTrue(all(job.kind == "tts" for job in jobs))
        self.assertNotIn("text", jobs[0].payload)
        internal = self.jobs.command_payload(jobs[0].id)
        self.assertEqual(internal["title"], "A")
        self.assertEqual(internal["text"], "private text")
        self.assertIn(internal["_tdl_sender_profile"], {"default", "archive"})
        self.assertNotIn("tdl_access_target", internal)

    def test_tts_worker_lane_admits_one_job_and_queues_another(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "single-tts-worker.json",
            {"tts-ready": "http://worker-a"},
            {"tts-ready": "a"},
        )
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda worker: {
            "tts": True,
            "capabilities": ["tts"],
            "tts_profiles": ["default", "archive"],
            "export_profiles": ["default", "archive"],
            "tts_health": {
                "helpers_ready": True,
                "helpers": [{"slot": slot, "status": "ready"} for slot in range(1, 4)],
            },
        }
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        self.configure_tdl_access(control, dispatcher, registry)

        first = control.submit_job(self.actor, "tts", {"title": "A", "text": "one"})
        second = control.submit_job(self.actor, "tts", {"title": "B", "text": "two"}, profile="archive")

        self.assertEqual(first.status, JobStatus.DISPATCHED)
        self.assertEqual(second.status, JobStatus.QUEUED)
        self.assertEqual(first.worker, second.worker)
        self.assertEqual(len(dispatcher.commands), 1)

    def test_tts_rejects_workers_without_capability(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "no-tts-worker.json",
            {"local": "http://worker"},
            {"local": "a"},
        )
        control = ControlPlane(self.jobs, FakeDispatcher(), self.profiles, worker_registry=registry)
        control.tdl_access_target_resolver = lambda _purpose: "123456789"
        with self.assertRaises(DomainError) as error:
            control.submit_job(self.actor, "tts", {"title": "A", "text": "private text"})
        self.assertEqual(error.exception.code, "TTS_WORKER_UNAVAILABLE")
        self.assertEqual(self.jobs.count(kind="tts"), 0)

    def test_tts_rejects_snapshot_for_a_different_destination_before_job_creation(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "stale-tts-destination.json",
            {"local": "http://worker"},
            {"local": "token"},
        )
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda _worker: {
            "tts": True,
            "export_profiles": ["default"],
            "profiles": ["default"],
        }
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        self.configure_tdl_access(control, dispatcher, registry)
        control.tdl_access_target_resolver = lambda _purpose: "987654321"

        with self.assertRaises(DomainError) as error:
            control.submit_job(self.actor, "tts", {"title": "A", "text": "private text"})

        self.assertEqual(error.exception.code, "TTS_WORKER_UNAVAILABLE")
        self.assertEqual(self.jobs.count(kind="tts"), 0)

    def test_tts_snapshot_fails_closed_when_export_session_cell_is_stale(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "stale-tts-session.json",
            {"local": "http://worker"},
            {"local": "token"},
        )
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda _worker: {
            "tts": True,
            "export_profiles": ["default"],
            "profiles": ["default"],
        }
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        self.configure_tdl_access(control, dispatcher, registry)
        control.runtime_readiness_gate.store.invalidate(
            worker="local",
            profile="default",
            runtime="export",
            reason_code="PROFILE_SESSION_CHANGED",
        )

        with self.assertRaises(DomainError) as error:
            control.submit_job(self.actor, "tts", {"title": "A", "text": "private text"})

        self.assertEqual(error.exception.code, "TTS_WORKER_UNAVAILABLE")
        self.assertEqual(self.jobs.count(kind="tts"), 0)

    def test_tts_failure_invalidates_execution_sender_cell_not_owner_cell(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "tts-execution-profile.json",
            {"local": "http://worker"},
            {"local": "token"},
        )
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda _worker: {
            "tts": True,
            "export_profiles": ["default", "archive"],
            "profiles": ["default", "archive"],
        }
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        self.configure_tdl_access(control, dispatcher, registry)
        control._tts_sender_round_robin["local"] = 0
        job = control.submit_job(
            self.actor, "tts", {"title": "A", "text": "private text"}
        )
        stored = self.jobs.command_payload(job.id)
        self.assertEqual(job.profile, "default")
        self.assertEqual(stored["_tdl_sender_profile"], "archive")

        control._invalidate_runtime_readiness_from_event(JobEvent(
            job_id=job.id,
            sequence=1,
            status=JobStatus.FAILED,
            event_type="failed",
            error={
                "code": "WORKER_JOB_FAILED",
                "message": "TTS_HELPER_UNAVAILABLE: helper stopped",
            },
        ))

        store = control.runtime_readiness_gate.store
        self.assertEqual(store.cell("local", "archive", "tts")["status"], "not_ready")
        self.assertEqual(store.cell("local", "default", "tts")["status"], "ready")

    def test_explicit_false_tts_capability_is_not_overridden_by_a_stale_capability_list(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "stale-tts-capability.json",
            {"local": "http://worker"},
            {"local": "token"},
        )
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda _worker: {
            "tts": False,
            "capabilities": ["tts"],
            "tts_profiles": ["default"],
            "export_profiles": ["default"],
            "tts_health": {
                "helpers_ready": True,
                "helpers": [{"slot": slot, "status": "ready"} for slot in range(1, 4)],
            },
        }
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        control.tdl_access_target_resolver = lambda _purpose: "123456789"

        status = control.tts_worker_diagnostics(profile="default")

        self.assertFalse(status[0]["ready"])
        self.assertFalse(status[0]["capability_ready"])
        self.assertEqual(status[0]["reason_code"], "tts_capability_missing")

    def test_safelink_durable_job_auto_routes_and_keeps_input_private(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "resolver-addon-workers.json",
            {
                "worker-a": "http://worker-a",
                "worker-b": "http://worker-b",
                "worker-c": "http://worker-c",
            },
            {"worker-a": "a", "worker-b": "b", "worker-c": "c"},
        )
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda _worker: self.fail(
            "Resolver job admission must not probe live capabilities"
        )
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        self.attach_resolver_readiness(control, {
            "worker-a": {"ready": True, "fingerprint": "a" * 64},
            "worker-b": {"ready": True, "fingerprint": "b" * 64},
            "worker-c": {"ready": False, "reason_code": "RESOLVER_RUNTIME_UNAVAILABLE"},
        })

        prepared = control.prepare_durable_job(
            self.actor,
            {},
            {
                "job_kind": "safelink_resolve",
                "payload": {"url": "https://pndk.to/private-token"},
            },
        )

        self.assertEqual(prepared.job.worker, "worker-a")
        self.assertEqual(prepared.job.payload, {"submitted": True})
        self.assertEqual(
            prepared.command_payload["payload"],
            {"url": "https://pndk.to/private-token"},
        )
        self.assertIn(
            "worker:worker-a:kind:safelink_resolve",
            prepared.execution_plan["resource_keys"],
        )

        manual = control.prepare_durable_job(
            self.actor,
            {"worker": "worker-b"},
            {
                "job_kind": "safelink_resolve",
                "payload": {"url": "https://pndk.to/another"},
            },
        )
        self.assertEqual(manual.job.worker, "worker-b")

    def test_safelink_router_uses_queue_depth_and_deterministic_ties(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "resolver-addon-load-workers.json",
            {"worker-a": "http://worker-a", "worker-b": "http://worker-b", "offline": "http://worker-c"},
            {"worker-a": "a", "worker-b": "b", "offline": "c"},
        )
        dispatcher = FakeDispatcher()
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        self.attach_resolver_readiness(control, {
            "worker-a": {"ready": True, "fingerprint": "a" * 64},
            "worker-b": {"ready": True, "fingerprint": "b" * 64},
            "offline": {"ready": False, "reason_code": "RESOLVER_RUNTIME_UNAVAILABLE"},
        })

        self.assertEqual(control._select_safelink_worker(), "worker-a")
        self.assertEqual(control._select_safelink_worker(), "worker-a")
        self.jobs.create(
            Job(
                id="worker-a-queued",
                kind="safelink_resolve",
                profile="default",
                actor_user_id=42,
                worker="worker-a",
                status=JobStatus.QUEUED,
                payload={"submitted": True},
            )
        )
        self.assertEqual(control._select_safelink_worker(), "worker-b")
        registry.set_enabled("worker-b", False)
        self.assertEqual(control._select_safelink_worker(), "worker-a")

    def test_safelink_manual_selection_rejects_disabled_or_unready_worker(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "resolver-manual-workers.json",
            {"ready": "http://ready", "not-ready": "http://not-ready", "disabled": "http://disabled"},
            {"ready": "a", "not-ready": "b", "disabled": "c"},
        )
        registry.set_enabled("disabled", False)
        control = ControlPlane(
            self.jobs, FakeDispatcher(), self.profiles, worker_registry=registry
        )
        self.attach_resolver_readiness(control, {
            "ready": {"ready": True, "fingerprint": "a" * 64},
            "not-ready": {"ready": False, "reason_code": "RESOLVER_RUNTIME_UNAVAILABLE"},
            "disabled": {"ready": True, "fingerprint": "c" * 64},
        })

        for worker, expected in (("not-ready", "RUNTIME_NOT_READY"), ("disabled", "WORKER_DISABLED")):
            with self.subTest(worker=worker), self.assertRaises(DomainError) as raised:
                control.prepare_durable_job(
                    self.actor,
                    {"worker": worker},
                    {"job_kind": "safelink_resolve", "payload": {"url": "https://pndk.to/code"}},
                )
            self.assertEqual(raised.exception.code, expected)

    def test_safelink_runtime_failure_invalidates_only_its_worker_cell(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "resolver-failure-workers.json",
            {"ready": "http://ready"},
            {"ready": "a"},
        )
        control = ControlPlane(
            self.jobs, FakeDispatcher(), self.profiles, worker_registry=registry
        )
        store = self.attach_resolver_readiness(control, {
            "ready": {"ready": True, "fingerprint": "a" * 64},
        })
        store.apply_export_scan(
            checked_at="2026-10-23T10:01:00Z",
            workers=[{"worker": "ready", "status": "success"}],
            profiles={"ready": [{
                "profile": "default", "ready": True, "fingerprint": "b" * 64,
            }]},
        )
        job = Job(
            id="resolver-runtime-failure",
            kind="safelink_resolve",
            profile="default",
            actor_user_id=42,
            worker="ready",
            status=JobStatus.FAILED,
            payload={"submitted": True},
        )
        self.jobs.create(job)

        control._invalidate_runtime_readiness_from_event(JobEvent(
            job_id=job.id,
            sequence=1,
            status=JobStatus.FAILED,
            event_type="failed",
            error={"code": "RESOLVER_RUNTIME_UNAVAILABLE", "message": "Addon tidak dapat dihubungi."},
        ))

        self.assertEqual(store.cell("ready", None, "resolver")["status"], "not_ready")
        self.assertEqual(store.cell("ready", "default", "export")["status"], "ready")

        store.upsert_cell(
            worker="ready", profile=None, runtime="resolver", ready=True,
            fingerprint="c" * 64,
        )
        control._invalidate_runtime_readiness_from_event(JobEvent(
            job_id=job.id,
            sequence=2,
            status=JobStatus.FAILED,
            event_type="failed",
            error={"code": "RESOLVER_FAILED", "message": "Shortlink tidak dapat diproses."},
        ))
        self.assertEqual(store.cell("ready", None, "resolver")["status"], "ready")

    def test_safelink_submit_rejects_untrusted_domains_and_missing_workers(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "no-resolver-workers.json",
            {"ordinary": "http://worker"},
            {"ordinary": "token"},
        )
        control = ControlPlane(self.jobs, FakeDispatcher(), self.profiles, worker_registry=registry)
        with self.assertRaises(DomainError) as unavailable:
            control.prepare_durable_job(
                self.actor,
                {},
                {"job_kind": "safelink_resolve", "payload": {"url": "https://pndk.to/code"}},
            )
        self.assertEqual(unavailable.exception.code, "SAFELINK_WORKER_UNAVAILABLE")

        self.attach_resolver_readiness(control, {
            "ordinary": {"ready": True, "fingerprint": "a" * 64},
        })
        with self.assertRaises(DomainError) as invalid:
            control.prepare_durable_job(
                self.actor,
                {},
                {"job_kind": "safelink_resolve", "payload": {"url": "https://example.com/code"}},
            )
        self.assertEqual(invalid.exception.code, "SAFELINK_URL_INVALID")

    def test_tts_routes_only_to_worker_with_active_profile_tdl_session(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "tts-profile-workers.json",
            {"tts-default": "http://worker-a", "tts-archive": "http://worker-b"},
            {"tts-default": "a", "tts-archive": "b"},
        )
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda worker: {
            "tts": True,
            "capabilities": ["tts"],
            "tts_profiles": ["default"] if worker == "tts-default" else ["archive"],
            "export_profiles": ["default"] if worker == "tts-default" else ["archive"],
            "tts_health": {
                "ready": True,
                "helpers_ready": True,
                "helpers": [
                    {"slot": slot, "status": "ready", "bootstrap_percent": 100}
                    for slot in range(1, 4)
                ],
            },
        }
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        self.configure_tdl_access(control, dispatcher, registry)

        job = control.submit_job(
            self.actor,
            "tts",
            {"title": "Bab", "text": "Isi"},
            profile="archive",
        )

        self.assertEqual(job.worker, "tts-archive")
        self.assertEqual(job.profile, "default")
        self.assertEqual(dispatcher.commands[-1]["profile"], "archive")

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

    def test_utility_does_not_wait_for_unrelated_profile_sync(self):
        self.control.profile_readiness = lambda _profile, _worker: False
        job = self.control.submit_job(
            self.actor,
            "utility",
            {"utility": "compress", "folders": ["/workspace/biasa"]},
        )
        self.assertEqual(job.status, JobStatus.DISPATCHED)

    def test_utility_runtime_failure_invalidates_only_utility_cell(self):
        store = RuntimeReadinessStore(Path(self.temp.name) / "runtime-readiness.json")
        store.apply_export_scan(
            checked_at="2026-10-23T10:00:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [{
                "profile": "default", "ready": True, "fingerprint": "a" * 64,
            }]},
        )
        store.upsert_cell(
            worker="local", profile=None, runtime="utility", ready=True,
            fingerprint="b" * 64,
        )
        control = ControlPlane(
            self.jobs,
            self.dispatcher,
            self.profiles,
            runtime_readiness_gate=RuntimeReadinessGate(store),
        )
        job = Job(
            id="utility-runtime-failure",
            kind="utility",
            profile="default",
            actor_user_id=42,
            worker="local",
            status=JobStatus.FAILED,
            payload={"utility": "compress", "folders": ["/workspace/folder"]},
        )
        self.jobs.create(job)

        control._invalidate_runtime_readiness_from_event(JobEvent(
            job_id=job.id,
            sequence=1,
            status=JobStatus.FAILED,
            event_type="failed",
            error={
                "code": "WORKER_JOB_FAILED",
                "message": "UTILITY_PATH_INVALID: folder outside workspace",
            },
        ))
        self.assertEqual(store.cell("local", None, "utility")["status"], "ready")

        control._invalidate_runtime_readiness_from_event(JobEvent(
            job_id=job.id,
            sequence=2,
            status=JobStatus.FAILED,
            event_type="failed",
            error={
                "code": "WORKER_JOB_FAILED",
                "message": "UTILITY_RUNTIME_UNAVAILABLE: cannot start process",
            },
        ))
        self.assertEqual(store.cell("local", None, "utility")["status"], "not_ready")
        self.assertEqual(store.cell("local", "default", "export")["status"], "ready")

    def test_storage_uses_verified_sender_profile_but_keeps_actor_as_job_owner(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "storage-sender-workers.json",
            {"local": "http://worker-local"},
            {"local": "worker-token"},
        )
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda _worker: {
            "profiles": ["default"],
            "export_profiles": ["default"],
            "available_storage_profiles": ["default", "archive"],
            "storage_upload_fingerprints": {"default": "a" * 64, "archive": "b" * 64},
        }
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        store = SqliteTdlAccessStore(Path(self.temp.name) / "storage-sender.db")
        control.tdl_access_store = store
        control.tdl_access_target_resolver = lambda purpose: "-100123" if purpose == "storage" else ""
        control.runtime_settings_store = FakeJobSecretStore()
        destination_hash = store.destination_fingerprint("-100123")
        fingerprints = {"default": "a" * 64, "archive": "b" * 64}
        inventory_hash = store.inventory_fingerprint(["default", "archive"], fingerprints)
        store.replace_results(
            "local", "storage", destination_hash, inventory_hash,
            [{"profile": "archive", "ready": True}],
            session_fingerprints=fingerprints,
        )

        job = control.submit_job(
            self.actor,
            "storage_upload",
            {"folder_path": "/workspace/source"},
            worker="local",
        )
        command = dispatcher.commands[0]
        self.assertEqual(job.profile, "default")
        self.assertEqual(command["profile"], "archive")
        self.assertEqual(command["payload"]["tdl_access_target"], "-100123")
        self.assertEqual(
            command["payload"]["_tdl_sender_session_fingerprints"],
            {"archive": fingerprints["archive"]},
        )
        self.assertNotIn("_tdl_sender_session_fingerprints", job.payload)
        self.assertEqual(job.payload["sender_profile"], "archive")

    def test_storage_submit_is_safe_when_scheduler_scans_during_job_creation(self):
        self.authorize_quick_mode_storage()
        create = self.jobs.create_with_private_values

        def create_and_scan_scheduler(job, private_values, **kwargs):
            created = create(job, private_values, **kwargs)
            self.control._dispatch_pending_jobs()
            return created

        self.jobs.create_with_private_values = create_and_scan_scheduler

        job = self.control.submit_job(
            self.actor,
            "storage_upload",
            {"folder_path": "/workspace/source"},
            worker="local",
        )

        self.assertEqual(job.status, JobStatus.DISPATCHED)
        self.assertEqual(len(self.dispatcher.commands), 1)
        self.assertEqual(
            self.dispatcher.commands[0]["payload"]["tdl_access_target"], "-100123"
        )
        self.assertEqual(
            self.dispatcher.commands[0]["payload"]["_tdl_sender_session_fingerprints"],
            {"default": "a" * 64, "archive": "b" * 64, "other": "c" * 64},
        )

    def test_scheduler_does_not_claim_job_already_admitted_by_submitter(self):
        self.authorize_quick_mode_storage()
        dispatch = self.control._dispatch_admitted_job

        def scan_after_submitter_claim(job, command):
            self.control._dispatch_pending_jobs()
            dispatch(job, command)

        self.control._dispatch_admitted_job = scan_after_submitter_claim

        job = self.control.submit_job(
            self.actor,
            "storage_upload",
            {"folder_path": "/workspace/source"},
            worker="local",
        )

        self.assertEqual(job.status, JobStatus.DISPATCHED)
        self.assertEqual(len(self.dispatcher.commands), 1)

    def test_storage_retry_submits_only_confirmed_not_sent_files(self):
        fingerprints = {"default": "a" * 64, "archive": "b" * 64}
        self.dispatcher.capabilities = lambda _worker: {
            "profiles": ["default", "archive"],
            "export_profiles": ["default", "archive"],
            "available_storage_profiles": ["default", "archive"],
            "storage_upload_fingerprints": fingerprints,
        }
        store = SqliteTdlAccessStore(Path(self.temp.name) / "storage-retry.db")
        self.control.tdl_access_store = store
        self.control.tdl_access_target_resolver = lambda _purpose: "-100123"
        self.control.runtime_settings_store = FakeJobSecretStore()
        inventory_hash = store.inventory_fingerprint(list(fingerprints), fingerprints)
        store.replace_results(
            "local",
            "storage",
            store.destination_fingerprint("-100123"),
            inventory_hash,
            [{"profile": profile, "ready": True} for profile in fingerprints],
            session_fingerprints=fingerprints,
        )
        original = self.control.submit_job(
            self.actor,
            "storage_upload",
            {"folder_path": "/workspace/source"},
            worker="local",
        )
        self.control.append_worker_event(
            JobEvent(
                job_id=original.id,
                sequence=2,
                status=JobStatus.FAILED,
                event_type="storage.batch_completed",
                result={
                    "value": {
                        "outcome": "partial_failure",
                        "items": [
                            {
                                "path": "subdir/safe.txt",
                                "status": "failed",
                                "retryable": True,
                                "attempt": 1,
                            },
                            {
                                "path": "ambiguous.txt",
                                "status": "needs_reconciliation",
                                "retryable": False,
                                "attempt": 1,
                            },
                            {
                                "path": "../outside.txt",
                                "status": "failed",
                                "retryable": True,
                                "attempt": 1,
                            },
                        ],
                    }
                },
            )
        )

        retry = self.control.retry_job(self.actor, original.id)

        self.assertNotEqual(retry.id, original.id)
        self.assertEqual(retry.worker, original.worker)
        retry_payload = self.dispatcher.commands[-1]["payload"]
        self.assertEqual(retry_payload["_storage_retry_paths"], ["subdir/safe.txt"])
        self.assertEqual(retry_payload["_storage_file_attempts"], {"subdir/safe.txt": 1})
        self.assertNotIn("ambiguous.txt", retry_payload["_storage_retry_paths"])
        self.assertEqual(self.jobs.get(original.id).status, JobStatus.FAILED)

    def test_storage_rejects_profiles_without_a_fingerprinted_upload_lane_before_job_creation(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "storage-unfingerprinted-workers.json",
            {"local": "http://worker-local"},
            {"local": "worker-token"},
        )
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda _worker: {
            "profiles": ["default"],
            "export_profiles": ["default"],
            "available_storage_profiles": ["default"],
        }
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        store = SqliteTdlAccessStore(Path(self.temp.name) / "storage-unfingerprinted.db")
        control.tdl_access_store = store
        control.tdl_access_target_resolver = lambda _purpose: "-100123"
        control.runtime_settings_store = FakeJobSecretStore()

        with self.assertRaises(DomainError) as error:
            control.submit_job(
                self.actor,
                "storage_upload",
                {"folder_path": "/workspace/source"},
                worker="local",
            )

        self.assertEqual(error.exception.code, "TDL_ACCESS_NOT_VERIFIED")
        self.assertEqual(self.jobs.count(kind="storage_upload"), 0)
        self.assertEqual(dispatcher.commands, [])

    def test_storage_permission_denial_revokes_only_the_rejected_profile_proof(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "storage-denial-workers.json",
            {"local": "http://worker-local"},
            {"local": "worker-token"},
        )
        fingerprints = {"default": "a" * 64, "archive": "b" * 64}
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda _worker: {
            "profiles": ["default"],
            "export_profiles": ["default"],
            "available_storage_profiles": ["default", "archive"],
            "storage_upload_fingerprints": fingerprints,
        }
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        store = SqliteTdlAccessStore(Path(self.temp.name) / "storage-denial.db")
        control.tdl_access_store = store
        control.tdl_access_target_resolver = lambda _purpose: "-100123"
        control.runtime_settings_store = FakeJobSecretStore()
        destination = store.destination_fingerprint("-100123")
        inventory = store.inventory_fingerprint(list(fingerprints), fingerprints)
        store.replace_results(
            "local",
            "storage",
            destination,
            inventory,
            [
                {"profile": "default", "ready": True},
                {"profile": "archive", "ready": True},
            ],
            session_fingerprints=fingerprints,
        )
        job = control.submit_job(
            self.actor,
            "storage_upload",
            {"folder_path": "/workspace/source"},
            worker="local",
        )

        control.append_worker_event(
            JobEvent(
                job_id=job.id,
                sequence=2,
                status=JobStatus.RUNNING,
                event_type="tdl_access.profile_denied",
                result={"profile": "default", "error_code": "CHAT_WRITE_FORBIDDEN"},
            )
        )

        status = control.tdl_access_verification_status("local", "storage")
        self.assertEqual(status["verified_profiles"], ["archive"])

    def test_storage_rejects_profiles_without_a_fingerprinted_upload_lane_before_job_creation(self):
        registry = WorkerRegistry(
            Path(self.temp.name) / "storage-unfingerprinted-workers.json",
            {"local": "http://worker-local"},
            {"local": "worker-token"},
        )
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda _worker: {
            "profiles": ["default"],
            "export_profiles": ["default"],
            "available_storage_profiles": ["default"],
        }
        control = ControlPlane(self.jobs, dispatcher, self.profiles, worker_registry=registry)
        store = SqliteTdlAccessStore(Path(self.temp.name) / "storage-unfingerprinted.db")
        control.tdl_access_store = store
        control.tdl_access_target_resolver = lambda _purpose: "-100123"
        control.runtime_settings_store = FakeJobSecretStore()

        with self.assertRaises(DomainError) as error:
            control.submit_job(
                self.actor,
                "storage_upload",
                {"folder_path": "/workspace/source"},
                worker="local",
            )

        self.assertEqual(error.exception.code, "TDL_ACCESS_NOT_VERIFIED")
        self.assertEqual(self.jobs.count(kind="storage_upload"), 0)
        self.assertEqual(dispatcher.commands, [])

    def test_quick_mode_other_profile_can_fill_worker_slot_behind_blocked_profile_queue(self):
        self.authorize_quick_mode_storage()
        first = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/20", "quick_mode": True},
            profile="default",
        )
        same_profile = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/21", "quick_mode": True},
            profile="default",
        )
        other_profile = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/22", "quick_mode": True},
            profile="archive",
        )

        self.assertEqual(first.status.value, "dispatched")
        self.assertEqual(same_profile.status.value, "queued")
        self.assertEqual(other_profile.status.value, "dispatched")
        self.assertEqual(
            [command["job_id"] for command in self.dispatcher.commands],
            [first.id, other_profile.id],
        )
        self.assertEqual(
            self.jobs.quickmode_limits(["local"]),
            [{"worker": "local", "max_concurrent": 2, "active": 2, "queued": 1}],
        )

    def test_export_modes_queue_on_one_worker_but_run_on_different_workers(self):
        self.authorize_quick_mode_storage(workers=("local", "remote-1"))
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

    def test_quickmode_json_ready_keeps_lane_until_shared_cursor_commit(self):
        cursor = FakeExportCursorGate()
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda _worker: {
            "contract_version": 1,
            "capabilities": [CAP_SHARED_EXPORT_CURSOR],
            "profiles": ["default", "archive", "other"],
            "export_profiles": ["default", "archive", "other"],
            "available_storage_profiles": ["default", "archive", "other"],
            "storage_upload_fingerprints": {
                "default": "a" * 64,
                "archive": "b" * 64,
                "other": "c" * 64,
            },
        }
        control = ControlPlane(
            self.jobs,
            dispatcher,
            self.profiles,
            export_cursor_service=cursor,
        )
        self.authorize_quick_mode_storage(control, dispatcher)
        first = control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/2", "quick_mode": True}
        )
        second = control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/3", "quick_mode": True}
        )
        self.assertEqual(first.status, JobStatus.DISPATCHED)
        self.assertEqual(second.status, JobStatus.QUEUED)

        cursor.enabled = True
        cursor.leases.add(first.id)
        control.append_worker_event(
            JobEvent(
                job_id=first.id,
                sequence=2,
                status=JobStatus.RUNNING,
                event_type="export.json_ready",
                progress={"phase": "json_ready"},
                result={"json_name": "export.json", "export_end_id": 10},
            )
        )
        self.assertEqual(self.jobs.get(second.id).status, JobStatus.QUEUED)

        cursor.committed.add(first.id)
        cursor.leases.discard(first.id)
        self.assertTrue(control.on_export_cursor_committed(first.id))
        self.assertEqual(self.jobs.get(second.id).status, JobStatus.DISPATCHED)

    def test_shared_cursor_gate_rejects_worker_without_capability(self):
        cursor = FakeExportCursorGate()
        cursor.enabled = True
        control = ControlPlane(
            self.jobs,
            FakeDispatcher(),
            self.profiles,
            export_cursor_service=cursor,
        )
        with self.assertRaises(DomainError) as raised:
            control.submit_job(
                self.actor, "export", {"url": "https://t.me/c/1/2"}
            )
        self.assertEqual(raised.exception.code, "WORKER_INCOMPATIBLE")
        self.assertEqual(self.jobs.count(kind="export"), 0)

    def test_shared_cursor_dispatch_marks_worker_payload_only_when_enabled(self):
        cursor = FakeExportCursorGate()
        cursor.enabled = True
        dispatcher = FakeDispatcher()
        dispatcher.capabilities = lambda _worker: {
            "contract_version": 1,
            "capabilities": [CAP_SHARED_EXPORT_CURSOR],
        }
        control = ControlPlane(
            self.jobs,
            dispatcher,
            self.profiles,
            export_cursor_service=cursor,
        )

        job = control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/2"}
        )

        self.assertTrue(dispatcher.commands[-1]["payload"]["_shared_export_cursor"])
        self.assertNotIn("_shared_export_cursor", job.payload)

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
                "folders": ["/workspace/folder"],
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

    def test_backend_force_cancels_stalled_job_after_worker_grace(self):
        control = ControlPlane(
            self.jobs,
            self.dispatcher,
            self.profiles,
            job_stall_timeout_seconds=10,
            job_cancel_grace_seconds=5,
        )
        job = control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/2"}
        )
        stale_at = utc_now() - timedelta(seconds=20)
        control.jobs.append_event(
            JobEvent(
                job_id=job.id,
                sequence=2,
                status=JobStatus.RUNNING,
                event_type="running",
                created_at=stale_at,
            )
        )

        control._recover_stale_jobs(now=stale_at + timedelta(seconds=11))
        self.assertEqual(self.jobs.get(job.id).status, JobStatus.RUNNING)
        self.assertTrue(self.dispatcher.cancel_result)

        # Worker output can arrive just after the first watchdog tick.  It is
        # proof of liveness and must prevent the grace timer from force
        # cancelling a healthy upload.
        control.update_worker_progress(
            JobEvent(
                job_id=job.id,
                sequence=3,
                status=JobStatus.RUNNING,
                event_type="progress.snapshot",
                progress={"heartbeat": True},
                created_at=stale_at + timedelta(seconds=12),
            )
        )
        self.assertNotIn(job.id, control._stale_cancel_requested)

        control._recover_stale_jobs(now=stale_at + timedelta(seconds=17))
        self.assertEqual(self.jobs.get(job.id).status, JobStatus.RUNNING)

        # If the worker goes silent again, the normal watchdog path still
        # cancels it after the configured grace period.
        control._recover_stale_jobs(now=stale_at + timedelta(seconds=30))
        self.assertEqual(self.jobs.get(job.id).status, JobStatus.RUNNING)
        control._recover_stale_jobs(now=stale_at + timedelta(seconds=36))
        self.assertEqual(self.jobs.get(job.id).status, JobStatus.CANCELLED)
        self.assertEqual(self.jobs.get(job.id).error["code"], "JOB_STALLED")

        late = control.append_worker_event(
            JobEvent(
                job_id=job.id,
                sequence=3,
                status=JobStatus.RUNNING,
                event_type="late_running",
            )
        )
        self.assertEqual(late.status, JobStatus.CANCELLED)

    def test_dispatch_failure_is_terminal_after_dispatched_event(self):
        control = ControlPlane(self.jobs, FailingDispatcher(), self.profiles)

        with self.assertRaisesRegex(Exception, "tidak dapat menerima job"):
            control.submit_job(self.actor, "export", {"url": "https://t.me/c/1/2"})

        jobs = self.jobs.list(profile="default", limit=10)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].status.value, "failed")
        self.assertEqual([event.sequence for event in self.jobs.events(jobs[0].id)], [1, 2])

    def test_incompatible_worker_failure_keeps_contract_error_code(self):
        control = ControlPlane(self.jobs, IncompatibleDispatcher(), self.profiles)

        with self.assertRaises(DomainError) as raised:
            control.submit_job(self.actor, "export", {"url": "https://t.me/c/1/2"})

        self.assertEqual(raised.exception.code, "WORKER_INCOMPATIBLE")
        job = self.jobs.list(profile="default", limit=10)[0]
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(self.jobs.events(job.id)[-1].error["code"], "WORKER_INCOMPATIBLE")

    def test_terminate_all_force_cancels_stale_jobs(self):
        first = self.control.submit_job(self.actor, "export", {"url": "https://t.me/c/1/2"})
        second = self.control.submit_job(self.actor, "utility", {"utility": "pindah", "folders": ["/workspace/folder"]})
        self.dispatcher.cancel_result = False

        result = self.control.terminate_active_jobs(self.actor)

        self.assertEqual(result, {"total": 2, "interrupted": 0, "force_cancelled": 2})
        self.assertEqual(self.jobs.get(first.id).status.value, "cancelled")
        self.assertEqual(self.jobs.get(second.id).status.value, "cancelled")

    def test_terminate_quick_mode_filter_does_not_touch_normal_export(self):
        self.authorize_quick_mode_storage()
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

    def test_retry_quick_mode_reuses_id_and_keeps_snapshot_and_stage(self):
        self.authorize_quick_mode_storage()
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

        self.assertEqual(retry.id, original.id)
        self.assertEqual(retry.profile, original.profile)
        self.assertEqual(retry.worker, original.worker)
        self.assertEqual(retry.status.value, "dispatched")
        internal = self.jobs.command_payload(retry.id)
        self.assertEqual(internal["quick_settings"]["compress_size"], "45m")
        self.assertEqual(internal["quick_settings"]["compress_password"], "secret")
        self.assertEqual(internal["quick_retry"]["retry_of"], original.id)
        self.assertEqual(internal["quick_retry"]["retry_phase"], "uploading")
        self.assertEqual(internal["quick_retry"]["stage_job_id"], original.id)
        self.assertEqual(self.jobs.get(original.id).status.value, "dispatched")

    def test_retry_succeeded_starts_a_new_quick_operation_from_exporting(self):
        self.authorize_quick_mode_storage()
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

    def test_retry_normal_export_reuses_id(self):
        original = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/8"}
        )
        self.control.append_worker_event(
            JobEvent(original.id, 2, JobStatus.FAILED, "failed", error={"message": "tdl"})
        )

        retry = self.control.retry_job(self.actor, original.id)

        self.assertEqual(retry.id, original.id)
        self.assertEqual(retry.status.value, "dispatched")
        internal = self.jobs.command_payload(retry.id)
        self.assertFalse(internal["quick_mode"])
        self.assertEqual(internal["export_retry"]["retry_of"], original.id)
        self.assertEqual(internal["export_retry"]["retry_phase"], "exporting")

    def test_reused_retry_ignores_late_event_from_previous_attempt(self):
        original = self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/12"}
        )
        self.control.append_worker_event(
            JobEvent(original.id, 2, JobStatus.FAILED, "failed", error={"message": "tdl"})
        )

        retry = self.control.retry_job(self.actor, original.id)
        self.assertEqual(retry.id, original.id)
        current = self.control.append_worker_event(
            JobEvent(original.id, 2, JobStatus.RUNNING, "late_old_attempt")
        )

        self.assertEqual(current.status, JobStatus.DISPATCHED)
        self.assertEqual(self.jobs.get(original.id).status, JobStatus.DISPATCHED)

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
        self.authorize_quick_mode_storage()
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

    def test_quick_mode_limit_is_per_worker_and_resume_rejoins_fifo_with_checkpoint(self):
        self.authorize_quick_mode_storage()
        first = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/31", "quick_mode": True},
        )
        second = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/32", "quick_mode": True},
            profile="archive",
        )
        third = self.control.submit_job(
            self.actor,
            "export",
            {"url": "https://t.me/c/1/33", "quick_mode": True},
            profile="other",
        )

        self.assertEqual([first.status.value, second.status.value, third.status.value], ["dispatched", "dispatched", "queued"])
        self.assertEqual(self.jobs.quickmode_limits(["local"]), [{"worker": "local", "max_concurrent": 2, "active": 2, "queued": 1}])

        self.control.append_worker_event(
            JobEvent(
                first.id,
                2,
                JobStatus.PAUSED,
                "paused",
                {"phase": "downloading", "paused_phase": "downloading", "pause_kind": "worker"},
            )
        )
        self.control.resume_job(self.actor, first.id)
        self.assertEqual(self.jobs.get(third.id).status, JobStatus.DISPATCHED)
        self.assertEqual(self.jobs.get(first.id).status, JobStatus.QUEUED)

        self.control.append_worker_event(JobEvent(second.id, 2, JobStatus.RUNNING, "started"))
        self.control.append_worker_event(JobEvent(second.id, 3, JobStatus.SUCCEEDED, "completed"))

        self.assertEqual(self.jobs.get(first.id).status, JobStatus.DISPATCHED)
        resumed_payload = self.jobs.command_payload(first.id)
        self.assertEqual(resumed_payload["quick_retry"]["stage_job_id"], first.id)
        self.assertEqual(resumed_payload["quick_retry"]["resume_phase"], "auto")
        self.assertEqual(len(self.dispatcher.commands), 4)

    def _create_ambiguous_storage_upload(self):
        self.authorize_quick_mode_storage()
        self.attach_storage_readiness()
        source = Job(
            id="storage-source-reconcile",
            kind="storage_upload",
            profile="default",
            actor_user_id=42,
            worker="local",
            status=JobStatus.FAILED,
            payload={"folder_path": "/workspace/storage", "keywords": "backup"},
            result={"value": {"items": [
                {
                    "path": "matched.txt", "name": "matched.txt",
                    "status": "needs_reconciliation", "attempt": 1,
                    "profile": "default", "retryable": False,
                },
                {
                    "path": "safe.txt", "name": "safe.txt",
                    "status": "needs_reconciliation", "attempt": 2,
                    "profile": "archive", "retryable": False,
                },
            ]}},
            created_at=utc_now() - timedelta(minutes=2),
        )
        self.jobs.create_with_private_values(
            source,
            {
                "tdl_storage_chat_ref": b"-100123",
                "tdl_sender_session_fingerprints": (
                    b'{"default":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
                    b'"archive":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}'
                ),
            },
        )
        return source

    def test_storage_reconciliation_uses_private_original_snapshot_and_deduplicates_active_jobs(self):
        source = self._create_ambiguous_storage_upload()

        reconciliation = self.control.reconcile_storage_upload(self.actor, source.id)
        self.assertEqual(reconciliation.kind, "storage_reconcile")
        self.assertEqual(reconciliation.payload, {"source_job_id": source.id})
        command = self.dispatcher.commands[-1]
        payload = command["payload"]
        self.assertEqual(payload["tdl_access_target"], "-100123")
        self.assertEqual(payload["start_timestamp"], int(source.created_at.timestamp()))
        self.assertNotIn("-100123", repr(reconciliation.payload))
        self.assertNotIn("matched.txt", repr(reconciliation.payload))
        self.assertEqual(payload["_tdl_sender_session_fingerprints"]["default"], "a" * 64)

        count = len(self.dispatcher.commands)
        duplicate = self.control.reconcile_storage_upload(self.actor, source.id)
        self.assertEqual(duplicate.id, reconciliation.id)
        self.assertEqual(len(self.dispatcher.commands), count)

    def test_reconciled_success_is_not_retried_and_only_zero_match_file_uses_original_destination(self):
        source = self._create_ambiguous_storage_upload()
        reconciliation = self.control.reconcile_storage_upload(self.actor, source.id)
        next_sequence = max(
            event.sequence for event in self.jobs.events(reconciliation.id)
        ) + 1
        self.control.append_worker_event(
            JobEvent(reconciliation.id, next_sequence, JobStatus.RUNNING, "started")
        )
        self.control.append_worker_event(
            JobEvent(
                reconciliation.id,
                next_sequence + 1,
                JobStatus.SUCCEEDED,
                "storage.reconciliation_completed",
                result={"value": {
                    "source_job_id": source.id,
                    "items": [
                        {
                            "index": 0, "name": "matched.txt", "profile": "default",
                            "status": "succeeded", "match_count": 1, "retryable": False,
                        },
                        {
                            "index": 1, "name": "safe.txt", "profile": "archive",
                            "status": "failed", "match_count": 0, "retryable": True,
                        },
                    ],
                }},
            )
        )
        updated = self.jobs.get(source.id)
        items = updated.result["value"]["items"]
        self.assertEqual(items[0]["status"], "succeeded")
        self.assertFalse(items[0]["retryable"])
        self.assertEqual(items[1]["status"], "failed")
        self.assertTrue(items[1]["retryable"])
        self.assertTrue(job_dict(updated)["retryable"])

        retry = self.control.retry_job(self.actor, source.id)
        retry_command = self.dispatcher.commands[-1]
        self.assertEqual(retry.kind, "storage_upload")
        self.assertEqual(retry_command["payload"]["_storage_retry_paths"], ["safe.txt"])
        self.assertEqual(retry_command["payload"]["tdl_access_target"], "-100123")


if __name__ == "__main__":
    unittest.main()
