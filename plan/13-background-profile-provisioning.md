# 13 — Workflow profil upload, login, adopsi, dan distribusi

## Tujuan

Daftarkan profile.upload/login/adopt/sync handlers pada operation service. POST hanya validasi ringan dan persist intent; untuk ZIP terima upload lengkap ke staging privat terlebih dahulu, lalu simpan encrypted input+outbox sebelum accepted.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 07, 12 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

upload()/start_login()/adopt pada profile_provisioning.py melakukan I/O worker di request. pending_operations hanya memasukkan validating/distributing; login_state() GET dapat memicu validating. Perubahan lokal sudah mengurangi polling tetapi belum memindahkan semua lifecycle.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/profile_provisioning.py` |
| Diubah | `tme3bot/api/backend.py` |
| Diubah | `tme3bot/api/schemas.py` |
| Diubah | `tme3bot/application/operations.py` |
| Diubah | `tme3bot/infrastructure/operation_store.py` |
| Diubah | `tme3bot/infrastructure/http_client.py` |
| Diubah | `tests/test_profile_provisioning.py` |
| Diubah | `tests/test_backend_api.py` |
| Baru | `tme3bot/application/profile_operations.py` |
| Baru | `tme3bot/api/routes/profile_operations.py` |
| Baru | `tests/test_profile_operations.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

POST operations kinds profile.login/adopt/sync; upload multipart pada POST /api/v1/profiles/operations/upload menghasilkan operation DTO. POST /api/v1/operations/{id}/login/input dan /login/renew; GET /{id}/login/challenge owner-only. Pertahankan endpoint lama sebagai adapter selama gate transisi.

## Spesifikasi implementasi

1. Daftarkan profile.upload/login/adopt/sync handlers pada operation service. POST hanya validasi ringan dan persist intent; untuk ZIP terima upload lengkap ke staging privat terlebih dahulu, lalu simpan encrypted input+outbox sebelum accepted.
2. Orkestrasi validate/whoami/snapshot/upload/login di worker command; callback/event menggerakkan validating, vault_stored, distributing dan active. Seluruh tahap menunggu pengguna/worker ikut rekonsiliasi background meskipun browser ditutup.
3. Jadikan endpoint status/management pure snapshot. Simpan stable operation ID dan actor; daftar dapat difilter actor/profile/status. Tidak memilih pending operation pertama secara implisit.
4. Tambahkan endpoint challenge owner-only, Cache-Control no-store, encrypted TTL; respons daftar/status umum tidak memuat QR/phone/OTP/2FA. Input hanya diterima untuk attempt aktif dan tidak disimpan setelah dikonsumsi/kedaluwarsa; jangan retry input pada attempt berbeda.
5. Adopsi menampilkan source, profile, target snapshot dan dampak sebelum submit. Pertahankan default serta sesi root/user1 asli secara terpisah; duplicate identity/name ditolak atomik.
6. Cancel menyetop workflow dan cleanup privat setelah worker ACK; terminal race tidak boleh menghapus bundle yang sudah menjadi revisi aktif. Dismiss hanya menyembunyikan card. Tutup browser bukan cancel; upload HTTP yang belum selesai tidak dijanjikan survive.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 13: Workflow profil upload, login, adopsi, dan distribusi.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 07, 12.
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
   Perbarui HANYA baris 13 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Upload/adopsi/login tidak menjalankan worker RPC panjang pada public request.
- Login selesai saat semua tab tertutup masuk vault dan distribusi.
- Refresh tidak memicu transisi baru atau whoami.
- Initial target offline menahan aktivasi; cancel/dismiss tidak tertukar.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_profile_operations tests.test_profile_provisioning tests.test_backend_api -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Matikan admission workflow baru, lanjutkan/reconcile accepted operations dengan versi kompatibel. Jangan mengembalikan GET menjadi pemicu atau menghapus input/result pending sebelum penyelesaian.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
