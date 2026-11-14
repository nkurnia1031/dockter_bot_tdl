# tme3bot Agent Context

Dokumen onboarding dan handoff untuk agent baru. Baca bagian **Status handoff**
lebih dahulu, lalu verifikasi keadaan aktual dengan `git status`, `git log`, dan
source code. Jangan menganggap ringkasan ini menggantikan pemeriksaan kode jika
branch sudah berubah.

Untuk tugas kesehatan, pengukuran, atau insiden Redis/RQ di gateway, baca
`docs/agents/redis-queue-audit.md` sebelum bertindak. Dokumen itu mencatat
insiden AOF 2026-10-30, akses yang tersedia, dan cakupan audit/no-op production
yang disetujui pengguna.

## Status handoff

Diperbarui 2026-11-11 (UTC). Verifikasi awal setiap sesi tetap memakai `git status`,
`git log`, dan source aktual. Web kembali memakai SvelteKit 5 + Svelte 5 dengan
adapter-static. Semua 17 route diprerender, `trailingSlash` disetel `always`,
dan fallback `200.html` tetap tersedia untuk static host. API gateway, login,
cookie, CSRF, dan kontrak endpoint tidak berubah. Tidak ada Node runtime atau
container Web di production; bundle tetap berada di
`/www/wwwroot/ui.utama.naufix.space`.

GitHub Actions memakai `pnpm check`, `pnpm test`, dan `pnpm build` untuk Svelte,
lalu mem-publish bundle static `web-latest`. Verifikasi rollback terakhir:
`pnpm check` tanpa error/warning, 139 tes dari 29 file lulus, build static
berhasil, seluruh 17 route memiliki entry langsung dan `200.html` tersedia;
11 tes `tests.test_container` juga lulus. Deploy bundle memakai
`python3 run.py deploy web` dari root gateway.

Jika task menyentuh Docker image, gunakan builder lokal yang memiliki base
image `tme3bot-base:py310-tdl0203`; jangan build di VPS 1 GB.

### Langkah operasional berikutnya

- Pada builder, publish image sesuai runbook. Pada gateway jalankan
  `git pull --ff-only origin main` lalu `python3 run.py deploy gateway --pull`.
  Pada worker remote jalankan `git pull --ff-only origin main` lalu
  `python3 run.py deploy worker --pull`.
- Perubahan Web perlu melalui CI sebelum static bundle dipublish.
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
lebih dahulu jika `graphify-out/graph.json` tersedia. Jika graph belum ada dan
berguna untuk pertanyaan tersebut, buat secara lokal dengan `graphify update .`.
Setelah mengubah source, jalankan `graphify update .` untuk memperbarui konteks
lokal. Seluruh `graphify-out/` diabaikan Git; jangan stage atau commit outputnya
dan jangan mengeditnya manual untuk memperbaiki kode aplikasi.

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
- Seluruh proses TDL worker berjalan sebagai root. HOME Export/leave tetap `/data/user1` dan Download `/data/root`; Bolt store masing-masing lane berada di `/database/tdl/<profile>/<export|download|upload>/.tdl`. Nama HOME historis bukan akun Linux, dan sesi antar-lane tetap terpisah.
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
- `docker-compose.gateway.yml` menjalankan backend, backend-queue, Redis
  internal, Telegram frontend, dan worker lokal di VPS utama;
  `docker-compose.worker.yml` menjalankan worker VPS kedua. Backend menyimpan
  identity/state dan worker mengaksesnya lewat `/internal/v1`.
- Route worker dipilih per profile dan disimpan di `worker_routes.json`. Job
  menyimpan worker asalnya saat dibuat, sehingga perubahan route hanya berlaku
  untuk job baru dan tidak memindahkan job aktif. `state.json` gateway adalah
  sumber kebenaran lintas VPS untuk source, `last_id`, label, dan warmup.
