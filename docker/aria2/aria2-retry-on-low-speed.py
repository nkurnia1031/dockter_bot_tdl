#!/usr/bin/env python3
"""Retry aria2 downloads stopped specifically by the lowest-speed limit."""

from __future__ import annotations

import json
import os
import posixpath
import sys
import time
from datetime import datetime, timezone
from fcntl import LOCK_EX, flock
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener


CONFIG_FILE = Path("/state/aria2.conf")
LOG_FILE = Path("/state/aria2-retry-hook.log")
STATUS_FILE = Path("/state/aria2-hook-status.json")
STATUS_LOCK_FILE = Path("/state/aria2-hook-status.lock")
RPC_URL = os.environ.get("ARIA2_RPC_URL", "http://127.0.0.1:6800/jsonrpc")
RPC_TIMEOUT_SECONDS = 10
RPC_OPENER = build_opener(ProxyHandler({}))

# Only copy per-download options that affect fetching or output. In particular,
# avoid passing daemon/RPC settings returned by getOption to aria2.addUri.
RETRY_OPTION_KEYS = {
    "all-proxy",
    "all-proxy-passwd",
    "all-proxy-user",
    "allow-overwrite",
    "always-resume",
    "async-dns",
    "ca-certificate",
    "check-certificate",
    "conditional-get",
    "connect-timeout",
    "content-disposition-default-utf8",
    "continue",
    "disable-ipv6",
    "enable-http-pipelining",
    "file-allocation",
    "ftp-passwd",
    "ftp-pasv",
    "ftp-reuse-connection",
    "ftp-type",
    "ftp-user",
    "header",
    "http-accept-gzip",
    "http-auth-challenge",
    "http-passwd",
    "http-proxy",
    "http-proxy-passwd",
    "http-proxy-user",
    "http-user",
    "https-proxy",
    "https-proxy-passwd",
    "https-proxy-user",
    "load-cookies",
    "lowest-speed-limit",
    "max-connection-per-server",
    "max-download-limit",
    "max-file-not-found",
    "max-tries",
    "max-resume-failure-tries",
    "min-split-size",
    "no-proxy",
    "out",
    "proxy-method",
    "referer",
    "remote-time",
    "retry-wait",
    "split",
    "timeout",
    "user-agent",
    "use-head",
}


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with LOG_FILE.open("a", encoding="utf-8") as output:
            output.write(f"{timestamp} {message}\n")
    except OSError:
        print(f"{timestamp} {message}", file=sys.stderr)


