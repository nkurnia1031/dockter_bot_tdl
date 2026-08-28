# TME3Bot Deployment Runbook

Versi: 3.8 - Per-feature target context dan Download manager global

Dokumen ini adalah urutan update resmi. Gateway menjalankan tiga container:
`backend`, `telegram`, dan `worker-local`. Dashboard adalah file static dan
tidak membutuhkan Node.js atau container web di VPS target.

## Topologi deployment

| Node | Service | Cara update |
|---|---|---|
| Mesin lokal dengan Docker | Build image gateway dan worker | `python3 run.py publish gateway` |
| VPS gateway | `backend`, `telegram`, `worker-local` | `python3 run.py deploy gateway --pull` |
| Setiap VPS worker remote | `worker` | `python3 run.py deploy worker --pull` |
| aaPanel UI | Svelte static di document root | `python3 run.py deploy web` |

Untuk update Download manager ini, urutan wajib adalah:

1. Backend dan worker-local di VPS gateway.
2. Seluruh worker remote.
3. Web static.

Backend harus diperbarui lebih dahulu karena backend menambahkan kolom inventory
artifact (`available`, inventory ID, waktu terakhir terlihat, dan waktu hilang),
filter worker pada job, serta proxy snapshot log aktif. Migrasi SQLite berjalan
otomatis dan idempotent saat backend mulai. Tidak ada perintah migrasi database
manual. Data `/data`, katalog, state, dan sesi TDL tidak dihapus.

Worker release ini mengirim inventory generation, milestone JSON download,
telemetry JSON N/N dan file N/N, speed/ETA, serta snapshot output TDL aktif.
Seluruh worker harus diperbarui sebelum web static agar kontrak telemetry sama.

Download manager secara default menampilkan artifact dan job lintas profile serta
worker. UI mengosongkan selection saat filter berubah dan memuat ulang katalog
tanpa memulai scan worker baru. Reconcile global berjalan saat halaman dibuka di
background atau saat tombol reconcile ditekan. Artifact yang tidak lagi ada di
worker dipertahankan untuk audit di History dengan status `File tidak tersedia`,
tetapi tidak dapat dijalankan. `Mulai semua` memakai endpoint batch dan
mengelompokkan artifact berdasarkan origin tersimpan.

Reconcile inventory dikirim worker dalam batch (maksimal 100 artifact per event),
lalu gateway melakukan bulk upsert dalam satu transaksi SQLite. Katalog lama
ditampilkan lebih dahulu ketika halaman dibuka sehingga pengguna tidak menunggu
seluruh scan selesai. SQLite tetap menjadi satu sumber kebenaran; database
terpisah tidak diperlukan untuk optimasi ini. Worker juga menyimpan fingerprint
file JSON selama proses hidupnya sehingga JSON yang tidak berubah tidak diparse
ulang pada reconcile berikutnya.

Activity tetap menampilkan job lintas-worker untuk profile aktif. Mengganti
worker hanya mengubah route job berikutnya; job lama tetap berjalan pada worker
asal dan tidak dipindahkan.

### Recovery download `CHAT_ID_INVALID`

Cache peer Telegram berada pada sesi TDL download masing-masing worker. Jika
download mengembalikan `CHAT_ID_INVALID`, worker tidak langsung memindahkan JSON
ke `failed`. Worker membuat URL warm-up dari `chat_ref` dan ID media pertama,
menjalankan warm-up pada sesi download worker aktif, lalu mencoba download ulang
satu kali. Jika warm-up atau retry tetap gagal, barulah artifact masuk ke
`failed` dengan error yang relevan.

Perubahan ini berada pada image worker Python. Deploy `worker-local` melalui
deploy gateway dan deploy seluruh worker remote yang dapat menjalankan download.
Base Go/TDL tidak perlu dibangun ulang.

## Workspace export Telegram

`/start`, `/menu`, dan `/panel` sekarang membuka `Export fokus` sebagai panel
awal. Panel ini menggabungkan pemilihan source, label opsional, Start ID, dan
pengiriman export dalam satu pesan Telegram. Source tersimpan dipilih melalui
tombol inline; source baru dapat dimasukkan sebagai username tanpa `@` atau
numeric chat ID. Username dengan dan tanpa `@` dianggap source yang sama.

