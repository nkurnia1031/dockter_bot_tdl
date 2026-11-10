from __future__ import annotations

import unittest
import threading

from tme3bot.worker.telegram_upload_verification import TelegramUploadBatchVerifier


class TelegramUploadBatchVerifierTests(unittest.TestCase):
    def test_immediate_export_uses_same_profile_and_one_minute_window(self):
        calls = []

        def export(profile, chat_ref, start, end):
            calls.append((profile, chat_ref, start, end))
            return [{
                "id": 41,
                "date": 1_700_000_000,
                "file_name": "episode 7.mkv",
                "caption": "📄 Name: episode 7.mkv\n#storage",
            }]

        verifier = TelegramUploadBatchVerifier(export)
        upload = verifier.record_upload(
            profile="irang",
            chat_ref="@storage",
            filename="episode 7.mkv",
            caption="📄 Name: episode 7.mkv\n#storage",
            uploaded_at=1_700_000_000,
        )

        self.assertEqual(upload.status, "verified")
        self.assertEqual(upload.message_id, 41)
        self.assertEqual(calls, [("irang", "@storage", 1_699_999_940, 1_700_000_060)])

    def test_missing_immediate_match_gets_one_batch_export_for_duplicate_names(self):
        calls = []

        def export(profile, chat_ref, start, end):
            calls.append((profile, chat_ref, start, end))
            if len(calls) <= 2:
                return []
            return [
                {"id": 52, "file_name": "same.zip", "caption": "backup same.zip"},
                {"id": 53, "file_name": "same.zip", "caption": "backup same.zip"},
            ]

        verifier = TelegramUploadBatchVerifier(export)
        first = verifier.record_upload(
            profile="default", chat_ref="123", filename="same.zip",
            caption="backup same.zip", uploaded_at=1_700_000_000,
        )
        second = verifier.record_upload(
            profile="default", chat_ref="123", filename="same.zip",
            caption="backup same.zip", uploaded_at=1_700_000_030,
        )
        self.assertEqual((first.status, second.status), ("pending", "pending"))

        verifier.finalize()

        self.assertEqual((first.status, second.status), ("verified", "verified"))
        self.assertEqual({first.message_id, second.message_id}, {52, 53})
        self.assertEqual(
            calls,
            [
                ("default", "123", 1_699_999_940, 1_700_000_060),
                ("default", "123", 1_699_999_970, 1_700_000_090),
                ("default", "123", 1_699_999_940, 1_700_000_090),
            ],
        )

    def test_cross_profile_batch_uses_full_chat_window_and_distinct_messages(self):
        calls = []

        def export(profile, chat_ref, start, end):
            calls.append((profile, chat_ref, start, end))
            if len(calls) <= 2:
                return []
            return [
                {
                    "id": 71,
                    "date": 1_700_000_000,
                    "file_name": "same.zip",
                    "caption": "same caption",
                },
                {
                    "id": 72,
                    "date": 1_700_000_180,
                    "file_name": "same.zip",
                    "caption": "same caption",
                },
            ]

        verifier = TelegramUploadBatchVerifier(export)
        first = verifier.record_upload(
            profile="default", chat_ref="123", filename="same.zip",
            caption="same caption", uploaded_at=1_700_000_000,
        )
        second = verifier.record_upload(
            profile="irang", chat_ref="123", filename="same.zip",
            caption="same caption", uploaded_at=1_700_000_180,
        )

        verifier.finalize()

        self.assertEqual((first.status, second.status), ("verified", "verified"))
        self.assertEqual({first.message_id, second.message_id}, {71, 72})
        self.assertEqual(
            calls[2:],
            [
                ("default", "123", 1_699_999_940, 1_700_000_240),
                ("irang", "123", 1_699_999_940, 1_700_000_240),
            ],
        )

    def test_missing_or_mismatched_file_remains_unverified_after_batch_export(self):
        calls = []

        def export(profile, chat_ref, start, end):
            calls.append((profile, chat_ref, start, end))
            return [{
                "id": 60,
                "file_name": "other.zip",
                "caption": "backup requested.zip",
            }]

        verifier = TelegramUploadBatchVerifier(export)
        upload = verifier.record_upload(
            profile="default", chat_ref="123", filename="requested.zip",
            caption="backup requested.zip", uploaded_at=1_700_000_000,
        )
        verifier.finalize()

        self.assertEqual(upload.status, "unverified")
        self.assertIsNone(upload.message_id)
        self.assertEqual(len(calls), 2)

    def test_caption_match_is_byte_for_byte_exact(self):
        verifier = TelegramUploadBatchVerifier(lambda *_args: [{
            "id": 61,
            "file_name": "audio.mp3",
            "caption": "Bab  4",
        }])
        upload = verifier.record_upload(
            profile="default", chat_ref="123", filename="audio.mp3",
            caption="Bab 4", uploaded_at=1_700_000_000,
        )

        verifier.finalize()

        self.assertEqual(upload.status, "unverified")

    def test_empty_caption_does_not_match_nonempty_caption(self):
        verifier = TelegramUploadBatchVerifier(lambda *_args: [{
            "id": 611,
            "file_name": "audio.mp3",
            "caption": "unrelated",
        }])

        upload = verifier.record_upload(
            profile="default", chat_ref="123", filename="audio.mp3",
            caption="", uploaded_at=1_700_000_000,
        )
        verifier.finalize()

        self.assertEqual(upload.status, "unverified")

    def test_storage_caption_name_does_not_substitute_for_attachment_name(self):
        caption = "📄 Name: requested.pdf\n#storage"
        verifier = TelegramUploadBatchVerifier(lambda *_args: [{
            "id": 612,
            "file_name": "different.pdf",
            "caption": caption,
        }])

        upload = verifier.record_upload(
            profile="default", chat_ref="123", filename="requested.pdf",
            caption=caption, uploaded_at=1_700_000_000,
        )
        verifier.finalize()

        self.assertEqual(upload.status, "unverified")

    def test_parallel_checks_cannot_claim_one_message_for_two_uploads(self):
        barrier = threading.Barrier(2)

        def export(*_args):
            barrier.wait(timeout=2)
            return [{
                "id": 613,
                "file_name": "same.zip",
                "caption": "same caption",
            }]

        verifier = TelegramUploadBatchVerifier(export)
        records = []

        def verify():
            records.append(verifier.record_upload(
                profile="default", chat_ref="123", filename="same.zip",
                caption="same caption", uploaded_at=1_700_000_000,
            ))

        threads = [threading.Thread(target=verify) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(sum(record.status == "verified" for record in records), 1)

    def test_tdl_file_field_matches_the_exact_attachment_name(self):
        verifier = TelegramUploadBatchVerifier(lambda *_args: [{
            "id": 62,
            "file": "nested/report.final.pdf",
            "caption": "Original report caption",
        }])

        upload = verifier.record_upload(
            profile="default", chat_ref="123", filename="report.final.pdf",
            caption="Original report caption", uploaded_at=1_700_000_000,
        )

        self.assertEqual(upload.status, "verified")
        self.assertEqual(upload.message_id, 62)

    def test_existing_upload_lookup_prefers_message_nearest_to_saved_upload_time(self):
        expected = {
            "file_name": "same.zip",
            "caption": "same caption",
        }
        messages = [
            {"id": 80, "date": 110, **expected},
            {"id": 81, "date": 190, **expected},
        ]
        verifier = TelegramUploadBatchVerifier(lambda *_args: messages)
        found = verifier.find_existing_upload(
            profile="irang",
            chat_ref="123",
            filename="same.zip",
            caption="same caption",
            start=100,
            end=200,
            reference_time=190,
        )

        self.assertEqual(found.message_id, 81)

    def test_failed_exports_are_not_retried_or_treated_as_verified(self):
        calls = []

        def export(profile, chat_ref, start, end):
            calls.append((profile, chat_ref, start, end))
            raise RuntimeError("export unavailable")

        verifier = TelegramUploadBatchVerifier(export)
        upload = verifier.record_upload(
            profile="default", chat_ref="123", filename="file.bin",
            caption="file.bin", uploaded_at=1_700_000_000,
        )
        verifier.finalize()

        self.assertEqual(upload.status, "unverified")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
