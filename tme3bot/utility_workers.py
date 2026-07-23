from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass

from telegram import Bot

from tme3bot.bot_keyboards import main_menu_markup
from tme3bot.bot_panel import PanelManager, safe_edit_bot_message
from tme3bot.profile_queue import SerialPerKeyQueue
from tme3bot.profiles import ProfileManager
from tme3bot.utility import UtilityRunner

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class UtilityQueueJob:
    batch_id: str
    utility: str
    folder: str
    profile_name: str
    chat_id: int
    reply_to_message_id: int
    folder_index: int = 1
    password: str | None = None
    panel_chat_id: int | None = None
    panel_message_id: int | None = None
    panel_view_token: int | None = None


@dataclass
class _BatchState:
    total: int
    done: int = 0
    succeeded: list[str] | None = None
    failed: dict[str, str] | None = None
    current_folder: str = ""
    current_index: int = 0
    last_log: str = ""
    last_panel_update: float = 0.0
    panel_recovered: bool = False

    def __post_init__(self) -> None:
        self.succeeded = []
        self.failed = {}


class UtilityQueueWorker:
    # Telegram edits are intentionally much slower than subprocess output.
    PANEL_LOG_INTERVAL = 1.0

    def __init__(self, bot: Bot, profile_manager: ProfileManager, panel: PanelManager, utility_root) -> None:
        self.bot = bot
        self.profile_manager = profile_manager
        self.panel = panel
        self.utility_root = utility_root
        self._batches: dict[str, _BatchState] = {}
        self._panel_message_ids: dict[str, int] = {}
        self._lock = threading.RLock()
        self._panel_lock = threading.Lock()
        self._jobs = SerialPerKeyQueue[str, UtilityQueueJob](
            self._run_job, thread_name_prefix="tme3-utility-worker"
        )

    def start(self) -> None:
        self._jobs.start()

    def enqueue(self, utility: str, folders: list[str], profile_name: str, chat_id: int,
                message_id: int, token: int, password: str | None = None) -> tuple[str, int]:
        batch_id = uuid.uuid4().hex[:10]
        with self._lock:
            self._batches[batch_id] = _BatchState(len(folders))
        positions = [
            self._jobs.enqueue(folder, UtilityQueueJob(
                batch_id=batch_id, utility=utility, folder=folder,
                profile_name=profile_name, chat_id=chat_id,
                reply_to_message_id=message_id, password=password,
                folder_index=index,
                panel_chat_id=chat_id, panel_message_id=message_id,
                panel_view_token=token,
            ))
            for index, folder in enumerate(folders, start=1)
        ]
        with self._lock:
            self._panel_message_ids[batch_id] = message_id
        return batch_id, max(positions, default=0)

    def _run_job(self, job: UtilityQueueJob, _queue: queue.Queue[UtilityQueueJob]) -> None:
        self._update_batch(job, force=True)

        def on_log(line: str) -> None:
            clean = self._compact_log(line)
            if not clean:
                return
            with self._lock:
                state = self._batches.get(job.batch_id)
                if state is None:
                    return
                state.current_folder = job.folder
                state.current_index = job.folder_index
                state.last_log = clean
                now = time.monotonic()
                if now - state.last_panel_update < self.PANEL_LOG_INTERVAL:
                    return
                state.last_panel_update = now
                text = self._running_text(job.utility, state)
            self._panel(job, text)

        runner = UtilityRunner(self.utility_root, on_log)
        error: str | None = None
        try:
            self._panel(job, f"[{job.utility}] Memproses {job.folder}...")
            result = runner.run(job.utility, [job.folder], job.password)
            if result.failed:
                error = result.failed.get(job.folder, "utility gagal")
        except Exception as exc:
            error = str(exc)
            LOGGER.exception("Utility worker failed: %s", job.folder)
        with self._lock:
            state = self._batches[job.batch_id]
            state.done += 1
            state.current_folder = job.folder
            state.current_index = job.folder_index
            state.last_log = "gagal" if error else "selesai"
            if error:
                assert state.failed is not None
                state.failed[job.folder] = error
            else:
                assert state.succeeded is not None
                state.succeeded.append(job.folder)
            done, total = state.done, state.total
            final = done >= total
            succeeded = list(state.succeeded or [])
            failed = dict(state.failed or {})
            if final:
                self._batches.pop(job.batch_id, None)
        if final:
            lines = [f"[{job.utility}] Selesai: {len(succeeded)}/{total} folder."]
            lines.extend(f"OK: {folder}" for folder in succeeded)
            lines.extend(f"GAGAL: {folder} | {err}" for folder, err in failed.items())
            self._panel(job, "\n".join(lines))
            with self._lock:
                self._panel_message_ids.pop(job.batch_id, None)
        else:
            self._panel(job, self._running_text(job.utility, state))

    @staticmethod
    def _compact_log(line: str) -> str:
        return " ".join(line.replace("\r", " ").split())[-500:]

    @staticmethod
    def _running_text(utility: str, state: _BatchState) -> str:
        current = state.current_folder or "menunggu"
        index = state.current_index or min(state.done + 1, state.total)
        lines = [
            f"[{utility}] sedang berjalan",
            f"Folder: {index}/{state.total} sedang diproses",
            f"Selesai: {state.done}/{state.total}",
            f"Target: {current}",
        ]
        if state.last_log:
            lines.append(f"Log terakhir: {state.last_log}")
        return "\n".join(lines)

    def _panel(self, job: UtilityQueueJob, text: str) -> None:
        chat_id = job.panel_chat_id or job.chat_id
        if self.panel.is_view_active(chat_id, job.panel_view_token):
            with self._panel_lock:
                with self._lock:
                    message_id = self._panel_message_ids.get(
                        job.batch_id, job.panel_message_id
                    )
                if safe_edit_bot_message(
                    self.bot,
                    chat_id,
                    message_id,
                    text,
                    reply_markup=main_menu_markup(job.profile_name),
                ):
                    return

                with self._lock:
                    state = self._batches.get(job.batch_id)
                    if state is None or state.panel_recovered:
                        LOGGER.warning(
                            "Utility panel recovery already attempted; skipping new message chat=%s",
                            chat_id,
                        )
                        return
                    state.panel_recovered = True

                # Recover at most once per batch. PanelManager.update() forgets
                # the stale message and remembers the replacement, so subsequent
                # throttled updates continue editing one panel.
                LOGGER.warning(
                    "Utility panel edit failed; recovering panel chat=%s message=%s",
                    chat_id,
                    message_id,
                )
                _new_chat_id, new_message_id = self.panel.update(
                    chat_id,
                    text,
                    main_menu_markup(job.profile_name),
                )
                with self._lock:
                    self._panel_message_ids[job.batch_id] = new_message_id

    def _update_batch(self, job: UtilityQueueJob, force: bool = False) -> None:
        with self._lock:
            state = self._batches.get(job.batch_id)
            if state is None:
                return
            state.current_folder = job.folder
            state.current_index = job.folder_index
            now = time.monotonic()
            if not force and now - state.last_panel_update < self.PANEL_LOG_INTERVAL:
                return
            state.last_panel_update = now
            text = self._running_text(job.utility, state)
        self._panel(job, text)
