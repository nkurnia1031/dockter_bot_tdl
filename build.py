#!/usr/bin/env python3
"""Create a clean deployment archive for the Docker service."""

from __future__ import annotations

import argparse
import fnmatch
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent

# Only source/runtime files are needed to build and run the container.
INCLUDE_ROOTS = (
    "bot.py",
    "Dockerfile",
    "docker-compose.yml",
    ".dockerignore",
    ".docker",
    ".env.example",
    "requirements.txt",
    "run.py",
    "README.md",
    "AGENTS.md",
    "tme3bot",
    "utility",
    "leave-helper",
)

EXCLUDED_NAMES = {
    ".env",
    ".git",
    ".codex",
    ".agents",
    ".tdl",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "tests",
    "graphify-out",
}

EXCLUDED_PATTERNS = (
    "*.pyc",
    "*.pyo",
    "*.tmp",
    "*.zip",
    "state.json",
    "max.json",
    "profile_state.json",
    "identity.json",
    "labels.json",
    "utility_folders.json",
)


def is_excluded(path: Path) -> bool:
    relative_parts = path.relative_to(ROOT).parts
    if any(part in EXCLUDED_NAMES for part in relative_parts):
        return True
    return any(
        fnmatch.fnmatch(path.name, pattern)
        or fnmatch.fnmatch(str(path.relative_to(ROOT)).replace(os.sep, "/"), pattern)
        for pattern in EXCLUDED_PATTERNS
    )


def iter_files() -> list[Path]:
    files: list[Path] = []
    for root_name in INCLUDE_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        if root.is_file():
            if not is_excluded(root):
                files.append(root)
            continue
        for path in root.rglob("*"):
            if path.is_file() and not is_excluded(path):
                files.append(path)
    return sorted(set(files), key=lambda item: str(item.relative_to(ROOT)).lower())


def build_archive(output: Path) -> tuple[int, int]:
    output = output.resolve()
    files = iter_files()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    return len(files), output.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a clean Docker deployment zip.")
    parser.add_argument("-o", "--output", default="output.zip", help="Output zip path")
    args = parser.parse_args()
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    count, size = build_archive(output)
    print(f"Created: {output}")
    print(f"Files: {count}")
    print(f"Size: {size / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