`Overwrite Start ID` default OFF dan memakai `Last ID backend + 1`. Saat switch
ON, user wajib mengisi Start ID angka minimal 1 dan frontend mengirim
`use_url_message_id=true` agar override dipakai untuk satu job tersebut. Memilih
source lain mematikan overwrite. Last ID backend tetap monotonic dan tidak
diturunkan oleh export ulang dari ID lama. Perilaku yang sama berlaku pada form
Export Web. Label custom otomatis masuk daftar label berikutnya.

Tombol `Workspace full fitur` membuka menu utility, storage, download, backup,
worker, settings, dan source management lama. Pergantian workspace hanya
mengubah tampilan bot; profile, worker route, state source, dan job aktif tidak
berubah. Setelah restart frontend Telegram, mode awal kembali ke `Export fokus`.

Saat export dikirim, callback hanya di-acknowledge tanpa popup. Status antrean,
progress, dan report terminal ditulis ke panel export utama yang sama. Tidak ada
popup atau keyboard job khusus. Jika user memilih
source lagi, detail job pada panel dihapus dan form kembali ke kondisi awal;
job backend yang sudah berjalan tetap dilanjutkan.

Selain panel utama, setiap export mengirim satu pesan status tanpa keyboard.
Pesan yang sama diedit untuk antrean dan progress, menampilkan report sukses,
gagal, atau dibatalkan selama 3 detik, lalu otomatis dihapus. Polling status
tetap berjalan walaupun panel utama berpindah source; hanya pembaruan panel yang
dihentikan ketika view token sudah tidak aktif. Pesan status tidak dibuat ulang
pada setiap polling atau saat job selesai.

Export yang selesai tanpa media tidak didaftarkan sebagai artifact download.
Worker membaca statistik JSON terlebih dahulu, menghapus file JSON tersebut
secara otomatis, dan report job menampilkan `JSON dihapus otomatis (tidak ada
media)`. Jika penghapusan gagal karena permission atau filesystem, job tetap
menyimpan report cleanup error dan artifact tetap tidak dibuat sebagai item
download; perbaiki filesystem lalu biarkan inventory/maintenance berikutnya
membersihkan file yang tersisa.

Perubahan status Telegram ini hanya mengubah image gateway/frontend Telegram.
Tidak memerlukan rebuild base Go/TDL atau update worker remote.

Jika chat Telegram dibersihkan, `/panel` memaksa pembuatan panel baru. `/start`,
`/menu`, unknown command, serta teks `menu`, `panel`, atau `start` juga menjalankan
recovery. Bot menampilkan `Memuat panelâ€¦` sebelum meminta data backend; command
user baru dihapus setelah panel berhasil dibuat.

Deep link Storage adalah capability link bertanda tangan. Semua user Telegram
yang memiliki link valid dapat menerima file walaupun tidak mempunyai
`identity.json`. Akses ini hanya mengizinkan delivery file aktif; user tersebut
tidak memperoleh akses katalog, profile, metadata, atau menu admin. Item dalam
Trash/deleted dan token yang rusak selalu ditolak.

UX utama pemanggilan file memakai kode capability, bukan perpindahan lewat deep
link. Web Storage menyediakan tombol `Salin kode file`; pengguna memilih
`Panggil file dengan kode` pada menu Storage atau menjalankan `/file`, lalu
menempel kode tersebut. `/file` juga dapat dipakai user tanpa identity. Deep link
`/start storage_...` tetap tersedia hanya untuk kompatibilitas link lama.

Rollout perubahan ini: publish image gateway, deploy gateway (backend dan
Telegram), lalu deploy web static. Worker lokal/remote dan base Go/TDL tidak
perlu dibangun ulang.

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

### Jika base image terhapus setelah cleanup Docker

Build aplikasi tidak membuat ulang Go/TDL base image. Jika muncul error seperti
`failed to resolve source metadata for tme3bot-base:py310-tdl0203`, berarti base
image lokal sudah terhapus atau belum pernah di-load pada mesin tersebut.

Jalankan di VPS builder besar:

```bash
python3 run.py build-base
```

Pada Docker lama mungkin muncul peringatan:

```text
DEPRECATED: The legacy builder is deprecated
```

