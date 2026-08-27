"""Safe VectorDrive package inspection and import."""

from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Tuple
from urllib.parse import unquote, urlparse

from backend.identity import MetadataError
from backend.install import _validate_png_artwork
from backend.rom_scan import SUPPORTED_EXTENSIONS, validate_runtime_path

from .library import Game, LibraryStore


def _normalize_artwork(data: bytes, label: str) -> bytes:
    """Convert valid VectorDrive artwork to the runtime's RGB PNG format."""

    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as error:
        raise MetadataError("Pillow is required to import package artwork") from error
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format != "PNG" or getattr(source, "n_frames", 1) != 1:
                raise MetadataError(f"{label} is not a single-frame PNG")
            source.load()
            if source.mode in {"RGBA", "LA"} or "transparency" in source.info:
                rgba = source.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
                image = Image.alpha_composite(background, rgba).convert("RGB")
            else:
                image = source.convert("RGB")
            output = BytesIO()
            image.save(output, format="PNG", optimize=False, compress_level=9, interlace=0)
            return output.getvalue()
    except MetadataError:
        raise
    except (OSError, ValueError, UnidentifiedImageError) as error:
        raise MetadataError(f"cannot normalize package artwork {label}: {error}") from error


def _unsafe_name(name: str) -> bool:
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return True
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in name):
        return True
    return any(part in {"", ".", ".."} for part in name.split("/"))


def _scalar(value: str, line: int) -> str:
    value = value.strip()
    if not value:
        raise MetadataError(f"games.yaml line {line}: empty value")
    if value[0] == '"':
        if len(value) < 2 or value[-1] != '"':
            raise MetadataError(f"games.yaml line {line}: unterminated string")
        body = value[1:-1]
        result: List[str] = []
        index = 0
        while index < len(body):
            character = body[index]
            if character == "\\":
                index += 1
                if index >= len(body) or body[index] not in '\\"/':
                    raise MetadataError(f"games.yaml line {line}: unsupported escape")
                character = body[index]
            result.append(character)
            index += 1
        return "".join(result)
    if value[0] == "'":
        if len(value) < 2 or value[-1] != "'":
            raise MetadataError(f"games.yaml line {line}: unterminated string")
        return value[1:-1].replace("''", "'")
    return value.split(" #", 1)[0].strip()


def parse_manifest(data: bytes) -> Dict[str, Dict[str, object]]:
    """Parse the deliberately small games.yaml dialect used by VectorDrive."""

    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise MetadataError("games.yaml must contain ASCII only") from error
    games: Dict[str, Dict[str, object]] = {}
    current: Optional[Dict[str, object]] = None
    in_games = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line == "version: 1":
            continue
        if line == "games:":
            in_games = True
            continue
        if not in_games:
            raise MetadataError(f"games.yaml line {number}: invalid content")
        if line.startswith("  - "):
            if current is not None:
                _finish_manifest_game(games, current, number)
            current = {}
            body = line[4:]
        elif line.startswith("    ") and current is not None:
            body = line[4:]
        else:
            raise MetadataError(f"games.yaml line {number}: invalid indentation")
        if ":" not in body:
            raise MetadataError(f"games.yaml line {number}: expected key/value")
        key, value = body.split(":", 1)
        key = key.strip()
        if key in current:
            raise MetadataError(f"games.yaml line {number}: duplicate field {key}")
        parsed = _scalar(value, number)
        if key in {"release_year", "players", "rating"}:
            try:
                parsed_value: object = int(parsed, 10)
            except ValueError as error:
                raise MetadataError(f"games.yaml line {number}: invalid integer") from error
        else:
            parsed_value = parsed
        current[key] = parsed_value
    if current is not None:
        _finish_manifest_game(games, current, len(text.splitlines()) or 1)
    if not in_games:
        raise MetadataError("games.yaml requires a games list")
    return games


def _finish_manifest_game(games: Dict[str, Dict[str, object]], game: Dict[str, object], line: int) -> None:
    rom = game.get("rom")
    if not isinstance(rom, str):
        raise MetadataError(f"games.yaml line {line}: game is missing rom")
    validate_runtime_path(rom, "manifest ROM path")
    key = rom.casefold()
    if key in {value.casefold() for value in games}:
        raise MetadataError(f"games.yaml has a duplicate ROM path: {rom}")
    games[rom] = dict(game)


@dataclass(frozen=True)
class PackageInfo:
    path: Path
    root: str
    files: int
    roms: int
    manifest: Dict[str, Dict[str, object]]


