from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tme3bot.utility import UtilityFlattenPreviewStaleError, UtilityRunner


class UtilityFeatureTests(unittest.TestCase):
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
            self.assertTrue(any(action.get("destination") == "dup_wrapper_asset.txt" for action in actions))
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
            self.assertTrue((root / "dup_wrapper_asset.txt").is_file())
            self.assertEqual((root / "asset.txt").read_text(encoding="utf-8"), "existing")
            self.assertTrue((root / "multi").is_dir())

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
