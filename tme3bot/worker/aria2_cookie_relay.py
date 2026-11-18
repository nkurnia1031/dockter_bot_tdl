"""Task-scoped Netscape cookies for Aria2 downloads, with redirect-safe delivery."""

from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import re
import secrets
import sqlite3
import ssl
import tempfile
import threading
import time
import urllib.error
from http.cookiejar import Cookie, MozillaCookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from tme3bot.database_paths import DatabasePaths, ensure_private_directory


MAX_COOKIE_FILE_BYTES = 2 * 1024 * 1024
MAX_RELAY_REQUEST_BYTES = 20 * 1024 * 1024
_COOKIE_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_TASK_PATH = re.compile(r"^/task/([a-f0-9]{64})/(\d+)(?:/[^/]*)?$")
_COOKIE_TASK_URL = re.compile(r"(?P<prefix>https?://[^/\s]+/task/)[a-f0-9]{64}(?=/)", re.I)
_RELAY_HEADERS = frozenset({
    "accept", "if-modified-since", "if-none-match", "if-range", "range", "user-agent",
})
_RESPONSE_HEADERS = frozenset({
    "accept-ranges", "cache-control", "content-disposition", "content-encoding", "content-range",
    "content-type", "etag", "expires", "last-modified", "pragma", "vary",
})
_HOP_HEADERS = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "set-cookie", "set-cookie2",
    "location",
})


class Aria2CookieError(ValueError):
    """A safe, user-displayable cookie task validation error."""


def redact_cookie_task_urls(value: object) -> str:
    """Hide relay capability tokens if Aria2 includes a source URI in its logs."""
    return _COOKIE_TASK_URL.sub(r"\g<prefix>[task-token]", str(value or ""))


def parse_netscape_cookie_file(cookie_bytes: bytes) -> list[Cookie]:
    if not cookie_bytes or len(cookie_bytes) > MAX_COOKIE_FILE_BYTES:
        raise Aria2CookieError("File cookies.txt kosong atau melebihi batas 2 MiB.")
    try:
        text = cookie_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Aria2CookieError("File cookies.txt harus berupa teks Netscape UTF-8.") from exc
    if "\x00" in text:
        raise Aria2CookieError("File cookies.txt tidak valid.")

    cookies: list[Cookie] = []
    for raw_line in text.splitlines():
        line = raw_line.strip("\r")
        if not line:
            continue
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            raise Aria2CookieError("Baris cookies.txt tidak mengikuti format Netscape.")
        raw_domain, include_subdomains, path, secure, expiry, name, value = fields
        domain = raw_domain.strip().lower()
        include_subdomains = include_subdomains.strip().upper()
        secure = secure.strip().upper()
        if (
            not domain
            or any(char.isspace() for char in domain)
            or any(char in domain for char in "/\\;@")
            or include_subdomains not in {"TRUE", "FALSE"}
            or secure not in {"TRUE", "FALSE"}
            or not path.startswith("/")
            or not _COOKIE_NAME.fullmatch(name)
            or any(char in value for char in "\r\n\x00")
        ):
            raise Aria2CookieError("Baris cookies.txt tidak valid.")
        try:
            expires_value = int(expiry)
        except ValueError as exc:
            raise Aria2CookieError("Waktu kedaluwarsa cookie tidak valid.") from exc
        if expires_value < 0:
            raise Aria2CookieError("Waktu kedaluwarsa cookie tidak valid.")

        domain_initial_dot = domain.startswith(".")
        domain_specified = include_subdomains == "TRUE"
        if domain_specified and not domain_initial_dot:
            domain = "." + domain
            domain_initial_dot = True
        rest = {"HttpOnly": None} if http_only else {}
        cookies.append(Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=domain_specified,
            domain_initial_dot=domain_initial_dot,
            path=path,
            path_specified=True,
            secure=secure == "TRUE",
            expires=expires_value or None,
            discard=expires_value == 0,
            comment=None,
            comment_url=None,
            rest=rest,
            rfc2109=False,
        ))
    if not cookies:
        raise Aria2CookieError("File cookies.txt tidak berisi cookie yang dapat dipakai.")
    return cookies


