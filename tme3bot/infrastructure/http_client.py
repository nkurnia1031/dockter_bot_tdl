from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from tme3bot.domain.worker_contract import (
    CAP_JOB_CONTROL,
    CAP_JOB_LOG_SNAPSHOT,
    CAP_QUICKMODE_SCAN,
    CAP_QUICKMODE_STAGING,
    CAP_QUICKMODE_DELETE,
    CAP_QUICKMODE_VERIFY,
    CAP_TTS,
    CAP_WORKSPACE_TREE,
    WORKER_JOB_CAPABILITIES,
    require_worker_contract,
)


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
        required = set(WORKER_JOB_CAPABILITIES)
        job_payload = payload.get("payload")
        if isinstance(job_payload, dict) and bool(job_payload.get("quick_mode")):
            required.add(CAP_QUICKMODE_STAGING)
        if str(payload.get("kind") or "") == "tts":
            required.add(CAP_TTS)
        self._require_capabilities(worker, required, record=record)
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
        self._require_capabilities(worker, {CAP_JOB_CONTROL}, record=record)
        result = request_json(
            str(record["url"]),
            str(record["token"]),
            "POST",
            f"/internal/v1/jobs/{job_id}/cancel",
        )
        return bool(result.get("cancelled"))

    def pause(self, worker: str, job_id: str) -> bool:
        record = self.worker_registry.get(worker)
        if not record:
            return False
        self._require_capabilities(worker, {CAP_JOB_CONTROL}, record=record)
        result = request_json(
            str(record["url"]),
            str(record["token"]),
            "POST",
            f"/internal/v1/jobs/{job_id}/pause",
        )
        return bool(result.get("paused"))

    def resume(self, worker: str, job_id: str, event_sequence_start: int) -> bool:
        record = self.worker_registry.get(worker)
        if not record:
            return False
        self._require_capabilities(worker, {CAP_JOB_CONTROL}, record=record)
        result = request_json(
            str(record["url"]),
            str(record["token"]),
            "POST",
            f"/internal/v1/jobs/{job_id}/resume",
            {"event_sequence_start": int(event_sequence_start)},
        )
        return bool(result.get("resumed"))

    def workspace_tree(self, worker: str, path: str = "/workspace") -> dict[str, Any]:
        record = self.worker_registry.get(worker)
        if not record:
            raise RuntimeError(f"Worker tidak ditemukan: {worker}.")
        self._require_capabilities(worker, {CAP_WORKSPACE_TREE}, record=record)
        return request_json(
            str(record["url"]),
            str(record["token"]),
            "GET",
            "/internal/v1/workspace/tree?path=" + quote(path, safe=""),
        )

    def quickmode_scan(self, worker: str) -> dict[str, Any]:
        record = self.worker_registry.get(worker)
        if not record:
            raise RuntimeError(f"Worker tidak ditemukan: {worker}.")
        self._require_capabilities(worker, {CAP_QUICKMODE_SCAN}, record=record)
        return request_json(
            str(record["url"]),
            str(record["token"]),
            "GET",
            "/internal/v1/quickmode/scan",
            timeout=30,
        )

    def quickmode_verify(self, worker: str, stage_job_id: str, expected_phase: str = "uploading") -> dict[str, Any]:
        record = self.worker_registry.get(worker)
        if not record:
            raise RuntimeError(f"Worker tidak ditemukan: {worker}.")
        self._require_capabilities(worker, {CAP_QUICKMODE_VERIFY}, record=record)
        return request_json(
            str(record["url"]),
            str(record["token"]),
            "POST",
            "/internal/v1/quickmode/verify",
            {"stage_job_id": stage_job_id, "expected_phase": expected_phase},
            timeout=120,
        )

    def quickmode_delete(self, worker: str, stage_job_id: str) -> dict[str, Any]:
        record = self.worker_registry.get(worker)
        if not record:
            raise RuntimeError(f"Worker tidak ditemukan: {worker}.")
        self._require_capabilities(worker, {CAP_QUICKMODE_DELETE}, record=record)
        return request_json(
            str(record["url"]),
            str(record["token"]),
            "DELETE",
            "/internal/v1/quickmode/staging/" + quote(str(stage_job_id), safe=""),
            timeout=180,
        )

    def capabilities(self, worker: str) -> dict[str, Any]:
        record = self.worker_registry.get(worker)
        if not record:
            raise RuntimeError(f"Worker tidak ditemukan: {worker}.")
        return request_json(
            str(record["url"]),
            str(record["token"]),
            "GET",
            "/internal/v1/capabilities",
            timeout=15,
        )

    def open_tts_artifact(self, worker: str, job_id: str, artifact_ref: str):
        record = self.worker_registry.get(worker)
        if not record:
            raise RuntimeError(f"Worker tidak ditemukan: {worker}.")
        self._require_capabilities(worker, {CAP_TTS}, record=record)
        request = Request(
            str(record["url"]).rstrip("/")
            + f"/internal/v1/tts/artifacts/{quote(job_id, safe='')}/{quote(artifact_ref, safe='')}",
            headers={"Authorization": f"Bearer {record['token']}", "Accept": "audio/mpeg"},
            method="GET",
        )
        try:
            return urlopen(request, timeout=90)
        except urllib.error.HTTPError as exc:
            raise JsonHttpError(exc.code, "Worker tidak dapat menyediakan audio TTS.") from exc
        except urllib.error.URLError as exc:
            raise JsonHttpError(503, "Worker audio TTS tidak dapat dihubungi.") from exc

    def check_worker(self, worker: str) -> dict[str, Any]:
        record = self.worker_registry.get(worker)
        if not record:
            raise RuntimeError(f"Worker tidak ditemukan: {worker}.")
        capabilities = require_worker_contract(
            self.capabilities(worker),
            worker,
            required_capabilities=WORKER_JOB_CAPABILITIES,
        )
        return {"healthy": True, **capabilities}

    def _require_capabilities(
        self,
        worker: str,
        required: set[str],
        *,
        record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if record is None:
            record = self.worker_registry.get(worker)
        if not record:
            raise RuntimeError(f"Worker tidak ditemukan: {worker}.")
        response = request_json(
            str(record["url"]),
            str(record["token"]),
            "GET",
            "/internal/v1/capabilities",
            timeout=15,
        )
        return require_worker_contract(
            response, worker, required_capabilities=required
        )

    def job_log(self, worker: str, job_id: str) -> dict[str, Any]:
        record = self.worker_registry.get(worker)
        if not record:
            raise RuntimeError(f"Worker tidak ditemukan: {worker}.")
        self._require_capabilities(worker, {CAP_JOB_LOG_SNAPSHOT}, record=record)
        return request_json(
            str(record["url"]),
            str(record["token"]),
            "GET",
            f"/internal/v1/jobs/{quote(job_id, safe='')}/log-snapshot",
        )
