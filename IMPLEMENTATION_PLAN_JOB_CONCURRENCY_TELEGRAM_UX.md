# Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram

Status: **rencana analisis — belum mengubah kode produksi**  
Tanggal: 2026-08-18  
Target eksekusi: agent/sesi berikutnya

## 1. Tujuan

Perubahan ini menyelesaikan tiga kebutuhan:

1. Job dengan jenis yang sama tetap serial, tetapi jenis job berbeda dapat berjalan paralel jika tidak memakai resource yang sama.
2. Setiap job yang dibuat dari bot Telegram mempunyai satu pesan status sementara tanpa keyboard. Pesan diperbarui selama job berjalan, menampilkan report saat selesai, lalu dihapus otomatis setelah tiga detik.
3. Pemilihan source pada Export Fokus tidak lagi memenuhi panel dengan satu tombol untuk setiap source. Picker menjadi ringkas, dapat dicari, memiliki pagination, dan aman terhadap callback lama.

Prinsip:

- Antrean ditentukan oleh resource yang dipakai, bukan hanya profile dan bukan hanya string kind.
- Status job/report berasal dari backend API; worker tidak mengetahui komponen UI Telegram.
- Pesan status Telegram adalah adapter UI yang terpisah dari panel utama.
- Tidak ada perubahan Go atau base image TDL dalam pekerjaan ini.

## 2. Temuan dari kode saat ini

### 2.1 Akar masalah antrean

WorkerJobExecutor membuat SerialPerKeyQueue dan memasukkan setiap job dengan key:

~~~python
str(command["profile"])
~~~

Akibatnya semua job pada profile yang sama memakai satu slot serial:

~~~text
download -> export
export   -> utility
utility  -> storage_upload
~~~

Padahal runtime sudah mempunyai dua client TDL:

~~~text
export_tdl_client   -> sesi user1/.tdl
download_tdl_client -> sesi root/.tdl
~~~

Jadi masalah utamanya bukan TDL export dan download, melainkan scheduler worker yang menjadikan profile sebagai lock global.

### 2.2 Resource lock saat ini

| Job | Resource saat ini | Lock saat ini | Dampak |
|---|---|---|---|
| export | export_tdl_client | export_operation_lock | satu lane export |
| leave | leave service/lane export | export_operation_lock | berbagi dengan export |
| download | download_tdl_client | download_operation_lock | seharusnya dapat paralel dengan export |
| storage_upload | export_tdl_client | export_operation_lock | masih menahan export |
| backup_node | uploader export client | lock export dan download lintas runtime | terlalu luas |
| utility | filesystem/workspace | runner per job | perlu path conflict lock |

Storage upload dan backup tidak aman diparalelkan hanya dengan menghapus lock, karena sekarang keduanya berbagi session/SQLite Bolt TDL dengan export.

### 2.3 Notifikasi Telegram

Export Fokus sudah memiliki send_transient, update_transient, delete_transient, dan poller khusus. Jalur job lain hanya menggunakan _show_job dan memperbarui panel. Belum ada lifecycle generik untuk download, utility, storage, backup, leave, inventory, atau operasi asynchronous lain.

### 2.4 Source picker

Telegram Bot API tidak mempunyai native select untuk inline keyboard. Keyboard hanya mendukung tombol. Implementasi sekarang mengirim hingga delapan tombol source dan callback berbasis index list. Ini tidak skalabel dan callback index dapat stale jika daftar berubah.

## 3. Keputusan desain

### 3.1 Aturan concurrency

Gunakan scheduler berbasis exclusive resource key:

1. Dua job dengan resource key sama tidak boleh aktif bersamaan.
2. Job dengan key berbeda boleh aktif bersamaan sampai batas kapasitas worker.
3. “Jenis sama serial” diwujudkan melalui key logis per profile, bukan lock global profile.
4. Job menyimpan worker asal; perubahan route hanya memengaruhi job baru.
5. FIFO dipertahankan per resource group. Priority next tidak melakukan preemption.
6. Backend melakukan admission global; worker menegakkan aturan lagi sebagai defense-in-depth.

### 3.2 Resource key

