from __future__ import annotations

import base64
import select
import socket
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path

from tme3bot.worker.tor_http_proxy import TorHttpProxyServer


def _receive_exact(connection: socket.socket, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        chunk = connection.recv(count - len(chunks))
        if not chunk:
            raise ConnectionError("connection closed")
        chunks.extend(chunk)
    return bytes(chunks)


class _TargetHandler(socketserver.BaseRequestHandler):
    def handle(self):
        first = self.request.recv(4096)
        if first.startswith((b"GET ", b"HEAD ")):
            remaining = bytearray(first)
            while b"\r\n\r\n" not in remaining:
                chunk = self.request.recv(4096)
                if not chunk:
                    break
                remaining.extend(chunk)
            self.server.requests.append(bytes(remaining))
            self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello")
            return
        self.request.sendall(b"echo:" + first)
        while True:
            chunk = self.request.recv(4096)
            if not chunk:
                break
            self.request.sendall(chunk)


class _ThreadedTarget(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.requests: list[bytes] = []
        super().__init__(("127.0.0.1", 0), _TargetHandler)


class _SocksHandler(socketserver.BaseRequestHandler):
    def handle(self):
        version, count = _receive_exact(self.request, 2)
        _receive_exact(self.request, count)
        if version != 5:
            return
        self.request.sendall(b"\x05\x00")
        version, command, _reserved, address_type = _receive_exact(self.request, 4)
        if version != 5 or command != 1:
            return
        if address_type == 3:
            length = _receive_exact(self.request, 1)[0]
            host = _receive_exact(self.request, length).decode("ascii")
        elif address_type == 1:
            host = socket.inet_ntoa(_receive_exact(self.request, 4))
        elif address_type == 4:
            host = socket.inet_ntop(socket.AF_INET6, _receive_exact(self.request, 16))
        else:
            return
        port = int.from_bytes(_receive_exact(self.request, 2), "big")
        self.server.destinations.append((host, port))
        upstream = socket.create_connection(self.server.target.server_address)
        self.request.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
        try:
            while True:
                readable, _, _ = select.select([self.request, upstream], [], [], 2)
                if not readable:
                    continue
                for source in readable:
                    chunk = source.recv(4096)
                    if not chunk:
                        return
                    (upstream if source is self.request else self.request).sendall(chunk)
        finally:
            upstream.close()


class _ThreadedSocks(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, target: _ThreadedTarget):
        self.target = target
        self.destinations: list[tuple[str, int]] = []
        super().__init__(("127.0.0.1", 0), _SocksHandler)


class TorHttpProxyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.token_file = Path(self.temporary.name) / "proxy.token"
        self.token_file.write_text("test-proxy-token\n", encoding="utf-8")
        self.token_file.chmod(0o600)
        self.target = _ThreadedTarget()
        self.target_thread = threading.Thread(target=self.target.serve_forever, daemon=True)
        self.target_thread.start()
        self.socks = _ThreadedSocks(self.target)
        self.socks_thread = threading.Thread(target=self.socks.serve_forever, daemon=True)
        self.socks_thread.start()
        self.proxy = TorHttpProxyServer(
            token_file=self.token_file,
            socks_host="127.0.0.1",
            socks_port=self.socks.server_address[1],
            host="127.0.0.1",
            port=0,
        )
        self.proxy.start()

    def tearDown(self):
        self.proxy.close()
        self.socks.shutdown()
        self.socks.server_close()
        self.target.shutdown()
        self.target.server_close()
        self.temporary.cleanup()

    @property
    def proxy_authorization(self) -> bytes:
        value = base64.b64encode(b"aria2:test-proxy-token").decode("ascii")
        return f"Proxy-Authorization: Basic {value}\r\n".encode("ascii")

    def test_connect_uses_remote_socks_dns_and_relays_through_tor(self):
        with socket.create_connection(self.proxy.address, timeout=3) as client:
            client.settimeout(3)
            client.sendall(
                b"CONNECT download.example:443 HTTP/1.1\r\n"
                b"Host: download.example:443\r\n"
                + self.proxy_authorization
                + b"\r\n"
            )
            response = client.recv(1024)
            self.assertIn(b"200 Connection Established", response)
            client.sendall(b"hello")
            self.assertEqual(client.recv(1024), b"echo:hello")
        self.assertIn(("download.example", 443), self.socks.destinations)

    def test_connect_tunnels_nonstandard_http_ftp_and_sftp_ports(self):
        for port in (21, 22, 8080, 8443):
            with self.subTest(port=port):
                with socket.create_connection(self.proxy.address, timeout=3) as client:
                    client.settimeout(3)
                    client.sendall(
                        f"CONNECT download.example:{port} HTTP/1.1\r\n"
                        f"Host: download.example:{port}\r\n".encode("ascii")
                        + self.proxy_authorization
                        + b"\r\n"
                    )
                    response = client.recv(1024)
                    self.assertIn(b"200 Connection Established", response)
                    client.sendall(b"hello")
                    self.assertEqual(client.recv(1024), b"echo:hello")
        self.assertTrue({
            ("download.example", port) for port in (21, 22, 8080, 8443)
        }.issubset(set(self.socks.destinations)))

    def test_http_forward_request_strips_proxy_credentials_and_uses_tor(self):
        with socket.create_connection(self.proxy.address, timeout=3) as client:
            client.settimeout(3)
            client.sendall(
                b"GET http://download.example/file.bin?sig=private HTTP/1.1\r\n"
                b"Host: download.example\r\n"
                + self.proxy_authorization
                + b"\r\n"
            )
            response = bytearray()
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
        self.assertIn(b"200 OK", response)
        self.assertIn(b"hello", response)
        self.assertIn(("download.example", 80), self.socks.destinations)
        forwarded = self.target.requests[0]
        self.assertTrue(forwarded.startswith(b"GET /file.bin?sig=private HTTP/1.1"))
        self.assertNotIn(b"Proxy-Authorization", forwarded)
        self.assertNotIn(b"test-proxy-token", forwarded)

    def test_http_forward_accepts_nonstandard_port(self):
        with socket.create_connection(self.proxy.address, timeout=3) as client:
            client.settimeout(3)
            client.sendall(
                b"GET http://download.example:8080/file.bin HTTP/1.1\r\n"
                b"Host: download.example:8080\r\n"
                + self.proxy_authorization
                + b"\r\n"
            )
            response = bytearray()
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
        self.assertIn(b"200 OK", response)
        self.assertIn(("download.example", 8080), self.socks.destinations)

    def test_missing_auth_and_private_destination_are_rejected_before_tor(self):
        with socket.create_connection(self.proxy.address, timeout=3) as client:
            client.settimeout(3)
            client.sendall(
                b"CONNECT download.example:443 HTTP/1.1\r\n"
                b"Host: download.example:443\r\n\r\n"
            )
            self.assertIn(b"407 Proxy Authentication Required", client.recv(1024))
        with socket.create_connection(self.proxy.address, timeout=3) as client:
            client.settimeout(3)
            client.sendall(
                b"CONNECT 127.0.0.1:443 HTTP/1.1\r\n"
                b"Host: 127.0.0.1:443\r\n"
                + self.proxy_authorization
                + b"\r\n"
            )
            self.assertIn(b"403 Forbidden", client.recv(1024))
        self.assertEqual(self.socks.destinations, [])


if __name__ == "__main__":
    unittest.main()
