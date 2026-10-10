import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tme3bot.profile_backup_verifier import verify_profile_backup


class FakeArchive:
    def __init__(self, path, password, manifest, names=None, *, fail=None):
        self.path = Path(path)
        self.password = password
        self.manifest = manifest
        self.names = names or [
            "backup-manifest.json",
            "data/root/.tdl/data/default",
            "data/user1/.tdl/data/default",
        ]
        self.fail = fail

    def __enter__(self):
        if self.fail:
            raise self.fail()
        return self

    def __exit__(self, *_args):
        return False

    def getnames(self):
        return self.names

    def list(self):
        return [type("Entry", (), {"is_symlink": False, "is_hardlink": False})() for _ in self.names]

    def needs_password(self):
        return True

    def test(self):
        return True

    def extract(self, *, path, targets):
        assert targets == ["backup-manifest.json"]
        Path(path, "backup-manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")


class WrongPasswordError(Exception):
    pass


class ProfileBackupVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "storage.db"
        self.settings = self.root / "utility_settings.json"
        self.parts_dir = self.root / "parts"
        self.parts_dir.mkdir()
        self.run_id = "run-2026-10-11"
        self.worker = "remote-1"
        self.password = "private-backup-password"
        self.part_data = b"encrypted multipart archive fixture"
        self.part_name = "backup-remote.7z.001"
        (self.parts_dir / self.part_name).write_bytes(self.part_data)
        self.settings.write_text(json.dumps({"compress_password": self.password}), encoding="utf-8")
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE backup_runs (run_id TEXT, node_name TEXT, started_at TEXT, status TEXT);
            CREATE TABLE backup_parts (run_id TEXT, node_name TEXT, part_name TEXT, file_size INTEGER, sha256 TEXT, status TEXT);
            """
        )
        connection.execute(
            "INSERT INTO backup_runs VALUES (?, ?, ?, ?)",
            (self.run_id, self.worker, "2026-10-11T01:00:00+00:00", "complete"),
        )
        connection.execute(
            "INSERT INTO backup_parts VALUES (?, ?, ?, ?, ?, ?)",
            (
                self.run_id,
                self.worker,
                self.part_name,
                len(self.part_data),
                hashlib.sha256(self.part_data).hexdigest(),
                "active",
            ),
        )
        connection.commit()
        connection.close()
        self.manifest = {
            "run_id": self.run_id,
            "node_name": self.worker,
            "created_at": "2026-10-11T01:00:00+00:00",
            "included": [
                "data/root/.tdl/data/default",
                "data/user1/.tdl/data/default",
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def verify(self, *, manifest=None, names=None, fail=None):
        made_archives = []

        def factory(path, password):
            made_archives.append(Path(path).parent)
            return FakeArchive(path, password, manifest or self.manifest, names, fail=fail)

        report = verify_profile_backup(
            run_id=self.run_id,
            node_name=self.worker,
            profile="default",
            parts_dir=self.parts_dir,
            catalog_db=self.database,
            settings_file=self.settings,
            archive_factory=factory,
        )
        return report, made_archives

    def test_valid_multipart_archive_returns_redacted_evidence_and_cleans_temp(self):
        report, temporary_dirs = self.verify()
        self.assertEqual(report["status"], "verified")
        self.assertTrue(report["checksums_match"])
        self.assertEqual(report["integrity"], "verified")
        self.assertEqual(report["decryption"], "verified")
        self.assertTrue(all(item["included"] for item in report["sessions"]))
        self.assertNotIn(self.password, json.dumps(report))
        self.assertNotIn(str(self.parts_dir), json.dumps(report))
        self.assertNotIn(self.part_name, json.dumps(report))
        self.assertTrue(temporary_dirs)
        self.assertTrue(all(not path.exists() for path in temporary_dirs))

    def test_missing_part_and_checksum_mismatch_fail_before_archive_open(self):
        (self.parts_dir / self.part_name).unlink()
        report, _ = self.verify()
        self.assertEqual(report["reason_codes"], ["BACKUP_PART_MISSING"])

        (self.parts_dir / self.part_name).write_bytes(b"tampered")
        report, _ = self.verify()
        self.assertEqual(report["reason_codes"], ["BACKUP_PART_CHECKSUM_MISMATCH"])

    def test_wrong_password_is_reported_without_exception_text(self):
        report, _ = self.verify(fail=WrongPasswordError)
        self.assertEqual(report["reason_codes"], ["BACKUP_PASSWORD_INVALID"])
        self.assertNotIn(self.password, json.dumps(report))

    def test_missing_profile_session_entry_fails_verification(self):
        manifest = {**self.manifest, "included": ["data/root/.tdl/data/default"]}
        report, _ = self.verify(manifest=manifest)
        self.assertEqual(report["reason_codes"], ["BACKUP_PROFILE_SESSIONS_INCOMPLETE"])
        self.assertFalse(report["sessions"][1]["included"])

    def test_manifest_cannot_claim_profile_sessions_absent_from_archive(self):
        report, _ = self.verify(
            names=[
                "backup-manifest.json",
                "data/root/.tdl/data/default",
            ]
        )
        self.assertEqual(report["reason_codes"], ["BACKUP_PROFILE_SESSIONS_INCOMPLETE"])
        self.assertFalse(report["sessions"][1]["included"])

    def test_unsafe_archive_path_is_rejected(self):
        report, _ = self.verify(names=["backup-manifest.json", "../outside", "data/root/.tdl/data/default"])
        self.assertEqual(report["reason_codes"], ["BACKUP_ARCHIVE_UNSAFE_ENTRY"])

    def test_combined_report_requires_matching_redacted_tdl_diagnostics(self):
        diagnostics = {
            "worker": self.worker,
            "profile": "default",
            "checked_at": "2026-10-11T01:02:00+00:00",
            "ready": True,
            "identity_match": True,
            "reason_codes": [],
            "sessions": [
                {"name": name, "ready": True, "code": "OK", "identity_matches_metadata": True}
                for name in ("root", "user1")
            ],
        }
        archive_factory = lambda path, password: FakeArchive(path, password, self.manifest)
        report = verify_profile_backup(
            run_id=self.run_id,
            node_name=self.worker,
            profile="default",
            parts_dir=self.parts_dir,
            catalog_db=self.database,
            settings_file=self.settings,
            tdl_diagnostics=diagnostics,
            archive_factory=archive_factory,
        )
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["canary_evidence_status"], "ready_for_operator_review")
        self.assertTrue(report["tdl_diagnostics"]["identity_match"])
        self.assertEqual([item["name"] for item in report["tdl_diagnostics"]["sessions"]], ["root", "user1"])

        wrong_worker = {**diagnostics, "worker": "remote-2"}
        mismatch = verify_profile_backup(
            run_id=self.run_id,
            node_name=self.worker,
            profile="default",
            parts_dir=self.parts_dir,
            catalog_db=self.database,
            settings_file=self.settings,
            tdl_diagnostics=wrong_worker,
            archive_factory=archive_factory,
        )
        self.assertEqual(mismatch["reason_codes"], ["TDL_DIAGNOSTIC_SELECTION_MISMATCH"])

    @unittest.skipUnless(importlib.util.find_spec("py7zr"), "install requirements-verifier.txt")
    def test_real_encrypted_archive_split_into_two_parts_verifies(self):
        import py7zr

        manifest_file = self.root / "backup-manifest.json"
        manifest_file.write_text(json.dumps(self.manifest), encoding="utf-8")
        root_session = self.root / "root-session"
        user1_session = self.root / "user1-session"
        root_session.parent.mkdir(exist_ok=True)
        user1_session.parent.mkdir(exist_ok=True)
        root_session.write_bytes(b"root bolt data")
        user1_session.write_bytes(b"user1 bolt data")
        archive_file = self.root / "complete.7z"
        with py7zr.SevenZipFile(
            archive_file,
            "w",
            password=self.password,
            header_encryption=True,
        ) as archive:
            archive.write(manifest_file, "backup-manifest.json")
            archive.write(root_session, "data/root/.tdl/data/default")
            archive.write(user1_session, "data/user1/.tdl/data/default")
        archive_bytes = archive_file.read_bytes()
        split = len(archive_bytes) // 2
        first, second = archive_bytes[:split], archive_bytes[split:]
        first_name = "backup-remote.7z.001"
        second_name = "backup-remote.7z.002"
        (self.parts_dir / self.part_name).unlink()
        (self.parts_dir / first_name).write_bytes(first)
        (self.parts_dir / second_name).write_bytes(second)
        connection = sqlite3.connect(self.database)
        connection.execute("DELETE FROM backup_parts")
        for name, data in ((first_name, first), (second_name, second)):
            connection.execute(
                "INSERT INTO backup_parts VALUES (?, ?, ?, ?, ?, ?)",
                (self.run_id, self.worker, name, len(data), hashlib.sha256(data).hexdigest(), "active"),
            )
        connection.commit()
        connection.close()

        report = verify_profile_backup(
            run_id=self.run_id,
            node_name=self.worker,
            profile="default",
            parts_dir=self.parts_dir,
            catalog_db=self.database,
            settings_file=self.settings,
        )
        self.assertEqual(report["status"], "verified", report)
        self.assertTrue(report["checksums_match"])
        self.assertEqual(report["integrity"], "verified")
        self.assertEqual(report["decryption"], "verified")
        self.assertEqual(report["part_count"], 2)
        self.assertNotIn(self.password, json.dumps(report))

        self.settings.write_text(json.dumps({"compress_password": "wrong-password"}), encoding="utf-8")
        wrong_password = verify_profile_backup(
            run_id=self.run_id,
            node_name=self.worker,
            profile="default",
            parts_dir=self.parts_dir,
            catalog_db=self.database,
            settings_file=self.settings,
        )
        self.assertEqual(wrong_password["reason_codes"], ["BACKUP_PASSWORD_OR_HEADER_INVALID"])
        self.assertEqual(wrong_password["decryption"], "failed")
        self.assertNotIn("wrong-password", json.dumps(wrong_password))


if __name__ == "__main__":
    unittest.main()
