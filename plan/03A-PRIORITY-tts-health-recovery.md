# P1 — Diagnosis dan pemulihan kesiapan helper TTS

## Tujuan

Sediakan diagnosis per helper dan aksi pemulihan Tor dari Web untuk worker yang capability TTS-nya tidak siap. Kerjakan setelah Task 03 dan sebelum Task 04. Task ini tidak me-restart container Compose.

Dokumen ini adalah instruksi implementasi, bukan bukti fitur sudah tersedia. Semua test memakai process/helper tiruan; jangan akses production atau mengirim request gTTS nyata.

## Prasyarat dan konteks

- Task 03 selesai; Task 04 belum dimulai. Status harus diverifikasi di [PROGRESS](PROGRESS.md).
- `TtsPipeline.ready()` saat ini hanya mengembalikan boolean dari probe tiga endpoint `/readyz`. `WorkerJobExecutor.capabilities()` menerbitkan `tts` hanya dari boolean itu.
- `tts_helper.py` memulai Tor sebagai child process lalu tetap melayani HTTP ketika bootstrap Tor belum berhasil. Compose memakai `restart: unless-stopped` dan healthcheck `/readyz`; status unhealthy saja tidak me-restart proses yang masih hidup.
- `WorkersPage.svelte` menampilkan enable/route worker dan pengaturan TTS, tetapi tidak menampilkan status tiap helper atau aksi recovery. Halaman TTS hanya menampilkan worker yang siap.
- Gunakan worker API internal yang sudah memiliki autentikasi. Jangan pasang Docker socket, shell bebas, URL dari browser, atau polling berkala.

## File yang disentuh

| Aksi | Path |
|---|---|
| Diubah | `tme3bot/worker/tts_helper.py` |
| Diubah | `tme3bot/worker/tts_pipeline.py` |
| Diubah | `tme3bot/worker/executor_tts.py` |
| Diubah | `tme3bot/worker/executor.py` |
| Diubah | `tme3bot/api/worker.py` |
| Diubah | `tme3bot/infrastructure/http_client.py` |
| Diubah | `tme3bot/api/routes/workers.py` |
| Diubah | `tme3bot/api/schemas.py` |
| Diubah | `web/src/lib/components/WorkersPage.svelte` |
| Baru | `web/src/lib/components/WorkersPage.test.ts` |
| Diubah | `tests/test_tts_pipeline.py` |
| Diubah | `tests/test_tts_executor.py` |
| Diubah | `tests/test_worker_api.py` |
| Diubah | `tests/test_backend_api.py` |
| Diubah | `plan/PROGRESS.md` |
| Dihasilkan tool | `graphify-out/` (hanya output `graphify update .`) |

## Kontrak dan perilaku

- Status helper yang boleh ditampilkan: `ready`, `bootstrapping`, `tor_unreachable`, dan `helper_unreachable`; sertakan persen bootstrap jika tersedia. Jangan tampilkan URL internal, path, log Tor mentah, credential, atau IP.
- Capability TTS dan status Web memakai diagnosis yang sama. `GET /internal/v1/tts/health` mengembalikan `{helpers_ready, available_profiles, helpers:[{slot,status,bootstrap_percent,checked_at}]}`. Daftar profile sesi dihitung terpisah dari helper readiness. Public API menentukan `profile_session_ready` dengan mencocokkan profile actor; `ready` memerlukan helper dan sesi profile aktif siap.
- API Web: `GET /api/v1/workers/{worker}/tts/health` mengembalikan `{worker, ready, helpers_ready, profile_session_ready, helpers:[{slot,status,bootstrap_percent,checked_at}]}` untuk profile actor aktif. `ready` memerlukan semua helper dan sesi profile siap. `POST /api/v1/workers/{worker}/tts/helpers/{slot}/recover` menerima slot 1–3 dan mengembalikan 202 `{worker,slot,accepted,status:"restarting"}`. POST memerlukan autentikasi Web dan CSRF yang berlaku.
- Backend meneruskan aksi melalui endpoint worker terautentikasi. Worker memilih URL dari konfigurasi runtime miliknya; request Web tidak boleh memilih host atau path.
- Endpoint internal worker: `GET /internal/v1/tts/health` dan `POST /internal/v1/tts/helpers/{slot}/recover`, keduanya memakai auth worker. Worker memanggil `GET /diagnostics` atau `POST /recover-tor` pada helper di service network privat; endpoint helper tidak dipublikasikan ke host.
- Helper me-restart child Tor secara terkontrol, memakai data directory yang sama, dan tidak menghapus sesi atau data directory. Respons cepat menyatakan aksi diterima; bootstrap berjalan asinkron. `/readyz` tetap menjadi readiness probe Compose.
- Jangan memutus sintesis aktif: satu lock helper mengamankan pemeriksaan recovery dan hitungan request sintesis. Recovery ditolak dengan `TTS_HELPER_BUSY` jika ada request aktif. Permintaan bersamaan digabung; pemulihan dibatasi satu kali per helper dalam 60 detik (`TTS_RECOVERY_COOLDOWN` menyertakan sisa detik). Helper yang sudah `ready` ditolak dengan `TTS_HELPER_ALREADY_READY`; slot di luar 1–3 ditolak dengan 422.
- `TTS_HELPER_BUSY` dan `TTS_HELPER_ALREADY_READY` memakai HTTP 409; `TTS_RECOVERY_COOLDOWN` memakai HTTP 429 dan `Retry-After`; helper/worker tidak terjangkau memakai HTTP 503. `profile_session_ready=false` tampil terpisah dari diagnosis helper.
- Jika worker tidak terjangkau, status API menunjukkan worker unavailable; jika helper yang dipilih tidak terjangkau, recovery ditolak dengan `TTS_HELPER_UNREACHABLE`. GET status tetap mengembalikan helper berstatus `helper_unreachable` saat worker masih dapat dihubungi.
- UI menyediakan **Periksa ulang** dan **Pulihkan** per helper. Sesudah aksi, status berubah lewat refresh manual. Tidak ada timer polling.
- Jika proses helper tidak dapat dihubungi, tampilkan `helper_unreachable`; aksi Web tidak dapat me-restart container itu. Jelaskan bahwa restart container tetap memerlukan supervisor/operator host.

