"""SQLite-backed VectorForge ROM library."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from backend.artwork import MAX_ARTWORK_BYTES
from backend.identity import MetadataError, identify_plain, identify_zip
from backend.manifest import INTEGER_RANGES, RUNTIME_LIMITS, yaml_bytes
from backend.overrides import STRING_LIMITS, metadata_ascii
from backend.rom_scan import SUPPORTED_EXTENSIONS, validate_runtime_path


MANIFEST_FIELDS = (
    "title", "system", "release_year", "genre", "information", "players",
    "region", "rating", "publisher", "developer", "provider", "provider_id",
)


@dataclass(frozen=True)
class Game:
    id: str
    rom_path: str
    stored_path: Path
    filename: str
    system: str
    metadata: Dict[str, object]
    artwork_path: Optional[Path]
    status: str

    @property
    def title(self) -> str:
        return str(self.metadata.get("title") or PurePosixPath(self.rom_path).stem)

    @property
    def category(self) -> str:
        return "extra" if self.rom_path.casefold().startswith("rom_extra/") else "main"


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _safe_filename(name: str, extension: str) -> str:
    stem = metadata_ascii(Path(name).stem)
    invalid = '<>:"/\\|?*'
    stem = "".join("_" if character in invalid else character for character in stem)
    stem = stem.strip().rstrip(".") or "game"
    extension = extension.lower().lstrip(".")
    return f"{stem}.{extension}" if extension else stem


def _runtime_name(name: str, extension: str, used: Iterable[str], category: str = "main") -> str:
    root = "rom_extra" if category == "extra" else "rom"
    candidate = _safe_filename(name, extension)
    used_keys = {value.casefold() for value in used}
    stem = Path(candidate).stem
    suffix = Path(candidate).suffix
    index = 2
    while f"{root}/{candidate}".casefold() in used_keys:
        candidate = f"{stem} ({index}){suffix}"
        index += 1
    return validate_runtime_path(f"{root}/{candidate}", "library ROM path")


class LibraryStore:
    """Owns ROM bytes, artwork, metadata, and scrape state."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.roms = root / "roms"
        self.art = root / "art"
        self.database = root / "library.sqlite3"
        root.mkdir(parents=True, exist_ok=True)
        self.roms.mkdir(exist_ok=True)
        self.art.mkdir(exist_ok=True)
        self._initialize()

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connected(self):
        connection = self._connection()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connected() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS games (
                    id TEXT PRIMARY KEY,
                    rom_path TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    stored_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    system TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'raw',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS games_title ON games (json_extract(metadata, '$.title'))"
            )

    def _row(self, row: sqlite3.Row) -> Game:
        metadata = json.loads(str(row["metadata"]))
        stored = Path(str(row["stored_path"]))
        artwork = self.art / f"{row['id'].removeprefix('sha1:')}.png"
        return Game(
            id=str(row["id"]),
            rom_path=str(row["rom_path"]),
            stored_path=stored,
            filename=str(row["filename"]),
            system=str(row["system"]),
            metadata=metadata,
            artwork_path=artwork if artwork.is_file() else None,
            status=str(row["status"]),
        )

    def list_games(self) -> List[Game]:
        with self._connected() as connection:
            rows = connection.execute(
                "SELECT * FROM games ORDER BY rom_path COLLATE NOCASE, rom_path"
            ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, stable_id: str) -> Optional[Game]:
        with self._connected() as connection:
            row = connection.execute("SELECT * FROM games WHERE id = ?", (stable_id,)).fetchone()
        return self._row(row) if row is not None else None

    def _metadata(self, metadata: Optional[Mapping[str, object]], filename: str,
                  system: str, stable_id: str) -> Dict[str, object]:
        result: Dict[str, object] = {
            "title": metadata_ascii(str(metadata.get("title") or Path(filename).stem))
            if metadata else metadata_ascii(Path(filename).stem),
            "system": metadata_ascii(str(metadata.get("system") or system))
            if metadata else metadata_ascii(system),
        }
        if not result["title"]:
            result["title"] = stable_id
        if not result["system"]:
            result["system"] = "Unknown System"
        if metadata:
            for field in MANIFEST_FIELDS:
                value = metadata.get(field)
                if value not in (None, ""):
                    result[field] = value
        return result

    def add_path(
        self,
        source: Path,
        *,
        filename: Optional[str] = None,
        rom_path: Optional[str] = None,
        category: str = "main",
        metadata: Optional[Mapping[str, object]] = None,
        duplicate: str = "skip",
    ) -> Game:
        source = source.expanduser()
        if source.is_symlink() or not source.is_file():
            raise MetadataError(f"ROM input is not a regular file: {source}")
        extension = source.suffix.lower().lstrip(".")
        if extension not in SUPPORTED_EXTENSIONS:
            raise MetadataError(f"unsupported ROM extension: {source.name}")
        identity = identify_zip(source) if extension == "zip" else identify_plain(source, extension)
        stable_id = str(identity["id"])
        original_name = filename or source.name
        existing = self.get(stable_id)
        if existing is not None:
            if duplicate == "error":
                raise MetadataError(f"ROM is already in the library: {source.name}")
            if metadata:
                self.update_metadata(stable_id, metadata)
            return self.get(stable_id) or existing

        used = [game.rom_path for game in self.list_games()]
        if category not in {"main", "extra"}:
            raise MetadataError("ROM category must be main or extra")
        destination = validate_runtime_path(rom_path, "library ROM path") if rom_path else _runtime_name(
            original_name, extension, used, category
        )
        if destination.split("/", 1)[0] not in {"rom", "rom_extra"}:
            raise MetadataError("VectorForge library ROMs must be stored under rom/ or rom_extra/")
        stored = self.roms / f"{stable_id.removeprefix('sha1:')}.{extension}"
        temporary = stored.with_name(f".{stored.name}.tmp")
        shutil.copyfile(source, temporary)
        os.replace(temporary, stored)
        data = self._metadata(metadata, original_name, str(identity["system"]), stable_id)
        status = "scraped" if metadata else "raw"
        with self._connected() as connection:
            try:
                connection.execute(
                    "INSERT INTO games (id, rom_path, stored_path, filename, system, metadata, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (stable_id, destination, str(stored), original_name, str(identity["system"]), _json(data), status),
                )
            except sqlite3.IntegrityError as error:
                stored.unlink(missing_ok=True)
                raise MetadataError(f"library path collision: {destination}") from error
        return self.get(stable_id)  # type: ignore[return-value]

    def add_bytes(
        self,
        data: bytes,
        filename: str,
        *,
        rom_path: Optional[str] = None,
        category: str = "main",
        metadata: Optional[Mapping[str, object]] = None,
        duplicate: str = "skip",
    ) -> Game:
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="vectorforge-rom-", suffix=Path(filename).suffix,
                                         dir=self.root, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        try:
            return self.add_path(
                temporary, filename=filename, rom_path=rom_path,
                category=category,
                metadata=metadata, duplicate=duplicate,
            )
        finally:
            temporary.unlink(missing_ok=True)

    def update_metadata(self, stable_id: str, values: Mapping[str, object]) -> Game:
        game = self.get(stable_id)
        if game is None:
            raise MetadataError(f"unknown library game: {stable_id}")
        metadata = dict(game.metadata)
        for field in MANIFEST_FIELDS:
            if field not in values:
                continue
            value = values[field]
            if value is None or value == "":
                metadata.pop(field, None)
            else:
                if field in INTEGER_RANGES:
                    minimum, maximum = INTEGER_RANGES[field]
                    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                        raise MetadataError(f"{field} must be an integer from {minimum} to {maximum}")
                    metadata[field] = value
                else:
                    if not isinstance(value, str):
                        raise MetadataError(f"{field} must be text")
                    normalized = metadata_ascii(value)
                    if not normalized:
                        raise MetadataError(f"{field} must not be empty")
                    limit = RUNTIME_LIMITS.get(field, STRING_LIMITS.get(field))
                    if limit is None:
                        raise MetadataError(f"unsupported metadata field: {field}")
                    if len(normalized.encode("ascii")) > limit:
                        raise MetadataError(f"{field} exceeds its runtime limit")
                    metadata[field] = normalized
        with self._connected() as connection:
            connection.execute(
                "UPDATE games SET metadata = ?, status = 'edited', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (_json(metadata), stable_id),
            )
        return self.get(stable_id)  # type: ignore[return-value]

    def set_artwork(self, stable_id: str, data: bytes) -> Path:
        if self.get(stable_id) is None:
            raise MetadataError(f"unknown library game: {stable_id}")
        if len(data) > MAX_ARTWORK_BYTES:
            raise MetadataError("artwork exceeds 256 KiB")
        target = self.art / f"{stable_id.removeprefix('sha1:')}.png"
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, target)
        return target

    def manifest_games(self, stable_ids: Optional[Sequence[str]] = None) -> List[Dict[str, object]]:
        wanted = set(stable_ids) if stable_ids is not None else None
        result: List[Dict[str, object]] = []
        for game in self.list_games():
            if wanted is not None and game.id not in wanted:
                continue
            item: Dict[str, object] = {"rom": game.rom_path, "id": game.id}
            for field in MANIFEST_FIELDS:
                if field in game.metadata and game.metadata[field] not in (None, ""):
                    item[field] = game.metadata[field]
            item.setdefault("title", game.title)
            item.setdefault("system", game.system)
            if game.artwork_path is not None:
                item["thumbnail"] = f"metadata/art/sha1-{game.id.removeprefix('sha1:')}.png"
            result.append(item)
        result.sort(key=lambda item: (str(item["rom"]).casefold(), str(item["rom"])))
        return result

    def manifest_bytes(self, stable_ids: Optional[Sequence[str]] = None) -> bytes:
        return yaml_bytes(self.manifest_games(stable_ids))
