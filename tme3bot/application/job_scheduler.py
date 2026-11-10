from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from tme3bot.chat_refs import normalize_peer_identity


@dataclass(frozen=True)
class JobExecutionPlan:
    """Internal scheduling metadata shared by backend and worker."""

    resource_keys: frozenset[str]
    queue_group: str
    lane: str
    priority: int = 100

    def as_dict(self) -> dict[str, Any]:
        return {
            "resource_keys": sorted(self.resource_keys),
            "queue_group": self.queue_group,
            "lane": self.lane,
            "priority": self.priority,
        }


def _workspace_resource_keys(worker: str, raw_paths: Iterable[object]) -> set[str]:
    """Lock each selected Workspace path together with its ancestors."""
    keys: set[str] = set()
    for raw_path in raw_paths:
        normalized = str(raw_path or "").replace("\\", "/").rstrip("/")
        parts = [part for part in normalized.split("/") if part]
        start = 2 if parts and parts[0].casefold() == "workspace" else 1
        if len(parts) < start:
            parts = ["workspace"]
            start = 1
        for index in range(start, len(parts) + 1):
            ancestor = "/" + "/".join(parts[:index])
            keys.add(f"worker:{worker}:workspace:{ancestor}")
    return keys


def _workspace_transfer_resource_key(
    worker: str,
    raw_path: object,
    *,
    transfer_mode: str,
) -> set[str]:
    """Use a shared folder-tree lock for Copy and exclusive lock for Move."""
    keys = _workspace_resource_keys(worker, [raw_path])
    if not keys:
        return set()
    leaf = max(keys, key=lambda key: (key.count("/"), len(key)))
    lock_mode = "exclusive" if transfer_mode == "move" else "shared"
    return {f"{lock_mode}:{leaf}"}


