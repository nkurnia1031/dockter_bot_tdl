# tme3bot Agent Context

Dokumen onboarding dan handoff untuk agent baru. Baca bagian **Status handoff**
lebih dahulu, lalu verifikasi keadaan aktual dengan `git status`, `git log`, dan
source code. Jangan menganggap ringkasan ini menggantikan pemeriksaan kode jika
branch sudah berubah.

## Status handoff

Diperbarui 2026-09-24 (Asia/Jakarta). Pada saat handoff:

- branch `main` berada pada commit `853faab`
  (`fix(quickmode): reconcile cleanup stages with remote uploads`), dan
  `origin/main` berada pada commit yang sama;
- sebelum pembaruan dokumen ini worktree bersih; perubahan yang diharapkan
  setelahnya hanya pembaruan `AGENTS.md` ini;
- web tetap berupa SvelteKit static; tidak ada Next.js, Node runtime, atau
  container web di produksi. Target static UI aaPanel tetap
  `/www/wwwroot/ui.utama.naufix.space`;
- Quick Mode sudah memiliki staging/recovery, retry dengan stage/job ID yang
  stabil, dua clone `.tdl`, manifest `quickmode.json`, `worker.log`,
  thumbnail, compress, upload Telegram dan rclone Google Drive;
- telemetry worker sudah diperbaiki untuk retry dengan job ID stabil: backend
  meneruskan `event_sequence_start`, worker melanjutkan sequence, event worker
  mencatat send/delivered/ignored/failed, dan heartbeat berjalan berkala;
- snapshot log dikembalikan newest-first, progress berulang diringkas per
  transfer, timestamp memakai timezone Asia/Jakarta, serta command milestone
  mencatat command tersanitasi dan tail output;
- crosscheck Quick Mode sekarang berjalan untuk fase `uploading` maupun
  `cleanup` yang tidak aktif. Verifikasi Telegram mempercayai
  `channel_message_id` dari manifest; verifikasi Google Drive memakai
  `rclone check` dengan fallback inventory `rclone lsjson` untuk duplicate
  filename. Kegagalan crosscheck mempertahankan staging;
- command verifikasi sekarang ikut ditulis ke `worker.log`. Jangan menghapus
  staging hanya karena job backend terminal; hapus hanya setelah seluruh file
  Telegram dan archive Google Drive terverifikasi;
- verifikasi source terakhir: 281 unittest Python lulus, compileall lulus,
  test backend/rclone terkait lulus, `graphify update .` berhasil, dan
  `git diff --check` bersih sebelum perubahan dokumen ini. Verifikasi Web
  terakhir yang diketahui: `pnpm check` tanpa error/warning, test frontend
  lulus, dan `pnpm build` sukses;
- build Docker/Go produksi belum dijalankan pada handoff ini. Jika task
  menyentuh image, gunakan builder lokal yang memiliki base image
  `tme3bot-base:py310-tdl0203`; jangan build di VPS 1 GB.

### Catatan diagnosis produksi terakhir

- Binary lokal yang sudah diverifikasi: `C:\tdl\tdl.exe` versi `0.20.4` dan
  `D:\Downloads\Compressed\rclone-v1.75.1-windows-amd64\rclone.exe` versi
  `v1.75.1`. Config rclone lokal berada di
  `C:\Users\Admin\.config\rclone\rclone.conf`; jangan menampilkan isinya.
- Pemeriksaan langsung channel `1588718424` berhasil. Message ID `442` dan
  `443` adalah archive `.7z.001`/`.7z.002`, sedangkan ID `444` adalah thumbnail
  photo yang oleh TDL direpresentasikan sebagai nama JPG yang dibuat Telegram.
  Ini menjelaskan mengapa pencocokan lama melaporkan Telegram `2/3` walaupun
  thumbnail benar-benar ada.
- Pemeriksaan langsung Google Drive menemukan archive dengan ukuran yang
  sesuai di `googledrive:backup/quickmode`. Nama export memakai tanggal sumber
  (`20260921`), jadi tanggal nama file bukan bukti bahwa upload hari ini gagal.
  `rclone copyto` juga dapat mempertahankan modtime object lama ketika object
  yang sama ditulis ulang.
- Setelah deploy commit `853faab`, buka Quick Mode Manager dan lakukan
  `Refresh scan`. Hasil yang diharapkan untuk stage terkait adalah Telegram
  `3/3`, Google Drive `2/2`, kemudian staging dihapus. Jika belum, baca
  `/workspace/quickmode/<stage_job_id>/worker.log` dan
  `/workspace/quickmode/<stage_job_id>/quickmode.json` di worker; jangan
  mencetak credential, password, atau isi sesi `.tdl`.

