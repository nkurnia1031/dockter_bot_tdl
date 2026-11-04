"""Durably report explicit profile installs to the gateway."""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from tme3bot.names import normalize_profile_name
from tme3bot.persistence import write_json_atomic_private


LOGGER = logging.getLogger(__name__)
_MAX_PENDING_EVENTS = 10_000
_MAX_EVENT_RUNS = 512
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_PHASES = {
    "queued", "archive_download",
    "bundle_validation", "session_validation", "session_install", "session_commit",
    "worker_unreachable", "completed", "cancelled",
    "download_staging", "download_validation", "download_install",
    "export_staging", "export_validation", "export_install",
    "upload_staging", "upload_validation", "upload_install", "identity_install",
    "transaction_rollback", "installation_reused", "failed",
}
_STATUSES = {"queued", "running", "succeeded", "failed", "waiting", "cancelled"}


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


class ProfileDistributionEventReporter:
    """Sequence and retry delivery events for operator-started profile distribution."""

    def __init__(
        self,
        config: Any,
        *,
        request: Callable[[str, str, bytes | None], tuple[bytes, Any]] | None = None,
        worker_token_provider: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        state_root = Path(config.state_file).parent
        self.path = state_root / "profile-distribution-events.json"
        self._request_override = request
        self._worker_token_provider = worker_token_provider
        self._lock = threading.RLock()
        self._outbox_lock = threading.Lock()
        self._state = self._load_state()

    def seed_external_event_sequence(self, run_id: str, sequence: int) -> None:
        normalized = str(run_id or "")
        if not _RUN_ID_RE.fullmatch(normalized) or type(sequence) is not int or sequence < 0:
            raise ValueError("ID operasi distribusi profil tidak valid.")
        with self._lock:
            sequences = self._state.setdefault("external_event_sequences", {})
            sequences[normalized] = max(int(sequences.get(normalized, 0)), sequence)
            self._trim_sequences(sequences)
            self._save_locked()

    def next_external_event_sequence(self, run_id: str) -> int:
        normalized = str(run_id or "")
        if not _RUN_ID_RE.fullmatch(normalized):
            raise ValueError("ID operasi distribusi profil tidak valid.")
        with self._lock:
            sequences = self._state.setdefault("external_event_sequences", {})
            sequence = int(sequences.get(normalized, 0)) + 1
            sequences[normalized] = sequence
            self._trim_sequences(sequences)
            self._save_locked()
            return sequence

    def report_external_event(
        self,
        *,
        run_id: str,
        sequence: int,
        profile: str,
        revision: int,
        phase: str,
        status: str,
        code: str = "",
        details: dict[str, Any] | None = None,
        distribution_operation_id: str = "",
    ) -> None:
        event = self._safe_event({
            "profile": profile,
            "run_id": run_id,
            "sequence": sequence,
            "revision": revision,
            "phase": phase,
            "status": status,
            "code": code,
            "details": details or {},
            "distribution_operation_id": distribution_operation_id,
        })
        if event is None:
            LOGGER.warning("Skipped an invalid profile distribution event")
            return
        with self._outbox_lock:
            identity = self._identity(event)
            with self._lock:
                pending = self._state.setdefault("pending_events", [])
                if not any(self._identity(item) == identity for item in pending):
                    if len(pending) >= _MAX_PENDING_EVENTS:
                        LOGGER.error("Profile distribution event outbox is full")
                        return
                    pending.append(event)
                    self._save_locked()
            self._flush_locked()

    def _flush_locked(self) -> None:
        while True:
            with self._lock:
                pending = self._state.setdefault("pending_events", [])
                event = dict(pending[0]) if pending else None
            if event is None:
                return
            identity = self._identity(event)
            try:
                operation_id = str(event.pop("distribution_operation_id", ""))
                if operation_id:
                    event.pop("run_id", None)
                    path = f"/internal/v1/profile-distributions/{quote(operation_id, safe='')}/events"
                else:
                    path = "/internal/v1/profile-install/events"
                body, _ = self._request(
                    "POST", path, json.dumps(event, separators=(",", ":")).encode(), timeout=3
                )
                response = json.loads(body.decode("utf-8"))
                if not isinstance(response, dict) or response.get("accepted") is not True:
                    return
            except Exception as exc:
                LOGGER.debug("Could not report profile distribution event (%s)", type(exc).__name__)
                return
            with self._lock:
                self._state["pending_events"] = [
                    item for item in self._state.setdefault("pending_events", [])
                    if self._identity(item) != identity
                ]
                self._save_locked()

    def _request(
        self, method: str, path: str, data: bytes | None, *, timeout: float
    ) -> tuple[bytes, Any]:
        if self._request_override is not None:
            return self._request_override(method, path, data)
        base_url = str(getattr(self.config, "backend_api_url", "") or "").rstrip("/")
        internal_token = str(getattr(self.config, "backend_internal_token", "") or "")
        worker_name = str(getattr(self.config, "backup_node_name", "") or "").strip()
        token_provider = self._worker_token_provider
        worker_token = str(token_provider() or "") if callable(token_provider) else str(
            getattr(self.config, "worker_api_token", "") or ""
        )
        if not base_url or not internal_token or not worker_name or not worker_token:
            raise RuntimeError("WORKER_IDENTITY_NOT_CONFIGURED")
        if not _secure_backend_url(base_url):
            raise RuntimeError("PROFILE_TRANSFER_REQUIRES_HTTPS")
        headers = {
            "Authorization": f"Bearer {internal_token}",
            "X-Worker-Name": worker_name,
            "X-Worker-Token": worker_token,
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(base_url + path, data=data, headers=headers, method=method)
        try:
            opener = build_opener(ProxyHandler({}), _RejectRedirects())
            with opener.open(request, timeout=timeout) as response:
                return response.read(1024 * 1024), response.headers
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"PROFILE_DISTRIBUTION_EVENT_HTTP_{exc.code}") from None

    def _load_state(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        raw = raw if isinstance(raw, dict) else {}
        pending_raw = raw.get("pending_events", raw.get("pending_sync_events", []))
        pending: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int]] = set()
        for item in pending_raw if isinstance(pending_raw, list) else []:
            safe = self._safe_event(item) if isinstance(item, dict) else None
            if safe is None or self._identity(safe) in seen:
                continue
            seen.add(self._identity(safe))
            pending.append(safe)
            if len(pending) >= _MAX_PENDING_EVENTS:
                break
        sequences = raw.get("external_event_sequences", {})
        safe_sequences = {
            str(run_id): sequence
            for run_id, sequence in sequences.items()
            if isinstance(sequences, dict)
            and _RUN_ID_RE.fullmatch(str(run_id))
            and type(sequence) is int
            and 0 < sequence <= 2**31 - 1
        } if isinstance(sequences, dict) else {}
        return {"pending_events": pending, "external_event_sequences": dict(list(safe_sequences.items())[-_MAX_EVENT_RUNS:])}

    def _save_locked(self) -> None:
        write_json_atomic_private(self.path, self._state)

    @staticmethod
    def _trim_sequences(sequences: dict[str, int]) -> None:
        while len(sequences) > _MAX_EVENT_RUNS:
            sequences.pop(next(iter(sequences)))

    @staticmethod
    def _identity(event: dict[str, Any]) -> tuple[str, str, int]:
        return (str(event.get("profile") or ""), str(event.get("run_id") or ""), int(event.get("sequence") or 0))

    @staticmethod
    def _safe_event(value: dict[str, Any]) -> dict[str, Any] | None:
        profile = normalize_profile_name(str(value.get("profile") or ""))
        run_id = str(value.get("run_id") or "")
        sequence, revision = value.get("sequence"), value.get("revision")
        phase, status = str(value.get("phase") or ""), str(value.get("status") or "")
        if (
            not profile or not _RUN_ID_RE.fullmatch(run_id)
            or type(sequence) is not int or not 1 <= sequence <= 2**31 - 1
            or type(revision) is not int or not 1 <= revision <= 2**31 - 1
            or phase not in _PHASES or status not in _STATUSES
        ):
            return None
        event: dict[str, Any] = {
            "profile": profile,
            "run_id": run_id,
            "sequence": sequence,
            "revision": revision,
            "phase": phase,
            "status": status,
        }
        code = re.sub(r"[^A-Z0-9_-]", "", str(value.get("code") or "").upper())[:64]
        if code:
            event["code"] = code
        operation_id = str(value.get("distribution_operation_id") or "")
        if operation_id:
            if not re.fullmatch(r"[0-9a-fA-F-]{36}", operation_id):
                return None
            event["distribution_operation_id"] = operation_id
        details = value.get("details")
        if isinstance(details, dict):
            safe_details = {
                key: max(0, min(2**31 - 1, int(item)))
                for key, item in details.items()
                if key in {"desired_revision", "installed_revision", "bundle_bytes", "entry_count", "attempt"}
                and type(item) is int
            }
            if safe_details:
                event["details"] = safe_details
        return event


def _secure_backend_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value))
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return False
        return parsed.scheme == "https" or (
            parsed.scheme == "http"
            and parsed.hostname.lower() in {"backend", "worker-local", "local", "localhost", "127.0.0.1", "::1"}
        )
    except ValueError:
        return False
