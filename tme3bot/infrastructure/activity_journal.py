from __future__ import annotations

import base64
import json
import re
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from tme3bot.domain.models import DomainError

RETENTION_DAYS = 90
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 200
_SAFE_PROFILE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
_SAFE_WORKER_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
_SAFE_ERROR_RE = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _safe_uuid(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _safe_identifier(value: Any, pattern: re.Pattern[str]) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if pattern.fullmatch(candidate) else ""


def _decode_cursor(value: str) -> tuple[str, int]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(raw.decode("utf-8"))
        timestamp, row_id = payload["at"], payload["id"]
        parsed = datetime.fromisoformat(str(timestamp))
        if parsed.tzinfo is None or type(row_id) is not int or row_id <= 0:
            raise ValueError
    except (ValueError, TypeError, KeyError, IndexError, UnicodeDecodeError, json.JSONDecodeError):
        raise DomainError(
            "ACTIVITY_CURSOR_INVALID",
            "Cursor aktivitas tidak valid.",
            status_code=422,
        ) from None
    return _timestamp(parsed), row_id


def _encode_cursor(timestamp: str, row_id: int) -> str:
    raw = json.dumps({"at": timestamp, "id": row_id}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _filter_timestamp(value: str | None, *, field: str) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise DomainError(
            "ACTIVITY_FILTER_INVALID",
            f"Filter {field} harus berupa timestamp ISO-8601.",
            status_code=422,
        ) from None
    if parsed.tzinfo is None:
        raise DomainError(
            "ACTIVITY_FILTER_INVALID",
            f"Filter {field} harus mencantumkan zona waktu.",
            status_code=422,
        )
    return _timestamp(parsed)


class ActivityJournalStore:
    """Persistent metadata-only journal for public API requests."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        self._initialize()
        self.prune_expired()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _initialize(self) -> None:
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    route TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    actor_user_id INTEGER,
                    profile TEXT NOT NULL DEFAULT '',
                    worker TEXT NOT NULL DEFAULT '',
                    operation_id TEXT NOT NULL DEFAULT '',
                    job_id TEXT NOT NULL DEFAULT '',
                    activity_type TEXT NOT NULL DEFAULT 'request',
                    operation_kind TEXT NOT NULL DEFAULT '',
                    operation_status TEXT NOT NULL DEFAULT '',
                    event_key TEXT NOT NULL DEFAULT '',
                    result_code TEXT NOT NULL DEFAULT '',
                    error_code TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS api_activity_occurred
                    ON api_activity(occurred_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS api_activity_actor
                    ON api_activity(actor_user_id, occurred_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS api_activity_request
                    ON api_activity(request_id);
                CREATE INDEX IF NOT EXISTS api_activity_route_time
                    ON api_activity(route, occurred_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS api_activity_status_time
                    ON api_activity(status_code, occurred_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS api_activity_profile_time
                    ON api_activity(profile, occurred_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS api_activity_worker_time
                    ON api_activity(worker, occurred_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS api_activity_operation
                    ON api_activity(operation_id);
                """
            )
            columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(api_activity)").fetchall()
            }
            for name, definition in (
                ("activity_type", "TEXT NOT NULL DEFAULT 'request'"),
                ("operation_kind", "TEXT NOT NULL DEFAULT ''"),
                ("operation_status", "TEXT NOT NULL DEFAULT ''"),
                ("event_key", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE api_activity ADD COLUMN {name} {definition}")
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS api_activity_event_key "
                "ON api_activity(event_key) WHERE event_key <> ''"
            )
            db.commit()

    def _cutoff(self) -> str:
        return _timestamp(self._clock() - timedelta(days=RETENTION_DAYS))

    def prune_expired(self) -> int:
        with self._lock, closing(self._connect()) as db:
            cursor = db.execute(
                "DELETE FROM api_activity WHERE occurred_at < ?", (self._cutoff(),)
            )
            db.commit()
            return int(cursor.rowcount)

    def record(
        self,
        *,
        occurred_at: str,
        request_id: str,
        method: str,
        route: str,
        status_code: int,
        duration_ms: int,
        actor_user_id: int | None = None,
        profile: str = "",
        worker: str = "",
        operation_id: str = "",
        job_id: str = "",
        activity_type: str = "request",
        operation_kind: str = "",
        operation_status: str = "",
        event_key: str = "",
        result_code: str = "",
        error_code: str = "",
    ) -> None:
        try:
            parsed_time = datetime.fromisoformat(str(occurred_at).replace("Z", "+00:00"))
            if parsed_time.tzinfo is None:
                raise ValueError
            event_time = _timestamp(parsed_time)
        except (TypeError, ValueError):
            event_time = _timestamp(self._clock())

        safe_request_id = _safe_uuid(request_id) or str(uuid.uuid4())
        safe_method = str(method or "").upper()
        if not re.fullmatch(r"[A-Z]{1,12}\Z", safe_method):
            safe_method = "OTHER"
        safe_route = str(route or "")
        if (
            not safe_route.startswith("/api/v1/")
            or len(safe_route) > 240
            or not re.fullmatch(r"/[A-Za-z0-9_{}./:-]+\Z", safe_route)
        ):
            safe_route = "/api/v1/{unmatched}"
        try:
            safe_status = int(status_code)
        except (TypeError, ValueError):
            safe_status = 500
        if safe_status < 100 or safe_status > 599:
            safe_status = 500
        safe_duration = max(0, min(2_147_483_647, int(duration_ms or 0)))
        try:
            safe_actor = int(actor_user_id) if actor_user_id is not None else None
            if safe_actor is not None and safe_actor <= 0:
                safe_actor = None
        except (TypeError, ValueError, OverflowError):
            safe_actor = None
        safe_profile = _safe_identifier(profile, _SAFE_PROFILE_RE)
        safe_worker = _safe_identifier(worker, _SAFE_WORKER_RE)
        safe_operation = _safe_uuid(operation_id) or ""
        safe_job = _safe_uuid(job_id) or ""
        safe_activity_type = str(activity_type or "request").lower()
        if safe_activity_type not in {"request", "operation"}:
            safe_activity_type = "request"
        safe_operation_kind = str(operation_kind or "").lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}\Z", safe_operation_kind):
            safe_operation_kind = ""
        safe_operation_status = str(operation_status or "").lower()
        if safe_operation_status not in {
            "queued", "running", "waiting_user", "waiting_worker", "paused",
            "needs_reconciliation", "cancelling", "succeeded", "failed", "cancelled",
        }:
            safe_operation_status = ""
        safe_event_key = _safe_uuid(event_key) or ""
        safe_error = str(error_code or "").upper()
        if safe_activity_type == "operation":
            if not _SAFE_ERROR_RE.fullmatch(safe_error):
                safe_error = ""
        elif safe_status >= 400 and not _SAFE_ERROR_RE.fullmatch(safe_error):
            safe_error = f"HTTP_{safe_status}"
        elif safe_status < 400:
            safe_error = ""
        safe_result = str(result_code or "").upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}\Z", safe_result):
            safe_result = "SUCCESS" if safe_status < 400 else "ERROR"

        with self._lock, closing(self._connect()) as db:
            db.execute("DELETE FROM api_activity WHERE occurred_at < ?", (self._cutoff(),))
            db.execute(
                """INSERT OR IGNORE INTO api_activity(
                    occurred_at, request_id, method, route, status_code, duration_ms,
                    actor_user_id, profile, worker, operation_id, job_id,
                    activity_type, operation_kind, operation_status, event_key,
                    result_code, error_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_time,
                    safe_request_id,
                    safe_method,
                    safe_route,
                    safe_status,
                    safe_duration,
                    safe_actor,
                    safe_profile,
                    safe_worker,
                    safe_operation,
                    safe_job,
                    safe_activity_type,
                    safe_operation_kind,
                    safe_operation_status,
                    safe_event_key,
                    safe_result,
                    safe_error,
                ),
            )
            db.commit()

    def record_operation_event(self, event: dict[str, Any]) -> None:
        """Append a deduplicated, metadata-only operation lifecycle event."""
        event_id = _safe_uuid(event.get("event_id"))
        if not event_id:
            raise ValueError("ID event aktivitas operation tidak valid.")
        self.record(
            occurred_at=str(event.get("occurred_at") or ""),
            request_id=str(event.get("request_id") or ""),
            method="ASYNC",
            route=str(event.get("route") or "/api/v1/operations"),
            status_code=200,
            duration_ms=0,
            actor_user_id=event.get("actor_user_id"),
            profile=str(event.get("profile") or ""),
            worker=str(event.get("worker") or ""),
            operation_id=str(event.get("operation_id") or ""),
            job_id=str(event.get("job_id") or ""),
            activity_type="operation",
            operation_kind=str(event.get("operation_kind") or ""),
            operation_status=str(event.get("operation_status") or ""),
            event_key=event_id,
            result_code=str(event.get("result_code") or ""),
            error_code=str(event.get("error_code") or ""),
        )

    def list_entries(
        self,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
        method: str | None = None,
        route: str | None = None,
        status_code: int | None = None,
        actor_user_id: int | None = None,
        profile: str | None = None,
        worker: str | None = None,
        request_id: str | None = None,
        operation_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        if limit < 1 or limit > MAX_PAGE_SIZE:
            raise DomainError(
                "ACTIVITY_PAGE_SIZE_INVALID",
                f"Ukuran halaman aktivitas harus 1–{MAX_PAGE_SIZE}.",
                status_code=422,
            )
        clauses: list[str] = []
        params: list[Any] = []
        if cursor:
            cursor_at, cursor_id = _decode_cursor(cursor)
            clauses.append("(occurred_at < ? OR (occurred_at = ? AND id < ?))")
            params.extend((cursor_at, cursor_at, cursor_id))
        if method:
            method_value = method.upper()
            if not re.fullmatch(r"[A-Z]{1,12}\Z", method_value):
                raise DomainError("ACTIVITY_FILTER_INVALID", "Filter method tidak valid.", status_code=422)
            clauses.append("method = ?")
            params.append(method_value)
        if route:
            if (
                not route.startswith("/api/v1/")
                or len(route) > 240
                or not re.fullmatch(r"/[A-Za-z0-9_{}./:-]+\Z", route)
            ):
                raise DomainError("ACTIVITY_FILTER_INVALID", "Filter route tidak valid.", status_code=422)
            clauses.append("route = ?")
            params.append(route)
        if status_code is not None:
            if status_code < 100 or status_code > 599:
                raise DomainError("ACTIVITY_FILTER_INVALID", "Filter status tidak valid.", status_code=422)
            clauses.append("status_code = ?")
            params.append(status_code)
        if actor_user_id is not None:
            if actor_user_id <= 0:
                raise DomainError("ACTIVITY_FILTER_INVALID", "Filter actor tidak valid.", status_code=422)
            clauses.append("actor_user_id = ?")
            params.append(actor_user_id)
        if profile:
            value = _safe_identifier(profile, _SAFE_PROFILE_RE)
            if not value:
                raise DomainError("ACTIVITY_FILTER_INVALID", "Filter profile tidak valid.", status_code=422)
            clauses.append("profile = ?")
            params.append(value)
        if worker:
            value = _safe_identifier(worker, _SAFE_WORKER_RE)
            if not value:
                raise DomainError("ACTIVITY_FILTER_INVALID", "Filter worker tidak valid.", status_code=422)
            clauses.append("worker = ?")
            params.append(value)
        if request_id:
            value = _safe_uuid(request_id)
            if not value:
                raise DomainError("ACTIVITY_FILTER_INVALID", "Filter request_id tidak valid.", status_code=422)
            clauses.append("request_id = ?")
            params.append(value)
        if operation_id:
            value = _safe_uuid(operation_id)
            if not value:
                raise DomainError("ACTIVITY_FILTER_INVALID", "Filter operation_id tidak valid.", status_code=422)
            clauses.append("operation_id = ?")
            params.append(value)
        since_value = _filter_timestamp(since, field="since")
        until_value = _filter_timestamp(until, field="until")
        if since_value:
            clauses.append("occurred_at >= ?")
            params.append(since_value)
        if until_value:
            clauses.append("occurred_at <= ?")
            params.append(until_value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

        with self._lock, closing(self._connect()) as db:
            db.execute("DELETE FROM api_activity WHERE occurred_at < ?", (self._cutoff(),))
            rows = db.execute(
                "SELECT * FROM api_activity" + where + " ORDER BY occurred_at DESC, id DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            db.commit()

        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [
            {
                "id": int(row["id"]),
                "occurred_at": str(row["occurred_at"]),
                "request_id": str(row["request_id"]),
                "method": str(row["method"]),
                "route": str(row["route"]),
                "status_code": int(row["status_code"]),
                "duration_ms": int(row["duration_ms"]),
                "actor_user_id": row["actor_user_id"],
                "profile": str(row["profile"] or ""),
                "worker": str(row["worker"] or ""),
                "operation_id": str(row["operation_id"] or ""),
                "job_id": str(row["job_id"] or ""),
                "activity_type": str(row["activity_type"] or "request"),
                "operation_kind": str(row["operation_kind"] or ""),
                "operation_status": str(row["operation_status"] or ""),
                "result_code": str(row["result_code"] or ""),
                "error_code": str(row["error_code"] or ""),
            }
            for row in rows
        ]
        next_cursor = (
            _encode_cursor(items[-1]["occurred_at"], items[-1]["id"])
            if has_more and items
            else ""
        )
        return {"items": items, "next_cursor": next_cursor}
