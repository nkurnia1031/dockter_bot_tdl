import tempfile
import unittest
from pathlib import Path

from tme3bot.worker.executor import storage_logical_folder, storage_relative_folders


class StorageWorkerPathTests(unittest.TestCase):
    def test_preserves_nested_and_empty_folders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "album" / "empty"
            nested.mkdir(parents=True)
            media = root / "album" / "photo.jpg"
            media.write_bytes(b"x")

            self.assertEqual(storage_relative_folders(root), ["album", "album/empty"])
            logical, relative = storage_logical_folder(
                root, media, "Archive/2026", True
            )
            self.assertEqual(relative, "album")
            self.assertEqual(logical, "Archive/2026/album")

    def test_can_flatten_legacy_upload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "nested" / "file.bin"
            path.parent.mkdir()
            path.write_bytes(b"x")
            self.assertEqual(
                storage_logical_folder(root, path, "Legacy", False),
                ("Legacy", ""),
            )


if __name__ == "__main__":
    unittest.main()
