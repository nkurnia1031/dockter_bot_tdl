from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path

from tme3bot.persistence import utc_now_iso, write_json_atomic
from tme3bot.url_parser import slugify_label


def label_digest(label: str) -> str:
    return hashlib.sha1(label.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class SavedLabel:
    label: str
    updated_at: str


class LabelStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._labels: dict[str, SavedLabel] | None = None

    def add(self, raw_label: str | None) -> str | None:
        if raw_label is None:
            return None
        value = str(raw_label).strip()
        if not value:
            return None
        label = slugify_label(value)
        with self._lock:
            self._load_locked()
            assert self._labels is not None
            self._labels[label] = SavedLabel(label=label, updated_at=utc_now_iso())
            self._save_locked()
        return label

    def list_labels(self, limit: int | None = None) -> list[SavedLabel]:
        with self._lock:
            self._load_locked()
            assert self._labels is not None
            labels = sorted(
                self._labels.values(), key=lambda item: item.updated_at, reverse=True
            )
        return labels[:limit] if limit is not None else labels

    def find_by_digest(self, digest: str) -> str | None:
        wanted = digest.strip().lower()
        for item in self.list_labels():
            if label_digest(item.label) == wanted:
                return item.label
        return None

    def _load_locked(self) -> None:
        if self._labels is not None:
            return
        if not self.path.exists():
            self._labels = {}
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._labels = {}
            return

        raw_labels = payload.get("labels", {}) if isinstance(payload, dict) else {}
        labels: dict[str, SavedLabel] = {}
        if isinstance(raw_labels, dict):
            for raw_label, raw_value in raw_labels.items():
                label = slugify_label(str(raw_label))
                if not label:
                    continue
                updated_at = utc_now_iso()
                if isinstance(raw_value, dict):
                    updated_at = str(raw_value.get("updated_at") or updated_at)
                labels[label] = SavedLabel(label=label, updated_at=updated_at)
        elif isinstance(raw_labels, list):
            for raw_label in raw_labels:
                label = slugify_label(str(raw_label))
                if label:
                    labels[label] = SavedLabel(label=label, updated_at=utc_now_iso())
        self._labels = labels

    def _save_locked(self) -> None:
        if self._labels is None:
            return
        payload = {
            "labels": {
                label: {"updated_at": item.updated_at}
                for label, item in sorted(self._labels.items())
            }
        }
        write_json_atomic(self.path, payload)
