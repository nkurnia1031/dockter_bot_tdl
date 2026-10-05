from __future__ import annotations

import logging
import os
import secrets
from urllib.parse import quote

from tme3bot.infrastructure.http_client import request_json


LOGGER = logging.getLogger(__name__)


class QueueAdvanceRetry(RuntimeError):
    """A short backend wait; RQ applies the bounded retry policy."""


def advance_command(command_id: str) -> None:
    """Ask the backend to claim and advance one durable command identifier."""
    endpoint = os.getenv("BACKEND_API_URL", "").strip().rstrip("/")
    token = os.getenv("BACKEND_INTERNAL_TOKEN", "").strip()
    if not endpoint or not token:
        raise QueueAdvanceRetry("backend command endpoint is unavailable")
    try:
        result = request_json(
            endpoint,
            token,
            "POST",
            f"/internal/v1/queue/commands/{quote(str(command_id), safe='')}/advance",
            {"lease_claim": secrets.token_urlsafe(32)},
            timeout=12,
        )
    except Exception as exc:
        LOGGER.warning("Queue command request failed (%s).", type(exc).__name__)
        raise QueueAdvanceRetry("backend command request failed") from None

    status = str(result.get("status", "")).strip().lower()
    reason = str(result.get("reason", ""))[:48]
    try:
        from rq import get_current_job

        job = get_current_job()
        if job is not None:
            job.meta["awaiting_handler"] = status == "wait" and reason == "not_ready"
            job.meta["wait_reason"] = reason
            job.save_meta()
    except Exception as exc:
        LOGGER.warning("Queue command metadata update failed (%s).", type(exc).__name__)

    if status in {"accepted", "terminal"}:
        return
    if status == "wait" and reason == "not_ready":
        # Task 05 installs business handlers. Leave this durable outbox receipt
        # in place; the publisher will wake it when a handler becomes available.
        return
    if status in {"wait", "retry"}:
        raise QueueAdvanceRetry("backend requested a bounded command retry")
    raise QueueAdvanceRetry("backend returned an invalid command response")