Peringatan tersebut tidak lagi menjadi blocker. `Dockerfile.base` memiliki
default `BUILDPLATFORM=linux/amd64`, dan `run.py build-base` juga mengirimkan
nilai platform secara eksplisit. Pastikan source sudah terbaru:

```bash
git pull --ff-only origin main
python3 run.py build-base
```

Jika Docker menyediakan Buildx, Anda boleh memasangnya untuk menghilangkan
peringatan legacy builder, tetapi tidak wajib untuk memperbaiki error platform
kosong seperti `OSAndVersion specifier component ...`.

Download `base-migrate.zip` ke project target, extract dari root project, lalu
load image sebelum build:

```bash
unzip -o base-migrate.zip
docker load -i images/tme3bot-base.tar
docker image inspect tme3bot-base:py310-tdl0203 >/dev/null
```

Jika project juga memerlukan source terbaru, jalankan `git pull --ff-only`
setelah extract dan pastikan `TME3BOT_BASE_IMAGE` di `.env` sama dengan nama
image yang di-load. Setelah itu ulangi `python3 run.py migrate` atau
`python3 run.py deploy gateway`.

Versi `run.py` terbaru memeriksa image ini sebelum Compose berjalan. Jika image
belum tersedia tetapi `images/tme3bot-base.tar` ada, script akan mencoba
`docker load` otomatis. Jika keduanya tidak ada, script berhenti dengan pesan
recovery dan tidak mencoba pull dari Docker Hub.

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

## Autentikasi GitHub dan GHCR

Ada tiga kebutuhan autentikasi yang berbeda. Jangan mencampurkan tokennya
secara sembarangan:

1. **GitHub repository** — untuk `git clone`, `git pull`, dan `git push`.
2. **GHCR** — untuk `docker push` dari builder dan `docker pull` dari VPS.
3. **GitHub Release UI** — untuk mengambil release static web private melalui
   `python3 run.py deploy web`.

### A. Login repository GitHub

Cara yang disarankan untuk VPS adalah SSH deploy key, sehingga PAT tidak perlu
disimpan di mesin:

```bash
ssh-keygen -t ed25519 -C "tme3bot-vps"
cat ~/.ssh/id_ed25519.pub
```

Tambahkan public key tersebut di GitHub pada **Settings → SSH and GPG keys**
atau sebagai deploy key repository, lalu verifikasi:

```bash
ssh -T git@github.com
git remote set-url origin git@github.com:<owner>/<repository>.git
git pull --ff-only origin main
```

Jika memakai HTTPS, gunakan username GitHub dan PAT sebagai password ketika
Git meminta kredensial. Jangan menaruh PAT langsung di URL remote. Pada mesin
yang mendukung GitHub CLI, alternatifnya:

```bash
gh auth login
gh auth setup-git
git pull --ff-only origin main
```

`run.py` tidak melakukan login GitHub Git otomatis. Git tetap menggunakan
credential helper atau SSH key yang sudah dikonfigurasi di host.

### B. Login GitHub Container Registry

PAT untuk builder wajib memiliki akses package write. VPS target cukup
memerlukan akses package read. Login melalui stdin agar token tidak muncul di
history atau daftar proses:

```bash
export GHCR_USERNAME=<username-github>
read -rsp "GHCR token: " GHCR_TOKEN
echo
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io \
  --username "$GHCR_USERNAME" \
  --password-stdin
unset GHCR_TOKEN
```

Atau isi sementara di `.env` yang hanya berada di host builder/target:

```env
GHCR_USERNAME=<username-github>
GHCR_TOKEN=<PAT-dengan-akses-package-yang-sesuai>
```

Jangan commit `.env`. `python3 run.py publish` akan membaca `GHCR_TOKEN` dan
menjalankan `docker login` melalui stdin. Token tidak ditampilkan ke log.

### C. Token GitHub Release untuk static web

Jika repository atau release UI bersifat private, isi token terpisah pada
`.env` gateway:

```env
WEB_RELEASE_TOKEN=<PAT-dengan-Contents-Read>
```

Token ini hanya dipakai oleh `python3 run.py deploy web` untuk mengambil
artefak release. Token tidak diperlukan oleh backend, Telegram frontend,
worker, atau `.env.backend`.

## B. Langkah build lokal

