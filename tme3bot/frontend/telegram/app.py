from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    Filters,
    MessageHandler,
    Updater,
)

from tme3bot.frontend.telegram.keyboards import (
    backup_menu_markup,
    check_profile_markup,
    clear_confirm_markup,
    download_status_markup,
    main_menu_markup,
    storage_delete_markup,
    storage_folders_markup,
    storage_item_markup,
    storage_menu_markup,
    utility_confirm_markup,
    utility_folders_markup,
    utility_menu_markup,
    utility_settings_markup,
    worker_menu_markup,
)
from tme3bot.frontend.telegram.panel import (
    PanelManager,
    edit_menu_message,
)
from tme3bot.frontend.telegram.text import help_text, source_digest
from tme3bot.frontend.client import BackendApiClient
from tme3bot.infrastructure.http_client import JsonHttpError

LOGGER = logging.getLogger(__name__)
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


@dataclass
class PendingInput:
    action: str
    data: dict[str, Any] = field(default_factory=dict)


class TelegramFrontendApp:
    """Telegram presentation adapter; all business actions use BackendApiClient."""

    def __init__(self, config, client: BackendApiClient | None = None) -> None:
        self.config = config
        self.client = client or BackendApiClient(
            config.backend_api_url, config.frontend_service_token
        )
        self.updater = Updater(
            token=config.bot_token, use_context=True, workers=2
        )
        self.panel = PanelManager(self.updater.bot)
        self.pending: dict[tuple[int, int], PendingInput] = {}
        self.utility_selected: dict[int, set[str]] = {}
        self.source_selected: dict[int, set[str]] = {}
        self._register()

    def start(self) -> None:
        self._set_commands()
        self.updater.start_polling(drop_pending_updates=True)
        LOGGER.info("Telegram frontend polling started")
        self.updater.idle()

    def _register(self) -> None:
        dispatcher = self.updater.dispatcher
        dispatcher.add_handler(CommandHandler("start", self.start_command))
        for command in ("menu", "panel"):
            dispatcher.add_handler(CommandHandler(command, self.menu_command))
        dispatcher.add_handler(CommandHandler("help", self.help_command))
        dispatcher.add_handler(CommandHandler("check_profil", self.check_command))
        dispatcher.add_handler(CommandHandler("download", self.download_command))
        dispatcher.add_handler(
            CommandHandler("download_status", self.download_status_command)
        )
        dispatcher.add_handler(
            CommandHandler("retry_failed", self.retry_download_command)
        )
        dispatcher.add_handler(
            CommandHandler("clear_fail", self.clear_failed_command)
        )
        dispatcher.add_handler(
            CommandHandler("cancel_download", self.cancel_download_command)
        )
        dispatcher.add_handler(CommandHandler("utility", self.utility_command))
        dispatcher.add_handler(CommandHandler("storage", self.storage_command))
        dispatcher.add_handler(CommandHandler("backup", self.backup_command))
        dispatcher.add_handler(CommandHandler("worker", self.worker_command))
        dispatcher.add_handler(CommandHandler("profile", self.profile_command))
        dispatcher.add_handler(CommandHandler("profiles", self.profile_command))
        dispatcher.add_handler(CallbackQueryHandler(self.handle_callback))
        dispatcher.add_handler(
            MessageHandler(Filters.text & (~Filters.command), self.handle_text)
        )
        dispatcher.add_handler(MessageHandler(Filters.command, self.unknown_command))
        dispatcher.add_error_handler(self.error_handler)

    def error_handler(self, update: object, context: CallbackContext) -> None:
        error = context.error or RuntimeError("Unknown Telegram handler error")
        LOGGER.error(
            "Telegram frontend handler failed",
            exc_info=(type(error), error, error.__traceback__),
        )
        message = getattr(update, "effective_message", None)
        if message is not None:
            self._show_error(message, error)

    def _set_commands(self) -> None:
        commands = [
            BotCommand("menu", "Buka menu"),
            BotCommand("check_profil", "Cek identity"),
            BotCommand("utility", "Utility workspace"),
            BotCommand("storage", "Storage channel"),
            BotCommand("backup", "Backup runtime"),
            BotCommand("worker", "Pilih worker"),
            BotCommand("download", "Download JSON pending"),
            BotCommand("download_status", "Status job download"),
            BotCommand("retry_failed", "Retry JSON failed"),
            BotCommand("clear_fail", "Hapus JSON failed"),
            BotCommand("cancel_download", "Batalkan download"),
            BotCommand("help", "Bantuan"),
        ]
        try:
            self.updater.bot.set_my_commands(commands)
        except Exception:
            LOGGER.exception("Could not set Telegram commands")

    def start_command(self, update: Update, context: CallbackContext) -> None:
        payload = context.args[0] if context.args else ""
        if payload.startswith("login_") and update.effective_user:
            code = payload[len("login_") :]
            try:
                self.client.approve_login(code, update.effective_user.id)
                self.panel.update_from_message(
                    update.effective_message,
                    "Login web berhasil disetujui. Kembali ke browser untuk melanjutkan.",
                    check_profile_markup(),
                )
            except Exception as exc:
                self._show_error(update.effective_message, exc)
            return
        if payload.startswith("storage_") and update.effective_user:
            token = payload[len("storage_") :]
            try:
                result = self.client.post(
                    update.effective_user.id,
                    f"/api/v1/storage/deep-links/{quote(token, safe='.')}/deliver",
                )
                self.panel.update_from_message(
                    update.effective_message,
                    f"File dikirim: {result.get('display_name', 'storage')}",
                    storage_menu_markup(),
                )
            except Exception as exc:
                self._show_error(update.effective_message, exc)
            return
        self.menu_command(update, context)

    def menu_command(self, update: Update, context: CallbackContext) -> None:
        del context
        actor = self._actor(update)
        if actor is None:
            return
        self.panel.update_from_message(
            update.effective_message,
            "Menu bot:",
            main_menu_markup(actor["profile"]),
        )

    def help_command(self, update: Update, context: CallbackContext) -> None:
        del context
        actor = self._actor(update)
        if actor is None:
            return
        self.panel.update_from_message(
            update.effective_message,
            help_text(self.config.tme3_host),
            main_menu_markup(actor["profile"]),
        )

    def check_command(self, update: Update, context: CallbackContext) -> None:
        del context
        actor = self._actor(update)
        if actor is not None:
            self.panel.update_from_message(
                update.effective_message,
                f"Profile ditemukan: {actor['profile']}. Backend API terhubung.",
                main_menu_markup(actor["profile"]),
            )

    def profile_command(self, update: Update, context: CallbackContext) -> None:
        del context
        actor = self._actor(update)
        if actor is not None:
            self.panel.update_from_message(
                update.effective_message,
                f"Profile otomatis: {actor['profile']}\nWorker: {actor['worker_route']}\nMode download: {actor['download_mode']}",
                main_menu_markup(actor["profile"]),
            )

    def worker_command(self, update: Update, context: CallbackContext) -> None:
        del context
        actor = self._actor(update)
        if actor is not None:
            self._show_workers(update.effective_message, update.effective_user.id, actor)

    def utility_command(self, update: Update, context: CallbackContext) -> None:
        del context
        if self._actor(update) is not None:
            self.panel.update_from_message(
                update.effective_message, "Pilih utility.", utility_menu_markup()
            )

    def storage_command(self, update: Update, context: CallbackContext) -> None:
        del context
        if self._actor(update) is not None:
            self.panel.update_from_message(
                update.effective_message,
                "Pilih menu storage channel.",
                storage_menu_markup(),
            )

    def backup_command(self, update: Update, context: CallbackContext) -> None:
        del context
        if self._actor(update) is not None:
            self.panel.update_from_message(
                update.effective_message,
                "Backup runtime terenkripsi per-node.",
                backup_menu_markup(),
            )

    def download_command(self, update: Update, context: CallbackContext) -> None:
        del context
        self._submit_download(update, retry=False)

    def retry_download_command(
        self, update: Update, context: CallbackContext
    ) -> None:
        del context
        self._submit_download(update, retry=True)

    def download_status_command(
        self, update: Update, context: CallbackContext
    ) -> None:
        del context
        actor = self._actor(update)
        if actor is not None:
            self._show_download_status(
                update.effective_message, update.effective_user.id, actor
            )

    def clear_failed_command(
        self, update: Update, context: CallbackContext
    ) -> None:
        del context
        actor = self._actor(update)
        if actor is None:
            return
        try:
            job = self.client.post(
                update.effective_user.id, "/api/v1/downloads/clear-failed"
            )
            self._show_job(update.effective_message, update.effective_user.id, job)
        except Exception as exc:
            self._show_error(update.effective_message, exc)

    def cancel_download_command(
        self, update: Update, context: CallbackContext
    ) -> None:
        del context
        actor = self._actor(update)
        if actor is not None:
            self._cancel_latest_download(
                update.effective_message, update.effective_user.id, actor
            )

    def unknown_command(self, update: Update, context: CallbackContext) -> None:
        self.menu_command(update, context)

    def handle_callback(self, update: Update, context: CallbackContext) -> None:
        del context
        query = update.callback_query
        if query is None or query.message is None or query.data is None:
            return
        query.answer()
        user_id = update.effective_user.id if update.effective_user else 0
        actor = self._actor(update)
        if actor is None:
            return
        message, data = query.message, query.data
        self.panel.remember(message)
        self.panel.invalidate_view(message.chat_id)
        try:
            if data in {"menu:main", "access:check"}:
                edit_menu_message(
                    message, "Menu bot:", main_menu_markup(actor["profile"])
                )
            elif data in {"menu:help"}:
                edit_menu_message(
                    message,
                    help_text(self.config.tme3_host),
                    main_menu_markup(actor["profile"]),
                )
            elif data in {"profile:info", "profiles:list"} or data.startswith(
                "profile:"
            ):
                edit_menu_message(
                    message,
                    f"Profile otomatis: {actor['profile']}\nWorker: {actor['worker_route']}",
                    main_menu_markup(actor["profile"]),
                )
            elif data.startswith("worker:"):
                self._worker_callback(message, user_id, actor, data)
            elif data.startswith("backup:"):
                self._backup_callback(message, user_id, data)
            elif data.startswith("storage:"):
                self._storage_callback(message, user_id, data)
            elif data.startswith("utility:"):
                self._utility_callback(message, user_id, data)
            elif data.startswith(("sources:", "src:", "srcsel:", "srcbatch:", "srcdel:", "export:")):
                self._source_callback(message, user_id, actor, data)
            elif data in {
                "menu:download",
                "menu:retry",
                "menu:status",
                "status:refresh",
                "menu:cancel",
                "menu:clear_confirm",
                "menu:clear_yes",
                "download:settings",
            } or data.startswith("download:mode:"):
                self._download_callback(message, user_id, actor, data)
            else:
                edit_menu_message(
                    message,
                    "Menu tidak dikenal.",
                    main_menu_markup(actor["profile"]),
                )
        except Exception as exc:
            self._show_error(message, exc)

    def handle_text(self, update: Update, context: CallbackContext) -> None:
        del context
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or not message.text:
            return
        actor = self._actor(update)
        if actor is None:
            return
        key = (message.chat_id, user.id)
        pending = self.pending.pop(key, None)
        try:
            if pending is not None:
                self._handle_pending(message, user.id, actor, pending, message.text.strip())
                return
            job = self.client.post(
                user.id,
                "/api/v1/exports",
                {"url": message.text.strip(), "use_url_message_id": True},
            )
            self._show_job(message, user.id, job)
        except Exception as exc:
            self._show_error(message, exc)

    def _actor(self, update: Update) -> dict[str, Any] | None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return None
        try:
            return self.client.me(user.id)
        except Exception:
            self.panel.update_from_message(
                message,
                "Akses terbatas. Identity sesi TDL untuk user ini belum ditemukan atau backend tidak dapat dihubungi.",
                check_profile_markup(),
            )
            return None

    def _worker_callback(
        self, message, user_id: int, actor: dict[str, Any], data: str
    ) -> None:
        if data.startswith("worker:set:"):
            route = data.split(":", 2)[2]
            self.client.put(user_id, "/api/v1/me/worker-route", {"route": route})
            actor = self.client.me(user_id)
        self._show_workers(message, user_id, actor)

    def _show_workers(
        self, message, user_id: int, actor: dict[str, Any]
    ) -> None:
        workers = self.client.get(user_id, "/api/v1/workers").get("items", [])
        routes = [str(item["name"]) for item in workers]
        edit_menu_message(
            message,
            f"[{actor['profile']}] Worker aktif: {actor['worker_route']}\nPergantian worker berlaku untuk job baru; job aktif tetap berada di worker asalnya.",
            worker_menu_markup(actor["profile"], actor["worker_route"], routes),
        )

    def _backup_callback(self, message, user_id: int, data: str) -> None:
        action = data.split(":", 1)[1]
        if action == "menu":
            edit_menu_message(
                message, "Backup runtime terenkripsi per-node.", backup_menu_markup()
            )
        elif action == "now":
            result = self.client.post(user_id, "/api/v1/backups")
            edit_menu_message(
                message,
                f"Backup dimulai. Run ID: {result['run_id']}",
                backup_menu_markup(),
            )
        else:
            status = self.client.get(user_id, "/api/v1/backups/status")
            lines = [
                "Status backup:",
                f"Aktif: {'ya' if status['enabled'] else 'tidak'}",
                f"Jadwal: {status['schedule']} ({status['timezone']})",
                f"Retensi: {status['retention']}",
                f"Ukuran part: {status['volume_size']}",
            ]
            for item in status.get("items", [])[:15]:
                lines.append(
                    f"{item['node_name']} | {item['status']} | {item['started_at']}"
                )
            edit_menu_message(message, "\n".join(lines), backup_menu_markup())

    def _storage_callback(self, message, user_id: int, data: str) -> None:
        if data == "storage:menu":
            edit_menu_message(message, "Pilih menu storage.", storage_menu_markup())
        elif data == "storage:upload":
            folders = self.client.get(
                user_id, "/api/v1/utility/folders"
            ).get("items", [])
            self.pending[(message.chat_id, user_id)] = PendingInput(
                "storage_choose_folder", {"folders": folders}
            )
            edit_menu_message(
                message, "Pilih folder workspace.", storage_folders_markup(folders)
            )
        elif data.startswith("storage:folder:"):
            folders = self.client.get(
                user_id, "/api/v1/utility/folders"
            ).get("items", [])
            index = int(data.rsplit(":", 1)[1])
            folder_path = folders[index]
            self.pending[(message.chat_id, user_id)] = PendingInput(
                "storage_folder_name", {"folder_path": folder_path}
            )
            edit_menu_message(
                message,
                "Ketik nama folder logis storage.",
                storage_menu_markup(),
            )
        elif data == "storage:search":
            self.pending[(message.chat_id, user_id)] = PendingInput("storage_search")
            edit_menu_message(
                message, "Ketik nama, folder, keyword, atau caption.", storage_menu_markup()
            )
        elif data == "storage:mine":
            self._show_storage_results(message, user_id, "", mine=True)
        elif data == "storage:settings":
            settings = self.client.get(user_id, "/api/v1/storage/settings")
            edit_menu_message(
                message,
                f"Storage channel\nID: {settings.get('channel', '-')}\nNama: {settings.get('title', '-')}",
                storage_menu_markup(),
            )
        elif data.startswith("storage:detail:"):
            self._show_storage_detail(message, user_id, int(data.rsplit(":", 1)[1]))
        elif data.startswith("storage:download:"):
            item_id = int(data.rsplit(":", 1)[1])
            self.client.post(
                user_id,
                f"/api/v1/storage/items/{item_id}/deliveries",
                {"method": "telegram"},
            )
            edit_menu_message(
                message, "File dikirim ke chat ini.", storage_menu_markup()
            )
        elif data.startswith(("storage:rename:", "storage:folder_edit:", "storage:keyword_edit:")):
            prefix, item_id = data.rsplit(":", 1)
            action = {
                "storage:rename": "storage_rename",
                "storage:folder_edit": "storage_folder_edit",
                "storage:keyword_edit": "storage_keyword_edit",
            }[prefix]
            self.pending[(message.chat_id, user_id)] = PendingInput(
                action, {"item_id": int(item_id)}
            )
            edit_menu_message(message, "Ketik nilai metadata baru.", storage_menu_markup())
        elif data.startswith("storage:delete:"):
            item_id = int(data.rsplit(":", 1)[1])
            edit_menu_message(
                message,
                "Hapus file dari channel dan katalog?",
                storage_delete_markup(item_id),
            )
        elif data.startswith("storage:delete_yes:"):
            item_id = int(data.rsplit(":", 1)[1])
            self.client.delete(user_id, f"/api/v1/storage/items/{item_id}")
            edit_menu_message(message, "File storage dihapus.", storage_menu_markup())

    def _show_storage_results(
        self, message, user_id: int, query: str, *, mine: bool = False
    ) -> None:
        items = self.client.get(
            user_id,
            "/api/v1/storage/items",
            {"q": query, "mine": str(mine).lower(), "limit": 10},
        ).get("items", [])
        if not items:
            edit_menu_message(message, "File tidak ditemukan.", storage_menu_markup())
            return
        lines, rows = ["Hasil storage:"] , []
        for item in items:
            lines.append(
                f"{item['id']}. {item['display_name']}\n   Folder: {item.get('folder') or '-'}"
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        str(item["display_name"])[:55],
                        callback_data=f"storage:detail:{item['id']}",
                    )
                ]
            )
        rows.append([InlineKeyboardButton("Kembali", callback_data="storage:menu")])
        edit_menu_message(message, "\n".join(lines), InlineKeyboardMarkup(rows))

    def _show_storage_detail(self, message, user_id: int, item_id: int) -> None:
        item = self.client.get(user_id, f"/api/v1/storage/items/{item_id}")
        owner = int(item["owner_user_id"]) == int(user_id)
        text = (
            f"Nama tampilan: {item['display_name']}\n"
            f"Nama asli: {item['original_name']}\n"
            f"Folder: {item.get('folder') or '-'}\n"
            f"Keyword: {item.get('keywords') or '-'}\n"
            f"Ukuran: {item.get('file_size', 0)} byte"
        )
        edit_menu_message(message, text, storage_item_markup(item_id, owner))

    def _utility_callback(self, message, user_id: int, data: str) -> None:
        if data == "utility:menu":
            edit_menu_message(message, "Pilih utility.", utility_menu_markup())
        elif data == "utility:settings":
            values = self.client.get(user_id, "/api/v1/utility/settings")
            edit_menu_message(
                message, "Pengaturan default utility.", utility_settings_markup(values)
            )
        elif data.startswith("utility:setting:"):
            key = data.split(":", 2)[2]
            self.pending[(message.chat_id, user_id)] = PendingInput(
                "utility_setting", {"key": key}
            )
            edit_menu_message(message, f"Ketik nilai baru untuk {key}.", utility_menu_markup())
        elif data.startswith("utility:folders:"):
            utility = data.rsplit(":", 1)[1]
            self._show_utility_folders(message, user_id, utility)
        elif data.startswith("utility:select:"):
            _, _, utility, raw_index = data.split(":", 3)
            folders = self.client.get(
                user_id, "/api/v1/utility/folders"
            ).get("items", [])
            folder = folders[int(raw_index)]
            selected = self.utility_selected.setdefault(user_id, set())
            selected.remove(folder) if folder in selected else selected.add(folder)
            self._show_utility_folders(message, user_id, utility)
        elif data.startswith("utility:all:"):
            utility = data.rsplit(":", 1)[1]
            folders = self.client.get(
                user_id, "/api/v1/utility/folders"
            ).get("items", [])
            self.utility_selected[user_id] = set(folders)
            self._show_utility_folders(message, user_id, utility)
        elif data.startswith("utility:clear:"):
            utility = data.rsplit(":", 1)[1]
            self.utility_selected[user_id] = set()
            self._show_utility_folders(message, user_id, utility)
        elif data.startswith("utility:ask:"):
            utility = data.rsplit(":", 1)[1]
            edit_menu_message(
                message,
                f"Jalankan {utility} untuk {len(self.utility_selected.get(user_id, set()))} folder?",
                utility_confirm_markup(utility),
            )
        elif data.startswith("utility:run:"):
            utility = data.rsplit(":", 1)[1]
            self._submit_utility(message, user_id, utility)
        elif data.startswith("utility:add:"):
            utility = data.rsplit(":", 1)[1]
            self.pending[(message.chat_id, user_id)] = PendingInput(
                "utility_add_folder", {"utility": utility}
            )
            edit_menu_message(message, "Ketik path folder di dalam workspace.", utility_menu_markup())
        elif data.startswith("utility:remove:"):
            utility = data.rsplit(":", 1)[1]
            for folder in list(self.utility_selected.get(user_id, set())):
                self.client.delete(
                    user_id, "/api/v1/utility/folders", {"path": folder}
                )
            self.utility_selected[user_id] = set()
            self._show_utility_folders(message, user_id, utility)

    def _show_utility_folders(self, message, user_id: int, utility: str) -> None:
        folders = self.client.get(user_id, "/api/v1/utility/folders").get("items", [])
        selected = self.utility_selected.setdefault(user_id, set())
        selected.intersection_update(folders)
        edit_menu_message(
            message,
            f"Pilih folder untuk {utility}.",
            utility_folders_markup(utility, folders, selected),
        )

    def _submit_utility(self, message, user_id: int, utility: str) -> None:
        folders = sorted(self.utility_selected.get(user_id, set()))
        job = self.client.post(
            user_id,
            "/api/v1/utility/jobs",
            {"utility": utility, "folders": folders, "password": None},
        )
        self._show_job(message, user_id, job)

    def _source_callback(
        self, message, user_id: int, actor: dict[str, Any], data: str
    ) -> None:
        if data.startswith("sources:"):
            self._show_sources(message, user_id)
            return
        if data.startswith("srcbatch:"):
            action = data.split(":", 2)[1]
            selected = self.source_selected.setdefault(user_id, set())
            if action == "all":
                selected.update(
                    item["chat_ref"]
                    for item in self.client.get(user_id, "/api/v1/sources").get("items", [])
                )
                self._show_sources(message, user_id)
            elif action == "clear":
                selected.clear()
                self._show_sources(message, user_id)
            elif action in {"yes", "leave_yes"}:
                endpoint = (
                    "/api/v1/sources/batch-delete"
                    if action == "yes"
                    else "/api/v1/sources/leave"
                )
                result = self.client.post(user_id, endpoint, {"chat_refs": sorted(selected)})
                selected.clear()
                if "id" in result:
                    self._show_job(message, user_id, result)
                else:
                    self._show_sources(message, user_id)
            else:
                rows = [
                    [
                        InlineKeyboardButton(
                            "Ya",
                            callback_data=f"srcbatch:{'leave_yes' if action == 'leave' else 'yes'}:0",
                        )
                    ],
                    [InlineKeyboardButton("Batal", callback_data="sources:0")],
                ]
                edit_menu_message(
                    message,
                    f"Proses {len(selected)} source terpilih?",
                    InlineKeyboardMarkup(rows),
                )
            return
        digest = data.split(":", 2)[1] if ":" in data else ""
        source = self._source_by_digest(user_id, digest)
        if source is None:
            edit_menu_message(message, "Source tidak ditemukan.", main_menu_markup(actor["profile"]))
            return
        chat_ref = str(source["chat_ref"])
        if data.startswith("srcsel:"):
            selected = self.source_selected.setdefault(user_id, set())
            selected.remove(chat_ref) if chat_ref in selected else selected.add(chat_ref)
            self._show_sources(message, user_id)
        elif data.startswith("srcdel:"):
            action = data.rsplit(":", 1)[1]
            if action == "yes":
                self.client.delete(
                    user_id, f"/api/v1/sources/{quote(chat_ref, safe='')}"
                )
                self._show_sources(message, user_id)
            else:
                edit_menu_message(
                    message,
                    f"Hapus source {chat_ref}?",
                    InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "Ya", callback_data=f"srcdel:{digest}:yes"
                                )
                            ],
                            [
                                InlineKeyboardButton(
                                    "Batal", callback_data=f"src:{digest}"
                                )
                            ],
                        ]
                    ),
                )
        elif data.startswith("export:"):
            mode = data.split(":", 2)[2]
            if mode == "custom":
                self.pending[(message.chat_id, user_id)] = PendingInput(
                    "source_label", {"source": source}
                )
                edit_menu_message(message, "Ketik label export.", main_menu_markup(actor["profile"]))
            else:
                self._submit_source_export(message, user_id, source, None)
        else:
            rows = [
                [
                    InlineKeyboardButton(
                        "Export tanpa label", callback_data=f"export:{digest}:plain"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Label custom", callback_data=f"export:{digest}:custom"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Hapus source", callback_data=f"srcdel:{digest}:ask"
                    )
                ],
                [InlineKeyboardButton("Kembali", callback_data="sources:0")],
            ]
            edit_menu_message(
                message,
                f"Source: {chat_ref}\nLast ID: {source['last_id']}\nLabel: {source.get('label') or '-'}",
                InlineKeyboardMarkup(rows),
            )

    def _show_sources(self, message, user_id: int) -> None:
        items = self.client.get(user_id, "/api/v1/sources").get("items", [])
        selected = self.source_selected.setdefault(user_id, set())
        selected.intersection_update(item["chat_ref"] for item in items)
        if not items:
            edit_menu_message(message, "Belum ada source.", main_menu_markup())
            return
        rows = []
        for item in items[:30]:
            digest = source_digest(str(item["chat_ref"]))
            mark = "[x]" if item["chat_ref"] in selected else "[ ]"
            rows.append(
                [
                    InlineKeyboardButton(
                        mark, callback_data=f"srcsel:{digest}:0"
                    ),
                    InlineKeyboardButton(
                        str(item["chat_ref"])[:50], callback_data=f"src:{digest}"
                    ),
                ]
            )
        rows.extend(
            [
                [
                    InlineKeyboardButton("Pilih semua", callback_data="srcbatch:all:0"),
                    InlineKeyboardButton("Reset", callback_data="srcbatch:clear:0"),
                ],
                [
                    InlineKeyboardButton("Hapus", callback_data="srcbatch:ask:0"),
                    InlineKeyboardButton("Leave", callback_data="srcbatch:leave:0"),
                ],
                [InlineKeyboardButton("Kembali", callback_data="menu:main")],
            ]
        )
        edit_menu_message(
            message,
            f"Source tersimpan: {len(items)}\nDipilih: {len(selected)}",
            InlineKeyboardMarkup(rows),
        )

    def _source_by_digest(self, user_id: int, digest: str):
        for item in self.client.get(user_id, "/api/v1/sources").get("items", []):
            if source_digest(str(item["chat_ref"])) == digest:
                return item
        return None

    def _submit_source_export(
        self, message, user_id: int, source: dict[str, Any], label: str | None
    ) -> None:
        start_id = max(1, int(source.get("last_id", 0)) + 1)
        url = f"https://{self.config.tme3_host}/c/{source['chat_ref']}/{start_id}"
        if label:
            url += "/" + quote(label, safe="")
        job = self.client.post(
            user_id,
            "/api/v1/exports",
            {"url": url, "use_url_message_id": False},
        )
        self._show_job(message, user_id, job)

    def _download_callback(
        self, message, user_id: int, actor: dict[str, Any], data: str
    ) -> None:
        if data in {"menu:download", "menu:retry"}:
            job = self.client.post(
                user_id,
                "/api/v1/downloads"
                + ("?retry_failed=true" if data == "menu:retry" else ""),
            )
            self._show_job(message, user_id, job, download_status_markup())
        elif data in {"menu:status", "status:refresh"}:
            self._show_download_status(message, user_id, actor)
        elif data == "menu:cancel":
            self._cancel_latest_download(message, user_id, actor)
        elif data == "menu:clear_confirm":
            edit_menu_message(
                message, "Hapus seluruh JSON failed?", clear_confirm_markup()
            )
        elif data == "menu:clear_yes":
            job = self.client.post(user_id, "/api/v1/downloads/clear-failed")
            self._show_job(message, user_id, job)
        elif data == "download:settings":
            self._show_download_settings(message, actor)
        elif data.startswith("download:mode:"):
            mode = data.split(":", 2)[2]
            self.client.put(user_id, f"/api/v1/downloads/mode/{mode}", {})
            actor = self.client.me(user_id)
            self._show_download_settings(message, actor)

    def _show_download_settings(self, message, actor: dict[str, Any]) -> None:
        mode = actor["download_mode"]
        rows = [
            [
                InlineKeyboardButton(
                    ("* " if mode == "shared" else "") + "Download utama",
                    callback_data="download:mode:shared",
                )
            ],
            [
                InlineKeyboardButton(
                    ("* " if mode == "isolated" else "") + "Terpisah profile",
                    callback_data="download:mode:isolated",
                )
            ],
            [InlineKeyboardButton("Kembali", callback_data="menu:main")],
        ]
        edit_menu_message(
            message,
            f"[{actor['profile']}] Mode download: {mode}",
            InlineKeyboardMarkup(rows),
        )

    def _submit_download(self, update: Update, retry: bool) -> None:
        actor = self._actor(update)
        if actor is None:
            return
        try:
            job = self.client.post(
                update.effective_user.id,
                "/api/v1/downloads" + ("?retry_failed=true" if retry else ""),
            )
            self._show_job(
                update.effective_message,
                update.effective_user.id,
                job,
                download_status_markup(),
            )
        except Exception as exc:
            self._show_error(update.effective_message, exc)

    def _show_download_status(
        self, message, user_id: int, actor: dict[str, Any]
    ) -> None:
        jobs = self.client.get(user_id, "/api/v1/jobs", {"limit": 50}).get(
            "items", []
        )
        downloads = [
            item
            for item in jobs
            if item["kind"] in {"download", "download_clear_failed"}
        ]
        if not downloads:
            edit_menu_message(
                message,
                f"[{actor['profile']}] Belum ada job download.",
                download_status_markup(done=True),
            )
            return
        job = downloads[0]
        chat_id, message_id = self.panel.update_from_message(
            message,
            self._job_text(job),
            download_status_markup(job["status"] in TERMINAL_JOB_STATUSES),
        )
        if job["status"] not in TERMINAL_JOB_STATUSES:
            self._poll_job(chat_id, message_id, user_id, job["id"])

    def _cancel_latest_download(
        self, message, user_id: int, actor: dict[str, Any]
    ) -> None:
        jobs = self.client.get(user_id, "/api/v1/jobs", {"limit": 50}).get(
            "items", []
        )
        active = next(
            (
                item
                for item in jobs
                if item["kind"] == "download"
                and item["status"] not in TERMINAL_JOB_STATUSES
            ),
            None,
        )
        if active is None:
            edit_menu_message(
                message,
                f"[{actor['profile']}] Tidak ada download aktif.",
                main_menu_markup(actor["profile"]),
            )
            return
        job = self.client.post(user_id, f"/api/v1/jobs/{active['id']}/cancel")
        edit_menu_message(message, self._job_text(job), main_menu_markup(actor["profile"]))

    def _handle_pending(
        self,
        message,
        user_id: int,
        actor: dict[str, Any],
        pending: PendingInput,
        value: str,
    ) -> None:
        action = pending.action
        if value.lower() in {"batal", "cancel"}:
            edit_menu_message(message, "Input dibatalkan.", main_menu_markup(actor["profile"]))
        elif action == "storage_folder_name":
            self.pending[(message.chat_id, user_id)] = PendingInput(
                "storage_keywords",
                {**pending.data, "folder": value},
            )
            edit_menu_message(
                message,
                "Ketik keyword dipisahkan koma, atau '-' jika kosong.",
                storage_menu_markup(),
            )
        elif action == "storage_keywords":
            payload = {
                **pending.data,
                "keywords": "" if value == "-" else value,
            }
            job = self.client.post(
                user_id, "/api/v1/storage/uploads", payload
            )
            self._show_job(message, user_id, job)
        elif action == "storage_search":
            self._show_storage_results(message, user_id, value)
        elif action in {
            "storage_rename",
            "storage_folder_edit",
            "storage_keyword_edit",
        }:
            field = {
                "storage_rename": "display_name",
                "storage_folder_edit": "folder",
                "storage_keyword_edit": "keywords",
            }[action]
            item = self.client.patch(
                user_id,
                f"/api/v1/storage/items/{pending.data['item_id']}",
                {field: value},
            )
            self._show_storage_detail(message, user_id, int(item["id"]))
        elif action == "utility_setting":
            values = self.client.put(
                user_id,
                f"/api/v1/utility/settings/{pending.data['key']}",
                {"value": value},
            )
            edit_menu_message(
                message, "Pengaturan disimpan.", utility_settings_markup(values)
            )
        elif action == "utility_add_folder":
            self.client.post(
                user_id, "/api/v1/utility/folders", {"path": value}
            )
            self._show_utility_folders(
                message, user_id, str(pending.data["utility"])
            )
        elif action == "source_label":
            self.client.post(user_id, "/api/v1/labels", {"label": value})
            self._submit_source_export(
                message, user_id, pending.data["source"], value
            )

    def _show_job(
        self, message, user_id: int, job: dict[str, Any], markup=None
    ) -> None:
        markup = markup or main_menu_markup(job.get("profile"))
        chat_id, message_id = self.panel.update_from_message(
            message, self._job_text(job), markup
        )
        token = self.panel.begin_view(chat_id)
        if job["status"] not in TERMINAL_JOB_STATUSES:
            self._poll_job(chat_id, message_id, user_id, job["id"], token, markup)

    def _poll_job(
        self,
        chat_id: int,
        message_id: int,
        user_id: int,
        job_id: str,
        panel_token: int | None = None,
        markup=None,
    ) -> None:
        del message_id
        panel_token = panel_token or self.panel.begin_view(chat_id)

        def loop() -> None:
            last = ""
            for _ in range(10800):
                if not self.panel.is_view_active(chat_id, panel_token):
                    return
                try:
                    job = self.client.get(user_id, f"/api/v1/jobs/{job_id}")
                    text = self._job_text(job)
                    if text != last:
                        if not self.panel.is_view_active(chat_id, panel_token):
                            return
                        self.panel.update(
                            chat_id,
                            text,
                            markup or main_menu_markup(job.get("profile")),
                        )
                        last = text
                    if job["status"] in TERMINAL_JOB_STATUSES:
                        return
                except Exception:
                    LOGGER.exception("Job polling failed for %s", job_id)
                time.sleep(2)

        threading.Thread(
            target=loop,
            daemon=True,
            name=f"telegram-job-poll-{job_id[:8]}",
        ).start()

    @staticmethod
    def _job_text(job: dict[str, Any]) -> str:
        progress = job.get("progress") or {}
        lines = [
            f"[{job.get('profile', '-')}] Job {job.get('kind', '-')}",
            f"Status: {job.get('status', '-')}",
            f"ID: {str(job.get('id', ''))[:12]}",
        ]
        if progress.get("current") is not None:
            lines.append(
                f"Progress: {progress.get('current')}/{progress.get('total', '?')}"
            )
        if progress.get("message"):
            lines.append(f"Saat ini: {progress['message']}")
        if job.get("error"):
            lines.append(f"Error: {job['error'].get('message', job['error'])}")
        if job.get("result"):
            value = str(job["result"].get("value", job["result"]))
            lines.append(f"Hasil: {value[:1200]}")
        return "\n".join(lines)

    def _show_error(self, message, exc: Exception) -> None:
        if message is None:
            return
        if isinstance(exc, JsonHttpError):
            detail = str(exc)
        else:
            detail = str(exc)
        try:
            self.panel.update_from_message(
                message, f"Operasi gagal: {detail[:1000]}", check_profile_markup()
            )
        except Exception:
            LOGGER.exception("Could not display frontend error")
