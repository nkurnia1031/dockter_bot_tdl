# 05 — Penerimaan cepat dan kontrak dispatch berversi

## Tujuan

Ubah jalur baru submit menjadi validasi lokal, penyimpanan atomik dan response; pindahkan pemilihan/dispatch worker ke advance command. Target worker job yang sudah ditempatkan tetap terikat ke worker awal.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 03, 04 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

ControlPlane.submit_job melakukan dispatch sebelum response. build_execution_plan menyimpan resource lane. WorkerHttpDispatcher dan domain/worker_contract.py adalah batas integrasi yang sudah tersedia.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/application/control_plane.py` |
| Diubah | `tme3bot/domain/worker_contract.py` |
| Diubah | `tme3bot/infrastructure/http_client.py` |
| Diubah | `tme3bot/infrastructure/job_store.py` |
| Diubah | `tme3bot/application/operations.py` |
| Diubah | `tme3bot/api/backend.py` |
| Diubah | `tme3bot/api/routes/jobs.py` |
| Diubah | `tme3bot/api/schemas.py` |
| Diubah | `tests/test_control_plane.py` |
| Diubah | `tests/test_worker_contract.py` |
| Diubah | `tests/test_backend_api.py` |
| Baru | `tests/test_durable_dispatch.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

Worker command v2 dikirim melalui POST /internal/v1/commands, status GET /internal/v1/commands/{id}. API job legacy tetap tersedia; operations_v1 menjadi jalur accepted baru. Kesuksesan HTTP/RQ tidak berarti job succeeded.

## Spesifikasi implementasi

1. Ubah jalur baru submit menjadi validasi lokal, penyimpanan atomik dan response; pindahkan pemilihan/dispatch worker ke advance command. Target worker job yang sudah ditempatkan tetap terikat ke worker awal.
2. Envelope command v2 memuat command_id, operation_id, job_id opsional, attempt, dispatch_token, profile_revision, settings_version dan execution plan. Backend menyimpan attempt sebelum pengiriman dan menerima ACK secara idempotent.
3. Tambahkan capability durable_commands_v1 pada kontrak. Jalur baru menunggu worker kompatibel; jangan mengirim envelope baru ke worker lama. Gate per worker durable_dispatch default off.
4. Pertahankan shape API submit job lama dan Job DTO selama transisi; request dengan mode async memakai operation DTO. Semua jalur memakai penyimpanan job yang sama, sehingga tidak ada dua scheduler yang mengklaim job yang sama.
5. Deadline dispatch HTTP singkat; timeout berarti hasil penerimaan belum diketahui. Retry memakai command_id/token sama dan query ACK, bukan membuat job baru. Heartbeat hilang menandai waiting_worker atau needs_reconciliation, tidak langsung memberi worker lain side effect yang sama.
6. Pastikan resume/cancel/prioritas/limit lane lama tetap berlaku. Counter antrean dihitung dari catatan persisten, bukan panjang antrean RQ.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 05: Penerimaan cepat dan kontrak dispatch berversi.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 03, 04.
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
   Perbarui HANYA baris 05 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Worker mock lambat tidak menahan response submit operasi.
- Duplicate ACK/event dan timeout penerimaan tidak membuat job baru.
- Worker tanpa capability tidak menerima kontrak baru.
- Job existing, QuickMode per profile, TTS satu job per worker dan route origin tetap benar.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_durable_dispatch tests.test_control_plane tests.test_worker_contract tests.test_backend_api -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Matikan gate hanya untuk job baru setelah menandai pemilik scheduler untuk setiap job lama. Jangan memindahkan accepted command ke scheduler legacy tanpa dedupe/reconciliation.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
