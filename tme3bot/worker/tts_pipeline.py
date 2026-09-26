from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)
TTS_PART_CHARS = 90
TTS_PARALLELISM = 3
TTS_PART_DELAY_SECONDS = 0.2
TELEGRAM_AUDIO_SAFE_BYTES = 48_000_000
MAX_TTS_TEXT_CHARS = 100_000
_TOR_LOCK = threading.Lock()


class TtsError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = bool(retryable)


class TtsCancelled(TtsError):
    pass


def normalize_text(text: str) -> str:
    return " ".join(str(text).split())


def split_text(text: str, max_chars: int = TTS_PART_CHARS) -> list[str]:
    """Split normalized text into word-aware chunks no longer than 90 chars."""
    normalized = normalize_text(text)
    limit = min(TTS_PART_CHARS, max(1, int(max_chars)))
    if not normalized:
        return []
    parts: list[str] = []
    current: list[str] = []
    current_length = 0

    def flush() -> None:
        nonlocal current, current_length
        if current:
            parts.append(" ".join(current))
            current = []
            current_length = 0

    for sentence in re.split(r"(?<=[.!?])\s+", normalized):
        for word in sentence.split():
            if len(word) > limit:
                flush()
                parts.extend(word[i : i + limit] for i in range(0, len(word), limit))
                continue
            extra = len(word) + (1 if current else 0)
            if current and current_length + extra > limit:
                flush()
            current.append(word)
            current_length += len(word) + (1 if len(current) > 1 else 0)
    flush()
    return parts


def _tor_command(host: str, port: int, password: str) -> bool:
    """Request a fresh Tor circuit without logging the control credential."""
    try:
        with socket.create_connection((host, int(port)), timeout=3) as connection:
            stream = connection.makefile("rwb", buffering=0)
            if password:
                escaped = password.replace("\\", "\\\\").replace('"', '\\"')
                stream.write(f'AUTHENTICATE "{escaped}"\r\n'.encode("utf-8"))
                if not stream.readline().startswith(b"250"):
                    return False
            else:
                stream.write(b"AUTHENTICATE\r\n")
                if not stream.readline().startswith(b"250"):
                    return False
            stream.write(b"SIGNAL NEWNYM\r\n")
            return stream.readline().startswith(b"250")
    except (OSError, ValueError):
        return False


