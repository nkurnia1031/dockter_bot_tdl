# P0 — Akses production dari laptop tepercaya

## Tujuan

Daftarkan laptop sekali melalui Pengaturan dari sesi Web yang sudah login. Sesudah disetujui, agent pada akun Windows ini dapat membuat sesi production pada browser/headless baru tanpa persetujuan bot Telegram berulang.

Task ini adalah **rencana implementasi**, belum menyatakan fitur aktif atau perangkat production sudah terdaftar. Identitas memakai pasangan kunci Ed25519, bukan MAC address, IP, hostname atau fingerprint browser. Label perangkat hanya metadata.

## Prasyarat

Tidak bergantung pada task 01–22, Redis, atau settings store baru. Kerjakan P0 sebelum task 01. Baca [overview](00-OVERVIEW.md) dan periksa [progres](PROGRESS.md); agent cukup membaca dua dokumen ini untuk melaksanakan P0.

Backend menggunakan SQLite auth yang sudah ada. Pendaftaran nyata memerlukan sesi Web terautentikasi dan keputusan pengguna di Pengaturan; implementasi serta test lokal memakai actor/layanan mock.

Baseline audit: main commit c5c76b3 dengan perubahan lokal yang sudah dicatat di overview. Jangan membatalkan perubahan lokal tersebut.

## Konteks khusus task

- `tme3bot/infrastructure/auth.py:BotAuthService` membuat challenge Telegram, access token, refresh token dan sesi SQLite.
- `SqliteAuthRepository.create_single_session()` mencabut seluruh sesi actor saat login baru. `tests/test_auth_service.py:test_new_login_revokes_previous_web_session` mengunci perilaku itu.
- `tme3bot/api/backend.py` menyediakan cookie browser, refresh/logout, current_actor dan pemeriksaan CSRF. Cookie access/refresh memakai HttpOnly, Secure dan SameSite=Lax.
- `web/src/lib/session.svelte.ts:restore()` memulihkan sesi melalui API browser. Frontend tidak boleh memperoleh private key atau menandatangani challenge perangkat.
- `web/src/lib/components/SettingsPage.svelte` adalah titik pengelolaan perangkat; Web tetap SvelteKit static.
- Dependency `cryptography` sudah tersedia. Gunakan Ed25519 dari library tersebut, bukan implementasi kriptografi sendiri.
- Environment Windows lokal menyediakan Python Playwright dan Chrome. Runner repository mengimpor state melalui `browser.new_context(storage_state=...)`; verifikasi HTTPS headless dilakukan terhadap fixture lokal. Ini tidak mendaftarkan perangkat atau mengakses production.

## File yang disentuh

Path relatif terhadap root repository. Tidak ada penghapusan file yang direncanakan. Perubahan file berikut hanya dilakukan oleh agent pelaksana P0, bukan pada penyusunan dokumen ini.

| Aksi | Path yang diizinkan |
|---|---|
| Diubah | `tme3bot/infrastructure/auth.py` |
| Diubah | `tme3bot/api/backend.py` |
| Diubah | `tme3bot/api/schemas.py` |
| Diubah | `tme3bot/composition.py` |
| Diubah | `web/src/lib/api.ts` |
| Diubah | `web/src/lib/api.test.ts` |
| Diubah | `web/src/lib/session.svelte.ts` |
| Diubah | `web/src/lib/session.test.ts` |
| Diubah | `web/src/lib/components/SettingsPage.svelte` |
| Diubah | `tests/test_auth_service.py` |
| Diubah | `tests/test_backend_api.py` |
| Diubah | `AGENTS.md` |
| Baru | `tme3bot/infrastructure/device_auth.py` |
| Baru | `tme3bot/api/routes/devices.py` |
| Baru | `tools/trusted_device.py` |
| Baru | `tools/trusted_device_store.py` |
| Baru | `tools/trusted_device_browser.py` |
| Baru | `tests/test_device_auth.py` |
| Baru | `tests/test_trusted_device_helper.py` |
| Baru | `tests/test_trusted_device_browser_e2e.py` |
| Baru | `web/src/lib/components/TrustedDevices.svelte` |
| Baru | `web/src/lib/components/TrustedDevices.test.ts` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output graphify update) |

