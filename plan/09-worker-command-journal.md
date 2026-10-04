# 09 — Jurnal command worker dan outbox event persisten

## Tujuan

Simpan SQLite operational journal di data worker, terpisah dari sesi .tdl. Record command_id/attempt/dispatch_token, payload privat, phase/checkpoint, status dan ACK; jangan menyimpan source channel/last_id sebagai authority.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 05 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

WorkerJobExecutor dan ResourceAwareQueue memegang state eksekusi dalam memori. WorkerEventPublisher di executor_support.py menyimpan sequence dalam dict dan melakukan HTTP langsung; restart dapat kehilangan event yang belum terkirim.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/api/worker.py` |
| Diubah | `tme3bot/worker/executor.py` |
| Diubah | `tme3bot/worker/executor_support.py` |
| Diubah | `tme3bot/profile_queue.py` |
| Diubah | `tme3bot/domain/worker_contract.py` |
| Diubah | `tests/test_worker_api.py` |
| Diubah | `tests/test_worker_contract.py` |
| Baru | `tme3bot/worker/command_store.py` |
| Baru | `tme3bot/worker/command_runner.py` |
| Baru | `tests/test_worker_command_store.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

POST/GET internal commands memakai envelope task 05; operation command tanpa job_id juga didukung. Event menyertakan command_id, attempt, dispatch_token dan sequence. ACK accepted=false/stale mengakhiri retry sesuai alasan tanpa mengubah domain outcome.

## Spesifikasi implementasi

1. Simpan SQLite operational journal di data worker, terpisah dari sesi .tdl. Record command_id/attempt/dispatch_token, payload privat, phase/checkpoint, status dan ACK; jangan menyimpan source channel/last_id sebagai authority.
2. Implementasikan endpoint command v2 task 05: auth, validasi, persist, response accepted sebelum eksekusi. Command ID sama dengan payload berbeda ditolak; duplikat identik mengembalikan snapshot/hasil yang sudah ada.
3. Runner lokal membaca command accepted dan memakai resource queue lama untuk admission. Pastikan proses TDL tidak dijalankan dua kali untuk command/attempt yang sama. Persist klaim sebelum spawn.
4. Ganti pengiriman event langsung dengan sequence + event tersimpan atomik; background sender mengirim ulang sampai ACK backend. Coalesce hanya progress transient yang belum dikirim; event milestone/terminal tidak boleh hilang atau berubah sequence.
5. Startup merekonsiliasi journal dengan subprocess/checkpoint. Gunakan identitas proses yang tidak hanya PID. QuickMode/TTS yang aman melanjutkan checkpoint; upload atau efek lain yang tidak pasti menjadi needs_reconciliation.
6. Cancellation dicatat dahulu, kemudian sinyal proses dan terminal event. Hilangnya HTTP/browser tidak membatalkan command. Advertise durable_commands_v1 hanya setelah journal dan sender siap.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 09: Jurnal command worker dan outbox event persisten.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 05.
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
   Perbarui HANYA baris 09 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Duplikat submit/restart tidak menjalankan subprocess kedua.
- Backend offline tidak menghilangkan terminal event.
- ACK hilang diretry dengan sequence sama.
- Kill sebelum/sesudah side effect menghasilkan recovered atau needs_reconciliation, bukan sukses palsu.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_worker_command_store tests.test_worker_api tests.test_worker_contract -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Hentikan admission command baru, tunggu journal terminal atau catat pending. Jangan hapus database journal/outbox atau mengganti job ID saat kembali ke executor lama.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
