"""Private HTTP addon that runs Playwright shortlink resolution for a worker."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
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


def _browser_ready() -> bool:
    browser = None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
        return True
    except Exception:
        return False
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.browser_ready = await asyncio.to_thread(_browser_ready)
    yield


app = FastAPI(title="Tme3Bot resolver addon", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    if not bool(getattr(app.state, "browser_ready", False)):
        raise HTTPException(status_code=503, detail="browser_unavailable")
    return {"ready": True}


def _line(item: dict[str, Any]) -> bytes:
    return (json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


@app.post("/resolve")
async def resolve(request: ResolveRequest):
    if not bool(getattr(app.state, "browser_ready", False)):
        raise HTTPException(status_code=503, detail="browser_unavailable")
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
            _RESOLVE_LOCK.release()

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8091, access_log=False)


if __name__ == "__main__":
    main()