- Semua database persisten memakai host `DATABASE_ROOT` pada filesystem OS,
  terpisah dari volume data dan Workspace bila host memiliki disk berbeda.
  `run.py` memvalidasi filesystem, symlink, mount tersarang, permission root,
  dan kepemilikan Redis sebelum Compose berjalan. Gateway memakai
  `/database/gateway/storage.db` serta Redis `/database/redis`; worker-local
  memakai `/database/worker-local`, dan setiap worker remote memakai
  `/database`. SQLite worker, TDL/Bolt per profile/lane, dan staging clone TDL
  Quick Mode juga harus berada di bawah `/database`. Gunakan
  `tme3bot.database_paths.DatabasePaths` untuk membentuk path. `/data` tetap
  menyimpan metadata/profile serta artifact audio TTS di `/data/tts`;
  artifact audio bukan database dan bisa berukuran besar. `/workspace` menyimpan
  file pengguna dan staging besar. Database/cache persisten TTS di masa depan
  wajib di bawah `/database/tts`. Migrasi host harus menunggu job terminal dan menghentikan writer,
  membuat snapshot konsisten, lalu mempertahankan salinan lama untuk rollback.

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

### Pemisahan tes CI dan production

- GitHub Actions hanya menjalankan tes dengan fixture, data sementara, dan server lokal/terisolasi. Workflow CI tidak boleh mengakses URL production atau memakai credential, sesi browser, maupun cookie production.
- Tes production hanya boleh dijalankan dari mesin/workspace ini melalui tooling lokal, dan hanya untuk tugas yang secara eksplisit mengizinkan akses production. Jangan menambahkan tes production ke workflow GitHub Actions.

### Trusted device untuk browser agent

- Gunakan jalur ini hanya jika tugas yang sedang dikerjakan memang mengizinkan
  akses ke production. Credential perangkat hanya menyelesaikan autentikasi;
  credential ini tidak memberi izin untuk deploy, mengubah data, atau melakukan
  aksi production lain yang belum diminta.
- Pendaftaran perangkat dilakukan terpisah dari pekerjaan agent dan harus
  disetujui pengguna dari sesi Web yang sudah login. Jangan mendaftarkan key,
  membuka production, atau memulai login Telegram secara otomatis.
- Helper Windows/Linux berada di `tools/trusted_device.py`. Buat key dan
  berkas public-key enrollment dengan perintah sesuai OS:

  ```powershell
  python -m tools.trusted_device init --origin https://ui.utama.naufix.space --name "Laptop agent"
  ```

  ```bash
  python3 -m tools.trusted_device init --origin https://ui.utama.naufix.space --name "Laptop agent"
  ```

  Di Windows, private key dilindungi DPAPI akun saat ini. Di Linux, helper
  meminta passphrase minimal 12 karakter dan mengenkripsi private key dengan
  Scrypt + AES-GCM; file tetap dibatasi ke permission user (`0700`/`0600`).
  Passphrase diminta kembali saat `status` atau `prepare-browser`, dan tidak
  boleh disimpan di environment variable atau command history. Credential
  Linux berada di `$XDG_CONFIG_HOME/tme3bot/trusted-devices` atau
  `~/.config/tme3bot/trusted-devices`.

  Backend harus dikonfigurasi dengan `WEB_PUBLIC_ORIGIN` persis ke origin
  HTTPS situs sebelum fitur ini dapat dipakai.
  Pengguna mengunggah dan menyetujui berkas enrollment tersebut pada
  Pengaturan → Perangkat tepercaya setelah memeriksa fingerprint.
