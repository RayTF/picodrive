"""Runtime-constrained YAML manifest generation."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from .artwork import convert_artwork
from .identity import MetadataError
from .matches import load_matches
from .overrides import (
    ID_PATTERN,
    STRING_LIMITS,
    apply_overrides,
    load_json,
    load_overrides,
    metadata_ascii,
)
from .rom_scan import MAX_RECORDS, validate_runtime_path

MAX_MANIFEST_BYTES = 256 * 1024
MAX_LINE_BYTES = 768
SCAN_REQUIRED_FIELDS = {
    "rom", "id", "system", "identity_basis", "raw", "canonical", "warnings",
}
SCAN_OPTIONAL_FIELDS = {"archive"}
FIELD_ORDER = (
    "rom", "id", "title", "system", "release_year", "genre", "information",
    "thumbnail", "players", "region", "rating", "publisher", "developer",
    "provider", "provider_id",
)
INTEGER_RANGES = {
    "release_year": (1000, 9999),
    "players": (1, 8),
    "rating": (0, 100),
}
RUNTIME_LIMITS = {
    "rom": 255,
    "id": 63,
    **STRING_LIMITS,
    "thumbnail": 127,
    "provider": 31,
    "provider_id": 63,
}


class _RecoveryError(MetadataError):
    pass


def load_scan(path: Path) -> List[Dict[str, object]]:
    document = load_json(path, "scan")
    if not isinstance(document, dict):
        raise MetadataError("scan JSON must be an object")
    if set(document) != {"version", "games"}:
        raise MetadataError("scan JSON must contain only version and games")
    if document["version"] != 1 or isinstance(document["version"], bool):
        raise MetadataError("scan version must be 1")
    if not isinstance(document["games"], list):
        raise MetadataError("scan games must be a list")
    if len(document["games"]) > MAX_RECORDS:
        raise MetadataError(f"scan exceeds {MAX_RECORDS} records")

    games: List[Dict[str, object]] = []
    paths = set()
    for index, item in enumerate(document["games"], 1):
        if not isinstance(item, dict):
            raise MetadataError(f"scan game {index} must be an object")
        missing = SCAN_REQUIRED_FIELDS - set(item)
        unknown = set(item) - SCAN_REQUIRED_FIELDS - SCAN_OPTIONAL_FIELDS
        if missing or unknown:
            raise MetadataError(
                f"scan game {index} has an invalid field set"
            )
        rom = item.get("rom")
        stable_id = item.get("id")
        system = item.get("system")
        if not isinstance(rom, str):
            raise MetadataError(f"scan game {index} is missing rom")
        validate_runtime_path(rom, "scan ROM path")
        if rom.casefold() in paths:
            raise MetadataError(f"scan has a case-insensitive ROM collision: {rom}")
        paths.add(rom.casefold())
        if not isinstance(stable_id, str) or not ID_PATTERN.fullmatch(stable_id):
            raise MetadataError(f"scan game {index} has an invalid stable id")
        if not isinstance(system, str) or not system:
            raise MetadataError(f"scan game {index} has an invalid inferred system")
        if not isinstance(item.get("identity_basis"), str):
            raise MetadataError(f"scan game {index} has an invalid identity basis")
        if not isinstance(item.get("raw"), dict) or not isinstance(item.get("warnings"), list):
            raise MetadataError(f"scan game {index} has invalid identity details")
        games.append(dict(item))
    return games


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _validate_integer(field: str, value: object) -> int:
    minimum, maximum = INTEGER_RANGES[field]
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise MetadataError(f"{field} must be an integer from {minimum} to {maximum}")
    return value


def _prepare_games(
    games: Sequence[Dict[str, object]], overrides_path: Optional[Path],
    providers: Optional[Sequence[str]] = None, provider_cache: Optional[Path] = None,
    matches_path: Optional[Path] = None,
) -> Tuple[List[Dict[str, object]], Dict[str, bytes], List[Dict[str, object]]]:
    provider_names = [providers] if isinstance(providers, str) else list(providers or [])
    if provider_names:
        games = _merge_provider_data(games, provider_names, provider_cache, matches_path)
    overrides = load_overrides(overrides_path)
    prepared = apply_overrides(games, overrides)
    prepared = [game for game in prepared if not game.get("exclude", False)]
    if len(prepared) > MAX_RECORDS:
        raise MetadataError(f"manifest exceeds {MAX_RECORDS} entries")

    artwork_sources: Dict[str, Path] = {}
    for game in prepared:
        source = game.get("_artwork_source")
        if source is None:
            continue
        if not isinstance(source, Path):
            raise MetadataError("internal artwork source is invalid")
        stable_id = str(game["id"])
        previous = artwork_sources.get(stable_id)
        if previous is not None and previous != source:
            raise MetadataError(f"conflicting artwork sources for stable id {stable_id}")
        artwork_sources[stable_id] = source

    artwork = {stable_id: convert_artwork(source) for stable_id, source in artwork_sources.items()}
    result: List[Dict[str, object]] = []
    attribution: List[Dict[str, object]] = []
    for game in prepared:
        rom = str(game["rom"])
        stable_id = str(game["id"])
        entry: Dict[str, object] = {
            "rom": rom,
            "id": stable_id,
            "title": game.get("title", PurePosixPath(rom).stem),
            "system": game.get("system", "Unknown System"),
        }
        for field in ("release_year", "genre", "information", "players", "region",
                      "rating", "publisher", "developer", "provider", "provider_id"):
            if game.get(field) is not None:
                entry[field] = game[field]
        if game.get("_artwork_source") is not None:
            digest = stable_id.removeprefix("sha1:")
            entry["thumbnail"] = f"metadata/art/sha1-{digest}.png"

        contributions = game.get("_provider_contributions", [])
        if not isinstance(contributions, list):
            raise MetadataError("internal provider attribution is invalid")
        for contribution in contributions:
            if not isinstance(contribution, dict):
                raise MetadataError("internal provider attribution is invalid")
            provider_name = str(contribution["provider"])
            provider_id = str(contribution["provider_id"])
            source_pages = {
                "screenscraper": (
                    "https://www.screenscraper.fr/gameinfos.php?gameid=" +
                    quote(provider_id, safe="")
                ),
                "thegamesdb": "https://thegamesdb.net/game.php?id=" + quote(provider_id, safe=""),
            }
            item: Dict[str, object] = {
                "rom": rom,
                "provider": provider_name,
                "provider_id": provider_id,
                "source_page": source_pages[provider_name],
            }
            provider_artwork = contribution.get("artwork")
            if (isinstance(provider_artwork, dict) and
                    game.get("_artwork_source") == contribution.get("artwork_source")):
                item["artwork"] = {
                    "type": provider_artwork.get("type", ""),
                    "region": provider_artwork.get("region", ""),
                }
            attribution.append(item)

        for field, value in list(entry.items()):
            if field in INTEGER_RANGES:
                entry[field] = _validate_integer(field, value)
                continue
            if not isinstance(value, str):
                raise MetadataError(f"{field} must be a string")
            normalized = value if field == "rom" else metadata_ascii(value)
            if not normalized:
                raise MetadataError(f"{field} becomes empty after ASCII transliteration")
            if field == "rom":
                validate_runtime_path(normalized, "manifest ROM path")
            limit = RUNTIME_LIMITS[field]
            if len(normalized.encode("ascii")) > limit:
                raise MetadataError(f"{field} exceeds the runtime limit of {limit} bytes")
            entry[field] = normalized
        result.append(entry)

    result.sort(key=lambda game: (str(game["rom"]).casefold(), str(game["rom"])))
    priorities = {"screenscraper": 0, "thegamesdb": 1}
    attribution.sort(key=lambda game: (
        str(game["rom"]).casefold(), str(game["rom"]),
        priorities[str(game["provider"])], str(game["provider_id"]),
    ))
    return result, artwork, attribution


def _merge_provider_data(
    games: Sequence[Dict[str, object]], provider_names: Sequence[str], cache_dir: Optional[Path],
    matches_path: Optional[Path] = None,
) -> List[Dict[str, object]]:
    from copy import deepcopy

    from .provider_cache import ProviderCache, TheGamesDBCache
    from .providers import provider_class
    from .providers.base import lookup_candidates

    if cache_dir is None:
        raise MetadataError("--provider-cache is required when a provider is selected")
    if not provider_names:
        return deepcopy(list(games))
    if len(set(provider_names)) != len(provider_names):
        raise MetadataError("duplicate metadata providers are not allowed")
    priorities = {"screenscraper": 0, "thegamesdb": 1}
    for provider_name in provider_names:
        provider_class(provider_name)
    provider_names = sorted(provider_names, key=lambda name: priorities[name])
    if "thegamesdb" in provider_names and matches_path is None:
        raise MetadataError("--matches is required when TheGamesDB is selected")
    result = deepcopy(list(games))
    matches = load_matches(matches_path, result) if "thegamesdb" in provider_names else {}
    identities: Dict[Tuple[str, str], Dict[str, object]] = {}
    match_presence: Dict[Tuple[str, str], bool] = {}
    for game in result:
        stable_id = str(game["id"])
        contributions: List[Dict[str, object]] = []
        for provider_name in provider_names:
            provider_type = provider_class(provider_name)
            artwork_source = None
            if provider_name == "thegamesdb":
                from .providers.thegamesdb import TheGamesDBProvider

                platforms = TheGamesDBProvider.system_ids(str(game["system"]))
                selected_id = matches.get(str(game["rom"]))
                game_cache = TheGamesDBCache(cache_dir, provider_type.adapter_version)
                matched = game_cache.read_game(selected_id) if selected_id is not None else None
                if selected_id is not None and matched is None:
                    raise MetadataError(
                        f"confirmed TheGamesDB game {selected_id} is not cached; run enrich first"
                    )
                if matched is not None and int(matched["platform_id"]) not in platforms:
                    raise MetadataError(
                        f"cached TheGamesDB game {selected_id} has an incompatible platform"
                    )
                cache = game_cache.blobs
            else:
                requested_system = provider_type.system_id(str(game["system"]))
                matched = None
                cache = ProviderCache(cache_dir, provider_name, provider_type.adapter_version)
                if requested_system is not None:
                    for candidate in lookup_candidates(game):
                        cached = cache.read(requested_system, candidate)
                        if cached is not None and cached["result"] == "matched":
                            matched = cached
                            break
            has_provider_match = matched is not None
            presence_key = (stable_id, provider_name)
            previous_presence = match_presence.get(presence_key)
            if previous_presence is not None and previous_presence != has_provider_match:
                raise MetadataError(
                    f"inconsistent provider match presence for stable id {stable_id}"
                )
            match_presence[presence_key] = has_provider_match
            if matched is None:
                continue
            metadata = matched["metadata"]
            if not isinstance(metadata, dict):
                raise MetadataError("provider cache metadata is invalid")
            contributed = False
            contributed_fields: List[str] = []
            for field in ("title", "release_year", "genre", "information", "players",
                          "region", "rating", "publisher", "developer"):
                value = metadata.get(field)
                if value not in (None, "") and game.get(field) in (None, ""):
                    game[field] = value
                    contributed = True
                    contributed_fields.append(field)
            artwork = matched.get("artwork")
            if isinstance(artwork, dict) and game.get("_artwork_source") is None:
                source = cache.blob_path(str(artwork["blob"]), require=True)
                game["_artwork_source"] = source
                artwork_source = source
                contributed = True
            normalized_metadata = tuple(
                (field, metadata_ascii(value) if isinstance(value, str) else value)
                for field, value in sorted(metadata.items())
                if value not in (None, "")
            )
            artwork_identity = None if artwork is None else (
                str(artwork["blob"]), str(artwork["type"]), str(artwork["region"])
            )
            identity: Dict[str, object] = {
                "provider": provider_name,
                "provider_id": str(matched["provider_id"]),
                "metadata": normalized_metadata,
                "artwork": artwork_identity,
            }
            previous = identities.get(presence_key)
            if previous is not None:
                if previous["provider_id"] != identity["provider_id"]:
                    raise MetadataError(f"conflicting provider IDs for stable id {stable_id}")
                if previous["metadata"] != identity["metadata"]:
                    raise MetadataError(f"conflicting provider metadata for stable id {stable_id}")
                if previous["artwork"] != identity["artwork"]:
                    raise MetadataError(f"conflicting provider artwork for stable id {stable_id}")
            else:
                identities[presence_key] = identity
            if contributed:
                contribution: Dict[str, object] = {
                    "provider": provider_name,
                    "provider_id": matched["provider_id"],
                    "fields": contributed_fields,
                }
                if artwork_source is not None:
                    contribution["artwork"] = dict(artwork)  # type: ignore[arg-type]
                    contribution["artwork_source"] = artwork_source
                contributions.append(contribution)
                if game.get("provider") is None:
                    game["provider"] = provider_name
                    game["provider_id"] = matched["provider_id"]
        game["_provider_contributions"] = contributions
    return result


def yaml_bytes(games: Sequence[Dict[str, object]]) -> bytes:
    lines = ["version: 1", "games:"]
    for game in games:
        first = True
        for field in FIELD_ORDER:
            if field not in game:
                continue
            value = game[field]
            rendered = str(value) if field in INTEGER_RANGES else _quote(str(value))
            prefix = "  - " if first else "    "
            line = f"{prefix}{field}: {rendered}"
            if len(line.encode("ascii")) > MAX_LINE_BYTES:
                raise MetadataError(f"manifest line for {field} exceeds {MAX_LINE_BYTES} bytes")
            lines.append(line)
            first = False
    data = ("\n".join(lines) + "\n").encode("ascii")
    if len(data) > MAX_MANIFEST_BYTES:
        raise MetadataError("games.yaml exceeds the 256 KiB runtime limit")
    return data


def _install_generated_files(
    staged_targets: Sequence[Tuple[Path, Path]], stage: Path, force: bool,
    deleted_targets: Sequence[Path] = (),
) -> None:
    installed: List[Path] = []
    backups: List[Tuple[Path, Path]] = []
    backup_dir = stage / ".backups"

    try:
        for index, (staged, target) in enumerate(staged_targets):
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise MetadataError(f"generated target is not a regular file: {target}")
            if force and target.exists():
                backup_dir.mkdir(exist_ok=True)
                backup = backup_dir / str(index)
                os.replace(target, backup)
                backups.append((backup, target))
            if force:
                os.replace(staged, target)
            else:
                os.link(staged, target)
            installed.append(target)
            if not force:
                try:
                    staged.unlink()
                except OSError:
                    pass
        for index, target in enumerate(deleted_targets, len(staged_targets)):
            if not force:
                raise MetadataError("managed generated files may only be deleted with --force")
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise MetadataError(f"generated target is not a regular file: {target}")
            if target.exists():
                backup_dir.mkdir(exist_ok=True)
                backup = backup_dir / str(index)
                os.replace(target, backup)
                backups.append((backup, target))
    except (MetadataError, OSError) as error:
        rollback_errors = []
        for target in reversed(installed):
            try:
                target.unlink()
            except OSError as rollback_error:
                if not isinstance(rollback_error, FileNotFoundError):
                    rollback_errors.append(rollback_error)
        for backup, target in reversed(backups):
            try:
                os.replace(backup, target)
            except OSError as rollback_error:
                rollback_errors.append(rollback_error)
        if rollback_errors:
            recovery = stage.with_name(stage.name + "-recovery")
            try:
                os.replace(stage, recovery)
                location = str(recovery)
            except OSError:
                location = str(stage)
            raise _RecoveryError(
                f"metadata installation and rollback failed; recovery files retained at {location}"
            ) from error
        if isinstance(error, MetadataError):
            raise
        raise MetadataError(f"failed to install generated metadata: {error}") from error


def generate(
    scan_path: Path,
    output_dir: Path,
    overrides_path: Optional[Path] = None,
    force: bool = False,
    provider: Optional[Sequence[str]] = None,
    provider_cache: Optional[Path] = None,
    matches_path: Optional[Path] = None,
) -> Tuple[int, int]:
    games, artwork, attribution = _prepare_games(
        load_scan(scan_path), overrides_path, provider, provider_cache, matches_path
    )
    manifest = yaml_bytes(games)
    manifest_target = output_dir / "games.yaml"
    artwork_targets = {
        stable_id: output_dir / "metadata" / "art" /
        f"sha1-{stable_id.removeprefix('sha1:')}.png"
        for stable_id in artwork
    }
    attribution_path = output_dir / "metadata" / "attribution.json"
    attribution_target = attribution_path if attribution else None
    managed_targets = [manifest_target, *artwork_targets.values()]
    if attribution_target is not None:
        managed_targets.append(attribution_target)
    existing = [target for target in managed_targets if target.exists()]
    if existing and not force:
        raise MetadataError(f"output already exists (use --force): {existing[0]}")

    output_parent = output_dir.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".vectordrive-metadata-", dir=output_parent))
    preserve_stage = False
    try:
        (stage / "games.yaml").write_bytes(manifest)
        if artwork:
            (stage / "metadata" / "art").mkdir(parents=True)
            for stable_id, data in artwork.items():
                (stage / "metadata" / "art" /
                 f"sha1-{stable_id.removeprefix('sha1:')}.png").write_bytes(data)
        if attribution:
            (stage / "metadata").mkdir(parents=True, exist_ok=True)
            attribution_data = {
                "version": 1,
                "games": attribution,
            }
            (stage / "metadata" / "attribution.json").write_bytes(
                json.dumps(attribution_data, indent=2, sort_keys=True,
                           ensure_ascii=True).encode("ascii") + b"\n"
            )

        staged_targets: List[Tuple[Path, Path]] = []
        for stable_id, target in artwork_targets.items():
            staged_targets.append((
                stage / "metadata" / "art" / f"sha1-{stable_id.removeprefix('sha1:')}.png",
                target,
            ))
        if attribution_target is not None:
            staged_targets.append((stage / "metadata" / "attribution.json", attribution_target))
        staged_targets.append((stage / "games.yaml", manifest_target))
        deleted_targets = [attribution_path] if force and not attribution else []
        _install_generated_files(staged_targets, stage, force, deleted_targets)
    except _RecoveryError:
        preserve_stage = True
        raise
    except OSError as error:
        raise MetadataError(f"failed to write generated metadata: {error}") from error
    finally:
        if not preserve_stage:
            shutil.rmtree(stage, ignore_errors=True)
    return len(games), len(artwork)
