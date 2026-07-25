# TME3Bot Deployment Runbook

Versi: 3.0 · UI static SvelteKit

Dokumen ini adalah urutan update resmi. Gateway menjalankan tiga container:
`backend`, `telegram`, dan `worker-local`. Dashboard tidak lagi container
Docker dan tidak membutuhkan Node.js di VPS.

## Sekali saja: gateway dan UI

1. Pada `.env.backend`, tambahkan konfigurasi browser. Ganti domain dengan
   domain UI yang benar dan buat secret baru.

```env
WEB_PUBLIC_ORIGIN=https://ui.utama.naufix.space
WEB_COOKIE_SECRET=<openssl rand -hex 32>
WEB_COOKIE_SECURE=true
```

Simpan konfigurasi downloader release di `.env` utama (bukan `.env.backend`,
agar PAT GitHub tidak masuk container backend):

```env
WEB_DEPLOY_ROOT=/www/wwwroot/ui.utama.naufix.space
# Cache release berada di luar document root; dipakai untuk rollback.
WEB_RELEASE_CACHE_ROOT=/www/wwwroot/.tme3bot-ui-releases
WEB_RELEASE_TAG=web-latest
WEB_RELEASE_KEEP=5
# Hanya repository private: PAT GitHub dengan Contents: Read.
WEB_RELEASE_TOKEN=
```

2. Atur reverse proxy domain UI melalui aaPanel sendiri. Template
   `deploy/nginx/tme3bot-ui.conf` hanya referensi untuk location `/api/v1/` dan
   fallback SPA bila diperlukan; script deploy tidak membaca atau me-reload
   konfigurasi Nginx.

3. Pull source dan deploy backend satu kali agar endpoint browser-cookie aktif.
   `--pull` dipakai pada Oracle/host low-memory.

```bash
cd /www/wwwroot/downloads/bot
git pull --ff-only origin main
python3 run.py deploy gateway --pull
```

4. Push source web ke GitHub. Workflow `Publish static web` membuat release
   `web-latest` secara otomatis. Setelah workflow hijau, pasang UI tanpa build:

```bash
python3 run.py deploy web
```

Perintah tersebut mengunduh bundle release, memverifikasi SHA-256, lalu menyalin
isi static bundle ke document root aaPanel. Release cache disimpan di luar
document root untuk rollback. Script tidak mengubah atau me-reload Nginx. VPS
tidak menjalankan `pnpm`, `next build`, Docker web, atau Go build.

## Update biasa

Di komputer lokal:

```bash
python -m compileall -q tme3bot utility bot.py run.py
cd web && pnpm check && pnpm test && pnpm build && cd ..
git diff --check
git add .
git commit -m "jelaskan perubahan"
git push origin main
```

Jika hanya file `web/` berubah, tunggu workflow GitHub Actions selesai lalu di
gateway jalankan:

```bash
git pull --ff-only origin main
python3 run.py deploy web
```

Jika backend/telegram/worker-local berubah, publish image di VPS besar atau CI
registry seperti biasa, kemudian di gateway low-memory jalankan:

```bash
git pull --ff-only origin main
python3 run.py deploy gateway --pull
python3 run.py deploy web
```

Worker remote hanya perlu update bila file worker/Python worker berubah:

```bash
cd /www/wwwroot/downloads/bot
git pull --ff-only origin main
python3 run.py deploy worker --pull
```

## Rollback

Rollback UI tidak menyentuh data, Docker, sesi TDL, atau backend:

```bash
python3 run.py deploy web --rollback
```

Rollback gateway/worker memakai commit dan immutable image tag yang sesuai:

```bash
git log --oneline -5
git checkout <commit-stabil>
python3 run.py deploy gateway --pull
```

Kembali ke branch utama:

```bash
git switch main
git pull --ff-only origin main
```

## Pemeriksaan setelah deploy

```bash
docker compose -f docker-compose.gateway.yml ps
curl -fsS http://127.0.0.1:8080/healthz
curl -I https://ui.utama.naufix.space/build-info.json
```

`build-info.json` harus berisi revision commit yang sama dengan release web.
HTML tidak di-cache; hanya aset `/_app/immutable/` yang immutable dan diberi
nama hash. Jika UI lama muncul, cek domain yang benar dan baca build-info,
bukan cache/chunk Next.js—runtime Next sudah tidak digunakan.

## Batas keamanan

- Browser hanya memanggil `/api/v1` pada domain UI yang sama.
- Access/refresh token berada di cookie HttpOnly Secure; tidak boleh masuk
  localStorage, JavaScript, build-info, atau log browser.
- Semua mutation browser mengirim token CSRF dan harus berasal dari
  `WEB_PUBLIC_ORIGIN`.
- `WEB_RELEASE_TOKEN` hanya diperlukan untuk repository private dan tidak
  boleh dimasukkan ke Git.
