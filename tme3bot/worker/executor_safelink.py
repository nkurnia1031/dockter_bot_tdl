from __future__ import annotations

from typing import Any

from tme3bot.progress_reporter import ProgressReporter
from tme3bot.worker.safelink_resolver import (
    SafelinkCancelled,
    SafelinkResolveError,
    resolve_shortlink,
)


class SafelinkExecutorMixin:
    def _safelink_resolve(self, command: dict[str, Any]) -> dict[str, str]:
        job_id = str(command["job_id"])
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        reporter = ProgressReporter(self.publisher, job_id)

        def cancelled() -> bool:
            with self._lock:
                return job_id in self._cancel_requested

        def progress(item: dict[str, Any]) -> None:
            reporter.report(
                phase=str(item.get("phase") or "resolving"),
                message=str(item.get("message") or "Resolver berjalan."),
                indeterminate=True,
            )

        try:
            return resolve_shortlink(
                str(payload.get("url") or ""),
                on_progress=progress,
                is_cancelled=cancelled,
            )
        except SafelinkCancelled:
            raise
        except SafelinkResolveError:
            raise
        except Exception:
            # Never allow a third-party URL or browser exception into job logs.
            raise SafelinkResolveError("Resolver mengalami kendala saat memproses halaman.") from None
