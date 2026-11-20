from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tme3bot.utility import UtilityFlattenPreviewStaleError, UtilityRunner
from utility.extract.extract import _discard_partial_output


class UtilityFeatureTests(unittest.TestCase):
    def test_extract_only_treats_numbered_volumes_with_a_next_part_as_archives(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder = root / "numbered-volumes"
            folder.mkdir()
            orphan = folder / "orphan.001"
            orphan.write_bytes(b"ordinary numbered file")
            first_part = folder / "split.001"
            first_part.write_bytes(b"archive volume 1")
            (folder / "split.002").write_bytes(b"archive volume 2")

            bin_root = root / "bin"
            bin_root.mkdir()
            called = root / "7z-called"
            executable = bin_root / "7z"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                "from pathlib import Path\n"
                "args = sys.argv[1:]\n"
                "archive = next(arg for arg in args if arg.endswith('.001'))\n"
                "output = Path(next(arg[2:] for arg in args if arg.startswith('-o')))\n"
                "output.mkdir(parents=True, exist_ok=True)\n"
                "(output / 'payload.bin').write_bytes(b'extracted')\n"
                "Path(os.environ['UTILITY_TEST_7Z_CALLED']).write_text(archive)\n"
                "print('- payload.bin')\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=root,
            )

            with patch.dict(
                os.environ,
                {
                    "PATH": f"{bin_root}{os.pathsep}/usr/bin{os.pathsep}/bin",
                    "UTILITY_TEST_7Z_CALLED": str(called),
                },
            ):
                result = runner.run("extract", [str(folder)])

            self.assertEqual(result.outcome, "succeeded", result.archive_results)
            self.assertEqual([item["name"] for item in result.archive_results], ["split.001"])
            self.assertEqual(Path(called.read_text(encoding="utf-8")).name, "split.001")
            self.assertTrue(orphan.is_file())
            self.assertFalse(first_part.exists())
            self.assertFalse((folder / "split.002").exists())

    def test_split_7z_uses_supplied_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder = root / "split-password"
            folder.mkdir()
            archive = folder / "encrypted.7z.001"
            archive.write_bytes(b"archive volume 1")
            (folder / "encrypted.7z.002").write_bytes(b"archive volume 2")

            bin_root = root / "bin"
            bin_root.mkdir()
            command_record = root / "7z-arguments.json"
            executable = bin_root / "7z"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "args = sys.argv[1:]\n"
                "archive = next(arg for arg in args if arg.endswith('.7z.001'))\n"
                "output = Path(next(arg[2:] for arg in args if arg.startswith('-o')))\n"
                "output.mkdir(parents=True, exist_ok=True)\n"
                "(output / 'payload.bin').write_bytes(b'extracted')\n"
                "Path(os.environ['UTILITY_TEST_7Z_ARGS']).write_text(json.dumps(args))\n"
                "print('- payload.bin')\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=root,
            )

            with patch.dict(
                os.environ,
                {
                    "PATH": f"{bin_root}{os.pathsep}/usr/bin{os.pathsep}/bin",
                    "UTILITY_TEST_7Z_ARGS": str(command_record),
                },
            ):
                result = runner.run(
                    "extract", [str(folder)], password="split-secret-password"
                )

            self.assertEqual(result.outcome, "succeeded", result.archive_results)
            self.assertEqual(result.archive_results[0]["name"], archive.name)
            args = json.loads(command_record.read_text(encoding="utf-8"))
            self.assertIn("-psplit-secret-password", args)
            self.assertFalse(archive.exists())
            self.assertFalse((folder / "encrypted.7z.002").exists())

    def _fake_7z_rar_with_exclusions(self, root: Path) -> tuple[Path, dict[str, str]]:
        bin_root = root / "bin"
        bin_root.mkdir(parents=True)
        executable = bin_root / "7z"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import fnmatch, json, os, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['UTILITY_TEST_CALLS'], 'a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(args, ensure_ascii=False) + '\\n')\n"
            "if os.environ.get('UTILITY_TEST_7Z_FAIL') == '1':\n"
            "    print('ERROR: Unsupported Method : nested/payload.bin')\n"
            "    raise SystemExit(2)\n"
            "archive = Path(next(value for value in args if value.endswith('.rar')))\n"
            "output = Path(next(value[2:] for value in args if value.startswith('-o')))\n"
            "output.mkdir(parents=True, exist_ok=True)\n"
            "patterns = [arg[4:] for arg in args if arg.startswith('-xr!')]\n"
            "case_sensitive = '-ssc-' not in args\n"
            "members = ('nested/payload.bin', 'nested/readme.TXT', 'nested/link.Url')\n"
            "for member in members:\n"
            "    candidate = member if case_sensitive else member.casefold()\n"
            "    normalized = patterns if case_sensitive else [p.casefold() for p in patterns]\n"
            "    if any(fnmatch.fnmatchcase(candidate, pattern) for pattern in normalized):\n"
            "        continue\n"
            "    target = output / member\n"
            "    target.parent.mkdir(parents=True, exist_ok=True)\n"
            "    target.write_text('kept', encoding='utf-8')\n"
            "    print(f'- {member}')\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        for fallback_name in ("unrar", "unar"):
            fallback = bin_root / fallback_name
            fallback.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' {fallback_name} >> \"$UTILITY_TEST_FALLBACK_CALLS\"\n",
                encoding="utf-8",
            )
            fallback.chmod(0o755)
        return bin_root, {
            "PATH": f"{bin_root}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "UTILITY_TEST_CALLS": str(root / "calls.txt"),
            "UTILITY_TEST_FALLBACK_CALLS": str(root / "fallback-calls.txt"),
        }

    def _fake_7z_partial_with_missing_failed_member(
        self, root: Path
    ) -> tuple[Path, dict[str, str]]:
        bin_root = root / "bin"
        bin_root.mkdir(parents=True)
        executable = bin_root / "7z"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "output = Path(next(arg[2:] for arg in args if arg.startswith('-o')))\n"
            "output.mkdir(parents=True, exist_ok=True)\n"
            "(output / 'empty.txt').touch()\n"
            "print('- empty.txt')\n"
            "print('- missing.txt')\n"
            "print('ERROR: Data Error : missing.txt')\n"
            "raise SystemExit(2)\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return bin_root, {
            "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
        }

    def _fake_7z_unclassified_partial_error(
        self, root: Path
    ) -> tuple[Path, dict[str, str]]:
        bin_root = root / "bin"
        bin_root.mkdir(parents=True)
        executable = bin_root / "7z"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "output = Path(next(arg[2:] for arg in args if arg.startswith('-o')))\n"
            "output.mkdir(parents=True, exist_ok=True)\n"
            "(output / 'partial.txt').write_bytes(b'not a completed member')\n"
            "print('- partial.txt')\n"
            "print('ERROR: Data Error')\n"
            "raise SystemExit(2)\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return bin_root, {
            "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
        }

    def _fake_7z_colon_member_failure(
        self, root: Path
    ) -> tuple[Path, dict[str, str]]:
        bin_root = root / "bin"
        bin_root.mkdir(parents=True)
        executable = bin_root / "7z"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "output = Path(next(arg[2:] for arg in args if arg.startswith('-o')))\n"
            "output.mkdir(parents=True, exist_ok=True)\n"
            "(output / 'foo:bar.txt').touch()\n"
            "print('- foo:bar.txt')\n"
            "print('ERROR: Wrong password : foo:bar.txt')\n"
            "raise SystemExit(2)\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return bin_root, {
            "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
        }

    def _fake_7z_duplicate_member_names(self, root: Path) -> tuple[Path, dict[str, str]]:
        bin_root = root / "bin"
        bin_root.mkdir(parents=True)
        executable = bin_root / "7z"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "archive = next(Path(arg) for arg in args if arg.endswith(('.zip', '.7z', '.rar')))\n"
            "password = next((arg[2:] for arg in args if arg.startswith('-p')), '')\n"
            "output = Path(next(arg[2:] for arg in args if arg.startswith('-o')))\n"
            "output.mkdir(parents=True, exist_ok=True)\n"
            "if archive.name == 'first.zip':\n"
            "    if password == 'later-secret':\n"
            "        target = output / 'dirC' / 'other.txt'\n"
            "        target.parent.mkdir(parents=True, exist_ok=True)\n"
            "        target.write_text('other', encoding='utf-8')\n"
            "        print('- dirC/other.txt')\n"
            "        print('- dirA/item.txt')\n"
            "        print('ERROR: Data Error : dirA/item.txt')\n"
            "    else:\n"
            "        target = output / 'dirB' / 'item.txt'\n"
            "        target.parent.mkdir(parents=True, exist_ok=True)\n"
            "        target.write_text('item', encoding='utf-8')\n"
            "        print('- dirB/item.txt')\n"
            "        print('- dirC/other.txt')\n"
            "        print('ERROR: Data Error : dirC/other.txt')\n"
            "    raise SystemExit(2)\n"
            "(output / 'later.txt').write_text('later', encoding='utf-8')\n"
            "print('- later.txt')\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return bin_root, {
            "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
        }

    def _fake_7z(self, root: Path, passwords: dict[str, str]) -> tuple[Path, dict[str, str]]:
        bin_root = root / "bin"
        bin_root.mkdir(parents=True)
        executable = bin_root / "7z"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "archive = next(Path(arg) for arg in args if arg.lower().endswith(('.zip', '.7z', '.7z.001', '.rar')))\n"
            "password = next((arg[2:] for arg in args if arg.startswith('-p')), '')\n"
            "output = Path(next(arg[2:] for arg in args if arg.startswith('-o')))\n"
            "output.mkdir(parents=True, exist_ok=True)\n"
            "(output / 'partial.txt').write_text('partial', encoding='utf-8')\n"
            "accepted = json.loads(os.environ['UTILITY_TEST_PASSWORDS'])\n"
            "if password != accepted.get(archive.name):\n"
            "    print(f'ERROR: Wrong password : {output / \"partial.txt\"}')\n"
            "    raise SystemExit(2)\n"
            "(output / 'partial.txt').unlink()\n"
            "(output / 'contents.txt').write_text('extracted', encoding='utf-8')\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        env = {
            "PATH": f"{bin_root}{os.pathsep}{os.environ.get('PATH', '')}",
            "UTILITY_TEST_PASSWORDS": json.dumps(passwords),
        }
        return bin_root, env

    def test_rar_extract_uses_7z_and_excludes_text_and_url_members(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder = root / "partial-archive"
            folder.mkdir()
            archive = folder / "sample.rar"
            archive.write_bytes(b"archive")
            _, env = self._fake_7z_rar_with_exclusions(root)
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=root,
            )

            with patch.dict(os.environ, env):
                result = runner.run("extract", [str(folder)])

            self.assertEqual(result.outcome, "succeeded")
            item = result.archive_results[0]
            self.assertEqual(item["status"], "succeeded")
            output = Path(str(item["output"]))
            self.assertEqual(item["files_extracted"], 1)
            self.assertTrue((output / "nested" / "payload.bin").is_file())
            self.assertFalse(any(path.suffix.casefold() in {".txt", ".url"} for path in output.rglob("*")))
            command_args = json.loads((root / "calls.txt").read_text(encoding="utf-8"))
            self.assertEqual(command_args[0], "x")
            self.assertIn("-xr!*.txt", command_args)
            self.assertIn("-xr!*.url", command_args)
            self.assertIn("-ssc-", command_args)
            self.assertFalse((root / "fallback-calls.txt").exists())
            self.assertFalse(archive.exists())
            self.assertFalse(list(folder.glob(".extract-attempt-*")))
            self.assertEqual(
                [path.name for path in folder.iterdir() if path.is_dir()],
                [output.name],
            )

    def test_rar_extract_does_not_fallback_when_7z_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder = root / "failed-archive"
            folder.mkdir()
            archive = folder / "sample.rar"
            archive.write_bytes(b"archive")
            _, env = self._fake_7z_rar_with_exclusions(root)
            env["UTILITY_TEST_7Z_FAIL"] = "1"
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=root,
            )

            with patch.dict(os.environ, env):
                result = runner.run("extract", [str(folder)])

            self.assertEqual(result.outcome, "failed")
            self.assertEqual(result.archive_results[0]["status"], "failed")
            self.assertTrue(archive.is_file())
            self.assertFalse((root / "fallback-calls.txt").exists())

    def test_extract_keeps_empty_success_when_failed_member_has_no_staged_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder = root / "partial-archive"
            folder.mkdir()
            archive = folder / "sample.zip"
            archive.write_bytes(b"archive")
            _, env = self._fake_7z_partial_with_missing_failed_member(root)
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=root,
            )

            with patch.dict(os.environ, env):
                result = runner.run("extract", [str(folder)])

            self.assertEqual(result.outcome, "succeeded", result.archive_results)
            item = result.archive_results[0]
            self.assertEqual(item["status"], "succeeded")
            self.assertTrue(item["partial"])
            self.assertEqual(item["files_extracted"], 1)
            self.assertEqual(item["failed_files"], 1)
            output = Path(str(item["output"]))
            self.assertTrue((output / "empty.txt").is_file())
            self.assertEqual((output / "empty.txt").stat().st_size, 0)
            self.assertTrue(archive.is_file())

    def test_extract_rejects_nonempty_member_when_7z_error_is_unclassified(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder = root / "partial-archive"
            folder.mkdir()
            archive = folder / "sample.zip"
            archive.write_bytes(b"archive")
            _, env = self._fake_7z_unclassified_partial_error(root)
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=root,
            )

            with patch.dict(os.environ, env):
                result = runner.run("extract", [str(folder)])

            self.assertEqual(result.outcome, "failed", result.archive_results)
            self.assertEqual(result.archive_results[0]["status"], "failed")
            self.assertEqual(result.archive_results[0]["failed_files"], 1)
            self.assertIsNone(result.archive_results[0]["output"])
            self.assertTrue(archive.is_file())
            self.assertFalse((folder / "sample").exists())

    def test_extract_does_not_misclassify_colon_in_failed_member_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder = root / "colon-member"
            folder.mkdir()
            archive = folder / "sample.zip"
            archive.write_bytes(b"archive")
            _, env = self._fake_7z_colon_member_failure(root)
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=root,
            )

            with patch.dict(os.environ, env):
                result = runner.run("extract", [str(folder)])

            self.assertEqual(result.outcome, "failed", result.archive_results)
            self.assertEqual(result.archive_results[0]["failed_files"], 1)
            self.assertTrue(archive.is_file())
            self.assertFalse((folder / "sample").exists())

    def test_extract_does_not_resolve_failed_member_by_duplicate_basename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder = root / "duplicate-member-names"
            first_folder = folder / "A"
            later_folder = folder / "B"
            first_folder.mkdir(parents=True)
            later_folder.mkdir()
            first_archive = first_folder / "first.zip"
            later_archive = later_folder / "second.zip"
            first_archive.write_bytes(b"archive")
            later_archive.write_bytes(b"archive")
            (later_folder / ".pass").write_text("later-secret", encoding="utf-8")
            _, env = self._fake_7z_duplicate_member_names(root)
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=root,
            )

            with patch.dict(os.environ, env):
                result = runner.run("extract", [str(folder)])

            first = next(item for item in result.archive_results if item["name"] == "first.zip")
            self.assertEqual(first["status"], "succeeded")
            self.assertTrue(first["partial"])
            self.assertEqual(first["failed_files"], 1)
            output = Path(str(first["output"]))
            self.assertTrue((output / "dirB" / "item.txt").is_file())
            self.assertTrue((output / "dirC" / "other.txt").is_file())
            self.assertTrue(first_archive.is_file())

    def test_partial_cleanup_rejects_workspace_parent_replaced_by_symlink(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            selected = workspace / "selected"
            outside = root / "outside"
            selected.mkdir(parents=True)
            outside.mkdir()
            moved = workspace / "selected-original"
            selected.rename(moved)
            (outside / "archive").mkdir()
            (outside / "archive" / "keep.txt").write_text("keep")
            selected.symlink_to(outside, target_is_directory=True)

            removed = _discard_partial_output(
                selected / "archive.zip",
                selected / "archive",
                workspace.resolve(),
            )

            self.assertFalse(removed)
            self.assertEqual(
                (outside / "archive" / "keep.txt").read_text(), "keep"
            )

    def test_extract_retries_earlier_archives_with_folder_pool_and_keeps_secrets_private(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "selected"
            first_folder = root / "A"
            second_folder = root / "B"
            first_folder.mkdir(parents=True)
            second_folder.mkdir()
            first_archive = first_folder / "first.zip"
            second_archive = second_folder / "second.zip"
            first_archive.write_bytes(b"archive")
            second_archive.write_bytes(b"archive")
            (first_folder / ".pass").write_text("wrong-a", encoding="utf-8")
            (second_folder / ".pass").write_text("late-secret", encoding="utf-8")
            existing_output = first_folder / "first"
            existing_output.mkdir()
            (existing_output / "keep.txt").write_text("existing", encoding="utf-8")
            _, env = self._fake_7z(
                Path(temp_dir),
                {"first.zip": "late-secret", "second.zip": "late-secret"},
            )
            progress: list[dict[str, object]] = []
            logs: list[str] = []
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                progress_callback=progress.append,
                log_callback=logs.append,
                workspace_root=Path(temp_dir),
            )

            with patch.dict(os.environ, env):
                result = runner.run("extract", [str(root)], password="wrong-form")

            self.assertEqual(result.outcome, "succeeded")
            self.assertEqual(
                [(item["name"], item["status"]) for item in result.archive_results],
                [("first.zip", "succeeded"), ("second.zip", "succeeded")],
            )
            first = result.archive_results[0]
            self.assertEqual(first["pass"], "retry")
            self.assertGreaterEqual(int(first["attempt_count"]), 3)
            self.assertTrue((first_folder / "first_2" / "contents.txt").is_file())
            self.assertEqual((existing_output / "keep.txt").read_text(encoding="utf-8"), "existing")
            self.assertFalse(first_archive.exists())
            self.assertFalse(second_archive.exists())
            self.assertFalse((first_folder / "first_2" / "partial.txt").exists())
            self.assertTrue(any(item.get("phase") == "archive_retrying" for item in progress))
            self.assertNotIn("wrong-form", json.dumps(result.__dict__, ensure_ascii=False))
            self.assertNotIn("wrong-a", json.dumps(result.__dict__, ensure_ascii=False))
            self.assertNotIn("late-secret", json.dumps(result.__dict__, ensure_ascii=False))
            self.assertNotIn("wrong-form", "\n".join(logs))
            self.assertNotIn("wrong-a", "\n".join(logs))
            self.assertNotIn("late-secret", "\n".join(logs))
            self.assertNotIn("wrong-form", json.dumps(progress, ensure_ascii=False))
            self.assertNotIn("wrong-a", json.dumps(progress, ensure_ascii=False))
            self.assertNotIn("late-secret", json.dumps(progress, ensure_ascii=False))

    def test_extract_shares_all_discovered_password_candidates_even_after_an_early_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "workspace"
            first_folder = root / "A"
            second_folder = root / "B"
            first_folder.mkdir(parents=True)
            second_folder.mkdir()
            (first_folder / "first.zip").write_bytes(b"archive")
            (first_folder / ".pass").write_text("shared-password", encoding="utf-8")
            (second_folder / "second.zip").write_bytes(b"archive")
            _, env = self._fake_7z(
                Path(temp_dir),
                {"first.zip": "form-password", "second.zip": "shared-password"},
            )
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=root.parent,
            )

            with patch.dict(os.environ, env):
                result = runner.run(
                    "extract", [str(root)], password="form-password"
                )

            self.assertEqual(
                result.outcome,
                "succeeded",
                f"failed={result.failed}; archive_results={result.archive_results}",
            )
            self.assertEqual(
                [(item["name"], item["pass"]) for item in result.archive_results],
                [("first.zip", "first"), ("second.zip", "retry")],
            )
            self.assertFalse((first_folder / "first.zip").exists())
            self.assertFalse((second_folder / "second.zip").exists())

    def test_extract_password_pool_is_scoped_to_each_selected_folder_and_failed_sources_remain(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_folder = root / "folder-one"
            second_folder = root / "folder-two"
            first_folder.mkdir()
            second_folder.mkdir()
            first_archive = first_folder / "known.zip"
            second_archive = second_folder / "unknown.zip"
            first_archive.write_bytes(b"archive")
            second_archive.write_bytes(b"archive")
            (first_folder / ".pass").write_text("folder-one-secret", encoding="utf-8")
            _, env = self._fake_7z(
                root,
                {"known.zip": "folder-one-secret", "unknown.zip": "folder-one-secret"},
            )
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=root,
            )

            with patch.dict(os.environ, env):
                result = runner.run("extract", [str(first_folder), str(second_folder)])

            self.assertEqual(result.outcome, "partial_failure")
            self.assertEqual([item["status"] for item in result.archive_results], ["succeeded", "failed"])
            self.assertEqual(result.summary["archives_failed"], 1)
            self.assertFalse(first_archive.exists())
            self.assertTrue(second_archive.exists())
            self.assertFalse((second_folder / "unknown").exists())
            self.assertFalse(list(second_folder.glob(".extract-attempt-*")))
            self.assertNotIn("folder-one-secret", json.dumps(result.__dict__, ensure_ascii=False))

    def test_flatten_preview_shows_all_passes_without_mutating_then_apply_runs_that_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "flatten"
            root.mkdir()
            (root / "empty").mkdir()
            (root / "outer" / "inner").mkdir(parents=True)
            (root / "outer" / "inner" / "archive.txt").write_text("nested", encoding="utf-8")
            (root / "multi").mkdir()
            (root / "multi" / "one.txt").write_text("one", encoding="utf-8")
            (root / "multi" / "two.txt").write_text("two", encoding="utf-8")
            (root / "asset.txt").write_text("existing", encoding="utf-8")
            (root / "wrapper").mkdir()
            (root / "wrapper" / "asset.txt").write_text("collision", encoding="utf-8")
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=Path(temp_dir),
            )

            preview = runner.run("flatten", [str(root)], flatten_action="preview")

            self.assertTrue((root / "empty").is_dir())
            self.assertTrue((root / "outer" / "inner" / "archive.txt").is_file())
            self.assertTrue((root / "wrapper" / "asset.txt").is_file())
            plan = preview.details[0]["flatten_preview"]
            self.assertGreaterEqual(len(plan["passes"]), 2)
            actions = [action for batch in plan["passes"] for action in batch["actions"]]
            action_types = {action["type"] for action in actions}
            self.assertTrue({"delete_empty", "move", "skip_multiple"}.issubset(action_types))
            self.assertTrue(any(action.get("destination") == "asset_2.txt" for action in actions))
            self.assertEqual(plan["suffixed"], 1)
            self.assertEqual(preview.summary["moves"], 3)

            applied = runner.run(
                "flatten",
                [str(root)],
                flatten_action="apply",
                flatten_fingerprints={str(root): plan["fingerprint"]},
            )

            self.assertEqual(applied.succeeded, [str(root)])
            self.assertFalse((root / "empty").exists())
            self.assertTrue((root / "archive.txt").is_file())
            self.assertTrue((root / "asset_2.txt").is_file())
            self.assertEqual((root / "asset.txt").read_text(encoding="utf-8"), "existing")
            self.assertTrue((root / "multi").is_dir())

    def test_flatten_merges_existing_destination_and_resolves_collisions_by_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "tickzoo"
            destination = root / "Knottyjess"
            incoming = root / "wrapper" / "Knottyjess"
            destination.mkdir(parents=True)
            incoming.mkdir(parents=True)
            (destination / "same-size.txt").write_bytes(b"old-data")
            (incoming / "same-size.txt").write_bytes(b"new-data")
            (destination / "different-size.txt").write_bytes(b"old")
            (incoming / "different-size.txt").write_bytes(b"new-payload")
            (destination / "destination-only.txt").write_text("keep", encoding="utf-8")
            (incoming / "incoming-only.txt").write_text("add", encoding="utf-8")
            (destination / "nested").mkdir()
            (incoming / "nested").mkdir()
            (destination / "nested" / "same-size.bin").write_bytes(b"old!")
            (incoming / "nested" / "same-size.bin").write_bytes(b"new!")
            (incoming / "nested" / "nested-only.bin").write_bytes(b"nested")
            (incoming / "nested" / "empty").mkdir()
            (root / "empty").mkdir()
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=Path(temp_dir),
            )

            preview = runner.run("flatten", [str(root)], flatten_action="preview")
            plan = preview.details[0]["flatten_preview"]
            merge_actions = [
                action
                for batch in plan["passes"]
                for action in batch["actions"]
                if action["type"] == "merge"
            ]
            self.assertEqual(len(merge_actions), 1)
            self.assertEqual(
                merge_actions[0]["merge_summary"],
                {"added": 2, "replaced": 2, "suffixed": 1, "merged_folders": 1, "deleted": 0},
            )
            self.assertEqual(plan["deleted"], 2)
            self.assertEqual(plan["replaced"], 2)
            self.assertEqual(plan["suffixed"], 1)
            applied = runner.run(
                "flatten",
                [str(root)],
                flatten_action="apply",
                flatten_fingerprints={str(root): plan["fingerprint"]},
            )

            self.assertEqual(applied.succeeded, [str(root)])
            self.assertEqual((destination / "same-size.txt").read_bytes(), b"new-data")
            self.assertEqual((destination / "different-size.txt").read_bytes(), b"old")
            self.assertEqual((destination / "different-size_2.txt").read_bytes(), b"new-payload")
            self.assertEqual((destination / "destination-only.txt").read_text(encoding="utf-8"), "keep")
            self.assertEqual((destination / "incoming-only.txt").read_text(encoding="utf-8"), "add")
            self.assertEqual((destination / "nested" / "same-size.bin").read_bytes(), b"new!")
            self.assertEqual((destination / "nested" / "nested-only.bin").read_bytes(), b"nested")
            self.assertFalse((destination / "nested" / "empty").exists())
            self.assertFalse((root / "wrapper").exists())
            self.assertFalse((root / "empty").exists())

    def test_flatten_collapses_same_named_nested_folder_without_existing_destination_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "tickzoo"
            source = root / "Knottyjess" / "Knottyjess"
            source.mkdir(parents=True)
            (source / "episode.txt").write_text("episode", encoding="utf-8")
            (root / "empty").mkdir()
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=Path(temp_dir),
            )

            preview = runner.run("flatten", [str(root)], flatten_action="preview")
            plan = preview.details[0]["flatten_preview"]
            applied = runner.run(
                "flatten",
                [str(root)],
                flatten_action="apply",
                flatten_fingerprints={str(root): plan["fingerprint"]},
            )

            self.assertEqual(applied.succeeded, [str(root)])
            self.assertTrue((root / "episode.txt").is_file())
            self.assertFalse((root / "Knottyjess").exists())
            self.assertFalse(source.exists())
            self.assertFalse((root / "empty").exists())

    def test_flatten_apply_rejects_entire_batch_when_any_selected_root_is_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first"
            second = Path(temp_dir) / "second"
            first.mkdir()
            second.mkdir()
            (first / "empty").mkdir()
            (second / "empty").mkdir()
            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=Path(temp_dir),
            )
            preview = runner.run("flatten", [str(first), str(second)], flatten_action="preview")
            fingerprints = {
                str(item["folder"]): item["flatten_preview"]["fingerprint"]
                for item in preview.details
            }
            (second / "new.txt").write_text("changed", encoding="utf-8")

            with self.assertRaises(UtilityFlattenPreviewStaleError):
                runner.run(
                    "flatten",
                    [str(first), str(second)],
                    flatten_action="apply",
                    flatten_fingerprints=fingerprints,
                )

            self.assertTrue((first / "empty").is_dir())
            self.assertTrue((second / "empty").is_dir())

    def test_utility_rejects_workspace_symlink_that_resolves_outside(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            link = workspace / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            runner = UtilityRunner(
                Path(__file__).resolve().parents[1] / "utility",
                workspace_root=workspace,
            )
            result = runner.run("compress", [str(link)])

            self.assertFalse(result.succeeded)
            self.assertIn(str(link), result.failed)


if __name__ == "__main__":
    unittest.main()
