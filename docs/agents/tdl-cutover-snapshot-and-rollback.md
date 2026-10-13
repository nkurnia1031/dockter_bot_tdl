# Snapshot, canary, dan rollback storage TDL

Runbook ini mengamankan dua storage TDL pada satu worker sebelum cutover image yang menjalankan semua proses TDL sebagai root. Jalankan terpisah untuk setiap worker. Dokumen ini tidak mengubah vault dan tidak menjalankan deployment production.

Cakupan snapshot:

```text
default:         root/.tdl, user1/.tdl
profiles/<nama>: root/.tdl, user1/.tdl
```

`root/.tdl` adalah lane Download dan `user1/.tdl` adalah lane Export. Keduanya tetap database Bolt terpisah. Identity, state/cursor, export, download, konfigurasi, dan data lain di `/data` tidak masuk snapshot atau rollback.

## Gerbang sebelum snapshot

1. Pastikan bukti backup profil untuk worker/profil canary diterima operator sesuai issue #5. Canary hanya untuk profil dengan kedua sesi yang lolos pemeriksaan.
2. Nonaktifkan admission worker target dari halaman Workers. Tunggu semua job TDL aktif selesai; toggle hanya memblokir job baru.
3. Catat nama worker, image aktif, waktu UTC, dan profil lokal yang tersedia. Pastikan tidak ada operasi login atau penggantian sesi yang berjalan.
4. Jalankan perintah host sebagai `root` agar owner dan permission numerik dapat dipulihkan.

Jika storage lane yang diharapkan tidak ada, worker masih menjalankan TDL, atau ada provisioning yang belum selesai, hentikan prosedur dan selesaikan diagnosis.

## Buat snapshot worker idle

Pilih baris host yang sesuai:

| Host | Env Compose | Compose file | Service |
|---|---|---|---|
| Gateway, worker lokal | `.env` | `docker-compose.gateway.yml` | `worker-local` |
| VPS worker remote | `.env.worker` | `docker-compose.worker.yml` | `worker` |

Isi variabel sesuai baris tabel. Jalankan dari direktori repository pada host worker:

