# 10 — Tarik profil saat startup dan sinkronisasi manual

## Tujuan

Tambahkan profile sync client yang mengambil manifest backend setiap startup/deploy dan command profile.sync. Simpan installed revision/hash/status lokal; admission job profile menunggu desired revision terkonfirmasi.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 07, 09 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

Task ini mengubah executor dan Worker API yang juga menyediakan diagnosis/recovery TTS P1. Pertahankan capability per helper dan endpoint recovery Tor; sinkronisasi profil tidak boleh menyamarkan status helper atau menjadikan recovery bagian dari alur profile pull.

WorkerJobExecutor.start() memanggil sync_profiles() untuk melaporkan metadata lokal. ProfileSessionManager sudah memiliki export/install bundle; perubahan lokal menambah lock sesi dan dukungan default. Gunakan mekanisme aman tersebut, jangan kembali memasang zip langsung di data root.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/worker/executor.py` |
| Diubah | `tme3bot/worker/profile_sessions.py` |
| Diubah | `tme3bot/api/worker.py` |
| Diubah | `tme3bot/profiles.py` |
| Diubah | `tests/test_profile_provisioning.py` |
| Diubah | `tests/test_worker_api.py` |
| Baru | `tme3bot/worker/profile_sync.py` |
| Baru | `tests/test_worker_profile_sync.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

Command profile.sync input {profile,mode:check|repair}; target worker sudah dipastikan backend. Snapshot per profil mencakup desired_revision, installed_revision, status, error. Bundle endpoint dan ACK persis kontrak task 07.

## Spesifikasi implementasi

1. Tambahkan profile sync client yang mengambil manifest backend setiap startup/deploy dan command profile.sync. Simpan installed revision/hash/status lokal; admission job profile menunggu desired revision terkonfirmasi.
2. Download hanya revision hilang/berubah. Mode check cukup verifikasi metadata/integritas; mode repair eksplisit dapat reinstall revision yang sama. Jangan menimpa Bolt yang sudah berubah normal setiap container restart.
3. Validasi ZIP path traversal/symlink, limit ukuran, schema, identity dan hash. Stage pada filesystem sama; root/.tdl dan user1/.tdl terpisah. Adopsi mempertahankan dua sesi asli; profil dari satu sesi disalin menjadi dua direktori.
4. Ambil lock export lalu download dengan urutan tetap sesuai source sekarang. Tunggu job aktif selesai, hentikan admission profile, lakukan swap+backup privat, rollback jika validasi gagal; default tidak boleh mengganti seluruh /data.
5. ACK hanya sesudah install dan identitas berhasil diverifikasi. Backend tidak tersedia berarti waiting_worker/sync_pending dan profile job baru tertahan; worker health tetap menjelaskan proses hidup vs profile belum ready.
6. Hentikan push metadata sebagai cara mengubah registry vaulted. Pertahankan legacy discovery read-only untuk profil yang belum diadopsi. Manual sync tidak otomatis membuat snapshot vault dari worker.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 10: Tarik profil saat startup dan sinkronisasi manual.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 07, 09.
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
   Perbarui HANYA baris 10 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Startup worker baru menarik bundle; startup revision sama tidak reinstall.
- Sync ketika TDL berjalan menunggu, tidak merusak Bolt.
- Default aman, root/user1 tidak menunjuk database sama.
- Install rusak memulihkan sesi sebelumnya; job mismatch revision ditolak/ditahan.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_worker_profile_sync tests.test_profile_provisioning tests.test_worker_api -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Drain profile, kembalikan backup direktori sesi terakhir jika swap gagal, kemudian ACK revision yang benar. Jangan mengubah desired revision backend atau menghapus bundle untuk menyamarkan kegagalan.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
