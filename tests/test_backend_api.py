import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tme3bot.api.backend import BackendContext, create_backend_app
from tme3bot.application.control_plane import ControlPlane
from tme3bot.domain.models import Actor
from tme3bot.export_catalog import ExportArtifactCatalog
from tme3bot.infrastructure.auth import BotAuthService, SqliteAuthRepository
from tme3bot.infrastructure.job_store import SqliteJobRepository
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

    def dispatch(self, worker, payload):
        self.commands.append((worker, payload))
        return {"position": 1}

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

    def copy_message(self, **values):
        self.copy_calls.append(values)
        return type("CopiedMessage", (), {"message_id": 777})()


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
        command = self.dispatcher.commands[-1][1]
        self.assertNotEqual(command["payload"]["quick_settings"]["compress_password"], "***")
        self.assertTrue(command["payload"]["quick_settings"]["compress_password"])

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


if __name__ == "__main__":
    unittest.main()
