from __future__ import annotations

import io
import logging
import os
import re
import socket
import subprocess
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request
from gtts import gTTS

from tme3bot.worker.tts_pipeline import TTS_PART_CHARS

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("tme3bot.tts_helper")
_TOR_PROCESS: subprocess.Popen | None = None


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
            "0.0.0.0:9050",
            "--ControlPort",
            "0.0.0.0:9051",
            "--CookieAuthentication",
            "0",
            "--DataDirectory",
            str(data_dir),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        user=tor_user.pw_uid,
        group=tor_user.pw_gid,
    )


@app.get("/healthz")
def ready():
    return jsonify({"ok": True})


@app.get("/readyz")
def readyz():
    return (jsonify({"ok": True}), 200) if _tor_ready() else (jsonify({"ok": False}), 503)


@app.post("/newnym")
def renew_tor_circuit():
    try:
        renewed = _tor_status(b"SIGNAL NEWNYM").startswith(b"250")
    except OSError:
        renewed = False
    return (jsonify({"renewed": True}), 200) if renewed else (jsonify({"renewed": False}), 503)


@app.post("/synthesize-part")
def synthesize_part():
    payload = request.get_json(silent=True) or {}
    text = " ".join(str(payload.get("text") or "").split())
    if not text or len(text) > TTS_PART_CHARS:
        return jsonify({"error": "invalid_part"}), 422
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
