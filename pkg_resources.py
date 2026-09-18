"""Small importlib-backed compatibility shim for legacy APScheduler.

python-telegram-bot 13.x pins APScheduler 3.6.x, whose two imports of
``pkg_resources`` are only used for package version lookup and entry-point
discovery.  Modern setuptools no longer ships that deprecated module, so keep
the compatibility surface local and dependency-free.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, distribution, entry_points


class DistributionNotFound(PackageNotFoundError):
    """Compatibility name used by APScheduler 3.x."""


def get_distribution(name: str):
    try:
        return distribution(name)
    except PackageNotFoundError as exc:
        raise DistributionNotFound(name) from exc


def iter_entry_points(group: str, name: str | None = None):
    """Return importlib entry points with the old pkg_resources API shape."""
    discovered = entry_points()
    if hasattr(discovered, "select"):
        selected = discovered.select(group=group)
    else:  # pragma: no cover - Python 3.10 compatibility fallback
        selected = discovered.get(group, ())
    if name is not None:
        selected = [item for item in selected if item.name == name]
    return iter(selected)
