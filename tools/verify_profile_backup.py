from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tme3bot.profile_backup_verifier import verify_profile_backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verifikasi arsip backup worker tanpa memulihkan sesi aktif."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--parts-dir", required=True, type=Path)
    parser.add_argument("--tdl-diagnostics-json", required=True, type=Path)
    parser.add_argument("--catalog-db", type=Path, default=Path("/data/storage.db"))
    parser.add_argument(
        "--settings-file", type=Path, default=Path("/data/utility_settings.json")
    )
    args = parser.parse_args(argv)
    try:
        if args.tdl_diagnostics_json.is_symlink() or not args.tdl_diagnostics_json.is_file():
            raise ValueError
        tdl_diagnostics = json.loads(args.tdl_diagnostics_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        tdl_diagnostics = None
    report = verify_profile_backup(
        run_id=args.run_id,
        node_name=args.worker,
        profile=args.profile,
        parts_dir=args.parts_dir,
        catalog_db=args.catalog_db,
        settings_file=args.settings_file,
        tdl_diagnostics=tdl_diagnostics if tdl_diagnostics is not None else {},
    )
    json.dump(report, sys.stdout, ensure_ascii=True, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["status"] == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
