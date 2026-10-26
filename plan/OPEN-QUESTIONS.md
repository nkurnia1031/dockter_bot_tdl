# Pertanyaan terbuka

Tidak ada pertanyaan yang menghalangi implementasi aktif. Keputusan bersyarat berikut hanya diperlukan bila kondisi migrasi benar-benar ditemukan; task lanjutan 12–22 sudah dibatalkan.

| ID | Kondisi dan keputusan pengguna | Task yang terblokir | Default sementara | Bukti yang harus dibawa |
|---|---|---|---|---|
| Q1 | Inventory menemukan cursor/backend/worker bertentangan tanpa bukti export cukup. Sumber/cakupan mana yang dipercaya? | Rekonsiliasi data terkait migrasi task 02 jika diperlukan. | Tahan channel itu, pertahankan semua data, jangan pilih angka maksimum atau mengulang download otomatis. | Profile, peer/channel, asal snapshot, cursor, checksum, status artifact dan alasan bukti tidak cukup; tanpa isi chat/sesi/secret. |

## Keputusan yang sudah tetap

- Redis + RQ, dengan SQLite/outbox sebagai catatan resmi.
- Export profil-channel sama serial lintas worker; profil berbeda boleh paralel.
- QR kedaluwarsa diperbarui manual; operation ID tetap.
- Default masuk vault dan didistribusikan.
- Profil baru menunggu semua target awal, termasuk offline/disabled.
- Worker baru menunggu sync lokal sebelum memakai profil.
- root/.tdl dan user1/.tdl tetap terpisah.
- Pengiriman TTS melalui TDL profil aktif.

Pertanyaan kapasitas produksi, versi library saat implementasi, atau detail source yang bisa diperiksa adalah tugas investigasi agent, bukan pertanyaan pengguna baru.
