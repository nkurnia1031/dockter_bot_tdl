import hashlib
import io
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from tme3bot.worker.profile_sync import ProfileSyncClient, ProfileSyncError


def bundle_for(user_id=12345):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("identity.json", json.dumps({"telegram_user_id": user_id}))
        archive.writestr("root/.tdl/data/default", b"download-session")
        archive.writestr("user1/.tdl/data/default", b"export-session")
    return output.getvalue()


class FakeSessions:
    def __init__(self):
        self.installed = {}

    def verify_installed(self, profile, expected_user_id=None):
        user_id = self.installed.get(profile)
        if user_id is None or (expected_user_id is not None and user_id != expected_user_id):
            return False
        return user_id


class FakeTransport:
    def __init__(self, entries, bundles):
        self.entries = entries
        self.bundles = bundles
        self.bundle_requests = []
        self.acks = []
        self.legacy_profiles = []
        self.legacy_discovery_done = threading.Event()
        self.fail = None

    def __call__(self, method, path, data):
        if self.fail:
            raise self.fail
        if path == "/internal/v1/profile-manifest":
            return json.dumps({"profiles": self.entries}).encode(), {}
        if "/bundles/" in path:
            profile = path.split("/profiles/", 1)[1].split("/bundles/", 1)[0]
            revision = int(path.rsplit("/", 1)[1])
            self.bundle_requests.append((profile, revision))
            content = self.bundles[(profile, revision)]
            digest = hashlib.sha256(content).hexdigest()
            return content, {
                "ETag": f'"{digest}"',
                "X-Profile-Revision": str(revision),
                "X-Profile-Format-Version": "1",
            }
        if path.endswith("/ack"):
            payload = json.loads(data.decode())
            self.acks.append((path, payload))
            return json.dumps({"accepted": True}).encode(), {}
        if path == "/internal/v1/profiles/sync":
            payload = json.loads(data.decode())
            self.legacy_profiles.extend(payload.get("profiles", []))
            self.legacy_discovery_done.set()
            return json.dumps({"synced": []}).encode(), {}
        raise AssertionError((method, path))


def manifest_row(profile, revision, data, *, format_version=1):
    return {
        "profile": profile,
        "revision": revision,
        "format_version": format_version,
        "bundle_sha256": hashlib.sha256(data).hexdigest(),
        "admission_status": "pending",
        "sync_requested": True,
    }


class WorkerProfileSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.config = SimpleNamespace(
            state_file=root / "state.json",
            backend_api_url="https://backend.example",
            backend_internal_token="internal-token",
            backup_node_name="worker-a",
            worker_api_token="worker-token",
        )
        self.sessions = FakeSessions()
        self.installs = []
        self.rollbacks = []

    def tearDown(self):
        self.temporary.cleanup()

    def make_client(self, entries, bundles, *, install_error=None):
        transport = FakeTransport(entries, bundles)

        def install(profile, user_id, data, operation_id):
            self.installs.append((profile, user_id, operation_id))
            if install_error:
                self.sessions.installed[profile] = user_id
                raise install_error
            self.sessions.installed[profile] = user_id

        def rollback(profile, operation_id):
            self.rollbacks.append((profile, operation_id))
            self.sessions.installed.pop(profile, None)
            return True

        client = ProfileSyncClient(
            self.config,
            SimpleNamespace(
                local_profile_identities=lambda: [
                    {"name": "default", "telegram_user_id": 100},
                    {"name": "irang", "telegram_user_id": 12345},
                    {"name": "legacy", "telegram_user_id": 777},
                ]
            ),
            self.sessions,
            install_bundle=install,
            commit_bundle=lambda _profile, _operation: True,
            rollback_bundle=rollback,
            request=transport,
        )
        return client, transport

    def test_pull_verifies_installs_and_acks_only_after_install(self):
        content = bundle_for()
        entry = manifest_row("irang", 3, content)
        client, transport = self.make_client([entry], {("irang", 3): content})

        result = client.sync_now()

        self.assertEqual(result, {"status": "ready", "synced": 1, "failed": 0})
        self.assertEqual(
            self.installs,
            [("irang", 12345, f"sync-{hashlib.sha256(b'irang').hexdigest()[:16]}-3")],
        )
        self.assertEqual(len(transport.acks), 1)
        self.assertTrue(transport.legacy_discovery_done.wait(2))
        self.assertEqual(
            [item["name"] for item in transport.legacy_profiles],
            ["default", "legacy"],
        )
        self.assertEqual(client.snapshot()["profiles"]["irang"]["status"], "ready")
        self.assertTrue(client.profile_ready("irang", expected_revision=3))
        self.assertFalse(client.profile_ready("irang", expected_revision=2))
        with self.assertRaises(ProfileSyncError):
            client.wait_until_ready("irang", expected_revision=2)

    def test_same_revision_check_does_not_reinstall_but_repair_does(self):
        content = bundle_for()
        entry = manifest_row("irang", 4, content)
        client, transport = self.make_client([entry], {("irang", 4): content})
        client.sync_now()
        self.assertEqual(len(self.installs), 1)

        client.sync_now(mode="check")
        self.assertEqual(len(self.installs), 1)
        self.assertEqual(len(transport.bundle_requests), 1)
        self.assertTrue(client.profile_ready("irang"))

        client.sync_now(mode="repair", profile="irang")
        self.assertEqual(len(self.installs), 2)
        self.assertEqual(len(transport.bundle_requests), 2)

    def test_previous_ready_snapshot_is_gated_until_this_startup_checks_backend(self):
        content = bundle_for()
        entry = manifest_row("irang", 4, content)
        first, _ = self.make_client([entry], {("irang", 4): content})
        first.sync_now()
        second, _ = self.make_client([entry], {("irang", 4): content})

        self.assertEqual(second.snapshot()["status"], "sync_pending")
        self.assertFalse(second.profile_ready("irang"))

    def test_hash_or_format_mismatch_never_installs(self):
        content = bundle_for()
        wrong_hash = "0" * 64
        bad_hash_entry = {**manifest_row("irang", 1, content), "bundle_sha256": wrong_hash}
        client, _ = self.make_client([bad_hash_entry], {("irang", 1): content})
        result = client.sync_now()
        self.assertEqual(result["status"], "sync_pending")
        self.assertEqual(self.installs, [])
        self.assertEqual(
            client.snapshot()["profiles"]["irang"]["error_code"],
            "PROFILE_BUNDLE_HASH_MISMATCH",
        )

        unsupported = manifest_row("irang", 2, content, format_version=2)
        client2, transport2 = self.make_client([unsupported], {("irang", 2): content})
        client2.sync_now()
        self.assertEqual(transport2.bundle_requests, [])
        self.assertEqual(self.installs, [])

    def test_failed_install_rolls_back_and_keeps_admission_pending(self):
        content = bundle_for()
        entry = manifest_row("irang", 5, content)
        client, _ = self.make_client(
            [entry], {("irang", 5): content}, install_error=RuntimeError("private path")
        )

        result = client.sync_now()

        self.assertEqual(result["failed"], 1)
        self.assertEqual(
            self.rollbacks,
            [("irang", f"sync-{hashlib.sha256(b'irang').hexdigest()[:16]}-5")],
        )
        self.assertEqual(client.snapshot()["profiles"]["irang"]["status"], "sync_pending")
        self.assertFalse(client.profile_ready("irang"))

    def test_backend_outage_marks_profiles_waiting_and_holds_admission(self):
        content = bundle_for()
        entry = manifest_row("irang", 6, content)
        client, transport = self.make_client([entry], {("irang", 6): content})
        client.sync_now()
        transport.fail = ProfileSyncError("BACKEND_UNAVAILABLE")

        result = client.sync_now()

        self.assertEqual(result["status"], "waiting_worker")
        self.assertEqual(client.snapshot()["status"], "waiting_worker")
        self.assertEqual(client.snapshot()["profiles"]["irang"]["status"], "waiting_worker")
        self.assertFalse(client.profile_ready("irang"))
        self.assertFalse(client.wait_until_ready("irang", cancelled=lambda: True))

    def test_wait_reports_unchanged_backend_reason_only_once(self):
        client, _ = self.make_client([], {})
        client._startup_checked = True
        client._state = {"backend_available": False, "profiles": {}, "managed_profiles": []}

        class ImmediateCondition:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def wait(self, timeout=None):
                del timeout

        client._condition = ImmediateCondition()
        reports = []
        checks = 0

        def cancel_after_checks():
            nonlocal checks
            checks += 1
            return checks >= 5

        self.assertFalse(
            client.wait_until_ready(
                "irang", cancelled=cancel_after_checks, on_wait=reports.append
            )
        )
        self.assertEqual(reports, ["waiting_worker"])

    def test_only_https_or_internal_backend_hosts_enable_pull(self):
        client, _ = self.make_client([], {})
        self.config.backend_api_url = "http://backend:8000"
        self.assertTrue(client.enabled)
        self.config.backend_api_url = "http://backend.example"
        self.assertFalse(client.enabled)
        self.config.backend_api_url = "https://backend.example"
        self.assertTrue(client.enabled)

    def test_syncing_one_profile_does_not_block_another_ready_profile(self):
        alpha = bundle_for(111)
        beta = bundle_for(222)
        alpha_entry = manifest_row("alpha", 1, alpha)
        beta_entry = manifest_row("beta", 8, beta)
        client, transport = self.make_client(
            [alpha_entry, beta_entry],
            {("alpha", 1): alpha, ("beta", 8): beta},
        )
        client.sync_now()
        self.assertTrue(client.profile_ready("beta"))

        changed_alpha = bundle_for(111)
        alpha_entry = manifest_row("alpha", 2, changed_alpha)
        transport.entries = [alpha_entry, beta_entry]
        transport.bundles[("alpha", 2)] = changed_alpha
        client.sync_now(profile="alpha")

        self.assertTrue(client.profile_ready("alpha"))
        self.assertTrue(client.profile_ready("beta"))
        self.assertEqual(client.snapshot()["profiles"]["beta"]["status"], "ready")

        self.assertEqual(client.sync_now(profile="unassigned")["status"], "not_assigned")
        self.assertFalse(client.profile_ready("unassigned"))

    def test_local_legacy_profile_is_admitted_only_when_sessions_are_valid(self):
        content = bundle_for(123)
        entry = manifest_row("irang", 1, content)
        client, _ = self.make_client([entry], {("irang", 1): content})
        client.sync_now()

        self.assertFalse(client.profile_ready("legacy"))
        self.sessions.installed["legacy"] = 777
        self.assertTrue(client.profile_ready("legacy"))
        self.assertTrue(client.wait_until_ready("legacy"))


if __name__ == "__main__":
    unittest.main()
