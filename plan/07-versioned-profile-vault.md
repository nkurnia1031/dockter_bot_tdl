# 07 — Vault profil berversi dan kontrak tarik/ACK

## Tujuan

Tambahkan revision immutable, format_version, hash bundle, identity dan source worker pada vault. Bundle baru akibat upload/login/adopsi menghasilkan revision baru, bukan overwrite revision yang sedang diunduh.

Dokumen ini adalah instruksi untuk implementasi berikutnya; belum menyatakan fitur sudah dibuat.

## Prasyarat

Task 03 sudah selesai dan verifikasinya tercatat di PROGRESS. Modul baru dari prasyarat sudah tersedia; file itu ditandai Diubah di bawah.

Baca [overview](00-OVERVIEW.md); gunakan [progres](PROGRESS.md) untuk memeriksa hasil prasyarat. Semua perubahan diterapkan lokal dahulu, tanpa deployment otomatis.

## Konteks khusus task

ProfileProvisioningStore mempunyai profile_sessions/provisionings/distributions dan AES-GCM. Worker startup mengirim identity melalui /internal/v1/profiles/sync; registry dapat menerima perubahan identitas. Perubahan lokal sudah menambah dukungan default dan lock snapshot.

## File yang disentuh

Path relatif terhadap root repo. “Baru” berarti dibuat oleh task ini; “Diubah” dapat merupakan file yang dibuat prasyarat. Tidak ada penghapusan file yang direncanakan.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/profile_provisioning.py` |
| Diubah | `tme3bot/profile_registry.py` |
| Diubah | `tme3bot/api/backend.py` |
| Diubah | `tme3bot/composition.py` |
| Diubah | `tests/test_profile_provisioning.py` |
| Diubah | `tests/test_backend_api.py` |
| Diubah | `tests/test_worker_registry.py` |
| Baru | `tme3bot/api/routes/profile_sync.py` |
| Baru | `tests/test_profile_sync_contract.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

GET /internal/v1/profile-manifest; GET /internal/v1/profiles/{name}/bundles/{revision}; POST /internal/v1/profiles/{name}/ack. Identitas worker berasal dari auth. Public GET profiles/management memuat desired_revision, installed_revision, status per worker; POST operations kind profile.sync menargetkan worker/profile.

## Spesifikasi implementasi

1. Tambahkan revision immutable, format_version, hash bundle, identity dan source worker pada vault. Bundle baru akibat upload/login/adopsi menghasilkan revision baru, bukan overwrite revision yang sedang diunduh.
2. Manifest internal hanya memuat profile, revision, hash dan status admission yang ditugaskan ke worker pemanggil. Bundle lewat streaming HTTPS terautentikasi; tidak ada URL publik atau path lokal dalam DTO.
3. Tambahkan ACK installed revision/hash/identity, error tersanitasi dan waktu; ACK stale tidak memenuhi desired revision terbaru. Failed distribution tidak menghapus bundle resmi.
4. Pertahankan snapshot seluruh worker terdaftar termasuk disabled/offline untuk profil baru; aktif setelah seluruh target awal ready. Worker baru mendapat semua profil vaulted dan hanya diblokir untuk penggunaan lokal sampai sync selesai.
5. Cegah legacy sync identitas menimpa profil/identitas vaulted. Legacy discovery dicatat sebagai kandidat adopsi; profil lama tidak masuk vault tanpa adopsi eksplisit. Default boleh diadopsi dan didistribusikan.
6. Daftarkan operasi profile.sync untuk permintaan manual; sediakan kontrak pull sekarang, worker handler pada task 10. Revisi lokal tidak otomatis mengubah vault.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task 07: Vault profil berversi dan kontrak tarik/ACK.
Baca plan/00-OVERVIEW.md dan seluruh file task ini. Tidak perlu membaca task lain.
1. Periksa git status --short, git log -5 --oneline, dan diff file dalam allowlist.
   Pertahankan perubahan lokal yang sudah ada. Verifikasi prasyarat: 03.
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
   Perbarui HANYA baris 07 pada plan/PROGRESS.md: status, tanggal Asia/Jakarta,
   ringkasan perubahan, perintah/hasil verifikasi, dan sisa hambatan.
   Tandai selesai hanya jika semua kriteria terpenuhi; selain itu sedang/terblokir.
7. Laporkan hasil dan risiko singkat, lalu berhenti. Jangan mulai task berikutnya.
```

## Kriteria selesai

- Sesi default dan root/user1 terpisah dapat berada di vault.
- ACK revision lama tidak mengaktifkan revision baru.
- Worker baru/offline/disabled tercatat dengan benar.
- Cross-worker auth tidak dapat mengklaim ACK worker lain atau membaca bundle tanpa assignment.
- Test mencakup kegagalan dan kompatibilitas, bukan hanya jalur sukses.
- Tidak ada perubahan di luar allowlist atau rahasia dalam diff/log hasil kerja.
- PROGRESS mencatat hasil nyata dan status task; pekerjaan task berikutnya belum dimulai.

## Cara verifikasi

Jalankan dari root repository:

```text
python -m unittest tests.test_profile_sync_contract tests.test_profile_provisioning tests.test_backend_api -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Seluruh test memakai data temporary dan mock layanan eksternal. Jangan menggunakan sesi TDL/Telegram produksi untuk test otomatis.

Jika tool verifikasi tidak tersedia, catat hambatan dan jangan mengklaim lulus. Bandingkan kegagalan dengan baseline tanpa mengubah source di luar allowlist.

## Rollback

Matikan pull capability/gate, biarkan revision dan ciphertext tetap tersimpan. Jangan kembali ke push legacy untuk menimpa sesi yang telah maju tanpa explicit source snapshot.

Untuk kode, batalkan hanya patch/commit task ini setelah memeriksa dependensi task yang sudah memakai kontraknya. Jangan memakai reset/clean menyeluruh atau membatalkan perubahan lokal sebelumnya. Skema additive dan catatan accepted operation dipertahankan sampai jalur rollback data terverifikasi.