### Langkah operasional berikutnya

- Pada builder, publish image sesuai runbook. Pada gateway jalankan
  `git pull --ff-only origin main` lalu `python3 run.py deploy gateway --pull`.
  Pada worker remote jalankan `git pull --ff-only origin main` lalu
  `python3 run.py deploy worker --pull`.
- Perubahan terakhir hanya backend/worker; static Web tidak perlu dipublish
  ulang kecuali ada perubahan di `web/`.
- Jika source diubah lagi, jalankan minimal compileall, unittest terkait,
  `git diff --check`, dan `graphify update .`; untuk perubahan Web tambahkan
  `cd web && pnpm check && pnpm test && pnpm build`.
- Commit dokumentasi handoff ini dengan:
  `git add AGENTS.md && git commit -m "docs: refresh agent handoff"`.

### Checklist memulai sesi baru

```bash
git status --short
git log -5 --oneline --decorate
python -m compileall -q tme3bot utility bot.py run.py
python -m unittest discover -s tests -v
cd web && pnpm check && pnpm test && pnpm build
git diff --check
```

Untuk pertanyaan arsitektur atau relasi file, jalankan `graphify query ...`
lebih dahulu jika `graphify-out/graph.json` tersedia. Setelah mengubah source,
jalankan `graphify update .`. File di `graphify-out/` boleh berubah sebagai
hasil graphify; jangan mengeditnya manual untuk memperbaiki kode aplikasi.

Jangan menampilkan nilai rahasia dari `.env`, `.env.backend`, `.env.worker`,
`workers.json`, token GHCR/GitHub, token internal, cookie secret, password
utility, atau sesi `.tdl`. Jika perlu memeriksa konfigurasi, tampilkan hanya
nama key dan status configured/missing.

## Arsitektur

- `tme3bot/app.py` adalah composition entrypoint untuk role backend, telegram,
  dan worker.
- `tme3bot/api/backend.py` adalah FastAPI public/internal control plane.
- `tme3bot/frontend/telegram/app.py` hanya menangani UI Telegram dan selalu
  menggunakan `BackendApiClient`.
- `tme3bot/worker/executor.py` menjalankan job domain dan mengirim event JSON;
  modul ini tidak boleh bergantung pada Telegram.
- `domain/`, `application/`, dan `infrastructure/` menerapkan ports/adapters,
  job state machine, repository, auth bot challenge, dan worker strategy.
- `profiles.py` menentukan runtime profile dan authorization dari `identity.json`.
- Sesi `user1` dipakai export dan leave; sesi `root` dipakai download. Jangan gabungkan folder `.tdl`.
- `service.py` mengorkestrasi export/download; `tdl.py` menjalankan subprocess dan menangani output ANSI/PTY.
- `application/control_plane.py` mengorkestrasi command/query dan lifecycle job.
- `worker/executor.py` menangani export/download/leave, utility, storage, dan
  backup tanpa mengakses UI Telegram.
- `state.py` menyimpan `state.json`; akses source dan label dari frontend selalu
  melalui Backend API.
- `utility.py` menangani folder workspace dan adapter utility.
- `APP_ROLE=backend` menjalankan FastAPI dan persistence; `APP_ROLE=telegram`
  menjalankan UI Telegram tanpa mount `/data`; `APP_ROLE=worker` menjalankan
  sesi `.tdl`, export, download, serta utility tanpa `BOT_TOKEN`.
- `docker-compose.gateway.yml` menjalankan backend, Telegram frontend, dan
  worker lokal di VPS utama; `docker-compose.worker.yml` menjalankan worker VPS
  kedua. Backend menyimpan identity/state dan worker mengaksesnya lewat
  `/internal/v1`.
- Route worker dipilih per profile dan disimpan di `worker_routes.json`. Job
  menyimpan worker asalnya saat dibuat, sehingga perubahan route hanya berlaku
  untuk job baru dan tidak memindahkan job aktif. `state.json` gateway adalah
  sumber kebenaran lintas VPS untuk source, `last_id`, label, dan warmup.

### Model target fitur saat ini

Navbar Web hanya menampilkan actor/session context dan status; selector navbar
bukan sumber target operasional utama. Target dipilih sesuai fitur:

