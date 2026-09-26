from __future__ import annotations

from pathlib import (
    Path,
)
from typing import (
    Any,
)

class WorkspaceExecutorMixin:

    def _workspace_path(self, raw: str, *, require_absolute: bool = False) -> Path:
        root = Path(self.config.utility_workspace_root).resolve()
        path = Path(raw)
        if require_absolute and not path.is_absolute():
            raise ValueError("Path utility harus absolut dan berasal dari pilihan workspace.")
        if not path.is_absolute():
            path = root / path
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("Path harus berada di dalam workspace.") from exc
        return resolved

    def workspace_tree(self, raw: str = "/workspace") -> dict[str, Any]:
        """Return a safe, shallow directory listing for the active workspace."""
        root = Path(self.config.utility_workspace_root).resolve()
        current = self._workspace_path(raw or str(root))
        if not current.is_dir():
            raise ValueError("Folder workspace tidak ditemukan.")
        relative = current.relative_to(root)
        display_path = "/workspace" if not relative.parts else "/workspace/" + "/".join(relative.parts)
        items: list[dict[str, Any]] = []
        for entry in sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if entry.is_symlink():
                continue
            item_path = display_path.rstrip("/") + "/" + entry.name
            if entry.is_dir():
                try:
                    children = list(entry.iterdir())
                    files = sum(1 for child in children if child.is_file())
                    directories = sum(1 for child in children if child.is_dir())
                except OSError:
                    files, directories = 0, 0
                items.append({
                    "name": entry.name,
                    "path": item_path,
                    "kind": "directory",
                    "files": files,
                    "directories": directories,
                    "has_children": bool(files or directories),
                })
            elif entry.is_file():
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = None
                items.append({"name": entry.name, "path": item_path, "kind": "file", "size": size})
        return {"path": display_path, "items": items}
