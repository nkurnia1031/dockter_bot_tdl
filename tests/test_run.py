import tempfile
import sqlite3
import unittest
import subprocess
from pathlib import Path
from unittest.mock import call, patch

import run
from tme3bot.database_paths import FilesystemIdentity


class RunScriptTests(unittest.TestCase):
    def test_bootstrap_retries_over_debian_packages_without_uninstall(self) -> None:
        with (
            patch.object(run, "_python_requirements_ready", return_value=False),
            patch.object(run, "_system_python_install_fallback_available", return_value=True),
            patch.object(run, "_pip_supports_flag", return_value=True),
            patch.object(
                run.subprocess,
                "run",
                side_effect=[
                    None,
                    subprocess.CalledProcessError(1, ["pip", "install"]),
                    None,
                ],
            ) as subprocess_run,
        ):
            run.bootstrap_python_dependencies({}, install=True)

        fallback_command = subprocess_run.call_args_list[2].args[0]
        self.assertIn("--ignore-installed", fallback_command)
        self.assertIn("--break-system-packages", fallback_command)

    def test_release_image_tag_uses_immutable_git_revision_when_latest(self) -> None:
        with patch.object(run.subprocess, "check_output", return_value="abc123def456\n"):
            self.assertEqual(run.release_image_tag({"IMAGE_TAG": "latest"}), "abc123def456")
        self.assertEqual(run.release_image_tag({"IMAGE_TAG": "release-7"}), "release-7")

    def test_preflight_image_names_have_safe_defaults_and_check_git_tag(self) -> None:
        self.assertEqual(
            run.image_names_for_release({}),
            ["tme3bot-gateway", "tme3bot-worker"],
        )
        with patch.object(run, "docker_image_exists", return_value=True) as inspect:
            self.assertEqual(
                run.image_release_status("ghcr.io/example/gateway", "abc123", {}),
                "READY_LOCAL",
            )
        inspect.assert_called_once_with("ghcr.io/example/gateway:abc123", {})

    def test_gateway_data_root_is_accepted_by_preflight_helpers(self) -> None:
        self.assertEqual(run.data_root_value({"GATEWAY_DATA_ROOT": "/srv/gateway"}), "/srv/gateway")

    def test_database_root_preflight_requires_os_filesystem_when_data_is_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "database"
            data = root / "data"
            workspace = root / "workspace"
            identities = {
                "/": FilesystemIdentity(1, "/"),
                str(database): FilesystemIdentity(2, "/workspace"),
                str(data): FilesystemIdentity(3, "/data"),
                str(workspace): FilesystemIdentity(2, "/workspace"),
            }
            env = {
                "DATABASE_ROOT": str(database),
                "GATEWAY_DATA_ROOT": str(data),
                "LOCAL_WORKER_DATA_ROOT": str(root / "worker-data"),
                "UTILITY_WORKSPACE_HOST": str(workspace),
            }

            with patch.object(
                run,
                "filesystem_identity",
                side_effect=lambda path: identities[str(path)],
            ):
                with self.assertRaisesRegex(RuntimeError, "filesystem root OS"):
                    run.ensure_database_root(env, role="gateway")

            self.assertFalse(database.exists())

    def test_database_root_preflight_creates_private_root_and_redis_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "database"
            data = root / "data"
            workspace = root / "workspace"
            for path in (data, workspace):
                path.mkdir()
            env = {
                "DATABASE_ROOT": str(database),
                "PROFILE_ROOT": str(data),
                "UTILITY_WORKSPACE_HOST": str(workspace),
            }

            with (
                patch.object(
                    run,
                    "filesystem_identity",
                    return_value=FilesystemIdentity(1, "/"),
                ),
                patch.object(run.os, "chown") as chown,
            ):
                resolved = run.ensure_database_root(env, role="gateway")

            self.assertEqual(resolved, database)
            self.assertTrue((database / "redis").is_dir())
            if run.os.name == "posix":
                self.assertEqual(database.stat().st_mode & 0o777, 0o700)
                self.assertEqual((database / "redis").stat().st_mode & 0o777, 0o700)
                chown.assert_called_once_with(database / "redis", 999, 1000)

    def test_worker_database_preflight_does_not_create_gateway_redis_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "database"
            env = {
                "DATABASE_ROOT": str(database),
                "PROFILE_ROOT": str(root / "profile-data"),
                "UTILITY_WORKSPACE_HOST": str(root / "workspace"),
            }
            with patch.object(
                run,
                "filesystem_identity",
                return_value=FilesystemIdentity(1, "/"),
            ):
                run.ensure_database_root(env, role="worker")

            self.assertTrue(database.is_dir())
            self.assertFalse((database / "redis").exists())

    def test_compose_falls_back_to_legacy_binary(self) -> None:
        with (
            patch.object(run, "_compose_available", return_value=False),
            patch.object(run, "_legacy_compose_available", return_value=True),
        ):
            command = run.compose_base_command({"COMPOSE_FILE": "docker-compose.gateway.yml"})
        self.assertEqual(command[:2], ["docker-compose", "-f"])
        self.assertNotIn("docker-compose.resolver.yml", command)
        self.assertNotIn("docker-compose.resolver-gateway.yml", command)

    def test_resolver_never_enters_worker_deploy_even_with_legacy_settings(self) -> None:
        env = {
            "COMPOSE_FILE": run.os.pathsep.join(
                [
                    "docker-compose.worker.yml",
                    "docker-compose.resolver.yml",
                    "docker-compose.resolver-gateway.yml",
                ]
            ),
            "SAFELINK_RESOLVER_ENABLED": "true",
        }
        self.assertEqual(
            run.compose_files_for_target("worker").split(run.os.pathsep),
            ["docker-compose.worker.yml"],
        )
        command = run.compose_base_command(env)
        self.assertIn("docker-compose.worker.yml", command)
        self.assertNotIn("docker-compose.resolver.yml", command)
        self.assertNotIn("docker-compose.resolver-gateway.yml", command)
        self.assertEqual(
            run.image_names_for_release({
                "WORKER_IMAGE_NAME": "worker",
                "SAFELINK_RESOLVER_ENABLED": "true",
            }),
            ["tme3bot-gateway", "worker"],
        )

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

    def test_registry_login_passes_token_only_through_stdin(self) -> None:
        with patch.object(run, "run_docker") as run_docker:
            run.login_registry(
                {
                    "GATEWAY_IMAGE_NAME": "ghcr.io/nkurnia1031/tme3bot-gateway",
                    "GHCR_USERNAME": "nkurnia1031",
                    "GHCR_TOKEN": "secret-value",
                }
            )

        run_docker.assert_called_once_with(
            ["login", "ghcr.io", "--username", "nkurnia1031", "--password-stdin"],
            {
                "GATEWAY_IMAGE_NAME": "ghcr.io/nkurnia1031/tme3bot-gateway",
                "GHCR_USERNAME": "nkurnia1031",
                "GHCR_TOKEN": "secret-value",
            },
            stdin_text="secret-value",
        )

    def test_run_compose_accepts_compose_file_from_dotenv(self) -> None:
        env = {"COMPOSE_FILE": "docker-compose.gateway.yml", "COMPOSE_CMD": "docker compose"}
        with (
            patch.object(run, "_compose_available", return_value=True),
            patch.object(run.subprocess, "run") as subprocess_run,
        ):
            run.run_compose(["ps"], env)

        self.assertEqual(subprocess_run.call_args.args[0], [
            "docker", "compose", "-f", "docker-compose.gateway.yml",
            "ps"
        ])

    def test_gateway_compose_profile_follows_explicit_mode_and_defaults_full(self) -> None:
        full = run.compose_env({"COMPOSE_FILE": "docker-compose.gateway.yml"})
        lite = run.compose_env(
            {
                "COMPOSE_FILE": "docker-compose.gateway.yml",
                "GATEWAY_MODE": "lite",
            }
        )
        lite_without_local = run.compose_env(
            {
                "COMPOSE_FILE": "docker-compose.gateway.yml",
                "GATEWAY_MODE": "lite",
                "GATEWAY_LITE_LOCAL_STACK": "off",
            }
        )

        self.assertEqual(full["GATEWAY_MODE"], "full")
        self.assertEqual(full["COMPOSE_PROFILES"], "full")
        self.assertEqual(lite["GATEWAY_MODE"], "lite")
        self.assertEqual(lite["COMPOSE_PROFILES"], "lite,lite-local")
        self.assertEqual(lite["GATEWAY_LITE_LOCAL_STACK"], "true")
        self.assertEqual(lite_without_local["COMPOSE_PROFILES"], "lite")
        self.assertEqual(lite_without_local["GATEWAY_LITE_LOCAL_STACK"], "false")

    def test_lite_local_package_boolean_values_are_shared_with_runtime_config(self) -> None:
        from tme3bot.config import AppConfig

        values = {
            "1": True,
            "true": True,
            "yes": True,
            "on": True,
            "enabled": True,
            "0": False,
            "false": False,
            "no": False,
            "off": False,
            "disabled": False,
        }
        for raw_value, expected in values.items():
            with self.subTest(value=raw_value):
                with (
                    patch.dict(
                        run.os.environ,
                        {
                            "APP_ROLE": "worker",
                            "GATEWAY_LITE_LOCAL_STACK": raw_value,
                        },
                        clear=True,
                    ),
                    patch("tme3bot.config.load_dotenv"),
                ):
                    runtime_value = (
                        AppConfig.from_env().gateway_lite_local_stack_enabled
                    )
                deploy_value = run.gateway_lite_local_stack_for_compose(
                    {
                        "COMPOSE_FILE": "docker-compose.gateway.yml",
                        "GATEWAY_MODE": "lite",
                        "GATEWAY_LITE_LOCAL_STACK": raw_value,
                    }
                )
                self.assertEqual(runtime_value, expected)
                self.assertEqual(deploy_value, expected)

        with (
            patch.dict(
                run.os.environ,
                {
                    "APP_ROLE": "worker",
                    "GATEWAY_LITE_LOCAL_STACK": "sometimes",
                },
                clear=True,
            ),
            patch("tme3bot.config.load_dotenv"),
        ):
            with self.assertRaisesRegex(ValueError, "GATEWAY_LITE_LOCAL_STACK"):
                AppConfig.from_env()

        with self.assertRaisesRegex(RuntimeError, "GATEWAY_LITE_LOCAL_STACK"):
            run.gateway_lite_local_stack_for_compose(
                {
                    "COMPOSE_FILE": "docker-compose.gateway.yml",
                    "GATEWAY_MODE": "lite",
                    "GATEWAY_LITE_LOCAL_STACK": "sometimes",
                }
            )

    def test_existing_lite_local_package_does_not_identify_a_full_gateway(self) -> None:
        result = subprocess.CompletedProcess(
            args=["docker", "compose", "ps"],
            returncode=0,
            stdout="backend\nworker-local\naria2\ntts-1\ntts-2\ntts-3\ntelegram-login\n",
            stderr="",
        )
        with (
            patch.object(run, "compose_base_command", return_value=["docker", "compose"]),
            patch.object(run.subprocess, "run", return_value=result),
            patch("builtins.print"),
        ):
            self.assertEqual(
                run.existing_full_gateway_services(
                    {"COMPOSE_FILE": "docker-compose.gateway.yml", "GATEWAY_MODE": "lite"}
                ),
                set(),
            )

    def test_lite_gateway_start_stops_full_only_services_before_starting_login_bot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_root = Path(temp_dir)
            database_file = database_root / "gateway" / "storage.db"
            database_file.parent.mkdir(parents=True)
            with sqlite3.connect(database_file) as database:
                database.execute(
                    "CREATE TABLE jobs (id TEXT, worker TEXT, status TEXT, result TEXT, progress TEXT, updated_at TEXT)"
                )
                database.execute(
                    "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)",
                    ("local-job-running", "local", "running", None, "{}", "2026-11-22T00:00:00Z"),
                )
            env = {
                "COMPOSE_FILE": "docker-compose.gateway.yml",
                "COMPOSE_CMD": "docker compose",
                "DATABASE_ROOT": temp_dir,
                "GATEWAY_MODE": "lite",
            }
            with (
                patch.object(run, "_compose_available", return_value=True),
                patch.object(run, "active_gateway_mode", return_value=None),
                patch.object(
                    run.subprocess,
                    "run",
                    side_effect=[None, None, None],
                ) as subprocess_run,
                patch("builtins.print"),
            ):
                run.run_compose(["up", "-d"], env)

            admission_stop_call, stop_call, up_call = subprocess_run.call_args_list
            self.assertEqual(admission_stop_call.args[0][-2:], ["stop", "backend"])
            self.assertEqual(
                admission_stop_call.kwargs["env"]["COMPOSE_PROFILES"],
                "full,lite,lite-local",
            )
            self.assertEqual(
                stop_call.args[0][-2:],
                ["stop", "telegram"],
            )
            self.assertEqual(
                stop_call.kwargs["env"]["COMPOSE_PROFILES"],
                "full,lite,lite-local",
            )
            self.assertEqual(up_call.args[0][-2:], ["up", "-d"])
            self.assertEqual(
                up_call.kwargs["env"]["COMPOSE_PROFILES"], "lite,lite-local"
            )

    def test_lite_cutover_blocks_before_stop_when_local_job_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_root = Path(temp_dir)
            database_file = database_root / "gateway" / "storage.db"
            database_file.parent.mkdir(parents=True)
            with sqlite3.connect(database_file) as database:
                database.execute(
                    "CREATE TABLE jobs (id TEXT, worker TEXT, status TEXT, result TEXT, progress TEXT, updated_at TEXT)"
                )
                database.execute(
                    "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)",
                    ("local-job-123", "local", "running", None, "{}", "2026-11-22T00:00:00Z"),
                )

            env = {
                "COMPOSE_FILE": "docker-compose.gateway.yml",
                "COMPOSE_CMD": "docker compose",
                "DATABASE_ROOT": str(database_root),
                "GATEWAY_MODE": "lite",
                "GATEWAY_LITE_LOCAL_STACK": "off",
            }
            ps_result = subprocess.CompletedProcess(
                args=["docker", "compose", "ps"],
                returncode=0,
                stdout="",
                stderr="",
            )
            with (
                patch.object(run, "_compose_available", return_value=True),
                patch.object(run.subprocess, "run", return_value=ps_result) as subprocess_run,
                patch("builtins.print"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, r"local-job-123.*running"
                ) as raised:
                    run.run_compose(["up", "-d"], env)

            self.assertNotIn("secret", str(raised.exception).lower())
            subprocess_run.assert_not_called()

    def test_lite_cutover_blocks_terminal_job_needing_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_root = Path(temp_dir)
            database_file = database_root / "gateway" / "storage.db"
            database_file.parent.mkdir(parents=True)
            with sqlite3.connect(database_file) as database:
                database.execute(
                    "CREATE TABLE jobs (id TEXT, worker TEXT, status TEXT, result TEXT, progress TEXT, updated_at TEXT)"
                )
                database.execute(
                    "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "local-job-ambiguous",
                        "local",
                        "failed",
                        '{"value":{"items":[{"status":"needs_reconciliation"}]}}',
                        "{}",
                        "2026-11-22T00:00:00Z",
                    ),
                )

            blockers = run.local_jobs_blocking_lite_cutover(database_file)

            self.assertEqual(
                blockers,
                [("local-job-ambiguous", "needs_reconciliation")],
            )

    def test_lite_cutover_blocks_each_terminal_progress_reconciliation_marker(self) -> None:
        progress_markers = (
            '{"reconciliation_required":true}',
            '{"outcome_uncertain":true}',
        )
        for index, progress in enumerate(progress_markers):
            with self.subTest(progress=progress), tempfile.TemporaryDirectory() as temp_dir:
                database_file = Path(temp_dir) / "storage.db"
                with sqlite3.connect(database_file) as database:
                    database.execute(
                        "CREATE TABLE jobs (id TEXT, worker TEXT, status TEXT, result TEXT, progress TEXT, updated_at TEXT)"
                    )
                    job_id = f"local-job-progress-ambiguous-{index}"
                    database.execute(
                        "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            job_id,
                            "local",
                            "failed",
                            '{"value":{"outcome":"failed"}}',
                            progress,
                            "2026-11-22T00:00:00Z",
                        ),
                    )

                blockers = run.local_jobs_blocking_lite_cutover(database_file)

                self.assertEqual(blockers, [(job_id, "needs_reconciliation")])

    def test_lite_cutover_fails_closed_when_database_cannot_be_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "COMPOSE_FILE": "docker-compose.gateway.yml",
                "COMPOSE_CMD": "docker compose",
                "DATABASE_ROOT": temp_dir,
                "GATEWAY_MODE": "lite",
                "GATEWAY_LITE_LOCAL_STACK": "off",
            }
            ps_result = subprocess.CompletedProcess(
                args=["docker", "compose", "ps"],
                returncode=0,
                stdout="telegram\n",
                stderr="",
            )
            with (
                patch.object(run, "_compose_available", return_value=True),
                patch.object(run.subprocess, "run", return_value=ps_result) as subprocess_run,
                patch("builtins.print"),
            ):
                with self.assertRaisesRegex(RuntimeError, "database gateway tidak ditemukan"):
                    run.run_compose(["up", "-d"], env)

            subprocess_run.assert_called_once()
            self.assertEqual(
                subprocess_run.call_args.args[0][-3:], ["ps", "--all", "--services"]
            )

    def test_lite_cutover_fails_closed_when_jobs_table_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = Path(temp_dir) / "storage.db"
            with sqlite3.connect(database_file):
                pass

            with self.assertRaisesRegex(RuntimeError, "jobs tidak ditemukan"):
                run.local_jobs_blocking_lite_cutover(database_file)

    def test_lite_cutover_fails_closed_when_jobs_schema_has_no_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = Path(temp_dir) / "storage.db"
            with sqlite3.connect(database_file) as database:
                database.execute(
                    "CREATE TABLE jobs (id TEXT, worker TEXT, status TEXT, result TEXT)"
                )

            with self.assertRaisesRegex(RuntimeError, "skema jobs tidak dapat diverifikasi"):
                run.local_jobs_blocking_lite_cutover(database_file)

    def test_lite_without_local_stack_proceeds_after_local_jobs_are_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_root = Path(temp_dir)
            database_file = database_root / "gateway" / "storage.db"
            database_file.parent.mkdir(parents=True)
            with sqlite3.connect(database_file) as database:
                database.execute(
                    "CREATE TABLE jobs (id TEXT, worker TEXT, status TEXT, result TEXT, progress TEXT, updated_at TEXT)"
                )
                database.execute(
                    "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)",
                    ("local-job-done", "local", "succeeded", '{"outcome":"succeeded"}', "{}", "2026-11-22T00:00:00Z"),
                )

            env = {
                "COMPOSE_FILE": "docker-compose.gateway.yml",
                "COMPOSE_CMD": "docker compose",
                "DATABASE_ROOT": str(database_root),
                "GATEWAY_MODE": "lite",
                "GATEWAY_LITE_LOCAL_STACK": "off",
            }
            with (
                patch.object(run, "_compose_available", return_value=True),
                patch.object(run, "active_gateway_mode", return_value=None),
                patch.object(run.subprocess, "run", side_effect=[None, None, None]) as subprocess_run,
                patch("builtins.print"),
            ):
                run.run_compose(["up", "-d"], env)

            self.assertEqual(subprocess_run.call_count, 3)
            self.assertEqual(subprocess_run.call_args_list[0].args[0][-2:], ["stop", "backend"])
            self.assertEqual(
                subprocess_run.call_args_list[1].args[0][-7:],
                ["stop", "telegram", "worker-local", "aria2", "tts-1", "tts-2", "tts-3"],
            )
            self.assertEqual(subprocess_run.call_args_list[2].args[0][-2:], ["up", "-d"])
            self.assertEqual(subprocess_run.call_args_list[2].kwargs["env"]["COMPOSE_PROFILES"], "lite")

    def test_lite_cutover_rechecks_after_admission_stop_and_restores_previous_full_mode(self) -> None:
        env = {
            "COMPOSE_FILE": "docker-compose.gateway.yml",
            "COMPOSE_CMD": "docker compose",
            "GATEWAY_MODE": "lite",
            "GATEWAY_LITE_LOCAL_STACK": "off",
        }
        with (
            patch.object(run, "_compose_available", return_value=True),
            patch.object(
                run,
                "guard_lite_gateway_cutover",
                side_effect=[None, RuntimeError("late local job")],
            ),
            patch.object(run, "active_gateway_mode", return_value="full"),
            patch.object(run.subprocess, "run", return_value=None) as subprocess_run,
            patch("builtins.print"),
        ):
            with self.assertRaisesRegex(RuntimeError, "late local job"):
                run.run_compose(["up", "-d"], env)

        self.assertEqual(subprocess_run.call_count, 3)
        self.assertEqual(subprocess_run.call_args_list[0].args[0][-2:], ["stop", "backend"])
        inactive_stop, recovery = subprocess_run.call_args_list[1:]
        self.assertEqual(inactive_stop.args[0][-2:], ["stop", "telegram-login"])
        self.assertEqual(recovery.args[0][-2:], ["up", "-d"])
        self.assertEqual(recovery.kwargs["env"]["GATEWAY_MODE"], "full")
        self.assertEqual(recovery.kwargs["env"]["COMPOSE_PROFILES"], "full")

    def test_failed_lite_restart_restores_lite_without_starting_full_services(self) -> None:
        env = {
            "COMPOSE_FILE": "docker-compose.gateway.yml",
            "COMPOSE_CMD": "docker compose",
            "GATEWAY_MODE": "lite",
            "GATEWAY_LITE_LOCAL_STACK": "off",
        }
        with (
            patch.object(run, "_compose_available", return_value=True),
            patch.object(
                run,
                "guard_lite_gateway_cutover",
                side_effect=[None, RuntimeError("late preflight failure")],
            ),
            patch.object(run, "active_gateway_mode", return_value="lite"),
            patch.object(run.subprocess, "run", return_value=None) as subprocess_run,
            patch("builtins.print"),
        ):
            with self.assertRaisesRegex(RuntimeError, "late preflight failure"):
                run.run_compose(["up", "-d"], env)

        self.assertEqual(subprocess_run.call_count, 3)
        self.assertEqual(subprocess_run.call_args_list[0].args[0][-2:], ["stop", "backend"])
        self.assertEqual(
            subprocess_run.call_args_list[1].args[0][-7:],
            ["stop", "telegram", "worker-local", "aria2", "tts-1", "tts-2", "tts-3"],
        )
        restore = subprocess_run.call_args_list[2]
        self.assertEqual(restore.args[0][-2:], ["up", "-d"])
        self.assertEqual(restore.kwargs["env"]["GATEWAY_MODE"], "lite")
        self.assertEqual(restore.kwargs["env"]["COMPOSE_PROFILES"], "lite")

    def test_failed_admission_stop_restores_previous_gateway_mode(self) -> None:
        env = {
            "COMPOSE_FILE": "docker-compose.gateway.yml",
            "COMPOSE_CMD": "docker compose",
            "GATEWAY_MODE": "lite",
        }
        with (
            patch.object(run, "_compose_available", return_value=True),
            patch.object(run, "guard_lite_gateway_cutover", return_value=None),
            patch.object(run, "active_gateway_mode", return_value="full"),
            patch.object(
                run, "stop_gateway_admission", side_effect=RuntimeError("stop failed")
            ) as stop_admission,
            patch.object(run, "restore_gateway_after_aborted_lite_cutover") as restore,
            patch("builtins.print"),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop failed"):
                run.run_compose(["up", "-d"], env)

        stop_admission.assert_called_once_with(env)
        restore.assert_called_once_with(env, "full")

    def test_full_gateway_start_stops_lite_login_poller(self) -> None:
        env = {
            "COMPOSE_FILE": "docker-compose.gateway.yml",
            "COMPOSE_CMD": "docker compose",
            "GATEWAY_MODE": "full",
        }
        with (
            patch.object(run, "_compose_available", return_value=True),
            patch.object(run.subprocess, "run") as subprocess_run,
            patch("builtins.print"),
        ):
            run.run_compose(["up", "-d"], env)

        stop_call, _up_call = subprocess_run.call_args_list
        self.assertEqual(stop_call.args[0][-2:], ["stop", "telegram-login"])

    def test_gateway_restart_reconciles_selected_compose_profile(self) -> None:
        env = {
            "COMPOSE_FILE": "docker-compose.gateway.yml",
            "GATEWAY_MODE": "lite",
        }
        with (
            patch.object(run, "load_env_file", return_value=env),
            patch.object(run, "require_env_file"),
            patch.object(run, "run_compose") as run_compose,
            patch.object(run.sys, "argv", ["run.py", "restart"]),
        ):
            self.assertEqual(run.main(), 0)

        run_compose.assert_called_once_with(
            ["up", "-d", "--remove-orphans", "--force-recreate"], env
        )

    def test_static_web_install_preserves_aapanel_files_and_replaces_managed_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "release"
            target = root / "ui.utama.naufix.space"
            (source / "_app").mkdir(parents=True)
            (source / "_app" / "fresh.js").write_text("fresh", encoding="utf-8")
            (source / "index.html").write_text("new", encoding="utf-8")
            target.mkdir()
            (target / "custom-aapanel-file.txt").write_text("keep", encoding="utf-8")
            (target / "old.html").write_text("remove", encoding="utf-8")
            (target / ".tme3bot-static-manifest.json").write_text(
                '["old.html"]\n', encoding="utf-8"
            )

            run._install_static_release(source, target)

            self.assertEqual((target / "index.html").read_text(encoding="utf-8"), "new")
            self.assertTrue((target / "_app" / "fresh.js").is_file())
            self.assertFalse((target / "old.html").exists())
            self.assertEqual((target / "custom-aapanel-file.txt").read_text(encoding="utf-8"), "keep")

    def test_deploy_gateway_reuses_base_and_recreates_services(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            env = {"COMPOSE_FILE": "docker-compose.worker.yml"}
            with (
                patch.object(run, "PROJECT_DIR", project),
                patch.object(run, "require_env_file"),
                patch.object(run, "validate_local_base_image") as validate_base,
                patch.object(run, "ensure_base_image_available"),
                patch.object(run, "ensure_profile_root") as ensure_root,
                patch.object(run, "ensure_database_root") as ensure_db_root,
                patch.object(run, "prepare_tdl_build_asset") as prepare_tdl,
                patch.object(run, "run_compose") as run_compose,
            ):
                run.deploy_application(env, ["gateway"])

        validate_base.assert_called_once_with()
        ensure_root.assert_called_once()
        ensure_db_root.assert_called()
        prepare_tdl.assert_called_once()
        self.assertEqual([call.args[0] for call in run_compose.call_args_list], [
            ["build"],
            ["up", "-d", "--remove-orphans"],
            ["ps"],
        ])
        self.assertEqual(
            run_compose.call_args_list[0].args[1]["COMPOSE_FILE"],
            run.compose_files_for_target("gateway"),
        )

    def test_deploy_worker_imports_profile_root_for_compose_interpolation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            worker_env = project / ".env.worker.test"
            worker_env.write_text("PROFILE_ROOT=/srv/remote-worker\n", encoding="utf-8")
            env = {"WORKER_ENV_FILE": worker_env.name}
            with (
                patch.object(run, "PROJECT_DIR", project),
                patch.object(run, "require_env_file"),
                patch.object(run, "validate_local_base_image"),
                patch.object(run, "ensure_profile_root"),
                patch.object(run, "prepare_tdl_build_asset"),
                patch.object(run, "run_compose") as run_compose,
            ):
                run.deploy_application(env, ["worker", "--pull"], start_services=False)

        deploy_env = run_compose.call_args.args[1]
        self.assertEqual(deploy_env["PROFILE_ROOT"], "/srv/remote-worker")
        self.assertEqual(
            deploy_env["COMPOSE_FILE"], run.compose_files_for_target("worker")
        )

    def test_gateway_stack_omits_resolver_addon_by_default(self) -> None:
        self.assertEqual(
            run.compose_files_for_target("gateway").split(run.os.pathsep),
            ["docker-compose.gateway.yml"],
        )
        self.assertEqual(
            run.compose_files_for_target("worker").split(run.os.pathsep),
            ["docker-compose.worker.yml"],
        )

    def test_target_deploy_uses_only_primary_compose_file(self) -> None:
        env = {
            "COMPOSE_FILE": run.os.pathsep.join(
                [
                    "docker-compose.gateway.yml",
                    "/srv/tme3bot/ssd-upload-test/compose.override.yml",
                    "docker-compose.resolver-gateway.yml",
                ]
            )
        }

        self.assertEqual(
            run.compose_files_for_target("gateway"),
            "docker-compose.gateway.yml",
        )

    def test_migrate_builds_gateway_and_worker_without_resolver_even_when_legacy_flag_enabled(self) -> None:
        env = {"SAFELINK_RESOLVER_ENABLED": "true"}

        def fake_docker(args, _env):
            if args[:2] == ["save", "-o"]:
                Path(args[2]).write_bytes(b"docker images")

        def fake_archive(output, _image_tar):
            output.write_bytes(b"migration archive")
            return 10, output.stat().st_size

        with (
            patch.object(run, "require_env_file"),
            patch.object(run, "ensure_base_image_available"),
            patch.object(run, "prepare_tdl_build_asset"),
            patch.object(run, "run_compose") as run_compose,
            patch.object(run, "capture_compose", side_effect=[
                "gateway-image\nworker-image\n",
                "worker-image\n",
            ]),
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
        self.assertEqual(
            worker_build_env["COMPOSE_FILE"], run.compose_files_for_target("worker")
        )
        for build_env in [call.args[1] for call in run_compose.call_args_list]:
            self.assertNotIn("docker-compose.resolver.yml", build_env["COMPOSE_FILE"])
        run_docker.assert_called_once()
        self.assertEqual(run_docker.call_args.args[0][:2], ["save", "-o"])

    def test_missing_base_image_fails_before_compose_with_recovery_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            with (
                patch.object(run, "PROJECT_DIR", project),
                patch.object(run, "docker_image_exists", return_value=False),
            ):
                with self.assertRaisesRegex(RuntimeError, "build-base.*base-migrate.zip"):
                    run.ensure_base_image_available({})

    def test_base_tar_is_loaded_when_local_image_was_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            base_tar = project / "images" / "tme3bot-base.tar"
            base_tar.parent.mkdir()
            base_tar.write_bytes(b"base")
            with (
                patch.object(run, "PROJECT_DIR", project),
                patch.object(run, "docker_image_exists", side_effect=[False, True]),
                patch.object(run, "run_docker") as run_docker,
            ):
                run.ensure_base_image_available({})

            run_docker.assert_called_once_with(["load", "-i", str(base_tar)], {})

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
                run_docker.call_args_list[0].args[0][:8],
                [
                    "build",
                    "--platform",
                    "linux/amd64",
                    "--build-arg",
                    "BUILDPLATFORM=linux/amd64",
                    "-f",
                    "Dockerfile.base",
                    "-t",
                ],
            )
            self.assertEqual(run_docker.call_args_list[1].args[0][:2], ["save", "-o"])

    def test_update_reuses_cache_and_prepares_host_tdl(self) -> None:
        env = {"PROFILE_ROOT": "/srv/bot"}
        with (
            patch.object(run.sys, "argv", ["run.py", "update"]),
            patch.object(run, "load_env_file", return_value=env),
            patch.object(run, "ensure_profile_root"),
            patch.object(run, "ensure_database_root"),
            patch.object(run, "ensure_base_image_available"),
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

    def test_write_profile_identity_uses_export_lane_without_runuser(self):
        with patch.object(run, "run_compose") as run_compose, patch("builtins.print"):
            run.write_profile_identity(
                {"LEAVE_HELPER_BINARY": "/usr/local/bin/tdl-leave"}, "default"
            )

        command = run_compose.call_args.args[0]
        self.assertEqual(
            command[:4],
            ["exec", "-T", "worker-local", "/usr/local/bin/tdl-leave"],
        )
        self.assertNotIn("runuser", command)
        self.assertEqual(
            command[command.index("--storage") + 1],
            "/database/worker-local/tdl/default/export/.tdl/data",
        )
        self.assertEqual(command[command.index("--namespace") + 1], "default")

    def test_write_profile_identity_uses_container_database_path_for_gateway_worker(self):
        with patch.object(run, "run_compose") as run_compose, patch("builtins.print"):
            run.write_profile_identity(
                {
                    "COMPOSE_FILE": "docker-compose.gateway.yml",
                    "DATABASE_ROOT": "/srv/tme3bot/db/gateway",
                },
                "irang",
            )

        command = run_compose.call_args.args[0]
        self.assertEqual(
            command[command.index("--storage") + 1],
            "/database/worker-local/tdl/irang/export/.tdl/data",
        )

    def test_profile_setup_creates_data_paths_without_tdl_database_directories(self):
        with patch.object(run, "run_compose") as run_compose:
            run.ensure_container_profile_dirs({}, "default")

        command = run_compose.call_args.args[0]
        self.assertNotIn("/data/root/.tdl", command[-1])
        self.assertNotIn("/data/user1/.tdl", command[-1])
        self.assertIn("/data/download", command[-1])
        self.assertNotIn("chown", command[-1])
        self.assertNotIn("runuser", command[-1])

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
