#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import stat
import unicodedata
from collections import OrderedDict
from pathlib import Path, PurePosixPath


JSON_EXPORT_RE = re.compile(r"^messages(?P<part>\d*)\.json$", re.IGNORECASE)
POTENTIAL_PHOTO_THRESHOLD = 10
POTENTIAL_FOLDER_SUFFIX = "-potensial"


def ordered_dedupe(values):
    return list(OrderedDict.fromkeys(item for item in values if item))


def sanitize_folder_name(name: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return cleaned or "untitled"


def part_sort_key(path: Path):
    match = JSON_EXPORT_RE.match(path.name)
    if not match:
        return (1, path.name.lower())

    suffix = match.group("part")
    return (0 if suffix == "" else int(suffix), path.name.lower())


def discover_json_files(base_dir: Path):
    files = [path for path in base_dir.iterdir() if path.is_file() and JSON_EXPORT_RE.match(path.name)]
    return sorted(files, key=part_sort_key)


def json_to_source_html(json_path: Path) -> str:
    match = JSON_EXPORT_RE.match(json_path.name)
    if not match:
        return json_path.with_suffix(".html").name

    suffix = match.group("part")
    return "messages.html" if suffix == "" else f"messages{suffix}.html"


def read_payload(json_path: Path):
    payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
    normalized = []
    default_source_html = json_to_source_html(json_path) if JSON_EXPORT_RE.match(json_path.name) else None

    for raw_entry in payload:
        entry = dict(raw_entry)
        entry_type = entry.get("entry_type", "root")
        entry["entry_type"] = entry_type
        entry["photos"] = ordered_dedupe(entry.get("photos", []))
        entry["videos"] = ordered_dedupe(entry.get("videos", []))
        if default_source_html:
            entry.setdefault("source_html", default_source_html)

        normalized.append(entry)

    return normalized


def write_payload(json_path: Path, payload):
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def unique_file_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    original = Path(filename)
    stem = original.stem
    suffix = original.suffix
    index = 2
    while True:
        candidate = directory / f"{stem}__{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def href_to_path(base_dir: Path, href: str) -> Path:
    posix_path = PurePosixPath(href)
    return base_dir.joinpath(*posix_path.parts)


def flatten_media(entry):
    photos = ordered_dedupe(entry.get("photos", []))
    videos = ordered_dedupe(entry.get("videos", []))
    return [(href, "photo") for href in photos] + [(href, "video") for href in videos]


def is_thumb_file(path: Path) -> bool:
    stem = path.stem.lower()
    return "_thumb" in stem


def normalize_href_key(href: str) -> str:
    return str(PurePosixPath(href)).lower()


def collect_referenced_media_from_html(base_dir: Path):
    try:
        from telegram_messages_to_json import discover_html_files as discover_html_exports
        from telegram_messages_to_json import parse_messages
    except Exception:
        return set()

    references = set()
    for html_path in discover_html_exports(base_dir):
        html_text = html_path.read_text(encoding="utf-8-sig")
        for message in parse_messages(html_text, html_path.name):
            references.update(normalize_href_key(href) for href in entry_media_hrefs(message))
    return references


def entry_media_hrefs(entry):
    return ordered_dedupe(entry.get("photos", []) + entry.get("videos", []))


def entry_identity(entry, default_source_html=None):
    source_html = entry.get("source_html") or entry.get("target_source_html") or default_source_html
    message_id = entry.get("message_id") or entry.get("target_message_id")
    if not source_html or not message_id:
        return None
    return source_html, message_id


def entry_label(entry):
    label = str(entry.get("label") or entry.get("target_message_id") or "").strip()
    return label or "untitled"


def entry_photo_count(entry) -> int:
    return len(ordered_dedupe(entry.get("photos", [])))


def target_folder_name(entry, potential_folder_names) -> str:
    safe_name = sanitize_folder_name(entry_label(entry))
    if safe_name in potential_folder_names and not safe_name.lower().endswith(POTENTIAL_FOLDER_SUFFIX):
        return f"{safe_name}{POTENTIAL_FOLDER_SUFFIX}"
    return safe_name


def ensure_target_directory(
    entry,
    base_dir: Path,
    folder_registry,
    created_folders,
    default_source_html,
    report,
    potential_folder_names,
):
    identity = entry_identity(entry, default_source_html)
    if identity and identity in folder_registry:
        return folder_registry[identity]

    folder_name = target_folder_name(entry, potential_folder_names)
    target_dir = base_dir / folder_name
    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        created_folders.add(target_dir)
        report["folders_created"] += 1

    if identity:
        folder_registry[identity] = target_dir

    return target_dir


def move_media_items(media_items, target_dir: Path, base_dir: Path, report):
    moved_items = []
    skipped_items = []

    for href, media_type in media_items:
        source = href_to_path(base_dir, href)
        if not source.exists():
            report["skipped_missing"] += 1
            skipped_items.append((href, media_type, "missing source file"))
            print(f"  skip ({media_type}): {href} [missing]")
            continue

        destination = unique_file_path(target_dir, source.name)
        if destination.name != source.name:
            report["renamed_files"] += 1

        try:
            shutil.move(str(source), str(destination))
            report["moved"] += 1
            moved_items.append((href, media_type, destination.name))
            print(f"  moved ({media_type}): {href} -> {target_dir.name}/{destination.name}")
        except Exception as exc:
            report["errors"] += 1
            skipped_items.append((href, media_type, f"move failed: {exc}"))
            print(f"  error ({media_type}): {href} [{exc}]")

    return moved_items, skipped_items


def register_skipped_media(skipped_entries, entry, origin_json_name, href, media_type, reason, default_source_html):
    if reason == "missing source file":
        return

    identity = entry_identity(entry, default_source_html)
    key = identity or (
        origin_json_name,
        entry.get("label") or entry.get("target_message_id") or "untitled",
        entry.get("target_source_html"),
        entry.get("target_message_id"),
    )

    if key not in skipped_entries:
        skipped_entries[key] = {
            "entry_type": entry.get("entry_type", "root"),
            "source_html": entry.get("source_html") or entry.get("target_source_html") or default_source_html,
            "message_id": entry.get("message_id") or entry.get("target_message_id"),
            "sequence": entry.get("sequence"),
            "label": entry.get("label") or entry.get("target_message_id") or "untitled",
            "label_resolved": entry.get("label_resolved"),
            "target_source_html": entry.get("target_source_html"),
            "target_message_id": entry.get("target_message_id"),
            "derived_from_source_html": entry.get("derived_from_source_html"),
            "derived_from_message_ids": list(entry.get("derived_from_message_ids", [])),
            "photos": [],
            "videos": [],
            "skip_reasons": [],
            "origin_jsons": [],
        }

    bucket = skipped_entries[key]
    bucket["origin_jsons"] = ordered_dedupe(bucket["origin_jsons"] + [origin_json_name])
    bucket["skip_reasons"] = ordered_dedupe(bucket["skip_reasons"] + [reason])

    if media_type == "photo":
        bucket["photos"] = ordered_dedupe(bucket["photos"] + [href])
    else:
        bucket["videos"] = ordered_dedupe(bucket["videos"] + [href])


def serialize_skipped_entries(skipped_entries):
    payload = []
    for bucket in skipped_entries.values():
        payload.append(
            {
                key: value
                for key, value in bucket.items()
                if key not in {"photos", "videos", "skip_reasons", "origin_jsons"}
            }
            | {
                "photos": ordered_dedupe(bucket["photos"]),
                "videos": ordered_dedupe(bucket["videos"]),
                "skip_reasons": ordered_dedupe(bucket["skip_reasons"]),
                "origin_jsons": ordered_dedupe(bucket["origin_jsons"]),
            }
        )
    return payload


def cleanup_empty_directories(directories, report, log_lines):
    def on_remove_error(func, path, exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
        except Exception:
            pass
        func(path)

    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        try:
            if directory.is_dir() and not any(directory.iterdir()):
                shutil.rmtree(directory, onerror=on_remove_error)
                report["folders_removed"] += 1
                log_lines.append(f"cleanup | removed empty folder | {directory.name}")
        except Exception as exc:
            report["errors"] += 1
            log_lines.append(f"cleanup | error removing {directory} | {exc}")


def collect_referenced_media(base_dir: Path, json_paths):
    references = collect_referenced_media_from_html(base_dir)
    if references:
        return references

    fallback = set()
    for json_path in json_paths:
        for entry in read_payload(json_path):
            fallback.update(normalize_href_key(href) for href in entry_media_hrefs(entry))
    return fallback


def collect_potential_folder_names(payloads):
    folder_photo_totals = OrderedDict()

    for payload in payloads:
        for entry in payload:
            safe_name = sanitize_folder_name(entry_label(entry))
            folder_photo_totals[safe_name] = folder_photo_totals.get(safe_name, 0) + entry_photo_count(entry)

    return {
        folder_name
        for folder_name, photo_total in folder_photo_totals.items()
        if photo_total > POTENTIAL_PHOTO_THRESHOLD
    }


def crosscheck_unreferenced_media(base_dir: Path, referenced_media, report, log_lines):
    bucket_root = base_dir / "not_in_html"

    for folder_name in ("photos", "video_files"):
        source_dir = base_dir / folder_name
        if not source_dir.is_dir():
            continue

        for source in sorted(source_dir.iterdir(), key=lambda item: item.name.lower()):
            if not source.is_file() or is_thumb_file(source):
                continue

            href = str(PurePosixPath(folder_name, source.name))
            if normalize_href_key(href) in referenced_media:
                continue

            target_dir = bucket_root / folder_name
            if not target_dir.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
                report["crosscheck_folders_created"] += 1

            destination = unique_file_path(target_dir, source.name)
            if destination.name != source.name:
                report["renamed_files"] += 1

            try:
                shutil.move(str(source), str(destination))
                report["crosscheck_moved"] += 1
                log_lines.append(
                    f"crosscheck | moved not-in-html | {href} | {bucket_root.name}/{folder_name}/{destination.name}"
                )
            except Exception as exc:
                report["errors"] += 1
                report["crosscheck_errors"] += 1
                log_lines.append(f"crosscheck | error moving {href} | {exc}")


def organize_single_payload(
    json_path: Path,
    payload,
    base_dir: Path,
    report,
    folder_registry,
    created_folders,
    skipped_entries,
    log_lines,
    potential_folder_names,
):
    default_source_html = json_to_source_html(json_path) if JSON_EXPORT_RE.match(json_path.name) else None

    for entry in payload:
        label = entry_label(entry)
        target_dir = ensure_target_directory(
            entry,
            base_dir,
            folder_registry,
            created_folders,
            default_source_html,
            report,
            potential_folder_names,
        )
        identity = entry_identity(entry, default_source_html)
        identity_text = f"{identity[0]}/{identity[1]}" if identity else "unknown"

        print(f"\n[{label}] -> {target_dir.name}")
        log_lines.append(f"{json_path.name} | {identity_text} | start | {label}")

        moved_items, skipped_items = move_media_items(flatten_media(entry), target_dir, base_dir, report)
        for href, media_type, reason in skipped_items:
            log_lines.append(f"{json_path.name} | {identity_text} | skip {media_type} | {href} | {reason}")
            register_skipped_media(skipped_entries, entry, json_path.name, href, media_type, reason, default_source_html)

        if moved_items:
            log_lines.append(
                f"{json_path.name} | {identity_text} | moved {len(moved_items)} item{'s' if len(moved_items) != 1 else ''}"
            )

    return None


def organize_batch(json_paths, base_dir: Path):
    report = {
        "folders_created": 0,
        "moved": 0,
        "skipped_missing": 0,
        "renamed_files": 0,
        "errors": 0,
        "folders_removed": 0,
        "crosscheck_folders_created": 0,
        "crosscheck_moved": 0,
        "crosscheck_errors": 0,
    }

    folder_registry = {}
    created_folders = set()
    skipped_entries = OrderedDict()
    log_lines = []
    payloads = []

    for json_path in json_paths:
        payload = read_payload(json_path)
        payloads.append(payload)

    potential_folder_names = collect_potential_folder_names(payloads)

    for json_path, payload in zip(json_paths, payloads):
        organize_single_payload(
            json_path,
            payload,
            base_dir,
            report,
            folder_registry,
            created_folders,
            skipped_entries,
            log_lines,
            potential_folder_names,
        )

    cleanup_empty_directories(created_folders, report, log_lines)
    crosscheck_unreferenced_media(base_dir, collect_referenced_media(base_dir, json_paths), report, log_lines)

    log_path = base_dir / "log.txt"
    skipped_path = base_dir / "skipped.json"
    log_path.write_text("\n".join(log_lines) + ("\n" if log_lines else ""), encoding="utf-8")
    write_payload(skipped_path, serialize_skipped_entries(skipped_entries))

    print(
        f"\nDone. folders={report['folders_created']} moved={report['moved']} "
        f"missing={report['skipped_missing']} renamed={report['renamed_files']} "
        f"errors={report['errors']} cleaned={report['folders_removed']} "
        f"crosscheck_folders={report['crosscheck_folders_created']} "
        f"crosscheck_moved={report['crosscheck_moved']}"
    )
    print(f"Log: {log_path}")
    print(f"Skipped JSON: {skipped_path}")


def main():
    script_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(description="Create folders per Telegram root label and move related media into them.")
    parser.add_argument(
        "--input",
        default=None,
        help="Path to one JSON file. If omitted, all messages*.json files in the base directory are processed.",
    )
    parser.add_argument("--base-dir", default=str(script_dir), help="Base directory containing exported media folders.")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()

    if args.input:
        json_paths = [Path(args.input).resolve()]
    else:
        json_paths = discover_json_files(base_dir)
        if not json_paths:
            raise SystemExit(f"No messages*.json files found in {base_dir}")

    organize_batch(json_paths, base_dir)


if __name__ == "__main__":
    main()
