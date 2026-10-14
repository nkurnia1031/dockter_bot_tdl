import json
import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tme3bot.worker.upload_lane import UploadLanePreparer


class _ProfileManager:
    def __init__(self, profile_root: Path) -> None:
        self.profile_root = profile_root
        self.export_lock = threading.RLock()
        self.download_lock = threading.RLock()
        self.upload_lock = threading.RLock()

    def session_config(self, _profile: str):
        return type("Config", (), {
            "profile_root": self.profile_root,
            "tdl_export_storage": self.profile_root / "user1" / ".tdl",
            "tdl_export_namespace": "export-ns",
            "tdl_export_home": self.profile_root / "user1",
        })()

    def profile_operation_locks(self, _profile: str):
        return self.export_lock, self.download_lock

    def profile_upload_operation_lock(self, _profile: str):
        return self.upload_lock


class UploadLanePreparerTests(unittest.TestCase):
    def _profile(self, root: Path) -> tuple[Path, Path, Path]:
        profile_root = root / "profile"
        (profile_root / "user1" / ".tdl" / "data").mkdir(parents=True)
        (profile_root / "root" / ".tdl" / "data").mkdir(parents=True)
        (profile_root / "identity.json").write_text(
            json.dumps({"telegram_user_id": 424242}), encoding="utf-8"
        )
        export_db = profile_root / "user1" / ".tdl" / "data" / "export-ns"
        download_db = profile_root / "root" / ".tdl" / "data" / "download-ns"
        export_db.write_bytes(b"export bolt session")
        download_db.write_bytes(b"download bolt session")
        return profile_root, export_db, download_db

    def _preparer(self, root: Path, profile_root: Path, checker=None):
        manager = _ProfileManager(profile_root)
        checked = []

        def validate(storage_root: Path, namespace: str, _home: Path) -> int:
            db = Path(storage_root) / "data" / namespace
            checked.append((Path(storage_root), db.read_bytes()))
            if checker is not None:
                return checker(Path(storage_root), db.read_bytes())
            return 424242

        preparer = UploadLanePreparer(
            profile_manager=manager,
            session_checker=validate,
            state_path=root / "state" / "upload-lanes.json",
        )
        return preparer, manager, checked

    def _wait_terminal(self, preparer: UploadLanePreparer, timeout: float = 3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = preparer.status("irang")
            if state["status"] in {"ready", "failed"}:
                return state
            time.sleep(0.01)
        self.fail("Upload lane preparation did not finish")

    def test_scan_prepares_a_distinct_upload_copy_without_changing_download_or_export(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile_root, export_db, download_db = self._profile(root)
            source_export = export_db.read_bytes()
            source_download = download_db.read_bytes()
            preparer, _manager, checked = self._preparer(root, profile_root)

            started = preparer.ensure("irang")
            self.assertIn(started["status"], {"running", "ready"})
            result = self._wait_terminal(preparer)

            upload_db = profile_root / "upload" / ".tdl" / "data" / "export-ns"
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["phase"], "ready")
            self.assertEqual(result["progress"], 100)
            self.assertTrue(upload_db.is_file())
            self.assertEqual(upload_db.read_bytes(), source_export)
            self.assertNotEqual(upload_db.stat().st_ino, export_db.stat().st_ino)
            self.assertEqual(export_db.read_bytes(), source_export)
            self.assertEqual(download_db.read_bytes(), source_download)
            self.assertEqual([payload for _path, payload in checked], [source_export, source_export])
            if os.name == "posix":
                upload_root = profile_root / "upload"
                self.assertEqual(stat.S_IMODE(upload_root.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(upload_db.stat().st_mode), 0o600)

    def test_ready_lane_is_revalidated_and_not_recopied_when_export_is_unchanged(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile_root, export_db, _download_db = self._profile(root)
            preparer, _manager, _checked = self._preparer(root, profile_root)
            preparer.ensure("irang")
            self.assertEqual(self._wait_terminal(preparer)["status"], "ready")
            upload_db = profile_root / "upload" / ".tdl" / "data" / "export-ns"
            installed_inode = upload_db.stat().st_ino

            preparer.ensure("irang")
            result = self._wait_terminal(preparer)

            self.assertEqual(result["status"], "ready")
            self.assertEqual(upload_db.stat().st_ino, installed_inode)
            self.assertEqual(upload_db.read_bytes(), export_db.read_bytes())

    def test_session_fingerprint_is_stable_for_uploads_and_changes_when_lane_is_replaced(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile_root, export_db, _download_db = self._profile(root)
            preparer, _manager, _checked = self._preparer(root, profile_root)
            preparer.ensure("irang")
            self.assertEqual(self._wait_terminal(preparer)["status"], "ready")

            first = preparer.session_fingerprint("irang")
            upload_db = profile_root / "upload" / ".tdl" / "data" / "export-ns"
            upload_db.write_bytes(b"updated by normal Upload lane use")
            self.assertEqual(preparer.session_fingerprint("irang"), first)

            export_db.write_bytes(b"new Export session generation")
            preparer.ensure("irang")
            self.assertEqual(self._wait_terminal(preparer)["status"], "ready")
            self.assertNotEqual(preparer.session_fingerprint("irang"), first)

    def test_identity_mismatch_keeps_existing_upload_and_both_source_lanes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile_root, export_db, download_db = self._profile(root)
            preparer, _manager, _checked = self._preparer(root, profile_root)
            preparer.ensure("irang")
            self.assertEqual(self._wait_terminal(preparer)["status"], "ready")
            upload_db = profile_root / "upload" / ".tdl" / "data" / "export-ns"
            old_upload = upload_db.read_bytes()
            upload_home = profile_root / "upload"
            old_modes = None
            if os.name == "posix":
                upload_home.chmod(0o755)
                upload_db.chmod(0o644)
                old_modes = (
                    stat.S_IMODE(upload_home.stat().st_mode),
                    stat.S_IMODE(upload_db.stat().st_mode),
                )
            export_db.write_bytes(b"new export session")

            # Source is valid; only the newly copied candidate reports a different account.
            calls = 0

            def candidate_mismatch(storage: Path, namespace: str, _home: Path) -> int:
                nonlocal calls
                calls += 1
                del storage, namespace
                return 424242 if calls % 2 == 1 else 987654

            preparer.session_checker = candidate_mismatch
            preparer.ensure("irang")
            result = self._wait_terminal(preparer)

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["code"], "PROFILE_UPLOAD_IDENTITY_MISMATCH")
            self.assertEqual(upload_db.read_bytes(), old_upload)
            if old_modes is not None:
                self.assertEqual(
                    (
                        stat.S_IMODE(upload_home.stat().st_mode),
                        stat.S_IMODE(upload_db.stat().st_mode),
                    ),
                    old_modes,
                )
            self.assertEqual(export_db.read_bytes(), b"new export session")
            self.assertEqual(download_db.read_bytes(), b"download bolt session")
            self.assertFalse(any(profile_root.glob(".upload-candidate-*")))

    def test_active_tdl_work_is_waited_out_before_copying_source_database(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile_root, _export_db, _download_db = self._profile(root)
            preparer, manager, _checked = self._preparer(root, profile_root)
            manager.export_lock.acquire()
            try:
                preparer.ensure("irang")
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    state = preparer.status("irang")
                    if state["phase"] == "waiting_idle":
                        break
                    time.sleep(0.01)
                self.assertEqual(preparer.status("irang")["phase"], "waiting_idle")
                self.assertFalse((profile_root / "upload").exists())
            finally:
                manager.export_lock.release()

            self.assertEqual(self._wait_terminal(preparer)["status"], "ready")

    def test_duplicate_triggers_share_one_preparation(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile_root, _export_db, _download_db = self._profile(root)
            entered = threading.Event()
            release = threading.Event()
            calls = 0

            def slow_check(storage: Path, _namespace: str, _home: Path) -> int:
                nonlocal calls
                calls += 1
                entered.set()
                release.wait(2)
                return 424242

            manager = _ProfileManager(profile_root)
            preparer = UploadLanePreparer(
                profile_manager=manager,
                session_checker=slow_check,
                state_path=root / "state" / "upload-lanes.json",
            )
            preparer.ensure("irang")
            self.assertTrue(entered.wait(1))
            duplicate = preparer.ensure("irang")
            self.assertEqual(duplicate["status"], "running")
            release.set()

            result = self._wait_terminal(preparer)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(calls, 2)  # Export session and candidate Upload session.

    def test_interrupted_progress_is_persisted_as_retryable_on_worker_restart(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile_root, _export_db, _download_db = self._profile(root)
            _first, manager, _checked = self._preparer(root, profile_root)
            state_path = root / "state" / "upload-lanes.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({
                "version": 1,
                "profiles": {
                    "irang": {
                        "status": "running",
                        "phase": "copying",
                        "progress": 35,
                        "code": "OK",
                    }
                },
            }), encoding="utf-8")

            restarted = UploadLanePreparer(
                profile_manager=manager,
                session_checker=lambda *_args: 424242,
                state_path=state_path,
            )

            snapshot = restarted.status("irang")
            self.assertEqual(snapshot["status"], "pending")
            self.assertEqual(snapshot["phase"], "queued")
            self.assertEqual(snapshot["code"], "PROFILE_UPLOAD_PREPARATION_INTERRUPTED")
            self.assertNotIn("source_fingerprint", json.dumps(snapshot))


if __name__ == "__main__":
    unittest.main()