class TtsPipeline:
    """Three-route gTTS pipeline with stable per-part checkpoints."""

    def __init__(
        self,
        helper_urls: tuple[str, ...] | list[str],
        tor_control_host: str | tuple[str, ...] | list[str],
        tor_control_ports: tuple[int, ...] | list[int],
        tor_control_password: str = "",
        *,
        retries: int = 4,
        retry_base_seconds: float = 2.0,
        newnym_after_retries: int = 3,
        part_delay_seconds: float = TTS_PART_DELAY_SECONDS,
        request_timeout_seconds: float = 130,
        telegram_audio_safe_bytes: int = TELEGRAM_AUDIO_SAFE_BYTES,
        health_probe: Callable[[str], bool] | None = None,
        tor_probe: Callable[[str, int], bool] | None = None,
        request_part: Callable[..., bytes] | None = None,
        renew_route: Callable[[int], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.helper_urls = tuple(str(url).rstrip("/") for url in helper_urls if str(url).strip())
        if isinstance(tor_control_host, str):
            self.tor_control_hosts = tuple(
                item.strip() for item in tor_control_host.split(",") if item.strip()
            )
        else:
            self.tor_control_hosts = tuple(str(item).strip() for item in tor_control_host if str(item).strip())
        self.tor_control_ports = tuple(int(port) for port in tor_control_ports)
        self.tor_control_password = str(tor_control_password)
        self.retries = max(0, int(retries))
        self.retry_base_seconds = max(0.1, float(retry_base_seconds))
        self.newnym_after_retries = max(1, int(newnym_after_retries))
        self.part_delay_seconds = max(0.0, float(part_delay_seconds))
        self.request_timeout_seconds = max(1.0, float(request_timeout_seconds))
        self.telegram_audio_safe_bytes = max(1, int(telegram_audio_safe_bytes))
        self._health_probe = health_probe or self._probe_helper
        self._tor_probe = tor_probe or self._probe_tor
        self._request_part = request_part or self._http_request_part
        self._renew_route = renew_route or self._renew_tor_route
        self._sleep = sleep

    @classmethod
    def from_config(cls, config) -> "TtsPipeline":
        return cls(
            getattr(config, "tts_helper_urls", ()),
            getattr(config, "tts_tor_control_hosts", ()),
            getattr(config, "tts_tor_control_ports", ()),
            getattr(config, "tts_tor_control_password", ""),
            retries=getattr(config, "tts_part_retries", 4),
            retry_base_seconds=getattr(config, "tts_retry_base_seconds", 2.0),
            newnym_after_retries=getattr(config, "tts_newnym_after_retries", 3),
        )

    def ready(self) -> bool:
        if len(self.helper_urls) != TTS_PARALLELISM or len(self.tor_control_ports) != TTS_PARALLELISM:
            return False
        if len(self.tor_control_hosts) != TTS_PARALLELISM:
            return False
        return all(self._health_probe(url) for url in self.helper_urls) and all(
            self._tor_probe(host, port)
            for host, port in zip(self.tor_control_hosts, self.tor_control_ports)
        )

    @staticmethod
    def _probe_helper(url: str) -> bool:
        try:
            with urllib.request.urlopen(url + "/readyz", timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    @staticmethod
    def _probe_tor(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            return False

    def _renew_tor_route(self, route_index: int) -> bool:
        index = route_index % len(self.tor_control_ports)
        port = self.tor_control_ports[index]
        with _TOR_LOCK:
            return _tor_command(self.tor_control_hosts[index], port, self.tor_control_password)

    def _http_request_part(
        self,
        text: str,
        job_id: str,
        part_index: int,
        total_parts: int,
        route_index: int,
        attempt: int,
        directory: Path,
    ) -> Path:
        url = self.helper_urls[route_index % len(self.helper_urls)] + "/synthesize-part"
        request = urllib.request.Request(
            url,
            data=json.dumps(
                {
                    "text": text,
                    "job_id": job_id,
                    "part_index": part_index,
                    "total_parts": total_parts,
                    "route": f"tor-{route_index + 1}",
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "audio/mpeg"},
            method="POST",
        )
        target = directory / f"part-{part_index:05d}.mp3"
        temporary = directory / f".part-{part_index:05d}.{attempt}.{os.getpid()}.tmp"
        try:
            with urllib.request.urlopen(request, timeout=self.request_timeout_seconds) as response:
                content_type = response.headers.get("Content-Type", "")
                if response.status != 200:
                    raise TtsError("gTTS helper rejected the request", status=response.status)
                if "audio" not in content_type and "octet-stream" not in content_type:
                    raise TtsError("gTTS helper returned an invalid audio response", status=response.status)
                size = 0
                with temporary.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        size += len(chunk)
                if size == 0:
                    raise TtsError("gTTS helper returned an empty audio part")
            os.replace(temporary, target)
            return target
        except urllib.error.HTTPError as exc:
            try:
                exc.close()
            except Exception:
                pass
            raise TtsError("gTTS helper request failed", status=int(exc.code)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TtsError(
                f"gTTS helper connection failed ({type(exc).__name__})", retryable=True
            ) from None
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def synthesize(
        self,
        job_id: str,
        text: str,
        root: Path,
        *,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        pause_event: threading.Event | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        on_paused: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        if len(text) > MAX_TTS_TEXT_CHARS:
            raise TtsError("Teks melewati batas 100.000 karakter")
        if len(self.helper_urls) != TTS_PARALLELISM or len(self.tor_control_ports) != TTS_PARALLELISM or len(self.tor_control_hosts) != TTS_PARALLELISM:
            raise TtsError("Konfigurasi TTS memerlukan tiga helper dan tiga jalur Tor")
        root.mkdir(parents=True, exist_ok=True)
        for old in root.glob("artifact-*.mp3"):
            try:
                old.unlink()
            except OSError:
                pass
        chunks = split_text(text)
        if not chunks:
            raise TtsError("Teks tidak berisi kata untuk disintesis")
        total = len(chunks)
        completed: dict[int, Path] = {}
        pending: list[tuple[int, str, int, int]] = []
        for index, chunk in enumerate(chunks, start=1):
            cached = root / f"part-{index:05d}.mp3"
            try:
                if cached.is_file() and cached.stat().st_size > 0:
                    completed[index] = cached
                    continue
            except OSError:
                pass
            pending.append((index, chunk, 0, (index - 1) % TTS_PARALLELISM))
        self._emit(on_progress, phase="synthesizing", current=len(completed), total=total)
        max_attempts = self.retries + 1
        while pending:
            self._check_cancelled(is_cancelled)
            batch = [pending.pop(0) for _ in range(min(TTS_PARALLELISM, len(pending)))]
            results: dict[Any, tuple[int, str, int, int]] = {}
            with ThreadPoolExecutor(max_workers=TTS_PARALLELISM, thread_name_prefix="tts-part") as pool:
                for index, chunk, previous_attempt, route in batch:
                    attempt = previous_attempt + 1
                    future = pool.submit(self._request_part, chunk, job_id, index, total, route, attempt, root)
                    results[future] = (index, chunk, attempt, route)
                for future in as_completed(results):
                    index, chunk, attempt, route = results[future]
                    try:
                        completed[index] = future.result()
                        self._emit(on_progress, phase="synthesizing", current=len(completed), total=total, part=index)
                    except Exception as exc:
                        status = getattr(exc, "status", None)
                        rate_limited = status in {403, 429} or any(
                            marker in str(exc).lower()
                            for marker in ("rate limit", "too many requests", "captcha", "blocked", "forbidden")
                        )
                        retryable = (
                            rate_limited
                            or status in {408, 425}
                            or (status is not None and status >= 500)
                            or bool(getattr(exc, "retryable", False))
                        )
                        if not retryable or attempt >= max_attempts:
                            raise TtsError(f"Sintesis bagian {index}/{total} gagal setelah {attempt} percobaan") from None
                        next_route = (route + 1) % TTS_PARALLELISM if rate_limited else route
                        if rate_limited or attempt >= self.newnym_after_retries:
                            self._renew_route(route)
                        delay = min(60.0, self.retry_base_seconds * (2 ** (attempt - 1)))
                        self._emit(on_progress, phase="synthesizing", current=len(completed), total=total, part=index, retry=True)
                        self._sleep(delay)
                        pending.append((index, chunk, attempt, next_route))
            self._check_cancelled(is_cancelled)
            self._wait_for_resume(job_id, pause_event, is_cancelled, on_paused)
            if pending and self.part_delay_seconds:
                self._sleep(self.part_delay_seconds)
        self._wait_for_resume(job_id, pause_event, is_cancelled, on_paused)
        self._emit(on_progress, phase="merging", current=total, total=total)
        merged = root / "merged.mp3"
        with merged.open("wb") as output:
            for index in range(1, total + 1):
                with completed[index].open("rb") as source:
                    shutil.copyfileobj(source, output, 1024 * 1024)
        if merged.stat().st_size <= 0:
            raise TtsError("Penggabungan audio menghasilkan file kosong")
        if merged.stat().st_size <= self.telegram_audio_safe_bytes:
            source_files = [(1, merged)]
        else:
            source_files = [(index, completed[index]) for index in range(1, total + 1)]
        artifacts = []
        artifact_count = len(source_files)
        for output_index, (source_index, source) in enumerate(source_files, start=1):
            artifact_ref = secrets.token_hex(24)
            target = root / f"artifact-{artifact_ref}.mp3"
            shutil.copyfile(source, target)
            size = target.stat().st_size
            if size > self.telegram_audio_safe_bytes:
                raise TtsError("Satu bagian audio melebihi batas aman pengiriman Telegram")
            artifacts.append(
                {
                    "artifact_ref": artifact_ref,
                    "part_index": output_index,
                    "source_part_index": source_index,
                    "total_parts": artifact_count,
                    "byte_size": size,
                }
            )
        self._emit(on_progress, phase="telegram_delivery", current=total, total=total)
        return {"character_count": len(text), "part_count": total, "artifacts": artifacts}

    @staticmethod
    def _emit(callback, **values) -> None:
        if callback is not None:
            callback(values)

    @staticmethod
    def _check_cancelled(is_cancelled) -> None:
        if callable(is_cancelled) and is_cancelled():
            raise TtsCancelled("Job TTS dibatalkan")

    @staticmethod
    def _wait_for_resume(job_id, pause_event, is_cancelled, on_paused) -> None:
        if pause_event is None:
            return
        if pause_event.is_set() and on_paused is not None:
            on_paused()
        while pause_event.is_set():
            TtsPipeline._check_cancelled(is_cancelled)
            time.sleep(0.25)
        TtsPipeline._check_cancelled(is_cancelled)
