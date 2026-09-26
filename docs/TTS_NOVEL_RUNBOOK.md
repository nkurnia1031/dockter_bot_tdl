# TTS Novel: konfigurasi dan rollout

Fitur TTS menerima judul dan teks dari Web, membagi teks menjadi bagian
maksimal 90 karakter, lalu membuat audio memakai tiga helper gTTS. Setiap
helper menjalankan proses Tor sendiri. Backend memilih worker TTS dengan
antrean paling sedikit. Bot Telegram mengambil audio dari outbox SQLite dan
mengirimkannya ke satu chat tujuan.

Teks lengkap hanya ada pada command internal yang disimpan backend dan dikirim
ke worker. Monitor, event, hasil job, dan log hanya menyimpan judul, jumlah
karakter/bagian, fase, progress, serta status. Bot token hanya berada di
layanan Telegram. Worker tidak menerima token bot atau chat tujuan.

## Persiapan

1. Build dan publish image gateway/worker seperti biasa. Image worker sekarang
   memuat dependency helper TTS dan Tor.
2. Pada gateway, isi `TELEGRAM_TTS_CHAT_ID` di `.env.telegram`. Gunakan ID
   numerik atau username chat yang bisa dikirimi audio oleh bot. Jangan taruh
   nilai ini di file env backend atau worker.
3. Pada `.env.worker.local` atau `.env.worker`, periksa nilai `TTS_HELPER_URLS`,
   `TTS_TOR_CONTROL_HOSTS`, dan `TTS_TOR_CONTROL_PORTS`. Nilai contoh sudah
   menunjuk tiga service Compose `tts-1`, `tts-2`, dan `tts-3`.
4. Pastikan direktori `/data/tts` termasuk dalam volume data worker agar
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
kesiapan hanya jika `TELEGRAM_TTS_CHAT_ID` terisi; endpoint pembuatan job
menolak permintaan bila layanan Telegram belum siap.

## Pemeriksaan uji coba

1. Pastikan `tts-1`, `tts-2`, dan `tts-3` sehat, lalu lihat capability worker
   melalui monitor/API worker. Nilai TTS harus aktif.
2. Buat satu job kecil di menu **TTS Novel**. Pantau fase antre, sintesis,
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
