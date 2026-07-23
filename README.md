# t.me3 Telegram Bot

Untuk konteks teknis lengkap bagi agent/developer baru, baca [AGENTS.md](AGENTS.md).

Service Python dan Docker untuk membuat export JSON melalui `tdl`, lalu mengunduh semua media dari JSON tersebut. Satu bot dapat mengelola beberapa profile Telegram dengan storage dan state terpisah.

Image tetap menggunakan `ubuntu:22.04`. Saat build melalui `run.py`, binary `tdl` dari host Linux akan disalin ke image; bila tidak tersedia atau tidak kompatibel, Docker mengunduh fallback tetap sesuai arsitektur host.

## Alur

1. URL `t.me3` atau `t.me/c/...` dikirim ke bot.
2. Worker export menjalankan `tdl` sebagai `user1` dan menyimpan JSON ke folder `exports/pending` profile aktif.
3. Perintah `/download` memindahkan JSON ke `processing` lalu menjalankan `tdl` sebagai `root`.
4. JSON berhasil dihapus. JSON gagal dipindahkan ke `exports/failed` agar dapat dicoba ulang.

URL yang dikirim langsung memakai message ID dari URL sebagai override. Export dari menu source tersimpan selalu melanjutkan dari `last_id + 1`.

Download memakai queue terpisah per profile. Profile berbeda dapat berjalan paralel dan memperbarui panel status masing-masing, sedangkan beberapa job pada profile yang sama tetap diproses serial untuk mencegah konflik database `tdl`.

## Struktur Kode

```text
tme3bot/
  app.py               Bootstrap dan router utama Telegram
  profile_handler.py   Command dan callback profile
  source_handler.py    Source, label, export, dan batch selection
  download_handler.py  Download, retry, cancel, dan status realtime
  bot_workers.py       Worker queue export dan download
  bot_panel.py         Lifecycle satu panel message Telegram
  bot_keyboards.py     Inline keyboard
  bot_text.py          Formatter pesan
  profiles.py          Runtime dan konfigurasi per profile
  service.py           Orchestration export dan batch download
  progress.py          State progress download thread-safe
  profile_queue.py     Scheduler paralel antarprofile, serial per profile
  tdl.py               Eksekusi proses dan command tdl
  tdl_output.py        Parser output terminal tdl
  state.py             Persistensi source dan last ID
```

## Menjalankan

Siapkan `.env` berdasarkan `.env.example`, kemudian:

```bash
python3 run.py up
python3 run.py logs
```

Untuk memperbarui kode dan recreate container tanpa menghapus data mount:

```bash
python3 run.py update
```

Untuk membuat paket deployment bersih:

```bash
python3 build.py
```

Perintah tersebut menghasilkan `output.zip` dan tidak menyertakan `.env`, sesi `.tdl`, state, download, export, test, atau cache Graphify.

Perintah `update` tidak memakai `--pull`, `--no-cache`, atau cache-buster. Dengan demikian layer Ubuntu, `apt`, Python, dan `tdl` digunakan kembali selama inputnya tidak berubah. Binary `tdl` host dicari dari `PATH`; lokasi khusus dapat diatur dengan `TDL_HOST_BINARY=/path/ke/tdl`.

Instalasi paket Ubuntu host tidak dapat diwariskan langsung ke container karena filesystem dan library keduanya terpisah. Paket dasar tetap dipasang pada build pertama, tetapi tidak dipasang ulang pada update normal.

Untuk membersihkan image lama berstatus dangling (`<none>`) setelah beberapa kali rebuild:

```bash
python3 run.py cleanup
```

Pembersihan ini mempertahankan image bertag dan semua image yang masih dipakai container.

Profile tambahan dibuat dengan:

```bash
python3 run.py add-profile nama-profile
```

Salin sesi download ke `profiles/<nama>/root/.tdl` dan sesi export ke `profiles/<nama>/user1/.tdl`.

## Verifikasi Lokal

```bash
python -m unittest discover -s tests
python -m compileall -q tme3bot bot.py run.py
```
