from __future__ import annotations

import os
import random
import shutil
import subprocess
import tarfile
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
        missing = [name for name in ("7z",) if shutil.which(name) is None]
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
        source = self._payload(folder, "payload.bin", 43)
        archive = folder / "plain.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.write(source, "nested/payload.bin")
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
        self.assertEqual((output / "nested" / "payload.bin").read_bytes(), source.read_bytes())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing output must survive")
        self.assertEqual(outside_sentinel.read_text(encoding="utf-8"), "outside selected workspace")
        self.assertFalse(archive.exists(), "only successful source archives may be deleted")
        self.assertFalse(list(folder.glob(".extract-attempt-*")))

    def test_text_and_url_members_are_excluded_case_insensitively(self) -> None:
        folder = self._selected_folder("exclude-members")
        archive = folder / "members.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr("nested/payload.bin", b"keep this")
            zipped.writestr("nested/readme.txt", b"exclude this")
            zipped.writestr("nested/readme.TXT", b"exclude this too")
            zipped.writestr("nested/link.url", b"exclude this")
            zipped.writestr("nested/link.URL", b"exclude this too")

        result = self._extract(folder)

        item = self._assert_success(result, archive.name, folder)
        output = Path(str(item["output"]))
        self.assertEqual(
            sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()),
            ["nested/payload.bin"],
        )

    def test_tgz_extracts_tar_members_without_intermediate_tar_file(self) -> None:
        folder = self._selected_folder("tgz")
        source = self._payload(folder, "payload.bin", 43)
        excluded_text = self._payload(folder, "readme.txt", 17)
        excluded_url = self._payload(folder, "link.url", 19)
        archive = folder / "bundle.tgz"
        with tarfile.open(archive, "w:gz") as compressed_tar:
            compressed_tar.add(source, arcname="nested/payload.bin")
            compressed_tar.add(excluded_text, arcname="nested/readme.txt")
            compressed_tar.add(excluded_url, arcname="nested/link.url")

        result = self._extract(folder)

        item = self._assert_success(result, archive.name, folder)
        output = Path(str(item["output"]))
        self.assertEqual(output.name, "bundle")
        self.assertEqual((output / "nested" / "payload.bin").read_bytes(), source.read_bytes())
        self.assertFalse((output / "nested" / "readme.txt").exists())
        self.assertFalse((output / "nested" / "link.url").exists())
        self.assertFalse((output / "bundle.tar").exists())
        self.assertFalse(archive.exists())

    def test_extractor_writes_directly_to_final_output_directory(self) -> None:
        folder = self._selected_folder("direct-output")
        archive = folder / "direct.zip"
        archive.write_bytes(b"fake archive handled by fake 7z")
        fake_bin = self.temp_root / "fake-bin"
        fake_bin.mkdir()
        output_record = self.temp_root / "7z-output-path.txt"
        fake_7z = fake_bin / "7z"
        fake_7z.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, sys\n"
            "output = pathlib.Path(next(arg[2:] for arg in sys.argv if arg.startswith('-o')))\n"
            "output.mkdir(parents=True, exist_ok=True)\n"
            "(output / 'payload.bin').write_bytes(b'direct output')\n"
            "pathlib.Path(os.environ['TME3_TEST_7Z_OUTPUT']).write_text(str(output))\n"
            "print('- payload.bin')\n",
            encoding="utf-8",
        )
        fake_7z.chmod(0o755)
        old_path = os.environ.get("PATH", "")
        old_record = os.environ.get("TME3_TEST_7Z_OUTPUT")
        os.environ["PATH"] = f"{fake_bin}{os.pathsep}{old_path}"
        os.environ["TME3_TEST_7Z_OUTPUT"] = str(output_record)
        try:
            result = self._extract(folder)
        finally:
            os.environ["PATH"] = old_path
            if old_record is None:
                os.environ.pop("TME3_TEST_7Z_OUTPUT", None)
            else:
                os.environ["TME3_TEST_7Z_OUTPUT"] = old_record

        item = self._assert_success(result, archive.name, folder)
        final_output = Path(str(item["output"])).resolve()
        extractor_output = Path(output_record.read_text(encoding="utf-8")).resolve()
        self.assertEqual(extractor_output, final_output)
        self.assertEqual(extractor_output.parent, folder.resolve())
        self.assertFalse(list(folder.glob(".extract-attempt-*")))
        self.assertFalse(list(folder.glob(".extract-merge-*.tmp")))

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

    def test_rar3_fixture_extracts_with_7z(self) -> None:
        folder = self._selected_folder("rar3")
        fixture = self.archive_fixture_root / "rar3-sample.rar"
        archive = folder / fixture.name
        shutil.copy2(fixture, archive)

        result = self._extract(folder)

        item = self._assert_success(result, archive.name, folder)
        output = Path(str(item["output"]))
        self.assertEqual((output / "testfile.jpg").stat().st_size, 220)
        self.assertEqual((output / "testfile.png").stat().st_size, 87)
        self.assertFalse(archive.exists())
        self.assertFalse(list(folder.glob(".extract-attempt-*")))

    def test_archive_path_traversal_cannot_write_outside_selected_folder(self) -> None:
        folder = self._selected_folder("path-boundary")
        archive = folder / "traversal.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr("../../../../escaped.bin", "must stay in the temporary test tree")
            zipped.writestr("safe/payload.bin", "inside archive")
        outside_target = self.temp_root / "escaped.bin"

        result = self._extract(folder)

        self.assertFalse(outside_target.exists(), "archive members must not escape the chosen folder")
        if result.outcome == "succeeded":
            item = self._assert_success(result, archive.name, folder)
            self.assertFalse(archive.exists())
            output = Path(str(item["output"]))
            self.assertEqual((output / "safe" / "payload.bin").read_text(encoding="utf-8"), "inside archive")
        else:
            self.assertTrue(archive.is_file(), "a rejected archive must remain available")
        self.assertFalse(list(folder.glob(".extract-attempt-*")))

    def test_password_pool_retries_an_earlier_archive_after_later_candidate_is_discovered(self) -> None:
        selected = self._selected_folder("password-pool")
        seed_folder = selected / "seed-folder"
        later_folder = selected / "later-folder"
        seed_folder.mkdir()
        later_folder.mkdir()
        seed_source = self._payload(seed_folder, "seed.bin")
        later_source = self._payload(later_folder, "later.bin")
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

    def test_failed_encrypted_and_corrupt_archives_are_retained_without_temp_outputs(self) -> None:
        folder = self._selected_folder("failed-archives")
        source = self._payload(folder, "private.bin")
        encrypted = folder / "encrypted.zip"
        self._make_7z(
            folder, encrypted, source, password="actual-secret", archive_type="zip"
        )
        corrupted = folder / "corrupted.zip"
        corrupted.write_bytes(b"not a zip or 7z archive")
        (folder / ".pass").write_text("wrong-pass-file", encoding="utf-8")
        rar_folder = folder / "corrupt-rar"
        rar_folder.mkdir()
        corrupted_rar = rar_folder / "corrupted.rar"
        corrupted_rar.write_bytes(b"not a rar archive")

        result = self._extract(folder, password="wrong-form-password")

        self.assertEqual(result.outcome, "failed")
        self.assertEqual(result.summary["archives_failed"], 3)
        self.assertTrue(encrypted.is_file(), "failed encrypted source must remain available")
        self.assertTrue(corrupted.is_file(), "corrupt source must remain available")
        self.assertTrue(corrupted_rar.is_file(), "corrupt RAR source must remain available")
        self.assertFalse((folder / "encrypted").exists())
        self.assertFalse((folder / "corrupted").exists())
        self.assertFalse((rar_folder / "corrupted").exists())
        self.assertFalse(list(folder.glob(".extract-attempt-*")))
        self.assertFalse(list(rar_folder.glob(".extract-attempt-*")))
        self.assertFalse(list(folder.glob(".extract-merge-*.tmp")))
        self.assertFalse(list(rar_folder.glob(".extract-merge-*.tmp")))
        self.assertTrue(all(item["cleanup_status"] == "retained_failed" for item in result.archive_results))

    def test_archive_with_one_successful_member_is_successful_and_keeps_only_that_file(self) -> None:
        folder = self._selected_folder("mixed-result")
        good_source = self._payload(folder, "good.bin", 31)
        secret_source = self._payload(folder, "secret.bin", 47)
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

    def test_partial_extract_preserves_successful_empty_members(self) -> None:
        folder = self._selected_folder("mixed-empty-result")
        empty_source = folder / "empty.bin"
        empty_source.touch()
        secret_source = self._payload(folder, "secret.bin", 47)
        archive = folder / "mixed-empty.zip"
        self._run_archive_builder(
            ["7z", "a", "-y", "-bso0", "-bsp0", "-tzip", str(archive), empty_source.name],
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
        output = Path(str(item["output"]))
        self.assertTrue((output / empty_source.name).is_file())
        self.assertEqual((output / empty_source.name).stat().st_size, 0)
        self.assertFalse((output / secret_source.name).exists())
        self.assertTrue(archive.is_file())
        self.assertFalse(list(folder.glob(".extract-attempt-*")))

    def test_partial_archive_retries_with_password_found_in_later_archive(self) -> None:
        folder = self._selected_folder("late-password-pool")
        first_folder = folder / "A"
        later_folder = folder / "B"
        first_folder.mkdir()
        later_folder.mkdir()
        plain_source = self._payload(first_folder, "plain.bin", 31)
        secret_source = self._payload(first_folder, "secret.bin", 47)
        first_archive = first_folder / "first.zip"
        self._run_archive_builder(
            ["7z", "a", "-y", "-bso0", "-bsp0", "-tzip", str(first_archive), plain_source.name],
            first_folder,
        )
        self._run_archive_builder(
            [
                "7z", "a", "-y", "-bso0", "-bsp0", "-tzip", "-pactual-secret",
                str(first_archive), secret_source.name,
            ],
            first_folder,
        )

        later_source = self._payload(later_folder, "later.bin", 19)
        later_archive = later_folder / "second.zip"
        self._run_archive_builder(
            ["7z", "a", "-y", "-bso0", "-bsp0", "-tzip", str(later_archive), later_source.name],
            later_folder,
        )
        (later_folder / ".pass").write_text("actual-secret", encoding="utf-8")

        result = self._extract(folder)

        first = self._assert_success(result, first_archive.name, first_folder)
        self.assertEqual(first["pass"], "retry")
        self.assertFalse(first["partial"])
        self.assertEqual(first["files_extracted"], 2)
        first_output = Path(str(first["output"]))
        self.assertEqual((first_output / plain_source.name).read_bytes(), plain_source.read_bytes())
        self.assertEqual((first_output / secret_source.name).read_bytes(), secret_source.read_bytes())
        self.assertEqual(
            [path.name for path in first_folder.iterdir() if path.is_dir()],
            [first_output.name],
        )
        self.assertFalse(first_archive.exists())
        self.assertFalse(later_archive.exists())

    def test_partial_results_from_distinct_passwords_are_combined(self) -> None:
        folder = self._selected_folder("combine-partial-passwords")
        first_folder = folder / "A"
        later_folder = folder / "B"
        first_folder.mkdir()
        later_folder.mkdir()

        first_source = self._payload(first_folder, "first.bin", 31)
        second_source = self._payload(first_folder, "second.bin", 47)
        first_archive = first_folder / "first.zip"
        self._run_archive_builder(
            [
                "7z", "a", "-y", "-bso0", "-bsp0", "-tzip", "-pfirst-secret",
                str(first_archive), first_source.name,
            ],
            first_folder,
        )
        self._run_archive_builder(
            [
                "7z", "a", "-y", "-bso0", "-bsp0", "-tzip", "-psecond-secret",
                str(first_archive), second_source.name,
            ],
            first_folder,
        )
        (first_folder / ".pass").write_text("first-secret", encoding="utf-8")

        later_source = self._payload(later_folder, "later.bin", 19)
        later_archive = later_folder / "second.zip"
        self._run_archive_builder(
            ["7z", "a", "-y", "-bso0", "-bsp0", "-tzip", str(later_archive), later_source.name],
            later_folder,
        )
        (later_folder / ".pass").write_text("second-secret", encoding="utf-8")

        result = self._extract(folder)

        first = self._assert_success(result, first_archive.name, first_folder)
        self.assertEqual(first["pass"], "retry")
        self.assertFalse(first["partial"])
        self.assertEqual(first["files_extracted"], 2)
        output = Path(str(first["output"]))
        self.assertEqual((output / first_source.name).read_bytes(), first_source.read_bytes())
        self.assertEqual((output / second_source.name).read_bytes(), second_source.read_bytes())
        self.assertFalse(first_archive.exists())
        self.assertEqual(
            [path.name for path in first_folder.iterdir() if path.is_dir()],
            [output.name],
        )

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
