from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    Filters,
    MessageHandler,
    Updater,
)

from tme3bot.bot_keyboards import check_profile_markup, main_menu_markup, utility_menu_markup
from tme3bot.bot_panel import PanelManager, edit_menu_message, safe_edit_bot_message
from tme3bot.bot_text import help_text
from tme3bot.bot_workers import ExportQueueJob, ExportQueueWorker
from tme3bot.config import AppConfig
from tme3bot.download_handler import DownloadHandler
from tme3bot.labels import LabelStore
from tme3bot.profile_handler import ProfileHandler
from tme3bot.profiles import ProfileManager
from tme3bot.source_handler import SourceHandler
from tme3bot.url_parser import URLParseError
from tme3bot.utility_handler import UtilityHandler
from tme3bot.utility_workers import UtilityQueueWorker

LOGGER = logging.getLogger(__name__)


class TelegramBotApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.profile_manager = ProfileManager(config)
        self.profile_manager.runtime(self.profile_manager.default_profile)

        self.updater = Updater(token=config.bot_token, use_context=True, workers=2)
        self.panel = PanelManager(self.updater.bot)
        self.export_worker = ExportQueueWorker(
            self.updater.bot, self.profile_manager, self.panel
        )
        self.utility_worker = UtilityQueueWorker(
            self.updater.bot, self.profile_manager, self.panel,
            config.utility_workspace_root.parent / "app" / "utility",
        )
        self.utility_handler = UtilityHandler(
            config, self.profile_manager, self.panel, self.utility_worker
        )
        self.profile_handler = ProfileHandler(self.profile_manager, self.panel)
        self.download_handler = DownloadHandler(
            self.updater.bot, self.profile_manager, self.panel
        )
        self.source_handler = SourceHandler(
            config,
            self.profile_manager,
            LabelStore(config.state_file.parent / "labels.json"),
            self.export_worker,
            self.panel,
        )
        self._register_handlers()

    def start(self) -> None:
        self.export_worker.start()
        self.utility_worker.start()
        self.download_handler.start()
        self._set_bot_commands()
        self.updater.start_polling(drop_pending_updates=True)
        LOGGER.info("Bot polling started for host %s", self.config.tme3_host)
        self.updater.idle()

    def _register_handlers(self) -> None:
        dispatcher = self.updater.dispatcher
        for command in ("start", "menu", "panel"):
            callback = self.start_command if command == "start" else self.menu_command
            dispatcher.add_handler(CommandHandler(command, callback))
        dispatcher.add_handler(CommandHandler("help", self.help_command))
        dispatcher.add_handler(CommandHandler("check_profil", self.check_profile_command))
        dispatcher.add_handler(CommandHandler("utility", self.utility_command))
        dispatcher.add_handler(
            CommandHandler("profile", self.profile_handler.profile_command)
        )
        dispatcher.add_handler(
            CommandHandler("profiles", self.profile_handler.profiles_command)
        )
        dispatcher.add_handler(
            CommandHandler("download", self.download_handler.download_command)
        )
        dispatcher.add_handler(
            CommandHandler(
                "download_status", self.download_handler.download_status_command
            )
        )
        dispatcher.add_handler(
            CommandHandler("retry_failed", self.download_handler.retry_failed_command)
        )
        dispatcher.add_handler(
            CommandHandler("clear_fail", self.download_handler.clear_fail_command)
        )
        dispatcher.add_handler(
            CommandHandler(
                "cancel_download", self.download_handler.cancel_download_command
            )
        )
        dispatcher.add_handler(MessageHandler(Filters.command, self.unknown_command))
        dispatcher.add_handler(CallbackQueryHandler(self.handle_callback))
        dispatcher.add_handler(
            MessageHandler(Filters.text & (~Filters.command), self.handle_text)
        )

    def _set_bot_commands(self) -> None:
        commands = [
            BotCommand("menu", "Buka tombol menu bot"),
            BotCommand("panel", "Munculkan ulang panel bot"),
            BotCommand("check_profil", "Cek identity sesi TDL"),
            BotCommand("utility", "Jalankan utility workspace"),
            BotCommand("download", "Download semua JSON pending"),
            BotCommand("download_status", "Cek status download"),
            BotCommand("retry_failed", "Coba ulang JSON failed"),
            BotCommand("clear_fail", "Hapus JSON failed"),
            BotCommand("cancel_download", "Hentikan download aktif"),
            BotCommand("help", "Lihat bantuan"),
        ]
        try:
            self.updater.bot.set_my_commands(commands)
        except (
            Exception
        ):  # pragma: no cover - Telegram network failure should not stop polling
            LOGGER.exception("Failed to set Telegram bot commands")

    def unknown_command(self, update: Update, context: CallbackContext) -> None:
        del context
        if update.effective_message is None or update.effective_chat is None:
            return
        if not update.effective_user or not self._authorized(update.effective_user.id):
            self._show_locked(update.effective_message)
            return
        profile_name = self._active_profile_name(update.effective_user.id)
        self.panel.update_from_message(
            update.effective_message,
            "Command tidak dikenal. Panel bot dimunculkan ulang; pilih menu di bawah ini.",
            main_menu_markup(profile_name),
        )

    def start_command(self, update: Update, context: CallbackContext) -> None:
        del context
        if not update.effective_chat or not update.effective_user or not self._authorized(update.effective_user.id):
            self._show_locked(update.effective_message)
            return
        profile_name = self._active_profile_name(update.effective_user.id)
        self.panel.update_from_message(
            update.effective_message,
            "Menu bot siap. Kamu juga bisa kirim URL t.me3 atau t.me langsung.",
            main_menu_markup(profile_name),
        )

    def menu_command(self, update: Update, context: CallbackContext) -> None:
        del context
        if not update.effective_chat or not update.effective_user or not self._authorized(update.effective_user.id):
            self._show_locked(update.effective_message)
            return
        profile_name = self._active_profile_name(update.effective_user.id)
        self.panel.update_from_message(
            update.effective_message, "Menu bot:", main_menu_markup(profile_name)
        )

    def help_command(self, update: Update, context: CallbackContext) -> None:
        del context
        if not update.effective_chat or not update.effective_user or not self._authorized(update.effective_user.id):
            self._show_locked(update.effective_message)
            return
        profile_name = self._active_profile_name(update.effective_user.id)
        self.panel.update_from_message(
            update.effective_message,
            help_text(self.config.tme3_host),
            main_menu_markup(profile_name),
        )

    def handle_callback(self, update: Update, context: CallbackContext) -> None:
        del context
        query = update.callback_query
        if query is None or query.message is None or query.data is None:
            return
        query.answer()
        message = query.message
        data = query.data
        if data == "access:check":
            self.check_profile_command(update, context)
            return
        if not update.effective_user or not self._authorized(update.effective_user.id):
            edit_menu_message(message, "Akses belum tersedia untuk user ini.", check_profile_markup())
            return
        self.panel.remember(message)
        self.panel.invalidate_view(message.chat_id)

        if self.utility_handler.handles_callback(data):
            self.utility_handler.handle_callback(update, data)
        elif self.source_handler.handles_callback(data):
            self.source_handler.handle_callback(update, data)
        elif self.profile_handler.handles_callback(data):
            self.profile_handler.handle_callback(message, data)
        elif self.download_handler.handles_callback(data):
            self.download_handler.handle_callback(message, data)
        else:
            profile_name = self._active_profile_name(update.effective_user.id)
            if data == "menu:main":
                edit_menu_message(message, "Menu bot:", main_menu_markup(profile_name))
            elif data == "menu:help":
                edit_menu_message(
                    message,
                    help_text(self.config.tme3_host),
                    main_menu_markup(profile_name),
                )
            else:
                edit_menu_message(
                    message,
                    "Menu tidak dikenal. Ketik /menu untuk membuka ulang.",
                    main_menu_markup(profile_name),
                )

    def handle_text(self, update: Update, context: CallbackContext) -> None:
        del context
        message = update.effective_message
        if message is None or not message.text:
            return
        if not update.effective_chat or not update.effective_user or not self._authorized(update.effective_user.id):
            self._show_locked(message)
            return
        if self.utility_handler.handle_text(update):
            return
        if self.source_handler.handle_pending_label(update):
            return

        profile_name = self._active_profile_name(update.effective_user.id)
        runtime = self.profile_manager.runtime(profile_name)
        try:
            parsed = runtime.export_service.validate_url(message.text.strip())
        except URLParseError as exc:
            self.panel.update_from_message(
                message,
                f"{exc}\nContoh: https://t.me/c/4429689667/12",
                main_menu_markup(profile_name),
            )
            return

        if parsed.requested_label:
            self.source_handler.label_store.add(parsed.canonical_label)
        label_text = parsed.canonical_label if parsed.requested_label else "tanpa label"
        queued_text = f"[{profile_name}] Export JSON masuk antrian...\nChat: {parsed.chat_ref}\nLabel: {label_text}"
        panel_chat_id, panel_message_id = self.panel.update_from_message(
            message, queued_text, main_menu_markup(profile_name)
        )
        panel_view_token = self.panel.begin_view(panel_chat_id)
        position = self.export_worker.enqueue(
            ExportQueueJob(
                profile_name=profile_name,
                chat_id=update.effective_chat.id,
                reply_to_message_id=message.message_id,
                url=parsed.original_url,
                use_url_message_id=True,
                panel_chat_id=panel_chat_id,
                panel_message_id=panel_message_id,
                panel_view_token=panel_view_token,
            )
        )
        final_text = f"[{profile_name}] Export JSON masuk antrian #{position}\nChat: {parsed.chat_ref}\nLabel: {label_text}"
        if self.panel.is_view_active(panel_chat_id, panel_view_token):
            safe_edit_bot_message(
                self.updater.bot,
                panel_chat_id,
                panel_message_id,
                final_text,
                main_menu_markup(profile_name),
            )

    def _active_profile_name(self, user_id: int) -> str:
        return self.profile_manager.active_profile_for_chat(user_id)

    def _authorized(self, user_id: int) -> bool:
        return self.profile_manager.is_authorized(user_id)

    def _show_locked(self, message) -> None:
        if message is not None:
            self.panel.update_from_message(
                message,
                "Akses terbatas. Sesi TDL untuk user Telegram ini belum terdaftar. Tekan Check Profile setelah admin menambahkan sesi.",
                check_profile_markup(),
            )

    def check_profile_command(self, update: Update, context: CallbackContext) -> None:
        del context
        message = update.effective_message
        chat = update.effective_chat
        if message is None or chat is None:
            return
        if update.effective_user is None:
            return
        profile_name = self.profile_manager.profile_for_user(update.effective_user.id)
        if profile_name is None:
            self._show_locked(message)
            return
        self.panel.update_from_message(
            message,
            f"Profile ditemukan: {profile_name}. Akses menu diberikan.",
            main_menu_markup(profile_name),
        )

    def utility_command(self, update: Update, context: CallbackContext) -> None:
        del context
        if not update.effective_chat or not update.effective_user or not self._authorized(update.effective_user.id):
            self._show_locked(update.effective_message)
            return
        self.panel.update_from_message(update.effective_message, "Pilih utility.", utility_menu_markup())


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    config = AppConfig.from_env()
    configure_logging(config.log_level)
    TelegramBotApp(config).start()
