"""Pull versioned TDL profiles from the backend vault into a worker."""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import re
import threading
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from tme3bot.names import normalize_profile_name
from tme3bot.persistence import write_json_atomic_private
from tme3bot.profile_provisioning import (
    MAX_PROFILE_BUNDLE_BYTES,
    profile_bundle_identity,
)


LOGGER = logging.getLogger(__name__)
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_SUPPORTED_FORMAT = 1
_MAX_QUEUED_SYNC_REQUESTS = 32


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


class ProfileSyncError(RuntimeError):
    """An error safe to classify without retaining a response body or URL."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ProfileSyncClient:
    """Fetch, verify, safely install, and ACK backend-owned profile revisions."""

    def __init__(
        self,
        config: Any,
        profile_manager: Any,
        session_manager: Any,
        *,
        install_bundle: Callable[[str, int, bytes, str], Any],
        commit_bundle: Callable[[str, str], bool],
        rollback_bundle: Callable[[str, str], bool],
        request: Callable[[str, str, bytes | None], tuple[bytes, Any]] | None = None,
    ) -> None:
        self.config = config
        self.profile_manager = profile_manager
        self.session_manager = session_manager
        self.install_bundle = install_bundle
        self.commit_bundle = commit_bundle
        self.rollback_bundle = rollback_bundle
        self._request_override = request
        self.path = Path(config.state_file).parent / "profile-sync.json"
        self._condition = threading.Condition(threading.RLock())
        self._sync_lock = threading.Lock()
        self._requests: queue.Queue[tuple[str | None, str]] = queue.Queue()
        self._queued: set[tuple[str | None, str]] = set()
        self._active_request: tuple[str | None, str] | None = None
        self._legacy_discovery_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state = self._load_state()
        self._startup_checked = not self.enabled

    @property
    def enabled(self) -> bool:
        base_url = str(getattr(self.config, "backend_api_url", "") or "").rstrip("/")
        return bool(
            base_url
            and getattr(self.config, "backend_internal_token", "")
            and getattr(self.config, "backup_node_name", "")
            and getattr(self.config, "worker_api_token", "")
            and _secure_backend_url(base_url)
        )

    def start(self) -> None:
        """Start one background pull on worker startup without blocking API boot."""
        self.request_sync(mode="check", profile=None)

    def request_sync(
        self, *, mode: str = "check", profile: str | None = None
    ) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Sinkronisasi profil backend belum dikonfigurasi.")
        mode = str(mode or "check").strip().lower()
        if mode not in {"check", "repair"}:
            raise ValueError("Mode sinkronisasi harus check atau repair.")
        normalized = normalize_profile_name(profile) if profile else None
        if profile and not normalized:
            raise ValueError("Nama profil tidak valid.")
        key = (normalized, mode)
        with self._condition:
            if (
                key not in self._queued
                and key != self._active_request
                and len(self._queued) >= _MAX_QUEUED_SYNC_REQUESTS
            ):
                raise RuntimeError("Antrean sinkronisasi profil penuh.")
            if key not in self._queued and key != self._active_request:
                self._queued.add(key)
                self._requests.put(key)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run_requests,
                    daemon=True,
                    name="worker-profile-sync",
                )
                self._thread.start()
            self._condition.notify_all()
        return {"accepted": True, "status": "sync_pending", "profile": normalized}

    def sync_now(self, *, mode: str = "check", profile: str | None = None) -> dict[str, Any]:
        """Synchronize inline for a durable profile.sync worker operation."""
        if not self.enabled:
            return {"status": "disabled", "synced": 0}
        mode = str(mode or "check").strip().lower()
        if mode not in {"check", "repair"}:
            raise ValueError("Mode sinkronisasi harus check atau repair.")
        normalized = normalize_profile_name(profile) if profile else None
        if profile and not normalized:
            raise ValueError("Nama profil tidak valid.")
        with self._sync_lock:
            try:
                return self._sync(mode=mode, profile=normalized)
            finally:
                self._mark_startup_checked()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            state = json.loads(json.dumps(self._state))
            active = self._active_request
            queued = sorted(
                (profile or "*", mode) for profile, mode in self._queued
            )
        public_profiles = {
            name: {
                key: row.get(key)
                for key in (
                    "desired_revision",
                    "installed_revision",
                    "bundle_sha256",
                    "installed_sha256",
                    "status",
                    "error_code",
                    "updated_at",
                )
            }
            for name, row in state.get("profiles", {}).items()
        }
        return {
            "backend_available": state.get("backend_available"),
            "status": (
                "disabled"
                if not self.enabled
                else (
                    self._worker_status(state)
                    if self._startup_checked
                    else "sync_pending"
                )
            ),
            "last_checked_at": state.get("last_checked_at", ""),
            "managed_profiles": list(state.get("managed_profiles", [])),
            "profiles": public_profiles,
            "active_request": (
                {"profile": active[0], "mode": active[1]} if active else None
            ),
            "queued_requests": [
                {"profile": profile, "mode": mode} for profile, mode in queued
            ],
        }

    def profile_ready(self, profile: str, expected_revision: int = 0) -> bool:
        normalized = normalize_profile_name(profile)
        if not normalized:
            return False
        if not self.enabled:
            try:
                return not expected_revision and bool(
                    self.session_manager.verify_installed(normalized)
                )
            except Exception:
                return False
        with self._condition:
            if not self._startup_checked:
                return False
            if self._state.get("backend_available") is not True:
                return False
            row = self._state.get("profiles", {}).get(normalized)
            managed = set(self._state.get("managed_profiles", []))
            if normalized in managed:
                if not isinstance(row, dict) or row.get("status") != "ready":
                    return False
                installed = int(row.get("installed_revision") or 0)
                desired = int(row.get("desired_revision") or 0)
                return (
                    installed == desired
                    and (not expected_revision or expected_revision == installed)
                )
        # Profiles absent from the vault manifest are legacy, read-only local
        # profiles. They remain usable only while both independent sessions
        # and their identity are present.
        try:
            return bool(self.session_manager.verify_installed(normalized))
        except Exception:
            return False

    def wait_until_ready(
        self,
        profile: str,
        expected_revision: int = 0,
        *,
        cancelled: Callable[[], bool] | None = None,
        on_wait: Callable[[str], None] | None = None,
    ) -> bool:
        normalized = normalize_profile_name(profile)
        if not normalized:
            return False
        if not self.enabled:
            if expected_revision:
                raise ProfileSyncError("PROFILE_REVISION_MISMATCH")
            try:
                return bool(self.session_manager.verify_installed(normalized))
            except Exception:
                return False
        announced: str | None = None
        while True:
            if cancelled is not None and cancelled():
                return False
            with self._condition:
                state = self._state
                if not self._startup_checked:
                    reason = "sync_pending"
                elif state.get("backend_available") is True:
                    row = state.get("profiles", {}).get(normalized)
                    managed = set(state.get("managed_profiles", []))
                    if normalized in managed:
                        status = str((row or {}).get("status") or "sync_pending")
                        desired = int((row or {}).get("desired_revision") or 0)
                        installed = int((row or {}).get("installed_revision") or 0)
                        if status == "ready" and installed == desired:
                            if expected_revision and installed != expected_revision:
                                raise ProfileSyncError("PROFILE_REVISION_MISMATCH")
                            return True
                        reason = status
                    else:
                        try:
                            legacy_identity = self.session_manager.verify_installed(
                                normalized
                            )
                        except Exception:
                            legacy_identity = False
                        if legacy_identity is not False:
                            if expected_revision:
                                raise ProfileSyncError("PROFILE_REVISION_MISMATCH")
                            return True
                        reason = "legacy_profile_unavailable"
                else:
                    reason = "waiting_worker"
                should_announce = reason != announced
                if should_announce:
                    announced = reason
                    # Run callback outside the condition below.
                if not should_announce or on_wait is None:
                    self._condition.wait(timeout=1.0)
                    continue
            try:
                on_wait(reason)
            except Exception:
                LOGGER.debug("Could not report profile sync wait state")

    def _run_requests(self) -> None:
        while True:
            key = self._requests.get()
            with self._condition:
                self._queued.discard(key)
                self._active_request = key
                self._condition.notify_all()
            try:
                with self._sync_lock:
                    self._sync(mode=key[1], profile=key[0])
            except Exception as exc:  # Defensive boundary for the daemon loop.
                LOGGER.warning("Worker profile sync failed (%s)", type(exc).__name__)
                self._set_backend_unavailable("SYNC_FAILED")
            finally:
                self._mark_startup_checked()
                with self._condition:
                    self._active_request = None
                    self._condition.notify_all()
                self._requests.task_done()

    def _sync(self, *, mode: str, profile: str | None) -> dict[str, Any]:
        try:
            manifest = self._get_manifest()
        except Exception as exc:
            code = getattr(exc, "code", "BACKEND_UNAVAILABLE")
            self._set_backend_unavailable(str(code))
            return {"status": "waiting_worker", "synced": 0}

        try:
            entries = self._validate_manifest(manifest)
        except ProfileSyncError as exc:
            self._set_backend_unavailable(exc.code)
            return {"status": "waiting_worker", "synced": 0}
        now = _now()
        current_profiles = {str(item["profile"]) for item in entries}
        with self._condition:
            previous_managed = set(self._state.get("managed_profiles", []))
            managed = sorted(previous_managed | current_profiles)
            self._state["backend_available"] = True
            self._state["managed_profiles"] = managed
            self._state["last_checked_at"] = now
            rows = self._state.setdefault("profiles", {})
            for entry in entries:
                name = entry["profile"]
                old = rows.get(name, {})
                selected = profile is None or profile == name
                changed = (
                    int(old.get("desired_revision") or 0) != entry["revision"]
                    or str(old.get("bundle_sha256") or "").lower()
                    != entry["bundle_sha256"]
                )
                rows[name] = {
                    "desired_revision": entry["revision"],
                    "installed_revision": int(old.get("installed_revision") or 0),
                    "bundle_sha256": entry["bundle_sha256"],
                    "installed_sha256": str(old.get("installed_sha256") or ""),
                    "telegram_user_id": _positive_int(old.get("telegram_user_id")),
                    "status": (
                        "sync_pending"
                        if selected or changed or not old
                        else _safe_status(old.get("status"))
                    ),
                    "error_code": "" if selected or changed else _safe_code(old.get("error_code")),
                    "updated_at": now,
                }
            for missing in previous_managed - current_profiles:
                old = rows.setdefault(missing, {})
                old.update({"status": "not_assigned", "error_code": "PROFILE_NOT_ASSIGNED", "updated_at": now})
            self._save_locked()
            self._condition.notify_all()

        # Keep the old, metadata-only discovery path for local profiles that
        # are not in the backend vault manifest. Vaulted profiles are never
        # announced by workers and the backend endpoint also protects them.
        threading.Thread(
            target=self._discover_legacy_profiles,
            args=(set(managed),),
            daemon=True,
            name="worker-legacy-profile-discovery",
        ).start()

        synced = 0
        failures = 0
        if profile and profile not in current_profiles:
            with self._condition:
                self._state["managed_profiles"] = sorted(
                    set(self._state.get("managed_profiles", [])) | {profile}
                )
                self._state.setdefault("profiles", {}).setdefault(profile, {}).update(
                    {
                        "status": "not_assigned",
                        "error_code": "PROFILE_NOT_ASSIGNED",
                        "updated_at": _now(),
                    }
                )
                self._save_locked()
                self._condition.notify_all()
            return {"status": "not_assigned", "synced": 0, "failed": 1}
        for entry in entries:
            if profile and entry["profile"] != profile:
                continue
            try:
                if self._sync_entry(entry, mode=mode):
                    synced += 1
                else:
                    failures += 1
            except Exception as exc:
                code = getattr(exc, "code", "PROFILE_SYNC_FAILED")
                self._set_profile(entry["profile"], status="sync_pending", error_code=str(code))
                failures += 1
                LOGGER.warning(
                    "Profile revision sync failed for %s (%s)",
                    entry["profile"],
                    type(exc).__name__,
                )

        with self._condition:
            self._state["last_checked_at"] = _now()
            self._save_locked()
            self._condition.notify_all()
        if failures:
            return {"status": "sync_pending", "synced": synced, "failed": failures}
        return {"status": "ready", "synced": synced, "failed": 0}

    def _sync_entry(self, entry: dict[str, Any], *, mode: str) -> bool:
        profile = entry["profile"]
        revision = entry["revision"]
        digest = entry["bundle_sha256"]
        if entry["format_version"] != _SUPPORTED_FORMAT:
            raise ProfileSyncError("PROFILE_BUNDLE_FORMAT_UNSUPPORTED")
        with self._condition:
            previous = dict(self._state.get("profiles", {}).get(profile) or {})
        same_revision = (
            int(previous.get("installed_revision") or 0) == revision
            and str(previous.get("installed_sha256") or "").lower() == digest
        )
        if mode != "repair" and same_revision:
            installed_identity = self.session_manager.verify_installed(
                profile, _positive_int(previous.get("telegram_user_id")) or None
            )
            if installed_identity is not False:
                self._set_profile(
                    profile,
                    status="sync_pending",
                    installed_revision=revision,
                    installed_sha256=digest,
                    telegram_user_id=int(installed_identity),
                    error_code="",
                )
                return self._ack(profile, revision, digest, int(installed_identity))

        bundle, headers = self._get_bundle(profile, revision)
        actual_digest = hashlib.sha256(bundle).hexdigest()
        if not hmac_compare(actual_digest, digest):
            raise ProfileSyncError("PROFILE_BUNDLE_HASH_MISMATCH")
        etag = _header(headers, "ETag").strip('"').lower()
        if not etag or not hmac_compare(etag, digest):
            raise ProfileSyncError("PROFILE_BUNDLE_HASH_MISMATCH")
        if _header(headers, "X-Profile-Revision") != str(revision):
            raise ProfileSyncError("PROFILE_BUNDLE_REVISION_MISMATCH")
        format_version = _header(headers, "X-Profile-Format-Version")
        if format_version != str(_SUPPORTED_FORMAT):
            raise ProfileSyncError("PROFILE_BUNDLE_FORMAT_UNSUPPORTED")
        if entry["format_version"] != _SUPPORTED_FORMAT:
            raise ProfileSyncError("PROFILE_BUNDLE_FORMAT_UNSUPPORTED")
        try:
            user_id = profile_bundle_identity(bundle)
        except ValueError as exc:
            raise ProfileSyncError("PROFILE_BUNDLE_INVALID") from exc
        if user_id <= 0:
            raise ProfileSyncError("PROFILE_BUNDLE_INVALID")

        profile_key = hashlib.sha256(profile.encode("utf-8")).hexdigest()[:16]
        operation_id = f"sync-{profile_key}-{revision}"
        try:
            self.install_bundle(profile, user_id, bundle, operation_id)
            installed_identity = self.session_manager.verify_installed(profile, user_id)
            if installed_identity is False or int(installed_identity) != user_id:
                raise ProfileSyncError("PROFILE_INSTALL_VALIDATION_FAILED")
            if not self.commit_bundle(profile, operation_id):
                raise ProfileSyncError("PROFILE_INSTALL_COMMIT_FAILED")
        except Exception:
            self.rollback_bundle(profile, operation_id)
            raise
        self._set_profile(
            profile,
            status="sync_pending",
            installed_revision=revision,
            installed_sha256=digest,
            telegram_user_id=user_id,
            error_code="",
        )
        return self._ack(profile, revision, digest, user_id)

    def _ack(self, profile: str, revision: int, digest: str, user_id: int) -> bool:
        response, _ = self._request(
            "POST",
            f"/internal/v1/profiles/{quote(profile, safe='')}/ack",
            json.dumps(
                {
                    "revision": revision,
                    "bundle_sha256": digest,
                    "telegram_user_id": user_id,
                },
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        try:
            payload = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProfileSyncError("PROFILE_ACK_INVALID") from exc
        if payload.get("accepted") is not True:
            self._set_profile(profile, status="sync_pending", error_code="PROFILE_ACK_PENDING")
            return False
        self._set_profile(
            profile,
            status="ready",
            installed_revision=revision,
            installed_sha256=digest,
            error_code="",
        )
        return True

    def _get_manifest(self) -> dict[str, Any]:
        raw, _ = self._request("GET", "/internal/v1/profile-manifest", None)
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise ProfileSyncError("PROFILE_MANIFEST_TOO_LARGE")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProfileSyncError("PROFILE_MANIFEST_INVALID") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
            raise ProfileSyncError("PROFILE_MANIFEST_INVALID")
        return payload

    def _discover_legacy_profiles(self, managed_profiles: set[str]) -> None:
        discover = getattr(self.profile_manager, "local_profile_identities", None)
        if not callable(discover):
            return
        candidates = []
        if not self._legacy_discovery_lock.acquire(blocking=False):
            return
        try:
            for item in discover():
                if not isinstance(item, dict):
                    continue
                name = normalize_profile_name(str(item.get("name") or ""))
                if name and name not in managed_profiles:
                    candidates.append({
                        "name": name,
                        "telegram_user_id": item.get("telegram_user_id"),
                    })
            if candidates:
                self._request(
                    "POST",
                    "/internal/v1/profiles/sync",
                    json.dumps({"profiles": candidates}, separators=(",", ":")).encode("utf-8"),
                    timeout=8,
                )
        except Exception as exc:
            # Legacy discovery is best effort and cannot make vault-owned
            # profile synchronization appear healthy or fail closed.
            LOGGER.info("Legacy profile discovery unavailable (%s)", type(exc).__name__)
        finally:
            self._legacy_discovery_lock.release()

    def _get_bundle(self, profile: str, revision: int) -> tuple[bytes, Any]:
        return self._request(
            "GET",
            f"/internal/v1/profiles/{quote(profile, safe='')}/bundles/{revision}",
            None,
            max_bytes=MAX_PROFILE_BUNDLE_BYTES,
        )

    def _request(
        self,
        method: str,
        path: str,
        data: bytes | None,
        *,
        max_bytes: int = _MAX_MANIFEST_BYTES,
        timeout: float = 90,
    ) -> tuple[bytes, Any]:
        if self._request_override is not None:
            return self._request_override(method, path, data)
        base_url = str(getattr(self.config, "backend_api_url", "") or "").rstrip("/")
        internal_token = str(getattr(self.config, "backend_internal_token", "") or "")
        worker_name = str(getattr(self.config, "backup_node_name", "") or "").strip()
        worker_token = str(getattr(self.config, "worker_api_token", "") or "")
        if not base_url or not internal_token or not worker_name or not worker_token:
            raise ProfileSyncError("WORKER_IDENTITY_NOT_CONFIGURED")
        if not _secure_backend_url(base_url):
            raise ProfileSyncError("PROFILE_TRANSFER_REQUIRES_HTTPS")
        headers = {
            "Authorization": f"Bearer {internal_token}",
            "X-Worker-Name": worker_name,
            "X-Worker-Token": worker_token,
            "Accept": "application/zip, application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(base_url + path, data=data, headers=headers, method=method)
        try:
            opener = build_opener(ProxyHandler({}), _RejectRedirects())
            with opener.open(request, timeout=timeout) as response:
                content_length = _header(response.headers, "Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise ProfileSyncError("PROFILE_RESPONSE_TOO_LARGE")
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise ProfileSyncError("PROFILE_RESPONSE_TOO_LARGE")
                return body, response.headers
        except urllib.error.HTTPError as exc:
            # Do not retain backend response bodies: they may include internal
            # paths or diagnostic detail, and a redirect must never move tokens.
            code = "PROFILE_BACKEND_REJECTED" if exc.code < 500 else "BACKEND_UNAVAILABLE"
            raise ProfileSyncError(code) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise ProfileSyncError("BACKEND_UNAVAILABLE") from None

    def _validate_manifest(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        seen = set()
        for row in payload["profiles"]:
            if not isinstance(row, dict):
                raise ProfileSyncError("PROFILE_MANIFEST_INVALID")
            name = normalize_profile_name(str(row.get("profile") or ""))
            revision = row.get("revision")
            format_version = row.get("format_version")
            digest = str(row.get("bundle_sha256") or "").lower()
            if (
                not name
                or name != str(row.get("profile") or "").lower()
                or name in seen
                or type(revision) is not int
                or revision < 1
                or type(format_version) is not int
                or not _SHA256_RE.fullmatch(digest)
            ):
                raise ProfileSyncError("PROFILE_MANIFEST_INVALID")
            seen.add(name)
            result.append(
                {
                    "profile": name,
                    "revision": revision,
                    "format_version": format_version,
                    "bundle_sha256": digest,
                    "admission_status": str(row.get("admission_status") or "pending"),
                    "sync_requested": bool(row.get("sync_requested")),
                }
            )
        return result

    def _set_backend_unavailable(self, code: str) -> None:
        safe_code = _safe_code(code)
        with self._condition:
            self._state["backend_available"] = False
            self._state["last_checked_at"] = _now()
            for name in self._state.get("managed_profiles", []):
                self._state.setdefault("profiles", {}).setdefault(name, {}).update(
                    {"status": "waiting_worker", "error_code": safe_code, "updated_at": _now()}
                )
            self._save_locked()
            self._condition.notify_all()

    def _set_profile(self, profile: str, **values: Any) -> None:
        with self._condition:
            row = self._state.setdefault("profiles", {}).setdefault(profile, {})
            row.update(values)
            row["updated_at"] = _now()
            self._save_locked()
            self._condition.notify_all()

    def _load_state(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        rows = raw.get("profiles") if isinstance(raw.get("profiles"), dict) else {}
        safe_rows: dict[str, dict[str, Any]] = {}
        for name, value in rows.items():
            normalized = normalize_profile_name(str(name))
            if not normalized or not isinstance(value, dict):
                continue
            safe_rows[normalized] = {
                "desired_revision": _positive_int(value.get("desired_revision")),
                "installed_revision": _positive_int(value.get("installed_revision")),
                "bundle_sha256": _safe_digest(value.get("bundle_sha256")),
                "installed_sha256": _safe_digest(value.get("installed_sha256")),
                "telegram_user_id": _positive_int(value.get("telegram_user_id")),
                "status": _safe_status(value.get("status")),
                "error_code": _safe_code(value.get("error_code")),
                "updated_at": str(value.get("updated_at") or "")[:64],
            }
        managed = raw.get("managed_profiles")
        managed = managed if isinstance(managed, list) else []
        return {
            "backend_available": raw.get("backend_available") if isinstance(raw.get("backend_available"), bool) else None,
            "last_checked_at": str(raw.get("last_checked_at") or "")[:64],
            "managed_profiles": sorted({name for item in managed if (name := normalize_profile_name(str(item)))}),
            "profiles": safe_rows,
        }

    def _save_locked(self) -> None:
        write_json_atomic_private(self.path, self._state)

    def _mark_startup_checked(self) -> None:
        with self._condition:
            self._startup_checked = True
            self._condition.notify_all()

    @staticmethod
    def _worker_status(state: dict[str, Any]) -> str:
        if state.get("backend_available") is not True:
            return "waiting_worker"
        managed = state.get("managed_profiles", [])
        profiles = state.get("profiles", {})
        if any((profiles.get(name) or {}).get("status") != "ready" for name in managed):
            return "sync_pending"
        return "ready"


def _header(headers: Any, name: str) -> str:
    try:
        return str(headers.get(name, "") or "")
    except Exception:
        return ""


def _secure_backend_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value))
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return False
        return parsed.scheme == "https" or (
            parsed.scheme == "http"
            and parsed.hostname.lower()
            in {"backend", "worker-local", "local", "localhost", "127.0.0.1", "::1"}
        )
    except ValueError:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_code(value: Any) -> str:
    return re.sub(r"[^A-Z0-9_-]", "", str(value or "").upper())[:64]


def _safe_status(value: Any) -> str:
    candidate = str(value or "")
    return candidate if candidate in {"ready", "sync_pending", "waiting_worker", "failed", "not_assigned"} else "sync_pending"


def _safe_digest(value: Any) -> str:
    candidate = str(value or "").lower()
    return candidate if _SHA256_RE.fullmatch(candidate) else ""


def _positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def hmac_compare(left: str, right: str) -> bool:
    # compare_digest avoids content-dependent hash comparisons without adding
    # another secret-bearing dependency to the worker runtime.
    import hmac

    return hmac.compare_digest(str(left), str(right))


__all__ = ["ProfileSyncClient", "ProfileSyncError"]
