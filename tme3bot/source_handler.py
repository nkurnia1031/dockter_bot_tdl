from __future__ import annotations

from dataclasses import dataclass

from telegram import Message, Update

from tme3bot.bot_keyboards import (
    batch_delete_source_confirm_markup,
    batch_leave_source_confirm_markup,
    delete_source_confirm_markup,
    label_prompt_markup,
    main_menu_markup,
    source_detail_markup,
    sources_menu_markup,
)
from tme3bot.bot_panel import PanelManager, edit_menu_message, safe_edit_bot_message
from tme3bot.bot_text import (
    build_tme3_url,
    parse_callback_int,
    parse_int,
    source_digest,
)
from tme3bot.bot_workers import ExportQueueJob, ExportQueueWorker, LeaveQueueJob
from tme3bot.config import AppConfig
from tme3bot.labels import LabelStore
from tme3bot.profiles import ProfileManager
from tme3bot.source_selection import SourceSelectionStore
from tme3bot.state import SourceState

SOURCE_CALLBACK_PREFIXES = (
    "sources:",
    "src:",
    "srcsel:",
    "srcbatch:",
    "srcdel:",
    "export:",
)


@dataclass(frozen=True)
class PendingLabelRequest:
    chat_ref: str
    bootstrap_message_id: int


