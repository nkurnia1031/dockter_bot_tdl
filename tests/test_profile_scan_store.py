import tempfile
import unittest
from pathlib import Path

from tme3bot.infrastructure.profile_scan_store import ProfileScanOperationStore


class ProfileScanOperationStoreTests(unittest.TestCase):
    def test_worker_scan_persists_raw_log_events_in_order_and_can_continue_from_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileScanOperationStore(Path(directory) / "storage.db")
            operation, created = store.create(
                42, target={"kind": "worker", "worker": "REMOTE-1"}
            )
            self.assertTrue(created)
            store.set_status(operation["id"], "running")
            store.report_worker(
                operation["id"], "remote-1", "running", phase="profile_probe",
                profiles=["default"],
            )

            command_sequence = store.append_log(
                operation["id"], worker="remote-1", profile="default",
                runtime="export_canary", kind="command", stream="system",
                text="$ tdl chat export -c 123\r\n",
            )
            output_sequence = store.append_log(
                operation["id"], worker="remote-1", profile="default",
                runtime="export_canary", kind="output", stream="stdout",
                text="\x1b[32mExporting\x1b[0m\rExported 1\r\n",
            )
            exit_sequence = store.append_log(
                operation["id"], worker="remote-1", profile="default",
                runtime="export_canary", kind="exit", stream="system",
                text="process exited with code 0", exit_code=0,
            )

            page = store.get_logs(
                operation["id"], worker="remote-1",
                after_sequence=command_sequence, limit=1,
            )
            self.assertEqual(page["events"][0]["sequence"], output_sequence)
            self.assertEqual(page["events"][0]["text"], "\x1b[32mExporting\x1b[0m\rExported 1\r\n")
            self.assertTrue(page["has_more"])
            final_page = store.get_logs(
                operation["id"], worker="remote-1",
                after_sequence=output_sequence, limit=10,
            )
            self.assertEqual(final_page["events"][0]["sequence"], exit_sequence)
            self.assertEqual(final_page["events"][0]["exit_code"], 0)
            self.assertFalse(final_page["has_more"])

    def test_scan_log_events_follow_scan_operation_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileScanOperationStore(Path(directory) / "storage.db")
            first, _ = store.create(42, target={"kind": "worker", "worker": "local"})
            first_sequence = store.append_log(
                first["id"], worker="local", profile="default",
                runtime="export_canary", kind="command", stream="system",
                text="$ tdl chat export",
            )
            store.set_status(first["id"], "succeeded")

            for _ in range(32):
                operation, created = store.create(42)
                self.assertTrue(created)
                store.set_status(operation["id"], "succeeded")

            self.assertIsNone(
                store.get_logs(first["id"], worker="local", after_sequence=0)
            )
            self.assertGreater(first_sequence, 0)

    def test_targeted_profile_operation_persists_scope_and_progress(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "storage.db"
            store = ProfileScanOperationStore(path)
            operation, created = store.create(
                42,
                target={
                    "kind": "profile_runtime",
                    "worker": "REMOTE-1",
                    "profile": "IRANG",
                    "runtime": "storage",
                },
            )
            self.assertTrue(created)
            self.assertEqual(operation["target"], {
                "kind": "profile_runtime", "worker": "remote-1",
                "profile": "irang", "runtime": "storage",
            })
            store.report_worker(
                operation["id"], "remote-1", "running", phase="profile_probe",
                profiles=["irang"],
            )
            store.report_profile(
                operation["id"], "remote-1", "irang", "running",
                phase="verify_storage",
                checks={"upload": {"ready": True}, "storage": {"ready": False, "reason_code": "PROFILE_CANARY_STORAGE_VERIFY_FAILED"}},
                dependencies=["export", "upload", "private/path"],
            )

            restored = ProfileScanOperationStore(path)
            saved = restored.get(operation["id"])
            progress = saved["progress"]["workers"][0]["profiles"][0]
            self.assertEqual(saved["target"], operation["target"])
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(progress["phase"], "interrupted")
            self.assertEqual(progress["error_code"], "PROFILE_SCAN_INTERRUPTED")
            self.assertEqual(progress["checks"]["upload"]["ready"], True)
            self.assertEqual(progress["checks"]["storage"]["reason_code"], "PROFILE_CANARY_STORAGE_VERIFY_FAILED")
            self.assertEqual(progress["dependencies"], ["export", "upload"])

    def test_targeted_runtime_operation_persists_safe_target_and_check_progress(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "storage.db"
            store = ProfileScanOperationStore(path)
            operation, created = store.create(
                42,
                target={
                    "kind": "worker_runtime",
                    "worker": "LOCAL",
                    "runtime": "resolver",
                },
            )
            self.assertTrue(created)
            self.assertEqual(operation["target"], {
                "kind": "worker_runtime", "worker": "local", "runtime": "resolver",
            })
            store.report_worker(
                operation["id"],
                "local",
                "succeeded",
                phase="complete",
                runtime="resolver",
                checks={"resolver": {"ready": True, "reason_code": ""}},
            )

            restored = ProfileScanOperationStore(path)
            saved = restored.get(operation["id"])
            self.assertEqual(saved["target"], operation["target"])
            self.assertEqual(saved["progress"]["workers"][0]["runtime"], "resolver")
            self.assertEqual(saved["progress"]["workers"][0]["checks"]["resolver"]["ready"], True)

    def test_completed_operation_progress_survives_store_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "storage.db"
            store = ProfileScanOperationStore(path)
            operation, created = store.create(42)
            self.assertTrue(created)
            store.set_status(operation["id"], "running")
            store.report_worker(
                operation["id"],
                "remote-1",
                "running",
                phase="runtime_probe",
                profiles=["irang"],
            )
            store.report_profile(
                operation["id"], "remote-1", "irang", "succeeded", phase="complete",
                checks={
                    "export": {"ready": True, "reason_code": ""},
                    "storage": {"ready": False, "reason_code": "PROFILE_CANARY_STORAGE_VERIFY_FAILED"},
                    "fingerprint": "must-not-persist",
                },
                cleanup={
                    "status": "failed",
                    "items": [{
                        "target": "storage", "message_id": 123, "status": "failed",
                        "error_code": "CANARY_CLEANUP_FAILED", "detail": "must-not-persist",
                    }],
                },
            )
            store.report_worker(
                operation["id"], "remote-1", "succeeded", phase="complete"
            )
            store.set_status(operation["id"], "succeeded")

            reopened = ProfileScanOperationStore(path)
            saved = reopened.get(operation["id"])

            self.assertEqual(saved["status"], "succeeded")
            self.assertEqual(saved["progress"]["completed_workers"], 1)
            self.assertEqual(saved["progress"]["completed_profiles"], 1)
            self.assertEqual(
                saved["progress"]["workers"][0]["profiles"][0]["name"], "irang"
            )
            profile = saved["progress"]["workers"][0]["profiles"][0]
            self.assertEqual(profile["checks"]["export"]["ready"], True)
            self.assertEqual(
                profile["checks"]["storage"]["reason_code"],
                "PROFILE_CANARY_STORAGE_VERIFY_FAILED",
            )
            self.assertEqual(profile["cleanup"]["status"], "failed")
            self.assertEqual(profile["cleanup"]["items"][0]["message_id"], 123)
            self.assertNotIn("fingerprint", str(saved["progress"]))
            self.assertNotIn("detail", str(saved["progress"]))

    def test_backend_restart_marks_active_scan_and_progress_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "storage.db"
            store = ProfileScanOperationStore(path)
            operation, _ = store.create(42)
            store.set_status(operation["id"], "running")
            store.report_worker(
                operation["id"],
                "remote-1",
                "running",
                phase="runtime_probe",
                profiles=["irang"],
            )
            store.report_profile(
                operation["id"], "remote-1", "irang", "running", phase="runtime_probe"
            )

            restarted = ProfileScanOperationStore(path)
            saved = restarted.get(operation["id"])

            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["error_code"], "PROFILE_SCAN_INTERRUPTED")
            worker = saved["progress"]["workers"][0]
            self.assertEqual(worker["phase"], "interrupted")
            self.assertEqual(worker["profiles"][0]["status"], "failed")
            self.assertEqual(worker["profiles"][0]["error_code"], "PROFILE_SCAN_INTERRUPTED")

    def test_retains_only_recent_completed_scan_history(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileScanOperationStore(Path(directory) / "storage.db")
            operation_ids = []
            for actor_id in range(33):
                operation, _ = store.create(actor_id)
                operation_ids.append(operation["id"])
                store.set_status(operation["id"], "running")
                store.set_status(operation["id"], "succeeded")

            self.assertIsNone(store.get(operation_ids[0]))
            self.assertIsNotNone(store.get(operation_ids[1]))
            self.assertEqual(store.latest()["id"], operation_ids[-1])


if __name__ == "__main__":
    unittest.main()
