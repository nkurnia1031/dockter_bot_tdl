"""Safe, bounded command output helpers used by worker milestones."""

from __future__ import annotations

from collections.abc import Iterable
import re


COMMAND_OUTPUT_LINES = 40
COMMAND_OUTPUT_BYTES = 8 * 1024
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(password|passphrase|token|secret|credential|api[_-]?key)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)


def sanitize_text(value: object, secrets: Iterable[str] = ()) -> str:
    """Remove known and obvious secret values from command output."""
    result = str(value)
    for secret in secrets:
        secret_value = str(secret)
        if secret_value:
            result = result.replace(secret_value, "[redacted]")
    return _SENSITIVE_ASSIGNMENT.sub(r"\1\2[redacted]", result)


def bounded_output_tail(output: str, *, max_lines: int = COMMAND_OUTPUT_LINES, max_bytes: int = COMMAND_OUTPUT_BYTES) -> tuple[list[str], bool]:
    """Return only the newest output without splitting a line when possible."""
    if max_lines <= 0 or max_bytes <= 0:
        return [], bool(str(output or "").strip())
    lines = [line.rstrip() for line in str(output or "").splitlines() if line.strip()]
    truncated = len(lines) > max_lines
    lines = lines[-max_lines:]
    while len(lines) > 1 and sum(len(line.encode("utf-8")) + 1 for line in lines) > max_bytes:
        truncated = True
        lines.pop(0)
    if lines:
        prefix_bytes = sum(len(line.encode("utf-8")) + 1 for line in lines[:-1])
        while len(lines) > 1 and prefix_bytes + 1 > max_bytes:
            truncated = True
            lines.pop(0)
            prefix_bytes = sum(len(line.encode("utf-8")) + 1 for line in lines[:-1])
        allowed_bytes = max(1, max_bytes - prefix_bytes - 1)
        if len(lines[-1].encode("utf-8")) > allowed_bytes:
            raw = lines[-1].encode("utf-8")[-allowed_bytes:]
            lines[-1] = raw.decode("utf-8", errors="replace")
            truncated = True
    if lines and sum(len(line.encode("utf-8")) + 1 for line in lines) > max_bytes:
        # Defensive fallback for unusual multi-byte boundaries.
        raw = lines[-1].encode("utf-8")[-max(1, max_bytes - 1):]
        lines[-1] = raw.decode("utf-8", errors="replace")
        truncated = True
    return lines, truncated


def sanitize_command(command: Iterable[object], secrets: Iterable[str] = ()) -> list[str]:
    """Redact obvious secret flags and values before persisting a command."""
    secret_values = [str(value) for value in secrets if str(value)]
    result: list[str] = []
    redact_next = False
    sensitive_flags = {
        "--password",
        "--token",
        "--secret",
        "--credential",
        "--credentials",
    }
    for raw in command:
        value = sanitize_text(raw, secret_values)
        if redact_next:
            result.append("[redacted]")
            redact_next = False
            continue
        flag = value.split("=", 1)[0].casefold()
        if flag in sensitive_flags:
            result.append(value.split("=", 1)[0] + ("=[redacted]" if "=" in value else ""))
            redact_next = "=" not in value
            continue
        result.append(value)
    return result
