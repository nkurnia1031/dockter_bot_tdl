"""Private HTTP addon that resolves supported shortlinks over HTTP."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from tme3bot.worker.safelink_resolver import (
    SafelinkCancelled,
    SafelinkResolveError,
    resolve_shortlink,
)


_RESOLVE_LOCK = threading.Lock()


class ResolveRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)


app = FastAPI(title="Tme3Bot HTTP resolver addon")


@app.get("/healthz")
def healthz():
    return {"ready": True, "engine": "http"}


def _line(item: dict[str, Any]) -> bytes:
    return (json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


@app.post("/resolve")
async def resolve(request: ResolveRequest):
    if not _RESOLVE_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="resolver_busy")

    events: queue.Queue[dict[str, Any]] = queue.Queue()
    cancelled = threading.Event()

    def run_resolver() -> None:
        try:
            result = resolve_shortlink(
                request.url,
                on_progress=lambda item: events.put({"type": "progress", **item}),
                is_cancelled=cancelled.is_set,
            )
            events.put({"type": "result", "destination_url": result["destination_url"]})
        except SafelinkCancelled:
            events.put({"type": "error", "message": "Job resolver dibatalkan."})
        except SafelinkResolveError as exc:
            events.put({"type": "error", "message": str(exc)})
        except Exception:
            events.put({"type": "error", "message": "Resolver mengalami kendala saat memproses halaman."})
        finally:
            _RESOLVE_LOCK.release()
            events.put({"type": "done"})

    thread = threading.Thread(target=run_resolver, name="resolver-job", daemon=True)
    thread.start()

    async def stream():
        try:
            while True:
                try:
                    item = await asyncio.to_thread(events.get, True, 1.0)
                except queue.Empty:
                    yield _line({"type": "heartbeat"})
                    continue
                yield _line(item)
                if item.get("type") == "done":
                    break
        finally:
            cancelled.set()

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8091, access_log=False)


if __name__ == "__main__":
    main()
