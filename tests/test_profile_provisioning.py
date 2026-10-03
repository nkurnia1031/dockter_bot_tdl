import io
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from tme3bot.config import AppConfig
from tme3bot.profile_provisioning import (
    ProfileProvisioningService,
    ProfileProvisioningStore,
    build_profile_bundle,
    extract_single_session,
    profile_transfer_is_secure,
)
from tme3bot.worker.profile_sessions import ProfileSessionManager
from tme3bot.profile_registry import ProfileRegistry


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

    def validate_profile_session(self, worker, data):
        return 987654

    def install_profile_bundle(self, worker, profile, user_id, bundle, operation_id):
        if worker not in self.online:
            raise RuntimeError("worker offline")
        self.installed[(profile, worker)] = (user_id, bundle, operation_id)
        return {"ready": True}

    def commit_profile_bundle(self, worker, profile, operation_id):
        self.committed.append((worker, profile, operation_id))

    def cancel_profile_login(self, worker, operation_id):
        return None

    def remove_profile_bundle(self, worker, profile, operation_id):
        self.installed.pop((profile, worker), None)


class MutableWorkerRegistry(FakeWorkerRegistry):
    def add(self, name, enabled=True, url="https://worker.example"):
        self.workers[name] = {"enabled": enabled, "url": url}


class ProfileProvisioningTests(unittest.TestCase):
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

    def test_vault_encrypts_session_and_gates_worker_until_distribution_ready(self):
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
            store.update_distribution("novel", "remote", "ready", provisioning_id=operation)
            store.mark_active(operation)
            self.assertTrue(store.distribution_ready("novel", "local"))
            self.assertFalse(store.distribution_ready("novel", "new-worker"))

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

    def test_adoption_cannot_replace_the_default_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = ProfileProvisioningService(
                ProfileProvisioningStore(root / "storage.db", root / "vault"),
                FakeProfileManager(root),
                FakeWorkerRegistry(),
                FakeProfileDispatcher(),
            )
            with self.assertRaisesRegex(ValueError, "default"):
                service.adopt("default", "local", 42)

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
            self.assertFalse(service.worker_ready("novel", "local"))

            dispatcher.online.add("remote-offline")
            service.process_once()
            self.assertIn("novel", manager.list_profiles())
            self.assertTrue(service.worker_ready("novel", "local"))
            self.assertTrue(service.worker_ready("novel", "remote-offline"))

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