Gunakan format internal berikut:

~~~text
profile:<profile>:kind:<kind>
profile:<profile>:tdl:export
profile:<profile>:tdl:download
profile:<profile>:workspace:<canonical-path>
worker:<worker>:artifact:<artifact-id>
profile:<profile>:storage-destination:<folder-id>
~~~

Mapping awal:

| Job | Key wajib | Dapat paralel dengan |
|---|---|---|
| export | kind export + tdl export | download, utility path berbeda |
| leave | kind leave + tdl export | download, utility |
| download | kind download + tdl download | export, utility, storage lane |
| utility | kind/path conflict | TDL job dan path utility lain |
| storage_upload | kind storage + storage lane | export jika storage lane terpisah |
| backup_node | kind backup + backup lane | export/download jika terisolasi |
| inventory | inventory key | export; download menunggu inventory |
| artifact delete | artifact/folder key | job yang tidak menyentuh artifact tersebut |

Key kind per profile membuat dua export serial walaupun route worker berubah. Ini mencegah race pada last_id, state source, dan catalog ketika export lama masih berjalan di worker sebelumnya.

### 3.3 Batasan dua sesi TDL

Dengan layout saat ini, yang aman paralel hanya:

~~~text
export/leave -> user1/.tdl
download     -> root/.tdl
~~~

Agar upload dan backup juga paralel dengan export, sediakan lane terpisah:

~~~text
export  -> user1/.tdl
download -> root/.tdl
storage -> storage/.tdl atau storage path terpisah
backup  -> backup/.tdl atau uploader Bot API khusus
~~~

Rekomendasi:

- Implementasikan scheduler lebih dahulu.
- Tambahkan konfigurasi storage_tdl_* dan backup_tdl_* sebagai lane opsional.
- Jika lane belum ada, upload/backup menunggu lane export dengan alasan yang terlihat.
- Jangan membuka Bolt database TDL yang sama dari dua proses.
- Sediakan prosedur satu kali provision/login di setiap worker; ini bukan rebuild Go.

Jika tidak ingin menambah sesi, upload dan backup harus tetap serial dengan export. Itu adalah batasan resource yang valid, bukan kegagalan scheduler.

## 4. Arsitektur scheduler

### 4.1 Execution plan

Tambahkan value object/application service:

~~~text
JobExecutionPlan
├── concurrency_keys
├── queue_group
├── priority
├── lane
└── display_reason
~~~

Tambahkan JobConcurrencyPolicy dengan fungsi plan_export, plan_leave, plan_download, plan_utility, plan_storage_upload, plan_backup, dan plan_artifact_operation.

Payload Telegram seperti chat_id, message_id, dan panel_view_token tidak boleh masuk ke execution plan worker.

### 4.2 Backend admission

Saat ControlPlane.submit_job dipanggil:

1. Validasi actor, profile, route worker, dan payload.
2. Buat execution plan.
3. Simpan job sebagai queued.
4. Acquire semua resource key secara atomik.
5. Jika berhasil, dispatch ke worker dan ubah status menjadi dispatched.
6. Jika konflik, job tetap queued, simpan safe blocked reason, dan jangan dispatch.
7. Saat terminal atau cancelled, release key dan dispatch queue berikutnya.

Aturan ini harus berada di backend agar berlaku lintas VPS. Export lama di remote-1 tetap memblokir export baru di local setelah route berpindah.

### 4.3 Persistensi

Tambahkan migrasi SQLite idempoten:

~~~text
job_execution_plans
├── job_id PRIMARY KEY
├── concurrency_keys_json
├── queue_group
├── priority
├── lane
├── admitted_at
├── released_at
└── blocked_reason

job_resource_leases
├── resource_key PRIMARY KEY
├── job_id
├── acquired_at
└── worker
~~~

Kolom jobs yang disarankan:

~~~text
queue_position
blocked_reason_code
admitted_at
started_at
terminal_at
~~~

Recovery backend:

- lease job terminal dihapus;
- lease nonterminal diverifikasi terhadap job dan worker;
- dispatched tanpa heartbeat/event baru masuk reconciliation;
- queued tanpa lease tetap dapat dipilih;
- status lama tanpa lease/heartbeat tidak boleh dianggap aktif selamanya.

