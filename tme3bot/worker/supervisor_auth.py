from __future__ import annotations

import hashlib
import hmac


def derive_supervisor_token(worker: str, worker_api_token: str) -> str:
    """Derive a supervisor-only credential without storing the worker API token."""
    name = str(worker or "").strip().lower()
    secret = str(worker_api_token or "").encode("utf-8")
    if not name or not secret:
        return ""
    message = f"tme3bot:worker-supervisor:v1:{name}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()
