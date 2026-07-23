from __future__ import annotations

from telegram import Message, Update

from tme3bot.bot_keyboards import (
    main_menu_markup, utility_confirm_markup, utility_folders_markup,
    utility_menu_markup, utility_password_markup,
)
from tme3bot.bot_panel import PanelManager, edit_menu_message
from tme3bot.names import normalize_profile_name
from tme3bot.profiles import ProfileManager
from tme3bot.source_selection import SourceSelectionStore
from tme3bot.utility import UTILITY_NAMES, UtilityFolderStore, UtilityPathError
from tme3bot.utility_workers import UtilityQueueWorker

PREFIX = "utility:"


class UtilityHandler:
    def __init__(self, config, profile_manager: ProfileManager, panel: PanelManager,
                 worker: UtilityQueueWorker) -> None:
        self.profile_manager = profile_manager
        self.panel = panel
        self.worker = worker
        self.folders = UtilityFolderStore(config.utility_folders_file, config.utility_workspace_root)
        self.selections = SourceSelectionStore()
        self.pending_custom: dict[tuple[int, str], str] = {}
        self.pending_password: dict[tuple[int, str], tuple[str, list[str]]] = {}

    def handles_callback(self, data: str) -> bool:
        return data.startswith(PREFIX)

    def handle_callback(self, update: Update, data: str) -> None:
        message = update.callback_query.message if update.callback_query else None
        if message is None:
            return
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else "menu"
        utility = parts[2] if len(parts) > 2 else ""
        if action == "menu":
            self._show_utility_menu(message)
        elif action == "folders":
            self._show_folders(message, utility)
        elif action == "select":
            self._toggle(message, utility, parts[3] if len(parts) > 3 else "")
        elif action == "all":
            self.selections.select_all(self._owner(message, utility), self.folders.list())
            self._show_folders(message, utility)
        elif action == "clear":
            self.selections.clear(self._owner(message, utility)); self._show_folders(message, utility)
        elif action == "add":
            self.pending_custom[(message.chat_id, utility)] = utility
            edit_menu_message(message, "Kirim path folder custom di dalam /workspace.", utility_password_markup("cancel-custom"))
        elif action == "remove":
            self._remove_selected(message, utility)
        elif action == "ask":
            self._confirm(message, utility)
        elif action == "run":
            self._run(message, utility)
        elif action == "password":
            self.pending_password[(message.chat_id, utility)] = (utility, sorted(self.selections.get(self._owner(message, utility))))
            edit_menu_message(message, "Kirim password extract. Password tidak dicatat di log.", utility_password_markup("cancel-password"))
        elif action == "default":
            folders = sorted(self.selections.get(self._owner(message, utility)))
            self._enqueue(message, utility, folders, None)
        elif action == "cancel":
            self._show_utility_menu(message)

    def handle_text(self, update: Update) -> bool:
        message = update.effective_message
        if message is None or not message.text:
            return False
        utility = self.pending_custom.pop((message.chat_id, ""), None)
        for key in list(self.pending_custom):
            if key[0] == message.chat_id:
                utility = self.pending_custom.pop(key); break
        if utility:
            try:
                self.folders.add(message.text.strip())
                folders = self.folders.list()
                selected = self.selections.retain(self._owner(message, utility), folders)
                self.panel.update_from_message(message, f"Utility: {utility}\nFolder dipilih: {len(selected)}", utility_folders_markup(utility, folders, selected))
            except UtilityPathError as exc:
                self.panel.update_from_message(message, str(exc), utility_password_markup("cancel-custom"))
            return True
        for (chat_id, name), (_, folders) in list(self.pending_password.items()):
            if chat_id == message.chat_id:
                self.pending_password.pop((chat_id, name), None)
                self._enqueue(message, name, folders, message.text)
                return True
        return False

    def _show_utility_menu(self, message: Message) -> None:
        edit_menu_message(message, "Pilih utility yang ingin dijalankan.", utility_menu_markup())

    def _show_folders(self, message: Message, utility: str) -> None:
        folders = self.folders.list(); owner = self._owner(message, utility)
        selected = self.selections.retain(owner, folders)
        edit_menu_message(message, f"Utility: {utility}\nFolder dipilih: {len(selected)}", utility_folders_markup(utility, folders, selected))

    def _toggle(self, message: Message, utility: str, index: str) -> None:
        folders = self.folders.list()
        try: self.selections.toggle(self._owner(message, utility), folders[int(index)])
        except (ValueError, IndexError): pass
        self._show_folders(message, utility)

    def _remove_selected(self, message: Message, utility: str) -> None:
        for folder in self.selections.get(self._owner(message, utility)):
            self.folders.remove(folder)
        self.selections.clear(self._owner(message, utility)); self._show_folders(message, utility)

    def _confirm(self, message: Message, utility: str) -> None:
        selected = sorted(self.selections.get(self._owner(message, utility)))
        if not selected:
            self._show_folders(message, utility); return
        edit_menu_message(message, f"Jalankan {utility} pada {len(selected)} folder?\n\n" + "\n".join(selected), utility_confirm_markup(utility))

    def _run(self, message: Message, utility: str) -> None:
        folders = sorted(self.selections.get(self._owner(message, utility)))
        if not folders: return self._show_folders(message, utility)
        if utility == "extract":
            edit_menu_message(message, "Pilih password extract.", utility_password_markup("extract"))
            return
        self._enqueue(message, utility, folders, None)

    def _enqueue(self, message: Message, utility: str, folders: list[str], password: str | None) -> None:
        profile = self.profile_manager.active_profile_for_chat(message.chat_id)
        panel_chat_id, panel_message_id = self.panel.update_from_message(
            message, f"{utility} masuk antrian untuk {len(folders)} folder.", main_menu_markup(profile)
        )
        token = self.panel.begin_view(panel_chat_id)
        self.worker.enqueue(utility, folders, profile, panel_chat_id, panel_message_id, token, password)
        self.selections.clear(self._owner(message, utility))

    @staticmethod
    def _owner(message: Message, utility: str) -> tuple[int, str]:
        return message.chat_id, normalize_profile_name(utility)