### 4.4 Pending dispatcher dan queue worker

Buat PendingJobDispatcher di backend:

- dipicu setelah event terminal;
- dipicu setelah worker health online;
- memiliki polling fallback;
- memilih job tertua dengan priority valid;
- acquire key dalam satu transaksi;
- jika dispatch gagal, release lease dan kembalikan job ke queued atau failed.

Worker tetap memiliki ResourceAwareQueue untuk duplicate dispatch, restart recovery, perlindungan client TDL, dan queue position lokal. Worker tidak lagi memakai profile sebagai satu-satunya key.

### 4.5 Internal command

Command internal boleh membawa metadata:

~~~json
{
  "job_id": "uuid",
  "kind": "export",
  "profile": "default",
  "worker": "local",
  "execution": {
    "lane": "tdl-export",
    "resource_keys": ["profile:default:tdl:export"],
    "priority": 100
  },
  "payload": {}
}
~~~

Worker memvalidasi plan dan menolak command yang mencoba melewati lane. Metadata ini bukan data UI.

### 4.6 Utility path

Concurrency utility harus:

- resolve semua folder dan memastikan berada dalam /workspace;
- menserialkan path overlap;
- mengizinkan path tidak overlap berjalan paralel;
- menggunakan temp/output directory unik per job;
- memakai lock pendek untuk registry/settings global;
- mengisolasi log dan report.

## 5. Pesan status sementara untuk semua job

### 5.1 Komponen

Buat tme3bot/frontend/telegram/job_notifications.py berisi:

~~~text
JobNotificationRegistry
JobStatusNotifier
format_job_status_message()
format_job_completion_message()
~~~

Primitive PanelManager yang sudah ada tetap dipakai. Lifecycle tidak lagi khusus export.

### 5.2 Jalur submit

Semua jalur Telegram yang membuat asynchronous job memakai helper:

~~~text
submit_telegram_job(...)
├── POST job ke backend
├── register notification subscription
├── update panel utama
├── kirim satu message tanpa keyboard
└── mulai polling notifier
~~~

Cakupan minimal: export, download, retry, clear-failed, utility, storage upload, backup, leave/batch source, inventory/delete, dan job asynchronous lain.

Job dari web, CLI, atau scheduler tidak otomatis mengirim pesan Telegram. Notifikasi dibuat hanya dari subscription Telegram eksplisit.

### 5.3 Subscription persisten

Telegram container tidak me-mount data. Mapping job ke chat harus berada di backend:

~~~text
job_telegram_notifications
├── id
├── job_id
├── telegram_user_id
├── telegram_chat_id
├── profile
├── status pending|terminal|deleted|failed
├── created_at
├── terminal_notified_at
├── message_id
├── last_status_hash
└── error
~~~

Endpoint internal service-authenticated:

~~~text
POST /internal/v1/jobs/{job_id}/telegram-notifications
GET  /internal/v1/telegram-notifications/pending
PATCH /internal/v1/telegram-notifications/{id}
~~~

Validasi:

- FRONTEND_SERVICE_TOKEN valid;
- actor berhak melihat job;
- rollout pertama membatasi private chat chat_id sama dengan user ID;
- satu subscription aktif per job dan chat;
- terminal report memakai unique/idempotency guard.

### 5.4 Format message

Message status tidak memiliki inline keyboard, reply keyboard, atau reply-to panel. Formatter tidak boleh memakai str(dict).

Contoh download aktif:

~~~text
⏳ Download berjalan
Profile: default · Worker: local
Job: 89e337b7-30a
JSON: 1/2 — 1langs_export.json
File: 22/50 — (1).mp4
Progress: 17.8%
Speed: 1.2 MB/dtk · ETA: 15m 35d
Berhasil: 0 · Gagal: 0 · Skipped: 0
~~~

Contoh export selesai:

~~~text
✅ Export selesai
Profile: default · Worker: local
Job: 7cb722ea-406
Message: 26
Media: 10 · Foto: 6 · Video: 4
Latest ID: 7958
Artifact: 1cans_20260725.json
~~~

