from __future__ import annotations

import argparse
import errno
import ipaddress
import json
import os
import shutil
import stat
import sys
import time
from contextlib import contextmanager, nullcontext
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


def _is_loopback_origin(origin: str) -> bool:
    hostname = urlsplit(origin).hostname or ""
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _read_storage_state(store: TrustedDeviceStore, path: Path) -> dict:
    try:
        private_root_path = getattr(store, "root", store.states.parent)
        private_root = private_root_path.resolve(strict=True)
        if private_root_path.is_symlink():
            raise TrustedDeviceError("Direktori credential tidak boleh berupa symlink.")
        if store.states.is_symlink():
            raise TrustedDeviceError("Direktori browser state tidak boleh berupa symlink.")
        expected_root = store.states.resolve(strict=True)
        if expected_root.parent != private_root:
            raise TrustedDeviceError("Direktori browser state berada di luar root privat.")
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except TrustedDeviceError:
        raise
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
    if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise TrustedDeviceError("Permission file storage state harus privat untuk akun saat ini.")

    try:
        state = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrustedDeviceError("File Playwright storage state rusak.") from exc
    return _validate_storage_state(store, state)


def _validate_storage_state(store: TrustedDeviceStore, state: dict) -> dict:
    if not isinstance(state, dict) or state.get("origins") != [] or not isinstance(state.get("cookies"), list):
        raise TrustedDeviceError("Format Playwright storage state tidak valid.")

    host = urlsplit(store.origin).hostname
    cookies = state["cookies"]
    if {item.get("name") for item in cookies if isinstance(item, dict)} != COOKIE_NAMES or len(cookies) != len(COOKIE_NAMES):
        raise TrustedDeviceError("Storage state bukan sesi Web trusted device yang diharapkan.")
    now = time.time()
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise TrustedDeviceError("Cookie dalam storage state tidak valid.")
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        name = cookie.get("name")
        try:
            expires_at = float(cookie.get("expires") or 0)
        except (TypeError, ValueError):
            expires_at = 0
        if (
            domain != str(host).lower()
            or cookie.get("path") != "/"
            or cookie.get("secure") is not True
            or not isinstance(cookie.get("value"), str)
            or not cookie.get("value")
            # Access tokens are intentionally short-lived. The Web app refreshes
            # them through tme3_refresh when its initial session request returns
            # 401, so an expired access cookie must not invalidate an otherwise
            # live trusted-device session snapshot.
            or (name != "tme3_access" and expires_at <= now)
            or (name in {"tme3_access", "tme3_refresh"} and cookie.get("httpOnly") is not True)
            or (name == "tme3_csrf" and cookie.get("httpOnly") is not False)
        ):
            raise TrustedDeviceError("Atribut cookie storage state tidak memenuhi kebijakan sesi Web.")
    return state


def _latest_browser_state(store: TrustedDeviceStore) -> Path:
    try:
        candidates = sorted(
            store.states.glob("browser-*.json"),
            key=lambda path: path.lstat().st_mtime_ns,
            reverse=True,
        )
    except OSError as exc:
        raise TrustedDeviceError("Sesi browser tersimpan tidak dapat diperiksa.") from exc
    for path in candidates:
        try:
            state = _read_storage_state(store, path)
            if path.name.startswith("browser-session-"):
                expiry_text = path.name.removeprefix("browser-session-").split("-", 1)[0]
                expiry = int(expiry_text)
            else:
                refresh = next(cookie for cookie in state["cookies"] if cookie["name"] == "tme3_refresh")
                expiry = int(refresh["expires"])
            if expiry <= int(time.time()):
                continue
            return path
        except (TrustedDeviceError, StopIteration, ValueError):
            continue
    raise TrustedDeviceError(
        "Sesi browser lokal belum tersedia atau sudah kedaluwarsa. "
        "Buat sesi baru sekali dengan `python3 -m tools.trusted_device prepare-browser --origin <origin>`."
    )


@contextmanager
def _browser_state_lock(path: Path):
    """Serialize browser runs so rotating refresh cookies cannot race each other."""
    lock_path = path.with_suffix(".lock")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise TrustedDeviceError("Lock sesi browser tidak dapat dibuat dengan aman.") from exc
    locked = False
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise TrustedDeviceError("Lock sesi browser tidak aman.")
        if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise TrustedDeviceError("Permission lock sesi browser harus privat.")
        if os.name == "nt":
            import msvcrt

            if info.st_size == 0:
                os.write(fd, b"\0")
            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EDEADLK}:
                        raise TrustedDeviceError("Lock sesi browser tidak dapat diambil.") from None
                    time.sleep(0.1)
            locked = True
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def _refreshed_browser_state(store: TrustedDeviceStore, context) -> dict:
    try:
        current = context.storage_state()
    except Exception as exc:
        raise TrustedDeviceError("State browser terbaru tidak dapat dibaca.") from exc
    cookies = current.get("cookies") if isinstance(current, dict) else None
    if not isinstance(cookies, list):
        raise TrustedDeviceError("Browser tidak mengembalikan cookie sesi yang valid.")
    session_cookies = [cookie for cookie in cookies if isinstance(cookie, dict) and cookie.get("name") in COOKIE_NAMES]
    state = {"cookies": session_cookies, "origins": []}
    _validate_storage_state(store, state)
    return state


