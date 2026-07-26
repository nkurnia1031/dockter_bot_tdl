import tempfile
import unittest
from pathlib import Path

from tme3bot.storage_catalog import StorageCatalog
from tme3bot.storage_maintenance import StorageMaintenanceService
from tests.test_storage_catalog import item_values


class FakeBot:
    def __init__(self):
        self.deleted = []
        self.captions = []

    def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    def edit_message_caption(self, chat_id, message_id, caption):
        self.captions.append((chat_id, message_id, caption))


class StorageMaintenanceTests(unittest.TestCase):
    def test_caption_queue_and_manual_purge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            item = catalog.insert_item(**item_values())
            catalog.enqueue_caption(item.id, "caption baru")
            bot = FakeBot()
            service = StorageMaintenanceService(catalog, bot)

            service.tick()
            self.assertEqual(bot.captions[0][2], "caption baru")
            catalog.trash_items([item.id], 99)
            result = service.purge([item.id], [])

            self.assertEqual(result["purged_item_ids"], [item.id])
            self.assertEqual(catalog.get(item.id, include_deleted=True).status, "deleted")
            self.assertEqual(bot.deleted, [(-1001, 9001)])


if __name__ == "__main__":
    unittest.main()