Utility menampilkan jumlah group/item/archive/bytes yang relevan. Backup menampilkan node, part, ukuran, dan status. Password/token tidak pernah ditampilkan.

### 5.5 Polling

JobStatusNotifier:

1. Kirim satu message setelah job diterima.
2. Poll satu detik saat running.
3. Poll tiga detik saat queued/dispatched.
4. Edit message yang sama hanya ketika status hash berubah atau interval minimal satu detik terpenuhi.
5. Saat terminal, edit menjadi report.
6. Tunggu tiga detik.
7. Hapus best-effort.
8. Tandai terminal_notified_at.

Jika message dihapus user, hentikan update tanpa replacement otomatis. Jika API gagal sementara, pertahankan status terakhir dan retry dengan backoff.

Saat frontend restart, ambil subscription pending. Job terminal yang belum notified diberi satu report. Subscription terminal yang sudah notified tidak boleh mengulang.

Panel utama dan notifier terpisah:

- reset source tidak membatalkan notifier;
- panel dihapus/diganti tidak memengaruhi status message;
- panel_view_token hanya mengontrol panel;
- satu job maksimal satu status message per chat.

## 6. Source picker Export Fokus

### 6.1 Inline picker searchable

Karena tidak ada native select, panel utama cukup menampilkan:

~~~text
Source: 1cans — upfile247bot
[Pilih source] [Source baru]
~~~

Saat Pilih source ditekan, message yang sama berubah:

~~~text
Pilih source
[🔎 Cari source] [Terbaru]
✓ 1cans — upfile247bot
  1langs — blindstorearobot
  1langs — filelink14_bot
  1langs — kenikamatmanmalam_bot
  1langs — kfcmnb_bot
[‹] [Halaman 1/..] [›]
[Kembali ke export]
~~~

Gunakan lima atau enam source per halaman.

### 6.2 Search dan pagination

Cari source masuk ke input sementara. Query mencocokkan label, chat_ref dengan/ tanpa @, case-insensitive, dan numeric ID.

Untuk catalog besar, tambahkan:

~~~text
GET /api/v1/sources?q=upfile&limit=6&offset=0&sort=updated_at
~~~

Urutan default: recently used, recently updated, lalu alfabetis.

### 6.3 Callback stabil

Jangan memakai index seperti ew:s:7. Gunakan source ID backend atau digest pendek canonical chat_ref dan profile:

~~~text
ew:source:<view-token>:<source-digest>
~~~

Callback lama ditolak dengan “Daftar source sudah berubah, refresh picker.” Jangan memilih source berdasarkan index baru.

Memilih source:

- mereset report/detail job panel;
- mereset overwrite start ID;
- menghitung ulang last_id + 1;
- tidak membatalkan job asynchronous lama;
- membiarkan notifier job lama tetap hidup.

### 6.4 Mini App fase berikutnya

Jika source mencapai ratusan dan diperlukan dropdown sungguhan, buat Mini App khusus picker yang memanggil API yang sama dan mengembalikan signed selection. Mini App bukan dependency rollout pertama.

## 7. File/komponen yang diperkirakan

Backend/domain/application:

- tme3bot/domain/models.py
- tme3bot/application/control_plane.py
- tme3bot/application/ports.py
- tme3bot/infrastructure/job_store.py
- tme3bot/application/job_scheduler.py
- tme3bot/api/backend.py
- tme3bot/api/schemas.py

Worker:

- tme3bot/profile_queue.py
- tme3bot/worker/executor.py
- tme3bot/profiles.py
- utility runner dan path locking

Telegram:

- tme3bot/frontend/telegram/job_notifications.py baru
- tme3bot/frontend/telegram/app.py
- tme3bot/frontend/telegram/keyboards.py
- tme3bot/frontend/telegram/export_workspace.py
- formatter report per kind

Konfigurasi/dokumentasi:

- .env.example
- profile layout documentation
- backup manifest
- DEPLOYMENT_RUNBOOK.md

Jika lane tambahan dipilih:

~~~env
JOB_SCHEDULER_MODE=resource
JOB_MAX_PARALLEL=2
JOB_QUEUE_POLL_SECONDS=2
TELEGRAM_JOB_STATUS_ENABLED=true
TELEGRAM_JOB_STATUS_DELETE_SECONDS=3
TDL_STORAGE_HOME=/data/storage
TDL_STORAGE_USER=storage
TDL_BACKUP_HOME=/data/backup
TDL_BACKUP_USER=backup
~~~

## 8. Urutan implementasi

### Milestone 0 — Baseline

- Buat branch khusus.
- Tambahkan regression test queue profile saat ini.
- Tambahkan feature flag profile|resource.
- Catat snapshot job nonterminal sebelum rollout.

### Milestone 1 — Resource queue worker

Implementasikan policy dan ResourceAwareQueue unit-test-first.

Acceptance:

~~~text
export + download             -> running bersamaan
download + download           -> second queued
export + export               -> second queued
utility(path A) + export      -> running bersamaan
utility(A) + utility(A)       -> second queued
~~~

### Milestone 2 — Admission backend lintas worker

- Tambahkan plan/lease SQLite.
- Ubah ControlPlane.submit_job agar tidak selalu langsung dispatch.
- Tambahkan pending dispatcher dan terminal release.
- Tambahkan recovery stale lease.
- Uji perpindahan route saat job lama aktif.

Acceptance:

~~~text
export default di remote-1 aktif
route default pindah ke local
export default baru -> queued sampai export pertama terminal
download default baru -> boleh berjalan jika lane download tersedia
~~~

### Milestone 3 — Dedicated TDL lane

- Provision session storage/backup jika concurrency penuh diwajibkan.
- Ganti storage upload ke storage lane.
- Ganti backup uploader ke backup lane atau provider yang disetujui.
- Hilangkan backup lock lintas export/download.
- Jika lane unavailable, tampilkan WAITING_FOR_TDL_LANE.

### Milestone 4 — Telegram notifier

- Tambahkan subscription API/tabel.
- Generalisasi formatter export.
- Ganti semua asynchronous submit ke helper.
- Uji job cepat/lama, error, cancel, panel berubah, message dihapus, dan restart frontend.

### Milestone 5 — Source picker

- Picker tetap pada satu message tetapi menjadi view terpisah.
- Tambahkan query/pagination.
- Ganti callback index dengan digest/ID.
- Tambahkan recent/search/new source.
- Pastikan reset source tidak menghentikan notifier.

### Milestone 6 — Web dan runbook

- Web menampilkan queue position, blocked reason, lane, dan worker.
- Activity tetap lintas worker.
- Tambahkan indikator menunggu lane TDL.
- Perbarui runbook dan checklist deployment.

## 9. Test plan

Scheduler:

- key berbeda berjalan paralel;
- multiple key satu job di-acquire atomik;
- FIFO per resource group;
- priority next tanpa preemption;
- cancel queued tidak menginterupsi job lain;
- cancel active hanya menginterupsi lane job tersebut;
- duplicate dispatch idempotent;
- worker restart tidak meninggalkan lease palsu;
- job kind sama satu profile serial walau route berubah;
- profile berbeda dapat paralel.

Resource/TDL:

- export dan download profile sama running bersama;
- export dan leave serial pada session export;
- storage tidak membuka TDL export bersamaan tanpa dedicated lane;
- backup tidak mengunci semua runtime setelah refactor;
- utility overlap serial, path berbeda paralel;
- scope worker remote/local benar.

Telegram notifier:

- semua asynchronous kind membuat satu message tanpa keyboard;
- progress mengedit message yang sama;
- completion tidak mengirim message kedua;
- report sukses/gagal/cancel tanpa raw dict;
- delete sekitar tiga detik;
- duplicate polling tidak menggandakan report;
- message dihapus user tidak menyebabkan exception;
- panel reset tidak menghentikan notifier;
- restart frontend menyelesaikan subscription pending satu kali;
- secret tidak masuk status.

Source picker:

