# Pertanyaan terbuka

Tidak ada pertanyaan yang menghalangi penulisan paket atau implementasi kontrak dasar. Dua keputusan berikut hanya diperlukan jika kondisi tersebut benar-benar ditemukan. Agent tidak perlu menanyakannya sebelum ada bukti.

| ID | Kondisi dan keputusan pengguna | Task yang terblokir | Default sementara | Bukti yang harus dibawa |
|---|---|---|---|---|
| Q1 | Inventory menemukan cursor/backend/worker bertentangan tanpa bukti export cukup. Sumber/cakupan mana yang dipercaya? | Commit channel terkait pada 02; cutover terkait pada 22. Dry-run dan channel aman tetap berjalan. | Tahan channel itu, pertahankan semua data, jangan pilih angka maksimum atau mengulang download otomatis. | Profile, peer/channel, asal snapshot, cursor, checksum, status artifact dan alasan bukti tidak cukup; tanpa isi chat/sesi/secret. |
| Q2 | Uji sesi nyata menunjukkan auth key salinan tidak aman digunakan bersamaan. Apakah menerima otorisasi/login terpisah per worker dalam profil yang sama? | Rollout penggunaan paralel profil terkait pada 22; kontrak pull/sync dan uji mock tetap berjalan. | Jangan aktifkan paralel yang belum terbukti aman. Pertahankan worker/profil yang sudah aman; jangan auto re-login atau mengganti akun. | Versi TDL, topologi, gejala/error tersanitasi dan hasil uji terkontrol; tanpa auth key, token, phone atau sesi. |

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
