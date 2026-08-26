import unittest

from tme3bot.frontend.telegram.export_workspace import (
    ExportWorkspaceState,
    ExportWorkspaceStore,
    export_report,
    format_export_job,
    format_export_status,
)
from tme3bot.frontend.telegram.keyboards import export_workspace_markup


class ExportWorkspaceTests(unittest.TestCase):
    def test_source_selection_uses_backend_last_id_by_default(self):
        state = ExportWorkspaceState()
        state.select_source({"chat_ref": "@FileTuyenChonBot", "last_id": 7932})

        self.assertEqual(state.chat_ref, "filetuyenchonbot")
        self.assertEqual(state.default_start_id, 7933)
        self.assertEqual(
            state.payload(),
            {
                "chat_ref": "filetuyenchonbot",
                "use_url_message_id": False,
            },
        )

    def test_explicit_start_id_is_sent_as_override(self):
        state = ExportWorkspaceState()
        state.select_source({"chat_ref": "channel", "last_id": 99})
        state.set_label("arsip 2026")
        state.set_start_id("123")

        self.assertEqual(
            state.payload(),
            {
                "chat_ref": "channel",
                "label": "arsip 2026",
                "start_id": 123,
                "use_url_message_id": True,
            },
        )

    def test_overwrite_switch_requires_manual_value_and_can_reset_to_auto(self):
        state = ExportWorkspaceState()
        state.select_source({"chat_ref": "channel", "last_id": 99})
        state.set_overwrite_start_id(True)

        with self.assertRaisesRegex(ValueError, "Isi Start ID manual"):
            state.payload()

        state.set_start_id(12)
        self.assertTrue(state.overwrite_start_id)
        self.assertEqual(state.payload()["start_id"], 12)
        state.set_overwrite_start_id(False)
        self.assertEqual(state.effective_start_id, 100)
        self.assertNotIn("start_id", state.payload())
        self.assertFalse(state.payload()["use_url_message_id"])

    def test_new_source_defaults_to_message_one_and_at_is_ignored(self):
        state = ExportWorkspaceState()
        state.select_chat_ref("@NewChannel")

        self.assertEqual(state.effective_start_id, 1)
        self.assertEqual(state.payload()["chat_ref"], "newchannel")

    def test_numeric_source_defaults_to_not_saved_and_can_opt_in(self):
        state = ExportWorkspaceState()
        state.select_chat_ref("-100123")

        self.assertFalse(state.save_source)
        self.assertFalse(state.payload()["save_source"])
        state.set_save_source(True)
        self.assertTrue(state.payload()["save_source"])

    def test_store_isolated_by_chat_and_user(self):
        store = ExportWorkspaceStore()
        first = store.get(10, 42)
        second = store.get(10, 43)
        first.select_chat_ref("one")

        self.assertEqual(first.chat_ref, "one")
        self.assertIsNone(second.chat_ref)

    def test_selecting_source_resets_only_the_panel_job_view(self):
        state = ExportWorkspaceState()
        state.select_source({"chat_ref": "old", "last_id": 10})
        state.set_job({"id": "job-old", "status": "succeeded"})

        state.select_source({"chat_ref": "new", "last_id": 20})

        self.assertEqual(state.chat_ref, "new")
        self.assertIsNone(state.active_job_id)
        self.assertIsNone(state.job_snapshot)
        self.assertEqual(state.default_start_id, 21)
        self.assertFalse(state.overwrite_start_id)

    def test_report_unwraps_structured_worker_result(self):
        report = export_report(
            {
                "status": "succeeded",
                "result": {
                    "value": {
                        "exported_count": 26,
                        "message_count": 26,
                        "media_count": 10,
                        "photo_count": 6,
                        "video_count": 4,
                        "latest_id": 7958,
                        "filename": "export.json",
                    }
                },
            }
        )

        self.assertEqual(report["message_count"], 26)
        self.assertEqual(report["media_count"], 10)
        self.assertEqual(report["latest_id"], 7958)
        self.assertEqual(report["filename"], "export.json")

    def test_keyboard_renders_values_as_text(self):
        state = ExportWorkspaceState()
        state.select_source({"chat_ref": "channel", "last_id": 4})
        markup = export_workspace_markup(
            state,
            [{"chat_ref": "channel", "label": "arsip", "last_id": 4}],
            [{"label": "2026", "updated_at": "now"}],
        )
        labels = [button.text for row in markup.inline_keyboard for button in row]

        self.assertTrue(any("arsip" in value for value in labels))
        self.assertTrue(any("2026" in value for value in labels))
        self.assertFalse(any("object at" in value for value in labels))
        self.assertFalse(any(value in labels for value in ("Export lagi", "Detail job")))
        self.assertIn("Overwrite Start ID: OFF", labels)

    def test_source_picker_is_compact_and_uses_stable_digest_callbacks(self):
        state = ExportWorkspaceState(source_picker=True)
        sources = [
            {"chat_ref": f"channel-{index}", "label": f"label-{index}"}
            for index in range(10)
        ]
        markup = export_workspace_markup(state, sources, [])
        buttons = [button for row in markup.inline_keyboard for button in row]
        source_buttons = [button for button in buttons if button.callback_data.startswith("ew:s:")]

        self.assertEqual(len(source_buttons), 6)
        self.assertTrue(all(len(button.callback_data.split(":")[-1]) == 12 for button in source_buttons))
        self.assertIn("🔎 Cari source", [button.text for button in buttons])

    def test_default_export_form_does_not_render_every_source_as_a_button(self):
        state = ExportWorkspaceState()
        markup = export_workspace_markup(
            state,
            [{"chat_ref": f"source-{index}", "label": f"label-{index}"} for index in range(20)],
            [],
        )
        labels = [button.text for row in markup.inline_keyboard for button in row]

        self.assertIn("Pilih source tersimpan", labels)
        self.assertFalse(any("source-1" in value for value in labels))

    def test_source_picker_exposes_delete_action(self):
        state = ExportWorkspaceState(source_picker=True)
        markup = export_workspace_markup(
            state, [{"chat_ref": "channel", "label": "arsip"}], []
        )
        buttons = [button for row in markup.inline_keyboard for button in row]

        self.assertIn("Hapus", [button.text for button in buttons])
        self.assertTrue(any(button.callback_data.startswith("ew:del:") for button in buttons))

    def test_job_formatter_is_structured_and_omits_missing_fields(self):
        text = format_export_job(
            {
                "status": "succeeded",
                "id": "job-1234567890",
                "profile": "default",
                "worker": "local",
                "result": {"value": {"message_count": 3, "media_count": 1}},
            }
        )

        self.assertIn("Status: succeeded", text)
        self.assertIn("Message: 3", text)
        self.assertIn("Media: 1", text)
        self.assertNotIn("Foto:", text)
        self.assertNotIn("Video:", text)
        self.assertNotIn("{'", text)

    def test_status_formatter_includes_terminal_report_without_raw_objects(self):
        text = format_export_status(
            {
                "status": "succeeded",
                "id": "job-1234567890",
                "profile": "default",
                "worker": "local",
                "result": {
                    "value": {
                        "message_count": 26,
                        "media_count": 10,
                        "photo_count": 6,
                        "video_count": 4,
                        "latest_id": 7958,
                        "filename": "export.json",
                    }
                },
            }
        )

        self.assertIn("✅ Export selesai", text)
        self.assertIn("Message: 26", text)
        self.assertIn("Media: 10", text)
        self.assertIn("Artifact: export.json", text)
        self.assertNotIn("{'", text)

    def test_status_formatter_explains_media_less_artifact_cleanup(self):
        text = format_export_status(
            {
                "status": "succeeded",
                "id": "job-empty",
                "result": {
                    "value": {
                        "message_count": 4,
                        "media_count": 0,
                        "artifact_deleted": True,
                        "artifact_delete_reason": "no_media",
                    }
                },
            }
        )

        self.assertIn("Media: 0", text)
        self.assertIn("JSON dihapus otomatis (tidak ada media)", text)

    def test_status_formatter_includes_active_json_file_speed_and_eta(self):
        text = format_export_status(
            {
                "status": "running",
                "id": "job-running",
                "progress": {
                    "message": "Mendownload media",
                    "batch": {"name": "archive.json", "index": 2, "total": 3},
                    "item": {"name": "video.mp4", "index": 7, "total": 20},
                    "transfer": {"speed_bps": 1048576, "eta_seconds": 12},
                    "overall": {"current": 1, "total": 3, "percent": 50},
                },
            }
        )

        self.assertIn("JSON: archive.json (2/3)", text)
        self.assertIn("File: video.mp4 (7/20)", text)
        self.assertIn("Speed: 1.0 MB/dtk", text)
        self.assertIn("ETA: 12 dtk", text)


if __name__ == "__main__":
    unittest.main()
