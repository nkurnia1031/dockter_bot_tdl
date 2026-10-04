# 01 — Repository state backend dan pemisahan runtime profil

## Tujuan

Definisikan port SourceRepository dan SqliteSourceRepository di database backend yang sama dengan job store. Kunci awal (profile, canonical_chat_key); sediakan kolom peer_type/peer_id nullable untuk resolusi task 06.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Tidak ada task prasyarat. Mulai dari baseline yang tercatat di overview; pertahankan seluruh perubahan lokal.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

StateStore di tme3bot/state.py menyimpan snapshot JSON dalam memori dengan RLock. build_profile_runtime() di tme3bot/profiles.py memilih HttpStateStore untuk worker, tetapi backend masih membangun runtime yang membawa client TDL. SourceState berisi last_id, label, updated_at dan warmup; perilaku ini harus dipertahankan.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/state.py` |
| Diubah | `tme3bot/profiles.py` |
| Diubah | `tme3bot/composition.py` |
| Diubah | `tme3bot/application/ports.py` |
| Diubah | `tme3bot/api/backend.py` |
| Diubah | `tme3bot/api/routes/sources.py` |
| Diubah | `tests/test_state.py` |
| Diubah | `tests/test_profiles.py` |
| Diubah | `tests/test_architecture_boundaries.py` |
| Baru | `tme3bot/infrastructure/source_store.py` |
| Baru | `tests/test_source_store.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

API source publik tidak berubah. Repository menyediakan load/get/list/upsert serta commit dengan expected_revision; konflik revision dilaporkan terstruktur, bukan ditimpa. Gerbang hanya dapat diaktifkan setelah import backend mempunyai catatan sukses.

## Spesifikasi implementasi

1. Definisikan port SourceRepository dan SqliteSourceRepository di database backend yang sama dengan job store. Kunci awal (profile, canonical_chat_key); sediakan kolom peer_type/peer_id nullable untuk resolusi task 06.
2. Simpan last_id, label, warmup dan revision secara transaksional. Gunakan koneksi per transaksi, busy timeout, serta update bersyarat revision. Tidak ada read-modify-write terhadap cache JSON sebagai sumber resmi.
3. Pisahkan akses metadata/state profil dari pembuatan TdlClient. Endpoint daftar profil/source harus bisa berjalan tanpa binary atau sesi TDL di backend.
4. Pertahankan bentuk SourceState dan kontrak HttpStateStore. Tambahkan adapter SQL di belakang gerbang backend_source_state; default nonaktif sampai import task 02 selesai. Gerbang disimpan sebagai metadata migrasi backend, bukan ENV baru.
5. Sumber numeric yang tidak diminta disimpan tetap bersifat sementara sesuai perilaku service saat ini. Jangan mengubah last_id berdasarkan label atau membuat source tersimpan hanya karena resolve.
6. Tambahkan test repository dan boundary; pastikan runtime worker tetap menjalankan TDL dan backend tidak mengeksekusi subprocess TDL dari endpoint metadata.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 01: Repository state backend dan pemisahan runtime profil.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: tidak ada.
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
   Perbarui HANYA baris 01 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Update bersamaan tidak kehilangan perubahan; last_id normal tidak turun.
- Label dan warmup lama tetap terbaca; dua profile tidak berbagi source.
- Backend metadata berfungsi tanpa sesi/binary TDL; gerbang mati mempertahankan jalur lama.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_source_store tests.test_state tests.test_profiles tests.test_architecture_boundaries -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Matikan backend_source_state sebelum ada write SQL baru. Setelah ada write baru, drain export dan ekspor snapshot SQL terbaru ke format legacy melalui alat task 02 sebelum mengembalikan reader lama. Jangan menimpa SQL atau menurunkan cursor.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
