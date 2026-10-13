---
status: accepted
---

# Storage upload memakai lane TDL khusus

Upload Storage memakai storage TDL ketiga per profil, terpisah dari lane Download dan Export. Worker membuatnya dari sesi Export yang sudah diperiksa, lalu memvalidasi lane baru secara read-only saat scan profil dan startup; verifikasi akses ke tujuan Storage mengirim pesan uji melalui lane Upload itu. Pemisahan ini memungkinkan satu upload aktif per profil tanpa mengunci lane Export atau Download. Karena salinan storage tetap membawa identitas sesi Telegram yang sama, canary harus menguji pemakaian paralel sebelum rollout luas; worker tidak memakai lane Export sebagai fallback ketika lane Upload belum siap.
