import hashlib
import io
import json
import urllib.error
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path
from types import SimpleNamespace

from tme3bot.worker.profile_sync import (
    ProfileSyncClient,
    ProfileSyncError,
    _ProfileSyncCancelled,
)


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
        self.sync_events = []
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
        if path == "/internal/v1/profile-sync/events":
            self.sync_events.append(json.loads(data.decode("utf-8")))
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
            diagnose_installed_tdl=lambda _profile: {"ready": True, "reason_codes": []},
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
        self.assertEqual(
            [event["phase"] for event in transport.sync_events],
            [
                "manifest_fetch", "revision_compare", "bundle_download", "bundle_download",
                "bundle_validation", "session_install", "session_validation",
                "session_commit", "session_commit", "acknowledgement", "completed",
            ],
        )
        self.assertEqual(transport.sync_events[-1]["status"], "succeeded")
        self.assertTrue(all("bundle" not in event for event in transport.sync_events))

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
        self.assertTrue(any(
            event["phase"] == "revision_compare" and event.get("code") == "REVISION_CURRENT"
            for event in transport.sync_events[11:]
        ))
        self.assertFalse(any(event["phase"] == "bundle_download" for event in transport.sync_events[11:]))

        client.sync_now(mode="repair", profile="irang")
        self.assertEqual(len(self.installs), 2)
        self.assertEqual(len(transport.bundle_requests), 2)

    def test_same_revision_is_not_acked_ready_when_readonly_tdl_check_fails(self):
        content = bundle_for()
        entry = manifest_row("irang", 7, content)
        client, transport = self.make_client([entry], {("irang", 7): content})
        client.sync_now()
        transport.acks.clear()
        client.diagnose_installed_tdl = lambda _profile: {
            "ready": False,
            "reason_codes": ["PROFILE_ROOT_SESSION_TDL_INVALID"],
        }

        result = client.sync_now(mode="check")

        self.assertEqual(result["status"], "sync_pending")
        self.assertEqual(result["failed"], 1)
        self.assertEqual(transport.acks, [])
        self.assertEqual(
            client.snapshot()["profiles"]["irang"]["error_code"],
            "PROFILE_ROOT_SESSION_TDL_INVALID",
        )

    def test_sync_fails_closed_when_readonly_tdl_check_is_unavailable(self):
        content = bundle_for()
        entry = manifest_row("irang", 7, content)
        client, transport = self.make_client([entry], {("irang", 7): content})
        client.diagnose_installed_tdl = None

        result = client.sync_now()

        self.assertEqual(result["status"], "sync_pending")
        self.assertEqual(result["failed"], 1)
        self.assertEqual(transport.acks, [])
        self.assertEqual(self.sessions.installed.get("irang"), None)
        self.assertEqual(
            client.snapshot()["profiles"]["irang"]["error_code"],
            "PROFILE_TDL_DIAGNOSTIC_UNAVAILABLE",
        )

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

    def test_manifest_failure_before_first_profile_is_loaded_keeps_global_error_code(self):
        client, transport = self.make_client([], {})
        transport.fail = ProfileSyncError("PROFILE_TRANSFER_REQUIRES_HTTPS")

        result = client.sync_now()

        self.assertEqual(result["status"], "waiting_worker")
        snapshot = client.snapshot()
        self.assertEqual(snapshot["status"], "waiting_worker")
        self.assertEqual(
            snapshot["backend_error_code"], "PROFILE_TRANSFER_REQUIRES_HTTPS"
        )

    def test_backend_http_status_426_is_preserved_as_safe_sync_error(self):
        client, _ = self.make_client([], {})
        client._request_override = None

        class RejectingOpener:
            def open(self, *_args, **_kwargs):
                raise urllib.error.HTTPError(
                    "https://backend.example/internal/v1/profile-manifest",
                    426,
                    "Upgrade Required",
                    {},
                    None,
                )

        with patch("tme3bot.worker.profile_sync.build_opener", return_value=RejectingOpener()):
            with self.assertRaises(ProfileSyncError) as raised:
                client._request("GET", "/internal/v1/profile-manifest", None)
        self.assertEqual(raised.exception.code, "PROFILE_TRANSFER_REQUIRES_HTTPS")

    def test_backend_http_status_409_is_preserved_for_identity_diagnosis(self):
        client, _ = self.make_client([], {})
        client._request_override = None

        class RejectingOpener:
            def open(self, *_args, **_kwargs):
                raise urllib.error.HTTPError(
                    "https://backend.example/internal/v1/profile-manifest",
                    409,
                    "Conflict",
                    {},
                    None,
                )

        with patch("tme3bot.worker.profile_sync.build_opener", return_value=RejectingOpener()):
            with self.assertRaises(ProfileSyncError) as raised:
                client._request("GET", "/internal/v1/profile-manifest", None)
        self.assertEqual(raised.exception.code, "PROFILE_BACKEND_HTTP_409")

    def test_backend_safe_error_code_is_preserved_without_exposing_message(self):
        client, _ = self.make_client([], {})
        client._request_override = None
        body = json.dumps({
            "error": {
                "code": "WORKER_IDENTITY_AMBIGUOUS",
                "message": "Sensitive backend detail must not be retained.",
            }
        }).encode()

        class RejectingOpener:
            def open(self, *_args, **_kwargs):
                raise urllib.error.HTTPError(
                    "https://backend.example/internal/v1/profile-manifest",
                    409,
                    "Conflict",
                    {},
                    io.BytesIO(body),
                )

        with patch("tme3bot.worker.profile_sync.build_opener", return_value=RejectingOpener()):
            with self.assertRaises(ProfileSyncError) as raised:
                client._request("GET", "/internal/v1/profile-manifest", None)
        self.assertEqual(raised.exception.code, "WORKER_IDENTITY_AMBIGUOUS")
        self.assertNotIn("Sensitive", str(raised.exception))

    def test_backend_worker_unauthorized_code_is_not_misreported_as_internal_token_error(self):
        client, _ = self.make_client([], {})
        client._request_override = None
        body = json.dumps({"error": {"code": "WORKER_UNAUTHORIZED", "message": "redacted"}}).encode()

        class RejectingOpener:
            def open(self, *_args, **_kwargs):
                raise urllib.error.HTTPError(
                    "https://backend.example/internal/v1/profile-manifest",
                    401,
                    "Unauthorized",
                    {},
                    io.BytesIO(body),
                )

        with patch("tme3bot.worker.profile_sync.build_opener", return_value=RejectingOpener()):
            with self.assertRaises(ProfileSyncError) as raised:
                client._request("GET", "/internal/v1/profile-manifest", None)
        self.assertEqual(raised.exception.code, "WORKER_UNAUTHORIZED")

    def test_profile_sync_uses_worker_token_after_runtime_rotation(self):
        runtime_token = ["old-shared-token"]
        config = SimpleNamespace(
            state_file=self.config.state_file,
            backend_api_url="https://backend.example",
            backend_internal_token="internal-token",
            backup_node_name="worker-a",
            # This is the startup ENV value and does not change during Web rotation.
            worker_api_token="old-shared-token",
        )
        client = ProfileSyncClient(
            config,
            SimpleNamespace(local_profile_identities=lambda: []),
            self.sessions,
            install_bundle=lambda *_args: None,
            commit_bundle=lambda *_args: True,
            rollback_bundle=lambda *_args: True,
            worker_token_provider=lambda: runtime_token[0],
        )
        request_tokens = []

        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b'{"profiles": []}'

        class SwitchingOpener:
            def open(self, request, **_kwargs):
                headers = {key.lower(): value for key, value in request.header_items()}
                token = headers.get("x-worker-token", "")
                request_tokens.append(token)
                if token != "rotated-unique-token":
                    body = json.dumps({"error": {"code": "WORKER_IDENTITY_AMBIGUOUS"}}).encode()
                    raise urllib.error.HTTPError(
                        "https://backend.example/internal/v1/profile-manifest",
                        409,
                        "Conflict",
                        {},
                        io.BytesIO(body),
                    )
                return Response()

        with patch("tme3bot.worker.profile_sync.build_opener", return_value=SwitchingOpener()):
            first = client._sync(mode="check", profile=None)
            self.assertEqual(first["status"], "waiting_worker")
            self.assertEqual(client._state["backend_error_code"], "WORKER_IDENTITY_AMBIGUOUS")

            runtime_token[0] = "rotated-unique-token"
            second = client._sync(mode="check", profile=None)

        self.assertEqual(second["status"], "ready")
        self.assertTrue(client._state["backend_available"])
        self.assertEqual(client._state["backend_error_code"], "")
        self.assertEqual(request_tokens, ["old-shared-token", "rotated-unique-token"])

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

    def test_profile_sync_event_outbox_replays_same_event_after_restart(self):
        first_client, first_transport = self.make_client([], {})

        def unavailable(_method, _path, _data, **_kwargs):
            raise OSError("offline")

        first_client._request = unavailable
        first_client._report_sync_event(
            run_id="worker-run-123",
            sequence=1,
            profile="irang",
            revision=7,
            phase="bundle_download",
            status="running",
            details={"bundle_bytes": 512, "password": 123},
        )
        persisted = json.loads(first_client.path.read_text(encoding="utf-8"))
        self.assertEqual(len(persisted["pending_sync_events"]), 1)
        self.assertNotIn("password", json.dumps(persisted["pending_sync_events"]))

        restarted, replay_transport = self.make_client([], {})
        restarted._flush_sync_event_outbox()
        restarted._flush_sync_event_outbox()

        self.assertEqual(len(first_transport.sync_events), 0)
        self.assertEqual(len(replay_transport.sync_events), 1)
        self.assertEqual(replay_transport.sync_events[0]["run_id"], "worker-run-123")
        self.assertEqual(replay_transport.sync_events[0]["sequence"], 1)
        self.assertEqual(replay_transport.sync_events[0]["details"], {"bundle_bytes": 512})
        self.assertEqual(restarted._state["pending_sync_events"], [])

    def test_three_lane_progress_phases_are_durable_and_allowlisted(self):
        client, transport = self.make_client([], {})
        phases = (
            "download_staging", "download_validation", "download_install",
            "export_staging", "export_validation", "export_install",
            "upload_staging", "upload_validation", "upload_install",
            "identity_install", "transaction_rollback", "installation_reused",
        )

        for sequence, phase in enumerate(phases, start=1):
            client._report_sync_event(
                run_id="worker-run-three-lanes",
                sequence=sequence,
                profile="irang",
                revision=7,
                phase=phase,
                status="running",
            )

        self.assertEqual([event["phase"] for event in transport.sync_events], list(phases))
        self.assertTrue(all(event["sequence"] == index for index, event in enumerate(transport.sync_events, 1)))

    def test_external_install_and_commit_event_sequences_resume_after_restart(self):
        client, _ = self.make_client([], {})
        run_id = "vault-install-run-123"
        self.assertEqual(client.next_external_event_sequence(run_id), 1)
        self.assertEqual(client.next_external_event_sequence(run_id), 2)

        restarted, _ = self.make_client([], {})

        self.assertEqual(restarted.next_external_event_sequence(run_id), 3)
        self.assertEqual(restarted.next_external_event_sequence("another-run-123"), 1)

    def test_cancel_queued_profile_sync_skips_the_request(self):
        client, transport = self.make_client([], {})
        key = ("irang", "check")
        client._queued.add(key)
        client._requests.put(key)

        result = client.cancel_sync(profile="irang")
        client._run_one_request()

        self.assertEqual(result["status"], "cancelled")
        self.assertFalse(client._queued)
        self.assertIsNone(client._active_request)
        self.assertEqual(transport.bundle_requests, [])
        self.assertEqual(client._requests.unfinished_tasks, 0)

    def test_cancel_profile_sync_stops_a_scheduled_retry(self):
        client, _ = self.make_client([], {})
        key = ("irang", "repair")
        timer = threading.Timer(60, lambda: None)
        client._retry_timers[key] = timer

        result = client.cancel_sync(profile="irang", mode="repair")

        self.assertEqual(result["status"], "cancelled")
        self.assertNotIn(key, client._retry_timers)
        self.assertNotIn(key, client._retry_attempts)

    def test_cancel_active_profile_sync_stops_before_bundle_install(self):
        content = bundle_for()
        entry = manifest_row("irang", 7, content)
        client, transport = self.make_client([entry], {("irang", 7): content})
        client._active_request = ("irang", "check")

        result = client.cancel_sync(profile="irang")
        checks = 0

        def cancelled(_profile):
            nonlocal checks
            checks += 1
            return checks > 1

        with self.assertRaises(_ProfileSyncCancelled):
            client._sync_entry(entry, mode="check", cancelled=cancelled)

        self.assertEqual(result["status"], "cancelling")
        self.assertEqual(transport.bundle_requests, [("irang", 7)])
        self.assertEqual(self.installs, [])
        self.assertEqual(transport.acks, [])

    def test_cancelling_one_profile_does_not_stop_other_startup_syncs(self):
        alpha = bundle_for(111)
        beta = bundle_for(222)
        entries = [manifest_row("alpha", 1, alpha), manifest_row("beta", 1, beta)]
        client, transport = self.make_client(
            entries, {("alpha", 1): alpha, ("beta", 1): beta}
        )

        result = client._sync(
            mode="check", profile=None, cancelled=lambda profile: profile == "alpha"
        )

        self.assertEqual(result["status"], "sync_pending")
        self.assertEqual(result["cancelled"], 1)
        self.assertEqual([item[0] for item in self.installs], ["beta"])
        self.assertEqual(len(transport.acks), 1)
        self.assertEqual(client.snapshot()["profiles"]["alpha"]["error_code"], "SYNC_CANCELLED")
        self.assertEqual(client.snapshot()["profiles"]["beta"]["status"], "ready")

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