def update_status(result: str, *, new_run: bool = False) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with STATUS_LOCK_FILE.open("a+", encoding="utf-8") as lock_file:
            flock(lock_file.fileno(), LOCK_EX)
            try:
                status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                status = {
                    "buildId": "unknown",
                    "containerStartedAt": None,
                    "hookScriptPresent": True,
                    "hookConfigured": None,
                    "hookRunCount": 0,
                    "lastHookRunAt": None,
                    "lastHookResult": "unknown",
                }

            if new_run:
                status["hookRunCount"] = int(status.get("hookRunCount", 0)) + 1
                status["lastHookRunAt"] = timestamp
            status["lastHookResult"] = result

            temporary_file = STATUS_FILE.with_name(
                f".{STATUS_FILE.name}.{os.getpid()}.tmp"
            )
            temporary_file.write_text(
                json.dumps(status, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            temporary_file.chmod(0o644)
            os.replace(temporary_file, STATUS_FILE)
    except OSError as error:
        log(f"could not update status marker: {error}")


def read_rpc_secret() -> str:
    for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("rpc-secret="):
            secret = stripped.split("=", 1)[1].strip()
            if secret:
                return secret
    raise RuntimeError("rpc-secret is missing from the aria2 config")


def rpc(secret: str, method: str, *params: object) -> object:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "low-speed-retry-hook",
            "method": f"aria2.{method}",
            "params": [f"token:{secret}", *params],
        }
    ).encode("utf-8")
    request = Request(
        RPC_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with RPC_OPENER.open(request, timeout=RPC_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        # HTTPError is also a readable response; keep Aria2's RPC error body
        # so the hook log explains failures such as an unsupported method.
        response_body = getattr(error, "read", lambda: b"")()
        detail = response_body.decode("utf-8", errors="replace").strip()
        if detail:
            try:
                error_payload = json.loads(detail)
                rpc_error = error_payload.get("error", {})
                detail = (
                    f"aria2 RPC error {rpc_error.get('code')}: "
                    f"{rpc_error.get('message', detail)}"
                )
            except (AttributeError, json.JSONDecodeError):
                pass
        if detail:
            raise RuntimeError(f"{error}: {detail}") from error
        raise

    if "error" in payload:
        error = payload["error"]
        raise RuntimeError(
            f"aria2 RPC error {error.get('code')}: {error.get('message', 'unknown error')}"
        )
    return payload.get("result")


def is_low_speed_error(status: object) -> bool:
    if not isinstance(status, dict):
        return False
    message = str(status.get("errorMessage", "")).lower()
    return (
        status.get("status") == "error"
        and str(status.get("errorCode", "")) == "5"
        and "too slow downloading speed" in message
    )


def retry_delay_seconds() -> int:
    try:
        value = int(os.environ.get("ARIA2_LOW_SPEED_RETRY_DELAY_SECONDS", "30"))
    except ValueError:
        value = 30
    return max(0, min(value, 3600))


def resume_confirmation_timeout_seconds() -> int:
    try:
        value = int(os.environ.get("ARIA2_RESUME_CONFIRM_TIMEOUT_SECONDS", "90"))
    except ValueError:
        value = 90
    return max(5, min(value, 600))


def resume_confirmation_interval_seconds() -> int:
    try:
        value = int(os.environ.get("ARIA2_RESUME_CONFIRM_INTERVAL_SECONDS", "2"))
    except ValueError:
        value = 2
    return max(1, min(value, 30))


def status_length(status: dict[str, object], key: str) -> int:
    try:
        return max(0, int(str(status.get(key, "0"))))
    except (TypeError, ValueError):
        return 0


def retry_download(
    secret: str, gid: str, status: dict[str, object]
) -> tuple[str, str, int, int, bool]:
    files = status.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise RuntimeError("retry supports only a single-file HTTP/FTP/SFTP download")

    file_info = files[0]
    path = str(file_info.get("path", ""))
    if not path:
        raise RuntimeError("Aria2 did not report an output path for this download")

    uri_entries = file_info.get("uris")
    if not isinstance(uri_entries, list):
        raise RuntimeError("Aria2 did not report source URIs for this download")
    uris = [
        str(entry.get("uri", ""))
        for entry in uri_entries
        if isinstance(entry, dict) and entry.get("uri")
    ]
    if not uris:
        raise RuntimeError("Aria2 did not report a usable source URI for this download")

    options_result = rpc(secret, "getOption", gid)
    if not isinstance(options_result, dict):
        raise RuntimeError("Aria2 returned invalid download options")
    options = {
        key: str(value)
        for key, value in options_result.items()
        if key in RETRY_OPTION_KEYS and value is not None and str(value) != ""
    }

    # Reuse the exact destination and Aria2's .aria2 control file so addUri
    # resumes the partial file instead of creating a renamed duplicate.
    options["dir"] = posixpath.dirname(path) or "/downloads"
    options["out"] = posixpath.basename(path)
    options["continue"] = "true"
    options["always-resume"] = "true"
    options["auto-file-renaming"] = "false"
    old_completed = status_length(status, "completedLength")
    old_total = status_length(status, "totalLength")

    # A manual retry may already have created a replacement while this hook
    # was waiting. Reuse it so the old result is removed only after its resume
    # has been confirmed below.
    active = rpc(secret, "tellActive", ["files"])
    waiting = rpc(secret, "tellWaiting", 0, 1000, ["files"])
    for jobs in (active, waiting):
        if not isinstance(jobs, list):
            continue
        for job in jobs:
            if not isinstance(job, dict) or job.get("gid") == gid:
                continue
            job_files = job.get("files")
            if isinstance(job_files, list) and any(
                isinstance(item, dict) and item.get("path") == path
                for item in job_files
            ):
                existing_gid = str(job.get("gid", ""))
                if existing_gid:
                    return existing_gid, path, old_completed, old_total, True

    replacement_gid = rpc(secret, "addUri", uris, options)
    if not isinstance(replacement_gid, str) or not replacement_gid:
        raise RuntimeError("aria2.addUri did not return a replacement GID")
    return replacement_gid, path, old_completed, old_total, False


def wait_for_resume(
    secret: str,
    replacement_gid: str,
    expected_path: str,
    old_completed: int,
    old_total: int,
) -> int | None:
    timeout = resume_confirmation_timeout_seconds()
    interval = resume_confirmation_interval_seconds()
    deadline = time.monotonic() + timeout
    keys = ["status", "completedLength", "totalLength", "files"]

    while True:
        status = rpc(secret, "tellStatus", replacement_gid, keys)
        if isinstance(status, dict):
            state = str(status.get("status", "unknown"))
            completed = status_length(status, "completedLength")
            total = status_length(status, "totalLength")
            files = status.get("files")
            same_path = (
                isinstance(files, list)
                and any(
                    isinstance(item, dict) and item.get("path") == expected_path
                    for item in files
                )
            )
            same_size = old_total <= 0 or total == old_total
            resumed = (
                same_path
                and same_size
                and total > 0
                and completed >= old_completed
                and (
                    completed > old_completed
                    or (state in ("active", "complete") and old_completed > 0)
                )
            )
            if resumed:
                return completed
            if state in ("error", "complete", "removed"):
                return None

        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def main() -> int:
    gid = sys.argv[1] if len(sys.argv) >= 2 else ""
    update_status("invoked", new_run=True)
    log("hook invoked")

    if not gid:
        update_status("missing-gid")
        log("ignored error hook call without a GID")
        return 2

    try:
        secret = read_rpc_secret()
        status = rpc(
            secret,
            "tellStatus",
            gid,
            [
                "status",
                "errorCode",
                "errorMessage",
                "files",
                "completedLength",
                "totalLength",
            ],
        )
        if not is_low_speed_error(status):
            update_status("ignored-not-low-speed")
            log(f"GID {gid}: no low-speed error; left unchanged")
            return 0

        delay = retry_delay_seconds()
        log(f"GID {gid}: low-speed error detected; retry check in {delay}s")
        time.sleep(delay)

        status = rpc(
            secret,
            "tellStatus",
            gid,
            [
                "status",
                "errorCode",
                "errorMessage",
                "files",
                "completedLength",
                "totalLength",
            ],
        )
        if not is_low_speed_error(status):
            current_state = status.get("status", "unknown") if isinstance(status, dict) else "unknown"
            update_status("skipped-state-changed")
            log(f"GID {gid}: state changed to {current_state}; retry skipped")
            return 0

        replacement_gid, path, old_completed, old_total, already_exists = retry_download(
            secret, gid, status
        )
        if already_exists:
            log(
                f"GID {gid}: found existing retry GID {replacement_gid} "
                "for the same output path; waiting for resume confirmation"
            )
        else:
            log(f"GID {gid}: retry queued as replacement GID {replacement_gid}")

        resumed_at = wait_for_resume(
            secret, replacement_gid, path, old_completed, old_total
        )
        if resumed_at is None:
            update_status("retry-queued")
            log(
                f"GID {gid}: resume not confirmed for replacement GID "
                f"{replacement_gid}; old result retained"
            )
            return 0

        try:
            rpc(secret, "removeDownloadResult", gid)
        except Exception as error:
            update_status("retry-resumed-cleanup-error")
            log(
                f"GID {gid}: replacement GID {replacement_gid} resumed at "
                f"{resumed_at} bytes, but old result cleanup failed: {error}"
            )
            return 1

        update_status("retry-resumed")
        log(
            f"GID {gid}: replacement GID {replacement_gid} resumed at "
            f"{resumed_at} bytes; old result removed"
        )
        return 0
    except Exception as error:  # Keep hook failures visible without logging credentials.
        update_status("hook-error")
        log(f"GID {gid}: retry hook failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
