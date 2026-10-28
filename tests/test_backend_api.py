import hashlib
import tempfile
import unittest
import base64
import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tme3bot.api.backend import BackendContext, create_backend_app, job_dict
from tme3bot.backend_runtime_settings import BackendRuntimeSettings
from tme3bot.application.control_plane import ControlPlane
from tme3bot.application.operations import OperationsService, PreparedOperation
from tme3bot.application.runtime_readiness import RuntimeReadinessGate
from tme3bot.domain.models import Actor, DomainError, Job, JobEvent, JobStatus
from tme3bot.export_catalog import ExportArtifactCatalog
from tme3bot.infrastructure.auth import BotAuthService, SqliteAuthRepository
from tme3bot.infrastructure.activity_journal import ActivityJournalStore
from tme3bot.infrastructure.decrypt_history_store import SqliteDecryptHistoryStore
from tme3bot.infrastructure.device_auth import DeviceAuthService, challenge_payload
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.infrastructure.local_profile_catalog import LocalProfileCatalog
from tme3bot.infrastructure.profile_scan_store import ProfileScanOperationStore
from tme3bot.infrastructure.operation_store import SqliteOperationStore
from tme3bot.infrastructure.runtime_readiness_store import RuntimeReadinessStore
from tme3bot.infrastructure.settings_store import SqliteSettingsStore
from tme3bot.infrastructure.tdl_access_store import SqliteTdlAccessStore
from tme3bot.profile_provisioning import ProfileProvisioningStore, build_profile_bundle
from tme3bot.profile_distribution_store import ProfileDistributionStore
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


class JobDictionaryTests(unittest.TestCase):
    def test_storage_retryable_requires_a_terminal_job_and_safe_file(self):
        base = {
            "id": "storage-job",
            "kind": "storage_upload",
            "profile": "default",
            "actor_user_id": 42,
            "worker": "local",
            "payload": {},
            "result": {
                "value": {
                    "items": [
                        {"status": "failed", "retryable": True},
                        {"status": "needs_reconciliation", "retryable": False},
                    ]
                }
            },
        }

        active = Job(status=JobStatus.RUNNING, **base)
        terminal = Job(status=JobStatus.FAILED, **base)
        cancelled = Job(status=JobStatus.CANCELLED, **base)
        ambiguous_only = Job(
            status=JobStatus.FAILED,
            **{
                **base,
                "result": {
                    "value": {
                        "items": [
                            {"status": "needs_reconciliation", "retryable": False}
                        ]
                    }
                },
            },
        )

        self.assertFalse(job_dict(active)["retryable"])
        self.assertTrue(job_dict(terminal)["retryable"])
        self.assertTrue(job_dict(cancelled)["retryable"])
        self.assertFalse(job_dict(ambiguous_only)["retryable"])


class FakeDispatcher:
    def __init__(self):
        self.commands = []
        self.durable_commands = []
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
        self.tts_health_calls = []
        self.tts_recoveries = []
        self.storage_fingerprint_overrides = {}
        self.profile_sync_requests = []
        self.profile_sync_snapshot = {
            "status": "waiting_worker",
            "backend_available": False,
            "backend_error_code": "PROFILE_TRANSFER_REQUIRES_HTTPS",
            "last_checked_at": "2026-10-10T00:00:00Z",
            "profiles": {
                "default": {
                    "status": "waiting_worker",
                    "error_code": "BACKEND_UNAVAILABLE",
                    "desired_revision": 4,
                    "installed_revision": 3,
                    "bundle_sha256": "private-hash",
                }
            },
            "queued_requests": [{"profile": "default", "mode": "check"}],
        }
        self.profile_tdl_diagnostic_calls = []
        self.profile_readiness_canary_calls = []
        self.profile_readiness_canaries = {}
        self.profile_readiness_canary_messages = []
        self.profile_tdl_diagnostic_result = {
            "worker": "local",
            "profile": "default",
            "checked_at": "2026-10-11T06:46:22+00:00",
            "ready": True,
            "identity_match": True,
            "reason_codes": [],
            "sessions": [
                {"name": name, "ready": True, "code": "OK", "identity_matches_metadata": True}
                for name in ("root", "user1")
            ],
        }
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

    def capabilities(self, worker):
        del worker
        health = dict(self.tts_health_result)
        if self.tts_ready:
            health["helpers_ready"] = True
            health["helpers"] = [
                {"slot": slot, "status": "ready", "bootstrap_percent": 100, "checked_at": "now"}
                for slot in range(1, 4)
            ]
        # Profile sessions are independent of addon readiness. TTS capability
        # still follows helper health, while Storage and other TDL jobs can
        # use the same local session inventory without a TTS helper.
        profiles = list(health.get("available_profiles") or [])
        storage_fingerprints = {
            profile: self.storage_fingerprint_overrides.get(
                profile,
                hashlib.sha256(f"upload-session:{profile}".encode("utf-8")).hexdigest(),
            )
            for profile in profiles
        }
        return {
            "tts": self.tts_ready,
            "capabilities": ["tts"] if self.tts_ready else [],
            "tts_profiles": profiles if self.tts_ready else [],
            "profiles": profiles,
            "export_profiles": profiles,
            "available_storage_profiles": profiles,
            "storage_upload_fingerprints": storage_fingerprints,
            "tts_health": health,
        }

    def tts_health(self, worker):
        self.tts_health_calls.append(worker)
        return dict(self.tts_health_result)

    def recover_tts_helper(self, worker, slot):
        self.tts_recoveries.append((worker, slot))
        return {"accepted": True, "status": "restarting"}

    def profile_sync_status(self, worker):
        del worker
        return self.profile_sync_snapshot

    def profile_tdl_diagnostics(self, worker, profile):
        self.profile_tdl_diagnostic_calls.append((worker, profile))
        return {
            **self.profile_tdl_diagnostic_result,
            "sessions": [dict(item) for item in self.profile_tdl_diagnostic_result["sessions"]],
        }

    def start_profile_readiness_canary(self, worker, profile, storage_target, tts_target):
        from uuid import uuid4

        self.profile_readiness_canary_calls.append((worker, profile, storage_target, tts_target))
        diagnostic = self.profile_tdl_diagnostics(worker, profile)
        fingerprint = str(diagnostic.get("fingerprint") or "")
        upload_fingerprint = self.capabilities(worker)["storage_upload_fingerprints"].get(profile, "")
        operation = {
            "id": str(uuid4()),
            "profile": profile,
            "status": "succeeded",
            "phase": "complete",
            "checks": {
                name: {"ready": True, "reason_code": ""}
                for name in ("export", "download", "upload", "storage", "tts")
            },
            "messages": list(self.profile_readiness_canary_messages),
            "session_fingerprint": fingerprint,
            "upload_session_fingerprint": upload_fingerprint,
            "error_code": "",
        }
        self.profile_readiness_canaries[operation["id"]] = operation
        return dict(operation)

    def profile_readiness_canary(self, _worker, operation_id):
        operation = self.profile_readiness_canaries.get(operation_id)
        return dict(operation) if operation else None

    def request_profile_sync(self, worker, *, profile=None, mode="check"):
        self.profile_sync_requests.append((worker, profile, mode))
        return {"accepted": True, "status": "sync_pending", "profile": profile}

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
        self.delete_calls = []
        self.delete_error = False

    def get_chat(self, chat_id):
        self.chat_lookups.append(chat_id)
        return type("Chat", (), {"id": -100987654321, "username": "backupchannel", "title": "Backup"})()

    def copy_message(self, **values):
        self.copy_calls.append(values)
        return type("CopiedMessage", (), {"message_id": 777})()

    def delete_message(self, **values):
        self.delete_calls.append(values)
        if self.delete_error:
            raise RuntimeError("Bot API deletion denied")
        return True


class FakeProfileProvisioner:
    def __init__(self):
        self.uploaded = None
        self.login = None
        self.delete_vault_call = None
        self.store = FakeDiagnosticStore()

    def profiles(self, actor_user_id=None):
        del actor_user_id
        return [{"name": "default", "active": True, "status": "legacy", "vault": False, "workers": []}]

    def upload(self, name, worker, data, actor_user_id, *, local_only=False):
        self.uploaded = (name, worker, data, actor_user_id, local_only)
        return "operation-upload"

    def start_login(self, name, worker, method, phone, actor_user_id, *, local_only=False):
        self.login = (name, worker, method, phone, actor_user_id, local_only)
        return "operation-login"

    def operation(self, operation_id, actor_user_id):
        if operation_id != "operation-login" or actor_user_id != 42:
            raise KeyError(operation_id)
        return {"id": operation_id, "profile": "novel", "status": "authenticating", "login": {"step": "qr", "qr_text": "qr-payload"}, "workers": []}

    def login_input(self, operation_id, actor_user_id, field, value):
        self.login_input_call = (operation_id, actor_user_id, field, value)
        return {"status": "waiting_input", "step": "password"}

    def diagnose_adoption(self, profile, worker, actor_user_id):
        self.store.append_diagnostic_log(
            category="profile_export",
            actor_user_id=actor_user_id,
            profile=profile,
            worker=worker,
            event_type="source_check",
            code="PROFILE_SOURCE_READY",
            details={"ready": True},
        )
        return {
            "profile": profile,
            "worker": worker,
            "ready": True,
            "reason_codes": [],
            "checks": [{"name": "root_session", "ready": True, "code": "PROFILE_ROOT_SESSION_READY"}],
            "logs_url": "/api/v1/diagnostics/profile-exports/logs?limit=100",
        }

    def retry(self, operation_id, actor_user_id, source_worker=None):
        self.retry_call = (operation_id, actor_user_id, source_worker)
        return None

    def cancel(self, operation_id, actor_user_id):
        return {"cancelled": True}

    def adopt(self, profile, worker, actor_user_id):
        self.adopt_call = (profile, worker, actor_user_id)
        return "operation-adopt"

    def delete_vault_bundle(self, profile, actor_user_id):
        self.delete_vault_call = (profile, actor_user_id)
        return {"deleted": True, "profile": profile, "local_copies_unchanged": True}


