import tempfile
import unittest
from pathlib import Path

from tme3bot.worker_registry import WorkerRegistry, worker_local_urls, worker_names_for_mode


class WorkerRegistryTests(unittest.TestCase):
    def test_lite_filters_worker_aliases_that_point_at_local_endpoint(self) -> None:
        workers = {
            "worker-alias": {"url": "http://worker-local:8080/", "enabled": True},
            "remote-1": {"url": "https://worker1.example", "enabled": True},
        }
        config = type("Config", (), {
            "worker_local_url": "http://worker-local:8080",
            "worker_endpoints": {"worker-alias": "http://worker-local:8080/"},
        })()

        self.assertEqual(
            worker_names_for_mode(
                workers, "lite", local_urls=worker_local_urls(config)
            ),
            ["remote-1"],
        )
        self.assertEqual(worker_names_for_mode(workers, "full"), ["worker-alias", "remote-1"])

    def test_lite_local_package_controls_local_worker_visibility(self) -> None:
        workers = {
            "local": {"url": "http://worker-local:8080", "enabled": True},
            "worker-alias": {"url": "http://worker-local:8080/", "enabled": True},
            "remote-1": {"url": "https://worker1.example", "enabled": True},
        }
        local_urls = {"http://worker-local:8080"}

        self.assertEqual(
            worker_names_for_mode(
                workers, "lite", local_urls=local_urls,
                include_local_in_lite=True,
            ),
            ["local", "worker-alias", "remote-1"],
        )
        self.assertEqual(
            worker_names_for_mode(
                workers, "lite", local_urls=local_urls,
                include_local_in_lite=False,
            ),
            ["remote-1"],
        )

    def test_lite_keeps_external_worker_named_local_when_package_is_disabled(self) -> None:
        workers = {
            "local": {"url": "https://bot.utama.naufix.space", "enabled": True},
            "worker-local": {"url": "http://worker-local:8080", "enabled": True},
            "remote-1": {"url": "https://worker1.example", "enabled": True},
        }

        self.assertEqual(
            worker_names_for_mode(
                workers,
                "lite",
                local_urls={"http://worker-local:8080"},
                include_local_in_lite=False,
            ),
            ["local", "remote-1"],
        )

    def test_external_local_endpoint_in_worker_endpoints_is_not_gateway_local(self) -> None:
        config = type("Config", (), {
            "worker_local_url": "",
            "worker_endpoints": {"local": "https://bot.utama.naufix.space"},
        })()

        self.assertEqual(worker_local_urls(config), frozenset())

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

    def test_worker_can_be_disabled_without_removing_registry_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = WorkerRegistry(Path(temp_dir) / "workers.json")
            registry.upsert("remote-1", "https://worker-1.example", "token-1")

            self.assertTrue(registry.set_enabled("remote-1", False))
            self.assertEqual(registry.names(), ["remote-1"])
            self.assertEqual(registry.enabled_names(), [])
            self.assertFalse(registry.get("remote-1")["enabled"])

            restored = WorkerRegistry(Path(temp_dir) / "workers.json")
            self.assertFalse(restored.get("remote-1")["enabled"])
            self.assertTrue(restored.set_enabled("remote-1", True))
            self.assertEqual(restored.enabled_names(), ["remote-1"])

    def test_worker_public_download_origin_is_https_and_persists_separately_from_api_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "workers.json"
            registry = WorkerRegistry(path)
            registry.upsert(
                "remote-1", "http://worker-api:8080", "token-1",
                public_url="https://files.worker.example/",
            )

            restored = WorkerRegistry(path)
            self.assertEqual(restored.get("remote-1")["url"], "http://worker-api:8080")
            self.assertEqual(
                restored.get("remote-1")["public_url"],
                "https://files.worker.example",
            )
            with self.assertRaises(ValueError):
                restored.upsert(
                    "remote-1", "http://worker-api:8080", "token-1",
                    public_url="http://files.worker.example",
                )
            with self.assertRaises(ValueError):
                restored.upsert(
                    "remote-1", "http://worker-api:8080", "token-1",
                    public_url="https://files.worker.example:70000",
                )


if __name__ == "__main__":
    unittest.main()
