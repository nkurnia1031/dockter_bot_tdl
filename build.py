#!/usr/bin/env python3
"""Create a clean deployment archive for the Docker service."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


ROOT = Path(__file__).resolve().parent
BASE_IMAGE_TAR = ROOT / "images" / "tme3bot-base.tar"
BASE_IMAGE_MANIFEST = ROOT / "base-image-manifest.json"
BASE_FINGERPRINT_FILES = (
    "Dockerfile.base",
    "requirements.txt",
    "leave-helper/go.mod",
    "leave-helper/main.go",
)

# Only source/runtime files are needed to build and run the container.
INCLUDE_ROOTS = (
    "bot.py",
    "Dockerfile",
    "Dockerfile.base",
    "Dockerfile.web",
    "base-image-manifest.json",
    "docker-compose.yml",
    "docker-compose.gateway.yml",
    "docker-compose.worker.yml",
    ".dockerignore",
    ".docker",
    ".env.example",
    ".env.backend.example",
    ".env.telegram.example",
    ".env.worker.example",
    ".env.worker.local.example",
    ".env.web.example",
    "requirements.txt",
    "build.py",
    "run.py",
    "README.md",
    "DEPLOYMENT_RUNBOOK.md",
    "AGENTS.md",
    "tme3bot",
    "utility",
    "leave-helper",
    "web",
)

EXCLUDED_NAMES = {
    ".env",
    ".git",
    ".codex",
    ".agents",
    ".tdl",
    ".venv",
    "node_modules",
    ".next",
    "test-results",
    "playwright-report",
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
    "profiles.json",
    "identity.json",
    "labels.json",
    "utility_folders.json",
    "worker_routes.json",
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


def build_archive(
    output: Path,
    extra_files: tuple[tuple[Path, str], ...] = (),
    *,
    include_base_image: bool = True,
) -> tuple[int, int]:
    output = output.resolve()
    files = iter_files()
    output.parent.mkdir(parents=True, exist_ok=True)
    extras = list(extra_files)
    if include_base_image and BASE_IMAGE_TAR.is_file():
        extras.append((BASE_IMAGE_TAR, "images/tme3bot-base.tar"))
        if BASE_IMAGE_MANIFEST.is_file():
            extras.append((BASE_IMAGE_MANIFEST, "base-image-manifest.json"))
            if base_manifest_is_current(BASE_IMAGE_MANIFEST) is False:
                print(
                    "WARNING: source/dependency fingerprint berubah; "
                    "base image perlu dibuat ulang di VPS besar."
                )
        else:
            print(
                "WARNING: images/tme3bot-base.tar ditemukan tetapi "
                "base-image-manifest.json tidak ada; kompatibilitas base tidak dapat diverifikasi."
            )
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
        seen_names: set[str] = {
            path.relative_to(ROOT).as_posix() for path in files
        }
        for path, archive_name in extras:
            if archive_name in seen_names:
                continue
            seen_names.add(archive_name)
            archive.write(path, archive_name, compress_type=ZIP_STORED)
    return len(files), output.stat().st_size


def build_migration_archive(output: Path, image_tar: Path) -> tuple[int, int]:
    """Package deployable source files together with prebuilt Docker images."""
    return build_archive(
        output,
        extra_files=((image_tar, "images/tme3bot-images.tar"),),
        include_base_image=False,
    )


def build_base_archive(
    output: Path, image_tar: Path, manifest: Path | None = None
) -> tuple[int, int]:
    """Package source plus the one-time prebuilt worker/runtime base image."""
    extras = [(image_tar, "images/tme3bot-base.tar")]
    if manifest is not None:
        extras.append((manifest, "base-image-manifest.json"))
    return build_archive(
        output,
        extra_files=tuple(extras),
        include_base_image=False,
    )


def base_fingerprint() -> str:
    digest = hashlib.sha256()
    for relative in BASE_FINGERPRINT_FILES:
        path = ROOT / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if not path.is_file():
            digest.update(b"<missing>\0")
            continue
        digest.update(path.read_bytes())
        digest.update(b"\0")
    host_tdl = ROOT / ".docker" / "tdl" / "tdl"
    digest.update(b".docker/tdl/tdl\0")
    digest.update(host_tdl.read_bytes() if host_tdl.is_file() else b"<missing>")
    return digest.hexdigest()


def make_base_manifest(image: str, platform: str) -> dict[str, object]:
    return {
        "schema": 1,
        "image": image,
        "platform": platform,
        "fingerprint": base_fingerprint(),
        "components": list(BASE_FINGERPRINT_FILES),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def base_manifest_is_current(path: Path = BASE_IMAGE_MANIFEST) -> bool | None:
    """Return True/False when a manifest exists, otherwise None."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return str(payload.get("fingerprint", "")) == base_fingerprint()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a clean Docker deployment zip.")
    parser.add_argument("-o", "--output", default="output.zip", help="Output zip path")
    parser.add_argument(
        "--base-image-tar",
        help="Also package a previously exported base image tar as images/tme3bot-base.tar",
    )
    args = parser.parse_args()
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    if args.base_image_tar:
        count, size = build_base_archive(output, Path(args.base_image_tar))
    else:
        count, size = build_archive(output)
    print(f"Created: {output}")
    print(f"Files: {count}")
    print(f"Size: {size / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
