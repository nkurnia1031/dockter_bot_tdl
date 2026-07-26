"""Background maintenance for Storage captions and recycle bin."""

from __future__ import annotations

import logging
import threading

LOGGER = logging.getLogger(__name__)


class StorageMaintenanceService:
    def __init__(self, catalog, bot, retention_days: int = 30, interval_seconds: int = 60):
        self.catalog = catalog
        self.bot = bot
        self.retention_days = max(1, int(retention_days))
        self.interval_seconds = max(10, int(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="storage-maintenance", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                LOGGER.exception("Storage maintenance tick gagal")
            self._stop.wait(self.interval_seconds)

    def tick(self) -> None:
        for task in self.catalog.pending_captions():
            try:
                self.bot.edit_message_caption(
                    chat_id=int(task["channel_id"]),
                    message_id=int(task["channel_message_id"]),
                    caption=str(task["caption"]),
                )
                self.catalog.finish_caption(int(task["item_id"]))
            except Exception as exc:
                self.catalog.finish_caption(int(task["item_id"]), str(exc))
        self.purge(
            [item.id for item in self.catalog.due_trash_items(self.retention_days)],
            [folder.id for folder in self.catalog.due_trash_folders(self.retention_days)],
        )

    def purge(self, item_ids: list[int], folder_ids: list[int]) -> dict[str, object]:
        all_ids = list(dict.fromkeys([*item_ids, *self.catalog.folder_item_ids(folder_ids)]))
        succeeded, failed = [], {}
        for item_id in all_ids:
            item = self.catalog.get(item_id, include_deleted=True)
            if item is None or item.status == "deleted":
                continue
            try:
                self.bot.delete_message(
                    chat_id=item.channel_id, message_id=item.channel_message_id
                )
                self.catalog.mark_purged(item_id)
                succeeded.append(item_id)
            except Exception as exc:
                self.catalog.mark_purged(item_id, str(exc))
                failed[str(item_id)] = str(exc)
        if folder_ids:
            self.catalog.mark_folders_purged(
                folder_ids, None if not failed else "Sebagian message gagal dihapus."
            )
        return {"purged_item_ids": succeeded, "failed": failed, "folder_ids": folder_ids}

    def purge_folders(self, folder_ids: list[int]) -> dict[str, object]:
        return self.purge([], folder_ids)
