from __future__ import annotations

import hashlib
import json
import os
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


Entry = tuple[str, int]


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


def _entry_kind(mode: int) -> str:
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "file"
    return "other"


def _inventory(root: Path) -> dict[str, Entry]:
    return {
        relative: (_entry_kind(mode), size)
        for relative, mode, _dev, _ino, size, _mtime, _ctime, _link in _walk(root)
    }


def _children(entries: dict[str, Entry], parent: str) -> list[str]:
    return sorted(
        path
        for path in entries
        if (PurePosixPath(path).parent.as_posix() or ".") == (parent or ".")
    )


def _subtree(entries: dict[str, Entry], source: str) -> dict[str, Entry]:
    prefix = source + "/"
    return {
        path: entry
        for path, entry in entries.items()
        if path == source or path.startswith(prefix)
    }


def _remove_subtree(entries: dict[str, Entry], path: str) -> None:
    prefix = path + "/"
    for candidate in list(entries):
        if candidate == path or candidate.startswith(prefix):
            del entries[candidate]


def _move_virtual(entries: dict[str, Entry], source: str, destination: str) -> None:
    moving = _subtree(entries, source)
    _remove_subtree(entries, source)
    for path, entry in moving.items():
        entries[destination + path[len(source):]] = entry


def _suffixed_path(entries: dict[str, Entry], path: str, kind: str) -> str:
    candidate_path = PurePosixPath(path)
    name = candidate_path.name
    if kind == "file" and candidate_path.suffix:
        stem, extension = candidate_path.stem, candidate_path.suffix
    else:
        stem, extension = name, ""
    suffix = 2
    while True:
        candidate_name = f"{stem}_{suffix}{extension}"
        candidate = (candidate_path.parent / candidate_name).as_posix()
        if candidate not in entries:
            return candidate
        suffix += 1


def _plan_merge(entries: dict[str, Entry], source: str, destination: str) -> list[dict[str, Any]]:
    """Plan and simulate a directory merge without replacing different-size files."""
    operations: list[dict[str, Any]] = []
    for source_child in _children(entries, source):
        destination_child = (PurePosixPath(destination) / PurePosixPath(source_child).name).as_posix()
        source_kind, source_size = entries[source_child]
        destination_entry = entries.get(destination_child)

        if source_kind == "directory" and not _children(entries, source_child):
            operations.append({"type": "delete_empty", "folder": source_child})
            entries.pop(source_child, None)
            continue

        if destination_entry is None:
            operations.append(
                {"type": "move", "source": source_child, "destination": destination_child}
            )
            _move_virtual(entries, source_child, destination_child)
            continue

        destination_kind, destination_size = destination_entry
        if source_kind == destination_kind == "directory":
            nested = _plan_merge(entries, source_child, destination_child)
            operations.append(
                {
                    "type": "merge",
                    "source": source_child,
                    "destination": destination_child,
                    "items": nested,
                    "merge_summary": _merge_summary(nested),
                }
            )
            entries.pop(source_child, None)
            continue

        if source_kind == destination_kind == "file" and source_size == destination_size:
            operations.append(
                {
                    "type": "replace",
                    "source": source_child,
                    "destination": destination_child,
                    "size": source_size,
                }
            )
            _remove_subtree(entries, source_child)
            entries[destination_child] = (source_kind, source_size)
            continue

        collision = (
            "different_size"
            if source_kind == destination_kind == "file"
            else "different_type"
        )
        renamed = _suffixed_path(entries, destination_child, source_kind)
        operations.append(
            {
                "type": "move",
                "source": source_child,
                "destination": renamed,
                "collision": True,
                "collision_reason": collision,
            }
        )
        _move_virtual(entries, source_child, renamed)

    entries.pop(source, None)
    return operations


def _merge_summary(operations: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"added": 0, "replaced": 0, "suffixed": 0, "merged_folders": 0, "deleted": 0}
    for operation in operations:
        kind = operation.get("type")
        if kind == "move":
            reason = operation.get("collision_reason")
            if reason in {"different_size", "different_type"}:
                summary["suffixed"] += 1
            elif reason is None:
                summary["added"] += 1
        elif kind == "replace":
            summary["replaced"] += 1
        elif kind == "delete_empty":
            summary["deleted"] += 1
        elif kind == "merge":
            summary["merged_folders"] += 1
            nested = operation.get("merge_summary") or _merge_summary(operation.get("items", []))
            for key in ("added", "replaced", "suffixed", "deleted"):
                summary[key] += int(nested.get(key, 0))
            summary["merged_folders"] += int(nested.get("merged_folders", 0))
    return summary


