#!/usr/bin/env bash
set -euo pipefail

volume_size="${UTILITY_COMPRESS_SIZE:-4g}"
password="${UTILITY_COMPRESS_PASSWORD:-A1031@bokep@1031A}"
folders=()
for folder in "$PWD/"*; do
  [[ -d "$folder" ]] && folders+=("$folder")
done

total="${#folders[@]}"
index=0
for folder in "${folders[@]}"; do
  index=$((index + 1))
  output_file="${folder##*/}.7z"
  size_bytes="$(du -sb -- "$folder" | cut -f1)"
  python3 - "$index" "$total" "$folder" "$size_bytes" <<'PY'
import json, sys
print("TME3_PROGRESS " + json.dumps({
    "phase": "compressing",
    "index": int(sys.argv[1]),
    "total": int(sys.argv[2]),
    "name": sys.argv[3].rstrip("/").split("/")[-1],
    "size_bytes": int(sys.argv[4]),
    "indeterminate": False,
}, ensure_ascii=True), flush=True)
PY
  7z a "$output_file" "$folder" -v"$volume_size" -mx=0 -mhe=on -p"$password" -sdel -bsp1 -bb1
  python3 - "$index" "$total" "$output_file" <<'PY'
import json, sys
print("TME3_PROGRESS " + json.dumps({
    "phase": "item_completed",
    "index": int(sys.argv[1]),
    "total": int(sys.argv[2]),
    "name": sys.argv[3],
    "percent": 100,
    "indeterminate": False,
}, ensure_ascii=True), flush=True)
PY
done
