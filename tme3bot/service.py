from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tme3bot.config import AppConfig
from tme3bot.media import has_downloadable_media, is_image_message
from tme3bot.progress import DownloadProgressTracker
from tme3bot.state import SourceState, StateStore
from tme3bot.tdl import ExportResult, TDLClient, TDLCommandError
from tme3bot.url_parser import ParsedTme3Url, parse_tme3_url, slugify_label


@dataclass(frozen=True)
class ExportJobResult:
    status: str
    chat_ref: str
    requested_label: str | None
    export_path: Path
    start_id: int
    latest_id: int | None
    exported_count: int
    has_media: bool
    warmup_required: bool
    warning: str | None = None


@dataclass(frozen=True)
class DownloadedJsonResult:
    json_path: Path
    download_dir: Path
    status: str
    error: str | None = None


@dataclass(frozen=True)
class BatchDownloadResult:
    moved_count: int
    success_count: int
    failed_count: int
    results: list[DownloadedJsonResult]


class ExportService:
    def __init__(
        self, config: AppConfig, state_store: StateStore, tdl_client: TDLClient
    ) -> None:
        self.config = config
        self.state_store = state_store
        self.tdl_client = tdl_client

    def validate_url(self, url: str) -> ParsedTme3Url:
        return parse_tme3_url(url, self.config.tme3_host)

    def export_from_url(
        self,
        url: str,
        use_url_message_id: bool = False,
        save_source: bool | None = None,
    ) -> ExportJobResult:
        parsed = self.validate_url(url)
        source = self.state_store.get_source(parsed.chat_ref)
        is_new_source = source is None
        # Numeric Telegram references are often one-off private/channel IDs.
        # Do not create persistent state for those unless the caller explicitly
        # opts in. Existing saved numeric sources remain persistent so their
        # monotonic last_id continues to work as before.
        is_numeric_source = parsed.chat_ref.strip().lstrip("-").isdigit()
        persist_source = (
            bool(save_source)
            if save_source is not None
            else (source is not None or not is_numeric_source)
        )
        start_id = self._resolve_start_id(parsed, source, use_url_message_id)
        export_path = self._next_export_path(parsed)
        temp_path = self._next_temp_path(export_path.name)

        export_result = self.tdl_client.export_messages(
            parsed.chat_ref, start_id, temp_path
        )
        warmup_url = (
            self._select_warmup_url(parsed, export_result) if is_new_source else None
        )
        warmup_required = warmup_url is not None
        self._write_export_metadata(temp_path, parsed, warmup_required, warmup_url)

        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path = unique_path(export_path)
        shutil.move(str(temp_path), str(export_path))

        latest_id = source.last_id if source is not None else None
        if export_result.max_message_id is not None:
            next_last_id = max(
                export_result.max_message_id,
                source.last_id if source is not None else export_result.max_message_id,
            )
            latest_id = next_last_id
            if persist_source:
                self.state_store.upsert_source(
                    parsed.chat_ref,
                    parsed.canonical_label if parsed.requested_label else None,
                    next_last_id,
                    warmup_url=warmup_url,
                    warmup_done=False if warmup_required else None,
                )
        elif persist_source and source is not None and parsed.requested_label:
            self.state_store.upsert_source(
                parsed.chat_ref, parsed.canonical_label, source.last_id
            )

        return ExportJobResult(
            status="exported" if export_result.exported_count else "empty_export",
            chat_ref=parsed.chat_ref,
            requested_label=parsed.requested_label,
            export_path=export_path,
            start_id=start_id,
            latest_id=latest_id,
            exported_count=export_result.exported_count,
            has_media=export_result.has_media,
            warmup_required=warmup_required,
        )

    def _resolve_start_id(
        self,
        parsed: ParsedTme3Url,
        source: SourceState | None,
        use_url_message_id: bool,
    ) -> int:
        if source is None or use_url_message_id:
            return parsed.bootstrap_message_id
        return source.last_id + 1

    def _next_export_path(self, parsed: ParsedTme3Url) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        chat_component = slugify_label(parsed.chat_ref.lstrip("@") or parsed.chat_ref)
        parts = [timestamp, chat_component]
        label = parsed.canonical_label if parsed.requested_label else None
        if label:
            parts.insert(0, label)
        return self.config.export_pending_dir / ("_".join(parts) + ".json")

    def _next_temp_path(self, filename: str) -> Path:
        self.config.temp_root.mkdir(parents=True, exist_ok=True)
        return unique_path(self.config.temp_root / filename)

    def _select_warmup_url(
        self, parsed: ParsedTme3Url, export_result: ExportResult
    ) -> str | None:
        message = self._select_warmup_message(export_result.messages)
        if message is None:
            return None

        message_id = message.get("id")
        if not isinstance(message_id, int):
            return None
        return build_telegram_message_url(parsed.chat_ref, message_id)

    @staticmethod
    def _select_warmup_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        media_messages = [
            message
            for message in messages
            if isinstance(message.get("id"), int) and has_downloadable_media(message)
        ]
        if not media_messages:
            return None

        image_messages = [
            message for message in media_messages if is_image_message(message)
        ]
        if image_messages:
            return min(image_messages, key=lambda message: int(message.get("id", 0)))
        return min(media_messages, key=lambda message: int(message.get("id", 0)))

    @staticmethod
    def _write_export_metadata(
        export_path: Path,
        parsed: ParsedTme3Url,
        warmup_required: bool,
        warmup_url: str | None,
    ) -> None:
        payload = json.loads(export_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["tme3bot"] = {
                "chat_ref": parsed.chat_ref,
                "label": parsed.canonical_label if parsed.requested_label else None,
                "warmup_url": warmup_url,
                "warmup_required": warmup_required,
            }
            export_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8"
            )


