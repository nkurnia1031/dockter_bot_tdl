from __future__ import annotations

import threading
from collections.abc import Hashable, Iterable


class SourceSelectionStore:
    """Thread-safe temporary selections scoped to a Telegram chat and profile."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[Hashable, set[str]] = {}

    def get(self, owner: Hashable) -> set[str]:
        with self._lock:
            return set(self._items.get(owner, set()))

    def toggle(self, owner: Hashable, chat_ref: str) -> set[str]:
        with self._lock:
            selected = self._items.setdefault(owner, set())
            if chat_ref in selected:
                selected.remove(chat_ref)
            else:
                selected.add(chat_ref)
            return self._cleanup(owner)

    def select_all(self, owner: Hashable, chat_refs: Iterable[str]) -> set[str]:
        with self._lock:
            self._items[owner] = set(chat_refs)
            return self._cleanup(owner)

    def discard(self, owner: Hashable, chat_refs: Iterable[str]) -> set[str]:
        with self._lock:
            selected = self._items.get(owner, set())
            selected.difference_update(chat_refs)
            return self._cleanup(owner)

    def retain(self, owner: Hashable, valid_chat_refs: Iterable[str]) -> set[str]:
        with self._lock:
            selected = self._items.get(owner, set())
            selected.intersection_update(valid_chat_refs)
            return self._cleanup(owner)

    def clear(self, owner: Hashable) -> None:
        with self._lock:
            self._items.pop(owner, None)

    def _cleanup(self, owner: Hashable) -> set[str]:
        selected = self._items.get(owner, set())
        if not selected:
            self._items.pop(owner, None)
            return set()
        return set(selected)
