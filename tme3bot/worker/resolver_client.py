"""Worker-side client for the private resolver addon service."""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx

from tme3bot.worker.safelink_resolver import SafelinkCancelled, SafelinkResolveError


RESOLVER_ADDON_URL = "http://resolver-addon:8091"


def resolver_addon_ready() -> bool:
    try:
        response = httpx.get(
            f"{RESOLVER_ADDON_URL}/healthz",
            timeout=3,
            trust_env=False,
        )
        return response.status_code == 200 and response.json().get("ready") is True
    except Exception:
        return False


def resolve_with_addon(
    url: str,
    *,
    on_progress: Callable[[dict[str, Any]], None],
    is_cancelled: Callable[[], bool],
) -> dict[str, str]:
    timeout = httpx.Timeout(connect=5, read=10, write=10, pool=5)
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            with client.stream(
                "POST",
                f"{RESOLVER_ADDON_URL}/resolve",
                json={"url": url},
            ) as response:
                if response.status_code == 409:
                    raise SafelinkResolveError("Resolver sedang memproses job lain.")
                if response.status_code == 503:
                    raise SafelinkResolveError("Layanan resolver belum siap.")
                if response.status_code >= 400:
                    raise SafelinkResolveError("Resolver tidak dapat menerima job.")

                result: dict[str, str] | None = None
                error: str | None = None
                for line in response.iter_lines():
                    if is_cancelled():
                        raise SafelinkCancelled("Job resolver dibatalkan.")
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    event_type = item.get("type")
                    if event_type == "heartbeat":
                        continue
                    if event_type == "progress":
                        on_progress(item)
                    elif event_type == "result":
                        destination = item.get("destination_url")
                        if isinstance(destination, str) and destination:
                            result = {"destination_url": destination}
                    elif event_type == "error":
                        error = str(item.get("message") or "Resolver mengalami kendala.")
                if is_cancelled():
                    raise SafelinkCancelled("Job resolver dibatalkan.")
                if error:
                    raise SafelinkResolveError(error)
                if result:
                    return result
                raise SafelinkResolveError("Koneksi ke resolver terputus sebelum job selesai.")
    except (SafelinkCancelled, SafelinkResolveError):
        raise
    except Exception:
        raise SafelinkResolveError("Resolver addon tidak dapat dihubungi.") from None
