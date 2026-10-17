"""Explicit, durable Vault-to-worker distribution over the private backup channel."""

from __future__ import annotations

import hashlib
import io
import logging
import math
import threading

from tme3bot.profile_distribution_crypto import encrypt_distribution_bundle

LOGGER = logging.getLogger(__name__)
_TELEGRAM_PART_BYTES = 40 * 1024 * 1024


class ProfileDistributionService:
    def __init__(self, config, bot, store, vault_store, worker_registry, dispatcher) -> None:
        self.config = config
        self.bot = bot
        self.store = store
        self.vault_store = vault_store
        self.worker_registry = worker_registry
        self.dispatcher = dispatcher
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None:
            return
        recover = getattr(self.store, "recover_interrupted", None)
        if callable(recover):
            recover()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="profile-distribution"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(3)
            self._wake.clear()
            if self._stop.is_set():
                return
            self.process_pending()

    def process_pending(self) -> int:
        if not self._lock.acquire(blocking=False):
            return 0
        processed = 0
        try:
            for target in self.store.pending_targets():
                if self._stop.is_set():
                    break
                self._process_target(target)
                processed += 1
        finally:
            self._lock.release()
        return processed

    def _process_target(self, target: dict) -> None:
        operation_id = str(target["operation_id"])
        profile = str(target["profile"])
        revision = int(target["revision"])
        worker = str(target["worker"])
        archive_sha256 = ""
        try:
            record = self.worker_registry.get(worker)
            token = str(record.get("token") or "") if record else ""
            revision_record = self.vault_store.bundle_for_revision(profile, revision)
            if record is None or len(token) < 16 or revision_record is None:
                raise ValueError("PROFILE_DISTRIBUTION_SOURCE_UNAVAILABLE")
            if str(revision_record["bundle_sha256"]) != str(target["bundle_sha256"]):
                raise ValueError("PROFILE_DISTRIBUTION_REVISION_MISMATCH")
            encrypted = encrypt_distribution_bundle(
                revision_record["bundle"],
                worker_token=token,
                operation_id=operation_id,
                profile=profile,
                revision=revision,
                worker=worker,
            )
            archive_sha256 = hashlib.sha256(encrypted).hexdigest()
            part_total = max(1, math.ceil(len(encrypted) / _TELEGRAM_PART_BYTES))
            existing_parts = self.store.artifact_parts(operation_id, worker)
            if existing_parts and any(
                int(part["part_total"]) != part_total
                or str(part["archive_sha256"]) != archive_sha256
                for part in existing_parts
            ):
                raise ValueError("PROFILE_DISTRIBUTION_ARTIFACT_CONFLICT")
            uploaded_indexes = {int(part["part_index"]) for part in existing_parts}
            for part_index in range(1, part_total + 1):
                if part_index in uploaded_indexes:
                    continue
                start = (part_index - 1) * _TELEGRAM_PART_BYTES
                end = min(len(encrypted), start + _TELEGRAM_PART_BYTES)
                chunk = encrypted[start:end]
                filename = (
                    f"profile-{operation_id.replace('-', '')}-{worker}-r{revision}"
                    f"-p{part_index:03d}-of-{part_total:03d}.enc"
                )
                caption = (
                    "#profile_distribution\n"
                    f"Operation: {operation_id}\nProfile: {profile}\nRevision: {revision}\n"
                    f"Worker: {worker}\nBundle-SHA256: {target['bundle_sha256']}\n"
                    f"Archive-SHA256: {archive_sha256}\nPart-Index: {part_index}\n"
                    f"Part-Total: {part_total}\nPart: {filename}"
                )
                self.store.update_target(operation_id, worker, "running", "archive_upload")
                result = self.bot.send_document(
                    chat_id=int(getattr(self.config, "backup_channel_id", 0)),
                    document=io.BytesIO(chunk),
                    filename=filename,
                    caption=caption,
                )
                message_id = int(getattr(result, "message_id", 0))
                if message_id < 1:
                    raise RuntimeError("PROFILE_DISTRIBUTION_CHANNEL_UPLOAD_FAILED")
                self.store.record_artifact_part(
                    operation_id,
                    worker,
                    part_index=part_index,
                    part_total=part_total,
                    message_id=message_id,
                    archive_sha256=archive_sha256,
                )
        except Exception as exc:
            code = _safe_error_code(exc, "BACKUP_CHANNEL_UNAVAILABLE")
            self.store.update_target(operation_id, worker, "waiting", "archive_upload", code)
            LOGGER.info("Profile distribution artifact deferred for %s (%s).", worker, code)
            return

        record = self.worker_registry.get(worker)
        if record is None:
            self.store.update_target(operation_id, worker, "waiting", "waiting_worker", "WORKER_UNAVAILABLE")
            return
        payload = {
            "profile": profile,
            "revision": revision,
            "telegram_user_id": int(target["telegram_user_id"]),
            "message_ids": [int(part["message_id"]) for part in self.store.artifact_parts(operation_id, worker)],
            "archive_sha256": archive_sha256,
            "bundle_sha256": str(target["bundle_sha256"]),
            "channel_ref": str(getattr(self.config, "backup_channel_ref", "") or ""),
            "event_sequence_start": 0,
        }
        try:
            self.store.update_target(operation_id, worker, "running", "worker_dispatch")
            result = self.dispatcher.distribute_profile_bundle(worker, operation_id, payload)
            if not isinstance(result, dict) or result.get("ready") is not True:
                raise RuntimeError("PROFILE_DISTRIBUTION_NOT_CONFIRMED")
            self.store.update_target(operation_id, worker, "ready", "completed")
        except Exception as exc:
            if _is_transient_worker_error(exc):
                code = "WORKER_UNAVAILABLE"
                self.store.update_target(operation_id, worker, "waiting", "waiting_worker", code)
            else:
                code = _safe_error_code(exc, "PROFILE_DISTRIBUTION_FAILED")
                self.store.update_target(operation_id, worker, "failed", "failed", code)
            LOGGER.info("Profile distribution deferred for %s (%s).", worker, code)


def _safe_error_code(error: Exception, fallback: str) -> str:
    raw = str(getattr(error, "code", "") or "")
    payload = getattr(error, "payload", None)
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        raw = str(payload["error"].get("code") or raw)
    if not raw:
        raw = str(error) if str(error).startswith("PROFILE_") else fallback
    code = "".join(char for char in raw.upper() if char.isalnum() or char in "_-")[:64]
    return code or fallback


def _is_transient_worker_error(error: Exception) -> bool:
    kind = str(getattr(error, "kind", ""))
    status = int(getattr(error, "status", 0) or 0)
    return kind in {"network", "timeout"} or status in {502, 503, 504}
