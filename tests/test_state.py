import json
import tempfile
import unittest
from pathlib import Path

from tme3bot.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_last_id_never_moves_backwards_when_worker_finishes_late(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = StateStore(root / "state.json", root / "max.json")

            store.upsert_source("123", None, 240)
            updated = store.upsert_source("123", None, 120)

            self.assertEqual(updated.last_id, 240)
            self.assertEqual(store.get_source("123").last_id, 240)

    def test_migrates_numeric_values_and_skips_tracebacks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_path = root / "max.json"
            state_path = root / "state.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "@good_bot": " 123\n",
                        "broken": "Traceback (most recent call last): boom",
                        "": "7",
                    }
                ),
                encoding="utf-8",
            )

            store = StateStore(state_path, legacy_path)
            state = store.load()

            self.assertEqual(state.sources["@good_bot"].last_id, 123)
            self.assertIsNone(state.sources["@good_bot"].label)
            self.assertEqual(len(state.migration["skipped_keys"]), 2)
            self.assertTrue(state_path.exists())

    def test_upsert_updates_latest_label_without_splitting_last_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = StateStore(root / "state.json", root / "max.json")
            store.load()

            store.upsert_source("@bot", "alpha", 10)
            store.upsert_source("@bot", "beta", 11)

            source = store.get_source("@bot")
            self.assertIsNotNone(source)
            self.assertEqual(source.label, "beta")
            self.assertEqual(source.last_id, 11)

    def test_delete_source_removes_only_requested_chat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = StateStore(root / "state.json", root / "max.json")
            store.upsert_source("@first", None, 10)
            store.upsert_source("@second", None, 20)

            self.assertTrue(store.delete_source("@first"))
            self.assertIsNone(store.get_source("@first"))
            self.assertEqual(store.get_source("@second").last_id, 20)
            self.assertFalse(store.delete_source("@missing"))

    def test_delete_sources_removes_batch_in_one_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = StateStore(root / "state.json", root / "max.json")
            for index in range(3):
                store.upsert_source(f"@chat{index}", None, index + 1)

            deleted = store.delete_sources({"@chat0", "@chat2", "@missing"})

            self.assertEqual(deleted, ["@chat0", "@chat2"])
            self.assertEqual([item[0] for item in store.list_sources()], ["@chat1"])


if __name__ == "__main__":
    unittest.main()
