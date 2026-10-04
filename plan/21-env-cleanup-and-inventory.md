# 21 — Penyederhanaan ENV dan inventaris pemakaian

## Tujuan

Verifikasi ulang setiap baris inventaris di lampiran dengan source terkini; bedakan pembaca parser dan consumer perilaku. Nilai tidak ditemukan/ambigu jangan dihapus atas dugaan. Tidak membuka atau menampilkan isi .env produksi.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 14, 15, 20 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

AppConfig.from_env membaca mayoritas konfigurasi; tdl.py, backup_service.py, utility/pindah dan run.py juga membaca ENV langsung. Contoh .env.web masih tersisa meski Web statis. Lampiran task ini adalah inventaris source, bukan daftar nilai deployment produksi.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/config.py` |
| Diubah | `tme3bot/app.py` |
| Diubah | `tme3bot/backend_runtime_settings.py` |
| Diubah | `tme3bot/worker/runtime_settings.py` |
| Diubah | `tme3bot/tdl.py` |
| Diubah | `tme3bot/backup_service.py` |
| Diubah | `utility/pindah/pindah.py` |
| Diubah | `utility/pindah/pindah4.py` |
| Diubah | `tme3bot/utility.py` |
| Diubah | `utility/compress/compress.sh` |
| Diubah | `tests/test_utility_settings.py` |
| Diubah | `run.py` |
| Diubah | `.env.example` |
| Diubah | `.env.backend.example` |
| Diubah | `.env.worker.example` |
| Diubah | `.env.worker.local.example` |
| Diubah | `.env.telegram.example` |
| Diubah | `.env.web.example` |
| Diubah | `docker-compose.gateway.yml` |
| Diubah | `docker-compose.worker.yml` |
| Diubah | `docker-compose.yml` |
| Diubah | `docs/PENGATURAN_RUNTIME.md` |
| Diubah | `DEPLOYMENT_RUNBOOK.md` |
| Diubah | `tests/test_run.py` |
| Diubah | `tests/test_backend_runtime_settings.py` |
| Diubah | `tests/test_worker_runtime_settings.py` |
| Baru | `tests/test_env_migration.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

Tidak ada API baru selain registry setting yang sudah dibuat. Nilai deploy-only tetap dikenali parser bootstrap; runtime values berasal dari stored configuration. Legacy alias dipetakan sekali dengan audit migration, bukan fallback tak terbatas.

## Spesifikasi implementasi

1. Verifikasi ulang setiap baris inventaris di lampiran dengan source terkini; bedakan pembaca parser dan consumer perilaku. Nilai tidak ditemukan/ambigu jangan dihapus atas dugaan. Tidak membuka atau menampilkan isi .env produksi.
2. Sisakan ENV role/identity, endpoint bootstrap, bind/port, mount/data root, trust enrollment, REDIS_URL control plane dan build/deploy tooling. Image paths/users/binary layout diturunkan dari image; override deploy lama dipertahankan sebagai bootstrap deprecated bila perlu.
3. Untuk runtime/secret, import-once ke settings backend dan tombstone clear. Migrasikan alias channel ke satu chat_ref canonical dengan sumber konflik dilaporkan; jangan mengubah target diam-diam. ENV bukan override setiap restart.
4. Selesaikan pembacaan langsung timeout/resolve/utility/logging yang masih bypass config snapshot. Namespace sesi yang sudah ada menjadi metadata profile revision; mengubah namespace tidak boleh dianggap sekadar setting yang aman pada database aktif.
5. Update contoh ENV dengan placeholder tanpa secret. Hapus key deprecated dari contoh hanya setelah consumer/compat diuji; .env.web.example boleh menjadi penjelasan static deployment, jangan menambah container web.
6. Dokumentasikan fresh install, upgrade konfigurasi, restore trust/vault dan restart tanpa seed. Perbarui CLI run.py agar bootstrap tetap bekerja dengan settings persisten. Jalankan fixture ENV test terisolasi; tidak memutasi file konfigurasi pengguna.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 21: Penyederhanaan ENV dan inventaris pemakaian.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 14, 15, 20.
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
   Perbarui HANYA baris 21 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Fresh install dan upgrade tanpa kehilangan config diuji.
