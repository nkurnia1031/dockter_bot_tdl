import io
import sqlite3
import threading
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from tme3bot.config import AppConfig
from tme3bot.profile_provisioning import (
    ProfileProvisioningService,
    ProfileProvisioningStore,
    build_profile_bundle,
    extract_single_session,
    profile_transfer_is_secure,
    validate_profile_bundle,
)
from tme3bot.worker.profile_sessions import ProfileSessionManager
from tme3bot.profile_registry import ProfileRegistry
from tme3bot.worker.executor import WorkerJobExecutor


def make_config(root: Path) -> AppConfig:
    return AppConfig(
        bot_token="token",
        profile_root=str(root),
        profiles_root=root / "profiles",
        default_profile="default",
        tme3_host="t.me3",
        download_root=root / "download",
        export_pending_dir=root / "exports" / "pending",
        export_processing_dir=root / "exports" / "processing",
        export_done_dir=root / "exports" / "done",
        export_failed_dir=root / "exports" / "failed",
        state_file=root / "state.json",
        legacy_max_json=root / "max.json",
        tdl_export_user="user1",
        tdl_download_user="root",
        tdl_export_home=root / "user1",
        tdl_download_home=root / "root",
        tdl_export_storage=root / "user1" / ".tdl",
        tdl_download_storage=root / "root" / ".tdl",
        tdl_export_namespace="default",
        tdl_download_namespace="default",
        tdl_export_stall_timeout_seconds=300,
        tdl_download_stall_timeout_seconds=1800,
        temp_root=root / "tmp",
        log_level="INFO",
        app_role="worker",
    )


def single_session_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(".tdl/data/default", b"bolt-session")
        archive.writestr(".tdl/config.toml", "namespace = 'default'")
    return output.getvalue()


class FakeWorkerRegistry:
    def __init__(self):
        self.workers = {
            "local": {"enabled": True, "url": "http://worker-local:8080"},
            "remote-offline": {"enabled": False, "url": "https://worker.example"},
        }

    def names(self):
        return list(self.workers)

    def get(self, name):
        return self.workers.get(name)


class FakeProfileManager:
    def __init__(self, root: Path):
        self.default_profile = "default"
        self.profile_registry = ProfileRegistry(root / "profiles.json", "default")

    def list_profiles(self):
        return self.profile_registry.names()


class FakeProfileDispatcher:
    def __init__(self):
        self.online = {"local"}
        self.installed = {}
        self.committed = []
        self.profile_sync_contexts = []
        self.login_state_value = {"status": "waiting_input", "step": "qr", "qr_text": "qr-test"}
        self.login_bundle_downloads = []
        self.profile_diagnostic_result = {
            "ready": True,
            "reason_codes": [],
            "checks": [
                {"name": "identity", "ready": True, "code": "PROFILE_IDENTITY_READY"},
                {"name": "root_session", "ready": True, "code": "PROFILE_ROOT_SESSION_READY"},
                {"name": "user1_session", "ready": True, "code": "PROFILE_USER1_SESSION_READY"},
            ],
        }

    def validate_profile_session(self, worker, data):
        return 987654

    def start_profile_login(self, worker, operation_id, method, phone):
        return {"status": "running"}

    def profile_login_state(self, worker, operation_id):
        return dict(self.login_state_value)

    def profile_login_bundle(self, worker, operation_id):
        self.login_bundle_downloads.append((worker, operation_id))
        return single_session_zip()

    def export_profile_bundle(self, worker, profile):
        return 987654, build_profile_bundle({"data/default": b"vault-session"}, 987654)

    def profile_export_diagnostics(self, worker, profile):
        return dict(self.profile_diagnostic_result)

    def install_profile_bundle(self, worker, profile, user_id, bundle, operation_id, **sync_context):
        self.profile_sync_contexts.append((worker, profile, dict(sync_context)))
        if worker not in self.online:
            raise RuntimeError("worker offline")
        self.installed[(profile, worker)] = (user_id, bundle, operation_id)
        return {"ready": True}

    def commit_profile_bundle(self, worker, profile, operation_id, **sync_context):
        self.committed.append((worker, profile, operation_id))

    def cancel_profile_login(self, worker, operation_id):
        return None

    def remove_profile_bundle(self, worker, profile, operation_id):
        self.installed.pop((profile, worker), None)


