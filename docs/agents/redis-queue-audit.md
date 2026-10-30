# Handoff audit Redis/RQ gateway

Gunakan dokumen ini untuk melanjutkan pemeriksaan Redis/RQ production yang
diminta pengguna pada 2026-10-30. Temuan dan cakupan ini melengkapi status
handoff lama di `AGENTS.md`.

## Temuan dan status awal

- Log production menunjukkan container `bot-redis-1` restart dengan exit code
  1. Redis membaca RDB dasar (`keys loaded: 6`), lalu gagal membaca
  `appendonly.aof.10.incr.aof` karena format file rusak. Healthcheck berulang
  menerima `LOADING`; peringatan `vm.overcommit_memory` bukan penyebab utama.
- Pengguna menyatakan tidak ada job berjalan dan tidak memerlukan pemulihan data.
  Reset volume Redis pernah disarankan; pengguna kemudian melaporkan sudah
  deploy. **Periksa keadaan live saat memulai; jangan anggap reset berhasil atau
  mengulang penghapusan volume.**
- Snapshot API production yang diambil setelah itu menunjukkan 0 job aktif,
  queued, dispatched, atau running. Worker `local`, `remote-1`, dan `remote-2`
  semuanya idle. Ini hanya snapshot job dari API, bukan pengukuran Redis.
- Workspace agent sebelumnya hanya melihat Docker stack worker, tanpa Redis;
  alias SSH `remote-1` tidak resolve. Pengguna berencana menjalankan Codex pada
  VPS gateway agar agent dapat memakai Docker lokal di sana. Pengguna juga
  menyatakan gateway belum menjalankan SSH server; jangan mengandalkan SSH untuk
  audit ini bila agent sudah berjalan langsung pada gateway.

## Izin dan batas audit

Pengguna meminta pengukuran Redis dan queue selama 10 menit, lalu meminta satu
job palsu karena belum ada aktivitas untuk diamati. Di gateway, jalankan audit
baca-saja selama 10 menit dan **maksimal satu** probe RQ no-op yang dijelaskan
di bawah. Jangan mengirim file/pesan, memulai job fitur, atau mengubah data
production lain.

Sebelum probe, pastikan Redis healthy, `backend-queue` ready, dan tidak ada job
production aktif atau queued. Jika syarat ini tidak terpenuhi, jangan enqueue
probe; catat kondisi dan laporkan.

## Probe queue aman

Tidak ada endpoint UI/API untuk no-op job. Gunakan RQ yang sudah berjalan di
service `backend-queue` dengan fungsi `tme3bot.queue_runner.advance_command` dan
ID command acak yang dipastikan belum ada di SQLite outbox.

Fungsi tersebut memanggil endpoint internal untuk ID itu. Karena command tidak
ada, `QueueCommandService` mengembalikan `terminal/command_missing` tanpa
memanggil handler domain atau menulis operation/job. RQ tetap menjalankan satu
task, sehingga probe mengukur enqueue, dequeue, eksekusi, dan completion.
Gunakan queue `tme3bot-operations`, serializer `JSONSerializer`, `job_timeout`
pendek, dan TTL hasil singkat. Catat hanya ID probe, waktu enqueue/completion,
dan status terminal; jangan mencatat token atau environment.

Referensi implementasi: `tme3bot/queue_runner.py`,
`tme3bot/infrastructure/queue_transport.py`,
`tme3bot/composition.py:run_queue`, dan `tme3bot/api/routes/queue.py`.

## Pengukuran 10 menit

1. Verifikasi status container `redis`, `backend-queue`, dan `backend` memakai
   Docker Compose gateway yang benar. Periksa Redis healthcheck, restart count,
   dan log startup terbaru.
2. Simpan baseline sebelum probe. Sampling setiap 30 detik selama 10 menit:
   CPU dan RAM `docker stats`; Redis `INFO stats`, `memory`, `clients`, `cpu`,
   `persistence`, dan `commandstats`; panjang queue dan jumlah worker RQ melalui
   API RQ/read-only Redis client.
3. Enqueue satu probe no-op setelah baseline, lalu catat berapa lama hingga
   selesai dan pastikan statusnya `terminal/command_missing`. Jangan membuat
   probe berulang untuk menaikkan beban.
4. Catat request backend hanya jika ada metrik atau access log yang sudah aktif.
   Jangan mengaktifkan logging baru atau mencetak payload/secret untuk audit.
5. Simpan ringkasan sampling ke berkas `.log` sementara. Laporkan rata-rata,
   puncak, tren/counter awal-akhir, latensi probe, dan metrik yang tidak tersedia.
   Hapus atau redaksi token, cookie, private path, dan payload sebelum membagikan
   log.

Audit selesai setelah 10 menit sampling, satu probe (jika prasyarat siap), dan
ringkasan yang membedakan metrik Redis/RQ langsung dari snapshot job API.
