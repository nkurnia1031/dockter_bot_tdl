# 16 — Aksi Quick Mode sebagai operation background

## Tujuan

Daftarkan quickmode.scan, quickmode.crosscheck dan quickmode.cleanup sebagai command operation. Simpan target worker/stage stabil; jangan menerima arbitrary filesystem path.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 05, 09 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

QuickMode mempunyai staging/recovery, manifest quickmode.json dan worker.log. Endpoint scan/crosscheck/cleanup masih berada di api/backend.py dan executor_quickmode.py. Job terminal tidak cukup menjadi alasan menghapus staging; verifikasi Telegram dan rclone tetap diperlukan.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/api/backend.py` |
| Diubah | `tme3bot/worker/executor_quickmode.py` |
| Diubah | `tme3bot/worker/quick_export.py` |
| Diubah | `tme3bot/application/operations.py` |
| Diubah | `tme3bot/infrastructure/http_client.py` |
| Diubah | `tests/test_backend_api.py` |
| Diubah | `tests/test_quick_export.py` |
| Baru | `tme3bot/application/quickmode_operations.py` |
| Baru | `tme3bot/api/routes/quickmode_operations.py` |
| Baru | `tests/test_quickmode_operations.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

POST /api/v1/operations kinds quickmode.scan/crosscheck/cleanup dengan target worker dan input stage_id bila relevan. Hasil inventory publik tidak mengekspos credential, path di luar representasi UI yang diizinkan, atau sesi.

## Spesifikasi implementasi

1. Daftarkan quickmode.scan, quickmode.crosscheck dan quickmode.cleanup sebagai command operation. Simpan target worker/stage stabil; jangan menerima arbitrary filesystem path.
2. GET staging manager membaca snapshot inventory backend dengan observed_at/stale/error. POST refresh menghasilkan 202 dan snapshot diperbarui oleh completion worker, bukan pada load halaman.
3. Worker menjalankan scan/crosscheck via command journal, mengirim fase/progress terukur dan result tersanitasi. Gunakan lock stage agar tidak bersaing dengan retry/upload job yang sama.
4. Cleanup otomatis hanya setelah seluruh target upload terverifikasi. Aksi hapus manual tetap mempertahankan konfirmasi eksplisit dan kebijakan yang ada; idempotent bila file sudah tidak ada, jangan memperluas menjadi force delete tersembunyi.
5. Pertahankan verifikasi channel_message_id, rclone check/fallback inventory dan artifact thumbnail. Metadata quickmode.json/worker.log yang tersisa ditangani sesuai cleanup manifest; gagal verifikasi mempertahankan staging.
6. Retain endpoint legacy melalui adapter di belakang gate sampai Web task 19 tersedia. Pindahkan logic baru ke modul terpisah, backend.py hanya wiring.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 16: Aksi Quick Mode sebagai operation background.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 05, 09.
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
   Perbarui HANYA baris 16 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Refresh scan selesai walau tab ditutup; membuka halaman tidak memulai scan.
- Cleanup gagal verifikasi mempertahankan file.
- Duplicate command dan stage aktif tidak membuat deletion race.
- Job ID/stage ID stabil serta concurrency profile lama tetap benar.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_quickmode_operations tests.test_quick_export tests.test_backend_api -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Matikan admission aksi async baru dan tunggu stage locks selesai. Jangan mengembalikan staging yang telah terverifikasi dihapus; simpan audit/result untuk status UI.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
