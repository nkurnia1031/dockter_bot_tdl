import json
import tempfile
import unittest
from pathlib import Path

from tme3bot.worker.backup_channel_download import (
    BackupChannelDownloadError,
    download_backup_parts,
)


class FakeTdlClient:
    def __init__(self, *, missing_id=None):
        self.missing_id = missing_id
        self.exported_ids = []
        self.downloaded_ids = []

    def export_messages(self, chat_ref, start_id, export_path, *, with_content, end_id):
        assert chat_ref == "12345"
        assert with_content is True
        assert start_id == end_id
        self.exported_ids.append(start_id)
        messages = [] if start_id == self.missing_id else [
            {"id": start_id, "type": "document", "file_name": "archive.7z.001"},
            {"id": start_id + 1000, "type": "document", "file_name": "other.7z"},
        ]
        Path(export_path).write_text(json.dumps({"messages": messages}), encoding="utf-8")

    def download(self, export_path, download_dir):
        payload = json.loads(Path(export_path).read_text(encoding="utf-8"))
        ids = [int(row["id"]) for row in payload["messages"]]
        self.downloaded_ids.extend(ids)
        target = Path(download_dir)
        target.mkdir(parents=True, exist_ok=True)
        for message_id in ids:
            (target / f"{message_id}_from-telegram.7z.001").write_bytes(f"part-{message_id}".encode())


class BackupChannelDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.destination = self.root / "parts"
        self.parts = [
            {"channel_message_id": 45, "part_name": "backup-node.7z.001"},
            {"channel_message_id": 51, "part_name": "backup-node.7z.002"},
        ]

    def tearDown(self):
        self.temp.cleanup()

    def test_downloads_only_selected_message_ids_and_uses_catalog_names(self):
        client = FakeTdlClient()
        progress = []
        result = download_backup_parts(
            client,
            channel_ref="12345",
            parts=self.parts,
            destination=self.destination,
            progress=lambda *item: progress.append(item),
        )

        self.assertEqual(client.exported_ids, [45, 51])
        self.assertEqual(client.downloaded_ids, [45, 51])
        self.assertEqual([path.name for path in result], [item["part_name"] for item in self.parts])
        self.assertEqual(result[0].read_bytes(), b"part-45")
        self.assertEqual([item[0] for item in progress], ["exporting", "downloading", "downloaded"] * 2)

    def test_missing_cataloged_message_fails_without_download(self):
        client = FakeTdlClient(missing_id=45)
        with self.assertRaises(BackupChannelDownloadError) as raised:
            download_backup_parts(
                client,
                channel_ref="12345",
                parts=self.parts,
                destination=self.destination,
            )
        self.assertEqual(raised.exception.code, "BACKUP_CHANNEL_MESSAGE_MISSING")
        self.assertEqual(client.downloaded_ids, [])

    def test_unsafe_or_duplicate_part_names_are_rejected_before_channel_access(self):
        client = FakeTdlClient()
        for parts in (
            [{"channel_message_id": 45, "part_name": "../backup.7z.001"}],
            [self.parts[0], {"channel_message_id": 46, "part_name": self.parts[0]["part_name"]}],
        ):
            with self.subTest(parts=parts), self.assertRaises(BackupChannelDownloadError):
                download_backup_parts(
                    client,
                    channel_ref="12345",
                    parts=parts,
                    destination=self.destination,
                )
        self.assertEqual(client.exported_ids, [])


if __name__ == "__main__":
    unittest.main()
