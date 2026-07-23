from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass

from telegram import Bot

from tme3bot.bot_keyboards import download_status_markup, main_menu_markup
from tme3bot.bot_panel import (
    PanelManager,
    edit_or_send_bot_message,
    safe_edit_bot_message,
)
from tme3bot.bot_text import (
    format_download_progress,
    format_exception,
    format_export_result,
)
from tme3bot.progress import DownloadProgressTracker
from tme3bot.profile_queue import SerialPerKeyQueue
from tme3bot.profiles import ProfileManager
from tme3bot.leave import LeaveResult

LOGGER = logging.getLogger(__name__)
STATUS_UPDATE_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True)
class ExportQueueJob:
    profile_name: str
    chat_id: int
    reply_to_message_id: int
    url: str
    use_url_message_id: bool = False
    panel_chat_id: int | None = None
    panel_message_id: int | None = None
    panel_view_token: int | None = None


@dataclass(frozen=True)
class DownloadQueueJob:
    profile_name: str
    chat_id: int
    reply_to_message_id: int
    retry_failed: bool = False
    panel_chat_id: int | None = None
    panel_message_id: int | None = None
    panel_view_token: int | None = None


@dataclass(frozen=True)
class LeaveQueueJob:
    profile_name: str
    chat_id: int
    reply_to_message_id: int
    chat_refs: list[str]
    panel_chat_id: int | None = None
    panel_message_id: int | None = None
    panel_view_token: int | None = None


class ExportQueueWorker:
    def __init__(
        self, bot: Bot, profile_manager: ProfileManager, panel: PanelManager
    ) -> None:
        self.bot = bot
        self.profile_manager = profile_manager
        self.panel = panel
        self.jobs: queue.Queue[ExportQueueJob | LeaveQueueJob] = queue.Queue()
        self.thread = threading.Thread(
            target=self._run, daemon=True, name="tme3-export-worker"
        )

    def start(self) -> None:
        self.thread.start()

    def enqueue(self, job: ExportQueueJob | LeaveQueueJob) -> int:
        self.jobs.put(job)
        return self.jobs.qsize()

    def _run(self) -> None:
        while True:
            job = self.jobs.get()
            panel_chat_id = job.panel_chat_id or job.chat_id
            panel_message_id = job.panel_message_id
            try:
                runtime = self.profile_manager.runtime(job.profile_name)
                if isinstance(job, LeaveQueueJob):
                    self._run_leave(runtime, job)
                    continue
                if self.panel.is_view_active(panel_chat_id, job.panel_view_token):
                    panel_message_id = edit_or_send_bot_message(
                        self.bot,
                        panel_chat_id,
                        panel_message_id,
                        f"[{job.profile_name}] Membuat export JSON...\nURL: {job.url}",
                        reply_markup=main_menu_markup(job.profile_name),
                        reply_to_message_id=job.reply_to_message_id
                        if panel_message_id is None
                        else None,
                    )
                result = runtime.export_service.export_from_url(
                    job.url, use_url_message_id=job.use_url_message_id
                )
                if self.panel.is_view_active(panel_chat_id, job.panel_view_token):
                    edit_or_send_bot_message(
                        self.bot,
                        panel_chat_id,
                        panel_message_id,
                        format_export_result(result, job.profile_name),
                        reply_markup=main_menu_markup(job.profile_name),
                        reply_to_message_id=job.reply_to_message_id
                        if panel_message_id is None
                        else None,
                    )
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                LOGGER.exception("Export job failed for URL %s", job.url)
                if self.panel.is_view_active(panel_chat_id, job.panel_view_token):
                    edit_or_send_bot_message(
                        self.bot,
                        panel_chat_id,
                        panel_message_id,
                        format_exception(exc),
                        reply_markup=main_menu_markup(job.profile_name),
                        reply_to_message_id=job.reply_to_message_id
                        if panel_message_id is None
                        else None,
                    )
            finally:
                self.jobs.task_done()

    def _run_leave(self, runtime, job: LeaveQueueJob) -> None:
        panel_chat_id = job.panel_chat_id or job.chat_id
        panel_message_id = job.panel_message_id
        try:
            if self.panel.is_view_active(panel_chat_id, job.panel_view_token):
                panel_message_id = edit_or_send_bot_message(
                    self.bot, panel_chat_id, panel_message_id,
                    f"[{job.profile_name}] Leave {len(job.chat_refs)} source masuk proses...",
                    reply_markup=main_menu_markup(job.profile_name),
                    reply_to_message_id=job.reply_to_message_id if panel_message_id is None else None,
                )
            result: LeaveResult = runtime.leave_service.leave(job.chat_refs)
            deleted = runtime.state_store.delete_sources(result.succeeded)
            lines = [f"[{job.profile_name}] Leave selesai.", f"Berhasil: {len(deleted)}"]
            if deleted:
                lines.append("\n".join(f"  + {item}" for item in deleted))
            if result.failed:
                lines.append(f"Gagal: {len(result.failed)}")
                lines.extend(f"  - {item}: {error}" for item, error in result.failed.items())
            text = "\n".join(lines)
            if self.panel.is_view_active(panel_chat_id, job.panel_view_token):
                edit_or_send_bot_message(self.bot, panel_chat_id, panel_message_id, text,
                                          reply_markup=main_menu_markup(job.profile_name))
        except Exception as exc:
            LOGGER.exception("Leave job failed for profile %s", job.profile_name)
            if self.panel.is_view_active(panel_chat_id, job.panel_view_token):
                edit_or_send_bot_message(self.bot, panel_chat_id, panel_message_id,
                                          format_exception(exc), reply_markup=main_menu_markup(job.profile_name))


