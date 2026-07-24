"""Text helpers owned by the Telegram presentation adapter."""

from __future__ import annotations

import hashlib


def source_digest(chat_ref: str) -> str:
    return hashlib.sha1(chat_ref.encode("utf-8")).hexdigest()[:12]


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
        "- /storage untuk upload folder workspace ke channel storage, mencari file, rename metadata, edit folder/keyword, dan download.\n"
        "- Storage memakai satu katalog SQLite global di gateway; rename nama tampilan terbuka untuk user terotorisasi, sedangkan folder/keyword/delete tetap milik uploader.\n"
        "- /backup untuk menjalankan atau melihat backup runtime 7z terenkripsi per-node.\n"
        "Catatan: bot memakai satu panel yang diedit realtime, dan input user akan dicoba dihapus setelah diproses. Log tdl tetap masuk Docker logs."
    )
