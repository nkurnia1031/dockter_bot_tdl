from __future__ import annotations

import json
import logging
import os
import queue
import shlex
import signal
import subprocess
import threading
import time
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tme3bot.media import has_downloadable_media
from tme3bot.tdl_output import (
    CommandProgress,
    clean_tdl_output_line,
    is_nonsemantic_tdl_output_line,
    parse_tdl_progress_line,
    parse_upload_message_id,
)

LOGGER = logging.getLogger(__name__)


class ProcessStalledError(RuntimeError):
    """Raised when a worker subprocess stops making meaningful progress."""

    def __init__(self, message: str, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(message)


class TDLCommandError(RuntimeError):
    def __init__(
        self, command: list[str], returncode: int, stdout: str, stderr: str
    ) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        detail = stderr.strip() or stdout.strip() or "unknown error"
        super().__init__(f"TDL command failed ({returncode}): {detail}")


def pause_process_group(process: subprocess.Popen[Any]) -> bool:
    if process.poll() is not None or os.name == "nt":  # pragma: no cover - workers run on Linux
        return False
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGSTOP)
        return True
    except (OSError, ProcessLookupError):
        return False


def resume_process_group(process: subprocess.Popen[Any]) -> bool:
    if process.poll() is not None or os.name == "nt":  # pragma: no cover - workers run on Linux
        return False
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGCONT)
        return True
    except (OSError, ProcessLookupError):
        return False


