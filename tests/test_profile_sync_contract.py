import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from tme3bot.api.routes.profile_sync import (
    advance_profile_sync_cancel,
    advance_profile_sync_command,
    prepare_profile_sync_operation,
    register_profile_sync,
)
from tme3bot.domain.models import Actor, DomainError
from tme3bot.profile_provisioning import ProfileProvisioningStore, build_profile_bundle
from tme3bot.profile_registry import ProfileRegistry
from tme3bot.worker_registry import WorkerRegistry


class ProfileSyncContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = ProfileProvisioningStore(root / "state.db", root / "vault")
        self.workers = WorkerRegistry(root / "workers.json")
        self.workers.upsert("worker-a", "https://worker-a.example", "worker-token-a")
        self.workers.upsert("worker-b", "https://worker-b.example", "worker-token-b")
        self.workers.upsert("worker-c", "https://worker-c.example", "worker-token-c")
        self.profile_registry = ProfileRegistry(
            root / "profile-registry.json", "default"
        )
        self.context = SimpleNamespace(
            profile_provisioner=SimpleNamespace(
                store=self.store,
                profile_manager=SimpleNamespace(profile_registry=self.profile_registry),
            ),
            worker_registry=self.workers,
            operation_service=None,
            control_plane=SimpleNamespace(require_profile=lambda actor, profile: profile),
        )
        self.app = FastAPI()

        @self.app.exception_handler(DomainError)
        async def domain_error_handler(_request: Request, exc: DomainError):
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": exc.code, "message": exc.message}},
            )

        register_profile_sync(self.app, self.context, require_internal=lambda: None)
        self.secure_client = TestClient(self.app, base_url="https://gateway.example")
        self.bundle = build_profile_bundle({"data/default": b"tdl-session"}, 10001)
        self.provisioning_id = self.store.begin(
            profile="novel",
            actor_user_id=9,
            bootstrap_worker="worker-a",
            source="upload",
            target_workers=["worker-a", "worker-b"],
        )
        self.store.store_bundle(self.provisioning_id, 10001, self.bundle)

    def tearDown(self):
        self.secure_client.close()
        self.temp.cleanup()

    def headers(self, worker, *, token=None):
        record = self.workers.get(worker)
        return {
            "Authorization": "Bearer backend-internal-token",
            "X-Worker-Name": worker,
            "X-Worker-Token": token or record["token"],
        }

    def test_revision_is_immutable_and_worker_scope_is_enforced(self):
        first = self.store.desired_revision("novel")
        self.assertEqual(first["revision"], 1)
        self.assertEqual(first["bundle_sha256"], hashlib.sha256(self.bundle).hexdigest())

        manifest = self.secure_client.get(
            "/internal/v1/profile-manifest", headers=self.headers("worker-a")
        )
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()["profiles"], [{
            "profile": "novel",
            "revision": 1,
            "format_version": 1,
            "bundle_sha256": first["bundle_sha256"],
            "admission_status": "pending",
            "sync_requested": False,
        }])

        download = self.secure_client.get(
            "/internal/v1/profiles/novel/bundles/1", headers=self.headers("worker-a")
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, self.bundle)
        self.assertEqual(download.headers["cache-control"], "no-store")
        self.assertEqual(download.headers["x-profile-revision"], "1")

        unassigned = self.secure_client.get(
            "/internal/v1/profiles/novel/bundles/1", headers=self.headers("worker-c")
        )
        self.assertEqual(unassigned.status_code, 404)
        cross_worker = self.secure_client.get(
            "/internal/v1/profile-manifest",
            headers=self.headers("worker-b", token="worker-token-a"),
        )
        self.assertEqual(cross_worker.status_code, 409)

        self.store.update_distribution("novel", "worker-a", "ready", provisioning_id=self.provisioning_id)
        self.store.update_distribution("novel", "worker-b", "ready", provisioning_id=self.provisioning_id)
        self.store.mark_active(self.provisioning_id)
        second_id = self.store.begin(
            profile="novel", actor_user_id=9, bootstrap_worker="worker-a",
            source="upload", target_workers=["worker-a", "worker-b"],
        )
        replacement = build_profile_bundle({"data/default": b"new-session"}, 10001)
        self.store.store_bundle(second_id, 10001, replacement)
        second = self.store.desired_revision("novel")
        self.assertEqual(second["revision"], 2)
        self.assertEqual(
            self.store.bundle_for_worker("novel", 1, "worker-a"), None,
            "workers may fetch only the assigned desired revision",
        )
        with self.store._db() as db:
            rows = db.execute(
                "SELECT revision,bundle_sha256 FROM profile_session_revisions WHERE profile='novel' ORDER BY revision"
            ).fetchall()
        self.assertEqual([row["revision"] for row in rows], [1, 2])
        self.assertEqual(rows[0]["bundle_sha256"], first["bundle_sha256"])

    def test_stale_ack_does_not_mark_desired_revision_ready(self):
        old = self.store.desired_revision("novel")
        self.store.update_distribution("novel", "worker-a", "ready", provisioning_id=self.provisioning_id)
        self.store.update_distribution("novel", "worker-b", "ready", provisioning_id=self.provisioning_id)
        self.store.mark_active(self.provisioning_id)
        second_id = self.store.begin(
            profile="novel", actor_user_id=9, bootstrap_worker="worker-a",
            source="adoption", target_workers=["worker-a", "worker-b"],
        )
        replacement = build_profile_bundle({"data/default": b"replacement"}, 10001)
        self.store.store_bundle(second_id, 10001, replacement)

        stale = self.secure_client.post(
            "/internal/v1/profiles/novel/ack",
            headers=self.headers("worker-a"),
            json={
                "revision": old["revision"],
                "bundle_sha256": old["bundle_sha256"],
                "telegram_user_id": old["telegram_user_id"],
            },
        )
        self.assertEqual(stale.status_code, 200)
        self.assertFalse(stale.json()["accepted"])
        self.assertEqual(stale.json()["reason"], "stale_revision")
        self.assertFalse(self.store.distribution_ready("novel", "worker-a"))

        desired = self.store.desired_revision("novel")
        applied = self.secure_client.post(
            "/internal/v1/profiles/novel/ack",
            headers=self.headers("worker-a"),
            json={
                "revision": desired["revision"],
                "bundle_sha256": desired["bundle_sha256"],
                "telegram_user_id": desired["telegram_user_id"],
            },
        )
        self.assertTrue(applied.json()["accepted"])
        self.assertTrue(self.store.distribution_ready("novel", "worker-a"))
        manifest = self.store.profile_manifest("worker-a")[0]
        self.assertEqual(manifest["admission_status"], "pending")
        self.assertEqual(manifest["revision"], 2)

    def test_initial_profile_activates_only_after_entire_snapshot_acknowledges(self):
        desired = self.store.desired_revision("novel")
        for worker in ("worker-a", "worker-b"):
            response = self.secure_client.post(
                "/internal/v1/profiles/novel/ack",
                headers=self.headers(worker),
                json={
                    "revision": desired["revision"],
                    "bundle_sha256": desired["bundle_sha256"],
                    "telegram_user_id": desired["telegram_user_id"],
                },
            )
            self.assertTrue(response.json()["accepted"])
            info = self.store.provisioning(self.provisioning_id)
            if worker == "worker-a":
                self.assertEqual(info["status"], "distributing")
                self.assertIsNone(self.profile_registry.profile_for_user(10001))

        self.assertEqual(self.store.provisioning(self.provisioning_id)["status"], "active")
        self.assertEqual(self.profile_registry.profile_for_user(10001), "novel")

    def test_bad_ack_and_http_transfer_are_rejected_safely(self):
        revision = self.store.desired_revision("novel")
        mismatch = self.secure_client.post(
            "/internal/v1/profiles/novel/ack",
            headers=self.headers("worker-a"),
            json={
                "revision": revision["revision"],
                "bundle_sha256": "0" * 64,
                "telegram_user_id": revision["telegram_user_id"],
            },
        )
        self.assertEqual(mismatch.status_code, 200)
        self.assertFalse(mismatch.json()["accepted"])
        self.assertEqual(mismatch.json()["reason"], "metadata_mismatch")
        self.assertFalse(self.store.distribution_ready("novel", "worker-a"))

        plaintext = TestClient(self.app, base_url="http://gateway.example")
        try:
            response = plaintext.get(
                "/internal/v1/profile-manifest", headers=self.headers("worker-a")
            )
        finally:
            plaintext.close()
        self.assertEqual(response.status_code, 426)

    def test_manual_sync_operation_sets_manifest_request_without_exposing_bundle(self):
        actor = Actor(telegram_user_id=9, profile="novel")
        prepared = prepare_profile_sync_operation(
            self.context,
            actor,
            {"profile": "novel", "worker": "worker-b"},
            {},
        )
        self.assertIsNone(prepared.job)
        self.assertNotIn("bundle", prepared.target)
        self.assertEqual(prepared.private_payload["actor_user_id"], 9)
        command = {
            "operation_id": "sync-op-1",
            "private_payload": prepared.private_payload,
        }
        self.assertEqual(advance_profile_sync_command(command, self.context)["status"], "accepted")
        manifest = self.store.profile_manifest("worker-b")
        self.assertTrue(manifest[0]["sync_requested"])

        self.assertEqual(advance_profile_sync_cancel(command, self.context)["status"], "terminal")
        self.assertFalse(self.store.profile_manifest("worker-b")[0]["sync_requested"])

    def test_legacy_identity_is_only_a_candidate_and_cannot_rewrite_vault_identity(self):
        self.assertFalse(self.store.record_legacy_discovery("novel", 20002))
        self.assertEqual(self.store.legacy_candidates("novel"), [])

        registry = ProfileRegistry(Path(self.temp.name) / "profiles.json", "default")
        registry.register_vaulted("novel", 10001)
        self.assertFalse(registry.register_discovered("novel", 20002))
        self.assertEqual(registry.profile_for_user(10001), "novel")
        self.assertIsNone(registry.profile_for_user(20002))

        self.assertTrue(self.store.record_legacy_discovery("old-profile", 30003))
        self.assertEqual(self.store.legacy_candidates("old-profile")[0]["source_worker"], "legacy-unattributed")

    def test_old_vault_rows_migrate_to_immutable_revision_one(self):
        root = Path(self.temp.name)
        legacy_bundle = build_profile_bundle({"data/default": b"legacy"}, 11001)
        operation_id = self.store.begin(
            profile="legacy-profile", actor_user_id=9, bootstrap_worker="worker-a",
            source="adoption", target_workers=["worker-a"],
        )
        self.store.store_bundle(operation_id, 11001, legacy_bundle)
        self.store.update_distribution(
            "legacy-profile", "worker-a", "ready", provisioning_id=operation_id
        )

        with sqlite3.connect(self.store.database) as db:
            db.execute("DROP INDEX IF EXISTS idx_profile_sessions_user_id")
            db.execute("DROP TABLE profile_session_revisions")
            db.execute("ALTER TABLE profile_sessions RENAME TO profile_sessions_versioned")
            db.execute(
                "CREATE TABLE profile_sessions (profile TEXT PRIMARY KEY,telegram_user_id INTEGER NOT NULL,encrypted_bundle BLOB NOT NULL,active INTEGER NOT NULL DEFAULT 0,source TEXT NOT NULL,updated_at TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO profile_sessions(profile,telegram_user_id,encrypted_bundle,active,source,updated_at) "
                "SELECT profile,telegram_user_id,encrypted_bundle,active,source,updated_at FROM profile_sessions_versioned"
            )
            db.execute("DROP TABLE profile_sessions_versioned")
            db.execute("ALTER TABLE profile_distributions RENAME TO profile_distributions_versioned")
            db.execute(
                "CREATE TABLE profile_distributions (profile TEXT NOT NULL,worker TEXT NOT NULL,status TEXT NOT NULL,provisioning_id TEXT,error TEXT,updated_at TEXT NOT NULL,PRIMARY KEY(profile,worker))"
            )
            db.execute(
                "INSERT INTO profile_distributions(profile,worker,status,provisioning_id,error,updated_at) "
                "SELECT profile,worker,status,provisioning_id,error,updated_at FROM profile_distributions_versioned"
            )
            db.execute("DROP TABLE profile_distributions_versioned")

        migrated = ProfileProvisioningStore(self.store.database, root / "vault")
        revision = migrated.desired_revision("legacy-profile")
        self.assertEqual(revision["revision"], 1)
        self.assertEqual(revision["bundle_sha256"], hashlib.sha256(legacy_bundle).hexdigest())
        self.assertTrue(migrated.distribution_ready("legacy-profile", "worker-a"))


if __name__ == "__main__":
    unittest.main()
