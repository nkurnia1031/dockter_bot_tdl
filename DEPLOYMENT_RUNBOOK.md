# TME3Bot Deployment Runbook

Versi: 3.4 - Storage file manager, notifikasi export, dan Telegram export workspace

Dokumen ini adalah urutan update resmi. Gateway menjalankan tiga container:
`backend`, `telegram`, dan `worker-local`. Dashboard adalah file static dan
tidak membutuhkan Node.js atau container web di VPS target.

## Topologi deployment

| Node | Service | Cara update |
|---|---|---|
| VPS builder besar | Build image gateway dan worker | `python3 run.py publish gateway` |
| VPS gateway | `backend`, `telegram`, `worker-local` | `python3 run.py deploy gateway --pull` |
| Setiap VPS worker remote | `worker` | `python3 run.py deploy worker --pull` |
| aaPanel UI | Svelte static di document root | `python3 run.py deploy web` |

Untuk update Storage file manager ini, urutan wajib adalah:

1. Backend dan worker-local di VPS gateway.
2. Seluruh worker remote.
3. Web static.

Backend harus diperbarui lebih dahulu karena backend membuat tabel folder,
kolom Trash, dan antrean sinkronisasi caption. Worker baru lalu mengirim relative
path agar nested/empty folder dapat dipertahankan. Migrasi SQLite berjalan
otomatis dan idempotent saat backend mulai. Tidak ada perintah migrasi database
manual. Data `/data`, katalog, state, dan sesi TDL tidak dihapus.

Worker release ini juga menambahkan statistik `message_count`, `media_count`,
`photo_count`, dan `video_count` pada report akhir export. Web memakai data itu
untuk notifikasi fixed saat export masuk antrean dan selesai.

## Workspace export Telegram

`/start`, `/menu`, dan `/panel` sekarang membuka `Export fokus` sebagai panel
awal. Panel ini menggabungkan pemilihan source, label opsional, Start ID, dan
pengiriman export dalam satu pesan Telegram. Source tersimpan dipilih melalui
tombol inline; source baru dapat dimasukkan sebagai username tanpa `@` atau
numeric chat ID. Username dengan dan tanpa `@` dianggap source yang sama.

`Start ID` kosong memakai `Last ID backend + 1`. Jika diisi manual, bot mengirim
`use_url_message_id=true` agar override benar-benar dipakai dan tidak ditimpa
oleh state source. Label custom otomatis masuk daftar label berikutnya.

Tombol `Workspace full fitur` membuka menu utility, storage, download, backup,
worker, settings, dan source management lama. Pergantian workspace hanya
mengubah tampilan bot; profile, worker route, state source, dan job aktif tidak
berubah. Setelah restart frontend Telegram, mode awal kembali ke `Export fokus`.

Saat export diterima, Telegram menampilkan alert antrean. Saat job terminal,
bot mengirim satu notifikasi baru berisi status, jumlah message/media/foto/video,
latest ID, dan artifact. Panel job tetap dapat dibuka melalui tombol report.

## Sekali saja: konfigurasi gateway dan UI

Pada `.env.backend`, isi konfigurasi browser:

```env
WEB_PUBLIC_ORIGIN=https://ui.utama.naufix.space
WEB_COOKIE_SECRET=<hasil openssl rand -hex 32>
WEB_COOKIE_SECURE=true
STORAGE_TRASH_RETENTION_DAYS=30
```

`STORAGE_TRASH_RETENTION_DAYS` menentukan kapan item Trash dihapus permanen
dari channel. Sebelum tenggat, delete dari web/bot hanya memindahkan item ke
Recycle Bin.

Pada `.env` utama di VPS gateway, simpan konfigurasi release UI. PAT GitHub
tidak boleh dimasukkan ke `.env.backend` karena backend tidak membutuhkannya.

```env
WEB_DEPLOY_ROOT=/www/wwwroot/ui.utama.naufix.space
WEB_RELEASE_CACHE_ROOT=/www/wwwroot/.tme3bot-ui-releases
WEB_RELEASE_TAG=web-latest
WEB_RELEASE_KEEP=5

# Hanya untuk repository private; token cukup memiliki Contents: Read.
WEB_RELEASE_TOKEN=
```

Atur Nginx melalui aaPanel. Script deploy hanya menyalin bundle ke
`WEB_DEPLOY_ROOT`; script tidak mengubah atau me-reload Nginx. Referensi
konfigurasi tersedia di `deploy/nginx/tme3bot-ui.conf`.

Pada `.env` semua node, image harus mengarah ke registry yang sama:

