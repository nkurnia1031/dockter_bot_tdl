from __future__ import annotations

import hashlib
import time
from urllib.parse import quote

from tme3bot.profiles import ProfileManager, describe_download_mode
from tme3bot.progress import DownloadProgressSnapshot
from tme3bot.service import BatchDownloadResult, ExportJobResult
from tme3bot.state import SourceState
from tme3bot.tdl import TDLCommandError, TDLDataError
from tme3bot.url_parser import URLParseError


def profile_status_text(active_profile: str, profiles: list[str]) -> str:
    profile_list = ", ".join(profiles) if profiles else "belum ada"
    return (
        f"Profile aktif: {active_profile}\n"
        f"Daftar profile: {profile_list}\n\n"
        "Pakai /profile <nama> untuk memilih atau membuat profile. "
        "Profile tambahan disimpan di /data/profiles/<nama>."
    )


def download_settings_text(profile_name: str, profile_manager: ProfileManager) -> str:
    mode = profile_manager.download_mode(profile_name)
    runtime = profile_manager.runtime(profile_name)
    base_download_root = profile_manager.base_config.download_root
    active_root = runtime.config.download_root
    return (
        f"[{profile_name}] Pengaturan download\n"
        f"Mode: {describe_download_mode(mode)}\n"
        f"Root aktif: {active_root}\n"
        f"Root default: {base_download_root}\n\n"
        "Hasil download selalu dipisah menjadi:\n"
        f"- Berlabel: {active_root}/berlabel/<nama-json>/\n"
        f"- Biasa: {active_root}/biasa/<nama-json>/\n\n"
        "Default semua profile memakai root download utama. Pilih mode terpisah jika profile ini perlu folder download sendiri."
    )


def format_source_button(chat_ref: str, source: SourceState) -> str:
    label = f" | {source.label}" if source.label else ""
    return f"{chat_ref}{label} | last {source.last_id}"[:60]


def source_digest(chat_ref: str) -> str:
    return hashlib.sha1(chat_ref.encode("utf-8")).hexdigest()[:12]


def build_tme3_url(
    host: str, chat_ref: str, message_id: int, label: str | None = None
) -> str:
    safe_chat = quote(chat_ref, safe="@")
    base = f"https://{host}/c/{safe_chat}/{message_id}"
    return f"{base}/{quote(label, safe='')}" if label else base


def parse_callback_int(data: str, default: int = 0) -> int:
    parts = data.split(":", 1)
    return parse_int(parts[1], default) if len(parts) == 2 else default


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def help_text(host: str) -> str:
    return (
        "Perintah bot:\n"
        "- /menu untuk membuka tombol dinamis dari bot.\n"
        "- /check_profil untuk memuat ulang akses dari identity sesi TDL. Profile ditentukan otomatis dan tidak dapat diganti dari bot.\n"
        f"- Kirim URL https://{host}/c/<chat_ref>/<message_id>/<label> untuk membuat export JSON berlabel.\n"
        "- Link Telegram normal seperti https://t.me/c/4429689667/12 juga diterima.\n"
        "- ID pada URL yang dikirim langsung selalu dipakai sebagai Mulai ID, termasuk untuk mengulang atau mengambil ulang ID lama.\n"
        f"- Kirim URL tanpa label seperti https://{host}/c/@KFCMNB_bot/3 untuk export tanpa prefix label.\n"
        "- Menu source tersimpan selalu melanjutkan dari Last ID + 1. Source bisa dipilih satu, beberapa, atau semua lalu dihapus secara batch.\n"
        "- Menu source bisa export tanpa copy-paste URL, dengan label terakhir, label global tersimpan, label custom, atau tanpa label.\n"
        "- Tombol Pengaturan download mengatur apakah profile aktif memakai download utama atau folder profile sendiri.\n"
        "- Output download dipisah ke download/berlabel/<nama-json>/ dan download/biasa/<nama-json>/.\n"
        "- /download untuk membuka panel download realtime dan memproses JSON pending.\n"
        "- Download profile berbeda berjalan paralel; job dalam profile yang sama tetap antre serial agar database tdl aman.\n"
        "- /download_status untuk membuka snapshot status download.\n"
        "- /retry_failed untuk mencoba ulang semua JSON di folder failed.\n"
        "- /clear_fail untuk menghapus JSON failed setelah kamu yakin tidak perlu dicoba lagi.\n"
        "- /cancel_download untuk menghentikan proses tdl download aktif.\n"
        "- /utility untuk menjalankan extract, compress, export, atau pindah pada folder workspace.\n"
        "Catatan: bot memakai satu panel yang diedit realtime, dan input user akan dicoba dihapus setelah diproses. Log tdl tetap masuk Docker logs."
    )


