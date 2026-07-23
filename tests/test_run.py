import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

import run


class RunScriptTests(unittest.TestCase):
    def test_cleanup_prunes_only_dangling_images(self) -> None:
        env = {"DOCKER_CMD": "docker"}
        with (
            patch.object(run.sys, "argv", ["run.py", "cleanup"]),
            patch.object(run, "load_env_file", return_value=env),
            patch.object(run, "run_docker") as run_docker,
        ):
            self.assertEqual(run.main(), 0)

        run_docker.assert_called_once_with(["image", "prune", "--force"], env)

    def test_run_docker_supports_custom_command(self) -> None:
        env = {"DOCKER_CMD": "sudo docker"}
        with patch.object(run.subprocess, "run") as subprocess_run:
            run.run_docker(["image", "prune", "--force"], env)

        subprocess_run.assert_called_once_with(
            ["sudo", "docker", "image", "prune", "--force"],
            cwd=run.PROJECT_DIR,
            env=run.compose_env(env),
            check=True,
        )

    def test_update_reuses_cache_and_prepares_host_tdl(self) -> None:
        env = {"PROFILE_ROOT": "/srv/bot"}
        with (
            patch.object(run.sys, "argv", ["run.py", "update"]),
            patch.object(run, "load_env_file", return_value=env),
            patch.object(run, "ensure_profile_root"),
            patch.object(run, "prepare_tdl_build_asset") as prepare_tdl,
            patch.object(run, "run_compose") as run_compose,
        ):
            self.assertEqual(run.main(), 0)

        prepare_tdl.assert_called_once_with(env)
        self.assertEqual(
            run_compose.call_args_list,
            [
                call(["build"], env),
                call(["up", "-d", "--remove-orphans"], env),
                call(["ps"], env),
            ],
        )

    def test_prepare_tdl_build_asset_copies_configured_linux_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            host_tdl = project / "host-tdl"
            host_tdl.write_bytes(b"host tdl")

            with (
                patch.object(run, "PROJECT_DIR", project),
                patch.object(run.sys, "platform", "linux"),
                patch("builtins.print"),
            ):
                source = run.prepare_tdl_build_asset(
                    {"TDL_HOST_BINARY": str(host_tdl)}
                )

            self.assertEqual(source, host_tdl.resolve())
            self.assertEqual(
                (project / ".docker" / "tdl" / "tdl").read_bytes(), b"host tdl"
            )

    def test_prepare_tdl_build_asset_removes_stale_copy_when_host_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            staged = project / ".docker" / "tdl" / "tdl"
            staged.parent.mkdir(parents=True)
            staged.write_bytes(b"stale")

            with (
                patch.object(run, "PROJECT_DIR", project),
                patch.object(run.sys, "platform", "linux"),
                patch("builtins.print"),
            ):
                source = run.prepare_tdl_build_asset(
                    {"TDL_HOST_BINARY": str(project / "missing-tdl")}
                )

            self.assertIsNone(source)
            self.assertFalse(staged.exists())

    def test_parse_env_line_supports_export_quotes_and_comments(self) -> None:
        self.assertEqual(
            run.parse_env_line('export PROFILE_ROOT = "/srv/bot 01"'),
            ("PROFILE_ROOT", "/srv/bot 01"),
        )
        self.assertEqual(
            run.parse_env_line("LOG_LEVEL=DEBUG # local"), ("LOG_LEVEL", "DEBUG")
        )
        self.assertIsNone(run.parse_env_line("# comment"))
        self.assertIsNone(run.parse_env_line("invalid key=value"))

    def test_map_data_path_keeps_mounts_inside_profile_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            self.assertEqual(run.map_data_path(root, "/data"), root)
            self.assertEqual(
                run.map_data_path(root, "/data/profiles/demo"),
                root / "profiles" / "demo",
            )
            self.assertIsNone(run.map_data_path(root, "/outside/data"))


if __name__ == "__main__":
    unittest.main()
