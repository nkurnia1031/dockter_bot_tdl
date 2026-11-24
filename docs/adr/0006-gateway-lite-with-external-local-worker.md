---
status: accepted
---

# Gateway Lite dengan worker eksternal bernama `local`

Gateway Lite dipindahkan ke remote-2 tanpa paket worker lokal, sementara worker, Aria2, TTS, profil, database worker, dan Workspace yang saat ini berada di gateway lama tetap hidup sebagai worker eksternal bernama `local`. `ui.utama.naufix.space` menjadi UI sekaligus endpoint API gateway di remote-2; `bot.utama.naufix.space` tetap pada host lama sebagai endpoint HTTPS worker. Pemisahan ini mempertahankan beban kerja lokal dan nama target yang sudah dikenal, tetapi memerlukan dukungan registry Lite untuk worker eksternal bernama `local`, drain job sebelum restart, serta koordinasi DNS dan satu poller Telegram.
