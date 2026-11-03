from __future__ import annotations

from collections.abc import Iterable


def resource_lock(resource: str) -> tuple[str, str]:
    """Decode shared/exclusive tokens; unprefixed resources remain exclusive."""
    if resource.startswith("shared:"):
        return "shared", resource[len("shared:"):]
    if resource.startswith("exclusive:"):
        return "exclusive", resource[len("exclusive:"):]
    return "exclusive", resource


def workspace_resource_scope(resource: str) -> tuple[str, str] | None:
    _mode, key = resource_lock(resource)
    namespace, separator, path = key.partition(":workspace:")
    if not separator or not namespace.startswith("worker:") or not path.startswith("/"):
        return None
    return namespace, path.rstrip("/") or "/"


def resource_locks_conflict(left: str, right: str) -> bool:
    """Check exact resources and overlapping worker Workspace paths."""
    left_mode, left_key = resource_lock(left)
    right_mode, right_key = resource_lock(right)
    if left_key == right_key:
        return left_mode != "shared" or right_mode != "shared"

    left_scope = workspace_resource_scope(left)
    right_scope = workspace_resource_scope(right)
    if left_scope is None or right_scope is None or left_scope[0] != right_scope[0]:
        return False
    left_path, right_path = left_scope[1], right_scope[1]
    paths_overlap = (
        left_path == right_path
        or left_path.startswith(right_path.rstrip("/") + "/")
        or right_path.startswith(left_path.rstrip("/") + "/")
    )
    return paths_overlap and (left_mode == "exclusive" or right_mode == "exclusive")


def first_resource_conflict(
    left: Iterable[str], right: Iterable[str]
) -> tuple[str, str] | None:
    """Return the first conflicting key pair, in stable order."""
    for left_key in sorted({str(key) for key in left if str(key)}):
        for right_key in sorted({str(key) for key in right if str(key)}):
            if resource_locks_conflict(left_key, right_key):
                return left_key, right_key
    return None


def resource_sets_conflict(left: Iterable[str], right: Iterable[str]) -> bool:
    return first_resource_conflict(left, right) is not None
