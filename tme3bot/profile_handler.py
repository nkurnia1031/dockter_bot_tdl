from __future__ import annotations

from telegram import Message, Update
from telegram.ext import CallbackContext

from tme3bot.bot_keyboards import check_profile_markup, main_menu_markup
from tme3bot.bot_panel import PanelManager, edit_menu_message
from tme3bot.profiles import ProfileManager


class ProfileHandler:
    def __init__(self, profile_manager: ProfileManager, panel: PanelManager) -> None:
        self.profile_manager = profile_manager
        self.panel = panel

    @staticmethod
    def handles_callback(data: str) -> bool:
        return data == "profiles:list" or data.startswith("profile:")

    def profile_command(self, update: Update, context: CallbackContext) -> None:
        message = update.effective_message
        chat_id = update.effective_chat.id
        del context
        selected = self.profile_manager.profile_for_user(chat_id)
        if selected is None:
            self.panel.update_from_message(message, "Akses ditolak. Profile ditentukan dari identity sesi TDL.", check_profile_markup())
            return
        folder = self.profile_manager.runtime(selected).config.profile_root
        self.panel.update_from_message(
            message,
            f"Profile aktif: {selected}\nFolder: {folder}",
            main_menu_markup(selected),
        )

    def profiles_command(self, update: Update, context: CallbackContext) -> None:
        self.profile_command(update, context)

    def handle_callback(self, message: Message, data: str) -> None:
        if data == "profiles:list":
            active = self.profile_manager.profile_for_user(message.chat_id)
            if active is None:
                edit_menu_message(message, "Akses ditolak. Tekan Check Profile terlebih dahulu.", check_profile_markup())
            else:
                edit_menu_message(message, f"Profile otomatis: {active}", main_menu_markup(active))
            return
        active = self.profile_manager.profile_for_user(message.chat_id)
        edit_menu_message(message, f"Profile otomatis: {active}", main_menu_markup(active))
