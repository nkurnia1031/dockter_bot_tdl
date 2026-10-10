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
melalui container lokal agar token tetap berada di environment container:

```bash
docker compose -f docker-compose.worker.yml exec -T worker python3 - <<'PY'
import json
import os
import urllib.request

port = os.environ.get("WORKER_PORT", "8080")
token = os.environ.get("WORKER_API_TOKEN", "")
profile = "default"
request = urllib.request.Request(
    f"http://127.0.0.1:{port}/internal/v1/profiles/{profile}/tdl-diagnostics",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(request, timeout=130) as response:
    print(json.dumps(json.loads(response.read()), sort_keys=True))
PY
```

Untuk worker gateway, gunakan compose file dan service `worker-local` yang
sesuai. Ganti `profile` untuk setiap profil yang sedang diinventarisasi. Output
memuat worker, profil, waktu, status `root` dan `user1`, hasil kecocokan
identitas, serta kode alasan. Nilai Telegram ID, path, dan output TDL tidak
dikembalikan.

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

Contoh setelah image gateway yang memuat verifier dideploy:

```bash
docker compose -f docker-compose.gateway.yml exec -T backend \
  python3 -m tools.verify_profile_backup \
  --run-id RUN_ID \
  --worker remote-1 \
  --profile default \
  --parts-dir /workspace/profile-backups/RUN_ID-remote-1 \
  --tdl-diagnostics-json /workspace/profile-backups/RUN_ID-remote-1/tdl-diagnostics.json
```

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
