import hashlib
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from tme3bot.infrastructure.tdl_access_store import SqliteTdlAccessStore
from tme3bot.tdl import TDLCommandError, tdl_write_denial_code
from tme3bot.worker.executor_tdl_access import TdlAccessExecutorMixin


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


class TdlWriteDenialTests(unittest.TestCase):
    def test_only_explicit_permission_errors_allow_sender_fallback(self):
        denied = TDLCommandError(["tdl", "up"], 1, "", "CHAT_WRITE_FORBIDDEN")
        timeout = TimeoutError("request timed out")
        self.assertEqual(tdl_write_denial_code(denied), "CHAT_WRITE_FORBIDDEN")
        self.assertIsNone(tdl_write_denial_code(timeout))


class _FakeTdlClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.uploads = []

    def upload(self, marker, target, caption):
        self.uploads.append((Path(marker).name, target, caption))
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
        self.profile_manager = SimpleNamespace(
            runtime=lambda name: SimpleNamespace(
                export_tdl_client=self.clients[name],
                export_operation_lock=threading.RLock(),
            )
        )

    def available_storage_profiles(self):
        return ["default", "archive"]

    def _job_cancelled(self, _job_id):
        return self._cancel


class TdlAccessWorkerTests(unittest.TestCase):
    def test_marker_permissions_are_private_and_owned_by_the_tdl_user(self):
        from tme3bot.worker.executor_tdl_access import _prepare_tdl_access_marker

        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "marker.txt"
            marker.write_text("test", encoding="utf-8")
            account = SimpleNamespace(pw_uid=1234, pw_gid=5678)
            pwd_module = SimpleNamespace(getpwnam=lambda name: account)

            with (
                patch("tme3bot.worker.executor_tdl_access.os.name", "posix"),
                patch("tme3bot.worker.executor_tdl_access.os.geteuid", return_value=0, create=True),
                patch("tme3bot.worker.executor_tdl_access.os.chown", create=True) as chown,
                patch.object(Path, "chmod") as chmod,
                patch.dict(sys.modules, {"pwd": pwd_module}),
            ):
                _prepare_tdl_access_marker(marker, "user1")

            self.assertEqual(
                chmod.call_args_list,
                [call(0o700), call(0o600)],
            )
            self.assertEqual(
                chown.call_args_list,
                [call(marker.parent, 1234, 5678), call(marker, 1234, 5678)],
            )

    def test_verification_prepares_each_marker_for_the_configured_tdl_user(self):
        executor = _VerifyExecutor()
        for client in executor.clients.values():
            client.run_as_user = "user1"

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
        self.assertEqual(prepare.call_count, 2)
        self.assertTrue(all(call.args[1] == "user1" for call in prepare.call_args_list))

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
            {"Worker tidak dapat menyiapkan file uji untuk user TDL."},
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
        self.assertEqual(result["profiles"][1]["error_code"], "CHAT_WRITE_FORBIDDEN")
        self.assertNotIn("-100123", json.dumps(result))
        self.assertEqual(len(executor.clients["default"].uploads), 1)
        self.assertEqual(len(executor.clients["archive"].uploads), 1)
        self.assertIn("-100123", executor._job_log.secrets)

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
