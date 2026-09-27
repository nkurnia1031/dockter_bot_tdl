# Pengaturan aplikasi dari Web

Dokumen ini memetakan pengaturan yang bisa diubah setelah container dibuat.
Pengaturan aplikasi semestinya dikelola dari Web. Pengaturan mesin dan Docker
tetap dikelola melalui deployment karena proses yang sedang berjalan tidak
bisa mengganti port, mount, atau binary host sendiri.

## Pengaturan yang sudah ada di Web

| Pengaturan | Lokasi | Penyimpanan dan dampak |
| --- | --- | --- |
| Alamat API worker, token API worker, status aktif, dan route profile | Workers | Registry gateway; berlaku untuk penerimaan job baru |
| Batas job Quick Mode yang aktif bersamaan | Quick Mode | Database gateway; mengatur antrean Quick Mode |
| Folder Utility, ukuran pindah/arsip, tujuan rclone, dan password arsip | Utility / Pengaturan | File pengaturan Utility pada volume data; dipakai job berikutnya |
| Folder, metadata, dan operasi Storage | Storage | Database Storage gateway |
| Profil sesi TDL Storage per worker | Workers / Runtime | `worker_settings.json` pada volume worker; dipakai job Storage dan Quick Mode berikutnya |
| URL tiga helper gTTS dan retry/backoff TTS | Workers / Runtime / Mesin TTS | `worker_settings.json` pada volume worker; dipakai job TTS baru |
| Watchdog job, timeout stall export TDL, dan timeout stall download TDL per worker | Workers / Runtime / Timeout job worker | `worker_settings.json` pada volume worker; berlaku untuk job berikutnya dan tidak bisa diubah saat ada job aktif |
| Jadwal, tujuan channel, retensi, dan ukuran arsip backup; retensi Trash Storage; watchdog/cancel job | Backup | `app_runtime_settings.json` pada volume gateway; langsung berlaku |
| Token bot Telegram | Pengaturan / Kredensial Telegram | `app_runtime_settings.json` pada volume gateway; tulis-saja, restart backend/Telegram |
| ID chat atau username tujuan audio TTS | TTS Novel / Chat tujuan MP3 | `app_runtime_settings.json` pada volume gateway; tulis-saja, restart Telegram |

Form yang meneruskan referensi ke TDL menerima `@username`, `username`, ID
numeric, link publik `https://t.me/<username>`, dan nomor telepon internasional
seperti `+1 123456789`. Tujuan TTS dan backup dikirim lewat Bot API, sehingga
menerima ID numeric atau username/link publik; nomor telepon tidak dapat
dipakai sebagai tujuan Bot API.

Pengaturan Storage dan TTS dipisah per worker karena sesi `.tdl` dan helper
tersedia pada mesin worker tertentu. Setiap helper menjalankan Tor lokal dan
menyediakan pemeriksaan serta rotasi circuit melalui HTTP internal. Mengganti konfigurasi tidak
memindahkan job yang sudah ditempatkan. Pengubahan profil Storage ditolak
selama job Storage atau Quick Mode berjalan; pengubahan TTS ditolak selama job
TTS berjalan.

## Pengelolaan rahasia

Rahasia yang sudah memiliki form Web dapat ditulis atau diganti setelah login.
Browser tidak menerima nilai yang sudah tersimpan: API hanya mengembalikan
status seperti `sudah diatur`. Worker TTS tidak memerlukan password Tor; control
port hanya listen pada loopback masing-masing helper.

Token bot dan tujuan audio TTS disimpan pada file runtime gateway. Telegram
membaca keduanya melalui endpoint internal ketika proses Telegram dimulai.
Mengganti token bot memerlukan restart backend dan Telegram; mengganti tujuan
TTS memerlukan restart Telegram. API Web hanya menampilkan status configured.
Token API worker bisa dirotasi dari form Edit Worker saat alamat worker tidak
berubah. Gateway mengirim token baru melalui koneksi lama yang terautentikasi,
worker memberi overlap token lama maksimal lima menit, lalu registry gateway
menggunakan token baru. Kolom token kosong mempertahankan token yang ada.

Pola ini berlaku untuk rahasia aplikasi yang sudah dipindahkan ke form Web.
Belum semua secret ada di sana. Token internal antar-service, secret login,
credential rclone, serta secret lain yang dibaca lebih dari satu container
masih perlu migrasi khusus. Untuk token lintas-service, Web harus menunjukkan
layanan yang terdampak dan urutan restart/rotasi sebelum nilainya dianggap
aktif. Jangan membuat endpoint yang mengembalikan nilai rahasia lama.

## Status migrasi konfigurasi

Konfigurasi masih tersebar antara `.env`, form fitur, registry worker, dan
file data. Jadi belum semua key environment tersedia di Web. Prioritas
migrasi berikutnya:

1. Timeout dan interval untuk menyelesaikan upload TDL yang masih memakai
   environment worker.
2. Token internal lintas-service serta secret autentikasi, disertai rotasi
   terkoordinasi dan status layanan yang perlu restart.
3. Pengaturan channel Storage per worker dan credential rclone yang masih
   berada di file konfigurasi mesin.

Setiap form harus menyatakan apakah perubahan langsung berlaku, hanya berlaku
untuk job baru, atau baru aktif setelah restart. Pengaturan yang terkait satu
job sebaiknya diambil sebagai snapshot ketika job dibuat.

## Pengaturan deployment

Nilai berikut tetap menjadi konfigurasi deployment karena memerlukan perubahan
container atau host:

- `APP_ROLE`, port, bind address, hostname layanan dan alamat backend;
- mount volume, direktori host, path data, dan path binary;
- image Docker, paket sistem, serta konfigurasi jaringan/container;
- kredensial registry image dan secret CI/CD.

Web boleh menyediakan alur deployment untuk mengubah nilai tersebut di masa
depan, tetapi perubahan itu harus membuat deployment baru dan menunjukkan
restart yang diperlukan. Mengubahnya di proses aplikasi saja tidak akan
mengubah port, mount, atau resource container yang sudah dibuat.

## Kontrak implementasi

- Sediakan field yang tervalidasi per pengaturan; jangan menambahkan editor
  bebas untuk seluruh environment.
- Simpan setting yang berubah saat runtime pada volume persisten.
- Rahasia hanya bisa ditulis, dihapus, atau diganti. Jangan kembalikan nilainya
  ke Web dan jangan masukkan ke log maupun payload monitor.
- Gunakan autentikasi Web yang sudah ada. Endpoint worker hanya dapat dicapai
  backend dengan token internal.
- Tampilkan status penerapan: langsung, job baru, atau setelah restart.
- Pertahankan `.env` sebagai bootstrap/fallback selama migrasi; hapus suatu key
  hanya setelah seluruh role yang memakainya membaca penyimpanan terkelola.
