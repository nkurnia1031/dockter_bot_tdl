import unittest
from unittest.mock import patch

from tme3bot.frontend.telegram.app import TelegramFrontendApp


class FakeStatusMessage:
    pass


class FakeStatusPanel:
    def __init__(self):
        self.status_updates = []
        self.deleted = []

    def is_view_active(self, chat_id, token):
        return False

    def update_transient(self, message, text):
        self.status_updates.append((message, text))
        return True

    def delete_transient(self, message):
        self.deleted.append(message)

    def update(self, *args, **kwargs):
        raise AssertionError("Panel utama tidak boleh diperbarui setelah view invalid")


class FakeClient:
    def __init__(self):
        self.jobs = iter(
            [
                {"id": "job-1", "status": "running", "profile": "default", "worker": "local"},
                {
                    "id": "job-1",
                    "status": "succeeded",
                    "profile": "default",
                    "worker": "local",
                    "result": {"value": {"message_count": 2, "media_count": 1}},
                },
            ]
        )

    def get(self, user_id, path):
        return next(self.jobs)


class ExportStatusPollingTests(unittest.TestCase):
    def test_status_message_continues_after_panel_view_changes_and_is_deleted(self):
        app = TelegramFrontendApp.__new__(TelegramFrontendApp)
        app.panel = FakeStatusPanel()
        app.client = FakeClient()
        status_message = FakeStatusMessage()

        with patch("tme3bot.frontend.telegram.app.time.sleep"):
            thread = app._poll_export_job(
                10,
                42,
                "job-1",
                7,
                {"profile": "default", "worker_route": "local"},
                status_message,
            )
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(app.panel.deleted, [status_message])
        self.assertEqual(len(app.panel.status_updates), 2)
        self.assertIn("Export sedang berjalan", app.panel.status_updates[0][1])
        self.assertIn("Message: 2", app.panel.status_updates[-1][1])


if __name__ == "__main__":
    unittest.main()
