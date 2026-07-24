from __future__ import annotations

import re
import time
from dataclasses import dataclass

ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MEDIA_FILE_RE = r"(?:[A-Za-z0-9][A-Za-z0-9+._-]*)"


@dataclass(frozen=True)
class CommandProgress:
    line: str
    stream_name: str
    updated_at: float
    percent: float | None = None
    speed: str | None = None
    fraction_current: int | None = None
    fraction_total: int | None = None
    file_name: str | None = None
    message_id: int | None = None


def is_nonsemantic_tdl_output_line(line: str) -> bool:
    return is_tdl_telemetry_line(line) or is_standalone_tdl_progress_bar(line)


def is_tdl_telemetry_line(line: str) -> bool:
    return bool(re.match(r"^CPU:\s+\d", line))


def is_standalone_tdl_progress_bar(line: str) -> bool:
    if " -> " in line or parse_message_id(line) is not None:
        return False
    return bool(
        re.match(r"^\[[#=.>\-\s]+\]\s+\[[^\]]*(?:/s|ETA|\d+s|\d+m|\d+h)[^\]]*\]$", line)
    )


def clean_tdl_output_line(line: str) -> str:
    cleaned = line.rstrip("\r\n")
    if "\r" in cleaned:
        parts = [part for part in cleaned.split("\r") if part.strip()]
        cleaned = parts[-1] if parts else ""
    cleaned = ANSI_ESCAPE_RE.sub("", cleaned)
    cleaned = CONTROL_CHARS_RE.sub("", cleaned)
    cleaned = cleaned.replace("\u001b", "")
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_tdl_progress_line(line: str, stream_name: str) -> CommandProgress:
    clean_line = clean_tdl_output_line(line)
    fraction_current, fraction_total = parse_fraction(clean_line)
    return CommandProgress(
        line=clean_line,
        stream_name=stream_name,
        updated_at=time.time(),
        percent=parse_percent(clean_line),
        speed=parse_speed(clean_line),
        fraction_current=fraction_current,
        fraction_total=fraction_total,
        file_name=parse_file_name(clean_line),
        message_id=parse_message_id(clean_line),
    )


def parse_percent(line: str) -> float | None:
    match = re.search(r"(?<!\d)(100(?:\.0+)?|\d{1,2}(?:\.\d+)?)\s*%", line)
    return float(match.group(1)) if match else None


def parse_speed(line: str) -> str | None:
    match = re.search(
        r"(\d+(?:\.\d+)?\s*(?:[KMGT]?i?B|B)/s)", line, flags=re.IGNORECASE
    )
    if match:
        return match.group(1)
    match = re.search(
        r"(\d+(?:\.\d+)?\s*(?:KB|MB|GB|TB|B)\s*/\s*s)", line, flags=re.IGNORECASE
    )
    return re.sub(r"\s+", "", match.group(1)) if match else None


def parse_fraction(line: str) -> tuple[int | None, int | None]:
    candidates = []
    for match in re.finditer(r"(?<!\d)(\d{1,6})\s*/\s*(\d{1,6})(?!\d)", line):
        current = int(match.group(1))
        total = int(match.group(2))
        if total > 0 and current <= total:
            candidates.append((current, total))
    return candidates[-1] if candidates else (None, None)


def parse_message_id(line: str) -> int | None:
    # Ignore clipped terminal redraw fragments such as ":2~ ...".
    match = re.search(r":(\d{1,12})\s*->", line)
    return int(match.group(1)) if match else None


def parse_upload_message_id(output: str) -> int | None:
    """Return the last Telegram message id emitted by ``tdl up``."""
    found = [parse_message_id(line) for line in output.splitlines()]
    ids = [item for item in found if item is not None]
    return ids[-1] if ids else None


def parse_file_name(line: str) -> str | None:
    quoted = re.search(rf"['\"]([^'\"]+\.{MEDIA_FILE_RE})['\"]", line, re.IGNORECASE)
    if quoted:
        return quoted.group(1)
    bare = re.search(rf"([^\s/\\]+\.{MEDIA_FILE_RE})", line, re.IGNORECASE)
    return bare.group(1) if bare else None
