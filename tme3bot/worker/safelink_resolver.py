"""HTTP-only resolver for supported multi-step Safelink pages.

The target pages expose their Livewire 2 component state in the initial HTML.
This module carries the session cookies and signed component state through the
same Livewire HTTP endpoint without starting a browser. It never opens or
downloads the final destination.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import socket
import time
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import httpx

from tme3bot.safelink import normalize_shortlink_url


DEFAULT_TIMEOUT_SECONDS = 480
DEFAULT_MAX_RETRIES = 4
MAX_REDIRECTS = 12
MAX_PAGE_BYTES = 1_000_000
MAX_LIVEWIRE_BYTES = 2_000_000
REQUEST_TIMEOUT_SECONDS = 20
RETRYABLE_GET_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
_GATE_HOST_SUFFIXES = (
    "pndk.to",
    "go.fakta.id",
    "datapendidikan.com",
    "urlwebsite.com",
    "adtival.network",
)
_CAPTCHA_TEXT = re.compile(
    r"(?:captcha|recaptcha|hcaptcha|turnstile|verify\s+you\s+are\s+human|"
    r"verifikasi\s+(?:bahwa\s+)?anda manusia|i\s+am\s+not\s+a\s+robot)",
    re.IGNORECASE,
)
_LIVEWIRE_TOKEN = re.compile(r"window\.livewire_token\s*=\s*['\"]([^'\"]+)['\"]")
_STEP_TEXT = re.compile(r"\bStep\s*(\d+)\s*/\s*\d+", re.IGNORECASE)
_COMPONENT_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class SafelinkResolveError(RuntimeError):
    """A safe, user-facing resolver failure with no untrusted URL attached."""


class SafelinkCancelled(SafelinkResolveError):
    """Raised when the persisted job receives a cancellation request."""


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.initial_data: str | None = None
        self.text: list[str] = []
        self._skip_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        initial_data = attributes.get("wire:initial-data")
        if self.initial_data is None and initial_data:
            self.initial_data = initial_data
        if tag in {"script", "style"}:
            self._skip_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._skip_tags and self._skip_tags[-1] == tag:
            self._skip_tags.pop()

    def handle_data(self, data: str) -> None:
        if not self._skip_tags:
            self.text.append(data)


def _host_addresses(host: str, port: int, resolver=socket.getaddrinfo) -> list[str]:
    try:
        direct = ipaddress.ip_address(host)
    except ValueError:
        try:
            records = resolver(host, port, type=socket.SOCK_STREAM)
        except (OSError, socket.gaierror):
            raise SafelinkResolveError("Domain shortlink tidak dapat dijangkau.") from None
        addresses = list(dict.fromkeys(str(record[4][0]).split("%", 1)[0] for record in records))
        if not addresses:
            raise SafelinkResolveError("Domain shortlink tidak memiliki alamat publik.")
        return addresses
    return [str(direct)]


def assert_public_http_url(url: str, *, resolver=socket.getaddrinfo) -> str:
    """Return a URL only when its host resolves exclusively to public IPs."""
    try:
        parsed = urlsplit(str(url))
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        explicit_port = parsed.port
        port = explicit_port if explicit_port is not None else (443 if scheme == "https" else 80)
    except (UnicodeError, ValueError):
        raise SafelinkResolveError("URL halaman atau tujuan tidak valid.") from None
    if scheme not in {"http", "https"} or not host:
        raise SafelinkResolveError("Navigasi hanya diizinkan ke alamat HTTP atau HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise SafelinkResolveError("Navigasi ke URL dengan kredensial ditolak.")
    if not 1 <= port <= 65535:
        raise SafelinkResolveError("Port tujuan tidak valid.")
    for address in _host_addresses(host, port, resolver):
        try:
            candidate = ipaddress.ip_address(address)
        except ValueError:
            raise SafelinkResolveError("Domain mengembalikan alamat yang tidak valid.") from None
        if not candidate.is_global:
            raise SafelinkResolveError("Navigasi ke jaringan privat atau alamat khusus ditolak.")
    return str(url)


def decode_safelinkearn_url(url: str, *, resolver=socket.getaddrinfo) -> str | None:
    """Decode a public HTTP(S) destination encoded in SafelinkEarn query data."""
    try:
        query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return None
    for name in ("shortid", "url", "u", "link", "target"):
        values = query.get(name)
        if not values or not values[0]:
            continue
        encoded = values[0].replace(" ", "+").strip()
        encoded += "=" * (-len(encoded) % 4)
        try:
            decoded = base64.urlsafe_b64decode(encoded).decode("utf-8").strip()
        except (ValueError, UnicodeDecodeError):
            continue
        try:
            return assert_public_http_url(decoded, resolver=resolver)
        except SafelinkResolveError:
            continue
    return None


def _url_host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
    except (UnicodeError, ValueError):
        raise SafelinkResolveError("URL halaman atau tujuan tidak valid.") from None


def _is_safelinkearn(host: str) -> bool:
    return host == "safelinkearn.com" or host.endswith(".safelinkearn.com")


def _is_gate_host(host: str) -> bool:
    return any(host == suffix or host.endswith("." + suffix) for suffix in _GATE_HOST_SUFFIXES)


def _request_timeout(deadline: float, monotonic: Callable[[], float]) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise SafelinkResolveError("Batas waktu resolver 480 detik tercapai.")
    return min(REQUEST_TIMEOUT_SECONDS, remaining)


def _check_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise SafelinkCancelled("Job resolver dibatalkan.")


def _read_limited(
    response: httpx.Response,
    *,
    limit: int,
    is_cancelled: Callable[[], bool] | None,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes(chunk_size=64 * 1024):
        _check_cancelled(is_cancelled)
        total += len(chunk)
        if total > limit:
            raise SafelinkResolveError("Respons halaman melebihi batas ukuran resolver.")
        chunks.append(chunk)
    return b"".join(chunks)


def _sleep_retry(
    attempt: int,
    *,
    deadline: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    is_cancelled: Callable[[], bool] | None,
) -> None:
    _check_cancelled(is_cancelled)
    delay = min(0.5 * (2**attempt), 2.0, max(0.0, deadline - monotonic()))
    if delay > 0:
        sleep(delay)
    _check_cancelled(is_cancelled)


def _get_gate_response(
    client: httpx.Client,
    url: str,
    *,
    deadline: float,
    retries: int,
    resolver,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    is_cancelled: Callable[[], bool] | None,
    progress: Callable[[str, str], None],
) -> tuple[int, dict[str, str], bytes]:
    assert_public_http_url(url, resolver=resolver)
    host = _url_host(url)
    if not _is_gate_host(host):
        raise SafelinkResolveError("Domain gate berubah dan belum didukung resolver.")

    for attempt in range(retries + 1):
        _check_cancelled(is_cancelled)
        timeout = _request_timeout(deadline, monotonic)
        retry_status: int | None = None
        try:
            with client.stream("GET", url, timeout=timeout) as response:
                headers = dict(response.headers)
                status = response.status_code
                if status in RETRYABLE_GET_STATUSES:
                    retry_status = status
                elif 300 <= status < 400:
                    return status, headers, b""
                elif status != 200:
                    raise SafelinkResolveError(f"Halaman gate menolak request (HTTP {status}).")
                else:
                    content_type = response.headers.get("content-type", "").lower()
                    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                        return status, headers, b""
                    body = _read_limited(response, limit=MAX_PAGE_BYTES, is_cancelled=is_cancelled)
                    return status, headers, body
        except SafelinkResolveError:
            raise
        except httpx.TransportError:
            if attempt >= retries:
                raise SafelinkResolveError("Halaman gate tidak dapat dijangkau setelah dicoba ulang.") from None
            retry_status = None

        if attempt >= retries:
            if retry_status is not None:
                raise SafelinkResolveError(
                    f"Halaman gate masih membatasi request (HTTP {retry_status})."
                )
            raise SafelinkResolveError("Halaman gate tidak dapat dijangkau setelah dicoba ulang.")
        progress("retrying", f"Mencoba ulang koneksi gate ({attempt + 1}/{retries}).")
        _sleep_retry(
            attempt,
            deadline=deadline,
            monotonic=monotonic,
            sleep=sleep,
            is_cancelled=is_cancelled,
        )

    raise SafelinkResolveError("Halaman gate tidak dapat dijangkau.")


def _parse_livewire_page(html_text: str) -> dict[str, Any]:
    parser = _PageParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:
        raise SafelinkResolveError("HTML halaman gate tidak dapat dibaca.") from None

    if not parser.initial_data:
        raise SafelinkResolveError("Halaman gate tidak memiliki state Livewire yang didukung.")
    try:
        # HTMLParser already decodes attribute entities. A second unescape could
        # corrupt literal entity text inside Livewire's JSON payload.
        initial = json.loads(parser.initial_data)
    except (TypeError, ValueError):
        raise SafelinkResolveError("State Livewire halaman tidak valid.") from None
    if not isinstance(initial, dict):
        raise SafelinkResolveError("State Livewire halaman tidak valid.")

    fingerprint = initial.get("fingerprint")
    server_memo = initial.get("serverMemo")
    if not isinstance(fingerprint, dict) or not isinstance(server_memo, dict):
        raise SafelinkResolveError("State Livewire halaman tidak lengkap.")
    component_name = fingerprint.get("name")
    component_id = fingerprint.get("id")
    if not isinstance(component_name, str) or not _COMPONENT_NAME.fullmatch(component_name):
        raise SafelinkResolveError("Nama komponen Livewire tidak didukung.")
    if not isinstance(component_id, str) or not component_id or len(component_id) > 128:
        raise SafelinkResolveError("Identitas komponen Livewire tidak valid.")

    state = server_memo.get("data")
    if not isinstance(state, dict):
        raise SafelinkResolveError("State komponen Livewire tidak lengkap.")
    visible_text = " ".join(parser.text)
    step_match = _STEP_TEXT.search(visible_text)
    if not step_match:
        raise SafelinkResolveError("Nomor langkah shortlink tidak ditemukan.")
    token_match = _LIVEWIRE_TOKEN.search(html_text)
    if not token_match:
        raise SafelinkResolveError("Token sesi halaman tidak ditemukan.")

    captcha_flag = state.get("captcha")
    if _CAPTCHA_TEXT.search(visible_text) or (
        state.get("hasCaptcha") is True and captcha_flag is not True
    ):
        raise SafelinkResolveError(
            "Shortlink meminta verifikasi CAPTCHA. Selesaikan manual lalu kirim ulang job."
        )

    return {
        "fingerprint": fingerprint,
        "serverMemo": server_memo,
        "component_id": component_id,
        "component_name": component_name,
        "step": int(step_match.group(1)),
        "phase": state.get("phase"),
        "token": token_match.group(1),
    }


def _decode_target(url: str, *, resolver) -> str:
    destination = decode_safelinkearn_url(url, resolver=resolver)
    if not destination:
        raise SafelinkResolveError("Halaman SafelinkEarn tercapai, tetapi URL tujuan tidak dapat dibaca.")
    return destination


def _load_page_or_destination(
    client: httpx.Client,
    url: str,
    *,
    allow_external_destination: bool,
    deadline: float,
    retries: int,
    resolver,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    is_cancelled: Callable[[], bool] | None,
    progress: Callable[[str, str], None],
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        _check_cancelled(is_cancelled)
        assert_public_http_url(current_url, resolver=resolver)
        host = _url_host(current_url)
        if _is_safelinkearn(host):
            return None, None, _decode_target(current_url, resolver=resolver)
        if not _is_gate_host(host):
            if allow_external_destination:
                return None, None, assert_public_http_url(current_url, resolver=resolver)
            raise SafelinkResolveError("Shortlink mengarah ke domain gate yang belum didukung.")

        status, headers, body = _get_gate_response(
            client,
            current_url,
            deadline=deadline,
            retries=retries,
            resolver=resolver,
            monotonic=monotonic,
            sleep=sleep,
            is_cancelled=is_cancelled,
            progress=progress,
        )
        if 300 <= status < 400:
            location = headers.get("location")
            if not location:
                raise SafelinkResolveError("Halaman gate mengirim redirect tanpa tujuan.")
            next_url = assert_public_http_url(urljoin(current_url, location), resolver=resolver)
            next_host = _url_host(next_url)
            if _is_safelinkearn(next_host):
                return None, None, _decode_target(next_url, resolver=resolver)
            if _is_gate_host(next_host):
                current_url = next_url
                progress("resolving", "Mengikuti redirect halaman gate.")
                continue
            if allow_external_destination:
                return None, None, next_url
            raise SafelinkResolveError("Redirect gate mengarah ke domain yang belum didukung.")

        content_type = headers.get("content-type", "").lower()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            if allow_external_destination:
                return None, None, assert_public_http_url(current_url, resolver=resolver)
            raise SafelinkResolveError("Halaman gate tidak mengembalikan HTML.")
        try:
            html_text = body.decode("utf-8", "replace")
        except Exception:
            raise SafelinkResolveError("HTML halaman gate tidak dapat dibaca.") from None
        return current_url, _parse_livewire_page(html_text), None

    raise SafelinkResolveError("Jumlah redirect halaman gate melebihi batas.")


def _set_link_from_response(data: Any, *, resolver) -> str:
    if not isinstance(data, dict):
        raise SafelinkResolveError("Respons Livewire tidak valid.")
    effects = data.get("effects")
    emits = effects.get("emits") if isinstance(effects, dict) else None
    if not isinstance(emits, list):
        raise SafelinkResolveError("Respons Livewire tidak membawa event setLink.")
    for emitted in emits:
        if not isinstance(emitted, dict) or emitted.get("event") != "setLink":
            continue
        params = emitted.get("params")
        if not isinstance(params, list) or not params or not isinstance(params[0], str):
            continue
        target = params[0]
        if len(target) > 4096:
            raise SafelinkResolveError("Link hasil Livewire terlalu panjang.")
        return assert_public_http_url(target, resolver=resolver)
    raise SafelinkResolveError("Respons Livewire tidak membawa event setLink.")


def _default_http_client_factory() -> httpx.Client:
    return httpx.Client(
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": _USER_AGENT, "Accept": "text/html, application/xhtml+xml, application/json, */*"},
        timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS),
    )


def resolve_shortlink(
    input_url: str,
    *,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    resolver=socket.getaddrinfo,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    http_client_factory: Callable[[], httpx.Client] | None = None,
) -> dict[str, str]:
    """Resolve a supported shortlink through Livewire HTTP requests only."""

    def progress(phase: str, message: str) -> None:
        if on_progress is not None:
            on_progress({"phase": phase, "message": message})

    source = normalize_shortlink_url(input_url)
    assert_public_http_url(source, resolver=resolver)
    deadline = monotonic() + max(0, int(timeout_seconds))
    retries = max(0, min(int(max_retries), DEFAULT_MAX_RETRIES))
    client_factory = http_client_factory or _default_http_client_factory
    progress("starting", "Menyiapkan sesi HTTP resolver.")
    visited: set[tuple[str, int, str, str]] = set()
    current_url = source
    allow_external_destination = False

    try:
        with client_factory() as client:
            for _ in range(32):
                _check_cancelled(is_cancelled)
                page_url, page, destination = _load_page_or_destination(
                    client,
                    current_url,
                    allow_external_destination=allow_external_destination,
                    deadline=deadline,
                    retries=retries,
                    resolver=resolver,
                    monotonic=monotonic,
                    sleep=sleep,
                    is_cancelled=is_cancelled,
                    progress=progress,
                )
                if destination:
                    progress("completed", "URL tujuan berhasil ditemukan.")
                    return {"destination_url": destination}
                if page_url is None or page is None:
                    raise SafelinkResolveError("State halaman gate tidak tersedia.")

                step = int(page["step"])
                phase = page.get("phase")
                event = "getData" if step >= 5 and str(phase) == "5" else "changePhase"
                signature = (page_url, step, str(phase), event)
                if signature in visited:
                    raise SafelinkResolveError("Tahap Livewire berulang; resolver menghentikan job.")
                visited.add(signature)
                progress("resolving", f"Membaca langkah {step}/5.")

                component_name = str(page["component_name"])
                endpoint = urljoin(page_url, f"/livewire/message/{quote(component_name, safe='')}")
                assert_public_http_url(endpoint, resolver=resolver)
                page_origin = urlsplit(page_url)
                endpoint_origin = urlsplit(endpoint)
                if (
                    endpoint_origin.scheme != page_origin.scheme
                    or endpoint_origin.netloc.lower() != page_origin.netloc.lower()
                ):
                    raise SafelinkResolveError("Endpoint Livewire keluar dari origin halaman.")

                payload = {
                    "fingerprint": page["fingerprint"],
                    "serverMemo": page["serverMemo"],
                    "updates": [
                        {
                            "type": "fireEvent",
                            "payload": {
                                "id": page["component_id"],
                                "event": event,
                                "params": [],
                            },
                        }
                    ],
                }
                headers = {
                    "Origin": f"{page_origin.scheme}://{page_origin.netloc}",
                    "Referer": page_url,
                    "X-Livewire": "true",
                    "X-CSRF-TOKEN": str(page["token"]),
                    "Content-Type": "application/json",
                }
                _check_cancelled(is_cancelled)
                timeout = _request_timeout(deadline, monotonic)
                try:
                    with client.stream(
                        "POST",
                        endpoint,
                        json=payload,
                        headers=headers,
                        timeout=timeout,
                    ) as response:
                        if response.status_code != 200:
                            if response.status_code == 419:
                                raise SafelinkResolveError("Sesi Livewire kedaluwarsa; kirim ulang job.")
                            raise SafelinkResolveError(
                                f"Request Livewire gagal (HTTP {response.status_code})."
                            )
                        body = _read_limited(
                            response,
                            limit=MAX_LIVEWIRE_BYTES,
                            is_cancelled=is_cancelled,
                        )
                except SafelinkResolveError:
                    raise
                except httpx.TransportError:
                    # A phase event may already have been applied by the server.
                    # Never replay an ambiguous POST automatically.
                    raise SafelinkResolveError(
                        "Respons Livewire tidak dapat dipastikan; job dihentikan agar fase tidak terkirim dua kali."
                    ) from None

                try:
                    response_data = json.loads(body)
                except (TypeError, ValueError):
                    raise SafelinkResolveError("Respons Livewire bukan JSON yang valid.") from None
                next_url = _set_link_from_response(response_data, resolver=resolver)
                progress("resolving", f"Livewire {event} dijalankan pada langkah {step}.")
                current_url = next_url
                allow_external_destination = event == "getData"

            raise SafelinkResolveError("Batas tahap HTTP resolver tercapai.")
    except (SafelinkCancelled, SafelinkResolveError):
        raise
    except Exception:
        # HTTP exception details can contain the complete shortlink and query.
        raise SafelinkResolveError("Resolver mengalami kendala saat memproses halaman.") from None