def _count_actions(actions: list[dict[str, Any]], kind: str) -> int:
    total = 0
    for action in actions:
        if action.get("type") == kind:
            total += 1
        if action.get("type") == "merge":
            total += _count_actions(action.get("items", []), kind)
    return total


def _top_level_move(
    entries: dict[str, Entry], folder: str, source: str, destination: str
) -> dict[str, Any]:
    source_kind, source_size = entries[source]
    destination_entry = entries.get(destination)

    if destination == folder and source_kind == "directory":
        items = _plan_merge(entries, source, destination)
        action: dict[str, Any] = {
            "type": "merge",
            "folder": folder,
            "source": source,
            "destination": destination,
            "items": items,
            "merge_summary": _merge_summary(items),
            "keep_folder": True,
        }
        return action

    if destination_entry is None:
        _move_virtual(entries, source, destination)
        entries.pop(folder, None)
        return {
            "type": "move",
            "folder": folder,
            "source": source,
            "destination": destination,
            "collision": False,
        }

    destination_kind, destination_size = destination_entry
    if source_kind == destination_kind == "directory":
        items = _plan_merge(entries, source, destination)
        if destination != folder:
            entries.pop(folder, None)
        return {
            "type": "merge",
            "folder": folder,
            "source": source,
            "destination": destination,
            "items": items,
            "merge_summary": _merge_summary(items),
            "keep_folder": destination == folder,
        }

    if source_kind == destination_kind == "file" and source_size == destination_size:
        _remove_subtree(entries, source)
        entries[destination] = (source_kind, source_size)
        entries.pop(folder, None)
        return {
            "type": "replace",
            "folder": folder,
            "source": source,
            "destination": destination,
            "size": source_size,
        }

    collision_reason = (
        "different_size"
        if source_kind == destination_kind == "file"
        else "different_type"
    )
    renamed = _suffixed_path(entries, destination, source_kind)
    _move_virtual(entries, source, renamed)
    entries.pop(folder, None)
    return {
        "type": "move",
        "folder": folder,
        "source": source,
        "destination": renamed,
        "collision": True,
        "collision_reason": collision_reason,
    }


