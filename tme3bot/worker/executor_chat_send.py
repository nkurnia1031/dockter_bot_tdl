from __future__ import annotations

import os
import time
from contextlib import ExitStack
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from tme3bot.tdl import tdl_access_denial_code


class ChatSendExecutorMixin:
    """Send Workspace files directly to a Telegram chat without catalog writes."""

    def _chat_send(self, command: dict[str, Any]) -> dict[str, Any]:
        job_id = str(command["job_id"])
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        chat_ref = str(payload.get("chat_ref") or "").strip()
        raw_profiles = payload.get("_tdl_sender_profiles")
        profiles = list(dict.fromkeys(
            str(item).strip().lower()
            for item in raw_profiles
            if str(item).strip()
        )) if isinstance(raw_profiles, list) else []
        if not profiles:
            profiles = [str(command.get("profile") or "").strip().lower()]
        if not profiles or not profiles[0]:
            raise ValueError("CHAT_SEND_PROFILES_REQUIRED: pilih setidaknya satu profil TDL.")

        retry_paths = payload.get("_retry_paths")
        retry_allowed: set[str] | None = None
        if isinstance(retry_paths, list):
            retry_allowed = set()
            for raw_path in retry_paths:
                value = str(raw_path or "")
                relative_path = PurePosixPath(value)
                if (
                    not value or relative_path.is_absolute() or ".." in relative_path.parts
                    or any(part in {"", "."} for part in relative_path.parts)
                    or relative_path.as_posix() != value
                ):
                    raise ValueError("CHAT_SEND_RETRY_INVALID: path Retry tidak aman.")
                retry_allowed.add(value)
            if not retry_allowed:
                raise ValueError("CHAT_SEND_RETRY_INVALID: tidak ada file Retry yang dipilih.")

        roots = self._chat_send_roots(
            payload.get("folders"), allow_missing=retry_allowed is not None
        )
        discovered = self._chat_send_files(roots)
        targets: list[tuple[Path, str, bool]] = [
            (path, self._chat_send_relative(path), False) for path in discovered
        ]
        if retry_allowed is not None:
            root_relatives = {
                "" if root == Path(self.config.utility_workspace_root).resolve()
                else root.relative_to(Path(self.config.utility_workspace_root).resolve()).as_posix()
                for root in roots
            }
            for relative in retry_allowed:
                if not any(
                    not root or relative == root or relative.startswith(root.rstrip("/") + "/")
                    for root in root_relatives
                ):
                    raise ValueError("CHAT_SEND_RETRY_INVALID: file Retry di luar folder pilihan.")
            discovered_by_relative = {relative: path for path, relative, _missing in targets}
            targets = [
                (discovered_by_relative[relative], relative, False)
                for relative in retry_allowed if relative in discovered_by_relative
            ] + [
                (Path(self.config.utility_workspace_root).resolve().joinpath(*PurePosixPath(relative).parts), relative, True)
                for relative in retry_allowed if relative not in discovered_by_relative
            ]
        targets.sort(key=lambda item: (item[1].casefold(), item[1]))

        # Capture every selected file before the first upload. Move cleanup
        # must compare against the job's starting identity, including files
        # that will not reach the front of the batch until much later.
        source_identities: dict[str, tuple[int, int, int, int] | None] = {}
        total_bytes = 0
        for path, _relative, missing in targets:
            if missing:
                continue
            try:
                identity = self._chat_send_file_identity(path)
            except OSError:
                identity = None
            source_identities[_relative] = identity
            if identity is not None:
                total_bytes += max(0, identity[2])
        succeeded = failed = ambiguous = completed_bytes = 0
        results: list[dict[str, Any]] = []
        verifier = self._telegram_upload_verifier(job_id)
        pending_verifications: list[tuple[dict[str, Any], Any, Path, list[Path], tuple[int, int, int, int], str, int]] = []
        self._chat_send_progress(
            job_id, phase="scanning", message=f"Menemukan {len(targets)} file untuk dikirim",
            current=0, total=len(targets), succeeded=0, failed=0, ambiguous=0,
            bytes_current=0, bytes_total=total_bytes, indeterminate=False,
        )

        sender_index = 0
        transfer_mode = str(payload.get("transfer_mode") or "copy").strip().lower()
        if transfer_mode not in {"copy", "move"}:
            transfer_mode = "copy"
        for index, (path, relative, missing) in enumerate(targets, start=1):
            if missing:
                failed += 1
                result = self._chat_send_item(
                    path, relative, status="failed", error_code="CHAT_SEND_SOURCE_MISSING",
                    retryable=False,
                )
                results.append(result)
                self._chat_send_progress(
                    job_id, phase="uploading", message=f"Sumber tidak ditemukan: {relative}",
                    current=index, total=len(targets), succeeded=succeeded, failed=failed,
                    ambiguous=ambiguous, bytes_current=completed_bytes,
                    bytes_total=total_bytes,
                    item={
                        "name": path.name, "path": relative, "index": index,
                        "total": len(targets), "status": "failed",
                        "error_code": "CHAT_SEND_SOURCE_MISSING", "percent": 100,
                    },
                    indeterminate=False, force=True,
                )
                continue
            source_identity = source_identities.get(relative)
            size = source_identity[2] if source_identity is not None else 0

            if self._job_cancelled(job_id):
                results.append(self._chat_send_item(
                    path, relative, status="cancelled", error_code="JOB_TERMINATED",
                    retryable=False,
                    **({"cleanup_status": "retained_upload_failed"} if transfer_mode == "move" else {}),
                ))
                continue
            if source_identity is None:
                result = self._chat_send_item(
                    path, relative, status="failed", error_code="CHAT_SEND_SOURCE_CHANGED",
                    retryable=True,
                )
                if transfer_mode == "move":
                    result["cleanup_status"] = "cleanup_skipped_source_changed"
                results.append(result)
                failed += 1
                completed_bytes += size
                continue

            self._chat_send_progress(
                job_id, phase="uploading", message=f"Mengirim {path.name}",
                current=index - 1, total=len(targets), succeeded=succeeded,
                failed=failed, ambiguous=ambiguous, bytes_current=completed_bytes,
                bytes_total=total_bytes,
                item={
                    "name": path.name, "path": relative, "index": index,
                    "total": len(targets), "size_bytes": size,
                    "profile": profiles[sender_index], "percent": 0,
                },
                indeterminate=False,
                force=True,
            )

            file_start_index = sender_index
            order = [(file_start_index + offset) % len(profiles) for offset in range(len(profiles))]
            attempts: list[dict[str, Any]] = []
            result: dict[str, Any] | None = None
            last_fallback_allowed = False
            for current_sender_index in order:
                sender = profiles[current_sender_index]
                attempt_result = self._chat_send_one(
                    job_id=job_id, path=path, relative=relative, chat_ref=chat_ref,
                    profile=sender, attempt=len(attempts) + 1,
                    total=len(targets), index=index, succeeded=succeeded, failed=failed,
                    ambiguous=ambiguous, completed_bytes=completed_bytes,
                    total_bytes=total_bytes, size=size,
                    source_identity=source_identity,
                )
                fallback_allowed = bool(attempt_result.pop("_fallback_allowed", False))
                last_fallback_allowed = fallback_allowed
                result = attempt_result
                if result["status"] == "accepted":
                    verification = verifier.record_upload(
                        profile=sender,
                        chat_ref=chat_ref,
                        filename=path.name,
                        caption=path.name,
                        uploaded_at=float(result.pop("_uploaded_at", time.time())),
                    )
                    if verification.status == "verified":
                        result["status"] = "succeeded"
                        result["message_id"] = verification.message_id
                    else:
                        result["status"] = "pending_verification"
                        pending_verifications.append((
                            result, verification, path, roots, source_identity,
                            transfer_mode, index,
                        ))
                    sender_index = (current_sender_index + 1) % len(profiles)
                attempts.append({
                    "profile": sender,
                    "status": result["status"],
                    **({"error_code": attempt_result["error_code"]} if attempt_result.get("error_code") else {}),
                })
                if result["status"] == "succeeded":
                    break
                if result["status"] == "pending_verification":
                    break
                if not fallback_allowed:
                    break

            assert result is not None
            if result["status"] != "succeeded" and last_fallback_allowed:
                sender_index = (file_start_index + 1) % len(profiles)
            result["attempts"] = attempts
            result["attempt"] = len(attempts)
            if result["status"] == "succeeded":
                succeeded += 1
                if transfer_mode == "move":
                    result["cleanup_status"] = self._chat_send_remove_source(
                        path, roots, source_identity
                    )
            elif result["status"] == "ambiguous":
                ambiguous += 1
                if transfer_mode == "move":
                    result["cleanup_status"] = "retained_ambiguous"
            elif result["status"] == "pending_verification":
                if transfer_mode == "move":
                    result["cleanup_status"] = "retained_ambiguous"
            else:
                failed += 1
                if transfer_mode == "move":
                    result["cleanup_status"] = (
                        "cleanup_skipped_source_changed"
                        if result.get("error_code") == "CHAT_SEND_SOURCE_CHANGED"
                        else "retained_upload_failed"
                    )
            completed_bytes += size
            self._chat_send_progress(
                job_id, phase="uploading", message=f"Selesai memproses {path.name}",
                current=index, total=len(targets), succeeded=succeeded, failed=failed,
                ambiguous=ambiguous, bytes_current=completed_bytes,
                bytes_total=total_bytes,
                item={
                    "name": path.name, "path": relative, "index": index,
                    "total": len(targets), "size_bytes": size,
                    "profile": result.get("profile") or profiles[sender_index],
                    "status": result["status"], "cleanup_status": result.get("cleanup_status"),
                    "percent": 100,
                },
                indeterminate=False,
                force=True,
            )
            results.append(result)

        if pending_verifications:
            verifier.finalize()
            for result, verification, path, roots, source_identity, mode, index in pending_verifications:
                if verification.status == "verified":
                    result["status"] = "succeeded"
                    result["message_id"] = verification.message_id
                    result.pop("error_code", None)
                    succeeded += 1
                    if mode == "move":
                        result["cleanup_status"] = self._chat_send_remove_source(
                            path, roots, source_identity
                        )
                else:
                    result["status"] = "ambiguous"
                    result["error_code"] = verification.error_code or "TELEGRAM_UPLOAD_NOT_FOUND"
                    result["retryable"] = False
                    ambiguous += 1
                    if mode == "move":
                        result["cleanup_status"] = "retained_ambiguous"
                if result.get("attempts"):
                    result["attempts"][-1]["status"] = result["status"]
                self._chat_send_progress(
                    job_id,
                    phase="verifying",
                    message=(
                        f"Terverifikasi: {path.name}"
                        if verification.status == "verified"
                        else f"Belum terverifikasi: {path.name}"
                    ),
                    current=index,
                    total=len(targets),
                    succeeded=succeeded,
                    failed=failed,
                    ambiguous=ambiguous,
                    bytes_current=completed_bytes,
                    bytes_total=total_bytes,
                    item={
                        "name": path.name,
                        "path": result["path"],
                        "index": index,
                        "total": len(targets),
                        "profile": result.get("profile"),
                        "status": result["status"],
                        "cleanup_status": result.get("cleanup_status"),
                        "error_code": result.get("error_code"),
                        "percent": 100,
                    },
                    indeterminate=False,
                    force=True,
                )

        outcome = "succeeded"
        if failed or ambiguous:
            outcome = "partial_failure" if succeeded else "failed"
        return {
            "outcome": outcome, "total": len(results), "succeeded": succeeded,
            "failed": failed, "ambiguous": ambiguous, "items": results,
        }

    def _chat_send_one(
        self, *, job_id: str, path: Path, relative: str, chat_ref: str,
        profile: str, attempt: int, total: int, index: int, succeeded: int,
        failed: int, ambiguous: int, completed_bytes: int, total_bytes: int,
        size: int, source_identity: tuple[int, int, int, int],
    ) -> dict[str, Any]:
        command_started = False

        def update_transfer(progress) -> None:
            percent = getattr(progress, "percent", None)
            transferred = getattr(progress, "transferred_bytes", None)
            transfer = {
                key: value
                for key, value in {
                    "speed_bps": getattr(progress, "speed_bps", None),
                    "speed_text": getattr(progress, "speed", None),
                    "eta_seconds": getattr(progress, "eta_seconds", None),
                    "bytes_current": transferred,
                    "bytes_total": size,
                }.items()
                if value is not None
            }
            item = {
                "name": path.name, "path": relative, "index": index,
                "total": total, "size_bytes": size, "profile": profile,
            }
            if percent is not None:
                item["percent"] = max(0.0, min(100.0, float(percent)))
            self.publisher.emit(
                job_id, "running", "chat_send.progress", transient=True,
                progress={
                    "phase": "uploading", "message": f"Mengirim {path.name}",
                    "overall": {
                        "current": index - 1, "total": total,
                        "percent": (index - 1) * 100 / total if total else 100,
                        "unit": "files",
                        "bytes_current": completed_bytes + int(transferred or 0),
                        "bytes_total": total_bytes,
                    },
                    "item": item, "transfer": transfer,
                    "counters": {"succeeded": succeeded, "failed": failed, "ambiguous": ambiguous},
                    "indeterminate": percent is None,
                },
            )

        def upload_phase(phase: str) -> None:
            nonlocal command_started
            if phase == "uploading":
                self._before_job_command(job_id)
                command_started = True

        try:
            runtime = self.profile_manager.runtime(profile)
            client = runtime.upload_tdl_client
            lock = getattr(runtime, "upload_operation_lock", None)
            with ExitStack() as stack:
                if lock is not None:
                    stack.enter_context(lock)
                try:
                    current_identity = self._chat_send_file_identity(path)
                except OSError:
                    current_identity = None
                if current_identity != source_identity:
                    return self._chat_send_item(
                        path, relative, status="failed", profile=profile,
                        attempt=attempt, error_code="CHAT_SEND_SOURCE_CHANGED",
                        retryable=True,
                    )
                capture_output = getattr(self, "_capture_tdl_output", None)
                if callable(capture_output):
                    stack.enter_context(capture_output(
                        client,
                        command_callback=self._command_callback(profile=profile, runtime="upload"),
                    ))
                capture_progress = getattr(self, "_capture_tdl_progress", None)
                if callable(capture_progress):
                    stack.enter_context(capture_progress(client, update_transfer))
                uploaded = client.upload(path, chat_ref, path.name, status_callback=upload_phase)
            message_id = getattr(uploaded, "message_id", None)
            accepted = self._chat_send_item(
                path, relative, status="accepted", profile=profile,
                attempt=attempt, retryable=False,
            )
            if isinstance(message_id, int) and not isinstance(message_id, bool) and message_id > 0:
                accepted["message_id_hint"] = message_id
            accepted["_uploaded_at"] = time.time()
            return accepted
        except Exception as exc:
            if self._job_cancelled(job_id):
                status = "ambiguous" if command_started else "cancelled"
                return self._chat_send_item(
                    path, relative, status=status, profile=profile, attempt=attempt,
                    error_code="TDL_SEND_AMBIGUOUS" if command_started else "JOB_TERMINATED",
                    retryable=False,
                )
            denial = tdl_access_denial_code(exc)
            if denial:
                item = self._chat_send_item(
                    path, relative, status="failed", profile=profile, attempt=attempt,
                    error_code=denial, retryable=True,
                )
                item["_fallback_allowed"] = True
                return item
            return self._chat_send_item(
                path, relative, status="ambiguous" if command_started else "failed",
                profile=profile, attempt=attempt,
                error_code="TDL_SEND_AMBIGUOUS" if command_started else "TDL_SEND_NOT_STARTED",
                retryable=not command_started,
            )

    def _chat_send_roots(self, raw_folders: Any, *, allow_missing: bool = False) -> list[Path]:
        if not isinstance(raw_folders, list) or not raw_folders:
            raise ValueError("CHAT_SEND_FOLDERS_REQUIRED: pilih setidaknya satu folder Workspace.")
        roots: list[Path] = []
        for raw in raw_folders:
            candidate = Path(str(raw or ""))
            if candidate.is_symlink():
                raise ValueError("CHAT_SEND_FOLDER_INVALID: folder symlink tidak didukung.")
            root = self._workspace_path(str(raw or ""), require_absolute=True)
            if not root.is_dir():
                if not allow_missing or root.exists():
                    raise ValueError("CHAT_SEND_FOLDER_MISSING: folder Workspace tidak ditemukan.")
            if root not in roots:
                roots.append(root)
        roots.sort(key=lambda path: (len(path.parts), path.as_posix().casefold()))
        selected: list[Path] = []
        for root in roots:
            if any(root == parent or parent in root.parents for parent in selected):
                continue
            selected.append(root)
        return selected

    def _chat_send_files(self, roots: list[Path]) -> list[Path]:
        files: set[Path] = set()
        workspace_root = Path(self.config.utility_workspace_root).resolve()
        for root in roots:
            for current, directories, names in os.walk(root, followlinks=False):
                current_path = Path(current)
                directories[:] = sorted(
                    name for name in directories if not (current_path / name).is_symlink()
                )
                for name in sorted(names):
                    path = current_path / name
                    try:
                        if path.is_symlink() or not path.is_file():
                            continue
                        resolved = path.resolve(strict=True)
                        resolved.relative_to(workspace_root)
                        files.add(resolved)
                    except (OSError, ValueError):
                        continue
        return sorted(
            files,
            key=lambda path: (self._chat_send_relative(path).casefold(), self._chat_send_relative(path)),
        )

    def _chat_send_file_identity(self, path: Path) -> tuple[int, int, int, int]:
        if path.is_symlink() or not path.is_file():
            raise OSError("File sumber berubah sebelum dikirim.")
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(Path(self.config.utility_workspace_root).resolve())
        except ValueError as exc:
            raise OSError("File sumber keluar dari Workspace.") from exc
        metadata = resolved.stat()
        return (
            int(metadata.st_dev), int(metadata.st_ino), int(metadata.st_size), int(metadata.st_mtime_ns),
        )

    def _chat_send_remove_source(
        self, path: Path, roots: list[Path], expected: tuple[int, int, int, int] | None,
    ) -> str:
        if expected is None:
            return "cleanup_skipped_source_changed"
        try:
            if self._chat_send_file_identity(path) != expected:
                return "cleanup_skipped_source_changed"
            path.unlink()
        except FileNotFoundError:
            return "cleanup_skipped_source_changed"
        except OSError:
            return "cleanup_failed"
        for root in roots:
            try:
                path.relative_to(root)
            except ValueError:
                continue
            directory = path.parent
            while directory != root.parent:
                try:
                    directory.rmdir()
                except OSError:
                    break
                if directory == root:
                    break
                directory = directory.parent
        return "deleted"

    def _chat_send_relative(self, path: Path) -> str:
        root = Path(self.config.utility_workspace_root).resolve()
        try:
            return path.relative_to(root).as_posix()
        except ValueError as exc:
            raise OSError("File sumber keluar dari Workspace.") from exc

    @staticmethod
    def _chat_send_item(
        path: Path, relative: str, *, status: str, profile: str = "",
        attempt: int = 1, message_id: int | None = None,
        error_code: str = "", retryable: bool,
    ) -> dict[str, Any]:
        item = {
            "path": relative, "name": path.name, "status": status,
            "profile": profile, "attempt": attempt, "retryable": retryable,
        }
        if message_id is not None:
            item["message_id"] = message_id
        if error_code:
            item["error_code"] = error_code
        return item

    def _chat_send_progress(
        self, job_id: str, *, phase: str, message: str, current: int, total: int,
        succeeded: int, failed: int, ambiguous: int, bytes_current: int,
        bytes_total: int, item: dict[str, Any] | None = None,
        indeterminate: bool, force: bool = False,
    ) -> None:
        self.publisher.emit(
            job_id, "running", "chat_send.progress", transient=not force,
            progress={
                "phase": phase, "message": message,
                "overall": {
                    "current": current, "total": total,
                    "percent": current * 100 / total if total else 100,
                    "unit": "files", "bytes_current": bytes_current,
                    "bytes_total": bytes_total,
                },
                "item": item or {}, "transfer": {},
                "counters": {"succeeded": succeeded, "failed": failed, "ambiguous": ambiguous},
                "indeterminate": indeterminate,
            },
        )
