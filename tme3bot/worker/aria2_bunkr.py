"""Bunkr link resolution and per-task Aria2 routing.

The signed download URLs are deliberately kept inside the worker.  The browser
only receives stable item metadata and task identifiers.
"""

from __future__ import annotations

import html
import logging
import math
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from tme3bot.database_paths import ensure_private_directory


_BUNKR_HOST = re.compile(r"^(?:[a-z0-9-]+\.)*bunkrr?\.[a-z]{2,}(?:\.[a-z]{2,})?$", re.I)
_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_GID = re.compile(r"^[0-9a-fA-F]{16}$")
_JS_VAR = re.compile(r"var\s+(\w+)\s*=\s*(\".*?\"|'.*?'|[^;]+);", re.S)
_JS_UNICODE = re.compile(r"\\u([0-9a-fA-F]{4})")
_HTTP_ERROR = re.compile(r"(?:HTTP\s*)?(?:status\s*)?(401|403)\b", re.I)
_URI = re.compile(r"(?:https?|ftp|sftp)://[^\s\"'<>]+", re.I)
_DOWNLOAD_API = "https://dl.bunkr.cr/api/_001_v2"
_SIGN_API = "https://glb-apisign.cdn.cr/sign"


def redact_sensitive_urls_in_text(value: object) -> str:
    """Hide URL query strings and userinfo before text reaches operator logs."""
    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        suffix = ""
        while raw and raw[-1] in ".,;)]}":
            suffix = raw[-1] + suffix
            raw = raw[:-1]
        try:
            parsed = urlsplit(raw)
            host = parsed.hostname or ""
            port = parsed.port
        except ValueError:
            return "[URL disembunyikan]" + suffix
        if not host:
            return "[URL disembunyikan]" + suffix
        safe_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        safe_netloc = f"{safe_host}:{port}" if port is not None else safe_host
        query = "[query disembunyikan]" if parsed.query else ""
        fragment = "[fragment disembunyikan]" if parsed.fragment else ""
        if not parsed.query and not parsed.fragment and not parsed.username and not parsed.password:
            return raw + suffix
        safe_url = urlunsplit((parsed.scheme, safe_netloc, parsed.path, query, fragment))
        return safe_url + suffix

    return _URI.sub(replace, str(value or ""))


class _HttpxUrlRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive_urls_in_text(record.getMessage())
        record.args = ()
        return True


_HTTPX_URL_REDACTION_FILTER = _HttpxUrlRedactionFilter()
_HTTPX_LOGGER = logging.getLogger("httpx")
if not any(isinstance(item, _HttpxUrlRedactionFilter) for item in _HTTPX_LOGGER.filters):
    _HTTPX_LOGGER.addFilter(_HTTPX_URL_REDACTION_FILTER)


class BunkrLinkError(ValueError):
    """Safe, displayable Bunkr resolution failure."""


@dataclass(frozen=True)
class BunkrFile:
    item_id: str
    source_url: str
    file_name: str
    thumbnail_url: str = ""
    direct_url: str = ""


@dataclass(frozen=True)
class RemoteFileMetadata:
    size: int | None
    range_supported: bool
    etag: str = ""
    last_modified: str = ""


