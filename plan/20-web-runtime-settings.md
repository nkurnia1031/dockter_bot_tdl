# 20 — Pengaturan Web dengan desired/applied status

## Tujuan

Gunakan registry schema dan DTO settings task 08. Kelompokkan backend, Telegram, worker; deploy-only ditampilkan sebagai informasi dengan alasan deployment, bukan kontrol yang berpura-pura dapat diterapkan.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task P0, P1, 14, 15 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

P0 menambahkan komponen TrustedDevices pada Settings dengan register/list/rename/revoke menggunakan API auth langsung. Pertahankan komponen, fingerprint confirmation, CSRF dan refresh manual saat menyusun kelompok runtime settings. Device public key/registry bukan field secret runtime dan tidak dipindahkan ke desired/applied settings. Private key tetap lokal; actor hanya mengelola perangkat sendiri.

SettingsPage dan WorkersPage sudah menampilkan beberapa runtime settings. Endpoint sebelumnya dapat menolak perubahan ketika worker sibuk dan mengembalikan restart_required_services. Target baru adalah persist desired terlebih dahulu lalu menampilkan penerapan.

WorkersPage juga memiliki kontrol P1 untuk diagnosis per helper TTS dan recovery Tor yang eksplisit. Pertahankan kontrol itu terpisah dari form settings; jangan menyebutnya sebagai restart container dan jangan menghilangkannya saat WorkersPage direfaktor.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `web/src/lib/components/SettingsPage.svelte` |
| Diubah | `web/src/lib/components/TrustedDevices.svelte` |
| Diubah | `web/src/lib/components/TrustedDevices.test.ts` |
| Diubah | `web/src/lib/components/WorkersPage.svelte` |
| Diubah | `web/src/lib/api.ts` |
| Diubah | `web/src/lib/api.test.ts` |
| Diubah | `web/src/lib/components/StoragePage.svelte` |
| Diubah | `web/src/lib/components/StoragePage.test.ts` |
| Diubah | `web/src/routes/tts/+page.svelte` |
| Diubah | `web/src/lib/components/TtsPage.test.ts` |
| Baru | `web/src/lib/components/SettingsPage.test.ts` |
| Diubah | `web/src/lib/components/WorkersPage.test.ts` (dibuat oleh P1) |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

GET/PUT runtime/settings dengan expected_version dan secret clear semantics task 08; operation runtime.apply untuk retry. Public secret response hanya configured; tidak menampilkan credential setelah save.

## Spesifikasi implementasi

1. Gunakan registry schema dan DTO settings task 08. Kelompokkan backend, Telegram, worker; deploy-only ditampilkan sebagai informasi dengan alasan deployment, bukan kontrol yang berpura-pura dapat diterapkan.
2. Tampilkan desired_version, applied_version, pending/busy/offline/error dan waktu ACK. Save berarti tersimpan; jangan memberi toast seolah sudah diterapkan ke worker offline.
3. Form secret kosong secara default dengan configured indicator, aksi Ganti dan Hapus eksplisit. Jangan meminta secret lama, mengisinya kembali dari API, atau menaruhnya di localStorage.
4. Tambahkan Refresh dan Retry apply secara manual; tidak ada interval settings polling. Setelah save fetch satu snapshot. Conflict expected_version menampilkan versi terbaru dan meminta pengguna mengulang edit secara sadar.
5. Gunakan validator chat ref bersama untuk target Storage/TTS/backup; profil aktif dan worker ditampilkan jelas. Tujuan TTS efektif tetap dipakai TDL dari profile, bukan layanan bot legacy.
6. Uji worker offline/busy, ACK gagal, stale form, clear secret, restart service pending dan deploy-only. Tidak ada perintah restart Docker untuk setting yang sudah mendukung reload.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 20: Pengaturan Web dengan desired/applied status.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: P0, P1, 14, 15.
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
   Perbarui HANYA baris 20 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Komponen Perangkat tepercaya tetap tersedia, memakai auth/CSRF dan refresh manual; save settings tidak mengubah key, owner atau status revoke.
- Kontrol diagnosis dan recovery TTS P1 tetap tersedia di WorkersPage, menggunakan aksi/refresh manual dan tanpa Docker socket.

- Save offline terlihat pending dan tidak hilang setelah reload.
- Secret tidak muncul kembali atau tersimpan browser.
- Konflik versi tidak silent overwrite.
- Refresh manual cukup untuk melihat ACK; tidak ada settings polling.
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

Dari web: pnpm test -- src/lib/components/SettingsPage.test.ts src/lib/components/WorkersPage.test.ts src/lib/components/StoragePage.test.ts src/lib/api.test.ts.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Rollback tampilan dengan tetap membaca metadata baru secara kompatibel. Jangan menghapus desired settings yang sudah disimpan atau menyarankan copy ulang secret ke ENV.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
