from __future__ import annotations

import re


PROFILE_NAME_RE = re.compile(r"[^a-z0-9_-]+")


def normalize_profile_name(name: str | None) -> str:
    normalized = PROFILE_NAME_RE.sub("-", str(name or "").strip().lower()).strip("-_")
    return normalized[:48]