Build sekarang dapat dilakukan langsung dari workspace lokal. Docker Desktop
dengan Linux containers/WSL2 harus aktif. Base Go/TDL dibangun sekali di mesin
lokal; setelah itu update biasa hanya membangun layer aplikasi.

```bash
cd D:\Laragon\www\dockter_bot_tdl
git switch main
git pull --ff-only origin main
git rev-parse --short=12 HEAD
docker version
```

Jika image private, lakukan login GHCR mengikuti bagian **Autentikasi GitHub
dan GHCR** di atas. Jangan menambahkan token sebagai argumen setelah
`ghcr.io`.

Build layer aplikasi dan push image gateway serta worker dari mesin lokal:

```bash
python run.py publish gateway
```

Jika base image `tme3bot-base:py310-tdl0203` belum ada di Docker lokal, buat
sekali dari workspace ini:

```bash
python run.py publish gateway --build-base
```

`publish` mencoba login registry memakai `GHCR_TOKEN` atau token release yang
tersimpan di env, melalui stdin Docker sehingga token tidak masuk command/log.
PAT yang dipakai push wajib memiliki permission `write:packages`. Gunakan
`--no-login` jika Docker sudah login sebelumnya.

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

## D. Menambah worker remote baru

Worker remote membutuhkan dua konfigurasi yang berbeda:

- `.env.worker` berada di VPS remote dan mengatur sesi TDL, workspace, port,
  `WORKER_API_TOKEN`, serta URL backend.
- `workers.json` berada di data gateway dan menyimpan nama worker, URL publik,
  serta token yang dipakai gateway saat mengakses worker.

`WORKER_API_TOKEN` harus sama pada kedua sisi. Jangan menggunakan
`MANAGEMENT_API_TOKEN` atau `BACKEND_INTERNAL_TOKEN` sebagai token worker.
`BACKEND_INTERNAL_TOKEN` adalah secret callback antara worker dan backend.

### D.1 Siapkan VPS worker remote

Di VPS remote baru:

```bash
git clone <repository-url> /www/wwwroot/dockter_bot_tdl
cd /www/wwwroot/dockter_bot_tdl
git switch main
cp .env.worker.example .env.worker
cp .env.example .env
```

Edit `.env.worker`:

```env
APP_ROLE=worker
PROFILE_ROOT=/www/wwwroot/downloads/HasilConvert/bot/remote-1
BACKEND_API_URL=https://bot.utama.example.com
BACKEND_INTERNAL_TOKEN=<sama-dengan-.env.backend-gateway>
WORKER_API_TOKEN=<token-unik-worker-remote-1>
WORKER_PORT=5800
UTILITY_WORKSPACE_HOST=/www/wwwroot/downloads
```

Buat token worker unik, lalu simpan nilainya hanya di `.env.worker` dan gunakan
nilai yang sama ketika menjalankan perintah registrasi pada gateway:

```bash
openssl rand -hex 32
```

`WORKER_PORT` boleh diganti bebas. Port tersebut hanya bind ke localhost pada
Docker host. Domain worker harus diproxy aaPanel/Nginx ke
`127.0.0.1:<WORKER_PORT>` dan meneruskan header `Authorization`.

Jika image registry private, login GHCR pada VPS remote dengan permission pull,
lalu deploy image yang sudah dipublish:

```bash
docker login ghcr.io
python3 run.py deploy worker --pull
docker compose -f docker-compose.worker.yml ps
curl -fsS https://worker1.example.com/healthz
```

Healthcheck `/healthz` tidak memerlukan token. Endpoint internal tetap wajib
menggunakan bearer token worker.

### D.2 Daftarkan worker pada VPS gateway

Setelah domain worker dapat diakses, jalankan perintah berikut **di VPS
gateway**, bukan di VPS remote:

```bash
cd /www/wwwroot/dockter_bot_tdl
python3 run.py worker add remote-1 https://worker1.example.com
```

Saat diminta `Worker API token:`, masukkan nilai `WORKER_API_TOKEN` dari
`.env.worker` remote. Token tidak ditulis sebagai argumen command agar tidak
masuk shell history atau daftar proses.

Verifikasi registry gateway:

```bash
python3 run.py worker list
```

Output akan menampilkan nama, URL, dan token dalam bentuk tersamarkan.
Perintah `worker add` langsung menulis registry gateway; tidak diperlukan
rebuild image atau restart worker untuk menambah worker berikutnya.

