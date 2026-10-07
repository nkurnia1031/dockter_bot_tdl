import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

import build
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ContainerBuildTests(unittest.TestCase):
    def test_dockerfile_prefers_host_tdl_with_fixed_fallback(self) -> None:
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        basefile = (PROJECT_ROOT / "Dockerfile.base").read_text(encoding="utf-8")

        self.assertIn("ARG TME3BOT_BASE_IMAGE=", dockerfile)
        self.assertIn("The base image contains Python dependencies", dockerfile)
        self.assertIn("COPY .docker/tdl/ /tmp/host-tdl/", basefile)
        self.assertIn("Trying tdl copied from the Docker host", basefile)
        self.assertIn("ARG TDL_FALLBACK_VERSION=0.20.3", basefile)
        self.assertIn("tdl_Linux_${tdl_arch}.tar.gz", basefile)
        self.assertIn("tdl version", basefile)
        self.assertIn("ARG TARGETARCH", basefile)
        self.assertIn("ARG BUILDPLATFORM=linux/amd64", basefile)
        self.assertIn("rclone", basefile)
        self.assertIn("FROM --platform=${BUILDPLATFORM}", basefile)
        self.assertIn("RUN go mod download", basefile)
        self.assertIn("go build -mod=mod -p=1", basefile)
        self.assertNotIn("go mod tidy", dockerfile)
        self.assertNotIn("docs.iyear.me/tdl/install.sh", dockerfile)
        self.assertNotIn("wget", dockerfile)

    def test_compose_does_not_force_platform_or_tdl_version(self) -> None:
        compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertNotIn("platform:", compose)
        self.assertNotIn("TDL_VERSION", compose)

    def test_split_compose_files_define_backend_telegram_and_worker_targets(self) -> None:
        gateway = (PROJECT_ROOT / "docker-compose.gateway.yml").read_text(encoding="utf-8")
        worker = (PROJECT_ROOT / "docker-compose.worker.yml").read_text(encoding="utf-8")
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("backend:", gateway)
        self.assertNotIn("web:", gateway)
        self.assertIn("telegram:", gateway)
        self.assertEqual(gateway.count("target: gateway"), 1)
        telegram_service = gateway.split("  telegram:", 1)[1].split(
            "  worker-local:", 1
        )[0]
        self.assertNotIn("volumes:", telegram_service)
        self.assertNotIn("/data", telegram_service)
        self.assertIn("target: worker", gateway)
        self.assertIn("target: worker", worker)
        self.assertIn('127.0.0.1:${WORKER_PORT:-8080}:${WORKER_PORT:-8080}', worker)
        self.assertIn("APP_ROLE=backend", (PROJECT_ROOT / ".env.backend.example").read_text(encoding="utf-8"))
        self.assertIn("APP_ROLE=telegram", (PROJECT_ROOT / ".env.telegram.example").read_text(encoding="utf-8"))
        self.assertIn("APP_ROLE=worker", (PROJECT_ROOT / ".env.worker.example").read_text(encoding="utf-8"))
        self.assertIn("FROM runtime-base AS gateway", dockerfile)
        self.assertIn("FROM runtime-base AS worker", dockerfile)
        self.assertFalse((PROJECT_ROOT / "Dockerfile.web").exists())
        self.assertTrue((PROJECT_ROOT / "deploy" / "nginx" / "tme3bot-ui.conf").is_file())

    def test_resolver_image_is_private_addon_instead_of_a_worker(self) -> None:
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = yaml.safe_load(
            (PROJECT_ROOT / "docker-compose.resolver.yml").read_text(encoding="utf-8")
        )
        requirements = (PROJECT_ROOT / "requirements-browser.txt").read_text(encoding="utf-8")
        service = compose["services"]["resolver-addon"]

        self.assertIn("FROM runtime-base AS browser-resolver", dockerfile)
        self.assertIn("python3 -m playwright install --with-deps chromium", dockerfile)
        self.assertIn('CMD ["python3", "/app/bot.py"]', dockerfile)
        self.assertIn("playwright==1.55.0", requirements)
        self.assertEqual(service["build"]["target"], "browser-resolver")
        self.assertEqual(service["command"], ["python3", "-m", "tme3bot.worker.resolver_addon"])
        self.assertEqual(service["expose"], ["8091"])
        self.assertNotIn("ports", service)
        self.assertNotIn("volumes", service)
        self.assertNotIn("env_file", service)

    def test_tts_helpers_are_in_default_gateway_and_worker_stacks(self) -> None:
        for filename in ("docker-compose.gateway.yml", "docker-compose.worker.yml"):
            services = yaml.safe_load((PROJECT_ROOT / filename).read_text(encoding="utf-8"))["services"]
            for name in ("tts-1", "tts-2", "tts-3"):
                self.assertIn(name, services)
                self.assertNotIn("profiles", services[name])

    def test_gateway_queue_uses_private_persistent_redis_without_worker_mounts(self) -> None:
        for filename in ("docker-compose.gateway.yml", "docker-compose.yml"):
            payload = yaml.safe_load((PROJECT_ROOT / filename).read_text(encoding="utf-8"))
            services = payload["services"]
            redis = services["redis"]
            runner = services["backend-queue"]
            self.assertNotIn("ports", redis)
            self.assertNotIn("ports", runner)
            self.assertNotIn("volumes", runner)
            self.assertEqual(redis["volumes"], ["queue-redis-data:/data"])
            self.assertIn("--appendonly", redis["command"])
            self.assertIn("--appendfsync", redis["command"])
            self.assertIn("everysec", redis["command"])
            self.assertIn("--maxmemory-policy", redis["command"])
            self.assertIn("noeviction", redis["command"])
            self.assertTrue(payload["networks"]["queue-private"]["internal"])
            self.assertIn("queue-private", redis["networks"])
            self.assertIn("queue-private", runner["networks"])
            self.assertEqual(runner["environment"]["APP_ROLE"], "backend-queue")
            self.assertEqual(runner["environment"]["REDIS_URL"], "redis://redis:6379/0")
            self.assertEqual(runner["environment"]["BOT_TOKEN"], "")
            self.assertNotIn("BACKEND_INTERNAL_TOKEN", runner["environment"])
            self.assertEqual(runner["env_file"], ["${BACKEND_ENV_FILE:-.env.backend}"])

            backend = services["backend"]
            self.assertIn("queue-private", backend["networks"])
            self.assertEqual(backend["environment"]["DURABLE_DISPATCH_ENABLED"], "true")
            self.assertEqual(backend["environment"]["REDIS_URL"], "redis://redis:6379/0")

        remote = yaml.safe_load((PROJECT_ROOT / "docker-compose.worker.yml").read_text(encoding="utf-8"))
        self.assertNotIn("redis", remote["services"])
        self.assertNotIn("backend-queue", remote["services"])

    def test_application_image_installs_pinned_queue_dependencies(self) -> None:
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        basefile = (PROJECT_ROOT / "Dockerfile.base").read_text(encoding="utf-8")
        requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("COPY requirements.txt /tmp/tme3bot-requirements.txt", dockerfile)
        self.assertIn("pip install --no-cache-dir -r /tmp/tme3bot-requirements.txt", dockerfile)
        self.assertIn("COPY requirements.txt /tmp/tme3bot-requirements.txt", basefile)
        self.assertIn("redis==8.1.0", requirements)
        self.assertIn("rq==2.12.0", requirements)

    def test_deployment_archive_includes_split_configs(self) -> None:
        names = {path.name for path in build.iter_files()}
        self.assertIn("docker-compose.gateway.yml", names)
        self.assertIn("docker-compose.worker.yml", names)
        self.assertIn("docker-compose.resolver.yml", names)
        self.assertNotIn("docker-compose.resolver-gateway.yml", names)
        self.assertNotIn(".env.resolver.example", names)
        self.assertIn("requirements-browser.txt", names)
        self.assertIn(".env.backend.example", names)
        self.assertIn(".env.telegram.example", names)
        self.assertIn(".env.worker.example", names)
        self.assertIn("package.json", names)
        self.assertIn("svelte.config.js", names)
        self.assertIn("DEPLOYMENT_RUNBOOK.md", names)

    def test_migration_archive_contains_prebuilt_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_tar = Path(temp_dir) / "images.tar"
            image_tar.write_bytes(b"prebuilt image tar")
            output = Path(temp_dir) / "migrate.zip"

            count, size = build.build_migration_archive(output, image_tar)

            self.assertGreater(count, 0)
            self.assertGreater(size, 0)
            with build.ZipFile(output) as archive:
                self.assertIn("images/tme3bot-images.tar", archive.namelist())
                self.assertEqual(
                    archive.read("images/tme3bot-images.tar"), b"prebuilt image tar"
                )

    def test_base_archive_contains_prebuilt_base_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_tar = Path(temp_dir) / "base.tar"
            image_tar.write_bytes(b"prebuilt base image")
            output = Path(temp_dir) / "base-migrate.zip"

            count, size = build.build_base_archive(output, image_tar)

            self.assertGreater(count, 0)
            self.assertGreater(size, 0)
            with build.ZipFile(output) as archive:
                self.assertIn("images/tme3bot-base.tar", archive.namelist())

    def test_normal_source_archive_auto_includes_extracted_base_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_tar = Path(temp_dir) / "base.tar"
            manifest = Path(temp_dir) / "manifest.json"
            base_tar.write_bytes(b"base")
            manifest.write_text(
                json.dumps(
                    {"fingerprint": build.base_fingerprint()},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output = Path(temp_dir) / "output.zip"

            with (
                patch.object(build, "BASE_IMAGE_TAR", base_tar),
                patch.object(build, "BASE_IMAGE_MANIFEST", manifest),
            ):
                build.build_archive(output)

            with build.ZipFile(output) as archive:
                self.assertIn("images/tme3bot-base.tar", archive.namelist())
                self.assertIn("base-image-manifest.json", archive.namelist())


if __name__ == "__main__":
    unittest.main()
