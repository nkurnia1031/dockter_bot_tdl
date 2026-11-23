import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tme3bot import composition


class BackendStartupTests(unittest.TestCase):
    def test_profile_recovery_starts_before_database_compaction(self):
        order = []

        class Service:
            def __init__(self, name):
                self.name = name

            def start(self):
                order.append(self.name)

            def stop(self):
                pass

        context = SimpleNamespace(
            worker_health_monitor=None,
            storage_maintenance=Service("storage-maintenance"),
            profile_provisioner=Service("profile-provisioner-recovery"),
            profile_distribution_service=Service("profile-distribution-recovery"),
            queue_publisher=Service("queue-publisher"),
            database_compaction_service=Service("database-compaction"),
        )
        scheduler = Service("scheduler")

        with (
            patch.object(composition, "build_backend_context", return_value=(context, scheduler)),
            patch.object(composition, "create_backend_app", return_value=object()),
            patch.object(composition.uvicorn, "run", side_effect=RuntimeError("stop after startup")),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop after startup"):
                composition.run_backend(SimpleNamespace(
                    gateway_mode="full",
                    backend_bind_host="127.0.0.1",
                    backend_port=8000,
                    log_level="INFO",
                ))

        self.assertLess(
            order.index("profile-provisioner-recovery"),
            order.index("database-compaction"),
        )
        self.assertLess(
            order.index("profile-distribution-recovery"),
            order.index("database-compaction"),
        )


if __name__ == "__main__":
    unittest.main()