def build_execution_plan(
    kind: str,
    profile: str,
    worker: str,
    payload: dict[str, Any],
    profiles: Iterable[str] = (),
    stage_job_id: str | None = None,
) -> JobExecutionPlan:
    kind = str(kind)
    profile = str(profile)
    worker = str(worker)
    # Profile and worker together identify an execution origin.  Jobs from
    # different origins must not serialize one another.
    keys: set[str] = {f"profile:{profile}:worker:{worker}:kind:{kind}"}
    lane = "filesystem"

    if kind in {"export", "leave"}:
        lane = "tdl-export"
        if kind == "export":
            resolved_peer = payload.get("_verified_export_peer")
            if isinstance(resolved_peer, dict):
                peer_type, peer_id = normalize_peer_identity(
                    resolved_peer.get("peer_type", ""),
                    resolved_peer.get("peer_id", ""),
                )
                # Peer identity is supplied only by the backend alias registry.
                # This global key is independent of labels and worker routing.
                keys.add(
                    f"profile:{profile}:peer:{peer_type}:{peer_id}:export-cursor"
                )
        if kind == "export" and bool(payload.get("quick_mode")):
            # Quick Mode is a single job, but its phases use different
            # sessions.  Only the export phase is admitted on the export
            # lane.  Once json_ready is emitted, the backend and worker
            # release these two keys so the next Quick Mode can export while
            # this job downloads/compresses/uploads.  The actual TDL clients
            # and runtime locks still serialize operations on each session.
            retry = payload.get("quick_retry") or {}
            retry = retry if isinstance(retry, dict) else {}
            retry_phase = str(
                retry.get("resume_phase")
                or payload.get("quick_phase")
                or retry.get("retry_phase")
                or "exporting"
            ).strip().lower()
            if retry_phase not in {"exporting", "auto"}:
                keys = {
                    key
                    for key in keys
                    if ":kind:export" not in key and ":tdl:export" not in key
                }
            else:
                keys.add(f"profile:{profile}:worker:{worker}:kind:export")
                keys.add(f"profile:{profile}:worker:{worker}:tdl:export")
            stage_job_id = retry.get("stage_job_id") or payload.get("stage_job_id") or stage_job_id
            # Initial jobs do not yet have retry metadata.  The job ID is the
            # stable physical staging identity for the whole retry chain.
            stage_job_id = stage_job_id or payload.get("job_id")
            if stage_job_id:
                keys.add(f"worker:{worker}:quick-stage:{str(stage_job_id)}")
                if retry_phase in {"exporting", "auto"}:
                    # The additions above are kept explicit for readability;
                    # this branch also documents that a retry from the
                    # exporting phase owns the export lane.
                    keys.update(
                        {
                            f"profile:{profile}:worker:{worker}:kind:export",
                            f"profile:{profile}:worker:{worker}:tdl:export",
                        }
                    )
            lane = "tdl-quick-export"
        else:
            keys.add(f"profile:{profile}:worker:{worker}:tdl:export")
    elif kind == "storage_upload":
        keys = set()
        workspace_path = payload.get("folder_path") or payload.get("folder")
        if workspace_path:
            transfer_mode = str(payload.get("transfer_mode") or "copy").strip().lower()
            keys.update(
                _workspace_transfer_resource_key(
                    worker,
                    workspace_path,
                    transfer_mode=transfer_mode,
                )
            )
        if str(payload.get("provider") or "telegram").strip().lower() == "rclone":
            keys.add(f"worker:{worker}:rclone:storage")
            lane = "rclone-storage"
        else:
            keys.add(f"worker:{worker}:tdl:storage")
            sender_profiles = payload.get("_tdl_sender_profiles") or [profile]
            for sender_profile in sender_profiles:
                keys.add(f"profile:{str(sender_profile).lower()}:worker:{worker}:tdl:upload")
            lane = "tdl-storage"
    elif kind == "chat_send":
        keys = set()
        transfer_mode = str(payload.get("transfer_mode") or "copy").strip().lower()
        folders = payload.get("folders") or []
        for folder in folders if isinstance(folders, list) else []:
            keys.update(_workspace_transfer_resource_key(
                worker, folder, transfer_mode=transfer_mode
            ))
        sender_profiles = payload.get("_tdl_sender_profiles") or [profile]
        for sender_profile in sender_profiles:
            keys.add(f"profile:{str(sender_profile).lower()}:worker:{worker}:tdl:upload")
        lane = "tdl-chat-send"
    elif kind == "storage_reconcile":
        keys = {f"worker:{worker}:kind:storage_reconcile"}
        workspace_path = payload.get("folder_path") or payload.get("folder")
        reconcile_provider = str(
            payload.get("_storage_reconcile_provider") or "telegram"
        ).strip().lower()
        if reconcile_provider == "rclone":
            keys.add(f"worker:{worker}:rclone:storage")
            if workspace_path:
                keys.update(
                    _workspace_transfer_resource_key(
                        worker,
                        workspace_path,
                        transfer_mode=str(payload.get("transfer_mode") or "copy"),
                    )
                )
            lane = "rclone-storage-reconcile"
        else:
            keys.add(f"worker:{worker}:tdl:storage")
            if workspace_path:
                keys.update(_workspace_resource_keys(worker, [workspace_path]))
            sender_profiles = payload.get("_tdl_sender_profiles") or [profile]
            for sender_profile in sender_profiles:
                keys.add(f"profile:{str(sender_profile).lower()}:worker:{worker}:tdl:upload")
            lane = "tdl-storage-reconcile"
    elif kind == "storage_sync":
        keys = {
            f"worker:{worker}:kind:storage_sync",
            f"worker:{worker}:tdl:storage",
            f"profile:{profile}:worker:{worker}:tdl:upload",
        }
        lane = "tdl-storage-sync"
    elif kind == "storage_download":
        keys = {f"worker:{worker}:kind:storage_download"}
        keys.update(_workspace_resource_keys(worker, [payload.get("destination_path")]))
        if str(payload.get("provider") or "") == "rclone":
            keys.add(f"worker:{worker}:rclone:storage")
            lane = "rclone-storage-download"
        else:
            keys.add(f"profile:{profile}:worker:{worker}:tdl:download")
            lane = "tdl-storage-download"
    elif kind == "storage_rclone_manage":
        keys = {
            f"worker:{worker}:kind:storage_rclone_manage",
            f"worker:{worker}:rclone:storage",
        }
        lane = "rclone-storage-manage"
    elif kind == "tts":
        # Keep one end-to-end TTS job per worker, including Telegram delivery.
        # Different workers remain independent and can each use three routes.
        keys = {f"worker:{worker}:kind:tts"}
        sender_profiles = payload.get("_tdl_sender_profiles") or [profile]
        for sender_profile in sender_profiles:
            keys.add(f"profile:{str(sender_profile).lower()}:worker:{worker}:tdl:export")
        lane = "tts"
    elif kind == "tdl_access_verify":
        keys = {f"worker:{worker}:kind:tdl_access_verify"}
        candidate_profiles = payload.get("candidate_profiles") or profiles
        lane = "upload" if str(payload.get("purpose") or "") == "storage" else "export"
        for candidate_profile in candidate_profiles:
            keys.add(f"profile:{str(candidate_profile).lower()}:worker:{worker}:tdl:{lane}")
        lane = "tdl-access-verification"
    elif kind == "safelink_resolve":
        # The HTTP resolver addon exposes one active resolution slot per worker.
        keys = {f"worker:{worker}:kind:safelink_resolve"}
        lane = "safelink-resolver"
    elif kind in {"download", "download_clear_failed"}:
        keys.add(f"profile:{profile}:worker:{worker}:tdl:download")
        artifact_lock = f"worker:{worker}:artifact-files"
        if kind == "download_clear_failed":
            # This command scans/removes every failed JSON, including files
            # absent from the catalog, so fence the complete local tree.
            keys.add(f"exclusive:{artifact_lock}")
        else:
            keys.add(f"shared:{artifact_lock}")
        artifact_keys = payload.get("artifact_keys") or payload.get("artifact_key") or []
        if not isinstance(artifact_keys, (list, tuple, set)):
            artifact_keys = [artifact_keys]
        keys.update(f"worker:{worker}:artifact:{item}" for item in artifact_keys)
        lane = "tdl-download"
    elif kind == "backup_node":
        # Backup currently snapshots all profiles and uploads through the
        # export client. Keep the plan conservative until dedicated lanes are
        # configured on every worker.
        lane = "tdl-backup-fallback-export"
        for name in profiles:
            keys.add(f"profile:{name}:tdl:export")
            keys.add(f"profile:{name}:tdl:download")
    elif kind == "backup_verify":
        keys = {
            f"worker:{worker}:kind:backup_verify",
            f"profile:{profile}:worker:{worker}:tdl:export",
        }
        lane = "tdl-backup-channel-verify"
    elif kind == "utility":
        lane = "filesystem"
        folders = payload.get("folders") or []
        if folders:
            # Include ancestors so /workspace/a and /workspace/a/sub cannot
            # mutate the same tree concurrently, while sibling folders stay
            # independent.
            keys = set()
            for folder in folders:
                normalized = str(folder).replace("\\", "/").rstrip("/")
                parts = [part for part in normalized.split("/") if part]
                start = 2 if parts and parts[0].casefold() == "workspace" else 1
                if len(parts) < start:
                    parts = ["workspace"]
                    start = 1
                for index in range(start, len(parts) + 1):
                    ancestor = "/" + "/".join(parts[:index])
                    keys.add(
                        f"worker:{worker}:workspace:{ancestor}"
                    )
        else:
            keys.add(f"worker:{worker}:workspace")
    elif kind.startswith("artifact_"):
        lane = "artifact"
        artifact_lock = f"worker:{worker}:artifact-files"
        if kind == "artifact_inventory":
            # Inventory may delete media-less JSON and mark unseen rows
            # unavailable, so it must fence every per-file operation.
            keys.add(f"exclusive:{artifact_lock}")
        else:
            keys.add(f"shared:{artifact_lock}")
        artifact_ids = (
            payload.get("artifact_keys")
            or payload.get("artifact_key")
            or payload.get("artifact_ids")
            or payload.get("artifact_id")
            or []
        )
        if not isinstance(artifact_ids, (list, tuple, set)):
            artifact_ids = [artifact_ids]
        keys.update(f"worker:{worker}:artifact:{item}" for item in artifact_ids)

    return JobExecutionPlan(
        resource_keys=frozenset(key for key in keys if key),
        queue_group=(
            f"worker:{worker}:kind:{kind}"
            if kind in {"tts", "safelink_resolve", "chat_send"}
            or (kind == "storage_upload" and str(payload.get("provider") or "telegram").strip().lower() == "rclone")
            or (kind == "storage_download" and str(payload.get("provider") or "").strip().lower() == "rclone")
            else f"profile:{profile}:worker:{worker}:kind:{kind}"
        ),
        lane=lane,
        priority=(
            0
            if kind != "storage_upload" and payload.get("priority") == "next"
            else 100
        ),
    )