### D.3 Verifikasi worker dan route legacy

Registrasi worker belum otomatis memindahkan route profile. Untuk alur baru,
pilih target profile-worker langsung di halaman Export, atau pilih worker di
Utility/Storage lalu jalankan checker. Halaman **Workers** masih menyediakan
route profile legacy untuk client lama dan Telegram; perubahan route hanya
berlaku untuk job baru, sedangkan job yang sudah berjalan tetap pada origin
asalnya.

Pastikan worker terlihat sehat dan buat satu job percobaan sebelum dipakai
untuk batch besar. Untuk menambah worker kedua, ulangi langkah D.1–D.3 dengan
nama berbeda, misalnya `remote-2`, URL berbeda, `PROFILE_ROOT` berbeda, dan
token berbeda.

## E. Update di setiap VPS worker remote

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

## F. Deploy web static di VPS gateway

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

## G. Smoke test worker dan Download manager

1. Login ke dashboard dan pastikan navbar hanya menampilkan actor profile,
   status backend, dan indikator target per fitur; tidak ada selector target
   operasional global.
2. Buka Export, pilih profile-worker pada TargetPicker, tekan `Verifikasi
   target`, lalu pastikan source dan Last ID berasal dari profile tersebut.
3. Buka Download. Tunggu status reconcile global selesai sebelum menekan aksi.
   Daftar harus memuat artifact lintas profile-worker dan origin tampil pada
   setiap artifact. Gunakan filter profile/worker bila diperlukan.
4. Pastikan Pending/Processing tidak menampilkan artifact yang file JSON-nya
   sudah hilang. Metadata lama boleh tetap terlihat di History dengan badge
   `File tidak tersedia` dan tanpa tombol Start/Retry.
5. Jalankan dua JSON pada worker aktif. Kartu harus memakai nama JSON sebagai
   judul, badge `JSON N/N`, nama media aktif, `File N/N`, speed, ETA, berhasil,
   gagal, dan dilewati.
6. Buka Log saat job masih berjalan. Ringkasan JSON/file harus tampil di atas,
   sedangkan output TDL aktif tampil pada terminal di bawahnya.
7. Uji `Select all`, `Mulai terpilih`, `Berikutnya`, `Hapus terpilih`, dan
   `Mulai semua`. Pastikan artifact campuran dikelompokkan menjadi satu job
   untuk setiap profile-worker asal dan kelompok berbeda dapat paralel.
8. Buka Utility dan Storage, pilih worker serta verifikasi target sebelum
   memilih folder. Pastikan Storage menolak worker tanpa profile
   `WORKER_STORAGE_PROFILE`.
9. Pastikan job terminal berpindah ke History dan snapshot log terakhir tetap
   dapat dibuka.

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
| Backend + Telegram + web, tanpa worker | Publish gateway | Deploy gateway | Tidak | Deploy terakhir |
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

## Bootstrap VPS baru dengan `run.py`

Pada VPS baru, checkout repository lalu jalankan check terlebih dahulu:

```bash
git clone <repository-url> /opt/tme3bot
cd /opt/tme3bot
python3 run.py check
```

`run.py` memeriksa Python dependency, Git, Docker, Docker Compose, curl, tar,
OpenSSL, env, base image, dan status image berdasarkan Git SHA. Jika dependency
Python atau tool belum ada, mode default boleh memasangnya pada Linux berbasis
apt. Compose v2 diprioritaskan dan `docker-compose` menjadi fallback.
Pada Linux yang menggunakan `apt`, `python3 run.py deploy` dapat memasang tool
yang belum tersedia. Jika installer tidak didukung, report akan memberikan
command install yang aman untuk dicopy.

Deploy target baru tidak langsung membangun base Go/TDL yang berat. Alurnya:

```bash
python3 run.py deploy
```

Script akan:

1. Memeriksa tools dan memasang yang hilang jika memungkinkan.
2. Membaca Git HEAD dan menolak worktree dirty kecuali `--allow-dirty`.
3. Memeriksa base image lokal/registry.
4. Memeriksa gateway/worker image dengan tag Git SHA dan digest registry.
5. Pull image jika release SHA sudah dipublish.
6. Berhenti dengan instruksi builder jika image belum dipublish atau base belum tersedia.
7. Menjalankan Compose, healthcheck, dan menyimpan deployment state.

