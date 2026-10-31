# TTS Novel: konfigurasi dan rollout

Fitur TTS menerima judul dan teks dari Web, membagi teks menjadi bagian
maksimal 90 karakter, lalu membuat audio memakai tiga helper gTTS. Setiap
helper menjalankan proses Tor sendiri. Secara default backend memilih worker
TTS dengan antrean paling sedikit. Halaman TTS juga bisa memilih worker TTS
tertentu yang siap. Setelah sintesis selesai, worker memakai sesi TDL `user1`
pada profile job untuk mengirim setiap bagian ke satu chat tujuan yang diatur
dari halaman TTS.

Teks lengkap hanya ada pada command internal yang disimpan backend dan dikirim
ke worker. Monitor, event, hasil job, dan log hanya menyimpan judul, jumlah
karakter/bagian, fase, progress, serta status. Worker memakai sesi `.tdl`
profile aktif; bot token tidak dipakai untuk delivery TTS.

## Persiapan

1. Build dan publish image gateway/worker seperti biasa. Image worker sekarang
   memuat dependency helper TTS dan Tor.
2. `.env.telegram` masih perlu memiliki `BOT_TOKEN` bootstrap pada pemasangan
   awal. Setelah login Web, token bot dapat diganti dari **Pengaturan →
   Kredensial Telegram**. Nilai yang disimpan Web menjadi sumber saat backend
   mulai; service Telegram membacanya melalui endpoint internal ketika
   dimulai. Perubahan token dari Web meminta restart backend dan Telegram.
3. Tujuan audio dapat diatur dari kartu **Chat tujuan MP3** di halaman
   **TTS Novel**. Masukkan ID numeric, username, link publik
   `https://t.me/<username>`, atau nomor telepon internasional. Nilai baru
   dipakai job berikutnya tanpa restart container Telegram. Nilai awal dapat
   tetap diisi pada `TELEGRAM_TTS_CHAT_ID` di konfigurasi backend.
4. URL tiga helper dapat diubah dari **Workers → Runtime → Mesin TTS** untuk
   masing-masing worker. Setiap helper menjalankan Tor pada loopback container;
   worker memeriksa `/readyz` dan meminta rotasi lewat `/newnym`. Tidak ada
   password atau control port Tor yang perlu disimpan di Web atau `.env`.
5. Pastikan direktori `/data/tts` termasuk dalam volume data worker agar
   artifact dan checkpoint tetap ada setelah container worker restart.

## Aktifkan helper TTS pada worker

Stack gateway dan worker menjalankan tiga helper TTS pada jaringan Compose
internal masing-masing. `worker-local` memakai nama layanan `tts-1`, `tts-2`,
dan `tts-3` secara default; worker remote memakai nama layanan yang sama pada
stack remote-nya. Jangan mengisi `TTS_HELPER_URLS` dengan string kosong karena
nilai kosong menimpa URL default dan membuat seluruh slot dilaporkan tidak
terjangkau.

Deploy gateway dengan:

```bash
python3 run.py deploy gateway --pull
```

Deploy worker remote dengan:

```bash
python3 run.py deploy worker --pull
```

Kedua deployment menjalankan tiga container helper beserta Tor. Hanya HTTP
helper yang tersedia di jaringan internal Compose; control port Tor tetap
loopback di dalam setiap helper dan tidak diekspos ke container lain atau port
publik host. Jalur Tor memakai circuit terpisah sebagai upaya terbaik; alamat
IP keluarnya tidak diperiksa atau dijamin berbeda.

Worker baru melaporkan capability `tts` setelah ketiga helper merespons
`/readyz`. Gateway mengirim job hanya ke worker dengan capability itu. Job
ditolak bila chat tujuan belum diatur; tidak ada readiness TTS yang bergantung
pada container Telegram.

## Pemeriksaan uji coba

1. Pastikan `tts-1`, `tts-2`, dan `tts-3` sehat, lalu lihat capability worker
   melalui monitor/API worker. Nilai TTS harus aktif.
2. Pada halaman **TTS Novel**, pilih **Otomatis** untuk antrean terpendek atau
   tentukan satu worker TTS tertentu. Buat job kecil, lalu pantau fase antre, sintesis,
   penggabungan, dan pengiriman di monitor.
3. Pastikan jumlah bagian bertambah selama sintesis dan job baru sukses setelah
   TDL profile aktif mengonfirmasi semua upload.
4. Coba Pause ketika sintesis berjalan. Pause berlaku setelah batch maksimal
   tiga request selesai; Resume meneruskan checkpoint yang sudah tersimpan.
5. Pastikan audio masuk ke chat tujuan, lalu pastikan folder artifact job sudah
   dibersihkan dari volume worker. Jika job gagal, buka log job dan gunakan
   Retry setelah penyebabnya diperbaiki.

Setelah satu worker berhasil diuji, readiness TTS berlaku hanya pada worker
yang lolos probe dan canary. Job yang dibuat tetap melekat ke worker asalnya.