def format_export_result(
    result: ExportJobResult, profile_name: str | None = None
) -> str:
    status = (
        "Export JSON selesai."
        if result.status == "exported"
        else "Export JSON dibuat, tapi tidak ada pesan baru."
    )
    label = result.requested_label if result.requested_label else "tanpa label"
    lines = [status]
    if profile_name:
        lines.append(f"Profile: {profile_name}")
    lines.extend(
        [
            f"Chat: {result.chat_ref}",
            f"Label: {label}",
            f"Mulai ID: {result.start_id}",
            f"Pesan diekspor: {result.exported_count}",
            f"Ada media: {'ya' if result.has_media else 'tidak'}",
            f"Warmup diperlukan: {'ya' if result.warmup_required else 'tidak'}",
            f"JSON: {result.export_path}",
        ]
    )
    if result.latest_id is not None:
        lines.append(f"Last ID: {result.latest_id}")
    if result.warning:
        lines.append(f"Catatan: {result.warning}")
    return "\n".join(lines)


def format_batch_download_result(result: BatchDownloadResult) -> str:
    if result.moved_count == 0:
        return "Tidak ada JSON untuk diproses."
    lines = [
        "Batch download selesai.",
        f"JSON dipindahkan: {result.moved_count}",
        f"Berhasil: {result.success_count}",
        f"Gagal: {result.failed_count}",
    ]
    for item in result.results[:5]:
        if item.status in {"success", "success_deleted"}:
            lines.append(
                f"OK: {item.json_path.name} -> {item.download_dir} (JSON dihapus)"
            )
        else:
            lines.append(f"Gagal: {item.json_path.name} ({(item.error or '')[:160]})")
    if len(result.results) > 5:
        lines.append(f"...dan {len(result.results) - 5} file lain.")
    return "\n".join(lines)


def format_download_progress(
    snapshot: DownloadProgressSnapshot,
    queue_size: int,
    result: BatchDownloadResult | None = None,
    error: str | None = None,
    profile_name: str | None = None,
) -> str:
    if result is not None:
        return f"{format_download_progress(snapshot, queue_size, profile_name=profile_name)}\n\n{format_batch_download_result(result)}"
    if error is not None:
        return f"{format_download_progress(snapshot, queue_size, profile_name=profile_name)}\n\nError:\n{error[:900]}"

    header = (
        "Download idle"
        if not snapshot.active and snapshot.phase in {"idle", "done"}
        else "Download realtime"
    )
    lines = [header]
    if profile_name:
        lines.append(f"Profile: {profile_name}")
    lines.extend(
        [
            f"Phase: {snapshot.phase}",
            f"Queue: {queue_size}",
            f"Durasi: {format_elapsed(snapshot.started_at)}",
            f"Batch JSON: {snapshot.current_json_index if snapshot.total_json else 0}/{snapshot.total_json} | OK {snapshot.success_count} | Fail {snapshot.failed_count}",
        ]
    )
    if snapshot.current_json_name:
        lines.append(f"JSON: {compact_text(snapshot.current_json_name, 58)}")
    if snapshot.current_media_total:
        current_media = snapshot.tdl_fraction_current
        media_text = (
            f"{current_media}/{snapshot.current_media_total}"
            if current_media is not None
            else f"?/{snapshot.current_media_total}"
        )
        lines.append(f"Media JSON: {media_text}")

    progress_bits = []
    if snapshot.tdl_percent is not None:
        progress_bits.append(
            f"{snapshot.tdl_percent:.1f}% {progress_bar(snapshot.tdl_percent)}"
        )
    if snapshot.tdl_speed:
        progress_bits.append(snapshot.tdl_speed)
    if progress_bits:
        lines.append("File: " + " | ".join(progress_bits))
    if snapshot.tdl_file_name:
        lines.append(f"Nama: {compact_text(snapshot.tdl_file_name, 58)}")
    if snapshot.tdl_line:
        lines.append(f"tdl: {compact_text(snapshot.tdl_line, 90)}")
    if snapshot.last_error:
        lines.append(f"Last error: {compact_text(snapshot.last_error, 90)}")
    return "\n".join(lines)


def format_elapsed(started_at: float | None) -> str:
    if started_at is None:
        return "0s"
    seconds = max(int(time.time() - started_at), 0)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{sec:02d}s"
    if minutes:
        return f"{minutes}m{sec:02d}s"
    return f"{sec}s"


def progress_bar(percent: float) -> str:
    clamped = max(0.0, min(percent, 100.0))
    filled = int(round(clamped / 10))
    return "[" + "#" * filled + "-" * (10 - filled) + "]"


def compact_text(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: max(limit - 3, 0)] + "..."


def format_exception(exc: Exception) -> str:
    if isinstance(exc, URLParseError):
        return str(exc)
    if isinstance(exc, TDLCommandError):
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        return f"TDL gagal: {detail[:1200]}"
    if isinstance(exc, TDLDataError):
        return f"Data export tidak valid: {exc}"
    return f"Terjadi error: {str(exc)[:1200]}"
