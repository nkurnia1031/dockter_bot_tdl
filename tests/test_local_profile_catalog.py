import tempfile
import unittest
from pathlib import Path

from tme3bot.infrastructure.local_profile_catalog import LocalProfileCatalog


class LocalProfileCatalogTests(unittest.TestCase):
    def test_worker_scan_replaces_only_selected_worker_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            catalog = LocalProfileCatalog(Path(temp) / "catalog.json")
            catalog.replace_scan(
                checked_at="t1",
                workers=[
                    {"name": "local", "status": "success", "checked_at": "local-old"},
                    {"name": "remote-1", "status": "success", "checked_at": "remote-old"},
                ],
                inventories=[
                    {"worker": "local", "checked_at": "local-old", "items": [{"name": "default", "ready": True}]},
                    {"worker": "remote-1", "checked_at": "remote-old", "items": [{"name": "irang", "ready": True}]},
                ],
            )
            revision = catalog.revision()

            updated = catalog.replace_worker_scan(
                worker="local",
                checked_at="t2",
                status="success",
                error_code="",
                inventory={
                    "worker": "local",
                    "checked_at": "local-new",
                    "items": [{"name": "default", "ready": False}],
                },
                expected_revision=revision,
            )

            self.assertIsNotNone(updated)
            self.assertEqual(
                {item["name"]: item["checked_at"] for item in updated["workers"]},
                {"local": "t2", "remote-1": "remote-old"},
            )
            self.assertEqual(
                {item["worker"]: item["checked_at"] for item in updated["inventories"]},
                {"local": "local-new", "remote-1": "remote-old"},
            )
            self.assertEqual(
                next(item for item in updated["inventories"] if item["worker"] == "remote-1")["items"],
                [{"name": "irang", "ready": True}],
            )

    def test_delete_invalidates_inflight_scan_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            catalog = LocalProfileCatalog(Path(temp) / "catalog.json")
            workers = [
                {"name": "local", "status": "success", "checked_at": "t1"},
                {"name": "remote-1", "status": "success", "checked_at": "t1"},
            ]
            stale_inventories = [
                {
                    "worker": "local",
                    "checked_at": "t1",
                    "items": [
                        {"name": "default", "ready": True},
                        {"name": "crestfalen", "ready": True},
                    ],
                },
                {
                    "worker": "remote-1",
                    "checked_at": "t1",
                    "items": [{"name": "crestfalen", "ready": True}],
                },
            ]
            catalog.replace_scan(
                checked_at="t1",
                workers=workers,
                inventories=stale_inventories,
            )

            scan_revision = catalog.revision()
            catalog.mark_profile_deleted("local", "crestfalen")
            stale_scan_effects = []
            stale_result = catalog.replace_scan(
                checked_at="t2",
                workers=workers,
                inventories=stale_inventories,
                expected_revision=scan_revision,
                after_commit=lambda snapshot: stale_scan_effects.append(snapshot),
            )

            self.assertIsNone(stale_result)
            self.assertEqual(stale_scan_effects, [])
            snapshot = catalog.snapshot()
            self.assertEqual(
                snapshot["profiles"],
                [{
                    "name": "crestfalen",
                    "workers": ["remote-1"],
                    "exclusive_worker": "remote-1",
                }, {
                    "name": "default",
                    "workers": ["local"],
                    "exclusive_worker": "local",
                }],
            )
            local_items = next(
                item["items"] for item in snapshot["inventories"]
                if item["worker"] == "local"
            )
            self.assertEqual([item["name"] for item in local_items], ["default"])

    def test_scan_snapshot_persists_only_successful_worker_inventories(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.json"
            first = LocalProfileCatalog(path)
            first.replace_scan(
                checked_at="2026-10-16T00:00:00+00:00",
                workers=[
                    {"name": "local", "status": "success", "checked_at": "t1"},
                    {"name": "remote-1", "status": "success", "checked_at": "t1"},
                ],
                inventories=[
                    {"worker": "local", "checked_at": "t1", "items": [
                        {"name": "default", "ready": True},
                        {"name": "broken", "ready": False},
                    ]},
                    {"worker": "remote-1", "checked_at": "t1", "items": [
                        {"name": "default", "ready": True},
                        {"name": "archive", "ready": True},
                    ]},
                ],
            )
            self.assertEqual(first.snapshot()["profiles"], [
                {"name": "archive", "workers": ["remote-1"], "exclusive_worker": "remote-1"},
                {"name": "default", "workers": ["local", "remote-1"], "exclusive_worker": ""},
            ])

            updated = first.replace_scan(
                checked_at="2026-10-16T00:01:00+00:00",
                workers=[
                    {"name": "local", "status": "success", "checked_at": "t2"},
                    {"name": "remote-1", "status": "failed", "checked_at": "t2", "error_code": "WORKER_UNAVAILABLE"},
                    {"name": "remote-2", "status": "disabled", "checked_at": ""},
                ],
                inventories=[
                    {"worker": "local", "checked_at": "t2", "items": [{"name": "default", "ready": True}]},
                    {"worker": "remote-1", "checked_at": "t1", "items": [{"name": "stale", "ready": True}]},
                    {"worker": "remote-2", "checked_at": "t2", "items": [{"name": "disabled", "ready": True}]},
                ],
            )

            self.assertEqual([item["worker"] for item in updated["inventories"]], ["local"])
            self.assertEqual(updated["profiles"], [
                {"name": "default", "workers": ["local"], "exclusive_worker": "local"},
            ])
            self.assertEqual(
                [(item["name"], item["status"]) for item in updated["workers"]],
                [("local", "success"), ("remote-1", "failed"), ("remote-2", "disabled")],
            )
            restored = LocalProfileCatalog(path).snapshot()
            self.assertEqual(restored, updated)
