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
) -> JobExecutionPlan:
    kind = str(kind)
    profile = str(profile)
    worker = str(worker)
    keys: set[str] = {f"profile:{profile}:kind:{kind}"}
    lane = "filesystem"

    if kind in {"export", "leave", "storage_upload"}:
        keys.add(f"profile:{profile}:tdl:export")
        lane = "tdl-export"
    elif kind in {"download", "download_clear_failed"}:
        keys.add(f"profile:{profile}:tdl:download")
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
                        f"profile:{profile}:worker:{worker}:workspace:{ancestor}"
                    )
        else:
            keys.add(f"profile:{profile}:worker:{worker}:workspace")
    elif kind.startswith("artifact_"):
        lane = "artifact"
        artifact_ids = payload.get("artifact_ids") or payload.get("artifact_id") or []
        if not isinstance(artifact_ids, (list, tuple, set)):
            artifact_ids = [artifact_ids]
        keys.update(f"worker:{worker}:artifact:{item}" for item in artifact_ids)

    return JobExecutionPlan(
        resource_keys=frozenset(key for key in keys if key),
        queue_group=f"profile:{profile}:kind:{kind}",
        lane=lane,
        priority=0 if payload.get("priority") == "next" else 100,
    )
