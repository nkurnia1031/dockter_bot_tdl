# tme3bot

Bot Telegram dan control plane JSON untuk export/download TDL, utility,
storage channel, worker multi-VPS, dan backup terenkripsi.

## Arsitektur

```text
Telegram frontend ── JWT/JSON ──► Backend FastAPI ── JSON job ──► Worker
       │                              │                            │
       │                              ├─ /data + SQLite            ├─ TDL
       │                              ├─ source/state              ├─ utility
       │                              ├─ routing worker            └─ event JSON
       │                              └─ storage/backup
       └─ keyboard, prompt, panel
```

- `APP_ROLE=backend` menjalankan FastAPI, repository, scheduler, dan routing.
- `APP_ROLE=telegram` hanya menjalankan polling serta presentasi Telegram.
- `APP_ROLE=worker` menjalankan TDL/utility dan mengirim event job ke backend.
- Role lama `local` dan `gateway` tidak digunakan lagi.
- Frontend tidak membawa `chat_id`, `message_id`, atau state panel ke worker.
- Public API berada di `/api/v1`; kontrak OpenAPI tersedia di
  `/openapi.json`.
- Internal API worker/frontend berada di `/internal/v1` dan tidak muncul di
  OpenAPI publik.

Struktur source aktif:

```text
tme3bot/
├── api/                  FastAPI public dan internal
├── application/          use case, ports, dan control plane
├── domain/               entity serta state machine
├── frontend/
│   └── telegram/         polling, panel, keyboard, dan presenter
├── infrastructure/       SQLite, auth, dan HTTP adapter
├── worker/               executor TDL/utility tanpa dependency Telegram
├── composition.py        composition root per APP_ROLE
└── profiles.py           runtime profile dan kompatibilitas data lama
```

## Setup VPS utama

```bash
cp .env.example .env
cp .env.backend.example .env.backend
cp .env.telegram.example .env.telegram
cp .env.worker.local.example .env.worker.local
```

Buat empat secret yang berbeda:

```bash
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 48
```

Isi:

- `FRONTEND_SERVICE_TOKEN` yang sama pada backend dan Telegram.
- `BACKEND_INTERNAL_TOKEN` yang sama pada backend dan semua worker.
- `MANAGEMENT_API_TOKEN` hanya pada backend.
- `AUTH_JWT_SECRET` hanya pada backend.
- `WORKER_API_TOKEN` worker-local harus sama dengan token `local` pada
  `WORKER_API_TOKENS`.
- `BOT_TOKEN` yang sama pada backend dan Telegram. Backend menggunakannya
  sebagai adapter storage/backup; Telegram menggunakannya untuk UI polling.
- `BOT_USERNAME` tanpa `@` pada backend.

Data lama tetap dapat dipakai dengan menunjuk `GATEWAY_DATA_ROOT` dan
`LOCAL_WORKER_DATA_ROOT` ke direktori lama.

Jalankan:

```bash
python3 run.py up
python3 run.py status
python3 run.py logs
```

Compose membangun image gateway satu kali. Container `telegram` menggunakan
image yang sama tanpa build kedua.

## Build Docker melalui GitHub Actions

Release Docker dibangun oleh workflow
`.github/workflows/docker-images.yml`. Workflow tersebut membuat image dasar
Go/TDL/Python terlebih dahulu, kemudian membangun image gateway dan worker dari
base image immutable, lalu mem-publish semuanya ke GHCR. VPS tidak perlu lagi
menjalankan `docker build` atau mengompilasi Go.

Push ke `main` akan menghasilkan tag image berdasarkan 12 karakter SHA commit:

```text
ghcr.io/<owner>/tme3bot-base:py310-tdl0203-<sha12>
ghcr.io/<owner>/tme3bot-gateway:<sha12>
ghcr.io/<owner>/tme3bot-worker:<sha12>
```

Workflow juga memperbarui tag `latest` untuk penggunaan sederhana. Untuk
produksi, gunakan tag SHA agar gateway dan worker tetap immutable.

Pada VPS, isi `.env` dengan nama package GHCR dan tag commit yang sama:

```env
GATEWAY_IMAGE_NAME=ghcr.io/<owner>/tme3bot-gateway
WORKER_IMAGE_NAME=ghcr.io/<owner>/tme3bot-worker
IMAGE_TAG=<sha12>
```

