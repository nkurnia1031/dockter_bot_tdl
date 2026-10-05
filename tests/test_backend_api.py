import tempfile
import unittest
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tme3bot.api.backend import BackendContext, create_backend_app
from tme3bot.backend_runtime_settings import BackendRuntimeSettings
from tme3bot.application.control_plane import ControlPlane
from tme3bot.application.operations import OperationsService, PreparedOperation
from tme3bot.domain.models import Actor, JobEvent, JobStatus
from tme3bot.export_catalog import ExportArtifactCatalog
from tme3bot.infrastructure.auth import BotAuthService, SqliteAuthRepository
from tme3bot.infrastructure.device_auth import DeviceAuthService, challenge_payload
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.infrastructure.operation_store import SqliteOperationStore
from tme3bot.profile_registry import ProfileRegistry
from tme3bot.storage_catalog import StorageCatalog
from tme3bot.storage_links import sign_storage_item
from tme3bot.utility import UtilityFolderStore, UtilitySettingsStore


class FakeProfiles:
    def __init__(self):
        self.route = "local"

    def profile_for_user(self, user_id):
        return "default" if int(user_id) in {42, 43} else None

    def worker_route(self, profile):
        return self.route

    def set_worker_route(self, profile, route):
        self.route = route
        return route

    def download_mode(self, profile):
        return "shared"

    def list_profiles(self):
        return ["default", "archive"]


class FakeDispatcher:
    def __init__(self):
        self.commands = []
        self.storage_available = True
        self.tts_ready = False
        self.tts_health_result = {
            "helpers_ready": False,
            "available_profiles": ["default"],
            "helpers": [
                {"slot": slot, "status": "tor_unreachable", "bootstrap_percent": None, "checked_at": "now"}
                for slot in range(1, 4)
            ],
        }
        self.tts_recoveries = []
        self.quick_scan = {"local": {"worker": "local", "items": []}}
        self.quick_verifications = []
        self.quick_deletions = []
        self.fast_worker_checks = []
        self.runtime_settings = {
            "storage_profile": "storage",
            "storage_profile_available": True,
            "available_storage_profiles": ["storage", "archive"],
            "worker_api_token_configured": True,
            "tts_helper_urls": ["http://tts-1:5000", "http://tts-2:5000", "http://tts-3:5000"],
            "tts_tor_control_hosts": ["tor-1", "tor-2", "tor-3"],
            "tts_tor_control_ports": [9051, 9051, 9051],
            "tts_part_retries": 4,
            "tts_retry_base_seconds": 2.0,
            "tts_newnym_after_retries": 3,
        }

    def dispatch(self, worker, payload):
        self.commands.append((worker, payload))
        return {"position": 1}

    def capabilities(self, worker):
        return {"capabilities": ["tts"] if self.tts_ready else []}

    def tts_health(self, worker):
        del worker
        return dict(self.tts_health_result)

    def recover_tts_helper(self, worker, slot):
        self.tts_recoveries.append((worker, slot))
        return {"accepted": True, "status": "restarting"}

    def worker_settings(self, worker):
        return dict(self.runtime_settings)

    def update_worker_settings(self, worker, payload):
        selected = payload.get("storage_profile")
        if selected and selected not in self.runtime_settings["available_storage_profiles"]:
            from tme3bot.infrastructure.http_client import JsonHttpError

            raise JsonHttpError(
                409,
                "Profil Storage belum tersedia.",
                {"error": {"code": "STORAGE_PROFILE_UNAVAILABLE", "message": "Profil Storage belum tersedia."}},
            )
        if selected:
            self.runtime_settings["storage_profile"] = selected
        if payload.get("worker_api_token"):
            self.runtime_settings["worker_api_token_configured"] = True
        return dict(self.runtime_settings)

    def cancel(self, worker, job_id):
        return True

    def job_log(self, worker, job_id):
        return {
            "log": {
                "lines": [f"{worker}:{job_id}:active"],
                "line_count": 1,
                "truncated": False,
            }
        }

    def check_worker(self, worker):
        return {
            "healthy": True,
            "profiles": ["default", "archive"],
            "storage_profile": "storage",
            "storage_profile_available": self.storage_available,
            "workspace": True,
        }

    def check_worker_fast(self, worker):
        self.fast_worker_checks.append(worker)
        return {"healthy": True}

    def quickmode_scan(self, worker):
        return self.quick_scan.get(worker, {"worker": worker, "items": []})

    def quickmode_verify(self, worker, stage_job_id, expected_phase="uploading"):
        self.quick_verifications.append((worker, stage_job_id, expected_phase))
        return {
            "stage_job_id": stage_job_id,
            "status": "verified",
            "channel_expected": 3,
            "channel_found": 3,
            "drive_expected": 2,
            "drive_found": 2,
            "staging_cleaned": True,
        }

    def quickmode_delete(self, worker, stage_job_id):
        self.quick_deletions.append((worker, stage_job_id))
        return {"stage_job_id": stage_job_id, "deleted": True}


class FakeWorkers:
    def __init__(self):
        self.values = {"local": {"url": "http://worker", "token": "secret", "enabled": True}}

    def list(self):
        return dict(self.values)

    def names(self):
        return sorted(self.values)

    def get(self, name):
        return self.values.get(name)

    def upsert(self, name, url, token, enabled=None):
        current = self.values.get(name, {})
        self.values[name] = {
            "url": url,
            "token": token,
            "enabled": current.get("enabled", True) if enabled is None else bool(enabled),
        }
        return name

    def set_enabled(self, name, enabled):
        if name not in self.values:
            return False
        self.values[name]["enabled"] = bool(enabled)
        return True

    def remove(self, name):
        return self.values.pop(name, None) is not None


class FakeTelegramBot:
    def __init__(self):
        self.copy_calls = []
        self.chat_lookups = []

    def get_chat(self, chat_id):
        self.chat_lookups.append(chat_id)
        return type("Chat", (), {"id": -100987654321, "username": "backupchannel", "title": "Backup"})()

    def copy_message(self, **values):
        self.copy_calls.append(values)
        return type("CopiedMessage", (), {"message_id": 777})()


class FakeProfileProvisioner:
    def __init__(self):
        self.uploaded = None
        self.login = None

    def profiles(self, actor_user_id=None):
        del actor_user_id
        return [{"name": "default", "active": True, "status": "legacy", "vault": False, "workers": []}]

    def upload(self, name, worker, data, actor_user_id):
        self.uploaded = (name, worker, data, actor_user_id)
        return "operation-upload"

    def start_login(self, name, worker, method, phone, actor_user_id):
        self.login = (name, worker, method, phone, actor_user_id)
        return "operation-login"

    def operation(self, operation_id, actor_user_id):
        if operation_id != "operation-login" or actor_user_id != 42:
            raise KeyError(operation_id)
        return {"id": operation_id, "profile": "novel", "status": "authenticating", "login": {"step": "qr", "qr_text": "qr-payload"}, "workers": []}

    def login_input(self, operation_id, actor_user_id, field, value):
        self.login_input_call = (operation_id, actor_user_id, field, value)
        return {"status": "waiting_input", "step": "password"}

    def retry(self, operation_id, actor_user_id):
        return None

    def cancel(self, operation_id, actor_user_id):
        return {"cancelled": True}

    def adopt(self, profile, worker, actor_user_id):
        return "operation-adopt"


class BackendApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "workspace").mkdir()
        db = root / "app.db"
        self.profiles = FakeProfiles()
        self.profiles.profile_registry = ProfileRegistry(root / "profiles.json", "default")
        self.dispatcher = FakeDispatcher()
        self.jobs = SqliteJobRepository(db)
        self.operation_service = OperationsService(SqliteOperationStore(self.jobs))
        self.catalog = StorageCatalog(db)
        self.export_catalog = ExportArtifactCatalog(db)
        self.workers = FakeWorkers()
        self.bot = FakeTelegramBot()
        self.control = ControlPlane(
            self.jobs,
            self.dispatcher,
            self.profiles,
            storage_catalog=self.catalog,
            export_catalog=self.export_catalog,
            worker_registry=self.workers,
        )
        self.auth = BotAuthService(
            SqliteAuthRepository(db),
            self.control.actor,
            "a" * 48,
            "my_bot",
        )
        self.auth_repository = self.auth.repository
        config = type(
            "Config",
            (),
            {
                "frontend_service_token": "frontend",
                "auth_jwt_secret": "a" * 48,
                "bot_username": "my_bot",
                "backend_internal_token": "internal",
                "management_api_token": "management",
                "storage_channel": "123",
                "storage_channel_id": -100123,
                "backup_enabled": True,
                "backup_schedule": "03:00",
                "backup_timezone": "Asia/Jakarta",
                "backup_retention": 7,
                "backup_volume_size": "45m",
                "backup_channel": "456",
                "backup_channel_ref": "-100456",
                "backup_channel_id": -100456,
                "backup_channel_username": "456",
                "storage_trash_retention_days": 30,
                "job_stall_timeout_seconds": 600,
                "job_cancel_grace_seconds": 30,
                "bot_token": "123456:abcdefghijklmnopqrstuvwxyzABCDE12345",
                "telegram_tts_chat_id": "123456789",
                "web_cookie_secret": "w" * 48,
                "web_cookie_secure": False,
                "web_public_origin": "",
            },
        )()
        context = BackendContext(
            config=config,
            control_plane=self.control,
            auth=self.auth,
            profile_manager=self.profiles,
            storage_catalog=self.catalog,
            export_catalog=self.export_catalog,
            worker_registry=self.workers,
            utility_folders=UtilityFolderStore(
                root / "folders.json", root / "workspace"
            ),
            utility_settings=UtilitySettingsStore(root / "settings.json"),
            worker_dispatcher=self.dispatcher,
            bot=self.bot,
            runtime_settings=BackendRuntimeSettings(
                root / "runtime-settings.json",
                {
                    "backup_enabled": True,
                    "backup_schedule": "03:00",
                    "backup_timezone": "Asia/Jakarta",
                    "backup_retention": 7,
                    "backup_volume_size": "45m",
                    "backup_channel": "456",
                    "storage_trash_retention_days": 30,
                    "job_stall_timeout_seconds": 600,
                    "job_cancel_grace_seconds": 30,
                    "bot_token": "123456:abcdefghijklmnopqrstuvwxyzABCDE12345",
                    "telegram_tts_chat_id": "123456789",
                },
            ),
            device_auth=DeviceAuthService(
                self.auth_repository, self.auth, "https://ui.example.test"
            ),
            operation_service=self.operation_service,
        )
        self.context = context
        self.client = TestClient(create_backend_app(context))

    def tearDown(self):
        self.temp.cleanup()

    def login(self, user_id=42):
        challenge = self.client.post(
            "/api/v1/auth/telegram/challenges"
        ).json()
        code = challenge["verification_uri"].split("login_", 1)[1]
        approved = self.client.post(
            f"/internal/v1/auth/telegram/challenges/{code}/approve",
            headers={"Authorization": "Bearer frontend"},
            json={"telegram_user_id": user_id},
        )
        self.assertEqual(approved.status_code, 200)
        token = self.client.post(
            f"/api/v1/auth/telegram/challenges/{challenge['challenge_id']}/token",
            json={"poll_token": challenge["poll_token"]},
        ).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def browser_login(self, user_id=42, csrf="csrf-device-test"):
        pair = self.auth._new_web_session(user_id)
        self.client.cookies.set("tme3_access", pair.access_token)
        self.client.cookies.set("tme3_refresh", pair.refresh_token)
        self.client.cookies.set("tme3_csrf", csrf)
        return {"Origin": "http://testserver", "X-CSRF-Token": csrf}

    def test_operations_api_is_idempotent_private_and_actor_scoped(self):
        def prepare(actor, target, input_data):
            return PreparedOperation(
                profile=actor.profile,
                target={"worker": "local"},
                private_payload={"text": input_data["text"]},
            )

        self.operation_service.register_handler("test.echo", prepare)
        auth = self.login(42)
        submitted = self.client.post(
            "/api/v1/operations",
            headers={**auth, "Idempotency-Key": "operation-submit-1"},
            json={"kind": "test.echo", "target": {"worker": "ignored"}, "input": {"text": "private-operation-text"}},
        )
        self.assertEqual(submitted.status_code, 202)
        operation_id = submitted.json()["operation_id"]
        self.assertEqual(submitted.headers["location"], f"/api/v1/operations/{operation_id}")
        self.assertNotIn("private-operation-text", submitted.text)
        self.assertNotIn("input", submitted.json())
        self.assertEqual(submitted.json()["status"], "queued")
        self.assertEqual(submitted.json()["revision"], 1)
        repeated = self.client.post(
            "/api/v1/operations",
            headers={**auth, "Idempotency-Key": "operation-submit-1"},
            json={"kind": "test.echo", "target": {"worker": "ignored"}, "input": {"text": "private-operation-text"}},
        )
        self.assertEqual(repeated.status_code, 202)
        self.assertEqual(repeated.json()["operation_id"], operation_id)
        collision = self.client.post(
            "/api/v1/operations",
            headers={**auth, "Idempotency-Key": "operation-submit-1"},
            json={"kind": "test.echo", "target": {"worker": "ignored"}, "input": {"text": "different-private-text"}},
        )
        self.assertEqual(collision.status_code, 409)
        self.assertNotIn("different-private-text", collision.text)
        self.assertEqual(self.client.get(f"/api/v1/operations/{operation_id}", headers=self.login(43)).status_code, 404)
        listed = self.client.get("/api/v1/operations", headers=auth)
        self.assertEqual([item["operation_id"] for item in listed.json()["items"]], [operation_id])
        private = self.operation_service.store.get_private_payload(operation_id)
        self.assertEqual(private, {"text": "private-operation-text"})

    def test_operations_validation_redacts_rejected_input_and_kind_is_allowlisted(self):
        auth = self.login(42)
        malformed = self.client.post(
            "/api/v1/operations",
            headers={**auth, "Idempotency-Key": "operation-invalid-1"},
            json={"kind": "test.echo", "target": {}, "input": "do-not-echo-this-value"},
        )
        self.assertEqual(malformed.status_code, 422)
        self.assertNotIn("do-not-echo-this-value", malformed.text)
        unavailable = self.client.post(
            "/api/v1/operations",
            headers={**auth, "Idempotency-Key": "operation-unavailable-1"},
            json={"kind": "arbitrary.command", "target": {}, "input": {}},
        )
        self.assertEqual(unavailable.status_code, 422)
        self.assertEqual(unavailable.json()["error"]["code"], "OPERATION_KIND_UNAVAILABLE")
        capability = self.client.get("/api/v1/capabilities")
        self.assertIn("operations_v1", capability.json()["capabilities"])

    def test_background_job_submit_is_accepted_without_worker_dispatch(self):
        self.context.queue_publisher = object()
        self.context.queue_command_service = object()
        client = TestClient(create_backend_app(self.context))
        auth = self.login(42)

        response = client.post(
            "/api/v1/operations",
            headers={**auth, "Idempotency-Key": "background-job-1"},
            json={
                "kind": "job.submit",
                "target": {"profile": "default", "worker": "local"},
                "input": {
                    "job_kind": "export",
                    "payload": {"url": "https://t.me/c/100/42"},
                },
            },
        )

        self.assertEqual(response.status_code, 202)
        self.assertIn("job.submit", client.get("/api/v1/capabilities").json()["operations"]["supported_kinds"])
        self.assertEqual(self.dispatcher.commands, [])
        operation = self.operation_service.get(self.control.actor(42), response.json()["operation_id"])
        job = self.jobs.get(operation.job_id)
        self.assertEqual(operation.status.value, "queued")
        self.assertEqual(job.status.value, "queued")
        self.assertEqual(job.worker, "local")
        self.assertEqual(self.jobs.command_payload(job.id)["dispatch_mode"], "durable")

    def test_background_job_submit_is_not_advertised_without_queue(self):
        capabilities = self.client.get("/api/v1/capabilities").json()
        self.assertNotIn("job.submit", capabilities["operations"]["supported_kinds"])

    def test_trusted_device_routes_require_browser_csrf_and_hide_keys(self):
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        device_id = "fd9f67f1-bba8-4011-9ed3-0f819ac8df10"
        document = {
            "device_id": device_id,
            "name": "Agent laptop",
            "algorithm": "Ed25519",
            "public_key": base64.urlsafe_b64encode(public).decode().rstrip("="),
            "origin": "https://ui.example.test",
        }
        headers = self.browser_login()

        rejected = self.client.post("/api/v1/auth/devices", json=document)
        self.assertEqual(rejected.status_code, 403)
        registered = self.client.post("/api/v1/auth/devices", headers=headers, json=document)
        self.assertEqual(registered.status_code, 201)
        self.assertTrue(registered.json()["created"])
        self.assertNotIn("public_key", registered.text)
        self.assertNotIn("private_key", registered.text)

        listing = self.client.get("/api/v1/auth/devices")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["items"][0]["fingerprint"], registered.json()["device"]["fingerprint"])
        self.assertNotIn("public_key", listing.text)

        denied = self.client.post(
            "/api/v1/auth/device/challenge",
            headers={"Origin": "https://attacker.example"},
            json={"device_id": device_id},
        )
        self.assertEqual(denied.status_code, 403)
        challenge_response = self.client.post(
            "/api/v1/auth/device/challenge",
            headers={"Origin": "https://ui.example.test"},
            json={"device_id": device_id},
        )
        self.assertEqual(challenge_response.status_code, 200)
        challenge = challenge_response.json()
        signature = base64.urlsafe_b64encode(
            private.sign(
                challenge_payload(
                    origin=challenge["origin"],
                    device_id=device_id,
                    challenge_id=challenge["challenge_id"],
                    nonce=challenge["nonce"],
                    expires_unix=challenge["expires_unix"],
                )
            )
        ).decode().rstrip("=")
        self.client.cookies.clear()
        exchanged = self.client.post(
            "/api/v1/auth/device/exchange",
            headers={"Origin": "https://ui.example.test"},
            json={"device_id": device_id, "challenge_id": challenge["challenge_id"], "signature": signature},
        )
        self.assertEqual(exchanged.status_code, 200, exchanged.text)
        self.assertNotIn("access_token", exchanged.text)
        self.assertNotIn("refresh_token", exchanged.text)
        set_cookie = "\n".join(exchanged.headers.get_list("set-cookie"))
        self.assertIn("tme3_access=", set_cookie)
        self.assertIn("tme3_refresh=", set_cookie)
        self.assertEqual(self.client.get("/api/v1/auth/browser/session").status_code, 200)
        headers["X-CSRF-Token"] = exchanged.cookies.get("tme3_csrf")

        # A new Telegram login retains the separate device session.
        self.auth._new_web_session(42)
        self.assertEqual(self.client.get("/api/v1/auth/browser/session").status_code, 200)
        revoked = self.client.delete(
            f"/api/v1/auth/devices/{device_id}", headers=headers
        )
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/browser/session").status_code, 401)

    def test_trusted_device_list_and_mutations_are_actor_scoped(self):
        headers = self.browser_login(42)
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        device_id = "fd9f67f1-bba8-4011-9ed3-0f819ac8df10"
        body = {
            "device_id": device_id,
            "name": "Owner laptop",
            "algorithm": "Ed25519",
            "public_key": base64.urlsafe_b64encode(public).decode().rstrip("="),
            "origin": "https://ui.example.test",
        }
        self.assertEqual(self.client.post("/api/v1/auth/devices", headers=headers, json=body).status_code, 201)

        actor_headers = self.browser_login(43, "csrf-other-actor")
        self.assertEqual(self.client.get("/api/v1/auth/devices").json()["items"], [])
        renamed = self.client.patch(
            f"/api/v1/auth/devices/{device_id}", headers=actor_headers, json={"name": "stolen"}
        )
        self.assertEqual(renamed.status_code, 404)

    def test_worker_profile_sync_persists_gateway_registry(self):
        response = self.client.post(
            "/internal/v1/profiles/sync",
            headers={"Authorization": "Bearer internal"},
            json={"profiles": [{"name": "remote-1", "telegram_user_id": 42}]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profiles"], ["remote-1"])
        self.assertEqual(self.profiles.profile_registry.profile_for_user(42), "remote-1")

    def test_web_profile_upload_and_stepwise_login_keep_private_input_out_of_response(self):
        headers = self.login()
        provisioner = FakeProfileProvisioner()
        self.context.profile_provisioner = provisioner

        denied = self.client.post(
            "/api/v1/profiles/provisionings/upload?name=novel&worker=local",
            content=b"zip",
            headers={"content-type": "application/zip"},
        )
        self.assertEqual(denied.status_code, 401)

        uploaded = self.client.post(
            "/api/v1/profiles/provisionings/upload?name=novel&worker=local",
            content=b"session-zip",
            headers={**headers, "content-type": "application/zip"},
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.json(), {"id": "operation-upload", "status": "distributing"})
        self.assertEqual(provisioner.uploaded[:3], ("novel", "local", b"session-zip"))

        secret_phone = "+62 812 0000 9999"
        started = self.client.post(
            "/api/v1/profiles/provisionings/login",
            headers=headers,
            json={"name": "novel", "worker": "local", "method": "code", "phone": secret_phone},
        )
        self.assertEqual(started.status_code, 200)
        self.assertNotIn(secret_phone, started.text)
        self.assertEqual(provisioner.login[3], secret_phone)

        state = self.client.get(
            "/api/v1/profiles/provisionings/operation-login", headers=headers
        )
        self.assertEqual(state.json()["login"]["step"], "qr")
        self.assertNotIn("actor_user_id", state.text)

    def test_profile_management_uses_fast_worker_health_check(self):
        headers = self.login()
        self.context.profile_provisioner = FakeProfileProvisioner()

        response = self.client.get("/api/v1/profiles/management", headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.dispatcher.fast_worker_checks, ["local"])
        self.assertTrue(response.json()["workers"][0]["online"])
        self.assertNotIn("secret", response.text)

    def test_worker_can_be_enabled_or_disabled_from_web_api(self):
        headers = self.login()

        disabled = self.client.patch(
            "/api/v1/workers/local",
            headers=headers,
            json={"enabled": False},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["enabled"])
        listed = self.client.get("/api/v1/workers", headers=headers)
        self.assertEqual(listed.status_code, 200)
        self.assertFalse(listed.json()["items"][0]["enabled"])

        rejected_route = self.client.put(
            "/api/v1/me/worker-route",
            headers=headers,
            json={"route": "local"},
        )
        self.assertEqual(rejected_route.status_code, 409)
        self.assertEqual(rejected_route.json()["error"]["code"], "WORKER_DISABLED")

        enabled = self.client.patch(
            "/api/v1/workers/local",
            headers=headers,
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)
        self.assertTrue(enabled.json()["enabled"])

    def test_worker_tts_health_is_manual_authenticated_and_profile_scoped(self):
        denied = self.client.get("/api/v1/workers/local/tts/health")
        self.assertEqual(denied.status_code, 401)
        headers = self.login()
        self.dispatcher.tts_health_result = {
            "helpers_ready": True,
            "available_profiles": ["default"],
            "helpers": [
                {"slot": slot, "status": "ready", "bootstrap_percent": 100, "checked_at": "now", "url": "http://private-helper"}
                for slot in range(1, 4)
            ],
        }
        ready = self.client.get("/api/v1/workers/local/tts/health", headers=headers)
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assertTrue(ready.json()["ready"])
        self.assertTrue(ready.json()["profile_session_ready"])
        self.assertNotIn("available_profiles", ready.json())
        self.assertNotIn("private-helper", ready.text)

        self.profiles.set_worker_route("default", "local")
        self.dispatcher.tts_health_result["available_profiles"] = []
        no_session = self.client.get("/api/v1/workers/local/tts/health", headers=headers)
        self.assertFalse(no_session.json()["ready"])
        self.assertTrue(no_session.json()["helpers_ready"])
        self.assertFalse(no_session.json()["profile_session_ready"])

    def test_worker_tts_helper_recovery_is_explicit_and_slot_limited(self):
        headers = self.login()
        denied = self.client.post("/api/v1/workers/local/tts/helpers/1/recover")
        self.assertEqual(denied.status_code, 401)
        accepted = self.client.post(
            "/api/v1/workers/local/tts/helpers/2/recover", headers=headers
        )
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(accepted.json(), {
            "worker": "local", "slot": 2, "accepted": True, "status": "restarting",
        })
        self.assertEqual(self.dispatcher.tts_recoveries, [("local", 2)])
        invalid = self.client.post(
            "/api/v1/workers/local/tts/helpers/4/recover", headers=headers
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.dispatcher.tts_recoveries, [("local", 2)])

    def test_worker_tts_recovery_forwards_helper_busy_without_internal_details(self):
        from tme3bot.infrastructure.http_client import JsonHttpError

        headers = self.login()
        self.dispatcher.recover_tts_helper = lambda worker, slot: (_ for _ in ()).throw(
            JsonHttpError(409, "Helper busy", {"error": {
                "code": "TTS_HELPER_BUSY", "message": "Helper sedang memproses sintesis.",
                "details": {"active_requests": 3, "worker_path": "/private/path"},
            }})
        )
        response = self.client.post(
            "/api/v1/workers/local/tts/helpers/1/recover", headers=headers
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "TTS_HELPER_BUSY")
        self.assertNotIn("private/path", response.text)
        self.assertNotIn("active_requests", response.text)

    def test_worker_storage_profile_can_be_read_and_updated_from_web(self):
        headers = self.login()

        current = self.client.get("/api/v1/workers/local/settings", headers=headers)
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["storage_profile"], "storage")
        self.assertNotIn("token", current.json())

        updated = self.client.put(
            "/api/v1/workers/local/settings",
            headers=headers,
            json={"storage_profile": "archive"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["storage_profile"], "archive")

        rejected = self.client.put(
            "/api/v1/workers/local/settings",
            headers=headers,
            json={"storage_profile": "missing"},
        )
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()["error"]["code"], "STORAGE_PROFILE_UNAVAILABLE")

    def test_backup_runtime_settings_are_persisted_and_applied_immediately(self):
        headers = self.login()
        response = self.client.put(
            "/api/v1/backups/settings",
            headers=headers,
            json={
                "enabled": False,
                "schedule": "04:15",
                "timezone": "Asia/Jakarta",
                "retention": 12,
                "volume_size": "2g",
                "channel": "789",
                "storage_trash_retention_days": 45,
                "job_stall_timeout_seconds": 900,
                "job_cancel_grace_seconds": 60,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])
        self.assertEqual(response.json()["channel"], "789")
        self.assertEqual(self.client.get("/api/v1/backups/status", headers=headers).json()["schedule"], "04:15")
        self.assertEqual(self.context.config.backup_channel_id, -100789)
        self.assertEqual(self.context.control_plane.job_stall_timeout_seconds, 900)

    def test_backup_runtime_settings_reject_invalid_timezone_without_applying(self):
        headers = self.login()
        response = self.client.put(
            "/api/v1/backups/settings",
            headers=headers,
            json={
                "enabled": True,
                "schedule": "04:15",
                "timezone": "Not/A_Timezone",
                "retention": 12,
                "volume_size": "2g",
                "channel": "789",
                "storage_trash_retention_days": 45,
                "job_stall_timeout_seconds": 900,
                "job_cancel_grace_seconds": 60,
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.context.config.backup_schedule, "03:00")

    def test_backup_settings_accept_public_tme_link_and_resolve_bot_api_id(self):
        headers = self.login()
        response = self.client.put(
            "/api/v1/backups/settings",
            headers=headers,
            json={
                "enabled": False,
                "schedule": "04:15",
                "timezone": "Asia/Jakarta",
                "retention": 12,
                "volume_size": "2g",
                "channel": "https://t.me/BackupChannel",
                "storage_trash_retention_days": 45,
                "job_stall_timeout_seconds": 900,
                "job_cancel_grace_seconds": 60,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["channel"], "backupchannel")
        self.assertEqual(self.bot.chat_lookups, ["@backupchannel"])
        self.assertEqual(self.context.config.backup_channel_id, -100987654321)
        self.assertEqual(self.context.config.backup_channel_ref, "backupchannel")

    def test_web_managed_telegram_credentials_are_write_only_and_bootstrap_is_service_only(self):
        headers = self.login()
        secret = "987654:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"
        status = self.client.get("/api/v1/runtime/secrets", headers=headers)
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["telegram_bot_token_configured"])

        updated = self.client.put(
            "/api/v1/runtime/secrets",
            headers=headers,
            json={"bot_token": secret, "telegram_tts_chat_id": "-100123456789"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertNotIn(secret, updated.text)
        self.assertEqual(updated.json()["restart_required_services"], ["backend", "telegram"])

        denied = self.client.get("/internal/v1/telegram/bootstrap")
        self.assertEqual(denied.status_code, 401)
        bootstrap = self.client.get(
            "/internal/v1/telegram/bootstrap",
            headers={"Authorization": "Bearer frontend"},
        )
        self.assertEqual(bootstrap.status_code, 200)
        self.assertEqual(bootstrap.json()["bot_token"], secret)
        self.assertEqual(bootstrap.json()["telegram_tts_chat_id"], "-100123456789")
        public_status = self.client.get("/api/v1/runtime/secrets", headers=headers)
        self.assertTrue(public_status.json()["telegram_tts_chat_configured"])
        self.assertNotIn("-100123456789", public_status.text)
        chat_update = self.client.put(
            "/api/v1/runtime/secrets",
            headers=headers,
            json={"telegram_tts_chat_id": "-100987654321"},
        )
        self.assertEqual(chat_update.status_code, 200)
        self.assertEqual(chat_update.json()["restart_required_services"], [])

        rejected_secret = "short-secret"
        rejected = self.client.put(
            "/api/v1/runtime/secrets",
            headers=headers,
            json={"bot_token": rejected_secret},
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertNotIn(rejected_secret, rejected.text)

        invalid_chat = self.client.put(
            "/api/v1/runtime/secrets",
            headers=headers,
            json={"telegram_tts_chat_id": "@not-a-numeric-id"},
        )
        self.assertEqual(invalid_chat.status_code, 422)
        self.assertNotIn("@not-a-numeric-id", invalid_chat.text)

        public_username = self.client.put(
            "/api/v1/runtime/secrets",
            headers=headers,
            json={"telegram_tts_chat_id": "https://t.me/IYear"},
        )
        self.assertEqual(public_username.status_code, 200)
        self.assertEqual(
            self.context.runtime_settings.get()["telegram_tts_chat_id"], "iyear"
        )
        self.assertEqual(public_username.json()["restart_required_services"], [])

        phone_target = self.client.put(
            "/api/v1/runtime/secrets",
            headers=headers,
            json={"telegram_tts_chat_id": "+1 123456789"},
        )
        self.assertEqual(phone_target.status_code, 200)

    def test_tts_tor_secret_is_not_required_or_stored(self):
        headers = self.login()
        secret = "tor-password-is-write-only"
        updated = self.client.put(
            "/api/v1/workers/local/settings",
            headers=headers,
            json={
                "tts_tor_control_password": secret,
                "tts_part_retries": 6,
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertNotIn(secret, updated.text)
        self.assertNotIn("tts_tor_control_password_configured", updated.json())

    def test_worker_api_token_rotation_updates_worker_then_gateway_registry(self):
        headers = self.login()
        secret = "new-worker-token-long-enough-123"
        response = self.client.put(
            "/api/v1/workers/local",
            headers=headers,
            json={"url": "http://worker", "token": secret},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(secret, response.text)
        self.assertEqual(self.workers.get("local")["token"], secret)
        self.assertTrue(self.dispatcher.runtime_settings["worker_api_token_configured"])

    def insert_storage_item(self):
        return self.catalog.insert_item(
            upload_id="upload-1",
            owner_user_id=42,
            owner_profile="default",
            channel_id=-100123,
            channel_message_id=9,
            original_name="original.txt",
            display_name="Original",
            folder="old",
            keywords="alpha",
            caption="caption",
            file_size=10,
            mime_type="text/plain",
            sha256="abc",
            status="active",
        )

    def test_login_and_openapi_hide_internal_routes(self):
        headers = self.login()
        me = self.client.get("/api/v1/me", headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["telegram_user_id"], 42)
        paths = self.client.get("/api/v1/openapi.json").json()["paths"]
        self.assertIn("/api/v1/me", paths)
        self.assertFalse(any(path.startswith("/internal/") for path in paths))
        job_schema = paths["/api/v1/jobs"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        self.assertEqual(
            job_schema["$ref"], "#/components/schemas/JobListResponse"
        )

    def test_authorized_browser_can_select_any_existing_profile_by_header(self):
        headers = self.login()
        headers["X-Profile"] = "archive"
        me = self.client.get("/api/v1/me", headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["profile"], "archive")
        missing = dict(headers)
        missing["X-Profile"] = "missing"
        self.assertEqual(
            self.client.get("/api/v1/me", headers=missing).status_code, 404
        )

    def test_download_rejects_unavailable_and_pins_artifact_origin(self):
        headers = self.login()
        unavailable = self.export_catalog.upsert(
            profile="default",
            worker="local",
            filename="missing.json",
            artifact_key="missing.json",
            status="pending",
            available=False,
        )
        response = self.client.post(
            "/api/v1/downloads",
            headers=headers,
            json={"artifact_ids": [unavailable["id"]]},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "ARTIFACT_UNAVAILABLE")

        remote = self.export_catalog.upsert(
            profile="default",
            worker="remote-1",
            filename="remote.json",
            artifact_key="remote.json",
            status="pending",
        )
        self.workers.values["remote-1"] = {"url": "http://remote", "token": "secret"}
        response = self.client.post(
            "/api/v1/downloads",
            headers=headers,
            json={"artifact_ids": [remote["id"]]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["worker"], "remote-1")
        self.assertEqual(response.json()["profile"], "default")

    def test_download_artifact_list_can_filter_worker_and_availability(self):
        headers = self.login()
        self.export_catalog.upsert(
            profile="default",
            worker="local",
            filename="available.json",
            artifact_key="available.json",
            status="pending",
        )
        self.export_catalog.upsert(
            profile="default",
            worker="local",
            filename="missing.json",
            artifact_key="missing.json",
            status="pending",
            available=False,
        )
        self.export_catalog.upsert(
            profile="default",
            worker="remote-1",
            filename="remote.json",
            artifact_key="remote.json",
            status="pending",
        )
        response = self.client.get(
            "/api/v1/downloads/artifacts?worker=local&available=true",
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(
            response.json()["items"][0]["artifact_key"], "available.json"
        )

    def test_download_artifact_list_can_filter_label_and_chat_ref(self):
        headers = self.login()
        self.export_catalog.upsert(
            profile="default", worker="local", filename="labelled.json",
            artifact_key="labelled.json", status="pending",
            label="Archive JS", chat_ref="@ExampleChannel",
        )
        self.export_catalog.upsert(
            profile="default", worker="local", filename="other.json",
            artifact_key="other.json", status="pending",
            label="Other", chat_ref="987654321",
        )
        response = self.client.get(
            "/api/v1/downloads/artifacts?scope=global&label=archive&chat_ref=examplechannel",
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["artifact_key"], "labelled.json")

    def test_global_artifact_scope_and_batch_pin_each_origin(self):
        headers = self.login()
        self.workers.values["remote-1"] = {"url": "http://remote", "token": "secret"}
        first = self.export_catalog.upsert(
            profile="default", worker="local", filename="local.json",
            artifact_key="local.json", status="pending"
        )
        second = self.export_catalog.upsert(
            profile="archive", worker="remote-1", filename="remote.json",
            artifact_key="remote.json", status="pending"
        )
        listing = self.client.get(
            "/api/v1/downloads/artifacts?scope=global", headers=headers
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["total"], 2)
        response = self.client.post(
            "/api/v1/downloads/batch", headers=headers,
            json={"artifact_ids": [first["id"], second["id"]]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["groups"]), 2)
        self.assertEqual(
            {(item["profile"], item["worker"]) for item in response.json()["groups"]},
            {("default", "local"), ("archive", "remote-1")},
        )

    def test_context_checker_returns_verified_target(self):
        headers = self.login()
        response = self.client.post(
            "/api/v1/context/verify", headers=headers,
            json={"purpose": "export", "profile": "archive", "worker": "local"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["verified"])
        self.assertEqual(response.json()["profile"], "archive")
        self.assertEqual(response.json()["worker"], "local")

    def test_job_metrics_include_worker_activity_and_queue_wait(self):
        headers = self.login()
        for message_id in (20, 21):
            self.client.post(
                "/api/v1/exports",
                headers=headers,
                json={"url": f"https://t.me/c/123/{message_id}"},
            )

        response = self.client.get("/api/v1/jobs/metrics", headers=headers)

        self.assertEqual(response.status_code, 200)
        metrics = response.json()
        self.assertEqual(metrics["active_jobs"], 1)
        self.assertEqual(metrics["queued_jobs"], 1)
        self.assertEqual(metrics["workers"][0]["worker"], "local")
        self.assertEqual(metrics["workers"][0]["status"], "busy")
        self.assertIsNotNone(metrics["average_queue_wait_seconds"])

    def test_worker_event_latency_and_phase_timing_are_scoped_to_owner_job(self):
        headers = self.login()
        job = self.client.post(
            "/api/v1/exports",
            headers=headers,
            json={"url": "https://t.me/c/123/22"},
        ).json()
        event_headers = {"Authorization": "Bearer internal"}
        sent_at = (datetime.now(timezone.utc) - timedelta(milliseconds=250)).isoformat()

        wrong_worker = self.client.post(
            f"/internal/v1/jobs/{job['id']}/events",
            headers=event_headers,
            json={
                "sequence": 2,
                "status": "running",
                "event_type": "started",
                "worker": "remote-1",
                "progress": {"phase": "downloading", "item": {"percent": 10}},
            },
        )
        self.assertEqual(wrong_worker.status_code, 403)
        self.assertEqual(wrong_worker.json()["error"]["code"], "JOB_WORKER_MISMATCH")
        self.assertNotIn("item", self.control.jobs.get(job["id"]).progress)

        started = self.client.post(
            f"/internal/v1/jobs/{job['id']}/events",
            headers=event_headers,
            json={
                "sequence": 2,
                "status": "running",
                "event_type": "started",
                "worker": "local",
                "sent_at": sent_at,
                "progress": {"phase": "downloading"},
            },
        )
        self.assertEqual(started.status_code, 200)
        observability = started.json()["job"]["progress"]["observability"]
        self.assertEqual(observability["event_latency"]["count"], 1)
        self.assertGreaterEqual(observability["event_latency"]["average_ms"], 200)
        self.assertEqual(observability["phase"], "downloading")
        self.assertIsNotNone(observability["phase_started_at"])

        changed_phase = self.client.post(
            f"/internal/v1/jobs/{job['id']}/events",
            headers=event_headers,
            json={
                "sequence": 3,
                "status": "running",
                "event_type": "progress.snapshot",
                "worker": "local",
                "transient": True,
                "progress": {"phase": "compressing"},
            },
        )
        self.assertEqual(changed_phase.status_code, 200)
        observability = changed_phase.json()["job"]["progress"]["observability"]
        self.assertIn("downloading", observability["phase_durations_seconds"])
        self.assertEqual(observability["phase"], "compressing")

    def test_browser_cookie_login_refresh_profile_and_logout_keep_tokens_out_of_json(self):
        challenge = self.client.post("/api/v1/auth/browser/challenge")
        self.assertEqual(challenge.status_code, 200)
        body = challenge.json()
        self.assertNotIn("poll_token", body)
        self.assertIn("tme3_poll", self.client.cookies)
        code = body["verification_uri"].split("login_", 1)[1]
        approved = self.client.post(
            f"/internal/v1/auth/telegram/challenges/{code}/approve",
            headers={"Authorization": "Bearer frontend"},
            json={"telegram_user_id": 42},
        )
        self.assertEqual(approved.status_code, 200)
        session = self.client.get("/api/v1/auth/browser/challenge")
        self.assertEqual(session.status_code, 200)
        self.assertTrue(session.json()["authenticated"])
        self.assertNotIn("access_token", session.text)
        self.assertIn("tme3_access", self.client.cookies)
        self.assertEqual(self.client.get("/api/v1/me").status_code, 200)

        csrf = self.client.cookies.get("tme3_csrf")
        profile = self.client.put(
            "/api/v1/auth/browser/profile",
            headers={"X-CSRF-Token": csrf},
            json={"profile": "archive"},
        )
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["actor"]["profile"], "archive")
        self.assertEqual(
            self.client.post("/api/v1/auth/browser/refresh").status_code, 403
        )
        refreshed = self.client.post(
            "/api/v1/auth/browser/refresh", headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(refreshed.status_code, 200)
        logged_out = self.client.post(
            "/api/v1/auth/browser/logout", headers={"X-CSRF-Token": self.client.cookies.get("tme3_csrf")}
        )
        self.assertEqual(logged_out.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/me").status_code, 401)

    def test_submit_job_and_worker_events_are_json_only(self):
        headers = self.login()
        response = self.client.post(
            "/api/v1/exports",
            headers=headers,
            json={
                "url": "https://t.me/c/123/4",
                "use_url_message_id": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        job = response.json()
        command = self.dispatcher.commands[0][1]
        self.assertEqual(command["job_id"], job["id"])
        self.assertFalse(
            {"chat_id", "message_id", "panel_view_token"} & set(command)
        )

        stale = self.client.post(
            f"/internal/v1/jobs/{job['id']}/events",
            headers={"Authorization": "Bearer internal"},
            json={
                "sequence": 1,
                "status": "running",
                "event_type": "stale_worker_event",
            },
        )
        self.assertEqual(stale.status_code, 200)
        self.assertFalse(stale.json()["accepted"])

        running = self.client.post(
            f"/internal/v1/jobs/{job['id']}/events",
            headers={"Authorization": "Bearer internal"},
            json={
                "sequence": 2,
                "status": "running",
                "event_type": "progress",
                "progress": {"current": 1, "total": 2},
            },
        )
        self.assertEqual(running.status_code, 200)
        transient = self.client.post(
            f"/internal/v1/jobs/{job['id']}/events",
            headers={"Authorization": "Bearer internal"},
            json={
                "sequence": 3,
                "status": "running",
                "event_type": "progress.snapshot",
                "transient": True,
                "progress": {
                    "phase": "exporting",
                    "item": {"percent": 50},
                },
            },
        )
        self.assertEqual(transient.status_code, 200)
        self.assertEqual(
            transient.json()["job"]["progress"]["item"]["percent"], 50
        )
        log_snapshot = self.client.get(
            f"/api/v1/jobs/{job['id']}/log-snapshot",
            headers=headers,
        )
        self.assertEqual(log_snapshot.status_code, 200)
        self.assertEqual(log_snapshot.json()["source"], "worker")
        self.assertEqual(log_snapshot.json()["log"]["line_count"], 1)
        self.assertEqual(log_snapshot.json()["log"]["order"], "newest_first")
        completed = self.client.post(
            f"/internal/v1/jobs/{job['id']}/events",
            headers={"Authorization": "Bearer internal"},
            json={
                "sequence": 4,
                "status": "succeeded",
                "event_type": "completed",
                "result": {"ok": True},
            },
        )
        self.assertEqual(completed.status_code, 200)
        fetched = self.client.get(
            f"/api/v1/jobs/{job['id']}", headers=headers
        ).json()
        self.assertEqual(fetched["status"], "succeeded")
        self.assertEqual(fetched["result"], {"ok": True})
        events = self.client.get(
            f"/api/v1/jobs/{job['id']}/events", headers=headers
        ).json()["items"]
        self.assertNotIn("progress.snapshot", [event["event_type"] for event in events])

    def test_export_chat_ref_is_normalized_to_tdl_peer_selector(self):
        headers = self.login()
        for raw, expected in (
            ("@IYear", "iyear"),
            ("iyear", "iyear"),
            ("123456789", "123456789"),
            ("https://t.me/IYear", "iyear"),
            ("+1 123456789", "+1123456789"),
        ):
            with self.subTest(raw=raw):
                response = self.client.post(
                    "/api/v1/exports",
                    headers=headers,
                    json={"chat_ref": raw},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["payload"]["chat_ref"], expected)

        invalid = self.client.post(
            "/api/v1/exports",
            headers=headers,
            json={"chat_ref": "https://example.com/IYear"},
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["error"]["code"], "INVALID_CHAT_REF")

    def test_telegram_job_notification_is_service_authenticated_and_idempotent(self):
        headers = self.login()
        created = self.client.post(
            "/api/v1/exports",
            headers=headers,
            json={"url": "https://t.me/c/1/2", "use_url_message_id": True},
        )
        self.assertEqual(created.status_code, 200)
        job_id = created.json()["id"]
        service_headers = {"Authorization": "Bearer frontend"}
        first = self.client.post(
            f"/internal/v1/jobs/{job_id}/telegram-notifications",
            headers=service_headers,
            json={"telegram_user_id": 42, "telegram_chat_id": 42},
        )
        duplicate = self.client.post(
            f"/internal/v1/jobs/{job_id}/telegram-notifications",
            headers=service_headers,
            json={"telegram_user_id": 42, "telegram_chat_id": 42},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(
            first.json()["notification"]["id"], duplicate.json()["notification"]["id"]
        )
        pending = self.client.get(
            "/internal/v1/telegram-notifications/pending",
            headers=service_headers,
        )
        self.assertEqual(len(pending.json()["items"]), 1)
        notification_id = first.json()["notification"]["id"]
        updated = self.client.patch(
            f"/internal/v1/telegram-notifications/{notification_id}",
            headers=service_headers,
            json={
                "message_id": 999,
                "status": "terminal",
                "terminal_notified_at": "2026-01-01T00:00:00+00:00",
            },
        )
        self.assertEqual(updated.status_code, 200)
        pending_again = self.client.get(
            "/internal/v1/telegram-notifications/pending",
            headers=service_headers,
        )
        self.assertEqual(pending_again.json()["items"], [])

    def test_error_envelope_is_stable(self):
        response = self.client.get("/api/v1/me")
        self.assertEqual(response.status_code, 401)
        payload = response.json()["error"]
        self.assertEqual(payload["code"], "TOKEN_REQUIRED")
        self.assertTrue(payload["request_id"])

    def test_utility_settings_explain_allowed_values_without_exposing_password(self):
        headers = self.login()
        settings = self.client.get("/api/v1/utility/settings", headers=headers)
        self.assertEqual(settings.status_code, 200)
        self.assertNotIn("compress_password", settings.json())
        self.assertTrue(settings.json()["compress_password_configured"])
        self.assertEqual(settings.json()["rclone_destination"], "googledrive:backup")

        metadata = self.client.get("/api/v1/utility/settings/meta", headers=headers)
        self.assertEqual(metadata.status_code, 200)
        move = next(item for item in metadata.json()["items"] if item["key"] == "move_size")
        self.assertIn("500m", move["examples"])

        invalid = self.client.put(
            "/api/v1/utility/settings/compress_size",
            headers=headers,
            json={"value": "4"},
        )
        self.assertEqual(invalid.status_code, 400)

    def test_quick_export_requires_storage_and_redacts_settings(self):
        headers = self.login()
        self.dispatcher.storage_available = False
        rejected = self.client.post(
            "/api/v1/exports",
            headers=headers,
            json={"url": "https://t.me/c/1/2", "quick_mode": True},
        )
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()["error"]["code"], "STORAGE_PROFILE_UNAVAILABLE")

        self.dispatcher.storage_available = True
        created = self.client.post(
            "/api/v1/exports",
            headers=headers,
            json={"url": "https://t.me/c/1/2", "quick_mode": True},
        )
        self.assertEqual(created.status_code, 200)
        job = self.client.get(f"/api/v1/jobs/{created.json()['id']}", headers=headers).json()
        self.assertEqual(job["payload"]["quick_mode"], True)
        self.assertEqual(job["payload"]["quick_settings"]["compress_password"], "***")
        self.assertEqual(
            job["payload"]["quick_settings"]["rclone_destination"],
            "googledrive:backup",
        )
        command = self.dispatcher.commands[-1][1]
        self.assertNotEqual(command["payload"]["quick_settings"]["compress_password"], "***")
        self.assertTrue(command["payload"]["quick_settings"]["compress_password"])

    def test_storage_upload_can_snapshot_rclone_destination(self):
        headers = self.login()
        created = self.client.post(
            "/api/v1/storage/uploads",
            headers=headers,
            json={
                "folder_path": "/workspace/biasa",
                "worker": "local",
                "rclone_upload": True,
            },
        )
        self.assertEqual(created.status_code, 200)
        command = self.dispatcher.commands[-1][1]
        self.assertTrue(command["payload"]["rclone_upload"])
        self.assertEqual(
            command["payload"]["rclone_destination"], "googledrive:backup"
        )

    def test_terminate_all_active_jobs_endpoint_handles_stale_jobs(self):
        headers = self.login()
        created = self.client.post(
            "/api/v1/exports",
            headers=headers,
            json={"url": "https://t.me/c/123/4", "use_url_message_id": True},
        )
        self.assertEqual(created.status_code, 200)
        self.dispatcher.cancel = lambda worker, job_id: False

        terminated = self.client.post(
            "/api/v1/jobs/terminate-active", headers=headers
        )

        self.assertEqual(terminated.status_code, 200)
        self.assertEqual(terminated.json()["force_cancelled"], 1)
        self.assertEqual(
            self.client.get(f"/api/v1/jobs/{created.json()['id']}", headers=headers).json()["status"],
            "cancelled",
        )

    def test_quick_manager_filters_terminate_and_retries_without_exposing_password(self):
        headers = self.login()
        quick = self.client.post(
            "/api/v1/exports",
            headers=headers,
            json={"url": "https://t.me/c/123/5", "quick_mode": True},
        ).json()
        quick_id = quick["id"]
        self.control.append_worker_event(
            JobEvent(quick_id, 2, JobStatus.RUNNING, "progress", {"phase": "compressing"})
        )
        self.control.append_worker_event(
            JobEvent(quick_id, 3, JobStatus.FAILED, "failed", error={"message": "compress failed"})
        )
        normal = self.client.post(
            "/api/v1/exports",
            headers=headers,
            json={"url": "https://t.me/c/123/4"},
        ).json()

        listed = self.client.get(
            "/api/v1/jobs?scope=global&kind=export&quick_mode=true",
            headers=headers,
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["id"] for item in listed.json()["items"]], [quick_id])

        retried = self.client.post(f"/api/v1/jobs/{quick_id}/retry", headers=headers)
        self.assertEqual(retried.status_code, 200)
        retry_id = retried.json()["id"]
        self.assertEqual(retry_id, quick_id)
        active_listed = self.client.get(
            "/api/v1/jobs?scope=global&kind=export&quick_mode=true&status=queued,dispatched,running",
            headers=headers,
        )
        self.assertEqual(active_listed.status_code, 200)
        self.assertEqual([item["id"] for item in active_listed.json()["items"]], [quick_id])
        retry_job = self.client.get(f"/api/v1/jobs/{retry_id}", headers=headers).json()
        self.assertEqual(retry_job["worker"], quick["worker"])
        self.assertNotIn("secret", str(retry_job))
        self.assertEqual(self.jobs.command_payload(retry_id)["quick_retry"]["retry_phase"], "compressing")

        self.dispatcher.cancel = lambda worker, job_id: False
        terminated = self.client.post(
            "/api/v1/jobs/terminate-active?scope=global&kind=export&quick_mode=true",
            headers=headers,
        )
        self.assertEqual(terminated.status_code, 200)
        self.assertEqual(terminated.json()["total"], 1)
        self.assertEqual(
            self.client.get(f"/api/v1/jobs/{normal['id']}", headers=headers).json()["status"],
            "dispatched",
        )

    def test_quick_staging_scan_merges_orphan_and_recovery_creates_job_on_origin_worker(self):
        headers = self.login()
        self.dispatcher.quick_scan["local"] = {
            "worker": "local",
            "items": [{
                "stage_job_id": "orphan-1",
                "quick_operation_id": "op-1",
                "profile": "default",
                "worker": "local",
                "folder_name": "batch",
                "phase": "downloading",
                "resume_phase": "downloading",
                "json_present": True,
                "expected_media_count": 2,
                "actual_media_count": 1,
                "archive_parts": 0,
                "thumbnail_present": False,
                "tdl_export_present": True,
                "tdl_download_present": True,
                "staging_path": "/workspace/quickmode/orphan-1",
            }],
        }
        scanned = self.client.get("/api/v1/quick-mode/staging", headers=headers)
        self.assertEqual(scanned.status_code, 200)
        self.assertTrue(scanned.json()["items"][0]["orphan"])
        recovered = self.client.post(
            "/api/v1/quick-mode/recover",
            headers=headers,
            json={"worker": "local", "stage_job_id": "orphan-1", "profile": "default"},
        )
        self.assertEqual(recovered.status_code, 200)
        command = self.dispatcher.commands[-1][1]
        self.assertEqual(command["worker"], "local")
        self.assertEqual(command["payload"]["quick_retry"]["stage_job_id"], "orphan-1")
        self.assertNotIn("A1031@bokep@1031A", str(recovered.json()))

    def test_quick_staging_delete_removes_worker_folder_and_keeps_job_history(self):
        headers = self.login()

        deleted = self.client.delete(
            "/api/v1/quick-mode/staging/local/orphan-1",
            headers=headers,
        )

        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["stage_job_id"], "orphan-1")
        self.assertTrue(deleted.json()["deleted"])
        self.assertEqual(self.dispatcher.quick_deletions, [("local", "orphan-1")])
        self.assertEqual(self.jobs.list(kind="export", quick_mode=True), [])

    def test_quick_staging_delete_rejects_stage_with_active_backend_job(self):
        headers = self.login()
        active = self.control.submit_job(
            Actor(42, "default"),
            "export",
            {"url": "https://t.me/c/1/44", "quick_mode": True},
            worker="local",
        )

        deleted = self.client.delete(
            f"/api/v1/quick-mode/staging/local/{active.id}",
            headers=headers,
        )

        self.assertEqual(deleted.status_code, 409)
        self.assertEqual(deleted.json()["error"]["code"], "QUICKMODE_STAGE_BUSY")
        self.assertEqual(self.dispatcher.quick_deletions, [])

    def test_quick_staging_scan_verifies_inactive_uploading_folder(self):
        headers = self.login()
        self.dispatcher.quick_scan["local"] = {
            "worker": "local",
            "items": [{
                "stage_job_id": "uploaded-1",
                "folder_name": "batch",
                "phase": "uploading",
                "archive_parts": 2,
                "thumbnail_present": True,
                "staging_path": "/workspace/quickmode/uploaded-1",
            }],
        }

        response = self.client.get("/api/v1/quick-mode/staging", headers=headers)

        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertEqual(item["cleanup_verification"]["status"], "verified")
        self.assertTrue(item["staging_cleaned"])
        self.assertEqual(
            self.dispatcher.quick_verifications,
            [("local", "uploaded-1", "uploading")],
        )

    def test_quick_mode_limit_pause_and_resume_api_preserve_worker_fifo(self):
        headers = self.login()
        saved = self.client.put(
            "/api/v1/quick-mode/limits/local",
            headers=headers,
            json={"max_concurrent": 1},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["max_concurrent"], 1)

        first = self.control.submit_job(
            Actor(42, "default"),
            "export",
            {"url": "https://t.me/c/1/41", "quick_mode": True},
        )
        second = self.control.submit_job(
            Actor(42, "default"),
            "export",
            {"url": "https://t.me/c/1/42", "quick_mode": True},
            profile="archive",
        )
        self.assertEqual(first.status.value, "dispatched")
        self.assertEqual(second.status.value, "queued")

        limits = self.client.get("/api/v1/quick-mode/limits", headers=headers)
        self.assertEqual(limits.status_code, 200)
        self.assertEqual(limits.json()["items"][0]["active"], 1)
        self.assertEqual(limits.json()["items"][0]["queued"], 1)

        paused = self.client.post(f"/api/v1/jobs/{second.id}/pause", headers=headers)
        self.assertEqual(paused.status_code, 200)
        self.assertEqual(paused.json()["status"], "paused")
        resumed = self.client.post(f"/api/v1/jobs/{second.id}/resume", headers=headers)
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["status"], "queued")

        self.control.append_worker_event(JobEvent(first.id, 2, JobStatus.RUNNING, "started"))
        self.control.append_worker_event(JobEvent(first.id, 3, JobStatus.SUCCEEDED, "completed"))
        self.assertEqual(self.jobs.get(second.id).status, JobStatus.DISPATCHED)

    def test_quick_staging_scan_verifies_inactive_cleanup_folder(self):
        headers = self.login()
        self.dispatcher.quick_scan["local"] = {
            "worker": "local",
            "items": [{
                "stage_job_id": "cleanup-1",
                "folder_name": "batch",
                "phase": "cleanup",
                "archive_parts": 2,
                "thumbnail_present": True,
                "staging_path": "/workspace/quickmode/cleanup-1",
            }],
        }

        response = self.client.get("/api/v1/quick-mode/staging", headers=headers)

        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertEqual(item["cleanup_verification"]["status"], "verified")
        self.assertTrue(item["staging_cleaned"])
        self.assertEqual(
            self.dispatcher.quick_verifications,
            [("local", "cleanup-1", "cleanup")],
        )

    def test_quickmode_staging_excludes_backend_jobs_without_physical_folder(self):
        headers = self.login()
        # Create a quick mode export job in the database
        job_res = self.client.post(
            "/api/v1/exports",
            headers=headers,
            json={
                "chat_ref": "@past_channel",
                "profile": "default",
                "worker": "local",
                "quick_mode": True,
            },
        )
        self.assertEqual(job_res.status_code, 200)
        # Scanner reports empty items (meaning no physical folders on disk)
        self.dispatcher.quick_scan["local"] = {"worker": "local", "items": []}
        scanned = self.client.get("/api/v1/quick-mode/staging", headers=headers)
        self.assertEqual(scanned.status_code, 200)
        # Verify no items are returned since physical folder does not exist
        self.assertEqual(len(scanned.json()["items"]), 0)

    def test_quickmode_recover_honors_resume_phase_and_blocks_active_job(self):
        headers = self.login()
        # 1. Create a job that is active
        active_res = self.client.post(
            "/api/v1/exports",
            headers=headers,
            json={
                "chat_ref": "@stage_chan",
                "profile": "default",
                "worker": "local",
                "quick_mode": True,
            },
        )
        self.assertEqual(active_res.status_code, 200)
        active_job = active_res.json()

        # Trying to recover while job is active must return 409
        busy_res = self.client.post(
            "/api/v1/quick-mode/recover",
            headers=headers,
            json={
                "worker": "local",
                "stage_job_id": active_job["id"],
                "profile": "default",
                "resume_phase": "uploading",
            },
        )
        self.assertEqual(busy_res.status_code, 409)
        self.assertEqual(busy_res.json()["error"]["code"], "JOB_NOT_TERMINAL")

        # 2. Mark the job as failed (terminal)
        self.client.post(
            f"/internal/v1/jobs/{active_job['id']}/events",
            headers={"Authorization": "Bearer internal"},
            json={
                "sequence": 2,
                "status": "failed",
                "event_type": "failed",
                "progress": {"phase": "downloading"},
                "error": {"code": "DOWNLOAD_FAILED", "message": "network drop"},
            },
        )

        # 3. Recover with resume_phase="uploading"
        recovered = self.client.post(
            "/api/v1/quick-mode/recover",
            headers=headers,
            json={
                "worker": "local",
                "stage_job_id": active_job["id"],
                "profile": "default",
                "resume_phase": "uploading",
                "single_phase": True,
            },
        )
        self.assertEqual(recovered.status_code, 200)
        retried_job = recovered.json()["job"]
        command = self.dispatcher.commands[-1][1]
        self.assertEqual(command["job_id"], retried_job["id"])
        self.assertEqual(command["payload"]["quick_retry"]["resume_phase"], "uploading")
        self.assertEqual(command["payload"]["quick_retry"]["retry_phase"], "uploading")
        self.assertTrue(command["payload"]["quick_retry"]["single_phase"])
        self.assertEqual(command["payload"]["quick_phase"], "uploading")
        self.assertEqual(command["payload"]["quick_retry"]["stage_job_id"], active_job["id"])

    def test_storage_metadata_is_shared_for_all_authorized_users(self):
        item = self.insert_storage_item()
        headers = self.login(43)

        renamed = self.client.patch(
            f"/api/v1/storage/items/{item.id}",
            headers=headers,
            json={"display_name": "Shared rename"},
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["display_name"], "Shared rename")

        updated = self.client.patch(
            f"/api/v1/storage/items/{item.id}",
            headers=headers,
            json={"display_name": "Shared metadata", "folder": "shared-folder"},
        )
        self.assertEqual(updated.status_code, 200)
        current = self.catalog.get(item.id)
        self.assertEqual(current.display_name, "Shared metadata")
        self.assertEqual(current.folder, "shared-folder")

    def test_storage_capability_link_delivers_to_user_without_identity(self):
        item = self.insert_storage_item()
        token = sign_storage_item(item.id, "a" * 48)

        code_response = self.client.get(
            f"/api/v1/storage/items/{item.id}/deep-link",
            headers=self.login(42),
        )
        self.assertEqual(code_response.status_code, 200)
        self.assertEqual(code_response.json()["code"], token)

        delivered = self.client.post(
            f"/internal/v1/storage/deep-links/{token}/deliver",
            headers={"Authorization": "Bearer frontend"},
            json={"telegram_user_id": 99},
        )

        self.assertEqual(delivered.status_code, 200)
        self.assertEqual(delivered.json()["destination"], 99)
        self.assertEqual(self.bot.copy_calls[-1]["chat_id"], 99)
        denied = self.client.post(
            "/internal/v1/auth/telegram/exchange",
            headers={"Authorization": "Bearer frontend"},
            json={"telegram_user_id": 99},
        )
        self.assertEqual(denied.status_code, 403)

    def test_storage_capability_link_rejects_tampering_and_trash(self):
        item = self.insert_storage_item()
        token = sign_storage_item(item.id, "a" * 48)
        invalid = self.client.post(
            f"/internal/v1/storage/deep-links/{token}x/deliver",
            headers={"Authorization": "Bearer frontend"},
            json={"telegram_user_id": 99},
        )
        self.assertEqual(invalid.status_code, 400)

        self.catalog.trash_items([item.id], 42)
        unavailable = self.client.post(
            f"/internal/v1/storage/deep-links/{token}/deliver",
            headers={"Authorization": "Bearer frontend"},
            json={"telegram_user_id": 99},
        )
        self.assertEqual(unavailable.status_code, 410)
        self.assertEqual(
            unavailable.json()["error"]["code"], "STORAGE_ITEM_UNAVAILABLE"
        )

    def test_storage_browser_folder_and_trash_flow(self):
        item = self.insert_storage_item()
        headers = self.login()
        created = self.client.post(
            "/api/v1/storage/folders",
            headers=headers,
            json={"name": "Shared", "parent_id": None},
        )
        self.assertEqual(created.status_code, 200)
        folder_id = created.json()["id"]
        moved = self.client.post(
            "/api/v1/storage/actions/move",
            headers=headers,
            json={"item_ids": [item.id], "folder_ids": [], "destination_folder_id": folder_id},
        )
        self.assertEqual(moved.status_code, 200)
        browser = self.client.get(
            f"/api/v1/storage/browser?folder_id={folder_id}", headers=headers
        )
        self.assertEqual(browser.status_code, 200)
        self.assertEqual(browser.json()["items"][0]["folder"], "Shared")
        trashed = self.client.delete(
            f"/api/v1/storage/items/{item.id}", headers=headers
        )
        self.assertEqual(trashed.json()["status"], "trashed")

    def test_tts_submission_and_delivery_metadata_hide_text_and_artifact_refs(self):
        self.dispatcher.tts_ready = True
        self.jobs.set_tts_telegram_ready(True)
        headers = self.login()
        secret_text = "Teks rahasia untuk audio ini"
        marker = "PRIVATE-NOVEL-TEXT-"
        too_long = marker * 5_556
        invalid_length = self.client.post(
            "/api/v1/tts/jobs",
            headers=headers,
            json={"title": "Bab", "text": too_long},
        )
        self.assertEqual(invalid_length.status_code, 422)
        self.assertNotIn(marker, invalid_length.text)
        invalid_type = self.client.post(
            "/api/v1/tts/jobs",
            headers=headers,
            json={"title": "Bab", "text": {"private": marker}},
        )
        self.assertEqual(invalid_type.status_code, 422)
        self.assertNotIn(marker, invalid_type.text)

        unauthorized = self.client.post(
            "/api/v1/tts/jobs",
            json={"title": "Bab rahasia", "text": secret_text},
        )
        self.assertEqual(unauthorized.status_code, 401)

        created = self.client.post(
            "/api/v1/tts/jobs",
            headers=headers,
            json={"title": "Bab rahasia", "text": secret_text},
        )
        self.assertEqual(created.status_code, 200, created.text)
        job = created.json()
        self.assertEqual(job["kind"], "tts")
        self.assertEqual(job["payload"], {"title": "Bab rahasia", "character_count": len(secret_text)})
        self.assertNotIn(secret_text, created.text)
        internal_command = self.dispatcher.commands[-1][1]
        self.assertEqual(internal_command["payload"]["text"], secret_text)

        artifact_ref = "a" * 48
        registered = self.client.post(
            "/internal/v1/tts/artifacts/ready",
            headers={"Authorization": "Bearer internal"},
            json={
                "job_id": job["id"],
                "worker": "local",
                "parts": [{
                    "artifact_ref": artifact_ref,
                    "part_index": 1,
                    "total_parts": 1,
                    "byte_size": 512,
                }],
            },
        )
        self.assertEqual(registered.status_code, 200, registered.text)
        self.assertNotIn(artifact_ref, registered.text)
        self.assertEqual(
            self.client.post(
                "/internal/v1/tts/artifacts/ready",
                json={"job_id": job["id"], "worker": "local", "parts": []},
            ).status_code,
            401,
        )

        service_headers = {"Authorization": "Bearer frontend"}
        pending = self.client.get(
            "/internal/v1/tts/deliveries/pending", headers=service_headers
        )
        self.assertEqual(pending.status_code, 200, pending.text)
        pending_json = pending.json()
        self.assertEqual(len(pending_json["items"]), 1)
        self.assertNotIn(artifact_ref, pending.text)
        self.assertNotIn(secret_text, pending.text)
        self.assertNotIn("chat_id", pending.text.lower())

        public_job = self.client.get(
            f"/api/v1/jobs/{job['id']}", headers=headers
        )
        public_events = self.client.get(
            f"/api/v1/jobs/{job['id']}/events", headers=headers
        )
        self.assertNotIn(secret_text, public_job.text + public_events.text)
        self.assertNotIn(artifact_ref, public_job.text + public_events.text)
        self.assertNotIn("chat_id", (public_job.text + public_events.text).lower())

    def test_tts_requires_chat_and_ready_worker(self):
        headers = self.login()
        self.context.runtime_settings.update({"telegram_tts_chat_id": ""})
        not_ready = self.client.post(
            "/api/v1/tts/jobs",
            headers=headers,
            json={"title": "Bab", "text": "Teks"},
        )
        self.assertEqual(not_ready.status_code, 503)
        self.context.runtime_settings.update({"telegram_tts_chat_id": "123456789"})
        no_worker = self.client.post(
            "/api/v1/tts/jobs",
            headers=headers,
            json={"title": "Bab", "text": "Teks"},
        )
        self.assertEqual(no_worker.status_code, 503)
        self.assertEqual(no_worker.json()["error"]["code"], "TTS_WORKER_UNAVAILABLE")

    def test_tts_worker_delivery_claim_is_scoped_and_exposes_ref_only_internal(self):
        self.dispatcher.tts_ready = True
        headers = self.login()
        created = self.client.post(
            "/api/v1/tts/jobs",
            headers=headers,
            json={"title": "Bab", "text": "Isi"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        job_id = created.json()["id"]
        artifact_ref = "b" * 48
        registered = self.client.post(
            "/internal/v1/tts/artifacts/ready",
            headers={"Authorization": "Bearer internal"},
            json={
                "job_id": job_id,
                "worker": "local",
                "parts": [{
                    "artifact_ref": artifact_ref,
                    "part_index": 1,
                    "total_parts": 1,
                    "byte_size": 512,
                }],
            },
        )
        self.assertEqual(registered.status_code, 200, registered.text)
        self.assertEqual(registered.json()["chat_ref"], "123456789")

        pending_path = f"/internal/v1/tts/deliveries/worker-pending?worker=local&job_id={job_id}"
        self.assertEqual(self.client.get(pending_path).status_code, 401)
        wrong_worker = self.client.get(
            pending_path.replace("worker=local", "worker=remote"),
            headers={"Authorization": "Bearer internal"},
        )
        self.assertEqual(wrong_worker.status_code, 403)
        pending = self.client.get(
            pending_path,
            headers={"Authorization": "Bearer internal"},
        )
        self.assertEqual(pending.status_code, 200, pending.text)
        item = pending.json()["items"][0]
        self.assertEqual(item["artifact_ref"], artifact_ref)
        delivery_id = item["id"]
        denied = self.client.patch(
            f"/internal/v1/tts/deliveries/{delivery_id}/worker-result",
            headers={"Authorization": "Bearer internal"},
            json={"worker": "remote", "delivered": True},
        )
        self.assertEqual(denied.status_code, 403)
        completed = self.client.patch(
            f"/internal/v1/tts/deliveries/{delivery_id}/worker-result",
            headers={"Authorization": "Bearer internal"},
            json={"worker": "local", "delivered": True},
        )
        self.assertEqual(completed.status_code, 200, completed.text)

    def test_tts_worker_options_and_explicit_worker_selection(self):
        self.dispatcher.tts_ready = True
        self.jobs.set_tts_telegram_ready(True)
        self.workers.upsert("remote-tts", "http://remote-tts", "remote-token")
        headers = self.login()

        options = self.client.get("/api/v1/tts/workers", headers=headers)
        self.assertEqual(options.status_code, 200, options.text)
        self.assertEqual(
            {item["name"] for item in options.json()["items"]},
            {"local", "remote-tts"},
        )
        self.assertTrue(all(item["queued_jobs"] == 0 for item in options.json()["items"]))

        created = self.client.post(
            "/api/v1/tts/jobs",
            headers=headers,
            json={"title": "Bab", "text": "Isi", "worker": "remote-tts"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["worker"], "remote-tts")
        self.assertEqual(self.dispatcher.commands[-1][0], "remote-tts")


if __name__ == "__main__":
    unittest.main()
