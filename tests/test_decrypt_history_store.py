import sqlite3
import tempfile
import unittest
from pathlib import Path

from tme3bot.infrastructure.decrypt_history_store import SqliteDecryptHistoryStore
from tme3bot.infrastructure.secret_store import AesGcmSecretStore


class DecryptHistoryStoreTests(unittest.TestCase):
    def test_records_are_encrypted_and_listed_newest_first_per_actor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key_path = root / "settings.key"
            AesGcmSecretStore(key_path)
            store = SqliteDecryptHistoryStore(root / "app.db", key_path)

            older = store.add(42, "https://example.test/older")
            newer = store.add(42, "https://example.test/newer")
            store.add(43, "https://example.test/other-user")

            rows = sqlite3.connect(root / "app.db").execute(
                "SELECT result_ciphertext FROM decrypt_history ORDER BY created_at"
            ).fetchall()
            self.assertTrue(all(b"example.test" not in bytes(row[0]) for row in rows))
            self.assertEqual(
                [item["result"] for item in store.list_for_actor(42)],
                [newer["result"], older["result"]],
            )
            self.assertEqual(store.count_for_actor(42), 2)
            self.assertEqual(store.list_for_actor(43)[0]["result"], "https://example.test/other-user")


if __name__ == "__main__":
    unittest.main()
