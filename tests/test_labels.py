import tempfile
import unittest
from pathlib import Path

from tme3bot.labels import LabelStore, label_digest


class LabelStoreTests(unittest.TestCase):
    def test_add_dedupes_and_finds_label_by_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "labels.json"
            store = LabelStore(path)

            first = store.add("My Label")
            second = store.add("my-label")

            self.assertEqual(first, "my-label")
            self.assertEqual(second, "my-label")
            labels = store.list_labels()
            self.assertEqual([item.label for item in labels], ["my-label"])
            self.assertEqual(store.find_by_digest(label_digest("my-label")), "my-label")
            self.assertTrue(path.exists())

    def test_labels_persist_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "labels.json"
            LabelStore(path).add("Alpha")

            labels = LabelStore(path).list_labels()

            self.assertEqual([item.label for item in labels], ["alpha"])

    def test_empty_label_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LabelStore(Path(temp_dir) / "labels.json")

            self.assertIsNone(store.add("   "))
            self.assertEqual(store.list_labels(), [])


if __name__ == "__main__":
    unittest.main()