- Restart tanpa ENV runtime bekerja; clear tetap clear.
- Seluruh nama inventory mempunyai owner/kategori/migration, termasuk helper dan tooling.
- Static Web tetap tidak membutuhkan .env runtime/Node server.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_env_migration tests.test_run tests.test_backend_runtime_settings tests.test_worker_runtime_settings -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Pertahankan seed backup privat dan settings store. Rollback parser hanya setelah effective config diekspor privat ke format versi lama; jangan menulis secret ke contoh ENV atau log.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.

## Lampiran — inventaris ENV baseline

Audit 2026-10-04 pada `c5c76b3` beserta worktree lokal. Inventaris awal 133 nama diperluas menjadi **153 nama** setelah memasukkan env subprocess, proxy, shell dan build. Angka ini bukan jumlah setting aplikasi aktif.

Metode: AST Python untuk getenv/environ/env-dict, interpolasi Compose/Dockerfile, contoh ENV, lalu pemeriksaan injection subprocess, shell dan workflow CI. Pencarian consumer field dibatasi source aplikasi; parser-only dinyatakan demikian. ENV bawaan seluruh OS/library tidak didaftar kecuali repo membaca atau mengaturnya secara eksplisit. Nama variabel shell lokal DIR/SCRIPT_DIR bukan ENV konfigurasi.

Kategori adalah **tujuan desain**; kolom penggunaan adalah bukti keadaan saat audit. Jalur contoh ENV hanya dipakai jika pembaca source tidak ditemukan. Tidak ada nilai rahasia atau nilai konfigurasi production di tabel.

