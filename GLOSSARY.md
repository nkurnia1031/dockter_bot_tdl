# Profil dan Sesi TDL

Istilah ini menjelaskan profil Telegram lokal dan vault yang dipakai aplikasi serta worker.

## Profil

**Profil lokal**:
Sesi TDL yang berada pada worker dan digunakan job pada worker tersebut. Setiap worker memiliki salinan lokalnya sendiri.
_Avoid_: bundle distribusi, sumber distribusi.

**Bundle vault**:
Arsip profil terenkripsi yang disimpan backend sebagai sumber untuk distribusi yang dimulai operator. Job tetap memakai profil lokal worker; menghapus bundle vault tidak menghapus profil lokal.
_Avoid_: sesi aktif worker, sumber sesi job.

**Adopsi profil**:
Operasi eksplisit yang menyalin profil lokal dari worker terpilih ke bundle terenkripsi di vault. Adopsi tidak memasang profil ke worker lain.
_Avoid_: sinkronisasi otomatis, distribusi.

**Distribusi profil**:
Operasi eksplisit yang memasang bundle vault ke profil lokal pada seluruh worker terdaftar dalam satu job. Kemajuan dicatat per worker; worker offline menunggu sampai dapat dijangkau.
_Avoid_: sinkronisasi startup, adopsi.

**Hapus bundle vault**:
Menghapus arsip distribusi dari backend tanpa mengubah profil lokal yang sudah terpasang pada worker.
_Avoid_: hapus profil lokal, sinkronisasi penghapusan ke worker.

**Hapus profil lokal**:
Menghapus profil dan data di dalam folder profil pada worker yang dipilih. Ini terpisah dari penghapusan bundle vault dan tidak memasang ulang profil sampai operator memulai distribusi.
_Avoid_: hapus bundle vault.

**Pasangan sesi**:
Dua storage utama profil, masing-masing untuk lane Download dan Export; keduanya menunjukkan identitas Telegram yang sama. Pasangan ini tidak mencakup lane Upload.
_Avoid_: satu sesi profil, dua pengguna Linux.

**Lane TDL**:
Storage sesi TDL yang dipakai oleh kelas pekerjaan tertentu. Lane Download, Export, dan Upload dipisahkan agar operasi paralel tidak membuka database Bolt yang sama.
_Avoid_: pengguna TDL.

**Lane Upload**:
Storage sesi khusus untuk mengirim file Storage. Lane ini terpisah dari lane Export dan Download, tetapi memakai identitas Telegram profil yang sama.
_Avoid_: sesi Storage bersama, storage Export.

**Tujuan Storage**:
Penyimpanan yang dipilih untuk melihat atau mengunggah file, berupa katalog channel Telegram atau lokasi di remote rclone yang dikonfigurasi.
_Avoid_: worker sebagai tujuan.

**Mode transfer Storage**:
Pilihan salin atau pindah file dari worker ke Tujuan Storage. Salin mempertahankan file sumber; pindah menghapus file sumber hanya setelah upload dipastikan berhasil, sedangkan file gagal atau ambigu tetap disimpan.
_Avoid_: pindah folder katalog.

**Pemindahan katalog Storage**:
Memindahkan item di antara folder katalog Telegram tanpa menghapus file sumber yang berada di worker.
_Avoid_: mode transfer pindah.

**Bukti akses kirim**:
Hasil pemeriksaan bahwa satu profil pada satu worker dapat mengirim ke tujuan tertentu. Bukti berlaku sampai izin atau sesi gagal, tujuan berubah, atau sesi yang diuji berubah.
_Avoid_: kesiapan worker, verifikasi setiap job.

**Hasil upload ambigu**:
Upload sudah mulai dikirim tetapi worker tidak dapat memastikan apakah Telegram menerimanya. File tidak boleh dikirim ulang sebelum rekonsiliasi.
_Avoid_: upload gagal, aman untuk retry.

**Rekonsiliasi upload**:
Pemeriksaan chat tujuan dengan ekspor TDL berisi caption untuk menentukan hasil upload ambigu. Caption yang cocok berarti terkirim; ekspor sukses tanpa kecocokan berarti aman untuk retry.
_Avoid_: retry otomatis tanpa pemeriksaan.

**Identitas proses TDL**:
Akun sistem operasi yang menjalankan proses TDL; identitas ini terpisah dari akun Telegram yang tersimpan di storage sesi.
_Avoid_: identitas profil, pengguna Telegram.

**Identitas profil**:
Satu ID numerik Telegram yang berlaku bagi seluruh pasangan sesi dan menentukan akun serta pemetaan actor profil.
_Avoid_: identitas folder, identitas worker.

**Kesiapan profil worker**:
Status apakah salinan lokal profil pada satu worker lolos pemeriksaan TDL dan cocok dengan identitas profil. Kesiapan dicatat per worker dan tidak menunggu worker lain.
_Avoid_: kesiapan seluruh worker.

**Kesiapan runtime**:
Bukti bahwa kemampuan fitur tertentu tersedia pada satu worker dan, bila diperlukan, satu profil. Bukti berasal dari probe runtime atau canary operasional yang sesuai dengan jalur fitur. Bukti tetap berlaku sampai fingerprint terkait berubah atau kegagalan akses/runtime yang cocok menginvalidasinya.
_Avoid_: status online worker, verifikasi setiap job.

**Scan kesiapan profil**:
Operasi eksplisit yang memeriksa service worker dan menguji lane profil melalui canary terisolasi. Hasil disimpan per worker, profil, service, lane, dan tujuan; pesan canary dihapus setelah verifikasi, sedangkan kegagalan cleanup ditampilkan terpisah dari kesiapan lane.
_Avoid_: scan read-only, satu status global semua worker.

**Kesiapan lane**:
Bukti bahwa lane Export, Download, atau Upload pada satu profil-worker berhasil melewati canary-nya. Kesiapan Download dicatat setelah kecepatan transfer terlihat lalu job canary dibatalkan; pembatalan itu tidak membatalkan hasil lane lain.
_Avoid_: satu kesiapan gabungan profil, hasil job fitur lain.

**Revision vault**:
Versi tertentu dari bundle kanonis di backend yang hanya dipasang ke worker melalui operasi distribusi eksplisit.
_Avoid_: status sync.

**State export bersama**:
Daftar channel dan last message ID yang disimpan backend per profil dan channel. Semua worker memakai state yang sama saat export.
_Avoid_: salinan state per worker.

**Rollback sesi**:
Pemulihan sesi lokal sebelumnya jika bundle baru gagal dipasang atau diuji. Sesi lama hanya boleh dipakai bila masih lolos pemeriksaan TDL dan identitasnya cocok.
_Avoid_: fallback ke sumber profil lain.
