from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Callable


class UtilityFlattenPreviewStaleError(ValueError):
    code = "UTILITY_FLATTEN_PREVIEW_STALE"

    def __init__(self, folders: list[str]) -> None:
        self.folders = folders
        super().__init__(
            "Preview Flatten sudah berubah untuk: "
            + ", ".join(folders)
            + ". Buat preview baru sebelum menerapkan perubahan."
        )


def _walk(root: Path) -> list[tuple[str, int, int, int, int, int, int, str]]:
    records: list[tuple[str, int, int, int, int, int, int, str]] = []

    def visit(directory: Path, relative: str) -> None:
        with os.scandir(directory) as scanned:
            entries = sorted(scanned, key=lambda entry: (entry.name.casefold(), entry.name))
        for entry in entries:
            path = Path(entry.path)
            child_relative = f"{relative}/{entry.name}" if relative else entry.name
            metadata = entry.stat(follow_symlinks=False)
            is_link = stat.S_ISLNK(metadata.st_mode)
            link_target = os.readlink(path) if is_link else ""
            records.append(
                (
                    child_relative,
                    stat.S_IFMT(metadata.st_mode),
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                    metadata.st_ctime_ns,
                    link_target,
                )
            )
            if stat.S_ISDIR(metadata.st_mode) and not is_link:
                visit(path, child_relative)

    visit(root, "")
    return records


