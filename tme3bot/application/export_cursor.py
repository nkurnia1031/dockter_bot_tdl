"""Application service for verified peer aliases and shared export cursors."""

from __future__ import annotations

import json
from typing import Any

from tme3bot.infrastructure.source_store import (
    SqliteSourceRepository,
)


_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_kind",
        "catalog",
        "artifact_key",
        "filename",
        "chat_ref",
        "label",
        "json_bytes",
        "message_count",
        "media_count",
        "photo_count",
        "video_count",
        "other_media_count",
        "expected_media_bytes",
    }
)


class ExportCursorService:
    """Keep peer resolution, lease fencing, and artifact/cursor commit ordered.

    The SQLite completion record is written before updating the artifact
    catalog. If a process stops between those steps, a retry replays the
    catalog upsert and then atomically advances/releases the cursor lane.
    """

    def __init__(self, repository: SqliteSourceRepository, export_catalog: Any, jobs: Any) -> None:
        self.repository = repository
        self.export_catalog = export_catalog
        self.jobs = jobs

    @property
    def enabled(self) -> bool:
        return self.repository.shared_export_cursor_enabled()

    def set_enabled(self, enabled: bool) -> None:
        self.repository.set_shared_export_cursor_enabled(enabled)

    def resolve_alias(
        self,
        profile: str,
        requested_ref: str,
        peer_type: str,
        peer_id: str | int,
    ) -> dict[str, str]:
        return self.repository.register_peer_alias(
            profile, requested_ref, peer_type, peer_id
        )

    def alias_identity(self, profile: str, requested_ref: str) -> dict[str, str] | None:
        return self.repository.peer_for_alias(profile, requested_ref)

    def acquire(
        self,
        *,
        profile: str,
        requested_ref: str,
        job_id: str,
        worker: str,
        attempt: int,
    ) -> dict[str, object]:
        if not self.enabled:
            raise RuntimeError("Shared export cursor belum diaktifkan untuk worker yang kompatibel.")
        self.recover_pending(tolerate_failures=True)
        return self.repository.acquire_export_lease(
            profile, requested_ref, job_id, worker, attempt
        )

    def heartbeat(
        self,
        *,
        job_id: str,
        worker: str,
        attempt: int,
        fencing_token: int,
    ) -> bool:
        if not self.enabled:
            raise RuntimeError("Shared export cursor belum diaktifkan.")
        return self.repository.heartbeat_export_lease(
            job_id, worker, attempt, fencing_token
        )

    @staticmethod
    def _safe_artifact(artifact: dict[str, Any]) -> dict[str, object]:
        if not isinstance(artifact, dict) or set(artifact) - _ARTIFACT_FIELDS:
            raise ValueError("Metadata artifact export tidak dikenal atau memuat field privat.")
        normalized: dict[str, object] = {}
        for key in sorted(_ARTIFACT_FIELDS):
            if key in artifact:
                value = artifact[key]
                if key in {
                    "json_bytes", "message_count", "media_count", "photo_count",
                    "video_count", "other_media_count", "expected_media_bytes",
                } and value is not None:
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                        raise ValueError("Statistik artifact export tidak valid.")
                    value = int(value)
                elif key in {"artifact_kind", "artifact_key", "filename", "chat_ref", "label"} and value is not None:
                    value = str(value).strip()
                elif key == "catalog":
                    if type(value) is not bool:
                        raise ValueError("Flag katalog artifact tidak valid.")
                normalized[key] = value

        catalog = normalized.get("catalog", True)
        if catalog:
            if not normalized.get("filename") or not normalized.get("artifact_key"):
                raise ValueError("Nama file dan key artifact wajib untuk pencatatan katalog.")
        elif normalized.get("artifact_kind") != "quickmode_stage":
            raise ValueError("Artifact tanpa katalog hanya berlaku untuk staging Quick Mode.")
        elif not normalized.get("filename") or not normalized.get("artifact_key"):
            raise ValueError("Nama dan key artifact staging wajib diisi.")
        return normalized

    def commit(
        self,
        *,
        job_id: str,
        attempt: int,
        worker: str,
        fencing_token: int,
        expected_revision: int,
        last_id: int,
        artifact: dict[str, Any],
    ) -> dict[str, object]:
        if not self.enabled:
            raise RuntimeError("Shared export cursor belum diaktifkan.")
        safe_artifact = self._safe_artifact(artifact)
        completion = self.repository.prepare_export_completion(
            job_id=job_id,
            attempt=attempt,
            worker=worker,
            fencing_token=fencing_token,
            expected_revision=expected_revision,
            last_id=last_id,
            artifact=safe_artifact,
        )
        if str(completion["status"]) == "applied":
            return self._public_completion(completion)
        self._apply_artifact(
            profile=str(completion["profile"]),
            worker=str(completion["worker"]),
            job_id=str(completion["job_id"]),
            peer_type=str(completion["peer_type"]),
            peer_id=str(completion["peer_id"]),
            artifact=safe_artifact,
        )
        completed = self.repository.finalize_export_completion(job_id, attempt)
        return self._public_completion(completed)

    def recover_pending(self, *, tolerate_failures: bool = False) -> int:
        applied = 0
        failures: list[Exception] = []
        for completion in self.repository.pending_export_completions():
            try:
                artifact = json.loads(str(completion["artifact_json"]))
                self._apply_artifact(
                    profile=str(completion["profile"]),
                    worker=str(completion["worker"]),
                    job_id=str(completion["job_id"]),
                    peer_type=str(completion["peer_type"]),
                    peer_id=str(completion["peer_id"]),
                    artifact=artifact,
                )
                self.repository.finalize_export_completion(
                    str(completion["job_id"]), int(completion["attempt"])
                )
                applied += 1
            except Exception as exc:
                failures.append(exc)
        if failures and not tolerate_failures:
            raise failures[0]
        return applied

    def _apply_artifact(
        self,
        *,
        profile: str,
        worker: str,
        job_id: str,
        peer_type: str,
        peer_id: str,
        artifact: dict[str, Any],
    ) -> None:
        if not bool(artifact.get("catalog", True)):
            return
        if self.export_catalog is None:
            raise RuntimeError("Katalog export belum tersedia; commit cursor menunggu pemulihan.")
        record = {
            key: artifact[key]
            for key in _ARTIFACT_FIELDS
            if key in artifact and key not in {"catalog", "artifact_kind"}
        }
        record.update(
            {
                "profile": profile,
                "worker": worker,
                "export_job_id": job_id,
                "chat_ref": str(artifact.get("chat_ref") or f"peer:{peer_type}:{peer_id}"),
                "status": "pending",
            }
        )
        write = getattr(self.export_catalog, "upsert_for_export_cursor", None)
        if callable(write):
            write(**record)
        else:
            self.export_catalog.upsert(**record)

    @staticmethod
    def _public_completion(completion: dict[str, Any]) -> dict[str, object]:
        return {
            "job_id": str(completion["job_id"]),
            "attempt": int(completion["attempt"]),
            "profile": str(completion["profile"]),
            "peer_type": str(completion["peer_type"]),
            "peer_id": str(completion["peer_id"]),
            "cursor_revision": int(completion["expected_revision"]) + 1,
            "last_id": int(completion["cursor_after"] or completion["last_id"]),
            "status": str(completion["status"]),
        }

    def lease_for_job(self, job_id: str) -> dict[str, object] | None:
        return self.repository.export_lease_for_job(job_id)

    def job_has_active_lease(self, job_id: str) -> bool:
        lease = self.lease_for_job(job_id)
        # A reconciliation hold is still a held peer lane.
        return lease is not None

    def completion_applied(self, job_id: str, attempt: int | None = None) -> bool:
        completion = self.repository.export_completion(job_id, attempt)
        return bool(completion and completion.get("status") == "applied")

    def finish_job(
        self,
        job_id: str,
        *,
        attempt: int | None = None,
        worker_confirmed: bool,
        require_applied_completion: bool = False,
    ) -> bool:
        if require_applied_completion and not self.completion_applied(job_id, attempt):
            worker_confirmed = False
        return self.repository.release_export_lease_for_job(
            job_id,
            attempt=attempt,
            worker_confirmed=worker_confirmed,
            require_applied_completion=require_applied_completion,
        )
