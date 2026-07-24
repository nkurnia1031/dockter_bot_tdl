import tempfile
import unittest
from pathlib import Path

from tme3bot.application.control_plane import ControlPlane
from tme3bot.domain.models import Actor, DomainError
from tme3bot.infrastructure.job_store import SqliteJobRepository


class FakeProfiles:
    def __init__(self):
        self.route = "local"

    def worker_route(self, profile):
        return self.route

    def set_worker_route(self, profile, route):
        self.route = route
        return route


class FakeDispatcher:
    def __init__(self):
        self.commands = []

    def dispatch(self, worker, command):
        self.commands.append(command)

    def cancel(self, worker, job_id):
        return True


class ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs = SqliteJobRepository(Path(self.temp.name) / "jobs.db")
        self.profiles = FakeProfiles()
        self.dispatcher = FakeDispatcher()
        self.control = ControlPlane(self.jobs, self.dispatcher, self.profiles)
        self.actor = Actor(42, "default")

    def tearDown(self):
        self.temp.cleanup()

    def test_active_job_locks_worker_route(self):
        self.control.submit_job(
            self.actor, "export", {"url": "https://t.me/c/1/2"}
        )

        with self.assertRaises(DomainError) as raised:
            self.control.set_worker_route(self.actor, "remote-1")

        self.assertEqual(raised.exception.code, "PROFILE_BUSY")
        self.assertEqual(self.profiles.route, "local")

    def test_nested_utility_secrets_are_not_persisted(self):
        job = self.control.submit_job(
            self.actor,
            "utility",
            {
                "utility": "compress",
                "password": "extract-secret",
                "settings": {
                    "compress_password": "archive-secret",
                    "compress_size": "45m",
                },
            },
        )

        persisted = self.jobs.get(job.id)
        self.assertEqual(persisted.payload["password"], "***")
        self.assertEqual(
            persisted.payload["settings"]["compress_password"], "***"
        )
        self.assertEqual(
            self.dispatcher.commands[0]["payload"]["password"],
            "extract-secret",
        )


if __name__ == "__main__":
    unittest.main()