class BatchDownloadService:
    def __init__(
        self,
        config: AppConfig,
        state_store: StateStore,
        tdl_client: TDLClient,
        progress_tracker: DownloadProgressTracker | None = None,
    ) -> None:
        self.config = config
        self.state_store = state_store
        self.tdl_client = tdl_client
        self.progress_tracker = progress_tracker or DownloadProgressTracker()

    def download_pending_exports(self) -> BatchDownloadResult:
        pending_files = sorted(self.config.export_pending_dir.glob("*.json"))
        moved_files = [self._move_to_processing(path) for path in pending_files]
        return self._download_files(moved_files, mode="download")

    def download_selected_exports(
        self, artifact_keys: list[str]
    ) -> BatchDownloadResult:
        """Download selected opaque filenames after strict directory validation."""
        return self.download_selected_artifacts(
            [{"key": key, "status": "pending"} for key in artifact_keys]
        )

    def download_selected_artifacts(
        self, artifacts: list[dict[str, str]]
    ) -> BatchDownloadResult:
        """Download selected pending/failed JSON files from validated roots."""
        selected: list[Path] = []
        roots = {
            "pending": self.config.export_pending_dir.resolve(),
            "failed": self.config.export_failed_dir.resolve(),
        }
        for artifact in artifacts:
            key = str(artifact.get("key") or "")
            if Path(key).name != key or not key.lower().endswith(".json"):
                raise ValueError("Artifact key tidak valid.")
            source_root = roots.get(str(artifact.get("status") or "pending"))
            if source_root is None:
                raise ValueError("Status artifact tidak dapat dijalankan.")
            path = (source_root / key).resolve()
            try:
                path.relative_to(source_root)
            except ValueError as exc:
                raise ValueError("Artifact key keluar dari direktori export.") from exc
            if not path.is_file():
                raise FileNotFoundError(f"Artifact tidak ditemukan: {key}")
            selected.append(path)
        moved_files = [self._move_to_processing(path) for path in selected]
        return self._download_files(moved_files, mode="selected")

    def retry_failed_exports(self) -> BatchDownloadResult:
        failed_files = sorted(self.config.export_failed_dir.glob("*.json"))
        moved_files = [self._move_to_processing(path) for path in failed_files]
        return self._download_files(moved_files, mode="retry_failed")

    def download_export_to(
        self,
        export_json: Path,
        download_dir: Path,
        *,
        delete_json_on_success: bool = True,
    ) -> DownloadedJsonResult:
        """Download one export into a caller-owned staging directory.

        Quick Mode owns the downloaded tree and must not publish the JSON to
        the normal Download Manager.  The JSON is still moved through
        ``processing`` so a failed TDL command follows the regular failed
        artifact path.
        """
        candidate = Path(export_json).resolve()
        roots = {
            "pending": self.config.export_pending_dir.resolve(),
            "failed": self.config.export_failed_dir.resolve(),
            "processing": self.config.export_processing_dir.resolve(),
        }
        source_root = next(
            (root for root in roots.values() if _is_relative_to(candidate, root)),
            None,
        )
        if source_root is None or not candidate.is_file():
            raise ValueError("Export JSON Quick Mode tidak berada di direktori yang valid.")
        moved = (
            self._move_to_processing(candidate)
            if source_root != roots["processing"]
            else candidate
        )
        batch = self._download_files(
            [moved],
            mode="quick",
            download_dir_overrides={moved: Path(download_dir)},
            delete_json_on_success=delete_json_on_success,
        )
        return batch.results[0]

    def clear_failed_exports(self) -> int:
        failed_files = sorted(self.config.export_failed_dir.glob("*.json"))
        for path in failed_files:
            path.unlink()
        return len(failed_files)

    def _download_files(
        self,
        moved_files: list[Path],
        mode: str,
        *,
        download_dir_overrides: dict[Path, Path] | None = None,
        delete_json_on_success: bool = False,
    ) -> BatchDownloadResult:
        results: list[DownloadedJsonResult] = []
        self.progress_tracker.start_batch(mode=mode, total_json=len(moved_files))

        try:
            for index, export_json in enumerate(moved_files, start=1):
                media_ids = media_ids_in_export(export_json)
                self.progress_tracker.start_json(
                    index, len(moved_files), export_json.name, media_ids
                )
                download_dir = (download_dir_overrides or {}).get(
                    export_json, self._download_dir_for_export(export_json)
                )
                try:
                    download_dir.mkdir(parents=True, exist_ok=True)
                    self.progress_tracker.set_phase("warmup")
                    self._warmup_if_needed(export_json, download_dir)
                    self.progress_tracker.set_phase("downloading")
                    try:
                        self.tdl_client.download(export_json, download_dir)
                    except TDLCommandError as exc:
                        if not self._is_chat_id_invalid(exc):
                            raise
                        self.progress_tracker.set_phase("warmup")
                        self._force_warmup(export_json, download_dir, exc)
                        self.progress_tracker.set_phase("downloading")
                        self.tdl_client.download(export_json, download_dir)
                except Exception as exc:
                    failed_path = unique_path(
                        self.config.export_failed_dir / export_json.name
                    )
                    failed_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(export_json), str(failed_path))
                    error = (
                        str(getattr(exc, "stderr", "") or "").strip()
                        or str(getattr(exc, "stdout", "") or "").strip()
                        or str(exc)
                    )
                    self.progress_tracker.finish_json(False, error=error[:500])
                    results.append(
                        DownloadedJsonResult(
                            json_path=failed_path,
                            download_dir=download_dir,
                            status="failed",
                            error=error,
                        )
                    )
                    continue

                if delete_json_on_success:
                    export_json.unlink()
                    done_path = export_json
                    result_status = "success_deleted"
                else:
                    done_path = unique_path(self.config.export_done_dir / export_json.name)
                    done_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(export_json), str(done_path))
                    result_status = "success"
                self.progress_tracker.finish_json(True)
                results.append(
                    DownloadedJsonResult(
                        json_path=done_path,
                        download_dir=download_dir,
                        status=result_status,
                    )
                )
        finally:
            self.progress_tracker.finish_batch()

        success_count = sum(
            1 for result in results if result.status in {"success", "success_deleted"}
        )
        failed_count = sum(1 for result in results if result.status == "failed")
        return BatchDownloadResult(
            moved_count=len(moved_files),
            success_count=success_count,
            failed_count=failed_count,
            results=results,
        )

    def _download_dir_for_export(self, export_json: Path) -> Path:
        metadata = self._read_export_metadata(export_json)
        raw_label = metadata.get("label")
        if raw_label:
            named_folder = slugify_label(export_json.stem) or "tanpa-label"
            return self.config.download_root / "berlabel" / named_folder

        plain_name = slugify_label(export_json.stem) or "tanpa-label"
        return self.config.download_root / "biasa" / plain_name

    def _warmup_if_needed(self, export_json: Path, download_dir: Path) -> None:
        metadata = self._read_export_metadata(export_json)
        chat_ref = str(metadata.get("chat_ref") or "")
        warmup_url = str(metadata.get("warmup_url") or "")
        if not chat_ref or not warmup_url:
            return

        source = self.state_store.get_source(chat_ref)
        if source is None:
            # A numeric one-off export may deliberately not be persisted as a
            # source, but its export metadata still carries the warmup URL.
            # Warm it up once from the artifact metadata so download does not
            # fail with CHAT_ID_INVALID.
            if not bool(metadata.get("warmup_required")):
                return
            warmup_dir = download_dir / "__warmup"
            try:
                self.tdl_client.download_url(warmup_url, warmup_dir)
            finally:
                shutil.rmtree(warmup_dir, ignore_errors=True)
            return
        if source.warmup_done:
            return

        warmup_dir = download_dir / "__warmup"
        try:
            self.tdl_client.download_url(warmup_url, warmup_dir)
        finally:
            shutil.rmtree(warmup_dir, ignore_errors=True)
        self.state_store.mark_warmup_done(chat_ref)

    def _force_warmup(
        self,
        export_json: Path,
        download_dir: Path,
        failure: TDLCommandError,
    ) -> None:
        """Resolve a chat in the active download session, then allow one retry."""
        metadata = self._read_export_metadata(export_json)
        chat_ref = str(metadata.get("chat_ref") or "").strip()
        if not chat_ref:
            output = f"{failure.stdout}\n{failure.stderr}\n{failure}"
            match = re.search(r"failed to get result from\s+(-?\d+)", output, re.I)
            if match:
                chat_ref = match.group(1)
        warmup_url = str(metadata.get("warmup_url") or "").strip()
        if not warmup_url and chat_ref:
            media_ids = media_ids_in_export(export_json)
            if media_ids:
                warmup_url = build_telegram_message_url(chat_ref, min(media_ids))
        if not warmup_url:
            raise TDLCommandError(
                failure.command,
                failure.returncode,
                failure.stdout,
                "CHAT_ID_INVALID dan URL warm-up tidak dapat ditentukan dari export JSON.",
            ) from failure

        warmup_dir = download_dir / "__warmup"
        try:
            self.tdl_client.download_url(warmup_url, warmup_dir)
        finally:
            shutil.rmtree(warmup_dir, ignore_errors=True)
        if chat_ref:
            self.state_store.mark_warmup_done(chat_ref)

    @staticmethod
    def _is_chat_id_invalid(exc: TDLCommandError) -> bool:
        output = f"{exc.stdout}\n{exc.stderr}\n{exc}".upper()
        return "CHAT_ID_INVALID" in output

    @staticmethod
    def _read_export_metadata(export_json: Path) -> dict[str, Any]:
        try:
            payload = json.loads(export_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        metadata = payload.get("tme3bot", {})
        return metadata if isinstance(metadata, dict) else {}

    def _move_to_processing(self, path: Path) -> Path:
        self.config.export_processing_dir.mkdir(parents=True, exist_ok=True)
        destination = unique_path(self.config.export_processing_dir / path.name)
        shutil.move(str(path), str(destination))
        return destination


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def build_telegram_message_url(chat_ref: str, message_id: int) -> str:
    cleaned = chat_ref.strip()
    if cleaned.startswith("@"):
        return f"https://t.me/{cleaned.lstrip('@')}/{message_id}"

    numeric = cleaned.lstrip("-")
    if numeric.isdigit():
        if cleaned.startswith("-100") and len(cleaned) > 4:
            numeric = cleaned[4:]
        return f"https://t.me/c/{numeric}/{message_id}"

    return f"https://t.me/{cleaned}/{message_id}"


def media_ids_in_export(export_json: Path) -> list[int]:
    try:
        payload = json.loads(export_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        return []
    ids: list[int] = []
    for message in messages:
        if (
            isinstance(message, dict)
            and isinstance(message.get("id"), int)
            and has_downloadable_media(message)
        ):
            ids.append(message["id"])
    return ids
