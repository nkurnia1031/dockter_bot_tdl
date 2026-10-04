from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.trusted_device_store import (
    TrustedDeviceError,
    TrustedDeviceStore,
    _b64,
    canonical_origin,
    create_device_keypair,
)


PROTOCOL = "tme3-device-auth-v1"
PURPOSE = "browser-session"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def canonical_payload(challenge: dict, expected_origin: str, device_id: str) -> bytes:
    if (
        challenge.get("protocol_version") != PROTOCOL
        or challenge.get("origin") != expected_origin
        or challenge.get("device_id") != device_id
    ):
        raise TrustedDeviceError("Server mengirim challenge perangkat yang tidak cocok.")
    try:
        expires = int(challenge["expires_unix"])
        nonce = str(challenge["nonce"])
        challenge_id = str(challenge["challenge_id"])
        if not challenge_id or any("\r" in value or "\n" in value for value in (nonce, challenge_id)):
            raise ValueError("Invalid field")
        if expires < int(time.time()) or expires > int(time.time()) + 125:
            raise ValueError("Expired or implausible challenge")
        raw_nonce = base64.urlsafe_b64decode(nonce + "=" * (-len(nonce) % 4))
        if len(raw_nonce) != 32:
            raise ValueError("Invalid nonce")
        return "\n".join(
            [PROTOCOL, PURPOSE, expected_origin, device_id, challenge_id, nonce, str(expires)]
        ).encode("utf-8")
    except (KeyError, TypeError, ValueError) as exc:
        raise TrustedDeviceError("Challenge perangkat rusak atau telah kedaluwarsa.") from exc


def _open_json(origin: str, path: str, body: dict) -> tuple[dict, list[str]]:
    url = canonical_origin(origin) + "/api/v1" + path
    payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": canonical_origin(origin),
        },
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(1024 * 1024)
            result = json.loads(raw.decode("utf-8"))
            cookies = list(response.headers.get_all("Set-Cookie", []))
    except urllib.error.HTTPError as exc:
        # Error response is deliberately not printed; it may contain deployment-specific text.
        raise TrustedDeviceError(f"Backend autentikasi menolak request (HTTP {exc.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise TrustedDeviceError("Backend autentikasi tidak dapat dijangkau atau memberi respons tidak valid.") from None
    if not isinstance(result, dict):
        raise TrustedDeviceError("Respons autentikasi tidak valid.")
    return result, cookies


def browser_state(origin: str, set_cookie_headers: list[str]) -> dict:
    host = urlsplit(canonical_origin(origin)).hostname
    cookies = []
    parsed_names = set()
    for header in set_cookie_headers:
        parsed = SimpleCookie()
        try:
            parsed.load(header)
        except Exception:
            continue
        for name, morsel in parsed.items():
            if name not in {"tme3_access", "tme3_refresh", "tme3_csrf"}:
                continue
            if not morsel.value:
                raise TrustedDeviceError("Backend mengirim cookie sesi kosong.")
            cookie_domain = morsel["domain"].lstrip(".").lower()
            if cookie_domain and cookie_domain != str(host).lower():
                raise TrustedDeviceError("Backend mengirim cookie dengan domain di luar origin tepercaya.")
            if morsel["path"] and morsel["path"] != "/":
                raise TrustedDeviceError("Backend mengirim cookie dengan path yang tidak diharapkan.")
            if name in parsed_names:
                raise TrustedDeviceError("Backend mengirim cookie sesi ganda.")
            try:
                max_age = int(morsel["max-age"])
            except (TypeError, ValueError) as exc:
                raise TrustedDeviceError("Backend tidak mengirim masa berlaku cookie sesi.") from exc
            if max_age <= 0:
                raise TrustedDeviceError("Backend mengirim cookie sesi yang sudah kedaluwarsa.")
            same_site = morsel["samesite"].capitalize() if morsel["samesite"] else "Lax"
            cookie = {
                "name": name,
                "value": morsel.value,
                "domain": morsel["domain"] or host,
                "path": morsel["path"] or "/",
                "expires": int(time.time()) + max_age,
                "httpOnly": bool(morsel["httponly"]),
                "secure": bool(morsel["secure"]),
                "sameSite": same_site if same_site in {"Strict", "Lax", "None"} else "Lax",
            }
            if cookie["secure"] is not True or name != "tme3_csrf" and cookie["httpOnly"] is not True:
                raise TrustedDeviceError("Backend mengirim cookie sesi tanpa atribut Secure/HttpOnly yang diwajibkan.")
            if name == "tme3_csrf" and cookie["httpOnly"] is True:
                raise TrustedDeviceError("Cookie CSRF harus dapat dibaca oleh Web agar request mutasi tetap terlindungi.")
            cookies.append(cookie)
            parsed_names.add(name)
    if parsed_names != {"tme3_access", "tme3_refresh", "tme3_csrf"}:
        raise TrustedDeviceError("Backend tidak menerbitkan seluruh cookie sesi Web.")
    return {"cookies": cookies, "origins": []}


def command_init(args) -> dict:
    origin = canonical_origin(args.origin)
    store = TrustedDeviceStore(origin)
    device_id, public_key, private_key = create_device_keypair()
    enrollment = store.save_credentials(
        device_id=device_id,
        name=args.name,
        public_key=public_key,
        private_key=private_key,
    )
    return {
        "enrollment_file": str(store.enrollment_path),
        "device_id": enrollment["device_id"],
        "fingerprint": enrollment["fingerprint"],
        "origin": origin,
    }


def command_prepare(args) -> dict:
    origin = canonical_origin(args.origin)
    store = TrustedDeviceStore(origin)
    store.clean_stale_states()
    document, private_bytes = store.credentials()
    challenge, _ = _open_json(origin, "/auth/device/challenge", {"device_id": document["device_id"]})
    signed = canonical_payload(challenge, origin, str(document["device_id"]))
    private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
    signature = _b64(private_key.sign(signed))
    session_data, set_cookie = _open_json(
        origin,
        "/auth/device/exchange",
        {
            "device_id": document["device_id"],
            "challenge_id": challenge["challenge_id"],
            "signature": signature,
        },
    )
    if session_data.get("authenticated") is not True:
        raise TrustedDeviceError("Backend tidak mengonfirmasi sesi perangkat.")
    state = browser_state(origin, set_cookie)
    state_path = store.new_browser_state_path()
    store.write_browser_state(state_path, state)
    return {
        "browser_state_file": str(state_path),
        "device_id": str(document["device_id"]),
        "fingerprint": str(document["fingerprint"]),
        "origin": origin,
        "challenge_expires_at": challenge.get("expires_at"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Trusted device credential untuk browser automation.")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--origin", required=True)
    init.add_argument("--name", required=True)
    init.set_defaults(run=command_init)
    prepare = sub.add_parser("prepare-browser")
    prepare.add_argument("--origin", required=True)
    prepare.set_defaults(run=command_prepare)
    status = sub.add_parser("status")
    status.add_argument("--origin", required=True)
    status.set_defaults(run=lambda args: TrustedDeviceStore(args.origin).status())
    forget = sub.add_parser("forget-local")
    forget.add_argument("--origin", required=True)
    forget.set_defaults(run=lambda args: (TrustedDeviceStore(args.origin).forget_local() or {"forgotten": True}))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.run(args)
    except TrustedDeviceError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        print("Trusted device helper gagal tanpa menyimpan credential dalam output.", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