def tree_fingerprint(root: Path) -> str:
    """Hash the complete selected tree without following symbolic links."""
    root = Path(root)
    metadata = root.stat(follow_symlinks=False)
    is_link = stat.S_ISLNK(metadata.st_mode)
    records = [
        (
            ".",
            stat.S_IFMT(metadata.st_mode),
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            os.readlink(root) if is_link else "",
        ),
        *_walk(root),
    ]
    canonical = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _inventory(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for relative, mode, *_ in _walk(root):
        if stat.S_ISLNK(mode):
            kind = "symlink"
        elif stat.S_ISDIR(mode):
            kind = "directory"
        elif stat.S_ISREG(mode):
            kind = "file"
        else:
            kind = "other"
        entries[relative] = kind
    return entries


def _children(entries: dict[str, str], parent: str) -> list[str]:
    return sorted(
        path
        for path in entries
        if (PurePosixPath(path).parent.as_posix() or ".") == (parent or ".")
    )


def _subtree(entries: dict[str, str], source: str) -> dict[str, str]:
    prefix = source + "/"
    return {
        path: kind
        for path, kind in entries.items()
        if path == source or path.startswith(prefix)
    }


def _destination_name(entries: dict[str, str], folder_name: str, item_name: str) -> tuple[str, bool]:
    if item_name == folder_name:
        return item_name, False
    if item_name not in entries:
        return item_name, False
    base = f"dup_{folder_name}_{item_name}"
    candidate = base
    suffix = 2
    while candidate in entries:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate, True


def _move_virtual(entries: dict[str, str], folder: str, item: str, destination: str) -> None:
    moving = _subtree(entries, item)
    prefix = folder + "/"
    for path in list(entries):
        if path == folder or path.startswith(prefix):
            del entries[path]
    for path, kind in moving.items():
        relative_suffix = path[len(item):]
        entries[destination + relative_suffix] = kind


def plan_flatten(root: Path) -> dict[str, Any]:
    """Simulate Flatten passes to stability and capture the original tree hash."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"Folder Flatten tidak ditemukan: {root}")
    fingerprint = tree_fingerprint(root)
    entries = _inventory(root)
    passes: list[dict[str, Any]] = []

    while True:
        folder_candidates = [
            path
            for path in _children(entries, "")
            if entries.get(path) == "directory"
        ]
        actions: list[dict[str, Any]] = []
        changed = False
        for folder in folder_candidates:
            if entries.get(folder) != "directory":
                continue
            items = _children(entries, folder)
            folder_name = PurePosixPath(folder).name
            if not items:
                actions.append({"type": "delete_empty", "folder": folder})
                del entries[folder]
                changed = True
                continue
            if len(items) > 1:
                actions.append(
                    {"type": "skip_multiple", "folder": folder, "item_count": len(items)}
                )
                continue

            item = items[0]
            item_name = PurePosixPath(item).name
            destination_name, collision = _destination_name(
                entries, folder_name, item_name
            )
            destination = destination_name
            actions.append(
                {
                    "type": "move",
                    "folder": folder,
                    "source": item,
                    "destination": destination,
                    "collision": collision,
                }
            )
            _move_virtual(entries, folder, item, destination)
            changed = True

        if actions:
            passes.append({"index": len(passes) + 1, "actions": actions})
        if not changed:
            break

    actionable = [
        action
        for pass_item in passes
        for action in pass_item["actions"]
        if action["type"] in {"move", "delete_empty"}
    ]
    return {
        "folder": str(root),
        "fingerprint": fingerprint,
        "passes": passes,
        "action_count": len(actionable),
        "moves": sum(action["type"] == "move" for action in actionable),
        "deleted": sum(action["type"] == "delete_empty" for action in actionable),
        "skipped": sum(
            action["type"] == "skip_multiple"
            for pass_item in passes
            for action in pass_item["actions"]
        ),
    }


def apply_flatten_plan(
    root: Path,
    plan: dict[str, Any],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Apply a previously checked plan without overwriting existing paths."""
    root = Path(root).resolve()
    results: list[dict[str, Any]] = []
    for pass_item in plan.get("passes", []):
        for action in pass_item.get("actions", []):
            kind = action.get("type")
            if kind == "skip_multiple":
                results.append({**action, "status": "skipped"})
                if progress_callback is not None:
                    progress_callback({**action, "status": "skipped"})
                continue
            if kind == "delete_empty":
                folder = root / str(action["folder"])
                folder.rmdir()
                results.append({**action, "status": "deleted"})
            elif kind == "move":
                source = root / str(action["source"])
                folder = root / str(action["folder"])
                destination = root / str(action["destination"])
                temporary = root / f".tmp-flatten-{uuid.uuid4().hex}"
                if destination.exists() or destination.is_symlink():
                    raise FileExistsError(f"Tujuan Flatten sudah ada: {destination}")
                source.rename(temporary)
                try:
                    folder.rmdir()
                except Exception:
                    temporary.rename(source)
                    raise
                try:
                    if destination.exists() or destination.is_symlink():
                        raise FileExistsError(f"Tujuan Flatten sudah ada: {destination}")
                    temporary.rename(destination)
                except Exception:
                    if not folder.exists():
                        folder.mkdir()
                    temporary.rename(source)
                    raise
                results.append({**action, "status": "moved"})
            if progress_callback is not None:
                progress_callback({**action, "status": results[-1]["status"]})
    return results


def validate_flatten_roots(roots: list[Path]) -> list[Path]:
    normalized = [Path(root).resolve() for root in roots]
    for index, left in enumerate(normalized):
        for right in normalized[index + 1:]:
            if left == right or left in right.parents or right in left.parents:
                raise ValueError(
                    "Folder Flatten pilihan tidak boleh duplikat atau saling bertumpang tindih."
                )
    return normalized


def apply_flatten_batch(
    roots: list[Path],
    fingerprints: dict[str, str],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Preflight every selected root before making the first filesystem change."""
    normalized = validate_flatten_roots(roots)
    expected = {str(root): str(value) for root, value in fingerprints.items()}
    if set(expected) != {str(root) for root in normalized}:
        raise ValueError("Snapshot Preview Flatten tidak cocok dengan folder pilihan.")
    plans = [plan_flatten(root) for root in normalized]
    stale = [
        str(root)
        for root, plan in zip(normalized, plans)
        if expected[str(root)] != plan["fingerprint"]
    ]
    if stale:
        raise UtilityFlattenPreviewStaleError(stale)

    results: list[dict[str, Any]] = []
    for index, (root, plan) in enumerate(zip(normalized, plans), start=1):
        def report_action(action: dict[str, Any]) -> None:
            if progress_callback is not None:
                progress_callback(
                    {
                        **action,
                        "root": str(root),
                        "folder_index": index,
                        "folder_total": len(normalized),
                    }
                )

        actions = apply_flatten_plan(root, plan, report_action)
        results.append(
            {
                "folder": str(root),
                "fingerprint": plan["fingerprint"],
                "actions": actions,
                "moves": sum(item["status"] == "moved" for item in actions),
                "deleted": sum(item["status"] == "deleted" for item in actions),
                "skipped": sum(item["status"] == "skipped" for item in actions),
            }
        )
    return results