def plan_flatten(root: Path) -> dict[str, Any]:
    """Simulate Flatten passes to stability and capture the original tree hash."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"Folder Flatten tidak ditemukan: {root}")
    fingerprint = tree_fingerprint(root)
    entries = _inventory(root)
    passes: list[dict[str, Any]] = []

    while True:
        actions: list[dict[str, Any]] = []
        empty_folders = sorted(
            (
                path
                for path, (kind, _size) in entries.items()
                if kind == "directory" and not _children(entries, path)
            ),
            key=lambda path: (-path.count("/"), path.casefold(), path),
        )
        for folder in empty_folders:
            if entries.get(folder, ("", 0))[0] == "directory" and not _children(entries, folder):
                actions.append({"type": "delete_empty", "folder": folder})
                entries.pop(folder, None)

        folder_candidates = [
            path for path in _children(entries, "") if entries.get(path, ("", 0))[0] == "directory"
        ]
        changed = bool(empty_folders)
        for folder in folder_candidates:
            if entries.get(folder, ("", 0))[0] != "directory":
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
            action = _top_level_move(entries, folder, item, item_name)
            actions.append(action)
            changed = True

        if actions:
            passes.append({"index": len(passes) + 1, "actions": actions})
        if not changed:
            break

    actionable_types = {"move", "merge", "replace", "delete_empty"}
    actionable = [
        action
        for pass_item in passes
        for action in pass_item["actions"]
        if action["type"] in actionable_types
    ]
    return {
        "folder": str(root),
        "fingerprint": fingerprint,
        "passes": passes,
        "action_count": sum(
            _count_actions(pass_item["actions"], kind)
            for pass_item in passes
            for kind in actionable_types
        ),
        "moves": sum(action["type"] in {"move", "merge", "replace"} for action in actionable),
        "deleted": sum(
            _count_actions(pass_item["actions"], "delete_empty") for pass_item in passes
        ),
        "replaced": sum(
            1 if action["type"] == "replace" else int(action.get("merge_summary", {}).get("replaced", 0))
            for action in actionable
        ),
        "suffixed": sum(
            1 if action.get("collision_reason") == "different_size"
            else int(action.get("merge_summary", {}).get("suffixed", 0))
            for action in actionable
        ),
        "skipped": sum(
            action["type"] == "skip_multiple"
            for pass_item in passes
            for action in pass_item["actions"]
        ),
    }


def _safe_move(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Tujuan Flatten sudah ada: {destination}")
    source.rename(destination)


def _apply_merge(
    root: Path, source_relative: str, destination_relative: str, operations: list[dict[str, Any]]
) -> None:
    source = root / source_relative
    destination = root / destination_relative
    if not source.is_dir() or source.is_symlink() or not destination.is_dir() or destination.is_symlink():
        raise ValueError("Struktur folder Flatten berubah saat merge diterapkan.")

    for operation in operations:
        kind = operation.get("type")
        item_source = root / str(operation["source"])
        item_destination = root / str(operation["destination"])
        if kind == "move":
            _safe_move(item_source, item_destination)
        elif kind == "replace":
            metadata_source = item_source.stat(follow_symlinks=False)
            metadata_destination = item_destination.stat(follow_symlinks=False)
            expected_size = int(operation["size"])
            if (
                not stat.S_ISREG(metadata_source.st_mode)
                or not stat.S_ISREG(metadata_destination.st_mode)
                or metadata_source.st_size != expected_size
                or metadata_destination.st_size != expected_size
            ):
                raise ValueError("Ukuran file Flatten berubah setelah preview.")
            os.replace(item_source, item_destination)
        elif kind == "delete_empty":
            (root / str(operation["folder"])).rmdir()
        elif kind == "merge":
            _apply_merge(root, str(operation["source"]), str(operation["destination"]), operation["items"])
        else:
            raise ValueError(f"Aksi merge Flatten tidak dikenal: {kind}")

    source.rmdir()


def apply_flatten_plan(
    root: Path,
    plan: dict[str, Any],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Apply a previously checked plan, merging folders and resolving file conflicts by size."""
    root = Path(root).resolve()
    results: list[dict[str, Any]] = []
    for pass_item in plan.get("passes", []):
        for action in pass_item.get("actions", []):
            kind = action.get("type")
            if kind == "skip_multiple":
                status = "skipped"
            elif kind == "delete_empty":
                (root / str(action["folder"])).rmdir()
                status = "deleted"
            elif kind == "move":
                source = root / str(action["source"])
                folder = root / str(action["folder"])
                destination = root / str(action["destination"])
                temporary = root / f".tmp-flatten-{uuid.uuid4().hex}"
                _safe_move(source, temporary)
                try:
                    folder.rmdir()
                except Exception:
                    temporary.rename(source)
                    raise
                try:
                    _safe_move(temporary, destination)
                except Exception:
                    if not folder.exists():
                        folder.mkdir()
                    temporary.rename(source)
                    raise
                status = "moved"
            elif kind == "replace":
                source = root / str(action["source"])
                destination = root / str(action["destination"])
                source_stat = source.stat(follow_symlinks=False)
                destination_stat = destination.stat(follow_symlinks=False)
                expected_size = int(action["size"])
                if (
                    not stat.S_ISREG(source_stat.st_mode)
                    or not stat.S_ISREG(destination_stat.st_mode)
                    or source_stat.st_size != expected_size
                    or destination_stat.st_size != expected_size
                ):
                    raise ValueError("Ukuran file Flatten berubah setelah preview.")
                os.replace(source, destination)
                (root / str(action["folder"])).rmdir()
                status = "replaced"
            elif kind == "merge":
                source = root / str(action["source"])
                _apply_merge(root, str(action["source"]), str(action["destination"]), action["items"])
                if not action.get("keep_folder"):
                    (root / str(action["folder"])).rmdir()
                status = "merged"
            else:
                raise ValueError(f"Aksi Flatten tidak dikenal: {kind}")

            result = {**action, "status": status}
            results.append(result)
            if progress_callback is not None:
                progress_callback(result)
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
                "moves": sum(item["status"] in {"moved", "merged", "replaced"} for item in actions),
                "deleted": sum(
                    1 if item["status"] == "deleted" else int(item.get("merge_summary", {}).get("deleted", 0))
                    for item in actions
                ),
                "skipped": sum(item["status"] == "skipped" for item in actions),
                "replaced": sum(
                    1 if item["type"] == "replace" else int(item.get("merge_summary", {}).get("replaced", 0))
                    for item in actions
                ),
                "suffixed": sum(
                    1 if item.get("collision_reason") == "different_size"
                    else int(item.get("merge_summary", {}).get("suffixed", 0))
                    for item in actions
                ),
            }
        )
    return results
