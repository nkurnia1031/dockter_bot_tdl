from contextlib import contextmanager
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
    def test_lite_trash_schedule_is_independent_from_caption_recovery(self):
        class Catalog:
            def __init__(self):
                self.trash_checks = 0

            def pending_captions(self):
                return []

            def due_trash_items(self, _retention_days):
                self.trash_checks += 1
                return []

            def due_trash_folders(self, _retention_days):
                return []

        class Clock:
            now = 0.0

            def __call__(self):
                return self.now

        catalog = Catalog()
        clock = Clock()
        service = StorageMaintenanceService(
            catalog,
            FakeBot(),
            interval_seconds=30,
            trash_interval_seconds=3600,
            monotonic_clock=clock,
        )

        service.run_scheduled_tick()
        clock.now = 30
        service.run_scheduled_tick()
        clock.now = 3599
        service.run_scheduled_tick()
        self.assertEqual(catalog.trash_checks, 1)

        clock.now = 3600
        service.run_scheduled_tick()
        self.assertEqual(catalog.trash_checks, 2)
        self.assertEqual(service.interval_seconds, 30)
        self.assertEqual(service.trash_interval_seconds, 3600)

    def test_caption_queue_and_manual_purge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            item = catalog.insert_item(**item_values())
            catalog.enqueue_caption(item.id, "caption baru")
            bot = FakeBot()
            database_writes = []

            @contextmanager
            def database_activity():
                database_writes.append("begin")
                try:
                    yield
                finally:
                    database_writes.append("end")

            service = StorageMaintenanceService(
                catalog,
                bot,
                database_activity=database_activity,
            )

            service.tick()
            self.assertEqual(bot.captions[0][2], "caption baru")
            self.assertEqual(database_writes, ["begin", "end"])
            catalog.trash_items([item.id], 99)
            result = service.purge([item.id], [])

            self.assertEqual(result["purged_item_ids"], [item.id])
            self.assertEqual(database_writes, ["begin", "end", "begin", "end"])
            self.assertEqual(catalog.get(item.id, include_deleted=True).status, "deleted")
            self.assertEqual(bot.deleted, [(-1001, 9001)])


if __name__ == "__main__":
    unittest.main()
