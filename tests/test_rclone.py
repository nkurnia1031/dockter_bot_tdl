import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tme3bot.rclone import RcloneError, RcloneRunner
from tme3bot.tdl import TDLCommandError


class FakeSubprocessRunner:
    def __init__(self):
        self.commands = []

    def run(self, command, **kwargs):
        self.commands.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    def interrupt_current(self):
        return False


class RcloneRunnerTests(unittest.TestCase):
    def test_recursive_folder_summary_aggregates_metadata_in_one_listing(self):
        class RecursiveListingRunner(FakeSubprocessRunner):
            def run(self, command, **kwargs):
                self.commands.append((command, kwargs))
                return SimpleNamespace(returncode=0, stdout=json.dumps([
                    {"Path": "Projects/readme.txt", "Name": "readme.txt", "IsDir": False, "Size": 10},
                    {"Path": "Projects/2026", "Name": "2026", "IsDir": True},
                    {"Path": "Projects/2026/plan.pdf", "Name": "plan.pdf", "IsDir": False, "Size": 5},
                    {"Path": "Projects/unknown.bin", "Name": "unknown.bin", "IsDir": False},
                    {"Path": "Empty", "Name": "Empty", "IsDir": True},
                    {"Path": "loose.txt", "Name": "loose.txt", "IsDir": False, "Size": 99},
                ]), stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "rclone.conf"
            config.write_text("[remote]\n", encoding="utf-8")
            fake = RecursiveListingRunner()
            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                result = RcloneRunner(fake).list_directory_summaries(
                    "remote:backup", "", config, config_root=root,
                )

        self.assertEqual(result["path"], "")
        self.assertEqual(result["summaries"], [
            {"path": "Empty", "file_count": 0, "folder_count": 0, "size_bytes": 0, "size_complete": True},
            {"path": "Projects", "file_count": 3, "folder_count": 1, "size_bytes": 15, "size_complete": False},
        ])
        self.assertEqual(len(fake.commands), 1)
        command = fake.commands[0][0]
        self.assertEqual(command[1:3], ["lsjson", "remote:backup"])
        self.assertIn("--recursive", command)
        self.assertIn("--no-modtime", command)
        self.assertIn("--no-mimetype", command)
        self.assertFalse(any("hash" in value.casefold() for value in command))

    def test_rclone_upload_progress_parses_structured_stats_without_logging_raw_stats(self):
        progress = []
        log_lines = []

        class StatsRunner(FakeSubprocessRunner):
            def run(self, command, **kwargs):
                self.commands.append((command, kwargs))
                line = json.dumps({
                    "level": "notice", "msg": "transfer details", "stats": {
                        "bytes": 42, "totalBytes": 100, "speed": 21.5, "eta": 3,
                        "transferring": [{
                            "name": "nested/archive.zip", "bytes": 42, "size": 100,
                            "percentage": 42, "speed": 21.5, "speedAvg": 20.0, "eta": 3,
                        }],
                    },
                })
                kwargs["output_callback"](line)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "rclone.conf"
            config.write_text("[remote]\n", encoding="utf-8")
            source = root / "archive.zip"
            source.write_bytes(b"x" * 100)
            fake = StatsRunner()
            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                RcloneRunner(fake, transfer_callback=progress.append, log_callback=log_lines.append).copy_files(
                    [source], "remote:backup", config,
                    workspace_root=root, config_root=root,
                    remote_names=["nested/archive.zip"],
                )

        self.assertEqual(progress, [{
            "name": "nested/archive.zip", "bytes_current": 42,
            "bytes_total": 100, "speed_bps": 21, "eta_seconds": 3,
            "percent": 42.0, "index": 1, "total": 1,
        }])
        self.assertEqual(log_lines, [])
        command, kwargs = fake.commands[0]
        self.assertIn("--stats", command)
        self.assertIn("--use-json-log", command)
        self.assertEqual(command[command.index("--stats-log-level") + 1], "NOTICE")
        self.assertEqual(command[command.index("--log-level") + 1], "NOTICE")
        self.assertFalse(kwargs["output_filter"](json.dumps({"stats": {"bytes": 1}})))
        self.assertTrue(kwargs["output_filter"](json.dumps({"level": "notice", "msg": "normal"})))

    def test_rclone_download_reports_structured_file_progress(self):
        progress = []

        class StatsRunner(FakeSubprocessRunner):
            def run(self, command, **kwargs):
                self.commands.append((command, kwargs))
                kwargs["output_callback"](json.dumps({
                    "stats": {"bytes": 8, "totalBytes": 16, "speed": 4, "eta": 2,
                              "transferring": [{"name": "file.bin", "bytes": 8, "size": 16,
                                                "percentage": 50, "speed": 4, "eta": 2}]}
                }))
                return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "rclone.conf"
            config.write_text("[remote]\n", encoding="utf-8")
            fake = StatsRunner()
            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                RcloneRunner(fake, transfer_callback=progress.append).download_file(
                    "remote:backup/file.bin", root / "file.bin", config,
                    config_root=root, file_name="file.bin", total_bytes=16,
                )

        self.assertEqual(progress[0]["bytes_current"], 8)
        self.assertEqual(progress[0]["bytes_total"], 16)
        self.assertEqual(progress[0]["speed_bps"], 4)
        self.assertEqual(progress[0]["eta_seconds"], 2)
        self.assertEqual(progress[0]["percent"], 50.0)

    def test_quickmode_folder_creation_rejects_existing_name_and_reuses_owned_folder(self):
        class ListingRunner(FakeSubprocessRunner):
            entries = []

            def run(self, command, **kwargs):
                self.commands.append((command, kwargs))
                return SimpleNamespace(returncode=0, stdout=json.dumps(self.entries), stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "rclone.conf"
            config.write_text("[remote]\n", encoding="utf-8")
            ListingRunner.entries = [{"Name": "batch", "IsDir": True}]
            collision_runner = ListingRunner()
            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                with self.assertRaises(RcloneError) as raised:
                    RcloneRunner(collision_runner).ensure_directory(
                        "remote:backup", "archive/batch", config,
                        config_root=root, create_new=True,
                    )
                self.assertEqual(raised.exception.code, "RCLONE_TARGET_EXISTS")
                self.assertEqual(len(collision_runner.commands), 1)

                ListingRunner.entries = []
                create_runner = ListingRunner()
                actual = RcloneRunner(create_runner).ensure_directory(
                    "remote:backup", "archive/batch", config,
                    config_root=root, create_new=True,
                )
                recovery_runner = ListingRunner()
                recovered = RcloneRunner(recovery_runner).ensure_directory(
                    "remote:backup", "archive/batch", config,
                    config_root=root, create_new=True, created_by_job=True,
                )

        self.assertEqual(actual, "remote:backup/archive/batch")
        self.assertEqual(recovered, actual)
        self.assertEqual(len(create_runner.commands), 2)
        self.assertEqual(create_runner.commands[0][0][1], "lsjson")
        self.assertEqual(create_runner.commands[1][0][1], "mkdir")
        self.assertEqual(len(recovery_runner.commands), 1)
        self.assertEqual(recovery_runner.commands[0][0][1], "mkdir")

    def test_folder_download_expansion_keeps_structure_for_overlapping_file_selections(self):
        class RecursiveListingRunner(FakeSubprocessRunner):
            def run(self, command, **kwargs):
                self.commands.append((command, kwargs))
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps([
                        {"Path": "sub/part.bin", "Name": "part.bin", "IsDir": False, "Size": 7},
                    ]),
                    stderr="",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "rclone.conf"
            config.write_text("[remote]\n", encoding="utf-8")
            expected = [{
                "remote_path": "remote:backup/archive/sub/part.bin",
                "relative_path": "archive/sub/part.bin",
                "name": "part.bin",
                "size": 7,
            }]
            for selections in (
                [
                    {"path": "archive", "is_dir": True},
                    {"path": "archive/sub/part.bin", "is_dir": False},
                ],
                [
                    {"path": "archive/sub/part.bin", "is_dir": False},
                    {"path": "archive", "is_dir": True},
                ],
            ):
                fake = RecursiveListingRunner()
                with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                    result = RcloneRunner(fake).list_download_files(
                        "remote:backup", selections, config, config_root=root,
                    )
                self.assertEqual(result, expected)
                self.assertEqual(len(fake.commands), 1)
                self.assertIn("--recursive", fake.commands[0][0])

    def test_download_file_uses_copyto_for_one_exact_remote_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "rclone.conf"
            config.write_text("[remote]\n", encoding="utf-8")
            target = root / "download.part"

            class DownloadRunner(FakeSubprocessRunner):
                def run(self, command, **kwargs):
                    self.commands.append((command, kwargs))
                    Path(command[3]).write_bytes(b"downloaded")
                    return SimpleNamespace(returncode=0)

            fake = DownloadRunner()
            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                RcloneRunner(fake).download_file(
                    "remote:backup/a.bin", target, config, config_root=root,
                )

            self.assertEqual(target.read_bytes(), b"downloaded")
            self.assertEqual(fake.commands[0][0][1:4], ["copyto", "remote:backup/a.bin", str(target)])

    def test_list_directory_is_read_only_searchable_sorted_and_paginated(self):
        class ListingRunner(FakeSubprocessRunner):
            def run(self, command, **kwargs):
                self.commands.append((command, kwargs))
                return SimpleNamespace(returncode=0, stdout=json.dumps([
                    {"Name": "zeta.txt", "IsDir": False, "Size": 8},
                    {"Name": "Folder", "IsDir": True, "Size": -1},
                    {"Name": "alpha.txt", "IsDir": False, "Size": 3},
                ]), stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "rclone.conf"
            config.write_text("[remote]\n", encoding="utf-8")
            fake = ListingRunner()
            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                result = RcloneRunner(fake).list_directory(
                    "remote:backup", "team", config, config_root=root,
                    query="txt", sort="name", order="asc", limit=1, offset=1,
                )
            self.assertEqual(result["path"], "team")
            self.assertEqual(result["total"], 2)
            self.assertEqual([item["name"] for item in result["items"]], ["zeta.txt"])
            command = fake.commands[0][0]
            self.assertEqual(command[1:4], ["lsjson", "remote:backup/team", "--max-depth"])
            self.assertFalse(any(part in {"copy", "copyto", "mkdir", "move", "delete"} for part in command))

    def test_list_directory_rejects_traversal_before_remote_access(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "rclone.conf"
            config.write_text("[remote]\n", encoding="utf-8")
            fake = FakeSubprocessRunner()
            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                with self.assertRaises(RcloneError):
                    RcloneRunner(fake).list_directory(
                        "remote:backup", "../outside", config, config_root=root,
                    )
            self.assertEqual(fake.commands, [])

    def test_upload_rejects_absolute_remote_name_before_remote_access(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "rclone.conf"
            config.write_text("[remote]\n", encoding="utf-8")
            source = root / "source.bin"
            source.write_bytes(b"payload")
            fake = FakeSubprocessRunner()
            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                with self.assertRaises(RcloneError):
                    RcloneRunner(fake).copy_files(
                        [source], "remote:backup", config,
                        workspace_root=root, config_root=root,
                        remote_names=["/outside/source.bin"], ignore_existing=True,
                    )
            self.assertEqual(fake.commands, [])

    def test_full_content_verification_uses_download_and_never_size_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "rclone.conf"
            config.write_text("[remote]\n", encoding="utf-8")
            source = root / "source.bin"
            source.write_bytes(b"full contents")
            fake = FakeSubprocessRunner()
            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                result = RcloneRunner(fake).verify_complete_files(
                    [source], "remote:backup", config, workspace_root=root,
                    config_root=root, remote_names=["nested/source.bin"],
                )
            self.assertTrue(result["complete"])
            command = fake.commands[0][0]
            self.assertIn("--download", command)
            self.assertNotIn("--size-only", command)
            self.assertEqual(command[3], "remote:backup/nested/source.bin")

    def test_probe_access_reads_config_and_remote_without_mutating_or_exposing_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = workspace / ".config" / "rclone.conf"
            config.parent.mkdir()
            config.write_text(
                "[googledrive]\ntoken = private-test-token\n", encoding="utf-8"
            )
            binary = workspace / "bin" / "rclone"
            binary.parent.mkdir()
            binary.write_bytes(b"fake-rclone-binary")
            subprocess_runner = FakeSubprocessRunner()

            with patch("tme3bot.rclone.shutil.which", return_value=str(binary)):
                result = RcloneRunner(subprocess_runner).probe_access(
                    "googledrive:backup",
                    config,
                    config_root=workspace,
                )

            self.assertTrue(result["ready"])
            self.assertEqual(result["reason_code"], "")
            self.assertRegex(result["fingerprint"], r"^[a-f0-9]{64}$")
            self.assertEqual(
                result["destination_fingerprint"],
                hashlib.sha256(b"googledrive:backup").hexdigest(),
            )
            self.assertNotIn("private-test-token", repr(result))
            self.assertEqual(len(subprocess_runner.commands), 1)
            command = subprocess_runner.commands[0][0]
            self.assertEqual(command[:3], ["rclone", "lsf", "googledrive:backup"])
            self.assertEqual(command[command.index("--max-depth") + 1], "1")
            self.assertEqual(
                command[command.index("--config") + 1], str(config.resolve())
            )
            self.assertFalse(
                any(
                    value in {"copy", "copyto", "mkdir", "move", "delete"}
                    for value in command
                )
            )

    def test_probe_access_reports_remote_failure_without_returning_command_output(self):
        class AccessDeniedRunner(FakeSubprocessRunner):
            def run(self, command, **kwargs):
                self.commands.append((command, kwargs))
                return SimpleNamespace(
                    returncode=1,
                    stdout="",
                    stderr="403 Forbidden token=private-test-token",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = workspace / ".config" / "rclone.conf"
            config.parent.mkdir()
            config.write_text("[googledrive]\n", encoding="utf-8")
            binary = workspace / "bin" / "rclone"
            binary.parent.mkdir()
            binary.write_bytes(b"fake-rclone-binary")

            with patch("tme3bot.rclone.shutil.which", return_value=str(binary)):
                result = RcloneRunner(AccessDeniedRunner()).probe_access(
                    "googledrive:backup", config, config_root=workspace
                )

            self.assertFalse(result["ready"])
            self.assertEqual(result["reason_code"], "RCLONE_ACCESS_FAILED")
            self.assertEqual(result["fingerprint"], "")
            self.assertNotIn("private-test-token", repr(result))

    def test_upload_remote_access_failure_has_stable_runtime_code(self):
        class AccessDeniedRunner(FakeSubprocessRunner):
            def run(self, command, **kwargs):
                del kwargs
                raise TDLCommandError(
                    command, 1, "", "Failed to copy: 403 Forbidden: access denied"
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = workspace / ".config" / "rclone.conf"
            config.parent.mkdir()
            config.write_text("[googledrive]\n", encoding="utf-8")
            archive = workspace / "result.7z.001"
            archive.write_bytes(b"archive")

            with patch("tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"):
                with self.assertRaises(RcloneError) as raised:
                    RcloneRunner(AccessDeniedRunner()).copy_files(
                        [archive],
                        "googledrive:backup",
                        config,
                        workspace_root=workspace,
                    )

            self.assertEqual(raised.exception.code, "RCLONE_ACCESS_FAILED")

    def test_nonzero_rclone_result_classifies_remote_access_but_not_input_permission(self):
        class ResultRunner(FakeSubprocessRunner):
            def __init__(self, stderr):
                super().__init__()
                self.stderr = stderr

            def run(self, command, **kwargs):
                self.commands.append((command, kwargs))
                return SimpleNamespace(returncode=1, stdout="", stderr=self.stderr)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = workspace / ".config" / "rclone.conf"
            config.parent.mkdir()
            config.write_text("[googledrive]\n", encoding="utf-8")
            archive = workspace / "result.7z.001"
            archive.write_bytes(b"archive")

            for detail, expected_code in (
                ("googleapi: Error 403: Forbidden", "RCLONE_ACCESS_FAILED"),
                ("permission denied while opening local source", ""),
            ):
                with self.subTest(detail=detail), patch(
                    "tme3bot.rclone.shutil.which", return_value="/usr/bin/rclone"
                ):
                    with self.assertRaises(RcloneError) as raised:
                        RcloneRunner(ResultRunner(detail)).copy_files(
                            [archive],
                            "googledrive:backup",
                            config,
                            workspace_root=workspace,
                        )
                    self.assertEqual(raised.exception.code, expected_code)

    def test_missing_rclone_binary_has_stable_runtime_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = workspace / ".config" / "rclone.conf"
            config.parent.mkdir()
            config.write_text("[googledrive]\n", encoding="utf-8")
            archive = workspace / "result.7z.001"
            archive.write_bytes(b"archive")

            with patch("tme3bot.rclone.shutil.which", return_value=None):
                with self.assertRaises(RcloneError) as raised:
                    RcloneRunner(FakeSubprocessRunner()).copy_files(
                        [archive],
                        "googledrive:backup",
                        config,
                        workspace_root=workspace,
                    )

            self.assertEqual(raised.exception.code, "RCLONE_RUNTIME_UNAVAILABLE")

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
                    ignore_existing=True,
                )

            self.assertEqual(result["files"], ["result.7z.001"])
            self.assertEqual(len(subprocess_runner.commands), 1)
            command = subprocess_runner.commands[0][0]
            self.assertEqual(command[:4], ["rclone", "copyto", str(archive), "googledrive:backup/result.7z.001"])
            self.assertIn("--ignore-existing", command)
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