def _refresh_browser_session(context, origin: str) -> bool:
    """Rotate the refresh cookie before the CLI's direct API session check."""
    cookies = context.cookies(origin)
    csrf = next((cookie["value"] for cookie in cookies if cookie.get("name") == "tme3_csrf"), None)
    if not csrf:
        return False
    try:
        response = context.request.post(
            f"{origin}/api/v1/auth/browser/refresh",
            headers={"Origin": origin, "X-CSRF-Token": csrf},
            max_redirects=0,
            timeout=15_000,
        )
        if response.status != 200:
            return False
        payload = response.json()
    except Exception:
        return False
    return isinstance(payload, dict) and payload.get("authenticated") is True


@contextmanager
def open_trusted_context(
    *,
    origin: str,
    storage_state: str | Path | None = None,
    headless: bool = True,
    executable_path: str | None = None,
    allow_localhost_tls_errors: bool = False,
):
    """Yield a pinned-origin context, reusing and refreshing the local session by default.

    Omitting ``storage_state`` selects the newest valid helper-issued state and
    atomically saves rotated cookies when the context closes. Helper-issued
    ``browser-session-*`` paths remain persistent when supplied explicitly;
    legacy state paths retain one-use import behavior. TLS errors can be ignored
    only for loopback origins used by local HTTPS tests.
    """
    origin = canonical_origin(origin)
    if allow_localhost_tls_errors and not _is_loopback_origin(origin):
        raise TrustedDeviceError("Validasi TLS hanya boleh diabaikan untuk origin localhost.")
    store = TrustedDeviceStore(origin)
    explicit_path = storage_state is not None
    persistent = not explicit_path or Path(storage_state).name.startswith("browser-session-")
    if persistent and not store.states.is_dir():
        raise TrustedDeviceError(
            "Sesi browser lokal belum tersedia. Buat sesi baru sekali dengan "
            "`python3 -m tools.trusted_device prepare-browser --origin <origin>`."
        )
    lock_context = _browser_state_lock(store.states / "browser-session.json") if persistent else nullcontext()
    with lock_context:
        path = Path(storage_state).expanduser() if explicit_path else _latest_browser_state(store)
        if persistent and not path.name.startswith("browser-session-"):
            legacy_state = _read_storage_state(store, path)
            refresh = next(cookie for cookie in legacy_state["cookies"] if cookie["name"] == "tme3_refresh")
            path = store.new_persistent_browser_state_path(expires_at=int(refresh["expires"]))
            store.write_browser_state(path, legacy_state)
        state = None
        browser = None
        context = None
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
                    context = browser.new_context(
                        storage_state=state,
                        ignore_https_errors=allow_localhost_tls_errors,
                    )
                    state = None
                    if not persistent:
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
                    try:
                        if persistent and context is not None:
                            store.update_browser_state(path, _refreshed_browser_state(store, context))
                        elif not persistent:
                            try:
                                if path.name.startswith("browser-") and path.suffix == ".json" and path.resolve().parent == store.states.resolve():
                                    path.unlink(missing_ok=True)
                            except OSError:
                                pass
                    finally:
                        try:
                            if context is not None:
                                context.close()
                        finally:
                            if browser is not None:
                                browser.close()
        finally:
            # Preserve the documented one-use cleanup for explicit temporary imports.
            if not persistent:
                try:
                    if path.name.startswith("browser-") and path.suffix == ".json" and path.resolve().parent == store.states.resolve():
                        path.unlink(missing_ok=True)
                except OSError:
                    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open a browser using a trusted-device Playwright storage state.")
    parser.add_argument("--origin", required=True, help="Pinned HTTPS origin used by trusted_device.py")
    parser.add_argument(
        "--state-file",
        help="Optional private state file; omit to reuse and refresh the newest saved trusted-device session",
    )
    parser.add_argument("--url", help="Same-origin URL; defaults to the authenticated browser-session API")
    parser.add_argument("--browser-executable", help="Chrome/Chromium executable; defaults to installed Chrome/Edge or Playwright Chromium")
    parser.add_argument("--headed", action="store_true", help="Show the browser window")
    parser.add_argument(
        "--allow-localhost-tls-errors",
        action="store_true",
        help="Allow a self-signed certificate only for a loopback origin used in local tests",
    )
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
            allow_localhost_tls_errors=args.allow_localhost_tls_errors,
        ) as context:
            if args.url is None and not _refresh_browser_session(context, origin):
                print(json.dumps({"status": 401, "url": target, "authenticated": False}, ensure_ascii=False))
                return 1
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