- Untuk tugas production yang sudah diotorisasi, periksa metadata lalu minta
  helper membuat sesi browser sementara:

  ```powershell
  python -m tools.trusted_device status --origin https://ui.utama.naufix.space
  python -m tools.trusted_device prepare-browser --origin https://ui.utama.naufix.space
  ```

  Di Linux, gunakan `python3 -m tools.trusted_device` untuk kedua perintah itu.

  Helper menghasilkan Playwright storage state di direktori privat OS.
  Jangan membuka atau mencetak isi file, menyalin cookie ke log/chat, atau
  memasukkannya ke URL. State dipertahankan untuk masa sesi yang diterbitkan
  server (default 30 hari). Bila
  `prepare-browser` diperlukan, agent membaca path dari output secara lokal;
  pengguna tidak perlu menyalin path pada setiap tes.

  Repository menyediakan `tools.trusted_device_browser.open_trusted_context()`
  untuk agent berbasis Playwright serta `python -m tools.trusted_device_browser`
  untuk memeriksa sesi browser. Tanpa `--state-file`, runner otomatis memakai
  state tersimpan terbaru, membatasi request ke origin tersebut, lalu
  menyimpan rotasi cookie secara atomik saat context ditutup. Jalankan browser
  secara serial agar refresh token tidak berlomba. State eksplisit yang dipakai
  sebagai impor sekali pakai tetap dihapus setelah import. Setelah masa sesi
  habis, buat satu state baru dengan `prepare-browser`; device yang sudah
  dipercaya tidak perlu dienroll ulang.
- Setelah autentikasi, verifikasi sesi melalui UI/API yang diizinkan sebelum
  melakukan tindakan. Cabut perangkat dari Pengaturan bila laptop tidak lagi
  dipercaya; `forget-local` hanya menghapus credential pada laptop dan tidak
  mencabut perangkat di server.

## Profile Layout

Profile default memakai `/data`; profile tambahan memakai `/data/profiles/<name>`.

```text
<profile>/root/.tdl/       sesi lane Download
<profile>/user1/.tdl/      sesi lane Export/leave
<profile>/identity.json    telegram_user_id/tdl_user_id
<profile>/state.json       source dan last_id
<profile>/exports/         pending/processing/done/failed
```

`python3 run.py identity <profile>` membaca sesi lane Export (`user1/.tdl`) tanpa login ulang dan membuat identity.

## Queue Rules

- Download: artifact global dikelompokkan berdasarkan `(profile, worker)`;
  profile-worker berbeda paralel, origin yang sama serial melalui
  `SerialPerKeyQueue`.
- Utility: folder berbeda paralel, folder sama serial.
- Export: serial per profile-worker export lane.
- Storage upload: serialize within each destination lane (TDL or rclone). Copy
  holds a shared lock on the selected Workspace tree, so Telegram and rclone
  copies can run together. Move holds an exclusive lock on that tree and waits
  for overlapping copies/moves to finish; unrelated Workspace trees remain
  independent.
- Storage upload mode `Move` menghapus sumber per file segera setelah upload file
  itu terkonfirmasi: Telegram setelah TDL mengembalikan `message_id`, rclone
  setelah verifikasi penuh file tujuan. Worker hanya menghapus file yang masih
  berada di `/workspace` dan metadata identitasnya (device/inode/size/mtime_ns)
  belum berubah. File gagal, ambigu, atau berubah tetap ada; `cleanup_status`
  melaporkan hasil per file. Folder induk dibersihkan hanya jika kosong.
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

### Workflow Git agent

Semua pekerjaan agent dilakukan langsung pada branch `main`. Pastikan
`git branch --show-current` menghasilkan `main`, lalu edit dan commit di
worktree tersebut. Push ke `origin main` ketika pengguna memintanya. Jangan
membuat atau berpindah ke branch fitur maupun worktree terpisah untuk
implementasi.

Sebelum staging, periksa `git status` dan stage hanya file atau hunk yang
terkait tujuan aktif. Pertahankan perubahan lain yang sudah ada di worktree;
commit perubahan tersebut hanya jika pengguna meminta.

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

Setelah push ke `main`, GitHub Actions memvalidasi source, mem-publish image
gateway/worker, dan mem-publish release static Web. Deploy dilakukan dari root
production yang benar agar Compose project dan volume yang sudah ada tetap
digunakan.

Gateway lokal berada di `/www/wwwroot/dockter_bot_tdl`. Dari direktori itu:

```bash
git pull --ff-only origin main
python3 run.py deploy gateway --pull
```