class TDLStalledError(TDLCommandError):
    """Raised when a TDL subprocess stops making semantic progress."""

    def __init__(
        self,
        command: list[str],
        returncode: int,
        stdout: str,
        stderr: str,
        timeout_seconds: int,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(command, returncode, stdout, stderr)
        self.args = (
            f"TDL command stalled for {timeout_seconds}s: {' '.join(command)}",
        )


class TDLDataError(RuntimeError):
    """Raised when TDL returns unusable or malformed export data."""


@dataclass
class ExportResult:
    export_path: Path
    messages: list[dict[str, Any]]
    exported_count: int
    max_message_id: int | None
    has_media: bool


@dataclass
class UploadResult:
    message_id: int
    output: str


ProgressCallback = Callable[[CommandProgress], None]
OutputCallback = Callable[[str], None]
CommandCallback = Callable[[list[str], int, str, float, str], None]


def notify_command_started(
    callback: CommandCallback | None,
    command: list[str],
    log_prefix: str,
) -> object | None:
    """Notify an observer without making telemetry a process dependency.

    New observers may expose ``command_started`` and return an opaque command
    id which is passed back to ``notify_command_completed``.  The callable
    callback form remains supported for older integrations.
    """
    if callback is None:
        return None
    observer = getattr(callback, "command_started", None)
    declared = getattr(type(callback), "command_started", None)
    if callable(observer) and callable(declared):
        try:
            return observer(command, log_prefix)
        except Exception:
            LOGGER.warning("Command start callback failed for %s", log_prefix, exc_info=True)
            return None
    return None


def notify_command_completed(
    callback: CommandCallback | None,
    command: list[str],
    returncode: int,
    output: str,
    duration_seconds: float,
    log_prefix: str,
    command_id: object | None = None,
) -> None:
    """Notify completion, supporting both new and legacy command observers."""
    if callback is None:
        return
    observer = getattr(callback, "command_completed", None)
    declared = getattr(type(callback), "command_completed", None)
    try:
        if callable(observer) and callable(declared):
            observer(
                command,
                returncode,
                output,
                duration_seconds,
                log_prefix,
                command_id,
            )
        else:
            callback(command, returncode, output, duration_seconds, log_prefix)
    except Exception:
        LOGGER.warning("Command callback failed for %s", log_prefix, exc_info=True)


class SubprocessRunner:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pause_condition = threading.Condition(self._lock)
        self._pause_requested = False
        self._paused = False
        self._pause_owner: str | None = None
        self._current_process: subprocess.Popen[bytes] | None = None
        self._current_command: list[str] | None = None
        self._current_owner: str | None = None
        self._last_output_at: float | None = None
        self._last_progress_signature: tuple[Any, ...] | None = None

    def run(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        log_prefix: str = "tdl",
        stall_timeout_seconds: int = 0,
        progress_callback: ProgressCallback | None = None,
        output_callback: OutputCallback | None = None,
        command_callback: CommandCallback | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command_owner = str(getattr(command_callback, "job_id", "") or "") or None
        with self._pause_condition:
            while self._pause_requested and self._pause_owner in {None, command_owner}:
                self._pause_condition.wait(timeout=1.0)
        process_command = prepare_subprocess_command(command, env)
        if process_command == command:
            LOGGER.info("%s start: %s", log_prefix, " ".join(command))
        else:
            LOGGER.info("%s start via pseudo-tty: %s", log_prefix, " ".join(command))
        if output_callback is not None:
            output_callback(f"$ {' '.join(command)}")
        started_at = time.time()
        started_monotonic = time.monotonic()
        output_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        stalled = False

        try:
            process = subprocess.Popen(
                process_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
                env=env,
                start_new_session=os.name != "nt",
            )
        except FileNotFoundError as exc:
            if command_callback is not None:
                notify_command_completed(
                    command_callback,
                    command,
                    -1,
                    str(exc),
                    max(0.0, time.monotonic() - started_monotonic),
                    log_prefix,
                )
            raise TDLCommandError(command, -1, "", str(exc)) from exc

        command_id = notify_command_started(command_callback, command, log_prefix)

        with self._lock:
            self._current_process = process
            self._current_command = command
            self._current_owner = command_owner
            self._last_output_at = started_at
            self._last_progress_signature = None

        stdout_thread = threading.Thread(
            target=self._read_stream,
            args=(process.stdout, "stdout", output_queue),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._read_stream,
            args=(process.stderr, "stderr", output_queue),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        try:
            while process.poll() is None:
                self._drain_output(
                    output_queue,
                    stdout_lines,
                    stderr_lines,
                    log_prefix,
                    progress_callback,
                    output_callback,
                )
                if stall_timeout_seconds > 0 and self._is_stalled(
                    stall_timeout_seconds
                ):
                    LOGGER.error(
                        "%s stalled for %ss; terminating process",
                        log_prefix,
                        stall_timeout_seconds,
                    )
                    self._terminate_process(process)
                    stalled = True
                    break
                time.sleep(0.2)

            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            self._drain_output(
                output_queue, stdout_lines, stderr_lines, log_prefix, progress_callback, output_callback
            )
            returncode = process.poll()
            if returncode is None:
                returncode = process.wait(timeout=5)
        finally:
            with self._lock:
                if self._current_process is process:
                    self._current_process = None
                    self._current_command = None
                    self._current_owner = None
                    self._last_output_at = None
                    self._last_progress_signature = None
                    self._paused = False
                    self._pause_requested = False
                    self._pause_owner = None
                    self._pause_condition.notify_all()

        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        if returncode != 0:
            self._log_failure_output(log_prefix, returncode, stdout, stderr)
        LOGGER.info("%s finished with exit code %s", log_prefix, returncode)
        if output_callback is not None:
            output_callback(f"[process exited with code {returncode}]")
        if command_callback is not None:
            notify_command_completed(
                command_callback,
                command,
                int(returncode),
                f"{stdout}\n{stderr}",
                max(0.0, time.monotonic() - started_monotonic),
                log_prefix,
                command_id,
            )
        if stalled:
            raise TDLStalledError(
                command,
                returncode,
                stdout,
                stderr,
                stall_timeout_seconds,
            )
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    def cancel_current(self) -> bool:
        return self.interrupt_current()

    def pause_current(self, owner_job_id: str | None = None) -> bool:
        with self._pause_condition:
            owner = str(owner_job_id) if owner_job_id is not None else None
            process = self._current_process
            if process is not None and owner is not None and self._current_owner != owner:
                return False
            self._pause_requested = True
            self._pause_owner = owner
            if process is None or process.poll() is not None:
                return True
            try:
                if os.name == "nt":  # pragma: no cover - production workers run on Linux
                    return False
                os.killpg(os.getpgid(process.pid), signal.SIGSTOP)
                self._paused = True
                return True
            except (OSError, ProcessLookupError):
                return False

    def resume_current(self, owner_job_id: str | None = None) -> bool:
        with self._pause_condition:
            process = self._current_process
            owner = str(owner_job_id) if owner_job_id is not None else None
            if owner is not None and self._pause_owner not in {None, owner}:
                return False
            if process is not None and owner is not None and self._current_owner != owner:
                return False
            resumed = process is None or process.poll() is not None
            if process is not None and process.poll() is None and self._paused:
                try:
                    if os.name == "nt":  # pragma: no cover - production workers run on Linux
                        return False
                    os.killpg(os.getpgid(process.pid), signal.SIGCONT)
                    resumed = True
                except (OSError, ProcessLookupError):
                    resumed = False
            self._paused = False
            self._pause_requested = False
            self._pause_owner = None
            if process is not None:
                self._last_output_at = time.time()
            self._pause_condition.notify_all()
            return resumed

    def interrupt_current(self) -> bool:
        with self._lock:
            process = self._current_process
            command = self._current_command
        if process is None or process.poll() is not None:
            return False

        LOGGER.warning("Interrupting running TDL command: %s", " ".join(command or []))
        self._interrupt_process(process)
        return True

    @staticmethod
    def _interrupt_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name != "nt":
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGINT)
            except ProcessLookupError:
                return
        else:  # pragma: no cover - production workers run on Linux
            process.send_signal(signal.CTRL_BREAK_EVENT)
        try:
            process.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            SubprocessRunner._terminate_process(process)

    @staticmethod
    def _read_stream(
        stream: Any,
        stream_name: str,
        output_queue: queue.Queue[tuple[str, str]],
    ) -> None:
        if stream is None:
            return
        try:
            for raw_line in iter(stream.readline, b""):
                output_queue.put(
                    (stream_name, decode_process_output(raw_line))
                )
        except Exception as exc:  # pragma: no cover - defensive pipe reader guard
            output_queue.put(
                (
                    "stderr",
                    f"tdl {stream_name} reader failed: {exc!r}\n",
                )
            )
        finally:
            stream.close()

    def _drain_output(
        self,
        output_queue: queue.Queue[tuple[str, str]],
        stdout_lines: list[str],
        stderr_lines: list[str],
        log_prefix: str,
        progress_callback: ProgressCallback | None,
        output_callback: OutputCallback | None,
    ) -> None:
        while True:
            try:
                stream_name, line = output_queue.get_nowait()
            except queue.Empty:
                return

            clean_line = clean_tdl_output_line(line)
            if not clean_line:
                continue

            if output_callback is not None:
                output_callback(clean_line)

            target_lines = stderr_lines if stream_name == "stderr" else stdout_lines
            target_lines.append(clean_line + "\n")
            if is_nonsemantic_tdl_output_line(clean_line):
                LOGGER.debug(
                    "%s %s skipped nonsemantic tdl line | %s",
                    log_prefix,
                    stream_name,
                    clean_line,
                )
                continue

            progress = parse_tdl_progress_line(clean_line, stream_name)
            signature = self._progress_signature(progress)
            with self._lock:
                if signature != self._last_progress_signature:
                    self._last_progress_signature = signature
                    self._last_output_at = progress.updated_at

            if progress_callback is not None:
                try:
                    progress_callback(progress)
                except (
                    Exception
                ):  # pragma: no cover - progress UI should never kill tdl
                    LOGGER.exception("Progress callback failed")

            if stream_name == "stderr":
                LOGGER.warning("%s stderr | %s", log_prefix, clean_line)
            else:
                LOGGER.info("%s stdout | %s", log_prefix, clean_line)

    @staticmethod
    def _log_failure_output(
        log_prefix: str,
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        LOGGER.error(
            "%s failed with exit code %s; complete captured output follows",
            log_prefix,
            returncode,
        )
        for stream_name, output in (("stdout", stdout), ("stderr", stderr)):
            lines = output.rstrip("\n").splitlines() or ["<empty>"]
            for index, line in enumerate(lines, start=1):
                LOGGER.error(
                    "%s failure %s[%s] | %s",
                    log_prefix,
                    stream_name,
                    index,
                    line,
                )

    def _is_stalled(self, stall_timeout_seconds: int) -> bool:
        with self._lock:
            last_output_at = self._last_output_at
            paused = self._paused
        if paused:
            return False
        if last_output_at is None:
            return False
        return time.time() - last_output_at > stall_timeout_seconds

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name != "nt":
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except ProcessLookupError:
                return
        else:  # pragma: no cover - production workers run on Linux
            process.terminate()
        try:
            process.wait(timeout=15)
            return
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    return
            else:  # pragma: no cover - production workers run on Linux
                process.kill()
            process.wait(timeout=15)

    @staticmethod
    def _progress_signature(progress: CommandProgress) -> tuple[Any, ...]:
        values = (
            progress.message_id,
            progress.fraction_current,
            progress.fraction_total,
            progress.percent,
            progress.transferred_bytes,
            progress.file_name,
        )
        if any(value is not None for value in values):
            return ("progress", *values)
        return ("line", progress.line)


def prepare_subprocess_command(
    command: list[str], env: dict[str, str] | None
) -> list[str]:
    if os.name == "nt":
        return command

    effective_env = env or os.environ
    force_pty = effective_env.get("TDL_FORCE_PTY", "1").strip().lower()
    if force_pty in {"0", "false", "no", "off"}:
        return command

    columns = parse_terminal_size(
        effective_env.get("TDL_TERMINAL_COLUMNS"), default=300, minimum=120
    )
    rows = parse_terminal_size(
        effective_env.get("TDL_TERMINAL_ROWS"), default=40, minimum=20
    )
    shell_command = f"stty cols {columns} rows {rows}; exec {shlex.join(command)}"
    return ["script", "-q", "-e", "-c", shell_command, "/dev/null"]


def decode_process_output(raw_line: bytes | str) -> str:
    if isinstance(raw_line, str):
        return raw_line
    return raw_line.decode("utf-8", errors="backslashreplace")


def parse_terminal_size(value: str | None, default: int, minimum: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        parsed = default
    return max(parsed, minimum)


def _normalize_upload_caption(value: str) -> str:
    return " ".join(str(value).split()).strip().casefold()


def _message_contains_caption(message: dict[str, Any], normalized_caption: str) -> bool:
    """Match captions across the different JSON shapes emitted by TDL."""
    if not normalized_caption:
        return False

    def visit(value: Any) -> bool:
        if isinstance(value, str):
            return normalized_caption in _normalize_upload_caption(value)
        if isinstance(value, dict):
            return any(visit(item) for item in value.values())
        if isinstance(value, list):
            return any(visit(item) for item in value)
        return False

    return visit(message)


class TDLClient:
    def __init__(
        self,
        storage_root: Path,
        namespace: str,
        runner: SubprocessRunner | None = None,
        debug: bool = False,
        run_as_user: str | None = None,
        home: Path | None = None,
        log_prefix: str = "tdl",
        stall_timeout_seconds: int = 0,
        progress_callback: ProgressCallback | None = None,
        output_callback: OutputCallback | None = None,
        command_callback: CommandCallback | None = None,
        upload_resolve_timeout_seconds: float | None = None,
        upload_resolve_interval_seconds: float | None = None,
    ) -> None:
        self.storage_root = storage_root
        self.namespace = namespace
        self.runner = runner or SubprocessRunner()
        self.debug = debug
        self.run_as_user = run_as_user
        self.home = home
        self.log_prefix = log_prefix
        self.stall_timeout_seconds = stall_timeout_seconds
        self.progress_callback = progress_callback
        self.output_callback = output_callback
        self.command_callback = command_callback
        self.upload_resolve_timeout_seconds = (
            float(upload_resolve_timeout_seconds)
            if upload_resolve_timeout_seconds is not None
            else float(os.getenv("TDL_UPLOAD_RESOLVE_TIMEOUT_SECONDS", "300"))
        )
        self.upload_resolve_interval_seconds = (
            float(upload_resolve_interval_seconds)
            if upload_resolve_interval_seconds is not None
            else float(os.getenv("TDL_UPLOAD_RESOLVE_INTERVAL_SECONDS", "5"))
        )

    def export_messages(
        self,
        chat_ref: str,
        start_id: int,
        export_path: Path,
        *,
        with_content: bool = False,
        last_count: int | None = None,
        end_id: int | None = None,
    ) -> ExportResult:
        export_path.parent.mkdir(parents=True, exist_ok=True)

        export_args = ["chat", "export", "-c", chat_ref]
        if last_count is not None:
            export_args.extend(["-T", "last", "-i", str(max(1, last_count))])
        else:
            end = 999999999 if end_id is None else max(start_id, int(end_id))
            export_args.extend(["-T", "id", "-i", f"{start_id},{end}"])
        export_args.extend(["-o", str(export_path)])
        if with_content:
            export_args.append("--with-content")
        command = self._wrap_command(self._base_command() + export_args)
        result = self.runner.run(
            command,
            env=self._command_env(),
            log_prefix=f"{self.log_prefix}:export",
            stall_timeout_seconds=self.stall_timeout_seconds,
            progress_callback=self.progress_callback,
            output_callback=self.output_callback,
            **({"command_callback": self.command_callback} if self.command_callback is not None else {}),
        )
        self._ensure_success(command, result)

        if not export_path.exists():
            raise TDLDataError(f"TDL tidak membuat file export: {export_path}")

        payload = json.loads(export_path.read_text(encoding="utf-8"))
        messages_raw = payload.get("messages", [])
        if not isinstance(messages_raw, list):
            raise TDLDataError(
                "Format export tidak valid: 'messages' harus berupa array."
            )

        messages = [message for message in messages_raw if isinstance(message, dict)]
        max_message_id = max(
            (
                message.get("id")
                for message in messages
                if isinstance(message.get("id"), int)
            ),
            default=None,
        )
        has_media = any(has_downloadable_media(message) for message in messages)

        return ExportResult(
            export_path=export_path,
            messages=messages,
            exported_count=len(messages),
            max_message_id=max_message_id,
            has_media=has_media,
        )

    def download(
        self, export_path: Path, download_dir: Path
    ) -> subprocess.CompletedProcess[str]:
        download_dir.mkdir(parents=True, exist_ok=True)
        command = self._wrap_command(
            self._base_command()
            + [
                "dl",
                "-f",
                str(export_path),
                "-d",
                str(download_dir),
                "--template",
                "{{ .MessageID }}_{{.FileName}}",
                "--continue",
                "--skip-same",
            ]
        )
        result = self.runner.run(
            command,
            env=self._command_env(),
            log_prefix=f"{self.log_prefix}:download",
            stall_timeout_seconds=self.stall_timeout_seconds,
            progress_callback=self.progress_callback,
            output_callback=self.output_callback,
            **({"command_callback": self.command_callback} if self.command_callback is not None else {}),
        )
        self._ensure_success(command, result)
        return result

    def download_url(
        self, url: str, download_dir: Path
    ) -> subprocess.CompletedProcess[str]:
        download_dir.mkdir(parents=True, exist_ok=True)
        command = self._wrap_command(
            self._base_command()
            + [
                "dl",
                "-u",
                url,
                "-d",
                str(download_dir),
                "--template",
                "{{.FileName}}",
                "--continue",
                "--skip-same",
            ]
        )
        result = self.runner.run(
            command,
            env=self._command_env(),
            log_prefix=f"{self.log_prefix}:download-url",
            stall_timeout_seconds=self.stall_timeout_seconds,
            progress_callback=self.progress_callback,
            output_callback=self.output_callback,
            **({"command_callback": self.command_callback} if self.command_callback is not None else {}),
        )
        self._ensure_success(command, result)
        return result

    def upload(
        self,
        file_path: Path,
        chat_ref: str,
        caption: str,
        resolve_after_id: int | None = None,
        status_callback: Callable[[str], None] | None = None,
        as_photo: bool = False,
    ) -> UploadResult:
        """Upload one file and optionally force it to Telegram photo media."""
        if not file_path.is_file():
            raise TDLDataError(f"File upload tidak ditemukan: {file_path}")
        # tdl parses --caption as an expression. Passing raw text makes values
        # such as `#backup` or `node=local` fail during expression parsing.
        # Store a JSON-quoted constant expression in a temporary caption file,
        # following the documented `--caption caption.txt` form.
        caption_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="tme3bot-caption-",
                suffix=".txt",
                delete=False,
            ) as handle:
                handle.write(json.dumps(str(caption), ensure_ascii=False))
                handle.write("\n")
                caption_path = Path(handle.name)
            # Upload sessions may run through `runuser -u user1`.
            caption_path.chmod(0o644)
            upload_args = ["up", "-p", str(file_path), "-c", chat_ref]
            if as_photo:
                upload_args.append("--photo")
            upload_args.extend(["--caption", str(caption_path)])
            command = self._wrap_command(self._base_command() + upload_args)
            if status_callback is not None:
                status_callback("uploading")
            result = self.runner.run(
                command,
                env=self._command_env(),
                log_prefix=f"{self.log_prefix}:upload",
                stall_timeout_seconds=self.stall_timeout_seconds,
                progress_callback=self.progress_callback,
                output_callback=self.output_callback,
                **({"command_callback": self.command_callback} if self.command_callback is not None else {}),
            )
            self._ensure_success(command, result)
            message_id = parse_upload_message_id(f"{result.stdout}\n{result.stderr}")
            if message_id is None:
                if status_callback is not None:
                    status_callback("resolving_message")
                message_id = self._wait_for_upload_message_id(
                    chat_ref,
                    caption,
                    resolve_after_id=resolve_after_id,
                )
            if message_id is None:
                raise TDLDataError(
                    "TDL upload selesai tetapi channel message ID tidak ditemukan "
                    f"dalam {self.upload_resolve_timeout_seconds:g} detik."
                )
            if status_callback is not None:
                status_callback("uploaded")
            return UploadResult(message_id=message_id, output=f"{result.stdout}\n{result.stderr}")
        finally:
            if caption_path is not None:
                caption_path.unlink(missing_ok=True)

    def _wait_for_upload_message_id(
        self,
        chat_ref: str,
        caption: str,
        *,
        resolve_after_id: int | None = None,
    ) -> int | None:
        """Resolve delayed TDL upload results by polling channel history.

        Some TDL versions return exit code 0 and ``done!`` but omit the
        message id.  The upload itself is still valid; exporting the channel
        history lets us find the message once Telegram has committed it.
        The timeout is deliberately bounded so a genuinely broken upload does
        not leave a worker job running forever.
        """
        timeout = max(0.0, self.upload_resolve_timeout_seconds)
        interval = max(0.0, self.upload_resolve_interval_seconds)
        deadline = time.monotonic() + timeout
        start_id = max(1, int(resolve_after_id or 0) + 1)
        normalized_caption = _normalize_upload_caption(caption)

        while True:
            export_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", prefix="tme3bot-upload-resolve-", delete=False
                ) as handle:
                    export_path = Path(handle.name)
                # The resolver can run TDL through ``runuser -u user1``. A
                # NamedTemporaryFile belongs to root and defaults to 0600, so
                # user1 could not overwrite it with the exported JSON.
                # /tmp itself is sticky; making this one random output file
                # writable is limited to the short lookup window.
                export_path.chmod(0o666)
                exported = self.export_messages(
                    chat_ref,
                    start_id,
                    export_path,
                    with_content=True,
                    last_count=(
                        None
                        if resolve_after_id is not None
                        else max(
                            1,
                            int(os.getenv("TDL_UPLOAD_RESOLVE_LAST_COUNT", "100")),
                        )
                    ),
                )
                for message in reversed(exported.messages):
                    message_id = message.get("id")
                    if isinstance(message_id, int) and _message_contains_caption(
                        message, normalized_caption
                    ):
                        LOGGER.info(
                            "%s upload message id resolved after delayed TDL result: %s",
                            self.log_prefix,
                            message_id,
                        )
                        return message_id
            except (TDLCommandError, TDLDataError, OSError, json.JSONDecodeError) as exc:
                LOGGER.warning("%s upload result lookup failed; retrying: %s", self.log_prefix, exc)
            finally:
                if export_path is not None:
                    export_path.unlink(missing_ok=True)

            if time.monotonic() >= deadline:
                return None
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))

    def cancel_current(self) -> bool:
        return self.runner.cancel_current()

    def pause_current(self, owner_job_id: str | None = None) -> bool:
        return self.runner.pause_current(owner_job_id)

    def resume_current(self, owner_job_id: str | None = None) -> bool:
        return self.runner.resume_current(owner_job_id)

    def _base_command(self) -> list[str]:
        command = [
            "tdl",
            "--storage",
            f"type=bolt,path={self.storage_root / 'data'}",
            "-n",
            self.namespace,
        ]
        if self.debug:
            command.append("--debug")
        return command

    def _command_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.home is not None:
            env["HOME"] = str(self.home)
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLUMNS", env.get("TDL_TERMINAL_COLUMNS", "300"))
        env.setdefault("LINES", env.get("TDL_TERMINAL_ROWS", "40"))
        env.setdefault("TDL_FORCE_PTY", "1")
        env.setdefault("TDL_TERMINAL_COLUMNS", "300")
        env.setdefault("TDL_TERMINAL_ROWS", "40")
        return env

    def _wrap_command(self, command: list[str]) -> list[str]:
        if not self.run_as_user or self.run_as_user == "root":
            return command
        return ["runuser", "-u", self.run_as_user, "--"] + command

    @staticmethod
    def _ensure_success(
        command: list[str],
        result: subprocess.CompletedProcess[str],
    ) -> None:
        if result.returncode != 0:
            raise TDLCommandError(
                command, result.returncode, result.stdout, result.stderr
            )
