"""ROM tree scanning and deterministic scan JSON output."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Sequence, Tuple

from .identity import MetadataError, identify_plain, identify_zip

SUPPORTED_EXTENSIONS = {
    "zip", "bin", "pco", "smd", "gen", "md", "iso", "cso", "cue", "chd",
    "32x", "sms", "gg",
}
MAX_RECORDS = 512
INVALID_FAT_CHARS = set('<>:"\\|?*')
RESERVED_FAT_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def validate_runtime_path(value: str, label: str = "runtime path") -> str:
    if not isinstance(value, str) or not value:
        raise MetadataError(f"{label} must be a non-empty string")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as error:
        raise MetadataError(f"{label} must contain ASCII characters only: {value!r}") from error
    if len(encoded) > 255:
        raise MetadataError(f"{label} exceeds 255 bytes: {value!r}")
    if value.startswith("/") or "\\" in value or ":" in value:
        raise MetadataError(f"{label} must be application-relative with forward slashes: {value!r}")
    parts = value.split("/")
    for part in parts:
        if not part or part in {".", ".."}:
            raise MetadataError(f"{label} contains an empty or traversing segment: {value!r}")
        if part.endswith((".", " ")):
            raise MetadataError(f"{label} has a trailing dot or space: {value!r}")
        if any(not 0x20 <= ord(character) <= 0x7E or character in INVALID_FAT_CHARS
               for character in part):
            raise MetadataError(f"{label} contains a FAT-unsafe character: {value!r}")
        if part.split(".", 1)[0].upper() in RESERVED_FAT_NAMES:
            raise MetadataError(f"{label} uses a reserved FAT name: {value!r}")
    return value


def _extension(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def _directory_files(source: Path) -> Iterable[Tuple[Path, str]]:
    def walk_error(error: OSError) -> None:
        raise MetadataError(f"cannot scan directory: {error}") from error

    for root, directories, files in os.walk(source, followlinks=False, onerror=walk_error):
        directories[:] = sorted(
            directory for directory in directories
            if not (Path(root) / directory).is_symlink()
        )
        for filename in sorted(files):
            path = Path(root) / filename
            if path.is_symlink() or _extension(path) not in SUPPORTED_EXTENSIONS:
                continue
            relative = path.relative_to(source).as_posix()
            yield path, relative


def _record(path: Path, rom: str) -> Dict[str, object]:
    extension = PurePosixPath(rom).suffix.lower().lstrip(".")
    identity = identify_zip(path) if extension == "zip" else identify_plain(path, extension)
    return {"rom": rom, **identity}


def scan_mappings(mappings: Sequence[Tuple[str, str]]) -> Dict[str, object]:
    records: List[Dict[str, object]] = []
    collisions: Dict[str, str] = {}
    if not mappings:
        raise MetadataError("at least one --input SOURCE PSP_DEST mapping is required")

    for source_value, destination_value in mappings:
        source = Path(source_value)
        destination = validate_runtime_path(destination_value, "PSP destination")
        if source.is_symlink():
            raise MetadataError(f"explicit input may not be a symlink: {source_value}")
        if not source.exists():
            raise MetadataError(f"input does not exist: {source_value}")
        if source.is_file():
            if _extension(source) not in SUPPORTED_EXTENSIONS:
                raise MetadataError(f"unsupported explicit input: {source_value}")
            destination_extension = PurePosixPath(destination).suffix.lower().lstrip(".")
            if destination_extension not in SUPPORTED_EXTENSIONS:
                raise MetadataError(f"unsupported explicit PSP destination: {destination_value}")
            if destination_extension != _extension(source):
                raise MetadataError(
                    "explicit input and PSP destination must use the same extension"
                )
            candidates = [(source, destination)]
        elif source.is_dir():
            candidates = [
                (path, validate_runtime_path(f"{destination}/{relative}", "mapped ROM path"))
                for path, relative in _directory_files(source)
            ]
        else:
            raise MetadataError(f"input is not a regular file or directory: {source_value}")

        for path, rom in candidates:
            collision_key = rom.casefold()
            if collision_key in collisions:
                raise MetadataError(
                    f"case-insensitive ROM path collision: {collisions[collision_key]!r} and {rom!r}"
                )
            collisions[collision_key] = rom
            records.append(_record(path, rom))
            if len(records) > MAX_RECORDS:
                raise MetadataError(f"scan exceeds {MAX_RECORDS} records")

    records.sort(key=lambda record: (str(record["rom"]).casefold(), str(record["rom"])))
    return {"version": 1, "games": records}


def json_bytes(document: Dict[str, object]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


def write_scan(document: Dict[str, object], output: Path, force: bool = False) -> None:
    if output.exists() and not force:
        raise MetadataError(f"output already exists (use --force): {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    data = json_bytes(document)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temporary_name, output)
        else:
            os.link(temporary_name, output)
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
