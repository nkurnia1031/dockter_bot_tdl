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

    def test_utility_does_not_wait_for_telegram_profile_sync(self):
        ready = self.executor._wait_for_profile_sync(
            "utility",
            "irang",
            0,
            cancelled=Mock(return_value=False),
            on_wait=Mock(),
        )

        self.assertTrue(ready)
        self.executor.profile_sync.wait_until_ready.assert_not_called()

    def test_profile_job_does_not_wait_for_vault_ack_when_local_session_check_is_separate(self):
        self.executor.profile_sync.wait_until_ready.return_value = False
        cancelled = Mock(return_value=False)
        on_wait = Mock()

        ready = self.executor._wait_for_profile_sync(
            "export", "irang", 3, cancelled=cancelled, on_wait=on_wait
        )

        self.assertTrue(ready)
        self.executor.profile_sync.wait_until_ready.assert_not_called()


if __name__ == "__main__":
    unittest.main()
