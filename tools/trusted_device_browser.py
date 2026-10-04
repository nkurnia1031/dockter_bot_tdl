from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from tools.trusted_device_store import TrustedDeviceError, TrustedDeviceStore, canonical_origin


COOKIE_NAMES = {"tme3_access", "tme3_refresh", "tme3_csrf"}


def _browser_executable(explicit: str | None = None) -> str | None:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise TrustedDeviceError("Executable browser yang diminta tidak ditemukan.")
        return str(path.resolve())

    configured = os.environ.get("TME3_TRUSTED_DEVICE_BROWSER", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise TrustedDeviceError("TME3_TRUSTED_DEVICE_BROWSER tidak menunjuk file browser.")
        return str(path.resolve())

    candidates = []
    if os.name == "nt":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(variable, "")
            if root:
                candidates.extend(
                    [
                        Path(root) / "Google/Chrome/Application/chrome.exe",
                        Path(root) / "Microsoft/Edge/Application/msedge.exe",
                    ]
                )
    else:
        for command in ("chromium", "chromium-browser", "google-chrome", "chrome", "microsoft-edge"):
            found = shutil.which(command)
            if found:
                candidates.append(Path(found))

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def _validate_target(origin: str, url: str, *, allow_query: bool = False) -> None:
    expected = canonical_origin(origin)
    parsed = urlsplit(url)
    actual = canonical_origin(f"{parsed.scheme}://{parsed.netloc}")
    if (
        actual != expected
        or parsed.username is not None
        or parsed.password is not None
        or (parsed.query and not allow_query)
        or parsed.fragment
    ):
        raise TrustedDeviceError("URL browser harus memakai origin yang sama dengan credential perangkat.")


def _read_storage_state(store: TrustedDeviceStore, path: Path) -> dict:
    expected_root = store.states.resolve()
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise TrustedDeviceError("File Playwright storage state tidak dapat dibaca.") from exc
    if (
        not path.name.startswith("browser-")
        or path.suffix != ".json"
        or path.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or resolved.parent != expected_root
        or not resolved.is_file()
        or info.st_nlink != 1
    ):
        raise TrustedDeviceError("File storage state berada di luar lokasi privat helper.")

    try:
        state = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrustedDeviceError("File Playwright storage state rusak.") from exc
    if not isinstance(state, dict) or state.get("origins") != [] or not isinstance(state.get("cookies"), list):
        raise TrustedDeviceError("Format Playwright storage state tidak valid.")

    host = urlsplit(store.origin).hostname
    cookies = state["cookies"]
    if {item.get("name") for item in cookies if isinstance(item, dict)} != COOKIE_NAMES or len(cookies) != len(COOKIE_NAMES):
        raise TrustedDeviceError("Storage state bukan sesi Web trusted device yang diharapkan.")
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise TrustedDeviceError("Cookie dalam storage state tidak valid.")
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        name = cookie.get("name")
        if (
            domain != str(host).lower()
            or cookie.get("path") != "/"
            or cookie.get("secure") is not True
            or not isinstance(cookie.get("value"), str)
            or not cookie.get("value")
            or float(cookie.get("expires") or 0) <= time.time()
            or (name in {"tme3_access", "tme3_refresh"} and cookie.get("httpOnly") is not True)
            or (name == "tme3_csrf" and cookie.get("httpOnly") is not False)
        ):
            raise TrustedDeviceError("Atribut cookie storage state tidak memenuhi kebijakan sesi Web.")
    return state


@contextmanager
def open_trusted_context(
    *,
    origin: str,
    storage_state: str | Path,
    headless: bool = True,
    executable_path: str | None = None,
):
    """Import one helper-issued Playwright state and yield a same-origin browser context.

    The helper state file is deleted after import, including when browser startup fails.
    Callers must keep navigation on the pinned origin and must not log cookie data.
    """
    origin = canonical_origin(origin)
    path = Path(storage_state).expanduser()
    store = TrustedDeviceStore(origin)
    state = None
    try:
        state = _read_storage_state(store, path)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise TrustedDeviceError(
                "Playwright Python belum tersedia. Pasang dengan: python -m pip install playwright"
            ) from exc

        executable = _browser_executable(executable_path)
        with sync_playwright() as playwright:
            options = {"headless": headless}
            if executable:
                options["executable_path"] = executable
            try:
                browser = playwright.chromium.launch(**options)
            except Exception as exc:
                raise TrustedDeviceError(
                    "Browser Chromium/Chrome tidak dapat dijalankan. Pasang browser Playwright atau atur TME3_TRUSTED_DEVICE_BROWSER."
                ) from exc
            try:
                context = browser.new_context(storage_state=state)
                state = None
                path.unlink(missing_ok=True)

                def same_origin_only(route):
                    try:
                        _validate_target(origin, route.request.url, allow_query=True)
                    except TrustedDeviceError:
                        route.abort()
                    else:
                        route.continue_()

                context.route("**/*", same_origin_only)
                yield context
            finally:
                # Best effort: closing the context drops its in-memory cookie copy.
                try:
                    if "context" in locals():
                        context.close()
                finally:
                    browser.close()
    finally:
        # Do not delete arbitrary paths: only consume files in this origin's private helper directory.
        try:
            if path.name.startswith("browser-") and path.suffix == ".json" and path.resolve().parent == store.states.resolve():
                path.unlink(missing_ok=True)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open a browser using a trusted-device Playwright storage state.")
    parser.add_argument("--origin", required=True, help="Pinned HTTPS origin used by trusted_device.py")
    parser.add_argument("--state-file", required=True, help="Private browser state file from prepare-browser")
    parser.add_argument("--url", help="Same-origin URL; defaults to the authenticated browser-session API")
    parser.add_argument("--browser-executable", help="Chrome/Chromium executable; defaults to installed Chrome/Edge or Playwright Chromium")
    parser.add_argument("--headed", action="store_true", help="Show the browser window")
    args = parser.parse_args(argv)
    try:
        origin = canonical_origin(args.origin)
        target = args.url or f"{origin}/api/v1/auth/browser/session"
        _validate_target(origin, target)
        with open_trusted_context(
            origin=origin,
            storage_state=args.state_file,
            headless=not args.headed,
            executable_path=args.browser_executable,
        ) as context:
            page = context.new_page()
            response = page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            safe_url = urlsplit(page.url)._replace(query="", fragment="").geturl()
            result = {"status": response.status if response else None, "url": safe_url}
            if response and "application/json" in response.headers.get("content-type", ""):
                payload = response.json()
                result["authenticated"] = payload.get("authenticated") is True
                actor = payload.get("actor")
                if isinstance(actor, dict):
                    result["actor_id"] = actor.get("telegram_user_id")
            print(json.dumps(result, ensure_ascii=False))
            return 0 if response and response.ok else 1
    except TrustedDeviceError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        print("Browser agent gagal tanpa menampilkan isi storage state.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