class DownloadQueueWorker:
    def __init__(
        self, bot: Bot, profile_manager: ProfileManager, panel: PanelManager
    ) -> None:
        self.bot = bot
        self.profile_manager = profile_manager
        self.panel = panel
        self._jobs = SerialPerKeyQueue[str, DownloadQueueJob](
            self._run_job,
            error_handler=self._handle_worker_failure,
            thread_name_prefix="tme3-download-worker",
        )

    def start(self) -> None:
        self._jobs.start()

    def enqueue(self, job: DownloadQueueJob) -> int:
        return self._jobs.enqueue(job.profile_name, job)

    def queue_size(self, profile_name: str) -> int:
        return self._jobs.queue_size(profile_name)

    def _handle_worker_failure(
        self, profile_name: str, job: DownloadQueueJob, exc: Exception
    ) -> None:
        LOGGER.exception(
            "Unhandled download worker failure for profile %s",
            profile_name,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        panel_chat_id = job.panel_chat_id or job.chat_id
        if self.panel.is_view_active(panel_chat_id, job.panel_view_token):
            edit_or_send_bot_message(
                self.bot,
                panel_chat_id,
                job.panel_message_id,
                format_exception(exc),
                reply_markup=download_status_markup(done=True),
            )

    def _run_job(
        self,
        job: DownloadQueueJob,
        profile_jobs: queue.Queue[DownloadQueueJob],
    ) -> None:
        runtime = self.profile_manager.runtime(job.profile_name)
        panel_chat_id = job.panel_chat_id or job.chat_id
        panel_message_id = job.panel_message_id
        mode_text = "Retry JSON failed" if job.retry_failed else "Batch download"
        stop_event = threading.Event()

        updater = None
        if self.panel.is_view_active(panel_chat_id, job.panel_view_token):
            panel_message_id = edit_or_send_bot_message(
                self.bot,
                panel_chat_id,
                panel_message_id,
                f"[{job.profile_name}] {mode_text} masuk antrian. Menyiapkan panel status...",
                reply_markup=download_status_markup(),
                reply_to_message_id=job.reply_to_message_id
                if panel_message_id is None
                else None,
            )
            updater = threading.Thread(
                target=self._update_status_panel_loop,
                args=(
                    job.profile_name,
                    runtime.download_progress,
                    panel_chat_id,
                    panel_message_id,
                    job.panel_view_token,
                    stop_event,
                    profile_jobs,
                ),
                daemon=True,
                name=f"tme3-download-status-panel-{job.profile_name}",
            )
            updater.start()
        try:
            result = (
                runtime.download_service.retry_failed_exports()
                if job.retry_failed
                else runtime.download_service.download_pending_exports()
            )
            stop_event.set()
            if updater is not None:
                updater.join(timeout=3)
            if self.panel.is_view_active(panel_chat_id, job.panel_view_token):
                edit_or_send_bot_message(
                    self.bot,
                    panel_chat_id,
                    panel_message_id,
                    format_download_progress(
                        runtime.download_progress.snapshot(),
                        profile_jobs.qsize(),
                        result=result,
                        profile_name=job.profile_name,
                    ),
                    reply_markup=download_status_markup(done=True),
                )
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            stop_event.set()
            if updater is not None:
                updater.join(timeout=3)
            LOGGER.exception("Download batch failed for profile %s", job.profile_name)
            if self.panel.is_view_active(panel_chat_id, job.panel_view_token):
                edit_or_send_bot_message(
                    self.bot,
                    panel_chat_id,
                    panel_message_id,
                    format_download_progress(
                        runtime.download_progress.snapshot(),
                        profile_jobs.qsize(),
                        error=format_exception(exc),
                        profile_name=job.profile_name,
                    ),
                    reply_markup=download_status_markup(done=True),
                )

    def _update_status_panel_loop(
        self,
        profile_name: str,
        progress_tracker: DownloadProgressTracker,
        chat_id: int,
        message_id: int,
        panel_view_token: int | None,
        stop_event: threading.Event,
        profile_jobs: queue.Queue[DownloadQueueJob],
    ) -> None:
        last_text = ""
        while not stop_event.wait(STATUS_UPDATE_INTERVAL_SECONDS):
            if not self.panel.is_view_active(chat_id, panel_view_token):
                return
            text = format_download_progress(
                progress_tracker.snapshot(),
                profile_jobs.qsize(),
                profile_name=profile_name,
            )
            if text == last_text:
                continue
            if safe_edit_bot_message(
                self.bot,
                chat_id,
                message_id,
                text,
                reply_markup=download_status_markup(),
            ):
                last_text = text