```env
GATEWAY_IMAGE_NAME=ghcr.io/<owner>/tme3bot-gateway
WORKER_IMAGE_NAME=ghcr.io/<owner>/tme3bot-worker
IMAGE_TAG=latest
TME3BOT_BASE_IMAGE=tme3bot-base:py310-tdl0203
```

`run.py` mengganti `latest` dengan 12 karakter Git SHA saat publish/deploy,
sehingga target mengambil image immutable dari commit yang sama.

## A. Langkah di komputer lokal

Jalankan dari root project sebelum push:

```bash
git status --short
python -m compileall -q tme3bot utility bot.py run.py
python -m unittest discover -s tests -v
cd web
pnpm install --frozen-lockfile
pnpm check
pnpm test
pnpm build
cd ..
git diff --check
graphify update .
```

Pastikan static build terbentuk:

```bash
python -c "from pathlib import Path; assert all((Path('web/build') / name).is_file() for name in ('index.html', '200.html', 'build-info.json'))"
```

Commit dan push:

```bash
git add .
git commit -m "add structured job progress telemetry"
git push origin main
git rev-parse --short=12 HEAD
```

Catat SHA yang dicetak. SHA tersebut harus sama di builder, gateway, seluruh
worker, image registry, dan `build-info.json`.

GitHub Actions `Publish static web` akan membuat/update release `web-latest`.
Tunggu workflow selesai sebelum langkah deploy web.

## B. Langkah di VPS builder besar

Langkah ini diperlukan karena perubahan menyentuh backend dan worker. Base
Go/TDL tidak berubah, jadi jangan menjalankan `build-base`.

```bash
cd /www/wwwroot/downloads/bot
git switch main
git pull --ff-only origin main
git rev-parse --short=12 HEAD
docker image inspect tme3bot-base:py310-tdl0203 >/dev/null
```

Login GHCR bila image private. Jangan menambahkan token sebagai argumen setelah
`ghcr.io`.

```bash
export GHCR_USERNAME=<username-github>
read -rsp "GHCR token: " GHCR_TOKEN
echo
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io \
  --username "$GHCR_USERNAME" \
  --password-stdin
unset GHCR_TOKEN
```

Build layer aplikasi dan push image gateway serta worker:

```bash
python3 run.py publish gateway
```

Perintah ini tidak menjalankan service di builder. Karena compose gateway
memuat target gateway dan worker-local, dua image berikut dipublish dengan Git
SHA yang sama:

```text
ghcr.io/<owner>/tme3bot-gateway:<git-sha-12>
ghcr.io/<owner>/tme3bot-worker:<git-sha-12>
```

Tidak perlu menjalankan `publish worker` lagi untuk release yang sama.

## C. Langkah di VPS gateway

Sebelum update, buat backup terenkripsi:

```bash
cd /www/wwwroot/downloads/bot
python3 run.py backup now
python3 run.py backup status
```

Ambil source yang sama dengan builder:

```bash
git switch main
git pull --ff-only origin main
git rev-parse --short=12 HEAD
```

Jika registry private dan node belum login, lakukan login GHCR seperti pada VPS
builder. Kemudian deploy backend, Telegram frontend, dan worker lokal:

```bash
python3 run.py deploy gateway --pull
```

Periksa container dan health backend:

```bash
docker compose -f docker-compose.gateway.yml ps
curl -fsS http://127.0.0.1:8080/healthz
docker compose -f docker-compose.gateway.yml logs --tail=100 backend
docker compose -f docker-compose.gateway.yml logs --tail=100 worker-local
```

Jangan deploy web dahulu. Selesaikan semua worker remote pada bagian D agar UI
tidak menampilkan kemampuan telemetry baru sementara worker masih memakai
protokol lama.

## D. Langkah di setiap VPS worker remote

Ulangi langkah berikut pada `remote-1`, `remote-2`, dan worker lain yang
terdaftar:

```bash
cd /www/wwwroot/downloads/bot
git switch main
git pull --ff-only origin main
git rev-parse --short=12 HEAD
python3 run.py deploy worker --pull
```

`run.py` membaca `PROFILE_ROOT` dari `.env.worker` sebelum Docker Compose
melakukan interpolasi volume. Jangan menjalankan compose worker secara langsung
jika environment tersebut belum diekspor.

Periksa worker:

```bash
docker compose -f docker-compose.worker.yml ps
docker compose -f docker-compose.worker.yml logs --tail=100 worker
```

Pastikan tidak ada error autentikasi internal, `401`, atau worker callback yang
ditolak. Ulangi sampai seluruh worker remote menggunakan SHA yang sama.

