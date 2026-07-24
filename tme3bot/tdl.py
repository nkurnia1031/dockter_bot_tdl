from __future__ import annotations

import json
import logging
import os
import queue
import shlex
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


class SubprocessRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_process: subprocess.Popen[bytes] | None = None
        self._current_command: list[str] | None = None
        self._last_output_at: float | None = None

    def run(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        log_prefix: str = "tdl",
        stall_timeout_seconds: int = 0,
        progress_callback: ProgressCallback | None = None,
    ) -> subprocess.CompletedProcess[str]:
        process_command = prepare_subprocess_command(command, env)
        if process_command == command:
            LOGGER.info("%s start: %s", log_prefix, " ".join(command))
        else:
            LOGGER.info("%s start via pseudo-tty: %s", log_prefix, " ".join(command))
        started_at = time.time()
        output_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        try:
            process = subprocess.Popen(
                process_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
                env=env,
            )
        except FileNotFoundError as exc:
            raise TDLCommandError(command, -1, "", str(exc)) from exc

        with self._lock:
            self._current_process = process
            self._current_command = command
            self._last_output_at = started_at

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
                    break
                time.sleep(0.2)

            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            self._drain_output(
                output_queue, stdout_lines, stderr_lines, log_prefix, progress_callback
            )
            returncode = process.poll()
            if returncode is None:
                returncode = process.wait(timeout=5)
        finally:
            with self._lock:
                if self._current_process is process:
                    self._current_process = None
                    self._current_command = None
                    self._last_output_at = None

        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        if returncode != 0:
            self._log_failure_output(log_prefix, returncode, stdout, stderr)
        LOGGER.info("%s finished with exit code %s", log_prefix, returncode)
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    def cancel_current(self) -> bool:
        with self._lock:
            process = self._current_process
            command = self._current_command
        if process is None or process.poll() is not None:
            return False

        LOGGER.warning("Cancelling running TDL command: %s", " ".join(command or []))
        self._terminate_process(process)
        return True

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
    ) -> None:
        while True:
            try:
                stream_name, line = output_queue.get_nowait()
            except queue.Empty:
                return

            clean_line = clean_tdl_output_line(line)
            if not clean_line:
                continue

            target_lines = stderr_lines if stream_name == "stderr" else stdout_lines
            target_lines.append(clean_line + "\n")
            if is_nonsemantic_tdl_output_line(clean_line):
                with self._lock:
                    self._last_output_at = time.time()
                LOGGER.debug(
                    "%s %s skipped nonsemantic tdl line | %s",
                    log_prefix,
                    stream_name,
                    clean_line,
                )
                continue

            progress = parse_tdl_progress_line(clean_line, stream_name)
            with self._lock:
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
        if last_output_at is None:
            return False
        return time.time() - last_output_at > stall_timeout_seconds

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=15)
            return
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)


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

    def export_messages(
        self, chat_ref: str, start_id: int, export_path: Path
    ) -> ExportResult:
        export_path.parent.mkdir(parents=True, exist_ok=True)

        command = self._wrap_command(
            self._base_command()
            + [
                "chat",
                "export",
                "-c",
                chat_ref,
                "-T",
                "id",
                "-i",
                f"{start_id},999999999",
                "-o",
                str(export_path),
            ]
        )
        result = self.runner.run(
            command,
            env=self._command_env(),
            log_prefix=f"{self.log_prefix}:export",
            stall_timeout_seconds=self.stall_timeout_seconds,
            progress_callback=self.progress_callback,
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
        )
        self._ensure_success(command, result)
        return result

    def upload(self, file_path: Path, chat_ref: str, caption: str) -> UploadResult:
        """Upload exactly one file and return its Telegram channel message id."""
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
            command = self._wrap_command(
                self._base_command()
                + ["up", "-p", str(file_path), "-c", chat_ref, "--caption", str(caption_path)]
            )
            result = self.runner.run(
                command,
                env=self._command_env(),
                log_prefix=f"{self.log_prefix}:upload",
                stall_timeout_seconds=self.stall_timeout_seconds,
                progress_callback=self.progress_callback,
            )
            self._ensure_success(command, result)
            message_id = parse_upload_message_id(f"{result.stdout}\n{result.stderr}")
            if message_id is None:
                raise TDLDataError("TDL upload selesai tetapi channel message ID tidak ditemukan.")
            return UploadResult(message_id=message_id, output=f"{result.stdout}\n{result.stderr}")
        finally:
            if caption_path is not None:
                caption_path.unlink(missing_ok=True)

    def cancel_current(self) -> bool:
        return self.runner.cancel_current()

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