- lima/enam source per halaman;
- search label, username normalized, numeric ID;
- pagination tidak salah memilih source;
- callback lama ditolak;
- source baru memakai username/numeric ID;
- 100+ source tetap dapat dicari.

Verifikasi standar:

~~~bash
python -m compileall -q tme3bot utility bot.py run.py
python -m unittest discover -s tests -v
git diff --check
graphify update .
~~~

Jika UI static berubah:

~~~bash
pnpm check
pnpm test
pnpm build
~~~

## 10. Rollout dan rollback

Urutan deploy:

1. Backup SQLite gateway dan state runtime.
2. Deploy backend dengan schema idempoten.
3. Deploy worker-local.
4. Deploy seluruh worker remote.
5. Jalankan preflight lane tiap worker.
6. Aktifkan JOB_SCHEDULER_MODE=resource.
7. Deploy Telegram frontend.
8. Deploy static web jika DTO monitor berubah.
9. Pantau queued jobs, lease, health worker, dan error TDL.

Rollback:

- Matikan mode resource setelah queued job diproses atau dibatalkan aman.
- Jangan menghapus tabel plan/lease.
- Jika lane tambahan gagal, serialkan kembali; jangan membuka Bolt DB yang sama bersamaan.
- Jika notifier gagal, nonaktifkan notifikasi tanpa mengubah lifecycle job.
- Rollback web tidak memengaruhi backend queue.

Perubahan ini berada di Python, SQLite, worker scheduler, Telegram frontend, dan static web. Tidak memerlukan rebuild Go/TDL base.

## 11. Keputusan default untuk agent berikutnya

| Keputusan | Default |
|---|---|
| Scope serial jenis sama | per profile secara global walau worker berbeda |
| Export vs download | paralel menggunakan dua sesi yang ada |
| Export vs leave | serial karena lane export |
| Storage vs export | dedicated storage lane; fallback serial |
| Backup vs job lain | dedicated backup lane; fallback serial saat upload |
| Utility | path overlap serial, path berbeda paralel |
| Notifikasi | hanya job dibuat dari Telegram, satu message per job/chat |
| Durasi report terminal | tiga detik lalu delete |
| Source picker | searchable inline picker + pagination |
| Native select | Mini App fase berikutnya |
| Max parallel default | konservatif, misalnya 2 pada VM kecil |

Jangan menambah paralelisme tanpa menambah sesi TDL untuk storage/backup. Jika lane belum tersedia, tampilkan alasan antrean dan tetap aman.

## 12. Bootstrap VPS baru dan satu-command deployment

### 12.1 Tujuan

Pada VPS baru operator cukup menjalankan:

~~~bash
python3 run.py deploy
~~~

Script harus mendeteksi keadaan mesin dan melanjutkan dari tahap terakhir yang valid. Operator tidak perlu menebak apakah harus install Docker, build base image, login registry, pull image, atau menjalankan compose.

Mode yang disarankan:

~~~bash
python3 run.py check       # hanya pemeriksaan dan rencana
python3 run.py deploy      # bootstrap, validasi, pull/build, lalu up
python3 run.py deploy --yes
~~~

'python3 run.py' tanpa argumen boleh menjadi alias check terlebih dahulu agar tidak mengubah service produksi tanpa konfirmasi.

### 12.2 Preflight tools

Buat PreflightChecker di run.py atau modul utility terpisah. Periksa:

| Tool | Pemeriksaan | Tindakan jika tidak tersedia |
|---|---|---|
| Python 3.10+ | versi interpreter | hentikan dengan instruksi install |
| Git | git --version | install package Git |
| Docker | docker version | install Docker Engine |
| Docker Compose | docker compose version | install Compose plugin |
| curl/wget | download metadata/release | install salah satu |
| 7z | backup/utility host | install p7zip jika diperlukan |
| tar/unzip | extract release | install package |
| openssl | checksum/helper | install OpenSSL |

Aturan installer:

- deteksi distro/package manager (apt, dnf, yum, atau unsupported);
- minta sudo/root hanya ketika perlu;
- jangan menimpa Docker valid;
- ulangi check setelah install;
- log command tanpa mencetak secret;
- jika auto-install tidak didukung, tampilkan command copy-paste;
- jangan menghapus image, volume, atau container lama saat bootstrap.

