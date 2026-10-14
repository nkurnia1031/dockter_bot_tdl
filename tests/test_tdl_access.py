import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from tme3bot.infrastructure.tdl_access_store import SqliteTdlAccessStore
from tme3bot.tdl import TDLCommandError, tdl_write_denial_code
from tme3bot.worker.executor_tdl_access import (
    TdlAccessExecutorMixin,
    _tdl_access_error_code,
)


class TdlAccessStoreTests(unittest.TestCase):
    def test_verified_sender_rotation_is_scoped_to_destination_and_inventory(self):
        with tempfile.TemporaryDirectory() as root:
            store = SqliteTdlAccessStore(Path(root) / "access.db")
            destination = store.destination_fingerprint("@target")
            inventory = store.inventory_fingerprint(["default", "archive"])
            store.replace_results(
                "local",
                "tts",
                destination,
                inventory,
                [
                    {"profile": "default", "ready": True},
                    {"profile": "archive", "ready": True},
                ],
            )

            self.assertEqual(store.choose_next("local", "tts", destination, inventory), "archive")
            self.assertEqual(store.choose_next("local", "tts", destination, inventory), "default")
            self.assertEqual(
                store.verified_profiles(
                    "local", "tts", store.destination_fingerprint("@different"), inventory
                ),
                [],
            )
            changed_inventory = store.inventory_fingerprint(["default"])
            self.assertEqual(store.verified_profiles("local", "tts", destination, changed_inventory), [])

    def test_replacing_results_keeps_failed_profiles_visible_but_not_eligible(self):
        with tempfile.TemporaryDirectory() as root:
            store = SqliteTdlAccessStore(Path(root) / "access.db")
            destination = store.destination_fingerprint("-100123")
            inventory = store.inventory_fingerprint(["default", "archive"])
            rows = store.replace_results(
                "remote-1",
                "storage",
                destination,
                inventory,
                [
                    {"profile": "default", "ready": True},
                    {"profile": "archive", "ready": False, "error_code": "CHAT_WRITE_FORBIDDEN"},
                ],
            )
            self.assertEqual([row["profile"] for row in rows], ["archive", "default"])
            self.assertEqual(store.verified_profiles("remote-1", "storage", destination, inventory), ["default"])

    def test_upload_session_change_invalidates_only_that_profiles_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            store = SqliteTdlAccessStore(Path(root) / "access.db")
            destination = store.destination_fingerprint("-100123")
            original = {"default": "a" * 64, "archive": "b" * 64}
            inventory = store.inventory_fingerprint(list(original), original)
            store.replace_results(
                "remote-1",
                "storage",
                destination,
                inventory,
                [
                    {"profile": "default", "ready": True},
                    {"profile": "archive", "ready": True},
                ],
                session_fingerprints=original,
            )

            rotated = {"default": "c" * 64, "archive": original["archive"]}
            current_inventory = store.inventory_fingerprint(list(rotated), rotated)
            self.assertEqual(
                store.verified_profiles(
                    "remote-1",
                    "storage",
                    destination,
                    current_inventory,
                    session_fingerprints=rotated,
                ),
                ["archive"],
            )

    def test_explicit_denial_invalidates_only_the_matching_upload_lane_proof(self):
        with tempfile.TemporaryDirectory() as root:
            store = SqliteTdlAccessStore(Path(root) / "access.db")
            destination = store.destination_fingerprint("-100123")
            fingerprints = {"default": "a" * 64, "archive": "b" * 64}
            inventory = store.inventory_fingerprint(list(fingerprints), fingerprints)
            store.replace_results(
                "remote-1",
                "storage",
                destination,
                inventory,
                [
                    {"profile": "default", "ready": True},
                    {"profile": "archive", "ready": True},
                ],
                session_fingerprints=fingerprints,
            )

            self.assertTrue(
                store.invalidate_profile(
                    "remote-1", destination, "default", fingerprints["default"], "CHAT_WRITE_FORBIDDEN"
                )
            )
            self.assertEqual(
                store.verified_profiles(
                    "remote-1",
                    "storage",
                    destination,
                    inventory,
                    session_fingerprints=fingerprints,
                ),
                ["archive"],
            )

    def test_existing_access_database_gains_fingerprint_column_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "access.db"
            destination = SqliteTdlAccessStore.destination_fingerprint("-100123")
            inventory = SqliteTdlAccessStore.inventory_fingerprint(["default"])
            db = sqlite3.connect(path)
            try:
                db.execute(
                    "CREATE TABLE tdl_access_profiles ("
                    "worker TEXT NOT NULL, purpose TEXT NOT NULL, destination_hash TEXT NOT NULL, "
                    "inventory_hash TEXT NOT NULL, profile TEXT NOT NULL, ready INTEGER NOT NULL, "
                    "error_code TEXT, checked_at TEXT NOT NULL, "
                    "PRIMARY KEY(worker,purpose,destination_hash,inventory_hash,profile))"
                )
                db.execute(
                    "INSERT INTO tdl_access_profiles VALUES(?,?,?,?,?,?,?,?)",
                    ("local", "storage", destination, inventory, "default", 1, None, "now"),
                )
                db.commit()
            finally:
                db.close()

            store = SqliteTdlAccessStore(path)
            self.assertEqual(
                store.verified_profiles("local", "storage", destination, inventory),
                ["default"],
            )


