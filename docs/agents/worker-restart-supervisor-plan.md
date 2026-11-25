# Restart worker dari Web

**Status:** implementasi ada di `main`; supervisor host belum dipasang pada host
production. Tombol Web tidak dapat me-restart Docker sampai service systemd
supervisor terpasang dan heartbeat muncul.

## Tujuan

Status event yang terlambat atau hilang tidak boleh menahan job baru ketika
worker masih dapat dijangkau. Jika dua probe baru memastikan worker tidak sehat
atau tidak dapat dijangkau, operator dapat meminta restart service worker dari
Web. Sesudah container dipastikan berhenti, job aktif yang terputus menjadi
`cancelled` dengan hasil tidak pasti; tidak ada retry otomatis.

## Admission dan status event

- Probe background tiap 30 detik hanya memberi status informasi.
- `unknown`, `stale`, keterlambatan event, dan satu probe gagal bukan bukti
  worker mati. Gateway mencoba operasi yang diminta dan membiarkan respons
  worker menentukan hasilnya.
- Jika perlu memastikan health, gateway menjalankan paling banyak dua probe
  ringan. Admission baru ditahan hanya jika kedua probe baru gagal atau worker
  memang dinonaktifkan. Snapshot lama tidak cukup untuk mengarantina worker.
- Job yang progress/event-nya stale tidak dibatalkan otomatis, termasuk saat
  dua probe worker gagal. Gateway mempertahankan job dan resource lease agar
  proses fisik tidak terlihat selesai sebelum supervisor memastikan container
  berhenti.
- Saat operasi restart aktif, gateway menahan admission dan dispatcher untuk
  worker tersebut sampai supervisor melaporkan hasil terminal.
- Worker outbox memadatkan progress lama dan milestone command lama sebelum
  event terminal dikirim, sambil mempertahankan hasil command terbaru per
  runtime/profile, snapshot progress/log terakhir, serta event dengan efek
  samping katalog.

## Supervisor host

Supervisor berjalan sebagai service `systemd` di host Docker. Backend/worker
tidak menerima Docker socket. Supervisor hanya menjalankan `restart_worker`
untuk target allowlist tetap, tanpa shell atau command yang dikirim pengguna.
Supervisor membuat koneksi HTTPS keluar ke gateway setiap sekitar 3 detik dan
menyimpan hasil lokal untuk deduplikasi.

| Worker | Root Compose | Compose file | Service |
| --- | --- | --- | --- |
| `local` | `/www/wwwroot/dockter_bot_tdl` | `docker-compose.gateway.yml` | `worker-local` |
| `remote-1` | `/www/wwwroot/downloads/bot` | `docker-compose.worker.yml` | `worker` |
| `remote-2` | `/www/wwwroot/dockter_bot_tdl` | `docker-compose.worker.yml` | `worker` |

Installer memeriksa label Compose container yang sedang ada dan menolak project,
root, atau service yang tidak cocok. Ia membaca `WORKER_API_TOKEN` dari env file
host tetapi menurunkan token supervisor khusus per worker dengan HMAC; token API
worker tidak disalin ke konfigurasi supervisor. Perubahan/rotasi token worker
mengharuskan supervisor pada host tersebut dipasang ulang.

Jalankan installer hanya dari checkout yang benar, pada host target, setelah
Compose service worker sudah berjalan dan labelnya diverifikasi. Contoh:

```bash
python3 tools/install_worker_supervisor.py --worker local --gateway-url https://ui.utama.naufix.space
python3 tools/install_worker_supervisor.py --worker remote-1 --gateway-url https://ui.utama.naufix.space
python3 tools/install_worker_supervisor.py --worker remote-2 --gateway-url https://ui.utama.naufix.space
```

Perintah tersebut memerlukan root dan mengaktifkan unit
`tme3bot-worker-supervisor@<worker>.service`. Jangan menjalankan installer
untuk worker yang tidak tersedia pada host. Instalasi production belum
dilakukan.

## Alur operator

1. Tombol **Restart worker** menjalankan preflight baru; status UI atau event
   latency saja tidak memulai restart.
2. Konfirmasi muncul hanya setelah dua probe gagal dan heartbeat supervisor
   masih segar. Dialog menunjukkan jumlah job aktif yang terdampak.
3. Gateway membuat satu operasi idempoten per worker. Selama operasi queued atau
   restarting, job baru dan dispatch tertahan untuk worker itu.
4. Supervisor validasi ulang label Docker, menghentikan lalu memulai kembali
   hanya service worker tetap. Aria2, TTS, Redis, dan backend tidak ikut
   direstart.
5. Jika worker tidak merespons karena request lambat namun akhirnya merespons,
   gateway tidak menandai worker mati hanya dari event delay. Probe health
   terpisah yang memutuskan apakah restart tersedia.

## Dampak job

Saat konfirmasi restart dibuat, gateway menyimpan ID job aktif sebagai bukti.
Setelah Docker memastikan worker berhenti, gateway juga mengambil ulang seluruh
job nonterminal untuk worker tersebut agar job yang berlomba masuk selama
preflight tidak tertinggal. Job itu ditandai `cancelled` dengan
`WORKER_RESTARTED`, `outcome_uncertain=true`, dan
`reconciliation_required=true`. Event lama tidak boleh menghidupkan kembali
status terminal. Jika stop gagal dan container masih hidup, job tidak dibatalkan.
Retry tetap manual.

## Keamanan dan kegagalan

- Endpoint supervisor hanya menerima token turunan khusus yang dibandingkan
  secara constant-time; endpoint tetap memakai HTTPS.
- Target Compose, path dan nama service ditetapkan di kode allowlist dan
  diperiksa lagi terhadap label Docker.
- Hanya ada satu operasi restart aktif per worker dan ada batas frekuensi
  restart di supervisor.
- Jika supervisor offline, tombol menjelaskan bahwa restart tidak dapat
  dikirim. Gateway tidak mengaku worker sudah direstart.
- Jika host atau daemon Docker mati, pemulihan host tetap memerlukan akses
  infrastruktur di luar aplikasi.

## Verifikasi

- Unit/integrasi lokal menguji bounded health probes, admission saat snapshot
  stale, pemadatan outbox, fence operasi restart, pembatalan job setelah stop,
  autentikasi supervisor, crash recovery, idempotensi, allowlist Docker, dan
  batas frekuensi.
- UI diuji dengan API mock untuk memastikan restart hanya dapat dikonfirmasi
  sesudah preflight yang valid dan status operasi dapat diikuti.
- Setelah CI dan review lulus, pasang supervisor di satu host staging terlebih
  dahulu; uji health dan restart sebelum memasangnya di host lain. Jangan
  menguji restart pada production tanpa permintaan eksplisit.
