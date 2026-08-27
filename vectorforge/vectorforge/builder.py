"""Deterministic VectorDrive ZIP building from a library and base package."""

from __future__ import annotations

import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from backend.identity import MetadataError

from .library import Game, LibraryStore
from .package import PackageReader


ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class BuildResult:
    output: Path
    files: int
    roms: int
    artwork: int


def _info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _generated(relative: str) -> bool:
    return (
        relative in {"games.yaml", "games-smduc.yaml"}
        or relative.startswith("rom/")
        or relative.startswith("rom_extra/")
        or relative.startswith("metadata/art/")
        or relative in {"metadata/attribution.json", "metadata/attribution-smduc.json"}
    )


def _attribution(games: Sequence[Game]) -> Optional[bytes]:
    records: List[Dict[str, object]] = []
    for game in games:
        provider = game.metadata.get("provider")
        provider_id = game.metadata.get("provider_id")
        if provider not in {"screenscraper", "thegamesdb"} or not provider_id:
            continue
        source = (
            "https://www.screenscraper.fr/gameinfos.php?gameid="
            if provider == "screenscraper" else "https://thegamesdb.net/game.php?id="
        ) + quote(str(provider_id), safe="")
        records.append({
            "rom": game.rom_path,
            "provider": provider,
            "provider_id": str(provider_id),
            "source_page": source,
        })
    if not records:
        return None
    records.sort(key=lambda item: (str(item["rom"]).casefold(), str(item["rom"]), str(item["provider"])))
    import json
    return (json.dumps({"version": 1, "games": records}, indent=2, sort_keys=True,
                       ensure_ascii=True) + "\n").encode("ascii")


def build_zip(
    base_zip: Path,
    output: Path,
    library: LibraryStore,
    stable_ids: Optional[Sequence[str]] = None,
    force: bool = False,
) -> BuildResult:
    """Build a package while preserving all non-generated base assets."""

    reader = PackageReader(base_zip)
    output = output.expanduser()
    if output.resolve(strict=False) == base_zip.resolve(strict=False):
        raise MetadataError("output must not replace the base package")
    if output.exists() and not force:
        raise MetadataError(f"output already exists (use force to replace): {output}")
    if output.exists() and not output.is_file():
        raise MetadataError(f"output is not a regular file: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    games = [game for game in library.list_games() if stable_ids is None or game.id in set(stable_ids)]
    base_entries: Dict[str, bytes] = {}
    with zipfile.ZipFile(base_zip, "r") as archive:
        for name in reader._names:
            relative = reader._relative(name)
            if not _generated(relative):
                base_entries[name] = archive.read(name)

    generated: Dict[str, bytes] = {
        f"{reader.root}/games.yaml": library.manifest_bytes([game.id for game in games]),
    }
    attribution = _attribution(games)
    if attribution is not None:
        generated[f"{reader.root}/metadata/attribution.json"] = attribution
    artwork_count = 0
    for game in games:
        if game.artwork_path is not None:
            name = f"{reader.root}/metadata/art/sha1-{game.id.removeprefix('sha1:')}.png"
            generated[name] = game.artwork_path.read_bytes()
            artwork_count += 1

    entries: List[Tuple[str, Optional[bytes], Optional[Path]]] = []
    entries.extend((name, data, None) for name, data in base_entries.items())
    entries.extend((name, data, None) for name, data in generated.items())
    for game in games:
        if game.stored_path.is_symlink() or not game.stored_path.is_file():
            raise MetadataError(f"library ROM is unavailable: {game.stored_path}")
        entries.append((f"{reader.root}/{game.rom_path}", None, game.stored_path))
    entries.sort(key=lambda item: item[0])
    names = [item[0] for item in entries]
    if len(names) != len({name.casefold() for name in names}):
        raise MetadataError("generated package contains a case-insensitive path collision")

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for name, data, source in entries:
                info = _info(name)
                if data is not None:
                    archive.writestr(info, data)
                else:
                    assert source is not None
                    with source.open("rb") as stream, archive.open(info, "w") as target:
                        while True:
                            block = stream.read(1024 * 1024)
                            if not block:
                                break
                            target.write(block)
        with zipfile.ZipFile(temporary, "r") as archive:
            if archive.testzip() is not None:
                raise MetadataError("generated package failed CRC validation")
            actual = archive.namelist()
            if actual != names:
                raise MetadataError("generated package ordering validation failed")
        if force:
            os.replace(temporary, output)
        else:
            try:
                os.link(temporary, output)
                temporary.unlink()
            except FileExistsError as error:
                raise MetadataError(f"output already exists (use force to replace): {output}") from error
        return BuildResult(output, len(entries), len(games), artwork_count)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
