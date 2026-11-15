"""Authenticated HTTP proxy that tunnels HTTP(S) requests through Tor SOCKS."""

from __future__ import annotations

import base64
import hmac
import ipaddress
import re
import select
import socket
import socketserver
import threading
from pathlib import Path
from urllib.parse import urlsplit


_HEADER_NAME = re.compile(rb"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_PROXY_USER = "aria2"


class _ThreadingProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False


class TorHttpProxyServer:
    """Small internal-only HTTP/CONNECT proxy with remote DNS via Tor."""

    def __init__(
        self,
        *,
        token_file: Path | str,
        socks_host: str = "127.0.0.1",
        socks_port: int = 9050,
        host: str = "0.0.0.0",
        port: int = 8118,
    ) -> None:
        self.token_file = Path(token_file)
        self.socks_host = socks_host
        self.socks_port = int(socks_port)
        self._server = _ThreadingProxyServer((host, int(port)), self._handler_type())
        self._server.proxy_owner = self
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        return self._server.server_address[:2]

    @staticmethod
    def _handler_type():
        class ProxyHandler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                self.connection.settimeout(20)
                try:
                    request_line = self.rfile.readline(8193)
                    if len(request_line) > 8192 or not request_line.endswith(b"\r\n"):
                        self._respond(400, "Bad Request")
                        return
                    try:
                        method, target, version = request_line.decode("ascii").strip().split(" ", 2)
                    except (UnicodeDecodeError, ValueError):
                        self._respond(400, "Bad Request")
                        return
                    if version not in {"HTTP/1.0", "HTTP/1.1"}:
                        self._respond(400, "Bad Request")
                        return
                    headers = self._read_headers()
                    if headers is None:
                        self._respond(400, "Bad Request")
                        return
                    owner = self.server.proxy_owner
                    if not owner._authorized(headers.get("proxy-authorization", "")):
                        self._respond(407, "Proxy Authentication Required", authenticate=True)
                        return
                    if method.upper() == "CONNECT":
                        self._connect(target, owner)
                    elif method.upper() in {"GET", "HEAD"}:
                        self._forward_http(method.upper(), target, version, headers, owner)
                    else:
                        self._respond(405, "Method Not Allowed")
                except (OSError, ValueError, UnicodeError):
                    self._respond(502, "Bad Gateway")
                finally:
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    self.connection.close()

            def _read_headers(self) -> dict[str, str] | None:
                headers: dict[str, str] = {}
                total = 0
                while True:
                    line = self.rfile.readline(8193)
                    total += len(line)
                    if not line or len(line) > 8192 or total > 65536:
                        return None
                    if line == b"\r\n":
                        return headers
                    if not line.endswith(b"\r\n") or b":" not in line:
                        return None
                    name, value = line[:-2].split(b":", 1)
                    if not _HEADER_NAME.fullmatch(name.strip()):
                        return None
                    try:
                        key = name.decode("ascii").strip().lower()
                        text = value.decode("latin-1").strip()
                    except UnicodeDecodeError:
                        return None
                    # Reject duplicate authentication or routing headers instead
                    # of choosing one interpretation across proxy layers.
                    if key in headers and key in {"proxy-authorization", "host"}:
                        return None
                    headers[key] = text

            def _connect(self, authority: str, owner: "TorHttpProxyServer") -> None:
                host, port = owner._parse_authority(authority)
                if port != 443 or not owner._safe_host(host):
                    self._respond(403, "Forbidden")
                    return
                upstream = owner._connect_via_tor(host, port)
                self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self.wfile.flush()
                owner._relay(self.connection, upstream)

            def _forward_http(
                self,
                method: str,
                target: str,
                version: str,
                headers: dict[str, str],
                owner: "TorHttpProxyServer",
            ) -> None:
                parsed = urlsplit(target)
                try:
                    port = parsed.port or (80 if parsed.scheme.lower() == "http" else 0)
                except ValueError:
                    port = 0
                host = (parsed.hostname or "").rstrip(".").lower()
                if (
                    parsed.scheme.lower() != "http"
                    or parsed.username is not None
                    or parsed.password is not None
                    or port != 80
                    or not owner._safe_host(host)
                ):
                    self._respond(403, "Forbidden")
                    return
                upstream = owner._connect_via_tor(host, port)
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                output = [f"{method} {path} {version}\r\n"]
                for key, value in headers.items():
                    if key in {"proxy-authorization", "proxy-connection", "connection"}:
                        continue
                    output.append(f"{key}: {value}\r\n")
                if "host" not in headers:
                    output.append(f"Host: {host}\r\n")
                output.append("Connection: close\r\n\r\n")
                upstream.sendall("".join(output).encode("latin-1"))
                owner._relay(self.connection, upstream)

            def _respond(self, status: int, reason: str, *, authenticate: bool = False) -> None:
                headers = [
                    f"HTTP/1.1 {status} {reason}\r\n",
                    "Connection: close\r\n",
                    "Content-Length: 0\r\n",
                ]
                if authenticate:
                    headers.append('Proxy-Authenticate: Basic realm="Aria2 Tor route"\r\n')
                headers.append("\r\n")
                try:
                    self.wfile.write("".join(headers).encode("ascii"))
                    self.wfile.flush()
                except OSError:
                    pass

        return ProxyHandler

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="aria2-tor-http-proxy",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)

    def ready(self) -> bool:
        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
            if not token or not (self._thread and self._thread.is_alive()):
                return False
            with socket.create_connection((self.socks_host, self.socks_port), timeout=1) as connection:
                connection.settimeout(1)
                connection.sendall(b"\x05\x01\x00")
                return connection.recv(2) == b"\x05\x00"
        except OSError:
            return False

    def _authorized(self, header: str) -> bool:
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
            expected = self.token_file.read_text(encoding="utf-8").strip()
        except (OSError, ValueError, UnicodeError):
            return False
        return bool(expected) and username == _PROXY_USER and hmac.compare_digest(password, expected)

    @staticmethod
    def _parse_authority(authority: str) -> tuple[str, int]:
        parsed = urlsplit("//" + authority)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("invalid proxy authority")
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
        if not host or port is None:
            raise ValueError("invalid proxy authority")
        return host, port

    @staticmethod
    def _safe_host(host: str) -> bool:
        if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan")):
            return False
        if host in {"host.docker.internal", "gateway.docker.internal"}:
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return bool(re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", host))

    def _connect_via_tor(self, host: str, port: int) -> socket.socket:
        upstream = socket.create_connection((self.socks_host, self.socks_port), timeout=15)
        try:
            upstream.settimeout(15)
            upstream.sendall(b"\x05\x01\x00")
            if self._receive_exact(upstream, 2) != b"\x05\x00":
                raise OSError("Tor SOCKS authentication negotiation failed")
            encoded_host = host.encode("idna")
            if len(encoded_host) > 255:
                raise ValueError("host name is too long")
            request = b"\x05\x01\x00\x03" + bytes((len(encoded_host),)) + encoded_host + int(port).to_bytes(2, "big")
            upstream.sendall(request)
            response = self._receive_exact(upstream, 4)
            if response[0] != 5 or response[1] != 0:
                raise OSError("Tor SOCKS connection failed")
            if response[3] == 1:
                self._receive_exact(upstream, 4)
            elif response[3] == 3:
                self._receive_exact(upstream, self._receive_exact(upstream, 1)[0])
            elif response[3] == 4:
                self._receive_exact(upstream, 16)
            else:
                raise OSError("Tor SOCKS returned an invalid address")
            self._receive_exact(upstream, 2)
            upstream.settimeout(None)
            return upstream
        except Exception:
            upstream.close()
            raise

    @staticmethod
    def _receive_exact(connection: socket.socket, count: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < count:
            chunk = connection.recv(count - len(chunks))
            if not chunk:
                raise OSError("Tor SOCKS connection closed")
            chunks.extend(chunk)
        return bytes(chunks)

    @staticmethod
    def _relay(client: socket.socket, upstream: socket.socket) -> None:
        try:
            while True:
                readable, _, exceptional = select.select([client, upstream], [], [client, upstream], 60)
                if exceptional or not readable:
                    return
                for source in readable:
                    chunk = source.recv(65536)
                    if not chunk:
                        return
                    (upstream if source is client else client).sendall(chunk)
        finally:
            upstream.close()
