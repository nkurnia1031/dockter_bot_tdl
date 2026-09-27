# TTS Novel: konfigurasi dan rollout

Fitur TTS menerima judul dan teks dari Web, membagi teks menjadi bagian
maksimal 90 karakter, lalu membuat audio memakai tiga helper gTTS. Setiap
helper menjalankan proses Tor sendiri. Secara default backend memilih worker
TTS dengan antrean paling sedikit. Halaman TTS juga bisa memilih worker TTS
tertentu yang siap. Bot Telegram mengambil audio dari outbox SQLite dan
mengirimkannya ke satu chat tujuan yang ID-nya diatur dari halaman TTS.

Teks lengkap hanya ada pada command internal yang disimpan backend dan dikirim
ke worker. Monitor, event, hasil job, dan log hanya menyimpan judul, jumlah
karakter/bagian, fase, progress, serta status. Bot token hanya berada di
layanan Telegram. Worker tidak menerima token bot atau chat tujuan.

## Persiapan

1. Build dan publish image gateway/worker seperti biasa. Image worker sekarang
   memuat dependency helper TTS dan Tor.
2. `.env.telegram` masih perlu memiliki `BOT_TOKEN` bootstrap pada pemasangan
   awal. Setelah login Web, token bot dapat diganti dari **Pengaturan →
   Kredensial Telegram**. Nilai yang disimpan Web menjadi sumber saat backend
   mulai; service Telegram membacanya melalui endpoint internal ketika
   dimulai. Perubahan token dari Web meminta restart backend dan Telegram.
3. Tujuan audio dapat diatur dari kartu **Chat tujuan MP3** di halaman
   **TTS Novel**. Masukkan ID numeric, username, atau link publik
   `https://t.me/<username>`, lalu restart container Telegram agar perubahan
   aktif. Tujuan harus dapat dijangkau bot. Bot API tidak mengirim berdasarkan
   nomor telepon. Nilai awal dapat tetap diisi pada `TELEGRAM_TTS_CHAT_ID` di
   `.env.telegram`.
4. URL helper dan host/port control Tor dapat diubah dari **Workers → Runtime
   → Mesin TTS** untuk masing-masing worker. Nilai `.env.worker.local` atau
   `.env.worker` tetap menjadi bootstrap/fallback; perubahan Web berlaku pada
   job TTS berikutnya.
5. Pastikan direktori `/data/tts` termasuk dalam volume data worker agar
   artifact dan checkpoint tetap ada setelah container worker restart.

## Aktifkan satu worker untuk uji coba

Aktifkan profile Compose `tts` hanya pada satu host worker terlebih dahulu.
Untuk gateway, jalankan deployment dengan profile tersebut:

```bash
COMPOSE_PROFILES=tts python3 run.py deploy gateway --pull
```

Untuk VPS worker terpisah, gunakan:

```bash
COMPOSE_PROFILES=tts python3 run.py deploy worker --pull
```

Gunakan perintah worker hanya pada host yang env worker-nya memiliki konfigurasi
helper dan volume data TTS. Profile tersebut menjalankan tiga container helper
beserta Tor; port helper hanya diekspos ke jaringan internal Compose, bukan ke
port publik host. Jalur Tor memakai circuit terpisah sebagai upaya terbaik;
alamat IP keluarnya tidak diperiksa atau dijamin berbeda.

Worker baru melaporkan capability `tts` setelah ketiga helper merespons
`/readyz` dan ketiga port kontrol Tor dapat dijangkau. Gateway mengirim job
hanya ke worker dengan capability itu. Proses Telegram mengirim heartbeat
kesiapan hanya jika chat tujuan audio terisi; endpoint pembuatan job
menolak permintaan bila layanan Telegram belum siap.

## Pemeriksaan uji coba

1. Pastikan `tts-1`, `tts-2`, dan `tts-3` sehat, lalu lihat capability worker
   melalui monitor/API worker. Nilai TTS harus aktif.
2. Pada halaman **TTS Novel**, pilih **Otomatis** untuk antrean terpendek atau
   tentukan satu worker TTS tertentu. Buat job kecil, lalu pantau fase antre, sintesis,
   penggabungan, dan pengiriman di monitor.
3. Pastikan jumlah bagian bertambah selama sintesis dan job baru sukses setelah
   Telegram mengonfirmasi semua audio.
4. Coba Pause ketika sintesis berjalan. Pause berlaku setelah batch maksimal
   tiga request selesai; Resume meneruskan checkpoint yang sudah tersimpan.
5. Pastikan audio masuk ke chat tujuan, lalu pastikan folder artifact job sudah
   dibersihkan dari volume worker. Jika job gagal, buka log job dan gunakan
   Retry setelah penyebabnya diperbaiki.

Setelah satu worker berhasil diuji, aktifkan profile `tts` dan helper pada
worker lain satu per satu. Job yang dibuat tetap melekat ke worker asalnya.