`latest` bukan bukti bahwa release terbaru sedang digunakan. Untuk melihat
status tanpa mengubah service:

```bash
python3 run.py deploy --status
```

`python3 run.py` tanpa argumen sama dengan `python3 run.py check`; command ini
hanya melakukan preflight dan tidak mengubah service. Setelah report siap,
jalankan `python3 run.py deploy`. Exit code preflight `10` berarti tool masih
hilang dan `20` berarti env/data root belum siap. Image SHA yang belum ada akan
ditolak oleh deploy dengan instruksi publish builder. Secret tidak pernah
dicetak ke report.

### PyJWT `RECORD file not found` pada Ubuntu/Debian

Jika publish menampilkan error seperti:

```text
Cannot uninstall PyJWT ... RECORD file not found
```

versi PyJWT lama berasal dari paket `apt/dpkg`, bukan pip. Jangan menghapus
paket Debian secara manual. Tarik perubahan terbaru lalu jalankan ulang command
publish; `run.py` akan mencoba instalasi kedua dengan `--ignore-installed`
dan `--break-system-packages`, sehingga pip memasang versi requirements tanpa
mencoba meng-uninstall file milik Debian:

```bash
git pull --ff-only origin main
python3 run.py publish --all --build-base
```

Fallback ini hanya dipakai pada Python sistem Linux. Jika VPS menggunakan
virtualenv, gunakan interpreter virtualenv tersebut dan biarkan pip memakai
prosedur normalnya.

## Publish di VPS builder

Build berat hanya dilakukan di VPS builder yang cukup kuat:

```bash
git pull --ff-only origin main
python3 run.py check
python3 run.py publish --all --build-base
```

Untuk update Python tanpa perubahan base, cukup:

```bash
python3 run.py publish --all
```

Publish memberi tag immutable berdasarkan Git SHA, memverifikasi seluruh
manifest, lalu push gateway dan worker. Setelah itu setiap target cukup:

```bash
git pull --ff-only origin main
python3 run.py deploy
```

Tidak ada `docker build` di VPS target jika image SHA sudah tersedia di
registry.

## Concurrency dan pesan status job

Queue worker memakai resource lane yang menyimpan target eksekusi pada job.
Export serial per kombinasi `profile + worker + export`; download serial per
kombinasi `profile + worker + download`. Export dan download pada origin yang
sama dapat berjalan bersamaan karena memakai dua sesi `.tdl`; origin berbeda
juga dapat berjalan paralel. Leave berbagi lane export. Utility memakai worker
dan path workspace; path sibling dapat paralel, path yang overlap tetap serial.
Storage memakai lane `worker + tdl:storage` dan tidak memakai profile actor.

Setiap worker yang melayani Storage wajib memiliki profile sesi dedicated sesuai
`WORKER_STORAGE_PROFILE` (default `storage`), misalnya:

```bash
python3 run.py identity storage
```

Pastikan sesi tersebut sudah login dan memiliki akses channel Storage sebelum
menjalankan upload. Jika sesi belum ada, checker mengembalikan
`STORAGE_PROFILE_UNAVAILABLE`; jangan melewati checker dengan mengubah payload
manual. Jangan menghapus lock untuk memaksa paralel karena database Bolt `.tdl`
tidak boleh dibuka bersamaan. Backup tetap mengikuti lane backup yang ada.

Setiap job asynchronous yang dibuat dari Telegram membuat satu pesan status
tanpa keyboard. Pesan yang sama diperbarui saat queued/running, menampilkan
progress dan report terminal, lalu dihapus setelah sekitar tiga detik. Panel
utama boleh berubah atau diganti tanpa menghentikan pesan status job. Pesan
yang sudah dihapus user tidak dibuat ulang. Subscription status disimpan di
SQLite backend; jika container Telegram restart, subscription yang belum
terminal-notified dipulihkan dan diproses satu kali. Endpoint subscription
internal memakai `FRONTEND_SERVICE_TOKEN` dan tidak masuk OpenAPI publik.

## Source picker Export Fokus