- Export memakai `TargetPicker`: profile + worker + `POST /api/v1/context/verify`.
- Utility dan Storage memakai worker saja + checker workspace/storage.
- Download secara default memakai katalog global lintas profile dan worker;
  profile/worker/label/ID-username adalah filter opsional.
- Setiap artifact menyimpan origin profile-worker. Saat batch download dikirim,
  backend mengelompokkan artifact berdasarkan origin dan membuat job terpisah;
  job berbeda boleh berjalan paralel, sedangkan lane yang sama pada origin yang
  sama tetap serial.
- Job selalu menyimpan target asal secara permanen. Mengganti route atau filter
  tidak memindahkan job aktif.

Endpoint penting untuk target dan worker:

- `POST /api/v1/context/verify` memeriksa target aktual sebelum submit;
- `GET /api/v1/workers` mengembalikan `enabled` dan route terpilih;
- `PATCH /api/v1/workers/{name}` dengan `{"enabled": false|true}` mengatur
  admission worker;
- `PUT /api/v1/me/worker-route` mengubah route legacy/profile untuk job baru.

Enable/disable worker hanya memblokir job dan route baru di gateway. Ini tidak
mematikan proses Docker/VPS dan tidak membatalkan job lama. Registry tetap
menyimpan worker agar bisa diaktifkan lagi. Record worker lama yang belum
memiliki field `enabled` dianggap aktif. Error admission yang diharapkan adalah
`WORKER_DISABLED` (HTTP 409).

## Security

- Profile ditentukan otomatis dari numeric Telegram user ID dalam `identity.json`.
- User tanpa identity hanya boleh memakai `Check Profile` atau `/check_profil`.
- Semua command, text input, dan callback harus melewati authorization.
- Utility hanya boleh memakai path di dalam `/workspace` setelah `resolve()` dan `relative_to()`.
- Jangan log password utility.

## Profile Layout

Profile default memakai `/data`; profile tambahan memakai `/data/profiles/<name>`.

```text
<profile>/root/.tdl/       sesi download
<profile>/user1/.tdl/      sesi export/leave
<profile>/identity.json    telegram_user_id/tdl_user_id
<profile>/state.json       source dan last_id
<profile>/exports/         pending/processing/done/failed
```

`python3 run.py identity <profile>` membaca sesi `user1` tanpa login ulang dan membuat identity.

## Queue Rules

- Download: artifact global dikelompokkan berdasarkan `(profile, worker)`;
  profile-worker berbeda paralel, origin yang sama serial melalui
  `SerialPerKeyQueue`.
- Utility: folder berbeda paralel, folder sama serial.
- Export: serial per profile-worker export lane.
- Storage upload: serial per worker storage lane.
- Jangan membuka database Bolt `.tdl` yang sama dari dua proses bersamaan.
- Async panel wajib memakai `panel_view_token` agar panel lama tidak hidup kembali.
- Metadata panel tidak boleh masuk payload job worker. Progress worker harus
  dikirim sebagai event JSON idempotent `job_id + sequence`; frontend melakukan
  polling public job API.

## Download Manager: aturan penting

- Membuka `web/src/lib/components/DownloadsPage.svelte` hanya melakukan GET
  katalog. Tidak ada reconcile otomatis dan tidak ada polling inventory saat
  halaman dibuka. Tombol reconcile yang terlihat adalah aksi manual operator.
- Pemeriksaan fisik artifact terjadi ketika job download dikirim. Worker
  melakukan preflight terhadap file JSON di `pending`/`failed`.
- Jika file hilang, worker mengirim event `artifact.missing`; gateway memanggil
  `ExportArtifactCatalog.mark_missing()`, mengubah status menjadi `deleted`,
  mengatur `available=0`, dan menyimpan metadata untuk History/audit. Karena
  file fisiknya sudah hilang, tidak dibuat job delete tambahan. Artifact itu
  tidak boleh memiliki tombol Start/Retry.
- Backend tetap menolak artifact `available=false`, status non-pending, origin
  yang tidak terdaftar, dan worker nonaktif sebelum membuat job. Batch divalidasi
  seluruhnya sebelum kelompok pertama didispatch agar tidak terjadi batch
  setengah jadi.
- `Reconcile` tetap berguna untuk sinkronisasi katalog/manual repair, tetapi
  bukan bagian dari jalur buka halaman atau jalur normal submit download.
- Jangan mengubah missing menjadi hard delete database tanpa keputusan baru;
  history/audit dan diagnosis membutuhkan record terminal tersebut.

## Utility

Host `/www/wwwroot/downloads` di-mount ke `/workspace`. Daftar global berada di `/data/utility_folders.json`, dengan default `/workspace/biasa`, `/workspace/pilihan`, dan `/workspace/downloads`.

