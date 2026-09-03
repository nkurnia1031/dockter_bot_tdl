import json
import tempfile
import unittest
from pathlib import Path

from tme3bot.export_catalog import (
    ExportArtifactCatalog,
    discard_export_without_media,
    inspect_export_json,
)


class ExportArtifactCatalogTests(unittest.TestCase):
    def test_media_less_export_is_discarded_but_media_export_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            empty = root / "empty.json"
            empty.write_text(json.dumps({"messages": [{"id": 1, "type": "text"}]}), encoding="utf-8")
            empty_stats = inspect_export_json(empty)
            self.assertEqual(empty_stats["media_count"], 0)
            self.assertTrue(discard_export_without_media(empty, empty_stats))
            self.assertFalse(empty.exists())

            media = root / "media.json"
            media.write_text(json.dumps({"messages": [{"id": 2, "file": "a.jpg"}]}), encoding="utf-8")
            media_stats = inspect_export_json(media)
            self.assertEqual(media_stats["media_count"], 1)
            self.assertFalse(discard_export_without_media(media, media_stats))
            self.assertTrue(media.exists())

    def test_inspection_classifies_media_and_preserves_unknown_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "export.json"
            path.write_text(
                json.dumps(
                    {
                        "id": "chat",
                        "messages": [
                            {"id": 1, "type": "photo", "file": "a.jpg"},
                            {
                                "id": 2,
                                "type": "video",
                                "file": {"name": "b.mp4", "size": 2048},
                            },
                            {"id": 3, "type": "text"},
                        ],
                        "tme3bot": {"chat_ref": "@chat", "label": "demo"},
                    }
                ),
                encoding="utf-8",
            )
            result = inspect_export_json(path)
            self.assertEqual(result["message_count"], 3)
            self.assertEqual(result["photo_count"], 1)
            self.assertEqual(result["video_count"], 1)
            self.assertEqual(result["expected_media_bytes"], 2048)

    def test_catalog_upsert_is_idempotent_and_archive_requires_terminal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = ExportArtifactCatalog(Path(temp_dir) / "app.db")
            values = {
                "profile": "default",
                "worker": "local",
                "filename": "a.json",
                "artifact_key": "a.json",
                "status": "pending",
            }
            first = catalog.upsert(**values)
            second = catalog.upsert(**values)
            self.assertEqual(first["id"], second["id"])
            with self.assertRaises(ValueError):
                catalog.archive(first["id"])
            catalog.update_status(first["id"], "downloaded")
            archived = catalog.archive(first["id"])
            self.assertEqual(archived["status"], "archived")
            self.assertTrue(archived["archived_at"])
            self.assertEqual(catalog.restore(first["id"])["status"], "downloaded")

    def test_inventory_batch_upserts_in_one_catalog_operation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = ExportArtifactCatalog(Path(temp_dir) / "app.db")
            records = [
                {
                    "profile": "default",
                    "worker": "local",
                    "filename": f"{index}.json",
                    "artifact_key": f"{index}.json",
                    "status": "pending",
                    "media_count": 1,
                    "last_seen_inventory_id": "inventory-1",
                }
                for index in range(3)
            ]
            self.assertEqual(catalog.upsert_many(records), 3)
            items, total = catalog.list(profile="default", worker="local")
            self.assertEqual(total, 3)
            self.assertEqual(len(items), 3)

    def test_list_filters_label_and_chat_ref_without_distinguishing_at_sign(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = ExportArtifactCatalog(Path(temp_dir) / "app.db")
            catalog.upsert(
                profile="default", worker="local", filename="one.json",
                artifact_key="one.json", status="pending", label="Archive JS",
                chat_ref="@ExampleChannel",
            )
            catalog.upsert(
                profile="default", worker="local", filename="two.json",
                artifact_key="two.json", status="pending", label="Other",
                chat_ref="987654321",
            )
            items, total = catalog.list(label="archive")
            self.assertEqual(total, 1)
            self.assertEqual(items[0]["filename"], "one.json")
            items, total = catalog.list(chat_ref="examplechannel")
            self.assertEqual(total, 1)
            self.assertEqual(items[0]["filename"], "one.json")
            items, total = catalog.list(chat_ref="@987654321")
            self.assertEqual(total, 1)
            self.assertEqual(items[0]["filename"], "two.json")

    def test_inventory_marks_missing_and_restores_discovered_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = ExportArtifactCatalog(Path(temp_dir) / "app.db")
            first = catalog.upsert(
                profile="default",
                worker="local",
                filename="first.json",
                artifact_key="first.json",
                status="pending",
            )
            second = catalog.upsert(
                profile="default",
                worker="local",
                filename="second.json",
                artifact_key="second.json",
                status="pending",
            )

            catalog.upsert(
                profile="default",
                worker="local",
                filename="first.json",
                artifact_key="first.json",
                status="pending",
                last_seen_inventory_id="inventory-2",
            )
            self.assertEqual(
                catalog.complete_inventory("default", "local", "inventory-2"), 1
            )
            self.assertTrue(catalog.get(first["id"])["available"])
            missing = catalog.get(second["id"])
            self.assertFalse(missing["available"])
            self.assertTrue(missing["missing_at"])
            available, total = catalog.list(
                profile="default", worker="local", available=True
            )
            self.assertEqual(total, 1)
            self.assertEqual(available[0]["artifact_key"], "first.json")

            restored = catalog.upsert(
                profile="default",
                worker="local",
                filename="second.json",
                artifact_key="second.json",
                status="failed",
                last_seen_inventory_id="inventory-3",
            )
            self.assertTrue(restored["available"])
            self.assertIsNone(restored["missing_at"])
            self.assertEqual(restored["status"], "failed")

    def test_preflight_missing_removes_artifact_from_runnable_queue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = ExportArtifactCatalog(Path(temp_dir) / "app.db")
            item = catalog.upsert(
                profile="default",
                worker="local",
                filename="gone.json",
                artifact_key="gone.json",
                status="pending",
            )

            missing = catalog.mark_missing("default", "local", "gone.json")

            self.assertEqual(missing["id"], item["id"])
            self.assertEqual(missing["status"], "deleted")
            self.assertFalse(missing["available"])
            pending, total = catalog.list(
                profile="default", worker="local", status="pending"
            )
            self.assertEqual(pending, [])
            self.assertEqual(total, 0)

    def test_reconcile_does_not_unarchive_terminal_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = ExportArtifactCatalog(Path(temp_dir) / "app.db")
            item = catalog.upsert(
                profile="default",
                worker="local",
                filename="done.json",
                artifact_key="done.json",
                status="downloaded",
            )
            archived = catalog.archive(item["id"])
            catalog.upsert(
                profile="default",
                worker="local",
                filename="done.json",
                artifact_key="done.json",
                status="downloaded",
                last_seen_inventory_id="inventory-1",
            )
            refreshed = catalog.get(item["id"])
            self.assertEqual(refreshed["archived_at"], archived["archived_at"])


if __name__ == "__main__":
    unittest.main()