Pisahkan logika perangkat dari file backend.py yang besar; backend.py hanya wiring dan pemakaian helper cookie/auth bersama. Task 20 nantinya mempertahankan komponen TrustedDevices ini.

## Kontrak dan perilaku

### API perangkat milik actor

| Endpoint | Input | Hasil dan otorisasi |
|---|---|---|
| POST /api/v1/auth/devices | device_id, name, public_key, algorithm=Ed25519, origin | 201 metadata perangkat; hanya sesi Web login dengan CSRF, actor berasal dari sesi |
| GET /api/v1/auth/devices | Tidak ada secret | Daftar milik actor: ID, nama, fingerprint, created_at, last_used_at, revoked_at/status |
| PATCH /api/v1/auth/devices/{id} | name | Ubah nama milik actor dengan CSRF; key/owner immutable |
| DELETE /api/v1/auth/devices/{id} | Tidak ada | Cabut perangkat dan semua sesi turunannya secara atomik; idempotent dan CSRF |
| POST /api/v1/auth/device/challenge | device_id | challenge_id, nonce, expires_at, origin, protocol_version; tidak menerbitkan sesi |
| POST /api/v1/auth/device/exchange | device_id, challenge_id, signature | Cookie browser dan DTO sesi yang sama dengan login Web; tanpa token dalam JSON |

Public key adalah raw Ed25519 32 byte dengan encoding base64url; fingerprint adalah SHA-256 public key. Private key tidak pernah menjadi field API.

Helper membuat UUID device_id sebelum pendaftaran dan menyimpannya bersama metadata origin. Backend menerima ID unik tersebut, sehingga helper tidak perlu menyalin token/ID rahasia dari browser. Public key tidak boleh terdaftar ulang pada actor lain. Duplikat identik milik actor yang sama mengembalikan metadata yang sama; konflik ID/key ditolak 409. Key yang telah dicabut tidak dapat diaktifkan lagi melalui upload ulang; pendaftaran ulang menggunakan pasangan kunci baru.

Origin harus cocok persis dengan origin Web HTTPS yang dikonfigurasi pada backend, bukan dari Host header yang tidak dipercaya. API URL untuk helper harus memakai origin tersebut dan jalur API situs yang ditetapkan; jangan mengikuti redirect lintas origin ketika membawa credential.

### Challenge dan signature

- Nonce acak 32 byte, expiry dari server 120 detik, dan konsumsi sekali pakai melalui transaksi SQLite.
- Backend menyimpan payload challenge yang persis ditandatangani. Format UTF-8 kanonis: tujuh baris tanpa newline terakhir, berurutan protocol `tme3-device-auth-v1`, purpose `browser-session`, origin, device_id, challenge_id, nonce base64url, expiry Unix seconds desimal. Semua field ID/nonce/origin divalidasi agar tidak mengandung CR/LF.
- Signature mencakup seluruh payload. Helper memeriksa origin, versi dan expiry sebelum menandatangani; tidak menandatangani bytes arbitrary yang diminta server.
- Exchange memverifikasi key, payload tersimpan, expiry, status device dan actor; konsumsi challenge dan pembuatan sesi dalam transaksi yang sama. Dua exchange bersamaan hanya satu berhasil.
- Challenge dibatasi 10 per menit per device, maksimal 3 belum dikonsumsi; percobaan exchange salah dibatasi 5 per challenge. Terapkan pula batas 60 request challenge/exchange per menit per alamat koneksi terpercaya untuk menahan unknown-ID spam.
- Counter pembatasan memakai repository SQLite; tidak memerlukan Redis. Jangan percaya X-Forwarded-For sembarang request. Unknown/revoked device dan signature salah tidak mengungkap owner/key melalui pesan error.
- Endpoint challenge/exchange tidak memakai CSRF sesi karena belum login; bukti signature dan scope origin menggantikannya untuk autentikasi perangkat. Endpoint CRUD tetap memakai CSRF dan otorisasi Web.

### Sesi dan pencabutan

Tambahkan `session_kind` (telegram/device) dan `device_id` nullable melalui migrasi additive. Sesi Web existing dimigrasikan menjadi telegram.

