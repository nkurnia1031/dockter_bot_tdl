from __future__ import annotations

import os
import random
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from tme3bot.utility import UtilityRunner


RUN_EXTRACT_E2E = os.getenv("TME3_RUN_UTILITY_EXTRACT_E2E") == "1"


@unittest.skipUnless(
    RUN_EXTRACT_E2E,
    "real archive-tool E2E runs in the dedicated GitHub Actions job",
)
class UtilityExtractE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        missing = [name for name in ("7z", "unar") if shutil.which(name) is None]
        if missing:
            raise unittest.SkipTest(f"archive tools unavailable: {', '.join(missing)}")
        repo_root = Path(__file__).resolve().parents[1]
        cls.utility_root = repo_root / "utility"
        cls.archive_fixture_root = repo_root / "tests" / "fixtures" / "utility_extract"

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="tme3bot-extract-e2e-", dir=tempfile.gettempdir()
        )
        self.temp_root = Path(self._temporary.name).resolve()
        self.workspace = self.temp_root / "workspace"
        self.workspace.mkdir()
        self.progress: list[dict[str, object]] = []
        self.logs: list[str] = []
        self.runner = UtilityRunner(
            self.utility_root,
            workspace_root=self.workspace,
            progress_callback=self.progress.append,
            log_callback=self.logs.append,
            stall_timeout_seconds=120,
        )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _selected_folder(self, name: str = "selected") -> Path:
        folder = self.workspace / name
        folder.mkdir(parents=True, exist_ok=True)
        self.assertTrue(folder.resolve().is_relative_to(self.workspace.resolve()))
        return folder

    def _payload(self, folder: Path, name: str = "payload.bin", size: int = 257) -> Path:
        path = folder / name
        path.write_bytes(bytes((index * 37 + 13) % 256 for index in range(size)))
        return path

    def _large_payload(self, folder: Path, name: str = "large.bin", size: int = 96 * 1024) -> Path:
        generator = random.Random(20261114)
        path = folder / name
        path.write_bytes(generator.randbytes(size))
        return path

    def _make_7z(
        self,
        folder: Path,
        archive: Path,
        source: Path,
        *,
        password: str | None = None,
        archive_type: str | None = None,
        volume_size: str | None = None,
        encrypt_headers: bool = False,
    ) -> None:
        command = ["7z", "a", "-y", "-bso0", "-bsp0"]
        if archive_type:
            command.append(f"-t{archive_type}")
        if password is not None:
            command.append(f"-p{password}")
        if encrypt_headers:
            command.append("-mhe=on")
        if volume_size:
            command.append(f"-v{volume_size}")
        command.extend([str(archive), source.name])
        self._run_archive_builder(command, folder)

    def _run_archive_builder(self, command: list[str], cwd: Path) -> None:
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"archive fixture creation failed (exit {completed.returncode}): {completed.stdout}",
        )

    def _extract(self, folder: Path, password: str | None = None):
        kwargs = {} if password is None else {"password": password}
        return self.runner.run("extract", [str(folder)], **kwargs)

    def _assert_success(
        self, result, archive_name: str, expected_parent: Path
    ) -> dict[str, object]:
        self.assertEqual(result.outcome, "succeeded", result.archive_results)
        item = next(item for item in result.archive_results if item["name"] == archive_name)
        self.assertEqual(item["status"], "succeeded")
        output = Path(str(item["output"])).resolve()
        expected_parent = expected_parent.resolve()
        self.assertTrue(
            output.is_relative_to(expected_parent),
            f"output escaped selected folder {expected_parent}: {output}",
        )
        self.assertTrue(output.is_dir())
        return item

    def test_plain_zip_ignores_wrong_password_and_uses_a_unique_output_inside_workspace(self) -> None:
        folder = self._selected_folder("no-password")
        source = self._payload(folder, "payload.txt", 43)
        archive = folder / "plain.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.write(source, "nested/payload.txt")
        (folder / ".pass").write_text("wrong-pass-file\n", encoding="utf-8")

        existing = folder / "plain"
        existing.mkdir()
        sentinel = existing / "keep.txt"
        sentinel.write_text("existing output must survive", encoding="utf-8")
        outside_sentinel = self.temp_root / "outside.txt"
        outside_sentinel.write_text("outside selected workspace", encoding="utf-8")

        result = self._extract(folder, password="wrong-form-password")

        item = self._assert_success(result, archive.name, folder)
        output = Path(str(item["output"]))
        self.assertEqual(output.name, "plain_2")
        self.assertEqual((output / "nested" / "payload.txt").read_bytes(), source.read_bytes())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing output must survive")
        self.assertEqual(outside_sentinel.read_text(encoding="utf-8"), "outside selected workspace")
        self.assertFalse(archive.exists(), "only successful source archives may be deleted")
        self.assertFalse(list(folder.glob(".extract-attempt-*")))

    def test_password_from_utility_form_unlocks_encrypted_7z(self) -> None:
        folder = self._selected_folder("form-password")
        source = self._payload(folder)
        archive = folder / "form.7z"
        self._make_7z(
            folder, archive, source, password="form-secret", encrypt_headers=True
        )

        result = self._extract(folder, password="form-secret")

        item = self._assert_success(result, archive.name, folder)
        self.assertEqual((Path(str(item["output"])) / source.name).read_bytes(), source.read_bytes())
        self.assertFalse(archive.exists())

    def test_parent_folder_name_unlocks_encrypted_zip(self) -> None:
        folder = self._selected_folder("folder-secret")
        source = self._payload(folder)
        archive = folder / "folder.zip"
        self._make_7z(
            folder,
            archive,
            source,
            password=folder.name,
            archive_type="zip",
        )

        result = self._extract(folder)

        item = self._assert_success(result, archive.name, folder)
        self.assertEqual((Path(str(item["output"])) / source.name).read_bytes(), source.read_bytes())
        self.assertFalse(archive.exists())

    def test_pass_file_unlocks_encrypted_rar_and_removes_all_parts_after_success(self) -> None:
        folder = self._selected_folder("rar-pass-file")
        source = self._large_payload(folder, size=64 * 1024)
        fixture_parts = sorted(self.archive_fixture_root.glob("multipart.part*.rar"))
        self.assertGreater(len(fixture_parts), 1, "committed fixture must contain multiple RAR volumes")
        parts: set[Path] = set()
        for fixture in fixture_parts:
            target = folder / fixture.name
            shutil.copy2(fixture, target)
            parts.add(target)
        (folder / ".pass").write_text("pass-file-secret\n", encoding="utf-8")
        main_part = folder / "multipart.part1.rar"
        self.assertTrue(main_part.is_file())

        result = self._extract(folder)

        item = self._assert_success(result, main_part.name, folder)
        output = Path(str(item["output"]))
        self.assertEqual((output / source.name).read_bytes(), source.read_bytes())
        self.assertTrue(parts.isdisjoint(set(folder.iterdir())))
        self.assertFalse(list(folder.glob(".extract-attempt-*")))

    def test_archive_path_traversal_cannot_write_outside_selected_folder(self) -> None:
        folder = self._selected_folder("path-boundary")
        archive = folder / "traversal.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr("../../../../escaped.txt", "must stay in the temporary test tree")
            zipped.writestr("safe/payload.txt", "inside archive")
        outside_target = self.temp_root / "escaped.txt"

        result = self._extract(folder)

        self.assertFalse(outside_target.exists(), "archive members must not escape the chosen folder")
        if result.outcome == "succeeded":
            item = self._assert_success(result, archive.name, folder)
            self.assertFalse(archive.exists())
            output = Path(str(item["output"]))
            self.assertEqual((output / "safe" / "payload.txt").read_text(encoding="utf-8"), "inside archive")
        else:
            self.assertTrue(archive.is_file(), "a rejected archive must remain available")
        self.assertFalse(list(folder.glob(".extract-attempt-*")))

    def test_password_pool_retries_an_earlier_archive_after_later_candidate_is_discovered(self) -> None:
        selected = self._selected_folder("password-pool")
        seed_folder = selected / "seed-folder"
        later_folder = selected / "later-folder"
        seed_folder.mkdir()
        later_folder.mkdir()
        seed_source = self._payload(seed_folder, "seed.txt")
        later_source = self._payload(later_folder, "later.txt")
        seed_archive = seed_folder / "seed.7z"
        later_archive = later_folder / "later.zip"
        self._make_7z(seed_folder, seed_archive, seed_source, password="shared-secret")
        self._make_7z(
            later_folder,
            later_archive,
            later_source,
            password="shared-secret",
            archive_type="zip",
        )
        (seed_folder / ".pass").write_text("shared-secret", encoding="utf-8")

        result = self._extract(selected)

        self.assertEqual(result.outcome, "succeeded", result.archive_results)
        by_name = {item["name"]: item for item in result.archive_results}
        self.assertEqual(by_name[seed_archive.name]["pass"], "first")
        self.assertEqual(by_name[later_archive.name]["pass"], "retry")
        later_output = Path(str(by_name[later_archive.name]["output"]))
        self.assertTrue(later_output.is_relative_to(later_folder.resolve()))
        self.assertEqual((later_output / later_source.name).read_bytes(), later_source.read_bytes())
        self.assertFalse(seed_archive.exists())
        self.assertFalse(later_archive.exists())

    def test_failed_encrypted_and_corrupt_archives_are_retained_and_staging_is_removed(self) -> None:
        folder = self._selected_folder("failed-archives")
        source = self._payload(folder, "private.txt")
        encrypted = folder / "encrypted.zip"
        self._make_7z(
            folder, encrypted, source, password="actual-secret", archive_type="zip"
        )
        corrupted = folder / "corrupted.zip"
        corrupted.write_bytes(b"not a zip or 7z archive")
        (folder / ".pass").write_text("wrong-pass-file", encoding="utf-8")
        multipart_folder = folder / "multipart-failure"
        multipart_folder.mkdir()
        fixture_parts = sorted(self.archive_fixture_root.glob("multipart.part*.rar"))
        for fixture in fixture_parts:
            shutil.copy2(fixture, multipart_folder / fixture.name)
        (multipart_folder / ".pass").write_text("wrong-multipart-password", encoding="utf-8")

        result = self._extract(folder, password="wrong-form-password")

        self.assertEqual(result.outcome, "failed")
        self.assertEqual(result.summary["archives_failed"], 3)
        self.assertTrue(encrypted.is_file(), "failed encrypted source must remain available")
        self.assertTrue(corrupted.is_file(), "corrupt source must remain available")
        self.assertTrue(
            all((multipart_folder / part.name).is_file() for part in fixture_parts),
            "failed multipart source parts must remain available",
        )
        self.assertFalse((folder / "encrypted").exists())
        self.assertFalse((folder / "corrupted").exists())
        self.assertFalse((multipart_folder / "multipart").exists())
        self.assertFalse(list(folder.glob(".extract-attempt-*")))
        self.assertFalse(list(multipart_folder.glob(".extract-attempt-*")))
        self.assertTrue(all(item["cleanup_status"] == "retained_failed" for item in result.archive_results))

    def test_archive_with_one_successful_member_is_successful_and_keeps_only_that_file(self) -> None:
        folder = self._selected_folder("mixed-result")
        good_source = self._payload(folder, "good.txt", 31)
        secret_source = self._payload(folder, "secret.txt", 47)
        archive = folder / "mixed.zip"
        self._run_archive_builder(
            ["7z", "a", "-y", "-bso0", "-bsp0", "-tzip", str(archive), good_source.name],
            folder,
        )
        self._run_archive_builder(
            [
                "7z", "a", "-y", "-bso0", "-bsp0", "-tzip", "-pactual-secret",
                str(archive), secret_source.name,
            ],
            folder,
        )

        result = self._extract(folder, password="wrong-test-password")

        self.assertEqual(result.outcome, "succeeded", result.archive_results)
        item = self._assert_success(result, archive.name, folder)
        self.assertTrue(item["partial"])
        self.assertEqual(item["files_extracted"], 1)
        self.assertEqual(item["failed_files"], 1)
        self.assertEqual(item["cleanup_status"], "retained_partial")
        self.assertTrue(archive.is_file(), "partial archives remain available for recovery")
        output = Path(str(item["output"]))
        self.assertEqual((output / good_source.name).read_bytes(), good_source.read_bytes())
        self.assertFalse((output / secret_source.name).exists())
        self.assertFalse(list(folder.glob(".extract-attempt-*")))

    def test_split_7z_is_detected_as_one_archive_and_all_parts_are_deleted_only_after_success(self) -> None:
        folder = self._selected_folder("split-7z")
        source = self._large_payload(folder)
        archive_base = folder / "split.7z"
        self._make_7z(folder, archive_base, source, volume_size="16k")
        parts = sorted(folder.glob("split.7z.[0-9][0-9][0-9]"))
        self.assertGreater(len(parts), 1, "fixture must be a real multi-volume 7z")

        result = self._extract(folder)

        item = self._assert_success(result, parts[0].name, folder)
        output = Path(str(item["output"]))
        self.assertEqual((output / source.name).read_bytes(), source.read_bytes())
        self.assertTrue(all(not part.exists() for part in parts))


if __name__ == "__main__":
    unittest.main()
