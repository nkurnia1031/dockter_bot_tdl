from __future__ import annotations

from fastapi import Depends, Query

from tme3bot.domain.models import DomainError
from tme3bot.infrastructure.activity_journal import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def register_activity(app, journal, *, current_actor, operations=None) -> None:
    @app.get("/api/v1/activity")
    def list_activity(
        limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        cursor: str | None = Query(default=None, max_length=512),
        method: str | None = Query(default=None, max_length=12),
        route: str | None = Query(default=None, max_length=240),
        status_code: int | None = Query(default=None, ge=100, le=599),
        actor_user_id: int | None = Query(default=None, gt=0),
        profile: str | None = Query(default=None, max_length=48),
        worker: str | None = Query(default=None, max_length=48),
        request_id: str | None = Query(default=None, max_length=64),
        operation_id: str | None = Query(default=None, max_length=64),
        since: str | None = Query(default=None, max_length=40),
        until: str | None = Query(default=None, max_length=40),
        actor=Depends(current_actor),
    ):
        if not getattr(actor, "authorized", False):
            raise DomainError(
                "FORBIDDEN",
                "Akses jurnal aktivitas memerlukan actor yang berwenang.",
                status_code=403,
            )
        if journal is None or not callable(getattr(journal, "list_entries", None)):
            raise DomainError(
                "ACTIVITY_JOURNAL_UNAVAILABLE",
                "Jurnal aktivitas belum tersedia.",
                status_code=503,
            )
        flush = getattr(operations, "flush_activity_events", None)
        if callable(flush):
            flush()
        result = journal.list_entries(
            limit=limit,
            cursor=cursor,
            method=method,
            route=route,
            status_code=status_code,
            actor_user_id=actor_user_id,
            profile=profile,
            worker=worker,
            request_id=request_id,
            operation_id=operation_id,
            since=since,
            until=until,
        )
        return {**result, "retention_days": 90}
