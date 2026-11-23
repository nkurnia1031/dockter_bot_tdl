# Restart worker dari Web: rencana

**Status:** rencana disimpan untuk dilanjutkan nanti. Pengguna menyetujui
rencana ini untuk dicatat, tetapi belum meminta spec, tiket, implementasi,
deployment, atau restart production.

## Tujuan

Operator dapat meminta restart worker tertentu dari Web tanpa login ke VPS
atau menjalankan SSH. Jalur kontrol tetap bekerja ketika API atau event loop
worker macet.

## Fakta implementasi saat ini

- Gateway mengirim job dan kontrol worker melalui HTTP dispatcher yang
  terautentikasi.
- Backend gateway dan container worker tidak memiliki Docker socket.
- Worker Compose memakai `restart: unless-stopped`, tetapi gateway belum punya
  perintah untuk me-restart seluruh service worker.
- Recovery helper TTS hanya me-restart helper TTS, bukan worker.
- Target Docker yang ada: `worker-local` pada Compose gateway, dan service
  `worker` pada Compose masing-masing remote.

## Arsitektur yang disarankan

Pasang supervisor host kecil sebagai service `systemd` pada setiap host Docker:

- VPS gateway: hanya mengelola Compose service `worker-local`.
- VPS `remote-1`: hanya mengelola Compose service `worker`.
- VPS `remote-2`: hanya mengelola Compose service `worker`.

Mapping checkout yang diketahui saat rencana ini ditulis:

| Host | Root Compose | Compose file | Service |
| --- | --- | --- | --- |
| Gateway / `worker-local` | `/www/wwwroot/dockter_bot_tdl` | `docker-compose.gateway.yml` | `worker-local` |
| `remote-1` | `/www/wwwroot/downloads/bot` | `docker-compose.worker.yml` | `worker` |
| `remote-2` | `/www/wwwroot/dockter_bot_tdl` | `docker-compose.worker.yml` | `worker` |

Saat supervisor dipasang nanti, validasi project Compose aktual dari label
container di host tersebut dan simpan mapping tetapnya dalam konfigurasi lokal
supervisor. Jangan menebak project dari nama checkout atau memakai direktori
repo yang kebetulan sama.

Supervisor berjalan terpisah dari container worker dan memakai koneksi HTTPS
keluar yang terautentikasi untuk mengambil perintah dari gateway. Tidak perlu
membuka port supervisor ke internet. Untuk gateway-local, supervisor berada di
host yang sama tetapi tetap terpisah dari backend dan worker.

Supervisor hanya menerima operasi restart untuk target Compose tetap dari
konfigurasinya. Nama project, root Compose, dan nama service tidak berasal dari
request pengguna. Supervisor tidak menyediakan shell atau perintah Docker
generik. Jangan memasang Docker socket ke backend atau worker. Akses Docker
host tetap berprivilege tinggi, jadi kode supervisor harus kecil, diaudit,
mencatat operasi, dan membatasi satu restart aktif per worker.

## Alur operator

1. Halaman Workers menampilkan aksi **Restart worker**. Aksi tetap tersedia
   saat Worker API tidak merespons, selama supervisor host masih terhubung.
2. Konfirmasi menunjukkan worker terpilih dan jumlah job aktif yang akan
   terputus. Hanya satu operasi restart per worker boleh berjalan pada satu
   waktu; operasi duplikat menggunakan ID idempotensi yang sama.
3. Gateway mencatat operasi restart, menahan dispatch baru untuk worker itu,
   lalu mengantrikan perintah bagi supervisor yang terikat ke worker tersebut.
   Status restart memakai state terpisah; jangan mengubah `enabled` worker,
   karena `enabled` adalah kontrol admission permanen operator.
4. Supervisor mengambil perintah, memeriksa target allowlist, lalu menjalankan
   restart Compose hanya pada service worker yang ditetapkan. Helper TTS,
   Aria2, Redis, dan service lain tidak ikut direstart.
5. Supervisor melaporkan hasil tindakan. Gateway memeriksa kembali health
   worker sebelum melepas penahanan dispatch.
6. UI menampilkan status `diminta`, `sedang restart`, `siap`, atau `gagal`,
   beserta alasan aman bila supervisor tidak dapat dijangkau.

## Dampak job

Sebelum perintah dijalankan, gateway mengambil daftar job nonterminal yang
terikat ke worker. Setelah supervisor mengonfirmasi container worker benar-benar
direstart, job yang terputus ditandai `cancelled` dengan hasil tidak pasti
karena efek eksternal mungkin sudah terjadi. Bila restart gagal sebelum worker
berhenti, job tidak diterminalkan oleh operasi restart. Job tidak dilanjutkan
atau di-retry otomatis setelah restart. Retry tetap manual dan hanya tersedia
untuk jenis job yang sudah mendukung retry.

Event terlambat dari worker yang baru hidup tidak boleh menghidupkan kembali
job terminal. Simpan sebagai hasil terlambat untuk rekonsiliasi/audit bila
kontrak job mendukungnya. Worker tetap dikarantina bila restart berhasil tetapi
health check belum pulih; lepaskan karantina hanya setelah worker sehat.

## Keamanan dan kegagalan

- Gunakan kredensial supervisor terpisah per host, autentikasi TLS, masa berlaku
  perintah, ID idempotensi, dan audit tanpa mencatat rahasia.
- Supervisor menolak target yang tidak ada di konfigurasi tetapnya dan
  membatasi frekuensi restart.
- Bila supervisor offline, UI menyatakan perintah tidak terkirim; gateway tidak
  mengklaim worker sudah direstart.
- Bila VPS atau Docker daemon host mati, supervisor tidak bisa menjalankan
  restart. Kondisi itu tetap memerlukan pemulihan host di luar aplikasi.
- Jangan membuat retry job otomatis sebagai bagian dari restart.

## Verifikasi yang direncanakan untuk tahap implementasi

- Tes supervisor memakai adapter Docker palsu: target allowlist, penolakan
  target bebas, idempotensi, batas frekuensi, dan status hasil.
- Tes gateway dengan supervisor palsu: otorisasi operator, satu operasi aktif
  per worker, antrean/ack, timeout supervisor, job terdampak, dan tidak ada
  retry otomatis.
- Tes UI dengan API mock: restart saat worker sehat maupun tidak merespons,
  konfirmasi dampak job, status operasi, serta pesan saat supervisor offline.
- Uji staging satu worker lebih dahulu. Lanjutkan ke host lain setelah restart
  dan health check terverifikasi.

## Batas rencana

Dokumen ini mencatat arsitektur yang disarankan untuk kelanjutan. Dokumen ini
bukan tiket atau izin untuk membuat tiket, mengubah source, memasang supervisor,
menjalankan restart, atau deploy. Tunggu permintaan lanjutan pengguna sebelum
memasuki tahap tersebut.
