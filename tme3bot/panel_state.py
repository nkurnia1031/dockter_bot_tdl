from __future__ import annotations

import threading


class PanelViewStore:
    """Tracks which asynchronous task currently owns a chat's panel view."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._versions: dict[int, int] = {}

    def begin(self, chat_id: int) -> int:
        with self._lock:
            token = self._versions.get(chat_id, 0) + 1
            self._versions[chat_id] = token
            return token

    def invalidate(self, chat_id: int) -> None:
        self.begin(chat_id)

    def is_active(self, chat_id: int, token: int | None) -> bool:
        if token is None:
            return True
        with self._lock:
            return self._versions.get(chat_id) == token
