import json
import tempfile
import unittest
from pathlib import Path

import tme3bot.worker.backup_channel_download as backup_channel_download
from tme3bot.worker.backup_channel_download import (
    BackupChannelDownloadError,
    download_backup_parts,
    download_profile_distribution_artifact,
)


class FakeTdlClient:
    def __init__(self, *, messages=None, events=None):
        self.messages = [
            {
                "id": 45,
                "type": "document",
                "file_name": "backup-remote-2-2026-10-11T072127+0000.7z.001",
                "caption": (
                    "Backup node=remote-2 run=81a8f86e1434\n"
                    "Part: backup-remote-2-2026-10-11T072127+0000.7z.001"
                ),
            },
            {
                "id": 51,
                "type": "document",
                "file_name": "backup-remote-2-2026-10-11T072127+0000.7z.002",
                "caption": "",
                "text": (
                    "#backup #node_remote-2 #run_81a8f86e1434\n"
                    "Part: backup-remote-2-2026-10-11T072127+0000.7z.002"
                ),
            },
            {
                "id": 60,
                "type": "document",
                "file_name": "backup-remote-1.7z.001",
                "caption": "Backup node=remote-1 run=81a8f86e1434\nPart: backup-remote-1.7z.001",
            },
            {
                "id": 61,
                "type": "document",
                "file_name": "backup-remote-2-old.7z.001",
                "caption": "Backup node=remote-2 run=000000000000\nPart: backup-remote-2-old.7z.001",
            },
        ] if messages is None else messages
        self.exported_ids = []
        self.downloaded_ids = []
        self.export_calls = []
        self.events = events if events is not None else []

    def export_messages(self, chat_ref, start_id, export_path, *, with_content, last_count=None, end_id=None):
        self.events.append(("export", Path(export_path)))
        assert chat_ref == "12345"
        assert with_content is True
        self.export_calls.append({"start_id": start_id, "last_count": last_count, "end_id": end_id})
        Path(export_path).write_text(json.dumps({"messages": self.messages}), encoding="utf-8")

    def download(self, export_path, download_dir):
        payload = json.loads(Path(export_path).read_text(encoding="utf-8"))
        rows = payload["messages"]
        ids = [int(row["id"]) for row in rows]
        self.events.append(("download", Path(export_path)))
        self.downloaded_ids.extend(ids)
        target = Path(download_dir)
        target.mkdir(parents=True, exist_ok=True)
        for row in rows:
            message_id = int(row["id"])
            (target / f"{message_id}_{row['file_name']}").write_bytes(f"part-{message_id}".encode())


class BackupChannelDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.destination = self.root / "parts"
        self.parts = [
            {"part_name": "backup-remote-2-2026-10-11T072127+0000.7z.001"},
            {"part_name": "backup-remote-2-2026-10-11T072127+0000.7z.002"},
        ]

    def tearDown(self):
        self.temp.cleanup()

    def test_scans_channel_json_matches_worker_run_and_part_names_then_downloads_by_id(self):
        client = FakeTdlClient()
        progress = []
        result = download_backup_parts(
            client,
            channel_ref="12345",
            node_name="remote-2",
            run_id="81a8f86e1434-full-run-id",
            parts=self.parts,
            destination=self.destination,
            progress=lambda *item: progress.append(item),
        )

        self.assertEqual(client.export_calls, [{"start_id": 1, "last_count": 1000, "end_id": None}])
        self.assertEqual(client.downloaded_ids, [45, 51])
        self.assertEqual([item.path.name for item in result], [item["part_name"] for item in self.parts])
        self.assertEqual([item.message_id for item in result], [45, 51])
        self.assertEqual(result[0].path.read_bytes(), b"part-45")
        self.assertIn("scanning", [item[0] for item in progress])
        self.assertEqual(progress[-1][0], "downloaded")

    def test_missing_selected_run_fails_without_download(self):
        client = FakeTdlClient(messages=[])
        with self.assertRaises(BackupChannelDownloadError) as raised:
            download_backup_parts(
                client,
                channel_ref="12345",
                node_name="remote-2",
                run_id="81a8f86e1434-full-run-id",
                parts=self.parts,
                destination=self.destination,
            )
        self.assertEqual(raised.exception.code, "BACKUP_CHANNEL_PARTS_NOT_FOUND")
        self.assertEqual(client.downloaded_ids, [])

    def test_tdl_work_files_share_private_temporary_workspace(self):
        events = []
        client = FakeTdlClient(events=events)
        download_backup_parts(
            client,
            channel_ref="12345",
            node_name="remote-2",
            run_id="81a8f86e1434-full-run-id",
            parts=self.parts,
            destination=self.destination,
        )

        self.assertEqual([kind for kind, _path in events], ["export", "download", "download"])
        workspace = events[0][1].parent
        self.assertTrue(workspace.name.startswith("backup-channel-"))
        self.assertTrue(all(path.parent == workspace or path.parent.parent == workspace for _kind, path in events))
        self.assertTrue(all(not path.exists() for _kind, path in events))

    def test_unsafe_or_duplicate_part_names_are_rejected_before_channel_access(self):
        client = FakeTdlClient()
        for parts in (
            [{"part_name": "../backup.7z.001"}],
            [self.parts[0], {"channel_message_id": 46, "part_name": self.parts[0]["part_name"]}],
        ):
            with self.subTest(parts=parts), self.assertRaises(BackupChannelDownloadError):
                download_backup_parts(
                    client,
                    channel_ref="12345",
                    node_name="remote-2",
                    run_id="81a8f86e1434-full-run-id",
                    parts=parts,
                    destination=self.destination,
                )
        self.assertEqual(client.export_calls, [])

    def test_profile_distribution_fetches_exact_message_and_binds_caption(self):
        operation_id = "a36b11cb-2135-4fce-89c2-772b0eb25792"

        class DistributionClient:
            def __init__(self, caption):
                self.caption = caption
                self.export_args = None
                self.download_ids = []

            def export_messages(self, chat_ref, start_id, export_path, *, with_content, last_count=None, end_id=None):
                self.export_args = (chat_ref, start_id, end_id, with_content, last_count)
                Path(export_path).write_text(json.dumps({"messages": [{
                    "id": 77,
                    "type": "document",
                    "file_name": "profile-artifact.enc",
                    "caption": self.caption,
                }]}), encoding="utf-8")

            def download(self, export_path, download_dir):
                payload = json.loads(Path(export_path).read_text(encoding="utf-8"))
                self.download_ids.extend(int(item["id"]) for item in payload["messages"])
                Path(download_dir, "77_profile-artifact.enc").write_bytes(b"ciphertext")

        caption = (
            "#profile_distribution\n"
            f"Operation: {operation_id}\nProfile: archive\nRevision: 7\nWorker: remote-2\n"
            "Bundle-SHA256: " + "a" * 64 + "\nArchive-SHA256: " + "b" * 64
            + "\nPart-Index: 1\nPart-Total: 1\nPart: profile-artifact.enc"
        )
        client = DistributionClient(caption)
        destination = self.root / "distribution"
        artifact = download_profile_distribution_artifact(
            client,
            channel_ref="12345",
            node_name="remote-2",
            operation_id=operation_id,
            profile="archive",
            revision=7,
            destination=destination,
            message_ids=[77],
            archive_sha256="b" * 64,
        )
        self.assertEqual(client.export_args, ("12345", 77, 77, True, None))
        self.assertEqual(client.download_ids, [77])
        self.assertEqual(artifact.read_bytes(), b"ciphertext")

        wrong_client = DistributionClient(caption.replace("Revision: 7", "Revision: 6"))
        with self.assertRaises(BackupChannelDownloadError) as raised:
            download_profile_distribution_artifact(
                wrong_client,
                channel_ref="12345",
                node_name="remote-2",
                operation_id=operation_id,
                profile="archive",
                revision=7,
                destination=self.root / "wrong-binding",
                message_ids=[77],
                archive_sha256="b" * 64,
            )
        self.assertEqual(raised.exception.code, "PROFILE_DISTRIBUTION_BINDING_MISMATCH")
        self.assertEqual(wrong_client.download_ids, [])


if __name__ == "__main__":
    unittest.main()
