"""Small parsers shared by runtime configuration and deploy tooling."""

from __future__ import annotations


_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "enabled"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})


def parse_bool_setting(
    value: object | None, *, name: str, default: bool
) -> bool:
    """Parse one boolean setting consistently in app and deploy processes."""
    if value is None:
        return bool(default)
    normalized = str(value).strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} harus bernilai true atau false.")
