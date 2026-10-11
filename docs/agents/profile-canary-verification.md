# Verifikasi sesi TDL dan arsip backup untuk canary

Dokumen ini menjelaskan bukti lokal yang diperlukan sebelum memilih pasangan
profil-worker untuk canary vault. Perintah di sini hanya membaca sesi dan
arsip; tidak mengadopsi, memasang, atau memulihkan sesi. Jangan mengirim hasil
diagnosis yang belum lolos ke issue sebagai bukti kesiapan.

## Diagnosis sesi pada worker

Worker menyediakan endpoint internal read-only:

```text
GET /internal/v1/profiles/{profile}/tdl-diagnostics
```

Endpoint memakai autentikasi worker yang sudah ada. Jalankan dari host worker
melalui container lokal agar token tetap berada di environment container.
Jalankan perintah dari root repository. Pada VPS worker mandiri, Compose perlu
membaca `.env.worker` untuk interpolasi `PROFILE_ROOT` pada mount `/data`;
`env_file` milik service baru dimuat setelah interpolasi Compose, jadi tidak
cukup hanya mengandalkan `env_file` tersebut. Gunakan opsi env yang sama untuk
perintah `ps`, `exec`, atau perintah Compose lain pada deployment ini.
Field `worker` pada hasil diagnosis berasal dari `BACKUP_NODE_NAME` di env
worker, bukan dari nama host yang dideteksi otomatis. Nilai itu juga menjadi
label node backup. Cocokkan dengan nama worker dan node backup yang benar
sebelum memakai hasilnya; jangan mengedit JSON hasil untuk mengganti label.

```bash
docker compose --env-file .env.worker -f docker-compose.worker.yml exec -T worker python3 - <<'PY'
import json
import os
import urllib.request

port = os.environ.get("WORKER_PORT", "8080")
token = os.environ.get("WORKER_API_TOKEN", "")
profile = "default"
expected_worker = "remote-1"  # ganti dengan nama worker yang sedang diperiksa
request = urllib.request.Request(
    f"http://127.0.0.1:{port}/internal/v1/profiles/{profile}/tdl-diagnostics",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(request, timeout=130) as response:
    result = json.loads(response.read())
if result.get("worker") != expected_worker:
    raise SystemExit("Nama worker hasil diagnosis tidak cocok; periksa BACKUP_NODE_NAME.")
print(json.dumps(result, sort_keys=True))
PY
```

Untuk worker gateway, gunakan konfigurasi host `.env` dan service
`worker-local`; Compose memuat `.env.worker.local` ke container melalui
`env_file` service. Contoh command-nya:

```bash
docker compose --env-file .env -f docker-compose.gateway.yml exec -T worker-local python3 - <<'PY'
import json
import os
import urllib.request

port = os.environ.get("WORKER_PORT", "8080")
token = os.environ.get("WORKER_API_TOKEN", "")
profile = "default"
expected_worker = "local"  # ganti dengan nama worker yang sedang diperiksa
request = urllib.request.Request(
    f"http://127.0.0.1:{port}/internal/v1/profiles/{profile}/tdl-diagnostics",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(request, timeout=130) as response:
    result = json.loads(response.read())
if result.get("worker") != expected_worker:
    raise SystemExit("Nama worker hasil diagnosis tidak cocok; periksa BACKUP_NODE_NAME.")
print(json.dumps(result, sort_keys=True))
PY
```

Ganti `profile` untuk setiap profil yang sedang diinventarisasi. Pada kedua
contoh, token dibaca dari environment container dan tidak perlu disalin ke
command. Output memuat worker, profil, waktu, status `root` dan `user1`, hasil
kecocokan identitas, serta kode alasan. Nilai Telegram ID, path, dan output TDL
tidak dikembalikan.

Pemeriksaan mengambil lock export lalu download secara non-blocking, sama
seperti operasi profil. Jika salah satu sesi sibuk hasilnya
`PROFILE_SESSION_BUSY`; ulangi saat worker idle. Pemeriksaan menolak sesi
tanpa file Bolt namespace yang sudah ada sebelum memanggil `tdl-leave`, karena
helper tersebut dapat membuat database baru ketika membuka path kosong.
Perintah `--whoami` dijalankan sekali untuk masing-masing sesi menggunakan
user, home, namespace, dan storage yang aktif. Output identitas dibuat di
direktori sementara privat dan langsung dibersihkan.