Gateway compose hanya menjalankan `backend`, `telegram`, dan `worker-local`.
Worker `remote-1` berada di VPS `138.2.34.55` dan dideploy melalui SSH dari
root `/www/wwwroot/downloads/bot` pada host tersebut. `HostKeyAlias` memakai
hostname worker yang sudah dipercaya untuk memvalidasi host key saat koneksi
menggunakan IP. Worker `remote-2` berada di `aapanel2.naufix.space`; root
repo dan Compose project yang benar adalah `/www/wwwroot/dockter_bot_tdl` dan
`dockter_bot_tdl`:

```bash
ssh -i ~/.ssh/id_ed25519_dockter_gateway -o HostKeyAlias=bot.worker1.naufix.space root@138.2.34.55 'cd /www/wwwroot/downloads/bot && git pull --ff-only origin main && python3 run.py deploy worker --pull'
ssh -i ~/.ssh/id_ed25519_dockter_gateway -o IdentitiesOnly=yes root@aapanel2.naufix.space 'cd /www/wwwroot/dockter_bot_tdl && git pull --ff-only origin main && python3 run.py deploy worker --pull'
```

Web static sekarang berada dan dideploy pada gateway yang sama dengan backend,
bukan pada VPS `remote-1`. Setelah GitHub Actions mem-publish release
`web-latest`, jalankan deploy Web secara lokal dari root gateway
`/www/wwwroot/dockter_bot_tdl`:

```bash
python3 run.py deploy web
```

Sebelum deploy gateway, verifikasi label Compose `project.working_dir` dan
`project` pada container gateway; sebelum deploy worker, verifikasi label yang
sama pada container `remote-1` atau `remote-2` sesuai host tujuan. Untuk
`remote-2`, pastikan `project.working_dir=/www/wwwroot/dockter_bot_tdl` dan
`project=dockter_bot_tdl`; jangan memakai path gateway/worker lain yang
kebetulan juga memiliki checkout. Selalu jalankan setiap deploy dari root yang
ditetapkan agar Compose memakai stack dan volume data yang benar; jangan
membuat clone/deployment project kedua. Untuk SSH ke kedua worker, gunakan host
key tepercaya dan agent/key yang tersedia. Deploy rutin tidak memerlukan
enrollment atau pembuatan key baru. Jangan tampilkan private key atau
passphrase.

Perintah static deploy mengambil release `web-latest`, memverifikasi checksum,
dan mengekstrak bundle ke `/www/wwwroot/ui.utama.naufix.space` pada gateway.
Ia tidak menjalankan pnpm, Docker web, atau mengubah/reload Nginx. Untuk
repository private, `WEB_RELEASE_TOKEN` adalah PAT GitHub dengan akses
`Contents: Read` dan disimpan hanya di `.env` gateway; bukan di `.env.backend`
dan bukan di Git.
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
- README bisa tertinggal; gunakan source code, file `.env.*.example` yang tersedia, dan dokumen ini sebagai konteks aktual.

Pertahankan Python 3.10/Ubuntu 22.04 compatibility, gunakan `apply_patch`, tambahkan test untuk behavior baru, dan laporkan bila Docker/Go tidak tersedia untuk verifikasi build.

## graphify

This project can generate a local knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships. The generated directory is ignored by Git.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. If it does not exist and graph traversal would help, generate it locally with `graphify update .` first. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Graphify outputs are local generated files. Never stage or commit graphify-out/; regenerate it as needed. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the local graph current (AST-only, no API cost). Leave its ignored output out of Git.

## Agent skills

### Required first step

Before acting on any actionable user request in this repository, run `/ask-matt` by reading `.agents/skills/ask-matt/SKILL.md` and routing the request to the appropriate skill or flow. Do this for every scope—including code, bugs, documentation, tests, GitHub, production, and deployment—even when the task looks small. Read the selected skill's `SKILL.md` before applying its workflow. Finish routing before inspecting or changing task files or making external requests, then carry out the authorized work without asking the user to repeat details already provided. Ask Matt selects a workflow; it does not authorize external side effects.

### Issue tracker

Project issues live in GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical labels listed in `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo. See `docs/agents/domain.md`.
