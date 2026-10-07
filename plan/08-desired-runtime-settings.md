# 08 — Konfigurasi terpusat, versi penerapan, dan rahasia

## Tujuan

Buat registry setting dengan tipe, scope backend/telegram/worker, secret flag, validasi, apply policy dan seed ENV. Gunakan SQLite backend untuk desired version/ACK/audit; encrypt secret dengan AES-GCM dan kunci persisten berizin terbatas.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 03 dan P1 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

BackendRuntimeSettings memakai app_runtime_settings.json; worker runtime memakai worker_settings.json. PUT settings worker saat ini diteruskan sinkron dan dapat gagal ketika worker offline/sibuk. Sebagian secret berada di JSON privat; profile vault sudah memiliki kunci persisten.

Pertahankan kontrak P1: status kesiapan tiap helper TTS dan aksi recovery Tor yang dipicu operator di Workers Web bukan field settings biasa. Perubahan desired/applied `tts_helper_urls` harus tetap menjadi sumber target recovery; jangan menghapus diagnosis atau mengganti recovery terbatas dengan restart Docker.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/backend_runtime_settings.py` |
| Diubah | `tme3bot/api/routes/runtime_settings.py` |
| Diubah | `tme3bot/api/routes/workers.py` |
| Diubah | `tme3bot/api/schemas.py` |
| Diubah | `tme3bot/composition.py` |
| Diubah | `tme3bot/worker_registry.py` |
| Diubah | `tme3bot/utility.py` |
| Diubah | `tme3bot/api/routes/utility.py` |
| Diubah | `tme3bot/domain/models.py` |
| Diubah | `tme3bot/infrastructure/job_store.py` |
| Diubah | `tme3bot/infrastructure/operation_store.py` |
| Diubah | `tme3bot/application/control_plane.py` |
| Diubah | `tme3bot/application/operations.py` |
| Diubah | `tme3bot/api/routes/tts.py` |
| Diubah | `tme3bot/api/backend.py` |
| Diubah | `tests/test_utility_settings.py` |
| Diubah | `tests/test_backend_runtime_settings.py` |
| Diubah | `tests/test_backend_api.py` |
| Diubah | `tests/test_durable_dispatch.py` |
| Baru | `tme3bot/infrastructure/settings_store.py` |
| Baru | `tme3bot/infrastructure/secret_store.py` |
| Baru | `tests/test_desired_settings.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

GET/PUT /api/v1/runtime/settings?scope=&worker=; PUT {expected_version,values}; snapshot {desired_version,applied_version,status,settings,secret_status}. Internal GET /internal/v1/runtime/settings dan POST /internal/v1/runtime/settings/ack dibatasi role/worker. Field clear eksplisit berbeda dari unset.

## Spesifikasi implementasi

1. Buat registry setting dengan tipe, scope backend/telegram/worker, secret flag, validasi, apply policy dan seed ENV. Gunakan SQLite backend untuk desired version/ACK/audit; encrypt secret dengan AES-GCM dan kunci persisten berizin terbatas.
2. Import JSON/ENV lama sekali dengan migration marker; nilai persisten menang. Simpan tombstone untuk clear agar restart tidak memunculkan seed lagi. Jangan log nilai secret atau menyimpan plaintext di audit.
3. GET mengembalikan snapshot backend tanpa worker RPC; PUT menyimpan desired+outbox dengan optimistic version. Worker offline/busy tetap menerima desired dan berstatus pending. Respons status configured untuk secret, bukan nilai.
4. Pertahankan API settings lama melalui adapter. Tambahkan schema-setting response agar Web dapat membedakan runtime dan deploy-only. Validasi chat ref memakai parser tdl yang sama untuk Storage/TTS/backup; jangan mengganti pengiriman TTS menjadi Bot API.
5. Scope secret internal hanya komponen yang membutuhkan. Worker tidak menerima bot token. Rotasi service token mempertahankan old/new overlap sampai ACK; kunci enkripsi vault tetap bootstrap trust dengan prosedur backup.
6. Tambahkan internal settings manifest/ACK untuk task 14/15. Setiap job menyimpan `settings_version` worker saat diterima dan meneruskannya ke command durable. Job TTS juga menyimpan target chat yang dipin saat submit sebagai ciphertext backend-only; perubahan konfigurasi berikutnya tidak mengubah target job yang sudah diterima. Jangan tampilkan target itu di API job, event, log, atau payload worker.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 08: Konfigurasi terpusat, versi penerapan, dan rahasia.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 03, P1.
2. Periksa fungsi dan kontrak pada bagian Konteks. Gunakan graphify query terlebih
   dahulu untuk relasi kode, lalu source aktual. Jangan membuka nilai secret.
3. Ikuti seluruh langkah bernomor pada Spesifikasi implementasi dalam file ini.
   Gunakan apply_patch, Python 3.10 dan batas domain/application/infrastructure.
   Allowlist di atas telah diperluas secara terbatas untuk menutup kontrak
   snapshot job yang tertinggal. Jangan mengubah file lain atau mengerjakan task
   berikutnya.
4. Pertahankan API legacy/gate sesuai kontrak. Jangan deploy, publish, commit,
   mengakses production, mengirim Telegram nyata, atau menjalankan migrasi data nyata.
5. Tambahkan/uji skenario Kriteria selesai dengan mock/fixture lokal. Jalankan
   seluruh Cara verifikasi. Catat kegagalan atau tool tidak tersedia secara jujur.
6. Periksa diff agar hanya perubahan task ini dan output tool yang diizinkan.
   Perbarui HANYA baris 08 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- PUT offline cepat dan persisten; restart membaca desired terbaru.
- Konflik expected_version mendapat 409.
- Clear+restart tidak menghidupkan ENV lama.
- Secret tidak ada di public GET/log/audit; ACK scope salah ditolak.
- Versi settings worker tercatat sama pada job dan command durable; target TTS terenkripsi dan tetap sesuai snapshot setelah setting berubah.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_desired_settings tests.test_backend_runtime_settings tests.test_utility_settings tests.test_backend_api tests.test_durable_dispatch -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Pertahankan ciphertext, version dan migration marker. Nonaktifkan jalur apply baru setelah drain; bila perlu ekspor konfigurasi efektif secara privat, bukan mencetak rahasia atau restore seed ENV lama.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
