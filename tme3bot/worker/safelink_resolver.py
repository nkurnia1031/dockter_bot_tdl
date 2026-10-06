"""Playwright resolver for supported multi-step Safelink pages.

The resolver follows visible controls and their normal timers only. It does
not invoke site JavaScript directly, solve CAPTCHA, or download destination
files. Browser requests are checked before they leave Chromium so redirects
cannot target local or reserved addresses.
"""

from __future__ import annotations

import base64
import ipaddress
import re
import socket
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from tme3bot.safelink import normalize_shortlink_url


DEFAULT_TIMEOUT_SECONDS = 480
DEFAULT_MAX_RESTARTS = 4
STATE_RETRY_SECONDS = 20
CLICK_RETRY_SECONDS = 5
NAVIGATION_TIMEOUT_MS = 15_000
_CAPTCHA_TEXT = re.compile(
    r"(?:captcha|recaptcha|hcaptcha|turnstile|verify\s+you\s+are\s+human|"
    r"verifikasi\s+(?:bahwa\s+)?anda\s+manusia|i\s+am\s+not\s+a\s+robot)",
    re.IGNORECASE,
)
_CAPTCHA_SELECTORS = (
    "iframe[src*='captcha']",
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    ".g-recaptcha",
    ".h-captcha",
    ".cf-turnstile",
    "[data-sitekey]",
)


class SafelinkResolveError(RuntimeError):
    """A safe, user-facing resolver failure with no untrusted URL attached."""


class SafelinkCancelled(SafelinkResolveError):
    """Raised when the persisted job receives a cancellation request."""


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
        port = parsed.port or (443 if scheme == "https" else 80)
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


def _visible_buttons(page) -> list[tuple[str, str, bool, Any]]:
    found: list[tuple[str, str, bool, Any]] = []
    for button in page.locator("button:visible").all():
        try:
            label = " ".join(button.inner_text(timeout=500).split())
            handler = button.get_attribute("x-on:click") or button.get_attribute("@click") or ""
            if label or handler:
                found.append((label, handler.strip(), bool(button.is_disabled()), button))
        except Exception:
            continue
    return found


def _choose_gate_action(step: int | None, buttons: list[tuple[str, str, bool, Any]]):
    active = [(label, handler, locator) for label, handler, disabled, locator in buttons if not disabled]

    def match(label: str, handler: str):
        for current_label, current_handler, locator in active:
            if current_label.strip().lower() == label.lower() and current_handler.replace(" ", "").lower() == handler.lower():
                return current_label, current_handler, locator
        return None

    if step == 3:
        return match("Go", "go()") or match("Next", "next()") or match("Next Step", "scrollDown")
    if step == 4:
        return match("Next Step", "openClick()") or match("Next", "openClick()")
    if step is not None and step >= 5:
        for label, handler, locator in active:
            normalized = label.strip().lower()
            if "bot" in normalized and handler.replace(" ", "").lower() == "confirm()":
                return label, handler, locator
            if normalized == "click to continue" and handler.replace(" ", "").lower() == "confirm()":
                return label, handler, locator
        return None
    return match("Scroll Down", "next")


def _captcha_present(page, body: str) -> bool:
    if _CAPTCHA_TEXT.search(body):
        return True
    for selector in _CAPTCHA_SELECTORS:
        try:
            locator = page.locator(selector)
            if locator.count() and locator.first.is_visible():
                return True
        except Exception:
            continue
    for frame in getattr(page, "frames", []):
        try:
            host = (urlsplit(frame.url).hostname or "").lower()
        except ValueError:
            continue
        if any(token in host for token in ("captcha", "recaptcha", "hcaptcha")):
            return True
    return False


def _close_ad_overlay(page) -> bool:
    for frame in getattr(page, "frames", []):
        try:
            if "googleads.g.doubleclick.net/pagead/html" not in frame.url:
                continue
            close = frame.locator('div#dismiss-button[role="button"][aria-label="Tutup iklan"]')
            if close.count() and close.first.is_visible():
                close.first.click(timeout=7000)
                return True
        except Exception:
            continue
    try:
        close = page.get_by_role("button", name=re.compile(r"^Tutup$", re.IGNORECASE))
        if close.count() and close.first.is_visible():
            close.first.click(timeout=5000)
            return True
    except Exception:
        pass
    return False


