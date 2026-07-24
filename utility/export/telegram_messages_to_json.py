#!/usr/bin/env python3
import argparse
import json
import re
import unicodedata
from collections import OrderedDict
from html.parser import HTMLParser
from pathlib import Path


HTML_EXPORT_RE = re.compile(r"^messages(?P<part>\d*)\.html$", re.IGNORECASE)
ROOT_LABEL_RE = re.compile(r"^(?P<sequence>\d{4})\.\s+.+$")
REPLY_TARGET_RE = re.compile(r"^(?:(?P<source>[^#]+))?#go_to_message(?P<message_id>\d+)$")
LABEL_HASHTAG_RE = re.compile(r"^#[\w]+$", re.UNICODE)


def normalize_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def ordered_dedupe(values):
    return list(OrderedDict.fromkeys(item for item in values if item))


def message_has_media(message) -> bool:
    return bool(message.get("photos") or message.get("videos"))


def is_comment_section_root(message) -> bool:
    text = normalize_line(message.get("text", "")).lower()
    return (
        "konten berada di dalam kolom komentar" in text
        or "media inside the comment section" in text
    )


def merge_media(entry, photos, videos):
    entry["photos"] = ordered_dedupe(entry.get("photos", []) + list(photos))
    entry["videos"] = ordered_dedupe(entry.get("videos", []) + list(videos))


def entry_sort_key(entry):
    return entry.pop("_sort_index", 0)


