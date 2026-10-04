# 18 — Halaman Profil pulih setelah ditutup

## Tujuan

Tambahkan typed Operation DTO/API helper sesuai kontrak backend. Pilih operation melalui query ?operation=<id>; saat tidak ada ID tampilkan daftar milik actor, bukan auto mengambil operasi pertama.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 10, 13 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

ProfilesPage.svelte sudah memiliki perubahan lokal refresh manual. load() masih memilih pending operation pertama; state aktif tidak selalu terikat URL. Browser statis menggunakan web/src/lib/api.ts dan session.svelte.ts.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `web/src/lib/components/ProfilesPage.svelte` |
| Diubah | `web/src/lib/components/ProfilesPage.test.ts` |
| Diubah | `web/src/lib/api.ts` |
| Diubah | `web/src/lib/api.test.ts` |
| Diubah | `web/src/routes/profiles/+page.svelte` |
| Baru | `web/src/lib/operations.ts` |
| Baru | `web/src/lib/operations.test.ts` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

Gunakan endpoints task 13/07 tanpa membaca backend internals. 202 bukan sukses akhir. Form upload menjelaskan accepted setelah upload lengkap; pindah halaman saat upload belum selesai tidak dianggap operation tersimpan.

## Spesifikasi implementasi

1. Tambahkan typed Operation DTO/API helper sesuai kontrak backend. Pilih operation melalui query ?operation=<id>; saat tidak ada ID tampilkan daftar milik actor, bukan auto mengambil operasi pertama.
2. Submit upload/login/adopt/sync menampilkan accepted ID segera dan menyimpan pemilihan ke URL. Navigasi kembali mengambil snapshot backend. Jangan menyimpan QR, kode, password atau sesi di localStorage/URL.
3. Tampilkan step menunggu QR/phone/code/2FA, validasi, distribusi dan hasil. GET challenge hanya saat membuka detail/refresh/aksi, owner-only; jangan membuat timer yang meminta QR berulang.
4. Tambahkan Refresh, Perbarui QR, Batal dan Sembunyikan dengan makna berbeda. Tutup panel/route tidak cancel. QR expired/restart hanya bisa renew lewat aksi eksplisit; input cleared sesudah submit atau attempt berubah.
5. Untuk adopsi tampilkan source worker, target termasuk offline/disabled, dan dampak distribusi sebelum submit. Default tersedia. Manual sync menampilkan desired/installed revision dan check vs repair.
6. Tambahkan test fake clock/network: tidak ada polling saat waiting_user, URL reload memulihkan operation, stale response dibuang, auth/actor berubah membersihkan tampilan privat. Progress aktif boleh dihubungkan ke monitor task 19; tahap ini Refresh tetap berfungsi.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 18: Halaman Profil pulih setelah ditutup.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 10, 13.
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
   Perbarui HANYA baris 18 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Close/reopen memilih ID operation sama, bukan record lain.
- Tidak ada secret dalam URL/storage/log browser.
- Waiting_user tetap tanpa network interval; renew manual menghasilkan attempt baru.
- Default adoption dan target sync status tersedia.
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

Dari web: pnpm test -- src/lib/components/ProfilesPage.test.ts src/lib/operations.test.ts src/lib/api.test.ts. Uji reload URL operation dengan mock API; tidak melakukan login production.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Kembalikan hanya UI task ini; operation backend tetap berjalan. Jangan membatalkan operasi atau menghapus browser auth sebagai bagian rollback UI.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
