from __future__ import annotations

from pathlib import PurePosixPath


def safe_chat_send_retry_paths(job) -> list[str]:
    """Extract only confirmed failed relative paths from an owned terminal job."""
    result = job.result if isinstance(job.result, dict) else {}
    value = result.get("value", result)
    items = value.get("items") if isinstance(value, dict) else None
    items = items if isinstance(items, list) else []
    payload = job.payload if isinstance(job.payload, dict) else {}
    folders = payload.get("folders") if isinstance(payload.get("folders"), list) else []
    roots: list[str] = []
    for raw in folders:
        path = PurePosixPath(str(raw or ""))
        if path.is_absolute() and len(path.parts) >= 2 and path.parts[1] == "workspace" and ".." not in path.parts:
            relative = path.relative_to("/workspace").as_posix()
            roots.append("" if relative == "." else relative)

    retry_paths: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or item.get("status") != "failed" or item.get("retryable") is not True:
            continue
        raw_path = str(item.get("path") or "")
        path = PurePosixPath(raw_path)
        if (
            not raw_path or path.is_absolute() or ".." in path.parts
            or any(part in {"", "."} for part in path.parts)
            or path.as_posix() != raw_path or any(ord(char) < 32 for char in raw_path)
        ):
            continue
        if any(
            not root or raw_path == root or raw_path.startswith(root.rstrip("/") + "/")
            for root in roots
        ):
            retry_paths.add(raw_path)
    return sorted(retry_paths)
