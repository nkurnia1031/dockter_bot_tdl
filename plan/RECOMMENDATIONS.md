# Rekomendasi lanjutan

Dokumen ini dipisahkan dari 23 task wajib (P0 dan 01–22). Perluasan di bawah tidak otomatis menjadi scope agent pelaksana. Beberapa fondasi minimum (misalnya audit metadata dan capability) sudah wajib; rekomendasi menyangkut penguatan sesudah fondasi itu tersedia.

Perkiraan usaha adalah hari kerja engineer dengan konteks repo, bukan janji durasi. Audit pada 2026-10-04; deployment/kapasitas produksi saat ini belum diperiksa.

| Prioritas | Perbaikan | Alasan dan bukti | Usaha | Kapan dilakukan |
|---|---|---|---|---|
| Tinggi | Validasi sesi salinan paralel dan opsi otorisasi terpisah per worker | Direktori berbeda tidak menciptakan auth key Telegram baru. Telegram mendokumentasikan AUTH_KEY_DUPLICATED; perilaku binary TDL yang dipakai belum diuji. | 2–4 hari untuk penelitian/uji, 3–7 hari bila enrollment per worker diperlukan | Sebelum mengaktifkan profile sama lintas worker secara paralel |
| Tinggi | Drill restore otomatis DB + vault + key + desired settings | Vault AES-GCM tidak dapat dipulihkan hanya dari database tanpa kunci. Ledger/outbox harus konsisten dengan snapshot. | 1–3 hari | Sesudah task 22 dan berkala |
| Tinggi | Audit UI yang dapat ditelusuri untuk perubahan profil, cursor, target dan rahasia | Task 08 mencatat audit minimum; operator perlu pencarian actor/operation/revision dan retensi. Tidak menyimpan nilai rahasia. | 2–4 hari | Sesudah settings stabil |
| Sedang | Dashboard antrean dan SLO internal | Bedakan queue age, resource wait, worker latency, outbox lag dan ACK lag; UI lambat tidak selalu berarti CPU worker penuh. | 2–4 hari | Sesudah queue canary |
| Sedang | Tampilan kompatibilitas per worker | Capability/gates sudah wajib; tampilkan alasan worker belum siap, versi kontrak dan tindakan operator pada Workers. | 1–2 hari | Setelah task 20 |
| Sedang | Retensi terukur untuk event/operation/artifact sementara | SQLite/outbox/log dapat tumbuh terus. Cleanup harus mempertahankan unresolved delivery, audit dan checkpoint recovery. | 1–3 hari | Setelah pola penggunaan diketahui |
| Sedang | Resource budget dan admission menurut kapasitas nyata | Redis/RQ menambah proses pada gateway kecil. Ukur RSS, CPU, disk fsync dan antrean; batasi pengiriman tanpa merusak fairness profil. | 2–4 hari | Sebelum memperbanyak worker |
| Sedang | Role operator/admin dan reauthentication untuk perubahan rahasia | Lapisan login yang ada memberi identitas, tetapi perubahan token/vault mempunyai dampak lebih luas daripada menjalankan job. | 3–5 hari | Bila pengguna bertambah |
| Rendah | Evaluasi PostgreSQL | SQLite cukup untuk backend penulis tunggal; kebutuhan beberapa instance backend atau kontensi write berkelanjutan menjadi pemicu evaluasi. | 5–10 hari migrasi | Setelah metrik menunjukkan kebutuhan |
| Rendah | Evaluasi event stream Web | SSE dapat mengurangi polling monitor aktif, tetapi menambah koneksi panjang/reconnect/proxy behavior. Manual refresh dan coordinator sudah memenuhi target awal. | 2–4 hari | Jika polling monitor masih signifikan |

## Batas penting sesi Telegram

[Teks resmi Telegram tentang error](https://core.telegram.org/api/errors) dan [otorisasi data center](https://core.telegram.org/api/datacenter) menjadi dasar risiko auth key. Ini **bukan bukti** bahwa binary TDL pada deployment pengguna sudah mengalami error tersebut. Test otomatis memakai mock; validasi sesi nyata memerlukan langkah operator yang terpisah. Jangan mengubah keputusan distribusi profil menjadi login per worker tanpa keputusan pengguna.

## Dasar pilihan antrean

[RQ](https://python-rq.org/docs/) dipakai untuk orkestrasi Python singkat. Job domain tetap berakhir melalui event worker. [Persistensi Redis](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/) tidak menggantikan transactional outbox SQLite: kehilangan broker tidak boleh menghilangkan request yang sudah diterima.

## Pemicu pemisahan layanan lebih lanjut

Pertahankan satu control plane selama ownership dan kontrak sudah jelas. Pisahkan fitur menjadi service mandiri jika ada kebutuhan deployment, kapasitas, kegagalan atau tim yang benar-benar berbeda. Penambahan service sendiri tidak otomatis mengurangi kerja backend.