class FakeDiagnosticStore:
    def __init__(self):
        self.logs = []

    def append_diagnostic_log(self, **values):
        self.logs.append(dict(values))

    def diagnostic_logs(self, actor_user_id, category, limit=100):
        return [
            {"worker": item.get("worker"), "code": item.get("code"), "details": item.get("details") or {}}
            for item in self.logs
            if item.get("actor_user_id") == actor_user_id and item.get("category") == category
        ][:limit]

    def provisioning_logs(self, operation_id, actor_user_id, limit=500):
        del operation_id, actor_user_id, limit
        return []


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
        self.local_profile_catalog = LocalProfileCatalog(root / "local-profile-catalog.json")
        self.profile_scan_store = ProfileScanOperationStore(db)
        self.runtime_readiness_store = RuntimeReadinessStore(
            root / "runtime-readiness.json"
        )
        self.activity_journal = ActivityJournalStore(db)
        self.operation_service = OperationsService(
            SqliteOperationStore(self.jobs), activity_journal=self.activity_journal
        )
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
        runtime_settings = BackendRuntimeSettings(
            root / "runtime-settings.json",
            {
                "backup_enabled": True,
                "backup_schedule": "03:00",
                "backup_timezone": "Asia/Jakarta",
                "backup_retention": 7,
                "backup_volume_size": "45m",
                "backup_channel": "456",
                "backup_channel_id": -100456,
                "storage_trash_retention_days": 30,
                "job_stall_timeout_seconds": 600,
                "job_cancel_grace_seconds": 30,
                "bot_token": "123456:abcdefghijklmnopqrstuvwxyzABCDE12345",
                "telegram_tts_chat_id": "123456789",
            },
        )
        utility_settings = UtilitySettingsStore(root / "settings.json")
        runtime_settings_store = SqliteSettingsStore(
            db, root / "runtime-settings" / "settings.key"
        )
        self.decrypt_history_store = SqliteDecryptHistoryStore(
            db, root / "runtime-settings" / "settings.key"
        )
        runtime_settings_store.seed_once(
            "test-runtime-seed-v1", runtime_settings.get(), source="test-env"
        )
        runtime_settings_store.seed_once(
            "test-utility-seed-v1", utility_settings.get(), source="test-json"
        )
        runtime_settings.attach_settings_store(runtime_settings_store)
        self.control.runtime_settings_store = runtime_settings_store
        self.control.tdl_access_store = SqliteTdlAccessStore(db)
        self.control.tdl_access_target_resolver = lambda purpose: (
            "123456789" if purpose == "tts" else "123" if purpose == "storage" else ""
        )
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
            utility_settings=UtilitySettingsStore(
                root / "settings.json", desired_store=runtime_settings_store
            ),
            worker_dispatcher=self.dispatcher,
            local_profile_catalog=self.local_profile_catalog,
            profile_scan_store=self.profile_scan_store,
            runtime_readiness_store=self.runtime_readiness_store,
            activity_journal=self.activity_journal,
            decrypt_history_store=self.decrypt_history_store,
            bot=self.bot,
            runtime_settings=runtime_settings,
            runtime_settings_store=runtime_settings_store,
            device_auth=DeviceAuthService(
                self.auth_repository, self.auth, "https://ui.example.test"
            ),
            operation_service=self.operation_service,
        )
        self.context = context
        self.app = create_backend_app(context)
        self.client = TestClient(self.app)

    def seed_tdl_access(self, worker="local", purpose="tts", profiles=None):
        capabilities = self.dispatcher.capabilities(worker)
        if purpose == "storage":
            profiles = list(profiles if profiles is not None else capabilities.get("available_storage_profiles", []))
            session_fingerprints = capabilities.get("storage_upload_fingerprints", {})
        else:
            profiles = list(profiles if profiles is not None else capabilities.get("export_profiles", []))
            session_fingerprints = {profile: "a" * 64 for profile in profiles}
        store = self.control.tdl_access_store
        destination = "123456789" if purpose == "tts" else "123"
        inventory_hash = store.inventory_fingerprint(
            profiles,
            session_fingerprints if purpose == "storage" else None,
        )
        store.replace_results(
            worker,
            purpose,
            store.destination_fingerprint(destination),
            inventory_hash,
            [{"profile": profile, "ready": True} for profile in profiles],
            session_fingerprints=session_fingerprints,
        )
        if purpose == "tts":
            self.runtime_readiness_store.apply_export_scan(
                checked_at="2026-10-23T00:00:00Z",
                workers=[{"worker": worker, "status": "success"}],
                profiles={worker: [
                    {
                        "profile": profile,
                        "ready": True,
                        "fingerprint": session_fingerprints[profile],
                    }
                    for profile in profiles
                ]},
            )
            self.runtime_readiness_store.apply_tts_scan(
                checked_at="2026-10-23T00:00:00Z",
                profiles={worker: [
                    {
                        "profile": profile,
                        "ready": bool(capabilities.get("tts")),
                        "reason_code": "TTS_HELPER_UNAVAILABLE",
                        "fingerprint": "c" * 64,
                        "session_fingerprint": session_fingerprints[profile],
                        "destination_fingerprint": store.destination_fingerprint(destination),
                    }
                    for profile in profiles
                ]},
            )
            helper_ready = capabilities.get("tts") is True
            self.runtime_readiness_store.upsert_cell(
                worker=worker,
                profile=None,
                runtime="tts_helper",
                ready=helper_ready,
                fingerprint="b" * 64 if helper_ready else "",
                reason_code="" if helper_ready else "TTS_HELPER_UNAVAILABLE",
                checked_at="2026-10-23T00:00:00Z",
            )
            self.control.runtime_readiness_gate = RuntimeReadinessGate(
                self.runtime_readiness_store
            )

    def run_profile_catalog_scan(self, headers):
        response = self.client.post("/api/v1/profiles/local/scan", headers=headers)
        self.assertEqual(response.status_code, 202, response.text)
        operation_id = response.json()["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            operation = self.client.get(
                f"/api/v1/profiles/local/scan/{operation_id}", headers=headers
            )
            self.assertEqual(operation.status_code, 200, operation.text)
            if operation.json()["status"] in {"succeeded", "failed"}:
                self.assertEqual(operation.json()["status"], "succeeded")
                return self.client.get("/api/v1/profiles/local", headers=headers)
            time.sleep(0.01)
        self.fail("profile scan did not finish before the test deadline")

    def seed_resolver_readiness(self, workers=None):
        workers = workers or {"local": {"ready": True, "fingerprint": "d" * 64}}
        self.runtime_readiness_store.apply_export_scan(
            checked_at="2026-10-23T00:00:00Z",
            workers=[{"worker": name, "status": "success"} for name in workers],
            profiles={},
        )
        self.runtime_readiness_store.apply_resolver_scan(
            checked_at="2026-10-23T00:00:00Z",
            workers=workers,
        )
        self.control.runtime_readiness_gate = RuntimeReadinessGate(
            self.runtime_readiness_store
        )

    def local_profile_delete_client(self, inventories):
        self.dispatcher.local_profile_deletes = []
        self.dispatcher.profile_local_inventory = lambda worker: dict(inventories[worker])

        def delete_local_profile(worker, profile):
            self.dispatcher.local_profile_deletes = getattr(
                self.dispatcher, "local_profile_deletes", []
            )
            self.dispatcher.local_profile_deletes.append((worker, profile))
            inventory = inventories[worker]
            inventory["items"] = [
                item for item in inventory.get("items", [])
                if item.get("name") != profile
            ]
            return {"profile": profile, "deleted": True, "already_absent": False}

        self.dispatcher.delete_local_profile = delete_local_profile
        self.context.queue_publisher = object()
        self.context.queue_command_service = object()
        return TestClient(create_backend_app(self.context))

    def tearDown(self):
        self.client.close()
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

    def test_multi_status_job_list_queries_repository_once_and_paginates(self):
        repository = Mock()
        repository.list.return_value = [
            Job(
                id="running-b",
                kind="export",
                profile="default",
                actor_user_id=42,
                worker="local",
                status=JobStatus.RUNNING,
                payload={},
            )
        ]
        repository.count.return_value = 3
        original_repository = self.control.jobs
        self.control.jobs = repository
        try:
            response = self.client.get(
                "/api/v1/jobs?scope=global&status=%20QUEUED%20,,running,queued&limit=1",
                headers=self.login(),
            )
        finally:
            self.control.jobs = original_repository

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(repository.list.call_count, 1)
        self.assertEqual(repository.count.call_count, 1)
        self.assertEqual(
            repository.list.call_args.kwargs["statuses"],
            ("queued", "running"),
        )
        self.assertEqual(
            repository.count.call_args.kwargs["statuses"],
            ("queued", "running"),
        )
        self.assertEqual(response.json()["items"][0]["id"], "running-b")
        self.assertEqual(response.json()["total"], 3)
        self.assertEqual(response.json()["next_offset"], 1)

    def test_operations_api_is_idempotent_private_and_actor_scoped(self):
        def prepare(actor, target, input_data):
            return PreparedOperation(
                profile=actor.profile,
                target={"worker": "local"},
                private_payload={"text": input_data["text"]},
            )

        self.operation_service.register_handler("test.echo", prepare)
        auth = self.login(42)
        operation_request_id = str(uuid.uuid4())
        submitted = self.client.post(
            "/api/v1/operations",
            headers={
                **auth,
                "Idempotency-Key": "operation-submit-1",
                "X-Request-ID": operation_request_id,
            },
            json={"kind": "test.echo", "target": {"worker": "ignored"}, "input": {"text": "private-operation-text"}},
        )
        self.assertEqual(submitted.status_code, 202)
        operation_id = submitted.json()["operation_id"]
        self.assertEqual(submitted.headers["location"], f"/api/v1/operations/{operation_id}")
        self.assertNotIn("private-operation-text", submitted.text)
        self.assertNotIn("input", submitted.json())
        self.assertEqual(submitted.json()["status"], "queued")
        self.assertEqual(submitted.json()["revision"], 1)
        correlated = self.client.get(
            f"/api/v1/activity?request_id={operation_request_id}", headers=auth
        )
        self.assertEqual(correlated.status_code, 200, correlated.text)
        correlated_items = correlated.json()["items"]
        self.assertEqual(
            {item["activity_type"] for item in correlated_items}, {"request", "operation"}
        )
        lifecycle = next(
            item for item in correlated_items if item["activity_type"] == "operation"
        )
        self.assertEqual(lifecycle["operation_id"], operation_id)
        self.assertEqual(lifecycle["operation_kind"], "test.echo")
        self.assertEqual(lifecycle["operation_status"], "queued")
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

    def test_backup_verification_submit_accepts_private_archive_password_snapshot(self):
        self.catalog.start_backup_run("backup-run-1", "local")
        self.catalog.finish_backup_run("backup-run-1", "local")
        self.control.utility_settings = self.context.utility_settings
        self.context.utility_settings.set("compress_password", "test-archive-password")
        self.context.queue_publisher = object()
        self.context.queue_command_service = object()
        client = TestClient(create_backend_app(self.context))

        response = client.post(
            "/api/v1/backups/verify",
            headers={**self.login(42), "Idempotency-Key": "backup-verify-secret-snapshot"},
            json={"worker": "local", "profile": "default", "run_id": "backup-run-1"},
        )

        self.assertEqual(response.status_code, 202, response.text)
        job = self.jobs.get(response.json()["id"])
        self.assertIsNotNone(job)
        self.assertNotIn("test-archive-password", response.text)
        ciphertext = self.jobs.private_value(job.id, "backup_archive_password")
        self.assertIsNotNone(ciphertext)
        self.assertEqual(
            self.context.runtime_settings_store.decrypt_job_secret(
                job.id, "backup_archive_password", ciphertext
            ),
            "test-archive-password",
        )

    def test_background_job_submit_is_not_advertised_without_queue(self):
        capabilities = self.client.get("/api/v1/capabilities").json()
        self.assertNotIn("job.submit", capabilities["operations"]["supported_kinds"])

    def test_profile_sync_is_a_durable_operation_completed_by_worker_ack(self):
        from tme3bot.api.routes.profile_sync import advance_profile_sync_command

        vault = ProfileProvisioningStore(
            Path(self.temp.name) / "app.db", Path(self.temp.name) / "vault"
        )
        provisioning_id = vault.begin(
            profile="default", actor_user_id=42, bootstrap_worker="local",
            source="adoption", target_workers=["local"],
        )
        bundle = build_profile_bundle({"data/default": b"vault-session"}, 42)
        vault.store_bundle(provisioning_id, 42, bundle)
        vault.update_distribution("default", "local", "ready", provisioning_id=provisioning_id)
        vault.mark_active(provisioning_id)
        self.context.profile_provisioner = type("Provisioner", (), {"store": vault})()
        self.context.queue_publisher = object()
        self.context.queue_command_service = object()
        client = TestClient(create_backend_app(self.context))

        response = client.post(
            "/api/v1/operations",
            headers={**self.login(42), "Idempotency-Key": "profile-sync-default-local"},
            json={"kind": "profile.sync", "target": {"profile": "default", "worker": "local"}, "input": {}},
        )

        self.assertEqual(response.status_code, 202)
        self.assertIn("profile.sync", client.get("/api/v1/capabilities").json()["operations"]["supported_kinds"])
        operation_id = response.json()["operation_id"]
        progress = client.get(
            f"/api/v1/operations/{operation_id}/events", headers=self.login(42)
        )
        self.assertEqual(progress.status_code, 200, progress.text)
        self.assertEqual(progress.json()["items"][0]["phase"], "queued")
        self.assertEqual(progress.json()["items"][0]["code"], "PROFILE_SYNC_QUEUED")
        self.assertEqual(
            client.get(f"/api/v1/operations/{operation_id}/events").status_code,
            401,
        )
        repeated = client.post(
            "/api/v1/operations",
            headers={**self.login(42), "Idempotency-Key": "profile-sync-default-local"},
            json={"kind": "profile.sync", "target": {"profile": "default", "worker": "local"}, "input": {}},
        )
        self.assertEqual(repeated.status_code, 202)
        self.assertEqual(repeated.json()["operation_id"], operation_id)
        private = self.operation_service.store.get_private_payload(operation_id)
        self.assertNotIn("bundle", private)
        command = {
            "operation_id": operation_id,
            "kind": "profile.sync",
            "private_payload": private,
        }
        self.assertEqual(advance_profile_sync_command(command, self.context)["status"], "accepted")
        self.assertEqual(self.dispatcher.profile_sync_requests, [("local", "default", "check")])
        self.assertEqual(
            self.operation_service.get(self.control.actor(42), operation_id).status.value,
            "waiting_worker",
        )

        revision = vault.desired_revision("default")
        self.control.runtime_readiness_gate = RuntimeReadinessGate(
            self.runtime_readiness_store
        )
        self.runtime_readiness_store.apply_export_scan(
            checked_at="2026-10-23T10:00:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [{"profile": "default", "ready": True, "fingerprint": "a" * 64}]},
        )
        worker_headers = {
            "Authorization": "Bearer internal",
            "X-Worker-Name": "local",
            "X-Worker-Token": "secret",
        }
        worker_event = {
            "profile": "default",
            "run_id": "worker-run-123",
            "sequence": 1,
            "revision": revision["revision"],
            "phase": "session_install",
            "status": "running",
            "details": {"entry_count": 2, "password": "must-not-be-stored"},
        }
        event_response = client.post(
            "/internal/v1/profile-sync/events",
            headers=worker_headers,
            json=worker_event,
        )
        self.assertEqual(event_response.status_code, 200, event_response.text)
        changed_cell = self.runtime_readiness_store.cell("local", "default", "export")
        self.assertEqual(changed_cell["status"], "not_ready")
        self.assertEqual(changed_cell["reason_code"], "PROFILE_SESSION_CHANGED")
        duplicate_response = client.post(
            "/internal/v1/profile-sync/events",
            headers=worker_headers,
            json=worker_event,
        )
        self.assertTrue(duplicate_response.json()["duplicate"])
        events = client.get(
            f"/api/v1/operations/{operation_id}/events", headers=self.login(42)
        ).json()["items"]
        install_events = [item for item in events if item["phase"] == "session_install"]
        self.assertEqual(len(install_events), 1)
        self.assertNotIn("password", repr(install_events))

        acknowledged = client.post(
            "/internal/v1/profiles/default/ack",
            headers=worker_headers,
            json={
                "revision": revision["revision"],
                "bundle_sha256": revision["bundle_sha256"],
                "telegram_user_id": 42,
            },
        )
        self.assertEqual(acknowledged.status_code, 200, acknowledged.text)
        self.assertEqual(
            self.operation_service.get(self.control.actor(42), operation_id).status.value,
            "succeeded",
        )
        progress = client.get(
            f"/api/v1/operations/{operation_id}/events", headers=self.login(42)
        )
        self.assertTrue(any(
            item["phase"] == "completed" and item["status"] == "succeeded"
            for item in progress.json()["items"]
        ))

        failed_response = client.post(
            "/api/v1/operations",
            headers={**self.login(42), "Idempotency-Key": "profile-sync-default-local-failed"},
            json={
                "kind": "profile.sync",
                "target": {"profile": "default", "worker": "local"},
                "input": {"mode": "repair"},
            },
        )
        self.assertEqual(failed_response.status_code, 202, failed_response.text)
        failed_id = failed_response.json()["operation_id"]
        failed_command = {
            "operation_id": failed_id,
            "kind": "profile.sync",
            "private_payload": self.operation_service.store.get_private_payload(failed_id),
        }
        self.assertEqual(advance_profile_sync_command(failed_command, self.context)["status"], "accepted")
        failed_event = client.post(
            "/internal/v1/profile-sync/events",
            headers=worker_headers,
            json={
                "profile": "default",
                "run_id": "worker-fail-123",
                "sequence": 1,
                "revision": revision["revision"],
                "phase": "completed",
                "status": "failed",
                "code": "PROFILE_SESSION_TDL_INVALID",
            },
        )
        self.assertEqual(failed_event.status_code, 200, failed_event.text)
        self.assertEqual(
            self.operation_service.get(self.control.actor(42), failed_id).status.value,
            "failed",
        )
        failed_progress = client.get(
            f"/api/v1/operations/{failed_id}/events", headers=self.login(42)
        ).json()["items"]
        self.assertTrue(any(
            item["phase"] == "completed" and item["status"] == "failed"
            for item in failed_progress
        ))
        client.close()

    def test_worker_profile_sync_status_is_authenticated_and_redacted(self):
        denied = self.client.get("/api/v1/workers/local/profile-sync")
        self.assertEqual(denied.status_code, 401)
        response = self.client.get(
            "/api/v1/workers/local/profile-sync", headers=self.login()
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "waiting_worker")
        self.assertEqual(response.json()["profiles"]["default"]["error_code"], "BACKEND_UNAVAILABLE")
        self.assertEqual(
            response.json()["backend_error_code"], "PROFILE_TRANSFER_REQUIRES_HTTPS"
        )
        self.assertNotIn("bundle_sha256", response.text)
        self.assertNotIn("private-hash", response.text)
        self.assertNotIn("queued_requests", response.json())

    def test_profile_management_does_not_call_vault_ack_ready_runtime_ready(self):
        headers = self.login()
        provisioner = FakeProfileProvisioner()
        provisioner.profiles = lambda actor_user_id=None: [{
            "name": "default",
            "active": True,
            "status": "active",
            "vault": True,
            "workers": [{
                "worker": "local",
                "status": "ready",
                "desired_revision": 4,
                "installed_revision": 4,
            }],
        }]
        self.context.profile_provisioner = provisioner
        self.dispatcher.profile_sync_snapshot = {
            "status": "waiting_worker",
            "backend_available": False,
            "startup_checked": True,
            "backend_error_code": "PROFILE_TRANSFER_REQUIRES_HTTPS",
            "profiles": {},
        }

        response = self.client.get("/api/v1/profiles/management", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        worker_status = response.json()["items"][0]["workers"][0]
        self.assertEqual(worker_status["vault_ack_status"], "ready")
        self.assertEqual(worker_status["runtime_status"], "waiting_worker")
        self.assertEqual(worker_status["runtime_error_code"], "PROFILE_TRANSFER_REQUIRES_HTTPS")
        self.assertEqual(worker_status["status"], "waiting_worker")

    def test_profile_management_hides_cached_ready_until_this_startup_sync_check_finishes(self):
        headers = self.login()
        provisioner = FakeProfileProvisioner()
        provisioner.profiles = lambda actor_user_id=None: [{
            "name": "default",
            "active": True,
            "status": "active",
            "vault": True,
            "workers": [{
                "worker": "local",
                "status": "ready",
                "desired_revision": 4,
                "installed_revision": 4,
            }],
        }]
        self.context.profile_provisioner = provisioner
        self.dispatcher.profile_sync_snapshot = {
            "status": "sync_pending",
            "backend_available": True,
            "startup_checked": False,
            "profiles": {
                "default": {
                    "status": "ready",
                    "desired_revision": 4,
                    "installed_revision": 4,
                }
            },
        }

        response = self.client.get("/api/v1/profiles/management", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        worker_status = response.json()["items"][0]["workers"][0]
        self.assertEqual(worker_status["vault_ack_status"], "ready")
        self.assertEqual(worker_status["runtime_status"], "sync_pending")
        self.assertEqual(worker_status["runtime_error_code"], "PROFILE_STARTUP_CHECK_PENDING")
        self.assertEqual(worker_status["status"], "sync_pending")

    def test_profile_management_does_not_trust_cached_ready_without_live_backend_confirmation(self):
        headers = self.login()
        provisioner = FakeProfileProvisioner()
        provisioner.profiles = lambda actor_user_id=None: [{
            "name": "default",
            "active": True,
            "status": "active",
            "vault": True,
            "workers": [{
                "worker": "local",
                "status": "ready",
                "desired_revision": 4,
                "installed_revision": 4,
            }],
        }]
        self.context.profile_provisioner = provisioner
        self.dispatcher.profile_sync_snapshot = {
            "status": "ready",
            "startup_checked": True,
            # A cached profile row is not proof that the backend manifest was
            # reached during this worker's latest live sync check.
            "profiles": {
                "default": {
                    "status": "ready",
                    "desired_revision": 4,
                    "installed_revision": 4,
                }
            },
        }

        response = self.client.get("/api/v1/profiles/management", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        worker_status = response.json()["items"][0]["workers"][0]
        self.assertEqual(worker_status["vault_ack_status"], "ready")
        self.assertEqual(worker_status["runtime_status"], "waiting_worker")
        self.assertEqual(worker_status["runtime_error_code"], "PROFILE_BACKEND_UNAVAILABLE")
        self.assertEqual(worker_status["status"], "waiting_worker")

    def test_local_profile_scan_requires_actor_and_returns_selected_worker_snapshot(self):
        calls = []
        self.dispatcher.scan_local_profiles = lambda worker: calls.append(worker) or {
            "items": [
                {
                    "name": "irang",
                    "ready": True,
                    "reason_codes": [],
                    "checks": [
                        {"name": "identity", "ready": True, "code": "OK"},
                        {"name": "root_session", "ready": True, "code": "OK"},
                        {"name": "user1_session", "ready": True, "code": "OK"},
                    ],
                    "upload_lane": {
                        "status": "running",
                        "phase": "validating_upload",
                        "progress": 70,
                        "code": "OK",
                        "updated_at": "2026-10-14T00:00:00+00:00",
                    },
                }
            ]
        }

        denied = self.client.post("/api/v1/workers/local/profiles/scan")
        self.assertEqual(denied.status_code, 401)

        response = self.client.post(
            "/api/v1/workers/local/profiles/scan", headers=self.login(42)
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(calls, ["local"])
        self.assertEqual(body["worker"], "local")
        self.assertTrue(body["checked_at"])
        self.assertEqual(body["items"][0]["name"], "irang")
        self.assertTrue(body["items"][0]["ready"])
        self.assertEqual(body["items"][0]["upload_lane"]["phase"], "validating_upload")
        self.assertEqual(body["items"][0]["upload_lane"]["progress"], 70)
        self.assertNotIn("/data", response.text)
        self.assertNotIn("telegram_user_id", response.text)

        self.dispatcher.profile_local_inventory = lambda worker: calls.append(f"snapshot:{worker}") or {
            "items": [{
                "name": "irang",
                "ready": True,
                "reason_codes": [],
                "checks": [
                    {"name": "identity", "ready": True, "code": "OK"},
                    {"name": "root_session", "ready": True, "code": "OK"},
                    {"name": "user1_session", "ready": True, "code": "OK"},
                ],
                "upload_lane": {
                    "status": "ready", "phase": "ready", "progress": 100,
                    "code": "OK", "updated_at": "2026-10-14T00:00:00+00:00"
                },
            }]
        }
        status_response = self.client.get(
            "/api/v1/workers/local/profiles/local", headers=self.login(42)
        )
        self.assertEqual(status_response.status_code, 200, status_response.text)
        self.assertEqual(status_response.json()["items"][0]["upload_lane"]["status"], "ready")
        self.assertEqual(calls[-1], "snapshot:local")

        missing = self.client.post(
            "/api/v1/workers/not-registered/profiles/scan", headers=self.login(42)
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(calls, ["local", "snapshot:local"])

    def test_profile_catalog_scan_returns_async_operation_with_worker_profile_progress(self):
        entered = threading.Event()
        release = threading.Event()
        self.dispatcher.profile_local_inventory = lambda _worker: {"items": [{
            "name": "default",
            "ready": True,
            "reason_codes": [],
            "checks": [
                {"name": "identity", "ready": True, "code": "OK"},
                {"name": "root_session", "ready": True, "code": "OK"},
                {"name": "user1_session", "ready": True, "code": "OK"},
            ],
        }]}

        def slow_diagnostics(_worker, _profile):
            entered.set()
            release.wait(timeout=3)
            return {"ready": True, "reason_codes": [], "fingerprint": "a" * 64}

        self.dispatcher.profile_tdl_diagnostics = slow_diagnostics
        try:
            response = self.client.post(
                "/api/v1/profiles/local/scan", headers=self.login(42)
            )
            self.assertEqual(response.status_code, 202, response.text)
            operation_id = response.json()["id"]
            self.assertTrue(entered.wait(timeout=1), "scan must run outside the HTTP request")

            progress = self.client.get(
                f"/api/v1/profiles/local/scan/{operation_id}", headers=self.login(42)
            )
            self.assertEqual(progress.status_code, 200, progress.text)
            self.assertEqual(progress.json()["status"], "running")
            worker = progress.json()["progress"]["workers"][0]
            self.assertEqual(worker["name"], "local")
            self.assertEqual(worker["status"], "running")
            self.assertEqual(worker["profiles"][0]["name"], "default")
            self.assertEqual(worker["profiles"][0]["status"], "running")
        finally:
            release.set()

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            completed = self.client.get(
                f"/api/v1/profiles/local/scan/{operation_id}", headers=self.login(42)
            )
            if completed.status_code == 200 and completed.json()["status"] in {
                "succeeded", "failed"
            }:
                break
            time.sleep(0.01)
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(completed.json()["status"], "succeeded")
        self.assertEqual(
            completed.json()["progress"]["workers"][0]["profiles"][0]["status"],
            "succeeded",
        )

    def test_local_profile_scan_distinguishes_timeout_offline_and_worker_api_failure(self):
        from tme3bot.infrastructure.http_client import JsonHttpError

        auth = self.login(42)
        client = TestClient(create_backend_app(self.context))
        cases = (
            (JsonHttpError(504, "timeout", kind="timeout"), 504, "WORKER_TIMEOUT"),
            (JsonHttpError(503, "unavailable", kind="network"), 503, "WORKER_UNAVAILABLE"),
            (JsonHttpError(500, "private worker detail", kind="response"), 502, "WORKER_SCAN_FAILED"),
        )
        for error, expected_status, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                def fail(_worker, current=error):
                    raise current

                self.dispatcher.scan_local_profiles = fail
                response = client.post("/api/v1/workers/local/profiles/scan", headers=auth)
                self.assertEqual(response.status_code, expected_status, response.text)
                self.assertEqual(response.json()["error"]["code"], expected_code)
                self.assertNotIn("private worker detail", response.text)

    def test_cross_worker_profile_scan_persists_successful_workers_and_drops_failed_inventory(self):
        from tme3bot.infrastructure.http_client import JsonHttpError

        self.workers.values["remote-1"] = {
            "url": "https://remote-1.example.test",
            "token": "remote-secret",
            "enabled": True,
        }
        self.workers.values["remote-2"] = {
            "url": "https://remote-2.example.test",
            "token": "remote-secret-2",
            "enabled": False,
        }
        self.local_profile_catalog.replace_scan(
            checked_at="2026-10-15T00:00:00+00:00",
            workers=[{"name": "remote-1", "status": "success", "checked_at": "old"}],
            inventories=[{
                "worker": "remote-1", "checked_at": "old", "items": [{"name": "stale"}]
            }],
        )
        calls = []

        def inventory(worker):
            calls.append(worker)
            if worker == "remote-1":
                raise JsonHttpError(503, "private worker detail", kind="network")
            return {"items": [
                {
                    "name": "default",
                    "ready": True,
                    "reason_codes": [],
                    "checks": [
                        {"name": "identity", "ready": True, "code": "OK"},
                        {"name": "root_session", "ready": True, "code": "OK"},
                        {"name": "user1_session", "ready": True, "code": "OK"},
                    ],
                    "upload_lane": {"status": "ready", "phase": "ready", "progress": 100, "code": "OK"},
                    "telegram_user_id": 42,
                    "path": "/data/private",
                    "secret": "must-not-leak",
                },
                {
                    "name": "incomplete",
                    "ready": False,
                    "reason_codes": ["PROFILE_USER1_SESSION_MISSING"],
                    "checks": [
                        {"name": "identity", "ready": True, "code": "OK"},
                        {"name": "root_session", "ready": True, "code": "OK"},
                        {"name": "user1_session", "ready": False, "code": "PROFILE_USER1_SESSION_MISSING"},
                    ],
                },
            ]}

        self.dispatcher.profile_local_inventory = inventory
        self.dispatcher.profile_tdl_diagnostics = lambda worker, profile: {
            "ready": True,
            "reason_codes": [],
            "fingerprint": hashlib.sha256(f"{worker}:{profile}".encode()).hexdigest(),
        }
        utility_probe_calls = []
        self.dispatcher.utility_runtime_readiness = lambda worker: utility_probe_calls.append(worker) or {
            "ready": True, "reason_code": "", "fingerprint": "c" * 64,
        }
        resolver_probe_calls = []
        self.dispatcher.safelink_runtime_readiness = lambda worker: (
            resolver_probe_calls.append(worker)
            or {"ready": True, "reason_code": "", "fingerprint": "e" * 64}
        )
        self.dispatcher.scan_local_profiles = lambda _worker: self.fail(
            "cross-worker scan must not start Upload lane preparation"
        )
        auth = self.login(42)
        denied = self.client.post("/api/v1/profiles/local/scan")
        self.assertEqual(denied.status_code, 401)

        response = self.run_profile_catalog_scan(auth)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertCountEqual(calls, ["local", "remote-1"])
        self.assertEqual(
            [(item["name"], item["status"]) for item in body["workers"]],
            [("local", "success"), ("remote-1", "failed"), ("remote-2", "disabled")],
        )
        self.assertEqual(body["workers"][1]["error_code"], "WORKER_UNAVAILABLE")
        self.assertEqual([item["worker"] for item in body["inventories"]], ["local"])
        self.assertEqual(
            [item["name"] for item in body["inventories"][0]["items"]],
            ["default", "incomplete"],
        )
        self.assertEqual(body["profiles"], [
            {"name": "default", "workers": ["local"], "exclusive_worker": "local"},
        ])
        self.assertNotIn("telegram_user_id", response.text)
        self.assertNotIn("/data", response.text)
        self.assertNotIn("must-not-leak", response.text)
        self.assertNotIn("fingerprint", response.text)
        self.assertEqual(resolver_probe_calls, ["local"])
        utility_cells = [
            item for item in body["runtime_readiness"]["cells"]
            if item["runtime"] == "utility"
        ]
        self.assertEqual(utility_cells, [])
        self.assertEqual(utility_probe_calls, [])
        self.assertIsNone(self.runtime_readiness_store.cell("local", None, "utility"))
        self.assertEqual(
            self.runtime_readiness_store.cell("local", "default", "export")["fingerprint"],
            hashlib.sha256(b"local:default").hexdigest(),
        )
        self.assertEqual(
            self.runtime_readiness_store.cell("local", "incomplete", "export")["status"],
            "not_ready",
        )
        self.assertEqual(
            self.runtime_readiness_store.cell("local", None, "resolver")["fingerprint"],
            "e" * 64,
        )
        resolver_cells = [
            item for item in body["runtime_readiness"]["cells"]
            if item["runtime"] == "resolver"
        ]
        self.assertEqual(len(resolver_cells), 1)
        self.assertEqual(resolver_cells[0]["worker"], "local")
        self.assertEqual(resolver_cells[0]["profile"], None)
        self.assertEqual(resolver_cells[0]["status"], "ready")
        self.assertEqual(body["runtime_readiness"]["workers"][1]["status"], "failed")

        before_read = list(calls)
        read = self.client.get("/api/v1/profiles/local", headers=auth)
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json(), body)
        self.assertEqual(calls, before_read)
        self.assertEqual(resolver_probe_calls, ["local"])
        self.assertNotIn("stale", read.text)

    def test_profile_scan_uses_tts_canary_and_helper_probe_without_manual_marker(self):
        self.control.runtime_readiness_gate = RuntimeReadinessGate(
            self.runtime_readiness_store
        )
        self.dispatcher.profile_local_inventory = lambda _worker: {"items": [{
            "name": "default",
            "ready": True,
            "reason_codes": [],
            "checks": [
                {"name": "identity", "ready": True, "code": "OK"},
                {"name": "root_session", "ready": True, "code": "OK"},
                {"name": "user1_session", "ready": True, "code": "OK"},
            ],
            "upload_lane": {
                "status": "ready", "phase": "ready", "progress": 100,
                "code": "OK", "updated_at": "2026-10-23T00:00:00Z",
            },
        }]}

        def diagnose_profile(worker, profile):
            self.dispatcher.profile_tdl_diagnostic_calls.append((worker, profile))
            return {
                "ready": True,
                "reason_codes": [],
                "fingerprint": "a" * 64,
            }

        self.dispatcher.profile_tdl_diagnostics = diagnose_profile
        self.dispatcher.tts_health_result = {
            "ready": True,
            "helpers_ready": True,
            "helpers": [
                {"slot": slot, "status": "ready", "bootstrap_percent": 100}
                for slot in range(1, 4)
            ],
        }
        response = self.run_profile_catalog_scan(self.login(42))

        self.assertEqual(response.status_code, 200, response.text)
        cell = self.runtime_readiness_store.cell("local", "default", "tts")
        self.assertEqual(cell["status"], "ready")
        self.assertEqual(cell["session_fingerprint"], "a" * 64)
        self.assertNotIn("a" * 64, response.text)
        tts_worker = self.runtime_readiness_store.cell("local", None, "tts_helper")
        self.assertEqual(tts_worker["status"], "ready")
        self.assertEqual(self.dispatcher.tts_health_calls, ["local"])
        self.assertEqual(
            self.dispatcher.profile_tdl_diagnostic_calls,
            [("local", "default")],
        )
        self.assertEqual(len(self.dispatcher.profile_readiness_canary_calls), 1)
        self.assertEqual(self.dispatcher.commands, [])
        self.assertEqual(self.jobs.list(profile="default", limit=20), [])

    def test_profile_scan_reports_cleanup_failure_without_revoking_ready_lanes(self):
        self.dispatcher.profile_local_inventory = lambda _worker: {"items": [{
            "name": "default", "ready": True, "reason_codes": [],
            "checks": [
                {"name": "identity", "ready": True, "code": "OK"},
                {"name": "root_session", "ready": True, "code": "OK"},
                {"name": "user1_session", "ready": True, "code": "OK"},
            ],
        }]}
        self.dispatcher.profile_tdl_diagnostics = lambda _worker, _profile: {
            "ready": True, "reason_codes": [], "fingerprint": "a" * 64,
        }
        self.dispatcher.profile_readiness_canary_messages = [
            {"target": "storage", "message_id": 801},
            {"target": "tts", "message_id": 802},
        ]
        self.bot.delete_error = True

        response = self.run_profile_catalog_scan(self.login(42))

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.runtime_readiness_store.cell("local", "default", "upload")["status"], "ready")
        self.assertEqual(self.runtime_readiness_store.cell("local", "default", "storage")["status"], "ready")
        self.assertEqual(len(self.bot.delete_calls), 2)
        operation = self.profile_scan_store.latest()
        progress_profile = operation["progress"]["workers"][0]["profiles"][0]
        self.assertEqual(progress_profile["cleanup"]["status"], "failed")
        self.assertEqual(
            [item["message_id"] for item in progress_profile["cleanup"]["items"]],
            [801, 802],
        )
        self.assertTrue(all(
            item["error_code"] == "CANARY_CLEANUP_FAILED"
            for item in progress_profile["cleanup"]["items"]
        ))

    def test_profile_scan_stores_separate_quick_mode_cell_and_private_upload_snapshot(self):
        self.control.runtime_readiness_gate = RuntimeReadinessGate(
            self.runtime_readiness_store
        )
        self.dispatcher.profile_local_inventory = lambda _worker: {"items": [{
            "name": "default",
            "ready": True,
            "reason_codes": [],
            "checks": [
                {"name": "identity", "ready": True, "code": "OK"},
                {"name": "root_session", "ready": True, "code": "OK"},
                {"name": "user1_session", "ready": True, "code": "OK"},
            ],
            "upload_lane": {
                "status": "ready", "phase": "ready", "progress": 100,
                "code": "OK", "updated_at": "2026-10-23T00:00:00Z",
            },
        }]}
        self.dispatcher.profile_tdl_diagnostics = lambda _worker, _profile: {
            "ready": True, "reason_codes": [], "fingerprint": "a" * 64,
        }
        self.dispatcher.quickmode_runtime_readiness = lambda _worker, _destination: {
            "ready": True, "reason_code": "", "fingerprint": "b" * 64,
        }
        access_store = self.control.tdl_access_store
        destination = self.control._tdl_access_target("storage")
        destination_hash = access_store.destination_fingerprint(destination)

        response = self.run_profile_catalog_scan(self.login(42))

        self.assertEqual(response.status_code, 200, response.text)
        quick = self.runtime_readiness_store.cell("local", "default", "quick_mode")
        quick_worker = self.runtime_readiness_store.cell("local", None, "quick_mode_runtime")
        storage = self.runtime_readiness_store.cell("local", "default", "storage")
        export = self.runtime_readiness_store.cell("local", "default", "export")
        self.assertEqual(export["status"], "ready")
        self.assertEqual(quick["status"], "ready")
        self.assertEqual(quick_worker["status"], "ready")
        self.assertEqual(storage["status"], "ready")
        upload_fingerprint = self.dispatcher.capabilities("local")["storage_upload_fingerprints"]["default"]
        self.assertEqual(storage["session_fingerprint"], upload_fingerprint)
        self.assertEqual(storage["destination_fingerprint"], destination_hash)
        self.assertEqual(quick["session_fingerprint"], "a" * 64)
        self.assertEqual(quick["destination_fingerprint"], destination_hash)
        self.assertEqual(quick["sender_profiles"], ["default"])
        self.assertEqual(
            quick["sender_session_fingerprints"]["default"],
            upload_fingerprint,
        )
        body = response.json()
        public_quick = next(
            cell for cell in body["runtime_readiness"]["cells"]
            if cell["runtime"] == "quick_mode"
        )
        self.assertEqual(public_quick["status"], "ready")
        self.assertNotIn("fingerprint", str(body["runtime_readiness"]))
        self.assertNotIn("sender_session_fingerprints", response.text)
        self.assertNotIn("_storage_readiness", response.text)
        self.assertEqual(self.dispatcher.commands, [])
        self.assertEqual(self.jobs.list(profile="default", limit=20), [])

    def test_profile_scan_replaces_stale_tts_marker_with_canary_evidence(self):
        self.dispatcher.profile_local_inventory = lambda _worker: {"items": [{
            "name": "default", "ready": True, "reason_codes": [],
            "checks": [
                {"name": "identity", "ready": True, "code": "OK"},
                {"name": "root_session", "ready": True, "code": "OK"},
                {"name": "user1_session", "ready": True, "code": "OK"},
            ],
        }]}
        self.dispatcher.profile_tdl_diagnostics = lambda _worker, _profile: {
            "ready": True, "reason_codes": [], "fingerprint": "b" * 64,
        }
        self.dispatcher.tts_health_result = {
            "ready": True, "helpers_ready": True,
            "helpers": [{"slot": slot, "status": "ready"} for slot in range(1, 4)],
        }
        access_store = self.control.tdl_access_store
        destination_hash = access_store.destination_fingerprint("123456789")
        stale_fingerprints = {"default": "a" * 64}
        access_store.replace_results(
            "local", "tts", destination_hash,
            access_store.inventory_fingerprint(["default"], stale_fingerprints),
            [{"profile": "default", "ready": True}],
            session_fingerprints=stale_fingerprints,
        )

        response = self.run_profile_catalog_scan(self.login(42))

        self.assertEqual(response.status_code, 200, response.text)
        cell = self.runtime_readiness_store.cell("local", "default", "tts")
        self.assertEqual(cell["status"], "ready")
        self.assertEqual(cell["session_fingerprint"], "b" * 64)

    def test_successful_tts_proof_event_persists_export_session_fingerprint(self):
        store = self.control.tdl_access_store
        destination_hash = store.destination_fingerprint("123456789")
        inventory_hash = store.inventory_fingerprint(["default"])
        job = Job(
            id="verify-tts-proof",
            kind="tdl_access_verify",
            profile="default",
            actor_user_id=42,
            worker="local",
            status=JobStatus.QUEUED,
            payload={"purpose": "tts"},
        )
        self.jobs.create_with_private_values(
            job,
            {},
            execution_plan={},
            command_payload={
                "payload": {
                    "purpose": "tts",
                    "destination_hash": destination_hash,
                }
            },
        )

        self.control._apply_event_side_effects(job, JobEvent(
            job_id=job.id,
            sequence=1,
            status=JobStatus.SUCCEEDED,
            event_type="succeeded",
            result={"value": {
                "purpose": "tts",
                "inventory_hash": inventory_hash,
                "session_fingerprints": {"default": "a" * 64},
                "profiles": [{"profile": "default", "ready": True}],
            }},
        ))

        self.assertEqual(
            store.verified_profiles(
                "local",
                "tts",
                destination_hash,
                inventory_hash,
                session_fingerprints={"default": "a" * 64},
            ),
            ["default"],
        )

    def test_local_profile_delete_rejects_default_and_any_active_profile_job(self):
        inventories = {"local": {"worker": "local", "items": [
            {"name": "default"}, {"name": "archive"}
        ]}}
        client = self.local_profile_delete_client(inventories)
        auth = self.login(42)

        default = client.delete(
            "/api/v1/workers/local/profiles/local/default",
            headers={**auth, "Idempotency-Key": "delete-default-profile"},
        )
        self.assertEqual(default.status_code, 409, default.text)
        self.assertEqual(default.json()["error"]["code"], "PROFILE_DEFAULT_PROTECTED")
        self.assertEqual(self.dispatcher.local_profile_deletes, [])

        self.control.submit_job(
            self.control.actor(42), "export", {"url": "https://t.me/c/1/2"},
            profile="archive", worker="local",
        )
        active = client.delete(
            "/api/v1/workers/local/profiles/local/archive",
            headers={**auth, "Idempotency-Key": "delete-active-profile"},
        )
        self.assertEqual(active.status_code, 409, active.text)
        self.assertEqual(active.json()["error"]["code"], "PROFILE_JOB_ACTIVE")
        self.assertEqual(self.dispatcher.local_profile_deletes, [])

    def test_local_profile_delete_accepts_raw_inventory_and_removes_identity_after_last_copy(self):
        from tme3bot.api.routes.profile_local_delete import advance_profile_local_delete_command

        # WorkerHttpDispatcher returns the worker's raw contract, which carries
        # items but does not echo the backend's selected worker name.
        inventories = {"local": {"items": [
            {"name": "default"}, {"name": "archive"}
        ]}}
        self.profiles.profile_registry.register("archive", 900)
        client = self.local_profile_delete_client(inventories)
        auth = self.login(42)

        response = client.delete(
            "/api/v1/workers/local/profiles/local/archive",
            headers={**auth, "Idempotency-Key": "delete-archive-last-copy"},
        )
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertEqual(body["kind"], "profile.local_delete")
        self.assertEqual(body["status"], "queued")
        self.assertTrue(self.profiles.profile_registry.local_deletion_active("archive", "local"))

        with self.assertRaises(DomainError) as blocked:
            self.control.submit_job(
                self.control.actor(42), "export", {"url": "https://t.me/c/1/2"},
                profile="archive", worker="local",
            )
        self.assertEqual(getattr(blocked.exception, "code", ""), "PROFILE_DELETION_IN_PROGRESS")

        operation_id = body["operation_id"]
        private = self.operation_service.store.get_private_payload(operation_id)
        result = advance_profile_local_delete_command(
            {"operation_id": operation_id, "kind": "profile.local_delete", "private_payload": private},
            self.context,
        )
        self.assertEqual(result["status"], "accepted")
        completed = self.operation_service.get(self.control.actor(42), operation_id)
        self.assertEqual(completed.status.value, "succeeded")
        self.assertEqual(completed.progress["identity_mapping_status"], "removed")
        self.assertFalse(self.profiles.profile_registry.local_deletion_active("archive", "local"))
        self.assertIsNone(self.profiles.profile_registry.profile_for_user(900))
        self.assertIn("archive", self.profiles.profile_registry.names())
        self.assertEqual(self.dispatcher.local_profile_deletes, [("local", "archive")])

    def test_local_profile_delete_rejects_inventory_echo_from_another_worker(self):
        inventories = {"local": {"worker": "remote-1", "items": [
            {"name": "archive"}
        ]}}
        client = self.local_profile_delete_client(inventories)

        response = client.delete(
            "/api/v1/workers/local/profiles/local/archive",
            headers={**self.login(42), "Idempotency-Key": "delete-wrong-worker-inventory"},
        )

        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["error"]["code"], "WORKER_UNAVAILABLE")
        self.assertEqual(self.dispatcher.local_profile_deletes, [])

    def test_local_profile_delete_keeps_mapping_when_other_worker_inventory_is_stale_then_rechecks(self):
        from tme3bot.api.routes.profile_local_delete import (
            advance_profile_local_delete_command,
            reconcile_pending_identity_cleanups,
        )
        from tme3bot.infrastructure.http_client import JsonHttpError

        inventories = {
            "local": {"worker": "local", "items": [{"name": "archive"}]},
            "remote-1": {"worker": "remote-1", "items": []},
        }
        self.workers.upsert("remote-1", "https://worker.example", "remote-token")
        self.profiles.profile_registry.register("archive", 901)
        client = self.local_profile_delete_client(inventories)

        def inventory(worker):
            if worker == "remote-1":
                raise JsonHttpError(503, "worker unavailable", kind="network")
            return dict(inventories[worker])

        self.dispatcher.profile_local_inventory = inventory
        response = client.delete(
            "/api/v1/workers/local/profiles/local/archive",
            headers={**self.login(42), "Idempotency-Key": "delete-stale-inventory"},
        )
        self.assertEqual(response.status_code, 202, response.text)
        operation_id = response.json()["operation_id"]
        private = self.operation_service.store.get_private_payload(operation_id)
        advance_profile_local_delete_command(
            {"operation_id": operation_id, "private_payload": private}, self.context
        )

        completed = self.operation_service.get(self.control.actor(42), operation_id)
        self.assertEqual(completed.status.value, "succeeded")
        self.assertEqual(completed.progress["identity_mapping_status"], "pending_recheck")
        self.assertEqual(self.profiles.profile_registry.profile_for_user(901), "archive")
        self.assertEqual(
            self.profiles.profile_registry.pending_identity_cleanups()[0]["profile"],
            "archive",
        )

        self.dispatcher.profile_local_inventory = lambda worker: dict(inventories[worker])
        reconciled = reconcile_pending_identity_cleanups(self.context)
        self.assertEqual(reconciled, [])
        self.assertIsNone(self.profiles.profile_registry.profile_for_user(901))

    def test_local_profile_delete_keeps_identity_while_another_worker_has_a_copy(self):
        from tme3bot.api.routes.profile_local_delete import advance_profile_local_delete_command

        inventories = {
            "local": {"worker": "local", "items": [{"name": "archive"}]},
            "remote-1": {"worker": "remote-1", "items": [{"name": "archive"}]},
        }
        self.workers.upsert("remote-1", "https://worker.example", "remote-token")
        self.profiles.profile_registry.register("archive", 902)
        client = self.local_profile_delete_client(inventories)
        response = client.delete(
            "/api/v1/workers/local/profiles/local/archive",
            headers={**self.login(42), "Idempotency-Key": "delete-with-remote-copy"},
        )
        self.assertEqual(response.status_code, 202, response.text)
        operation_id = response.json()["operation_id"]
        private = self.operation_service.store.get_private_payload(operation_id)
        advance_profile_local_delete_command(
            {"operation_id": operation_id, "private_payload": private}, self.context
        )

        completed = self.operation_service.get(self.control.actor(42), operation_id)
        self.assertEqual(completed.status.value, "succeeded")
        self.assertEqual(completed.progress["identity_mapping_status"], "local_copy_remaining")
        self.assertEqual(self.profiles.profile_registry.profile_for_user(902), "archive")
        self.assertEqual(self.profiles.profile_registry.pending_identity_cleanups(), [])

    def test_safelink_submit_is_persisted_and_does_not_echo_input_url(self):
        self.context.queue_publisher = object()
        self.context.queue_command_service = object()
        self.seed_resolver_readiness()
        self.dispatcher.capabilities = lambda _worker: self.fail(
            "job submission must use the persisted Resolver snapshot"
        )
        client = TestClient(create_backend_app(self.context))
        auth = self.login(42)
        private_url = "https://pndk.to/private-short-token"

        options = client.get("/api/v1/safelink/workers", headers=auth)
        self.assertEqual(options.status_code, 200, options.text)
        self.assertEqual(options.json()["items"], [{
            "name": "local", "enabled": True, "status": "ready",
            "reason_code": "", "queued_jobs": 0,
        }])

        response = client.post(
            "/api/v1/safelink/jobs",
            headers={**auth, "Idempotency-Key": "safelink-submit-1"},
            json={"url": private_url, "worker": "local"},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["kind"], "safelink_resolve")
        self.assertEqual(response.json()["status"], "queued")
        self.assertEqual(response.json()["payload"], {"submitted": True})
        self.assertNotIn(private_url, response.text)
        job = self.jobs.get(response.json()["id"])
        self.assertEqual(
            self.jobs.command_payload(job.id)["payload"],
            {"url": private_url},
        )
        self.assertEqual(job.worker, "local")

    def test_decrypt_history_is_persisted_encrypted_and_scoped_to_actor(self):
        client = TestClient(create_backend_app(self.context))
        result = "https://files.example.test/private-result.zip"

        saved = client.post(
            "/api/v1/decrypt/history",
            headers=self.login(42),
            json={"result": result},
        )

        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual(saved.json()["item"]["result"], result)
        row = sqlite3.connect(self.jobs.path).execute(
            "SELECT result_ciphertext FROM decrypt_history WHERE id=?",
            (saved.json()["item"]["id"],),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertNotIn(result.encode(), bytes(row[0]))

        own_history = client.get("/api/v1/decrypt/history", headers=self.login(42))
        other_history = client.get("/api/v1/decrypt/history", headers=self.login(43))
        self.assertEqual(own_history.status_code, 200)
        self.assertEqual(own_history.json()["items"][0]["result"], result)
        self.assertEqual(own_history.json()["total"], 1)
        self.assertEqual(other_history.status_code, 200)
        self.assertEqual(other_history.json(), {"items": [], "total": 0, "next_offset": None})

    def test_decrypt_history_rejects_oversized_result_without_echoing_it(self):
        oversized = "private-" + ("x" * 65536)
        response = self.client.post(
            "/api/v1/decrypt/history",
            headers=self.login(42),
            json={"result": oversized},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "DECRYPT_HISTORY_INVALID")
        self.assertNotIn("private-", response.text)

    def test_safelink_submit_errors_are_clear_without_echoing_shortlink(self):
        self.context.queue_publisher = object()
        self.context.queue_command_service = object()
        auth = self.login(42)
        client = TestClient(create_backend_app(self.context))
        private_url = "https://pndk.to/do-not-echo-this"

        unavailable = client.post(
            "/api/v1/safelink/jobs",
            headers={**auth, "Idempotency-Key": "safelink-no-worker"},
            json={"url": private_url},
        )
        self.assertEqual(unavailable.status_code, 503, unavailable.text)
        self.assertEqual(unavailable.json()["error"]["code"], "SAFELINK_WORKER_UNAVAILABLE")
        self.assertNotIn(private_url, unavailable.text)

        self.seed_resolver_readiness()
        invalid = client.post(
            "/api/v1/safelink/jobs",
            headers={**auth, "Idempotency-Key": "safelink-invalid-host"},
            json={"url": "https://example.com/do-not-echo-this"},
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["error"]["code"], "SAFELINK_URL_INVALID")
        self.assertNotIn("do-not-echo-this", invalid.text)

        oversized_url = "https://pndk.to/" + ("x" * 2050)
        oversized = client.post(
            "/api/v1/safelink/jobs",
            headers={**auth, "Idempotency-Key": "safelink-oversized"},
            json={"url": oversized_url},
        )
        self.assertEqual(oversized.status_code, 422)
        self.assertEqual(oversized.json()["error"]["code"], "SAFELINK_URL_INVALID")
        self.assertNotIn(oversized_url, oversized.text)
        self.assertEqual(
            self.runtime_readiness_store.cell("local", None, "resolver")["status"],
            "ready",
        )

    def test_safelink_jobs_use_persisted_cancel_and_retry_operations(self):
        self.context.queue_publisher = object()
        self.context.queue_command_service = object()
        self.seed_resolver_readiness()
        client = TestClient(create_backend_app(self.context))
        auth = self.login(42)
        self.control.add_event_observer(self.operation_service.on_job_event)

        submitted = client.post(
            "/api/v1/safelink/jobs",
            headers={**auth, "Idempotency-Key": "safelink-cancel-submit"},
            json={"url": "https://pndk.to/cancel-me"},
        )
        cancel = client.post(
            f"/api/v1/safelink/jobs/{submitted.json()['id']}/cancel",
            headers={**auth, "Idempotency-Key": "safelink-cancel-1"},
        )
        self.assertEqual(cancel.status_code, 202)
        cancel_operation = self.operation_service.store.get_by_job_id(submitted.json()["id"])
        self.assertEqual(cancel_operation.status.value, "cancelling")
        self.assertEqual(
            self.runtime_readiness_store.cell("local", None, "resolver")["status"],
            "ready",
        )

        retriable = client.post(
            "/api/v1/safelink/jobs",
            headers={**auth, "Idempotency-Key": "safelink-retry-submit"},
            json={"url": "https://go.fakta.id/retry-me"},
        )
        job_id = retriable.json()["id"]
        failed = JobEvent(
            job_id=job_id,
            sequence=1,
            status=JobStatus.FAILED,
            event_type="failed",
            error={"code": "RESOLVER_FAILED", "message": "Resolver gagal."},
        )
        self.jobs.append_event(failed)
        self.operation_service.on_job_event(failed)
        self.assertEqual(
            self.runtime_readiness_store.cell("local", None, "resolver")["status"],
            "ready",
        )
        retry = client.post(
            f"/api/v1/safelink/jobs/{job_id}/retry",
            headers={**auth, "Idempotency-Key": "safelink-retry-1"},
        )
        self.assertEqual(retry.status_code, 202)
        self.assertEqual(retry.json()["status"], "queued")
        self.assertEqual(self.operation_service.store.get_by_job_id(job_id).status.value, "queued")
        self.assertEqual(self.jobs.command_payload(job_id)["payload"], {"url": "https://go.fakta.id/retry-me"})

    def test_safelink_manual_worker_gate_rejects_disabled_and_unready_before_creating_job(self):
        self.workers.upsert("remote", "http://remote-worker", "remote-secret")
        self.seed_resolver_readiness({
            "local": {"ready": True, "fingerprint": "d" * 64},
            "remote": {"ready": False, "reason_code": "RESOLVER_RUNTIME_UNAVAILABLE"},
        })
        self.context.queue_publisher = object()
        self.context.queue_command_service = object()
        client = TestClient(create_backend_app(self.context))
        auth = self.login(42)
        before = len(self.jobs.list(profile="default", limit=20))

        unready = client.post(
            "/api/v1/safelink/jobs",
            headers={**auth, "Idempotency-Key": "safelink-manual-unready"},
            json={"url": "https://pndk.to/not-ready", "worker": "remote"},
        )
        self.assertEqual(unready.status_code, 409, unready.text)
        self.assertEqual(unready.json()["error"]["code"], "RUNTIME_NOT_READY")
        self.assertEqual(len(self.jobs.list(profile="default", limit=20)), before)

        self.workers.set_enabled("remote", False)
        disabled = client.post(
            "/api/v1/safelink/jobs",
            headers={**auth, "Idempotency-Key": "safelink-manual-disabled"},
            json={"url": "https://pndk.to/disabled", "worker": "remote"},
        )
        self.assertEqual(disabled.status_code, 409, disabled.text)
        self.assertEqual(disabled.json()["error"]["code"], "WORKER_DISABLED")
        self.assertEqual(len(self.jobs.list(profile="default", limit=20)), before)

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
        vault = ProfileProvisioningStore(
            Path(self.temp.name) / "app.db", Path(self.temp.name) / "vault"
        )
        self.context.profile_provisioner = type("Provisioner", (), {"store": vault})()
        response = self.client.post(
            "/internal/v1/profiles/sync",
            headers={"Authorization": "Bearer internal"},
            json={"profiles": [{"name": "remote-1", "telegram_user_id": 42}]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profiles"], ["remote-1"])
        self.assertEqual(response.json()["adoption_candidates"], ["remote-1"])
        self.assertEqual(self.profiles.profile_registry.profile_for_user(42), "remote-1")

        changed = self.client.post(
            "/internal/v1/profiles/sync",
            headers={"Authorization": "Bearer internal"},
            json={"profiles": [{"name": "remote-1", "telegram_user_id": 43}]},
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.profiles.profile_registry.profile_for_user(42), "remote-1")
        self.assertIsNone(self.profiles.profile_registry.profile_for_user(43))

    def test_worker_profile_sync_cannot_rewrite_vaulted_identity(self):
        vault = ProfileProvisioningStore(
            Path(self.temp.name) / "app.db", Path(self.temp.name) / "vault"
        )
        operation_id = vault.begin(
            profile="vaulted", actor_user_id=42, bootstrap_worker="local",
            source="adoption", target_workers=["local"],
        )
        vault.store_bundle(
            operation_id, 4242, build_profile_bundle({"data/default": b"session"}, 4242)
        )
        self.profiles.profile_registry.register_vaulted("vaulted", 4242)
        self.context.profile_provisioner = type("Provisioner", (), {"store": vault})()

        response = self.client.post(
            "/internal/v1/profiles/sync",
            headers={"Authorization": "Bearer internal"},
            json={"profiles": [{"name": "vaulted", "telegram_user_id": 9999}]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["vault_protected"], ["vaulted"])
        self.assertEqual(self.profiles.profile_registry.profile_for_user(4242), "vaulted")
        self.assertIsNone(self.profiles.profile_registry.profile_for_user(9999))
        self.assertEqual(vault.legacy_candidates("vaulted"), [])

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
            "/api/v1/profiles/provisionings/upload?name=novel&worker=local&local_only=true",
            content=b"session-zip",
            headers={**headers, "content-type": "application/zip"},
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.json(), {"id": "operation-upload", "status": "distributing"})
        self.assertEqual(provisioner.uploaded[:3], ("novel", "local", b"session-zip"))
        self.assertTrue(provisioner.uploaded[4])

        secret_phone = "+62 812 0000 9999"
        started = self.client.post(
            "/api/v1/profiles/provisionings/login",
            headers=headers,
            json={"name": "novel", "worker": "local", "method": "code", "phone": secret_phone, "local_only": True},
        )
        self.assertEqual(started.status_code, 200)
        self.assertNotIn(secret_phone, started.text)
        self.assertEqual(provisioner.login[3], secret_phone)
        self.assertTrue(provisioner.login[5])

        state = self.client.get(
            "/api/v1/profiles/provisionings/operation-login", headers=headers
        )
        self.assertEqual(state.json()["login"]["step"], "qr")
        self.assertNotIn("actor_user_id", state.text)

    def test_profile_adoption_runs_as_a_background_operation_and_exposes_json_logs(self):
        headers = self.login()
        provisioner = FakeProfileProvisioner()
        self.context.profile_provisioner = provisioner

        denied = self.client.post(
            "/api/v1/profiles/default/adoption-diagnostics", json={"worker": "local"}
        )
        self.assertEqual(denied.status_code, 401)
        checked = self.client.post(
            "/api/v1/profiles/default/adoption-diagnostics",
            headers=headers,
            json={"worker": "local"},
        )
        self.assertEqual(checked.status_code, 200, checked.text)
        self.assertTrue(checked.json()["ready"])

        adopted = self.client.post(
            "/api/v1/profiles/default/adopt",
            headers=headers,
            json={"worker": "local"},
        )
        self.assertEqual(adopted.status_code, 200, adopted.text)
        self.assertEqual(adopted.json(), {"id": "operation-adopt", "status": "validating"})
        self.assertEqual(provisioner.adopt_call, ("default", "local", 42))

        logs = self.client.get(
            "/api/v1/diagnostics/profile-exports/logs?limit=50", headers=headers
        )
        self.assertEqual(logs.status_code, 200, logs.text)
        self.assertEqual(logs.json()["items"][0]["worker"], "local")
        self.assertEqual(logs.json()["items"][0]["code"], "PROFILE_SOURCE_READY")

    def test_vault_bundle_delete_requires_authentication_and_preserves_local_copy_contract(self):
        headers = self.login()
        provisioner = FakeProfileProvisioner()
        self.context.profile_provisioner = provisioner

        denied = self.client.delete("/api/v1/profiles/default/vault")
        self.assertEqual(denied.status_code, 401)

        response = self.client.delete("/api/v1/profiles/default/vault", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {
            "deleted": True,
            "profile": "default",
            "local_copies_unchanged": True,
        })
        self.assertEqual(provisioner.delete_vault_call, ("default", 42))

    def test_manual_vault_distribution_pins_workers_revision_and_accepts_durable_worker_events(self):
        headers = self.login()
        vault = ProfileProvisioningStore(self.jobs.path, Path(self.temp.name) / "vault")
        provision = vault.begin(
            profile="default", actor_user_id=42, bootstrap_worker="local",
            source="adoption", target_workers=["local"],
        )
        bundle = build_profile_bundle({"data/session": b"synthetic-session"}, 42)
        vault.store_bundle(provision, 42, bundle)
        distribution_store = ProfileDistributionStore(self.jobs.path)
        wake = []
        self.context.profile_provisioner = type("Provisioner", (), {"store": vault})()
        self.context.profile_distribution_store = distribution_store
        self.context.profile_distribution_service = type(
            "DistributionService", (), {"wake": lambda _self: wake.append(True)}
        )()
        self.context.bot.send_document = lambda **_kwargs: None

        response = self.client.post(
            "/api/v1/profiles/default/distributions",
            headers={**headers, "Idempotency-Key": "vault-distribution-once"},
        )
        self.assertEqual(response.status_code, 202, response.text)
        operation = response.json()
        self.assertEqual(operation["revision"], 1)
        self.assertEqual(operation["target_workers"], ["local"])
        self.assertEqual(operation["status"], "queued")
        self.assertEqual(wake, [True])

        duplicate = self.client.post(
            "/api/v1/profiles/default/distributions",
            headers={**headers, "Idempotency-Key": "vault-distribution-once"},
        )
        self.assertEqual(duplicate.status_code, 202, duplicate.text)
        self.assertEqual(duplicate.json()["id"], operation["id"])
        self.assertEqual(duplicate.json()["target_workers"], ["local"])
        self.assertEqual(wake, [True])

        internal_headers = {
            "Authorization": "Bearer internal",
            "X-Worker-Name": "local",
            "X-Worker-Token": "secret",
        }
        event = {
            "profile": "default", "revision": 1, "sequence": 1,
            "phase": "archive_download", "status": "running",
        }
        reported = self.client.post(
            f"/internal/v1/profile-distributions/{operation['id']}/events",
            headers=internal_headers,
            json=event,
        )
        self.assertEqual(reported.status_code, 200, reported.text)
        self.assertTrue(reported.json()["accepted"])
        repeated = self.client.post(
            f"/internal/v1/profile-distributions/{operation['id']}/events",
            headers=internal_headers,
            json=event,
        )
        self.assertTrue(repeated.json()["duplicate"])
        install_started = self.client.post(
            f"/internal/v1/profile-distributions/{operation['id']}/events",
            headers=internal_headers,
            json={
                "profile": "default", "revision": 1, "sequence": 2,
                "phase": "session_install", "status": "running",
            },
        )
        self.assertEqual(install_started.status_code, 200, install_started.text)
        progress = self.client.get(
            f"/api/v1/profile-distributions/{operation['id']}/events", headers=headers
        )
        self.assertEqual(progress.status_code, 200, progress.text)
        self.assertEqual(
            [item["phase"] for item in progress.json()["items"]],
            ["queued", "archive_download", "session_install"],
        )
        self.assertNotIn("synthetic-session", progress.text)

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
        self.dispatcher.tts_ready = True
        self.seed_tdl_access(worker="local", purpose="tts", profiles=["default"])
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
        self.assertGreaterEqual(current.json()["desired_version"], 1)
        self.assertEqual(current.json()["settings_status"], "applied")

        updated = self.client.put(
            "/api/v1/workers/local/settings",
            headers=headers,
            json={"storage_profile": "archive"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["storage_profile"], "archive")
        self.assertEqual(updated.json()["settings_status"], "applied")

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

    def test_backup_tdl_diagnostics_requires_auth_and_returns_worker_profile_pair(self):
        denied = self.client.post(
            "/api/v1/backups/tdl-diagnostics",
            json={"worker": "local", "profile": "default"},
        )
        self.assertEqual(denied.status_code, 401)

        response = self.client.post(
            "/api/v1/backups/tdl-diagnostics",
            headers=self.login(),
            json={"worker": "local", "profile": "default"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.dispatcher.profile_tdl_diagnostic_calls, [("local", "default")])
        self.assertEqual(response.json()["worker"], "local")
        self.assertEqual(response.json()["profile"], "default")
        self.assertEqual([item["name"] for item in response.json()["sessions"]], ["root", "user1"])
        self.assertNotIn("path", response.text.lower())

    def test_backup_tdl_diagnostics_rejects_worker_label_mismatch(self):
        self.dispatcher.profile_tdl_diagnostic_result["worker"] = "gateway"
        response = self.client.post(
            "/api/v1/backups/tdl-diagnostics",
            headers=self.login(),
            json={"worker": "local", "profile": "default"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "BACKUP_DIAGNOSTIC_WORKER_MISMATCH")
        self.assertEqual(response.json()["error"]["details"]["reported_worker"], "gateway")

    def test_backup_tdl_diagnostics_rejects_invalid_profile_before_worker_rpc(self):
        response = self.client.post(
            "/api/v1/backups/tdl-diagnostics",
            headers=self.login(),
            json={"worker": "local", "profile": "!!!"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "PROFILE_NAME_INVALID")
        self.assertEqual(self.dispatcher.profile_tdl_diagnostic_calls, [])

    def test_desired_worker_settings_are_persisted_without_worker_rpc_then_acked(self):
        headers = self.login()
        response = self.client.put(
            "/api/v1/runtime/settings?scope=worker&worker=local",
            headers=headers,
            json={
                "expected_version": 0,
                "values": {
                    "tts_helper_urls": [
                        "http://tts-1:8090",
                        "http://tts-2:8090",
                        "http://tts-3:8090",
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "pending")
        self.assertEqual(response.json()["desired_version"], 1)
        self.assertEqual(response.json()["applied_version"], 0)
        self.assertEqual(
            self.client.get(
                "/api/v1/runtime/settings?scope=worker&worker=local", headers=headers
            ).json()["settings"]["tts_helper_urls"],
            ["http://tts-1:8090", "http://tts-2:8090", "http://tts-3:8090"],
        )
        stale = self.client.put(
            "/api/v1/runtime/settings?scope=worker&worker=local",
            headers=headers,
            json={"expected_version": 0, "values": {"tts_part_retries": 4}},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["details"]["current_version"], 1)

        internal = {"Authorization": "Bearer internal"}
        denied_manifest = self.client.get(
            "/internal/v1/runtime/settings?worker=local", headers=internal
        )
        self.assertEqual(denied_manifest.status_code, 401)
        internal["X-Worker-Token"] = "secret"
        manifest = self.client.get(
            "/internal/v1/runtime/settings?worker=local", headers=internal
        )
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()["desired_version"], 1)
        wrong_scope = self.client.post(
            "/internal/v1/runtime/settings/ack",
            headers=internal,
            json={"worker": "local", "scope": "backend", "applied_version": 1},
        )
        self.assertEqual(wrong_scope.status_code, 422)
        ack = self.client.post(
            "/internal/v1/runtime/settings/ack",
            headers=internal,
            json={"worker": "local", "scope": "worker", "applied_version": 1},
        )
        self.assertEqual(ack.status_code, 200)
        self.assertEqual(ack.json()["status"], "applied")

    def test_desired_settings_api_requires_actor_and_redacts_secrets(self):
        denied = self.client.get("/api/v1/runtime/settings?scope=telegram")
        self.assertEqual(denied.status_code, 401)
        headers = self.login()
        response = self.client.get(
            "/api/v1/runtime/settings?scope=telegram", headers=headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("bot_token", response.json()["settings"])
        self.assertTrue(response.json()["secret_status"]["bot_token"])
        schema = self.client.get(
            "/api/v1/runtime/settings/schema?scope=backend", headers=headers
        )
        self.assertEqual(schema.status_code, 200)
        self.assertTrue(any(item["scope"] == "deployment" for item in schema.json()["items"]))

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
        self.assertIn(("local", None, "check"), self.dispatcher.profile_sync_requests)

    def test_worker_api_token_rotation_rejects_token_used_by_another_worker(self):
        headers = self.login()
        duplicate = "another-worker-token-long-enough"
        self.workers.upsert("remote-1", "http://remote-worker", duplicate)

        response = self.client.put(
            "/api/v1/workers/local",
            headers=headers,
            json={"url": "http://worker", "token": duplicate},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "WORKER_TOKEN_DUPLICATE")
        self.assertNotEqual(self.workers.get("local")["token"], duplicate)

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

    def test_export_submit_uses_persisted_readiness_without_worker_probe(self):
        store = RuntimeReadinessStore(Path(self.temp.name) / "runtime-readiness.json")
        self.control.runtime_readiness_gate = RuntimeReadinessGate(store)
        calls = []

        def forbidden_probe(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("Export submit must not probe the worker")

        self.dispatcher.check_worker = forbidden_probe
        self.dispatcher.profile_tdl_diagnostics = forbidden_probe

        denied = self.client.post(
            "/api/v1/exports",
            headers=self.login(),
            json={"url": "https://t.me/c/123/456"},
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(denied.json()["error"]["code"], "RUNTIME_NOT_READY")
        self.assertEqual(self.jobs.list(actor_user_id=42), [])
        self.assertEqual(calls, [])

        store.apply_export_scan(
            checked_at="2026-10-23T10:00:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [{"profile": "default", "ready": True, "fingerprint": "a" * 64}]},
        )
        response = self.client.post(
            "/api/v1/exports",
            headers=self.login(),
            json={"url": "https://t.me/c/123/457"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "dispatched")
        self.assertEqual(calls, [])

    def test_quick_export_submit_uses_quick_snapshot_and_pins_upload_evidence(self):
        store = self.runtime_readiness_store
        self.control.runtime_readiness_gate = RuntimeReadinessGate(store)
        self.dispatcher.profile_local_inventory = lambda _worker: {"items": []}
        destination = self.control._tdl_access_target("storage")
        capabilities = self.dispatcher.capabilities("local")
        senders = capabilities["storage_upload_fingerprints"]
        destination_hash = self.control.tdl_access_store.destination_fingerprint(destination)
        inventory_hash = self.control.tdl_access_store.inventory_fingerprint(
            capabilities["available_storage_profiles"], senders
        )
        self.control.tdl_access_store.replace_results(
            "local", "storage", destination_hash, inventory_hash,
            [{"profile": profile, "ready": True} for profile in senders],
            session_fingerprints=senders,
        )
        rclone_destination_fingerprint = hashlib.sha256(
            b"googledrive:backup"
        ).hexdigest()
        store.apply_export_scan(
            checked_at="2026-10-23T10:00:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [{"profile": "default", "ready": True, "fingerprint": "a" * 64}]},
        )
        store.apply_quickmode_scan(
            checked_at="2026-10-23T10:05:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [{
                "profile": "default", "ready": True, "fingerprint": "b" * 64,
                "session_fingerprint": "a" * 64,
                "destination_fingerprint": destination_hash,
                "rclone_destination_fingerprint": rclone_destination_fingerprint,
                "sender_profiles": list(senders),
                "sender_session_fingerprints": senders,
            }]},
        )
        store.upsert_cell(
            worker="local",
            profile=None,
            runtime="quick_mode_runtime",
            ready=True,
            fingerprint=hashlib.sha256(b"quick-mode-runtime").hexdigest(),
        )
        store.apply_profile_lane_scan(
            runtime="download",
            checked_at="2026-10-23T10:05:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [{
                "profile": "default",
                "ready": True,
                "fingerprint": hashlib.sha256(b"download-lane").hexdigest(),
                "session_fingerprint": "a" * 64,
            }]},
        )
        store.apply_profile_lane_scan(
            runtime="upload",
            checked_at="2026-10-23T10:05:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": [{
                "profile": profile,
                "ready": True,
                "fingerprint": hashlib.sha256(f"upload:{profile}".encode()).hexdigest(),
                "session_fingerprint": senders[profile],
            } for profile in senders]},
        )
        store.apply_storage_scan(
            checked_at="2026-10-23T10:05:00Z",
            profiles={"local": [{
                "profile": profile,
                "ready": True,
                "fingerprint": hashlib.sha256(f"storage:{profile}".encode()).hexdigest(),
                "session_fingerprint": senders[profile],
                "destination_fingerprint": destination_hash,
            } for profile in senders]},
        )

        def forbidden_capability_probe(_worker):
            self.fail("Quick Mode submit must use Profile scan evidence")

        self.dispatcher.capabilities = forbidden_capability_probe
        response = self.client.post(
            "/api/v1/exports",
            headers=self.login(),
            json={
                "url": "https://t.me/c/123/458",
                "quick_mode": True,
                "profile": "default",
                "worker": "local",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["payload"]["quick_mode"], True)
        self.assertNotIn("tdl_storage_chat_ref", str(response.json()["payload"]))
        self.assertNotIn("sender_session_fingerprints", str(response.json()["payload"]))
        worker_payload = self.dispatcher.commands[-1][1]["payload"]
        self.assertEqual(worker_payload["_quick_storage_tdl_access_target"], "123")
        self.assertEqual(worker_payload["_quick_storage_sender_session_fingerprints"], senders)

        jobs_before_stale_submit = len(self.jobs.list(actor_user_id=42))
        self.control.tdl_access_store.invalidate_profile(
            "local",
            destination_hash,
            "default",
            senders["default"],
            "TDL_SESSION_UNAUTHORIZED",
            purpose="storage",
        )
        stale = self.client.post(
            "/api/v1/exports",
            headers=self.login(),
            json={
                "url": "https://t.me/c/123/459",
                "quick_mode": True,
                "profile": "default",
                "worker": "local",
            },
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["error"]["code"], "RUNTIME_NOT_READY")
        self.assertEqual(len(self.jobs.list(actor_user_id=42)), jobs_before_stale_submit)

    def test_utility_submit_uses_worker_snapshot_and_preserves_workspace_guard(self):
        self.control.runtime_readiness_gate = RuntimeReadinessGate(
            self.runtime_readiness_store
        )
        self.runtime_readiness_store.apply_export_scan(
            checked_at="2026-10-23T10:00:00Z",
            workers=[{"worker": "local", "status": "success"}],
            profiles={"local": []},
        )
        checker_calls = []

        def forbidden_probe(worker):
            checker_calls.append(worker)
            raise AssertionError("Utility submit must use the saved runtime snapshot")

        self.dispatcher.check_worker = forbidden_probe
        headers = self.login()
        invalid_path = self.client.post(
            "/api/v1/utility/jobs",
            headers=headers,
            json={"utility": "compress", "folders": ["/etc"], "worker": "local"},
        )
        self.assertEqual(invalid_path.status_code, 422, invalid_path.text)
        self.assertEqual(invalid_path.json()["error"]["code"], "UTILITY_PATH_INVALID")

        accepted = self.client.post(
            "/api/v1/utility/jobs",
            headers=headers,
            json={"utility": "compress", "folders": ["/workspace/archive"], "worker": "local"},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["kind"], "utility")
        self.assertEqual(accepted.json()["status"], "dispatched")
        self.assertIsNone(self.runtime_readiness_store.cell("local", None, "utility"))
        self.assertEqual(checker_calls, [])

    def test_context_checker_rejects_profile_worker_pair_outside_verified_catalog(self):
        headers = self.login()
        self.workers.values["remote-1"] = {"url": "http://remote", "token": "secret"}
        self.local_profile_catalog.replace_scan(
            checked_at="2026-10-16T00:00:00Z",
            workers=[
                {"name": "local", "status": "success"},
                {"name": "remote-1", "status": "success"},
            ],
            inventories=[
                {"worker": "local", "items": [{"name": "default", "ready": True}]},
                {"worker": "remote-1", "items": [{"name": "archive", "ready": True}]},
            ],
        )
        self.control.local_profile_catalog = self.local_profile_catalog

        response = self.client.post(
            "/api/v1/context/verify", headers=headers,
            json={"purpose": "export", "profile": "archive", "worker": "local"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "PROFILE_WORKER_MISMATCH")
        self.assertEqual(response.json()["error"]["details"]["available_workers"], ["remote-1"])

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
        self.assertEqual(metrics["workers"][0]["quickmode_limit"], 2)
        self.assertEqual(metrics["workers"][0]["quickmode_slots"], 0)
        self.assertEqual(metrics["workers"][0]["quickmode_queued"], 0)
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

    def test_browser_remember_me_persists_cookie_and_session_until_logout(self):
        challenge = self.client.post(
            "/api/v1/auth/browser/challenge", json={"remember_me": True}
        )
        self.assertEqual(challenge.status_code, 200)
        body = challenge.json()
        stored_challenge = self.auth_repository.challenge_by_id(body["challenge_id"])
        self.assertEqual(stored_challenge["remember_me"], 1)
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
        refresh_cookie = next(
            value for value in session.headers.get_list("set-cookie")
            if value.startswith("tme3_refresh=")
        )
        self.assertIn("Max-Age=2147483647", refresh_cookie)
        self.assertNotIn("refresh_token", session.text)

        claims = self.auth.decode_access(self.client.cookies.get("tme3_access"))
        with self.auth_repository._db() as db:
            db.execute(
                "UPDATE auth_sessions SET expires_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", claims["sid"]),
            )
        csrf = self.client.cookies.get("tme3_csrf")
        refreshed = self.client.post(
            "/api/v1/auth/browser/refresh", headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertTrue(any(
            value.startswith("tme3_refresh=") and "Max-Age=2147483647" in value
            for value in refreshed.headers.get_list("set-cookie")
        ))

        csrf = self.client.cookies.get("tme3_csrf")
        logged_out = self.client.post(
            "/api/v1/auth/browser/logout", headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(logged_out.status_code, 200)
        self.assertTrue(logged_out.json()["revoked"])
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

    def test_activity_journal_captures_public_metadata_and_redacts_request_content(self):
        async def echo_body(body: dict):
            return {"echo": body}

        def fail_with_private_detail():
            raise DomainError(
                "ACTIVITY_TEST_FAILURE", "Detail internal yang tidak dicatat.", status_code=503
            )

        self.app.add_api_route(
            "/api/v1/test/activity-echo", echo_body, methods=["POST"], include_in_schema=False
        )
        self.app.add_api_route(
            "/api/v1/test/activity-fail", fail_with_private_detail, methods=["GET"], include_in_schema=False
        )
        headers = self.login()
        sentinels = [
            "ACTIVITY_BODY_SENTINEL",
            "ACTIVITY_HEADER_SENTINEL",
            "ACTIVITY_COOKIE_SENTINEL",
            "ACTIVITY_QUERY_SENTINEL",
            "ACTIVITY_REQUEST_ID_SENTINEL",
        ]
        self.client.cookies.set("sensitive-cookie", "ACTIVITY_COOKIE_SENTINEL")
        echoed = self.client.post(
            "/api/v1/test/activity-echo?unused=ACTIVITY_QUERY_SENTINEL",
            headers={
                **headers,
                "X-Sensitive": "ACTIVITY_HEADER_SENTINEL",
                "X-Request-ID": "ACTIVITY_REQUEST_ID_SENTINEL",
            },
            json={"value": "ACTIVITY_BODY_SENTINEL"},
        )
        self.assertEqual(echoed.status_code, 200)
        self.assertEqual(echoed.json()["echo"]["value"], sentinels[0])

        success = self.client.get("/api/v1/workers", headers=headers)
        denied = self.client.get("/api/v1/me")
        invalid = self.client.get(
            "/api/v1/diagnostics/tts/logs?limit=not-an-integer", headers=headers
        )
        try:
            failed = self.client.get("/api/v1/test/activity-fail", headers=headers)
        except BaseException:
            failed = None
        health = self.client.get("/healthz")
        internal = self.client.get(
            "/internal/v1/capabilities",
            headers={"Authorization": "Bearer internal"},
        )
        self.assertEqual(success.status_code, 200)
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(invalid.status_code, 422)
        self.assertIsNotNone(failed)
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(health.status_code, 200)
        self.assertNotIn(internal.status_code, {500})

        response = self.client.get("/api/v1/activity?limit=200", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        entries = response.json()["items"]
        by_route = {item["route"]: item for item in entries}
        self.assertEqual(by_route["/api/v1/workers"]["status_code"], 200)
        self.assertEqual(by_route["/api/v1/workers"]["actor_user_id"], 42)
        self.assertEqual(by_route["/api/v1/workers"]["profile"], "default")
        self.assertEqual(by_route["/api/v1/me"]["error_code"], "TOKEN_REQUIRED")
        self.assertEqual(by_route["/api/v1/diagnostics/tts/logs"]["error_code"], "VALIDATION_ERROR")
        self.assertEqual(by_route["/api/v1/test/activity-fail"]["error_code"], "ACTIVITY_TEST_FAILURE")
        self.assertEqual(by_route["/api/v1/test/activity-echo"]["request_id"] != sentinels[4], True)
        self.assertEqual(response.json()["retention_days"], 90)
        self.assertFalse(any("/internal/v1/" in item["route"] for item in entries))
        self.assertFalse(any(item["route"] == "/healthz" for item in entries))
        for item in entries:
            self.assertNotIn("body", item)
            self.assertNotIn("response", item)
            self.assertNotIn("headers", item)
            self.assertNotIn("cookies", item)

        page = self.client.get("/api/v1/activity?limit=1&method=POST", headers=headers)
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.json()["next_cursor"])
        filtered = self.client.get(
            "/api/v1/activity?method=GET&status_code=401&route=%2Fapi%2Fv1%2Fme",
            headers=headers,
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertTrue(all(item["status_code"] == 401 for item in filtered.json()["items"]))

        with sqlite3.connect(self.activity_journal.path) as db:
            stored = repr(db.execute("SELECT * FROM api_activity").fetchall())
        activity_response = self.client.get("/api/v1/activity?limit=200", headers=headers)
        journal_payload = activity_response.text + stored
        for sentinel in sentinels:
            self.assertNotIn(sentinel, journal_payload)

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

    def test_quick_export_requires_saved_storage_proof_and_redacts_settings(self):
        headers = self.login()
        self.dispatcher.storage_available = False
        rejected = self.client.post(
            "/api/v1/exports",
            headers=headers,
            json={"url": "https://t.me/c/1/2", "quick_mode": True},
        )
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()["error"]["code"], "TDL_ACCESS_NOT_VERIFIED")

        self.dispatcher.storage_available = True
        self.seed_tdl_access(worker="local", purpose="storage")
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
        self.seed_tdl_access(worker="local", purpose="storage")
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

    def test_storage_reconciliation_endpoint_uses_original_private_destination(self):
        headers = self.login()
        created_at = datetime.now(timezone.utc) - timedelta(minutes=3)
        source = Job(
            id="api-storage-reconcile-source",
            kind="storage_upload",
            profile="default",
            actor_user_id=42,
            worker="local",
            status=JobStatus.FAILED,
            payload={"folder_path": "/workspace/biasa"},
            result={"value": {"items": [
                {
                    "path": "ambiguous.txt", "name": "ambiguous.txt",
                    "status": "needs_reconciliation", "attempt": 1,
                    "profile": "default", "retryable": False,
                }
            ]}},
            created_at=created_at,
        )
        fingerprints = self.dispatcher.capabilities("local")["storage_upload_fingerprints"]
        private_values = {
            "tdl_storage_chat_ref": self.context.runtime_settings_store.encrypt_job_secret(
                source.id, "tdl_storage_chat_ref", "-1009876543210"
            ),
            "tdl_sender_session_fingerprints": self.context.runtime_settings_store.encrypt_job_secret(
                source.id,
                "tdl_sender_session_fingerprints",
                json.dumps({"default": fingerprints["default"]}),
            ),
        }
        self.jobs.create_with_private_values(source, private_values)

        response = self.client.post(
            f"/api/v1/jobs/{source.id}/reconcile",
            headers=headers,
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["kind"], "storage_reconcile")
        self.assertEqual(response.json()["payload"], {"source_job_id": source.id})
        self.assertNotIn("-1009876543210", response.text)
        command = self.dispatcher.commands[-1][1]
        self.assertEqual(command["payload"]["tdl_access_target"], "-1009876543210")
        self.assertEqual(command["payload"]["start_timestamp"], int(created_at.timestamp()))

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
        self.seed_tdl_access(worker="local", purpose="storage")
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
        self.seed_tdl_access(worker="local", purpose="storage")
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
        self.seed_tdl_access(worker="local", purpose="storage")
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
        self.seed_tdl_access(worker="local", purpose="storage")
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
        self.seed_tdl_access(worker="local", purpose="storage")
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
        self.seed_tdl_access(worker="local", purpose="storage")
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
        self.seed_tdl_access(worker="local", purpose="tts")
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
        self.assertEqual(job["payload"], {
            "title": "Bab rahasia",
            "character_count": len(secret_text),
            "sender_profile": "default",
        })
        self.assertEqual(job["settings_version"], 0)
        self.assertNotIn(secret_text, created.text)
        internal_command = self.dispatcher.commands[-1][1]
        self.assertEqual(internal_command["payload"]["text"], secret_text)
        encrypted_chat_ref = self.jobs.private_value(job["id"], "telegram_tts_chat_id")
        self.assertIsNotNone(encrypted_chat_ref)
        self.assertNotIn(b"123456789", encrypted_chat_ref)
        self.context.runtime_settings.update({"telegram_tts_chat_id": "987654321"})

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
        self.assertEqual(registered.json()["chat_ref"], "123456789")
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
        self.seed_tdl_access(worker="local", purpose="tts")
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

        self.dispatcher.tts_health_result["available_profiles"] = ["default"]
        self.seed_tdl_access("local", "tts", ["default"])
        self.seed_tdl_access("remote-tts", "tts", ["default"])
        self.dispatcher.capabilities = lambda _worker: self.fail(
            "TTS status and submission must use the Profile scan snapshot"
        )
        self.dispatcher.tts_health = lambda _worker: self.fail(
            "TTS status and submission must not probe helper health"
        )

        options = self.client.get("/api/v1/tts/workers", headers=headers)
        self.assertEqual(options.status_code, 200, options.text)
        self.assertEqual(
            {item["name"] for item in options.json()["items"]},
            {"local", "remote-tts"},
        )
        self.assertTrue(all(item["queued_jobs"] == 0 for item in options.json()["items"]))
        self.assertTrue(all(item["ready"] for item in options.json()["items"]))

        created = self.client.post(
            "/api/v1/tts/jobs",
            headers=headers,
            json={"title": "Bab", "text": "Isi", "worker": "remote-tts"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["worker"], "remote-tts")
        self.assertEqual(created.json()["profile"], "default")
        self.assertEqual(created.json()["payload"]["sender_profile"], "default")
        self.assertEqual(self.dispatcher.commands[-1][0], "remote-tts")

    def test_tts_access_denial_invalidates_only_matching_tts_proof_and_readiness_cell(self):
        self.dispatcher.tts_ready = True
        self.seed_tdl_access("local", "tts", ["default"])
        self.seed_tdl_access("local", "storage", ["default"])
        headers = self.login(42)
        submitted = self.client.post(
            "/api/v1/tts/jobs",
            headers=headers,
            json={"title": "Bab", "text": "Isi"},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        job = self.jobs.get(submitted.json()["id"])

        self.control._apply_event_side_effects(job, JobEvent(
            job_id=job.id,
            sequence=1,
            status=JobStatus.RUNNING,
            event_type="tdl_access.profile_denied",
            result={"profile": "default", "error_code": "CHAT_WRITE_FORBIDDEN"},
        ))

        store = self.control.tdl_access_store
        tts_destination = store.destination_fingerprint("123456789")
        storage_destination = store.destination_fingerprint("123")
        session_fingerprints = {"default": "a" * 64}
        self.assertEqual(
            store.verified_profiles(
                "local", "tts", tts_destination,
                store.inventory_fingerprint(["default"]),
                session_fingerprints=session_fingerprints,
            ),
            [],
        )
        storage_fingerprints = self.dispatcher.capabilities("local")["storage_upload_fingerprints"]
        self.assertEqual(
            store.verified_profiles(
                "local", "storage", storage_destination,
                store.inventory_fingerprint(["default"], storage_fingerprints),
                session_fingerprints=storage_fingerprints,
            ),
            ["default"],
        )
        self.assertEqual(
            self.runtime_readiness_store.cell("local", "default", "tts")["status"],
            "not_ready",
        )

    def test_tdl_access_verification_is_durable_and_target_is_private_to_owner_worker(self):
        self.context.queue_publisher = object()
        self.context.queue_command_service = object()
        client = TestClient(create_backend_app(self.context))
        headers = self.login(42)
        submitted = client.post(
            "/api/v1/tdl-access/verification",
            headers={**headers, "Idempotency-Key": "tdl-access-test-1"},
            json={"purpose": "storage", "worker": "local"},
        )
        self.assertEqual(submitted.status_code, 202, submitted.text)
        self.assertEqual(submitted.json()["status"], "queued")
        self.assertEqual(submitted.json()["target"]["job_kind"], "tdl_access_verify")
        self.assertNotIn("123", submitted.text)
        job_id = submitted.json()["job_id"]
        target_path = f"/internal/v1/tdl-access/jobs/{job_id}/target?worker=local"
        unauthorized = client.get(target_path)
        self.assertEqual(unauthorized.status_code, 401)
        wrong_worker = client.get(
            target_path.replace("worker=local", "worker=remote"),
            headers={"Authorization": "Bearer internal"},
        )
        self.assertEqual(wrong_worker.status_code, 403)
        target = client.get(target_path, headers={"Authorization": "Bearer internal"})
        self.assertEqual(target.status_code, 200, target.text)
        self.assertEqual(target.json(), {"purpose": "storage", "target": "123"})

    def test_tdl_access_status_invalidates_when_worker_inventory_changes(self):
        self.dispatcher.tts_ready = True
        self.dispatcher.tts_health_result["available_profiles"] = ["default"]
        self.seed_tdl_access("local", "storage", ["default"])
        headers = self.login(42)
        initial = self.client.get(
            "/api/v1/tdl-access/verification?purpose=storage&worker=local",
            headers=headers,
        )
        self.assertTrue(initial.json()["ready"])
        self.dispatcher.tts_health_result["available_profiles"] = ["archive"]
        stale = self.client.get(
            "/api/v1/tdl-access/verification?purpose=storage&worker=local",
            headers=headers,
        )
        self.assertFalse(stale.json()["ready"])
        self.assertEqual(stale.json()["verified_profiles"], [])

    def test_storage_status_invalidates_only_the_profile_with_a_changed_upload_session(self):
        self.dispatcher.tts_health_result["available_profiles"] = ["default", "archive"]
        self.seed_tdl_access("local", "storage", ["default", "archive"])
        self.dispatcher.storage_fingerprint_overrides["default"] = "f" * 64

        status = self.client.get(
            "/api/v1/tdl-access/verification?purpose=storage&worker=local",
            headers=self.login(42),
        )

        self.assertEqual(status.status_code, 200, status.text)
        self.assertTrue(status.json()["ready"])
        self.assertEqual(status.json()["session"], "upload")
        self.assertEqual(status.json()["verified_profiles"], ["archive"])

    def test_tts_worker_list_reads_snapshot_and_diagnostics_logs_remain_authenticated(self):
        headers = self.login()
        store = ProfileProvisioningStore(
            Path(self.temp.name) / "diagnostic.db", Path(self.temp.name) / "diagnostic-vault"
        )
        self.context.profile_provisioner = type("Provisioner", (), {"store": store})()
        self.dispatcher.tts_health_result = {
            "helpers_ready": False,
            "available_profiles": ["default"],
            "helpers": [
                {"slot": slot, "status": "tor_unreachable", "bootstrap_percent": None}
                for slot in range(1, 4)
            ],
        }
        response = self.client.get("/api/v1/tts/workers", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertFalse(response.json()["items"][0]["ready"])
        self.assertEqual(response.json()["items"][0]["reason_code"], "tts_helper_not_scanned")
        self.assertEqual(store.diagnostic_logs(42, "tts", 20), [])

        self.client.get("/api/v1/workers/local/tts/health", headers=headers)

        denied = self.client.get("/api/v1/diagnostics/tts/logs")
        self.assertEqual(denied.status_code, 401)
        logs = self.client.get("/api/v1/diagnostics/tts/logs?limit=20", headers=headers)
        self.assertEqual(logs.status_code, 200, logs.text)
        self.assertEqual(logs.json()["items"][0]["worker"], "local")
        self.assertEqual(logs.json()["items"][0]["event"], "worker_health_check")

if __name__ == "__main__":
    unittest.main()
