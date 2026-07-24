# tme3bot Agent Context

Dokumen onboarding singkat untuk agent baru.

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
- Route worker dipilih per profile dan disimpan di `worker_routes.json`; jangan
  mengubah worker di tengah job profile karena folder export berada di worker
  yang dipilih. `state.json` gateway adalah sumber kebenaran lintas VPS untuk
  source, `last_id`, label, dan warmup.

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

- Download: profile berbeda paralel, profile sama serial melalui `SerialPerKeyQueue`.
- Utility: folder berbeda paralel, folder sama serial.
- Jangan membuka database Bolt `.tdl` yang sama dari dua proses bersamaan.
- Async panel wajib memakai `panel_view_token` agar panel lama tidak hidup kembali.
- Metadata panel tidak boleh masuk payload job worker. Progress worker harus
  dikirim sebagai event JSON idempotent `job_id + sequence`; frontend melakukan
  polling public job API.

## Utility

Host `/www/wwwroot/downloads` di-mount ke `/workspace`. Daftar global berada di `/data/utility_folders.json`, dengan default `/workspace/biasa`, `/workspace/pilihan`, dan `/workspace/downloads`.

Adapter utility selalu memakai absolute path script, `cwd` folder target, stdout/stderr ke Docker log, dan exit code non-zero sebagai failure. Export terdiri dari converter HTML ke JSON lalu organizer media. Compress mempertahankan password hardcoded dan `-sdel`. Extract memakai nama folder sebagai password default atau password dari bot.

## Operasional

```bash
python3 run.py up
python3 run.py update
python3 run.py logs
python3 run.py shell
python3 run.py cleanup
```

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