def url_friendly_name(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return cleaned or "untitled"


def text_lines(message):
    lines = [normalize_line(line) for line in message.get("text", "").splitlines() if normalize_line(line)]
    return lines


def label_from_lines(lines):
    if lines:
        label_parts = [lines[0]]
        for line in lines[1:]:
            if not LABEL_HASHTAG_RE.match(line):
                break
            label_parts.append(line)
        return url_friendly_name(" ".join(label_parts))
    return ""


def label_from_message(message, source_html: str):
    label = label_from_lines(text_lines(message))
    if label:
        return label
    return url_friendly_name(f"orphan {source_html} {message['id']}")


def first_text_line(message):
    lines = text_lines(message)
    if lines:
        return lines[0]
    return ""


def part_sort_key(path: Path):
    match = HTML_EXPORT_RE.match(path.name)
    if not match:
        return (1, path.name.lower())

    suffix = match.group("part")
    return (0 if suffix == "" else int(suffix), path.name.lower())


def discover_html_files(base_dir: Path):
    files = [path for path in base_dir.iterdir() if path.is_file() and HTML_EXPORT_RE.match(path.name)]
    return sorted(files, key=part_sort_key)


def html_to_json_path(html_path: Path) -> Path:
    match = HTML_EXPORT_RE.match(html_path.name)
    if not match:
        return html_path.with_suffix(".json")

    suffix = match.group("part")
    filename = "messages.json" if suffix == "" else f"messages{suffix}.json"
    return html_path.with_name(filename)


def parse_reply_target(href: str, current_source_html: str):
    match = REPLY_TARGET_RE.match(href.strip())
    if not match:
        return None

    source_html = (match.group("source") or current_source_html).strip()
    return {
        "source_html": source_html,
        "message_id": f"message{match.group('message_id')}",
    }


def parse_messages(html_text: str, source_html: str):
    parser = TelegramExportParser(source_html)
    parser.feed(html_text)
    return parser.messages


def build_root_entries(messages, source_html: str):
    entries = OrderedDict()
    root_order = []
    first_root_index = None
    numbered_roots = []
    fallback_roots = []

    for index, message in enumerate(messages):
        first_line = first_text_line(message)
        if not first_line or message.get("reply_to"):
            continue

        match = ROOT_LABEL_RE.match(first_line)
        if match:
            numbered_roots.append((index, message, first_line, match.group("sequence")))
            continue

        fallback_roots.append((index, message, first_line, None))

    # Some exports use plain titles like "Kolpri Rasya" instead of
    # "1472. Kolpri Rasya". When no numbered roots exist in a file, treat
    # non-reply text messages as roots so reply chains still resolve.
    selected_roots = numbered_roots if numbered_roots else fallback_roots

    for index, message, first_line, sequence in selected_roots:
        message_id = message["id"]
        if first_root_index is None:
            first_root_index = index

        root_order.append(message_id)
        entries[message_id] = {
            "entry_type": "root",
            "source_html": source_html,
            "message_id": message_id,
            "sequence": sequence,
            "label": label_from_lines(text_lines(message)) or first_line,
            "photos": ordered_dedupe(message["photos"]),
            "videos": ordered_dedupe(message["videos"]),
        }

    return entries, root_order, first_root_index


def build_reply_group_entry(target_source_html, target_message_id, group, root_catalog):
    target_info = root_catalog.get(target_source_html, {}).get(target_message_id)
    is_resolved = bool(target_info)
    return {
        "entry_type": "continuation" if is_resolved else "unresolved_reply",
        "source_html": target_source_html,
        "message_id": target_message_id,
        "sequence": target_info["sequence"] if target_info else None,
        "label": target_info["label"] if target_info else url_friendly_name(f"unresolved {target_source_html} {target_message_id}"),
        "label_resolved": is_resolved,
        "target_source_html": target_source_html,
        "target_message_id": target_message_id,
        "derived_from_source_html": group["derived_from_source_html"],
        "derived_from_message_ids": ordered_dedupe(group["derived_from_message_ids"]),
        "photos": ordered_dedupe(group["photos"]),
        "videos": ordered_dedupe(group["videos"]),
        "_sort_index": group["first_index"],
    }


def build_orphan_group_entry(source_html: str, group):
    first_message = group["messages"][0]
    entry = {
        "entry_type": "orphan_media",
        "source_html": source_html,
        "message_id": first_message["id"],
        "sequence": None,
        "label": label_from_message(first_message, source_html),
        "label_resolved": False,
        "derived_from_source_html": source_html,
        "derived_from_message_ids": [message["id"] for message in group["messages"]],
        "photos": [],
        "videos": [],
        "_sort_index": group["first_index"],
    }
    for message in group["messages"]:
        merge_media(entry, message["photos"], message["videos"])
    return entry


def build_root_catalog(html_files):
    catalog = {}

    for html_path in html_files:
        html_text = html_path.read_text(encoding="utf-8-sig")
        messages = parse_messages(html_text, html_path.name)
        root_entries, _, _ = build_root_entries(messages, html_path.name)
        catalog[html_path.name] = {
            message_id: {
                "label": entry["label"],
                "sequence": entry["sequence"],
            }
            for message_id, entry in root_entries.items()
        }

    return catalog


class TelegramExportParser(HTMLParser):
    def __init__(self, source_html: str):
        super().__init__(convert_charrefs=True)
        self.source_html = source_html
        self.messages = []
        self.current_message = None
        self.div_stack = []
        self.text_depth = None
        self.media_depth = None
        self.reply_depth = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "div":
            classes = set(attrs.get("class", "").split())
            self.div_stack.append(classes)
            depth = len(self.div_stack)

            if "message" in classes and attrs.get("id", "").startswith("message"):
                self.current_message = {
                    "id": attrs.get("id", ""),
                    "reply_to": None,
                    "reply_source_html": None,
                    "text_parts": [],
                    "photos": [],
                    "videos": [],
                    "message_depth": depth,
                }
                return

            if self.current_message and "text" in classes:
                self.text_depth = depth

            if self.current_message and "media_wrap" in classes:
                self.media_depth = depth

            if self.current_message and "reply_to" in classes:
                self.reply_depth = depth
            return

        if not self.current_message:
            return

        if tag == "br" and self.text_depth:
            self.current_message["text_parts"].append("\n")
            return

        if tag != "a":
            return

        classes = set(attrs.get("class", "").split())
        href = attrs.get("href", "").strip()
        if not href:
            return

        if self.media_depth:
            if href.startswith("photos/"):
                self.current_message["photos"].append(href)
            else:
                self.current_message["videos"].append(href)
            return

        if self.reply_depth:
            reply_target = parse_reply_target(href, self.source_html)
            if reply_target:
                self.current_message["reply_to"] = reply_target["message_id"]
                self.current_message["reply_source_html"] = reply_target["source_html"]

    def handle_endtag(self, tag):
        if tag != "div":
            return

        depth = len(self.div_stack)
        if self.text_depth and depth == self.text_depth:
            self.text_depth = None

        if self.media_depth and depth == self.media_depth:
            self.media_depth = None

        if self.reply_depth and depth == self.reply_depth:
            self.reply_depth = None

        if self.current_message and depth == self.current_message["message_depth"]:
            message = {
                "id": self.current_message["id"],
                "reply_to": self.current_message["reply_to"],
                "reply_source_html": self.current_message["reply_source_html"],
                "text": "".join(self.current_message["text_parts"]).strip(),
                "photos": ordered_dedupe(self.current_message["photos"]),
                "videos": ordered_dedupe(self.current_message["videos"]),
            }
            self.messages.append(message)
            self.current_message = None
            self.text_depth = None
            self.media_depth = None
            self.reply_depth = None

        if self.div_stack:
            self.div_stack.pop()

    def handle_data(self, data):
        if self.current_message and self.text_depth:
            self.current_message["text_parts"].append(data)


def parse_export(html_text: str, source_html: str, root_catalog):
    messages = parse_messages(html_text, source_html)
    entries, root_order, _ = build_root_entries(messages, source_html)
    message_index_by_id = {message["id"]: index for index, message in enumerate(messages)}
    message_by_id = {message["id"]: message for message in messages}
    consumed_message_ids = set(entries)

    for message in messages:
        reply_to = message["reply_to"]
        reply_source_html = message["reply_source_html"]
        if not reply_to or reply_source_html != source_html or reply_to not in entries:
            continue

        entry = entries[reply_to]
        merge_media(entry, message["photos"], message["videos"])
        consumed_message_ids.add(message["id"])

    # Telegram exports sometimes place the media block immediately before the
    # labeled root message instead of inside replies. Attach that contiguous
    # block to the next "comment section" root so the files are not lost.
    for root_id in root_order:
        root_message = message_by_id.get(root_id)
        if not root_message or not is_comment_section_root(root_message):
            continue

        root_index = message_index_by_id.get(root_id, -1)
        orphan_block = []
        cursor = root_index - 1
        while cursor >= 0:
            candidate = messages[cursor]
            if candidate["id"] in consumed_message_ids:
                break
            if candidate["reply_to"] or candidate["text"].strip() or not message_has_media(candidate):
                break
            orphan_block.append(candidate)
            cursor -= 1

        for candidate in reversed(orphan_block):
            merge_media(entries[root_id], candidate["photos"], candidate["videos"])
            consumed_message_ids.add(candidate["id"])

    reply_groups = OrderedDict()
    for index, message in enumerate(messages):
        if message["id"] in consumed_message_ids or not message_has_media(message):
            continue

        reply_to = message["reply_to"]
        reply_source_html = message["reply_source_html"]
        if not reply_to or not reply_source_html:
            continue

        key = (reply_source_html, reply_to)
        if key not in reply_groups:
            reply_groups[key] = {
                "derived_from_source_html": source_html,
                "derived_from_message_ids": [],
                "photos": [],
                "videos": [],
                "first_index": index,
            }

        reply_groups[key]["derived_from_message_ids"].append(message["id"])
        merge_media(reply_groups[key], message["photos"], message["videos"])
        consumed_message_ids.add(message["id"])

    orphan_groups = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message["id"] in consumed_message_ids or not message_has_media(message):
            index += 1
            continue

        if not message["reply_to"] and not message["text"].strip():
            group_messages = [message]
            consumed_message_ids.add(message["id"])
            cursor = index + 1
            while cursor < len(messages):
                candidate = messages[cursor]
                if candidate["id"] in consumed_message_ids:
                    break
                if candidate["reply_to"] or candidate["text"].strip() or not message_has_media(candidate):
                    break
                group_messages.append(candidate)
                consumed_message_ids.add(candidate["id"])
                cursor += 1

            orphan_groups.append({"first_index": index, "messages": group_messages})
            index = cursor
            continue

        orphan_groups.append({"first_index": index, "messages": [message]})
        consumed_message_ids.add(message["id"])
        index += 1

    payload = []
    for root_id in root_order:
        entry = dict(entries[root_id])
        entry["_sort_index"] = message_index_by_id.get(root_id, 0)
        payload.append(entry)

    for (target_source_html, target_message_id), group in reply_groups.items():
        payload.append(build_reply_group_entry(target_source_html, target_message_id, group, root_catalog))

    for group in orphan_groups:
        payload.append(build_orphan_group_entry(source_html, group))

    payload.sort(key=entry_sort_key)
    return payload


def write_payload(output_path: Path, payload):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_single_file(input_path: Path, output_path: Path, root_catalog):
    html_text = input_path.read_text(encoding="utf-8-sig")
    payload = parse_export(html_text, input_path.name, root_catalog)
    write_payload(output_path, payload)
    print(f"Parsed {len(payload)} entr{'y' if len(payload) == 1 else 'ies'} into {output_path}")


def parse_batch(base_dir: Path):
    html_files = discover_html_files(base_dir)
    if not html_files:
        raise SystemExit(f"No messages*.html files found in {base_dir}")

    root_catalog = build_root_catalog(html_files)
    for input_path in html_files:
        parse_single_file(input_path, html_to_json_path(input_path), root_catalog)


def main():
    script_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(description="Convert Telegram exported messages HTML into grouped media JSON.")
    parser.add_argument(
        "--input",
        default=None,
        help="Path to a Telegram export HTML file. If omitted, all messages*.html files in the script directory are parsed.",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Folder containing messages*.html files when using batch mode.",
    )
    parser.add_argument("--output", default=None, help="Path to output JSON file for single-file mode.")
    args = parser.parse_args()

    if args.output and not args.input:
        parser.error("--output requires --input.")

    if args.input:
        input_path = Path(args.input).resolve()
        root_catalog = build_root_catalog(discover_html_files(input_path.parent))
        output_path = Path(args.output).resolve() if args.output else html_to_json_path(input_path)
        parse_single_file(input_path, output_path, root_catalog)
        return

    parse_batch(Path(args.base_dir).resolve() if args.base_dir else Path.cwd())


if __name__ == "__main__":
    main()

