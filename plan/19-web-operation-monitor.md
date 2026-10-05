# 19 — Monitor progress terpusat dan refresh berdasarkan aksi

## Tujuan

Bangun satu coordinator polling per tab untuk query monitor yang sama. Interval dasar 2500ms, satu request in-flight per key, backoff error sampai 30 detik dengan jitter, AbortController saat unmount/target berubah.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task P0, P1, 16, 17, 18 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

P0 sudah menyediakan helper laptop untuk memasang cookie pada browser agent baru. session.restore tetap menerima sesi device melalui API browser yang sama. Refactor Login/monitor tidak boleh otomatis memanggil helper atau membuka challenge Telegram saat sesi device valid. Logout tetap eksplisit dan tidak diikuti auto re-auth; browser tanpa credential tetap menampilkan login normal.

JobTable interval 2500ms; QuickMode memuat statistik dan limits dalam interval yang sama; ExportPage memeriksa notices dan Login melakukan polling auth. Workers/Profiles sudah lebih manual. SvelteKit static harus tetap tanpa server runtime.

Pertahankan kontrol P1 pada WorkersPage: diagnosis dan recovery TTS tetap berbasis aksi/refresh manual, tanpa polling settings. Bila recovery dipindahkan ke operation monitor, status dan kontrol operator harus tetap tersedia dengan pembatasan worker/helper yang sama.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `web/src/lib/api.ts` |
| Diubah | `web/src/lib/api.test.ts` |
| Diubah | `web/src/lib/operations.ts` |
| Diubah | `web/src/lib/operations.test.ts` |
| Diubah | `web/src/lib/components/JobTable.svelte` |
| Diubah | `web/src/lib/components/JobTable.test.ts` |
| Diubah | `web/src/lib/components/QuickModePage.svelte` |
| Diubah | `web/src/lib/components/QuickModePage.test.ts` |
| Diubah | `web/src/lib/components/ExportPage.svelte` |
| Diubah | `web/src/lib/components/ExportPage.test.ts` |
| Diubah | `web/src/lib/components/StoragePage.svelte` |
| Diubah | `web/src/lib/components/StoragePage.test.ts` |
| Diubah | `web/src/lib/components/UtilityPage.svelte` |
| Diubah | `web/src/lib/components/DownloadsPage.svelte` |
| Diubah | `web/src/lib/components/WorkspaceExplorer.svelte` |
| Diubah | `web/src/lib/components/WorkspaceExplorer.test.ts` |
| Diubah | `web/src/lib/components/TargetPicker.svelte` |
| Diubah | `web/src/lib/components/Login.svelte` |
| Diubah | `web/src/lib/components/ProfilesPage.svelte` |
| Diubah | `web/src/lib/session.svelte.ts` |
| Diubah | `web/src/lib/session.test.ts` |
| Diubah | `web/src/routes/tts/+page.svelte` |
| Diubah | `web/src/lib/components/TtsPage.test.ts` |
| Diubah | `web/src/lib/components/BackupsPage.svelte` |
| Baru | `web/src/lib/operation-monitor.ts` |
| Baru | `web/src/lib/operation-monitor.test.ts` |
| Baru | `web/src/lib/components/Login.test.ts` |
| Baru | `web/src/lib/components/UtilityPage.test.ts` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

Coordinator memakai GET job/operation snapshot; mutation response 202 diikuti refresh singkat, bukan await completion. UI menampilkan status pengiriman/antre/sintesis/export sesuai metadata yang sudah ada.

## Spesifikasi implementasi

1. Bangun satu coordinator polling per tab untuk query monitor yang sama. Interval dasar 2500ms, satu request in-flight per key, backoff error sampai 30 detik dengan jitter, AbortController saat unmount/target berubah.
2. Polling hanya ketika halaman terlihat dan ada running/cancelling dengan progress. queued/waiting_user/waiting_worker/paused/terminal memakai refresh manual; queued yang berubah running di server akan terlihat setelah refresh atau user membuka monitor. Heartbeat internal tidak disentuh.
3. Refresh setelah submit/cancel/resume/renew dan saat membuka halaman. Jangan melakukan auto refresh pada focus untuk halaman menunggu input; aktif monitor boleh refresh saat visible kembali. Shared coordinator tidak mem-poll settings/limits/inventory.
4. Hubungkan scan QuickMode dan checks Storage/Utility/TargetPicker ke operation accepted/status. Tampilkan stale snapshot dan last refreshed, serta tombol Refresh. Job progress tetap per job ID dan attempt, bukan global file label.
5. Login Web Telegram menampilkan tombol Sudah disetujui/Periksa login dan regenerate link eksplisit; hentikan polling challenge berkala. Pertahankan expiry dan cookie auth. Jangan mengubah challenge menjadi login otomatis tanpa konfirmasi.
6. Tambahkan fake timer tests jumlah request, hidden tab, slow response, terminal, error backoff dan target change. Pertahankan no-auto-reconcile Download Manager; job yang berlangsung di backend tidak dibatalkan saat component unmount.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 19: Monitor progress terpusat dan refresh berdasarkan aksi.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: P0, P1, 16, 17, 18.
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
   Perbarui HANYA baris 19 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Restore sesi device tidak memulai challenge Telegram/polling login; logout tidak menghidupkan sesi lagi, dan sesi revoked tampil unauthenticated.

- Dua komponen query sama tidak menggandakan timer.
- Tidak ada request berkala untuk waiting input/settings/inventory.
- Slow GET tidak overlap; hidden tab berhenti dan response lama diabaikan.
- Semua aksi tetap selesai di background setelah UI ditutup.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
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

Dari web: pnpm test -- src/lib/operation-monitor.test.ts src/lib/components/JobTable.test.ts src/lib/components/Login.test.ts src/lib/components/QuickModePage.test.ts src/lib/components/StoragePage.test.ts. Gunakan fake timers dan mock API, lalu jalankan seluruh pnpm test.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Kembalikan coordinator/UI saja sambil mempertahankan API async; sediakan Refresh manual yang tetap kompatibel. Jangan menyalakan kembali inventory reconcile otomatis atau cancel-on-unmount.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
