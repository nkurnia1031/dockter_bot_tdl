# 11 — Executor export memakai cursor bersama dan mengarsip state lokal

## Tujuan

Pasang handler resolve peer sebelum export dari kontrak task 06, memakai TDL terkontrol pada profile/worker yang sudah sinkron. Hasil resolve dilaporkan tanpa mencatat isi pesan.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 02, 06, 09, 10 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

service.py membaca last_id dari state_store sebelum export; QuickMode memiliki export.json_ready dan resource release terpisah. Worker runtime sudah memakai HttpStateStore, tetapi jalur fallback/backup masih perlu dipastikan tidak menghidupkan state lama.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/service.py` |
| Diubah | `tme3bot/state.py` |
| Diubah | `tme3bot/tdl.py` |
| Diubah | `tme3bot/worker/executor.py` |
| Diubah | `tme3bot/worker/executor_quickmode.py` |
| Diubah | `tme3bot/worker/quick_export.py` |
| Diubah | `tme3bot/backup_service.py` |
| Diubah | `tme3bot/worker/executor_backup.py` |
| Diubah | `tests/test_service.py` |
| Diubah | `tests/test_quick_export.py` |
| Diubah | `tests/test_backup_service.py` |
| Baru | `tests/test_worker_shared_cursor.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

Advertise shared_export_cursor_v1 setelah resolver/commit terpasang. HTTP backend tidak tersedia menahan commit dan lane; tidak ada sukses lokal palsu. File source lama hanya read-only untuk alat migrasi.

## Spesifikasi implementasi

1. Pasang handler resolve peer sebelum export dari kontrak task 06, memakai TDL terkontrol pada profile/worker yang sudah sinkron. Hasil resolve dilaporkan tanpa mencatat isi pesan.
2. Jalankan export hanya sesudah lease backend diberikan; gunakan cursor/start_id yang dikonfirmasi saat claim. Jangan mempercayai last_id kiriman browser atau file state worker.
3. Setelah JSON export aman, kirim artifact+cursor commit dengan attempt/revision/fencing. Event json_ready yang melepas lane menunggu ACK commit. Simpan checkpoint commit pending untuk replay jika koneksi hilang.
4. Pastikan explicit start/overwrite, warmup, source sementara, retry failed export dan QuickMode retry fase setelah exporting tidak mengalami perubahan yang tidak diminta.
5. Pada gerbang shared_export_cursor aktif, semua fallback source lokal ditolak dengan error recoverable. Backup worker menyimpan operational checkpoints/sesi/artifact yang relevan; state bisnis hanya ikut backup backend.
6. Arsipkan state.json/max.json worker hanya melalui migrasi yang memiliki migration receipt backend dan checksum cocok. Jangan menghapus otomatis saat startup atau mengarsipkan TTS/QuickMode manifests.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 11: Executor export memakai cursor bersama dan mengarsip state lokal.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 02, 06, 09, 10.
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
   Perbarui HANYA baris 11 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Dua worker profile-channel sama melanjutkan last_id secara benar.
- Koneksi putus setelah artifact dibuat tidak menduplikasi catalog/cursor commit.
- QuickMode melepas export lane setelah ACK, fase lanjut tetap berjalan.
- Tidak ada file channel/last_id baru di worker setelah cutover.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_worker_shared_cursor tests.test_service tests.test_quick_export tests.test_backup_service -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Drain lane dan commit pending, ekspor state backend terbaru ke format legacy bila rollback reader diperlukan. Pertahankan source archive/journal serta fencing; jangan memakai state worker yang lebih tua.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
