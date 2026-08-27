"""Validated, deterministic PSP install archive construction."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import struct
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import quote

from .artwork import ARTWORK_SIZE, MAX_ARTWORK_BYTES
from .identity import (
    MAX_CARTRIDGE_SIZE,
    MAX_ZIP_CONTAINER_SIZE,
    MetadataError,
    identify_plain,
    identify_zip,
)
from .manifest import INTEGER_RANGES, MAX_LINE_BYTES, MAX_MANIFEST_BYTES, RUNTIME_LIMITS
from .rom_scan import MAX_RECORDS, SUPPORTED_EXTENSIONS, validate_runtime_path

THEMES = ("sugc", "smduc", "vectordrive")
SHARED_SKIN_FILES = ("retro_dreams.mp3", "selector.png", "skin.txt")
THEME_BACKGROUNDS = ("background.png", "background_selector.png", "background_title.png")
MAX_ARCHIVE_FILES = 2048
MAX_ARCHIVE_PATH_BYTES = 255
MAX_ARCHIVE_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
MAX_ATTRIBUTION_BYTES = 8 * 1024 * 1024
MAX_ATTRIBUTION_RECORDS = MAX_RECORDS
MAX_ATTRIBUTION_STRING = 255
MAX_DISC_SIZE = MAX_ARCHIVE_UNCOMPRESSED
MAX_ZIP_EXPANDED_SIZE = 256 * 1024 * 1024
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_after_rom_preflight = None  # type: Optional[object]


@dataclass(frozen=True)
class InstallResult:
    output: Path
    files: int
    roms: int
    artwork: int


@dataclass(frozen=True)
class _Entry:
    name: str
    data: Optional[bytes] = None
    source: Optional[Path] = None
    size: int = 0


def _regular_signature(path: Path, label: str) -> Tuple[int, int, int, int]:
    try:
        details = path.lstat()
    except OSError as error:
        raise MetadataError(f"cannot inspect {label} {path}: {error}") from error
    if not stat.S_ISREG(details.st_mode):
        raise MetadataError(f"{label} is not a regular file: {path}")
    return (details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns)


def _read_regular(path: Path, limit: int, label: str, nonempty: bool = False) -> bytes:
    expected = _regular_signature(path, label)
    if expected[2] > limit:
        raise MetadataError(f"{label} exceeds {limit} bytes: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            current = os.fstat(stream.fileno())
            signature = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            if not stat.S_ISREG(current.st_mode) or signature != expected:
                raise MetadataError(f"{label} changed while being read: {path}")
            data = stream.read(limit + 1)
    except MetadataError:
        raise
    except OSError as error:
        raise MetadataError(f"cannot read {label} {path}: {error}") from error
    if len(data) > limit:
        raise MetadataError(f"{label} exceeds {limit} bytes: {path}")
    if len(data) != expected[2]:
        raise MetadataError(f"{label} changed while being read: {path}")
    if nonempty and not data:
        raise MetadataError(f"{label} is empty: {path}")
    return data


def _parse_scalar(value: str, line: int) -> str:
    if not value:
        raise MetadataError(f"games.yaml line {line}: empty scalar")
    quote = value[0] if value[0] in "\"'" else ""
    index = 1 if quote else 0
    output: List[str] = []
    while index < len(value):
        character = value[index]
        index += 1
        if quote and character == quote:
            if quote == "'" and index < len(value) and value[index] == "'":
                output.append("'")
                index += 1
                continue
            if index != len(value):
                raise MetadataError(f"games.yaml line {line}: text after quoted scalar")
            quote = ""
            break
        if character == "\\" and quote == '"':
            if index >= len(value) or value[index] not in '\\"/':
                raise MetadataError(f"games.yaml line {line}: unsupported escape")
            character = value[index]
            index += 1
        elif not quote and character in "[]{}&*!|>`":
            raise MetadataError(f"games.yaml line {line}: unsupported scalar syntax")
        elif not quote and character == ":" and index < len(value) and value[index] == " ":
            raise MetadataError(f"games.yaml line {line}: unsupported scalar syntax")
        output.append(character)
    if quote:
        raise MetadataError(f"games.yaml line {line}: unterminated quote")
    result = "".join(output)
    if not result:
        raise MetadataError(f"games.yaml line {line}: empty scalar")
    return result


def _strip_comment(value: str, line: int) -> str:
    colon = value.find(":")
    scalar = colon + 1
    while scalar < len(value) and value[scalar] == " ":
        scalar += 1
    quote = value[scalar] if scalar < len(value) and value[scalar] in "\"'" else ""
    if not quote:
        marker = value.find("#")
        return value[:marker].rstrip(" ") if marker >= 0 else value.rstrip(" ")
    escaped = False
    index = scalar + 1
    while index < len(value):
        character = value[index]
        code = ord(character)
        if code < 0x20 or code > 0x7E:
            raise MetadataError(f"games.yaml line {line}: non-printable ASCII character")
        if quote == '"' and character == "\\" and not escaped:
            escaped = True
            index += 1
            continue
        if character == quote and not escaped:
            if quote == "'" and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            remainder = value[index + 1:]
            marker = remainder.find("#")
            if marker >= 0:
                return value[:index + 1 + marker].rstrip(" ")
            return value.rstrip(" ")
        escaped = False
        index += 1
    if quote:
        raise MetadataError(f"games.yaml line {line}: unterminated quote")
    return value.rstrip(" ")


def _key_value(text: str, line: int) -> Tuple[str, str]:
    if ":" not in text:
        raise MetadataError(f"games.yaml line {line}: expected key/value")
    key, value = text.split(":", 1)
    key = key.rstrip(" ")
    value = value.lstrip(" ").rstrip(" ")
    if not key or any(not (character.islower() or character.isdigit() or character == "_")
                      for character in key):
        raise MetadataError(f"games.yaml line {line}: invalid key")
    return key, value


def _manifest_fields(data: bytes) -> Tuple[Set[str], Set[str]]:
    """Return (thumbnail paths, ROM paths) from a games.yaml manifest."""
    if not data or len(data) > MAX_MANIFEST_BYTES:
        raise MetadataError("games.yaml is empty or exceeds the 256 KiB runtime limit")
    try:
        text = data.decode("ascii", errors="strict")
    except UnicodeError as error:
        raise MetadataError("games.yaml must contain ASCII only") from error
    if any(ord(character) < 0x20 and character not in "\r\n" for character in text):
        raise MetadataError("games.yaml contains a non-printable ASCII character")

    version_seen = False
    games_seen = False
    in_games = False
    current: Optional[Dict[str, str]] = None
    unknown: Set[str] = set()
    roms: Set[str] = set()
    thumbnails: Set[str] = set()
    entries = 0

    def finish_entry(line: int) -> None:
        nonlocal current, entries, unknown
        if current is None:
            return
        if "rom" not in current:
            raise MetadataError(f"games.yaml line {line}: game is missing rom")
        rom = validate_runtime_path(current["rom"], "metadata ROM path")
        if rom.casefold() in roms:
            raise MetadataError(f"games.yaml has a case-insensitive ROM collision: {rom}")
        roms.add(rom.casefold())
        thumbnail = current.get("thumbnail")
        if thumbnail is not None:
            validate_runtime_path(thumbnail, "metadata thumbnail path")
            if (not thumbnail.startswith("metadata/art/") or
                    not thumbnail.lower().endswith(".png")):
                raise MetadataError(f"metadata thumbnail must be metadata/art/*.png: {thumbnail}")
            thumbnails.add(thumbnail)
        entries += 1
        if entries > MAX_RECORDS:
            raise MetadataError(f"games.yaml exceeds {MAX_RECORDS} entries")
        current = None
        unknown = set()

    lines = text.splitlines()
    for number, raw_line in enumerate(lines, 1):
        if len(raw_line.encode("ascii")) > MAX_LINE_BYTES:
            raise MetadataError(f"games.yaml line {number} exceeds {MAX_LINE_BYTES} bytes")
        line = _strip_comment(raw_line, number)
        if not line:
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = line[indent:]
        if indent == 0:
            if in_games:
                finish_entry(number)
                in_games = False
            key, value = _key_value(body, number)
            if key == "version":
                if version_seen or value != "1":
                    raise MetadataError(f"games.yaml line {number}: invalid or duplicate version")
                version_seen = True
            elif key == "games":
                if games_seen or value:
                    raise MetadataError(f"games.yaml line {number}: games must introduce a list")
                games_seen = True
                in_games = True
            else:
                raise MetadataError(f"games.yaml line {number}: unknown top-level key")
            continue
        if not in_games:
            raise MetadataError(f"games.yaml line {number}: invalid games list indentation")
        if indent == 2 and body.startswith("- "):
            finish_entry(number)
            current = {}
            body = body[2:].lstrip(" ")
        elif indent != 4 or current is None:
            raise MetadataError(f"games.yaml line {number}: invalid games list indentation")
        key, value = _key_value(body, number)
        if not value:
            raise MetadataError(f"games.yaml line {number}: empty game field")
        if key in current or key in unknown:
            raise MetadataError(f"games.yaml line {number}: duplicate game field {key}")
        parsed = _parse_scalar(value, number)
        if key in INTEGER_RANGES:
            minimum, maximum = INTEGER_RANGES[key]
            try:
                integer = int(parsed, 10)
            except ValueError as error:
                raise MetadataError(f"games.yaml line {number}: invalid {key}") from error
            if str(integer) != parsed or not minimum <= integer <= maximum:
                raise MetadataError(f"games.yaml line {number}: invalid {key}")
        elif key in RUNTIME_LIMITS:
            if len(parsed) > RUNTIME_LIMITS[key]:
                raise MetadataError(f"games.yaml line {number}: value for {key} is too long")
        else:
            if len(key) >= 32 or len(unknown) >= 16:
                raise MetadataError(f"games.yaml line {number}: too many or oversized unknown fields")
            unknown.add(key)
        current[key] = parsed
    if in_games:
        finish_entry(len(lines) or 1)
    if not version_seen or not games_seen:
        raise MetadataError("games.yaml requires version and games")
    return thumbnails, roms


def _validate_png_artwork(data: bytes, label: str) -> None:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as error:
        raise MetadataError("Pillow is required to validate package artwork") from error
    if len(data) < 29 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise MetadataError(f"{label} is not a PNG file")
    if data[28] != 0:
        raise MetadataError(f"{label} must be non-interlaced")
    if not data.endswith(b"IEND\xAEB`\x82"):
        raise MetadataError(f"{label} is not a valid PNG: cannot decode")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG":
                raise MetadataError(f"{label} is not a PNG file")
            if getattr(image, "n_frames", 1) != 1:
                raise MetadataError(f"{label} is animated or multiframe")
            if image.size != ARTWORK_SIZE:
                raise MetadataError(f"{label} must be {ARTWORK_SIZE[0]}x{ARTWORK_SIZE[1]}")
            if image.mode != "RGB":
                raise MetadataError(f"{label} must be RGB8 mode")
            image.load()
    except MetadataError:
        raise
    except UnidentifiedImageError:
        raise MetadataError(f"{label} is not a PNG file")
    except (OSError, ValueError) as error:
        raise MetadataError(f"{label} is not a decodable PNG: {error}") from error


def _validate_attribution(data: bytes, manifest_roms: Set[str]) -> None:
    def unique_object(pairs: Sequence[Tuple[str, object]]) -> Dict[str, object]:
        result: Dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise MetadataError(f"duplicate JSON key in attribution: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise MetadataError(f"nonstandard JSON value in attribution: {value}")

    try:
        text = data.decode("utf-8", errors="strict")
        document = json.loads(text, object_pairs_hook=unique_object,
                              parse_constant=reject_constant)
    except MetadataError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise MetadataError(f"invalid attribution JSON: {error}") from error
    if not isinstance(document, dict):
        raise MetadataError("attribution must be a JSON object")
    if set(document) != {"version", "games"}:
        raise MetadataError("attribution must contain only version and games")
    if type(document["version"]) is not int or document["version"] != 1:
        raise MetadataError("attribution version must be 1")
    games = document.get("games")
    if not isinstance(games, list):
        raise MetadataError("attribution games must be a list")
    if not games:
        raise MetadataError("attribution games must be non-empty")
    if len(games) > MAX_ATTRIBUTION_RECORDS:
        raise MetadataError(f"attribution exceeds {MAX_ATTRIBUTION_RECORDS} records")
    seen: Set[Tuple[str, str]] = set()
    for record in games:
        if not isinstance(record, dict):
            raise MetadataError("attribution record must be an object")
        required = {"rom", "provider", "provider_id", "source_page"}
        if not required <= set(record) or set(record) - required - {"artwork"}:
            raise MetadataError("attribution record has unknown or missing fields")
        provider = record.get("provider")
        if provider not in ("screenscraper", "thegamesdb"):
            raise MetadataError(f"unsupported provider in attribution: {provider!r}")
        provider_id = record.get("provider_id")
        if not isinstance(provider_id, str) or not provider_id:
            raise MetadataError("attribution record has invalid provider_id")
        try:
            provider_id_bytes = provider_id.encode("ascii")
        except UnicodeEncodeError as error:
            raise MetadataError("attribution provider_id must be ASCII") from error
        if (len(provider_id_bytes) > MAX_ATTRIBUTION_STRING or
                any(byte < 0x20 or byte > 0x7E for byte in provider_id_bytes)):
            raise MetadataError("attribution provider_id exceeds limit")
        rom = record.get("rom")
        if not isinstance(rom, str) or not rom:
            raise MetadataError("attribution record has invalid rom")
        try:
            validate_runtime_path(rom, "attribution rom")
        except MetadataError:
            raise
        if rom.casefold() not in manifest_roms:
            raise MetadataError(f"attribution rom absent from games.yaml: {rom}")
        source_page = record.get("source_page")
        expected_page = (
            "https://www.screenscraper.fr/gameinfos.php?gameid="
            if provider == "screenscraper" else
            "https://thegamesdb.net/game.php?id="
        ) + quote(provider_id, safe="")
        if source_page != expected_page:
            raise MetadataError("attribution record has mismatched source URL")
        try:
            source_page_bytes = source_page.encode("ascii")
        except (AttributeError, UnicodeEncodeError) as error:
            raise MetadataError("attribution source_page must be ASCII") from error
        if len(source_page_bytes) > MAX_ATTRIBUTION_STRING:
            raise MetadataError("attribution source_page exceeds limit")
        key = (rom.casefold(), provider)
        if key in seen:
            raise MetadataError(f"duplicate attribution for {rom} ({provider})")
        seen.add(key)
        artwork = record.get("artwork")
        if artwork is not None:
            if not isinstance(artwork, dict):
                raise MetadataError("attribution artwork must be an object")
            if set(artwork) != {"type", "region"}:
                raise MetadataError("attribution artwork has unknown or missing fields")
            for field in ("type", "region"):
                value = artwork.get(field)
                if not isinstance(value, str):
                    raise MetadataError(f"attribution artwork {field} is invalid")
                try:
                    encoded = value.encode("ascii")
                except UnicodeEncodeError as error:
                    raise MetadataError(
                        f"attribution artwork {field} must be ASCII"
                    ) from error
                if (len(encoded) > MAX_ATTRIBUTION_STRING or
                        any(byte < 0x20 or byte > 0x7E for byte in encoded)):
                    raise MetadataError(f"attribution artwork {field} is invalid")


def _validate_archive_name(name: str) -> None:
    validate_runtime_path(name, "archive path")
    if len(name.encode("ascii")) > MAX_ARCHIVE_PATH_BYTES:
        raise MetadataError(f"archive path exceeds {MAX_ARCHIVE_PATH_BYTES} bytes: {name}")


def _resolve_output(output: Path) -> Path:
    try:
        return output.resolve(strict=False)
    except OSError:
        return output


def _resolve_components(path: Path) -> Optional[Path]:
    """Return the resolved path or None if any component is a symlink."""
    try:
        parts = path.resolve(strict=False).parts
    except OSError:
        return None
    if path.is_symlink():
        return None
    current = Path(path.anchor)
    for part in parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                return None
        except OSError:
            return None
    return path.resolve(strict=False)


def _has_symlink_component(path: Path) -> bool:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                return True
        except FileNotFoundError:
            break
        except OSError:
            return True
    return False


def _reject_output_overlap(output: Path, eboot: Path, source_root: Path,
                           metadata_dir: Path, rom_sources: Sequence[Path]) -> None:
    resolved_output = _resolve_output(output)
    resolved_eboot = _resolve_output(eboot)
    if resolved_output == resolved_eboot:
        raise MetadataError(f"output must not be the same path as the EBOOT.PBP input: {output}")
    resolved_root = _resolve_output(source_root)
    resolved_metadata = _resolve_output(metadata_dir)
    for candidate in (resolved_eboot, resolved_root, resolved_metadata):
        if resolved_output == candidate:
            raise MetadataError(f"output must not be the same path as an input: {output}")
    for source in rom_sources:
        resolved_source = _resolve_output(source)
        if resolved_output == resolved_source:
            raise MetadataError(f"output must not be the same path as a ROM input: {output}")
        try:
            resolved_output.relative_to(resolved_source)
            raise MetadataError(
                f"output must not be inside a mapped ROM source directory: {output}"
            )
        except ValueError:
            pass


def _rom_limit(extension: str) -> int:
    if extension in ("iso", "cso", "cue", "chd"):
        return MAX_DISC_SIZE
    return MAX_CARTRIDGE_SIZE


def _stage_rom(source: Path, destination: str, staging: Path,
               expected_sig: Optional[Tuple[int, int, int, int]] = None) -> Tuple[Path, int]:
    """Copy a ROM into a private staging directory, then validate the staged copy."""
    extension = source.suffix.lower().lstrip(".")
    limit = _rom_limit(extension)
    if expected_sig is None:
        expected_sig = _regular_signature(source, "ROM input")
    if expected_sig[2] > limit:
        if limit == MAX_CARTRIDGE_SIZE:
            raise MetadataError(f"ROM input exceeds 64 MiB limit: {source}")
        raise MetadataError(f"ROM input exceeds {limit} bytes: {source}")
    staged = staging / "roms" / destination
    staged.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
        with os.fdopen(descriptor, "rb") as source_stream:
            details = os.fstat(source_stream.fileno())
            signature = (details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns)
            if not stat.S_ISREG(details.st_mode) or signature != expected_sig:
                raise MetadataError(f"ROM input changed before staging: {source}")
            with staged.open("wb") as target:
                copied = 0
                while True:
                    block = source_stream.read(1024 * 1024)
                    if not block:
                        break
                    copied += len(block)
                    if copied > limit:
                        raise MetadataError(f"ROM input grew while staging: {source}")
                    target.write(block)
                if copied != expected_sig[2]:
                    raise MetadataError(f"ROM input changed before staging: {source}")
    except MetadataError:
        raise
    except OSError as error:
        raise MetadataError(f"cannot stage ROM input {source}: {error}") from error
    staged_signature = _regular_signature(staged, "staged ROM")
    if staged_signature[2] != expected_sig[2]:
        raise MetadataError(f"staged ROM size mismatch: {source}")
    if extension == "zip":
        _validate_source_zip(staged)
        identify_zip(staged)
    else:
        identify_plain(staged, extension)
    return staged, staged_signature[2]


def _rom_candidates(mappings: Sequence[Tuple[str, str]], staging: Path) -> List[Tuple[Path, str]]:
    candidates: List[Tuple[Path, str]] = []
    rom_sources: List[Path] = []
    for source_value, destination_value in mappings:
        source = Path(source_value)
        if _has_symlink_component(source):
            raise MetadataError(f"ROM input has a symlink component: {source}")
        rom_sources.append(source)
        destination = validate_runtime_path(destination_value, "PSP destination")
        if destination.split("/", 1)[0] not in {"rom", "rom_extra"}:
            raise MetadataError("PSP ROM destination must be rom or rom_extra")
        try:
            source_details = source.lstat()
        except OSError as error:
            raise MetadataError(f"cannot inspect ROM input {source}: {error}") from error
        if stat.S_ISREG(source_details.st_mode):
            extension = source.suffix.lower().lstrip(".")
            destination_extension = PurePosixPath(destination).suffix.lower().lstrip(".")
            if extension not in SUPPORTED_EXTENSIONS:
                raise MetadataError(f"unsupported explicit input: {source}")
            if destination_extension not in SUPPORTED_EXTENSIONS:
                raise MetadataError(f"unsupported explicit PSP destination: {destination}")
            if extension != destination_extension:
                raise MetadataError("explicit input and PSP destination must use the same extension")
            candidates.append((source, destination))
            continue
        if not stat.S_ISDIR(source_details.st_mode):
            raise MetadataError(f"ROM input is not a regular file or directory: {source}")
        try:
            def walk_error(error: OSError) -> None:
                raise MetadataError(f"cannot scan ROM input {source}: {error}") from error

            for root, directories, files in os.walk(source, followlinks=False,
                                                     onerror=walk_error):
                directories.sort()
                files.sort()
                for name in [*directories, *files]:
                    child = Path(root) / name
                    details = child.lstat()
                    if name in directories and stat.S_ISDIR(details.st_mode):
                        relative = child.relative_to(source).as_posix()
                        validate_runtime_path(f"{destination}/{relative}", "mapped ROM directory")
                        continue
                    if name in files and stat.S_ISREG(details.st_mode):
                        extension = child.suffix.lower().lstrip(".")
                        if extension not in SUPPORTED_EXTENSIONS:
                            raise MetadataError(f"unsupported file in ROM input: {child}")
                        relative = child.relative_to(source).as_posix()
                        mapped = validate_runtime_path(f"{destination}/{relative}", "mapped ROM path")
                        candidates.append((child, mapped))
                        continue
                    raise MetadataError(f"symlink or irregular file in ROM input: {child}")
        except MetadataError:
            raise
        except OSError as error:
            raise MetadataError(f"cannot scan ROM input {source}: {error}") from error

    if len(candidates) > MAX_RECORDS:
        raise MetadataError(f"install exceeds {MAX_RECORDS} ROM files")
    if not candidates:
        raise MetadataError("with-ROM inputs contain no supported ROM files")
    collisions: Dict[str, str] = {}
    staged: List[Tuple[Path, str]] = []
    total_size = 0
    for path, destination in candidates:
        key = destination.casefold()
        if key in collisions:
            raise MetadataError(
                f"case-insensitive or duplicate ROM destination: {collisions[key]!r} and {destination!r}"
            )
        collisions[key] = destination
        extension = path.suffix.lower().lstrip(".")
        limit = _rom_limit(extension)
        expected = _regular_signature(path, "ROM input")
        if expected[2] > limit:
            if limit == MAX_CARTRIDGE_SIZE:
                raise MetadataError(f"ROM input exceeds 64 MiB limit: {path}")
            raise MetadataError(f"ROM input exceeds {limit} bytes: {path}")
        total_size += expected[2]
        if total_size > MAX_ARCHIVE_UNCOMPRESSED:
            raise MetadataError("cumulative ROM size exceeds package uncompressed-size limit")
        if _after_rom_preflight is not None:
            _after_rom_preflight(candidates)
        staged_path, size = _stage_rom(path, destination, staging, expected)
        staged.append((staged_path, destination))
    return sorted(staged, key=lambda item: (item[1].casefold(), item[1]))


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.flag_bits = 0
    return info


def _write_data(archive: zipfile.ZipFile, info: zipfile.ZipInfo, data: bytes) -> None:
    archive.writestr(info, data, compress_type=zipfile.ZIP_STORED)


def _write_source(archive: zipfile.ZipFile, info: zipfile.ZipInfo, entry: _Entry) -> None:
    assert entry.source is not None
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(entry.source, flags)
        with os.fdopen(descriptor, "rb") as source, archive.open(info, "w") as target:
            details = os.fstat(source.fileno())
            if not stat.S_ISREG(details.st_mode) or details.st_size != entry.size:
                raise MetadataError(f"staged ROM changed while packaging: {entry.source}")
            copied = 0
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                copied += len(block)
                target.write(block)
            if copied != entry.size:
                raise MetadataError(f"staged ROM changed while packaging: {entry.source}")
    except MetadataError:
        raise
    except OSError as error:
        raise MetadataError(f"cannot package ROM input {entry.source}: {error}") from error


def _validate_zip(path: Path, expected_names: Sequence[str], backgrounds: Dict[str, bytes]) -> None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if names != list(expected_names) or len(names) != len(set(names)):
                raise MetadataError("install ZIP has missing, duplicate, or unsorted entries")
            top_levels = {name.split("/", 1)[0] for name in names}
            if len(top_levels) != 1:
                raise MetadataError("install ZIP must contain exactly one top-level directory")
            for info in infos:
                mode = info.external_attr >> 16
                if info.is_dir() or not stat.S_ISREG(mode):
                    raise MetadataError(f"install ZIP contains a non-regular entry: {info.filename}")
                if info.date_time != ZIP_TIMESTAMP or mode & 0o777 != 0o644:
                    raise MetadataError(f"install ZIP entry is not normalized: {info.filename}")
                if info.compress_type != zipfile.ZIP_STORED:
                    raise MetadataError(f"install ZIP entry is not stored: {info.filename}")
            corrupt = archive.testzip()
            if corrupt is not None:
                raise MetadataError(f"install ZIP CRC validation failed: {corrupt}")
            for name, source_data in backgrounds.items():
                if archive.read(name) != source_data:
                    raise MetadataError(f"theme background does not match its source: {name}")
    except MetadataError:
        raise
    except (OSError, zipfile.BadZipFile) as error:
        raise MetadataError(f"install ZIP integrity validation failed: {error}") from error


def _validate_selector(data: bytes) -> None:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as error:
        raise MetadataError("Pillow is required to validate package artwork") from error
    from io import BytesIO
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG":
                raise MetadataError("selector is not a PNG file")
            if image.size != (8, 10):
                raise MetadataError(f"selector must be 8x10, got {image.size}")
            if image.mode not in {"1", "L", "P"}:
                raise MetadataError(f"selector must be single-channel, got {image.mode}")
            image.load()
    except MetadataError:
        raise
    except (OSError, ValueError, UnidentifiedImageError) as error:
        raise MetadataError(f"selector is not a decodable PNG: {error}") from error


def _validate_source_zip(path: Path) -> None:
    import zipfile as _zipfile
    try:
        with _zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > 4096:
                raise MetadataError(f"ZIP has too many entries: {path.name}")
            names: List[str] = []
            folded: Dict[str, str] = {}
            total_expanded = 0
            for info in infos:
                mode = (info.external_attr >> 16) & 0xFFFF
                kind = stat.S_IFMT(mode)
                if info.is_dir() or kind == stat.S_IFDIR:
                    if _unsafe_member_name(info.filename):
                        raise MetadataError(f"ZIP has a traversing directory entry: {info.filename}")
                    continue
                if kind not in (0, stat.S_IFREG):
                    raise MetadataError(f"ZIP has a non-regular member: {info.filename}")
                if _unsafe_member_name(info.filename):
                    raise MetadataError(f"ZIP has a traversing member: {info.filename}")
                key = info.filename.casefold()
                if key in folded:
                    raise MetadataError(
                        f"ZIP has a case-colliding member: {folded[key]} and {info.filename}"
                    )
                folded[key] = info.filename
                names.append(info.filename)
                if info.flag_bits & 1:
                    raise MetadataError(f"encrypted ZIP member is unsupported: {info.filename}")
                if info.compress_type not in (_zipfile.ZIP_STORED, _zipfile.ZIP_DEFLATED):
                    raise MetadataError(f"unsupported ZIP compression: {info.filename}")
                if info.file_size > MAX_CARTRIDGE_SIZE:
                    raise MetadataError(f"ZIP member exceeds 64 MiB: {info.filename}")
                total_expanded += info.file_size
                if total_expanded > MAX_ZIP_EXPANDED_SIZE:
                    raise MetadataError(f"ZIP expanded contents exceed limit: {path.name}")
            corrupt = archive.testzip()
            if corrupt is not None:
                raise MetadataError(f"ZIP CRC validation failed: {corrupt}")
    except MetadataError:
        raise
    except (_zipfile.BadZipFile, RuntimeError, OSError) as error:
        if isinstance(error, MetadataError):
            raise
        raise MetadataError(f"invalid ZIP {path.name}: {error}") from error


def _unsafe_member_name(name: str) -> bool:
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return True
    if any(ord(c) < 0x20 for c in name):
        return True
    return any(part in {"", ".", ".."} for part in name.split("/"))


def _publish(temporary: Path, output: Path, force: bool) -> None:
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    directory = output.parent
    if force:
        os.replace(temporary, output)
    else:
        try:
            os.link(temporary, output)
            temporary.unlink()
        except (FileExistsError, OSError):
            reserved = False
            try:
                descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            except FileExistsError:
                raise MetadataError(f"output already exists (use --force): {output}")
            try:
                os.close(descriptor)
                reserved = True
                os.replace(temporary, output)
            except OSError as error:
                if reserved:
                    try:
                        output.unlink()
                    except FileNotFoundError:
                        pass
                raise MetadataError(f"failed to publish install ZIP: {error}") from error
    try:
        directory_fd = os.open(str(directory), os.O_RDONLY)
        os.fsync(directory_fd)
        os.close(directory_fd)
    except OSError:
        pass


def build_install(
    eboot: Path,
    theme: str,
    output: Path,
    source_root: Optional[Path] = None,
    metadata_dir: Optional[Path] = None,
    with_roms: bool = False,
    inputs: Sequence[Tuple[str, str]] = (),
    force: bool = False,
) -> InstallResult:
    """Build and atomically publish one validated PSP install ZIP."""
    if theme not in THEMES:
        raise MetadataError(f"unsupported theme: {theme}")
    if inputs and not with_roms:
        raise MetadataError("--input requires explicit --with-roms")
    if with_roms and not inputs:
        raise MetadataError("--with-roms requires at least one --input mapping")
    if output.is_symlink() or (output.exists() and not output.is_file()):
        raise MetadataError(f"output is not a regular file: {output}")
    if output.exists() and not force:
        raise MetadataError(f"output already exists (use --force): {output}")
    root = source_root if source_root is not None else Path(__file__).resolve().parents[2]
    metadata_root = metadata_dir if metadata_dir is not None else root
    if root.is_symlink() or not root.is_dir():
        raise MetadataError(f"source root is not a regular directory: {root}")
    if metadata_root.is_symlink() or not metadata_root.is_dir():
        raise MetadataError(f"metadata directory is not a regular directory: {metadata_root}")
    if not output.parent.is_dir():
        raise MetadataError(f"output parent does not exist: {output.parent}")

    rom_sources = [Path(source) for source, _ in inputs] if with_roms else []
    _reject_output_overlap(output, eboot, root, metadata_root, rom_sources)

    app = f"VectorDrive-{theme}"
    entries: List[_Entry] = []
    backgrounds: Dict[str, bytes] = {}

    def add_data(relative: str, data: bytes) -> None:
        name = f"{app}/{relative}"
        _validate_archive_name(name)
        entries.append(_Entry(name=name, data=data))

    add_data("EBOOT.PBP", _read_regular(eboot, MAX_CARTRIDGE_SIZE, "EBOOT.PBP", True))
    add_data("game_def.cfg", _read_regular(root / "platform/game_def.cfg", 1024 * 1024,
                                            "platform/game_def.cfg", True))
    copying = _read_regular(root / "COPYING", 1024 * 1024, "COPYING", True)
    add_data("COPYING", copying)
    for filename in SHARED_SKIN_FILES:
        data = _read_regular(root / "platform/psp/skin" / filename,
                             16 * 1024 * 1024,
                             f"shared skin file {filename}", True)
        if filename == "selector.png":
            _validate_selector(data)
        add_data(f"skin/{filename}", data)
    for filename in THEME_BACKGROUNDS:
        relative = f"skin/{filename}"
        data = _read_regular(root / "platform/psp/themes" / theme / filename,
                             16 * 1024 * 1024, f"theme background {filename}", True)
        add_data(relative, data)
        backgrounds[f"{app}/{relative}"] = data

    manifest_filename = "games-smduc.yaml" if theme == "smduc" else "games.yaml"
    attribution_filename = (
        "metadata/attribution-smduc.json"
        if theme == "smduc" else "metadata/attribution.json"
    )
    manifest_path = metadata_root / manifest_filename
    artwork_count = 0
    manifest_roms: Set[str] = set()
    thumbnails: Set[str] = set()
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest = _read_regular(manifest_path, MAX_MANIFEST_BYTES, "games.yaml", True)
        thumbnails, manifest_roms = _manifest_fields(manifest)
        add_data("games.yaml", manifest)
        for thumbnail in sorted(thumbnails, key=lambda value: (value.casefold(), value)):
            art_path = metadata_root / Path(thumbnail)
            artwork = _read_regular(
                art_path, MAX_ARTWORK_BYTES, f"thumbnail {thumbnail}", True
            )
            _validate_png_artwork(artwork, f"thumbnail {thumbnail}")
            add_data(thumbnail, artwork)
            artwork_count += 1
        attribution_path = metadata_root / attribution_filename
        if attribution_path.exists() or attribution_path.is_symlink():
            attribution = _read_regular(attribution_path, MAX_ATTRIBUTION_BYTES,
                                        "metadata attribution", True)
            _validate_attribution(attribution, manifest_roms)
            add_data("metadata/attribution.json", attribution)

    staging = Path(tempfile.mkdtemp(prefix=".vectordrive-install-", dir=output.parent))
    try:
        rom_candidates = _rom_candidates(inputs, staging) if with_roms else []
        if manifest_roms and with_roms:
            packaged_destinations = {destination.casefold()
                                    for _, destination in rom_candidates}
            for rom in manifest_roms:
                if rom.casefold() not in packaged_destinations:
                    raise MetadataError(
                        f"manifest ROM not included in package: {rom}"
                    )
        for staged_path, destination in rom_candidates:
            name = f"{app}/{destination}"
            _validate_archive_name(name)
            entries.append(_Entry(name=name, source=staged_path,
                                   size=staged_path.stat().st_size))

        entries.sort(key=lambda entry: entry.name)
        names = [entry.name for entry in entries]
        folded: Dict[str, str] = {}
        total_size = 0
        for entry in entries:
            key = entry.name.casefold()
            if key in folded:
                raise MetadataError(
                    f"case-insensitive package path collision: {folded[key]} and {entry.name}"
                )
            folded[key] = entry.name
            total_size += len(entry.data) if entry.data is not None else entry.size
        if len(entries) > MAX_ARCHIVE_FILES or total_size > MAX_ARCHIVE_UNCOMPRESSED:
            raise MetadataError("install exceeds package file-count or uncompressed-size limit")

        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.",
                                                       dir=output.parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED,
                                 allowZip64=False) as archive:
                for entry in entries:
                    info = _zip_info(entry.name)
                    if entry.data is not None:
                        _write_data(archive, info, entry.data)
                    else:
                        _write_source(archive, info, entry)
            _validate_zip(temporary, names, backgrounds)
            _publish(temporary, output, force)
        except MetadataError:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile) as error:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise MetadataError(f"failed to build install ZIP: {error}") from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return InstallResult(output=output, files=len(entries), roms=len(rom_candidates),
                         artwork=artwork_count)