Login Telegram mencabut hanya sesi telegram sebelumnya. Login perangkat membuat sesi device terpisah tanpa mencabut sesi pengguna atau agent lain; pola refresh/cookie expiry tetap mengikuti konfigurasi auth yang ada. Sesi service bot yang sudah ada tidak berubah.

Pada exchange, refresh, dan setiap pemakaian access token device, periksa device masih aktif dan actor masih authorized. Device tidak menambah akses profil/worker di luar actor tersebut. Pencabutan membuat access token yang belum expired pun tidak berlaku.

Trust key tidak memiliki expiry otomatis; berlaku sampai dicabut. Browser session tetap memiliki expiry dan refresh rotation. Logout mencabut sesi browser saat ini; tidak mencabut perangkat dan tidak diam-diam memanggil helper untuk login ulang. Pengguna memilih Cabut perangkat untuk menghentikan seluruh akses turunannya.

### Helper Windows

Gunakan empat subcommand pada `tools/trusted_device.py`:

| Perintah | Perilaku |
|---|---|
| init --origin URL --name LABEL | Buat Ed25519 sekali dan berkas enrollment public; tidak menghubungi production atau menimpa key existing |
| prepare-browser --origin URL | Ambil challenge, sign, exchange; keluarkan hanya path state browser privat dan metadata non-secret |
| status --origin URL | Tampilkan device ID, fingerprint, origin, status credential lokal; tidak mencetak key/cookie |
| forget-local --origin URL | Hapus credential lokal setelah tindakan eksplisit, bukan otomatis pada error; tidak mengklaim sudah mencabut device server |

Root lokal adalah direktori khusus aplikasi di bawah LOCALAPPDATA pengguna Windows, di luar repo. Pisahkan per origin menggunakan hash origin. Kunci dienkripsi memakai DPAPI scope CurrentUser tanpa CRYPTPROTECT_LOCAL_MACHINE, ACL hanya pengguna terkait dan akun sistem yang diperlukan. Jangan fallback plaintext jika DPAPI/ACL gagal. Operasi helper pada platform lain menampilkan unsupported yang jelas; backend tetap Python 3.10/Ubuntu 22.04.

Gunakan wrapper DPAPI terbatas di trusted_device_store.py dengan API Windows standar; jangan menambah ketergantungan Windows pada import backend Linux. Buffer key tidak dicetak atau disimpan plaintext. DPAPI mengikat akses ke akun Windows; jangan menjanjikan identitas hardware atau perlindungan terhadap proses lain yang berjalan sebagai pengguna yang sama.

Berkas enrollment berisi versi, device_id, origin, name, public_key dan fingerprint saja. Web menghitung ulang fingerprint sebelum persetujuan. Tidak ada rahasia dalam berkas itu.

State browser mengikuti format Playwright storage_state (cookies dan origins), membawa cookie access/refresh/CSRF dengan domain/path/secure/httpOnly/sameSite/expiry yang diterbitkan server. Jangan menurunkan atribut cookie atau mengembalikan token melalui stdout. File state sementara harus diberi ACL sebelum bytes credential ditulis, path selalu di root lokal aplikasi, dan tidak ditaruh dalam repo atau temp bersama.

Runner `tools/trusted_device_browser.py` mengimpor state langsung ke Playwright context, membatasi request pada origin terdaftar, lalu menghapus file setelah import. `open_trusted_context()` dapat dipakai agent Python untuk interaksi Playwright selanjutnya. Jika browser gagal dibuka, runner juga menghapus file state. Helper membersihkan state miliknya yang tertinggal lebih dari 5 menit pada invocation berikutnya. Tidak ada janji cleanup otomatis saat seluruh mesin mati; ACL dan expiry sesi tetap berlaku.

### Web dan workflow agent

Tambahkan komponen Perangkat tepercaya pada Settings. Sediakan upload enrollment, pemeriksaan fingerprint/origin, konfirmasi pengguna, daftar, rename dan revoke. Metadata di-refresh saat mount/aksi atau melalui tombol Refresh; tidak ada polling baru.

