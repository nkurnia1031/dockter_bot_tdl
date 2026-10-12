# Vault backend sebagai distributor profil

- Status: diterima
- Tanggal: 2026-10-12

## Konteks

TDL harus berjalan di worker dan membuka sesi `.tdl` yang tersedia pada filesystem worker tersebut. Saat akun baru dibuat atau perlu login ulang, operator sekarang harus menyiapkan sesi pada satu tempat lalu memindahkannya ke worker lain secara manual.

Istilah “sync profil” juga sempat dipakai untuk dua hal berbeda: distribusi sesi `.tdl` dan state export seperti daftar channel serta `last_id`. Pencampuran ini membuat ACK distribusi vault terlihat seperti bukti bahwa runtime worker selalu dapat membaca revision terbaru. Pada Issue #2, worker melaporkan `waiting_worker` setelah permintaan manifest ditolak dengan HTTP 426, walaupun ACK distribusi sebelumnya menyatakan revision terpasang.

## Keputusan

1. Backend vault menyimpan satu bundle profil kanonis dan menjadi sumber distribusinya.
2. Setiap worker tetap memiliki salinan sesi `.tdl` lokal; proses TDL selalu memakai salinan lokal pada worker tersebut.
3. Setelah satu profil dibuat atau diperbarui, backend mendistribusikan revision baru ke worker. Worker memasang bundle baru hanya setelah validasi TDL berhasil.
4. Status berlaku per worker. Worker yang sudah berhasil memasang dan memeriksa profil boleh bekerja walaupun worker lain offline atau gagal menerima revision.
5. Jika pemasangan revision baru gagal, worker mempertahankan sesi sebelumnya. Sesi itu tetap boleh digunakan hanya jika pemeriksaan TDL lulus dan identitasnya cocok dengan identitas profil.
6. Profil tidak memiliki pilihan runtime “lokal atau vault”. Vault mengelola distribusi; worker menjalankan sesi lokal hasil distribusi.
7. Daftar channel dan `last_id` export adalah state bersama yang terpisah. Backend menyimpannya sebagai satu kebenaran per profil dan channel; worker membacanya saat export, bukan dengan menyalin state antar-worker.
8. Job hanya bergantung pada kesiapan profil di worker yang ditargetkan jika job itu memang memakai profil tersebut. Profil yang belum terdistribusi pada worker lain dan sync yang tidak terkait tidak menjadi penghalang umum.
9. Control request, metadata manifest, dan status worker memakai API internal terautentikasi yang sudah ada. Byte arsip profil terenkripsi berpindah melalui channel backup privat; akun pengunduh harus memiliki akses ke channel tersebut. Arsip tidak diunduh melalui endpoint HTTP bundle.

## Konsekuensi

- UI harus membedakan revision yang diminta backend, revision yang terpasang, dan kesiapan sesi lokal pada tiap worker.
- ACK vault saja tidak cukup untuk menyatakan worker siap, tetapi kegagalan mengambil manifest juga tidak boleh dilabeli seolah sesi lokal rusak.
- Pemeriksaan skema/IP reverse proxy pada API profile-sync dihapus. TLS berakhir di reverse proxy sehingga backend tidak dapat memakai skema hop internal untuk menilai koneksi worker. Worker tetap wajib memakai URL HTTPS untuk backend remote dan menolak redirect; backend tetap memeriksa bearer internal serta token unik worker. Tidak ada `BACKEND_TRUSTED_PROXY_IPS`.
- Channel backup menjadi jalur untuk byte arsip profil, dengan enkripsi bundle dan kontrol akses channel sebagai lapisan keamanan yang diterima maintainer. API internal tetap mengatur operasi dan status. Pemindahan byte bundle dari API ke channel belum diterapkan; issue #2 tetap terbuka sampai implementasi dan verifikasi production selesai.
- Distribusi ulang dapat diulang pada worker tertentu tanpa mengganti sesi worker lain yang sudah siap.
- Perubahan ini tidak mengubah kepemilikan state export backend yang sudah ada.

## Alternatif yang ditolak

- Menyimpan dua sesi aktif terpisah di setiap worker lalu memilih lokal atau vault saat menjalankan job. Ini menambah pemilihan sumber dan status tanpa diperlukan untuk tujuan distribusi otomatis.
- Menganggap seluruh fleet sebagai satu kesiapan global. Worker offline akan menahan worker lain yang sudah memiliki sesi valid.