class SourceHandler:
    def __init__(
        self,
        config: AppConfig,
        profile_manager: ProfileManager,
        label_store: LabelStore,
        export_worker: ExportQueueWorker,
        panel: PanelManager,
    ) -> None:
        self.config = config
        self.profile_manager = profile_manager
        self.label_store = label_store
        self.export_worker = export_worker
        self.panel = panel
        self.selections = SourceSelectionStore()
        self.pending_labels: dict[tuple[int, int], PendingLabelRequest] = {}

    @staticmethod
    def handles_callback(data: str) -> bool:
        return data.startswith(SOURCE_CALLBACK_PREFIXES)

    def handle_callback(self, update: Update, data: str) -> None:
        query = update.callback_query
        if query is None or query.message is None:
            return
        if data.startswith("export:"):
            self._handle_export_callback(update, data)
        else:
            self._handle_source_callback(query.message, data)

    def handle_pending_label(self, update: Update) -> bool:
        message = update.effective_message
        if message is None or message.text is None:
            return False
        key = pending_key(update)
        pending = self.pending_labels.get(key)
        if pending is None:
            return False

        profile_name = self.profile_manager.active_profile_for_chat(message.chat_id)
        label = message.text.strip()
        if label.lower() in {"batal", "cancel"}:
            self.pending_labels.pop(key, None)
            self.panel.update_from_message(
                message, "Input label dibatalkan.", main_menu_markup(profile_name)
            )
            return True
        if not label:
            self.panel.update_from_message(
                message,
                "Label kosong. Ketik label, atau ketik batal.",
                label_prompt_markup(),
            )
            return True

        self.pending_labels.pop(key, None)
        label = self.label_store.add(label) or label
        url = build_tme3_url(
            self.config.tme3_host, pending.chat_ref, pending.bootstrap_message_id, label
        )
        queued_text = self._queued_export_text(profile_name, pending.chat_ref, label)
        panel_chat_id, panel_message_id = self.panel.update_from_message(
            message, queued_text, main_menu_markup(profile_name)
        )
        panel_view_token = self.panel.begin_view(panel_chat_id)
        position = self.export_worker.enqueue(
            ExportQueueJob(
                profile_name=profile_name,
                chat_id=message.chat_id,
                reply_to_message_id=message.message_id,
                url=url,
                panel_chat_id=panel_chat_id,
                panel_message_id=panel_message_id,
                panel_view_token=panel_view_token,
            )
        )
        if self.panel.is_view_active(panel_chat_id, panel_view_token):
            safe_edit_bot_message(
                self.panel.bot,
                panel_chat_id,
                panel_message_id,
                self._queued_export_text(
                    profile_name, pending.chat_ref, label, position
                ),
                main_menu_markup(profile_name),
            )
        return True

    def _handle_source_callback(self, message: Message, data: str) -> None:
        if data.startswith("sources:"):
            self._show_sources_menu(message, parse_callback_int(data))
        elif data.startswith("src:"):
            self._show_source_detail(message, data.split(":", 1)[1])
        elif data.startswith("srcsel:"):
            self._toggle_source_selection(message, data)
        elif data.startswith("srcbatch:"):
            self._handle_batch_source_callback(message, data)
        else:
            self._handle_delete_source_callback(message, data)

    def _show_sources_menu(self, message: Message, page: int) -> None:
        profile_name = self.profile_manager.active_profile_for_chat(message.chat_id)
        sources = self.profile_manager.runtime(profile_name).state_store.list_sources()
        owner = self._selection_owner(message.chat_id, profile_name)
        if not sources:
            self.selections.clear(owner)
            edit_menu_message(
                message,
                f"[{profile_name}] Belum ada channel/id chat yang pernah diexport. Kirim URL t.me3 atau t.me terlebih dahulu.",
                main_menu_markup(profile_name),
            )
            return

        selected = self.selections.retain(owner, (chat_ref for chat_ref, _ in sources))
        text = (
            f"[{profile_name}] Source tersimpan: {len(sources)}\n"
            f"Dipilih: {len(selected)}\n\n"
            "Tekan [ ] untuk memilih beberapa source, atau tekan nama source untuk membuka detail."
        )
        edit_menu_message(message, text, sources_menu_markup(sources, page, selected))

    def _toggle_source_selection(self, message: Message, data: str) -> None:
        profile_name = self.profile_manager.active_profile_for_chat(message.chat_id)
        parts = data.split(":", 2)
        source_item = (
            self._find_source_by_digest(profile_name, parts[1])
            if len(parts) == 3
            else None
        )
        if source_item is None:
            edit_menu_message(
                message,
                "Source tidak ditemukan. Daftar source dimuat ulang.",
                main_menu_markup(profile_name),
            )
            return
        self.selections.toggle(
            self._selection_owner(message.chat_id, profile_name), source_item[0]
        )
        self._show_sources_menu(message, parse_int(parts[2]))

    def _handle_batch_source_callback(self, message: Message, data: str) -> None:
        profile_name = self.profile_manager.active_profile_for_chat(message.chat_id)
        parts = data.split(":", 2)
        if len(parts) != 3:
            self._show_sources_menu(message, 0)
            return

        _, action, raw_page = parts
        page = parse_int(raw_page)
        runtime = self.profile_manager.runtime(profile_name)
        sources = runtime.state_store.list_sources()
        owner = self._selection_owner(message.chat_id, profile_name)

        if action == "all":
            self.selections.select_all(owner, (chat_ref for chat_ref, _ in sources))
        elif action == "clear":
            self.selections.clear(owner)
        elif action == "ask":
            selected = self.selections.retain(
                owner, (chat_ref for chat_ref, _ in sources)
            )
            if not selected:
                edit_menu_message(
                    message,
                    "Belum ada source yang dipilih.",
                    sources_menu_markup(sources, page, selected),
                )
                return
            preview = "\n".join(f"- {chat_ref}" for chat_ref in sorted(selected)[:10])
            suffix = (
                f"\n...dan {len(selected) - 10} source lain."
                if len(selected) > 10
                else ""
            )
            text = f"[{profile_name}] Hapus {len(selected)} source dari state?\n\n{preview}{suffix}\n\nFile JSON dan hasil download tidak ikut dihapus."
            edit_menu_message(message, text, batch_delete_source_confirm_markup(page))
            return
        elif action == "leave":
            selected = self.selections.retain(owner, (chat_ref for chat_ref, _ in sources))
            if not selected:
                edit_menu_message(message, "Belum ada source yang dipilih.", sources_menu_markup(sources, page, selected))
                return
            preview = "\n".join(f"- {chat_ref}" for chat_ref in sorted(selected)[:10])
            suffix = f"\n...dan {len(selected) - 10} source lain." if len(selected) > 10 else ""
            edit_menu_message(message, f"[{profile_name}] Leave dari {len(selected)} channel?\n\n{preview}{suffix}\n\nSource yang berhasil akan dihapus dari daftar.", batch_leave_source_confirm_markup(page))
            return
        elif action == "leave_yes":
            selected = sorted(self.selections.retain(owner, (chat_ref for chat_ref, _ in sources)))
            if not selected:
                self._show_sources_menu(message, page)
                return
            self.selections.clear(owner)
            panel_token = self.panel.begin_view(message.chat_id)
            position = self.export_worker.enqueue(
                LeaveQueueJob(profile_name=profile_name, chat_id=message.chat_id,
                              reply_to_message_id=message.message_id, chat_refs=selected,
                              panel_chat_id=message.chat_id, panel_message_id=message.message_id,
                              panel_view_token=panel_token)
            )
            edit_menu_message(message, f"[{profile_name}] Leave masuk antrian export #{position} untuk {len(selected)} source.", main_menu_markup(profile_name))
            return
        elif action == "yes":
            deleted = runtime.state_store.delete_sources(self.selections.get(owner))
            self.selections.clear(owner)
            remaining = runtime.state_store.list_sources()
            if not remaining:
                edit_menu_message(
                    message,
                    f"[{profile_name}] {len(deleted)} source dihapus. Daftar source sekarang kosong.",
                    main_menu_markup(profile_name),
                )
                return
            text = f"[{profile_name}] Source berhasil dihapus: {len(deleted)}.\nTersisa: {len(remaining)}."
            edit_menu_message(
                message, text, sources_menu_markup(remaining, page, set())
            )
            return
        else:
            edit_menu_message(
                message,
                "Aksi batch source tidak dikenal.",
                main_menu_markup(profile_name),
            )
            return

        self._show_sources_menu(message, page)

    def _show_source_detail(self, message: Message, digest: str) -> None:
        profile_name = self.profile_manager.active_profile_for_chat(message.chat_id)
        source_item = self._find_source_by_digest(profile_name, digest)
        if source_item is None:
            edit_menu_message(
                message,
                "Source tidak ditemukan. Buka ulang /menu agar daftar terbaru dimuat.",
                main_menu_markup(profile_name),
            )
            return
        chat_ref, source = source_item
        label_text = source.label or "belum ada"
        text = f"[{profile_name}] Source: {chat_ref}\nLast ID: {source.last_id}\nLabel terakhir: {label_text}\n\nPilih cara membuat export JSON berikutnya."
        edit_menu_message(
            message,
            text,
            source_detail_markup(
                chat_ref, source, self.label_store.list_labels(limit=10)
            ),
        )

    def _handle_delete_source_callback(self, message: Message, data: str) -> None:
        profile_name = self.profile_manager.active_profile_for_chat(message.chat_id)
        parts = data.split(":", 2)
        if len(parts) != 3:
            edit_menu_message(
                message,
                "Format tombol hapus tidak valid.",
                main_menu_markup(profile_name),
            )
            return

        _, digest, action = parts
        source_item = self._find_source_by_digest(profile_name, digest)
        if source_item is None:
            edit_menu_message(
                message,
                "Source tidak ditemukan atau sudah dihapus.",
                main_menu_markup(profile_name),
            )
            return

        chat_ref, source = source_item
        if action == "ask":
            text = (
                f"[{profile_name}] Hapus source {chat_ref} dari state?\n"
                f"Last ID saat ini: {source.last_id}\n\n"
                "File JSON dan hasil download tidak ikut dihapus. URL berikutnya akan dianggap sebagai source baru."
            )
            edit_menu_message(message, text, delete_source_confirm_markup(digest))
            return
        if action == "yes":
            self.profile_manager.runtime(profile_name).state_store.delete_source(
                chat_ref
            )
            self.selections.discard(
                self._selection_owner(message.chat_id, profile_name), [chat_ref]
            )
            edit_menu_message(
                message,
                f"[{profile_name}] Source {chat_ref} dan Last ID-nya sudah dihapus dari state.",
                main_menu_markup(profile_name),
            )
            return

        edit_menu_message(
            message,
            "Aksi hapus tidak dikenal.",
            source_detail_markup(
                chat_ref, source, self.label_store.list_labels(limit=10)
            ),
        )

    def _handle_export_callback(self, update: Update, data: str) -> None:
        query = update.callback_query
        if query is None or query.message is None:
            return
        message = query.message
        profile_name = self.profile_manager.active_profile_for_chat(message.chat_id)
        parts = data.split(":", 2)
        if len(parts) != 3:
            edit_menu_message(
                message,
                "Format tombol export tidak valid. Ketik /menu untuk membuka ulang.",
                main_menu_markup(profile_name),
            )
            return

        _, digest, mode = parts
        source_item = self._find_source_by_digest(profile_name, digest)
        if source_item is None:
            edit_menu_message(
                message,
                "Source tidak ditemukan. Ketik /menu untuk membuka ulang.",
                main_menu_markup(profile_name),
            )
            return

        chat_ref, source = source_item
        bootstrap_id = max(source.last_id + 1, 1)
        if mode == "custom":
            self.pending_labels[pending_key(update)] = PendingLabelRequest(
                chat_ref, bootstrap_id
            )
            edit_menu_message(
                message,
                f"[{profile_name}] Ketik label untuk {chat_ref}. Ketik batal untuk membatalkan.",
                label_prompt_markup(),
            )
            return

        if mode.startswith("saved:"):
            label = self.label_store.find_by_digest(mode.split(":", 1)[1])
            if label is None:
                edit_menu_message(
                    message,
                    "Label pilihan tidak ditemukan. Buka ulang menu source.",
                    source_detail_markup(
                        chat_ref, source, self.label_store.list_labels(limit=10)
                    ),
                )
                return
        else:
            label = source.label if mode == "label" and source.label else None
        if label:
            label = self.label_store.add(label) or label

        url = build_tme3_url(self.config.tme3_host, chat_ref, bootstrap_id, label)
        edit_menu_message(
            message,
            self._queued_export_text(profile_name, chat_ref, label),
            main_menu_markup(profile_name),
        )
        panel_view_token = self.panel.begin_view(message.chat_id)
        position = self.export_worker.enqueue(
            ExportQueueJob(
                profile_name=profile_name,
                chat_id=message.chat_id,
                reply_to_message_id=message.message_id,
                url=url,
                panel_chat_id=message.chat_id,
                panel_message_id=message.message_id,
                panel_view_token=panel_view_token,
            )
        )
        if self.panel.is_view_active(message.chat_id, panel_view_token):
            edit_menu_message(
                message,
                self._queued_export_text(profile_name, chat_ref, label, position),
                main_menu_markup(profile_name),
            )

    def _find_source_by_digest(
        self, profile_name: str, digest: str
    ) -> tuple[str, SourceState] | None:
        for chat_ref, source in self.profile_manager.runtime(
            profile_name
        ).state_store.list_sources():
            if source_digest(chat_ref) == digest:
                return chat_ref, source
        return None

    @staticmethod
    def _selection_owner(chat_id: int, profile_name: str) -> tuple[int, str]:
        return chat_id, profile_name

    @staticmethod
    def _queued_export_text(
        profile_name: str, chat_ref: str, label: str | None, position: int | None = None
    ) -> str:
        queue_text = (
            "Export JSON masuk antrian..."
            if position is None
            else f"Export JSON masuk antrian #{position}"
        )
        return f"[{profile_name}] {queue_text}\nChat: {chat_ref}\nLabel: {label or 'tanpa label'}"


def pending_key(update: Update) -> tuple[int, int]:
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0
    return chat_id, user_id
