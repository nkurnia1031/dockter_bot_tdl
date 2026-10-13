---
status: accepted
---

# Rekonsiliasi upload Storage sebelum retry

Jika worker kehilangan hasil setelah upload dimulai, file masuk status ambigu dan tidak langsung dikirim ulang. Worker mengekspor chat Storage dengan TDL `--with-content` dari waktu job dikirim sampai waktu pemeriksaan, lalu mencocokkan caption persis yang dibuat untuk file tersebut. Ekspor berhasil dengan satu atau lebih kecocokan berarti file sudah terkirim; ekspor berhasil tanpa kecocokan berarti file aman untuk di-retry. Jika ekspor gagal atau tidak lengkap, status tetap ambigu dan tidak ada retry otomatis. Ini mencegah retry buta yang bisa membuat duplikasi sambil memungkinkan pemulihan otomatis berdasarkan bukti di chat.
