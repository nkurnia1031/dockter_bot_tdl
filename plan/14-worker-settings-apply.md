# 14 — Penerapan konfigurasi worker saat aman

## Tujuan

Tambahkan settings sync pada startup, command runtime.apply dan pemberitahuan version melalui heartbeat. Fetch hanya scope worker tersebut; persist desired/applied version lokal dengan izin privat.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task P1, 08, 09 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

worker/runtime_settings.py menolak beberapa perubahan ketika job aktif. Executor membaca settings lokal, sedangkan tdl.py masih membaca langsung TDL_UPLOAD_RESOLVE_* dari ENV. Desired settings task 08 memungkinkan perubahan disimpan meski worker offline.

Pertahankan kontrak P1 saat settings TTS berubah: diagnosis dan recovery memakai URL helper yang sudah diterapkan pada worker, bukan URL dari request Web. Apply settings tidak boleh me-restart Tor/helper secara tersembunyi atau memutus sintesis aktif.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/worker/runtime_settings.py` |
| Diubah | `tme3bot/worker/executor.py` |
| Diubah | `tme3bot/worker/executor_tts.py` |
| Diubah | `tme3bot/worker/tts_pipeline.py` |
| Diubah | `tme3bot/tdl.py` |
| Diubah | `tme3bot/config.py` |
| Diubah | `tests/test_worker_runtime_settings.py` |
| Diubah | `tests/test_tdl.py` |
| Diubah | `tests/test_tts_executor.py` |
| Baru | `tme3bot/worker/settings_sync.py` |
| Baru | `tests/test_worker_settings_sync.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

Command runtime.apply hanya menunjuk desired_version. GET internal settings memakai worker auth; POST ACK memuat applied_version/status/error tanpa values. Public status berasal dari backend task 08.

## Spesifikasi implementasi

1. Tambahkan settings sync pada startup, command runtime.apply dan pemberitahuan version melalui heartbeat. Fetch hanya scope worker tersebut; persist desired/applied version lokal dengan izin privat.
2. Validasi seluruh desired snapshot sebelum apply; jika resource sibuk, catat pending_reason dan tunggu batas aman. Jangan menolak penyimpanan backend hanya karena worker busy.
3. Salin effective settings immutable ke context job pada admission. Helper Tor, namespace sesi dan storage profile yang sedang dipakai tidak berubah di tengah subprocess.
4. Injeksi timeout/retry/resolve options ke TdlClient; hilangkan pembacaan ENV langsung pada jalur runtime terkelola. Nilai image/path/user yang deploy-only tetap fixed dan tervalidasi.
5. Terapkan perubahan secara atomik, kirim ACK version atau error tersanitasi. Versi lama tidak menggantikan desired baru; boot memakai applied cache yang sah sampai backend terhubung, sesuai admission/profile revision.
6. Rotasi token worker memakai overlap dan ACK; cache worker tidak berisi bot token. Uji offline update, busy apply dan crash antara apply/ACK.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 14: Penerapan konfigurasi worker saat aman.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: P1, 08, 09.
2. Periksa fungsi dan kontrak pada bagian Konteks. Gunakan graphify query terlebih
   dahulu untuk relasi kode, lalu source aktual. Jangan membuka nilai secret.
3. Ikuti seluruh langkah bernomor pada Spesifikasi implementasi dalam file ini.
   Gunakan apply_patch, Python 3.10 dan batas domain/application/infrastructure.
   Daftar File yang disentuh adalah allowlist lengkap. Jangan mengubah file lain;
   jika benar-benar diperlukan, catat alasan dan status terblokir, jangan memperluas
   cakupan atau mengerjakan task berikutnya.
4. Pertahankan API legacy/gate sesuai kontrak. Jangan deploy, publish, commit,
   mengakses production, mengirim Telegram nyata, atau menjalankan migrasi data nyata.
5. Tambahkan/uji skenario Kriteria selesai dengan mock/fixture lokal. Jalankan
   seluruh Cara verifikasi. Catat kegagalan atau tool tidak tersedia secara jujur.
6. Periksa diff agar hanya perubahan task ini dan output tool yang diizinkan.
   Perbarui HANYA baris 14 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Job berjalan tetap memakai versi awal; job berikutnya memakai versi baru.
- Update offline akhirnya diterapkan dan terlihat applied.
- ACK hilang/restart tidak menerapkan ulang side effect yang tidak idempotent.
- Timeout TDL tidak dibaca ulang dari ENV setelah import.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_worker_settings_sync tests.test_worker_runtime_settings tests.test_tdl tests.test_tts_executor -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Pause apply baru dan pin versi efektif terakhir yang valid melalui backend. Jangan menghapus tombstone/migration marker atau menyalin secret backend ke worker.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
