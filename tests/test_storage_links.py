import unittest

from tme3bot.storage_links import sign_storage_item, verify_storage_item


class StorageLinkTests(unittest.TestCase):
    def test_token_is_stable_compact_and_tamper_evident(self):
        token = sign_storage_item(42, "x" * 48)
        self.assertEqual(token, sign_storage_item(42, "x" * 48))
        self.assertLess(len(token), 40)
        self.assertEqual(verify_storage_item(token, "x" * 48), 42)
        with self.assertRaises(ValueError):
            verify_storage_item(token + "a", "x" * 48)


if __name__ == "__main__":
    unittest.main()