## Prompt implementasi

```text
Kerjakan HANYA P1: Diagnosis dan pemulihan kesiapan helper TTS.
1. Periksa git status/log dan hanya diff path allowlist. Pertahankan seluruh perubahan lokal.
2. Verifikasi Task 03 selesai dan Task 04 belum dimulai. Gunakan graphify query lalu baca source aktual.
3. Implementasikan `GET /diagnostics` dan `POST /recover-tor` di helper. Diagnosis mengembalikan hanya status aman dan persen bootstrap. Recovery Tor memakai satu lock bersama untuk counter sintesis, penghentian child bounded, restart asinkron, data directory yang sama, coalescing concurrent request, dan cooldown 60 detik.
4. Tambahkan `GET /internal/v1/tts/health` dan `POST /internal/v1/tts/helpers/{slot}/recover` dengan auth worker. Tambahkan API Web `GET /api/v1/workers/{worker}/tts/health` dan `POST /api/v1/workers/{worker}/tts/helpers/{slot}/recover` memakai actor auth + CSRF. Backend hanya meneruskan slot, bukan URL bebas.
6. Tambahkan kontrol diagnosis/recovery di WorkersPage. Status worker enabled, kesiapan helper, dan kesiapan sesi profile aktif ditampilkan terpisah. Tombol recovery tidak tersedia untuk helper unreachable; diagnosis dan hasil POST dimuat dengan aksi eksplisit, tanpa polling berkala.
7. Jangan mengakses Docker socket, menjalankan shell, mengubah Compose/restart policy, mengubah perilaku pengiriman TDL, atau mengerjakan Task 04.
8. Tambahkan test mock untuk setiap status, timeout, restart, sintesis aktif, request ganda/cooldown, autentikasi, slot tidak valid, URL injection, dan UI refresh manual.
9. Jalankan verifikasi di bawah. Perbarui hanya baris P1 pada PROGRESS; jangan ubah status task lain. Berhenti setelah task selesai.
```

## Kriteria selesai

- Masing-masing dari tiga helper ditampilkan dengan status yang tepat; satu helper belum siap membuat capability TTS false.
- Recovery berjalan cepat tanpa menunggu bootstrap, tidak memutus sintesis aktif, dan hanya menyasar slot terkonfigurasi.
- Actor tanpa autentikasi/CSRF, worker tanpa token, slot di luar 1–3, dan input host bebas ditolak.
- Helper tak terjangkau ditampilkan sebagai tidak terjangkau tanpa berpura-pura bahwa recovery berhasil.
- WorkersPage tidak melakukan polling otomatis; status berubah setelah refresh manual.
- Test meliputi kegagalan, timeout, concurrent request, cooldown, capability, API, serta UI.
- Tidak ada perubahan selain allowlist dan output graphify; tidak ada deployment atau akses production.

## Verifikasi

```text
python -m unittest tests.test_tts_pipeline tests.test_tts_executor tests.test_worker_api tests.test_backend_api -v
python -m compileall -q tme3bot utility bot.py run.py
git diff --check
graphify update .
git diff --check
```

Di `web/`, jalankan `pnpm check`, `pnpm test -- src/lib/components/WorkersPage.test.ts`, `pnpm test`, dan `pnpm build`. Semua dependency eksternal harus dimock. Jangan menjalankan restart Tor/container atau menghubungi gTTS production.

## Rollback

UI dapat dikembalikan ke tampilan sebelumnya sambil mempertahankan endpoint dan status capability yang aman. Jika endpoint recovery dinonaktifkan, capability tetap mencerminkan readiness nyata. Jangan mengubah restart menjadi akses Docker socket sebagai fallback.
