from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Callable, Iterable

from tme3bot.command_audit import bounded_output_tail, sanitize_text
from tme3bot.tdl import CommandCallback, SubprocessRunner, TDLCommandError, TDLStalledError
from tme3bot.utility import validate_rclone_destination


class RcloneError(RuntimeError):
    """Raised when an rclone transfer cannot be completed."""

    def __init__(self, message: str, *, code: str = "") -> None:
        self.code = str(code or "").strip().upper()
        super().__init__(message)


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

    def pause_current(self, owner_job_id: str | None = None) -> bool:
        return self.runner.pause_current(owner_job_id)

    def resume_current(self, owner_job_id: str | None = None) -> bool:
        return self.runner.resume_current(owner_job_id)

    def probe_access(
        self,
        destination: str,
        config_path: Path,
        *,
        config_root: Path,
    ) -> dict[str, object]:
        """Check read-only access to one configured remote root."""
        def not_ready(reason_code: str) -> dict[str, object]:
            return {
                "ready": False,
                "reason_code": reason_code,
                "fingerprint": "",
                "destination_fingerprint": "",
            }

        destination = str(destination or "").strip()
        try:
            validate_rclone_destination(destination)
        except ValueError:
            return not_ready("RCLONE_RUNTIME_UNAVAILABLE")

        config = Path(config_path).resolve()
        allowed_root = Path(config_root).resolve()
        try:
            config.relative_to(allowed_root)
        except ValueError:
            return not_ready("RCLONE_RUNTIME_UNAVAILABLE")
        if not config.is_file():
            return not_ready("RCLONE_RUNTIME_UNAVAILABLE")

        binary = shutil.which("rclone")
        if binary is None:
            return not_ready("RCLONE_RUNTIME_UNAVAILABLE")

        try:
            config_bytes = config.read_bytes()
            binary_path = Path(binary).resolve()
            binary_stat = binary_path.stat()
        except OSError:
            return not_ready("RCLONE_RUNTIME_UNAVAILABLE")

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
                log_prefix="rclone-storage-readiness",
                output_callback=self.log_callback,
                stall_timeout_seconds=self.stall_timeout_seconds,
                command_callback=self.command_callback,
            )
        except (TDLStalledError, TDLCommandError):
            return not_ready("RCLONE_ACCESS_FAILED")
        except OSError:
            return not_ready("RCLONE_RUNTIME_UNAVAILABLE")
        if result.returncode != 0:
            return not_ready(
                self._access_error_code(result) or "RCLONE_ACCESS_FAILED"
            )

        evidence = {
            "runtime": "rclone-storage-readiness-v1",
            "destination": destination,
            "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
            "binary_path": str(binary_path),
            "binary_size": binary_stat.st_size,
            "binary_mtime_ns": binary_stat.st_mtime_ns,
        }
        encoded = json.dumps(
            evidence, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return {
            "ready": True,
            "reason_code": "",
            "fingerprint": hashlib.sha256(encoded).hexdigest(),
            "destination_fingerprint": hashlib.sha256(
                destination.encode("utf-8")
            ).hexdigest(),
        }

    @staticmethod
    def _remote_path(root: str, relative_path: str = "") -> tuple[str, str]:
        """Join a browser path below a configured root and reject traversal."""
        root = str(root or "").strip().rstrip("/")
        relative = str(relative_path or "").replace("\\", "/")
        if relative.startswith("/"):
            raise RcloneError("Path rclone harus berada di bawah root yang dikonfigurasi.")
        relative = relative.strip("/")
        parts = relative.split("/") if relative else []
        if (
            not root
            or relative.startswith("/")
            or len(relative) > 2048
            or any(ord(char) < 32 for char in relative)
            or any(not part or part in {".", ".."} or ":" in part for part in parts)
        ):
            raise RcloneError("Path rclone harus berada di bawah root yang dikonfigurasi.")
        return root + ("/" + "/".join(parts) if parts else ""), relative

    def list_directory(
        self,
        destination: str,
        relative_path: str,
        config_path: Path,
        *,
        config_root: Path,
        query: str = "",
        sort: str = "name",
        order: str = "asc",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        """Return a read-only, paginated listing below the configured root."""
        try:
            validate_rclone_destination(destination)
            remote, normalized = self._remote_path(destination, relative_path)
        except ValueError as exc:
            raise RcloneError("Root rclone tidak valid.") from exc
        config = Path(config_path).resolve()
        try:
            config.relative_to(Path(config_root).resolve())
        except ValueError as exc:
            raise RcloneError("Konfigurasi rclone tidak tersedia untuk worker ini.") from exc
        if not config.is_file() or shutil.which("rclone") is None:
            raise RcloneError("Runtime rclone belum tersedia pada worker.", code="RCLONE_RUNTIME_UNAVAILABLE")
        if sort not in {"name", "updated_at", "size", "type"} or order not in {"asc", "desc"}:
            raise RcloneError("Opsi pengurutan listing rclone tidak valid.")
        limit = max(1, min(200, int(limit)))
        offset = max(0, int(offset))
        command = ["rclone", "lsjson", remote, "--max-depth", "1", "--config", str(config), "--log-level", "ERROR"]
        try:
            result = self.runner.run(
                command, log_prefix="rclone-storage-browser", output_callback=self.log_callback,
                stall_timeout_seconds=self.stall_timeout_seconds,
                command_callback=self.command_callback,
            )
        except (TDLStalledError, TDLCommandError, OSError) as exc:
            raise RcloneError("Worker tidak dapat membaca folder rclone.", code="RCLONE_ACCESS_FAILED") from exc
        if result.returncode != 0:
            raise RcloneError("Worker tidak dapat membaca folder rclone.", code="RCLONE_ACCESS_FAILED")
        try:
            raw_entries = json.loads(getattr(result, "stdout", "") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RcloneError("Worker menerima listing rclone yang tidak valid.") from exc
        if not isinstance(raw_entries, list):
            raise RcloneError("Worker menerima listing rclone yang tidak valid.")
        needle = str(query or "").strip().casefold()
        entries: list[dict[str, object]] = []
        for raw in raw_entries:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("Name") or "").strip()
            if not name or name in {".", ".."} or "/" in name or "\\" in name:
                continue
            is_dir = raw.get("IsDir") is True
            try:
                size = max(0, int(raw.get("Size") or 0))
            except (TypeError, ValueError):
                size = 0
            modified = str(raw.get("ModTime") or "")[:64]
            if needle and needle not in name.casefold():
                continue
            entries.append({"name": name, "path": "/".join(part for part in (normalized, name) if part),
                            "is_dir": is_dir, "size": size, "updated_at": modified})
        def key(item: dict[str, object]):
            if sort == "size":
                return (not bool(item["is_dir"]), int(item["size"]), str(item["name"]).casefold())
            if sort == "updated_at":
                return (not bool(item["is_dir"]), str(item["updated_at"]), str(item["name"]).casefold())
            if sort == "type":
                return (not bool(item["is_dir"]), Path(str(item["name"])).suffix.casefold(), str(item["name"]).casefold())
            return (not bool(item["is_dir"]), str(item["name"]).casefold())
        entries.sort(key=key, reverse=order == "desc")
        return {"path": normalized, "breadcrumbs": normalized.split("/") if normalized else [],
                "items": entries[offset:offset + limit], "total": len(entries),
                "limit": limit, "offset": offset}

    def target_file_exists(
        self, destination: str, remote_name: str, config_path: Path, *, config_root: Path
    ) -> bool:
        """Check one exact target path without changing the remote."""
        _, normalized = self._remote_path(destination, remote_name)
        if not normalized:
            raise RcloneError("Path target rclone tidak valid.")
        parent_name, _, file_name = normalized.rpartition("/")
        parent, _ = self._remote_path(destination, parent_name)
        config = Path(config_path).resolve()
        try:
            config.relative_to(Path(config_root).resolve())
        except ValueError as exc:
            raise RcloneError("Konfigurasi rclone tidak tersedia untuk worker ini.") from exc
        command = ["rclone", "lsjson", parent, "--max-depth", "1", "--config", str(config), "--log-level", "ERROR"]
        try:
            result = self.runner.run(command, log_prefix="rclone-storage-conflict-check",
                                     output_callback=self.log_callback,
                                     stall_timeout_seconds=self.stall_timeout_seconds,
                                     command_callback=self.command_callback)
        except (TDLStalledError, TDLCommandError, OSError) as exc:
            raise RcloneError("Worker tidak dapat memeriksa benturan target rclone.", code="RCLONE_ACCESS_FAILED") from exc
        if result.returncode != 0:
            detail = self._command_output(result).casefold()
            if any(marker in detail for marker in ("directory not found", "object not found", "not found", "doesn't exist", "does not exist")):
                return False
            raise RcloneError("Worker tidak dapat memeriksa benturan target rclone.", code="RCLONE_ACCESS_FAILED")
        try:
            entries = json.loads(getattr(result, "stdout", "") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RcloneError("Worker menerima listing rclone yang tidak valid.") from exc
        return isinstance(entries, list) and any(
            isinstance(item, dict) and str(item.get("Name") or "") == file_name
            for item in entries
        )

    def verify_complete_files(
        self,
        files: Iterable[Path],
        destination: str,
        config_path: Path,
        *,
        workspace_root: Path,
        config_root: Path,
        remote_names: Iterable[str],
    ) -> dict[str, object]:
        """Verify complete content via read-only rclone checksums/download reads."""
        paths = [Path(item).resolve() for item in files]
        names = list(remote_names)
        if len(paths) != len(names):
            raise RcloneError("Jumlah path verifikasi rclone tidak sesuai.")
        workspace = Path(workspace_root).resolve()
        config = Path(config_path).resolve()
        try:
            config.relative_to(Path(config_root).resolve())
        except ValueError as exc:
            raise RcloneError("Konfigurasi rclone tidak tersedia untuk worker ini.") from exc
        verified: list[str] = []
        for path, name in zip(paths, names):
            try:
                path.relative_to(workspace)
            except ValueError as exc:
                raise RcloneError("File verifikasi harus berada di dalam workspace.") from exc
            target, normalized = self._remote_path(destination, str(name))
            command = ["rclone", "check", str(path), target, "--download", "--one-way",
                       "--config", str(config), "--log-level", "ERROR"]
            try:
                result = self.runner.run(command, log_prefix="rclone-storage-full-verify",
                                         output_callback=self.log_callback,
                                         stall_timeout_seconds=self.stall_timeout_seconds,
                                         command_callback=self.command_callback)
            except (TDLStalledError, TDLCommandError, OSError) as exc:
                return {"complete": False, "verified": verified, "reason_code": "RCLONE_VERIFY_UNAVAILABLE"}
            if result.returncode != 0:
                return {"complete": False, "verified": verified, "reason_code": "RCLONE_CONTENT_MISMATCH"}
            verified.append(normalized)
        return {"complete": len(verified) == len(paths), "verified": verified, "reason_code": ""}

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

    @staticmethod
    def _access_error_code(exc: BaseException) -> str:
        """Classify only explicit remote authentication/connectivity failures."""
        sources = [str(exc)]
        for name in ("stdout", "stderr"):
            value = getattr(exc, name, None)
            if isinstance(value, str):
                sources.append(value)
        text = "\n".join(sources).casefold()
        markers = (
            "401 unauthorized",
            "401: unauthorized",
            "403 forbidden",
            "403: forbidden",
            "authentication failed",
            "authorization failed",
            "invalid_grant",
            "token expired",
            "failed to renew token",
            "accessdenied",
            "insufficient permission",
            "insufficientpermissions",
            "permission denied (publickey)",
            "connection refused",
            "network is unreachable",
            "no route to host",
            "no such host",
            "i/o timeout",
            "context deadline exceeded",
        )
        return "RCLONE_ACCESS_FAILED" if any(marker in text for marker in markers) else ""

    def copy_files(
        self,
        files: Iterable[Path],
        destination: str,
        config_path: Path,
        *,
        workspace_root: Path,
        config_root: Path | None = None,
        remote_names: Iterable[str] | None = None,
        ignore_existing: bool = False,
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
            raise RcloneError(
                f"Konfigurasi rclone tidak ditemukan: {config}",
                code="RCLONE_RUNTIME_UNAVAILABLE",
            )
        if shutil.which("rclone") is None:
            raise RcloneError(
                "Binary rclone belum tersedia pada worker.",
                code="RCLONE_RUNTIME_UNAVAILABLE",
            )

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
            try:
                target, normalized_name = self._remote_path(destination, str(remote_name))
            except RcloneError as exc:
                raise RcloneError(f"Nama tujuan rclone tidak valid untuk {path.name}.") from exc
            remote_parts = normalized_name.split("/") if normalized_name else []
            if not remote_parts:
                raise RcloneError(f"Nama tujuan rclone tidak valid untuk {path.name}.")
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
            if ignore_existing:
                command.extend(["--ignore-existing"])
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
                    f"rclone gagal untuk {path.name} (exit code {exc.returncode}).",
                    code=self._access_error_code(exc),
                ) from exc
            except OSError as exc:
                raise RcloneError(
                    "Worker tidak dapat memulai proses rclone.",
                    code="RCLONE_RUNTIME_UNAVAILABLE",
                ) from exc
            if result.returncode != 0:
                raise RcloneError(
                    f"rclone gagal untuk {path.name} (exit code {result.returncode}).",
                    code=self._access_error_code(result),
                )
            uploaded.append(normalized_name)
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
