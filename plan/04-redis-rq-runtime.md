# 04 — Redis privat dan proses RQ untuk orkestrasi

## Tujuan

Tambahkan versi redis-py dan RQ yang kompatibel Python 3.10 dengan pin hasil pemeriksaan metadata resmi saat implementasi. Tambahkan role backend-queue menggunakan image gateway; dependency tersedia dari build yang benar, bukan mengandalkan base lama.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 03 dan P1 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah. Task 04 tidak boleh dimulai sebelum P1 selesai.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

Belum ada Redis/RQ pada requirements. Dockerfile memakai runtime-base dengan dependency dari Dockerfile.base. Gateway menjalankan backend, telegram dan worker-local; remote worker harus tetap HTTP dan tidak memperoleh koneksi Redis. P1 menambahkan diagnosis/recovery helper TTS melalui Worker API; queue tidak boleh menghapus atau melemahkan kontrol Workers Web, auth, atau refresh manual tersebut.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `requirements.txt` |
| Diubah | `Dockerfile` |
| Diubah | `Dockerfile.base` |
| Diubah | `docker-compose.gateway.yml` |
| Diubah | `docker-compose.yml` |
| Diubah | `tme3bot/app.py` |
| Diubah | `tme3bot/config.py` |
| Diubah | `tme3bot/composition.py` |
| Diubah | `tests/test_container.py` |
| Diubah | `tme3bot/api/backend.py` |
| Diubah | `tme3bot/application/operations.py` |
| Baru | `tme3bot/infrastructure/queue_transport.py` |
| Baru | `tme3bot/queue_runner.py` |
| Baru | `tests/test_queue_transport.py` |
| Baru | `tme3bot/api/routes/queue.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

Internal POST /internal/v1/queue/commands/{id}/advance memerlukan service auth dan lease claim; respons hanya accepted/wait/retry/terminal. REDIS_URL adalah bootstrap control-plane baru. RQ membawa ID tanpa secret/text/bundle. Gate durable_dispatch default mati sampai worker mendukung kontrak.

## Spesifikasi implementasi

1. Tambahkan versi redis-py dan RQ yang kompatibel Python 3.10 dengan pin hasil pemeriksaan metadata resmi saat implementasi. Tambahkan role backend-queue menggunakan image gateway; dependency tersedia dari build yang benar, bukan mengandalkan base lama.
2. Tambahkan service Redis di jaringan internal Compose tanpa published port, volume persisten, AOF everysec, dan maxmemory-policy noeviction. Sediakan REDIS_URL hanya untuk backend/backend-queue; runner tidak mount /data atau vault.
3. Backend publisher membaca outbox, enqueue RQ berisi command_id saja dengan job_id deduplikasi. Catat broker receipt setelah publish; proses periodik merekonsiliasi outbox belum terminal agar kehilangan Redis dapat dipulihkan dari SQLite.
4. Runner memanggil endpoint internal backend untuk claim/advance command singkat. Backend memvalidasi service, revision dan fencing, lalu memanggil handler registry operation. Pada task ini handler bisnis yang belum tersedia mengembalikan wait/not_ready tanpa side effect; dispatch worker dipasang task 05. Endpoint tidak menjalankan TDL atau menunggu hasil job. Runner tidak menulis DB langsung.
5. Gunakan bounded retry dengan backoff+jitter dan batas attempt tersimpan. Queue-level timeout bukan pembatalan domain job. Ketika Redis down, accepted operation tetap queued/pending_delivery dan publisher mencoba lagi tanpa fallback sinkron.
6. Pisahkan liveness dan readiness antrean; kegagalan broker tidak membuat data accepted hilang. Tambahkan integration harness memakai Redis lokal disposable, bukan Redis/worker produksi.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 04: Redis privat dan proses RQ untuk orkestrasi.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 03 dan P1.
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
   Perbarui HANYA baris 04 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Publish crash sesudah enqueue tidak menyebabkan command ganda.
- Redis restart/flush pada instance test dapat direkonstruksi dari DB.
- Remote compose tidak membutuhkan Redis; tidak ada port Redis publik.
- Role lama tetap boot saat durable_dispatch belum aktif.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_queue_transport tests.test_container tests.test_operations -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Pada builder dengan Docker: gunakan env fixture tanpa rahasia untuk docker compose -f docker-compose.gateway.yml config --quiet, lalu build image gateway sesuai runbook. Jangan mencetak interpolasi config produksi. Test Redis menggunakan fixture test_queue_transport; catat skip bila Docker tidak tersedia.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Stop runner/publisher setelah drain atau catat seluruh outbox pending. Matikan gate, pertahankan volume Redis dan DB; jangan hapus broker sebagai cara membatalkan domain job.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
