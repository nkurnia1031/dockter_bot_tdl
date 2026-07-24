# TME3Bot Deployment Runbook

Versi: 1.1  
Tanggal: 2026-07-24

Dokumen ini adalah instruksi operasional utama setiap kali source code berubah.
Jika arsitektur, nama service, env, atau proses build berubah, file ini wajib
diperbarui bersamaan dengan perubahan code.

## Catatan update 1.1

Update ini merapikan struktur source dan menghapus runtime legacy
`APP_ROLE=gateway|local`. Komponen presentasi Telegram sekarang berada di
`tme3bot/frontend/telegram/`; backend dan worker tetap memakai kontrak API JSON
yang sama.

- Base image tidak perlu dibangun ulang karena `requirements.txt`,
  `Dockerfile.base`, Go helper, dan binary TDL tidak berubah.
- `.env.gateway.example` sudah dihapus. Gunakan `.env.backend.example`,
  `.env.telegram.example`, dan `.env.worker.local.example` pada VPS gateway.
- Sebelum memindahkan file, jalankan verifikasi lokal pada bagian B1 lalu buat
  ulang `output.zip`.
- Di VPS besar, extract `output.zip`, jalankan `python3 run.py migrate`, lalu
  distribusikan `migrate.zip` baru ke gateway dan seluruh worker.
- Data `/data`, SQLite, JSON export, sesi `.tdl`, dan file `.env` lama tidak
  perlu dipindahkan atau dihapus.

## Peta mesin

```text
Project lokal
    │ output.zip (source + base image jika tersedia)
    ▼
VPS besar / builder
    │ python3 run.py migrate
    │ migrate.zip (image aplikasi)
    ├──────────────► VPS gateway
    └──────────────► VPS worker remote
```

Komponen:

- `backend`: API FastAPI, SQLite, state, scheduler, worker routing.
- `telegram`: UI Telegram. Menggunakan image gateway yang sama dengan backend.
- `worker-local`: worker TDL lokal, hanya dijalankan jika gateway juga menjadi
  worker.
- `worker`: worker TDL remote pada VPS worker.
- `tme3bot-base`: image dasar immutable berisi Go helper, TDL, Python
  dependency, dan paket sistem.

## Aturan dasar

- Jangan menjalankan `docker build` di VPS kecil.
- Jangan menjalankan Go build pada update biasa.
- Jangan menghapus volume `/data`, state, database, atau sesi `.tdl` saat update.
- File `.env`, `.env.backend`, `.env.telegram`, `.env.worker`, dan secret tidak
  dipindahkan melalui archive deployment.
- Image dasar harus sama arsitekturnya dengan mesin target. Default project ini
  `linux/amd64`.
- `migrate.zip` berisi image aplikasi siap load. `output.zip` berisi source
  untuk builder dan base image jika base sudah diekstrak ke project.

## A. Kondisi pertama: membuat base image di VPS besar

Lakukan hanya sekali, atau ketika runbook memberi peringatan base image usang.

### A1. Kirim source terbaru ke VPS besar

Dari project lokal, buat archive source terlebih dahulu:

```bash
python3 build.py -o output.zip
```

Jika `images/tme3bot-base.tar` belum ada, archive ini belum membawa base image.
Kirim ke VPS besar:

```bash
scp output.zip USER_BUILDER@HOST_BUILDER:/opt/tme3bot/
```

### A2. Siapkan source di VPS besar

```bash
cd /opt/tme3bot
unzip -o output.zip
cp .env.example .env
```

Isi `.env` minimal:

```env
TME3BOT_BASE_IMAGE=tme3bot-base:py310-tdl0203
BASE_PLATFORM=linux/amd64
```

Sesuaikan `BASE_PLATFORM` jika semua target memakai ARM64.

### A3. Build base image satu kali

```bash
python3 run.py build-base
```

Output:

```text
base-migrate.zip
```

Archive ini berisi:

- `images/tme3bot-base.tar`
- `base-image-manifest.json`
- `Dockerfile.base`
- source project

Download `base-migrate.zip` kembali ke project lokal untuk disimpan sebagai
artefak base resmi.

