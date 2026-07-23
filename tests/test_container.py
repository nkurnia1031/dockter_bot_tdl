import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ContainerBuildTests(unittest.TestCase):
    def test_dockerfile_prefers_host_tdl_with_fixed_fallback(self) -> None:
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("COPY .docker/tdl/ /tmp/host-tdl/", dockerfile)
        self.assertIn("Trying tdl copied from the Docker host", dockerfile)
        self.assertIn("ARG TDL_FALLBACK_VERSION=0.20.3", dockerfile)
        self.assertIn("tdl_Linux_${tdl_arch}.tar.gz", dockerfile)
        self.assertIn("tdl version", dockerfile)
        self.assertIn("ARG TARGETARCH\n", dockerfile)
        self.assertNotIn("docs.iyear.me/tdl/install.sh", dockerfile)
        self.assertNotIn("wget", dockerfile)

    def test_compose_does_not_force_platform_or_tdl_version(self) -> None:
        compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertNotIn("platform:", compose)
        self.assertNotIn("TDL_VERSION", compose)


if __name__ == "__main__":
    unittest.main()
