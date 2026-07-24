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

    def test_worker_registry_can_be_managed_from_run_script(self) -> None:
        env = {"MANAGEMENT_API_TOKEN": "management"}
        workers = {}

        def api(_env, method, path, payload=None):
            if method == "POST":
                workers[payload["name"]] = payload
                return {"name": payload["name"]}
            if method == "DELETE":
                return {"removed": workers.pop(path.rsplit("/", 1)[1], None) is not None}
            return {"items": list(workers.values())}

        with patch.object(run, "backend_management_request", side_effect=api):
            run.manage_workers(env, ["add", "remote-1", "https://worker.example", "secret"])
            run.manage_workers(env, ["add", "remote-2", "https://worker-2.example", "secret-2"])
            self.assertEqual(sorted(workers), ["remote-1", "remote-2"])
            run.manage_workers(env, ["remove", "remote-1"])
            self.assertEqual(sorted(workers), ["remote-2"])

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

    def test_run_compose_accepts_compose_file_from_dotenv(self) -> None:
        env = {"COMPOSE_FILE": "docker-compose.gateway.yml", "COMPOSE_CMD": "docker compose"}
        with patch.object(run.subprocess, "run") as subprocess_run:
            run.run_compose(["ps"], env)

        self.assertEqual(subprocess_run.call_args.args[0], [
            "docker", "compose", "-f", "docker-compose.gateway.yml", "ps"
        ])

    def test_migrate_builds_both_compose_files_and_saves_images(self) -> None:
        env = {}

        def fake_docker(args, _env):
            if args[:2] == ["save", "-o"]:
                Path(args[2]).write_bytes(b"docker images")

        def fake_archive(output, _image_tar):
            output.write_bytes(b"migration archive")
            return 10, output.stat().st_size

        with (
            patch.object(run, "require_env_file"),
            patch.object(run, "prepare_tdl_build_asset"),
            patch.object(run, "run_compose") as run_compose,
            patch.object(run, "capture_compose", side_effect=["gateway-image\nworker-image\n", "worker-image\n"]),
            patch.object(run, "run_docker", side_effect=fake_docker) as run_docker,
            patch.object(run, "build_migration_archive", side_effect=fake_archive),
        ):
            output = run.migrate_images(env)

        self.assertEqual(output, run.PROJECT_DIR / "migrate.zip")
        self.assertEqual(run_compose.call_count, 2)
        worker_build_env = run_compose.call_args_list[1].args[1]
        self.assertEqual(
            worker_build_env["PROFILE_ROOT"], "/tmp/tme3bot-worker-build"
        )
        run_docker.assert_called_once()
        self.assertEqual(run_docker.call_args.args[0][:2], ["save", "-o"])

    def test_build_base_builds_and_exports_only_the_base_image(self) -> None:
        env = {"BASE_PLATFORM": "linux/amd64", "TME3BOT_BASE_IMAGE": "base:test"}
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)

            def fake_docker(args, _env):
                if args[0] == "save":
                    Path(args[2]).write_bytes(b"base image")

            with (
                patch.object(run, "PROJECT_DIR", project),
                patch.object(run, "prepare_tdl_build_asset"),
                patch.object(run, "run_docker", side_effect=fake_docker) as run_docker,
                patch.object(run, "build_base_archive", return_value=(4, 8)),
            ):
                output = run.build_base_image(env)

            self.assertEqual(output, project / "base-migrate.zip")
            self.assertEqual(run_docker.call_count, 2)
            self.assertEqual(
                run_docker.call_args_list[0].args[0][:6],
                ["build", "--platform", "linux/amd64", "-f", "Dockerfile.base", "-t"],
            )
            self.assertEqual(run_docker.call_args_list[1].args[0][:2], ["save", "-o"])

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

    def test_gateway_uses_local_worker_data_root_and_split_service_names(self):
        env = {
            "COMPOSE_FILE": "docker-compose.gateway.yml",
            "LOCAL_WORKER_DATA_ROOT": "/srv/worker-local",
        }
        self.assertEqual(run.data_root_value(env), "/srv/worker-local")
        self.assertEqual(run.worker_service(env), "worker-local")
        self.assertEqual(run.shell_service(env), "backend")

        remote = {
            "COMPOSE_FILE": "docker-compose.worker.yml",
            "PROFILE_ROOT": "/srv/remote",
        }
        self.assertEqual(run.worker_service(remote), "worker")
        self.assertEqual(run.shell_service(remote), "worker")

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