class PackageReader:
    """Validates and imports a VectorDrive distribution ZIP."""

    def __init__(self, path: Path) -> None:
        raw_path = str(path)
        if raw_path.startswith("file://"):
            raw_path = unquote(urlparse(raw_path).path)
        self.path = Path(raw_path).expanduser().resolve(strict=False)
        self._names: List[str] = []
        self._root: Optional[str] = None
        self._manifest: Optional[Dict[str, Dict[str, object]]] = None
        self._inspect()

    @property
    def root(self) -> str:
        assert self._root is not None
        return self._root

    @property
    def manifest(self) -> Dict[str, Dict[str, object]]:
        return dict(self._manifest or {})

    def _inspect(self) -> None:
        try:
            details = self.path.stat()
        except OSError as error:
            raise MetadataError(f"cannot access VectorDrive package {self.path}: {error}") from error
        if self.path.is_symlink() or not stat.S_ISREG(details.st_mode):
            raise MetadataError(f"VectorDrive package is not a regular file: {self.path}")
        try:
            with zipfile.ZipFile(self.path, "r") as archive:
                infos = archive.infolist()
                if not infos:
                    raise MetadataError("VectorDrive package is empty")
                roots = set()
                folded = set()
                for info in infos:
                    name = info.filename.rstrip("/")
                    if not name:
                        continue
                    if _unsafe_name(name):
                        raise MetadataError(f"unsafe package path: {info.filename}")
                    key = name.casefold()
                    if key in folded:
                        raise MetadataError(f"duplicate package path: {name}")
                    folded.add(key)
                    roots.add(name.split("/", 1)[0])
                    mode = (info.external_attr >> 16) & 0xFFFF
                    if not info.is_dir() and stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                        raise MetadataError(f"package contains a non-regular file: {name}")
                    if not info.is_dir():
                        self._names.append(name)
                if len(roots) != 1:
                    raise MetadataError("package must contain exactly one top-level directory")
                self._root = next(iter(roots))
                eboot = f"{self.root}/EBOOT.PBP"
                if eboot not in self._names:
                    raise MetadataError("package does not contain EBOOT.PBP")
                manifest_name = f"{self.root}/games.yaml"
                if manifest_name in self._names:
                    self._manifest = parse_manifest(archive.read(manifest_name))
                else:
                    self._manifest = {}
                corrupt = archive.testzip()
                if corrupt is not None:
                    raise MetadataError(f"package CRC validation failed: {corrupt}")
        except MetadataError:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile) as error:
            raise MetadataError(f"invalid VectorDrive package: {error}") from error

    def info(self) -> PackageInfo:
        roms = sum(1 for name in self._names if self._is_rom(name))
        return PackageInfo(self.path, self.root, len(self._names), roms, self.manifest)

    def _relative(self, name: str) -> str:
        return name[len(self.root) + 1:]

    def _is_rom(self, name: str) -> bool:
        relative = self._relative(name)
        if not (relative.startswith("rom/") or relative.startswith("rom_extra/")):
            return False
        return PurePosixPath(relative).suffix.lower().lstrip(".") in SUPPORTED_EXTENSIONS

    def read(self, name: str) -> bytes:
        try:
            with zipfile.ZipFile(self.path, "r") as archive:
                return archive.read(name)
        except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as error:
            raise MetadataError(f"cannot read package member {name}: {error}") from error

    def import_into(self, library: LibraryStore) -> Tuple[PackageInfo, List[Game]]:
        imported: List[Game] = []
        with zipfile.ZipFile(self.path, "r") as archive:
            for name in self._names:
                if not self._is_rom(name):
                    continue
                relative = self._relative(name)
                filename = PurePosixPath(relative).name
                extension = PurePosixPath(filename).suffix.lower().lstrip(".")
                metadata = self._manifest.get(relative)
                game = library.add_bytes(
                    archive.read(name), filename, rom_path=relative, metadata=metadata,
                )
                imported.append(game)
                if metadata and isinstance(metadata.get("thumbnail"), str):
                    thumbnail = str(metadata["thumbnail"])
                    if thumbnail.startswith("metadata/art/"):
                        artwork_name = f"{self.root}/{thumbnail}"
                        if artwork_name in self._names:
                            artwork = _normalize_artwork(archive.read(artwork_name), f"package artwork {thumbnail}")
                            _validate_png_artwork(artwork, f"package artwork {thumbnail}")
                            library.set_artwork(game.id, artwork)
        return self.info(), imported
