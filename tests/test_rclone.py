import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tme3bot.rclone import RcloneError, RcloneRunner


class FakeSubprocessRunner:
    def __init__(self):
        self.commands = []

    def run(self, command, **kwargs):
        self.commands.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    def interrupt_current(self):
        return False


class RcloneRunnerTests(unittest.TestCase):
    def test_uploads_only_the_given_workspace_files_with_explicit_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = workspace / ".config" / "rclone.conf"
            config.parent.mkdir()
            config.write_text("[googledrive]\n", encoding="utf-8")
            archive = workspace / "result.7z.001"
            thumbnail = workspace / "result.png"
            archive.write_bytes(b"archive")
            thumbnail.write_bytes(b"thumbnail")
            subprocess_runner = FakeSubprocessRunner()

            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                result = RcloneRunner(subprocess_runner).copy_files(
                    [archive],
                    "googledrive:backup",
                    config,
                    workspace_root=workspace,
                )

            self.assertEqual(result["files"], ["result.7z.001"])
            self.assertEqual(len(subprocess_runner.commands), 1)
            command = subprocess_runner.commands[0][0]
            self.assertEqual(command[:4], ["rclone", "copyto", str(archive), "googledrive:backup/result.7z.001"])
            self.assertEqual(command[command.index("--config") + 1], str(config.resolve()))
            self.assertNotIn(str(thumbnail), command)

    def test_rejects_sources_and_config_outside_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            outside = Path(temp_dir) / "outside.7z"
            outside.write_bytes(b"archive")
            config = workspace / ".config" / "rclone.conf"
            config.parent.mkdir()
            config.write_text("[remote]\n", encoding="utf-8")

            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                with self.assertRaises(RuntimeError):
                    RcloneRunner(FakeSubprocessRunner()).copy_files(
                        [outside],
                        "googledrive:backup",
                        config,
                        workspace_root=workspace,
                    )

    def test_verifies_exact_workspace_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = workspace / ".config" / "rclone.conf"
            config.parent.mkdir()
            config.write_text("[googledrive]\n", encoding="utf-8")
            archive = workspace / "result.7z.001"
            archive.write_bytes(b"archive")
            subprocess_runner = FakeSubprocessRunner()

            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                result = RcloneRunner(subprocess_runner).verify_files(
                    [archive],
                    "googledrive:backup",
                    config,
                    workspace_root=workspace,
                )

            self.assertEqual(result["expected"], 1)
            self.assertEqual(result["found"], 1)
            self.assertEqual(result["files"], ["result.7z.001"])
            self.assertEqual(subprocess_runner.commands[0][0][:2], ["rclone", "lsf"])
            command = subprocess_runner.commands[1][0]
            self.assertEqual(command[:3], ["rclone", "check", str(archive)])
            self.assertIn("--size-only", command)

    def test_verify_reports_remote_configuration_failure(self):
        class FailedPreflightRunner(FakeSubprocessRunner):
            def run(self, command, **kwargs):
                self.commands.append((command, kwargs))
                if command[1] == "lsf":
                    return SimpleNamespace(
                        returncode=1,
                        stdout="",
                        stderr="invalid_grant: token expired",
                    )
                return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = workspace / ".config" / "rclone.conf"
            config.parent.mkdir()
            config.write_text("[googledrive]\n", encoding="utf-8")
            archive = workspace / "result.7z.001"
            archive.write_bytes(b"archive")

            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                with self.assertRaisesRegex(RcloneError, "Periksa file konfigurasi"):
                    RcloneRunner(FailedPreflightRunner()).verify_files(
                        [archive],
                        "googledrive:backup",
                        config,
                        workspace_root=workspace,
                    )

    def test_verify_recovers_matching_duplicate_from_remote_inventory(self):
        class DuplicateRemoteRunner(FakeSubprocessRunner):
            def run(self, command, **kwargs):
                self.commands.append((command, kwargs))
                if command[1] == "check":
                    return SimpleNamespace(returncode=1, stdout="", stderr="")
                if command[1] == "lsjson":
                    return SimpleNamespace(
                        returncode=0,
                        stdout=json.dumps([
                            {"Path": "result.7z.001", "Size": 7},
                            {"Path": "result.7z.001", "Size": 8},
                        ]),
                        stderr="",
                    )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = workspace / ".config" / "rclone.conf"
            config.parent.mkdir()
            config.write_text("[googledrive]\n", encoding="utf-8")
            archive = workspace / "result.7z.001"
            archive.write_bytes(b"1234567")
            runner = DuplicateRemoteRunner()

            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                result = RcloneRunner(runner).verify_files(
                    [archive],
                    "googledrive:backup",
                    config,
                    workspace_root=workspace,
                )

            self.assertEqual(result["found"], 1)
            self.assertEqual(result["missing"], [])
            self.assertTrue(any(command[0][1] == "lsjson" for command in runner.commands))


if __name__ == "__main__":
    unittest.main()
