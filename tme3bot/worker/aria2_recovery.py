"""Persistent coordinator for Aria2 adaptive speed recovery and stopped retries."""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from tme3bot.database_paths import ensure_private_directory

try:  # Aria2 runs on Linux; keeping import local lets the pure model load elsewhere.
    from fcntl import LOCK_EX, LOCK_UN, flock
except ImportError:  # pragma: no cover - Windows development fallback
    LOCK_EX = LOCK_UN = 0

    def flock(_file, _operation):
        return None


DEFAULT_SPEED_THRESHOLD = 100_000
MAX_SPEED_THRESHOLD = 1_073_741_824
LOW_WINDOW_SECONDS = 10
WARMUP_SECONDS = 60
PAUSE_SECONDS = 3
OBSERVE_SECONDS = 10
COOLDOWN_SECONDS = 300
STOPPED_RECONCILE_SECONDS = 60
ERROR_EVENT_RETRY_SECONDS = 60
ERROR_EVENT_ACTIVE_RETRY_SECONDS = 5
ERROR_EVENT_MAX_AGE_SECONDS = 86_400
MAX_ERROR_EVENTS_PER_TICK = 1
MAX_PENDING_ERROR_EVENTS = 256
MAX_EXTERNAL_RETRIES = 10
RETRY_BACKOFF_SECONDS = (5, 15, 30, 60, 120, 300)
RETRYABLE_SCHEMES = {"http", "https", "ftp", "sftp"}
RETRY_OPTION_KEYS = {
    "all-proxy", "all-proxy-passwd", "all-proxy-user", "allow-overwrite",
    "always-resume", "async-dns", "ca-certificate", "check-certificate",
    "conditional-get", "connect-timeout", "content-disposition-default-utf8",
    "continue", "disable-ipv6", "enable-http-pipelining", "file-allocation",
    "ftp-passwd", "ftp-pasv", "ftp-reuse-connection", "ftp-type", "ftp-user",
    "header", "http-accept-gzip", "http-auth-challenge", "http-passwd",
    "http-proxy", "http-proxy-passwd", "http-proxy-user", "http-user",
    "https-proxy", "https-proxy-passwd", "https-proxy-user", "load-cookies", "max-connection-per-server",
    "max-download-limit", "max-file-not-found", "max-resume-failure-tries",
    "min-split-size", "no-proxy", "out", "proxy-method", "referer", "remote-time",
    "retry-wait", "split", "timeout", "user-agent", "use-head",
}
JOB_FIELD_TYPES = {
    "monitor_paused": bool,
    "ever_spiked": bool,
    "intervention_disabled": bool,
    "phase": str,
    "boot_id": str,
    "initial_cycles": int,
    "resume_at": (int, float),
    "cooldown_until": (int, float),
    "last_recovery_at": (int, float),
    "updated_at": (int, float),
}
RETRY_FIELD_TYPES = {
    "canonical_gid": str,
    "pending_gid": str,
    "old_gid": str,
    "submission_old_gid": str,
    "manual_stop": bool,
    "submission_unknown": bool,
    "submission_preexisting_gids": list,
    "retry_count": int,
    "submission_failures": int,
    "baseline_completed": int,
    "submission_baseline": int,
    "next_retry_at": (int, float),
    "completed_at": (int, float),
    "progress_confirmed_at": (int, float),
    "last_attempt_at": (int, float),
    "last_submission_failure_at": (int, float),
    "submission_started_at": (int, float),
    "submission_reconcile_at": (int, float),
    "updated_at": (int, float),
}


def _empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "speed_threshold_bytes_per_second": DEFAULT_SPEED_THRESHOLD,
        "boot_id": "",
        "jobs": {},
        "retry_paths": {},
        "error_event_gids": [],
        "error_event_seen_at": {},
        "error_event_retry_after": {},
        "last_stopped_reconcile_at": None,
    }


