"""Deterministic complete working-source archives for binary release sets."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import List, Tuple

from .identity import MetadataError
from .install import ZIP_TIMESTAMP

VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
PRIVATE_KEY_SUFFIXES = {".key", ".p12", ".pfx", ".pem"}
SENSITIVE_NAMES = {
    ".netrc", "client_secret.json", "credentials.json", "secrets.json",
}


def _excluded(relative: str) -> bool:
    parts = Path(relative).parts
    if not parts:
        return True
    name = parts[-1].lower()
    root_name = parts[0].lower()
    if root_name in {"build", "compiled", "dist", "rom", "rom_eu", "rom_extra"}:
        return True
    if root_name.startswith("release-") or root_name.startswith(".release-"):
        return True
    if any(part.lower() in {".cache", "cache", "caches", "__pycache__"}
           for part in parts) or name.endswith((".pyc", ".pyo")):
        return True
    if name == ".env" or name.startswith(".env."):
        return True
    if (name in SENSITIVE_NAMES
            or name.startswith(("client_secret.", "credentials.", "secrets."))
            or Path(name).suffix in PRIVATE_KEY_SUFFIXES):
        return True
    return False


def _git_listing(root: Path, arguments: List[str], description: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "ls-files", *arguments], cwd=root, check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise MetadataError(f"cannot enumerate {description}: {error}") from error


def build_source_archive(root: Path, output: Path, version: str) -> int:
    """Archive current tracked and untracked non-ignored source files."""
    if not VERSION_PATTERN.fullmatch(version):
        raise MetadataError(f"unsafe source archive version: {version}")
    if output.exists() or output.is_symlink():
        raise MetadataError(f"source archive output already exists: {output}")
    listing = _git_listing(root, ["-s", "-z", "--recurse-submodules"],
                           "tracked source")
    untracked = _git_listing(root, ["--others", "--exclude-standard", "-z"],
                            "untracked source")

    files: List[Tuple[str, Path, int]] = []
    seen = set()
    for record in listing.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode_text = metadata.split(b" ", 1)[0]
            relative = raw_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeError) as error:
            raise MetadataError("git returned an invalid tracked source record") from error
        mode = int(mode_text, 8)
        if mode == 0o160000:
            continue
        if mode not in {0o100644, 0o100755}:
            raise MetadataError(f"unsupported tracked source mode {mode_text!r}: {relative}")
        if relative in seen:
            continue
        seen.add(relative)
        if _excluded(relative):
            continue
        path = root / relative
        try:
            details = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise MetadataError(f"cannot inspect tracked source: {relative}") from error
        if not stat.S_ISREG(details.st_mode):
            raise MetadataError(f"tracked source is not a regular file: {relative}")
        permissions = 0o755 if details.st_mode & 0o111 else 0o644
        files.append((relative, path, permissions))

    for raw_path in untracked.split(b"\0"):
        if not raw_path:
            continue
        try:
            relative = raw_path.decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise MetadataError("git returned an invalid untracked source path") from error
        if relative in seen or _excluded(relative):
            continue
        seen.add(relative)
        path = root / relative
        try:
            details = path.lstat()
        except OSError as error:
            raise MetadataError(f"cannot inspect untracked source: {relative}") from error
        if not stat.S_ISREG(details.st_mode):
            raise MetadataError(f"untracked source is not a regular file: {relative}")
        permissions = 0o755 if details.st_mode & 0o111 else 0o644
        files.append((relative, path, permissions))
    files.sort(key=lambda item: item[0])
    if not files or not any(relative == "COPYING" for relative, _, _ in files):
        raise MetadataError("complete working source must include COPYING")

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    prefix = f"VectorDrive-source-{version}"
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED,
                             allowZip64=True) as archive:
            for relative, path, permissions in files:
                info = zipfile.ZipInfo(f"{prefix}/{relative}", ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | permissions) << 16
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_STORED)
        with zipfile.ZipFile(temporary, "r") as archive:
            if archive.testzip() is not None:
                raise MetadataError("source archive CRC validation failed")
        os.link(temporary, output)
        temporary.unlink()
    except FileExistsError as error:
        raise MetadataError(f"source archive output already exists: {output}") from error
    except MetadataError:
        raise
    except (OSError, zipfile.BadZipFile) as error:
        raise MetadataError(f"cannot build complete source archive: {error}") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return len(files)
