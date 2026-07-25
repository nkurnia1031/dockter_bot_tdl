import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tme3bot.api.backend import BackendContext, create_backend_app
from tme3bot.application.control_plane import ControlPlane
from tme3bot.domain.models import Actor
from tme3bot.infrastructure.auth import BotAuthService, SqliteAuthRepository
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.profile_registry import ProfileRegistry
from tme3bot.storage_catalog import StorageCatalog
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

    def dispatch(self, worker, payload):
        self.commands.append((worker, payload))
        return {"position": 1}

    def cancel(self, worker, job_id):
        return True


class FakeWorkers:
    def __init__(self):
        self.values = {"local": {"url": "http://worker", "token": "secret"}}

    def list(self):
        return dict(self.values)

    def names(self):
        return sorted(self.values)

    def get(self, name):
        return self.values.get(name)

    def upsert(self, name, url, token):
        self.values[name] = {"url": url, "token": token}
        return name

    def remove(self, name):
        return self.values.pop(name, None) is not None


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
        self.catalog = StorageCatalog(db)
        self.workers = FakeWorkers()
        self.control = ControlPlane(
            self.jobs,
            self.dispatcher,
            self.profiles,
            storage_catalog=self.catalog,
            worker_registry=self.workers,
        )
        self.auth = BotAuthService(
            SqliteAuthRepository(db),
            self.control.actor,
            "a" * 48,
            "my_bot",
        )
        config = type(
            "Config",
            (),
            {
                "frontend_service_token": "frontend",
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
            },
        )()
        context = BackendContext(
            config=config,
            control_plane=self.control,
            auth=self.auth,
            profile_manager=self.profiles,
            storage_catalog=self.catalog,
            worker_registry=self.workers,
            utility_folders=UtilityFolderStore(
                root / "folders.json", root / "workspace"
            ),
            utility_settings=UtilitySettingsStore(root / "settings.json"),
        )
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

    def test_worker_profile_sync_persists_gateway_registry(self):
        response = self.client.post(
            "/internal/v1/profiles/sync",
            headers={"Authorization": "Bearer internal"},
            json={"profiles": [{"name": "remote-1", "telegram_user_id": 42}]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profiles"], ["remote-1"])
        self.assertEqual(self.profiles.profile_registry.profile_for_user(42), "remote-1")

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
        completed = self.client.post(
            f"/internal/v1/jobs/{job['id']}/events",
            headers={"Authorization": "Bearer internal"},
            json={
                "sequence": 3,
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

    def test_storage_rename_is_shared_but_owned_metadata_is_atomic(self):
        item = self.insert_storage_item()
        headers = self.login(43)

        renamed = self.client.patch(
            f"/api/v1/storage/items/{item.id}",
            headers=headers,
            json={"display_name": "Shared rename"},
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["display_name"], "Shared rename")

        denied = self.client.patch(
            f"/api/v1/storage/items/{item.id}",
            headers=headers,
            json={"display_name": "Must not persist", "folder": "forbidden"},
        )
        self.assertEqual(denied.status_code, 403)
        current = self.catalog.get(item.id)
        self.assertEqual(current.display_name, "Shared rename")
        self.assertEqual(current.folder, "old")


if __name__ == "__main__":
    unittest.main()