class BunkrResolver:
    """Resolver using direct, non-proxied requests to Bunkr pages and APIs."""

    def __init__(self, *, client_factory: Callable[..., Any] = httpx.Client):
        self.client_factory = client_factory

    @staticmethod
    def normalize_source(value: object) -> str:
        raw = str(value or "").strip()
        if len(raw) > 4096:
            raise BunkrLinkError("URL terlalu panjang.")
        try:
            parsed = urlsplit(raw)
            host = (parsed.hostname or "").lower().rstrip(".")
            port = parsed.port
        except ValueError as exc:
            raise BunkrLinkError("URL Bunkr tidak valid.") from exc
        if (
            parsed.scheme.lower() != "https"
            or not host
            or not _BUNKR_HOST.fullmatch(host)
            or parsed.username
            or parsed.password
            or port not in (None, 443)
        ):
            raise BunkrLinkError("Gunakan URL HTTPS file atau album Bunkr yang valid.")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2 or parts[-2].lower() not in {"a", "f", "v"}:
            raise BunkrLinkError("URL harus mengarah ke file atau album Bunkr.")
        if not _ID.fullmatch(parts[-1]):
            raise BunkrLinkError("Identitas file atau album Bunkr tidak valid.")
        # Query strings can contain temporary credentials; neither persist nor
        # return them. Bunkr page identity is carried by its path.
        return urlunsplit(("https", parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))

    def preview(self, source: object) -> dict[str, Any]:
        clean = self.normalize_source(source)
        kind, item_id = self._source_parts(clean)
        if kind == "a":
            album_name, files = self._album(clean)
            return {
                "kind": "album",
                "title": album_name,
                "files": [self._public_file(item) for item in files],
            }
        item = self._file_page(clean, item_id)
        return {"kind": "file", "title": item.file_name, "files": [self._public_file(item)]}

    def resolve_file(self, source: object, item_id: str | None = None) -> BunkrFile:
        clean = self.normalize_source(source)
        kind, source_id = self._source_parts(clean)
        if kind == "a":
            _, files = self._album(clean)
            match = next((item for item in files if item.item_id == item_id), None)
            if match is None:
                raise BunkrLinkError("Item tidak ditemukan pada album.")
            return self._file_page(match.source_url, match.item_id)
        if item_id and item_id != source_id:
            raise BunkrLinkError("Identitas file Bunkr tidak sesuai dengan sumber.")
        return self._file_page(clean, source_id)

    @staticmethod
    def _public_file(item: BunkrFile) -> dict[str, str]:
        return {
            "item_id": item.item_id,
            "source_url": item.source_url,
            "file_name": item.file_name,
            "thumbnail_url": item.thumbnail_url,
        }

    @staticmethod
    def _source_parts(source: str) -> tuple[str, str]:
        parts = [part for part in urlsplit(source).path.split("/") if part]
        return parts[-2].lower(), parts[-1]

    @staticmethod
    def _safe_name(value: str, fallback: str) -> str:
        name = html.unescape(" ".join(str(value or "").split())).strip()
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
        if name in {"", ".", ".."}:
            name = fallback
        return name[:240]

    def _client(self, *, timeout: float = 20.0):
        return self.client_factory(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            },
        )

    def _get_page(self, client: Any, url: str) -> tuple[str, BeautifulSoup]:
        current = url
        for _ in range(6):
            try:
                response = client.get(current)
            except Exception as exc:
                raise BunkrLinkError("Halaman Bunkr tidak dapat dimuat.") from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location", "")
                target = urljoin(current, location)
                clean = self.normalize_source(target)
                current = clean
                continue
            if response.status_code in {401, 403}:
                raise BunkrLinkError("Bunkr menolak akses ke halaman.")
            if response.status_code >= 400:
                raise BunkrLinkError(f"Halaman Bunkr gagal dimuat (HTTP {response.status_code}).")
            return current, BeautifulSoup(response.content, "html.parser")
        raise BunkrLinkError("Pengalihan URL Bunkr terlalu banyak.")

    def _album(self, source: str) -> tuple[str, list[BunkrFile]]:
        with self._client() as client:
            final_url, soup = self._get_page(client, source)
            album_name = self._album_name(soup, self._source_parts(final_url)[1])
            page_count = 1
            pagination = soup.find("nav", class_="pagination")
            if pagination:
                page_ids = [int(value) for value in re.findall(r"\d+", pagination.get_text(" "))]
                page_count = max(page_ids or [1])
            if page_count > 1000:
                raise BunkrLinkError("Album memiliki jumlah halaman di luar batas yang didukung.")
            pages = [soup]
            for page in range(2, page_count + 1):
                page_url = f"{source}?page={page}"
                _, page_soup = self._get_page(client, page_url)
                pages.append(page_soup)
            items: dict[str, BunkrFile] = {}
            for page_soup in pages:
                for anchor in page_soup.find_all("a", href=True):
                    item_url = urljoin(source, str(anchor.get("href") or ""))
                    try:
                        normalized = self.normalize_source(item_url)
                    except BunkrLinkError:
                        continue
                    kind, item_id = self._source_parts(normalized)
                    if kind not in {"f", "v"}:
                        continue
                    card = anchor
                    for _ in range(4):
                        parent = getattr(card, "parent", None)
                        if parent is None:
                            break
                        card = parent
                        if card.find("img"):
                            break
                    image = card.find("img") if hasattr(card, "find") else None
                    thumbnail = ""
                    if image:
                        thumbnail = str(
                            image.get("data-src") or image.get("data-original") or image.get("src") or ""
                        ).strip()
                        if thumbnail.startswith("//"):
                            thumbnail = "https:" + thumbnail
                        if thumbnail.startswith("/"):
                            thumbnail = urljoin(normalized, thumbnail)
                        if not thumbnail.startswith("https://"):
                            thumbnail = ""
                    label = anchor.get_text(" ", strip=True)
                    if not label and image:
                        label = str(image.get("alt") or "")
                    file_name = self._safe_name(label, item_id)
                    items.setdefault(
                        item_id,
                        BunkrFile(item_id, normalized, file_name, thumbnail),
                    )
            if not items:
                raise BunkrLinkError("Album tidak berisi item file yang dapat dibaca.")
            return album_name, list(items.values())

    @classmethod
    def _album_name(cls, soup: BeautifulSoup, fallback: str) -> str:
        container = soup.find("div", class_="text-subs font-semibold flex text-base sm:text-lg")
        heading = container.find("h1") if container else soup.find("h1")
        if heading is None:
            title = soup.find("title")
            value = title.get_text(" ", strip=True) if title else fallback
        else:
            value = heading.get_text(" ", strip=True)
        return cls._safe_name(value, fallback)

    def _file_page(self, source: str, item_id: str) -> BunkrFile:
        with self._client() as client:
            final_url, soup = self._get_page(client, source)
            heading = soup.find("h1")
            file_name = self._safe_name(
                heading.get_text(" ", strip=True) if heading else "",
                item_id,
            )
            thumbnail_tag = soup.find("meta", attrs={"property": "og:image"})
            thumbnail = str(thumbnail_tag.get("content") or "") if thumbnail_tag else ""
            if thumbnail and not thumbnail.startswith("https://"):
                thumbnail = urljoin(final_url, thumbnail)
            page_vars: dict[str, str] = {}
            file_identifier = ""
            for script in soup.find_all("script"):
                script_text = script.string or script.get_text()
                if "var jsCDN" in script_text:
                    for key, value in _JS_VAR.findall(script_text):
                        value = _JS_UNICODE.sub(lambda match: chr(int(match.group(1), 16)), value)
                        page_vars[key] = value.strip().strip("'\"").replace(r"\/", "/")
                if not file_identifier:
                    file_identifier = str(script.get("data-file-id") or "")
            cdn_url = page_vars.get("jsCDN", "")
            unsigned_url = ""
            if not cdn_url and file_identifier:
                data = self._json_request(
                    client,
                    "POST",
                    _DOWNLOAD_API,
                    json={"id": file_identifier},
                    headers={"Accept-Encoding": "gzip, deflate"},
                )
                base = str(data.get("mediafiles") or "")
                path = str(data.get("path") or "")
                if base and path:
                    parsed = urlsplit(base)
                    unsigned_url = urlunsplit((parsed.scheme or "https", parsed.netloc, path, "", ""))
            if not cdn_url and not unsigned_url:
                raise BunkrLinkError("Metadata unduhan file Bunkr tidak tersedia.")
            base_url = cdn_url or unsigned_url
            media_slug = Path(urlsplit(unsigned_url or final_url).path).name
            media_path = urlsplit(cdn_url).path if cdn_url else f"/storage/media/{media_slug}"
            signing = self._json_request(client, "GET", _SIGN_API, params={"path": media_path})
            token = str(signing.get("token") or "")
            expires = str(signing.get("ex") or "")
            direct = base_url
            if token and expires:
                direct += f"?token={token}&ex={expires}"
            elif cdn_url:
                direct = cdn_url
            else:
                raise BunkrLinkError("Bunkr tidak memberikan URL unduhan saat ini.")
            return BunkrFile(item_id, self.normalize_source(final_url), file_name, thumbnail, direct)

    @staticmethod
    def _json_request(client: Any, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            value = response.json()
        except Exception as exc:
            raise BunkrLinkError("Bunkr gagal menyediakan metadata unduhan.") from exc
        if not isinstance(value, dict):
            raise BunkrLinkError("Format metadata unduhan Bunkr tidak dikenal.")
        return value

    def probe_metadata(self, direct_url: str) -> RemoteFileMetadata:
        """Read size, range support, and stable validators without downloading the body."""
        try:
            with self.client_factory(
                timeout=12,
                follow_redirects=True,
                trust_env=False,
                headers={"Range": "bytes=0-0", "Accept-Encoding": "identity"},
            ) as client:
                with client.stream("GET", direct_url) as response:
                    content_range = response.headers.get("content-range", "")
                    total_match = re.search(r"/([0-9]+)$", content_range)
                    size = int(total_match.group(1)) if total_match else None
                    if size is None:
                        raw_size = response.headers.get("content-length")
                        size = int(raw_size) if raw_size and raw_size.isdigit() else None
                    supports_ranges = response.status_code == 206 or response.headers.get(
                        "accept-ranges", ""
                    ).lower() == "bytes"
                    etag = str(response.headers.get("etag") or "").strip()[:512]
                    last_modified = str(response.headers.get("last-modified") or "").strip()[:512]
                    # Closing a streaming response after headers avoids fetching a
                    # full object from servers that ignore Range.
                    return RemoteFileMetadata(size, supports_ranges, etag, last_modified)
        except Exception:
            return RemoteFileMetadata(None, False)

    def probe(self, direct_url: str) -> tuple[int | None, bool]:
        """Return the legacy size/range pair for callers that do not need validators."""
        metadata = self.probe_metadata(direct_url)
        return metadata.size, metadata.range_supported


class BunkrTaskStore:
    """Private SQLite metadata for tasks managed through the Links integration."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.RLock()
        ensure_private_directory(self.path.parent)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS aria2_link_tasks (
                    task_key TEXT PRIMARY KEY,
                    gid TEXT UNIQUE,
                    kind TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    album_name TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    route TEXT NOT NULL,
                    expected_size INTEGER,
                    range_supported INTEGER NOT NULL DEFAULT 0,
                    source_scheme TEXT NOT NULL DEFAULT 'https',
                    source_port INTEGER NOT NULL DEFAULT 443,
                    expected_etag TEXT NOT NULL DEFAULT '',
                    expected_last_modified TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    reason_code TEXT NOT NULL DEFAULT '',
                    refresh_attempts INTEGER NOT NULL DEFAULT 0,
                    retry_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_aria2_link_destination ON aria2_link_tasks(destination)"
            )
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(aria2_link_tasks)")
            }
            if "source_scheme" not in columns:
                connection.execute(
                    "ALTER TABLE aria2_link_tasks ADD COLUMN source_scheme TEXT NOT NULL DEFAULT 'https'"
                )
            if "source_port" not in columns:
                connection.execute(
                    "ALTER TABLE aria2_link_tasks ADD COLUMN source_port INTEGER NOT NULL DEFAULT 443"
                )
            if "expected_etag" not in columns:
                connection.execute(
                    "ALTER TABLE aria2_link_tasks ADD COLUMN expected_etag TEXT NOT NULL DEFAULT ''"
                )
            if "expected_last_modified" not in columns:
                connection.execute(
                    "ALTER TABLE aria2_link_tasks ADD COLUMN expected_last_modified TEXT NOT NULL DEFAULT ''"
                )
        self.path.chmod(0o600)

    def reserve(self, row: dict[str, Any], *, destination_exists: bool) -> str:
        task_key = uuid.uuid4().hex
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT task_key, status FROM aria2_link_tasks WHERE destination=?",
                (row["destination"],),
            ).fetchone()
            if destination_exists or (
                current and current["status"] in {"resolving", "queued", "active", "paused", "refreshing", "held"}
            ):
                connection.rollback()
                raise FileExistsError("FILE_CONFLICT")
            if current:
                connection.execute(
                    "DELETE FROM aria2_link_tasks WHERE task_key=?", (current["task_key"],)
                )
            connection.execute(
                """INSERT INTO aria2_link_tasks
                (task_key, kind, source_url, item_id, album_name, file_name,
                 destination, route, expected_size, range_supported, source_scheme,
                 source_port, expected_etag, expected_last_modified, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'resolving', ?)""",
                (
                    task_key, row["kind"], row["source_url"], row["item_id"],
                    row["album_name"], row["file_name"], row["destination"],
                    row["route"], row.get("expected_size"),
                    1 if row.get("range_supported") else 0,
                    row.get("source_scheme", "https"), row.get("source_port", 443),
                    row.get("expected_etag", ""), row.get("expected_last_modified", ""),
                    time.time(),
                ),
            )
            return task_key

    def set_gid(
        self,
        task_key: str,
        gid: str,
        *,
        status: str = "queued",
        reason_code: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE aria2_link_tasks SET gid=?, status=?, reason_code=?, updated_at=? WHERE task_key=?",
                (gid, status, reason_code, time.time(), task_key),
            )

    def update(self, gid: str, **values: Any) -> None:
        allowed = {
            "route", "expected_size", "range_supported", "status", "reason_code",
            "expected_etag", "expected_last_modified", "refresh_attempts", "retry_at", "updated_at",
        }
        patch = {key: value for key, value in values.items() if key in allowed}
        if not patch:
            return
        patch.setdefault("updated_at", time.time())
        assignments = ", ".join(f"{key}=?" for key in patch)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE aria2_link_tasks SET {assignments} WHERE gid=?",
                (*patch.values(), gid),
            )

    def get(self, gid: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM aria2_link_tasks WHERE gid=?", (gid,)
            ).fetchone()
        return dict(row) if row else None

    def tasks(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM aria2_link_tasks ORDER BY updated_at DESC LIMIT 200"
            ).fetchall()
        return [dict(row) for row in rows]

    def contains(self, gid: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM aria2_link_tasks WHERE gid=?", (gid,)
            ).fetchone() is not None

    def contains_kind(self, gid: str, kind: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM aria2_link_tasks WHERE gid=? AND kind=?", (gid, kind)
            ).fetchone() is not None

    def reserve_refresh(self, gid: str, now: float) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE aria2_link_tasks SET status='refreshing', updated_at=?
                   WHERE gid=? AND retry_at<=? AND status!='held'""",
                (now, gid, now),
            )
            return cursor.rowcount == 1