Setelah workflow berhasil dan VPS sudah login ke GHCR, deploy hanya perlu
pull lalu menjalankan container:

```bash
docker compose -f docker-compose.gateway.yml pull
docker compose -f docker-compose.gateway.yml up -d --remove-orphans
```

`python3 run.py deploy gateway --pull` dan `python3 run.py deploy worker --pull`
tetap dapat dipakai sebagai wrapper. Build lokal dan `base-migrate.zip` masih
tersedia sebagai fallback untuk recovery atau deployment offline.

Jika arsitektur target bukan AMD64, workflow perlu ditambah target platform
tersebut dan image multi-arsitektur harus dibangun sebelum VPS ARM melakukan
pull.

Setelah `base-migrate.zip` diekstrak di project, `python3 build.py` otomatis
memasukkan `images/tme3bot-base.tar` dan manifest base ke `output.zip`. Jika
fingerprint dependency/base berubah, script akan memberi peringatan dan
`python3 run.py migrate` akan berhenti agar base baru dibuat di VPS besar dulu.

## Worker remote

Pada VPS worker:

```bash
cp .env.worker.example .env.worker
docker compose --env-file .env.worker -f docker-compose.worker.yml up -d --build
```

`BACKEND_API_URL` harus menunjuk domain backend HTTPS dan
`BACKEND_INTERNAL_TOKEN` harus sama dengan backend. Worker API sendiri
disarankan hanya tersedia melalui reverse proxy TLS atau jaringan privat.
`PROFILE_ROOT` pada `.env.worker` adalah lokasi data persistent di host worker.

Daftarkan worker dari VPS utama:

```bash
python3 run.py worker list
python3 run.py worker add remote-1 https://worker-1.example.com
python3 run.py worker remove remote-1
```

Perintah tersebut memanggil management JSON API. Penambahan worker tidak
memerlukan rebuild atau restart backend.

## Login web melalui bot

Website kelak menggunakan alur berikut:

1. `POST /api/v1/auth/telegram/challenges`.
2. Buka `verification_uri` yang dikembalikan backend.
3. User menekan Start pada bot.
4. Website melakukan polling endpoint token dengan `challenge_id` dan
   `poll_token`.
5. Backend mengembalikan access JWT 15 menit dan refresh token 30 hari.

Challenge berlaku lima menit dan hanya dapat digunakan sekali. Login web baru
mencabut sesi web lama user yang sama. Refresh token disimpan dalam bentuk hash
dan dirotasi setiap digunakan.

## Job dan progress

Semua operasi panjang menghasilkan resource job:

```text
queued → dispatched → running → succeeded | failed | cancelled
```

Frontend membaca:

```text
GET /api/v1/jobs
GET /api/v1/jobs/<job_id>
GET /api/v1/jobs/<job_id>/events?after_sequence=0
```

Worker menerbitkan event idempotent berdasarkan `job_id + sequence`. Telegram
frontend melakukan polling dua detik sekali selama panel masih aktif. Histori
job tetap tersedia setelah restart backend.

## Storage dan backup

Channel menggunakan satu nilai compact:

```env
STORAGE_CHANNEL=1588718424
BACKUP_CHANNEL=9876543210
```

Bot backend mencari nama channel melalui Bot API. Storage search/rename/edit,
delivery, dan backup dapat dipanggil melalui API maupun menu bot. Rename nama
tampilan tersedia untuk semua user authorized; folder, keyword, dan delete
tetap owner-only.

Backup gateway dan worker dibuat sebagai 7z encrypted menggunakan password
default Utility. Jalankan manual:

```bash
python3 run.py backup now
python3 run.py backup status
python3 run.py backup list
```

Quick Mode mengirim thumbnail sebagai foto ke channel Storage dan hanya file
arsip hasil compress ke Google Drive melalui rclone. Worker membaca konfigurasi
rclone dari `/workspace/.config/rclone.conf`; tujuan default
`googledrive:backup` dapat diubah pada Pengaturan. Upload Storage biasa juga
memiliki checklist untuk menyalin file ke tujuan rclone tersebut.

## Verifikasi

Runbook deployment lengkap dan diperbarui setiap perubahan workflow tersedia di
[DEPLOYMENT_RUNBOOK.md](DEPLOYMENT_RUNBOOK.md).

```bash
python -m compileall -q tme3bot utility bot.py run.py
python -m unittest discover -s tests -v
git diff --check
graphify update .
```