class TdlWriteDenialTests(unittest.TestCase):
    def test_only_explicit_permission_errors_allow_sender_fallback(self):
        denied = TDLCommandError(["tdl", "up"], 1, "", "CHAT_WRITE_FORBIDDEN")
        timeout = TimeoutError("request timed out")
        self.assertEqual(tdl_write_denial_code(denied), "CHAT_WRITE_FORBIDDEN")
        self.assertIsNone(tdl_write_denial_code(timeout))

    def test_only_explicit_session_errors_are_classified_as_lane_denials(self):
        self.assertEqual(
            _tdl_access_error_code(RuntimeError("AUTH_KEY_UNREGISTERED")),
            "TDL_SESSION_UNAUTHORIZED",
        )
        self.assertEqual(
            _tdl_access_error_code(TimeoutError("request timed out")),
            "VERIFICATION_FAILED",
        )

    def test_tdl_authentication_failure_is_reported_as_session_not_authorized(self):
        error = TDLCommandError(
            ["tdl", "up"], 1, "", "- not authorized. please login first"
        )
        self.assertEqual(_tdl_access_error_code(error), "TDL_SESSION_UNAUTHORIZED")

    def test_unclassified_errors_remain_generic_and_do_not_trigger_fallback(self):
        error = TDLCommandError(["tdl", "up"], 1, "", "connection reset")
        self.assertIsNone(tdl_write_denial_code(error))
        self.assertEqual(_tdl_access_error_code(error), "VERIFICATION_FAILED")


class _FakeTdlClient:
    def __init__(self, fail=False, error=None):
        self.fail = fail
        self.error = error
        self.uploads = []

    def upload(self, marker, target, caption):
        self.uploads.append((Path(marker).name, target, caption))
        if self.error is not None:
            raise self.error
        if self.fail:
            raise TDLCommandError(["tdl", "up"], 1, "", "CHAT_WRITE_FORBIDDEN")


class _VerifyExecutor(TdlAccessExecutorMixin):
    def __init__(self):
        self.config = SimpleNamespace(
            backend_api_url="https://backend.example",
            backend_internal_token="internal",
            backup_node_name="local",
        )
        self.publisher = SimpleNamespace(emit=lambda *args, **kwargs: None)
        self._job_log = SimpleNamespace(secrets=[])
        self._cancel = False
        self.clients = {
            "default": _FakeTdlClient(fail=True),
            "archive": _FakeTdlClient(fail=False),
        }
        self.export_clients = {
            "default": _FakeTdlClient(fail=False),
            "archive": _FakeTdlClient(fail=False),
        }
        self.session_fingerprints = {"default": "a" * 64, "archive": "b" * 64}
        self.profile_manager = SimpleNamespace(
            list_profiles=lambda: ["default", "archive"],
            runtime=lambda name: SimpleNamespace(
                upload_tdl_client=self.clients[name],
                export_operation_lock=threading.RLock(),
                upload_operation_lock=threading.RLock(),
                export_tdl_client=self.export_clients[name],
            )
        )

    def available_storage_profiles(self):
        return ["default", "archive"]

    def available_export_profiles(self):
        return ["default", "archive"]

    def available_storage_session_fingerprints(self, profiles=None):
        selected = profiles if profiles is not None else self.available_storage_profiles()
        return {
            profile: self.session_fingerprints[profile]
            for profile in selected
            if profile in self.session_fingerprints
        }

    def list_profiles(self):
        return ["default", "archive"]

    def _job_cancelled(self, _job_id):
        return self._cancel