Adapter utility selalu memakai absolute path script, `cwd` folder target, stdout/stderr ke Docker log, dan exit code non-zero sebagai failure. Export terdiri dari converter HTML ke JSON lalu organizer media. Compress mempertahankan password hardcoded dan `-sdel`. Extract memakai nama folder sebagai password default atau password dari bot.

Folder utility/storage harus berasal dari `/workspace` dan dikirim sebagai path
absolute. Worker yang dipilih menentukan filesystem; pergantian worker harus
membatalkan data tree lama dan memuat ulang tree worker baru.

## Telegram UI

`tme3bot/frontend/telegram/app.py` adalah presenter Telegram dan hanya boleh
memakai `BackendApiClient` untuk data domain. Export fokus adalah satu panel
utama: source, label, Start ID/overwrite, profile-worker, dan detail job.
Pemilihan source mereset tampilan detail panel tetapi tidak membatalkan job
backend.

Setiap export juga memiliki satu pesan status sementara tanpa keyboard. Pesan
yang sama diedit selama job berjalan, menampilkan report terstruktur saat
terminal, lalu dihapus sekitar 3 detik kemudian. Penyelesaian job tidak boleh
memanggil `send_message` untuk notifikasi tambahan. `PanelManager` harus
menangani panel/status message yang sudah dihapus user tanpa exception.

Recovery `/start`, `/menu`, `/panel`, unknown command, serta teks persis
`menu`/`panel` harus dapat membuat panel baru bila message lama hilang.

## Operasional

```bash
python3 run.py up
python3 run.py update
python3 run.py logs
python3 run.py shell
python3 run.py cleanup
```

### Deployment yang benar

Build dan publish dilakukan dari mesin yang memiliki Docker serta base image,
bukan dari VPS Oracle 1 GB. Pada builder lokal:

```bash
python run.py check
python run.py publish gateway
```

Jika base image hilang, jalankan sekali `python run.py build-base` (atau
`python run.py publish gateway --build-base`) pada builder besar. Jangan
menjalankan `docker compose build` di VPS target jika base image tidak ada.

Di VPS gateway:

```bash
git pull --ff-only origin main
python3 run.py deploy gateway --pull
```

Gateway compose hanya menjalankan `backend`, `telegram`, dan `worker-local`.
Setiap VPS remote menjalankan:

```bash
git pull --ff-only origin main
python3 run.py deploy worker --pull
```

Static UI dipublish oleh GitHub Actions, lalu di VPS gateway/aaPanel dijalankan:

```bash
python3 run.py deploy web
```

Perintah static deploy mengambil release `web-latest`, memverifikasi checksum,
dan mengekstrak bundle ke `/www/wwwroot/ui.utama.naufix.space`. Ia tidak
menjalankan pnpm, Docker web, atau mengubah/reload Nginx. Untuk repository
private, `WEB_RELEASE_TOKEN` adalah PAT GitHub dengan akses `Contents: Read`
dan disimpan hanya di `.env` VPS; bukan di `.env.backend` dan bukan di Git.
Rollback UI: `python3 run.py deploy web --rollback`.

## Verifikasi

```bash
python -m compileall -q tme3bot utility bot.py run.py
python -m unittest discover -s tests -v
git diff --check
```

## Jebakan

- Jangan memisahkan `last_id` berdasarkan label.
- Jangan memakai Bot API untuk operasi akun user TDL.
- Jangan menganggap satu baris output tdl selalu lengkap; output dapat ter-wrap dan mengandung ANSI.
- Jangan menghapus JSON failed otomatis; `/retry_failed` dan `/clear_fail` terpisah.
- Jangan membatalkan perubahan lokal yang tidak terkait task.
- Jangan menganggap toggle `enabled` mematikan container; ia hanya admission
  control gateway.
- Jangan menghidupkan reconcile otomatis kembali pada Download Manager untuk
  memperbaiki data stale; gunakan preflight submit atau aksi manual reconcile.
- Jangan mengelompokkan download berdasarkan actor/session navbar; gunakan
  origin profile-worker yang tersimpan pada artifact.
- README bisa tertinggal; gunakan source code, `.env.example`, dan dokumen ini sebagai konteks aktual.

Pertahankan Python 3.10/Ubuntu 22.04 compatibility, gunakan `apply_patch`, tambahkan test untuk behavior baru, dan laporkan bila Docker/Go tidak tersedia untuk verifikasi build.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
