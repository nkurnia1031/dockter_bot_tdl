import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tme3bot.profile_distribution import ProfileDistributionService
from tme3bot.profile_distribution_crypto import (
    decrypt_distribution_bundle,
    encrypt_distribution_bundle,
)
from tme3bot.profile_distribution_store import ProfileDistributionStore


class FakeVault:
    def __init__(self, bundle: bytes, user_id: int = 1234):
        self.bundle = bundle
        self.user_id = user_id
        self.digest = hashlib.sha256(bundle).hexdigest()

    def bundle_for_revision(self, profile: str, revision: int):
        if profile != "archive" or revision != 7:
            return None
        return {
            "bundle": self.bundle,
            "telegram_user_id": self.user_id,
            "bundle_sha256": self.digest,
        }


class FakeRegistry:
    def __init__(self, names):
        self.workers = {name: {"token": f"worker-token-{name}-long-enough"} for name in names}

    def get(self, name):
        return self.workers.get(name)


class FakeBot:
    def __init__(self):
        self.uploads = []

    def send_document(self, **kwargs):
        self.uploads.append(kwargs)
        return SimpleNamespace(message_id=900 + len(self.uploads))


class FakeDispatcher:
    def __init__(self, failed=(), offline=()):
        self.failed = set(failed)
        self.offline = set(offline)
        self.calls = []

    def distribute_profile_bundle(self, worker, operation_id, payload):
        self.calls.append((worker, operation_id, dict(payload)))
        if worker in self.offline:
            error = RuntimeError("worker unavailable")
            error.kind = "network"
            raise error
        if worker in self.failed:
            raise ValueError("PROFILE_INSTALL_FAILED")
        return {"ready": True}


class ProfileDistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProfileDistributionStore(self.root / "state.sqlite3")
        self.bundle = b"synthetic profile session archive"
        self.vault = FakeVault(self.bundle)
        self.workers = ["remote-1", "remote-2"]

    def tearDown(self):
        self.temp.cleanup()

    def create_operation(self, workers=None, key="submit-once"):
        return self.store.create(
            actor_user_id=456,
            idempotency_key=key,
            profile="archive",
            revision=7,
            bundle_sha256=self.vault.digest,
            telegram_user_id=self.vault.user_id,
            target_workers=list(workers or self.workers),
        )

    def service(self, dispatcher, bot=None):
        return ProfileDistributionService(
            SimpleNamespace(backup_channel_id=-100123),
            bot or FakeBot(),
            self.store,
            self.vault,
            FakeRegistry(self.workers),
            dispatcher,
        )

    def test_distribution_ciphertext_is_worker_bound_and_idempotent(self):
        args = {
            "worker_token": "worker-token-remote-1-long-enough",
            "operation_id": "a36b11cb-2135-4fce-89c2-772b0eb25792",
            "profile": "archive",
            "revision": 7,
            "worker": "remote-1",
        }
        encrypted = encrypt_distribution_bundle(self.bundle, **args)
        self.assertEqual(encrypted, encrypt_distribution_bundle(self.bundle, **args))
        self.assertNotIn(self.bundle, encrypted)
        self.assertEqual(decrypt_distribution_bundle(encrypted, **args), self.bundle)
        with self.assertRaisesRegex(ValueError, "PROFILE_DISTRIBUTION_ARCHIVE_INVALID"):
            decrypt_distribution_bundle(encrypted, **{**args, "worker_token": "wrong-token-long-enough"})
        with self.assertRaisesRegex(ValueError, "PROFILE_DISTRIBUTION_ARCHIVE_INVALID"):
            decrypt_distribution_bundle(encrypted[:-1] + bytes([encrypted[-1] ^ 1]), **args)

    def test_operation_pins_snapshot_and_queued_events_before_dispatch(self):
        first, created = self.create_operation()
        duplicate, duplicate_created = self.create_operation()
        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(first["target_workers"], self.workers)
        self.assertEqual(first["revision"], 7)
        self.assertEqual([item["status"] for item in first["workers"]], ["queued", "queued"])
        self.assertEqual(len(self.store.events(first["id"])["items"]), 2)
        reopened = ProfileDistributionStore(self.root / "state.sqlite3")
        self.assertEqual(reopened.operation(first["id"])["target_workers"], self.workers)
        after_registry_or_revision_change, created_again = reopened.create(
            actor_user_id=456,
            idempotency_key="submit-once",
            profile="archive",
            revision=8,
            bundle_sha256="f" * 64,
            telegram_user_id=9999,
            target_workers=["remote-3"],
        )
        self.assertFalse(created_again)
        self.assertEqual(after_registry_or_revision_change["id"], first["id"])
        self.assertEqual(after_registry_or_revision_change["revision"], 7)
        with self.assertRaisesRegex(ValueError, "IDEMPOTENCY_KEY_REUSED"):
            reopened.create(
                actor_user_id=456,
                idempotency_key="submit-once",
                profile="other",
                revision=1,
                bundle_sha256=self.vault.digest,
                telegram_user_id=self.vault.user_id,
                target_workers=self.workers,
            )

    def test_encrypted_artifact_and_metadata_only_worker_request(self):
        operation, _ = self.create_operation(workers=["remote-1"])
        bot = FakeBot()
        dispatcher = FakeDispatcher()
        service = self.service(dispatcher, bot)
        self.assertEqual(service.process_pending(), 1)
        current = self.store.operation(operation["id"])
        self.assertEqual(current["status"], "succeeded")
        self.assertEqual(current["workers"][0]["status"], "ready")
        self.assertEqual(len(bot.uploads), 1)
        artifact = bot.uploads[0]["document"].getvalue()
        self.assertNotIn(self.bundle, artifact)
        self.assertIn("#profile_distribution", bot.uploads[0]["caption"])
        worker, operation_id, payload = dispatcher.calls[0]
        self.assertEqual(worker, "remote-1")
        self.assertEqual(operation_id, operation["id"])
        self.assertNotIn("bundle", payload)
        self.assertNotIn("token", json.dumps(payload).lower())
        self.assertEqual(
            decrypt_distribution_bundle(
                artifact,
                worker_token="worker-token-remote-1-long-enough",
                operation_id=operation["id"],
                profile="archive",
                revision=7,
                worker="remote-1",
            ),
            self.bundle,
        )

    def test_offline_worker_waits_on_same_operation_and_retry_skips_ready_worker(self):
        operation, _ = self.create_operation()
        dispatcher = FakeDispatcher(failed={"remote-2"})
        service = self.service(dispatcher)
        service.process_pending()
        current = self.store.operation(operation["id"])
        self.assertEqual(current["workers"][0]["status"], "ready")
        self.assertEqual(current["workers"][1]["status"], "failed")
        self.assertEqual(current["status"], "failed")
        self.assertTrue(self.store.retry_worker(operation["id"], "remote-2", "retry-remote-2"))
        self.assertTrue(self.store.retry_worker(operation["id"], "remote-2", "retry-remote-2"))
        dispatcher.failed.clear()
        service.process_pending()
        current = self.store.operation(operation["id"])
        self.assertEqual(current["id"], operation["id"])
        self.assertEqual([item["status"] for item in current["workers"]], ["ready", "ready"])
        self.assertEqual([call[0] for call in dispatcher.calls], ["remote-1", "remote-2", "remote-2"])

    def test_temporarily_offline_worker_resumes_same_operation_without_reupload(self):
        operation, _ = self.create_operation(workers=["remote-1"])
        bot = FakeBot()
        dispatcher = FakeDispatcher(offline={"remote-1"})
        service = self.service(dispatcher, bot)

        service.process_pending()
        waiting = self.store.operation(operation["id"])
        self.assertEqual(waiting["id"], operation["id"])
        self.assertEqual(waiting["status"], "waiting")
        self.assertEqual(waiting["workers"][0]["status"], "waiting")
        self.assertEqual(waiting["workers"][0]["reason_code"], "WORKER_UNAVAILABLE")
        self.assertEqual(len(bot.uploads), 1)

        dispatcher.offline.clear()
        service.process_pending()
        resumed = self.store.operation(operation["id"])
        self.assertEqual(resumed["id"], operation["id"])
        self.assertEqual(resumed["status"], "succeeded")
        self.assertEqual(resumed["workers"][0]["status"], "ready")
        self.assertEqual(len(bot.uploads), 1)
        self.assertEqual([call[1] for call in dispatcher.calls], [operation["id"], operation["id"]])


if __name__ == "__main__":
    unittest.main()
