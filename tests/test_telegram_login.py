import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from tme3bot.frontend.telegram_login import TelegramLoginApp


class TelegramLoginAppTests(unittest.TestCase):
    def setUp(self):
        self.dispatcher = SimpleNamespace(handlers=[], error_handlers=[])

        def add_handler(handler):
            self.dispatcher.handlers.append(handler)

        def add_error_handler(handler):
            self.dispatcher.error_handlers.append(handler)

        self.dispatcher.add_handler = add_handler
        self.dispatcher.add_error_handler = add_error_handler
        self.bot = Mock()
        self.updater = SimpleNamespace(
            dispatcher=self.dispatcher,
            bot=self.bot,
            start_polling=Mock(),
            idle=Mock(),
        )
        self.client = Mock()

        def updater_factory(token, *, use_context, workers):
            self.assertEqual(token, "fake-token")
            self.assertTrue(use_context)
            self.assertEqual(workers, 1)
            return self.updater

        def command_handler_factory(command, callback):
            return SimpleNamespace(command=command, callback=callback)

        self.app = TelegramLoginApp(
            SimpleNamespace(bot_token="fake-token"),
            self.client,
            updater_factory=updater_factory,
            command_handler_factory=command_handler_factory,
            bot_command_factory=lambda command, description: (command, description),
        )

    def test_login_bot_registers_only_start_and_approves_web_challenge(self):
        message = Mock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42), effective_message=message
        )

        self.app.start_command(update, SimpleNamespace(args=["login_123456"]))

        self.assertEqual(
            [handler.command for handler in self.dispatcher.handlers], ["start"]
        )
        self.client.approve_login.assert_called_once_with("123456", 42)
        message.reply_text.assert_called_once()

    def test_login_bot_does_not_approve_or_expose_other_commands(self):
        message = Mock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42), effective_message=message
        )

        self.app.start_command(update, SimpleNamespace(args=["menu"]))

        self.client.approve_login.assert_not_called()
        self.assertEqual(
            [handler.command for handler in self.dispatcher.handlers], ["start"]
        )
        message.reply_text.assert_called_once()


if __name__ == "__main__":
    unittest.main()
