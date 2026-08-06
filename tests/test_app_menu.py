import unittest
from types import SimpleNamespace

from tme3bot.frontend.telegram.app import TelegramFrontendApp
from tme3bot.frontend.telegram.export_workspace import ExportWorkspaceStore
from tme3bot.frontend.telegram.text import source_digest


class FakePanel:
    def __init__(self):
        self.recovered = []
        self.updated = []

    def recover_from_message(self, message, text, reply_markup=None):
        self.recovered.append((message, text, reply_markup))
        return message.chat_id, 700

    def update_from_message(self, message, text, reply_markup=None):
        self.updated.append((message, text, reply_markup))
        return message.chat_id, 700


class FakeClient:
    def __init__(self):
        self.deliveries = []
        self.me_calls = []

    def me(self, user_id):
        self.me_calls.append(user_id)
        return {"profile": "default", "worker_route": "local", "download_mode": "shared"}

    def get(self, user_id, path):
        return {"items": []}

    def deliver_storage_link(self, token, user_id):
        self.deliveries.append((token, user_id))
        return {"display_name": "shared.bin"}


def fake_update(text="/panel"):
    message = SimpleNamespace(chat_id=10, message_id=20, text=text)
    return SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=99),
    )


class AppMenuTests(unittest.TestCase):
    def test_source_digest_is_short_callback_safe(self) -> None:
        self.assertEqual(len(source_digest("@bot")), 12)
        self.assertEqual(source_digest("@bot"), source_digest("@bot"))

    def make_app(self):
        app = TelegramFrontendApp.__new__(TelegramFrontendApp)
        app.panel = FakePanel()
        app.client = FakeClient()
        app.pending = {}
        app.export_workspaces = ExportWorkspaceStore()
        return app

    def test_panel_command_forces_recovery_before_backend_hydration(self) -> None:
        app = self.make_app()
        update = fake_update()

        app.panel_command(update, None)

        self.assertEqual(app.panel.recovered[0][1], "Memuat panelâ€¦")
        self.assertEqual(app.client.me_calls, [99])
        self.assertTrue(any("Export fokus" in text for _, text, _ in app.panel.updated))

    def test_plain_menu_text_uses_recovery_instead_of_export(self) -> None:
        app = self.make_app()
        update = fake_update("menu")

        app.handle_text(update, None)

        self.assertEqual(len(app.panel.recovered), 1)

    def test_storage_deep_link_does_not_require_actor_exchange(self) -> None:
        app = self.make_app()
        update = fake_update("/start storage_42.signature")

        app.start_command(update, SimpleNamespace(args=["storage_42.signature"]))

        self.assertEqual(app.client.deliveries, [("42.signature", 99)])
        self.assertEqual(app.client.me_calls, [])
        self.assertIn("File dikirim: shared.bin", app.panel.updated[-1][1])
        self.assertIsNone(app.panel.updated[-1][2])

    def test_storage_code_input_does_not_require_actor_exchange(self) -> None:
        app = self.make_app()
        update = fake_update("42.signature")
        app.pending[(10, 99)] = SimpleNamespace(action="storage_redeem")

        app.handle_text(update, None)

        self.assertEqual(app.client.deliveries, [("42.signature", 99)])
        self.assertEqual(app.client.me_calls, [])
        self.assertIn("File dikirim: shared.bin", app.panel.updated[-1][1])

    def test_file_command_prompts_for_storage_code_without_actor(self) -> None:
        app = self.make_app()
        update = fake_update("/file")

        app.storage_code_command(update, None)

        self.assertEqual(app.pending[(10, 99)].action, "storage_redeem")
        self.assertEqual(app.client.me_calls, [])


if __name__ == "__main__":
    unittest.main()
