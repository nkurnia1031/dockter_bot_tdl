from __future__ import annotations

import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from tme3bot.profile_distribution_crypto import encrypt_distribution_bundle
from tme3bot.profile_provisioning import build_profile_bundle
from tme3bot.worker.executor import WorkerJobExecutor


class _ProfileSync:
    def __init__(self) -> None:
        self.sequence = 0
        self.events: list[dict[str, object]] = []

    def next_external_event_sequence(self, _run_id: str) -> int:
        self.sequence += 1
        return self.sequence

    def seed_external_event_sequence(self, _run_id: str, sequence: int) -> None:
        self.sequence = sequence

    def report_external_event(self, **event: object) -> None:
        self.events.append(event)


class WorkerProfileDistributionTests(unittest.TestCase):
    def test_distribution_validates_vault_bundle_without_single_session_tdl_check(self) -> None:
        operation_id = str(uuid4())
        profile = "archive"
        revision = 3
        user_id = 12345
        worker = "remote-1"
        worker_token = "worker-token-for-distribution-test"
        channel_ref = "-1001234567890"
        bundle = build_profile_bundle({"data/default": b"tdl-session-fixture"}, user_id)
        encrypted = encrypt_distribution_bundle(
            bundle,
            worker_token=worker_token,
            operation_id=operation_id,
            profile=profile,
            revision=revision,
            worker=worker,
        )
        archive_sha256 = hashlib.sha256(encrypted).hexdigest()

        with tempfile.TemporaryDirectory() as temporary:
            config = SimpleNamespace(
                backup_node_name=worker,
                backup_channel_ref=channel_ref,
                default_profile="default",
                temp_root=Path(temporary),
            )
            runtime = SimpleNamespace(
                export_operation_lock=threading.RLock(),
                download_operation_lock=threading.RLock(),
                export_tdl_client=object(),
            )
            executor = WorkerJobExecutor.__new__(WorkerJobExecutor)
            executor.config = config
            executor.profile_manager = SimpleNamespace(runtime=lambda _profile: runtime)
            executor.profile_sync = _ProfileSync()
            executor.runtime_settings = SimpleNamespace(worker_api_token=lambda: worker_token)
            executor.validate_profile_session = lambda _data: self.fail(
                "Vault profile bundles must not use the single-session upload validator"
            )
            executor.install_profile_bundle = lambda *_args, **_kwargs: {"ready": True}
            executor.commit_profile_bundle = lambda *_args, **_kwargs: True
            executor.rollback_profile_bundle = lambda *_args, **_kwargs: True

            def download_artifact(*_args, destination: Path, **_kwargs) -> Path:
                artifact = destination / "distribution.enc"
                artifact.write_bytes(encrypted)
                return artifact

            payload = {
                "profile": profile,
                "revision": revision,
                "telegram_user_id": user_id,
                "message_ids": [42],
                "archive_sha256": archive_sha256,
                "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
                "worker": worker,
                "event_sequence_start": 0,
                "channel_ref": channel_ref,
            }

            with patch(
                "tme3bot.worker.backup_channel_download.download_profile_distribution_artifact",
                side_effect=download_artifact,
            ):
                result = executor.distribute_profile_bundle(operation_id, payload)

        self.assertEqual(result, {"ready": True, "profile": profile, "revision": revision})
        self.assertEqual(
            [event["phase"] for event in executor.profile_sync.events],
            ["archive_download", "archive_download", "bundle_validation", "bundle_validation", "completed"],
        )


if __name__ == "__main__":
    unittest.main()
