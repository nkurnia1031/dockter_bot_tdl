"""Discover and download one worker backup from the configured Telegram channel."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tme3bot.media import has_downloadable_media
from tme3bot.profile_provisioning import MAX_PROFILE_BUNDLE_BYTES

_SCAN_LAST_MESSAGES = 1000
_SAFE_PART_NAME = re.compile(r"[A-Za-z0-9_.+-]{1,200}\Z")
_BACKUP_IDENTITIES = (
    re.compile(
        r"\bBackup\s+node=(?P<node>[A-Za-z0-9_.-]{1,64})\s+run=(?P<run>[A-Za-z0-9_.-]{1,128})",
        re.IGNORECASE,
    ),
    re.compile(
        r"#node_(?P<node>[A-Za-z0-9_.-]{1,64})\s+#run_(?P<run>[A-Za-z0-9_.-]{1,128})",
        re.IGNORECASE,
    ),
)
_PART_NAME = re.compile(r"\bPart:\s*(?P<name>[A-Za-z0-9_.+-]{1,200})(?=\s|$)", re.IGNORECASE)


class BackupChannelDownloadError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DownloadedBackupPart:
    path: Path
    message_id: int


def download_profile_distribution_artifact(
    client: Any,
    *,
    channel_ref: str,
    node_name: str,
    operation_id: str,
    profile: str,
    revision: int,
    destination: Path,
    message_ids: list[int] | None = None,
    message_id: int | None = None,
    archive_sha256: str = "",
) -> Path:
    """Download one exact encrypted Vault artifact, bound by its channel caption."""
    if (
        not channel_ref
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", str(node_name or ""))
        or not re.fullmatch(r"[0-9a-fA-F-]{36}", str(operation_id or ""))
        or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", str(profile or ""))
        or type(revision) is not int or revision < 1
    ):
        raise BackupChannelDownloadError("PROFILE_DISTRIBUTION_METADATA_INVALID")
    selected_ids = list(message_ids) if isinstance(message_ids, list) else ([message_id] if message_id else [])
    if (
        not selected_ids or len(selected_ids) > 100
        or any(type(value) is not int or value < 1 for value in selected_ids)
        or len(set(selected_ids)) != len(selected_ids)
        or (archive_sha256 and not re.fullmatch(r"[a-fA-F0-9]{64}", archive_sha256))
    ):
        raise BackupChannelDownloadError("PROFILE_DISTRIBUTION_METADATA_INVALID")

    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        destination.chmod(0o700)
    except OSError:
        pass
    target = destination / f"{operation_id}.enc"
    if target.exists() or target.is_symlink():
        raise BackupChannelDownloadError("PROFILE_DISTRIBUTION_DESTINATION_EXISTS")
    try:
        with tempfile.TemporaryDirectory(prefix="profile-distribution-") as raw_temp:
            work = Path(raw_temp)
            total_bytes = 0
            with target.open("xb") as output:
                for part_index, selected_message_id in enumerate(selected_ids, start=1):
                    export_path = work / f"channel-messages-{part_index}.json"
                    try:
                        client.export_messages(
                            channel_ref, selected_message_id, export_path,
                            with_content=True, end_id=selected_message_id,
                        )
                        payload = json.loads(export_path.read_text(encoding="utf-8"))
                    except Exception:
                        raise BackupChannelDownloadError("BACKUP_CHANNEL_EXPORT_FAILED") from None
                    messages = payload.get("messages") if isinstance(payload, dict) else None
                    if not isinstance(messages, list):
                        raise BackupChannelDownloadError("BACKUP_CHANNEL_EXPORT_INVALID")
                    rows = [
                        row for row in messages
                        if isinstance(row, dict) and _message_id(row.get("id")) == selected_message_id
                    ]
                    if len(rows) != 1:
                        raise BackupChannelDownloadError("PROFILE_DISTRIBUTION_MESSAGE_NOT_FOUND")
                    row = rows[0]
                    caption = row.get("caption") if isinstance(row.get("caption"), str) else row.get("text")
                    if not isinstance(caption, str) or not _distribution_caption_matches(
                        caption, node_name, operation_id, profile, revision,
                        part_index, len(selected_ids), archive_sha256,
                    ):
                        raise BackupChannelDownloadError("PROFILE_DISTRIBUTION_BINDING_MISMATCH")
                    if not has_downloadable_media(row):
                        raise BackupChannelDownloadError("BACKUP_CHANNEL_MEDIA_MISSING")
                    one_message = work / f"message-{selected_message_id}.json"
                    download_dir = work / f"download-{selected_message_id}"
                    try:
                        payload["messages"] = [row]
                        one_message.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                        download_dir.mkdir(parents=True, mode=0o700)
                        client.download(one_message, download_dir)
                    except Exception:
                        raise BackupChannelDownloadError("BACKUP_CHANNEL_DOWNLOAD_FAILED") from None
                    media = [
                        path for path in download_dir.iterdir()
                        if path.is_file() and not path.is_symlink() and path.name.startswith(f"{selected_message_id}_")
                    ] if download_dir.is_dir() else []
                    if len(media) != 1:
                        raise BackupChannelDownloadError("BACKUP_CHANNEL_MEDIA_MISSING")
                    total_bytes += media[0].stat().st_size
                    if total_bytes > MAX_PROFILE_BUNDLE_BYTES + 28:
                        raise BackupChannelDownloadError("PROFILE_ARCHIVE_TOO_LARGE")
                    with media[0].open("rb") as part_file:
                        shutil.copyfileobj(part_file, output)
            return target
    except Exception:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _message_id(value: Any) -> int | None:
    if type(value) is int:
        return value if value > 0 else None
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value):
        return int(value)
    return None


def _distribution_caption_matches(
    caption: str, worker: str, operation_id: str, profile: str, revision: int,
    part_index: int, part_total: int, archive_sha256: str = "",
) -> bool:
    expected = {
        "Operation": operation_id,
        "Profile": profile,
        "Revision": str(revision),
        "Worker": worker,
        "Part-Index": str(part_index),
        "Part-Total": str(part_total),
    }
    if archive_sha256:
        expected["Archive-SHA256"] = archive_sha256.lower()
    rows = {}
    for line in caption.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            rows[key.strip()] = value.strip()
    return "#profile_distribution" in caption.splitlines() and all(rows.get(key) == value for key, value in expected.items())


def download_backup_parts(
    client: Any,
    *,
    channel_ref: str,
    node_name: str,
    run_id: str,
    parts: list[dict[str, Any]],
    destination: Path,
    progress: Callable[..., None] | None = None,
) -> list[DownloadedBackupPart]:
    """Export channel JSON first, match this worker/run's captions, then dl by ID.

    Catalog rows are deliberately not used as message-ID authority. Older or
    partially recorded rows can lack IDs/checksums/status even though Telegram
    still has the uploaded files. The backup captions carry the selected node,
    run prefix, and original part name needed to find the correct messages.
    """
    if (
        not channel_ref
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", str(node_name or ""))
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", str(run_id or ""))
        or not isinstance(parts, list)
        or len(parts) > 200
    ):
        raise BackupChannelDownloadError("BACKUP_SELECTION_INVALID")

    expected_names: set[str] = set()
    for item in parts:
        if not isinstance(item, dict):
            raise BackupChannelDownloadError("BACKUP_SELECTION_INVALID")
        name = str(item.get("part_name") or "")
        if not _safe_part_name(name) or name in expected_names:
            raise BackupChannelDownloadError("BACKUP_SELECTION_INVALID")
        expected_names.add(name)

    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        destination.chmod(0o700)
    except OSError:
        pass

    downloaded: list[DownloadedBackupPart] = []
    with tempfile.TemporaryDirectory(prefix="backup-channel-") as raw_temp:
        work = Path(raw_temp)
        export_path = work / "channel-messages.json"
        if progress is not None:
            progress("scanning", 0, 0, "")
        try:
            client.export_messages(
                channel_ref,
                1,
                export_path,
                with_content=True,
                last_count=_SCAN_LAST_MESSAGES,
            )
        except Exception:
            raise BackupChannelDownloadError("BACKUP_CHANNEL_EXPORT_FAILED") from None

        try:
            payload = json.loads(export_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise BackupChannelDownloadError("BACKUP_CHANNEL_EXPORT_INVALID") from None
        messages = payload.get("messages") if isinstance(payload, dict) else None
        if not isinstance(messages, list):
            raise BackupChannelDownloadError("BACKUP_CHANNEL_EXPORT_INVALID")

        matches: dict[str, tuple[int, dict[str, Any]]] = {}
        for row in messages:
            if not isinstance(row, dict):
                continue
            metadata = _backup_caption_metadata(row)
            if metadata is None:
                continue
            message_node, message_run, part_name = metadata
            if (
                message_node.casefold() != node_name.casefold()
                or not _run_matches(message_run, run_id)
            ):
                continue
            if not _safe_part_name(part_name) or ".7z" not in part_name.casefold():
                raise BackupChannelDownloadError("BACKUP_CHANNEL_PART_NAME_INVALID")
            raw_message_id = row.get("id")
            if type(raw_message_id) is int:
                message_id = raw_message_id
            elif isinstance(raw_message_id, str) and re.fullmatch(r"[1-9][0-9]{0,18}", raw_message_id):
                message_id = int(raw_message_id)
            else:
                raise BackupChannelDownloadError("BACKUP_CHANNEL_MESSAGE_ID_INVALID") from None
            if message_id < 1:
                raise BackupChannelDownloadError("BACKUP_CHANNEL_MESSAGE_ID_INVALID")
            if not has_downloadable_media(row):
                raise BackupChannelDownloadError("BACKUP_CHANNEL_MEDIA_MISSING")
            if part_name in matches:
                raise BackupChannelDownloadError("BACKUP_CHANNEL_PART_AMBIGUOUS")
            matches[part_name] = (message_id, row)

        if not matches:
            raise BackupChannelDownloadError("BACKUP_CHANNEL_PARTS_NOT_FOUND")
        if expected_names and not expected_names.issubset(matches):
            raise BackupChannelDownloadError("BACKUP_CHANNEL_PARTS_INCOMPLETE")
        if len(matches) > 200:
            raise BackupChannelDownloadError("BACKUP_SELECTION_INVALID")

        selected = sorted(matches.items(), key=lambda item: item[0].casefold())
        for index, (part_name, (message_id, row)) in enumerate(selected, start=1):
            if progress is not None:
                progress("matched", index, len(selected), part_name, message_id)

        for index, (part_name, (message_id, row)) in enumerate(selected, start=1):
            single_message_export = work / f"message-{message_id}.json"
            download_dir = work / f"download-{message_id}"
            payload["messages"] = [row]
            try:
                single_message_export.write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                )
                download_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                if progress is not None:
                    progress("downloading", index, len(selected), part_name, message_id)
                client.download(single_message_export, download_dir)
            except BackupChannelDownloadError:
                raise
            except Exception:
                raise BackupChannelDownloadError("BACKUP_CHANNEL_DOWNLOAD_FAILED") from None

            media = [
                path
                for path in download_dir.iterdir()
                if path.is_file()
                and not path.is_symlink()
                and path.name.startswith(f"{message_id}_")
            ] if download_dir.is_dir() else []
            if len(media) != 1:
                raise BackupChannelDownloadError("BACKUP_CHANNEL_MEDIA_MISSING")

            target = destination / part_name
            if target.exists() or target.is_symlink():
                raise BackupChannelDownloadError("BACKUP_PART_DESTINATION_EXISTS")
            try:
                shutil.move(str(media[0]), str(target))
            except OSError:
                raise BackupChannelDownloadError("BACKUP_CHANNEL_DOWNLOAD_FAILED") from None
            downloaded.append(DownloadedBackupPart(target, message_id))
            if progress is not None:
                progress("downloaded", index, len(selected), part_name, message_id)
    return downloaded


def _backup_caption_metadata(message: dict[str, Any]) -> tuple[str, str, str] | None:
    caption = message.get("caption")
    if not isinstance(caption, str) or not caption.strip():
        caption = message.get("text")
    if not isinstance(caption, str):
        return None
    identity = next((match for pattern in _BACKUP_IDENTITIES if (match := pattern.search(caption))), None)
    part = _PART_NAME.search(caption)
    if identity is None or part is None:
        return None
    return identity.group("node"), identity.group("run"), part.group("name")


def _run_matches(caption_run_id: str, selected_run_id: str) -> bool:
    caption_run_id = caption_run_id.casefold()
    selected_run_id = selected_run_id.casefold()
    if caption_run_id == selected_run_id:
        return True
    # Backup captions intentionally store the first 12 chars to keep them short.
    return len(caption_run_id) == 12 and selected_run_id.startswith(caption_run_id)


def _safe_part_name(name: str) -> bool:
    return bool(
        _SAFE_PART_NAME.fullmatch(name)
        and Path(name).name == name
        and ".7z" in name.casefold()
    )