class Aria2BunkrLinks:
    """Worker-side boundary for preview, enqueue, Tor switching, and refresh."""

    def __init__(
        self,
        *,
        workspace_root: Path | str,
        state_root: Path | str,
        rpc: Callable[..., Any],
        tor_ready: Callable[[], bool] | None = None,
        tor_proxy_url: Callable[[], str] | None = None,
        resolver: BunkrResolver | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.workspace_root = Path(workspace_root)
        self.state_root = Path(state_root)
        self.rpc = rpc
        self.tor_ready = tor_ready or self._probe_tor
        self.tor_proxy_url = tor_proxy_url or self._tor_proxy
        self.resolver = resolver or BunkrResolver()
        self.clock = clock
        self.store = BunkrTaskStore(self.state_root / "aria2-link-tasks.sqlite3")
        self._lock = threading.RLock()
        self._last_stopped_scan_at = 0.0
        self._stopped_scan_interval_seconds = 60.0
        self._tor_health_checked_at = 0.0
        self._tor_health_cache: bool | None = None

    def _tor_available(self, *, force: bool = False) -> bool:
        now = self.clock()
        if (
            not force
            and self._tor_health_cache is not None
            and now - self._tor_health_checked_at < 10.0
        ):
            return self._tor_health_cache
        try:
            ready = bool(self.tor_ready())
        except Exception:
            ready = False
        self._tor_health_checked_at = now
        self._tor_health_cache = ready
        return ready

    def _probe_metadata(self, direct_url: str) -> RemoteFileMetadata:
        probe_metadata = getattr(self.resolver, "probe_metadata", None)
        if callable(probe_metadata):
            value = probe_metadata(direct_url)
            return RemoteFileMetadata(
                size=_as_optional_nonnegative_int(getattr(value, "size", None)),
                range_supported=bool(getattr(value, "range_supported", False)),
                etag=str(getattr(value, "etag", "") or "").strip()[:512],
                last_modified=str(getattr(value, "last_modified", "") or "").strip()[:512],
            )
        # Keep the worker boundary compatible with older resolver adapters.
        size, range_supported = self.resolver.probe(direct_url)
        return RemoteFileMetadata(_as_optional_nonnegative_int(size), bool(range_supported))

    @staticmethod
    def _probe_tor() -> bool:
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                return client.get("http://tts-1:8090/aria2-proxy-readyz").status_code == 200
        except Exception:
            return False

    def preview(self, payload: object) -> dict[str, Any]:
        sources = self._sources(payload)
        items: list[dict[str, Any]] = []
        for index, source in enumerate(sources):
            try:
                parts = urlsplit(source)
                host = (parts.hostname or "").lower()
                if _BUNKR_HOST.fullmatch(host):
                    result = self.resolver.preview(source)
                    items.append({
                        "source_index": index,
                        "kind": result["kind"],
                        "title": result["title"],
                        "files": result["files"],
                        "error": "",
                    })
                else:
                    clean = self._validate_direct_url(source)
                    name = Path(urlsplit(clean).path).name or "download"
                    items.append({
                        "source_index": index,
                        "kind": "direct",
                        "title": name,
                        "files": [{"item_id": "", "file_name": name, "thumbnail_url": ""}],
                        "error": "",
                    })
            except Exception as exc:
                message = str(exc) if isinstance(exc, BunkrLinkError) else "Link tidak dapat diperiksa."
                items.append({"source_index": index, "kind": "error", "title": "", "files": [], "error": message})
        return {"items": items}

    def enqueue(self, payload: object) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) != {"sources", "selections", "directory", "route"}:
            raise BunkrLinkError("Format permintaan Links tidak valid.")
        sources = self._sources({"sources": payload.get("sources")})
        selections = payload.get("selections")
        if not isinstance(selections, dict):
            raise BunkrLinkError("Pilihan item album tidak valid.")
        route = str(payload.get("route") or "non").lower()
        if route not in {"non", "tor"}:
            raise BunkrLinkError("Mode jaringan tidak valid.")
        base_dir = self._workspace_directory(payload.get("directory"), create=False)
        tor_available = route != "tor" or self._tor_available(force=True)

        results: list[dict[str, Any]] = []
        for index, source in enumerate(sources):
            try:
                parts = urlsplit(source)
                host = (parts.hostname or "").lower()
                if _BUNKR_HOST.fullmatch(host):
                    clean_source = self.resolver.normalize_source(source)
                    result = self.resolver.preview(clean_source)
                    album_name = str(result["title"]) if result["kind"] == "album" else ""
                    public_files = result["files"]
                    selected = selections.get(str(index), [item["item_id"] for item in public_files])
                    if not isinstance(selected, list):
                        raise BunkrLinkError("Pilihan item album tidak valid.")
                    selected_ids = {str(value) for value in selected}
                    chosen = [item for item in public_files if str(item["item_id"]) in selected_ids]
                    if result["kind"] == "file":
                        chosen = [public_files[0]] if selected_ids else []
                    if not chosen:
                        results.append({"source_index": index, "status": "skipped", "reason_code": "NO_ITEMS_SELECTED"})
                        continue
                    for item in chosen:
                        try:
                            resolved = self.resolver.resolve_file(clean_source, str(item["item_id"]))
                            target_dir = self._workspace_directory(
                                str(base_dir / self._safe_component(album_name)) if album_name else str(base_dir),
                                create=True,
                            )
                            results.append(self._enqueue_one(
                                direct_url=resolved.direct_url,
                                file_name=resolved.file_name,
                                source_url=clean_source,
                                item_id=resolved.item_id,
                                album_name=album_name,
                                directory=target_dir,
                                kind="bunkr",
                                route=route,
                                tor_available=tor_available,
                            ))
                        except FileExistsError:
                            results.append({"source_index": index, "file_name": str(item["file_name"]), "status": "failed", "reason_code": "FILE_CONFLICT"})
                        except Exception as exc:
                            results.append({"source_index": index, "file_name": str(item["file_name"]), "status": "failed", "reason_code": self._reason(exc)})
                else:
                    clean = self._validate_direct_url(source)
                    name = Path(urlsplit(clean).path).name or "download"
                    try:
                        results.append(self._enqueue_one(
                            direct_url=clean, file_name=name, source_url="", item_id="",
                            album_name="", directory=base_dir, kind="direct", route=route,
                            tor_available=tor_available,
                            source_index=index,
                        ))
                    except FileExistsError:
                        results.append({"source_index": index, "file_name": name, "status": "failed", "reason_code": "FILE_CONFLICT"})
            except Exception as exc:
                results.append({"source_index": index, "status": "failed", "reason_code": self._reason(exc)})
        return {"items": results}

    def _enqueue_one(
        self, *, direct_url: str, file_name: str, source_url: str, item_id: str,
        album_name: str, directory: Path, kind: str, route: str,
        tor_available: bool = True,
        source_index: int = -1,
    ) -> dict[str, Any]:
        file_name = self._safe_component(file_name)
        destination = directory / file_name
        metadata = self._probe_metadata(direct_url) if kind == "bunkr" else RemoteFileMetadata(None, False)
        parsed_url = urlsplit(direct_url)
        source_scheme = parsed_url.scheme.lower()
        try:
            source_port = parsed_url.port or {"http": 80, "https": 443, "ftp": 21, "sftp": 22}.get(source_scheme, 0)
        except ValueError as exc:
            raise BunkrLinkError("URL unduhan tidak valid.") from exc
        tor_proxy = self.tor_proxy_url() if route == "tor" else ""
        held_for_tor = route == "tor" and not tor_available
        task_key = self.store.reserve({
            "kind": kind,
            "source_url": source_url,
            "item_id": item_id,
            "album_name": album_name,
            "file_name": file_name,
            "destination": str(destination),
            "route": route,
            "expected_size": metadata.size,
            "range_supported": metadata.range_supported,
            "expected_etag": metadata.etag,
            "expected_last_modified": metadata.last_modified,
            "source_scheme": source_scheme,
            "source_port": source_port,
        }, destination_exists=destination.exists() or destination.is_symlink())
        options = {
            "dir": str(directory),
            "out": file_name,
            "allow-overwrite": "false",
            "auto-file-renaming": "false",
            "max-tries": "0",
        }
        if route == "tor":
            options["all-proxy"] = tor_proxy
            options["proxy-method"] = "tunnel"
            if held_for_tor:
                # Keep the task visible and persistent in aria2 without starting
                # a transfer until the operator confirms Tor has recovered.
                options["pause"] = "true"
        try:
            gid = self.rpc("addUri", [direct_url], options)
            if not isinstance(gid, str) or not _GID.fullmatch(gid):
                raise RuntimeError("ARIA2_ADD_FAILED")
            self.store.set_gid(
                task_key,
                gid,
                status="held" if held_for_tor else "queued",
                reason_code="ARIA2_TOR_UNAVAILABLE" if held_for_tor else "",
            )
        except Exception:
            with self.store._connect() as connection:
                connection.execute(
                    "UPDATE aria2_link_tasks SET status='failed', reason_code='ARIA2_ADD_FAILED', updated_at=? WHERE task_key=?",
                    (self.clock(), task_key),
                )
            raise
        result = {
            "file_name": file_name, "gid": gid,
            "status": "held" if held_for_tor else "queued",
            "route": route,
            "reason_code": "ARIA2_TOR_UNAVAILABLE" if held_for_tor else "",
        }
        if source_index >= 0:
            result["source_index"] = source_index
        return result

    def _tor_proxy(self) -> str:
        try:
            token = (self.state_root / "tor-proxy.token").read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise BunkrLinkError("ARIA2_TOR_UNAVAILABLE: kredensial proxy internal belum siap.") from exc
        if not token:
            raise BunkrLinkError("ARIA2_TOR_UNAVAILABLE: kredensial proxy internal belum siap.")
        return f"http://aria2:{quote(token, safe='')}@tts-1:8118"

    def _workspace_directory(self, value: object, *, create: bool) -> Path:
        root = self.workspace_root.resolve(strict=True)
        candidate = Path(str(value or self.workspace_root / "aria2"))
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            if candidate.exists() or candidate.is_symlink():
                resolved = candidate.resolve(strict=True)
            elif create:
                parent = candidate.parent.resolve(strict=True)
                parent.relative_to(root)
                if not parent.is_dir():
                    raise ValueError
                candidate = parent / candidate.name
                candidate.mkdir()
                resolved = candidate.resolve(strict=True)
            else:
                resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
            if not resolved.is_dir():
                raise ValueError
            return resolved
        except (OSError, ValueError) as exc:
            raise BunkrLinkError("Folder tujuan harus berada di dalam Workspace.") from exc

    @staticmethod
    def _safe_component(value: object) -> str:
        name = " ".join(str(value or "").split())
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
        if name in {"", ".", ".."}:
            name = "download"
        return name[:240]

    @staticmethod
    def _validate_direct_url(value: object) -> str:
        raw = str(value or "").strip()
        try:
            parsed = urlsplit(raw)
            port = parsed.port
        except ValueError as exc:
            raise BunkrLinkError("URL unduhan tidak valid.") from exc
        if parsed.scheme.lower() not in {"http", "https", "ftp", "sftp"} or not parsed.hostname or parsed.username or parsed.password or port is not None and not 1 <= port <= 65535:
            raise BunkrLinkError("URL langsung harus memakai HTTP, HTTPS, FTP, atau SFTP.")
        if len(raw) > 8192:
            raise BunkrLinkError("URL terlalu panjang.")
        return raw

    @staticmethod
    def _sources(payload: object) -> list[str]:
        if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
            raise BunkrLinkError("Daftar URL tidak valid.")
        values = [str(item).strip() for item in payload["sources"] if str(item).strip()]
        if not values or len(values) > 100:
            raise BunkrLinkError("Kirim 1 sampai 100 URL per batch.")
        return values

    @staticmethod
    def _reason(exc: Exception) -> str:
        if isinstance(exc, BunkrLinkError):
            text = str(exc)
            if text.startswith("ARIA2_TOR_UNAVAILABLE"):
                return "ARIA2_TOR_UNAVAILABLE"
            if text.startswith("ARIA2_TOR_UNSUPPORTED_PROTOCOL"):
                return "ARIA2_TOR_UNSUPPORTED_PROTOCOL"
            return text[:200]
        if isinstance(exc, FileExistsError):
            return "FILE_CONFLICT"
        return "RESOLUTION_OR_ENQUEUE_FAILED"

    def tasks(self) -> dict[str, Any]:
        result: list[dict[str, Any]] = []
        now = self.clock()
        for row in self.store.tasks():
            gid = str(row.get("gid") or "")
            stored_status = str(row.get("status") or "")
            kind = str(row.get("kind") or "")
            status: dict[str, Any] = {}
            if gid:
                try:
                    value = self.rpc("tellStatus", gid, [
                        "gid", "status", "completedLength", "totalLength", "downloadSpeed",
                        "errorCode", "errorMessage",
                    ])
                    if isinstance(value, dict):
                        status = value
                except Exception:
                    pass
            refresh_pending = (
                kind == "bunkr"
                and str(status.get("status") or "") == "error"
                and (
                    bool(_HTTP_ERROR.search(str(status.get("errorMessage") or "")))
                    or str(status.get("errorCode") or "").strip() == "24"
                )
            )
            reported_status = (
                stored_status
                if stored_status in {"held", "refreshing"}
                else "refreshing" if refresh_pending
                else str(status.get("status") or row["status"])
            )
            result.append({
                "gid": gid,
                "kind": kind,
                "file_name": row["file_name"],
                "status": reported_status,
                "completed_bytes": _as_nonnegative_int(status.get("completedLength")),
                "total_bytes": _as_nonnegative_int(status.get("totalLength")),
                "speed_bytes_per_second": _as_nonnegative_int(status.get("downloadSpeed")),
                "error_code": str(status.get("errorCode") or ""),
                "reason_code": (
                    "BUNKR_URL_REFRESH_PENDING"
                    if refresh_pending and stored_status not in {"held", "refreshing"}
                    else str(row.get("reason_code") or "")
                ),
                "refresh_attempts": _as_nonnegative_int(row.get("refresh_attempts")),
                "retry_after_seconds": max(
                    0,
                    math.ceil(float(row.get("retry_at") or 0) - now),
                ) if stored_status == "refreshing" else 0,
                "route": str(row["route"]),
                "route_change_allowed": str(status.get("status") or "") == "paused",
            })
        return {"items": result}

    def pause(self, gid: str) -> dict[str, Any]:
        self._require_managed_gid(gid)
        result = self.rpc("pause", gid)
        return {"gid": gid, "status": str(result or "paused")}

    def set_route(self, gid: str, route: object) -> dict[str, Any]:
        self._require_managed_gid(gid)
        mode = str(route or "").lower()
        if mode not in {"non", "tor"}:
            raise BunkrLinkError("Mode jaringan tidak valid.")
        status = self.rpc("tellStatus", gid, ["gid", "status"])
        if not isinstance(status, dict) or status.get("status") != "paused":
            raise BunkrLinkError("Jeda task sebelum mengganti mode jaringan.")
        if mode == "tor" and not self._tor_available(force=True):
            self.store.update(gid, route="tor", status="held", reason_code="ARIA2_TOR_UNAVAILABLE")
            raise BunkrLinkError("ARIA2_TOR_UNAVAILABLE: layanan Tor worker belum siap.")
        options = {
            "all-proxy": self.tor_proxy_url() if mode == "tor" else "",
            "proxy-method": "tunnel" if mode == "tor" else "get",
        }
        self.rpc("changeOption", gid, options)
        self.store.update(gid, route=mode, status="paused", reason_code="")
        return {"gid": gid, "route": mode, "status": "paused"}

    def resume(self, gid: str) -> dict[str, Any]:
        self._require_managed_gid(gid)
        status = self.rpc("tellStatus", gid, ["gid", "status"])
        if not isinstance(status, dict) or status.get("status") != "paused":
            raise BunkrLinkError("Task tidak sedang dijeda.")
        row = self.store.get(gid) or {}
        route = str(row.get("route") or "non")
        if route == "tor" and not self._tor_available(force=True):
            self.store.update(gid, status="held", reason_code="ARIA2_TOR_UNAVAILABLE")
            raise BunkrLinkError("ARIA2_TOR_UNAVAILABLE: layanan Tor worker belum siap.")
        self.rpc("changeOption", gid, {
            "all-proxy": self.tor_proxy_url() if route == "tor" else "",
            "proxy-method": "tunnel" if route == "tor" else "get",
        })
        result = self.rpc("unpause", gid)
        self.store.update(gid, status="active", reason_code="")
        return {"gid": gid, "status": str(result or "active")}

    def _require_managed_gid(self, gid: str) -> dict[str, Any]:
        if not _GID.fullmatch(str(gid or "")):
            raise BunkrLinkError("Task Aria2 tidak valid.")
        row = self.store.get(gid)
        if row is None:
            raise BunkrLinkError("Task tidak dikelola melalui tab Links ini.")
        return row

    def is_bunkr_task(self, gid: str) -> bool:
        return self.store.contains_kind(gid, "bunkr")

    def tick(self, recovery_store: Any | None = None) -> None:
        """Refresh expired Bunkr URLs without creating another Aria2 task."""
        now = self.clock()
        managed_rows = {
            str(row.get("gid")): row
            for row in self.store.tasks()
            if row.get("gid")
        }
        bunkr_rows = {
            gid: row for gid, row in managed_rows.items()
            if row.get("kind") == "bunkr"
        }
        if not managed_rows:
            return
        try:
            active = self.rpc("tellActive", ["gid", "status", "errorCode", "errorMessage", "completedLength", "totalLength"])
            waiting = self.rpc("tellWaiting", 0, 1000, ["gid", "status", "errorCode", "errorMessage", "completedLength", "totalLength"])
        except Exception:
            return
        stopped = []
        if now - self._last_stopped_scan_at >= self._stopped_scan_interval_seconds:
            self._last_stopped_scan_at = now
            try:
                stopped = self.rpc("tellStopped", 0, 1000, ["gid", "status", "errorCode", "errorMessage", "completedLength", "totalLength"])
            except Exception:
                stopped = []
        live = [item for items in (active, waiting) if isinstance(items, list) for item in items if isinstance(item, dict)]
        terminal = [item for item in stopped if isinstance(item, dict)] if isinstance(stopped, list) else []
        observed = {str(item.get("gid")): item for item in (*live, *terminal) if item.get("gid")}
        tor_live = [
            (gid, observed[gid])
            for gid, row in managed_rows.items()
            if row.get("route") == "tor"
            and gid in observed
            and observed[gid].get("status") in {"active", "waiting"}
        ]
        if tor_live and not self._tor_available():
            for gid, current in tor_live:
                try:
                    self.rpc("forcePause", gid)
                except Exception:
                    continue
                self.store.update(gid, status="held", reason_code="ARIA2_TOR_UNAVAILABLE")
                observed[gid] = {**current, "status": "paused"}
        managed_error_events: list[str] = []
        processed_error_events: list[str] = []
        if recovery_store is not None:
            try:
                events = recovery_store.read().get("error_event_gids", [])
                for gid in events if isinstance(events, list) else []:
                    if gid in bunkr_rows:
                        managed_error_events.append(gid)
            except Exception:
                pass
        for gid in managed_error_events:
            try:
                current = self.rpc("tellStatus", gid, [
                    "gid", "status", "errorCode", "errorMessage", "completedLength", "totalLength",
                ])
            except Exception:
                continue
            if not isinstance(current, dict) or not current.get("status"):
                continue
            observed[gid] = current
            processed_error_events.append(gid)
        for gid, row in bunkr_rows.items():
            if gid in observed or row.get("status") != "refreshing" or float(row.get("retry_at") or 0) > now:
                continue
            try:
                current = self.rpc("tellStatus", gid, [
                    "gid", "status", "errorCode", "errorMessage", "completedLength", "totalLength",
                ])
                if isinstance(current, dict):
                    observed[gid] = current
            except Exception:
                continue
        for gid, row in bunkr_rows.items():
            current = observed.get(gid)
            if not current:
                continue
            if current.get("status") == "paused":
                continue
            expired = (
                bool(_HTTP_ERROR.search(str(current.get("errorMessage") or "")))
                or str(current.get("errorCode") or "").strip() == "24"
            )
            if not expired:
                continue
            if not self.store.reserve_refresh(gid, now):
                continue
            try:
                item = self.resolver.resolve_file(row["source_url"], row["item_id"])
                total = _as_nonnegative_int(current.get("totalLength"))
                completed = _as_nonnegative_int(current.get("completedLength"))
                metadata = self._probe_metadata(item.direct_url)
                new_size = metadata.size
                new_ranges = metadata.range_supported
                expected = _as_nonnegative_int(row.get("expected_size"))
                expected_etag = str(row.get("expected_etag") or "").strip()
                expected_last_modified = str(row.get("expected_last_modified") or "").strip()
                etag_mismatch = bool(
                    expected_etag and metadata.etag and expected_etag != metadata.etag
                )
                last_modified_mismatch = bool(
                    expected_last_modified
                    and metadata.last_modified
                    and expected_last_modified != metadata.last_modified
                )
                matching_validator = bool(
                    (expected_etag and metadata.etag and expected_etag == metadata.etag)
                    or (
                        expected_last_modified
                        and metadata.last_modified
                        and expected_last_modified == metadata.last_modified
                    )
                )
                validators_mismatch = etag_mismatch or last_modified_mismatch
                if completed > 0 and (
                    not expected or new_size != expected
                    or not bool(row.get("range_supported")) or not new_ranges
                    or not matching_validator or validators_mismatch
                ):
                    try:
                        self.rpc("forcePause", gid)
                    except Exception:
                        pass
                    self.store.update(gid, status="held", reason_code="BUNKR_PARTIAL_METADATA_MISMATCH")
                    continue
                if (expected and new_size and expected != new_size) or validators_mismatch:
                    try:
                        self.rpc("forcePause", gid)
                    except Exception:
                        pass
                    self.store.update(gid, status="held", reason_code="BUNKR_METADATA_MISMATCH")
                    continue
                uris = self.rpc("getUris", gid)
                old_uris = [str(value.get("uri")) for value in uris if isinstance(value, dict) and value.get("uri")] if isinstance(uris, list) else []
                changed = self.rpc("changeUri", gid, 1, old_uris, [item.direct_url])
                if (
                    not isinstance(changed, (list, tuple))
                    or len(changed) != 2
                    or any(isinstance(value, bool) or not isinstance(value, int) for value in changed)
                    or changed[0] != len(old_uris)
                    or changed[1] != 1
                ):
                    raise RuntimeError("ARIA2_URI_REFRESH_FAILED")
                self.store.update(
                    gid,
                    expected_size=new_size or expected or total or None,
                    range_supported=new_ranges,
                    expected_etag=metadata.etag or expected_etag,
                    expected_last_modified=metadata.last_modified or expected_last_modified,
                    status="active",
                    reason_code="",
                    refresh_attempts=0,
                    retry_at=0,
                )
            except Exception:
                attempts = int(row.get("refresh_attempts") or 0) + 1
                delay = min(300, 5 * (2 ** min(attempts - 1, 6)))
                self.store.update(
                    gid,
                    status="refreshing",
                    reason_code="BUNKR_URL_REFRESH_RETRYING",
                    refresh_attempts=attempts,
                    retry_at=now + delay,
                )
        if recovery_store is not None and processed_error_events:
            try:
                recovery_store.consume_error_events(processed_error_events)
            except Exception:
                pass


def _as_optional_nonnegative_int(value: object) -> int | None:
    try:
        return max(0, int(str(value)))
    except (TypeError, ValueError):
        return None


def _as_nonnegative_int(value: object) -> int:
    try:
        return max(0, int(str(value or "0")))
    except (TypeError, ValueError):
        return 0


def redact_aria2_response(value: Any) -> Any:
    """Remove task URIs and embedded signed query strings from public RPC data."""
    if isinstance(value, list):
        return [redact_aria2_response(item) for item in value]
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            if key == "uri" and isinstance(item, str):
                output[key] = "[URL disembunyikan]"
            elif key == "errorMessage" and isinstance(item, str):
                output[key] = _URI.sub("[URL disembunyikan]", item)
            elif key in {"all-proxy", "all-proxy-user", "all-proxy-passwd"}:
                continue
            else:
                output[key] = redact_aria2_response(item)
        return output
    return value