## B. Setelah base image selesai dibuat: update code biasa

### B1. Di project lokal

Setiap ada perubahan code:

```bash
python -m compileall -q tme3bot utility bot.py run.py build.py
python -m unittest discover -s tests -v
git diff --check
```

Jika project memakai graphify:

```bash
graphify update .
```

Jika semua lulus, buat archive:

```bash
python3 build.py -o output.zip
```

Jika base image sudah diekstrak di project, `output.zip` otomatis memasukkan:

```text
images/tme3bot-base.tar
base-image-manifest.json
```

### B2. Ekstrak base image dengan aman di project lokal

Saat menerima `base-migrate.zip` dari VPS besar, jangan menimpa seluruh source
lokal. Dari root project lokal jalankan:

```bash
mkdir -p images
unzip -o base-migrate.zip \
  images/tme3bot-base.tar \
  base-image-manifest.json
```

Setelah itu `python3 build.py -o output.zip` akan menyertakan base image.

### B3. Kirim source ke VPS besar

```bash
scp output.zip USER_BUILDER@HOST_BUILDER:/opt/tme3bot/
```

Di VPS besar:

```bash
cd /opt/tme3bot
unzip -o output.zip
docker load -i images/tme3bot-base.tar
python3 run.py migrate
```

Outputnya:

```text
migrate.zip
```

`migrate.zip` berisi image aplikasi terbaru untuk gateway dan worker.

### B4. Kirim migration archive ke mesin target

```bash
scp migrate.zip USER_GATEWAY@HOST_GATEWAY:/opt/tme3bot/
scp migrate.zip USER_WORKER@HOST_WORKER:/opt/tme3bot/
```

Jika gateway dan worker berada pada mesin yang sama, cukup kirim sekali.

## C. Instal atau update VPS gateway

### C1. Extract dan load image

```bash
cd /opt/tme3bot
unzip -o migrate.zip
docker load -i images/tme3bot-images.tar
```

Jika gateway perlu melakukan rebuild lokal di masa depan, load juga base image:

```bash
test -f images/tme3bot-base.tar && \
  docker load -i images/tme3bot-base.tar
```

### C2. Siapkan env gateway pada instalasi pertama

```bash
cp .env.example .env
cp .env.backend.example .env.backend
cp .env.telegram.example .env.telegram
cp .env.worker.local.example .env.worker.local
```

Isi secret dan konfigurasi. File env yang sudah berjalan jangan ditimpa saat
update berikutnya.

Pastikan:

- `BOT_TOKEN` backend dan Telegram sama.
- `FRONTEND_SERVICE_TOKEN` backend dan Telegram sama.
- `BACKEND_INTERNAL_TOKEN` sama dengan seluruh worker.
- `MANAGEMENT_API_TOKEN` tersedia pada `.env.backend`.
- `AUTH_JWT_SECRET` minimal 32 karakter.
- `GATEWAY_DATA_ROOT` menunjuk volume data gateway.
- `LOCAL_WORKER_DATA_ROOT` menunjuk volume worker-local jika service itu aktif.

### C3. Gateway-only

Jika mesin ini hanya menjalankan backend dan Telegram:

```bash
docker compose --env-file .env \
  -f docker-compose.gateway.yml \
  up -d --no-build backend telegram
```

### C4. Gateway plus worker-local

Jika mesin ini juga menjadi worker utama:

```bash
docker compose --env-file .env \
  -f docker-compose.gateway.yml \
  up -d --no-build backend telegram worker-local
```

Periksa:

```bash
docker compose --env-file .env \
  -f docker-compose.gateway.yml ps

docker compose --env-file .env \
  -f docker-compose.gateway.yml logs -f backend telegram
```

Pada update biasa gunakan `--no-build`. Image baru sudah berasal dari
`migrate.zip`.

## D. Instal atau update VPS worker remote

### D1. Extract dan load image

```bash
cd /opt/tme3bot
unzip -o migrate.zip
docker load -i images/tme3bot-images.tar
```

### D2. Siapkan env pada instalasi pertama

