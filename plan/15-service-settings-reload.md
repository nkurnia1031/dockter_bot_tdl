# 15 — Bootstrap persisten dan reload client layanan

## Tujuan

Pisahkan validasi bootstrap dari validasi effective settings. Backend memuat encrypted settings sebelum membuat client; Telegram mengambil scoped bootstrap sebelum memvalidasi bot token. Persisted clear tidak boleh fallback ke ENV.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task P0, 08 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

P0 sudah menyediakan sesi telegram/device dan registry public key laptop. Reload bot token tidak boleh menghapus trust perangkat atau mencabut sesi device. Rotasi JWT mematuhi grace key yang sama untuk kedua kategori; public key Ed25519 perangkat bukan JWT signing secret dan tidak dipindahkan ke settings runtime. Revoke perangkat harus tetap memutus access/refresh setelah reload.

AppConfig.from_env() memvalidasi BOT_TOKEN sebelum app.py memanggil telegram_bootstrap_settings(). runtime/secrets sekarang meminta restart backend/telegram. Telegram UI menggunakan python-telegram-bot 13.15 dan BackendApiClient.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/config.py` |
| Diubah | `tme3bot/app.py` |
| Diubah | `tme3bot/composition.py` |
| Diubah | `tme3bot/backend_runtime_settings.py` |
| Diubah | `tme3bot/api/routes/runtime_settings.py` |
| Diubah | `tme3bot/frontend/client.py` |
| Diubah | `tme3bot/frontend/telegram/app.py` |
| Diubah | `tme3bot/infrastructure/auth.py` |
| Diubah | `tests/test_backend_runtime_settings.py` |
| Diubah | `tests/test_auth_service.py` |
| Diubah | `tests/test_app_menu.py` |
| Baru | `tme3bot/frontend/telegram/runtime_reload.py` |
| Baru | `tests/test_service_settings_reload.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

GET internal telegram/bootstrap mengembalikan versi konfigurasi dan secret hanya untuk service Telegram. GET public secret status tetap redacted; response save memakai pending/applied/error, bukan instruksi restart container untuk perubahan runtime.

## Spesifikasi implementasi

1. Pisahkan validasi bootstrap dari validasi effective settings. Backend memuat encrypted settings sebelum membuat client; Telegram mengambil scoped bootstrap sebelum memvalidasi bot token. Persisted clear tidak boleh fallback ke ENV.
2. Implementasikan pengambilan version layanan di loop internal yang bounded, atau notifikasi yang ada dengan rekonsiliasi periodik. Ini komunikasi control-plane, bukan polling browser. Tidak memberi Redis kepada Telegram/worker.
3. Untuk perubahan bot token, validasi candidate tanpa menampilkan nilainya, drain callback yang sedang berjalan, stop updater lama, bangun client/updater baru dan ACK. Gagal candidate mempertahankan client efektif lama dengan status failed; hindari dua getUpdates loop.
4. Backend yang memakai Bot untuk challenge juga mengganti client setelah validasi; sinkronkan bot username/challenge generation agar link lama tidak dianggap berasal dari bot baru.
5. Rotasi auth/signing/service credential memakai key version dan grace sesuai masa berlaku sesi; token bootstrap enrollment dan kunci vault tidak dihapus dari trust setup. Runtime credential baru persisten dan ACK sebelum old credential dihentikan.
6. Tujuan TTS tetap pengiriman akun TDL dari profil aktif. Jangan menghidupkan kembali pengiriman MP3 melalui Bot API karena ada field legacy TELEGRAM_TTS_CHAT_ID.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 15: Bootstrap persisten dan reload client layanan.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: P0, 08.
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
   Perbarui HANYA baris 15 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Regresi P0 lulus: reload/rotasi credential layanan mempertahankan pemisahan sesi telegram/device, sementara revoke tetap efektif.

- Restart tanpa BOT_TOKEN ENV berhasil bila token persisten tersedia.
- Clear token menghasilkan unconfigured yang jujur, tidak memakai seed lama.
- Update token tidak memerlukan recreate container dan tidak menjalankan dua updater.
- Secret invalid tidak menghentikan client lama tanpa status error yang dapat dilihat.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_service_settings_reload tests.test_backend_runtime_settings tests.test_auth_service tests.test_app_menu -v
python -m unittest tests.test_device_auth tests.test_auth_service -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Pin last-known-good settings melalui backend dan drain/rebuild client sekali. Pertahankan credential overlap sampai ACK; jangan restore file ENV lama sebagai sumber resmi.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
