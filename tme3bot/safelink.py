"""Input validation shared by the Safelink API and resolver worker."""

from __future__ import annotations

from urllib.parse import urlsplit


ALLOWED_SHORTLINK_HOSTS = frozenset({"pndk.to", "go.fakta.id"})
MAX_SHORTLINK_LENGTH = 2048


def normalize_shortlink_url(value: object) -> str:
    """Validate and normalize a supported HTTP(S) shortlink without I/O."""
    raw = str(value or "").strip()
    if not raw or len(raw) > MAX_SHORTLINK_LENGTH:
        raise ValueError("URL shortlink wajib diisi dan maksimal 2.048 karakter.")
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        # Force validation of malformed/out-of-range ports too.
        parsed.port
    except (UnicodeError, ValueError):
        raise ValueError("Format URL shortlink tidak valid.") from None
    if parsed.scheme.lower() not in {"http", "https"} or not host:
        raise ValueError("URL harus menggunakan HTTP atau HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL dengan kredensial tidak diizinkan.")
    if host not in ALLOWED_SHORTLINK_HOSTS:
        raise ValueError("Domain shortlink yang didukung hanya pndk.to dan go.fakta.id.")
    if parsed.fragment:
        # Fragments are not sent to the server and have no role in the source flow.
        return raw
    return raw
