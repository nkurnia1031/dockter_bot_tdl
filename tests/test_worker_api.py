import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tme3bot.api.worker import WorkerContext, create_worker_app
from tme3bot.domain.models import DomainError
from tme3bot.domain.worker_contract import CAP_SHARED_EXPORT_CURSOR


class FakeExecutor:
    def __init__(self):
        self.commands = []
        self.deleted_stages = []
        self.tts_ready = False
        self.safelink_ready = False
        self.tts_helper_recoveries = []
        self.durable_ready = False
        self.durable_commands = {}
        self.artifact_file = None
        self.runtime_updates = []
        self.worker_api_token = "worker-secret"
        self.previous_worker_api_token = ""
        self.profile_inputs = []
        self.profile_installs = []
        self.profile_sync_contexts = []
        self.profile_sync_commits = []
        self.profile_sync_requests = []
        self.profile_sync_cancellations = []
        self.profile_sync_snapshot = {"status": "ready", "backend_available": True, "profiles": {}}
        self.worker_settings_values = {
            "storage_profile": "default",
            "storage_profile_available": True,
            "available_storage_profiles": ["default"],
            "worker_api_token_configured": True,
            "tts_helper_urls": ["http://tts-1:5000", "http://tts-2:5000", "http://tts-3:5000"],
            "tts_tor_control_hosts": ["tor-1", "tor-2", "tor-3"],
            "tts_tor_control_ports": [9051, 9051, 9051],
            "tts_part_retries": 4,
            "tts_retry_base_seconds": 2.0,
            "tts_newnym_after_retries": 3,
        }

    def capabilities(self):
        return {
            "profiles": ["default"],
            "tts": self.tts_ready,
            "safelink_resolver": self.safelink_ready,
            "profile_sync": {"status": "ready"},
        }

    def profile_sync_status(self):
        return dict(self.profile_sync_snapshot)

    def request_profile_sync(self, profile=None, mode="check"):
        self.profile_sync_requests.append((profile, mode))
        return {"accepted": True, "status": "sync_pending", "profile": profile}

    def cancel_profile_sync(self, profile, mode="check"):
        self.profile_sync_cancellations.append((profile, mode))
        return {"accepted": True, "status": "cancelling", "profile": profile}

    def durable_commands_ready(self):
        return self.durable_ready

    def accept_durable_command(self, envelope):
        if not self.durable_ready:
            raise DomainError(
                "DURABLE_COMMANDS_NOT_READY", "Jurnal belum siap.", status_code=503
            )
        command_id = str(envelope["command_id"])
        previous = self.durable_commands.get(command_id)
        if previous is not None and previous["payload"] != envelope:
            raise DomainError("COMMAND_ID_CONFLICT", "Conflict.", status_code=409)
        if previous is None:
            self.durable_commands[command_id] = {
                "payload": dict(envelope),
                "snapshot": {
                    "command_id": command_id,
                    "job_id": envelope.get("job_id"),
                    "status": "accepted",
                    "accepted": True,
                },
            }
        return {**self.durable_commands[command_id]["snapshot"], "replayed": previous is not None}

    def durable_command_status(self, command_id):
        entry = self.durable_commands.get(command_id)
        return dict(entry["snapshot"]) if entry else None

    def tts_health(self):
        return {
            "helpers_ready": self.tts_ready,
            "available_profiles": ["default"],
            "helpers": [
                {"slot": slot, "status": "ready" if self.tts_ready else "tor_unreachable", "bootstrap_percent": 100 if self.tts_ready else None, "checked_at": "now"}
                for slot in range(1, 4)
            ],
        }

    def diagnose_profile_export(self, profile):
        return {
            "ready": profile == "default",
            "reason_codes": [] if profile == "default" else ["PROFILE_ROOT_SESSION_MISSING"],
            "checks": [{"name": "root_session", "ready": profile == "default", "code": "PROFILE_ROOT_SESSION_READY" if profile == "default" else "PROFILE_ROOT_SESSION_MISSING"}],
        }

    def recover_tts_helper(self, slot):
        self.tts_helper_recoveries.append(slot)
        return {"accepted": True, "status": "restarting"}

    def worker_settings(self):
        return dict(self.worker_settings_values)

    def update_worker_settings(self, values):
        self.runtime_updates.append(values)
        if values.get("worker_api_token"):
            self.previous_worker_api_token = self.worker_api_token
            self.worker_api_token = values["worker_api_token"]
        profile = values.get("storage_profile")
        if profile and profile != "default":
            raise DomainError(
                "STORAGE_PROFILE_UNAVAILABLE",
                "Profil Storage belum tersedia.",
                status_code=409,
            )
        return self.worker_settings()

    def worker_token_matches(self, token):
        if token == self.worker_api_token:
            self.previous_worker_api_token = ""
            return True
        return token == self.previous_worker_api_token and bool(token)

    def tts_artifact_path(self, job_id, artifact_ref):
        if job_id == "job-tts" and artifact_ref == "a" * 48:
            return self.artifact_file
        return None

    def enqueue(self, command):
        self.commands.append(command)
        return 1

    def cancel(self, job_id):
        return job_id == "known"

    def pause(self, job_id):
        return job_id == "known"

    def resume(self, job_id, event_sequence_start=None):
        return job_id == "known" and event_sequence_start == 12

    def workspace_tree(self, path):
        return {"path": path, "items": [{"name": "biasa", "path": "/workspace/biasa", "kind": "directory"}]}

    def quickmode_scan(self):
        return {"worker": "local", "items": [{"stage_job_id": "stage-1", "phase": "uploading"}]}

    def quickmode_verify(self, stage_job_id, expected_phase="uploading"):
        return {
            "stage_job_id": stage_job_id,
            "status": "verified",
            "expected_phase": expected_phase,
            "staging_cleaned": True,
        }

    def quickmode_delete(self, stage_job_id):
        self.deleted_stages.append(stage_job_id)
        return {"stage_job_id": stage_job_id, "deleted": True}

    def job_log_snapshot(self, job_id):
        if job_id != "active":
            return None
        return {
            "lines": ["tdl download started", "50% 1 MB/s"],
            "line_count": 2,
            "truncated": False,
        }

    def validate_profile_session(self, archive_data):
        return {"telegram_user_id": 123}

    def start_profile_login(self, operation_id, method, phone=""):
        return {"status": "waiting_input", "step": "qr", "qr_text": "QR"}

    def profile_login_input(self, operation_id, field_name, value):
        self.profile_inputs.append((operation_id, field_name, value))
        return {"status": "waiting_input", "step": "password"}

    def profile_login_state(self, operation_id):
        return {"status": "ready", "telegram_user_id": 123}

    def profile_login_bundle_path(self, operation_id):
        return self.artifact_file

    def cancel_profile_login(self, operation_id):
        return True

    def install_profile_bundle(self, profile, telegram_user_id, bundle, operation_id, **sync_context):
        self.profile_installs.append((profile, telegram_user_id, bundle, operation_id))
        self.profile_sync_contexts.append(dict(sync_context))
        return {"profile": profile, "ready": True}

    def export_profile_bundle(self, profile):
        return 123, b"profile-bundle"

    def commit_profile_bundle(self, profile, operation_id, **sync_context):
        self.profile_sync_commits.append(dict(sync_context))
        return True

    def rollback_profile_bundle(self, profile, operation_id):
        return True


