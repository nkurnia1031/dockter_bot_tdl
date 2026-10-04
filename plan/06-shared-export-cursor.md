# 06 — Alias peer dan serialisasi export lintas worker

## Tujuan

Tambahkan alias registry per profile menuju (peer_type, peer_id); identitas dikonfirmasi worker melalui hasil resolve terautentikasi. Nama label tidak pernah dipakai menyamakan peer; username yang berubah memerlukan konfirmasi mapping baru.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 01, 05 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

canonical_chat_key menyamakan format username/link, tetapi tidak otomatis mengaitkannya dengan numeric peer. Resource scheduler sekarang menyertakan worker. QuickMode melepas lane export pada export.json_ready; urutan commit harus dijamin sebelum pelepasan.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/chat_refs.py` |
| Diubah | `tme3bot/infrastructure/source_store.py` |
| Diubah | `tme3bot/application/job_scheduler.py` |
| Diubah | `tme3bot/application/control_plane.py` |
| Diubah | `tme3bot/api/backend.py` |
| Diubah | `tme3bot/domain/worker_contract.py` |
| Diubah | `tme3bot/export_catalog.py` |
| Diubah | `tests/test_chat_refs.py` |
| Diubah | `tests/test_control_plane.py` |
| Baru | `tme3bot/application/export_cursor.py` |
| Baru | `tests/test_shared_export_cursor.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

Internal resolve result memuat profile, requested_ref, peer_type, peer_id dan attempt; internal cursor commit memuat job_id, attempt, fencing_token, expected_revision, last_id dan artifact metadata. Tolak worker yang bukan pemilik job/profile.

## Spesifikasi implementasi

1. Tambahkan alias registry per profile menuju (peer_type, peer_id); identitas dikonfirmasi worker melalui hasil resolve terautentikasi. Nama label tidak pernah dipakai menyamakan peer; username yang berubah memerlukan konfirmasi mapping baru.
2. Job dengan peer belum dikenal masuk fase resolving sebelum memperoleh lease export. Worker resolver dipasang task 11. Semua job memakai lease profile+resolved peer; lakukan claim dalam transaksi SQLite dan cek resource worker yang ada.
3. Persist lease owner job/attempt, fencing generation dan cursor revision. Cursor dibaca saat lane diperoleh, bukan dari snapshot halaman submit. Commit menerima expected revision/generation dan evidence artifact export.
4. Commit cursor dan katalog artifact dalam satu transaksi atau outbox completion yang dapat direplay atomik secara logis; jangan release lane sebelum dua catatan terkonfirmasi. Pelepasan QuickMode hanya lane export, lane stage/download tetap dimiliki job.
5. Pertahankan explicit start/overwrite per job; commit monotonic tidak menurunkan cursor bersama. Jangan menaikkan cursor hanya karena subprocess dimulai atau upload selesai.
6. Lease yang kehilangan heartbeat ditahan sampai stop/terminal/reconciliation dikonfirmasi; generation lama selalu ditolak. Aktifkan gate shared_export_cursor hanya setelah worker task 11 kompatibel.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 06: Alias peer dan serialisasi export lintas worker.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 01, 05.
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
   Perbarui HANYA baris 06 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Profile-channel sama di dua worker serial; profile berbeda tidak saling memblokir.
- Username dan numeric alias yang terverifikasi memperoleh lane sama.
- Event json_ready sebelum commit tidak melepas lane.
- Stale lease tidak dapat menulis cursor; label/overwrite tidak menurunkan nilai.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_shared_export_cursor tests.test_chat_refs tests.test_control_plane -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Drain export, nonaktifkan shared_export_cursor untuk job baru dan pastikan tidak ada lease lintas versi aktif. Pertahankan alias/ledger; jangan reset fencing atau cursor.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