```bash
cp .env.worker.example .env.worker
```

Isi minimal:

```env
PROFILE_ROOT=/srv/tme3bot/worker-remote-1
BACKEND_API_URL=https://backend.example.com
BACKEND_INTERNAL_TOKEN=SECRET_YANG_SAMA_DENGAN_BACKEND
WORKER_API_TOKEN=SECRET_WORKER_UNIK
WORKER_PORT=5800
BACKUP_NODE_NAME=remote-1
```

Jangan mengubah `PROFILE_DATA_ROOT=/data`; itu adalah path di dalam container.

### D3. Jalankan worker

```bash
docker compose --env-file .env.worker \
  -f docker-compose.worker.yml \
  up -d --no-build worker
```

Periksa:

```bash
docker compose --env-file .env.worker \
  -f docker-compose.worker.yml ps

docker compose --env-file .env.worker \
  -f docker-compose.worker.yml logs -f worker
```

Port worker sebaiknya tetap bind ke localhost dan diproxy melalui domain HTTPS.
Contoh reverse proxy:

```text
https://worker-1.example.com -> 127.0.0.1:5800
```

### D4. Daftarkan worker dari gateway

Jalankan pada project gateway yang memiliki `.env` dan `.env.backend`:

```bash
python3 run.py worker add \
  remote-1 \
  https://worker-1.example.com \
  SECRET_WORKER_UNIK

python3 run.py worker list
```

Kemudian pilih worker tersebut melalui `/worker` di Telegram. Perubahan route
profile tidak dilakukan ketika profile masih memiliki job aktif.

## E. Menentukan apakah base perlu dibuat ulang

Perubahan biasa yang tidak memerlukan base rebuild:

- File Python aplikasi.
- Handler Telegram.
- API route/use case.
- Template, keyboard, formatter, dan dokumentasi.
- Logic storage, backup, source, atau job yang tidak mengubah dependency dasar.

Perubahan yang memerlukan base rebuild di VPS besar:

- `requirements.txt` berubah.
- `Dockerfile.base` berubah.
- `leave-helper/main.go` berubah.
- `leave-helper/go.mod` berubah.
- Versi fallback TDL berubah.
- Binary TDL host berubah.
- Target architecture berubah.

Deteksi otomatis:

```bash
python3 build.py -o output.zip
```

Jika fingerprint base tidak cocok, script memberi warning. Build aplikasi akan
ditolak oleh:

```bash
python3 run.py migrate
```

Tindakan yang benar:

1. Kirim source terbaru ke VPS besar.
2. Jalankan `python3 run.py build-base` di VPS besar.
3. Download `base-migrate.zip` terbaru.
4. Extract hanya base image dan manifest ke project lokal.
5. Jalankan test lokal.
6. Jalankan `python3 build.py -o output.zip`.
7. Kirim `output.zip` ke VPS besar.
8. Jalankan `python3 run.py migrate`.

## F. Rollback

Simpan setiap `migrate.zip` dengan nama versi, misalnya:

```text
migrate-2026-07-24-1.zip
```

Untuk rollback:

```bash
unzip -o migrate-2026-07-24-1.zip
docker load -i images/tme3bot-images.tar
docker compose --env-file .env \
  -f docker-compose.gateway.yml \
  up -d --no-build backend telegram worker-local
```

Jangan menghapus volume data ketika rollback. Database, state, export JSON,
dan sesi `.tdl` tetap dipertahankan.

## G. Pemeriksaan akhir setelah update

Gateway:

```bash
docker compose --env-file .env -f docker-compose.gateway.yml ps
docker compose --env-file .env -f docker-compose.gateway.yml logs --tail=100 backend
```

Worker remote:

```bash
docker compose --env-file .env.worker -f docker-compose.worker.yml ps
docker compose --env-file .env.worker -f docker-compose.worker.yml logs --tail=100 worker
```

Telegram:

```text
/check_profil
/worker
/storage
/backup
```

Pastikan backend sehat, worker terlihat di `/worker`, dan satu job kecil dapat
berjalan sebelum migrasi data atau menjalankan batch besar.
