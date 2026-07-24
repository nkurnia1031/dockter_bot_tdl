import json
import tempfile
import unittest
from pathlib import Path

from tme3bot.export_catalog import ExportArtifactCatalog, inspect_export_json


class ExportArtifactCatalogTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