| Nama | Lokasi pembaca/injection | Pemakaian aktual | Kategori tujuan | Pengganti/pemilik | Strategi migrasi |
|---|---|---|---|---|---|
| `APP_ROLE` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/app.py`, `tme3bot/profiles.py`. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `AUTH_ACCESS_MINUTES` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/composition.py`. | Pengaturan backend | backend.auth_access_minutes | Import sekali; validated schema, persisted wins, apply sesuai scope. |
| `AUTH_CHALLENGE_MINUTES` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/composition.py`. | Pengaturan backend | backend.auth_challenge_minutes | Import sekali; validated schema, persisted wins, apply sesuai scope. |
| `AUTH_JWT_SECRET` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/routes/storage.py`, `tme3bot/composition.py`. | Rahasia terkelola | Trust bootstrap lalu secret store berversi | Seed privat untuk enrollment awal; runtime rotation lewat settings dengan overlap/ACK. Kunci vault persisten terpisah. |
| `AUTH_REFRESH_DAYS` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/composition.py`. | Pengaturan backend | backend.auth_refresh_days | Import sekali; validated schema, persisted wins, apply sesuai scope. |
| `BACKEND_API_URL` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/app.py`, `tme3bot/composition.py`, `tme3bot/frontend/telegram/app.py`, `tme3bot/profiles.py`. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `BACKEND_BIND_HOST` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/composition.py`. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `BACKEND_ENV_FILE` | `docker-compose.gateway.yml`, `docker-compose.yml`, `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `BACKEND_INTERNAL_TOKEN` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/backend.py`, `tme3bot/composition.py`, `tme3bot/profiles.py`, `tme3bot/worker/executor.py`. | Rahasia terkelola | Trust bootstrap lalu secret store berversi | Seed privat untuk enrollment awal; runtime rotation lewat settings dengan overlap/ACK. Kunci vault persisten terpisah. |
| `BACKEND_PORT` | `docker-compose.gateway.yml`, `docker-compose.yml`, `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/composition.py`. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `BACKUP_CHANNEL` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/routes/backups.py`, `tme3bot/composition.py`. | Pengaturan backend | backup.chat_ref | Gabungkan alias sekali setelah validasi; konflik target dilaporkan. |
| `BACKUP_CHANNEL_ID` | `tme3bot/config.py` | Alias numeric parser membentuk backup_channel_id bersama backup_channel. | Pengaturan backend | backup.chat_ref | Gabungkan alias sekali setelah validasi; konflik target dilaporkan. |
| `BACKUP_CHANNEL_REF` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/routes/backups.py`, `tme3bot/backup_coordinator.py`, `tme3bot/composition.py`. | Pengaturan backend | backup.chat_ref | Gabungkan alias sekali setelah validasi; konflik target dilaporkan. |
| `BACKUP_CHANNEL_USERNAME` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Pengaturan backend | backup.chat_ref | Gabungkan alias sekali setelah validasi; konflik target dilaporkan. |
| `BACKUP_ENABLED` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/backend.py`, `tme3bot/api/routes/backups.py`, `tme3bot/backup_coordinator.py`, `tme3bot/composition.py`. | Pengaturan backend | backup policy | Import sekali ke scheduler settings; job menyimpan snapshot efektif. |
| `BACKUP_NODE_NAME` | `tme3bot/config.py` | Identitas backup node; parser AppConfig dan backup coordinator/service. | Bootstrap/deployment | Identitas node backup | Pertahankan identitas stabil; label tampilan dapat runtime, penggantian identitas butuh migrasi. |
| `BACKUP_RETENTION` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/routes/backups.py`, `tme3bot/backup_coordinator.py`, `tme3bot/composition.py`. | Pengaturan backend | backup policy | Import sekali ke scheduler settings; job menyimpan snapshot efektif. |
| `BACKUP_SCHEDULE` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/backend.py`, `tme3bot/api/routes/backups.py`, `tme3bot/backup_coordinator.py`, `tme3bot/composition.py`. | Pengaturan backend | backup policy | Import sekali ke scheduler settings; job menyimpan snapshot efektif. |
| `BACKUP_TIMEZONE` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/backend.py`, `tme3bot/api/routes/backups.py`, `tme3bot/backup_coordinator.py`, `tme3bot/composition.py`. | Pengaturan backend | backup policy | Import sekali ke scheduler settings; job menyimpan snapshot efektif. |
| `BACKUP_VOLUME_SIZE` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/routes/backups.py`, `tme3bot/backup_coordinator.py`, `tme3bot/backup_service.py`, `tme3bot/composition.py`. | Pengaturan backend | backup policy | Import sekali ke scheduler settings; job menyimpan snapshot efektif. |
| `BASE_PLATFORM` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `BOT_TOKEN` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/routes/runtime_settings.py`, `tme3bot/composition.py`, `tme3bot/frontend/telegram/app.py`. | Rahasia terkelola | backend/telegram.bot_token | Import sekali, reload client setelah validasi, public API hanya configured; clear tidak fallback ENV. |
| `BOT_USERNAME` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/routes/storage.py`, `tme3bot/composition.py`, `tme3bot/infrastructure/auth.py`. | Pengaturan backend | backend.bot_username | Import sekali; validated schema, persisted wins, apply sesuai scope. |
| `BUILDPLATFORM` | `Dockerfile.base` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `BUILD_SHA` | `.github/workflows/web-static.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `CGO_ENABLED` | `Dockerfile.base` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `COLUMNS` | `tme3bot/tdl.py`, `tme3bot/worker/profile_sessions.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Environment sistem/subprocess | Pertahankan injection image/proses; bukan field pengaturan bisnis. |
| `COMPOSE_CMD` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `COMPOSE_FILE` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `DEBIAN_FRONTEND` | `Dockerfile.base` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `DEFAULT_PROFILE` | `run.py`, `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/profile_provisioning.py`, `tme3bot/profile_registry.py`, `tme3bot/profiles.py`, `tme3bot/worker/profile_sessions.py`. | Bootstrap/deployment | Identitas layout default | Pertahankan reserved profile default; pilihan default UI adalah setting berbeda, bukan rename filesystem. |
| `DEPLOY_TARGET` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `DOCKER_CMD` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `DOWNLOAD_ROOT` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/profiles.py`, `tme3bot/service.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `EXPORT_DONE_DIR` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/backup_service.py`, `tme3bot/profiles.py`, `tme3bot/service.py`, `tme3bot/worker/executor_downloads.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `EXPORT_FAILED_DIR` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/backup_service.py`, `tme3bot/profiles.py`, `tme3bot/service.py`, `tme3bot/worker/executor_downloads.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `EXPORT_PENDING_DIR` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/backup_service.py`, `tme3bot/profiles.py`, `tme3bot/service.py`, `tme3bot/worker/executor_downloads.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `EXPORT_PROCESSING_DIR` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/backup_service.py`, `tme3bot/profiles.py`, `tme3bot/service.py`, `tme3bot/worker/executor_downloads.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `EXPORT_ROOT` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `FRONTEND_SERVICE_TOKEN` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/backend.py`, `tme3bot/app.py`, `tme3bot/frontend/client.py`, `tme3bot/frontend/telegram/app.py`. | Rahasia terkelola | Trust bootstrap lalu secret store berversi | Seed privat untuk enrollment awal; runtime rotation lewat settings dengan overlap/ACK. Kunci vault persisten terpisah. |
| `GATEWAY_API_TOKEN` | `tme3bot/config.py` | Field dan parser config ditemukan; consumer perilaku lain tidak ditemukan. | Legacy/ambigu | Tidak ditemukan consumer selain field/parser AppConfig | Jangan hapus sampai compatibility test; bukan bukti dipakai runtime. Jangan tampilkan nilai token. |
| `GATEWAY_API_URL` | `tme3bot/config.py` | Field dan parser config ditemukan; consumer perilaku lain tidak ditemukan. | Legacy/ambigu | Tidak ditemukan consumer selain field/parser AppConfig | Jangan hapus sampai compatibility test; bukan bukti dipakai runtime. Jangan tampilkan nilai token. |
| `GATEWAY_DATA_ROOT` | `docker-compose.gateway.yml`, `docker-compose.yml`, `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `GATEWAY_IMAGE_NAME` | `docker-compose.gateway.yml`, `docker-compose.yml`, `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `GATEWAY_PORT` | `tme3bot/config.py` | Fallback parser ketika BACKEND_PORT tidak diset. | Legacy/migrasi | Alias BACKEND_PORT | Normalisasi bootstrap dengan deprecation; bukan runtime port change. |
| `GHCR_TOKEN` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `GHCR_USERNAME` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `GITHUB_OUTPUT` | `.github/workflows/docker-images.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `GITHUB_REPOSITORY_OWNER` | `.github/workflows/docker-images.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `GITHUB_SHA` | `.github/workflows/docker-images.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `GOARCH` | `Dockerfile.base` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `GOMAXPROCS` | `Dockerfile.base` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `GOOS` | `Dockerfile.base` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `HOME` | `Dockerfile.base`, `tme3bot/leave.py`, `tme3bot/tdl.py` | Ditetapkan image dan env subprocess untuk pemilihan home sesi. | Build/tooling | Environment sistem/subprocess | Pertahankan injection image/proses; bukan field pengaturan bisnis. |
| `HTTPS_PROXY` | `docker-compose.gateway.yml`, `docker-compose.worker.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Bootstrap/deployment | Jalur SOCKS helper dalam container | Library HTTP membaca proxy dari environment proses; konfigurasi topology helper tetap compose, bukan worker biasa. |
| `HTTP_PROXY` | `docker-compose.gateway.yml`, `docker-compose.worker.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Bootstrap/deployment | Jalur SOCKS helper dalam container | Library HTTP membaca proxy dari environment proses; konfigurasi topology helper tetap compose, bukan worker biasa. |
| `IMAGE_TAG` | `docker-compose.gateway.yml`, `docker-compose.worker.yml`, `docker-compose.yml`, `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `JOB_CANCEL_GRACE_SECONDS` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/routes/backups.py`, `tme3bot/application/control_plane.py`, `tme3bot/composition.py`. | Pengaturan backend | backend.job_cancel_grace_seconds | Import sekali; validated schema, persisted wins, apply sesuai scope. |
| `JOB_STALL_TIMEOUT_SECONDS` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/routes/backups.py`, `tme3bot/application/control_plane.py`, `tme3bot/composition.py`. | Pengaturan backend | backend.job_stall_timeout_seconds | Import sekali; validated schema, persisted wins, apply sesuai scope. |
| `LEAVE_HELPER_BINARY` | `run.py`, `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/leave.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `LEGACY_MAX_JSON` | `tme3bot/config.py` | Sumber migrasi legacy max.json pada StateStore. | Legacy/migrasi | Repository backend transaksional | Baca untuk import satu kali; archive sesudah verifikasi. Jangan fallback ke state worker. |
| `LINES` | `tme3bot/tdl.py`, `tme3bot/worker/profile_sessions.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Environment sistem/subprocess | Pertahankan injection image/proses; bukan field pengaturan bisnis. |
| `LOCAL_WORKER_DATA_ROOT` | `docker-compose.gateway.yml`, `docker-compose.yml`, `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `LOCAL_WORKER_ENV_FILE` | `docker-compose.gateway.yml`, `docker-compose.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `LOG_LEVEL` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/app.py`, `tme3bot/composition.py`, `tme3bot/profiles.py`. | Runtime backend/worker | logging.level per komponen | Import sekali, reload logger tanpa recreate container; tidak menambah logging secret. |
| `MANAGEMENT_API_TOKEN` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/backend.py`. | Rahasia terkelola | Trust bootstrap lalu secret store berversi | Seed privat untuk enrollment awal; runtime rotation lewat settings dengan overlap/ACK. Kunci vault persisten terpisah. |
| `NODE_ENV` | `.env.web.example` | Hanya .env.web.example; consumer aplikasi tidak ditemukan/ambigu. | Legacy/ambigu | Hanya contoh konfigurasi ditemukan | Tidak ditemukan consumer aplikasi langsung pada audit; verifikasi framework/deploy sebelum menghapus. |
| `NO_COLOR` | `tme3bot/worker/profile_sessions.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Environment sistem/subprocess | Pertahankan injection image/proses; bukan field pengaturan bisnis. |
| `NO_PROXY` | `docker-compose.gateway.yml`, `docker-compose.worker.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Bootstrap/deployment | Jalur SOCKS helper dalam container | Library HTTP membaca proxy dari environment proses; konfigurasi topology helper tetap compose, bukan worker biasa. |
| `PROFILES_ROOT` | `run.py`, `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/backup_service.py`, `tme3bot/profiles.py`. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `PROFILE_DATA_ROOT` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `PROFILE_ROOT` | `docker-compose.worker.yml`, `run.py` | Parser/injection; consumer field: `tme3bot/backup_service.py`, `tme3bot/profiles.py`, `tme3bot/worker/profile_sessions.py`. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `PWD` | `utility/compress/compress.sh` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Environment sistem/subprocess | Pertahankan injection image/proses; bukan field pengaturan bisnis. |
| `PYTHONDONTWRITEBYTECODE` | `Dockerfile.base` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Environment sistem/subprocess | Pertahankan injection image/proses; bukan field pengaturan bisnis. |
| `PYTHONUNBUFFERED` | `Dockerfile.base`, `tme3bot/utility.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Environment sistem/subprocess | Pertahankan injection image/proses; bukan field pengaturan bisnis. |
| `RCLONE_CONFIG_PATH` | `run.py`, `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `REQUIRE_7Z_HOST` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `SERVICE_NAME` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `SEVEN_ZIP_BINARY` | `tme3bot/backup_service.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `STATE_FILE` | `tme3bot/config.py` | Lokasi state JSON legacy yang menjadi dasar beberapa data-root; jangan hapus sebelum layout dipisahkan. | Legacy/migrasi | Repository backend transaksional | Baca untuk import satu kali; archive sesudah verifikasi. Jangan fallback ke state worker. |
| `STORAGE_CHANNEL` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/routes/storage.py`. | Pengaturan backend | storage.chat_ref | Gabungkan alias sekali; parser TDL menerima ID/username/link/phone yang sesuai. |
| `STORAGE_CHANNEL_ID` | `tme3bot/config.py` | Alias numeric parser membentuk storage_channel_id bersama storage_channel. | Pengaturan backend | storage.chat_ref | Gabungkan alias sekali; parser TDL menerima ID/username/link/phone yang sesuai. |
| `STORAGE_CHANNEL_REF` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/worker/executor_storage.py`. | Pengaturan backend | storage.chat_ref | Gabungkan alias sekali; parser TDL menerima ID/username/link/phone yang sesuai. |
| `STORAGE_CHANNEL_USERNAME` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Pengaturan backend | storage.chat_ref | Gabungkan alias sekali; parser TDL menerima ID/username/link/phone yang sesuai. |
| `STORAGE_DB_FILE` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/backup_service.py`, `tme3bot/composition.py`. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `STORAGE_TRASH_RETENTION_DAYS` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/routes/backups.py`, `tme3bot/composition.py`. | Pengaturan backend | backend.storage_trash_retention_days | Import sekali; validated schema, persisted wins, apply sesuai scope. |
| `TARGETARCH` | `Dockerfile.base` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `TDL_DOWNLOAD_HOME` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/backup_service.py`, `tme3bot/profiles.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `TDL_DOWNLOAD_NAMESPACE` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/profiles.py`. | Runtime worker/profil | Namespace dalam metadata revision profil | Import ke profil; perubahan perlu validasi sesi dan safe apply. Bukan mengganti identitas profil diam-diam. |
| `TDL_DOWNLOAD_STALL_TIMEOUT_SECONDS` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/profiles.py`. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TDL_DOWNLOAD_STORAGE` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/profiles.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `TDL_DOWNLOAD_USER` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/profiles.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `TDL_EXPORT_HOME` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/backup_service.py`, `tme3bot/leave.py`, `tme3bot/profiles.py`, `tme3bot/worker/profile_sessions.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `TDL_EXPORT_NAMESPACE` | `run.py`, `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/leave.py`, `tme3bot/profiles.py`, `tme3bot/worker/profile_sessions.py`. | Runtime worker/profil | Namespace dalam metadata revision profil | Import ke profil; perubahan perlu validasi sesi dan safe apply. Bukan mengganti identitas profil diam-diam. |
| `TDL_EXPORT_STALL_TIMEOUT_SECONDS` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/profiles.py`. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TDL_EXPORT_STORAGE` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/leave.py`, `tme3bot/profiles.py`, `tme3bot/worker/executor.py`, `tme3bot/worker/executor_storage.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `TDL_EXPORT_USER` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/leave.py`, `tme3bot/profiles.py`, `tme3bot/worker/profile_sessions.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `TDL_FALLBACK_VERSION` | `Dockerfile.base` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `TDL_FORCE_PTY` | `tests/test_tdl.py`, `tme3bot/leave.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TDL_HOST_BINARY` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `TDL_TERMINAL_COLUMNS` | `tme3bot/tdl.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TDL_TERMINAL_ROWS` | `tme3bot/tdl.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TDL_UPLOAD_RESOLVE_INTERVAL_SECONDS` | `tme3bot/tdl.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TDL_UPLOAD_RESOLVE_LAST_COUNT` | `tme3bot/tdl.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TDL_UPLOAD_RESOLVE_TIMEOUT_SECONDS` | `tme3bot/tdl.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TELEGRAM_ENV_FILE` | `docker-compose.gateway.yml`, `docker-compose.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `TELEGRAM_TTS_CHAT_ID` | `tme3bot/config.py` | Nama legacy dibaca config; routes/tts.py membaca pengaturan chat TTS efektif. | Pengaturan backend | tts.chat_ref | Legacy nama tetap adapter; pengiriman TDL profil aktif. Bukan alasan restart container Telegram. |
| `TEMP_ROOT` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/backup_service.py`, `tme3bot/profiles.py`, `tme3bot/service.py`. | Bootstrap/deployment | Layout image/data atau binary | Turunkan dari layout image; pertahankan override bootstrap kompatibel. Jangan pindah file aktif lewat settings. |
| `TERM` | `tme3bot/tdl.py`, `tme3bot/worker/profile_sessions.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Environment sistem/subprocess | Pertahankan injection image/proses; bukan field pengaturan bisnis. |
| `TME3BOT_BASE_IMAGE` | `Dockerfile`, `docker-compose.gateway.yml`, `docker-compose.worker.yml`, `docker-compose.yml`, `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `TME3BOT_ENV_FILE` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `TME3_HOST` | `tme3bot/config.py` | Domain normalisasi/link, diteruskan AppConfig ke service/url parser. | Pengaturan backend | backend.tme3_host | Import sekali; validated schema, persisted wins, apply sesuai scope. |
| `TTS_DATA_ROOT` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/worker/executor_tts.py`. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `TTS_HELPER_URLS` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TTS_NEWNYM_AFTER_RETRIES` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TTS_PART_RETRIES` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TTS_RETRY_BASE_SECONDS` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TTS_TOR_CONTROL_HOSTS` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TTS_TOR_CONTROL_PORTS` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `TTS_TOR_DATA_DIR` | `docker-compose.gateway.yml`, `docker-compose.worker.yml`, `tme3bot/worker/tts_helper.py` | Dibaca helper untuk direktori Tor; Compose memasok key. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `UTILITY_COMPRESS_PASSWORD` | `tme3bot/utility.py`, `utility/compress/compress.sh` | Ditulis utility.py dan dibaca script compress.sh; nilai tidak dicantumkan. | Rahasia terkelola | utility.compress_password | Kelola terenkripsi; env subprocess privat sementara. Jangan salin nilai fallback source ke dokumen atau log. |
| `UTILITY_COMPRESS_SIZE` | `tme3bot/utility.py`, `utility/compress/compress.sh` | Ditulis utility.py dan dibaca script compress.sh. | Runtime worker | utility options | Teruskan snapshot settings ke subprocess; bukan sumber ENV container wajib. |
| `UTILITY_FOLDERS_FILE` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/composition.py`. | Legacy/migrasi | Repository backend transaksional | Baca untuk import satu kali; archive sesudah verifikasi. Jangan fallback ke state worker. |
| `UTILITY_MOVE_SIZE` | `tme3bot/utility.py`, `utility/pindah/pindah.py`, `utility/pindah/pindah4.py` | Dibaca script pindah.py/pindah4.py. | Runtime worker | utility options | Teruskan snapshot settings ke subprocess; bukan sumber ENV container wajib. |
| `UTILITY_SETTINGS_FILE` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/backup_service.py`, `tme3bot/composition.py`. | Legacy/migrasi | Repository backend transaksional | Baca untuk import satu kali; archive sesudah verifikasi. Jangan fallback ke state worker. |
| `UTILITY_WORKSPACE_HOST` | `docker-compose.gateway.yml`, `docker-compose.worker.yml`, `docker-compose.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `UTILITY_WORKSPACE_ROOT` | `docker-compose.gateway.yml`, `docker-compose.worker.yml`, `docker-compose.yml`, `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/composition.py`, `tme3bot/worker/executor_workspace.py`. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `WEB_COOKIE_SECRET` | `tme3bot/config.py` | Digunakan backend untuk penandatanganan cookie Web. | Rahasia terkelola | Trust bootstrap lalu secret store berversi | Seed privat untuk enrollment awal; runtime rotation lewat settings dengan overlap/ACK. Kunci vault persisten terpisah. |
| `WEB_COOKIE_SECURE` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Pengaturan backend | backend.web_cookie_secure | Import sekali; validated schema, persisted wins, apply sesuai scope. |
| `WEB_DEPLOY_ROOT` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `WEB_ENV_FILE` | `.env.example` | Hanya .env.example; consumer aplikasi tidak ditemukan/ambigu. | Legacy/ambigu | Hanya contoh konfigurasi ditemukan | Tidak ditemukan consumer aplikasi langsung pada audit; verifikasi framework/deploy sebelum menghapus. |
| `WEB_IMAGE_MODE` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Legacy/tooling | Cabang container web lama di run.py | Aktif hanya pada jalur legacy eksplisit; produksi tetap static. Deprecate setelah uji CLI. |
| `WEB_IMAGE_NAME` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Legacy/tooling | Cabang container web lama di run.py | Aktif hanya pada jalur legacy eksplisit; produksi tetap static. Deprecate setelah uji CLI. |
| `WEB_PORT` | `.env.example` | Hanya .env.example; consumer aplikasi tidak ditemukan/ambigu. | Legacy/ambigu | Hanya contoh konfigurasi ditemukan | Tidak ditemukan consumer aplikasi langsung pada audit; verifikasi framework/deploy sebelum menghapus. |
| `WEB_PUBLIC_ORIGIN` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Pengaturan backend | backend.web_public_origin | Import sekali; validated schema, persisted wins, apply sesuai scope. |
| `WEB_RELEASE_CACHE_ROOT` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `WEB_RELEASE_KEEP` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `WEB_RELEASE_REPOSITORY` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `WEB_RELEASE_TAG` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `WEB_RELEASE_TOKEN` | `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `WORKER_API_TOKEN` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/api/worker.py`, `tme3bot/composition.py`, `tme3bot/worker/executor.py`, `tme3bot/worker/runtime_settings.py`. | Rahasia terkelola | Trust bootstrap lalu secret store berversi | Seed privat untuk enrollment awal; runtime rotation lewat settings dengan overlap/ACK. Kunci vault persisten terpisah. |
| `WORKER_API_TOKENS` | `tme3bot/config.py` | Mapping token per worker dibaca config lalu dipakai registry/dispatcher. | Rahasia terkelola | Trust bootstrap lalu secret store berversi | Seed privat untuk enrollment awal; runtime rotation lewat settings dengan overlap/ACK. Kunci vault persisten terpisah. |
| `WORKER_BIND_HOST` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/composition.py`. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `WORKER_ENDPOINTS` | `tme3bot/config.py` | JSON mapping endpoint dibaca config lalu menjadi seed WorkerRegistry. | Pengaturan backend | Registry worker dan route profil | Import seed sekali, pengubahan melalui Web; job aktif tetap di origin lama. |
| `WORKER_ENV_FILE` | `docker-compose.worker.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `WORKER_IMAGE_NAME` | `docker-compose.gateway.yml`, `docker-compose.worker.yml`, `docker-compose.yml`, `run.py` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Build/tooling | Build, CLI deploy, release atau CI | Tetap pada builder/host/CI; secret publish tidak dikirim ke Web/worker aplikasi. |
| `WORKER_LOCAL_URL` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/profiles.py`. | Pengaturan backend | Registry worker dan route profil | Import seed sekali, pengubahan melalui Web; job aktif tetap di origin lama. |
| `WORKER_PORT` | `docker-compose.worker.yml`, `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/composition.py`. | Bootstrap/deployment | Role, endpoint, mount atau lokasi data | Tetap bootstrap; perubahan topology/path memerlukan deployment, bukan apply runtime. |
| `WORKER_REMOTE_URL` | `tme3bot/config.py` | Parser/injection; consumer field: `tme3bot/profiles.py`. | Pengaturan backend | Registry worker dan route profil | Import seed sekali, pengubahan melalui Web; job aktif tetap di origin lama. |
| `WORKER_ROUTES` | `tme3bot/config.py` | Mapping route legacy dibaca config, menjadi seed route persisten. | Pengaturan backend | Registry worker dan route profil | Import seed sekali, pengubahan melalui Web; job aktif tetap di origin lama. |
| `WORKER_STORAGE_PROFILE` | `tme3bot/config.py` | Dibaca AppConfig; lihat field/alias pada parser sebelum mengubah consumer. | Runtime worker | worker options | Import sekali ke desired settings, apply saat resource aman; job snapshot tidak berubah. |
| `http_proxy` | `docker-compose.gateway.yml`, `docker-compose.worker.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Bootstrap/deployment | Jalur SOCKS helper dalam container | Library HTTP membaca proxy dari environment proses; konfigurasi topology helper tetap compose, bukan worker biasa. |
| `https_proxy` | `docker-compose.gateway.yml`, `docker-compose.worker.yml` | Dibaca atau diinjeksikan langsung oleh source pada kolom lokasi. | Bootstrap/deployment | Jalur SOCKS helper dalam container | Library HTTP membaca proxy dari environment proses; konfigurasi topology helper tetap compose, bukan worker biasa. |

### Penambahan yang direncanakan

- `REDIS_URL`: baru pada task 04; bootstrap backend dan backend-queue saja. Nilainya privat dan tidak diberikan ke worker remote atau Web.
- Kunci enkripsi vault tetap file persisten berizin terbatas, bukan field rahasia yang bisa diganti bebas tanpa re-enkripsi/backup.
- Gerbang migrasi disimpan sebagai metadata backend. Jangan menambah ENV flag untuk setiap tahap.
- Path rclone tetap bootstrap; isi credential rclone mengikuti pengaturan privat yang ada dan tidak dicetak pada inventaris.
- Asal nilai secret lama disimpan sebagai metadata audit tanpa nilainya. Rotasi dan clear diuji sebelum contoh ENV lama dirapikan.
