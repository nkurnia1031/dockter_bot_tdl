"""Background maintenance for Storage captions and recycle bin."""

from __future__ import annotations

import logging
import threading
from contextlib import nullcontext
import time

from tme3bot.background_schedule import run_event_driven_loop

LOGGER = logging.getLogger(__name__)


class StorageMaintenanceService:
    def __init__(
        self,
        catalog,
        bot,
        retention_days: int = 30,
        interval_seconds: int = 60,
        database_activity=None,
        trash_interval_seconds: int | None = None,
        monotonic_clock=None,
    ):
        self.catalog = catalog
        self.bot = bot
        self.retention_days = max(1, int(retention_days))
        self.interval_seconds = max(10, int(interval_seconds))
        self.trash_interval_seconds = max(
            self.interval_seconds,
            int(trash_interval_seconds if trash_interval_seconds is not None else interval_seconds),
        )
        self._monotonic = monotonic_clock or time.monotonic
        self._next_trash_check: float | None = None
        self.database_activity = database_activity
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._wake.set()
        self._thread = threading.Thread(target=self._run, name="storage-maintenance", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        def scheduled_tick() -> None:
            try:
                self.run_scheduled_tick()
            except Exception:
                LOGGER.exception("Storage maintenance tick gagal")

        run_event_driven_loop(
            self._stop,
            self._wake,
            recovery_seconds=self.interval_seconds,
            callback=scheduled_tick,
        )

    def tick(self) -> None:
        self._process_pending_captions()
        self._purge_due_trash()

    def run_scheduled_tick(self) -> None:
        """Process captions on recovery cadence and Trash only when due."""
        self._process_pending_captions()
        now = self._monotonic()
        if self._next_trash_check is not None and now < self._next_trash_check:
            return
        self._purge_due_trash()
        self._next_trash_check = now + self.trash_interval_seconds

    def _process_pending_captions(self) -> None:
        for task in self.catalog.pending_captions():
            try:
                self.bot.edit_message_caption(
                    chat_id=int(task["channel_id"]),
                    message_id=int(task["channel_message_id"]),
                    caption=str(task["caption"]),
                )
                with self._database_activity():
                    self.catalog.finish_caption(int(task["item_id"]))
            except Exception as exc:
                with self._database_activity():
                    self.catalog.finish_caption(int(task["item_id"]), str(exc))

    def _purge_due_trash(self) -> None:
        self.purge(
            [item.id for item in self.catalog.due_trash_items(self.retention_days)],
            [folder.id for folder in self.catalog.due_trash_folders(self.retention_days)],
        )

    def purge(self, item_ids: list[int], folder_ids: list[int]) -> dict[str, object]:
        folder_item_ids = self.catalog.folder_item_ids(folder_ids) if folder_ids else []
        all_ids = list(dict.fromkeys([*item_ids, *folder_item_ids]))
        succeeded, failed = [], {}
        for item_id in all_ids:
            item = self.catalog.get(item_id, include_deleted=True)
            if item is None or item.status == "deleted":
                continue
            try:
                self.bot.delete_message(
                    chat_id=item.channel_id, message_id=item.channel_message_id
                )
                with self._database_activity():
                    self.catalog.mark_purged(item_id)
                succeeded.append(item_id)
            except Exception as exc:
                with self._database_activity():
                    self.catalog.mark_purged(item_id, str(exc))
                failed[str(item_id)] = str(exc)
        if folder_ids:
            with self._database_activity():
                self.catalog.mark_folders_purged(
                    folder_ids, None if not failed else "Sebagian message gagal dihapus."
                )
        return {"purged_item_ids": succeeded, "failed": failed, "folder_ids": folder_ids}

    def _database_activity(self):
        factory = self.database_activity
        return factory() if callable(factory) else nullcontext()

    def purge_folders(self, folder_ids: list[int]) -> dict[str, object]:
        return self.purge([], folder_ids)