```bash
set -euo pipefail
umask 077

NODE_NAME='remote-1'                 # Nama worker di halaman Workers
ENV_FILE='.env.worker'               # Pilih baris tabel di atas
COMPOSE_FILE='docker-compose.worker.yml'
SERVICE='worker'
[[ "$NODE_NAME" =~ ^[a-z0-9_-]{1,64}$ ]] || { echo 'Nama worker tidak valid.' >&2; exit 1; }

CID="$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps -q "$SERVICE")"
test -n "$CID" || { echo 'Container worker tidak ditemukan.' >&2; exit 1; }
DATA_ROOT="$(docker inspect "$CID" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')"
test -n "$DATA_ROOT" || { echo 'Mount /data worker tidak ditemukan.' >&2; exit 1; }
DATA_ROOT="$(realpath -e "$DATA_ROOT")"
test -d "$DATA_ROOT" || { echo 'PROFILE_ROOT tidak dapat dibaca.' >&2; exit 1; }

SNAPSHOT_ROOT="$(realpath -m /var/backups/tme3bot/tdl-cutover)"
case "$SNAPSHOT_ROOT/" in "$DATA_ROOT/"*) echo 'Snapshot harus di luar PROFILE_ROOT.' >&2; exit 1 ;; esac
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SNAPSHOT_DIR="$SNAPSHOT_ROOT/${NODE_NAME}-${STAMP}"
ARCHIVE="$SNAPSHOT_DIR/tdl-storages.tar"
install -d -m 0700 "$SNAPSHOT_ROOT"
mkdir -m 0700 "$SNAPSHOT_DIR"
docker inspect "$CID" --format 'image={{.Config.Image}} image_id={{.Image}}' > "$SNAPSHOT_DIR/worker-image.txt"

# Profil default berada langsung di PROFILE_ROOT.
TDL_PATHS=(root/.tdl user1/.tdl)
for relative in "${TDL_PATHS[@]}"; do
  test -d "$DATA_ROOT/$relative" || { printf 'Storage default hilang: %s\n' "$relative" >&2; exit 1; }
done

has_symlink_component() {
  local path="$DATA_ROOT"
  local component
  local -a components
  IFS='/' read -r -a components <<< "$1"
  for component in "${components[@]}"; do
    path="$path/$component"
    [[ -L "$path" ]] && return 0
  done
  return 1
}

# Profil tambahan harus memiliki kedua lane. Nama profil memakai slug tervalidasi.
if [[ -L "$DATA_ROOT/profiles" ]]; then echo 'PROFILES_ROOT berupa symlink; inventarisasi manual diperlukan.' >&2; exit 1; fi
shopt -s nullglob
for profile_dir in "$DATA_ROOT"/profiles/.*; do
  test -d "$profile_dir" || continue
  case "${profile_dir##*/}" in .|..) continue ;; esac
  if [[ -e "$profile_dir/root/.tdl" || -e "$profile_dir/user1/.tdl" ]]; then
    echo 'Staging profil tersembunyi ditemukan; selesaikan atau tinjau sebelum snapshot.' >&2
    exit 1
  fi
done
for profile_dir in "$DATA_ROOT"/profiles/*; do
  test -d "$profile_dir" || continue
  [[ ! -L "$profile_dir" ]] || { echo 'Direktori profil berupa symlink; hentikan.' >&2; exit 1; }
  profile_name="${profile_dir##*/}"
  [[ "$profile_name" =~ ^[a-z0-9_-]{1,48}$ ]] || { echo 'Nama direktori profil tidak valid; periksa inventory manual.' >&2; exit 1; }
  for lane in root user1; do
    relative="profiles/$profile_name/$lane/.tdl"
    test -d "$DATA_ROOT/$relative" || { printf 'Storage profil tidak lengkap: %s\n' "$relative" >&2; exit 1; }
    TDL_PATHS+=("$relative")
  done
done

# Symlink atau file khusus perlu ditinjau karena dapat menunjuk ke data di luar snapshot.
for relative in "${TDL_PATHS[@]}"; do
  if has_symlink_component "$relative" || [[ -n "$(find "$DATA_ROOT/$relative" -type l -print -quit)" ]]; then printf 'Symlink ditemukan pada %s; hentikan dan inventarisasi targetnya.\n' "$relative" >&2; exit 1; fi
  if [[ -n "$(find "$DATA_ROOT/$relative" ! -type f ! -type d -print -quit)" ]]; then printf 'File khusus ditemukan pada %s; hentikan dan tinjau manual.\n' "$relative" >&2; exit 1; fi
done

printf '%s\n' "${TDL_PATHS[@]}" | sort > "$SNAPSHOT_DIR/tdl-paths.txt"
chmod 0600 "$SNAPSHOT_DIR/tdl-paths.txt" "$SNAPSHOT_DIR/worker-image.txt"
(
  cd "$DATA_ROOT"
  for relative in "${TDL_PATHS[@]}"; do find "$relative" -printf '%m\t%U:%G\t%s\t%y\t%p\n'; done
) | sort > "$SNAPSHOT_DIR/tdl-metadata.tsv"
chmod 0600 "$SNAPSHOT_DIR/tdl-metadata.tsv"

# Admission sudah ditutup dan seluruh job TDL terminal; stop hanya worker utama.
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" stop "$SERVICE"
tar --create --file="$ARCHIVE" --format=pax --numeric-owner --acls --xattrs --directory="$DATA_ROOT" -- "${TDL_PATHS[@]}"
chmod 0600 "$ARCHIVE"
tar --list --verbose --numeric-owner --file="$ARCHIVE" > "$SNAPSHOT_DIR/archive-metadata.txt"
chmod 0600 "$SNAPSHOT_DIR/archive-metadata.txt"

# Bandingkan isi, ukuran, mode, owner, dan waktu modifikasi sebelum cutover.
# Output metadata nama file disimpan privat, tidak dicetak.
(cd "$DATA_ROOT" && tar --compare --file="$ARCHIVE") > "$SNAPSHOT_DIR/source-compare.log" 2>&1
test ! -s "$SNAPSHOT_DIR/source-compare.log" || { echo 'Snapshot berbeda dari storage sumber.' >&2; exit 1; }
(cd "$SNAPSHOT_DIR" && sha256sum tdl-storages.tar > SHA256SUMS)
chmod 0600 "$SNAPSHOT_DIR/SHA256SUMS" "$SNAPSHOT_DIR/source-compare.log"
printf 'Snapshot siap: %s\n' "$SNAPSHOT_DIR"
```

Setelah blok berhasil, worker utama tetap berhenti sampai cutover terpisah
dijalankan. Backend dan worker lain tetap aktif. Simpan snapshot pada media
backup yang disetujui, terpisah dari volume `/data`. Arsip memuat sesi Telegram;
batasi akses seluruh direktori snapshot ke operator berwenang.

Jika perintah gagal setelah `docker compose stop` tetapi sebelum `Snapshot siap`,
jangan lakukan cutover dan jangan gunakan arsip parsial. Periksa kode keluar dan
log privat, lalu pulihkan worker lama dengan menjalankan perintah berikut dari
shell yang sama dengan blok di atas:

