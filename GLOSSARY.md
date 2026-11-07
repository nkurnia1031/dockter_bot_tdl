# Profil dan Sesi TDL

Istilah ini menjelaskan profil Telegram lokal dan vault yang dipakai aplikasi serta worker.

## Pemantauan

**Pembaruan manual**:
Memuat ulang data halaman saat pengguna membukanya, meminta refresh, atau menyelesaikan tindakan yang mengubah data. Data umum tidak diperbarui berulang kali tanpa tindakan pengguna.
_Avoid_: polling halaman.

**Polling progres operasi**:
Pembaruan sementara untuk operasi aktif yang sedang ditunggu pengguna pada halaman fitur. Polling berhenti ketika operasi selesai atau pengguna meninggalkan halaman; operasi tetap berjalan di backend.
_Avoid_: monitor global job.

**Monitor Aktivitas**:
Tampilan global job yang terus memperbarui status saat halaman terlihat, dengan pembaruan lebih sering ketika ada job aktif dan lebih jarang ketika idle.
_Avoid_: riwayat pasif.

**Progres transfer rclone**:
Kemajuan file yang sedang ditransfer, termasuk jumlah byte, kecepatan, dan estimasi waktu, bersama hitungan file selesai dari seluruh batch. Progres byte batch ditampilkan bila ukuran semua file diketahui.
_Avoid_: hanya status selesai per file, output mentah rclone.

## Profil

**Profil lokal**:
Sesi TDL yang berada pada worker dan digunakan job pada worker tersebut. Setiap worker memiliki salinan lokalnya sendiri.
_Avoid_: bundle distribusi, sumber distribusi.

**Bundle vault**:
Salinan arsip profil aktif yang dienkripsi dan disimpan backend. Vault menjadi tempat penyimpanan bersama untuk distribusi ke worker; job memakai salinan sesi lokal di worker. Menghapus bundle Vault tidak menghapus salinan lokal.
_Avoid_: sesi aktif worker, sumber sesi job.

**Adopsi profil**:
Operasi yang menyimpan profil aktif dari worker terpilih ke bundle terenkripsi Vault. Distribusi bundle ke worker dicatat sebagai proses tersendiri.
_Avoid_: pull saat startup, pemeriksaan kesiapan untuk setiap job.

**Distribusi profil**:
Pemasangan bundle aktif Vault ke salinan profil lokal pada worker yang dituju. Kemajuan dicatat per worker; status distribusi tidak menjadi gate job dan worker menjalankan perintah dengan sesi lokal yang tersedia.
_Avoid_: pull saat startup, syarat readiness Vault.

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

**Folder tujuan Quick Mode**:
Folder remote rclone tempat arsip hasil satu job Quick Mode disimpan, dipilih atau dibuat untuk job tersebut di bawah tujuan rclone terkonfigurasi.
_Avoid_: tujuan global Quick Mode, tujuan Storage.

**Sinkronisasi katalog Storage Telegram**:
Membandingkan file dan metadata pada channel Telegram Storage dengan katalog aplikasi agar daftar file dan lokasi folder katalog mengikuti isi channel. Operasi ini memperbarui katalog aplikasi dan tidak mengubah pesan atau media Telegram.
_Avoid_: pemulihan database identik, rekonsiliasi upload ambigu.

**Item Storage hasil pemulihan**:
Item katalog yang dibuat ulang dari pesan Telegram ketika data katalog asal tidak tersedia. Operator sync dan profil yang dipakai dicatat sebagai sumber pemulihan; keduanya tidak menyatakan siapa pengunggah asli.
_Avoid_: metadata pengunggah asli, item upload baru.

**Mode transfer Storage**:
Pilihan salin atau pindah file dari worker ke Tujuan Storage. Salin mempertahankan file sumber; pindah menghapus file sumber hanya setelah upload dipastikan berhasil, sedangkan file gagal atau ambigu tetap disimpan.
_Avoid_: pindah folder katalog.

**Rotasi profil upload Telegram Storage**:
Penugasan file upload bergiliran kepada profil lokal dalam satu batch, dengan satu file aktif pada satu waktu. Batch baru memulai urutan dari sender pertamanya.
_Avoid_: upload paralel lintas profil, rotasi lintas batch.

**Konflik upload Storage rclone**:
Jika nama/path file sudah ada pada folder tujuan rclone yang sama, item dilewati tanpa overwrite dan file sumber tetap disimpan pada mode Pindah. Item lain dalam batch tetap diproses.
_Avoid_: benturan dianggap gagal, menimpa tujuan, menghapus sumber yang dilewati.

**Pemindahan katalog Storage**:
Memindahkan item di antara folder katalog Telegram tanpa menghapus file sumber yang berada di worker.
_Avoid_: mode transfer pindah.

**Bukti akses channel**:
Hasil pemeriksaan bahwa lane profil-worker dapat menjalankan `tdl chat export` pada channel tujuan. Untuk lane Upload Storage dan TTS, scan memakai akses baca ke channel sebagai bukti tujuan tersedia; channel kosong tetap membuktikan akses bila perintah berhasil. Ini tidak menguji izin mengirim file.
_Avoid_: bukti izin upload, kesiapan worker, verifikasi setiap job.

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
ID numerik Telegram yang memetakan profil ke actor aplikasi. Identitas ini menetapkan kepemilikan profil di aplikasi, tetapi tidak menyatakan akun yang sedang dipakai sesi TDL.
_Avoid_: akun sesi aktif, identitas folder, identitas worker.

