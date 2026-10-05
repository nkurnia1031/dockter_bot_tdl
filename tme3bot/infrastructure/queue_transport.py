from __future__ import annotations

import logging
import random
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
QUEUE_NAME = "tme3bot-operations"
_TERMINAL_OPERATION_STATUSES = ("succeeded", "failed", "cancelled")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SqliteQueueState:
    """Queue-specific SQLite adapter over the durable operation outbox."""

    def __init__(self, operation_store) -> None:
        self.path = Path(operation_store.path)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def active_delivered_commands(self, *, limit: int = 200) -> list[dict[str, Any]]:
        db = self._connect()
        try:
            rows = db.execute(
                """SELECT o.id, o.operation_id, o.attempt, o.topic
                   FROM operation_outbox AS o
                   JOIN operations AS p ON p.id=o.operation_id
                   WHERE o.status='delivered' AND o.attempt=p.attempt
                     AND p.status NOT IN ('succeeded', 'failed', 'cancelled')
                   ORDER BY o.delivered_at, o.created_at, o.id LIMIT ?""",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            db.close()

    def mark_missing_for_delivery(self, command_id: str) -> bool:
        now = _now().isoformat()
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                """UPDATE operation_outbox
                   SET status='pending', available_at=?, lease_token=NULL,
                       lease_until=NULL, last_error_code='REDIS_JOB_MISSING'
                   WHERE id=? AND status='delivered' AND EXISTS (
                       SELECT 1 FROM operations AS p
                       WHERE p.id=operation_outbox.operation_id
                         AND p.attempt=operation_outbox.attempt
                         AND p.status NOT IN ('succeeded', 'failed', 'cancelled')
                   )""",
                (now, str(command_id)),
            )
            db.commit()
            return cursor.rowcount == 1
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def claim_command(
        self, command_id: str, claim_token: str, *, lease_seconds: int = 30
    ) -> dict[str, Any]:
        now = _now()
        now_text = now.isoformat()
        lease_until = (now + timedelta(seconds=max(5, min(int(lease_seconds), 120)))).isoformat()
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT o.id, o.operation_id, o.attempt AS outbox_attempt,
                          o.topic, o.status AS outbox_status, o.lease_token,
                          o.lease_until, o.attempts AS transport_attempts,
                          p.kind, p.status AS operation_status,
                          p.attempt AS operation_attempt, p.revision,
                          p.target_json, q.payload_json
                   FROM operation_outbox AS o
                   JOIN operations AS p ON p.id=o.operation_id
                   LEFT JOIN operation_payloads AS q ON q.operation_id=p.id
                   WHERE o.id=?""",
                (str(command_id),),
            ).fetchone()
            if row is None:
                db.commit()
                return {"status": "terminal", "reason": "command_missing"}

            is_terminal = row["operation_status"] in _TERMINAL_OPERATION_STATUSES
            is_stale = int(row["outbox_attempt"]) != int(row["operation_attempt"])
            if is_terminal or is_stale or row["outbox_status"] == "consumed":
                db.execute(
                    """UPDATE operation_outbox SET status='consumed',
                           lease_token=NULL, lease_until=NULL
                       WHERE id=? AND status!='consumed'""",
                    (str(command_id),),
                )
                db.commit()
                return {"status": "terminal", "reason": "operation_terminal" if is_terminal else "stale_attempt"}
            if row["outbox_status"] != "delivered":
                db.commit()
                return {"status": "wait", "reason": "delivery_pending"}
            current_lease = row["lease_until"]
            if (
                row["lease_token"]
                and row["lease_token"] != claim_token
                and current_lease
                and str(current_lease) > now_text
            ):
                db.commit()
                return {"status": "wait", "reason": "command_claimed"}

            cursor = db.execute(
                """UPDATE operation_outbox SET lease_token=?, lease_until=?,
                       attempts=attempts+1
                   WHERE id=? AND status='delivered'
                     AND (lease_token IS NULL OR lease_until IS NULL
                          OR lease_until<=? OR lease_token=?)""",
                (claim_token, lease_until, str(command_id), now_text, claim_token),
            )
            if cursor.rowcount != 1:
                db.commit()
                return {"status": "wait", "reason": "command_claimed"}

            import json

            try:
                target = json.loads(row["target_json"] or "{}")
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, ValueError):
                target, payload = {}, {}
            db.commit()
            return {
                "status": "claimed",
                "claim_token": claim_token,
                "lease_until": lease_until,
                "command": {
                    "command_id": str(row["id"]),
                    "operation_id": str(row["operation_id"]),
                    "attempt": int(row["outbox_attempt"]),
                    "transport_attempt": int(row["transport_attempts"]) + 1,
                    "topic": str(row["topic"]),
                    "kind": str(row["kind"]),
                    "operation_status": str(row["operation_status"]),
                    "revision": int(row["revision"]),
                    "target": target if isinstance(target, dict) else {},
                    "private_payload": payload if isinstance(payload, dict) else {},
                },
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def finish_command(self, command_id: str, claim_token: str, status: str) -> bool:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            if status in {"accepted", "terminal"}:
                cursor = db.execute(
                    """UPDATE operation_outbox SET status='consumed',
                           lease_token=NULL, lease_until=NULL
                       WHERE id=? AND status='delivered' AND lease_token=?""",
                    (str(command_id), claim_token),
                )
            else:
                cursor = db.execute(
                    """UPDATE operation_outbox SET lease_token=NULL, lease_until=NULL
                       WHERE id=? AND status='delivered' AND lease_token=?""",
                    (str(command_id), claim_token),
                )
            db.commit()
            return cursor.rowcount == 1
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


class QueueCommandService:
    """Claim and advance an outbox command without running work in a request."""

    _RESULTS = {"accepted", "wait", "retry", "terminal"}

    def __init__(self, operation_store) -> None:
        self.state = SqliteQueueState(operation_store)

    def advance(self, command_id: str, claim_token: str, operations) -> dict[str, str]:
        claimed = self.state.claim_command(command_id, claim_token)
        status = claimed.get("status")
        if status != "claimed":
            return {"status": str(status), "reason": str(claimed.get("reason", ""))}
        command = claimed["command"]
        handler = operations.command_handler(command["topic"]) if operations else None
        if handler is None:
            self.state.finish_command(command_id, claim_token, "wait")
            return {"status": "wait", "reason": "not_ready"}
        try:
            result = handler(command)
        except Exception as exc:
            LOGGER.warning("Queue command handler failed (%s).", type(exc).__name__)
            self.state.finish_command(command_id, claim_token, "retry")
            return {"status": "retry", "reason": "handler_error"}
        if isinstance(result, str):
            result = {"status": result}
        result = result if isinstance(result, dict) else {}
        outcome = str(result.get("status", "retry")).strip().lower()
        if outcome not in self._RESULTS:
            outcome = "retry"
        self.state.finish_command(command_id, claim_token, outcome)
        reason = str(result.get("reason", ""))[:48]
        return {"status": outcome, **({"reason": reason} if reason else {})}


class QueueOutboxPublisher:
    """Moves SQLite outbox messages to RQ and repairs missing Redis jobs."""

    def __init__(
        self,
        operation_store,
        redis_url: str,
        operations=None,
        *,
        queue=None,
        connection=None,
        interval_seconds: float = 2.0,
        reconcile_seconds: float = 20.0,
        batch_size: int = 50,
    ) -> None:
        self.store = operation_store
        self.state = SqliteQueueState(operation_store)
        self.redis_url = str(redis_url or "")
        self.operations = operations
        self._queue = queue
        self._connection = connection
        self.interval_seconds = max(0.2, float(interval_seconds))
        self.reconcile_seconds = max(self.interval_seconds, float(reconcile_seconds))
        self.batch_size = max(1, min(int(batch_size), 500))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue_lock = threading.Lock()
        self._next_reconcile = 0.0

    def _get_queue(self):
        if self._queue is None:
            with self._queue_lock:
                if self._queue is None:
                    from redis import Redis
                    from rq import Queue
                    from rq.serializers import JSONSerializer

                    self._connection = Redis.from_url(
                        self.redis_url,
                        socket_connect_timeout=3,
                        socket_timeout=5,
                        health_check_interval=30,
                    )
                    self._queue = Queue(
                        QUEUE_NAME, connection=self._connection, serializer=JSONSerializer
                    )
        return self._queue

    @staticmethod
    def _retry_policy():
        from rq import Retry

        intervals = [
            max(1, int(delay * random.uniform(0.8, 1.2)))
            for delay in (5, 15, 30, 60, 120)
        ]
        return Retry(max=5, interval=intervals)

    def publish_once(self) -> int:
        queue = self._get_queue()
        messages = self.store.claim_outbox(limit=self.batch_size, lease_seconds=45)
        published = 0
        for message in messages:
            command_id = str(message["id"])
            try:
                from tme3bot.queue_runner import advance_command

                queue.enqueue(
                    advance_command,
                    command_id,
                    job_id=command_id,
                    unique=True,
                    retry=self._retry_policy(),
                    job_timeout=30,
                    result_ttl=86400,
                    failure_ttl=7 * 86400,
                )
            except Exception as exc:
                attempts = int(message.get("attempts", 1))
                backoff = min(300.0, float(2 ** min(attempts, 8)))
                delay = max(1, int(backoff * random.uniform(0.8, 1.2)))
                self.store.retry_outbox(
                    command_id,
                    str(message["lease_token"]),
                    delay_seconds=delay,
                    error_code="QUEUE_PUBLISH_FAILED",
                )
                LOGGER.warning("Queue publish failed (%s).", type(exc).__name__)
                continue
            if self.store.acknowledge_outbox(command_id, str(message["lease_token"])):
                published += 1
        return published

    def reconcile_once(self) -> int:
        queue = self._get_queue()
        recovered = 0
        for command in self.state.active_delivered_commands(limit=self.batch_size * 4):
            command_id = str(command["id"])
            job = queue.fetch_job(command_id)
            if job is None:
                recovered += int(self.state.mark_missing_for_delivery(command_id))
                continue
            meta = getattr(job, "meta", {}) or {}
            if (
                meta.get("awaiting_handler")
                and self.operations is not None
                and self.operations.supports_command(str(command["topic"]))
            ):
                try:
                    job.delete()
                except Exception as exc:
                    LOGGER.warning("Queue stale job cleanup failed (%s).", type(exc).__name__)
                    continue
                recovered += int(self.state.mark_missing_for_delivery(command_id))
        return recovered

    def run_once(self) -> int:
        now = time.monotonic()
        recovered = 0
        if now >= self._next_reconcile:
            try:
                recovered = self.reconcile_once()
            finally:
                self._next_reconcile = now + self.reconcile_seconds
        return self.publish_once() + recovered

    def health_snapshot(self) -> dict[str, Any]:
        if not self.redis_url:
            return {"enabled": True, "ready": False, "status": "redis_unconfigured"}
        try:
            queue = self._get_queue()
            queue.connection.ping()
            from rq import Worker

            workers = Worker.all(connection=queue.connection, queue=queue)
            ready = bool(workers)
            return {
                "enabled": True,
                "ready": ready,
                "status": "ready" if ready else "no_queue_worker",
                "workers": len(workers),
            }
        except Exception as exc:
            LOGGER.warning("Queue health check failed (%s).", type(exc).__name__)
            return {"enabled": True, "ready": False, "status": "redis_unreachable"}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="operation-outbox-publisher", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:
                # Redis URLs can contain credentials; log only the exception class.
                LOGGER.warning("Queue outbox cycle failed (%s).", type(exc).__name__)
            self._stop_event.wait(self.interval_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=max(0.1, float(timeout)))
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
        self._thread = None
