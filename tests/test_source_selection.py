import unittest

from tme3bot.source_selection import SourceSelectionStore


class SourceSelectionStoreTests(unittest.TestCase):
    def test_selection_is_scoped_and_can_be_pruned(self) -> None:
        store = SourceSelectionStore()
        first_owner = (1, "default")
        second_owner = (1, "other")

        store.toggle(first_owner, "@one")
        store.select_all(second_owner, ["@two", "@three"])

        self.assertEqual(store.get(first_owner), {"@one"})
        self.assertEqual(store.get(second_owner), {"@two", "@three"})
        self.assertEqual(store.retain(second_owner, ["@three"]), {"@three"})

    def test_toggle_discard_and_clear_remove_empty_entries(self) -> None:
        store = SourceSelectionStore()
        owner = (1, "default")

        store.toggle(owner, "@one")
        self.assertEqual(store.toggle(owner, "@one"), set())
        store.select_all(owner, ["@one", "@two"])
        self.assertEqual(store.discard(owner, ["@one"]), {"@two"})
        store.clear(owner)
        self.assertEqual(store.get(owner), set())


if __name__ == "__main__":
    unittest.main()