Pada AGENTS.md, tulis urutan untuk pekerjaan production yang sudah diotorisasi: periksa helper status, prepare-browser, import state dengan tool yang mendukung, bersihkan file state, lalu periksa sesi. Jangan membaca file state melalui tool yang mencetak isinya, screenshot token, atau menyalin credential ke percakapan.

Jika browser automation tidak mendukung import state, berhenti pada laporan keterbatasan integrasi. Jangan memasang token di URL, menonaktifkan auth, atau otomatis memulai login Telegram. Browser biasa yang bersih tetap membutuhkan helper atau login normal; website tidak dapat mengambil key laptop dengan sendirinya.

## Spesifikasi implementasi

1. Verifikasi source auth/cookie/test baseline. Tambahkan schema additive device/challenge/rate counters serta kolom sesi tanpa menghapus sesi Telegram lama.
2. Implementasikan DeviceAuthService di modul terpisah: register, list, rename, revoke, challenge, exchange, dan pemeriksaan status pada sesi device. Gunakan kriptografi library dan transaksi untuk replay/revocation race.
3. Pasang route dengan dependency actor/CSRF yang sudah ada. Gunakan helper cookie existing; public API/log tidak berisi private key, signature lengkap, token atau cookie.
4. Implementasikan helper dan DPAPI store terpisah dari runtime backend. Terapkan origin pinning, ACL, duplicate init protection, output metadata saja dan lifecycle file browser state.
5. Tambahkan komponen Settings untuk enrollment public key dan pengelolaan perangkat. Pertahankan login Telegram normal, restore browser serta logout eksplisit.
6. Tambahkan instruksi agent hanya untuk akses production yang sudah diotorisasi. Jangan mendaftarkan laptop ini, menjalankan helper production atau melakukan deployment selama task implementasi lokal.
7. Tambahkan test unit, contract, Web, dan HTTPS headless menggunakan Chrome/Playwright lokal. Catat kemampuan browser automation yang benar-benar diverifikasi; jangan menyatakan headless end-to-end lulus hanya dari response HTTP.
8. Jalankan verifikasi, periksa diff dan perbarui hanya baris P0 pada PROGRESS. Berhenti sebelum task 01.

## Prompt untuk agent pelaksana

```text
Kerjakan HANYA task P0: Akses production dari laptop tepercaya.
Baca plan/00-OVERVIEW.md dan seluruh plan/00-PRIORITY-trusted-device-access.md.
1. Periksa git status --short, git log -5 --oneline, dan diff baseline.
   Gunakan graphify query untuk relasi auth, lalu source aktual.
2. Task ini mandiri, tidak membutuhkan Redis/task 01–22. Ikuti seluruh
   Kontrak dan perilaku serta Spesifikasi implementasi di file P0.
3. Edit hanya allowlist P0 menggunakan apply_patch. Pertahankan Python 3.10,
   SQLite auth existing, Web statis, CSRF, batas actor dan perubahan lokal.
4. Jangan deploy, commit, mendaftarkan perangkat production, membaca secret
   production, atau mengakses production. Test memakai fixture/mock lokal.
   Jangan menampilkan private key, cookie, token atau isi file browser state.
5. Jalankan Cara verifikasi dan seluruh Kriteria selesai. Tool/browser yang
   tidak tersedia dicatat sebagai belum terverifikasi, bukan lulus.
6. Jika kontrak memerlukan file di luar allowlist, catat bukti dan hambatan;
   jangan memperluas pekerjaan atau mengerjakan task lain.
7. Perbarui hanya baris P0 di plan/PROGRESS.md dengan status, tanggal,
   perubahan, hasil verifikasi dan risiko. Selesai hanya bila kriteria terpenuhi.
8. Laporkan hasil singkat lalu berhenti. Jangan mulai task 01.
```

## Kriteria selesai