```bash
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" start "$SERVICE"
```

Tunggu sampai worker sehat sebelum membuka admission kembali. Arsip parsial
tetap perlakukan sebagai data sesi sensitif; jangan hapus sampai operator
memastikan snapshot valid atau artefak itu tidak diperlukan untuk diagnosis.
Setelah worker pulih, tutup admission dan drain ulang sebelum mengulang snapshot.

Pastikan arsip, checksum, daftar path, metadata owner/mode, referensi image lama,
dan file compare tersedia. `source-compare.log` harus kosong. Perintah membuat
metadata dan daftar path, bukan isi database sesi.

## Canary setelah cutover disetujui

Cutover image dilakukan melalui prosedur deployment terpisah; runbook ini tidak
berisi perintah deploy production. Canary menunggu bukti issue #5 diterima operator.

1. Canary-kan satu worker dan satu profil. Jangan mengaktifkan atau mengubah vault.
2. Setelah worker online, jalankan **Scan** di halaman Profil. Identitas dan
   kedua sesi harus siap; UI menampilkan lane Download dan Export.
3. Jalankan satu Export kecil dan satu Download artifact kecil secara bersamaan
   pada worker/profil yang sama. Gunakan sumber uji pilihan operator dan catat
   cursor sebelum Export karena Export dapat memperbarui cursor backend.
4. Pastikan kedua job berhasil, log menunjukkan lane masing-masing, kedua sesi
   tetap memiliki identitas yang sama, serta tidak ada error permission,
   database, atau authorization. Export dan Download harus memakai storage
   terpisah.
5. Setelah operator menerima hasilnya, aktifkan kembali admission worker.
   Pertahankan snapshot sampai masa penerimaan selesai, lalu ulangi untuk worker
   berikutnya. Kesiapan satu worker tidak menunggu worker lain yang offline.

## Rollback ke image sebelumnya

Rollback berlaku untuk satu worker ketika job TDL-nya idle. Perubahan sesi
setelah snapshot akan hilang dari lane aktif. Snapshot tidak memulihkan
`state.json`, cursor backend, artifact, export, download, identity, atau file
lain di `/data`.

1. Nonaktifkan admission worker dan tunggu job aktif terminal.
2. Sebelum menghentikan container, pilih `ENV_FILE`, `COMPOSE_FILE`, dan
   `SERVICE` sesuai tabel. Jalankan di shell yang sama dengan langkah rollback:

   ```bash
   set -euo pipefail
   umask 077
   NODE_NAME='remote-1'
   ENV_FILE='.env.worker'
   COMPOSE_FILE='docker-compose.worker.yml'
   SERVICE='worker'
   CID="$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps -q "$SERVICE")"
   test -n "$CID"
   DATA_ROOT="$(docker inspect "$CID" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')"
   DATA_ROOT="$(realpath -e "$DATA_ROOT")"
   SNAPSHOT_DIR='/var/backups/tme3bot/tdl-cutover/remote-1-REPLACE_WITH_UTC_STAMP'
   STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
   test -d "$DATA_ROOT"
   test -d "$SNAPSHOT_DIR"
   ```

   Ganti variabel host sesuai tabel dan `SNAPSHOT_DIR` dengan path yang dicetak
   saat snapshot dibuat. Jangan menutup shell sebelum langkah restore selesai.
   Referensi di `worker-image.txt` harus menunjuk image sebelum cutover.
3. Hentikan service utama worker dengan Compose sesuai tabel, lalu verifikasi:

   ```bash
   (cd "$SNAPSHOT_DIR" && sha256sum --check SHA256SUMS)
   ```

4. Validasi path snapshot. Daftar harus berisi lane yang dikenal saja:

   ```bash
   test -s "$SNAPSHOT_DIR/tdl-paths.txt"
   if grep -Ev '^(root|user1)/\.tdl$|^profiles/[a-z0-9_-]{1,48}/(root|user1)/\.tdl$' "$SNAPSHOT_DIR/tdl-paths.txt"; then
     echo 'Path di luar lane TDL yang diizinkan; hentikan rollback.' >&2
     exit 1
   fi
   tar --list --file="$SNAPSHOT_DIR/tdl-storages.tar" > "$SNAPSHOT_DIR/restore-archive-paths.txt"
   if grep -Ev '^(root|user1)/\.tdl(/.*)?$|^profiles/[a-z0-9_-]{1,48}/(root|user1)/\.tdl(/.*)?$' "$SNAPSHOT_DIR/restore-archive-paths.txt"; then
     echo 'Anggota arsip di luar lane TDL; hentikan rollback.' >&2
     exit 1
   fi
   if grep -E '(^|/)\.\.?(/|$)' "$SNAPSHOT_DIR/restore-archive-paths.txt"; then
     echo 'Path traversal ditemukan dalam arsip; hentikan rollback.' >&2
     exit 1
   fi
   sort -u "$SNAPSHOT_DIR/tdl-paths.txt" | cmp -s - "$SNAPSHOT_DIR/tdl-paths.txt"
   while IFS= read -r relative; do
     current="$DATA_ROOT"
     IFS='/' read -r -a components <<< "$relative"
     for component in "${components[@]}"; do
       current="$current/$component"
       [[ ! -L "$current" ]] || { printf 'Symlink pada path target %s; hentikan rollback.\n' "$relative" >&2; exit 1; }
     done
   done < "$SNAPSHOT_DIR/tdl-paths.txt"
   ```

   Pastikan juga anggota arsip hanya berada di bawah lane default atau
   `profiles/<nama>/{root,user1}/.tdl` sebelum ekstraksi.