class TdlAccessWorkerTests(unittest.TestCase):
    def test_worker_publishes_only_opaque_upload_fingerprints(self):
        from tme3bot.worker.executor import WorkerJobExecutor

        executor = WorkerJobExecutor.__new__(WorkerJobExecutor)
        executor.upload_lane_preparer = SimpleNamespace(
            session_fingerprint=lambda profile: {
                "default": "a" * 64,
                "archive": "/data/profiles/archive/upload/.tdl",
            }[profile]
        )

        self.assertEqual(
            executor.available_storage_session_fingerprints(["default", "archive"]),
            {"default": "a" * 64},
        )

    def test_storage_verification_aborts_when_upload_session_changes_before_send(self):
        executor = _VerifyExecutor()
        executor.clients["default"] = _FakeTdlClient()
        calls = 0

        def fingerprints(profiles=None):
            nonlocal calls
            calls += 1
            values = {"default": "a" * 64, "archive": "b" * 64}
            if calls > 1:
                values["default"] = "c" * 64
            selected = profiles if profiles is not None else values
            return {profile: values[profile] for profile in selected if profile in values}

        executor.available_storage_session_fingerprints = fingerprints
        with patch(
            "tme3bot.worker.executor_tdl_access.request_json",
            return_value={"purpose": "storage", "target": "-100123"},
        ):
            result = executor._tdl_access_verify(
                {"job_id": "job-rotated", "worker": "local", "payload": {"purpose": "storage"}}
            )

        outcomes = {item["profile"]: item for item in result["profiles"]}
        self.assertEqual(outcomes["default"]["error_code"], "PROFILE_UPLOAD_SESSION_CHANGED")
        self.assertFalse(outcomes["default"]["ready"])
        self.assertFalse(executor.clients["default"].uploads)
        self.assertTrue(outcomes["archive"]["ready"])

    def test_tdl_authentication_error_is_visible_as_a_session_failure(self):
        executor = _VerifyExecutor()
        executor.clients["default"] = _FakeTdlClient(
            error=TDLCommandError(
                ["tdl", "up"], 1, "", "- not authorized. please login first"
            )
        )

        with patch(
            "tme3bot.worker.executor_tdl_access.request_json",
            return_value={"purpose": "storage", "target": "-100123"},
        ):
            result = executor._tdl_access_verify(
                {"job_id": "job-1", "worker": "local", "payload": {"purpose": "storage"}}
            )

        failed = next(item for item in result["profiles"] if item["profile"] == "default")
        self.assertEqual(failed["error_code"], "TDL_SESSION_UNAUTHORIZED")
        self.assertIn("scan profil", failed["error_message"])

    def test_marker_permissions_are_private_for_the_root_tdl_process(self):
        from tme3bot.worker.executor_tdl_access import _prepare_tdl_access_marker

        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "marker.txt"
            marker.write_text("test", encoding="utf-8")
            with (
                patch.object(Path, "chmod") as chmod,
            ):
                _prepare_tdl_access_marker(marker)

            self.assertEqual(
                chmod.call_args_list,
                [call(0o700), call(0o600)],
            )
    def test_verification_prepares_each_marker_without_uid_switching(self):
        executor = _VerifyExecutor()

        with (
            patch(
                "tme3bot.worker.executor_tdl_access.request_json",
                return_value={"purpose": "storage", "target": "-100123"},
            ),
            patch("tme3bot.worker.executor_tdl_access._prepare_tdl_access_marker") as prepare,
        ):
            result = executor._tdl_access_verify(
                {"job_id": "job-1", "worker": "local", "payload": {"purpose": "storage"}}
            )

        self.assertEqual(result["summary"]["ready"], 1)
        self.assertEqual(result["session_fingerprints"], executor.session_fingerprints)
        self.assertNotIn("/data/", json.dumps(result))
        self.assertEqual(prepare.call_count, 2)
        self.assertTrue(all(len(call.args) == 1 for call in prepare.call_args_list))

    def test_marker_permission_failure_is_reported_per_profile(self):
        from tme3bot.worker.executor_tdl_access import TdlAccessMarkerPermissionError

        executor = _VerifyExecutor()
        with (
            patch(
                "tme3bot.worker.executor_tdl_access.request_json",
                return_value={"purpose": "storage", "target": "-100123"},
            ),
            patch(
                "tme3bot.worker.executor_tdl_access._prepare_tdl_access_marker",
                side_effect=TdlAccessMarkerPermissionError(),
            ),
        ):
            result = executor._tdl_access_verify(
                {"job_id": "job-1", "worker": "local", "payload": {"purpose": "storage"}}
            )

        self.assertEqual(result["summary"]["ready"], 0)
        self.assertEqual(
            {item["error_code"] for item in result["profiles"]},
            {"TDL_ACCESS_MARKER_PERMISSION_FAILED"},
        )
        self.assertEqual(
            {item["error_message"] for item in result["profiles"]},
            {"Worker tidak dapat menyiapkan file uji TDL."},
        )

    def test_verification_reports_unavailable_profiles_and_redacted_command_contract(self):
        executor = _VerifyExecutor()
        executor.profile_manager = SimpleNamespace(
            list_profiles=lambda: ["default", "archive"],
            tdl_session_diagnostic=lambda profile, purpose: {
                "profile": profile,
                "available": profile == "archive",
                "error_code": None if profile == "archive" else "TDL_SESSION_DATABASE_MISSING",
            },
            runtime=lambda name: SimpleNamespace(
                upload_tdl_client=executor.clients[name],
                upload_operation_lock=threading.RLock(),
                export_tdl_client=executor.clients[name],
                export_operation_lock=threading.RLock(),
            ),
        )
        executor.available_storage_profiles = lambda: ["archive"]

        with patch(
            "tme3bot.worker.executor_tdl_access.request_json",
            return_value={"purpose": "storage", "target": "-100-secret"},
        ):
            result = executor._tdl_access_verify(
                {"job_id": "job-1", "worker": "local", "payload": {"purpose": "storage"}}
            )

        profiles = {item["profile"]: item for item in result["profiles"]}
        self.assertEqual(set(profiles), {"default", "archive"})
        self.assertEqual(profiles["default"]["error_code"], "TDL_SESSION_DATABASE_MISSING")
        self.assertFalse(profiles["default"]["command_attempted"])
        self.assertTrue(profiles["archive"]["command_attempted"])
        self.assertIn("tdl", result["command_template"])
        self.assertIn("--storage", result["command_template"])
        self.assertIn("up -p", result["command_template"])
        self.assertNotIn("-100-secret", json.dumps(result))
        self.assertNotIn("/data/", json.dumps(result))

    def test_verification_checks_each_local_profile_and_returns_only_safe_metadata(self):
        executor = _VerifyExecutor()
        with patch(
            "tme3bot.worker.executor_tdl_access.request_json",
            return_value={"purpose": "storage", "target": "-100123"},
        ):
            result = executor._tdl_access_verify(
                {"job_id": "job-1", "worker": "local", "payload": {"purpose": "storage"}}
            )
        self.assertTrue(result["profiles"][0]["ready"])
        self.assertEqual(result["session"], "upload")
        self.assertEqual(result["profiles"][1]["error_code"], "CHAT_WRITE_FORBIDDEN")
        self.assertNotIn("-100123", json.dumps(result))
        self.assertEqual(len(executor.clients["default"].uploads), 1)
        self.assertEqual(len(executor.clients["archive"].uploads), 1)
        self.assertFalse(any(client.uploads for client in executor.export_clients.values()))
        self.assertIn("-100123", executor._job_log.secrets)

    def test_storage_verification_fails_closed_when_upload_lane_is_not_ready(self):
        executor = _VerifyExecutor()
        executor.available_storage_profiles = lambda: []

        with patch(
            "tme3bot.worker.executor_tdl_access.request_json",
            return_value={"purpose": "storage", "target": "-100123"},
        ):
            result = executor._tdl_access_verify(
                {"job_id": "job-1", "worker": "local", "payload": {"purpose": "storage"}}
            )

        self.assertEqual(result["session"], "upload")
        self.assertEqual(result["summary"]["tested"], 0)
        self.assertTrue(all(item["command_attempted"] is False for item in result["profiles"]))
        self.assertFalse(any(client.uploads for client in executor.clients.values()))
        self.assertFalse(any(client.uploads for client in executor.export_clients.values()))

    def test_tts_verification_keeps_using_export_lane(self):
        executor = _VerifyExecutor()
        with patch(
            "tme3bot.worker.executor_tdl_access.request_json",
            return_value={"purpose": "tts", "target": "@target"},
        ):
            result = executor._tdl_access_verify(
                {"job_id": "job-tts", "worker": "local", "payload": {"purpose": "tts"}}
            )

        self.assertEqual(result["session"], "export")
        self.assertTrue(all(client.uploads for client in executor.export_clients.values()))
        self.assertFalse(any(client.uploads for client in executor.clients.values()))

    def test_cancel_stops_before_testing_next_profile(self):
        executor = _VerifyExecutor()
        executor._cancel = True
        with patch(
            "tme3bot.worker.executor_tdl_access.request_json",
            return_value={"purpose": "storage", "target": "-100123"},
        ), self.assertRaisesRegex(RuntimeError, "dibatalkan"):
            executor._tdl_access_verify(
                {"job_id": "job-1", "worker": "local", "payload": {"purpose": "storage"}}
            )
        self.assertFalse(any(client.uploads for client in executor.clients.values()))


if __name__ == "__main__":
    unittest.main()
