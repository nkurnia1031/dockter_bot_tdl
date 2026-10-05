# 17 — Pemeriksaan Storage, Utility, dan target melalui antrean

## Tujuan

Daftarkan context.verify, storage.refresh, workspace.list dan downloads.reconcile sebagai operation kind allowlist. Operasi file mutating yang ada tetap memakai job/lock lama melalui adapter durable command.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 05, 09 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

Task ini mengubah route worker dan dispatcher yang juga melayani diagnosis/recovery TTS P1. Pertahankan endpoint tersebut terpisah dari operasi Storage/Utility, dengan worker auth, slot helper terkonfigurasi, dan refresh manual.

Storage/Utility route meneruskan filesystem/TDL request ke worker; storage settings GET juga dapat resolve chat. context/verify memeriksa target aktual. Download Manager sengaja tidak reconcile saat dibuka; artifact missing dicatat deleted/available=false saat preflight.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/api/backend.py` |
| Diubah | `tme3bot/api/routes/storage.py` |
| Diubah | `tme3bot/api/routes/utility.py` |
| Diubah | `tme3bot/api/routes/downloads.py` |
| Diubah | `tme3bot/api/routes/workers.py` |
| Diubah | `tme3bot/worker/executor_storage.py` |
| Diubah | `tme3bot/worker/executor_workspace.py` |
| Diubah | `tme3bot/application/operations.py` |
| Diubah | `tme3bot/infrastructure/http_client.py` |
| Diubah | `tests/test_backend_api.py` |
| Diubah | `tests/test_storage_worker_paths.py` |
| Baru | `tme3bot/application/workspace_operations.py` |
| Baru | `tests/test_workspace_operations.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

POST operations kinds context.verify/storage.refresh/workspace.list/downloads.reconcile. Snapshot GET existing memperoleh observed_at/stale dan operation_id opsional. Verification result memuat target revision; tidak menjadi bypass admission saat submit.

## Spesifikasi implementasi

1. Daftarkan context.verify, storage.refresh, workspace.list dan downloads.reconcile sebagai operation kind allowlist. Operasi file mutating yang ada tetap memakai job/lock lama melalui adapter durable command.
2. Snapshot cache backend diberi target worker/profile, observed_at, revision dan stale/error. GET tidak memanggil worker/Telegram. Request verifikasi target explicit action menghasilkan operation; submit job tetap melakukan admission aktual.
3. Pertahankan path confinement resolve/relative_to /workspace. Input path hanya workspace-relative pada kontrak baru, dikonversi aman worker; worker switch tidak boleh memakai cache/filesystem worker sebelumnya.
4. Jangan otomatis reconcile saat buka Downloads. Preflight submit tetap menandai artifact missing deleted/available=false dengan audit dan tanpa job delete tambahan.
5. Storage settings menjadi config snapshot; resolusi chat/network verification adalah operation tersendiri. Offline worker menampilkan cached/stale dan status operasi, tidak menahan public request sampai reverse proxy timeout.
6. Isolasi cache menurut actor/target yang diizinkan dan urutkan generation agar hasil request lama tidak menimpa target baru. API legacy dipertahankan sampai Web baru tersedia.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 17: Pemeriksaan Storage, Utility, dan target melalui antrean.
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
   Perbarui HANYA baris 17 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- GET snapshot cepat ketika worker tidak dapat dijangkau.
- Hasil worker lama tidak muncul setelah target berubah.
- Path traversal ditolak; reconcile hanya manual.
- Missing artifact tetap ada di history dengan available=false.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_workspace_operations tests.test_backend_api tests.test_storage_worker_paths -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Hentikan operasi baru dan gunakan adapter lama hanya sesudah pending command direkonsiliasi. Pertahankan cache sebagai metadata dan jangan membalik missing artifact menjadi available.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