class WorkerApiTests(unittest.TestCase):
    def setUp(self):
        config = type("Config", (), {"worker_api_token": "worker-secret"})()
        self.executor = FakeExecutor()
        self.temp = tempfile.TemporaryDirectory()
        self.executor.artifact_file = Path(self.temp.name) / ("artifact-" + "a" * 48 + ".mp3")
        self.executor.artifact_file.write_bytes(b"audio")
        self.client = TestClient(
            create_worker_app(WorkerContext(config, self.executor))
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_worker_requires_token_and_accepts_frontend_neutral_job(self):
        payload = {
            "job_id": "job-1",
            "kind": "export",
            "profile": "default",
            "actor_user_id": 42,
            "payload": {"url": "https://t.me/c/1/2"},
        }
        denied = self.client.post("/internal/v1/jobs", json=payload)
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(denied.json()["error"]["code"], "WORKER_UNAUTHORIZED")

        accepted = self.client.post(
            "/internal/v1/jobs",
            headers={"Authorization": "Bearer worker-secret"},
            json=payload,
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["position"], 1)
        self.assertEqual(self.executor.commands, [payload])

    def test_worker_has_no_openapi_surface(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 404)

    def test_healthz_distinguishes_running_process_from_pending_profile_sync(self):
        ready = self.client.get("/healthz")
        self.assertEqual(ready.json()["ok"], True)
        self.assertTrue(ready.json()["profiles_ready"])

        self.executor.profile_sync_snapshot["status"] = "sync_pending"
        pending = self.client.get("/healthz")
        self.assertEqual(pending.json()["ok"], True)
        self.assertFalse(pending.json()["profiles_ready"])
        self.assertEqual(pending.json()["profile_sync_status"], "sync_pending")

    def test_profile_sync_status_and_manual_request_require_worker_auth(self):
        denied_status = self.client.get("/internal/v1/profile-sync")
        self.assertEqual(denied_status.status_code, 401)
        headers = {"Authorization": "Bearer worker-secret"}
        status = self.client.get("/internal/v1/profile-sync", headers=headers)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "ready")

        denied_request = self.client.post(
            "/internal/v1/profile-sync", json={"profile": "irang"}
        )
        self.assertEqual(denied_request.status_code, 401)
        accepted = self.client.post(
            "/internal/v1/profile-sync",
            headers=headers,
            json={"profile": "irang", "mode": "repair"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(self.executor.profile_sync_requests, [("irang", "repair")])

        invalid_mode = self.client.post(
            "/internal/v1/profile-sync",
            headers=headers,
            json={"mode": "force-shell"},
        )
        self.assertEqual(invalid_mode.status_code, 422)
        extra = self.client.post(
            "/internal/v1/profile-sync",
            headers=headers,
            json={"profile": "irang", "url": "http://attacker.invalid"},
        )
        self.assertEqual(extra.status_code, 422)
        self.assertEqual(len(self.executor.profile_sync_requests), 1)

        denied_cancel = self.client.request(
            "DELETE", "/internal/v1/profile-sync", json={"profile": "irang"}
        )
        self.assertEqual(denied_cancel.status_code, 401)
        cancelled = self.client.request(
            "DELETE",
            "/internal/v1/profile-sync",
            headers=headers,
            json={"profile": "irang", "mode": "check"},
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "cancelling")
        self.assertEqual(self.executor.profile_sync_cancellations, [("irang", "check")])
        invalid_cancel = self.client.request(
            "DELETE",
            "/internal/v1/profile-sync",
            headers=headers,
            json={"profile": "irang", "url": "http://attacker.invalid"},
        )
        self.assertEqual(invalid_cancel.status_code, 422)

    def test_durable_command_endpoints_require_auth_and_ready_journal(self):
        envelope = {
            "command_id": "command-1",
            "operation_id": "operation-1",
            "job_id": "job-durable-1",
            "attempt": 1,
            "dispatch_token": "private-dispatch-token",
            "job": {
                "kind": "export",
                "profile": "default",
                "actor_user_id": 42,
                "worker": "local",
                "payload": {"url": "https://t.me/c/1/2"},
            },
        }
        denied = self.client.post("/internal/v1/commands", json=envelope)
        self.assertEqual(denied.status_code, 401)
        headers = {"Authorization": "Bearer worker-secret"}
        not_ready = self.client.post(
            "/internal/v1/commands", headers=headers, json=envelope
        )
        self.assertEqual(not_ready.status_code, 503)
        self.executor.durable_ready = True
        accepted = self.client.post(
            "/internal/v1/commands", headers=headers, json=envelope
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.json()["accepted"])
        self.assertNotIn("payload", accepted.json())
        self.assertNotIn("dispatch_token", accepted.json())
        status = self.client.get(
            "/internal/v1/commands/command-1", headers=headers
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "accepted")
        changed = {**envelope, "job": {**envelope["job"], "payload": {"secret": "changed"}}}
        conflict = self.client.post(
            "/internal/v1/commands", headers=headers, json=changed
        )
        self.assertEqual(conflict.status_code, 409)
        missing = self.client.get(
            "/internal/v1/commands/missing", headers=headers
        )
        self.assertEqual(missing.status_code, 404)

    def test_tts_capability_is_dynamic_and_audio_route_is_internal(self):
        denied_capability = self.client.get("/internal/v1/capabilities")
        self.assertEqual(denied_capability.status_code, 401)
        headers = {"Authorization": "Bearer worker-secret"}
        capabilities = self.client.get("/internal/v1/capabilities", headers=headers)
        self.assertNotIn("tts", capabilities.json()["capabilities"])

        self.executor.tts_ready = True
        ready = self.client.get("/internal/v1/capabilities", headers=headers)
        self.assertIn("tts", ready.json()["capabilities"])

        denied_audio = self.client.get(
            f"/internal/v1/tts/artifacts/job-tts/{'a' * 48}"
        )
        self.assertEqual(denied_audio.status_code, 401)
        audio = self.client.get(
            f"/internal/v1/tts/artifacts/job-tts/{'a' * 48}", headers=headers
        )
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.content, b"audio")
        self.assertIn("artifact-", audio.headers["content-disposition"])

    def test_resolver_capability_tracks_private_addon_readiness(self):
        headers = {"Authorization": "Bearer worker-secret"}
        not_ready = self.client.get("/internal/v1/capabilities", headers=headers)
        self.assertNotIn("safelink_resolve.v1", not_ready.json()["capabilities"])

        self.executor.safelink_ready = True
        ready = self.client.get("/internal/v1/capabilities", headers=headers)
        self.assertIn("safelink_resolve.v1", ready.json()["capabilities"])

    def test_tts_health_and_helper_recovery_require_worker_auth(self):
        denied = self.client.get("/internal/v1/tts/health")
        self.assertEqual(denied.status_code, 401)
        headers = {"Authorization": "Bearer worker-secret"}
        health = self.client.get("/internal/v1/tts/health", headers=headers)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["helpers"][0]["status"], "tor_unreachable")
        self.assertEqual(health.json()["available_profiles"], ["default"])
        denied_recovery = self.client.post("/internal/v1/tts/helpers/1/recover")
        self.assertEqual(denied_recovery.status_code, 401)
        accepted = self.client.post("/internal/v1/tts/helpers/2/recover", headers=headers)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json(), {"accepted": True, "status": "restarting"})
        self.assertEqual(self.executor.tts_helper_recoveries, [2])
        invalid = self.client.post("/internal/v1/tts/helpers/4/recover", headers=headers)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.executor.tts_helper_recoveries, [2])

    def test_worker_runtime_settings_are_internal_and_validate_storage_profile(self):
        headers = {"Authorization": "Bearer worker-secret"}
        denied = self.client.get("/internal/v1/runtime-settings")
        self.assertEqual(denied.status_code, 401)

        current = self.client.get("/internal/v1/runtime-settings", headers=headers)
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["available_storage_profiles"], ["default"])

        rejected = self.client.put(
            "/internal/v1/runtime-settings",
            headers=headers,
            json={"storage_profile": "missing"},
        )
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()["error"]["code"], "STORAGE_PROFILE_UNAVAILABLE")

        accepted = self.client.put(
            "/internal/v1/runtime-settings",
            headers=headers,
            json={"storage_profile": "default"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["storage_profile"], "default")

    def test_worker_runtime_settings_do_not_store_tor_secret(self):
        headers = {"Authorization": "Bearer worker-secret"}
        secret = "tor-control-password-never-return-this"
        updated = self.client.put(
            "/internal/v1/runtime-settings",
            headers=headers,
            json={
                "tts_helper_urls": ["http://tts-1:5000", "http://tts-2:5000", "http://tts-3:5000"],
                "tts_tor_control_hosts": ["tor-1", "tor-2", "tor-3"],
                "tts_tor_control_ports": [9051, 9051, 9051],
                "tts_tor_control_password": secret,
                "tts_part_retries": 5,
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertNotIn(secret, updated.text)
        self.assertNotIn("tts_tor_control_password_configured", updated.json())
        self.assertNotIn("tts_tor_control_password", self.executor.runtime_updates[0])

    def test_worker_runtime_ignores_removed_tor_secret(self):
        secret = "tor-secret-must-not-echo"
        response = self.client.put(
            "/internal/v1/runtime-settings",
            headers={"Authorization": "Bearer worker-secret"},
            json={"tts_tor_control_password": secret * 30},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(secret, response.text)

    def test_worker_api_token_can_rotate_with_short_overlap_for_inflight_update(self):
        headers = {"Authorization": "Bearer worker-secret"}
        new_token = "rotated-worker-token-123456"
        updated = self.client.put(
            "/internal/v1/runtime-settings",
            headers=headers,
            json={"worker_api_token": new_token},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertNotIn(new_token, updated.text)

        accepted_new = self.client.get(
            "/internal/v1/capabilities",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        self.assertEqual(accepted_new.status_code, 200)
        rejected_old = self.client.get(
            "/internal/v1/capabilities", headers=headers
        )
        self.assertEqual(rejected_old.status_code, 401)

    def test_worker_preserves_event_sequence_start_for_reused_job_ids(self):
        payload = {
            "job_id": "retry-job",
            "kind": "export",
            "profile": "default",
            "actor_user_id": 42,
            "event_sequence_start": 983,
            "payload": {"quick_mode": True},
        }
        response = self.client.post(
            "/internal/v1/jobs",
            headers={"Authorization": "Bearer worker-secret"},
            json=payload,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.executor.commands[-1]["event_sequence_start"], 983)

    def test_pause_and_resume_endpoints_are_internal_and_forward_sequence(self):
        headers = {"Authorization": "Bearer worker-secret"}
        denied = self.client.post("/internal/v1/jobs/known/pause")
        self.assertEqual(denied.status_code, 401)
        paused = self.client.post("/internal/v1/jobs/known/pause", headers=headers)
        self.assertEqual(paused.status_code, 200)
        self.assertTrue(paused.json()["paused"])
        resumed = self.client.post(
            "/internal/v1/jobs/known/resume",
            headers=headers,
            json={"event_sequence_start": 12},
        )
        self.assertEqual(resumed.status_code, 200)
        self.assertTrue(resumed.json()["resumed"])

    def test_workspace_tree_requires_token(self):
        denied = self.client.get("/internal/v1/workspace/tree")
        self.assertEqual(denied.status_code, 401)
        accepted = self.client.get(
            "/internal/v1/workspace/tree?path=%2Fworkspace%2Fbiasa",
            headers={"Authorization": "Bearer worker-secret"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["path"], "/workspace/biasa")

    def test_quickmode_scan_requires_token_and_returns_derived_staging(self):
        denied = self.client.get("/internal/v1/quickmode/scan")
        self.assertEqual(denied.status_code, 401)
        accepted = self.client.get(
            "/internal/v1/quickmode/scan",
            headers={"Authorization": "Bearer worker-secret"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["items"][0]["stage_job_id"], "stage-1")

    def test_quickmode_verify_requires_token_and_returns_cleanup_result(self):
        denied = self.client.post(
            "/internal/v1/quickmode/verify",
            json={"stage_job_id": "stage-1", "expected_phase": "uploading"},
        )
        self.assertEqual(denied.status_code, 401)
        accepted = self.client.post(
            "/internal/v1/quickmode/verify",
            headers={"Authorization": "Bearer worker-secret"},
            json={"stage_job_id": "stage-1", "expected_phase": "uploading"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["status"], "verified")
        self.assertTrue(accepted.json()["staging_cleaned"])

    def test_quickmode_stage_delete_requires_token_and_forwards_stage_id(self):
        denied = self.client.delete("/internal/v1/quickmode/staging/stage-1")
        self.assertEqual(denied.status_code, 401)

        accepted = self.client.delete(
            "/internal/v1/quickmode/staging/stage-1",
            headers={"Authorization": "Bearer worker-secret"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json(), {"stage_job_id": "stage-1", "deleted": True})
        self.assertEqual(self.executor.deleted_stages, ["stage-1"])

    def test_active_job_log_snapshot_requires_token_and_handles_missing(self):
        denied = self.client.get("/internal/v1/jobs/active/log-snapshot")
        self.assertEqual(denied.status_code, 401)
        active = self.client.get(
            "/internal/v1/jobs/active/log-snapshot",
            headers={"Authorization": "Bearer worker-secret"},
        )
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()["log"]["line_count"], 2)
        missing = self.client.get(
            "/internal/v1/jobs/missing/log-snapshot",
            headers={"Authorization": "Bearer worker-secret"},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "JOB_LOG_NOT_ACTIVE")

    def test_profile_login_and_bundle_routes_are_internal_and_typed(self):
        headers = {"Authorization": "Bearer worker-secret"}
        denied = self.client.post("/internal/v1/profiles/login/op-1", json={"method": "qr"})
        self.assertEqual(denied.status_code, 401)

        started = self.client.post(
            "/internal/v1/profiles/login/op-1",
            headers=headers,
            json={"method": "qr", "phone": ""},
        )
        self.assertEqual(started.json()["step"], "qr")
        state = self.client.get("/internal/v1/profiles/login/op-1", headers=headers)
        self.assertEqual(state.json()["status"], "ready")
        self.assertNotIn("telegram_user_id", state.json())

        supplied = self.client.post(
            "/internal/v1/profiles/login/op-1/input",
            headers=headers,
            json={"field": "password", "value": "private-password"},
        )
        self.assertEqual(supplied.json()["step"], "password")
        self.assertEqual(self.executor.profile_inputs[-1][2], "private-password")

        installed = self.client.put(
            "/internal/v1/profiles/novel/session",
            headers={
                **headers,
                "X-Telegram-User-ID": "123",
                "X-Provisioning-ID": "op-1",
                "X-Profile-Sync-Run-ID": "a" * 32,
                "X-Profile-Sync-Revision": "7",
            },
            content=b"profile-bundle",
        )
        self.assertEqual(installed.status_code, 200)
        self.assertEqual(self.executor.profile_installs[-1][0:2], ("novel", 123))
        self.assertEqual(self.executor.profile_sync_contexts[-1], {"sync_run_id": "a" * 32, "sync_revision": 7})
        committed = self.client.post(
            "/internal/v1/profiles/novel/session/commit",
            headers=headers,
            json={"operation_id": "op-1", "sync_run_id": "a" * 32, "revision": 7},
        )
        self.assertEqual(committed.status_code, 200)
        self.assertEqual(self.executor.profile_sync_commits[-1], {"sync_run_id": "a" * 32, "sync_revision": 7})

    def test_profile_export_diagnostics_requires_worker_token_and_never_returns_paths(self):
        denied = self.client.get("/internal/v1/profiles/default/session/diagnostics")
        self.assertEqual(denied.status_code, 401)
        response = self.client.get(
            "/internal/v1/profiles/default/session/diagnostics",
            headers={"Authorization": "Bearer worker-secret"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ready"])
        self.assertNotIn("/workspace", response.text)

    def test_shared_export_cursor_capability_is_dynamic(self):
        self.executor.shared_export_cursor_ready = lambda: True
        ready = self.client.get(
            "/internal/v1/capabilities",
            headers={"Authorization": "Bearer worker-secret"},
        )
        self.assertEqual(ready.status_code, 200)
        self.assertIn(CAP_SHARED_EXPORT_CURSOR, ready.json()["capabilities"])

        self.executor.shared_export_cursor_ready = lambda: False
        unavailable = self.client.get(
            "/internal/v1/capabilities",
            headers={"Authorization": "Bearer worker-secret"},
        )
        self.assertNotIn(CAP_SHARED_EXPORT_CURSOR, unavailable.json()["capabilities"])


if __name__ == "__main__":
    unittest.main()
