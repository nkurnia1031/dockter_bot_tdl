"""Framework-independent worker execution adapter.

Keep package imports lightweight. Resolver and helper sidecars import modules
from this package without needing the full job executor, while existing callers
can still import :class:`WorkerJobExecutor` from ``tme3bot.worker``.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tme3bot.worker.executor import WorkerJobExecutor as WorkerJobExecutor

__all__ = ["WorkerJobExecutor"]


def __getattr__(name: str):
    if name == "WorkerJobExecutor":
        from tme3bot.worker.executor import WorkerJobExecutor

        return WorkerJobExecutor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
