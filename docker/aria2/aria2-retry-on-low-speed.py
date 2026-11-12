#!/usr/bin/env python3
"""Record Aria2 errors; the Aria2 service coordinator owns recovery."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import deque
from datetime import datetime, timezone
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path


STATUS_FILE = Path("/state/aria2-hook-status.json")
STATUS_LOCK_FILE = Path("/state/aria2-hook-status.lock")
RECOVERY_FILE = Path("/state/aria2-recovery.json")
RECOVERY_LOCK_FILE = Path("/state/aria2-recovery.json.lock")
GID_PATTERN = re.compile(r"^[0-9a-fA-F]{16}$")
MAX_PENDING_ERROR_EVENTS = 256


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    temporary_file = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(
            temporary_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_file, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary_file.unlink()
        except FileNotFoundError:
            pass


def enqueue_error_gid(gid: str) -> None:
    if not GID_PATTERN.fullmatch(gid):
        return
    RECOVERY_FILE.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(RECOVERY_FILE.parent, 0o700)
    with RECOVERY_LOCK_FILE.open("a+", encoding="utf-8") as lock_file:
        os.chmod(RECOVERY_LOCK_FILE, 0o600)
        flock(lock_file.fileno(), LOCK_EX)
        try:
            try:
                state = json.loads(RECOVERY_FILE.read_text(encoding="utf-8"))
            except FileNotFoundError:
                state = {
                    "version": 1,
                    "speed_threshold_bytes_per_second": 100_000,
                    "boot_id": "",
                    "jobs": {},
                    "retry_paths": {},
                    "error_event_gids": [],
                    "error_event_seen_at": {},
                    "error_event_retry_after": {},
                    "last_stopped_reconcile_at": None,
                }
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RuntimeError("Aria2 recovery state is unreadable; preserving it.") from exc
            if not isinstance(state, dict) or state.get("version") != 1:
                raise RuntimeError("Aria2 recovery state has an unsupported format; preserving it.")
            gids = state.get("error_event_gids")
            if "error_event_gids" not in state:
                gids = []
            elif not isinstance(gids, list):
                raise RuntimeError("Aria2 recovery event queue is malformed; preserving it.")
            if any(not isinstance(value, str) or not GID_PATTERN.fullmatch(value) for value in gids):
                raise RuntimeError("Aria2 recovery event queue contains invalid data; preserving it.")
            gids = list(dict.fromkeys(
                value for value in gids
            ))
            if gid not in gids:
                gids.append(gid)
            gids = list(deque(gids, maxlen=MAX_PENDING_ERROR_EVENTS))
            seen_at = state.get("error_event_seen_at")
            if "error_event_seen_at" not in state:
                seen_at = {}
            elif not isinstance(seen_at, dict):
                raise RuntimeError("Aria2 recovery event state is malformed; preserving it.")
            retry_after = state.get("error_event_retry_after")
            if "error_event_retry_after" not in state:
                retry_after = {}
            elif not isinstance(retry_after, dict):
                raise RuntimeError("Aria2 recovery event state is malformed; preserving it.")
            active_gids = set(gids)
            seen_at = {key: value for key, value in seen_at.items() if key in active_gids}
            retry_after = {key: value for key, value in retry_after.items() if key in active_gids}
            event_time = time.time()
            seen_at[gid] = event_time
            retry_after.pop(gid, None)
            state["error_event_gids"] = gids
            state["error_event_seen_at"] = seen_at
            state["error_event_retry_after"] = retry_after
            state["last_error_event_at"] = event_time
            _write_json_atomic(RECOVERY_FILE, state)
        finally:
            flock(lock_file.fileno(), LOCK_UN)


def update_status(result: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(STATUS_FILE.parent, 0o700)
    with STATUS_LOCK_FILE.open("a+", encoding="utf-8") as lock_file:
        os.chmod(STATUS_LOCK_FILE, 0o600)
        flock(lock_file.fileno(), LOCK_EX)
        try:
            try:
                status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                status = None
            if not isinstance(status, dict):
                status = {
                    "buildId": "unknown",
                    "containerStartedAt": None,
                    "hookScriptPresent": True,
                    "hookConfigured": None,
                    "hookRunCount": 0,
                    "lastHookRunAt": None,
                    "lastHookResult": "unknown",
                }
            try:
                run_count = max(0, int(status.get("hookRunCount", 0)))
            except (TypeError, ValueError):
                run_count = 0
            status["hookRunCount"] = run_count + 1
            status["lastHookRunAt"] = timestamp
            status["lastHookResult"] = result

            _write_json_atomic(STATUS_FILE, status)
        finally:
            flock(lock_file.fileno(), LOCK_UN)


def main() -> int:
    gid = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        enqueue_error_gid(gid)
    except (OSError, RuntimeError):
        try:
            update_status("hook-error")
        except OSError:
            pass
        return 1
    update_status(
        "coordinator-observes-error" if GID_PATTERN.fullmatch(gid) else "missing-gid"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