- Public enrollment yang disetujui actor mengikat key ke actor tersebut; private key tidak keluar dari laptop.
- Browser/headless baru pada lingkungan test dapat memuat state hasil helper tanpa challenge Telegram. Verifikasi dengan tool yang benar-benar mendukung import; catat bila tool tersebut belum tersedia.
- Restart helper/laptop tidak menghapus credential; DPAPI user berbeda gagal membuka key pada uji Windows lokal.
- Challenge expired, signature salah, ID/origin/purpose berubah, replay dan exchange bersamaan ditolak sesuai kontrak.
- CRUD device actor lain dan request mutating tanpa CSRF ditolak; unknown device tidak mengungkap metadata pemilik.
- Rate limit tetap efektif pada restart backend dan ketika beberapa proses membuat request bersamaan.
- Revoke memutus access/refresh lama serta exchange yang berlomba dengan revoke; actor kehilangan izin juga kehilangan akses.
- Login device tidak mengeluarkan sesi Telegram atau device lain. Dua login Telegram tetap mencabut sesi Telegram sebelumnya.
- Logout tidak memicu re-auth otomatis; forget-local tidak disalahartikan sebagai server revoke.
- Web tidak melakukan polling perangkat; halaman bersih tanpa helper tidak mengklaim mengenali laptop.
- API daftar, log, stdout, repository dan URL tidak memuat private key, signature penuh, cookie, refresh token atau access token.
- Backend Linux dapat import/start tanpa Windows API. Helper unsupported/DPAPI gagal tidak menyimpan plaintext.
- File state dibuat privat sebelum diisi, dihapus setelah import/gagal, dan stale cleanup tidak keluar dari root aplikasi.
- Semua verifikasi dan keterbatasan dicatat di PROGRESS; produksi tidak diubah.

## Cara verifikasi

Dari root repository, dengan fixture dan mock:

```text
python -m unittest tests.test_device_auth tests.test_trusted_device_helper tests.test_auth_service tests.test_backend_api -v
python -m compileall -q tme3bot tools
git diff --check
graphify update .
git diff --check
```

Uji browser HTTPS lokal pada Windows (sertifikat CA sementara dipasang pada CurrentUser Root selama test dan dibersihkan sesudahnya):

```powershell
$env:TME3_RUN_TRUSTED_DEVICE_BROWSER_E2E = "1"
python -m unittest tests.test_trusted_device_browser_e2e -v
Remove-Item Env:TME3_RUN_TRUSTED_DEVICE_BROWSER_E2E
```

Test memakai backend, actor, key, dan HTTPS origin loopback sementara. Ia memastikan Chrome mengimpor sesi, lalu menolak sesi lama setelah revoke. TLS verification dan atribut Secure cookie tetap aktif.

Dari web/:

```text
pnpm check
pnpm test
pnpm build
```

Pada Windows, test helper meliputi round-trip DPAPI, ACL file sebelum write, origin isolation, restart, dan cleanup memakai direktori test privat. Test platform lain memakai mock DPAPI; tidak diklaim sebagai verifikasi DPAPI Windows.

Uji browser lokal dengan HTTPS fixture/mock yang sesuai Secure cookie: jalankan prepare-browser, import state, pastikan authenticated actor, lalu revoke dan pastikan sesi lama ditolak. Gunakan key/actor test sekali pakai. Jangan menonaktifkan TLS verification atau Secure cookie pada jalur production untuk membuat test lolos.

## Rollback

Hentikan admission device login dan cabut seluruh sesi device terlebih dahulu, lalu lepaskan route/helper/UI bila perlu. Pertahankan login Telegram, session_kind dan tabel additive agar downgrade tidak menghidupkan kembali sesi device yang telah dicabut. Jalur legacy harus menolak sesi device saat fitur dinonaktifkan.

Jangan menghapus key lokal pengguna secara otomatis saat rollback kode. Pengguna dapat mencabut di server dan menjalankan forget-local secara eksplisit. Jika credential hilang, pendaftaran ulang memakai key baru dan persetujuan Web; tidak ada fallback MAC/IP.

Rollback hanya patch P0 setelah memeriksa task dependent. Jangan reset/clean worktree atau mengembalikan auth database lama di atas pencabutan/sesi baru.

## Referensi teknis

- [Microsoft: DPAPI CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/seccrypto/example-c-program-using-cryptprotectdata) — perlindungan key dalam scope pengguna Windows.
- [MDN: secure cookie configuration](https://developer.mozilla.org/en-US/docs/Web/Security/Practical_implementation_guides/Cookies) — atribut cookie tetap dipertahankan.