5. Ekstrak ke staging privat di volume yang sama, lalu bandingkan ekstrak dengan
   arsip dan pastikan semua path terdaftar tersedia. Langkah ini membuat
   `.tdl-restore.*` di bawah `/data`; langkah berikutnya membuat
   `.tdl-after-cutover-*` di lokasi yang sama. Keduanya dapat berisi database
   sesi lengkap. Lindungi sebagai data sensitif, pastikan ruang disk cukup, dan
   pertahankan sampai rollback diterima:

   ```bash
   RESTORE_STAGE="$(mktemp -d "$DATA_ROOT/.tdl-restore.XXXXXX")"
   chmod 0700 "$RESTORE_STAGE"
   tar --extract --file="$SNAPSHOT_DIR/tdl-storages.tar" --numeric-owner --same-owner --same-permissions --acls --xattrs --directory="$RESTORE_STAGE"
   (cd "$RESTORE_STAGE" && tar --compare --file="$SNAPSHOT_DIR/tdl-storages.tar") > "$SNAPSHOT_DIR/restore-compare.log" 2>&1
   while IFS= read -r relative; do test -d "$RESTORE_STAGE/$relative"; done < "$SNAPSHOT_DIR/tdl-paths.txt"
   ```

   Bila compare tidak kosong atau path staging hilang, jangan pindahkan storage aktif.
6. Pindahkan storage pasca-cutover ke hold privat, lalu pasang hanya path yang
   tercatat di daftar snapshot. Worker tetap berhenti:

   ```bash
   HOLD_DIR="$DATA_ROOT/.tdl-after-cutover-${STAMP}"
   install -d -m 0700 "$HOLD_DIR"
   while IFS= read -r relative; do
     test -d "$RESTORE_STAGE/$relative" || { printf 'Path staging hilang: %s\n' "$relative" >&2; exit 1; }
     mkdir -p "$HOLD_DIR/$(dirname "$relative")"
     if [[ -e "$DATA_ROOT/$relative" || -L "$DATA_ROOT/$relative" ]]; then mv -- "$DATA_ROOT/$relative" "$HOLD_DIR/$relative"; fi
     mkdir -p "$(dirname "$DATA_ROOT/$relative")"
     mv -- "$RESTORE_STAGE/$relative" "$DATA_ROOT/$relative"
   done < "$SNAPSHOT_DIR/tdl-paths.txt"
   ```

   Jika berhenti di tengah, biarkan worker berhenti dan pertahankan `HOLD_DIR`,
   `RESTORE_STAGE`, serta snapshot. Jangan hapus atau gabungkan folder manual;
   periksa setiap path yang sudah dipindah sebelum melanjutkan restore.
7. Bandingkan storage aktif dengan arsip. Compare harus kosong:

   ```bash
   (cd "$DATA_ROOT" && tar --compare --file="$SNAPSHOT_DIR/tdl-storages.tar") > "$SNAPSHOT_DIR/post-restore-compare.log" 2>&1
   ```

   Gunakan prosedur deployment terpisah untuk memasang image lama yang tercatat
   di `worker-image.txt`; dokumen ini tidak memberikan perintah deploy.
8. Setelah worker lama hidup, scan profil canary dan pastikan kedua lane lolos.
   Jalankan uji Export/Download terbatas. Aktifkan kembali admission setelah
   operator menerima hasil. Pertahankan arsip dan `HOLD_DIR` sampai rollback
   diterima; hold berisi sesi pasca-cutover dan juga merupakan data sensitif.

GNU tar `--compare` membandingkan ukuran, mode, owner, waktu modifikasi, dan isi
arsip dengan file system. Lihat [panduan resmi GNU tar](https://www.gnu.org/s/tar/manual/html_node/compare.html).
