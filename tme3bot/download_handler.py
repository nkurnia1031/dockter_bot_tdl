from __future__ import annotations

import threading
import time

from telegram import Bot, Message, Update
from telegram.ext import CallbackContext

from tme3bot.bot_keyboards import (
    clear_confirm_markup,
    download_settings_markup,
    download_status_markup,
    main_menu_markup,
)
from tme3bot.bot_panel import PanelManager, edit_menu_message, safe_edit_bot_message
from tme3bot.bot_text import download_settings_text, format_download_progress
from tme3bot.bot_workers import (
    STATUS_UPDATE_INTERVAL_SECONDS,
    DownloadQueueJob,
    DownloadQueueWorker,
)
from tme3bot.profiles import ProfileManager, describe_download_mode

DOWNLOAD_CALLBACKS = {
    "menu:download",
    "menu:retry",
    "menu:status",
    "status:refresh",
    "menu:cancel",
    "menu:clear_confirm",
    "menu:clear_yes",
    "download:settings",
}


class DownloadHandler:
    def __init__(
        self, bot: Bot, profile_manager: ProfileManager, panel: PanelManager
    ) -> None:
        self.bot = bot
        self.profile_manager = profile_manager
        self.panel = panel
        self.worker = DownloadQueueWorker(bot, profile_manager, panel)

    @staticmethod
    def handles_callback(data: str) -> bool:
        return data in DOWNLOAD_CALLBACKS or data.startswith("download:mode:")

    def start(self) -> None:
        self.worker.start()

    def download_command(self, update: Update, context: CallbackContext) -> None:
        del context
        self._queue_download_from_message(update.effective_message, retry_failed=False)

    def retry_failed_command(self, update: Update, context: CallbackContext) -> None:
        del context
        self._queue_download_from_message(update.effective_message, retry_failed=True)

    def clear_fail_command(self, update: Update, context: CallbackContext) -> None:
        del context
        message = update.effective_message
        profile_name = self.profile_manager.active_profile_for_chat(message.chat_id)
        deleted_count = self.profile_manager.runtime(
            profile_name
        ).download_service.clear_failed_exports()
        self.panel.update_from_message(
            message,
            f"[{profile_name}] Folder failed dibersihkan. JSON dihapus: {deleted_count}.",
            main_menu_markup(profile_name),
        )

    def download_status_command(self, update: Update, context: CallbackContext) -> None:
        del context
        message = update.effective_message
        profile_name = self.profile_manager.active_profile_for_chat(message.chat_id)
        runtime = self.profile_manager.runtime(profile_name)
        panel_chat_id, panel_message_id = self.panel.update_from_message(
            message,
            format_download_progress(
                runtime.download_progress.snapshot(),
                self.worker.queue_size(profile_name),
                profile_name=profile_name,
            ),
            download_status_markup(),
        )
        panel_view_token = self.panel.begin_view(panel_chat_id)
        self._start_passive_status_panel(
            profile_name, panel_chat_id, panel_message_id, panel_view_token
        )

    def cancel_download_command(self, update: Update, context: CallbackContext) -> None:
        del context
        message = update.effective_message
        profile_name = self.profile_manager.active_profile_for_chat(message.chat_id)
        self.panel.update_from_message(
            message,
            self._cancel_download_text(profile_name),
            main_menu_markup(profile_name),
        )

    def handle_callback(self, message: Message, data: str) -> None:
        profile_name = self.profile_manager.active_profile_for_chat(message.chat_id)
        runtime = self.profile_manager.runtime(profile_name)
        if data == "download:settings":
            edit_menu_message(
                message,
                download_settings_text(profile_name, self.profile_manager),
                download_settings_markup(profile_name, self.profile_manager),
            )
        elif data.startswith("download:mode:"):
            if runtime.download_progress.snapshot().active:
                edit_menu_message(
                    message,
                    "Download masih berjalan. Hentikan/tunggu selesai dulu sebelum mengganti mode path.",
                    download_settings_markup(profile_name, self.profile_manager),
                )
                return
            try:
                selected_mode = self.profile_manager.set_download_mode(
                    profile_name, data.split(":", 2)[2]
                )
            except ValueError as exc:
                edit_menu_message(
                    message,
                    str(exc),
                    download_settings_markup(profile_name, self.profile_manager),
                )
                return
            text = f"[{profile_name}] Mode download diubah ke: {describe_download_mode(selected_mode)}\n\n{download_settings_text(profile_name, self.profile_manager)}"
            edit_menu_message(
                message,
                text,
                download_settings_markup(profile_name, self.profile_manager),
            )
        elif data in {"menu:download", "menu:retry"}:
            retry_failed = data == "menu:retry"
            mode_text = "Retry JSON failed" if retry_failed else "Batch download"
            edit_menu_message(
                message,
                f"[{profile_name}] {mode_text} masuk antrian.",
                download_status_markup(),
            )
            panel_view_token = self.panel.begin_view(message.chat_id)
            position = self._enqueue(
                profile_name,
                message.chat_id,
                message.message_id,
                retry_failed,
                message.chat_id,
                message.message_id,
                panel_view_token,
            )
            if self.panel.is_view_active(message.chat_id, panel_view_token):
                edit_menu_message(
                    message,
                    f"[{profile_name}] {mode_text} masuk antrian #{position}.",
                    download_status_markup(),
                )
        elif data in {"menu:status", "status:refresh"}:
            text = format_download_progress(
                runtime.download_progress.snapshot(),
                self.worker.queue_size(profile_name),
                profile_name=profile_name,
            )
            edit_menu_message(message, text, download_status_markup())
            panel_view_token = self.panel.begin_view(message.chat_id)
            self._start_passive_status_panel(
                profile_name,
                message.chat_id,
                message.message_id,
                panel_view_token,
            )
        elif data == "menu:cancel":
            edit_menu_message(
                message,
                self._cancel_download_text(profile_name),
                main_menu_markup(profile_name),
            )
        elif data == "menu:clear_confirm":
            text = f"[{profile_name}] Yakin hapus semua JSON di folder failed? Ini hanya menghapus daftar gagal, bukan file download."
            edit_menu_message(message, text, clear_confirm_markup())
        elif data == "menu:clear_yes":
            deleted_count = runtime.download_service.clear_failed_exports()
            edit_menu_message(
                message,
                f"[{profile_name}] Folder failed dibersihkan. JSON dihapus: {deleted_count}.",
                main_menu_markup(profile_name),
            )

    def _queue_download_from_message(
        self, message: Message, retry_failed: bool
    ) -> None:
        profile_name = self.profile_manager.active_profile_for_chat(message.chat_id)
        mode_text = "Retry JSON failed" if retry_failed else "Batch download"
        panel_chat_id, panel_message_id = self.panel.update_from_message(
            message,
            f"[{profile_name}] {mode_text} masuk antrian.",
            download_status_markup(),
        )
        panel_view_token = self.panel.begin_view(panel_chat_id)
        position = self._enqueue(
            profile_name,
            message.chat_id,
            message.message_id,
            retry_failed,
            panel_chat_id,
            panel_message_id,
            panel_view_token,
        )
        if self.panel.is_view_active(panel_chat_id, panel_view_token):
            safe_edit_bot_message(
                self.bot,
                panel_chat_id,
                panel_message_id,
                f"[{profile_name}] {mode_text} masuk antrian #{position}.",
                download_status_markup(),
            )

    def _enqueue(
        self,
        profile_name: str,
        chat_id: int,
        reply_to_message_id: int,
        retry_failed: bool,
        panel_chat_id: int | None = None,
        panel_message_id: int | None = None,
        panel_view_token: int | None = None,
    ) -> int:
        return self.worker.enqueue(
            DownloadQueueJob(
                profile_name=profile_name,
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
                retry_failed=retry_failed,
                panel_chat_id=panel_chat_id,
                panel_message_id=panel_message_id,
                panel_view_token=panel_view_token,
            )
        )

    def _cancel_download_text(self, profile_name: str) -> str:
        cancelled = self.profile_manager.runtime(
            profile_name
        ).download_tdl_client.cancel_current()
        if cancelled:
            return f"[{profile_name}] Proses tdl download aktif sedang dihentikan. JSON batch akan masuk folder failed."
        return f"[{profile_name}] Tidak ada proses tdl download aktif untuk dihentikan."

    def _start_passive_status_panel(
        self,
        profile_name: str,
        chat_id: int,
        message_id: int,
        panel_view_token: int,
    ) -> None:
        progress_tracker = self.profile_manager.runtime(profile_name).download_progress
        if not progress_tracker.snapshot().active:
            return

        def update_loop() -> None:
            last_text = ""
            for _ in range(1800):
                if not self.panel.is_view_active(chat_id, panel_view_token):
                    return
                snapshot = progress_tracker.snapshot()
                text = format_download_progress(
                    snapshot,
                    self.worker.queue_size(profile_name),
                    profile_name=profile_name,
                )
                if text != last_text and safe_edit_bot_message(
                    self.bot,
                    chat_id,
                    message_id,
                    text,
                    download_status_markup(done=not snapshot.active),
                ):
                    last_text = text
                if not snapshot.active:
                    return
                time.sleep(STATUS_UPDATE_INTERVAL_SECONDS)

        threading.Thread(
            target=update_loop, daemon=True, name="tme3-passive-status-panel"
        ).start()