def _guard_request(route, *, resolver) -> None:
    try:
        assert_public_http_url(route.request.url, resolver=resolver)
    except SafelinkResolveError:
        route.abort()
        return
    route.continue_()


def resolve_shortlink(
    input_url: str,
    *,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_restarts: int = DEFAULT_MAX_RESTARTS,
    resolver=socket.getaddrinfo,
    monotonic: Callable[[], float] = time.monotonic,
    playwright_factory=None,
) -> dict[str, str]:
    """Resolve the destination URL using visible UI controls and regular timers."""

    def progress(phase: str, message: str) -> None:
        if on_progress is not None:
            on_progress({"phase": phase, "message": message})

    def check_cancelled() -> None:
        if is_cancelled is not None and is_cancelled():
            raise SafelinkCancelled("Job resolver dibatalkan.")

    source = normalize_shortlink_url(input_url)
    parsed_source = urlsplit(source)
    source_host = (parsed_source.hostname or "").lower().rstrip(".")
    # The source domain is constrained separately from public egress checks.
    if source_host not in {"pndk.to", "go.fakta.id"}:
        raise SafelinkResolveError("Domain shortlink tidak didukung.")
    assert_public_http_url(source, resolver=resolver)
    try:
        if playwright_factory is None:
            from playwright.sync_api import sync_playwright

            playwright_factory = sync_playwright
        deadline = monotonic() + max(0, int(timeout_seconds))
        progress("starting", "Menyiapkan browser resolver.")
        with playwright_factory() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception:
                raise SafelinkResolveError("Browser resolver tidak dapat dijalankan.") from None
            try:
                context = browser.new_context(
                    viewport={"width": 1365, "height": 900},
                    locale="id-ID",
                    accept_downloads=False,
                )
                context.route("**/*", lambda route: _guard_request(route, resolver=resolver))
                # This tool only reads the target URL; never allow site WebSocket
                # traffic to bypass the HTTP request guard.
                route_web_socket = getattr(context, "route_web_socket", None)
                if callable(route_web_socket):
                    route_web_socket("**/*", lambda socket_route: socket_route.close())
                page = context.new_page()
                download_attempted = False

                def reject_download(download) -> None:
                    nonlocal download_attempted
                    download_attempted = True
                    try:
                        download.cancel()
                    except Exception:
                        pass

                page.on("download", reject_download)
                try:
                    page.goto(source, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
                except Exception:
                    raise SafelinkResolveError("Halaman shortlink gagal dibuka.") from None
                restart_count = 0
                last_url = ""
                last_step: int | None = None
                last_action: tuple[str, int | None, str, str] | None = None
                last_action_time = 0.0
                last_state_signature = ""
                last_state_change = monotonic()
                dismissed_overlay = False
                while monotonic() < deadline:
                    check_cancelled()
                    page.wait_for_timeout(700)
                    check_cancelled()
                    if download_attempted:
                        raise SafelinkResolveError(
                            "Halaman mencoba mengunduh file. Resolver hanya mengembalikan URL tujuan."
                        )
                    current_url = page.url
                    current = urlsplit(current_url)
                    current_host = (current.hostname or "").lower().rstrip(".")
                    if current_host == "safelinkearn.com" or current_host.endswith(".safelinkearn.com"):
                        destination = decode_safelinkearn_url(current_url, resolver=resolver)
                        if destination:
                            progress("completed", "URL tujuan berhasil ditemukan.")
                            return {"destination_url": destination}
                        raise SafelinkResolveError("Halaman tujuan tercapai, tetapi URL target tidak dapat dibaca.")

                    try:
                        body = page.locator("body").inner_text(timeout=1500)
                    except Exception:
                        body = ""
                    if _captcha_present(page, body):
                        raise SafelinkResolveError(
                            "Shortlink meminta verifikasi CAPTCHA. Job dihentikan; selesaikan verifikasi secara manual lalu kirim ulang."
                        )
                    step_match = re.search(r"Step\s*(\d+)\s*/\s*\d+", body, re.IGNORECASE)
                    step = int(step_match.group(1)) if step_match else None
                    if current_url != last_url or step != last_step:
                        last_url, last_step = current_url, step
                        last_action = None
                        last_state_signature = ""
                        last_state_change = monotonic()
                        dismissed_overlay = False
                        progress("resolving", f"Membaca langkah {step}/5." if step else "Menunggu langkah shortlink.")

                    has_overlay = "google_vignette" in current_url or "Beralihlah dan hemat dengan AI" in body
                    if has_overlay and not dismissed_overlay:
                        if _close_ad_overlay(page):
                            dismissed_overlay = True
                            progress("resolving", "Overlay iklan ditutup.")
                            continue
                        restart_count += 1
                        if restart_count > max_restarts:
                            raise SafelinkResolveError("Overlay iklan menutupi halaman; batas pengulangan tercapai.")
                        progress("retrying", f"Mengulang halaman ({restart_count}/{max_restarts}).")
                        page.goto(source, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
                        last_url = ""
                        last_step = None
                        last_action = None
                        last_state_signature = ""
                        last_state_change = monotonic()
                        continue

                    buttons = _visible_buttons(page)
                    visible_gate = [
                        (label, handler, disabled)
                        for label, handler, disabled, _ in buttons
                        if handler.lower() not in ("openpopup", "opentxt") and (label or handler)
                    ]
                    signature = repr((step, visible_gate))
                    if signature != last_state_signature:
                        last_state_signature = signature
                        last_state_change = monotonic()
                    waiting = any(re.search(r"please\s*wait", label, re.IGNORECASE) for label, _, _ in visible_gate)
                    action = None if waiting else _choose_gate_action(step, buttons)
                    now = monotonic()
                    if action:
                        label, handler, locator = action
                        action_key = (current_url, step, label, handler)
                        if action_key != last_action or now - last_action_time >= CLICK_RETRY_SECONDS:
                            check_cancelled()
                            try:
                                locator.click(timeout=5000)
                                progress("resolving", f"Tombol langkah {step or '?'} ditekan.")
                            except Exception:
                                progress("resolving", f"Menunggu tombol langkah {step or '?'} siap.")
                            last_action = action_key
                            last_action_time = now
                            continue

                    continue_link = page.locator("#continue")
                    if not waiting and continue_link.count() and continue_link.first.is_visible():
                        action_key = (current_url, step, "Continue", "#continue")
                        if action_key != last_action or now - last_action_time >= CLICK_RETRY_SECONDS:
                            check_cancelled()
                            try:
                                continue_link.first.click(timeout=5000)
                                progress("resolving", "Tombol Continue ditekan.")
                            except Exception:
                                progress("resolving", "Menunggu tombol Continue siap.")
                            last_action = action_key
                            last_action_time = now
                            continue

                    stalled = monotonic() - last_state_change >= STATE_RETRY_SECONDS
                    no_step_or_timer = step is None or not visible_gate or (waiting and stalled)
                    if no_step_or_timer and stalled:
                        restart_count += 1
                        if restart_count > max_restarts:
                            raise SafelinkResolveError("Timer atau langkah shortlink tidak muncul; batas pengulangan tercapai.")
                        progress("retrying", f"Langkah belum muncul; mengulang ({restart_count}/{max_restarts}).")
                        page.goto(source, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
                        last_url = ""
                        last_step = None
                        last_action = None
                        last_state_signature = ""
                        last_state_change = monotonic()
                        dismissed_overlay = False
                raise SafelinkResolveError("Batas waktu resolver 480 detik tercapai.")
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    except (SafelinkResolveError, SafelinkCancelled):
        raise
    except Exception:
        # Playwright exceptions commonly include the complete URL and query.
        raise SafelinkResolveError("Resolver mengalami kendala saat memproses halaman.") from None
