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

    def test_pindah_removes_intermediate_json_after_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            runner = UtilityRunner(Path("utility"))

            def fake_run_folder(utility, path, password, settings):
                self.assertEqual(utility, "pindah")
                (path / "output.json").write_text("{}", encoding="utf-8")
                (path / "new_output.json").write_text("{}", encoding="utf-8")

            runner._run_folder = fake_run_folder
            result = runner.run("pindah", [str(folder)])

            self.assertEqual(result.succeeded, [str(folder)])
            self.assertFalse((folder / "output.json").exists())
            self.assertFalse((folder / "new_output.json").exists())
            self.assertEqual(result.details[0]["temporary_json_removed"], 2)

    def test_structured_marker_and_7z_line_become_progress(self):
        values = []
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = UtilityRunner(
                Path("utility"), progress_callback=lambda value: values.append(value)
            )
            script = (
                "print('TME3_PROGRESS {\"phase\":\"compressing\","
                "\"index\":1,\"total\":2,\"name\":\"group-1\"}');"
                "print('group-1 ... 25% [25 MB in 5s; ~ETA: 15s; 5 MB/s]')"
            )
            runner._command(
                ["python", "-c", script],
                Path(temp_dir),
                "utility-compress",
            )

        self.assertEqual(values[0]["phase"], "compressing")
        self.assertEqual(values[-1]["percent"], 25.0)
        self.assertEqual(values[-1]["eta_seconds"], 15)
        self.assertEqual(values[-1]["name"], "group-1")


if __name__ == "__main__":
    unittest.main()
