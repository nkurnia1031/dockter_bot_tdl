import unittest
from unittest.mock import Mock

from tme3bot.worker.executor import WorkerJobExecutor


class WorkerProfileAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.executor = object.__new__(WorkerJobExecutor)
        self.executor.profile_sync = Mock(enabled=True)

    def test_safelink_resolver_does_not_wait_for_telegram_profile_sync(self):
        ready = self.executor._wait_for_profile_sync(
            "safelink_resolve",
            "irang",
            0,
            cancelled=Mock(return_value=False),
            on_wait=Mock(),
        )

        self.assertTrue(ready)
        self.executor.profile_sync.wait_until_ready.assert_not_called()

    def test_profile_dependent_job_still_waits_for_profile_sync(self):
        self.executor.profile_sync.wait_until_ready.return_value = True
        cancelled = Mock(return_value=False)
        on_wait = Mock()

        ready = self.executor._wait_for_profile_sync(
            "export", "irang", 3, cancelled=cancelled, on_wait=on_wait
        )

        self.assertTrue(ready)
        self.executor.profile_sync.wait_until_ready.assert_called_once_with(
            "irang", 3, cancelled=cancelled, on_wait=on_wait
        )


if __name__ == "__main__":
    unittest.main()