Preflight juga memeriksa arsitektur, RAM, ruang disk, DNS/HTTPS GitHub dan registry, Docker daemon, permission volume, port compose, dan env role.

### 12.3 Pemeriksaan Git

Baca:

~~~text
git rev-parse --show-toplevel
git rev-parse HEAD
git status --porcelain
git describe --always --dirty
~~~

Aturan:

- deployment memakai commit SHA, bukan hanya latest;
- worktree dirty ditolak kecuali allow-dirty;
- semua service dalam satu rollout harus memakai SHA yang sama;
- image tag utama memakai short/full SHA;
- simpan SHA deployment pada .deploy-state.json tanpa secret.

### 12.4 Deteksi base image

Base image Go/TDL tidak boleh dibangun ulang tanpa alasan. Periksa:

1. Image base lokal dengan tag yang dibutuhkan.
2. Label revision/source dan digest image.
3. Kecocokan BASE_IMAGE_TAG repository.
4. Digest remote jika base registry digunakan.
5. Perubahan Dockerfile/Go module/leave-helper sejak base dibuat.

Klasifikasi:

~~~text
BASE_READY_LOCAL  -> gunakan image lokal
BASE_READY_PULL   -> pull digest cocok
BASE_MISSING      -> minta build di VPS builder besar
BASE_STALE        -> jangan build otomatis di VPS kecil
BASE_UNKNOWN      -> hentikan dan minta verifikasi
~~~

Build base hanya jika --build-base, mesin memenuhi resource minimum, atau metadata release menyatakan base digest baru diperlukan. VPS Oracle kecil default-nya berhenti sebelum build dan menampilkan instruksi builder.

### 12.5 Deteksi app image dan publish terbaru

Untuk gateway, worker, dan web jika masih image compose, cek:

- image tag SHA ada lokal atau di registry;
- digest lokal sama dengan registry;
- manifest cocok dengan arsitektur target;
- label org.opencontainers.image.revision cocok dengan HEAD;
- semua service menggunakan SHA release yang sama.

Status:

~~~text
IMAGE_READY_LOCAL
IMAGE_READY_REGISTRY
IMAGE_MISSING
IMAGE_STALE
IMAGE_UNVERIFIED
~~~

Jangan menganggap tag latest sebagai image terbaru. Query registry memakai manifest/digest tanpa mengunduh layer besar:

1. baca HEAD lokal;
2. query tag short/full SHA;
3. ambil digest manifest;
4. bandingkan semua service;
5. verifikasi revision label;
6. lewati build/publish jika cocok;
7. tandai publish/build hanya jika missing atau stale.

Untuk registry private:

- baca credential dari environment/secret store, bukan argumen command;
- login memakai stdin;
- bedakan unauthorized dari not found;
- jangan mencetak token, Authorization header, atau response sensitif.

Contoh report:

~~~text
Git HEAD:       eebf67407b45
Base image:     READY_LOCAL
Gateway image:  READY_REGISTRY, revision cocok
Worker image:   READY_REGISTRY, revision cocok
Web release:    READY_REGISTRY, revision cocok
Action:         pull + compose up; build/publish dilewati
~~~

### 12.6 State machine run.py

~~~text
CHECK_TOOLS
 -> CHECK_REPOSITORY
 -> CHECK_ENV
 -> CHECK_BASE_IMAGE
 -> CHECK_APP_IMAGES
 -> PULL_OR_BUILD
 -> VERIFY_DIGESTS
 -> START_SERVICES
 -> HEALTHCHECK
 -> SAVE_DEPLOY_STATE
~~~

Perilaku:

- fase yang sudah valid tidak diulang saat rerun;
- --force mengulang fase yang diminta;
- jika gagal, simpan fase terakhir dan alasan;
- START_SERVICES memakai compose/env project yang benar;
- HEALTHCHECK memeriksa backend, worker, Telegram, dan static UI;
- state berisi SHA, digest, timestamp, mode, dan hasil healthcheck, tanpa secret.

