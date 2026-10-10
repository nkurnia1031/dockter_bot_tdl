import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