class Aria2RecoveryStateStore:
    """Small locked JSON store shared by the worker API and Aria2 service."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._thread_lock = threading.RLock()

    @contextmanager
    def _locked(self):
        ensure_private_directory(self.path.parent)
        with self._thread_lock, self.lock_path.open("a+") as lock_file:
            self.lock_path.chmod(0o600)
            try:
                flock(lock_file.fileno(), LOCK_EX)
                yield
            finally:
                try:
                    flock(lock_file.fileno(), LOCK_UN)
                except (OSError, TypeError):
                    pass

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _empty_state()
        except OSError as exc:
            raise RuntimeError("Unable to read Aria2 recovery state.") from exc
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("Aria2 recovery state is corrupt; preserving it for diagnosis.") from exc
        if not isinstance(value, dict) or value.get("version") != 1:
            raise RuntimeError("Aria2 recovery state has an unsupported format; preserving it.")
        state = _empty_state()
        state.update(value)
        for key in ("jobs", "retry_paths"):
            entries = state.get(key)
            if not isinstance(entries, dict) or any(
                not isinstance(entry, dict) for entry in entries.values()
            ):
                raise RuntimeError(
                    f"Aria2 recovery state field {key} is malformed; preserving it for diagnosis."
                )
            state[key] = {str(name): entry for name, entry in entries.items()}
        self._validate_entry_fields(state["jobs"], JOB_FIELD_TYPES, "jobs")
        self._validate_entry_fields(state["retry_paths"], RETRY_FIELD_TYPES, "retry_paths")
        error_events = state.get("error_event_gids")
        if not isinstance(error_events, list):
            raise RuntimeError(
                "Aria2 recovery state error-event queue is malformed; preserving it for diagnosis."
            )
        if any(
            not isinstance(gid, str) or not re.fullmatch(r"[0-9a-fA-F]{16}", gid)
            for gid in error_events
        ):
            raise RuntimeError(
                "Aria2 recovery state error-event queue contains invalid data; preserving it."
            )
        state["error_event_gids"] = list(dict.fromkeys(
            gid for gid in error_events
        ))[-MAX_PENDING_ERROR_EVENTS:]
        active_event_gids = set(state["error_event_gids"])
        for key in ("error_event_seen_at", "error_event_retry_after"):
            value = state.get(key)
            if not isinstance(value, dict):
                raise RuntimeError(
                    f"Aria2 recovery state field {key} is malformed; preserving it for diagnosis."
                )
            if any(
                isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
                for item in value.values()
            ):
                raise RuntimeError(
                    f"Aria2 recovery state field {key} contains invalid timestamps; preserving it."
                )
            state[key] = {gid: item for gid, item in value.items() if gid in active_event_gids}
        try:
            threshold = state["speed_threshold_bytes_per_second"]
        except KeyError as exc:
            raise RuntimeError("Aria2 recovery state has no speed threshold; preserving it.") from exc
        if isinstance(threshold, bool) or not isinstance(threshold, int) or not 0 <= threshold <= MAX_SPEED_THRESHOLD:
            raise RuntimeError("Aria2 recovery state speed threshold is malformed; preserving it.")
        last_reconcile = state.get("last_stopped_reconcile_at")
        if last_reconcile is not None and (
            isinstance(last_reconcile, bool)
            or not isinstance(last_reconcile, (int, float))
            or not math.isfinite(last_reconcile)
        ):
            raise RuntimeError("Aria2 recovery state reconciliation timestamp is malformed; preserving it.")
        return state

    @staticmethod
    def _validate_entry_fields(
        entries: dict[str, dict[str, Any]],
        expected_types: dict[str, type | tuple[type, ...]],
        section: str,
    ) -> None:
        for entry_id, entry in entries.items():
            for field, expected in expected_types.items():
                if field not in entry:
                    continue
                value = entry[field]
                valid = isinstance(value, expected)
                if expected is int:
                    valid = isinstance(value, int) and not isinstance(value, bool)
                elif expected is list:
                    valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
                elif expected == (int, float):
                    valid = (
                        not isinstance(value, bool)
                        and isinstance(value, (int, float))
                        and math.isfinite(value)
                    )
                if valid and field in {
                    "initial_cycles", "retry_count", "submission_failures",
                    "baseline_completed", "submission_baseline",
                }:
                    valid = value >= 0
                if not valid:
                    raise RuntimeError(
                        f"Aria2 recovery state {section}.{entry_id}.{field} is malformed; preserving it."
                    )

    def _write_unlocked(self, state: dict[str, Any]) -> None:
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(state, output, separators=(",", ":"), sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            self.path.chmod(0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def read(self) -> dict[str, Any]:
        with self._locked():
            return self._read_unlocked()

    def update(self, callback: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with self._locked():
            state = self._read_unlocked()
            callback(state)
            self._write_unlocked(state)
            return state

    def get_speed_threshold(self) -> int:
        return int(self.read()["speed_threshold_bytes_per_second"])

    def set_speed_threshold(self, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Speed threshold must be an integer.")
        threshold = value
        if threshold < 0 or threshold > MAX_SPEED_THRESHOLD:
            raise ValueError("Speed threshold is outside the supported range.")

        def update(state):
            state["speed_threshold_bytes_per_second"] = threshold

        self.update(update)
        return threshold

    def update_job(self, gid: str, values: dict[str, Any] | None = None, *, remove=False) -> None:
        def update(state):
            jobs = state["jobs"]
            if remove:
                jobs.pop(str(gid), None)
            else:
                current = jobs.setdefault(str(gid), {})
                current.update(values or {})
                current["updated_at"] = time.time()

        self.update(update)

    def update_retry(self, path: str, values: dict[str, Any] | None = None, *, remove=False) -> None:
        def update(state):
            retries = state["retry_paths"]
            if remove:
                retries.pop(path, None)
            else:
                current = retries.setdefault(path, {})
                current.update(values or {})
                current["updated_at"] = time.time()

        self.update(update)

    def consume_error_events(self, gids: set[str]) -> None:
        if not gids:
            return

        def update(state):
            state["error_event_gids"] = [
                str(gid) for gid in state["error_event_gids"] if str(gid) not in gids
            ]
            for key in ("error_event_seen_at", "error_event_retry_after"):
                for gid in gids:
                    state[key].pop(str(gid), None)

        self.update(update)


class Aria2RecoveryCoordinator:
    """One-second Aria2 observer; it never retries a live or intentionally paused job."""

    def __init__(
        self,
        rpc: Callable[..., Any],
        state_store: Aria2RecoveryStateStore,
        *,
        workspace_root: Path | str = "/workspace",
        clock: Callable[[], float] = time.time,
        interval_seconds: float = 1.0,
    ):
        self.rpc = rpc
        self.store = state_store
        self.workspace_root = Path(workspace_root).resolve(strict=False)
        self.clock = clock
        self.interval_seconds = max(0.1, float(interval_seconds))
        self.boot_id = str(uuid.uuid4())
        self.observations: dict[str, dict[str, Any]] = {}
        self.enforced_native_options: set[str] = set()
        self.store.update(lambda state: state.update({"boot_id": self.boot_id}))

    def tick(self) -> None:
        now = self.clock()
        active = self._list("tellActive", ["gid", "status", "completedLength", "totalLength", "downloadSpeed", "files"])
        waiting = self._list("tellWaiting", 0, 1000, ["gid", "status", "completedLength", "totalLength", "files"])
        state_snapshot = self.store.read()
        try:
            last_reconcile = (
                float(state_snapshot["last_stopped_reconcile_at"])
                if state_snapshot.get("last_stopped_reconcile_at") is not None
                else None
            )
        except (TypeError, ValueError):
            last_reconcile = None
        active_by_gid = {str(item.get("gid")): item for item in active if item.get("gid")}
        waiting_by_gid = {str(item.get("gid")): item for item in waiting if item.get("gid")}
        self.enforced_native_options.intersection_update(
            set(active_by_gid) | set(waiting_by_gid)
        )

        for job in [*active, *waiting]:
            gid = str(job.get("gid") or "")
            if not gid or gid in self.enforced_native_options:
                continue
            try:
                options = self.rpc("getOption", gid)
                if not isinstance(options, dict):
                    continue
                lowest_speed = self._parse_bytes(options.get("lowest-speed-limit", "0"))
                try:
                    max_tries = int(str(options.get("max-tries", "0") or "0"))
                except ValueError:
                    max_tries = 0
                if lowest_speed > 0 or max_tries != 0:
                    # Aria2 restarts an active transfer when these options change;
                    # do that once only for legacy jobs which still have unsafe values.
                    self.rpc("changeOption", gid, {"lowest-speed-limit": "0", "max-tries": "0"})
            except Exception:
                continue
            self.enforced_native_options.add(gid)

        resumed_gids = self._resume_monitor_paused(now)
        state_snapshot = self.store.read()
        threshold = int(state_snapshot["speed_threshold_bytes_per_second"])
        persisted_jobs = state_snapshot["jobs"]
        live_gids = set(active_by_gid) | set(waiting_by_gid) | resumed_gids
        for gid, state in persisted_jobs.items():
            if gid not in live_gids and not (
                isinstance(state, dict) and state.get("monitor_paused")
            ):
                self.store.update_job(gid, remove=True)
                self.observations.pop(gid, None)
        for job in active:
            if isinstance(job, dict) and job.get("gid"):
                self._observe_speed(job, threshold, now, persisted_jobs)
        # The one-second speed observer runs before optional error-event lookups,
        # which can wait on aria2 RPC. A stale stopped-list refresh also cannot
        # delay a pause/resume decision for a live transfer.
        stopped = []
        if last_reconcile is None or now - last_reconcile >= STOPPED_RECONCILE_SECONDS:
            stopped = self._list("tellStopped", 0, 1000, ["gid", "status", "errorCode", "errorMessage", "completedLength", "totalLength", "files"])
            self.store.update(lambda state: state.update({"last_stopped_reconcile_at": now}))
        event_state = self.store.read()
        error_events, consumed_events, deferred_events = self._load_error_events(
            event_state.get("error_event_gids", []),
            event_state.get("error_event_seen_at", {}),
            event_state.get("error_event_retry_after", {}),
            now,
        )
        if deferred_events:
            def defer(state):
                state["error_event_retry_after"].update(deferred_events)
                for gid in deferred_events:
                    state["error_event_seen_at"].setdefault(gid, now)
            self.store.update(defer)
        stopped_by_gid = {
            str(item.get("gid")): item
            for item in stopped
            if item.get("gid") and item.get("status") == "error"
        }
        stopped_by_gid.update({str(item["gid"]): item for item in error_events})
        stopped_errors = list(stopped_by_gid.values())
        self._retry_stopped_errors(active, waiting, stopped_errors, active_by_gid, waiting_by_gid, now)
        self.store.consume_error_events(consumed_events)

    def _list(self, method: str, *params) -> list[dict[str, Any]]:
        result = self.rpc(method, *params)
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]

    def _load_error_events(
        self,
        raw_gids: object,
        raw_seen_at: object,
        raw_retry_after: object,
        now: float,
    ) -> tuple[list[dict[str, Any]], set[str], dict[str, float]]:
        if not isinstance(raw_gids, list):
            return [], set(), {}
        seen_at = raw_seen_at if isinstance(raw_seen_at, dict) else {}
        retry_after = raw_retry_after if isinstance(raw_retry_after, dict) else {}
        jobs: list[dict[str, Any]] = []
        consumed: set[str] = set()
        deferred: dict[str, float] = {}
        checked = 0
        for raw_gid in raw_gids:
            gid = str(raw_gid or "")
            if not gid or len(gid) > 64:
                if gid:
                    consumed.add(gid)
                continue
            try:
                first_seen = float(seen_at.get(gid, now))
                retry_at = float(retry_after.get(gid, 0) or 0)
            except (TypeError, ValueError):
                first_seen, retry_at = now, 0
            if now - first_seen > ERROR_EVENT_MAX_AGE_SECONDS:
                # Periodic tellStopped reconciliation remains the durable fallback.
                consumed.add(gid)
                continue
            if now < retry_at:
                continue
            if checked >= MAX_ERROR_EVENTS_PER_TICK:
                break
            checked += 1
            try:
                job = self.rpc(
                    "tellStatus", gid,
                    ["gid", "status", "errorCode", "errorMessage", "completedLength", "totalLength", "files"],
                )
            except Exception:
                deferred[gid] = now + ERROR_EVENT_RETRY_SECONDS
                continue
            if not isinstance(job, dict):
                consumed.add(gid)
                continue
            status = str(job.get("status") or "")
            if status == "error":
                jobs.append(job)
                consumed.add(gid)
            elif status not in {"active", "waiting"}:
                # A stale hook notification must not keep a removed, completed,
                # or intentionally paused task in the durable queue forever.
                consumed.add(gid)
            else:
                deferred[gid] = now + ERROR_EVENT_ACTIVE_RETRY_SECONDS
        return jobs, consumed, deferred

    def _resume_monitor_paused(self, now: float) -> set[str]:
        resumed: set[str] = set()
        jobs = self.store.read()["jobs"]
        for gid, state in jobs.items():
            if not isinstance(state, dict) or not state.get("monitor_paused"):
                continue
            try:
                current = self.rpc("tellStatus", gid, ["gid", "status", "completedLength"])
                status = str(current.get("status") or "") if isinstance(current, dict) else "removed"
                if status == "paused":
                    same_boot = state.get("boot_id") == self.boot_id
                    if same_boot and now < float(state.get("resume_at", 0) or 0):
                        continue
                    self.rpc("unpause", gid)
                    self.store.update_job(gid, {
                        "monitor_paused": False,
                        "phase": "observe" if same_boot else "monitoring",
                        "observe_started_at": now if same_boot else 0,
                        "resume_at": 0,
                    })
                    self.observations[gid] = self._new_observation(
                        now,
                        int(str(current.get("completedLength", "0") or "0")),
                        observing=same_boot,
                    )
                    resumed.add(gid)
                elif status == "active":
                    self.store.update_job(gid, {
                        "monitor_paused": False, "phase": "monitoring", "resume_at": 0,
                    })
                    self.observations.pop(gid, None)
                    resumed.add(gid)
                else:
                    self.store.update_job(gid, remove=True)
                    self.observations.pop(gid, None)
            except Exception:
                continue
        return resumed

    def _new_observation(self, now: float, completed: int, *, observing=False) -> dict[str, Any]:
        return {
            "active_seconds": 0.0,
            "last_at": now,
            "last_completed": completed,
            "samples": deque([(now, completed)], maxlen=16),
            "warmup_finished_at": None,
            "phase": "observe" if observing else "monitoring",
            "observe_started_at": now if observing else 0.0,
            "observe_until": now + OBSERVE_SECONDS if observing else 0.0,
            "observe_spike": False,
        }

    def _observe_speed(
        self, job: dict[str, Any], threshold: int, now: float,
        persisted_jobs: dict[str, Any],
    ) -> None:
        gid = str(job["gid"])
        status = str(job.get("status") or "active")
        if status != "active":
            # A manual pause is never resumed or otherwise controlled.
            self.observations.pop(gid, None)
            return
        try:
            completed = max(0, int(str(job.get("completedLength", "0") or "0")))
        except ValueError:
            completed = 0
        observation = self.observations.get(gid)
        if observation is None:
            observation = self._new_observation(now, completed)
            self.observations[gid] = observation
            persisted = persisted_jobs.get(gid)
            if isinstance(persisted, dict) and persisted.get("phase") == "observe":
                # After restart samples are deliberately discarded; a fresh active warm-up applies.
                self.store.update_job(gid, {"phase": "monitoring", "monitor_paused": False})
            elif not isinstance(persisted, dict):
                self.store.update_job(gid, {"ever_spiked": False, "initial_cycles": 0, "phase": "monitoring"})
            return

        elapsed = max(0.0, now - observation["last_at"])
        if elapsed:
            observation["active_seconds"] += elapsed
        interval_rate = max(0, completed - observation["last_completed"]) / elapsed if elapsed else 0
        observation["last_at"] = now
        observation["last_completed"] = completed
        observation["samples"].append((now, completed))
        while observation["samples"] and now - observation["samples"][0][0] > LOW_WINDOW_SECONDS + 2:
            observation["samples"].popleft()

        persistent = persisted_jobs.get(gid, {})
        if threshold > 0 and interval_rate > threshold:
            if observation["phase"] == "observe":
                observation["observe_spike"] = True
            if not persistent.get("ever_spiked") or persistent.get("intervention_disabled"):
                self.store.update_job(gid, {
                    "ever_spiked": True, "intervention_disabled": False,
                    "initial_cycles": 0, "cooldown_until": 0,
                })
                persistent = {
                    **persistent,
                    "ever_spiked": True,
                    "intervention_disabled": False,
                    "initial_cycles": 0,
                    "cooldown_until": 0,
                }

        if observation["phase"] == "observe":
            if now >= observation["observe_until"]:
                if threshold <= 0:
                    self.store.update_job(gid, {"phase": "monitoring"})
                elif observation["observe_spike"]:
                    self.store.update_job(gid, {
                        "ever_spiked": True, "intervention_disabled": False,
                        "initial_cycles": 0, "cooldown_until": 0, "phase": "monitoring",
                    })
                else:
                    cycles = int(persistent.get("initial_cycles", 0) or 0)
                    ever_spiked = bool(persistent.get("ever_spiked"))
                    if not ever_spiked:
                        cycles += 1
                    self.store.update_job(gid, {
                        "initial_cycles": cycles,
                        "intervention_disabled": not ever_spiked and cycles >= 2,
                        "cooldown_until": now + COOLDOWN_SECONDS if ever_spiked or cycles < 2 else 0,
                        "phase": "monitoring",
                    })
                self.observations[gid] = self._new_observation(now, completed)
                self.observations[gid]["warmup_finished_at"] = now
                self.observations[gid]["active_seconds"] = WARMUP_SECONDS
            return

        if threshold <= 0:
            return
        if observation["warmup_finished_at"] is None:
            if observation["active_seconds"] < WARMUP_SECONDS:
                return
            observation["warmup_finished_at"] = now
            observation["samples"].clear()
            observation["samples"].append((now, completed))
            return
        samples = list(observation["samples"])
        baseline = next(((at, size) for at, size in samples if now - at >= LOW_WINDOW_SECONDS - 0.5), None)
        if baseline is None or baseline[0] < float(observation["warmup_finished_at"]):
            return
        window = now - baseline[0]
        average = max(0, completed - baseline[1]) / window if window > 0 else 0
        if average >= threshold:
            return
        if persistent.get("intervention_disabled") and not persistent.get("ever_spiked"):
            return
        if now < float(persistent.get("cooldown_until", 0) or 0):
            return
        self.store.update_job(gid, {
            "monitor_paused": True,
            "phase": "pause_intent",
            "resume_at": now + PAUSE_SECONDS,
            "boot_id": self.boot_id,
            "last_recovery_at": now,
        })
        try:
            self.rpc("pause", gid)
        except Exception:
            self.store.update_job(gid, {
                "monitor_paused": False,
                "phase": "monitoring",
                "resume_at": 0,
            })
            return
        self.store.update_job(gid, {
            "monitor_paused": True,
            "phase": "pause_wait",
            "resume_at": now + PAUSE_SECONDS,
            "boot_id": self.boot_id,
            "last_recovery_at": now,
        })
        self.observations.pop(gid, None)

    def _retry_stopped_errors(
        self,
        active: list[dict[str, Any]],
        waiting: list[dict[str, Any]],
        stopped: list[dict[str, Any]],
        active_by_gid: dict[str, dict],
        waiting_by_gid: dict[str, dict],
        now: float,
    ) -> None:
        self._reconcile_unknown_submissions(active, waiting, now)
        live_paths = self._path_set(active) | self._path_set(waiting)
        by_path: dict[str, list[dict[str, Any]]] = {}
        for job in stopped:
            if job.get("status") != "error":
                continue
            path = self._single_retryable_path(job)
            if path:
                by_path.setdefault(path, []).append(job)

        for path, state in self.store.read()["retry_paths"].items():
            if (
                state.get("pending_gid")
                or state.get("submission_unknown")
                or int(state.get("retry_count", 0) or 0) >= MAX_EXTERNAL_RETRIES
            ):
                continue
            canonical_gid = str(state.get("canonical_gid") or "")
            if not canonical_gid or path in by_path:
                continue
            if now < float(state.get("next_retry_at", 0) or 0):
                continue
            path_liveness = self._path_is_live(path, active, waiting)
            if path_liveness is True:
                self.store.update_retry(path, {
                    "canonical_gid": "", "pending_gid": "", "next_retry_at": 0,
                    "manual_stop": False,
                })
                continue
            if path_liveness is None:
                continue
            try:
                canonical = self.rpc(
                    "tellStatus", canonical_gid,
                    ["gid", "status", "errorCode", "errorMessage", "completedLength", "totalLength", "files"],
                )
            except Exception:
                continue
            if not isinstance(canonical, dict):
                self.store.update_retry(path, remove=True)
                continue
            status = str(canonical.get("status") or "")
            if status == "error" and self._single_retryable_path(canonical) == path:
                by_path[path] = [canonical]
            elif status in {"active", "waiting"}:
                self.store.update_retry(path, {
                    "canonical_gid": "", "next_retry_at": 0, "manual_stop": False,
                })
            elif status == "paused":
                self.store.update_retry(path, {
                    "canonical_gid": "", "next_retry_at": 0, "manual_stop": True,
                })
            else:
                self.store.update_retry(path, remove=True)

        retry_states = self.store.read()["retry_paths"]
        resolved_paths: set[str] = set()
        for path, state in retry_states.items():
            pending_gid = str(state.get("pending_gid") or "")
            if not pending_gid:
                continue
            pending = active_by_gid.get(pending_gid) or waiting_by_gid.get(pending_gid)
            if pending is None:
                try:
                    pending = self.rpc("tellStatus", pending_gid, ["gid", "status", "completedLength", "totalLength", "files"])
                except Exception:
                    continue
            status = str(pending.get("status") or "") if isinstance(pending, dict) else ""
            completed = self._length(pending, "completedLength") if isinstance(pending, dict) else 0
            baseline = int(state.get("baseline_completed", 0) or 0)
            if status == "active" and completed > baseline:
                self._replace_canonical_after_progress(path, state, pending_gid, now)
                continue
            if status in {"active", "waiting", "paused"}:
                continue
            if status == "complete":
                resolved_paths.add(path)
                if completed > baseline:
                    self._replace_canonical_after_progress(path, state, pending_gid, now)
                else:
                    old_gid = str(state.get("old_gid") or state.get("canonical_gid") or "")
                    if old_gid and old_gid != pending_gid:
                        try:
                            self.rpc("removeDownloadResult", old_gid)
                        except Exception:
                            pass
                    # Completion is authoritative even for a zero-byte file. Keep
                    # the retry budget unless actual byte progress reset it.
                    self.store.update_retry(path, {
                        "canonical_gid": pending_gid,
                        "pending_gid": "",
                        "next_retry_at": 0,
                        "old_gid": "",
                        "manual_stop": False,
                        "completed_at": now,
                    })
                continue
            if status == "error":
                try:
                    self.rpc("removeDownloadResult", pending_gid)
                except Exception:
                    pass
                retry_count = int(state.get("retry_count", 0) or 0)
                self.store.update_retry(path, {
                    "pending_gid": "",
                    "next_retry_at": now + self._backoff(retry_count),
                    "manual_stop": False,
                })
            elif status in {"removed", "paused"}:
                self.store.update_retry(path, {"pending_gid": "", "manual_stop": True})

        for path, errors in by_path.items():
            if path in resolved_paths:
                continue
            state = self.store.read()["retry_paths"].get(path)
            if state and state.get("pending_gid"):
                continue
            if state and state.get("submission_unknown"):
                continue
            if path in live_paths:
                # An independently resumed replacement is confirmed live; old error
                # rows can be removed without touching the partial output file.
                for old in errors:
                    try:
                        self.rpc("removeDownloadResult", str(old.get("gid") or ""))
                    except Exception:
                        pass
                if state:
                    self.store.update_retry(path, {
                        "canonical_gid": "",
                        "pending_gid": "",
                        "next_retry_at": 0,
                    })
                continue
            if state and state.get("manual_stop"):
                continue
            gids = {str(job.get("gid") or "") for job in errors}
            canonical_gid = str(state.get("canonical_gid") or "") if state else ""
            canonical = next((job for job in errors if job.get("gid") == canonical_gid), None)
            if canonical is None:
                canonical = errors[0]
                canonical_gid = str(canonical.get("gid") or "")
                if not state:
                    state = {
                        "canonical_gid": canonical_gid,
                        "retry_count": 0,
                        "pending_gid": "",
                        "next_retry_at": now + self._backoff(0),
                        "manual_stop": False,
                    }
                    self.store.update_retry(path, state)
                    state = self.store.read()["retry_paths"][path]
                else:
                    state = {**state, "canonical_gid": canonical_gid}
                    self.store.update_retry(path, {"canonical_gid": canonical_gid})

            # Keep one stopped error record for this output path. Aria2 result removal never deletes files.
            for duplicate_gid in gids - {canonical_gid}:
                try:
                    self.rpc("removeDownloadResult", duplicate_gid)
                except Exception:
                    pass

            state = self.store.read()["retry_paths"].get(path, state)
            retry_count = int(state.get("retry_count", 0) or 0)
            if retry_count >= MAX_EXTERNAL_RETRIES:
                continue
            if (
                retry_count == 0
                and not float(state.get("next_retry_at", 0) or 0)
                and str(state.get("canonical_gid") or "") == canonical_gid
            ):
                self.store.update_retry(path, {"next_retry_at": now + self._backoff(0)})
                continue
            if now < float(state.get("next_retry_at", 0) or 0):
                continue
            path_liveness = self._path_is_live(path, active, waiting)
            if path_liveness is True:
                for old in errors:
                    try:
                        self.rpc("removeDownloadResult", str(old.get("gid") or ""))
                    except Exception:
                        pass
                self.store.update_retry(path, {
                    "canonical_gid": "", "pending_gid": "", "next_retry_at": 0,
                    "manual_stop": False,
                })
                continue
            if path_liveness is None:
                continue
            self._launch_retry(path, canonical, state, now)

    def _launch_retry(self, path: str, job: dict[str, Any], state: dict[str, Any], now: float) -> None:
        gid = str(state.get("canonical_gid") or job.get("gid") or "")
        files = job.get("files")
        if not gid or not isinstance(files, list) or len(files) != 1:
            return
        file_info = files[0]
        uri_entries = file_info.get("uris") if isinstance(file_info, dict) else None
        uris = [str(item.get("uri") or "") for item in uri_entries or [] if isinstance(item, dict) and item.get("uri")]
        if not uris:
            return
        try:
            options_result = self.rpc("getOption", gid)
            if not isinstance(options_result, dict):
                raise RuntimeError("aria2 returned invalid retry options")
            options = {
                key: str(value) for key, value in options_result.items()
                if key in RETRY_OPTION_KEYS and value is not None and str(value) != ""
            }
            options.update({
                "dir": str(Path(path).parent),
                "out": Path(path).name,
                "continue": "true",
                "always-resume": "true",
                "auto-file-renaming": "false",
                "allow-overwrite": "false",
                "lowest-speed-limit": "0",
                "max-tries": "0",
            })
            preexisting_stopped_gids = [
                str(item.get("gid") or "")
                for item in self._find_stopped_path_jobs(path)
                if item.get("gid")
            ]
        except Exception:
            self._record_submission_failure(path, now)
            return

        baseline = self._length(job, "completedLength")
        self.store.update_retry(path, {
            "submission_unknown": True,
            "submission_started_at": now,
            "submission_reconcile_at": now + 5,
            "submission_baseline": baseline,
            "submission_old_gid": gid,
            "submission_preexisting_gids": preexisting_stopped_gids,
        })
        try:
            replacement = self.rpc("addUri", uris, options)
        except Exception:
            # The RPC may time out after aria2 accepted the request. Leave the
            # durable intent in place until active/waiting/stopped are reconciled.
            return
        if not isinstance(replacement, str) or not replacement:
            return
        self.store.update_retry(path, {
            "pending_gid": replacement,
            "baseline_completed": baseline,
            "old_gid": gid,
            "retry_count": int(state.get("retry_count", 0) or 0) + 1,
            "submission_unknown": False,
            "submission_failures": 0,
            "submission_reconcile_at": 0,
            "submission_preexisting_gids": [],
            "last_attempt_at": now,
            "next_retry_at": 0,
            "manual_stop": False,
        })

    def _record_submission_failure(self, path: str, now: float) -> None:
        latest = self.store.read()["retry_paths"].get(path, {})
        failures = int(latest.get("submission_failures", 0) or 0) + 1
        self.store.update_retry(path, {
            "submission_failures": failures,
            "last_submission_failure_at": now,
            "next_retry_at": now + self._backoff(failures - 1),
        })

    def _reconcile_unknown_submissions(
        self,
        active: list[dict[str, Any]],
        waiting: list[dict[str, Any]],
        now: float,
    ) -> None:
        for path, state in self.store.read()["retry_paths"].items():
            if not state.get("submission_unknown"):
                continue
            if now < float(state.get("submission_reconcile_at", 0) or 0):
                continue
            old_gid = str(state.get("submission_old_gid") or state.get("canonical_gid") or "")
            try:
                replacement = self._find_live_path_job(path, active, waiting, exclude_gid=old_gid)
                if replacement is None:
                    replacement = self._find_stopped_path_job(
                        path,
                        exclude_gids={old_gid, *state.get("submission_preexisting_gids", [])},
                    )
            except Exception:
                self.store.update_retry(path, {"submission_reconcile_at": now + ERROR_EVENT_RETRY_SECONDS})
                continue
            if replacement is None:
                failures = int(state.get("submission_failures", 0) or 0) + 1
                self.store.update_retry(path, {
                    "submission_unknown": False,
                    "submission_reconcile_at": 0,
                    "submission_failures": failures,
                    "last_submission_failure_at": now,
                    "next_retry_at": now + self._backoff(failures - 1),
                })
                continue
            replacement_gid = str(replacement.get("gid") or "")
            if not replacement_gid:
                self.store.update_retry(path, {"submission_reconcile_at": now + ERROR_EVENT_RETRY_SECONDS})
                continue
            self.store.update_retry(path, {
                "pending_gid": replacement_gid,
                "baseline_completed": int(state.get("submission_baseline", 0) or 0),
                "old_gid": old_gid,
                "retry_count": int(state.get("retry_count", 0) or 0) + 1,
                "submission_unknown": False,
                "submission_failures": 0,
                "submission_reconcile_at": 0,
                "submission_preexisting_gids": [],
                "last_attempt_at": float(state.get("submission_started_at", now) or now),
                "next_retry_at": 0,
                "manual_stop": False,
            })

    def _find_live_path_job(
        self,
        path: str,
        active: list[dict[str, Any]],
        waiting: list[dict[str, Any]],
        *,
        exclude_gid: str,
    ) -> dict[str, Any] | None:
        for job in [*active, *waiting]:
            if str(job.get("gid") or "") != exclude_gid and path in self._path_set([job]):
                return job
        page_size = 1000
        if len(waiting) < page_size:
            return None
        offset = len(waiting)
        keys = ["gid", "status", "completedLength", "totalLength", "files"]
        while True:
            page = self.rpc("tellWaiting", offset, page_size, keys)
            if not isinstance(page, list):
                raise RuntimeError("Aria2 waiting list response is invalid.")
            page = [item for item in page if isinstance(item, dict)]
            for job in page:
                if str(job.get("gid") or "") != exclude_gid and path in self._path_set([job]):
                    return job
            if len(page) < page_size:
                return None
            offset += len(page)

    def _find_stopped_path_job(
        self, path: str, *, exclude_gids: set[str]
    ) -> dict[str, Any] | None:
        for job in self._find_stopped_path_jobs(path):
            if str(job.get("gid") or "") not in exclude_gids:
                return job
        return None

    def _find_stopped_path_jobs(self, path: str) -> list[dict[str, Any]]:
        page_size = 1000
        offset = 0
        keys = ["gid", "status", "errorCode", "errorMessage", "completedLength", "totalLength", "files"]
        matches: list[dict[str, Any]] = []
        while True:
            page = self.rpc("tellStopped", offset, page_size, keys)
            if not isinstance(page, list):
                raise RuntimeError("Aria2 stopped list response is invalid.")
            page = [item for item in page if isinstance(item, dict)]
            for job in page:
                if path in self._path_set([job]):
                    matches.append(job)
            if len(page) < page_size:
                return matches
            offset += len(page)

    def _replace_canonical_after_progress(self, path: str, state: dict[str, Any], gid: str, now: float) -> None:
        old_gid = str(state.get("old_gid") or state.get("canonical_gid") or "")
        if old_gid and old_gid != gid:
            try:
                self.rpc("removeDownloadResult", old_gid)
            except Exception:
                pass
        self.store.update_retry(path, {
            "canonical_gid": gid,
            "pending_gid": "",
            "retry_count": 0,
            "next_retry_at": 0,
            "baseline_completed": 0,
            "old_gid": "",
            "manual_stop": False,
            "progress_confirmed_at": now,
        })

    def _single_retryable_path(self, job: dict[str, Any]) -> str:
        files = job.get("files")
        if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
            return ""
        path = str(files[0].get("path") or "")
        candidate = Path(path).resolve(strict=False)
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError:
            return ""
        uris = files[0].get("uris")
        schemes = {
            str(item.get("uri") or "").split(":", 1)[0].lower()
            for item in uris or [] if isinstance(item, dict) and ":" in str(item.get("uri") or "")
        }
        if not schemes or not schemes.issubset(RETRYABLE_SCHEMES):
            return ""
        return str(candidate)

    @staticmethod
    def _path_set(jobs: list[dict[str, Any]]) -> set[str]:
        paths: set[str] = set()
        for job in jobs:
            for file_info in job.get("files", []) if isinstance(job.get("files"), list) else []:
                if isinstance(file_info, dict) and file_info.get("path"):
                    paths.add(str(Path(str(file_info["path"])).resolve(strict=False)))
        return paths

    def _path_is_live(
        self,
        path: str,
        active: list[dict[str, Any]],
        waiting: list[dict[str, Any]],
    ) -> bool | None:
        if path in self._path_set(active) or path in self._path_set(waiting):
            return True
        page_size = 1000
        if len(waiting) < page_size:
            return False
        offset = len(waiting)
        keys = ["gid", "status", "completedLength", "totalLength", "files"]
        while True:
            try:
                page = self.rpc("tellWaiting", offset, page_size, keys)
            except Exception:
                # Unknown queue state must never trigger a potentially duplicate retry.
                return None
            if not isinstance(page, list):
                return None
            page = [item for item in page if isinstance(item, dict)]
            if path in self._path_set(page):
                return True
            if len(page) < page_size:
                return False
            offset += len(page)

    @staticmethod
    def _length(job: dict[str, Any], key: str) -> int:
        try:
            return max(0, int(str(job.get(key, "0") or "0")))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _parse_bytes(value: object) -> int:
        match = re.fullmatch(r"\s*(\d+)([KMG]?)\s*", str(value or "0"), re.IGNORECASE)
        if not match:
            return 0
        multiplier = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[match.group(2).upper()]
        return int(match.group(1)) * multiplier

    @staticmethod
    def _backoff(retry_count: int) -> int:
        return RETRY_BACKOFF_SECONDS[min(max(0, retry_count), len(RETRY_BACKOFF_SECONDS) - 1)]