class MutableWorkerRegistry(FakeWorkerRegistry):
    def add(self, name, enabled=True, url="https://worker.example"):
        self.workers[name] = {"enabled": enabled, "url": url}


class ProfileProvisioningTests(unittest.TestCase):
    def test_legacy_profile_export_diagnosis_checks_both_sessions_without_exposing_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = ProfileSessionManager(make_config(root))
            missing = manager.diagnose_export_bundle("storage")
            self.assertFalse(missing["ready"])
            self.assertIn("PROFILE_IDENTITY_MISSING", missing["reason_codes"])

            profile_root = root / "profiles" / "storage"
            profile_root.mkdir(parents=True)
            (profile_root / "identity.json").write_text(
                '{"telegram_user_id":123,"tdl_user_id":123}', encoding="utf-8"
            )
            for session in ("root/.tdl/data", "user1/.tdl/data"):
                session_root = profile_root / Path(session)
                session_root.mkdir(parents=True)
                (session_root / "default").write_bytes(b"session")

            ready = manager.diagnose_export_bundle("storage")
            self.assertTrue(ready["ready"])
            self.assertEqual([item["name"] for item in ready["checks"]], ["identity", "root_session", "user1_session"])
            self.assertNotIn(str(profile_root), str(ready))

            (profile_root / "user1" / ".tdl" / "data" / "default").unlink()
            incomplete = manager.diagnose_export_bundle("storage")
            self.assertFalse(incomplete["ready"])
            self.assertIn("PROFILE_USER1_SESSION_EMPTY", incomplete["reason_codes"])

    def test_profile_adoption_export_waits_until_both_tdl_lanes_are_locked(self):
        runtime = SimpleNamespace(
            export_operation_lock=threading.Lock(),
            download_operation_lock=threading.Lock(),
        )

        class FakeProfileManager:
            def runtime(self, _profile):
                return runtime

        class FakeSessionExporter:
            def export_bundle(self, _profile):
                return (
                    123,
                    (runtime.export_operation_lock.locked(), runtime.download_operation_lock.locked()),
                )

            def install_bundle(self, _profile, _user_id, _bundle, _operation_id):
                return {
                    "locked": (
                        runtime.export_operation_lock.locked(),
                        runtime.download_operation_lock.locked(),
                    )
                }

        executor = object.__new__(WorkerJobExecutor)
        executor.profile_manager = FakeProfileManager()
        executor._profile_sessions = FakeSessionExporter()

        self.assertEqual(executor.export_profile_bundle("default"), (123, (True, True)))
        self.assertEqual(
            executor.install_profile_bundle("default", 123, b"bundle", "sync-1"),
            {"locked": (True, True)},
        )

    def test_tdl_login_validation_runs_in_background_after_manual_status_refresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dispatcher = FakeProfileDispatcher()
            store = ProfileProvisioningStore(root / "storage.db", root / "vault")
            workers = MutableWorkerRegistry()
            service = ProfileProvisioningService(
                store, FakeProfileManager(root), workers, dispatcher
            )

            operation = service.start_login("novel", "local", "qr", None, 42)
            dispatcher.login_state_value = {"status": "ready", "step": ""}
            refreshed = service.operation(operation, 42)

            self.assertEqual(refreshed["status"], "validating")
            self.assertEqual(refreshed["login"]["status"], "validating")
            self.assertEqual(dispatcher.login_bundle_downloads, [])

            service.process_once()

            self.assertEqual(dispatcher.login_bundle_downloads, [("local", operation)])
            self.assertEqual(store.provisioning(operation)["status"], "distributing")

    def test_single_session_zip_is_duplicated_into_independent_profile_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = extract_single_session(single_session_zip())
            bundle = build_profile_bundle(session, 123456)
            manager = ProfileSessionManager(make_config(root))

            manager.install_bundle("novel", 123456, bundle, "operation-1")
            profile_root = root / "profiles" / "novel"
            download_db = profile_root / "root" / ".tdl" / "data" / "default"
            export_db = profile_root / "user1" / ".tdl" / "data" / "default"
            self.assertEqual(download_db.read_bytes(), b"bolt-session")
            self.assertEqual(export_db.read_bytes(), b"bolt-session")
            self.assertNotEqual(download_db.resolve(), export_db.resolve())
            self.assertEqual(
                manager.export_bundle("novel")[0],
                123456,
            )
            self.assertTrue(manager.commit_bundle("novel", "operation-1"))
            self.assertFalse((profile_root / ".profile-provisioning.json").exists())

    def test_installed_profile_integrity_requires_both_independent_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = ProfileSessionManager(make_config(root))
            bundle = build_profile_bundle(
                extract_single_session(single_session_zip()), 123456
            )

            manager.install_bundle("novel", 123456, bundle, "integrity-check")

            self.assertEqual(manager.verify_installed("novel"), 123456)
            self.assertFalse(manager.verify_installed("novel", 123457))
            (root / "profiles" / "novel" / "root" / ".tdl" / "data" / "default").unlink()
            self.assertFalse(manager.verify_installed("novel"))

    def test_worker_restart_cleans_abandoned_login_data_but_keeps_install_backups(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            provisioning_root = root / "tmp" / "profile-provisioning"
            stale_login = provisioning_root / "logins" / "old-operation"
            stale_login.mkdir(parents=True)
            (stale_login / "session.db").write_bytes(b"temporary-session")
            backup = provisioning_root / "backups" / "install-operation" / "novel"
            backup.mkdir(parents=True)
            (backup / "previous-session.db").write_bytes(b"rollback-session")

            ProfileSessionManager(make_config(root))

            self.assertFalse(stale_login.exists())
            self.assertTrue((backup / "previous-session.db").exists())

    def test_cancel_rolls_back_existing_worker_profile_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = make_config(root)
            profile_root = root / "profiles" / "novel"
            old_root = profile_root / "root" / ".tdl" / "data" / "default"
            old_export = profile_root / "user1" / ".tdl" / "data" / "default"
            old_root.parent.mkdir(parents=True)
            old_export.parent.mkdir(parents=True)
            old_root.write_bytes(b"old-root-session")
            old_export.write_bytes(b"old-export-session")
            (profile_root / "identity.json").write_text('{"telegram_user_id":77}')
            manager = ProfileSessionManager(config)
            bundle = build_profile_bundle({"data/default": b"new-session"}, 88)

            manager.install_bundle("novel", 88, bundle, "operation-2")
            self.assertEqual(old_root.read_bytes(), b"new-session")
            self.assertTrue(manager.rollback_bundle("novel", "operation-2"))
            self.assertEqual(old_root.read_bytes(), b"old-root-session")
            self.assertEqual(old_export.read_bytes(), b"old-export-session")
            identity = (profile_root / "identity.json").read_text()
            self.assertIn("77", identity)

    def test_default_bundle_install_rolls_back_or_commits_without_touching_backend_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = make_config(root)
            old_root = root / "root" / ".tdl" / "data" / "default"
            old_export = root / "user1" / ".tdl" / "data" / "default"
            old_root.parent.mkdir(parents=True)
            old_export.parent.mkdir(parents=True)
            old_root.write_bytes(b"old-root-session")
            old_export.write_bytes(b"old-export-session")
            (root / "identity.json").write_text('{"telegram_user_id":77}')
            config.state_file.write_text("backend-state")
            manager = ProfileSessionManager(config)
            bundle = build_profile_bundle({"data/default": b"new-session"}, 88)

            manager.install_bundle("default", 88, bundle, "default-replace-1")

            self.assertEqual(old_root.read_bytes(), b"new-session")
            self.assertEqual(old_export.read_bytes(), b"new-session")
            self.assertEqual((root / "identity.json").read_text(), '{"telegram_user_id": 88, "tdl_user_id": 88}')
            self.assertEqual(config.state_file.read_text(), "backend-state")
            self.assertTrue(manager.rollback_bundle("default", "default-replace-1"))
            self.assertEqual(old_root.read_bytes(), b"old-root-session")
            self.assertEqual(old_export.read_bytes(), b"old-export-session")
            self.assertIn("77", (root / "identity.json").read_text())
            self.assertEqual(config.state_file.read_text(), "backend-state")

            manager.install_bundle("default", 88, bundle, "default-replace-2")
            self.assertTrue(manager.commit_bundle("default", "default-replace-2"))
            self.assertEqual(old_root.read_bytes(), b"new-session")
            self.assertEqual(old_export.read_bytes(), b"new-session")
            self.assertEqual(config.state_file.read_text(), "backend-state")
            self.assertFalse((root / ".profile-provisioning-backups").exists())

    def test_zip_path_traversal_and_missing_tdl_directory_are_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("../escape", b"bad")
        with self.assertRaises(ValueError):
            extract_single_session(output.getvalue())

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("other/data/default", b"bad")
        with self.assertRaises(ValueError):
            extract_single_session(output.getvalue())

    def test_vault_encrypts_session_and_gates_each_worker_independently(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ProfileProvisioningStore(root / "storage.db", root / "vault")
            operation = store.begin(
                profile="novel",
                actor_user_id=7,
                bootstrap_worker="local",
                source="upload",
                target_workers=["local", "remote"],
            )
            bundle = build_profile_bundle({"data/default": b"secret-session"}, 123)
            store.store_bundle(operation, 123, bundle)

            db = sqlite3.connect(root / "storage.db")
            try:
                encrypted = db.execute(
                    "SELECT encrypted_bundle FROM profile_sessions WHERE profile='novel'"
                ).fetchone()[0]
            finally:
                db.close()
            self.assertNotIn(b"secret-session", encrypted)
            self.assertEqual(store.bundle("novel"), (123, bundle))
            self.assertFalse(store.distribution_ready("novel", "local"))
            self.assertTrue(store.distribution_ready("legacy", "remote"))

            store.update_distribution("novel", "local", "ready", provisioning_id=operation)
            self.assertTrue(store.distribution_ready("novel", "local"))
            self.assertFalse(store.distribution_ready("novel", "remote"))
            # One unavailable worker keeps the provisioning operation pending,
            # but does not prevent using a worker that has installed the bundle.
            store.mark_active(operation)
            self.assertTrue(store.distribution_ready("novel", "local"))
            self.assertFalse(store.list_profiles()[0]["active"])
            self.assertEqual(store.provisioning(operation)["status"], "distributing")

            store.update_distribution("novel", "remote", "ready", provisioning_id=operation)
            store.mark_active(operation)
            self.assertTrue(store.distribution_ready("novel", "local"))
            self.assertFalse(store.distribution_ready("novel", "new-worker"))

    def test_worker_added_after_snapshot_gets_desired_revision_without_blocking_activation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ProfileProvisioningStore(root / "storage.db", root / "vault")
            operation = store.begin(
                profile="novel", actor_user_id=7, bootstrap_worker="local",
                source="upload", target_workers=["local", "offline-disabled"],
            )
            bundle = build_profile_bundle({"data/default": b"revision-one"}, 123)
            store.store_bundle(operation, 123, bundle)
            desired = store.desired_revision("novel")
            self.assertEqual(desired["revision"], 1)

            store.update_distribution("novel", "local", "ready", provisioning_id=operation)
            store.add_worker_for_active_profiles("worker-added-later")
            self.assertEqual(
                store.profile_manifest("worker-added-later")[0]["revision"], 1
            )
            self.assertFalse(store.distribution_ready("novel", "worker-added-later"))

            store.mark_active(operation)
            self.assertFalse(store.list_profiles()[0]["active"])
            store.update_distribution(
                "novel", "offline-disabled", "ready", provisioning_id=operation
            )
            store.mark_active(operation)
            self.assertTrue(store.list_profiles()[0]["active"])
            self.assertFalse(store.distribution_ready("novel", "worker-added-later"))

    def test_new_bundle_creates_revision_without_mutating_previous_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ProfileProvisioningStore(root / "storage.db", root / "vault")
            first_operation = store.begin(
                profile="novel", actor_user_id=7, bootstrap_worker="local",
                source="upload", target_workers=["local"],
            )
            first_bundle = build_profile_bundle({"data/default": b"first-session"}, 123)
            store.store_bundle(first_operation, 123, first_bundle)
            first = store.desired_revision("novel")
            store.update_distribution("novel", "local", "ready", provisioning_id=first_operation)
            store.mark_active(first_operation)

            second_operation = store.begin(
                profile="novel", actor_user_id=7, bootstrap_worker="local",
                source="adoption", target_workers=["local"],
            )
            second_bundle = build_profile_bundle({"data/default": b"second-session"}, 123)
            store.store_bundle(second_operation, 123, second_bundle)
            second = store.desired_revision("novel")

            self.assertEqual((first["revision"], second["revision"]), (1, 2))
            self.assertNotEqual(first["bundle_sha256"], second["bundle_sha256"])
            self.assertEqual(store.bundle("novel"), (123, second_bundle))
            with store._db() as db:
                revisions = db.execute(
                    "SELECT revision,bundle_sha256 FROM profile_session_revisions WHERE profile='novel' ORDER BY revision"
                ).fetchall()
            self.assertEqual([int(row["revision"]) for row in revisions], [1, 2])
            self.assertEqual(str(revisions[0]["bundle_sha256"]), first["bundle_sha256"])

    def test_store_bundle_rejects_identity_that_does_not_match_session_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ProfileProvisioningStore(root / "storage.db", root / "vault")
            operation = store.begin(
                profile="novel",
                actor_user_id=7,
                bootstrap_worker="local",
                source="upload",
                target_workers=["local"],
            )
            bundle = build_profile_bundle({"data/default": b"session"}, 123)

            with self.assertRaisesRegex(ValueError, "Identity bundle"):
                store.store_bundle(operation, 456, bundle)
            self.assertIsNone(store.bundle("novel"))

    def test_default_profile_can_be_adopted_and_distributed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ProfileProvisioningStore(root / "storage.db", root / "vault")
            service = ProfileProvisioningService(
                store,
                FakeProfileManager(root),
                FakeWorkerRegistry(),
                FakeProfileDispatcher(),
            )

            default_profile = next(
                item for item in service.profiles() if item["name"] == "default"
            )
            self.assertEqual(default_profile["status"], "legacy")
            self.assertTrue(default_profile["adoptable"])

            operation = service.adopt("default", "local", 42)

            self.assertIsNone(store.bundle("default"))
            self.assertEqual(store.provisioning(operation)["status"], "validating")
            service.process_once()

            stored_user_id, stored_bundle = store.bundle("default")
            self.assertEqual(stored_user_id, 987654)
            validate_profile_bundle(stored_bundle)
            with zipfile.ZipFile(io.BytesIO(stored_bundle)) as archive:
                self.assertEqual(archive.read("root/.tdl/data/default"), b"vault-session")
                self.assertEqual(archive.read("user1/.tdl/data/default"), b"vault-session")
            info = store.provisioning(operation)
            self.assertEqual(info["status"], "distributing")
            self.assertEqual(
                {item["worker"] for item in info["workers"]},
                {"local", "remote-offline"},
            )

    def test_adoption_source_diagnostics_and_operation_logs_are_json_safe_and_actor_scoped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ProfileProvisioningStore(root / "storage.db", root / "vault")
            service = ProfileProvisioningService(
                store, FakeProfileManager(root), FakeWorkerRegistry(), FakeProfileDispatcher()
            )

            result = service.diagnose_adoption("default", "local", 42)

            self.assertTrue(result["ready"])
            self.assertEqual(result["worker"], "local")
            self.assertNotIn("path", str(result).lower())
            operation_id = service.adopt("default", "local", 42)
            service.process_once()
            owner_logs = store.provisioning_logs(operation_id, 42)
            self.assertTrue(owner_logs)
            self.assertIsNone(store.provisioning_logs(operation_id, 43))
            self.assertIn("TARGET_INSTALL_READY", {item["code"] for item in owner_logs})

            store.append_diagnostic_log(
                category="profile_export",
                actor_user_id=42,
                event_type="source_check",
                code="PROFILE_SESSION_UNAVAILABLE",
                details={"checks": [{"name": "root/.tdl/data", "ready": False, "code": "x", "secret": "hidden"}]},
            )
            logs = store.diagnostic_logs(42, "profile_export")
            self.assertNotIn("secret", str(logs))
            self.assertNotIn("root/.tdl/data", str(logs))

    def test_failed_adoption_can_be_retried_with_a_selected_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ProfileProvisioningStore(root / "storage.db", root / "vault")
            dispatcher = FakeProfileDispatcher()
            dispatcher.profile_diagnostic_result = {
                "ready": False,
                "reason_codes": ["PROFILE_ROOT_SESSION_MISSING"],
                "checks": [{"name": "root_session", "ready": False, "code": "PROFILE_ROOT_SESSION_MISSING"}],
            }
            workers = FakeWorkerRegistry()
            service = ProfileProvisioningService(store, FakeProfileManager(root), workers, dispatcher)

            operation_id = service.adopt("default", "local", 42)
            self.assertEqual(store.provisioning(operation_id)["status"], "validating")
            service.process_once()
            self.assertEqual(store.provisioning(operation_id)["status"], "failed")
            self.assertIsNone(store.bundle("default"))

            dispatcher.profile_diagnostic_result = {"ready": True, "reason_codes": [], "checks": []}
            service.retry(operation_id, 42, "local")
            self.assertEqual(store.provisioning(operation_id)["bootstrap_worker"], "local")
            self.assertEqual(store.provisioning(operation_id)["status"], "validating")
            service.process_once()
            self.assertEqual(store.provisioning(operation_id)["status"], "distributing")
            self.assertIsNotNone(store.bundle("default"))

    def test_profile_names_must_not_be_silently_rewritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = ProfileProvisioningService(
                ProfileProvisioningStore(root / "storage.db", root / "vault"),
                FakeProfileManager(root),
                FakeWorkerRegistry(),
                FakeProfileDispatcher(),
            )
            with self.assertRaisesRegex(ValueError, "Nama profil"):
                service.start_login("novel/name", "local", "qr", None, 42)

    def test_login_phone_input_rejects_line_breaks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = ProfileProvisioningService(
                ProfileProvisioningStore(root / "storage.db", root / "vault"),
                FakeProfileManager(root),
                FakeWorkerRegistry(),
                FakeProfileDispatcher(),
            )
            with self.assertRaisesRegex(ValueError, "Nomor telepon"):
                service.start_login("novel", "local", "code", "+62 812\nlogin", 42)

    def test_profile_transfers_require_https_except_internal_worker_hosts(self):
        self.assertTrue(profile_transfer_is_secure("https://worker.example:8090"))
        self.assertTrue(profile_transfer_is_secure("http://worker-local:8080"))
        self.assertTrue(profile_transfer_is_secure("http://resolver:8080"))
        self.assertFalse(profile_transfer_is_secure("http://remote.example:8080"))
        self.assertFalse(profile_transfer_is_secure("https://user:secret@worker.example"))

    def test_remote_http_worker_stays_pending_with_a_safe_actionable_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workers = MutableWorkerRegistry()
            workers.add("remote-http", url="http://remote.example:8080")
            dispatcher = FakeProfileDispatcher()
            dispatcher.online.add("remote-http")
            store = ProfileProvisioningStore(root / "storage.db", root / "vault")
            service = ProfileProvisioningService(store, FakeProfileManager(root), workers, dispatcher)

            operation = service.upload("novel", "local", single_session_zip(), 42)
            service.process_once()
            state = store.provisioning(operation)
            remote = next(item for item in state["workers"] if item["worker"] == "remote-http")

            self.assertEqual(remote["status"], "failed")
            self.assertIn("HTTPS", remote["error"])
            self.assertNotIn("remote.example", remote["error"])
            self.assertNotIn(("novel", "remote-http"), dispatcher.installed)

    def test_duplicate_telegram_identity_is_rejected_and_operation_is_cleaned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = FakeProfileManager(root)
            workers = MutableWorkerRegistry()
            store = ProfileProvisioningStore(root / "storage.db", root / "vault")
            service = ProfileProvisioningService(store, manager, workers, FakeProfileDispatcher())

            service.upload("first", "local", single_session_zip(), 42)
            with self.assertRaisesRegex(FileExistsError, "Akun Telegram"):
                service.upload("second", "local", single_session_zip(), 42)

            self.assertIsNone(store.bundle("second"))
            with store._db() as db:
                row = db.execute(
                    "SELECT status FROM profile_provisionings WHERE profile='second'"
                ).fetchone()
            self.assertEqual(row["status"], "cancelled")

    def test_profile_management_hides_operation_id_from_other_actor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ProfileProvisioningStore(root / "storage.db", root / "vault")
            service = ProfileProvisioningService(
                store,
                FakeProfileManager(root),
                MutableWorkerRegistry(),
                FakeProfileDispatcher(),
            )
            operation = service.upload("novel", "local", single_session_zip(), 42)

            profile_for_owner = next(item for item in service.profiles(42) if item["name"] == "novel")
            profile_for_other = next(item for item in service.profiles(99) if item["name"] == "novel")
            self.assertEqual(profile_for_owner["operation_id"], operation)
            self.assertIsNone(profile_for_other["operation_id"])

    def test_profile_waits_for_disabled_offline_worker_then_syncs_future_workers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = FakeProfileManager(root)
            workers = MutableWorkerRegistry()
            dispatcher = FakeProfileDispatcher()
            store = ProfileProvisioningStore(root / "storage.db", root / "vault")
            service = ProfileProvisioningService(store, manager, workers, dispatcher)

            operation = service.upload("novel", "local", single_session_zip(), 42)
            service.process_once()
            state = store.provisioning(operation)
            self.assertEqual(state["status"], "distributing")
            self.assertEqual(
                {item["worker"]: item["status"] for item in state["workers"]},
                {"local": "ready", "remote-offline": "waiting"},
            )
            self.assertNotIn("novel", manager.list_profiles())
            self.assertTrue(service.worker_ready("novel", "local"))
            self.assertFalse(service.worker_ready("novel", "remote-offline"))
            offline_logs = store.profile_sync_logs("novel", "remote-offline")
            self.assertEqual(offline_logs["latest_status"], "waiting")
            self.assertEqual(offline_logs["items"][-1]["phase"], "worker_unreachable")
            self.assertEqual(offline_logs["items"][-1]["code"], "WORKER_UNAVAILABLE")
            local_context = next(item[2] for item in dispatcher.profile_sync_contexts if item[0] == "local")
            self.assertEqual(local_context["revision"], 1)
            self.assertRegex(local_context["sync_run_id"], r"^[a-f0-9]{32}$")

            dispatcher.online.add("remote-offline")
            service.process_once()
            self.assertIn("novel", manager.list_profiles())
            self.assertTrue(service.worker_ready("novel", "local"))
            self.assertTrue(service.worker_ready("novel", "remote-offline"))
            remote_logs = store.profile_sync_logs("novel", "remote-offline")
            self.assertEqual(remote_logs["latest_status"], "succeeded")
            self.assertEqual(remote_logs["items"][-1]["code"], "PROFILE_SYNC_INSTALLED")

            workers.add("future-worker")
            dispatcher.online.add("future-worker")
            service.process_once()
            self.assertIn(("novel", "future-worker"), dispatcher.installed)
            self.assertTrue(service.worker_ready("novel", "future-worker"))

            committed_before_retry = len(dispatcher.committed)
            store.update_distribution("novel", "remote-offline", "failed", provisioning_id=operation)
            service.retry(operation, 42)
            service.process_once()
            self.assertGreater(len(dispatcher.committed), committed_before_retry)
            self.assertIn(("remote-offline", "novel", operation), dispatcher.committed)


if __name__ == "__main__":
    unittest.main()
