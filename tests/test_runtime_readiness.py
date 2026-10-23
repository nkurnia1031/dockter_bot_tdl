import tempfile
import unittest
from pathlib import Path

from tme3bot.application.runtime_readiness import RuntimeReadinessGate
from tme3bot.domain.models import DomainError
from tme3bot.infrastructure.runtime_readiness_store import RuntimeReadinessStore


class RuntimeReadinessStoreTests(unittest.TestCase):
    def make_cell(self, profile, fingerprint, *, ready=True, reason_code=""):
        return {
            "profile": profile,
            "ready": ready,
            "reason_code": reason_code,
            "fingerprint": fingerprint,
        }

    def test_export_snapshot_persists_and_partial_scan_preserves_other_workers(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "runtime-readiness.json"
            store = RuntimeReadinessStore(path)
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[
                    {"worker": "local", "status": "success"},
                    {"worker": "remote-1", "status": "success"},
                ],
                profiles={
                    "local": [self.make_cell("default", "a" * 64)],
                    "remote-1": [self.make_cell("archive", "b" * 64)],
                },
            )

            restored = RuntimeReadinessStore(path)
            first_snapshot = restored.snapshot()
            self.assertEqual(len(first_snapshot["cells"]), 2)
            self.assertEqual(
                restored.cell("local", "default", "export")["fingerprint"],
                "a" * 64,
            )

            restored.apply_export_scan(
                checked_at="2026-10-23T11:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [self.make_cell("default", "c" * 64)]},
            )

            snapshot = restored.snapshot()
            self.assertEqual(
                {(item["worker"], item["profile"]) for item in snapshot["cells"]},
                {("local", "default"), ("remote-1", "archive")},
            )
            self.assertEqual(
                restored.cell("local", "default", "export")["fingerprint"],
                "c" * 64,
            )
            self.assertNotIn("fingerprint", restored.public_snapshot()["cells"][0])
            self.assertEqual(
                restored.cell("remote-1", "archive", "export")["status"],
                "ready",
            )

    def test_failed_worker_scan_is_separate_from_persisted_export_readiness(self):
        with tempfile.TemporaryDirectory() as raw:
            store = RuntimeReadinessStore(Path(raw) / "runtime-readiness.json")
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[
                    {"worker": "local", "status": "success"},
                    {"worker": "remote-1", "status": "success"},
                ],
                profiles={
                    "local": [self.make_cell("default", "a" * 64)],
                    "remote-1": [self.make_cell("archive", "b" * 64)],
                },
            )

            store.apply_export_scan(
                checked_at="2026-10-23T11:00:00Z",
                workers=[
                    {"worker": "local", "status": "success"},
                    {
                        "worker": "remote-1",
                        "status": "failed",
                        "error_code": "WORKER_UNAVAILABLE",
                    },
                ],
                profiles={"local": [self.make_cell("default", "a" * 64)]},
            )

            local = store.cell("local", "default", "export")
            remote = store.cell("remote-1", "archive", "export")
            self.assertEqual(local["status"], "ready")
            self.assertEqual(remote["status"], "ready")
            self.assertEqual(store.worker("remote-1")["status"], "failed")
            with self.assertRaises(DomainError) as raised:
                RuntimeReadinessGate(store).require_export("archive", "remote-1")
            self.assertEqual(raised.exception.code, "WORKER_OFFLINE")

    def test_export_gate_requires_a_ready_fingerprinted_cell_without_running_probe(self):
        with tempfile.TemporaryDirectory() as raw:
            store = RuntimeReadinessStore(Path(raw) / "runtime-readiness.json")
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [self.make_cell("default", "a" * 64)]},
            )
            gate = RuntimeReadinessGate(store)

            cell = gate.require_export("default", "local")

            self.assertEqual(cell["status"], "ready")
            with self.assertRaisesRegex(DomainError, "belum siap") as raised:
                gate.require_export("archive", "local")
            self.assertEqual(raised.exception.code, "RUNTIME_NOT_READY")

    def test_resolver_scan_persists_worker_only_cell_and_failure_is_scoped(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "runtime-readiness.json"
            store = RuntimeReadinessStore(path)
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [self.make_cell("default", "a" * 64)]},
            )
            store.apply_resolver_scan(
                checked_at="2026-10-23T10:05:00Z",
                workers={"local": {
                    "ready": True,
                    "fingerprint": "b" * 64,
                }},
            )

            restored = RuntimeReadinessStore(path)
            gate = RuntimeReadinessGate(restored)
            self.assertEqual(gate.require_resolver("local")["status"], "ready")
            public = restored.public_snapshot()
            resolver = next(cell for cell in public["cells"] if cell["runtime"] == "resolver")
            self.assertIsNone(resolver["profile"])
            self.assertNotIn("fingerprint", resolver)

            self.assertTrue(gate.record_resolver_failure(
                worker="local", error_code="RESOLVER_RUNTIME_UNAVAILABLE"
            ))
            self.assertEqual(restored.cell("local", None, "resolver")["status"], "not_ready")
            self.assertEqual(restored.cell("local", "default", "export")["status"], "ready")
            with self.assertRaises(DomainError) as raised:
                gate.require_resolver("local")
            self.assertEqual(raised.exception.code, "RUNTIME_NOT_READY")

            self.assertFalse(gate.record_resolver_failure(
                worker="local", error_code="SAFELINK_URL_INVALID"
            ))

    def test_quick_mode_scan_persists_separate_private_cells_and_scopes_invalidation(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "runtime-readiness.json"
            store = RuntimeReadinessStore(path)
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [self.make_cell("default", "a" * 64)]},
            )

            store.apply_quickmode_scan(
                checked_at="2026-10-23T10:05:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [{
                    "profile": "default",
                    "ready": True,
                    "fingerprint": "b" * 64,
                    "session_fingerprint": "a" * 64,
                    "destination_fingerprint": "c" * 64,
                    "rclone_destination_fingerprint": "e" * 64,
                    "sender_profiles": ["upload"],
                    "sender_session_fingerprints": {"upload": "d" * 64},
                }]},
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

            restored = RuntimeReadinessStore(path)
            quick = restored.cell("local", "default", "quick_mode")
            self.assertEqual(quick["status"], "ready")
            self.assertEqual(quick["sender_session_fingerprints"], {"upload": "d" * 64})
            self.assertEqual(restored.cell("local", "default", "export")["fingerprint"], "a" * 64)
            public = restored.public_snapshot()
            self.assertNotIn("sender_session_fingerprints", str(public))
            self.assertNotIn("fingerprint", public["cells"][0])

            restored.apply_quickmode_scan(
                checked_at="2026-10-23T11:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [{
                    "profile": "default", "ready": False,
                    "reason_code": "TDL_ACCESS_NOT_VERIFIED",
                }]},
            )
            self.assertEqual(restored.cell("local", "default", "quick_mode")["status"], "not_ready")
            self.assertEqual(restored.cell("local", "default", "export")["status"], "ready")

    def test_quick_mode_gate_requires_its_own_snapshot_cell(self):
        with tempfile.TemporaryDirectory() as raw:
            store = RuntimeReadinessStore(Path(raw) / "runtime-readiness.json")
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [self.make_cell("default", "a" * 64)]},
            )
            gate = RuntimeReadinessGate(store)

            with self.assertRaises(DomainError) as raised:
                gate.require(runtime="quick_mode", profile="default", worker="local")
            self.assertEqual(raised.exception.code, "RUNTIME_NOT_READY")
            self.assertEqual(gate.require_export("default", "local")["status"], "ready")

            store.apply_quickmode_scan(
                checked_at="2026-10-23T10:05:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [{
                    "profile": "default", "ready": True,
                    "fingerprint": "b" * 64,
                    "session_fingerprint": "a" * 64,
                    "destination_fingerprint": "c" * 64,
                    "rclone_destination_fingerprint": "e" * 64,
                    "sender_profiles": ["upload"],
                    "sender_session_fingerprints": {"upload": "d" * 64},
                }]},
            )
            cell = gate.require(runtime="quick_mode", profile="default", worker="local")
            self.assertEqual(cell["status"], "ready")
            self.assertEqual(cell["sender_session_fingerprints"], {"upload": "d" * 64})

    def test_quick_mode_access_failure_invalidates_only_matching_cell(self):
        with tempfile.TemporaryDirectory() as raw:
            store = RuntimeReadinessStore(Path(raw) / "runtime-readiness.json")
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [
                    self.make_cell("default", "a" * 64),
                    self.make_cell("archive", "f" * 64),
                ]},
            )
            quick_cells = [{
                "profile": profile,
                "ready": True,
                "fingerprint": fingerprint,
                "session_fingerprint": session,
                "destination_fingerprint": "c" * 64,
                "rclone_destination_fingerprint": "e" * 64,
                "sender_profiles": ["upload"],
                "sender_session_fingerprints": {"upload": "d" * 64},
            } for profile, fingerprint, session in (
                ("default", "b" * 64, "a" * 64),
                ("archive", "1" * 64, "f" * 64),
            )]
            store.apply_quickmode_scan(
                checked_at="2026-10-23T10:05:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": quick_cells},
            )
            gate = RuntimeReadinessGate(store)

            self.assertFalse(gate.record_quick_mode_failure(
                worker="local", profile="default", error_code="INVALID_CHAT_REF"
            ))
            self.assertEqual(store.cell("local", "default", "quick_mode")["status"], "ready")
            self.assertTrue(gate.record_quick_mode_failure(
                worker="local", profile="default", error_code="TDL_SESSION_UNAUTHORIZED"
            ))

            self.assertEqual(store.cell("local", "default", "quick_mode")["status"], "not_ready")
            self.assertEqual(store.cell("local", "archive", "quick_mode")["status"], "ready")
            self.assertEqual(store.cell("local", "default", "export")["status"], "ready")

    def test_storage_scan_persists_sender_cells_and_invalidates_only_failed_profile(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "runtime-readiness.json"
            store = RuntimeReadinessStore(path)
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [
                    self.make_cell("default", "a" * 64),
                    self.make_cell("archive", "b" * 64),
                ]},
            )
            store.apply_storage_scan(
                checked_at="2026-10-23T10:05:00Z",
                profiles={"local": [
                    {
                        "profile": "default", "ready": True,
                        "fingerprint": "1" * 64,
                        "session_fingerprint": "2" * 64,
                        "destination_fingerprint": "3" * 64,
                    },
                    {
                        "profile": "archive", "ready": False,
                        "reason_code": "TDL_ACCESS_NOT_VERIFIED",
                    },
                ]},
            )
            restored = RuntimeReadinessStore(path)
            self.assertEqual(
                RuntimeReadinessGate(restored).require_storage("default", "local")["status"],
                "ready",
            )
            self.assertNotIn("session_fingerprint", str(restored.public_snapshot()))
            self.assertNotIn("fingerprint", restored.public_snapshot()["cells"][0])

            gate = RuntimeReadinessGate(restored)
            self.assertFalse(gate.record_storage_failure(
                worker="local", profile="default", error_code="STORAGE_PATH_INVALID"
            ))
            self.assertFalse(gate.record_storage_failure(
                worker="local", profile="default", error_code="TDL_ACCESS_TARGET_UNAVAILABLE"
            ))
            self.assertTrue(gate.record_storage_failure(
                worker="local", profile="default", error_code="CHAT_WRITE_FORBIDDEN"
            ))
            self.assertEqual(restored.cell("local", "default", "storage")["status"], "not_ready")
            self.assertEqual(restored.cell("local", "archive", "storage")["reason_code"], "TDL_ACCESS_NOT_VERIFIED")
            self.assertEqual(restored.cell("local", "default", "export")["status"], "ready")

    def test_quick_mode_runtime_failure_codes_invalidate_only_matching_cell(self):
        with tempfile.TemporaryDirectory() as raw:
            store = RuntimeReadinessStore(Path(raw) / "runtime-readiness.json")
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [
                    self.make_cell("default", "a" * 64),
                    self.make_cell("archive", "f" * 64),
                ]},
            )
            store.apply_quickmode_scan(
                checked_at="2026-10-23T10:05:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [{
                    "profile": profile,
                    "ready": True,
                    "fingerprint": fingerprint,
                    "session_fingerprint": session,
                    "destination_fingerprint": "c" * 64,
                    "rclone_destination_fingerprint": "e" * 64,
                    "sender_profiles": ["upload"],
                    "sender_session_fingerprints": {"upload": "d" * 64},
                } for profile, fingerprint, session in (
                    ("default", "b" * 64, "a" * 64),
                    ("archive", "1" * 64, "f" * 64),
                )]},
            )
            gate = RuntimeReadinessGate(store)

            self.assertFalse(gate.record_quick_mode_failure(
                worker="local", profile="default", error_code="TTS_RUNTIME_UNAVAILABLE"
            ))
            self.assertTrue(gate.record_quick_mode_failure(
                worker="local", profile="default", error_code="UTILITY_PROCESS_STALLED"
            ))

            self.assertEqual(store.cell("local", "default", "quick_mode")["status"], "not_ready")
            self.assertEqual(store.cell("local", "archive", "quick_mode")["status"], "ready")
            self.assertEqual(store.cell("local", "default", "export")["status"], "ready")

    def test_explicit_rescan_replaces_old_fingerprint_without_affecting_other_workers(self):
        with tempfile.TemporaryDirectory() as raw:
            store = RuntimeReadinessStore(Path(raw) / "runtime-readiness.json")
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[
                    {"worker": "local", "status": "success"},
                    {"worker": "remote-1", "status": "success"},
                ],
                profiles={
                    "local": [self.make_cell("default", "a" * 64)],
                    "remote-1": [self.make_cell("archive", "b" * 64)],
                },
            )
            gate = RuntimeReadinessGate(store)

            store.apply_export_scan(
                checked_at="2026-10-23T11:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [self.make_cell("default", "c" * 64)]},
            )

            self.assertEqual(store.cell("local", "default", "export")["fingerprint"], "c" * 64)
            self.assertEqual(store.cell("remote-1", "archive", "export")["fingerprint"], "b" * 64)
            self.assertEqual(gate.require_export("default", "local")["status"], "ready")

    def test_runtime_failure_invalidation_is_scoped_to_one_cell(self):
        with tempfile.TemporaryDirectory() as raw:
            store = RuntimeReadinessStore(Path(raw) / "runtime-readiness.json")
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={
                    "local": [
                        self.make_cell("default", "a" * 64),
                        self.make_cell("archive", "b" * 64),
                    ]
                },
            )

            store.invalidate(
                worker="local",
                profile="default",
                runtime="export",
                reason_code="PROFILE_SESSION_UNAVAILABLE",
                checked_at="2026-10-23T11:00:00Z",
            )

            default = store.cell("local", "default", "export")
            archive = store.cell("local", "archive", "export")
            self.assertEqual(default["status"], "not_ready")
            self.assertEqual(default["fingerprint"], "")
            self.assertEqual(default["reason_code"], "PROFILE_SESSION_UNAVAILABLE")
            self.assertEqual(archive["status"], "ready")

    def test_worker_failure_marks_worker_offline_without_erasing_profile_evidence(self):
        with tempfile.TemporaryDirectory() as raw:
            store = RuntimeReadinessStore(Path(raw) / "runtime-readiness.json")
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [self.make_cell("default", "a" * 64)]},
            )

            RuntimeReadinessGate(store).record_export_failure(
                worker="local",
                profile="default",
                error_code="WORKER_UNAVAILABLE",
            )

            self.assertEqual(store.worker("local")["status"], "failed")
            self.assertEqual(store.cell("local", "default", "export")["status"], "ready")
            with self.assertRaises(DomainError) as raised:
                RuntimeReadinessGate(store).require_export("default", "local")
            self.assertEqual(raised.exception.code, "WORKER_OFFLINE")

    def test_worker_scoped_runtime_cell_supports_missing_profile(self):
        with tempfile.TemporaryDirectory() as raw:
            store = RuntimeReadinessStore(Path(raw) / "runtime-readiness.json")
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": []},
            )

            self.assertTrue(store.upsert_cell(
                worker="local",
                profile=None,
                runtime="utility",
                ready=True,
                fingerprint="c" * 64,
            ))

            cell = RuntimeReadinessGate(store).require(
                runtime="utility", profile=None, worker="local"
            )
            self.assertIsNone(cell["profile"])
            self.assertEqual(cell["status"], "ready")
            self.assertTrue(any(
                item["profile"] is None
                for item in store.public_snapshot()["cells"]
            ))
            self.assertNotIn("fingerprint", repr(store.public_snapshot()))

    def test_utility_failure_invalidates_only_worker_scoped_utility_cell(self):
        with tempfile.TemporaryDirectory() as raw:
            store = RuntimeReadinessStore(Path(raw) / "runtime-readiness.json")
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [self.make_cell("default", "a" * 64)]},
            )
            store.upsert_cell(
                worker="local", profile=None, runtime="utility", ready=True,
                fingerprint="b" * 64,
            )
            gate = RuntimeReadinessGate(store)

            self.assertFalse(gate.record_utility_failure(
                worker="local", error_code="UTILITY_PATH_INVALID"
            ))
            self.assertEqual(store.cell("local", None, "utility")["status"], "ready")
            self.assertTrue(gate.record_utility_failure(
                worker="local", error_code="UTILITY_RUNTIME_UNAVAILABLE"
            ))
            self.assertEqual(store.cell("local", None, "utility")["status"], "not_ready")
            self.assertEqual(store.cell("local", "default", "export")["status"], "ready")

    def test_tts_failure_invalidates_only_matching_worker_profile_runtime(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "runtime-readiness.json"
            store = RuntimeReadinessStore(path)
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [
                    self.make_cell("default", "a" * 64),
                    self.make_cell("archive", "b" * 64),
                ]},
            )
            for profile, fingerprint in (("default", "c" * 64), ("archive", "d" * 64)):
                store.upsert_cell(
                    worker="local", profile=profile, runtime="tts", ready=True,
                    fingerprint=fingerprint,
                )
            gate = RuntimeReadinessGate(store)

            self.assertFalse(gate.record_tts_failure(
                worker="local", profile="default", error_code="TTS_TEXT_INVALID"
            ))
            self.assertFalse(gate.record_tts_failure(
                worker="local", profile="default", error_code="TTS_ERROR"
            ))
            self.assertTrue(gate.record_tts_failure(
                worker="local", profile="default", error_code="TTS_HELPER_UNAVAILABLE"
            ))

            self.assertEqual(store.cell("local", "default", "tts")["status"], "not_ready")
            self.assertEqual(store.cell("local", "archive", "tts")["status"], "ready")
            self.assertEqual(store.cell("local", "default", "export")["status"], "ready")

    def test_tts_session_fingerprint_is_persisted_privately(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "runtime-readiness.json"
            store = RuntimeReadinessStore(path)
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": []},
            )

            store.apply_tts_scan(
                checked_at="2026-10-23T10:00:00Z",
                profiles={"local": [{
                    "profile": "default",
                    "ready": True,
                    "fingerprint": "c" * 64,
                    "session_fingerprint": "a" * 64,
                    "destination_fingerprint": "d" * 64,
                }]},
            )

            restored = RuntimeReadinessStore(path)
            self.assertEqual(restored.cell("local", "default", "tts")["session_fingerprint"], "a" * 64)
            self.assertEqual(restored.cell("local", "default", "tts")["destination_fingerprint"], "d" * 64)
            self.assertNotIn("session_fingerprint", repr(store.public_snapshot()))
            self.assertNotIn("destination_fingerprint", repr(store.public_snapshot()))

    def test_profile_mutation_invalidates_export_tts_and_dependent_quick_mode_cells(self):
        with tempfile.TemporaryDirectory() as raw:
            store = RuntimeReadinessStore(Path(raw) / "runtime-readiness.json")
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [self.make_cell("default", "a" * 64)]},
            )
            store.apply_tts_scan(
                checked_at="2026-10-23T10:00:00Z",
                profiles={"local": [{
                    "profile": "default",
                    "ready": True,
                    "fingerprint": "b" * 64,
                    "session_fingerprint": "a" * 64,
                    "destination_fingerprint": "c" * 64,
                }]},
            )
            store.apply_storage_scan(
                checked_at="2026-10-23T10:00:00Z",
                profiles={"local": [{
                    "profile": "default", "ready": True,
                    "fingerprint": "d" * 64,
                    "session_fingerprint": "a" * 64,
                    "destination_fingerprint": "c" * 64,
                }]},
            )
            store.apply_quickmode_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[{"worker": "local", "status": "success"}],
                profiles={"local": [
                    {
                        "profile": profile,
                        "ready": True,
                        "fingerprint": fingerprint,
                        "session_fingerprint": session,
                        "destination_fingerprint": "c" * 64,
                        "rclone_destination_fingerprint": "e" * 64,
                        "sender_profiles": [sender],
                        "sender_session_fingerprints": {sender: "d" * 64},
                    }
                    for profile, fingerprint, session, sender in (
                        ("default", "1" * 64, "a" * 64, "default"),
                        ("archive", "2" * 64, "b" * 64, "default"),
                        ("other", "3" * 64, "f" * 64, "other"),
                    )
                ]},
            )

            self.assertTrue(RuntimeReadinessGate(store).invalidate_profile_mutation(
                worker="local", profile="default"
            ))

            self.assertEqual(store.cell("local", "default", "export")["status"], "not_ready")
            self.assertEqual(store.cell("local", "default", "tts")["status"], "not_ready")
            self.assertEqual(store.cell("local", "default", "storage")["status"], "not_ready")
            self.assertEqual(store.cell("local", "default", "quick_mode")["status"], "not_ready")
            self.assertEqual(store.cell("local", "archive", "quick_mode")["status"], "not_ready")
            self.assertEqual(store.cell("local", "other", "quick_mode")["status"], "ready")

    def test_tts_scan_replaces_only_successful_workers_and_drops_removed_profiles(self):
        with tempfile.TemporaryDirectory() as raw:
            store = RuntimeReadinessStore(Path(raw) / "runtime-readiness.json")
            store.apply_export_scan(
                checked_at="2026-10-23T10:00:00Z",
                workers=[
                    {"worker": "local", "status": "success"},
                    {"worker": "remote-1", "status": "success"},
                ],
                profiles={"local": [], "remote-1": []},
            )
            for worker, profile, fingerprint in (
                ("local", "default", "a" * 64),
                ("local", "archive", "b" * 64),
                ("remote-1", "default", "c" * 64),
            ):
                store.upsert_cell(
                    worker=worker, profile=profile, runtime="tts", ready=True,
                    fingerprint=fingerprint, session_fingerprint=fingerprint,
                )

            store.apply_tts_scan(
                checked_at="2026-10-23T11:00:00Z",
                profiles={"local": [{
                    "profile": "default", "ready": False,
                    "reason_code": "TDL_ACCESS_NOT_VERIFIED",
                }]},
            )

            cells = store.snapshot()["cells"]
            self.assertEqual(
                {(item["worker"], item["profile"]) for item in cells if item["runtime"] == "tts"},
                {("local", "default"), ("remote-1", "default")},
            )
            self.assertEqual(store.cell("local", "default", "tts")["status"], "not_ready")
            self.assertEqual(store.cell("remote-1", "default", "tts")["status"], "ready")


if __name__ == "__main__":
    unittest.main()
