#!/usr/bin/env bash
set -euo pipefail

volume_size="${UTILITY_COMPRESS_SIZE:-4g}"
password="${UTILITY_COMPRESS_PASSWORD:-A1031@bokep@1031A}"
for folder in "$PWD/"*; do
  if [ -d "$folder" ]; then
    output_file="${folder##*/}.7z"
    7z a "$output_file" "$folder" -v"$volume_size" -mx=0 -mhe=on -p"$password" -sdel
  fi
done
