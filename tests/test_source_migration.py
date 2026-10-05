from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tme3bot.migrate_source_state import (
    MigrationError,
    apply_plan,
    build_plan,
    export_legacy,
    inventory,
)
from tme3bot.infrastructure.source_store import SqliteSourceRepository


class SourceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / "input"
        self.inputs.mkdir()
        self.database = self.inputs / "storage.db"
        SqliteSourceRepository(self.database)
        self.backend_state = {"sources": {"channel": {
            "last_id": 10, "label": "channel", "updated_at": "2026-10-01T00:00:00+00:00",
            "warmup_done": True,
        }}}
        self.worker_state = {"sources": {"channel": {
            "last_id": 20, "label": "channel", "updated_at": "2026-10-02T00:00:00+00:00",
            "warmup_done": True,
        }}}
        (self.inputs / "backend-state.json").write_text(json.dumps(self.backend_state), encoding="utf-8")
        (self.inputs / "worker-state.json").write_text(json.dumps(self.worker_state), encoding="utf-8")
        self.write_manifest()

    def write_manifest(self):
        (self.inputs / "migration-snapshots.json").write_text(json.dumps({
            "version": 1,
            "snapshots": [
                {"origin": "backend", "profile": "default", "state_file": "backend-state.json", "database": "storage.db"},
                {"origin": "worker", "worker": "remote-1", "profile": "default", "state_file": "worker-state.json"},
            ],
        }), encoding="utf-8")

    def add_export_evidence(self):
        with sqlite3.connect(self.database) as db:
            db.executescript("""
                CREATE TABLE jobs (
                    id TEXT PRIMARY KEY, kind TEXT, profile TEXT, status TEXT,
                    payload TEXT, progress TEXT, result TEXT
                );
                CREATE TABLE export_artifacts (
                    id TEXT PRIMARY KEY, profile TEXT, export_job_id TEXT,
                    chat_ref TEXT, status TEXT
                );
                INSERT INTO jobs VALUES (
                    'job-ok', 'export', 'default', 'succeeded',
                    '{"chat_ref":"channel","text":"must-not-appear"}', '{}', '{"start_id":11,"end_id":20}'
                );
                INSERT INTO export_artifacts VALUES (
                    'artifact-ok', 'default', 'job-ok', 'channel', 'pending'
                );
            """)

    def make_inventory_and_plan(self, *, decisions=None):
        inventory_path = self.root / "inventory.json"
        plan_path = self.root / "plan.json"
        inventory(self.inputs, inventory_path)
        plan = build_plan(inventory_path, plan_path, decisions=decisions or [], migration_id="migration-test")
        return inventory_path, plan_path, plan

    def test_worker_cursor_without_artifact_coverage_is_blocked(self):
        _, _, plan = self.make_inventory_and_plan()
        self.assertEqual(plan["rows"][0]["status"], "blocked")
        self.assertIn("cursor_conflict_without_complete_export_artifact_coverage", plan["rows"][0]["reasons"])

    def test_successful_export_and_linked_artifact_prove_cursor_coverage(self):
        self.add_export_evidence()
        _, _, plan = self.make_inventory_and_plan()
        row = plan["rows"][0]
        self.assertEqual(row["status"], "approved")
        self.assertEqual(row["cursor_after"], 20)
        self.assertEqual(row["decision"].split(";")[0], "cursor=promote_verified_worker")
        self.assertEqual(row["evidence"][0]["artifacts"][0]["id"], "artifact-ok")
        self.assertNotIn("must-not-appear", (self.root / "inventory.json").read_text(encoding="utf-8"))

    def test_metadata_conflict_requires_an_explicit_decision(self):
        self.worker_state["sources"]["channel"]["label"] = "different"
        (self.inputs / "worker-state.json").write_text(json.dumps(self.worker_state), encoding="utf-8")
        _, _, plan = self.make_inventory_and_plan()
        self.assertEqual(plan["rows"][0]["status"], "blocked")
        _, _, resolved = self.make_inventory_and_plan(decisions=["default|channel=metadata:keep_backend_metadata"])
        self.assertEqual(resolved["rows"][0]["status"], "blocked")  # cursor is still unproven
        self.add_export_evidence()
        _, _, resolved = self.make_inventory_and_plan(decisions=["default|channel=metadata:keep_backend_metadata"])
        self.assertEqual(resolved["rows"][0]["status"], "approved")
        self.assertEqual(resolved["rows"][0]["label"], "channel")

    def test_apply_defaults_to_dry_run_and_commit_replay_is_idempotent(self):
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE export_artifacts (id TEXT PRIMARY KEY, status TEXT)")
            db.execute("INSERT INTO export_artifacts VALUES ('artifact-pending', 'pending')")
        self.worker_state["sources"]["channel"]["last_id"] = 10
        (self.inputs / "worker-state.json").write_text(json.dumps(self.worker_state), encoding="utf-8")
        inventory_path = self.root / "inventory.json"
        plan_path = self.root / "plan.json"
        inventory(self.inputs, inventory_path)
        build_plan(inventory_path, plan_path, migration_id="migration-test")
        before = SqliteSourceRepository.export_database_snapshot(self.database)
        dry = apply_plan(plan_path, self.database, commit=False, backup=None, exports_drained=False)
        self.assertEqual(dry["mode"], "dry-run")
        self.assertEqual(SqliteSourceRepository.export_database_snapshot(self.database), before)
        backup = self.root / "backup.db"
        backup.write_bytes(b"verified-local-backup-placeholder")
        with self.assertRaises(MigrationError):
            apply_plan(plan_path, self.database, commit=True, backup=backup, exports_drained=False)
        result = apply_plan(plan_path, self.database, commit=True, backup=backup, exports_drained=True)
        self.assertFalse(result["replay"])
        source = SqliteSourceRepository(self.database).get_source("default", "channel")
        self.assertEqual(source.last_id, 10)
        revision = source.revision
        replay = apply_plan(plan_path, self.database, commit=True, backup=None, exports_drained=False)
        self.assertTrue(replay["replay"])
        self.assertEqual(SqliteSourceRepository(self.database).get_source("default", "channel").revision, revision)
        self.assertEqual(len(SqliteSourceRepository.export_database_snapshot(self.database)["ledger"]), 1)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT id, status FROM export_artifacts").fetchone(), ("artifact-pending", "pending"))

    def test_changed_input_is_rejected(self):
        self.worker_state["sources"]["channel"]["last_id"] = 10
        (self.inputs / "worker-state.json").write_text(json.dumps(self.worker_state), encoding="utf-8")
        _, plan_path, _ = self.make_inventory_and_plan()
        (self.inputs / "backend-state.json").write_text(json.dumps({"sources": {}}), encoding="utf-8")
        with self.assertRaisesRegex(MigrationError, "Checksum input berubah"):
            apply_plan(plan_path, self.database, commit=False, backup=None, exports_drained=False)

    def test_active_export_blocks_dry_run_and_commit(self):
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE jobs (id TEXT, kind TEXT, profile TEXT, status TEXT)")
            db.execute("INSERT INTO jobs VALUES ('active', 'export', 'default', 'running')")
        self.worker_state["sources"]["channel"]["last_id"] = 10
        (self.inputs / "worker-state.json").write_text(json.dumps(self.worker_state), encoding="utf-8")
        _, plan_path, _ = self.make_inventory_and_plan()
        with self.assertRaisesRegex(MigrationError, "export aktif"):
            apply_plan(plan_path, self.database, commit=False, backup=None, exports_drained=False)

    def test_legacy_export_contains_source_and_ledger_without_touching_artifacts(self):
        self.worker_state["sources"]["channel"]["last_id"] = 10
        (self.inputs / "worker-state.json").write_text(json.dumps(self.worker_state), encoding="utf-8")
        inventory_path = self.root / "inventory.json"
        plan_path = self.root / "plan.json"
        inventory(self.inputs, inventory_path)
        build_plan(inventory_path, plan_path, migration_id="migration-test")
        backup = self.root / "backup.db"
        backup.write_bytes(b"backup")
        apply_plan(plan_path, self.database, commit=True, backup=backup, exports_drained=True)
        output = self.root / "legacy-export"
        result = export_legacy(self.database, output, exports_drained=True)
        exported = json.loads((output / "state.json").read_text(encoding="utf-8"))
        ledger = json.loads((output / "source-migration-ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(exported["sources"]["channel"]["last_id"], 10)
        self.assertEqual(len(ledger["ledger"]), 1)
        self.assertEqual(ledger["runs"][0]["migration_id"], "migration-test")
        self.assertEqual(result["sources"], 1)
        with self.assertRaises(MigrationError):
            export_legacy(self.database, output, exports_drained=True)

    def test_manifest_rejects_path_escape(self):
        manifest = json.loads((self.inputs / "migration-snapshots.json").read_text(encoding="utf-8"))
        manifest["snapshots"][0]["database"] = "../../outside.db"
        (self.inputs / "migration-snapshots.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(MigrationError):
            inventory(self.inputs, self.root / "inventory.json")


if __name__ == "__main__":
    unittest.main()
