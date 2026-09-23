from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable, Iterable

from tme3bot.command_audit import bounded_output_tail, sanitize_text
from tme3bot.tdl import CommandCallback, SubprocessRunner, TDLCommandError, TDLStalledError
from tme3bot.utility import validate_rclone_destination


class RcloneError(RuntimeError):
    """Raised when an rclone transfer cannot be completed."""


class RcloneRunner:
    """Small, cancellable rclone adapter for files already in the workspace."""

    def __init__(
        self,
        runner: SubprocessRunner | None = None,
        *,
        log_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        stall_timeout_seconds: int = 0,
        command_callback: CommandCallback | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self.stall_timeout_seconds = max(0, int(stall_timeout_seconds))
        self.command_callback = command_callback

    def cancel_current(self) -> bool:
        return self.runner.interrupt_current()

    @staticmethod
    def _command_output(result) -> str:
        output = "\n".join(
            value
            for value in (
                getattr(result, "stdout", "") or "",
                getattr(result, "stderr", "") or "",
            )
            if value
        )
        lines, _ = bounded_output_tail(output, max_lines=12, max_bytes=2048)
        return "\n".join(sanitize_text(line) for line in lines)

    def copy_files(
        self,
        files: Iterable[Path],
        destination: str,
        config_path: Path,
        *,
        workspace_root: Path,
        config_root: Path | None = None,
        remote_names: Iterable[str] | None = None,
    ) -> dict[str, object]:
        destination = str(destination or "").strip()
        try:
            validate_rclone_destination(destination)
        except ValueError as exc:
            raise RcloneError(str(exc)) from exc

        workspace = Path(workspace_root).resolve()
        config = Path(config_path).resolve()
        allowed_config_root = Path(config_root or workspace).resolve()
        try:
            config.relative_to(allowed_config_root)
        except ValueError as exc:
            raise RcloneError(
                "Konfigurasi rclone harus berada di dalam direktori data yang diizinkan."
            ) from exc
        if not config.is_file():
            raise RcloneError(f"Konfigurasi rclone tidak ditemukan: {config}")
        if shutil.which("rclone") is None:
            raise RcloneError("Binary rclone belum tersedia pada worker.")

        paths = [Path(item).resolve() for item in files]
        names = list(remote_names) if remote_names is not None else [path.name for path in paths]
        if len(names) != len(paths):
            raise RcloneError("Jumlah nama tujuan rclone tidak sesuai dengan file.")
        for path in paths:
            try:
                path.relative_to(workspace)
            except ValueError as exc:
                raise RcloneError("File rclone harus berada di dalam workspace.") from exc
            if not path.is_file():
                raise RcloneError(f"File rclone tidak ditemukan: {path.name}")

        uploaded: list[str] = []
        for index, (path, remote_name) in enumerate(zip(paths, names), start=1):
            if self.cancel_check is not None and self.cancel_check():
                raise RcloneError("Upload rclone dibatalkan oleh user.")
            remote_name = str(remote_name).replace("\\", "/").strip("/")
            remote_parts = [part for part in remote_name.split("/") if part]
            if not remote_parts or any(part in {".", ".."} for part in remote_parts):
                raise RcloneError(f"Nama tujuan rclone tidak valid untuk {path.name}.")
            target = f"{destination.rstrip('/')}/{'/'.join(remote_parts)}"
            command = [
                "rclone",
                "copyto",
                str(path),
                target,
                "--config",
                str(config),
                "--log-level",
                "ERROR",
            ]
            try:
                result = self.runner.run(
                    command,
                    log_prefix="rclone-upload",
                    output_callback=self.log_callback,
                    stall_timeout_seconds=self.stall_timeout_seconds,
                    command_callback=self.command_callback,
                )
            except TDLStalledError:
                raise
            except TDLCommandError as exc:
                raise RcloneError(
                    f"rclone gagal untuk {path.name} (exit code {exc.returncode})."
                ) from exc
            if result.returncode != 0:
                raise RcloneError(
                    f"rclone gagal untuk {path.name} (exit code {result.returncode})."
                )
            uploaded.append("/".join(remote_parts))
            if self.progress_callback is not None:
                self.progress_callback(index, len(paths), "/".join(remote_parts))
        return {
            "destination": destination,
            "total": len(paths),
            "succeeded": len(uploaded),
            "files": uploaded,
        }

    def verify_files(
        self,
        files: Iterable[Path],
        destination: str,
        config_path: Path,
        *,
        workspace_root: Path,
        config_root: Path | None = None,
        remote_names: Iterable[str] | None = None,
    ) -> dict[str, object]:
        """Verify exact remote files without downloading or mutating them."""
        destination = str(destination or "").strip()
        try:
            validate_rclone_destination(destination)
        except ValueError as exc:
            raise RcloneError(str(exc)) from exc
        workspace = Path(workspace_root).resolve()
        config = Path(config_path).resolve()
        allowed_config_root = Path(config_root or workspace).resolve()
        try:
            config.relative_to(allowed_config_root)
        except ValueError as exc:
            raise RcloneError(
                "Konfigurasi rclone harus berada di dalam direktori data yang diizinkan."
            ) from exc
        if not config.is_file():
            raise RcloneError(f"Konfigurasi rclone tidak ditemukan: {config}")
        if shutil.which("rclone") is None:
            raise RcloneError("Binary rclone belum tersedia pada worker.")

        paths = [Path(item).resolve() for item in files]
        names = list(remote_names) if remote_names is not None else [path.name for path in paths]
        if len(names) != len(paths):
            raise RcloneError("Jumlah nama tujuan rclone tidak sesuai dengan file.")
        for path in paths:
            try:
                path.relative_to(workspace)
            except ValueError as exc:
                raise RcloneError("File rclone harus berada di dalam workspace.") from exc
            if not path.is_file():
                raise RcloneError(f"File rclone tidak ditemukan: {path.name}")

        self._verify_destination_access(
            destination,
            config,
            log_prefix="rclone-verify-preflight",
        )

        found: list[str] = []
        missing: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []
        inventory: list[dict[str, object]] | None = None
        inventory_error: str | None = None

        def remote_inventory() -> list[dict[str, object]] | None:
            nonlocal inventory, inventory_error
            if inventory is not None or inventory_error is not None:
                return inventory
            command = [
                "rclone",
                "lsjson",
                destination,
                "--files-only",
                "--recursive",
                "--config",
                str(config),
                "--log-level",
                "ERROR",
            ]
            try:
                result = self.runner.run(
                    command,
                    log_prefix="rclone-verify-inventory",
                    output_callback=self.log_callback,
                    stall_timeout_seconds=self.stall_timeout_seconds,
                    command_callback=self.command_callback,
                )
            except (TDLStalledError, TDLCommandError, OSError) as exc:
                inventory_error = str(exc)[:400]
                return None
            if result.returncode != 0:
                inventory_error = (
                    f"exit code {result.returncode}: "
                    f"{self._command_output(result) or 'detail tidak tersedia'}"
                )[:500]
                return None
            try:
                value = json.loads(getattr(result, "stdout", "") or "")
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                inventory_error = f"output lsjson tidak valid: {exc}"[:500]
                return None
            if not isinstance(value, list):
                inventory_error = "output lsjson bukan daftar file."[:500]
                return None
            inventory = [item for item in value if isinstance(item, dict)]
            return inventory

        def inventory_matches(remote_name: str, local_size: int) -> tuple[bool, bool]:
            entries = remote_inventory()
            if entries is None:
                return False, False
            normalized_name = remote_name.strip("/")
            has_name = False
            for entry in entries:
                candidate = str(entry.get("Path") or entry.get("Name") or "")
                candidate = candidate.replace("\\", "/").strip("/")
                if candidate != normalized_name:
                    continue
                has_name = True
                try:
                    if int(entry.get("Size")) == int(local_size):
                        return True, True
                except (TypeError, ValueError):
                    continue
            return False, has_name

        for path, raw_name in zip(paths, names):
            remote_name = str(raw_name).replace("\\", "/").strip("/")
            remote_parts = [part for part in remote_name.split("/") if part]
            if not remote_parts or any(part in {".", ".."} for part in remote_parts):
                raise RcloneError(f"Nama tujuan rclone tidak valid untuk {path.name}.")
            target = f"{destination.rstrip('/')}/{'/'.join(remote_parts)}"
            command = [
                "rclone",
                "check",
                str(path),
                target,
                "--size-only",
                "--config",
                str(config),
                "--log-level",
                "ERROR",
            ]
            try:
                result = self.runner.run(
                    command,
                    log_prefix="rclone-verify",
                    output_callback=self.log_callback,
                    stall_timeout_seconds=self.stall_timeout_seconds,
                    command_callback=self.command_callback,
                )
            except (TDLStalledError, TDLCommandError, OSError) as exc:
                errors.append({"name": remote_name, "error": str(exc)[:300]})
                continue
            if result.returncode == 0:
                found.append(remote_name)
            elif int(result.returncode) == 1:
                recovered, has_name = inventory_matches(remote_name, path.stat().st_size)
                if recovered:
                    found.append(remote_name)
                elif inventory_error:
                    errors.append(
                        {
                            "name": remote_name,
                            "error": (
                                "Rclone gagal mengambil daftar file Google Drive: "
                                f"{inventory_error}"
                            )[:500],
                        }
                    )
                else:
                    missing.append(
                        {
                            "name": remote_name,
                            "error": (
                                "File Google Drive ditemukan tetapi ukuran berbeda."
                                if has_name
                                else "File belum ditemukan di lokasi Google Drive yang diharapkan."
                            ),
                        }
                    )
            else:
                errors.append(
                    {
                        "name": remote_name,
                        "error": (
                            f"Rclone gagal memeriksa file (exit code {result.returncode}): "
                            f"{self._command_output(result) or 'detail tidak tersedia'}"
                        )[:500],
                    }
                )
        return {
            "destination": destination,
            "expected": len(paths),
            "found": len(found),
            "files": found,
            "missing": missing,
            "errors": errors,
            "status": "error" if errors else ("complete" if not missing else "incomplete"),
        }

    def _verify_destination_access(
        self,
        destination: str,
        config: Path,
        *,
        log_prefix: str,
    ) -> None:
        """Check remote/config access separately from per-file differences."""
        command = [
            "rclone",
            "lsf",
            destination,
            "--max-depth",
            "1",
            "--config",
            str(config),
            "--log-level",
            "ERROR",
        ]
        try:
            result = self.runner.run(
                command,
                log_prefix=log_prefix,
                output_callback=self.log_callback,
                stall_timeout_seconds=self.stall_timeout_seconds,
                command_callback=self.command_callback,
            )
        except (TDLStalledError, TDLCommandError, OSError) as exc:
            raise RcloneError(
                "Rclone tidak dapat mengakses Google Drive. "
                f"Periksa file konfigurasi {config} dan koneksi remote '{destination}'. "
                f"Detail: {str(exc)[:400]}"
            ) from exc
        if result.returncode != 0:
            detail = self._command_output(result) or "detail tidak tersedia"
            raise RcloneError(
                "Rclone tidak dapat mengakses Google Drive. "
                f"Periksa file konfigurasi {config} dan koneksi remote '{destination}'. "
                f"Detail: {detail[:400]}"
            )
