from __future__ import annotations

import io
import logging
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request
from gtts import gTTS

from tme3bot.worker.tts_pipeline import TTS_PART_CHARS

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("tme3bot.tts_helper")
_TOR_PROCESS: subprocess.Popen | None = None
_HELPER_LOCK = threading.RLock()
_ACTIVE_SYNTHESIS = 0
_RECOVERY_RUNNING = False
_RECOVERY_COOLDOWN_SECONDS = 60
_RECOVERY_LAST_STARTED = 0.0


def _bootstrap_percent(status: bytes) -> int | None:
    match = re.search(rb"(?:^|\s)PROGRESS=(\d{1,3})(?:\s|$)", status)
    if not match:
        return None
    return max(0, min(100, int(match.group(1))))


def _tor_status(command: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", 9051), timeout=2) as connection:
        stream = connection.makefile("rwb", buffering=0)
        stream.write(b"AUTHENTICATE\r\n")
        if not stream.readline().startswith(b"250"):
            return b""
        stream.write(command + b"\r\n")
        lines = []
        while True:
            line = stream.readline()
            lines.append(line)
            if line.startswith((b"250 ", b"5")):
                break
        return b"".join(lines)


def _tor_ready() -> bool:
    try:
        return b"PROGRESS=100" in _tor_status(b"GETINFO status/bootstrap-phase")
    except OSError:
        return False


def _tor_diagnostics() -> tuple[str, int | None]:
    try:
        status = _tor_status(b"GETINFO status/bootstrap-phase")
    except OSError:
        return "tor_unreachable", None
    percent = _bootstrap_percent(status)
    if percent is None:
        return "tor_unreachable", None
    return ("ready" if percent >= 100 else "bootstrapping"), percent


def _start_tor() -> None:
    global _TOR_PROCESS
    import pwd

    data_dir = Path(os.getenv("TTS_TOR_DATA_DIR", "/tmp/tme3-tor"))
    data_dir.mkdir(parents=True, exist_ok=True)
    tor_user = pwd.getpwnam("debian-tor")
    os.chown(data_dir, tor_user.pw_uid, tor_user.pw_gid)
    data_dir.chmod(0o700)
    _TOR_PROCESS = subprocess.Popen(
        [
            "tor",
            "--SocksPort",
            "127.0.0.1:9050",
            "--ControlPort",
            "127.0.0.1:9051",
            "--CookieAuthentication",
            "0",
            "--DataDirectory",
            str(data_dir),
            "--Log",
            "notice stdout",
        ],
        # Keep Tor diagnostics in the helper container log.  The control
        # listener is loopback-only, so no Tor credential is exposed here.
        stdout=None,
        stderr=None,
        user=tor_user.pw_uid,
        group=tor_user.pw_gid,
    )


def _restart_tor() -> None:
    global _TOR_PROCESS
    process = _TOR_PROCESS
    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except ChildProcessError:
                pass
        except ChildProcessError:
            pass
    _TOR_PROCESS = None
    _start_tor()


def _run_tor_recovery() -> None:
    global _RECOVERY_RUNNING
    try:
        _restart_tor()
    except Exception as exc:
        LOGGER.warning("Tor helper recovery failed error_type=%s", type(exc).__name__)
    finally:
        with _HELPER_LOCK:
            _RECOVERY_RUNNING = False


@app.get("/healthz")
def ready():
    return jsonify({"ok": True})


@app.get("/readyz")
def readyz():
    return (jsonify({"ok": True}), 200) if _tor_ready() else (jsonify({"ok": False}), 503)


@app.get("/diagnostics")
def diagnostics():
    with _HELPER_LOCK:
        recovering = _RECOVERY_RUNNING
    if recovering:
        return jsonify({"status": "bootstrapping", "bootstrap_percent": 0})
    status, percent = _tor_diagnostics()
    if _TOR_PROCESS is not None and _TOR_PROCESS.poll() is not None:
        status, percent = "tor_unreachable", None
    return jsonify({"status": status, "bootstrap_percent": percent})


@app.post("/recover-tor")
def recover_tor():
    global _RECOVERY_RUNNING, _RECOVERY_LAST_STARTED
    with _HELPER_LOCK:
        if _RECOVERY_RUNNING:
            return jsonify({"accepted": True, "status": "restarting"}), 202
        if _ACTIVE_SYNTHESIS:
            return jsonify({"error": "TTS_HELPER_BUSY", "active_requests": _ACTIVE_SYNTHESIS}), 409
        status, _ = _tor_diagnostics()
        if _TOR_PROCESS is not None and _TOR_PROCESS.poll() is not None:
            status = "tor_unreachable"
        if status == "ready":
            return jsonify({"error": "TTS_HELPER_ALREADY_READY"}), 409
        elapsed = time.monotonic() - _RECOVERY_LAST_STARTED
        if _RECOVERY_LAST_STARTED and elapsed < _RECOVERY_COOLDOWN_SECONDS:
            remaining = max(1, int(_RECOVERY_COOLDOWN_SECONDS - elapsed + 0.999))
            return (
                jsonify({"error": "TTS_RECOVERY_COOLDOWN", "retry_after_seconds": remaining}),
                429,
                {"Retry-After": str(remaining)},
            )
        _RECOVERY_RUNNING = True
        _RECOVERY_LAST_STARTED = time.monotonic()
        try:
            threading.Thread(target=_run_tor_recovery, name="tts-tor-recovery", daemon=True).start()
        except Exception as exc:
            _RECOVERY_RUNNING = False
            _RECOVERY_LAST_STARTED = 0.0
            LOGGER.warning("Could not start Tor recovery error_type=%s", type(exc).__name__)
            return jsonify({"error": "TTS_HELPER_UNAVAILABLE"}), 503
    return jsonify({"accepted": True, "status": "restarting"}), 202


@app.post("/newnym")
def renew_tor_circuit():
    try:
        renewed = _tor_status(b"SIGNAL NEWNYM").startswith(b"250")
    except OSError:
        renewed = False
    return (jsonify({"renewed": True}), 200) if renewed else (jsonify({"renewed": False}), 503)


@app.post("/synthesize-part")
def synthesize_part():
    global _ACTIVE_SYNTHESIS
    payload = request.get_json(silent=True) or {}
    text = " ".join(str(payload.get("text") or "").split())
    if not text or len(text) > TTS_PART_CHARS:
        return jsonify({"error": "invalid_part"}), 422
    with _HELPER_LOCK:
        if _RECOVERY_RUNNING:
            return jsonify({"error": "TTS_HELPER_RECOVERING"}), 503
        _ACTIVE_SYNTHESIS += 1
    try:
        output = io.BytesIO()
        gTTS(text=text, lang="id", tld="com", slow=False).write_to_fp(output)
        audio = output.getvalue()
        if not audio:
            raise RuntimeError("empty_audio")
    except Exception as exc:
        response = getattr(exc, "rsp", None)
        try:
            upstream_status = int(response.status_code) if response is not None else 0
        except (AttributeError, TypeError, ValueError):
            upstream_status = 0
        status = upstream_status if upstream_status in {403, 408, 425, 429} or upstream_status >= 500 else 502
        LOGGER.warning(
            "gTTS request failed job=%s part=%s route=%s error_type=%s status=%s",
            str(payload.get("job_id") or "")[:80],
            payload.get("part_index"),
            re.sub(r"[^a-zA-Z0-9_-]", "", str(payload.get("route") or ""))[:16],
            type(exc).__name__,
            status,
        )
        return jsonify({"error": "upstream_tts_failed"}), status
    finally:
        with _HELPER_LOCK:
            _ACTIVE_SYNTHESIS = max(0, _ACTIVE_SYNTHESIS - 1)
    return Response(audio, status=200, mimetype="audio/mpeg")


if __name__ == "__main__":
    from waitress import serve

    _start_tor()
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline and _TOR_PROCESS.poll() is None:
        if _tor_ready():
            break
        time.sleep(1)
    serve(app, host="0.0.0.0", port=8090, threads=8)
