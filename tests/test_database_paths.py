from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tme3bot.database_paths import (
    DatabasePaths,
    FilesystemIdentity,
    _mount_point_from_mountinfo,
    set_private_file_creation_umask,
    validate_database_root,
)


class DatabasePathsTests(unittest.TestCase):
    def test_sqlite_and_tdl_paths_are_contained_and_lane_specific(self) -> None:
        paths = DatabasePaths(Path("/database/worker-local"))

        self.assertEqual(
            paths.sqlite("worker-command-journal.sqlite3"),
            Path("/database/worker-local/worker-command-journal.sqlite3"),
        )
        self.assertEqual(
            paths.tdl("Bot 01", "upload"),
            Path("/database/worker-local/tdl/bot-01/upload/.tdl"),
        )
        self.assertNotEqual(paths.tdl("default", "export"), paths.tdl("default", "download"))

    def test_provisioning_and_tdl_staging_paths_use_validated_database_root(self) -> None:
        paths = DatabasePaths(Path("/database/worker-local"))

        self.assertEqual(
            paths.profile_provisioning("stages", "irang", "operation-1"),
            Path("/database/worker-local/profile-provisioning/stages/irang/operation-1"),
        )
        self.assertEqual(
            paths.tdl_profile("irang"),
            Path("/database/worker-local/tdl/irang"),
        )
        self.assertEqual(
            paths.tdl_staging_lane("irang", "upload"),
            Path("/database/worker-local/tdl-staging/irang/upload"),
        )
        with self.assertRaises(ValueError):
            paths.profile_provisioning("stages", "../workspace")

    def test_database_paths_reject_traversal_and_invalid_lane(self) -> None:
        paths = DatabasePaths(Path("/database"))

        for name in ("../outside.sqlite3", "/tmp/outside.sqlite3", "a/../../b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                paths.sqlite(name)
        with self.assertRaises(ValueError):
            paths.tdl("default", "../workspace")

    def test_database_paths_reject_symlink_components_inside_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "database"
            root.mkdir()
            outside = Path(temporary) / "outside"
            outside.mkdir()
            (root / "tdl").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "symlink"):
                DatabasePaths(root).tdl("default", "download")

    @unittest.skipUnless(os.name == "posix", "POSIX file modes only")
    def test_private_file_creation_umask_makes_new_database_files_0600(self) -> None:
        previous = os.umask(0o022)
        try:
            set_private_file_creation_umask()
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "store.sqlite3"
                path.touch()
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        finally:
            os.umask(previous)

    def test_root_database_is_accepted_when_data_is_on_another_filesystem(self) -> None:
        identities = {
            "/": FilesystemIdentity(1, "/"),
            "/srv/tme3bot/db/gateway": FilesystemIdentity(1, "/"),
            "/data": FilesystemIdentity(2, "/data"),
            "/workspace": FilesystemIdentity(3, "/workspace"),
        }

        result = validate_database_root(
            Path("/srv/tme3bot/db/gateway"),
            data_paths=[Path("/data")],
            workspace_paths=[Path("/workspace")],
            filesystem_identity=lambda path: identities[str(path)],
        )

        self.assertTrue(result.physically_isolated)
        self.assertEqual(result.warnings, ())

    def test_database_on_workspace_filesystem_is_rejected(self) -> None:
        identities = {
            "/": FilesystemIdentity(1, "/"),
            "/srv/tme3bot/db/gateway": FilesystemIdentity(3, "/workspace"),
            "/data": FilesystemIdentity(2, "/data"),
            "/workspace": FilesystemIdentity(3, "/workspace"),
        }

        with self.assertRaisesRegex(ValueError, "filesystem root OS"):
            validate_database_root(
                Path("/srv/tme3bot/db/gateway"),
                data_paths=[Path("/data")],
                workspace_paths=[Path("/workspace")],
                filesystem_identity=lambda path: identities[str(path)],
            )

    def test_database_root_rejects_nested_mount_on_same_device(self) -> None:
        identities = {
            "/": FilesystemIdentity(1, "/"),
            "/srv/tme3bot/db/gateway": FilesystemIdentity(1, "/srv/tme3bot/db"),
            "/data": FilesystemIdentity(2, "/data"),
            "/workspace": FilesystemIdentity(3, "/workspace"),
        }

        with self.assertRaisesRegex(ValueError, "mount tersarang"):
            validate_database_root(
                Path("/srv/tme3bot/db/gateway"),
                data_paths=[Path("/data")],
                workspace_paths=[Path("/workspace")],
                filesystem_identity=lambda path: identities[str(path)],
            )

    def test_mountinfo_fallback_selects_nested_mountpoint_and_unescapes_spaces(self) -> None:
        mountinfo = (
            "1 0 8:1 / / rw - ext4 /dev/root rw\n"
            "2 1 8:1 /nested /srv/database\\040ssd rw - ext4 /dev/root rw\n"
        )

        self.assertEqual(
            _mount_point_from_mountinfo(Path("/srv/database ssd/db"), mountinfo),
            "/srv/database ssd",
        )

    def test_single_filesystem_is_allowed_with_warning(self) -> None:
        same = FilesystemIdentity(1, "/")
        result = validate_database_root(
            Path("/srv/tme3bot/db/worker"),
            data_paths=[Path("/data")],
            workspace_paths=[Path("/workspace")],
            filesystem_identity=lambda _path: same,
        )

        self.assertFalse(result.physically_isolated)
        self.assertTrue(result.warnings)

    def test_database_path_with_symlink_component_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real"
            real.mkdir()
            link = root / "linked"
            link.symlink_to(real, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "symlink"):
                validate_database_root(
                    link / "database",
                    data_paths=[],
                    workspace_paths=[],
                    filesystem_identity=lambda _path: FilesystemIdentity(1, "/"),
                )


if __name__ == "__main__":
    unittest.main()
