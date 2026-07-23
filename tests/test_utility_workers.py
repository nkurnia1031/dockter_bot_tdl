from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

TELEGRAM_AVAILABLE = importlib.util.find_spec("telegram") is not None
if TELEGRAM_AVAILABLE:
    from tme3bot.utility_workers import UtilityQueueJob, UtilityQueueWorker, _BatchState


class _FakeBot:
    def __init__(self) -> None:
        self.edits = []

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        self.edits.append((chat_id, message_id, text))
        raise RuntimeError("stale panel")


class _FakePanel:
    def __init__(self) -> None:
        self.updated = []

    def is_view_active(self, chat_id, token):
        return True

    def update(self, chat_id, text, reply_markup=None):
        self.updated.append((chat_id, text))
        return chat_id, 11


@unittest.skipUnless(TELEGRAM_AVAILABLE, "python-telegram-bot is not installed")
class UtilityWorkerTests(unittest.TestCase):
    def _job(self) -> UtilityQueueJob:
        return UtilityQueueJob(
            batch_id="batch",
            utility="pindah",
            folder="/workspace/biasa",
            profile_name="default",
            chat_id=99,
            reply_to_message_id=1,
            folder_index=3,
            panel_message_id=10,
            panel_view_token=1,
        )

    def test_running_text_contains_folder_progress_and_last_log(self) -> None:
        state = _BatchState(total=9, done=2, current_folder="/workspace/biasa")
        state.current_index = 3
        state.last_log = "Memindahkan file.mp4"

        text = UtilityQueueWorker._running_text("pindah", state)

        self.assertIn("Folder: 3/9 sedang diproses", text)
        self.assertIn("Selesai: 2/9", text)
        self.assertIn("Log terakhir: Memindahkan file.mp4", text)

    def test_failed_edit_recovers_once_then_reuses_replacement(self) -> None:
        bot = _FakeBot()
        panel = _FakePanel()
        worker = UtilityQueueWorker(bot, object(), panel, Path("/app/utility"))
        worker._panel_message_ids["batch"] = 10
        job = self._job()

        worker._panel(job, "first")
        worker._panel(job, "second")

        self.assertEqual(len(panel.updated), 1)
        self.assertEqual([entry[1] for entry in bot.edits], [10, 11])
        self.assertEqual(worker._panel_message_ids["batch"], 11)


if __name__ == "__main__":
    unittest.main()