**Kesiapan profil worker**:
Status operasional profil pada satu worker yang dicatat terpisah dari worker lain. Status lane ditentukan oleh kemampuan nyata mengakses tujuan fitur, bukan kecocokan akun sesi dengan metadata profil.
_Avoid_: kesiapan seluruh worker, kecocokan identitas sebagai bukti akses.

**Kesiapan runtime**:
Status operasional service atau lane pada worker, dan bila relevan pada profil, untuk membantu operator memilih tujuan kerja. Perubahan sidik sesi tidak memblokir operasi; keberhasilan atau kegagalan perintah nyata memperbarui status terkait.
_Avoid_: status online worker, kecocokan fingerprint sebagai syarat job.

**Scan kesiapan profil**:
Operasi eksplisit yang memeriksa service worker dan menguji lane profil melalui canary. Hasil dipisahkan per worker, profil, service, dan lane; kegagalan cleanup canary dilaporkan terpisah dari hasil akses.
_Avoid_: scan read-only, satu status global semua worker.

**Scan worker**:
Scan kesiapan profil yang mencakup seluruh profil dan service/lane pada satu worker terpilih, tanpa mengubah hasil worker lain.
_Avoid_: scan semua worker, scan satu sel.

**Scan Storage worker**:
Pemeriksaan akses Storage pada worker terpilih yang menguji profil-profil lokal satu per satu dan melaporkan hasil tiap profil.
_Avoid_: status Storage global, scan profil tanpa target worker.

**Scan terpilih**:
Scan kesiapan profil yang hanya memeriksa satu service worker atau satu lane/service pada profil-worker yang dipilih operator, beserta dependency langsungnya. Sel readiness lain dan waktu pemeriksaannya tetap tersimpan.
_Avoid_: scan parsial otomatis, scan semua worker.

**Scan penuh**:
Scan kesiapan profil eksplisit yang memeriksa semua worker aktif, profil lokal, service, dan lane.
_Avoid_: scan otomatis, refresh readiness berkala.

**Kesiapan lane**:
Status operasional lane Export, Download, atau Upload pada satu profil-worker. Keberhasilan atau kegagalan perintah nyata memperbarui status lane itu; perubahan fingerprint saja tidak memblokir job.
_Avoid_: satu kesiapan gabungan profil, kecocokan fingerprint sebagai syarat job.

**Revision vault**:
Versi tertentu dari bundle kanonis di backend yang hanya dipasang ke worker melalui operasi distribusi eksplisit.
_Avoid_: status sync.

**State export bersama**:
Daftar channel dan last message ID yang disimpan backend per profil dan channel. Semua worker memakai state yang sama saat export.
_Avoid_: salinan state per worker.

**Rollback sesi**:
Pemulihan sesi lokal sebelumnya jika bundle baru gagal dipasang atau diuji. Sesi lama hanya boleh dipakai bila masih lolos pemeriksaan TDL dan identitasnya cocok.
_Avoid_: fallback ke sumber profil lain.

## Storage

**Unduhan Storage**:
Salinan file atau folder dari Telegram atau rclone ke folder `/workspace` pada worker yang dipilih, tanpa mengubah file sumber. Folder diunduh rekursif dengan struktur relatif tetap.
_Avoid_: delivery Telegram, download artifact export.

**Link unduhan publik**:
URL per file pada domain worker yang dapat dipakai siapa pun yang memilikinya tanpa login dan tetap berlaku sampai dicabut manual. Link disimpan di halaman Storage; mencabutnya juga menghapus file di path worker terkait.
_Avoid_: deep link Telegram, link sementara.

**Ringkasan folder Storage**:
Jumlah file dan subfolder serta ukuran seluruh file di folder dan semua turunannya. Ukuran ditandai tidak lengkap bila ada ukuran file yang tidak diketahui.
_Avoid_: hitungan isi langsung, total ukuran parsial tanpa penanda.

**Pengelolaan remote rclone**:
Pengaturan file dan folder pada root `rclone_destination` di worker terpilih: membuat folder, rename, copy, move, Trash, restore, dan hapus permanen. Operasi batch atau folder rekursif melaporkan hasil per item; benturan tidak menimpa data.
_Avoid_: akses ke remote atau path di luar root yang dikonfigurasi.

## Resolver

**Bookmarklet Resolver**:
JavaScript bookmark yang disalin operator dan dijalankan pada halaman Safelink yang sedang dibuka. Setiap klik memajukan paling banyak satu tahap; operator mengulanginya setelah halaman berpindah sampai URL akhir ditampilkan dan dapat disalin.
_Avoid_: resolver otomatis seluruh tahap di worker.

## Utility

**Kumpulan kandidat password arsip**:
Password unik yang ditemukan selama pemrosesan arsip dalam satu folder pilihan. Kandidat dicoba ulang hanya pada arsip yang belum berhasil di folder yang sama.
_Avoid_: password bersama lintas folder, password yang ditampilkan di laporan.

**Preview Flatten**:
Simulasi lengkap perubahan susunan folder pilihan sampai tidak ada tindakan lanjutan. Preview menjadi dasar konfirmasi; perubahan pada salah satu folder membatalkan seluruh batch apply.
_Avoid_: daftar tindakan parsial, apply atas preview yang sudah stale.

**Flatten folder**:
Perapian isi direktori dengan menghapus subfolder kosong dan menaikkan isi subfolder yang hanya memiliki satu item. Subfolder dengan lebih dari satu item tetap utuh; benturan nama mendapat nama unik tanpa menimpa data.
_Avoid_: flatten rekursif tanpa batas, overwrite saat benturan.