class Aria2CookieTaskStore:
    """Persist each cookie jar separately from the Aria2 task API."""

    def __init__(self, state_root: Path | str) -> None:
        requested_root = Path(os.path.abspath(Path(state_root)))
        paths = DatabasePaths(requested_root.parent)
        self.state_root = paths.aria2_directory()
        if requested_root != Path(os.path.abspath(self.state_root)):
            raise ValueError("Aria2 cookie state must use the validated aria2 database directory.")
        self.cookie_root = paths.sqlite("aria2/cookie-tasks")
        self.database = paths.sqlite("aria2/aria2-cookie-tasks.sqlite3")
        ensure_private_directory(self.state_root)
        ensure_private_directory(self.cookie_root)
        self._lock = threading.RLock()
        self._jar_locks: dict[str, threading.RLock] = {}
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS cookie_tasks (
                    token TEXT PRIMARY KEY,
                    gid TEXT UNIQUE,
                    uris_json TEXT NOT NULL,
                    route TEXT NOT NULL,
                    created_at REAL NOT NULL
                )"""
            )
            live_tokens = {
                str(row[0]) for row in db.execute("SELECT token FROM cookie_tasks").fetchall()
            }
        for path in self.cookie_root.glob("*.cookies"):
            if path.stem not in live_tokens:
                path.unlink(missing_ok=True)
        self.database.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def create_pending(self, uris: list[str], cookie_bytes: bytes, route: str) -> dict[str, Any]:
        cookies = parse_netscape_cookie_file(cookie_bytes)
        token = secrets.token_hex(32)
        cookie_path = self.cookie_root / f"{token}.cookies"
        self._save_cookie_jar(cookie_path, cookies)
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO cookie_tasks(token,gid,uris_json,route,created_at) VALUES(?,NULL,?,?,?)",
                    (token, json.dumps(uris, separators=(",", ":")), route, time.time()),
                )
        except Exception:
            cookie_path.unlink(missing_ok=True)
            raise
        return {"token": token, "uris": list(uris), "route": route, "cookie_path": cookie_path}

    def set_gid(self, token: str, gid: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE cookie_tasks SET gid=? WHERE token=?", (gid, token))

    def task_for_gid(self, gid: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM cookie_tasks WHERE gid=?", (gid,)).fetchone()
        return self._row_dict(row) if row else None

    def task_for_token(self, token: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM cookie_tasks WHERE token=?", (token,)).fetchone()
        return self._row_dict(row) if row else None

    def tasks(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM cookie_tasks ORDER BY created_at").fetchall()
        return [self._row_dict(row) for row in rows]

    @staticmethod
    def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["uris"] = json.loads(item.pop("uris_json"))
        item["cookie_path"] = ""
        return item

    def update_route(self, gid: str, route: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("UPDATE cookie_tasks SET route=? WHERE gid=?", (route, gid))
        return cursor.rowcount == 1

    def cookie_path(self, token: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            raise Aria2CookieError("Cookie task tidak ditemukan.")
        return self.cookie_root / f"{token}.cookies"

    def lock_for(self, token: str) -> threading.RLock:
        with self._lock:
            return self._jar_locks.setdefault(token, threading.RLock())

    def source_for_relay_uri(self, uri: str) -> str | None:
        try:
            path = urlsplit(uri).path
            match = _TASK_PATH.fullmatch(path)
            if not match:
                return None
            task = self.task_for_token(match.group(1))
            index = int(match.group(2))
            return task["uris"][index] if task and index < len(task["uris"]) else None
        except (ValueError, IndexError):
            return None

    def remove_token(self, token: str) -> None:
        path = self.cookie_path(token)
        with self._connect() as db:
            db.execute("DELETE FROM cookie_tasks WHERE token=?", (token,))
        path.unlink(missing_ok=True)
        with self._lock:
            self._jar_locks.pop(token, None)

    def remove_gid(self, gid: str) -> None:
        task = self.task_for_gid(gid)
        if task:
            self.remove_token(task["token"])

    def _save_cookie_jar(self, path: Path, cookies: list[Cookie]) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".cookie-", dir=self.cookie_root)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            jar = MozillaCookieJar(str(temporary))
            for cookie in cookies:
                jar.set_cookie(cookie)
            jar.save(ignore_discard=True, ignore_expires=True)
            temporary.chmod(0o600)
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)

    def load_cookie_jar(self, token: str) -> MozillaCookieJar:
        path = self.cookie_path(token)
        jar = MozillaCookieJar(str(path))
        jar.load(ignore_discard=True, ignore_expires=False)
        return jar

    def save_cookie_jar(self, token: str, jar: MozillaCookieJar) -> None:
        path = self.cookie_path(token)
        temporary = self.cookie_root / f".{token}.{secrets.token_hex(6)}.tmp"
        try:
            jar.save(str(temporary), ignore_discard=True, ignore_expires=True)
            temporary.chmod(0o600)
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)


class Aria2CookieRelayServer:
    """Internal HTTP relay used only as the URL source for cookie-backed Aria2 tasks."""

    def __init__(
        self,
        *,
        state_root: Path | str,
        rpc: Callable[..., Any],
        rpc_secret: Callable[[], str],
        tor_proxy_url: Callable[[], str],
        ssl_context: ssl.SSLContext | None = None,
        listen_host: str = "0.0.0.0",
        listen_port: int = 6801,
    ) -> None:
        self.state_root = Path(state_root)
        self.store = Aria2CookieTaskStore(self.state_root)
        self.rpc = rpc
        self.rpc_secret = rpc_secret
        self.tor_proxy_url = tor_proxy_url
        self.ssl_context = ssl_context
        self.listen_host = listen_host
        self.listen_port = listen_port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._last_reconcile = 0.0

    @property
    def base_url(self) -> str:
        if not self._server:
            raise RuntimeError("Cookie relay belum dijalankan.")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        if self._server:
            return
        relay = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, _format, *_args):
                pass

            def do_POST(self):
                if self.path != "/internal/add":
                    self.send_error(404)
                    return
                expected = f"Bearer {relay.rpc_secret()}"
                if not secrets.compare_digest(self.headers.get("Authorization", ""), expected):
                    self.send_error(401)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self.send_error(400)
                    return
                if length <= 0 or length > MAX_RELAY_REQUEST_BYTES:
                    self.send_error(413)
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    result = relay.add_task(payload)
                    data = json.dumps(result, separators=(",", ":")).encode("utf-8")
                except Aria2CookieError as exc:
                    data = json.dumps({
                        "jsonrpc": "2.0", "id": None,
                        "error": {"code": -32602, "message": str(exc)},
                    }).encode("utf-8")
                except Exception:
                    data = json.dumps({
                        "jsonrpc": "2.0", "id": None,
                        "error": {"code": -32000, "message": "Cookie task could not be created."},
                    }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                relay.serve_source(self)

            def do_HEAD(self):
                relay.serve_source(self)

        self._server = ThreadingHTTPServer((self.listen_host, self.listen_port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="aria2-cookie-relay"
        )
        self._thread.start()

    def close(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def add_task(self, payload: object) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise Aria2CookieError("Cookie task request is invalid.")
        request = payload.get("request")
        request_id = request.get("id") if isinstance(request, dict) else None
        if (
            not isinstance(request, dict)
            or request.get("jsonrpc") != "2.0"
            or request.get("method") != "aria2.addUri"
        ):
            raise Aria2CookieError("Cookie hanya didukung untuk task Links Aria2.")
        params = request.get("params")
        if not isinstance(params, list) or not params or not isinstance(params[0], list):
            raise Aria2CookieError("Daftar URL Aria2 tidak valid.")
        uris = [str(uri) for uri in params[0]]
        if not uris:
            raise Aria2CookieError("Daftar URL Aria2 kosong.")
        for uri in uris:
            parsed = urlsplit(uri)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise Aria2CookieError("Cookie hanya dapat digunakan pada URL HTTP atau HTTPS tanpa kredensial di URL.")
        route = str(payload.get("route") or "non")
        if route not in {"non", "tor"}:
            raise Aria2CookieError("Rute task cookie tidak valid.")
        encoded = payload.get("cookies_b64")
        if not isinstance(encoded, str) or len(encoded) > 3 * MAX_COOKIE_FILE_BYTES:
            raise Aria2CookieError("File cookies.txt kosong atau melebihi batas 2 MiB.")
        try:
            cookie_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise Aria2CookieError("Encoding cookies.txt tidak valid.") from exc
        if route == "tor":
            try:
                proxy = self.tor_proxy_url()
            except Exception as exc:
                raise Aria2CookieError("ARIA2_TOR_UNAVAILABLE: layanan Tor worker belum siap.") from exc
            if not proxy:
                raise Aria2CookieError("ARIA2_TOR_UNAVAILABLE: layanan Tor worker belum siap.")

        if len(params) < 2 or not isinstance(params[1], dict):
            params = [*params[:1], {}, *params[2:]]
        options = dict(params[1])
        task = self.store.create_pending(uris, cookie_bytes, route)
        proxy_uris = [self._relay_uri(task["token"], index, uri) for index, uri in enumerate(uris)]
        try:
            gid = self.rpc("addUri", proxy_uris, options)
            if not isinstance(gid, str) or not re.fullmatch(r"[0-9a-fA-F]{16}", gid):
                raise RuntimeError("Aria2 did not return a task id.")
            self.store.set_gid(task["token"], gid)
        except Exception:
            self.store.remove_token(task["token"])
            return {
                "jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32000, "message": "Aria2 rejected the cookie task."},
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": gid}

    def _relay_uri(self, token: str, index: int, source: str) -> str:
        if not self._server:
            raise RuntimeError("Cookie relay is not running.")
        host = self._server.server_address[0]
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        parsed = urlsplit(source)
        filename = Path(parsed.path).name or "download"
        return f"http://{host}:{self._server.server_address[1]}/task/{token}/{index}/{quote(filename, safe='')}"

    def serve_source(self, handler: BaseHTTPRequestHandler) -> None:
        match = _TASK_PATH.fullmatch(urlsplit(handler.path).path)
        if not match:
            handler.send_error(404)
            return
        token, index_text = match.groups()
        task = self.store.task_for_token(token)
        index = int(index_text)
        if not task or index >= len(task["uris"]):
            handler.send_error(404)
            return
        source = task["uris"][index]
        request_headers = {
            key: value for key, value in handler.headers.items()
            if key.lower() in _RELAY_HEADERS
        }
        request_headers["Accept-Encoding"] = "identity"
        upstream_request = Request(source, headers=request_headers, method=handler.command)
        if task["route"] == "tor":
            try:
                proxy = self.tor_proxy_url()
            except Exception:
                self._send_empty(handler, 503)
                return
            if not proxy:
                self._send_empty(handler, 503)
                return
            proxy_handler = ProxyHandler({"http": proxy, "https": proxy})
        else:
            proxy_handler = ProxyHandler({})
        try:
            with self.store.lock_for(token):
                jar = self.store.load_cookie_jar(token)
                opener = build_opener(
                    proxy_handler,
                    HTTPCookieProcessor(jar),
                    HTTPSHandler(context=self.ssl_context) if self.ssl_context else HTTPSHandler(),
                )
                response = opener.open(upstream_request, timeout=90)
                self.store.save_cookie_jar(token, jar)
        except urllib.error.HTTPError as exc:
            try:
                status = int(exc.code)
            except (ValueError, TypeError):
                status = 502
            self._send_empty(handler, status)
            return
        except (OSError, urllib.error.URLError, ValueError, http.cookiejar.LoadError):
            self._send_empty(handler, 502)
            return
        try:
            handler.send_response(response.status)
            sent_length = False
            for key, value in response.headers.items():
                lowered = key.lower()
                if (
                    lowered in _HOP_HEADERS
                    or lowered == "content-length"
                    or lowered not in _RESPONSE_HEADERS
                    or "\r" in value
                    or "\n" in value
                ):
                    continue
                handler.send_header(key, value)
            content_length = response.headers.get("Content-Length")
            if content_length is not None and content_length.isdigit():
                handler.send_header("Content-Length", content_length)
                sent_length = True
            handler.end_headers()
            if handler.command != "HEAD":
                while True:
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    handler.wfile.write(chunk)
            if not sent_length:
                handler.close_connection = True
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            response.close()

    @staticmethod
    def _send_empty(handler: BaseHTTPRequestHandler, status: int) -> None:
        try:
            handler.send_response(status)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
        except OSError:
            pass

    def reconcile(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_reconcile < 10:
            return
        self._last_reconcile = now
        try:
            observed: dict[str, str] = {}
            token_to_gid: dict[str, str] = {}
            active = self.rpc("tellActive", ["gid", "status", "files"])
            if not isinstance(active, list):
                return
            observed.update({str(row.get("gid")): str(row.get("status")) for row in active if isinstance(row, dict)})
            for method in ("tellWaiting", "tellStopped"):
                offset = 0
                while offset < 100_000:
                    rows = self.rpc(method, offset, 1000, ["gid", "status", "files"])
                    if not isinstance(rows, list):
                        return
                    observed.update({str(row.get("gid")): str(row.get("status")) for row in rows if isinstance(row, dict)})
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        gid = str(row.get("gid") or "")
                        for file_info in row.get("files", []) if isinstance(row.get("files"), list) else []:
                            for uri in file_info.get("uris", []) if isinstance(file_info, dict) and isinstance(file_info.get("uris"), list) else []:
                                if not isinstance(uri, dict):
                                    continue
                                match = _TASK_PATH.fullmatch(urlsplit(str(uri.get("uri") or "")).path)
                                if match and gid:
                                    token_to_gid[match.group(1)] = gid
                    if len(rows) < 1000:
                        break
                    offset += len(rows)
            for task in self.store.tasks():
                gid = str(task.get("gid") or "")
                if not gid and task["token"] in token_to_gid:
                    self.store.set_gid(task["token"], token_to_gid[task["token"]])
                    gid = token_to_gid[task["token"]]
                status = observed.get(gid)
                if status in {"complete", "removed"}:
                    self.store.remove_token(task["token"])
        except Exception:
            # A temporary RPC failure must not delete task cookies.
            return
