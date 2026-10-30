import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tme3bot.utility import (
    UTILITY_RUNTIME_COMMANDS,
    UtilityRuntimeError,
    UtilityRunner,
    UtilitySettingsStore,
    probe_quickmode_runtime,
    probe_utility_runtime,
)


class UtilitySummaryTests(unittest.TestCase):
    def test_compress_missing_runtime_command_has_stable_runtime_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / "quick-stage"
            folder.mkdir()
            runner = UtilityRunner(Path("utility"), workspace_root=Path(temp_dir))
            with patch.object(
                runner,
                "_run_folder",
                side_effect=RuntimeError(
                    "utility-compress exit code 127: 7z: command not found"
                ),
            ):
                with self.assertRaises(UtilityRuntimeError) as raised:
                    runner.run("compress", [str(folder)])

            self.assertEqual(raised.exception.code, "UTILITY_COMMAND_MISSING")

    def test_quickmode_probe_checks_only_quick_runtime_and_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            utility_root = root / "utility"
            workspace = root / "workspace"
            profile_root = root / "data"
            workspace.mkdir()
            profile_root.mkdir()
            compress = utility_root / "compress" / "compress.sh"
            compress.parent.mkdir(parents=True)
            compress.write_text("#!/bin/bash\n", encoding="utf-8")
            config = profile_root / "rclone.conf"
            config.write_text("[googledrive]\ntype = drive\ntoken = opaque\n", encoding="utf-8")
            before = list(workspace.iterdir())
            bin_root = root / "bin"
            bin_root.mkdir()
            commands = ("bash", "python3", "7z", "unar", "du", "cut", "ffmpeg", "ffprobe", "rclone")
            command_paths = {}
            for command in commands:
                path = bin_root / command
                path.write_text("#!/bin/sh\n", encoding="utf-8")
                path.chmod(0o755)
                command_paths[command] = str(path)

            with patch("tme3bot.utility.shutil.which", side_effect=command_paths.get):
                result = probe_quickmode_runtime(
                    utility_root,
                    workspace,
                    config,
                    profile_root,
                    "googledrive:backup",
                )

            self.assertTrue(result["ready"])
            self.assertRegex(result["fingerprint"], r"^[a-f0-9]{64}$")
            self.assertEqual(list(workspace.iterdir()), before)
            self.assertNotIn("opaque", str(result))

            with patch("tme3bot.utility.shutil.which", side_effect=command_paths.get):
                missing_remote = probe_quickmode_runtime(
                    utility_root,
                    workspace,
                    config,
                    profile_root,
                    "missing:backup",
                )
            self.assertFalse(missing_remote["ready"])
            self.assertEqual(missing_remote["reason_code"], "RCLONE_RUNTIME_UNAVAILABLE")

    def test_runtime_probe_is_read_only_and_fingerprints_utility_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            utility_root = root / "utility"
            workspace = root / "workspace"
            workspace.mkdir()
            bin_root = root / "bin"
            bin_root.mkdir()
            command_paths = {}
            for command in UTILITY_RUNTIME_COMMANDS:
                path = bin_root / command
                path.write_text("#!/bin/sh\n", encoding="utf-8")
                path.chmod(0o755)
                command_paths[command] = str(path)
            for relative in (
                "extract/extract.py",
                "flatten/flatten.py",
                "compress/compress.sh",
                "export/telegram_messages_to_json.py",
                "export/organize_media_from_json.py",
                "pindah/pindah.sh",
                "pindah/pindah4.py",
                "pindah/pindah.py",
                "pindah/pindah2.py",
            ):
                path = utility_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# probe fixture\n", encoding="utf-8")

            before = sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*"))
            with patch("tme3bot.utility.shutil.which", side_effect=command_paths.get):
                result = probe_utility_runtime(utility_root, workspace)

            after = sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*"))
            self.assertEqual(before, after)
            self.assertTrue(result["ready"])
            self.assertEqual(result["reason_code"], "")
            self.assertRegex(result["fingerprint"], r"^[a-f0-9]{64}$")

            (utility_root / "pindah" / "pindah.py").write_text(
                "# changed runtime fixture\n", encoding="utf-8"
            )
            with patch("tme3bot.utility.shutil.which", side_effect=command_paths.get):
                changed = probe_utility_runtime(utility_root, workspace)
            self.assertNotEqual(result["fingerprint"], changed["fingerprint"])

    def test_runtime_probe_reports_missing_script_without_workspace_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            utility_root = root / "utility"
            workspace = root / "workspace"
            workspace.mkdir()
            with patch("tme3bot.utility.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"):
                result = probe_utility_runtime(utility_root, workspace)

            self.assertFalse(result["ready"])
            self.assertEqual(result["reason_code"], "UTILITY_SCRIPT_MISSING")
            self.assertFalse(any(workspace.iterdir()))

    def test_runtime_probe_reports_missing_7z_without_mutating_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            utility_root = root / "utility"
            workspace = root / "workspace"
            workspace.mkdir()
            for relative in (
                "extract/extract.py",
                "flatten/flatten.py",
                "compress/compress.sh",
                "export/telegram_messages_to_json.py",
                "export/organize_media_from_json.py",
                "pindah/pindah.sh",
                "pindah/pindah4.py",
                "pindah/pindah.py",
                "pindah/pindah2.py",
            ):
                path = utility_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# probe fixture\n", encoding="utf-8")

            def which(name):
                return None if name == "7z" else f"/usr/bin/{name}"

            with patch("tme3bot.utility.shutil.which", side_effect=which):
                result = probe_utility_runtime(utility_root, workspace)

            self.assertFalse(result["ready"])
            self.assertEqual(result["reason_code"], "UTILITY_COMMAND_MISSING")
            self.assertFalse(any(workspace.iterdir()))

    def test_runner_classifies_process_start_failure_as_utility_runtime_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = UtilityRunner(Path("utility"), workspace_root=Path(temp_dir).parent)
            with patch("tme3bot.utility.subprocess.Popen", side_effect=OSError("missing executable")):
                with self.assertRaises(UtilityRuntimeError) as raised:
                    runner._command(["missing-tool"], Path(temp_dir), "utility-test")
            self.assertEqual(raised.exception.code, "UTILITY_RUNTIME_UNAVAILABLE")
            self.assertNotIn("missing executable", str(raised.exception))

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
            runner = UtilityRunner(Path("utility"), workspace_root=folder.parent)

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
                ["python3", "-c", script],
                Path(temp_dir),
                "utility-compress",
            )

        self.assertEqual(values[0]["phase"], "compressing")
        self.assertEqual(values[-1]["percent"], 25.0)
        self.assertEqual(values[-1]["eta_seconds"], 15)
        self.assertEqual(values[-1]["name"], "group-1")


if __name__ == "__main__":
    unittest.main()
