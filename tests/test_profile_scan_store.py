import tempfile
import unittest
from pathlib import Path

from tme3bot.infrastructure.profile_scan_store import ProfileScanOperationStore


class ProfileScanOperationStoreTests(unittest.TestCase):
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
