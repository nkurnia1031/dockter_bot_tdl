"""Archive formats recognized by the worker's 7-Zip runtime."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path


# Compound suffixes come first so ``bundle.tar.gz`` gets the output name
# ``bundle``. Keep this list shared by extraction and Utility's inventory.
ARCHIVE_SUFFIXES = (
    ".tar.bzip2", ".tar.bz2", ".tar.gzip", ".tar.gz", ".tar.lzma",
    ".tar.zstd", ".tar.zst", ".tar.xz", ".tar.z", ".tar",
    ".7z", ".zipx", ".zip", ".rar", ".arj", ".cab", ".chm",
    ".chi", ".chq", ".chw", ".cpio", ".cramfs", ".dmg", ".iso",
    ".lha", ".lzh", ".nsis", ".rpm", ".squashfs", ".udf", ".xar",
    ".pkg", ".xip", ".wim", ".swm", ".esd", ".ppkg", ".qcow2c",
    ".qcow2", ".qcow", ".vdi", ".avhdx", ".vhdx", ".vhd", ".vmdk",
    ".deb", ".udeb", ".ova", ".tgz", ".tpz", ".tbz2", ".tbz",
    ".txz", ".tzst", ".taz", ".gzip", ".bzip2", ".lzma86", ".lzma",
    ".bz2", ".zstd", ".zst", ".xz", ".gz", ".z", ".ar", ".lib",
    ".jar", ".xpi", ".odt", ".ods", ".docx", ".xlsx", ".pptx",
    ".epub", ".ipa", ".appx", ".msi", ".msp", ".msm", ".apk",
    ".doc", ".xls", ".ppt", ".aaf", ".apfs", ".b64", ".obj",
    ".elf", ".ext", ".ext2", ".ext3", ".ext4", ".fat", ".flv",
    ".gpt", ".hfs", ".hfsx", ".hxs", ".hxi", ".hxr", ".hxq",
    ".hxw", ".lit", ".img", ".lpimg", ".mbr", ".macho", ".mslz",
    ".mub", ".ntfs", ".exe", ".dll", ".sys", ".pmd", ".swf",
    ".simg", ".te", ".scap", ".uefif", ".ihex",
)

TAR_STREAM_TYPES = {
    ".tar.gz": "GZip",
    ".tar.gzip": "GZip",
    ".tgz": "GZip",
    ".tpz": "GZip",
    ".tar.lzma": "Lzma",
    ".tar.bz2": "BZip2",
    ".tar.bzip2": "BZip2",
    ".tbz": "BZip2",
    ".tbz2": "BZip2",
    ".tar.xz": "Xz",
    ".txz": "Xz",
    ".tar.zst": "Zstd",
    ".tar.zstd": "Zstd",
    ".tzst": "Zstd",
    ".tar.z": "Z",
    ".taz": "Z",
}


def _matching_suffix(
    filename: str, suffixes: Iterable[str]
) -> str | None:
    lower = filename.lower()
    return next((suffix for suffix in suffixes if lower.endswith(suffix)), None)


def archive_suffix(filename: str) -> str | None:
    return _matching_suffix(filename, ARCHIVE_SUFFIXES)


def tar_stream_type(filename: str) -> str | None:
    suffix = _matching_suffix(filename, TAR_STREAM_TYPES)
    return TAR_STREAM_TYPES.get(suffix) if suffix else None


def is_main_archive_filename(
    filename: str, *, has_next_volume: bool = False
) -> bool:
    lower = filename.lower()
    if re.fullmatch(r".+\.part\d+\.rar", lower):
        return re.fullmatch(r".+\.part0*1\.rar", lower) is not None
    if lower.endswith(".7z.001"):
        return True
    if lower.endswith(".001"):
        return has_next_volume
    return archive_suffix(filename) is not None


def is_main_archive_path(path: Path) -> bool:
    lower = path.name.lower()
    has_next_volume = False
    if lower.endswith(".001") and not lower.endswith(".7z.001"):
        next_volume = path.with_name(f"{path.name[:-4]}.002")
        has_next_volume = next_volume.is_file() and not next_volume.is_symlink()
    return is_main_archive_filename(path.name, has_next_volume=has_next_volume)
