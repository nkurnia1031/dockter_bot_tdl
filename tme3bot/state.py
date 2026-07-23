from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from tme3bot.persistence import utc_now_iso, write_json_atomic


@dataclass
class SourceState:
    last_id: int
    label: str | None
    updated_at: str
    warmup_url: str | None = None
    warmup_done: bool = False
    warmup_done_at: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceState":
        last_id = int(payload["last_id"])
        label = payload.get("label")
        updated_at = str(payload.get("updated_at") or utc_now_iso())
        return cls(
            last_id=last_id,
            label=label,
            updated_at=updated_at,
            warmup_url=payload.get("warmup_url"),
            warmup_done=bool(payload.get("warmup_done", True)),
            warmup_done_at=payload.get("warmup_done_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_id": self.last_id,
            "label": self.label,
            "updated_at": self.updated_at,
            "warmup_url": self.warmup_url,
            "warmup_done": self.warmup_done,
            "warmup_done_at": self.warmup_done_at,
        }


@dataclass
class StateSnapshot:
    sources: dict[str, SourceState]
    migration: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": {
                key: value.to_dict() for key, value in sorted(self.sources.items())
            },
            "migration": self.migration,
        }


class StateStore:
    def __init__(self, state_file: Path, legacy_max_json: Path) -> None:
        self.state_file = state_file
        self.legacy_max_json = legacy_max_json
        self._lock = threading.RLock()
        self._state: StateSnapshot | None = None

    def load(self) -> StateSnapshot:
        with self._lock:
            if self._state is not None:
                return self._state

            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            if self.state_file.exists():
                self._state = self._load_state_file()
            elif self.legacy_max_json.exists():
                self._state = self._migrate_legacy_state()
                self._save_locked()
            else:
                self._state = StateSnapshot(sources={}, migration={"skipped_keys": []})
            return self._state

    def get_source(self, chat_ref: str) -> SourceState | None:
        with self._lock:
            source = self.load().sources.get(chat_ref)
            return replace(source) if source is not None else None

    def list_sources(self) -> list[tuple[str, SourceState]]:
        with self._lock:
            return [
                (chat_ref, replace(source))
                for chat_ref, source in sorted(self.load().sources.items())
            ]

    def upsert_source(
        self,
        chat_ref: str,
        label: str | None,
        last_id: int,
        warmup_url: str | None = None,
        warmup_done: bool | None = None,
    ) -> SourceState:
        with self._lock:
            state = self.load()
            current = state.sources.get(chat_ref)
            next_label = (
                label if label is not None else (current.label if current else None)
            )
            next_warmup_url = (
                current.warmup_url if current and current.warmup_url else warmup_url
            )
            next_warmup_done = current.warmup_done if current else True
            next_warmup_done_at = current.warmup_done_at if current else None

            if warmup_done is not None:
                next_warmup_done = warmup_done
                next_warmup_done_at = utc_now_iso() if warmup_done else None

            updated = SourceState(
                last_id=last_id,
                label=next_label,
                updated_at=utc_now_iso(),
                warmup_url=next_warmup_url,
                warmup_done=next_warmup_done,
                warmup_done_at=next_warmup_done_at,
            )
            state.sources[chat_ref] = updated
            self._save_locked()
            return updated

    def mark_warmup_done(self, chat_ref: str) -> None:
        with self._lock:
            state = self.load()
            current = state.sources.get(chat_ref)
            if current is None:
                return
            current.warmup_done = True
            current.warmup_done_at = utc_now_iso()
            current.updated_at = utc_now_iso()
            self._save_locked()

    def delete_source(self, chat_ref: str) -> bool:
        return bool(self.delete_sources([chat_ref]))

    def delete_sources(self, chat_refs: Iterable[str]) -> list[str]:
        with self._lock:
            state = self.load()
            deleted = sorted(set(chat_refs).intersection(state.sources))
            if not deleted:
                return []
            for chat_ref in deleted:
                del state.sources[chat_ref]
            self._save_locked()
            return deleted

    def _load_state_file(self) -> StateSnapshot:
        payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        sources_payload = payload.get("sources", {})
        migration_payload = payload.get("migration", {"skipped_keys": []})
        sources = {
            key: SourceState.from_dict(value)
            for key, value in sources_payload.items()
            if isinstance(value, dict) and "last_id" in value
        }
        return StateSnapshot(sources=sources, migration=migration_payload)

    def _migrate_legacy_state(self) -> StateSnapshot:
        payload = json.loads(self.legacy_max_json.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Legacy max.json harus berupa object JSON.")

        sources: dict[str, SourceState] = {}
        skipped_keys: list[dict[str, str]] = []
        migrated_at = utc_now_iso()

        for raw_key, raw_value in payload.items():
            key = str(raw_key).strip()
            value = str(raw_value).strip()

            if not key:
                skipped_keys.append(
                    {
                        "key": key,
                        "value": value,
                        "reason": "empty_key",
                    }
                )
                continue

            if value.isdigit():
                sources[key] = SourceState(
                    last_id=int(value),
                    label=None,
                    updated_at=migrated_at,
                    warmup_done=True,
                    warmup_done_at=migrated_at,
                )
                continue

            skipped_keys.append(
                {
                    "key": key,
                    "value": value,
                    "reason": "non_numeric_last_id",
                }
            )

        migration = {
            "source_file": str(self.legacy_max_json),
            "migrated_at": migrated_at,
            "migrated_count": len(sources),
            "skipped_keys": skipped_keys,
        }
        return StateSnapshot(sources=sources, migration=migration)

    def _save_locked(self) -> None:
        if self._state is None:
            return

        write_json_atomic(self.state_file, self._state.to_dict())
