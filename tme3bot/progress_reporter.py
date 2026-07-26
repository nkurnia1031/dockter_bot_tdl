from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from tme3bot.tdl_output import CommandProgress


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProgressReporter:
    """Throttled current-state telemetry plus persistent milestone events."""

    def __init__(
        self,
        publisher,
        job_id: str,
        *,
        min_interval_seconds: float = 1.0,
        min_percent_delta: float = 1.0,
    ) -> None:
        self.publisher = publisher
        self.job_id = job_id
        self.min_interval_seconds = min_interval_seconds
        self.min_percent_delta = min_percent_delta
        self.started_at = time.monotonic()
        self._last_emit_at = 0.0
        self._last_percent: float | None = None
        self._speed_ewma: float | None = None
        self.latest: dict[str, Any] = {}

    def reset_transfer(self) -> None:
        self._speed_ewma = None

    def tdl_transfer(
        self,
        progress: CommandProgress,
        *,
        total_bytes: int | None = None,
    ) -> dict[str, Any]:
        return self.transfer_metrics(
            speed_bps=progress.speed_bps,
            current_bytes=progress.transferred_bytes,
            total_bytes=total_bytes,
            eta_seconds=progress.eta_seconds,
            elapsed_seconds=progress.elapsed_seconds,
            percent=progress.percent,
        )

    def transfer_metrics(
        self,
        *,
        speed_bps: float | int | None = None,
        current_bytes: int | None = None,
        total_bytes: int | None = None,
        eta_seconds: int | None = None,
        elapsed_seconds: float | None = None,
        percent: float | None = None,
    ) -> dict[str, Any]:
        """Normalize transfer telemetry and smooth noisy instantaneous speed."""
        speed = float(speed_bps) if speed_bps is not None else None
        if speed is not None and speed > 0:
            self._speed_ewma = (
                speed
                if self._speed_ewma is None
                else (0.3 * speed) + (0.7 * self._speed_ewma)
            )
        if current_bytes is None and total_bytes and percent is not None:
            current_bytes = int(total_bytes * min(100.0, max(0.0, percent)) / 100.0)
        eta = eta_seconds
        if eta is None and total_bytes and current_bytes is not None and self._speed_ewma:
            eta = max(0, int((total_bytes - current_bytes) / self._speed_ewma))
        return {
            "bytes_current": current_bytes,
            "bytes_total": total_bytes,
            "speed_bps": int(self._speed_ewma) if self._speed_ewma else None,
            "eta_seconds": eta,
            "elapsed_seconds": elapsed_seconds,
        }

    def report(
        self,
        *,
        phase: str,
        message: str,
        overall: dict[str, Any] | None = None,
        item: dict[str, Any] | None = None,
        transfer: dict[str, Any] | None = None,
        counters: dict[str, Any] | None = None,
        indeterminate: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "phase": phase,
            "message": message,
            "overall": _without_none(overall or {}),
            "item": _without_none(item or {}),
            "transfer": _without_none(transfer or {}),
            "counters": {
                "succeeded": 0,
                "failed": 0,
                "skipped": 0,
                **_without_none(counters or {}),
            },
            "indeterminate": bool(indeterminate),
            "elapsed_seconds": max(0, int(time.monotonic() - self.started_at)),
            "updated_at": utc_timestamp(),
        }
        self.latest = payload
        now = time.monotonic()
        percent = _progress_percent(payload)
        changed_enough = (
            percent is not None
            and (
                self._last_percent is None
                or abs(percent - self._last_percent) >= self.min_percent_delta
            )
        )
        if not force and now - self._last_emit_at < self.min_interval_seconds and not changed_enough:
            return payload
        self.publisher.emit(
            self.job_id,
            "running",
            "progress.snapshot",
            transient=True,
            progress=payload,
        )
        self._last_emit_at = now
        if percent is not None:
            self._last_percent = percent
        return payload

    def milestone(
        self,
        event_type: str,
        *,
        progress: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        payload = progress or self.latest
        self.publisher.emit(
            self.job_id,
            "running",
            event_type,
            progress=payload,
            result=result,
            error=error,
        )


def _progress_percent(payload: dict[str, Any]) -> float | None:
    for section in ("item", "overall"):
        value = payload.get(section, {}).get("percent")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _without_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}
