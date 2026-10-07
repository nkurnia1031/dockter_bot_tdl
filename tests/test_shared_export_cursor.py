import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from tme3bot.api.backend import _add_internal_state_routes
from tme3bot.application.export_cursor import ExportCursorService
from tme3bot.application.job_scheduler import build_execution_plan
from tme3bot.domain.models import Actor, DomainError, Job, JobStatus
from tme3bot.domain.worker_contract import CAP_SHARED_EXPORT_CURSOR
from tme3bot.export_catalog import ExportArtifactCatalog
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.infrastructure.source_store import (
    ExportCursorBusy,
    PeerAliasConflict,
    PeerAliasCursorConflict,
    SqliteSourceRepository,
    StaleExportLease,
)


class FailingCatalog:
    def __init__(self):
        self.should_fail = True
        self.rows = []

    def upsert_for_export_cursor(self, **values):
        if self.should_fail:
            raise RuntimeError("temporary catalog failure")
        self.rows.append(dict(values))
        return values


class SharedExportCursorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = Path(self.temp.name) / "application.db"
        self.repository = SqliteSourceRepository(database)
        self.catalog = ExportArtifactCatalog(database)
        self.jobs = SqliteJobRepository(database)
        self.service = ExportCursorService(self.repository, self.catalog, self.jobs)
        self.service.set_enabled(True)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def artifact(name="export.json", *, chat_ref="@channelname"):
        return {
            "catalog": True,
            "filename": name,
            "artifact_key": name,
            "chat_ref": chat_ref,
            "label": "different-label-is-not-peer-identity",
            "json_bytes": 128,
            "message_count": 3,
            "media_count": 1,
            "photo_count": 1,
            "video_count": 0,
            "other_media_count": 0,
        }

    def test_verified_username_and_numeric_aliases_share_lane_across_workers(self):
        self.service.resolve_alias("default", "@ChannelName", "channel", "9001")
        self.service.resolve_alias("default", "-1009001", "channel", 9001)

        first = self.service.acquire(
            profile="default", requested_ref="channelname", job_id="job-a",
            worker="local", attempt=1,
        )
        self.assertEqual((first["last_id"], first["revision"], first["fencing_token"]), (0, 0, 1))
        with self.assertRaises(ExportCursorBusy):
            self.service.acquire(
                profile="default", requested_ref="-1009001", job_id="job-b",
                worker="remote-2", attempt=1,
            )

        self.service.resolve_alias("archive", "-1009001", "channel", 9001)
        independent = self.service.acquire(
            profile="archive", requested_ref="-1009001", job_id="job-c",
            worker="remote-2", attempt=1,
        )
        self.assertEqual(independent["profile"], "archive")

    def test_alias_remap_requires_explicit_confirmation(self):
        self.service.resolve_alias("default", "@channelname", "channel", 10)
        with self.assertRaises(PeerAliasConflict):
            self.service.resolve_alias("default", "https://t.me/channelname", "channel", 11)

        candidates = self.repository.list_peer_alias_candidates("default")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["peer_id"], "11")
        self.assertEqual(self.service.alias_identity("default", "channelname")["peer_id"], "10")

        self.repository.confirm_peer_alias_candidate("default", "channelname", "channel", 11)
        self.assertEqual(self.service.alias_identity("default", "@channelname")["peer_id"], "11")
        self.assertEqual(self.repository.list_peer_alias_candidates("default"), [])

    def test_cursor_and_artifact_commit_is_idempotent_and_monotonic(self):
        self.service.resolve_alias("default", "@channelname", "channel", "21")
        first = self.service.acquire(
            profile="default", requested_ref="channelname", job_id="job-first",
            worker="local", attempt=1,
        )
        committed = self.service.commit(
            job_id="job-first", attempt=1, worker="local",
            fencing_token=int(first["fencing_token"]),
            expected_revision=int(first["revision"]), last_id=40,
            artifact=self.artifact("first.json"),
        )
        self.assertEqual(committed["status"], "applied")
        snapshot = SqliteSourceRepository.export_database_snapshot(self.repository.path)
        self.assertEqual(len(snapshot["peer_aliases"]), 1)
        self.assertEqual(len(snapshot["export_lanes"]), 1)
        self.assertEqual(snapshot["export_completions"][0]["status"], "applied")
        replay = self.service.commit(
            job_id="job-first", attempt=1, worker="local",
            fencing_token=int(first["fencing_token"]),
            expected_revision=int(first["revision"]), last_id=40,
            artifact=self.artifact("first.json"),
        )
        self.assertEqual(replay["last_id"], 40)
        self.assertEqual(self.catalog.get_by_key("default", "local", "first.json")["export_job_id"], "job-first")

        second = self.service.acquire(
            profile="default", requested_ref="@channelname", job_id="job-second",
            worker="remote-1", attempt=1,
        )
        self.assertEqual((second["last_id"], second["revision"]), (40, 1))
        lower = self.service.commit(
            job_id="job-second", attempt=1, worker="remote-1",
            fencing_token=int(second["fencing_token"]),
            expected_revision=int(second["revision"]), last_id=12,
            artifact=self.artifact("second.json"),
        )
        self.assertEqual(lower["last_id"], 40)
        self.assertEqual(lower["cursor_revision"], 2)

    def test_first_verified_alias_seeds_lane_from_that_alias_legacy_cursor(self):
        self.repository.upsert_source("default", "@channelname", "label-a", 23)
        self.service.resolve_alias("default", "@channelname", "channel", 25)
        lease = self.service.acquire(
            profile="default", requested_ref="channelname", job_id="job-seed",
            worker="local", attempt=1,
        )
        self.assertEqual((lease["last_id"], lease["revision"]), (23, 1))
        self.assertEqual(
            self.repository.get_source("default", "@channelname").last_id,
            23,
        )

    def test_unreconciled_legacy_cursor_conflict_blocks_alias_merge(self):
        self.repository.upsert_source("default", "@channelname", "first", 10)
        self.service.resolve_alias("default", "@channelname", "channel", 55)
        self.repository.upsert_source("default", "-10055", "second", 20)

        with self.assertRaises(PeerAliasCursorConflict):
            self.service.resolve_alias("default", "-10055", "channel", 55)
        self.assertIsNone(self.service.alias_identity("default", "-10055"))
        with self.assertRaises(PeerAliasCursorConflict):
            self.repository.confirm_peer_alias_candidate("default", "-10055", "channel", 55)

        original = self.service.acquire(
            profile="default", requested_ref="channelname", job_id="job-existing-cursor",
            worker="local", attempt=1,
        )
        self.assertEqual(original["last_id"], 10)

    def test_stale_generation_cannot_commit_after_lane_is_reacquired(self):
        self.service.resolve_alias("default", "@channelname", "channel", 31)
        old = self.service.acquire(
            profile="default", requested_ref="channelname", job_id="job-old",
            worker="local", attempt=1,
        )
        self.service.finish_job("job-old", attempt=1, worker_confirmed=True)
        current = self.service.acquire(
            profile="default", requested_ref="channelname", job_id="job-new",
            worker="remote-1", attempt=1,
        )
        self.assertGreater(current["fencing_token"], old["fencing_token"])
        with self.assertRaises(StaleExportLease):
            self.service.commit(
                job_id="job-old", attempt=1, worker="local",
                fencing_token=int(old["fencing_token"]),
                expected_revision=int(old["revision"]), last_id=50,
                artifact=self.artifact("stale.json"),
            )

    def test_pending_completion_replays_catalog_before_releasing_lane(self):
        self.service.resolve_alias("default", "@channelname", "channel", 41)
        lease = self.service.acquire(
            profile="default", requested_ref="channelname", job_id="job-pending",
            worker="local", attempt=1,
        )
        failing = FailingCatalog()
        service = ExportCursorService(self.repository, failing, self.jobs)
        with self.assertRaisesRegex(RuntimeError, "temporary catalog failure"):
            service.commit(
                job_id="job-pending", attempt=1, worker="local",
                fencing_token=int(lease["fencing_token"]),
                expected_revision=int(lease["revision"]), last_id=51,
                artifact=self.artifact("pending.json"),
            )
        self.assertTrue(service.job_has_active_lease("job-pending"))
        with self.assertRaises(ExportCursorBusy):
            service.acquire(
                profile="default", requested_ref="channelname", job_id="job-next",
                worker="remote-2", attempt=1,
            )
        self.assertFalse(
            service.finish_job("job-pending", attempt=1, worker_confirmed=True)
        )
        self.assertTrue(service.job_has_active_lease("job-pending"))

        failing.should_fail = False
        self.assertEqual(service.recover_pending(), 1)
        self.assertFalse(service.job_has_active_lease("job-pending"))
        self.assertEqual(failing.rows[0]["export_job_id"], "job-pending")
        replay = service.commit(
            job_id="job-pending", attempt=1, worker="local",
            fencing_token=int(lease["fencing_token"]),
            expected_revision=int(lease["revision"]), last_id=51,
            artifact=self.artifact("pending.json"),
        )
        self.assertEqual(replay["last_id"], 51)

    def test_missing_heartbeat_does_not_expire_owner_and_stale_heartbeat_is_rejected(self):
        self.service.resolve_alias("default", "@channelname", "channel", 61)
        lease = self.service.acquire(
            profile="default", requested_ref="channelname", job_id="job-heartbeat",
            worker="local", attempt=1,
        )
        with self.assertRaises(ExportCursorBusy):
            self.service.acquire(
                profile="default", requested_ref="channelname", job_id="job-waiting",
                worker="remote-1", attempt=1,
            )
        self.service.heartbeat(
            job_id="job-heartbeat", worker="local", attempt=1,
            fencing_token=int(lease["fencing_token"]),
        )
        self.service.finish_job("job-heartbeat", attempt=1, worker_confirmed=True)
        with self.assertRaises(StaleExportLease):
            self.service.heartbeat(
                job_id="job-heartbeat", worker="local", attempt=1,
                fencing_token=int(lease["fencing_token"]),
            )

    def test_scheduler_shared_resource_key_uses_verified_peer_not_label_or_worker(self):
        shared = {"peer_type": "channel", "peer_id": "77"}
        first = build_execution_plan(
            "export", "default", "local",
            {"_verified_export_peer": shared, "label": "one"},
        )
        second = build_execution_plan(
            "export", "default", "remote-2",
            {"_verified_export_peer": shared, "label": "another"},
        )
        other_profile = build_execution_plan(
            "export", "archive", "remote-2",
            {"_verified_export_peer": shared},
        )
        shared_key = "profile:default:peer:channel:77:export-cursor"
        self.assertIn(shared_key, first.resource_keys)
        self.assertIn(shared_key, second.resource_keys)
        self.assertNotIn(shared_key, other_profile.resource_keys)

    def test_quickmode_stage_artifact_can_be_committed_without_download_catalog(self):
        self.service.resolve_alias("default", "@channelname", "channel", 81)
        lease = self.service.acquire(
            profile="default", requested_ref="channelname", job_id="quick-job",
            worker="local", attempt=1,
        )
        result = self.service.commit(
            job_id="quick-job", attempt=1, worker="local",
            fencing_token=int(lease["fencing_token"]),
            expected_revision=int(lease["revision"]), last_id=9,
            artifact={
                "catalog": False,
                "artifact_kind": "quickmode_stage",
                "artifact_key": "stage-job/export.json",
                "filename": "export.json",
            },
        )
        self.assertEqual(result["status"], "applied")
        self.assertIsNone(self.catalog.get_by_key("default", "local", "export.json"))

    def test_artifact_metadata_rejects_worker_local_paths(self):
        self.service.resolve_alias("default", "@channelname", "channel", 91)
        lease = self.service.acquire(
            profile="default", requested_ref="channelname", job_id="job-path",
            worker="local", attempt=1,
        )
        with self.assertRaisesRegex(ValueError, "field privat"):
            self.service.commit(
                job_id="job-path", attempt=1, worker="local",
                fencing_token=int(lease["fencing_token"]),
                expected_revision=int(lease["revision"]), last_id=2,
                artifact={**self.artifact("path.json"), "path": "/worker/private/path.json"},
            )

    def test_internal_api_binds_resolve_lease_and_commit_to_job_owner(self):
        job_id = "api-export-job"
        job = Job(
            id=job_id,
            kind="export",
            profile="default",
            actor_user_id=42,
            worker="local",
            status=JobStatus.RUNNING,
            payload={"chat_ref": "channelname"},
        )
        self.jobs.create(job)
        self.jobs.save_execution_plan(
            job_id,
            {"resource_keys": [], "queue_group": "export", "lane": "tdl-export"},
            {"chat_ref": "channelname", "url": "https://t.me3.example/c/channelname/1"},
        )
        self.service.set_enabled(True)
        commits = []
        control_plane = SimpleNamespace(
            jobs=self.jobs,
            require_profile=lambda actor, profile: profile or actor.profile,
            on_export_cursor_committed=commits.append,
        )
        context = SimpleNamespace(
            config=SimpleNamespace(tme3_host="t.me3.example"),
            control_plane=control_plane,
            source_repository=self.repository,
            export_catalog=self.catalog,
            profile_manager=SimpleNamespace(),
            worker_dispatcher=SimpleNamespace(
                capabilities=lambda worker: {
                    "contract_version": 1,
                    "capabilities": [CAP_SHARED_EXPORT_CURSOR],
                }
            ),
        )
        app = FastAPI()

        @app.exception_handler(DomainError)
        async def handle_domain_error(_request, exc):
            return JSONResponse(status_code=exc.status_code, content={"code": exc.code})

        def require_internal(x_internal_token: str = Header(default="")):
            if x_internal_token != "test-internal":
                raise HTTPException(status_code=401)

        def current_actor():
            return Actor(42, "default")

        _add_internal_state_routes(
            app,
            context,
            require_internal,
            current_actor=current_actor,
        )
        client = TestClient(app)
        headers = {"X-Internal-Token": "test-internal"}
        common = {
            "job_id": job_id,
            "worker": "local",
            "profile": "default",
            "attempt": 1,
            "requested_ref": "@channelname",
        }
        resolved = client.post(
            "/internal/v1/export-cursor/resolve",
            headers=headers,
            json={**common, "peer_type": "channel", "peer_id": "111"},
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)
        wrong_worker = client.post(
            "/internal/v1/export-cursor/lease",
            headers=headers,
            json={**common, "worker": "remote-2"},
        )
        self.assertEqual(wrong_worker.status_code, 403)
        acquired = client.post(
            "/internal/v1/export-cursor/lease", headers=headers, json=common
        )
        self.assertEqual(acquired.status_code, 200, acquired.text)
        lease = acquired.json()
        committed = client.post(
            "/internal/v1/export-cursor/commit",
            headers=headers,
            json={
                "job_id": job_id,
                "worker": "local",
                "profile": "default",
                "attempt": 1,
                "fencing_token": lease["fencing_token"],
                "expected_revision": lease["revision"],
                "last_id": 15,
                "artifact": self.artifact("api-export.json"),
            },
        )
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual(committed.json()["last_id"], 15)
        self.assertEqual(commits, [job_id])
        conflict = client.post(
            "/internal/v1/export-cursor/resolve",
            headers=headers,
            json={**common, "peer_type": "channel", "peer_id": "222"},
        )
        self.assertEqual(conflict.status_code, 409)
        pending = client.get("/api/v1/peer-aliases/pending?profile=default")
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["items"][0]["peer_id"], "222")
        confirmed = client.post(
            "/api/v1/peer-aliases/confirm",
            json={
                "profile": "default",
                "requested_ref": "channelname",
                "peer_type": "channel",
                "peer_id": "222",
            },
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(self.service.alias_identity("default", "channelname")["peer_id"], "222")


if __name__ == "__main__":
    unittest.main()
