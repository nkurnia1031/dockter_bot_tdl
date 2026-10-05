# 22 — Uji kegagalan lintas komponen dan panduan cutover

## Tujuan

Buat harness backend SQLite temporary, Redis disposable, worker subprocess/mock TDL dan fake Telegram/rclone. Hindari akun/endpoint produksi. Uji matrix backend/worker/frontend lama-baru: gate off tetap kompatibel; gate on mensyaratkan capability.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task P0, P1, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

P0 telah memasang auth perangkat sebelum task 01. Masukkan device registry/session migration ke backup dan rehearsal rollback. Uji public-key enrollment, helper/browser baru, restart, expiry, replay, revoked access/refresh dan actor kehilangan izin. Registry public key dibackup pada backend; private key DPAPI tidak ikut backup backend. Automation tanpa import state harus dilaporkan sebagai keterbatasan, bukan diatasi dengan token URL atau mematikan auth.

Semua capability/gate baru masih dapat dipasang bertahap. Produksi memakai VPS gateway kecil, worker remote, static UI aaPanel, dan build image pada builder lokal yang memiliki base image. Kode task ini hanya test integrasi dan dokumentasi rollout; bug implementasi dicatat ke task pemilik.

P1 menyediakan diagnosis dan recovery Tor terbatas dari Workers Web. Uji bahwa queue/settings/worker refactor mempertahankan endpoint, auth, helper slot, guard sintesis aktif, dan refresh manual; container yang tidak merespons tetap memerlukan tindakan host.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tests/test_architecture_boundaries.py` |
| Diubah | `tests/test_worker_contract.py` |
| Diubah | `tests/test_backend_api.py` |
| Diubah | `docs/ARSITEKTUR_SISTEM.md` |
| Diubah | `DEPLOYMENT_RUNBOOK.md` |
| Diubah | `docs/PENGATURAN_RUNTIME.md` |
| Diubah | `README.md` |
| Baru | `tests/test_durable_workflows.py` |
| Baru | `tests/test_rollout_compatibility.py` |
| Baru | `docs/CONTROL_PLANE_MIGRATION_RUNBOOK.md` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

Dokumentasikan gates backend_source_state, durable_dispatch, shared_export_cursor dan capability operations_v1/durable_commands_v1/shared_export_cursor_v1/profile sync/settings. Public legacy endpoints belum dihapus; penghapusan menjadi pekerjaan versi berikutnya.

## Spesifikasi implementasi

1. Buat harness backend SQLite temporary, Redis disposable, worker subprocess/mock TDL dan fake Telegram/rclone. Hindari akun/endpoint produksi. Uji matrix backend/worker/frontend lama-baru: gate off tetap kompatibel; gate on mensyaratkan capability.
2. Simulasikan crash setelah persist/sebelum enqueue, sesudah dispatch/sebelum ACK, sesudah artifact/sebelum cursor commit dan setelah login tervalidasi/sebelum vault ACK. Assert tidak ada accepted operation hilang atau side effect diretry buta.
3. Uji dua worker profil-channel sama, alias peer, offline sync, default adoption, initial activation barrier, settings busy/offline/restart, diagnosis/status helper P1, recovery Tor dengan helper tiruan, guard sintesis aktif, dan UI close/reopen. Tambahkan assertion rahasia pada DTO/log dan no-browser-polling waiting input.
4. Tulis runbook preflight backup DB+vault+key, migration dry-run, penyelesaian konflik, drain export, import, canary satu worker, capability ACK, aktifkan gate, publish Web, perluas rollout dan arsip state lama.
5. Catat indikator lulus: tidak ada cursor mundur, outbox akhirnya terkirim, event terminal tidak hilang, snapshot GET tidak menunggu worker, dan submit accepted tetap cepat saat worker mock ditahan. Ambang performa integration terkontrol: submit/status selesai <1 detik ketika worker mock tertahan 10 detik; produksi dicatat p50/p95 tanpa mengklaim SLA dari mesin lokal.
6. Tulis rollback berurutan per gate dengan preservasi accepted jobs dan cursor terbaru. Pengujian penggunaan sesi salinan paralel di produksi butuh operator dan persetujuan terpisah; jika konflik auth key muncul tahan rollout profil terkait, jangan auto login ulang.
7. Perbarui arsitektur berdasarkan hasil test, bedakan implemented vs recommended. Jangan deploy, publish image, commit, atau menjalankan migrasi produksi sebagai bagian task ini.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 22: Uji kegagalan lintas komponen dan panduan cutover.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: P0, P1, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21.
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
   Perbarui HANYA baris 22 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Matrix P0 terverifikasi dengan fixture: sesi device dan Telegram berdampingan, revoke langsung efektif, dan rollback auth tidak menghidupkan device session yang dicabut.
- Matrix P1 terverifikasi: status per helper konsisten dengan capability, pemulihan Tor tidak menyentuh Docker, dan kondisi helper tak terjangkau tetap jelas.

- Semua scenario crash dan compatibility mempunyai assertion hasil, bukan hanya HTTP 200.
- Tidak ada data aplikasi hilang dalam rehearsal rollback.
- Runbook mencantumkan langkah gagal/stop serta source konflik yang memerlukan operator.
- Python/Web/diff/graphify hasil nyata dicatat; Docker/Go unavailable tidak dianggap lulus.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_durable_workflows tests.test_rollout_compatibility tests.test_architecture_boundaries tests.test_worker_contract -v
python -m unittest tests.test_device_auth tests.test_auth_service -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Jalankan dari direktori `web/` (kembali ke root sebelum perintah Git/Graphify):

```text
pnpm check
pnpm test
pnpm build
```

Dari root: python -m unittest discover -s tests -v. Dari web: pnpm check, pnpm test, pnpm build (perintah terpisah). Pada builder: validasi Compose dengan fixture dan build image sesuai runbook. Jalankan drill hanya pada temporary data/test services.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Task ini tidak mengubah production. Kembalikan hanya dokumentasi/test bila perlu; temuan kegagalan membuka kembali task pemilik. Runbook operasional wajib drain, preserve outbox, export cursor terbaru dan pertahankan vault revisions sebelum rollback aplikasi.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
