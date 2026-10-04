# 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress

## Tujuan

Buat CLI python -m tme3bot.migrate_source_state dengan subcommand inventory, plan, apply, export-legacy. Input adalah snapshot offline yang disiapkan operator; jangan otomatis menghubungi produksi atau membaca sesi .tdl.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 01 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

Backend sudah menjadi sumber last_id pada jalur normal. File state.json/max.json di worker bisa merupakan sisa historis; angka lebih besar tidak membuktikan export selesai. BackupService masih membawa metadata/state profil. Migration harus membedakan cursor export dan status download artifact.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/infrastructure/source_store.py` |
| Diubah | `tme3bot/backup_service.py` |
| Diubah | `tests/test_backup_service.py` |
| Baru | `tme3bot/migrate_source_state.py` |
| Baru | `tests/test_source_migration.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

CLI hanya bekerja terhadap path eksplisit yang ditentukan operator. Output plan berisi approved/blocked per source dan bukti; --commit menolak plan berubah atau target maju. Tidak ada endpoint publik yang menerima arbitrary path.

## Spesifikasi implementasi

1. Buat CLI python -m tme3bot.migrate_source_state dengan subcommand inventory, plan, apply, export-legacy. Input adalah snapshot offline yang disiapkan operator; jangan otomatis menghubungi produksi atau membaca sesi .tdl.
2. Inventory menerima --input-dir dan --output, menghasilkan JSON dengan asal backend/worker, profile, chat_ref, last_id, label, warmup, checksum sumber dan metadata artifact/job. Jangan masukkan credential atau isi chat.
3. Plan menerima --inventory dan --output; backend menjadi kandidat utama. Cursor yang berbeda memerlukan bukti export sukses dan artifact terkait, termasuk cakupan yang diproses. Timestamp atau max(last_id) saja tidak cukup. Label/warmup konflik juga dilaporkan, tidak ditimpa diam-diam.
4. Apply menerima --plan, --database, --dry-run (default) atau --commit. Commit wajib admission export profile terkait sudah dihentikan, checksum sumber/revision target masih sama, backup tersedia, dan keputusan konflik eksplisit ada di plan. Kanal konflik ditahan; kanal aman dapat diimport.
5. Simpan ledger migration_id + checksum + keputusan + cursor sebelum/sesudah dalam transaksi. Replay identik no-op; perubahan plan memerlukan ID baru. Verifikasi jumlah source dan metadata serta artifact pending/failed/done: migrasi tidak menjadwalkan download ulang.
6. Export-legacy menerima --database dan --output-dir untuk rollback setelah drain. Tambahkan format backup backend untuk SQL state dan ledger. Pertahankan file worker lama sampai cutover task 11/22; arsipkan hanya sesudah ACK/verifikasi, jangan hapus checkpoint.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 02: Inventarisasi dan migrasi state lama tanpa kehilangan progress.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 01.
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
   Perbarui HANYA baris 02 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Dry-run tidak mengubah sumber/target.
- Apply dua kali tidak menaikkan atau menurunkan cursor lagi.
- State worker lebih tinggi tanpa bukti ditandai blocked; konflik tidak dipilih otomatis.
- Rollback export memuat cursor terbaru; katalog download tidak berubah.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_source_migration tests.test_source_store tests.test_backup_service -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Simpan input asli dan migration ledger. Sebelum cutover, matikan gerbang tanpa menghapus hasil import. Sesudah write baru, drain lalu export-legacy dari SQL terbaru; jangan restore backup lama yang menghilangkan progress baru.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
