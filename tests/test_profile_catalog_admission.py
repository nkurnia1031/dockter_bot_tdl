from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tme3bot.application.control_plane import ControlPlane
from tme3bot.domain.models import Actor, DomainError
from tme3bot.infrastructure.local_profile_catalog import LocalProfileCatalog


class FakeProfiles:
    profile_registry = SimpleNamespace(local_deletion_active=lambda _profile, _worker: False)

    def list_profiles(self):
        return ["default", "stale"]

    def worker_route(self, _profile):
        return "local"


class FakeWorkers:
    def names(self):
        return ["local", "remote-1"]

    def get(self, _name):
        return {"enabled": True}


class ProfileCatalogAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.catalog = LocalProfileCatalog(Path(self.temp.name) / "catalog.json")
        self.catalog.replace_scan(
            checked_at="2026-10-16T00:00:00Z",
            workers=[
                {"name": "local", "status": "success"},
                {"name": "remote-1", "status": "success"},
            ],
            inventories=[
                {"worker": "local", "items": [
                    {"name": "default", "ready": True},
                    {"name": "shared", "ready": True},
                    {"name": "stale", "ready": True},
                ]},
                {"worker": "remote-1", "items": [
                    {"name": "shared", "ready": True},
                    {"name": "remote-only", "ready": True},
                ]},
            ],
        )
        self.control = ControlPlane(
            None,
            None,
            FakeProfiles(),
            worker_registry=FakeWorkers(),
            local_profile_catalog=self.catalog,
        )
        self.actor = Actor(42, "default")

    def test_exclusive_profile_routes_to_its_only_verified_worker(self):
        self.assertEqual(
            self.control.resolve_target(self.actor, profile="remote-only"),
            ("remote-only", "remote-1"),
        )

    def test_shared_profile_keeps_a_verified_route_or_selects_a_supported_worker(self):
        self.assertEqual(
            self.control.resolve_target(self.actor, profile="shared"),
            ("shared", "local"),
        )
        self.assertEqual(
            self.control.resolve_target(self.actor, profile="shared", worker="remote-1"),
            ("shared", "remote-1"),
        )

    def test_rejects_a_profile_worker_pair_missing_from_the_latest_catalog(self):
        with self.assertRaises(DomainError) as raised:
            self.control.resolve_target(self.actor, profile="remote-only", worker="local")

        self.assertEqual(raised.exception.code, "PROFILE_WORKER_MISMATCH")
        self.assertEqual(raised.exception.details["available_workers"], ["remote-1"])

    def test_job_admission_rejects_a_profile_worker_pair_missing_from_the_catalog(self):
        with self.assertRaises(DomainError) as raised:
            self.control._assert_profile_admission("export", "remote-only", "local", {})

        self.assertEqual(raised.exception.code, "PROFILE_WORKER_MISMATCH")

    def test_rejects_a_known_identity_profile_missing_from_the_latest_scan(self):
        self.catalog.replace_scan(
            checked_at="2026-10-16T00:01:00Z",
            workers=[{"name": "local", "status": "success"}],
            inventories=[{"worker": "local", "items": [{"name": "default", "ready": True}]}],
        )

        with self.assertRaises(DomainError) as raised:
            self.control.resolve_target(self.actor, profile="stale", worker="local")

        self.assertEqual(raised.exception.code, "PROFILE_NOT_VERIFIED")

    def test_catalog_only_profile_can_be_targeted_without_changing_identity_registry(self):
        self.assertEqual(
            self.control.require_profile(self.actor, "remote-only"),
            "remote-only",
        )
        self.assertEqual(self.control.profile_manager.list_profiles(), ["default", "stale"])


if __name__ == "__main__":
    unittest.main()
