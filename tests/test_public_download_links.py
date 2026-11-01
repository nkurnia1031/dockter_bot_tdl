import os
import stat
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tme3bot.api.worker import WorkerContext, create_worker_app
from tme3bot.worker.public_download_links import PublicDownloadLinks


class PublicDownloadLinksTests(unittest.TestCase):
    def test_database_and_sqlite_sidecars_are_private(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            database = root / "links.db"
            database.write_bytes(b"")
            os.chmod(database, 0o644)
            links = PublicDownloadLinks(database, workspace)

            self.assertEqual(stat.S_IMODE(database.stat().st_mode), 0o600)
            target = workspace / "public.txt"
            target.write_text("public", encoding="utf-8")
            links.create(
                target,
                public_base_url="https://worker.example.test",
                job_id="private-database-job",
                provider="telegram",
            )
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{database}{suffix}")
                if sidecar.exists():
                    self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o600)

    def test_link_is_idempotent_for_the_same_job_file_and_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            target = workspace / "downloads" / "report.txt"
            target.parent.mkdir()
            target.write_text("ready", encoding="utf-8")
            links = PublicDownloadLinks(root / "links.db", workspace)

            first = links.create(
                target,
                public_base_url="https://worker.example.test/",
                job_id="job-one",
                provider="telegram",
            )
            retry = links.create(
                target,
                public_base_url="https://worker.example.test",
                job_id="job-one",
                provider="telegram",
            )

            self.assertEqual(retry["id"], first["id"])
            self.assertEqual(retry["token"], first["token"])
            self.assertEqual(len(links.active_links()), 1)
            self.assertEqual(links.public_file(first["token"])["path"], str(target))

    def test_link_is_public_only_for_exact_active_token_and_revoke_deletes_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            target = workspace / "report.txt"
            target.write_text("current contents", encoding="utf-8")
            links = PublicDownloadLinks(root / "links.db", workspace)
            link = links.create(
                target,
                public_base_url="https://worker.example.test",
                job_id="job-one",
                provider="rclone",
            )

            target.write_text("changed after publishing", encoding="utf-8")
            revoked = links.revoke(link["id"])

            self.assertEqual(revoked, {"revoked": True, "cleanup_status": "deleted"})
            self.assertFalse(target.exists())
            self.assertEqual(links.active_links(), [])
            self.assertIsNone(links.public_file(link["token"]))
            self.assertIsNone(links.public_file("a" * 43))

    def test_rejects_non_https_origins_and_files_outside_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.txt"
            outside.write_text("private", encoding="utf-8")
            links = PublicDownloadLinks(root / "links.db", workspace)

            with self.assertRaises(ValueError):
                links.create(
                    outside,
                    public_base_url="https://worker.example.test",
                    job_id="job-one",
                    provider="telegram",
                )
            with self.assertRaises(ValueError):
                PublicDownloadLinks.normalize_public_base_url("http://worker.example.test")
            with self.assertRaises(ValueError):
                PublicDownloadLinks.normalize_public_base_url("https://worker.example.test:70000")

    def test_public_worker_route_streams_exact_token_without_auth_and_revoke_disables_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            target = workspace / "share.txt"
            target.write_text("public content", encoding="utf-8")
            registry = PublicDownloadLinks(root / "links.db", workspace)
            created = registry.create(
                target,
                public_base_url="https://worker.example.test",
                job_id="job-one",
                provider="telegram",
            )

            class Executor:
                def storage_download_public_file(self, token):
                    return registry.public_file(token)

                def storage_download_links(self):
                    return registry.active_links()

                def revoke_storage_download_link(self, link_id):
                    return registry.revoke(link_id)

            app = create_worker_app(
                WorkerContext(
                    type("Config", (), {"worker_api_token": "worker-secret"})(),
                    Executor(),
                )
            )
            with TestClient(app) as client:
                public = client.get(f"/public/download/{created['token']}")
                self.assertEqual(public.status_code, 200)
                self.assertEqual(public.content, b"public content")
                self.assertEqual(public.headers["content-disposition"].split("filename=")[-1], '"share.txt"')
                self.assertEqual(
                    client.get("/public/download/" + "a" * 43).status_code, 404
                )
                denied = client.get("/internal/v1/storage/download-links")
                self.assertEqual(denied.status_code, 401)
                headers = {"Authorization": "Bearer worker-secret"}
                listing = client.get("/internal/v1/storage/download-links", headers=headers)
                self.assertEqual(listing.status_code, 200)
                self.assertEqual(listing.json()["items"][0]["token"], created["token"])
                revoked = client.delete(
                    f"/internal/v1/storage/download-links/{created['id']}",
                    headers=headers,
                )
                self.assertEqual(revoked.status_code, 200)
                self.assertFalse(target.exists())
                self.assertEqual(
                    client.get(f"/public/download/{created['token']}").status_code,
                    404,
                )


if __name__ == "__main__":
    unittest.main()
