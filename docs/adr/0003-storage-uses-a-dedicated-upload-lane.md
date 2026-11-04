---
status: accepted
---

# Storage upload memakai lane TDL khusus

Upload Storage memakai storage TDL ketiga per profil, terpisah dari lane Download dan Export. Worker membuatnya dari sesi Export yang sudah diperiksa dan memvalidasi sesi lokal saat startup. Scan profil menguji akses channel Storage dengan `tdl chat export -T last -i 1` melalui lane Upload; scan tidak mengirim pesan atau file marker. Ekspor yang berhasil membuktikan akses ke channel meskipun channel kosong, tetapi tidak membuktikan izin mengirim. Upload job tetap memakai lane Upload, dan hasil command upload yang nyata menjadi bukti keberhasilan atau kegagalan kirim. Pemisahan ini memungkinkan satu upload aktif per profil tanpa mengunci lane Export atau Download; worker tidak memakai lane Export sebagai fallback untuk upload Storage.
