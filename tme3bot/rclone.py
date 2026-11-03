from __future__ import annotations

import configparser
import hashlib
import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Callable, Iterable

from tme3bot.command_audit import bounded_output_tail, sanitize_text
from tme3bot.tdl import CommandCallback, SubprocessRunner, TDLCommandError, TDLStalledError
from tme3bot.utility import validate_rclone_destination


_PERMANENT_DELETE_FLAGS = {
    "b2": "--b2-hard-delete",
    "drime": "--drime-hard-delete",
    "drive": "--drive-use-trash=false",
    "jottacloud": "--jottacloud-hard-delete",
    "mega": "--mega-hard-delete",
    "onedrive": "--onedrive-hard-delete",
    "pikpak": "--pikpak-use-trash=false",
    "quatrix": "--quatrix-hard-delete",
    "sugarsync": "--sugarsync-hard-delete",
    "yandex": "--yandex-hard-delete",
}
_PERMANENT_DELETE_DEFAULT_BACKENDS = frozenset({"ftp", "local", "sftp", "webdav"})


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
        transfer_callback: Callable[[dict[str, object]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        stall_timeout_seconds: int = 0,
        command_callback: CommandCallback | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.transfer_callback = transfer_callback
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
            raise RcloneError(
                "Path rclone harus berada di bawah root yang dikonfigurasi.",
                code="RCLONE_BROWSER_PATH_INVALID",
            )
        relative = relative.strip("/")
        parts = relative.split("/") if relative else []
        if (
            not root
            or relative.startswith("/")
            or len(relative) > 2048
            or any(ord(char) < 32 for char in relative)
            or any(not part or part in {".", ".."} or ":" in part for part in parts)
        ):
            raise RcloneError(
                "Path rclone harus berada di bawah root yang dikonfigurasi.",
                code="RCLONE_BROWSER_PATH_INVALID",
            )
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
        backend_type = self._remote_backend_type(destination, config)
        return {"path": normalized, "breadcrumbs": normalized.split("/") if normalized else [],
                "items": entries[offset:offset + limit], "total": len(entries),
                "trash_supported": backend_type == "drive",
                "permanent_delete_supported": self._permanent_delete_flags(backend_type) is not None,
                "limit": limit, "offset": offset}

    def list_directory_summaries(
        self,
        destination: str,
        relative_path: str,
        config_path: Path,
        *,
        config_root: Path,
    ) -> dict[str, object]:
        """Aggregate immediate-child folders from one recursive metadata listing."""
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
            raise RcloneError(
                "Runtime rclone belum tersedia pada worker.",
                code="RCLONE_RUNTIME_UNAVAILABLE",
            )
        command = [
            "rclone", "lsjson", remote, "--recursive", "--no-modtime",
            "--no-mimetype", "--config", str(config), "--log-level", "ERROR",
        ]
        try:
            result = self.runner.run(
                command,
                log_prefix="rclone-storage-folder-summary",
                output_callback=self.log_callback,
                stall_timeout_seconds=self.stall_timeout_seconds,
                command_callback=self.command_callback,
            )
        except (TDLStalledError, TDLCommandError, OSError) as exc:
            raise RcloneError(
                "Worker tidak dapat menghitung isi folder rclone.",
                code="RCLONE_ACCESS_FAILED",
            ) from exc
        if result.returncode != 0:
            raise RcloneError(
                "Worker tidak dapat menghitung isi folder rclone.",
                code=self._access_error_code(result) or "RCLONE_ACCESS_FAILED",
            )
        try:
            raw_entries = json.loads(getattr(result, "stdout", "") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RcloneError("Worker menerima inventaris rclone yang tidak valid.") from exc
        if not isinstance(raw_entries, list):
            raise RcloneError("Worker menerima inventaris rclone yang tidak valid.")

        summaries: dict[str, dict[str, object]] = {}
        directories: dict[str, set[str]] = {}
        for raw in raw_entries:
            if not isinstance(raw, dict):
                continue
            raw_path = str(raw.get("Path") or raw.get("Name") or "").replace("\\", "/")
            parts = raw_path.split("/")
            if not raw_path or raw_path.startswith("/") or any(
                not part or part in {".", ".."} or ":" in part for part in parts
            ):
                continue
            top = parts[0]
            if len(parts) < 2 and raw.get("IsDir") is not True:
                continue
            summary = summaries.setdefault(
                top,
                {"file_count": 0, "folder_count": 0, "size_bytes": 0, "size_complete": True},
            )
            directory_set = directories.setdefault(top, set())
            if raw.get("IsDir") is True:
                directory_set.add("/".join(parts))
                continue
            summary["file_count"] = int(summary["file_count"]) + 1
            # Infer implicit object-store folders from file paths as well as
            # counting explicit directory entries returned by the backend.
            directory_set.update(
                "/".join(parts[:index]) for index in range(2, len(parts))
            )
            size = raw.get("Size")
            if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
                summary["size_bytes"] = int(summary["size_bytes"]) + size
            else:
                summary["size_complete"] = False
        for top, summary in summaries.items():
            summary["folder_count"] = len(directories.get(top, set()) - {top})
        return {
            "path": normalized,
            "summaries": [
                {"path": "/".join(part for part in (normalized, name) if part), **summary}
                for name, summary in sorted(summaries.items())
            ],
        }

    @staticmethod
    def _transfer_log_callback(
        callback: Callable[[dict[str, object]], None] | None,
        *,
        file_name: str,
        file_size: int | None,
        log_callback: Callable[[str], None] | None,
    ) -> Callable[[str], None] | None:
        if callback is None and log_callback is None:
            return None

        def on_line(line: str) -> None:
            stats: object = None
            try:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    stats = payload.get("stats")
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = None
            if isinstance(stats, dict):
                if callback is not None:
                    active_items = stats.get("transferring")
                    active = active_items[0] if isinstance(active_items, list) and active_items and isinstance(active_items[0], dict) else {}
                    current = active.get("bytes", stats.get("bytes"))
                    total = active.get("size", file_size)
                    percent = active.get("percentage")
                    if percent is None and isinstance(current, (int, float)) and isinstance(total, (int, float)) and total > 0:
                        percent = min(100.0, max(0.0, float(current) * 100 / float(total)))
                    speed = active.get("speed", active.get("speedAvg", stats.get("speed")))
                    eta = active.get("eta", stats.get("eta"))
                    try:
                        current_value = max(0, int(current))
                    except (TypeError, ValueError):
                        current_value = 0
                    try:
                        total_value = max(0, int(total)) if total is not None else None
                    except (TypeError, ValueError):
                        total_value = None
                    try:
                        speed_value = max(0, int(float(speed))) if speed is not None else None
                    except (TypeError, ValueError):
                        speed_value = None
                    try:
                        eta_value = max(0, int(float(eta))) if eta is not None else None
                    except (TypeError, ValueError):
                        eta_value = None
                    try:
                        percent_value = min(100.0, max(0.0, float(percent))) if percent is not None else None
                    except (TypeError, ValueError):
                        percent_value = None
                try:
                    if callback is not None:
                        callback({
                            "name": str(active.get("name") or file_name)[:512],
                            "bytes_current": current_value,
                            "bytes_total": total_value,
                            "speed_bps": speed_value,
                            "eta_seconds": eta_value,
                            "percent": percent_value,
                        })
                except Exception:
                    # Telemetry must never change the outcome of a transfer.
                    pass
                # Never copy raw rclone progress output into the worker log or
                # job event; only the normalized fields above are user-facing.
                return
            if log_callback is not None:
                log_callback(line)

        return on_line

    @staticmethod
    def _keep_non_stats_output_line(line: str) -> bool:
        try:
            value = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            return True
        return not (isinstance(value, dict) and isinstance(value.get("stats"), dict))

    @staticmethod
    def _remote_entry_name(value: str) -> str:
        name = str(value or "").strip()
        if (
            not name
            or len(name) > 120
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or ":" in name
            or any(ord(char) < 32 for char in name)
        ):
            raise RcloneError(
                "Nama file atau folder rclone tidak valid.",
                code="RCLONE_BROWSER_PATH_INVALID",
            )
        return name

    def _storage_config(self, config_path: Path, config_root: Path) -> Path:
        config = Path(config_path).resolve()
        try:
            config.relative_to(Path(config_root).resolve())
        except ValueError as exc:
            raise RcloneError(
                "Konfigurasi rclone tidak tersedia untuk worker ini.",
                code="RCLONE_RUNTIME_UNAVAILABLE",
            ) from exc
        if not config.is_file() or shutil.which("rclone") is None:
            raise RcloneError(
                "Runtime rclone belum tersedia pada worker.",
                code="RCLONE_RUNTIME_UNAVAILABLE",
            )
        return config

    def _run_storage_command(
        self,
        command: list[str],
        *,
        log_prefix: str,
        error_code: str = "RCLONE_ACCESS_FAILED",
    ):
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
                "Worker tidak dapat menjalankan operasi rclone.",
                code=error_code,
            ) from exc
        if result.returncode != 0:
            raise RcloneError(
                "Worker tidak dapat menjalankan operasi rclone.",
                code=error_code,
            )
        return result

    def _list_storage_children(
        self, remote_parent: str, config: Path, *, log_prefix: str
    ) -> list[dict[str, object]]:
        result = self._run_storage_command(
            [
                "rclone",
                "lsjson",
                remote_parent,
                "--max-depth",
                "1",
                "--no-modtime",
                "--no-mimetype",
                "--config",
                str(config),
                "--log-level",
                "ERROR",
            ],
            log_prefix=log_prefix,
        )
        try:
            entries = json.loads(getattr(result, "stdout", "") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RcloneError("Worker menerima listing rclone yang tidak valid.") from exc
        if not isinstance(entries, list):
            raise RcloneError("Worker menerima listing rclone yang tidak valid.")
        return [entry for entry in entries if isinstance(entry, dict)]

    @staticmethod
    def _remote_backend_type(destination: str, config: Path) -> str:
        """Read only the configured backend type; never expose config values."""
        remote_name = str(destination or "").split(":", 1)[0].strip()
        if not remote_name:
            return ""
        parser = configparser.RawConfigParser(interpolation=None)
        try:
            try:
                parser.read(config, encoding="utf-8")
            except (configparser.Error, UnicodeError):
                # Encrypted rclone configs are not INI until rclone decrypts
                # and redacts them below.
                parser = configparser.RawConfigParser(interpolation=None)
            for _ in range(8):
                if parser.has_section(remote_name):
                    section = parser[remote_name]
                else:
                    # rclone supports encrypted configuration files. Ask its
                    # redaction command for this one section so capability
                    # detection can still work without exposing config values
                    # to logs or callers. An unavailable config passphrase
                    # simply makes destructive capability unknown.
                    try:
                        result = subprocess.run(
                            [
                                "rclone", "config", "redacted", remote_name,
                                "--config", str(config),
                            ],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=5,
                            input="",
                        )
                    except (OSError, subprocess.SubprocessError):
                        return ""
                    if result.returncode != 0 or len(result.stdout or "") > 65536:
                        return ""
                    redacted = configparser.RawConfigParser(interpolation=None)
                    try:
                        redacted.read_string(result.stdout or "")
                    except (configparser.Error, UnicodeError):
                        return ""
                    if not redacted.has_section(remote_name):
                        return ""
                    section = redacted[remote_name]
                backend = str(section.get("type") or "").strip().lower()
                if backend != "alias":
                    return backend
                alias_target = str(section.get("remote") or "").strip()
                remote_name = alias_target.split(":", 1)[0].strip()
                if not remote_name:
                    return ""
        except (OSError, configparser.Error, UnicodeError):
            return ""
        return ""

    @staticmethod
    def _permanent_delete_flags(backend_type: str, *, trashed: bool = False) -> list[str] | None:
        """Return a known permanent-delete strategy or None for unknown semantics."""
        backend = str(backend_type or "").strip().lower()
        if trashed:
            if backend != "drive":
                return None
            return ["--drive-use-trash=false", "--drive-trashed-only"]
        flag = _PERMANENT_DELETE_FLAGS.get(backend)
        if flag:
            return [flag]
        if backend in _PERMANENT_DELETE_DEFAULT_BACKENDS:
            return []
        return None

    def _list_recursive_entries(
        self,
        remote: str,
        config: Path,
        *,
        log_prefix: str,
        trashed_only: bool = False,
    ) -> list[dict[str, object]]:
        command = [
            "rclone", "lsjson", remote, "--recursive", "--config", str(config),
            "--log-level", "ERROR",
        ]
        if trashed_only:
            command.append("--drive-trashed-only")
        result = self._run_storage_command(
            command, log_prefix=log_prefix, error_code="RCLONE_LIST_FAILED"
        )
        try:
            entries = json.loads(getattr(result, "stdout", "") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RcloneError(
                "Worker menerima listing rclone yang tidak valid.",
                code="RCLONE_LIST_FAILED",
            ) from exc
        if not isinstance(entries, list):
            raise RcloneError(
                "Worker menerima listing rclone yang tidak valid.",
                code="RCLONE_LIST_FAILED",
            )
        normalized: list[dict[str, object]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            relative = str(entry.get("Path") or entry.get("Name") or "").replace("\\", "/")
            parts = relative.split("/")
            if (
                not relative
                or relative.startswith("/")
                or any(not part or part in {".", ".."} or ":" in part for part in parts)
                or any(ord(char) < 32 for char in relative)
            ):
                raise RcloneError(
                    "Remote memiliki path yang tidak aman untuk operasi ini.",
                    code="RCLONE_REMOTE_ENTRY_INVALID",
                )
            item = dict(entry)
            item["_relative_path"] = "/".join(parts)
            normalized.append(item)
        return normalized

    def list_trash(
        self,
        destination: str,
        config_path: Path,
        *,
        config_root: Path,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        """List trashed Drive items below the configured Storage root."""
        try:
            validate_rclone_destination(destination)
        except ValueError as exc:
            raise RcloneError("Root rclone tidak valid.", code="RCLONE_BROWSER_PATH_INVALID") from exc
        config = self._storage_config(config_path, config_root)
        backend_type = self._remote_backend_type(destination, config)
        supported = backend_type == "drive"
        if not supported:
            return {
                "supported": False,
                "permanent_delete_supported": self._permanent_delete_flags(backend_type) is not None,
                "items": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
            }
        remote, _ = self._remote_path(destination, "")
        entries = self._list_recursive_entries(
            remote, config, log_prefix="rclone-storage-trash-list", trashed_only=True
        )
        items: list[dict[str, object]] = []
        for entry in entries:
            relative = str(entry.get("_relative_path") or "")
            name = relative.rsplit("/", 1)[-1]
            if not name:
                continue
            raw_size = entry.get("Size")
            try:
                size = max(0, int(raw_size)) if raw_size is not None else None
            except (TypeError, ValueError):
                size = None
            items.append({
                "id": str(entry.get("ID") or "")[:256],
                "name": name,
                "path": relative,
                "is_dir": entry.get("IsDir") is True,
                "size": size,
                "updated_at": str(entry.get("ModTime") or "")[:64],
            })
        counts: dict[str, int] = {}
        for item in items:
            item_path = str(item["path"])
            counts[item_path] = counts.get(item_path, 0) + 1
        for item in items:
            item["ambiguous"] = counts[str(item["path"])] > 1
        items.sort(key=lambda item: (
            not bool(item["is_dir"]),
            str(item["path"]).casefold(),
            str(item["id"]),
        ))
        limit = max(1, min(200, int(limit)))
        offset = max(0, int(offset))
        return {
            "supported": True,
            "permanent_delete_supported": True,
            "items": items[offset:offset + limit],
            "total": len(items),
            "limit": limit,
            "offset": offset,
        }

    @staticmethod
    def _entry_metadata(entry: dict[str, object]) -> tuple[object, ...]:
        return (
            str(entry.get("_relative_path") or ""),
            entry.get("IsDir") is True,
            str(entry.get("ID") or ""),
            str(entry.get("Size") if entry.get("Size") is not None else ""),
            str(entry.get("ModTime") or ""),
        )

    def _source_snapshot(
        self,
        destination: str,
        relative_path: str,
        remote_path: str,
        *,
        is_dir: bool,
        config: Path,
    ) -> list[dict[str, object]]:
        """Capture the selected entry and all descendants for safe Move cleanup."""
        parent_relative = relative_path.rpartition("/")[0]
        leaf = relative_path.rsplit("/", 1)[-1]
        parent_remote, _ = self._remote_path(destination, parent_relative)
        entries = self._list_storage_children(
            parent_remote, config, log_prefix="rclone-storage-manage-source"
        )
        matches = [
            entry for entry in entries
            if str(entry.get("Name") or "") == leaf
            and (entry.get("IsDir") is True) == is_dir
        ]
        if not matches:
            raise RcloneError(
                "File atau folder sumber tidak ditemukan.", code="RCLONE_SOURCE_NOT_FOUND"
            )
        if len(matches) != 1:
            raise RcloneError(
                "Nama sumber tidak unik pada remote; operasi dibatalkan.",
                code="RCLONE_SOURCE_AMBIGUOUS",
            )
        root_entry = dict(matches[0])
        root_entry["_relative_path"] = relative_path
        snapshot = [root_entry]
        if not is_dir:
            return snapshot
        children = self._list_recursive_entries(
            remote_path, config, log_prefix="rclone-storage-manage-source"
        )
        for entry in children:
            child_relative = str(entry.get("_relative_path") or "")
            if child_relative == relative_path or child_relative.startswith(relative_path + "/"):
                normalized = child_relative
            else:
                normalized = relative_path + "/" + child_relative
            child = dict(entry)
            child["_relative_path"] = normalized
            snapshot.append(child)
        return snapshot

    def manage_storage_item(
        self,
        destination: str,
        *,
        action: str,
        path: str,
        is_dir: bool,
        config_path: Path,
        config_root: Path,
        destination_path: str = "",
        trashed: bool = False,
        item_id: str = "",
        selected_restore_sources: list[dict[str, object]] | None = None,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> dict[str, object]:
        """Safely mutate one item, keeping every command below the configured root."""
        try:
            validate_rclone_destination(destination)
            source_remote, source_relative = self._remote_path(destination, path)
        except ValueError as exc:
            raise RcloneError(
                "Path rclone harus berada di bawah root yang dikonfigurasi.",
                code="RCLONE_BROWSER_PATH_INVALID",
            ) from exc
        if not source_relative:
            raise RcloneError(
                "Root rclone tidak dapat diubah.", code="RCLONE_BROWSER_PATH_INVALID"
            )
        config = self._storage_config(config_path, config_root)
        if action in {"copy", "move"}:
            destination_remote, normalized_parent = self._remote_path(
                destination, destination_path
            )
            source_name = source_relative.rsplit("/", 1)[-1]
            target_relative = "/".join(
                part for part in (normalized_parent, source_name) if part
            )
            target_remote, target_relative = self._remote_path(destination, target_relative)
            if is_dir and (
                target_relative == source_relative
                or target_relative.startswith(source_relative + "/")
            ):
                raise RcloneError(
                    "Folder tidak dapat disalin ke dalam dirinya sendiri.",
                    code="RCLONE_TARGET_INVALID",
                )
            parent_entries = self._list_storage_children(
                destination_remote, config, log_prefix="rclone-storage-manage-target"
            )
            if any(str(item.get("Name") or "") == source_name for item in parent_entries):
                raise RcloneError(
                    "Nama tujuan rclone sudah ada.", code="RCLONE_TARGET_EXISTS"
                )

            before_entries = self._source_snapshot(
                destination, source_relative, source_remote,
                is_dir=is_dir, config=config,
            )

            stage_name = f".tme3bot-stage-{uuid.uuid4().hex}"
            stage_relative = "/".join(
                part for part in (normalized_parent, stage_name) if part
            )
            stage_remote, _ = self._remote_path(destination, stage_relative)
            transfer_command = [
                "rclone", "copy" if is_dir else "copyto", source_remote, stage_remote,
                "--config", str(config), "--log-level", "NOTICE", "--stats", "1s",
                "--stats-log-level", "NOTICE", "--use-json-log",
            ]
            if is_dir:
                transfer_command.append("--create-empty-src-dirs")
            transfer_output = self._transfer_log_callback(
                progress_callback,
                file_name=source_name,
                file_size=None,
                log_callback=self.log_callback,
            )
            try:
                result = self.runner.run(
                    transfer_command,
                    log_prefix="rclone-storage-manage-copy",
                    output_callback=transfer_output,
                    output_filter=self._keep_non_stats_output_line,
                    stall_timeout_seconds=self.stall_timeout_seconds,
                    command_callback=self.command_callback,
                )
                if result.returncode != 0:
                    raise RcloneError(
                        "rclone gagal menyalin item.", code="RCLONE_OPERATION_FAILED"
                    )
                self._run_storage_command(
                    [
                        "rclone", "moveto", stage_remote, target_remote,
                        "--ignore-existing", "--config", str(config), "--log-level", "ERROR",
                    ],
                    log_prefix="rclone-storage-manage-commit",
                    error_code="RCLONE_OPERATION_FAILED",
                )
                target_parent, _ = self._remote_path(destination, normalized_parent)
                committed = self._list_storage_children(
                    target_parent, config, log_prefix="rclone-storage-manage-verify"
                )
                stage_name_still_exists = any(
                    str(item.get("Name") or "") == stage_name for item in committed
                )
                if stage_name_still_exists:
                    raise RcloneError(
                        "Nama tujuan dibuat bersamaan; sumber remote tetap dipertahankan.",
                        code="RCLONE_TARGET_EXISTS",
                    )
                if not any(str(item.get("Name") or "") == source_name for item in committed):
                    raise RcloneError(
                        "Hasil salinan remote belum dapat dipastikan.",
                        code="RCLONE_OPERATION_AMBIGUOUS",
                    )
            except Exception:
                # The stage path is unique to this operation; cleanup cannot
                # target an operator-owned item.
                try:
                    self._run_storage_command(
                        [
                            "rclone", "purge" if is_dir else "deletefile", stage_remote,
                            "--config", str(config),
                            "--log-level", "ERROR",
                        ],
                        log_prefix="rclone-storage-manage-stage-cleanup",
                        error_code="RCLONE_STAGE_CLEANUP_FAILED",
                    )
                except Exception:
                    pass
                raise

            result: dict[str, object] = {
                "action": action,
                "path": source_relative,
                "target_path": target_relative,
                "status": "succeeded",
                "cleanup_status": "not_requested" if action == "copy" else "pending",
            }
            if action == "move":
                try:
                    after_entries = self._source_snapshot(
                        destination, source_relative, source_remote,
                        is_dir=is_dir, config=config,
                    )
                except RcloneError as exc:
                    result.update(
                        status="partial",
                        cleanup_status="skipped_source_changed",
                        error_code=exc.code or "RCLONE_SOURCE_CHANGED",
                        error="Salinan selesai, tetapi sumber berubah atau tidak dapat diperiksa; sumber tidak dihapus.",
                    )
                    return result
                before = sorted(self._entry_metadata(entry) for entry in before_entries)
                after = sorted(self._entry_metadata(entry) for entry in after_entries)
                if before != after:
                    result.update(status="partial", cleanup_status="skipped_source_changed")
                    return result
                cleanup_command = ["rclone", "purge" if is_dir else "deletefile", source_remote]
                cleanup_command.extend(["--config", str(config), "--log-level", "ERROR"])
                try:
                    self._run_storage_command(
                        cleanup_command,
                        log_prefix="rclone-storage-manage-move-cleanup",
                        error_code="RCLONE_SOURCE_CLEANUP_FAILED",
                    )
                    result["cleanup_status"] = "deleted"
                except RcloneError:
                    result.update(status="partial", cleanup_status="failed")
            return result

        if action in {"trash", "restore", "purge"}:
            trash_supported = self._remote_backend_type(destination, config) == "drive"
            if action == "trash" and not trash_supported:
                raise RcloneError(
                    "Remote ini tidak menyediakan Trash melalui adapter rclone.",
                    code="RCLONE_TRASH_UNSUPPORTED",
                )
            if action == "restore":
                if not trash_supported or not trashed:
                    raise RcloneError(
                        "Restore hanya tersedia untuk item Trash Google Drive.",
                        code="RCLONE_TRASH_UNSUPPORTED",
                    )
                trash_entries = self._list_recursive_entries(
                    self._remote_path(destination, "")[0], config,
                    log_prefix="rclone-storage-restore-scope", trashed_only=True,
                )
                selected_entries = [
                    entry for entry in trash_entries
                    if str(entry.get("_relative_path") or "") == source_relative
                    or (is_dir and str(entry.get("_relative_path") or "").startswith(source_relative + "/"))
                ]
                exact_matches = [
                    entry for entry in selected_entries
                    if str(entry.get("_relative_path") or "") == source_relative
                ]
                if not exact_matches:
                    parent_relative = source_relative.rpartition("/")[0]
                    parent_remote, _ = self._remote_path(destination, parent_relative)
                    active_children = self._list_storage_children(
                        parent_remote, config, log_prefix="rclone-storage-restore-check"
                    )
                    already_restored = [
                        entry for entry in active_children
                        if str(entry.get("Name") or "") == source_relative.rsplit("/", 1)[-1]
                        and (entry.get("IsDir") is True) == is_dir
                        and item_id
                        and str(entry.get("ID") or "") == item_id
                    ]
                    if len(already_restored) == 1:
                        return {
                            "action": action,
                            "path": source_relative,
                            "status": "succeeded",
                            "cleanup_status": "not_requested",
                        }
                    raise RcloneError(
                        "Item Trash tidak ditemukan.", code="RCLONE_SOURCE_NOT_FOUND"
                    )
                if len(exact_matches) != 1 or (
                    item_id and str(exact_matches[0].get("ID") or "") != item_id
                ):
                    raise RcloneError(
                        "Item Trash tidak unik atau sudah berubah; refresh daftar Trash.",
                        code="RCLONE_SOURCE_AMBIGUOUS",
                    )
                if (exact_matches[0].get("IsDir") is True) != is_dir:
                    raise RcloneError(
                        "Jenis item Trash berubah; refresh daftar Trash.",
                        code="RCLONE_SOURCE_CHANGED",
                    )
                parent_relative = source_relative.rpartition("/")[0]
                affected_entries = [
                    entry for entry in trash_entries
                    if not parent_relative
                    or str(entry.get("_relative_path") or "") == parent_relative
                    or str(entry.get("_relative_path") or "").startswith(parent_relative + "/")
                ]
                selected_scopes = selected_restore_sources or [
                    {"path": source_relative, "is_dir": is_dir, "id": item_id}
                ]
                selected_paths: list[tuple[str, bool, str]] = []
                for selected in selected_scopes:
                    selected_path = str(selected.get("path") or "").replace("\\", "/").strip("/")
                    selected_is_dir = selected.get("is_dir") is True
                    if not selected_path or selected_path.rpartition("/")[0] != parent_relative:
                        continue
                    selected_id = str(selected.get("id") or "")
                    selected_exact = [
                        entry for entry in trash_entries
                        if str(entry.get("_relative_path") or "") == selected_path
                    ]
                    if len(selected_exact) != 1 or (
                        selected_id and str(selected_exact[0].get("ID") or "") != selected_id
                    ) or (selected_exact[0].get("IsDir") is True) != selected_is_dir:
                        raise RcloneError(
                            "Pilihan Trash berubah; refresh daftar Trash.",
                            code="RCLONE_SOURCE_CHANGED",
                        )
                    selected_paths.append((selected_path, selected_is_dir, selected_id))
                selected_entries = [
                    entry for entry in trash_entries
                    if any(
                        str(entry.get("_relative_path") or "") == selected_path
                        or (selected_is_dir and str(entry.get("_relative_path") or "").startswith(selected_path + "/"))
                        for selected_path, selected_is_dir, _ in selected_paths
                    )
                ]
                selected_snapshot = sorted(self._entry_metadata(entry) for entry in selected_entries)
                affected_snapshot = sorted(self._entry_metadata(entry) for entry in affected_entries)
                if affected_snapshot != selected_snapshot:
                    raise RcloneError(
                        "Ada item Trash lain di folder induk yang sama. Pilih semua item Trash pada folder induk itu dalam satu batch agar item lain tidak ikut berubah.",
                        code="RCLONE_RESTORE_SCOPE_AMBIGUOUS",
                    )
                parent_remote, _ = self._remote_path(destination, parent_relative)
                active_children = self._list_storage_children(
                    parent_remote, config, log_prefix="rclone-storage-restore-check"
                )
                if any(str(item.get("Name") or "") == source_relative.rsplit("/", 1)[-1] for item in active_children):
                    raise RcloneError(
                        "Item aktif sudah memakai nama tujuan.", code="RCLONE_TARGET_EXISTS"
                    )
                # rclone's Drive untrash command works at directory scope. The
                # preflight above ensures this parent contains no other trashed
                # items, so the command cannot restore an unrelated sibling.
                command = ["rclone", "backend", "untrash", parent_remote]
            elif action == "trash":
                parent_relative = source_relative.rpartition("/")[0]
                parent_remote, _ = self._remote_path(destination, parent_relative)
                active_children = self._list_storage_children(
                    parent_remote, config, log_prefix="rclone-storage-trash-check"
                )
                matches = [
                    entry for entry in active_children
                    if str(entry.get("Name") or "") == source_relative.rsplit("/", 1)[-1]
                    and (entry.get("IsDir") is True) == is_dir
                ]
                if not matches:
                    raise RcloneError(
                        "File atau folder sumber tidak ditemukan.", code="RCLONE_SOURCE_NOT_FOUND"
                    )
                if len(matches) != 1:
                    raise RcloneError(
                        "Nama sumber tidak unik pada remote; operasi dibatalkan.",
                        code="RCLONE_SOURCE_AMBIGUOUS",
                    )
                command = ["rclone", "purge" if is_dir else "deletefile", source_remote]
                command.append("--drive-use-trash=true")
            else:
                if trashed:
                    if not trash_supported:
                        raise RcloneError(
                            "Remote ini tidak menyediakan Trash melalui adapter rclone.",
                            code="RCLONE_TRASH_UNSUPPORTED",
                        )
                    trash_entries = self._list_recursive_entries(
                        self._remote_path(destination, "")[0], config,
                        log_prefix="rclone-storage-purge-check", trashed_only=True,
                    )
                    matches = [
                        entry for entry in trash_entries
                        if str(entry.get("_relative_path") or "") == source_relative
                    ]
                    if not matches:
                        raise RcloneError(
                            "Item Trash tidak ditemukan.", code="RCLONE_SOURCE_NOT_FOUND"
                        )
                    if len(matches) != 1 or (
                        item_id and str(matches[0].get("ID") or "") != item_id
                    ):
                        raise RcloneError(
                            "Item Trash tidak unik atau sudah berubah; refresh daftar Trash.",
                            code="RCLONE_SOURCE_AMBIGUOUS",
                        )
                    if (matches[0].get("IsDir") is True) != is_dir:
                        raise RcloneError(
                            "Jenis item Trash berubah; refresh daftar Trash.",
                            code="RCLONE_SOURCE_CHANGED",
                        )
                else:
                    parent_relative = source_relative.rpartition("/")[0]
                    parent_remote, _ = self._remote_path(destination, parent_relative)
                    active_children = self._list_storage_children(
                        parent_remote, config, log_prefix="rclone-storage-purge-check"
                    )
                    matches = [
                        entry for entry in active_children
                        if str(entry.get("Name") or "") == source_relative.rsplit("/", 1)[-1]
                        and (entry.get("IsDir") is True) == is_dir
                    ]
                    if len(matches) != 1:
                        raise RcloneError(
                            "File atau folder sumber tidak ditemukan atau tidak unik.",
                            code="RCLONE_SOURCE_AMBIGUOUS" if matches else "RCLONE_SOURCE_NOT_FOUND",
                        )
                backend_type = self._remote_backend_type(destination, config)
                delete_flags = self._permanent_delete_flags(backend_type, trashed=trashed)
                if delete_flags is None:
                    raise RcloneError(
                        "Semantik hapus permanen backend ini tidak dapat dipastikan; aksi dibatalkan.",
                        code="RCLONE_PERMANENT_DELETE_UNSUPPORTED",
                    )
                command = ["rclone", "purge" if is_dir else "deletefile", source_remote]
                command.extend(delete_flags)
            command.extend(["--config", str(config), "--log-level", "ERROR"])
            self._run_storage_command(
                command,
                log_prefix=f"rclone-storage-{action}",
                error_code="RCLONE_OPERATION_FAILED",
            )
            if action == "restore":
                restored_children = self._list_storage_children(
                    parent_remote, config, log_prefix="rclone-storage-restore-verify"
                )
                restored = [
                    entry for entry in restored_children
                    if str(entry.get("Name") or "") == source_relative.rsplit("/", 1)[-1]
                ]
                if len(restored) != 1 or (item_id and str(restored[0].get("ID") or "") != item_id):
                    raise RcloneError(
                        "Hasil pemulihan belum dapat dipastikan.",
                        code="RCLONE_OPERATION_AMBIGUOUS",
                    )
            return {
                "action": action,
                "path": source_relative,
                "status": "succeeded",
                "cleanup_status": "not_requested",
            }

        raise RcloneError("Operasi Storage rclone tidak didukung.", code="RCLONE_ACTION_INVALID")

    def create_directory(
        self,
        destination: str,
        parent_path: str,
        name: str,
        config_path: Path,
        *,
        config_root: Path,
    ) -> dict[str, object]:
        """Create one folder below the configured Storage root."""
        try:
            validate_rclone_destination(destination)
            remote_parent, normalized_parent = self._remote_path(
                destination, parent_path
            )
        except ValueError as exc:
            raise RcloneError(
                "Path rclone harus berada di bawah root yang dikonfigurasi.",
                code="RCLONE_BROWSER_PATH_INVALID",
            ) from exc
        folder_name = self._remote_entry_name(name)
        normalized_path = "/".join(
            part for part in (normalized_parent, folder_name) if part
        )
        remote_folder, normalized_path = self._remote_path(
            destination, normalized_path
        )
        config = self._storage_config(config_path, config_root)
        children = self._list_storage_children(
            remote_parent, config, log_prefix="rclone-storage-mkdir-check"
        )
        if any(str(item.get("Name") or "") == folder_name for item in children):
            raise RcloneError(
                "Nama folder rclone sudah ada.",
                code="RCLONE_TARGET_EXISTS",
            )
        self._run_storage_command(
            [
                "rclone",
                "mkdir",
                remote_folder,
                "--config",
                str(config),
                "--log-level",
                "ERROR",
            ],
            log_prefix="rclone-storage-mkdir",
        )
        return {"action": "create_folder", "path": normalized_path}

    def rename_path(
        self,
        destination: str,
        source_path: str,
        new_name: str,
        config_path: Path,
        *,
        config_root: Path,
    ) -> dict[str, object]:
        """Rename one file or folder without replacing an existing sibling."""
        try:
            validate_rclone_destination(destination)
            source, normalized_source = self._remote_path(
                destination, source_path
            )
        except ValueError as exc:
            raise RcloneError(
                "Path rclone harus berada di bawah root yang dikonfigurasi.",
                code="RCLONE_BROWSER_PATH_INVALID",
            ) from exc
        source_parts = normalized_source.split("/") if normalized_source else []
        if not source_parts:
            raise RcloneError(
                "Root rclone tidak dapat di-rename.",
                code="RCLONE_BROWSER_PATH_INVALID",
            )
        source_name = source_parts[-1]
        parent_path = "/".join(source_parts[:-1])
        new_entry_name = self._remote_entry_name(new_name)
        if new_entry_name == source_name:
            return {"action": "rename", "path": normalized_source, "unchanged": True}
        target_relative = "/".join(
            part for part in (parent_path, new_entry_name) if part
        )
        target, normalized_target = self._remote_path(destination, target_relative)
        remote_parent, _ = self._remote_path(destination, parent_path)
        config = self._storage_config(config_path, config_root)
        children = self._list_storage_children(
            remote_parent, config, log_prefix="rclone-storage-rename-check"
        )
        sources = [item for item in children if str(item.get("Name") or "") == source_name]
        if not sources:
            raise RcloneError(
                "File atau folder yang akan di-rename tidak ditemukan.",
                code="RCLONE_SOURCE_NOT_FOUND",
            )
        if len(sources) != 1:
            raise RcloneError(
                "Nama sumber tidak unik pada remote; operasi dibatalkan.",
                code="RCLONE_SOURCE_AMBIGUOUS",
            )
        source_is_dir = sources[0].get("IsDir") is True
        if any(str(item.get("Name") or "") == new_entry_name for item in children):
            raise RcloneError(
                "Nama tujuan rclone sudah ada.",
                code="RCLONE_TARGET_EXISTS",
            )
        self._run_storage_command(
            [
                "rclone",
                "moveto",
                source,
                target,
                "--ignore-existing",
                "--config",
                str(config),
                "--log-level",
                "ERROR",
            ],
            log_prefix="rclone-storage-rename",
        )
        remaining = self._list_storage_children(
            remote_parent, config, log_prefix="rclone-storage-rename-verify"
        )
        renamed = [item for item in remaining if str(item.get("Name") or "") == new_entry_name]
        source_remains = any(str(item.get("Name") or "") == source_name for item in remaining)
        if source_remains:
            raise RcloneError(
                "Hasil rename belum dapat dipastikan; sumber masih tersedia.",
                code="RCLONE_OPERATION_AMBIGUOUS",
            )
        if len(renamed) != 1 or (renamed[0].get("IsDir") is True) != source_is_dir:
            raise RcloneError(
                "Hasil rename belum dapat dipastikan pada remote.",
                code="RCLONE_OPERATION_AMBIGUOUS",
            )
        return {"action": "rename", "path": normalized_target}

    def ensure_directory(
        self,
        destination: str,
        relative_path: str,
        config_path: Path,
        *,
        config_root: Path,
        create_new: bool,
        created_by_job: bool = False,
    ) -> str:
        """Resolve an existing folder or safely create a job-owned child folder."""
        try:
            validate_rclone_destination(destination)
            remote, normalized = RcloneRunner._remote_path(destination, relative_path)
        except ValueError as exc:
            raise RcloneError("Path tujuan Quick Mode tidak valid.", code="RCLONE_BROWSER_PATH_INVALID") from exc
        config = Path(config_path).resolve()
        try:
            config.relative_to(Path(config_root).resolve())
        except ValueError as exc:
            raise RcloneError("Konfigurasi rclone tidak tersedia untuk worker ini.") from exc
        if not config.is_file() or shutil.which("rclone") is None:
            raise RcloneError("Runtime rclone belum tersedia pada worker.", code="RCLONE_RUNTIME_UNAVAILABLE")
        if not normalized:
            if create_new:
                raise RcloneError("Nama subfolder Quick Mode wajib diisi.", code="RCLONE_TARGET_INVALID")
            return remote

        def run(command: list[str], log_prefix: str):
            try:
                result = self.runner.run(
                    command,
                    log_prefix=log_prefix,
                    output_callback=self.log_callback,
                    stall_timeout_seconds=self.stall_timeout_seconds,
                    command_callback=self.command_callback,
                )
            except (TDLStalledError, TDLCommandError, OSError) as exc:
                raise RcloneError("Worker tidak dapat memeriksa folder tujuan Quick Mode.", code="RCLONE_ACCESS_FAILED") from exc
            if result.returncode != 0:
                raise RcloneError("Worker tidak dapat memeriksa folder tujuan Quick Mode.", code="RCLONE_ACCESS_FAILED")
            return result

        def list_children(parent_name: str) -> list[object]:
            parent, _ = self._remote_path(destination, parent_name)
            listing = run(
                [
                    "rclone", "lsjson", parent, "--max-depth", "1", "--no-modtime",
                    "--no-mimetype", "--config", str(config), "--log-level", "ERROR",
                ],
                "rclone-quickmode-target-check",
            )
            try:
                entries = json.loads(getattr(listing, "stdout", "") or "[]")
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RcloneError("Worker menerima listing rclone yang tidak valid.") from exc
            if not isinstance(entries, list):
                raise RcloneError("Worker menerima listing rclone yang tidak valid.")
            return entries

        if create_new and not created_by_job:
            parent_name, _, child_name = normalized.rpartition("/")
            entries = list_children(parent_name)
            if any(
                isinstance(entry, dict) and str(entry.get("Name") or "") == child_name
                for entry in entries
            ):
                raise RcloneError(
                    "Nama folder tujuan Quick Mode sudah ada. Pilih folder lain.",
                    code="RCLONE_TARGET_EXISTS",
                )
            run(
                ["rclone", "mkdir", remote, "--config", str(config), "--log-level", "ERROR"],
                "rclone-quickmode-target-create",
            )
        elif not create_new and not created_by_job:
            # A selected existing folder must still be present when execution
            # starts; don't silently create a missing path during upload.
            parent_name, _, child_name = normalized.rpartition("/")
            entries = list_children(parent_name)
            if not any(
                isinstance(entry, dict)
                and str(entry.get("Name") or "") == child_name
                and entry.get("IsDir") is True
                for entry in entries
            ):
                raise RcloneError(
                    "Folder tujuan Quick Mode tidak lagi tersedia.",
                    code="RCLONE_TARGET_NOT_FOUND",
                )
        elif created_by_job:
            # Recovery after an interrupted mkdir/upload reuses the original
            # path. The manifest is the durable proof this stage owns it.
            run(
                ["rclone", "mkdir", remote, "--config", str(config), "--log-level", "ERROR"],
                "rclone-quickmode-target-recovery",
            )
        return remote

    def list_download_files(
        self,
        destination: str,
        selections: Iterable[dict[str, object]],
        config_path: Path,
        *,
        config_root: Path,
    ) -> list[dict[str, object]]:
        """Expand selected rclone files and folders below the configured root."""
        try:
            validate_rclone_destination(destination)
        except ValueError as exc:
            raise RcloneError("Root rclone tidak valid.") from exc
        config = Path(config_path).resolve()
        try:
            config.relative_to(Path(config_root).resolve())
        except ValueError as exc:
            raise RcloneError("Konfigurasi rclone tidak tersedia untuk worker ini.") from exc
        if not config.is_file() or shutil.which("rclone") is None:
            raise RcloneError("Runtime rclone belum tersedia pada worker.", code="RCLONE_RUNTIME_UNAVAILABLE")

        files: dict[str, dict[str, object]] = {}
        for selected in selections:
            if not isinstance(selected, dict):
                raise RcloneError("Pilihan sumber rclone tidak valid.")
            raw_path = str(selected.get("path") or "")
            is_dir = selected.get("is_dir") is True
            remote, normalized = self._remote_path(destination, raw_path)
            if not normalized:
                raise RcloneError("Path sumber rclone tidak valid.")
            if not is_dir:
                name = normalized.rsplit("/", 1)[-1]
                candidate = {
                    "remote_path": remote,
                    "relative_path": name,
                    "name": name,
                    "size": (
                        max(0, int(selected["size"]))
                        if isinstance(selected.get("size"), int)
                        and not isinstance(selected.get("size"), bool)
                        and int(selected["size"]) >= 0
                        else None
                    ),
                }
                previous = files.get(remote)
                if previous is None or len(str(candidate["relative_path"])) > len(str(previous["relative_path"])):
                    files[remote] = candidate
                continue

            command = ["rclone", "lsjson", remote, "--recursive", "--config", str(config), "--log-level", "ERROR"]
            try:
                result = self.runner.run(
                    command,
                    log_prefix="rclone-storage-download-list",
                    output_callback=self.log_callback,
                    stall_timeout_seconds=self.stall_timeout_seconds,
                    command_callback=self.command_callback,
                )
            except (TDLStalledError, TDLCommandError, OSError) as exc:
                raise RcloneError("Worker tidak dapat membaca folder rclone.", code="RCLONE_ACCESS_FAILED") from exc
            if result.returncode != 0:
                raise RcloneError("Worker tidak dapat membaca folder rclone.", code=self._access_error_code(result) or "RCLONE_ACCESS_FAILED")
            try:
                entries = json.loads(getattr(result, "stdout", "") or "[]")
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RcloneError("Worker menerima listing rclone yang tidak valid.") from exc
            if not isinstance(entries, list):
                raise RcloneError("Worker menerima listing rclone yang tidak valid.")
            if len(entries) > 2000:
                raise RcloneError(
                    "Pilihan melebihi batas 2000 file.", code="STORAGE_SELECTION_TOO_LARGE"
                )
            folder_name = normalized.rsplit("/", 1)[-1]
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("IsDir") is True:
                    continue
                relative = str(entry.get("Path") or entry.get("Name") or "").replace("\\", "/")
                parts = relative.split("/")
                if not relative or relative.startswith("/") or any(
                    not part or part in {".", ".."} or ":" in part for part in parts
                ):
                    raise RcloneError("Pilihan folder rclone berisi path file yang tidak valid.")
                child_remote, _ = self._remote_path(
                    destination, f"{normalized}/{relative}"
                )
                try:
                    size = max(0, int(entry.get("Size") or 0))
                except (TypeError, ValueError):
                    size = None
                relative_target = "/".join((folder_name, relative))
                candidate = {
                    "remote_path": child_remote,
                    "relative_path": relative_target,
                    "name": parts[-1],
                    "size": size,
                }
                previous = files.get(child_remote)
                if previous is None or len(relative_target) > len(str(previous["relative_path"])):
                    files[child_remote] = candidate
                if len(files) > 2000:
                    raise RcloneError(
                        "Pilihan melebihi batas 2000 file.", code="STORAGE_SELECTION_TOO_LARGE"
                    )
        return [files[key] for key in sorted(files)]

    def download_file(
        self,
        remote_path: str,
        destination_path: Path,
        config_path: Path,
        *,
        config_root: Path,
        file_name: str = "",
        total_bytes: int | None = None,
    ) -> None:
        """Download one remote file to an isolated temporary path."""
        config = Path(config_path).resolve()
        try:
            config.relative_to(Path(config_root).resolve())
        except ValueError as exc:
            raise RcloneError("Konfigurasi rclone tidak tersedia untuk worker ini.") from exc
        if not config.is_file() or shutil.which("rclone") is None:
            raise RcloneError("Runtime rclone belum tersedia pada worker.", code="RCLONE_RUNTIME_UNAVAILABLE")
        command = [
            "rclone", "copyto", str(remote_path), str(destination_path),
            "--config", str(config), "--log-level", "NOTICE",
            "--stats", "1s", "--stats-log-level", "NOTICE", "--use-json-log",
        ]
        try:
            result = self.runner.run(
                command,
                log_prefix="rclone-storage-download",
                output_callback=self._transfer_log_callback(
                    self.transfer_callback,
                    file_name=file_name or Path(destination_path).name,
                    file_size=total_bytes,
                    log_callback=self.log_callback,
                ),
                output_filter=self._keep_non_stats_output_line,
                stall_timeout_seconds=self.stall_timeout_seconds,
                command_callback=self.command_callback,
            )
        except TDLStalledError as exc:
            raise RcloneError(
                "rclone download berhenti merespons.", code="RCLONE_DOWNLOAD_FAILED"
            ) from exc
        except TDLCommandError as exc:
            raise RcloneError("rclone gagal mengunduh file.", code=self._access_error_code(exc) or "RCLONE_DOWNLOAD_FAILED") from exc
        except OSError as exc:
            raise RcloneError("Worker tidak dapat memulai proses rclone.", code="RCLONE_RUNTIME_UNAVAILABLE") from exc
        if result.returncode != 0:
            raise RcloneError("rclone gagal mengunduh file.", code=self._access_error_code(result) or "RCLONE_DOWNLOAD_FAILED")

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
            file_size = path.stat().st_size

            def on_transfer(value: dict[str, object]) -> None:
                if self.transfer_callback is not None:
                    self.transfer_callback({**value, "index": index, "total": len(paths)})

            command = [
                "rclone",
                "copyto",
                str(path),
                target,
                "--config",
                str(config),
                "--log-level",
                "NOTICE",
                "--stats",
                "1s",
                "--stats-log-level",
                "NOTICE",
                "--use-json-log",
            ]
            if ignore_existing:
                command.extend(["--ignore-existing"])
            try:
                result = self.runner.run(
                    command,
                    log_prefix="rclone-upload",
                    output_callback=self._transfer_log_callback(
                        on_transfer,
                        file_name=normalized_name,
                        file_size=file_size,
                        log_callback=self.log_callback,
                    ),
                    output_filter=self._keep_non_stats_output_line,
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
