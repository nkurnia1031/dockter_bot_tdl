import tempfile
import unittest
from pathlib import Path

from tme3bot.utility import UtilityRunner, UtilitySettingsStore


class UtilitySummaryTests(unittest.TestCase):
    def test_organizer_log_is_reduced_to_useful_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "log.txt").write_text(
                "\n".join(
                    [
                        "messages.json | messages.html/message1 | start | bp01",
                        "messages.json | messages.html/message1 | moved 4 items",
                        "messages.json | messages.html/message2 | start | unresolved-messages-html-message2",
                        "messages.json | messages.html/message2 | moved 2 items",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                UtilityRunner._organizer_log_summary(folder),
                {
                    "groups_created": 2,
                    "items_moved": 6,
                    "unresolved_groups": 1,
                    "log_lines": 4,
                },
            )

    def test_settings_validate_sizes_and_password_length(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = UtilitySettingsStore(Path(temp_dir) / "utility-settings.json")
            store.set("move_size", "1.5g")
            self.assertEqual(store.get()["move_size"], "1.5g")
            with self.assertRaisesRegex(ValueError, "angka positif"):
                store.set("compress_size", "4")
            with self.assertRaisesRegex(ValueError, "8 sampai 128"):
                store.set("compress_password", "short")

    def test_runner_rejects_relative_folder_path(self):
        runner = UtilityRunner(Path("utility"))
        result = runner.run("pindah", ["relative-folder"])
        self.assertFalse(result.succeeded)
        self.assertIn("relative-folder", result.failed)
        self.assertIn("absolut", result.failed["relative-folder"])


if __name__ == "__main__":
    unittest.main()
