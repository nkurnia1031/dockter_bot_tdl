from __future__ import annotations

import logging
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)


class TelegramLoginApp:
    """Minimal Telegram poller that only approves Web login challenges."""

    def __init__(
        self,
        config: Any,
        client: Any | None = None,
        *,
        updater_factory: Callable[..., Any] | None = None,
        command_handler_factory: Callable[..., Any] | None = None,
        bot_command_factory: Callable[..., Any] | None = None,
    ) -> None:
        if client is None:
            from tme3bot.frontend.client import BackendApiClient

            client = BackendApiClient(
                config.backend_api_url, config.frontend_service_token
            )
        if (
            updater_factory is None
            or command_handler_factory is None
            or bot_command_factory is None
        ):
            from telegram import BotCommand
            from telegram.ext import CommandHandler, Updater

            updater_factory = updater_factory or Updater
            command_handler_factory = command_handler_factory or CommandHandler
            bot_command_factory = bot_command_factory or BotCommand

        self.config = config
        self.client = client
        self._command_handler_factory = command_handler_factory
        self._bot_command_factory = bot_command_factory
        self.updater = updater_factory(
            token=config.bot_token, use_context=True, workers=1
        )
        self.updater.dispatcher.add_handler(
            self._command_handler_factory("start", self.start_command)
        )

    def start(self) -> None:
        self.updater.bot.set_my_commands(
            [self._bot_command_factory("start", "Approve Web login")]
        )
        self.updater.start_polling(drop_pending_updates=True)
        LOGGER.info("Telegram Web login poller started")
        self.updater.idle()

    def start_command(self, update: Any, context: Any) -> None:
        user = getattr(update, "effective_user", None)
        message = getattr(update, "effective_message", None)
        args = getattr(context, "args", None) or []
        payload = str(args[0]) if args else ""
        if user is None or message is None or not payload.startswith("login_"):
            self._reply(
                message,
                "Bot ini hanya digunakan untuk menyetujui login Web. "
                "Buka tautan login yang ditampilkan di browser.",
            )
            return

        code = payload[len("login_") :].strip()
        if not code:
            self._reply(message, "Kode login tidak valid. Mulai login lagi dari browser.")
            return
        try:
            self.client.approve_login(code, int(user.id))
        except Exception:
            LOGGER.warning("Web login challenge approval failed")
            self._reply(message, "Persetujuan login gagal. Coba lagi dari browser.")
            return
        self._reply(message, "Login Web disetujui. Kembali ke browser untuk melanjutkan.")

    @staticmethod
    def _reply(message: Any, text: str) -> None:
        if message is None:
            return
        try:
            message.reply_text(text)
        except Exception:
            LOGGER.debug("Could not reply to Web login message")
