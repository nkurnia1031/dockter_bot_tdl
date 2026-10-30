#!/usr/bin/env python3
"""Preview or apply a safe, fingerprint-checked Flatten plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tme3bot.utility_flatten import (
    UtilityFlattenPreviewStaleError,
    apply_flatten_batch,
    plan_flatten,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview/apply workspace folder flattening")
    parser.add_argument("root", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fingerprint", help="Fingerprint returned by a matching preview")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if not args.apply:
            print(json.dumps(plan_flatten(root), ensure_ascii=False, indent=2))
            return 0
        if not args.fingerprint:
            parser.error("--apply memerlukan --fingerprint dari preview.")
        result = apply_flatten_batch([root], {str(root): args.fingerprint})
        print(json.dumps(result[0], ensure_ascii=False, indent=2))
        return 0
    except UtilityFlattenPreviewStaleError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
