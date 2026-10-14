"""Stable fingerprints for TDL access evidence inventories."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


_PROFILE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")


def normalize_session_fingerprints(value: Any) -> dict[str, str]:
    """Return only safe profile-to-fingerprint pairs from worker metadata."""
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for raw_profile, raw_fingerprint in value.items():
        profile = str(raw_profile or "").strip().lower()
        fingerprint = str(raw_fingerprint or "").strip().lower()
        if _PROFILE.fullmatch(profile) and _FINGERPRINT.fullmatch(fingerprint):
            result[profile] = fingerprint
    return result


def normalize_profiles(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return sorted({
        profile
        for item in value
        if _PROFILE.fullmatch(profile := str(item or "").strip().lower())
    })


def tdl_access_inventory_fingerprint(
    profiles: Any,
    session_fingerprints: Any = None,
) -> str:
    """Hash profile names, and optionally each profile's TDL session generation."""
    normalized = normalize_profiles(profiles)
    if session_fingerprints is None:
        payload: Any = normalized
    else:
        fingerprints = normalize_session_fingerprints(session_fingerprints)
        payload = [[profile, fingerprints[profile]] for profile in normalized if profile in fingerprints]
    canonical = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
