import unittest
from types import SimpleNamespace

from tme3bot.frontend.telegram.panel import PanelManager, edit_menu_message


class FakeBot:
    def __init__(self) -> None:
        self.edit_calls = []
        self.send_calls = []
        self.fail_edit_ids = set()
        self.fail_send = False
        self.next_message_id = 700

    def edit_message_text(self, **kwargs):
        self.edit_calls.append(kwargs)
        if kwargs["message_id"] in self.fail_edit_ids:
            raise RuntimeError("Message to edit not found")
        return True

    def send_message(self, chat_id, text, **kwargs):
        if self.fail_send:
            raise RuntimeError("Telegram send failed")
        self.send_calls.append({"chat_id": chat_id, "text": text, **kwargs})
        message = FakeMessage(
            self,
            chat_id=chat_id,
            message_id=self.next_message_id,
            is_bot=True,
        )
        self.next_message_id += 1
        return message


class FakeMessage:
    def __init__(
        self,
        bot,
        *,
        chat_id=10,
        message_id=20,
        is_bot=True,
        edit_error=None,
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.from_user = SimpleNamespace(is_bot=is_bot)
        self.edit_error = edit_error
        self.deleted = False

    def edit_text(self, text, reply_markup=None):
        if self.edit_error is not None:
            raise self.edit_error
        return True

    def delete(self):
        self.deleted = True


class TelegramPanelRecoveryTests(unittest.TestCase):
    def test_menu_edit_creates_replacement_when_message_is_missing(self) -> None:
        bot = FakeBot()
        message = FakeMessage(
            bot,
            message_id=646,
            edit_error=RuntimeError("Message to edit not found"),
        )

        message_id = edit_menu_message(message, "Menu baru")

        self.assertEqual(message_id, 700)
        self.assertEqual(bot.send_calls[0]["chat_id"], 10)
        self.assertEqual(bot.send_calls[0]["text"], "Menu baru")

    def test_panel_manager_remembers_replacement_for_future_updates(self) -> None:
        bot = FakeBot()
        bot.fail_edit_ids.add(646)
        manager = PanelManager(bot)
        manager.remember(FakeMessage(bot, message_id=646))

        _, replacement_id = manager.update(10, "Progress pertama")
        _, reused_id = manager.update(10, "Progress berikutnya")

        self.assertEqual(replacement_id, 700)
        self.assertEqual(reused_id, 700)
        self.assertEqual(len(bot.send_calls), 1)
        self.assertEqual(bot.edit_calls[-1]["message_id"], 700)

    def test_force_recovery_creates_fresh_panel_without_reply(self) -> None:
        bot = FakeBot()
        manager = PanelManager(bot)
        manager.remember(FakeMessage(bot, message_id=646))
        command = FakeMessage(bot, message_id=900, is_bot=False)

        _, replacement_id = manager.recover_from_message(command, "Memuat panelâ€¦")
        _, reused_id = manager.update(10, "Panel siap")

        self.assertEqual(replacement_id, 700)
        self.assertEqual(reused_id, 700)
        self.assertIsNone(bot.send_calls[0].get("reply_to_message_id"))
        self.assertTrue(command.deleted)

    def test_recovery_keeps_user_command_when_send_fails(self) -> None:
        bot = FakeBot()
        bot.fail_send = True
        manager = PanelManager(bot)
        command = FakeMessage(bot, message_id=900, is_bot=False)

        with self.assertRaisesRegex(RuntimeError, "Telegram send failed"):
            manager.recover_from_message(command, "Memuat panelâ€¦")

        self.assertFalse(command.deleted)

    def test_callback_replacement_can_be_adopted_for_future_updates(self) -> None:
        bot = FakeBot()
        manager = PanelManager(bot)
        missing = FakeMessage(
            bot,
            message_id=646,
            edit_error=RuntimeError("Message to edit not found"),
        )

        edit_menu_message(missing, "Panel pengganti")
        self.assertEqual(manager.adopt_replacement(10), 700)
        _, reused_id = manager.update(10, "Update berikutnya")

        self.assertEqual(reused_id, 700)
        self.assertEqual(len(bot.send_calls), 1)

    def test_update_from_callback_never_deletes_bot_panel(self) -> None:
        bot = FakeBot()
        manager = PanelManager(bot)
        panel_message = FakeMessage(bot, message_id=646, is_bot=True)
        manager.remember(panel_message)

        manager.update_from_message(panel_message, "Job berjalan")

        self.assertFalse(panel_message.deleted)
        self.assertEqual(bot.edit_calls[-1]["message_id"], 646)

    def test_update_from_user_input_still_deletes_processed_message(self) -> None:
        bot = FakeBot()
        manager = PanelManager(bot)
        user_message = FakeMessage(bot, message_id=55, is_bot=False)

        manager.update_from_message(user_message, "Menu")

        self.assertTrue(user_message.deleted)

    def test_transient_status_has_no_keyboard_and_can_be_deleted(self) -> None:
        bot = FakeBot()
        manager = PanelManager(bot)

        status = manager.send_transient(10, "⏳ Export masuk antrean")
        self.assertIsNotNone(status)
        self.assertNotIn("reply_markup", bot.send_calls[-1])
        self.assertTrue(manager.update_transient(status, "⏳ Export berjalan"))

        manager.delete_transient(status)
        self.assertTrue(status.deleted)

    def test_deleted_transient_status_is_non_fatal(self) -> None:
        bot = FakeBot()
        manager = PanelManager(bot)
        status = manager.send_transient(10, "⏳ Export masuk antrean")
        bot.fail_edit_ids.add(status.message_id)

        self.assertFalse(manager.update_transient(status, "⏳ Export berjalan"))
        manager.delete_transient(status)


if __name__ == "__main__":
    unittest.main()