## Verifikasi arsip backup yang diunduh manual

Belum ada jalur aplikasi yang aman untuk mengunduh semua bagian backup terpilih
dari Telegram. Unduh bagian arsip secara manual, lalu tempatkan semuanya pada
satu direktori yang tersedia dari container backend sebagai `/workspace/...`.
Simpan JSON diagnosis worker dari langkah sebelumnya sebagai file pendamping
di workspace. Verifier membaca ukuran dan SHA-256 dari `storage.db`, password
dari `utility_settings.json`, serta JSON diagnosis tersebut; ia tidak menerima
password sebagai argumen.

Caption Telegram hanya menampilkan 12 karakter awal `run_id`; ambil `run_id`
lengkap dari `python3 run.py backup status` di gateway atau daftar backup Web.
Setiap `node_name` memiliki arsip sendiri meskipun `run_id`-nya sama. Untuk
`--worker remote-2`, gunakan semua part `remote-2` dari run tersebut saja;
part `backend` bukan kelanjutan arsip worker. Pastikan indeks part lengkap
sesuai katalog sebelum menjalankan verifier.

Contoh setelah image gateway yang memuat verifier dideploy. Ganti nilai
`FULL_RUN_ID_FROM_BACKUP_STATUS` dengan run ID lengkap sebelum menjalankan;
guard di bawah mencegah placeholder dipakai tanpa sengaja:

```bash
RUN_ID='FULL_RUN_ID_FROM_BACKUP_STATUS'
WORKER='remote-2'
PROFILE='default'
PARTS_DIR="/workspace/profile-backups/${RUN_ID}-${WORKER}"
TDL_JSON="${PARTS_DIR}/tdl-diagnostics.json"

if [ "$RUN_ID" = 'FULL_RUN_ID_FROM_BACKUP_STATUS' ]; then
  echo 'Ganti RUN_ID dengan nilai lengkap dari katalog backup.' >&2
  exit 2
fi

docker compose --env-file .env -f docker-compose.gateway.yml exec -T backend \
  python3 -m tools.verify_profile_backup \
  --run-id "$RUN_ID" \
  --worker "$WORKER" \
  --profile "$PROFILE" \
  --parts-dir "$PARTS_DIR" \
  --tdl-diagnostics-json "$TDL_JSON"
```

`.env` menyediakan nilai host untuk interpolasi Compose. Service `backend`
sendiri tetap memuat `.env.backend` melalui `env_file`; jangan menaruh password
backup pada command line atau menampilkan isi file env. Set `RUN_ID` ke ID
lengkap dari satu run nyata dan `WORKER` ke node yang arsipnya diperiksa. Nilai
`--worker` harus cocok dengan label worker pada JSON diagnosis dan node backup
di katalog. Jika salah satu tidak cocok, verifier akan berhenti sebelum
menyatakan arsip valid.

Jika menjalankan verifier dari environment lokal, pasang dependensi opsional
dengan `python -m pip install -r requirements-verifier.txt`, lalu berikan
`--catalog-db` dan `--settings-file` yang menunjuk salinan privat yang sah.
Jangan menaruh file settings atau password di repository, workspace bersama,
terminal transcript, atau issue.

Verifier memerlukan run berstatus lengkap dan semua part aktif yang memiliki
ukuran serta SHA-256 katalog. Ia menghitung checksum tiap part, memerlukan
ruang sementara sebesar gabungan part, menyatukan part di temp privat, lalu
menguji dekripsi dan integritas. Hanya `backup-manifest.json` yang diekstrak ke
temp privat setelah seluruh path arsip diperiksa. Ia memastikan manifest cocok
dengan run/worker terpilih dan memuat file namespace Bolt di kedua sesi profil
yang diminta. Semua temp dihapus setelah selesai. Tidak ada perintah restore.

Output adalah satu objek JSON aman berisi hasil TDL dan backup, termasuk waktu
diagnosis, status tiap sesi, kecocokan identitas, run, timestamp, checksum,
dekripsi, dan kelengkapan sesi arsip. `status=verified` berarti backup lolos;
`canary_evidence_status=ready_for_operator_review` berarti diagnosis TDL juga
lolos. Ini belum menyetujui canary secara otomatis. Simpan objek JSON ke
matriks issue tanpa menambahkan session ID, credential, path, atau isi arsip.