Telegram tidak memiliki native select pada inline keyboard. Export Fokus kini
menampilkan picker ringkas dengan maksimal enam source per halaman, pagination,
recent source, pencarian input, dan callback digest yang stabil. Source baru
tetap memakai username/numeric ID. Memilih source baru mereset report panel
dan overwrite Start ID, tetapi tidak membatalkan job lama.

## Source management dan cleanup Utility Pindah

Source tersimpan dapat dihapus dari Web pada daftar `Source tersimpan` melalui
ikon Trash setelah konfirmasi. Pada Telegram, buka `Pilih source tersimpan`
di Export Fokus lalu gunakan tombol `Hapus`, atau buka `Workspace full fitur`
dan menu source management untuk penghapusan tunggal maupun batch.

Source dengan chat reference numeric tidak otomatis ditambahkan ke backend.
Aktifkan `Simpan source numeric` pada panel Telegram atau Web jika ID tersebut
ingin dipakai lagi dengan Last ID yang tersinkron. Source username tetap
tersimpan otomatis setelah export sukses, sedangkan source numeric yang sudah
tersimpan tetap diperbarui monotonic.

Utility `Pindah` membuat `output.json` dan `new_output.json` sebagai file
perantara. Setelah seluruh pipeline Pindah berhasil, worker menghapus kedua
file tersebut dan report menyertakan `temporary_json_removed`. Jika pipeline
gagal, cleanup tidak dijalankan agar diagnosis tetap memungkinkan.

## Context target per fitur dan Download global

Navbar web tidak lagi menjadi sumber target operasional. Navbar hanya
menampilkan identity actor, profile actor untuk audit, status backend, dan
status worker terakhir. Target dipilih pada fitur yang memakainya:

- Export: pilih `profile` dan `worker`, lalu klik `Verifikasi target`. Source
  dan Last ID dimuat dari profile target; tombol submit baru aktif setelah
  response checker valid.
- Utility: pilih `worker`, verifikasi workspace, lalu pilih folder pada worker
  tersebut. Profile actor hanya dicatat untuk audit.
- Storage: pilih `worker`, verifikasi `WORKER_STORAGE_PROFILE`, lalu gunakan
  Workspace Explorer. Profile Storage dedicated adalah profile TDL worker,
  bukan profile actor.
- Download: default `scope=global`, sehingga artifact dari seluruh profile dan
  worker tampil. Filter profile/worker hanya untuk penyaringan tampilan.

Checker API:

```bash
curl -X POST "$BACKEND_URL/api/v1/context/verify" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"purpose":"export","profile":"default","worker":"local"}'
```

Submit job tetap melakukan validasi ulang. Status verified di browser bukan
otorisasi mandiri. Jika target berubah, verification dihapus dan request lama
diabaikan memakai generation ID.

### Download batch dan bulk action

Gunakan endpoint batch untuk memilih artifact lintas origin:

```bash
curl -X POST "$BACKEND_URL/api/v1/downloads/batch" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"artifact_ids":["id-1","id-2"],"priority":"normal"}'
```

Backend mengelompokkan artifact berdasarkan `(profile, worker)` dan membuat
satu job per kelompok. Kelompok berbeda berjalan paralel, sementara artifact
dalam origin yang sama mengikuti lane download origin tersebut. Artifact
unavailable atau file fisik yang hilang ditolak/ditandai History dan tidak
ditampilkan sebagai aksi Start. Hapus file terpilih memakai
`POST /api/v1/downloads/artifacts/actions/delete`; metadata History tetap ada.

### Urutan rollout perubahan context

Deploy selalu dalam urutan berikut:

1. Gateway/backend: migration SQLite, checker, source profile, download global
   dan endpoint batch.
2. Worker-local dan seluruh worker remote: scheduler origin, inventory,
   capability endpoint, serta `WORKER_STORAGE_PROFILE` dan sesi `.tdl`-nya.
3. Static web: TargetPicker, filter/download global, dan bulk actions.

Setelah setiap tahap, lakukan health check dan pastikan worker yang relevan
terdaftar. Job lama tetap memakai `profile/worker` yang tersimpan di dalam job;
perubahan target atau filter tidak memindahkan job aktif. Jika worker Storage
belum memiliki profile dedicated, rollback UI atau nonaktifkan upload Storage
sementara; jangan rollback database dengan menghapus kolom/tabel additive.
