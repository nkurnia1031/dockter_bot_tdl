from __future__ import annotations

import logging
import threading

from telegram import Bot, InlineKeyboardMarkup, Message

from tme3bot.panel_state import PanelViewStore

LOGGER = logging.getLogger(__name__)


def safe_edit_message(
    message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> bool:
    try:
        message.edit_text(text, reply_markup=reply_markup)
        return True
    except Exception as exc:
        if "message is not modified" in str(exc).lower():
            return True
        LOGGER.warning("Could not edit Telegram message: %s", exc)
        return False


def safe_edit_bot_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    try:
        bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup
        )
        return True
    except Exception as exc:
        if "message is not modified" in str(exc).lower():
            return True
        LOGGER.warning(
            "Could not edit Telegram bot message chat=%s message=%s: %s",
            chat_id,
            message_id,
            exc,
        )
        return False


def edit_or_send_bot_message(
    bot: Bot,
    chat_id: int,
    message_id: int | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    reply_to_message_id: int | None = None,
) -> int:
    if message_id is not None and safe_edit_bot_message(
        bot, chat_id, message_id, text, reply_markup
    ):
        return message_id
    try:
        message = bot.send_message(
            chat_id,
            text,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
    except Exception:
        if reply_to_message_id is None:
            raise
        LOGGER.info("Bot send with reply failed; retrying without reply", exc_info=True)
        message = bot.send_message(chat_id, text, reply_markup=reply_markup)
    return message.message_id


def edit_menu_message(
    message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    if not safe_edit_message(message, text, reply_markup):
        LOGGER.info("Menu message edit skipped; keeping existing Telegram message")


class PanelManager:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._message_ids: dict[int, int] = {}
        self._lock = threading.RLock()
        self._views = PanelViewStore()

    def begin_view(self, chat_id: int) -> int:
        return self._views.begin(chat_id)

    def invalidate_view(self, chat_id: int) -> None:
        self._views.invalidate(chat_id)

    def is_view_active(self, chat_id: int, token: int | None) -> bool:
        return self._views.is_active(chat_id, token)

    def remember(self, message: Message | None) -> None:
        if message is None:
            return
        with self._lock:
            self._message_ids[message.chat_id] = message.message_id

    def forget(self, chat_id: int, message_id: int | None = None) -> None:
        with self._lock:
            current = self._message_ids.get(chat_id)
            if message_id is None or current == message_id:
                self._message_ids.pop(chat_id, None)

    def update(
        self,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        reply_to_message_id: int | None = None,
    ) -> tuple[int, int]:
        with self._lock:
            panel_message_id = self._message_ids.get(chat_id)

        if panel_message_id is not None:
            if safe_edit_bot_message(
                self.bot, chat_id, panel_message_id, text, reply_markup
            ):
                return chat_id, panel_message_id
            self.forget(chat_id, panel_message_id)

        message = self._send(chat_id, text, reply_markup, reply_to_message_id)
        self.remember(message)
        return message.chat_id, message.message_id

    def update_from_message(
        self,
        message: Message,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> tuple[int, int]:
        self.invalidate_view(message.chat_id)
        panel = self.update(
            message.chat_id, text, reply_markup, reply_to_message_id=message.message_id
        )
        self.delete_user_message(message)
        return panel

    @staticmethod
    def delete_user_message(message: Message | None) -> None:
        if message is None:
            return
        try:
            message.delete()
        except Exception:
            LOGGER.debug("Could not delete processed user message", exc_info=True)

    def _send(
        self,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None,
        reply_to_message_id: int | None,
    ) -> Message:
        try:
            return self.bot.send_message(
                chat_id,
                text,
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup,
            )
        except Exception as exc:
            LOGGER.error(
                "Could not send panel message chat=%s reply_to=%s: %s",
                chat_id,
                reply_to_message_id,
                exc,
            )
            if reply_to_message_id is None:
                raise
            LOGGER.info(
                "Panel send with reply failed; retrying without reply", exc_info=True
            )
            return self.bot.send_message(chat_id, text, reply_markup=reply_markup)
