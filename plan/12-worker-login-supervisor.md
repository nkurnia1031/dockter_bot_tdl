# 12 — Supervisor login TDL yang tidak bergantung pada browser

## Tujuan

Pisahkan supervisor lifecycle dari method state(). Supervisor background menguras PTY, mendeteksi prompt/exit, menjalankan validasi identitas, dan mengirim event melalui journal task 09.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task P1, 09, 10 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

ProfileSessionManager menggunakan _LoginProcess, PTY dan dict _logins; state() menguras PTY dan memeriksa exit. _finish_if_exited dapat memanggil whoami dengan timeout panjang. Startup membersihkan direktori login tertinggal, sehingga hasil login bisa hilang sebelum backend mengambilnya.

Task ini juga mengubah Worker API. Jangan menghapus atau menggabungkan endpoint diagnosis/recovery helper TTS P1 ke alur login; auth worker, target slot tetap, dan lifecycle Tor harus tetap terpisah.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/worker/profile_sessions.py` |
| Diubah | `tme3bot/api/worker.py` |
| Diubah | `tme3bot/worker/executor.py` |
| Diubah | `tests/test_profile_provisioning.py` |
| Diubah | `tests/test_worker_api.py` |
| Baru | `tme3bot/worker/login_supervisor.py` |
| Baru | `tests/test_login_supervisor.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

Command profile.login.start/input/renew/cancel memuat operation_id+attempt; input input_id+type+value hanya pada jalur privat TLS. GET worker state hanya snapshot murah. Event publik login hanya phase, method, expiry dan metadata identitas yang diizinkan.

## Spesifikasi implementasi

1. Pisahkan supervisor lifecycle dari method state(). Supervisor background menguras PTY, mendeteksi prompt/exit, menjalankan validasi identitas, dan mengirim event melalui journal task 09.
2. Persist operation/attempt metadata, phase, deadline dan referensi direktori privat. Challenge aktif adalah attempt sementara; setelah proses restart jangan berpura-pura melanjutkan PTY yang sudah hilang.
3. Tambahkan command start, input, renew, cancel dengan attempt dan input ID idempotent. QR/code/2FA dipetakan ke form terkontrol; tidak ada shell/terminal bebas. Input rahasia tidak berada di event atau transcript log.
4. QR token dikirim melalui private challenge result milik actor, disimpan terenkripsi/berumur terbatas di backend task 13. Worker tidak menulis QR/token/phone ke log. Hilangkan buffer rahasia setelah dipakai; duplikat input tidak ditulis ke PTY dua kali.
5. Expiry dan restart mengubah phase menjadi waiting_user/renew_required. Renew manual membatalkan attempt lama dan membuat attempt baru dalam operation yang sama; tidak auto renew atau replay OTP/2FA.
6. Setelah login sukses simpan bundle tervalidasi sampai vault ACK; startup memulihkan completed result yang belum diambil. Cleanup hanya setelah ACK/cancel, dengan lock dan batas path aman.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 12: Supervisor login TDL yang tidak bergantung pada browser.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: P1, 09, 10.
2. Periksa fungsi dan kontrak pada bagian Konteks. Gunakan graphify query terlebih
   dahulu untuk relasi kode, lalu source aktual. Jangan membuka nilai secret.
3. Ikuti seluruh langkah bernomor pada Spesifikasi implementasi dalam file ini.
   Gunakan apply_patch, Python 3.10 dan batas domain/application/infrastructure.
   Daftar File yang disentuh adalah allowlist lengkap. Jangan mengubah file lain;
   jika benar-benar diperlukan, catat alasan dan status terblokir, jangan memperluas
   cakupan atau mengerjakan task berikutnya.
4. Pertahankan API legacy/gate sesuai kontrak. Jangan deploy, publish, commit,
   mengakses production, mengirim Telegram nyata, atau menjalankan migrasi data nyata.
5. Tambahkan/uji skenario Kriteria selesai dengan mock/fixture lokal. Jalankan
   seluruh Cara verifikasi. Catat kegagalan atau tool tidak tersedia secara jujur.
6. Periksa diff agar hanya perubahan task ini dan output tool yang diizinkan.
   Perbarui HANYA baris 12 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Login selesai tanpa satu pun GET browser tetap divalidasi dan dilaporkan.
- whoami lambat tidak membuat GET/start HTTP menunggu.
- QR expired/restart memerlukan renew; attempt lama tidak menerima input baru.
- Cancel, 2FA gagal dan duplicate input tidak membocorkan nilai sensitif.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_login_supervisor tests.test_profile_provisioning tests.test_worker_api -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Stop admission login baru, cancel proses PTY yang dikelola saat rollback dan tandai renew_required. Pertahankan hasil tervalidasi yang belum di-ACK; jangan kembali menghapus semua direktori startup.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
