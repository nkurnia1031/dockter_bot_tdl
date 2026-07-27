from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote


class JsonHttpError(RuntimeError):
    def __init__(self, status: int, message: str, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


def request_json(
    base_url: str,
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 30,
) -> dict[str, Any]:
    data = json.dumps(payload or {}).encode("utf-8") if method != "GET" else None
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {}
        message = (
            body.get("error", {}).get("message")
            if isinstance(body.get("error"), dict)
            else body.get("detail")
        ) or str(exc)
        raise JsonHttpError(exc.code, str(message), body) from exc
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise JsonHttpError(503, f"API tidak dapat dihubungi: {exc}") from exc


class WorkerHttpDispatcher:
    def __init__(self, worker_registry) -> None:
        self.worker_registry = worker_registry

    def dispatch(self, worker: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.worker_registry.get(worker)
        if not record:
            raise RuntimeError(f"Worker tidak ditemukan: {worker}.")
        return request_json(
            str(record["url"]),
            str(record["token"]),
            "POST",
            "/internal/v1/jobs",
            payload,
        )

    def cancel(self, worker: str, job_id: str) -> bool:
        record = self.worker_registry.get(worker)
        if not record:
            return False
        result = request_json(
            str(record["url"]),
            str(record["token"]),
            "POST",
            f"/internal/v1/jobs/{job_id}/cancel",
        )
        return bool(result.get("cancelled"))

    def workspace_tree(self, worker: str, path: str = "/workspace") -> dict[str, Any]:
        record = self.worker_registry.get(worker)
        if not record:
            raise RuntimeError(f"Worker tidak ditemukan: {worker}.")
        return request_json(
            str(record["url"]),
            str(record["token"]),
            "GET",
            "/internal/v1/workspace/tree?path=" + quote(path, safe=""),
        )

    def job_log(self, worker: str, job_id: str) -> dict[str, Any]:
        record = self.worker_registry.get(worker)
        if not record:
            raise RuntimeError(f"Worker tidak ditemukan: {worker}.")
        return request_json(
            str(record["url"]),
            str(record["token"]),
            "GET",
            f"/internal/v1/jobs/{quote(job_id, safe='')}/log-snapshot",
        )
