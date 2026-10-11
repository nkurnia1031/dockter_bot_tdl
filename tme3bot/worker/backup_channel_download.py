"""Download only the cataloged archive messages from the backup channel."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from tme3bot.media import has_downloadable_media


class BackupChannelDownloadError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def download_backup_parts(
    client: Any,
    *,
    channel_ref: str,
    parts: list[dict[str, Any]],
    destination: Path,
    progress: Callable[[str, int, int, str], None] | None = None,
) -> list[Path]:
    """Fetch selected Telegram message IDs, filtering every export before `tdl dl`.

    The worker never downloads arbitrary channel history: each export uses the
    exact catalog message ID and the JSON passed to `tdl dl` is filtered again.
    Output filenames come from the backend catalog, not from channel captions.
    """
    if not channel_ref or not parts or len(parts) > 200:
        raise BackupChannelDownloadError("BACKUP_SELECTION_INVALID")
    normalized: list[tuple[int, str]] = []
    names: set[str] = set()
    for item in parts:
        if not isinstance(item, dict):
            raise BackupChannelDownloadError("BACKUP_SELECTION_INVALID")
        message_id = item.get("channel_message_id")
        name = str(item.get("part_name") or "")
        if (
            type(message_id) is not int
            or message_id < 1
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", name)
            or Path(name).name != name
            or ".7z" not in name.lower()
            or name in names
        ):
            raise BackupChannelDownloadError("BACKUP_SELECTION_INVALID")
        names.add(name)
        normalized.append((message_id, name))

    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        destination.chmod(0o700)
    except OSError:
        pass

    downloaded: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="backup-channel-") as raw_temp:
        work = Path(raw_temp)
        for index, (message_id, part_name) in enumerate(normalized, start=1):
            export_path = work / f"message-{message_id}.json"
            download_dir = work / f"download-{message_id}"
            if progress is not None:
                progress("exporting", index, len(normalized), part_name)
            try:
                client.export_messages(
                    channel_ref,
                    message_id,
                    export_path,
                    with_content=True,
                    end_id=message_id,
                )
            except Exception:
                raise BackupChannelDownloadError("BACKUP_CHANNEL_EXPORT_FAILED") from None

            try:
                payload = json.loads(export_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise BackupChannelDownloadError("BACKUP_CHANNEL_EXPORT_INVALID") from None
            messages = payload.get("messages") if isinstance(payload, dict) else None
            exact = [
                row
                for row in messages or []
                if isinstance(row, dict) and str(row.get("id") or "") == str(message_id)
            ] if isinstance(messages, list) else []
            if len(exact) != 1:
                raise BackupChannelDownloadError("BACKUP_CHANNEL_MESSAGE_MISSING")
            if not has_downloadable_media(exact[0]):
                raise BackupChannelDownloadError("BACKUP_CHANNEL_MEDIA_MISSING")

            # Restrict TDL's input file to the one cataloged message even if a
            # version of `chat export` returns neighboring IDs.
            payload["messages"] = exact
            export_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            try:
                if progress is not None:
                    progress("downloading", index, len(normalized), part_name)
                client.download(export_path, download_dir)
            except Exception:
                raise BackupChannelDownloadError("BACKUP_CHANNEL_DOWNLOAD_FAILED") from None

            matches = [
                path
                for path in download_dir.iterdir()
                if path.is_file()
                and not path.is_symlink()
                and path.name.startswith(f"{message_id}_")
            ] if download_dir.is_dir() else []
            if len(matches) != 1:
                raise BackupChannelDownloadError("BACKUP_CHANNEL_MEDIA_MISSING")

            target = destination / part_name
            if target.exists() or target.is_symlink():
                raise BackupChannelDownloadError("BACKUP_PART_DESTINATION_EXISTS")
            try:
                shutil.move(str(matches[0]), str(target))
            except OSError:
                raise BackupChannelDownloadError("BACKUP_CHANNEL_DOWNLOAD_FAILED") from None
            downloaded.append(target)
            if progress is not None:
                progress("downloaded", index, len(normalized), part_name)
    return downloaded
