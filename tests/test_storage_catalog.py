import tempfile
import unittest
from pathlib import Path

from tme3bot.storage_catalog import StorageCatalog, build_storage_caption


def item_values(upload_id="upload-1", owner_user_id=10):
    return dict(
        upload_id=upload_id,
        owner_user_id=owner_user_id,
        owner_profile="default",
        channel_id=-1001,
        channel_message_id=9001,
        original_name="laporan-final.pdf",
        display_name="laporan-final.pdf",
        folder="2021jsa",
        keywords="javascript, archive",
        caption=build_storage_caption("2021jsa", "laporan-final.pdf", "javascript, archive"),
        file_size=1234,
        mime_type="application/pdf",
        sha256="abc",
    )


class StorageCatalogTests(unittest.TestCase):
    def test_caption_contains_folder_name_keywords_and_is_bounded(self):
        caption = build_storage_caption("2021jsa", "laporan-final.pdf", "javascript, archive")
        self.assertIn("📁 Folder: 2021jsa", caption)
        self.assertIn("#kw_javascript", caption)
        self.assertLessEqual(len(caption), 1024)

    def test_insert_is_idempotent_and_fts_searches_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            first = catalog.insert_item(**item_values())
            retry = catalog.insert_item(**item_values())
            self.assertEqual(first.id, retry.id)
            self.assertEqual(len(catalog.search("javascript")), 1)
            self.assertEqual(len(catalog.search("2021jsa")), 1)

    def test_caption_override_is_preserved_for_quick_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            caption = "batch-folder\n#ModeCepat #2026"
            item = catalog.insert_item(
                **{**item_values(), "caption": caption, "caption_override": True}
            )
            self.assertEqual(item.caption, caption)
            self.assertEqual(item.caption_sync_status, "synced")

    def test_all_authorized_users_can_edit_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            item = catalog.insert_item(**item_values())
            renamed = catalog.rename(item.id, 10, "Laporan JS 2021")
            self.assertEqual(renamed.display_name, "Laporan JS 2021")
            changed = catalog.update_metadata(item.id, 99, folder="other")
            self.assertEqual(changed.folder, "other")

    def test_any_authorized_user_can_rename_without_changing_original_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            item = catalog.insert_item(**item_values())
            renamed = catalog.rename(item.id, 99, "Nama baru")
            self.assertEqual(renamed.display_name, "Nama baru")
            self.assertEqual(renamed.original_name, "laporan-final.pdf")

    def test_delete_is_removed_from_search_but_history_remains(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            item = catalog.insert_item(**item_values())
            catalog.mark_deleted(item.id, 10)
            self.assertEqual(catalog.search("laporan"), [])
            self.assertEqual(catalog.get(item.id, include_deleted=True).status, "deleted")

    def test_backup_parts_are_idempotent_and_retention_is_per_node(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            for index in range(8):
                run_id = f"run-{index}"
                catalog.start_backup_run(run_id, "remote-1")
                catalog.upsert_backup_part(
                    run_id=run_id, node_name="remote-1", part_name="backup.7z.001",
                    channel_id=-1001, channel_message_id=100 + index, file_size=1, sha256="x",
                )
                catalog.upsert_backup_part(
                    run_id=run_id, node_name="remote-1", part_name="backup.7z.001",
                    channel_id=-1001, channel_message_id=100 + index, file_size=1, sha256="x",
                )
                catalog.finish_backup_run(run_id, "remote-1")
            self.assertEqual(len(catalog.backup_parts("run-1", "remote-1")), 1)
            self.assertEqual(len(catalog.backup_retention_candidates("remote-1", 7)), 1)

    def test_nested_folder_browser_move_and_cycle_prevention(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            parent = catalog.create_folder("Projects", 10)
            child = catalog.create_folder("2026", 10, parent.id)
            item = catalog.insert_item(
                **{**item_values(), "folder": "", "folder_id": child.id}
            )
            browser = catalog.browser(parent.id)
            self.assertEqual(browser["folders"][0]["name"], "2026")
            self.assertEqual(catalog.folder_path(child.id), "Projects/2026")
            moved = catalog.move_items([item.id], None)[0]
            self.assertEqual(moved.folder, "")
            with self.assertRaises(ValueError):
                catalog.move_folder(parent.id, child.id)

    def test_browser_reports_recursive_folder_counts_and_incomplete_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            parent = catalog.create_folder("Projects", 10)
            child = catalog.create_folder("2026", 10, parent.id)
            grandchild = catalog.create_folder("Reports", 10, child.id)

            for upload_id, message_id, name, folder_id, size in (
                ("summary-root", 9101, "root.txt", parent.id, 11),
                ("summary-child", 9102, "child.txt", child.id, 19),
                ("summary-unknown", 9103, "unknown.bin", grandchild.id, None),
            ):
                values = item_values(upload_id)
                values.update(
                    channel_message_id=message_id,
                    original_name=name,
                    display_name=name,
                    folder="",
                    folder_id=folder_id,
                    file_size=size,
                )
                catalog.insert_item(**values)

            summary = catalog.browser(None)["folders"][0]
            self.assertEqual(summary["file_count"], 3)
            self.assertEqual(summary["folder_count"], 2)
            self.assertEqual(summary["size_bytes"], 30)
            self.assertFalse(summary["size_complete"])

            nested_summary = catalog.browser(parent.id)["folders"][0]
            self.assertEqual(nested_summary["file_count"], 2)
            self.assertEqual(nested_summary["folder_count"], 1)
            self.assertEqual(nested_summary["size_bytes"], 19)
            self.assertFalse(nested_summary["size_complete"])

    def test_download_selection_deduplicates_file_and_folder_with_folder_structure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            parent = catalog.create_folder("Projects", 10)
            child = catalog.create_folder("2026", 10, parent.id)
            values = item_values("folder-download")
            values.update(
                channel_message_id=9003,
                original_name=r"C:\Exports\report.pdf",
                display_name="report.pdf",
                folder="",
                folder_id=child.id,
            )
            item = catalog.insert_item(**values)

            selected = catalog.download_selection([item.id], [parent.id])

            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["name"], "report.pdf")
            self.assertEqual(selected[0]["relative_path"], "Projects/2026/report.pdf")
            self.assertEqual(selected[0]["channel_message_id"], 9003)

    def test_duplicate_names_suffix_and_trash_restore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = StorageCatalog(Path(temp_dir) / "storage.db")
            first = catalog.insert_item(**item_values("one"))
            second_values = item_values("two")
            second_values["channel_message_id"] = 9002
            second = catalog.insert_item(**second_values)
            self.assertEqual(second.display_name, "laporan-final (2).pdf")
            catalog.trash_items([first.id], 99)
            self.assertEqual(catalog.get(first.id, include_deleted=True).status, "trashed")
            restored = catalog.restore_items([first.id])[0]
            self.assertEqual(restored.status, "active")
            self.assertEqual(restored.display_name, "laporan-final.pdf")

    def test_legacy_folder_path_migrates_to_nested_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "storage.db"
            catalog = StorageCatalog(path)
            item = catalog.insert_item(**{**item_values(), "folder": "A/B/C"})
            self.assertIsNotNone(item.folder_id)
            self.assertEqual(catalog.folder_path(item.folder_id), "A/B/C")
            self.assertEqual([part["name"] for part in catalog.breadcrumbs(item.folder_id)], ["A", "B", "C"])


if __name__ == "__main__":
    unittest.main()
