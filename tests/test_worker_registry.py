import tempfile
import unittest
from pathlib import Path

from tme3bot.worker_registry import WorkerRegistry


class WorkerRegistryTests(unittest.TestCase):
    def test_persists_workers_and_updates_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "workers.json"
            first = WorkerRegistry(path)
            first.upsert("remote-1", "https://worker-1.example", "token-1")

            second = WorkerRegistry(path)
            self.assertEqual(second.get("remote-1")["url"], "https://worker-1.example")
            second.upsert("remote-2", "https://worker-2.example", "token-2")
            self.assertEqual(second.names(), ["remote-1", "remote-2"])

    def test_bootstraps_default_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = WorkerRegistry(
                Path(temp_dir) / "workers.json",
                {"local": "http://worker-local:8080"},
                {"local": "token"},
            )
            self.assertEqual(registry.get("local")["token"], "token")

    def test_bootstrap_worker_is_added_to_existing_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "workers.json"
            first = WorkerRegistry(path)
            first.upsert("remote-1", "https://worker-1.example", "token-1")

            second = WorkerRegistry(
                path, {"local": "http://worker-local:8080"}, {"local": "local-token"}
            )
            self.assertEqual(second.names(), ["remote-1", "local"])
            self.assertEqual(second.get("local")["token"], "local-token")


if __name__ == "__main__":
    unittest.main()