## E. Deploy web static di VPS gateway

Pastikan workflow GitHub `Publish static web` untuk commit tersebut sudah hijau.
Lalu jalankan:

```bash
cd /www/wwwroot/downloads/bot
python3 run.py deploy web
```

Perintah ini:

- mengunduh release `web-latest`;
- memverifikasi SHA-256;
- mengekstrak release ke cache;
- menyalin file yang dikelola ke
  `/www/wwwroot/ui.utama.naufix.space`;
- mempertahankan file aaPanel yang bukan milik bundle;
- tidak menjalankan Node, pnpm, Docker web, atau reload Nginx.

Periksa revision UI:

```bash
curl -fsS https://ui.utama.naufix.space/build-info.json
curl -I https://ui.utama.naufix.space/
```

`build-info.json` harus memuat Git revision release terbaru. HTML dan
`build-info.json` harus `no-cache`; hanya `/_app/immutable/*` yang boleh memakai
cache immutable.

## F. Smoke test telemetry progress

1. Login ke dashboard lalu buka Activity.
2. Jalankan upload Storage dari folder kecil dengan beberapa file.
3. Pastikan kartu menampilkan jumlah file, file aktif, progress bar, speed, ETA,
   berhasil, dan gagal.
4. Saat TDL selesai tetapi message ID belum tersedia, fase harus menjadi
   `Menunggu Telegram`, bukan gagal atau kembali menjadi upload.
5. Jalankan Utility Compress atau Extract dan pastikan progress 7z bergerak.
6. Buka Detail untuk milestone dan Log untuk snapshot terminal.
7. Pastikan job terminal berpindah ke history dan report akhirnya tetap dapat
   dibuka.

Pantau server saat smoke test:

```bash
docker compose -f docker-compose.gateway.yml logs -f backend worker-local
```

Untuk worker remote:

```bash
docker compose -f docker-compose.worker.yml logs -f worker
```

Telemetry per detik tidak disimpan sebagai baris `job_events`; hanya snapshot
terbaru di `jobs.progress` dan milestone penting yang persisten. Ini adalah
perilaku yang diharapkan.

## Update berikutnya

Gunakan matriks berikut:

| File yang berubah | Builder | Gateway | Worker remote | Web |
|---|---:|---:|---:|---:|
| Hanya `web/` | Tidak | Tidak | Tidak | Deploy |
| Backend/API saja | Publish gateway | Deploy gateway | Tidak | Jika kontrak UI berubah |
| Worker/TDL/utility | Publish gateway | Deploy gateway | Semua worker | Jika UI progress berubah |
| Backend + worker + web | Publish gateway | Deploy gateway | Semua worker | Deploy terakhir |
| Base/Go/TDL binary | `build-base` dahulu | Deploy gateway | Semua worker | Sesuai perubahan |

### Hanya web

```bash
git pull --ff-only origin main
python3 run.py deploy web
```

### Backend atau worker

Di builder:

```bash
git pull --ff-only origin main
python3 run.py publish gateway
```

Di gateway:

```bash
git pull --ff-only origin main
python3 run.py deploy gateway --pull
```

Di setiap worker yang terdampak:

```bash
git pull --ff-only origin main
python3 run.py deploy worker --pull
```

## Rollback

### Rollback web saja

```bash
python3 run.py deploy web --rollback
```

### Rollback backend dan worker

Pilih commit stabil yang image-nya masih tersedia:

```bash
git log --oneline -10
git switch --detach <commit-stabil>
git rev-parse --short=12 HEAD
```

Rollback dengan urutan backend/gateway, seluruh worker remote, lalu UI:

```bash
python3 run.py deploy gateway --pull
```

Pada setiap worker:

```bash
python3 run.py deploy worker --pull
```

Untuk kembali ke branch utama:

```bash
git switch main
git pull --ff-only origin main
```

Kolom `progress_sequence` bersifat additive dan kompatibel, jadi rollback tidak
memerlukan penghapusan atau downgrade database.

## Batas keamanan

- Browser hanya memanggil `/api/v1` pada domain UI yang sama.
- Access/refresh token berada di cookie HttpOnly Secure.
- Secret tidak boleh masuk localStorage, JavaScript, `build-info.json`, log,
  caption, atau payload telemetry.
- Semua mutation browser harus membawa CSRF dan berasal dari
  `WEB_PUBLIC_ORIGIN`.
- `WEB_RELEASE_TOKEN` hanya untuk repository private dan tidak boleh masuk Git.
- Password Utility/Backup tidak boleh muncul dalam marker 7z, event progress,
  report, atau terminal log.
