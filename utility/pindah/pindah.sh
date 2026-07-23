#!/usr/bin/env bash
set -euo pipefail

# Semua tahap harus memakai folder target yang sama. pindah.py membaca
# output.json secara relatif, sehingga working directory wajib diubah dahulu.
DIR="${1:-${PWD}}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -d "$DIR" ]]; then
    echo "Folder tidak ditemukan: $DIR" >&2
    exit 1
fi

cd -- "$DIR"
python3 "$SCRIPT_DIR/pindah4.py" "$DIR"
python3 "$SCRIPT_DIR/pindah.py"
python3 "$SCRIPT_DIR/pindah2.py" "$DIR"
