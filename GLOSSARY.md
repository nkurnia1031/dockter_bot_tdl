# Profil dan Sesi TDL

Istilah ini menjelaskan profil Telegram lokal dan vault yang dipakai aplikasi serta worker.

## Profil

**Profil lokal**:
Sesi TDL yang dimiliki satu worker dan tetap tersedia sebagai sumber lokal.
_Avoid_: profil worker sebagai istilah untuk identitas akun.

**Profil vault**:
Profil bersama yang dikelola backend dan dapat dipasang sebagai salinan terpisah pada worker.
_Avoid_: profil lokal yang disinkronkan.

**Pasangan sesi**:
Dua sesi TDL `root` dan `user1` milik satu profil; keduanya harus menunjukkan identitas Telegram yang sama.
_Avoid_: satu sesi profil.

**Identitas profil**:
Satu ID numerik Telegram yang berlaku bagi seluruh pasangan sesi dan menentukan pemetaan actor sesuai sumber aktif.
_Avoid_: identitas folder, identitas worker.

**Sumber aktif**:
Pilihan profil lokal atau vault yang digunakan untuk satu pasangan worker dan profil; identitas sumber aktif menentukan pemetaan actor profil.
_Avoid_: profil tersinkron.

**Revision vault**:
Versi tertentu dari profil vault yang disimpan backend dan diuji pada worker.
_Avoid_: status sync.

**Siap digunakan**:
Sumber profil yang kedua sesi TDL-nya lolos pemeriksaan dan identitasnya cocok dengan identitas profil.
_Avoid_: ACK siap.

**Fallback**:
Peralihan otomatis dari vault ke profil lokal sebelum perintah TDL dimulai, hanya ketika identitas kedua sumber sama.
_Avoid_: retry dengan profil lain.
