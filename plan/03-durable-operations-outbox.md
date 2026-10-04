# 03 — Operation persisten dan transactional outbox

## Tujuan

Tambahkan operation, command attempt, outbox dan idempotency record pada SQLite backend dengan migration additive. Operation memuat actor, profile/worker target, kind, status, phase, revision, progress, job_id opsional, timestamp dan error tersanitasi.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 01 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

SqliteJobRepository sudah menyimpan job dan event; ControlPlane masih membuat job dan execution plan dalam langkah terpisah. Profile provisioning memiliki tabel sendiri. Kontrak operation harus dapat menghubungkan workflow ke job yang ada tanpa dua status yang saling bertentangan.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/infrastructure/job_store.py` |
| Diubah | `tme3bot/domain/models.py` |
| Diubah | `tme3bot/application/ports.py` |
| Diubah | `tme3bot/api/backend.py` |
| Diubah | `tme3bot/api/schemas.py` |
| Diubah | `tme3bot/composition.py` |
| Diubah | `tests/test_job_store.py` |
| Diubah | `tests/test_backend_api.py` |
| Baru | `tme3bot/domain/operations.py` |
| Baru | `tme3bot/infrastructure/operation_store.py` |
| Baru | `tme3bot/application/operations.py` |
| Baru | `tme3bot/api/routes/operations.py` |
| Baru | `tests/test_operations.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

POST /api/v1/operations menerima {kind,target,input} dan Idempotency-Key; 202 {operation_id,status,status_url}, Location ke status. GET /api/v1/operations?status=&cursor= dan /{id}; POST /{id}/cancel, /{id}/retry; PUT /{id}/visibility {dismissed}. Daftar/status hanya metadata; input rahasia tidak pernah tercermin.

## Spesifikasi implementasi

1. Tambahkan operation, command attempt, outbox dan idempotency record pada SQLite backend dengan migration additive. Operation memuat actor, profile/worker target, kind, status, phase, revision, progress, job_id opsional, timestamp dan error tersanitasi.
2. Gunakan status queued, running, waiting_user, waiting_worker, paused, needs_reconciliation, cancelling, succeeded, failed, cancelled. Tahap rinci seperti distributing menjadi phase. Dismissed adalah preferensi tampilan per actor, bukan status pembatalan.
3. Bangun Unit of Work yang menyimpan job + execution plan + operation + outbox memakai koneksi/transaksi yang sama. Payload privat disimpan terpisah dari DTO publik. Duplicate idempotency key actor+aksi+payload menghasilkan operation sama; payload berbeda dengan key sama 409.
4. Tambahkan GET daftar/status dengan pagination dan otorisasi actor yang ada. GET hanya membaca backend, tidak mendispatch atau menghubungi worker. Transisi memakai expected revision dan terminal tidak dapat kembali running.
5. Tambahkan POST cancel/retry dan PUT visibility dengan idempotency. Retry menambah attempt pada operation yang sama; side effect tidak pasti memerlukan rekonsiliasi. Hubungan job existing tetap mengikuti state machine lama melalui adapter.
6. Publikasikan metadata capability API operations_v1. Implementasikan endpoint submit action generik dengan allowlist kind; kind belum terpasang handler ditolak terstruktur. Jangan buka arbitrary command atau arbitrary URL.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 03: Operation persisten dan transactional outbox.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 01.
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
   Perbarui HANYA baris 03 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Crash di tengah transaksi tidak meninggalkan job tanpa plan/outbox.
- GET actor lain tidak mengungkap operasi; rahasia tidak ada di DTO.
- Retry submit sesudah response hilang memperoleh ID sama.
- Transisi stale/duplikat tidak memundurkan status.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_operations tests.test_job_store tests.test_backend_api -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Nonaktifkan operations_v1, biarkan schema additive dan record tetap ada. Drain/outbox dicatat sebelum rollback kode; jangan menghapus accepted operations.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