### 12.7 Publish di VPS builder

~~~bash
git pull --ff-only
python3 run.py check
python3 run.py publish --all --build-base
~~~

Script publish harus:

- memastikan commit bersih dan SHA diketahui;
- build base satu kali jika diperlukan;
- build app image menggunakan base lokal;
- tag image dengan SHA immutable;
- push gateway/worker ke registry;
- publish static web release bila berubah;
- membuat manifest berisi SHA, image tag, digest, base digest, dan checksum;
- memperbarui alias latest hanya setelah semua artifact SHA terverifikasi.

### 12.8 Deploy pada VPS target baru

1. Install Git dan clone repository.
2. Salin env role ke lokasi yang benar.
3. Jalankan python3 run.py deploy.
4. Script menginstall tools yang belum ada.
5. Script memeriksa base image lokal/registry.
6. Script memeriksa apakah image HEAD sudah dipublish.
7. Jika belum, berhenti dengan instruksi publish di VPS builder.
8. Jika sudah, pull image berdasarkan SHA.
9. Validasi digest.
10. Jalankan compose dan healthcheck.
11. Simpan deployment state.

Target baru tidak boleh otomatis membangun base image berat hanya karena image belum ada lokal.

### 12.9 Static web

Untuk mode static:

- cek artifact release berdasarkan Git SHA;
- verifikasi checksum sebelum extract;
- extract ke release directory baru;
- ubah symlink current secara atomik;
- simpan lima release untuk rollback;
- jangan menjalankan Docker web jika static mode aktif.

Jika web masih compose, validasi image web seperti gateway/worker.

### 12.10 Report dan exit code

run.py check menghasilkan report manusia dan deploy-report.json, tanpa secret.

~~~text
0  siap/sukses
10 tools belum lengkap tetapi dapat diinstall
20 env/repository invalid
30 base image perlu builder
40 image belum dipublish
50 registry unauthorized/unavailable
60 healthcheck gagal
70 deployment state tidak konsisten
~~~

Setiap error harus memuat fase, penyebab, command aman, apakah rerun aman, dan apakah perlu builder atau login registry.

### 12.11 Test tambahan run.py

Tambahkan mock test untuk:

- tool lengkap tidak diinstall ulang;
- tool hilang menghasilkan install plan;
- Docker/Compose hilang menghasilkan instruksi;
- base cocok sehingga build dilewati;
- base hilang pada VPS kecil menghasilkan exit code 30;
- image HEAD tersedia sehingga publish dilewati;
- revision lama menghasilkan IMAGE_STALE;
- unauthorized dibedakan dari not found;
- semua service memakai SHA sama;
- digest lokal dan registry sama;
- dirty worktree ditolak tanpa allow-dirty;
- deployment dapat dilanjutkan dari fase terakhir;
- --force mengulang fase;
- deploy tidak menghapus container/volume lama;
- secret tidak muncul di stdout/report/state;
- static release checksum dan symlink atomik;
- rollback memilih release sebelumnya.

Acceptance operasional:

~~~bash
python3 run.py check
python3 run.py publish --all
python3 run.py deploy
python3 run.py deploy --status
~~~

## Status eksekusi sesi ini

- Scheduler admission backend dan `ResourceAwareQueue` worker sudah diterapkan.
- Export/download pada profile yang sama memakai lane TDL berbeda; lane yang
  berbagi sesi `.tdl` tetap serial untuk mencegah konflik Bolt.
- Pesan status sementara generik untuk job Telegram sudah diterapkan, tanpa
  keyboard, diperbarui pada pesan yang sama, dan dihapus sekitar tiga detik
  setelah terminal.
- Export Fokus memakai picker source terpisah yang searchable, berpaginasi, dan
  callback-nya stabil berdasarkan digest source.
- `run.py` memiliki preflight, bootstrap dependency/tool Linux, pemeriksaan
  image berdasarkan Git SHA, `publish --all`, dan deploy pull tanpa rebuild di
  VPS target.
- Test terarah sudah lulus. Full test dan verifikasi Docker tetap perlu
  dijalankan pada environment yang memiliki Docker/Compose.
