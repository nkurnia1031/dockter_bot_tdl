from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace

from tme3bot.tdl_output import CommandProgress


@dataclass(frozen=True)
class DownloadProgressSnapshot:
    active: bool = False
    phase: str = "idle"
    mode: str | None = None
    started_at: float | None = None
    updated_at: float | None = None
    total_json: int = 0
    current_json_index: int = 0
    current_json_name: str | None = None
    current_media_total: int = 0
    success_count: int = 0
    failed_count: int = 0
    last_error: str | None = None
    tdl_line: str | None = None
    tdl_percent: float | None = None
    tdl_speed: str | None = None
    tdl_fraction_current: int | None = None
    tdl_fraction_total: int | None = None
    tdl_file_name: str | None = None


class DownloadProgressTracker:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot = DownloadProgressSnapshot()
        self._current_media_positions: dict[int, int] = {}

    def start_batch(self, mode: str, total_json: int) -> None:
        now = time.time()
        with self._lock:
            self._snapshot = DownloadProgressSnapshot(
                active=True,
                phase="starting",
                mode=mode,
                started_at=now,
                updated_at=now,
                total_json=total_json,
            )
            self._current_media_positions = {}

    def start_json(
        self, index: int, total_json: int, json_name: str, media_ids: list[int]
    ) -> None:
        with self._lock:
            ordered_media_ids = sorted(media_ids, reverse=True)
            self._current_media_positions = {
                message_id: position
                for position, message_id in enumerate(ordered_media_ids, start=1)
            }
        self._replace(
            phase="processing_json",
            total_json=total_json,
            current_json_index=index,
            current_json_name=json_name,
            current_media_total=len(media_ids),
            tdl_line=None,
            tdl_percent=None,
            tdl_speed=None,
            tdl_fraction_current=None,
            tdl_fraction_total=None,
            tdl_file_name=None,
            last_error=None,
        )

    def set_phase(self, phase: str) -> None:
        self._replace(phase=phase)

    def update_tdl_progress(self, progress: CommandProgress) -> None:
        snapshot = self.snapshot()
        media_current = progress.fraction_current
        media_total = progress.fraction_total
        if progress.message_id is not None:
            with self._lock:
                media_current = self._current_media_positions.get(
                    progress.message_id, media_current
                )
                media_total = len(self._current_media_positions) or media_total
        elif media_current is not None and snapshot.current_media_total:
            media_total = snapshot.current_media_total

        self._replace(
            tdl_line=progress.line,
            tdl_percent=progress.percent,
            tdl_speed=progress.speed,
            tdl_fraction_current=media_current,
            tdl_fraction_total=media_total,
            tdl_file_name=progress.file_name,
        )

    def finish_json(self, success: bool, error: str | None = None) -> None:
        snapshot = self.snapshot()
        self._replace(
            phase="json_done" if success else "json_failed",
            success_count=snapshot.success_count + int(success),
            failed_count=snapshot.failed_count + int(not success),
            last_error=error,
        )

    def finish_batch(self) -> None:
        self._replace(active=False, phase="done")

    def snapshot(self) -> DownloadProgressSnapshot:
        with self._lock:
            return self._snapshot

    def _replace(self, **changes: object) -> None:
        with self._lock:
            self._snapshot = replace(self._snapshot, updated_at=time.time(), **changes)
