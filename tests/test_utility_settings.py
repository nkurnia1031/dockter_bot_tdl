import tempfile
import unittest
from pathlib import Path

from tme3bot.utility import UtilitySettingsStore


class UtilitySettingsTests(unittest.TestCase):
    def test_defaults_persist_and_validate_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "utility_settings.json"
            store = UtilitySettingsStore(path)
            self.assertEqual(store.get()["move_size"], "4g")
            self.assertEqual(store.get()["rclone_destination"], "googledrive:backup")

            store.set("move_size", "750m")
            store.set("compress_size", "1.5g")
            store.set("compress_password", "new-secret")

            reloaded = UtilitySettingsStore(path)
            self.assertEqual(reloaded.get()["move_size"], "750m")
            self.assertEqual(reloaded.get()["compress_size"], "1.5g")
            self.assertEqual(reloaded.get()["compress_password"], "new-secret")
            with self.assertRaises(ValueError):
                reloaded.set("move_size", "not-a-size")
            reloaded.set("rclone_destination", "googledrive:archive")
            self.assertEqual(reloaded.get()["rclone_destination"], "googledrive:archive")
            with self.assertRaises(ValueError):
                reloaded.set("rclone_destination", "not-a-remote-path")


if __name__ == "__main__":
    unittest.main()
