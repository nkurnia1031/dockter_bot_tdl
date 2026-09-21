from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


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
        keys = {f"worker:{worker}:kind:storage_upload", f"worker:{worker}:tdl:storage"}
        lane = "tdl-storage"
    elif kind in {"download", "download_clear_failed"}:
        keys.add(f"profile:{profile}:worker:{worker}:tdl:download")
        lane = "tdl-download"
    elif kind == "backup_node":
        # Backup currently snapshots all profiles and uploads through the
        # export client. Keep the plan conservative until dedicated lanes are
        # configured on every worker.
        lane = "tdl-backup-fallback-export"
        for name in profiles:
            keys.add(f"profile:{name}:tdl:export")
            keys.add(f"profile:{name}:tdl:download")
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
        artifact_ids = payload.get("artifact_ids") or payload.get("artifact_id") or []
        if not isinstance(artifact_ids, (list, tuple, set)):
            artifact_ids = [artifact_ids]
        keys.update(f"worker:{worker}:artifact:{item}" for item in artifact_ids)

    return JobExecutionPlan(
        resource_keys=frozenset(key for key in keys if key),
        queue_group=f"profile:{profile}:worker:{worker}:kind:{kind}",
        lane=lane,
        priority=0 if payload.get("priority") == "next" else 100,
    )
