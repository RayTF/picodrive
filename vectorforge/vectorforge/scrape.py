"""VectorForge orchestration around the existing metadata providers."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Sequence

from backend.artwork import convert_artwork
from backend.enrich import enrich
from backend.identity import MetadataError
from backend.manifest import generate, load_scan
from backend.providers.base import MetadataProvider, lookup_candidates
from backend.providers.screenscraper import ScreenScraperCredentials, ScreenScraperProvider
from backend.providers.thegamesdb import TheGamesDBProvider
from backend.rom_scan import scan_mappings, write_scan

from .library import Game, LibraryStore
from .package import parse_manifest
from .paths import AppPaths


@dataclass(frozen=True)
class ScrapeResult:
    scanned: int
    matched: int
    artwork: int
    reports: tuple[Path, ...]


@dataclass(frozen=True)
class ManualCandidate:
    provider: str
    provider_id: str
    title: str
    system: str
    metadata: Dict[str, object]
    media: Optional[Dict[str, str]] = None

    @property
    def label(self) -> str:
        return f"{self.title}  |  {self.provider} #{self.provider_id}"


def find_manual_candidates(
    game: Game,
    *,
    providers: Sequence[str],
    query: Optional[str] = None,
    screenscraper: Optional[ScreenScraperCredentials] = None,
    thegamesdb_api_key: Optional[str] = None,
    screenscraper_provider: Optional[MetadataProvider] = None,
    thegamesdb_provider: Optional[MetadataProvider] = None,
) -> list[ManualCandidate]:
    """Return provider records that a user can explicitly apply to one game."""

    scan = scan_mappings([(str(game.stored_path), game.rom_path)])
    record = scan["games"][0]
    assert isinstance(record, dict)
    results: list[ManualCandidate] = []
    selected = list(dict.fromkeys(providers))
    if "screenscraper" in selected:
        client = screenscraper_provider
        if client is None:
            if screenscraper is None:
                raise MetadataError("ScreenScraper credentials are required")
            client = ScreenScraperProvider(screenscraper)
        seen = set()
        for lookup in lookup_candidates(record):
            result = client.lookup(lookup)
            if result.get("result") != "matched":
                continue
            provider_id = str(result.get("provider_id", ""))
            metadata = result.get("metadata")
            if not provider_id or not isinstance(metadata, dict) or provider_id in seen:
                continue
            seen.add(provider_id)
            media = result.get("media")
            results.append(ManualCandidate(
                "screenscraper", provider_id,
                str(metadata.get("title") or game.title), game.system, dict(metadata),
                dict(media) if isinstance(media, dict) else None,
            ))
    if "thegamesdb" in selected:
        client = thegamesdb_provider
        if client is None:
            client = TheGamesDBProvider(thegamesdb_api_key or "")
        if not hasattr(client, "search"):
            raise MetadataError("TheGamesDB search capability is unavailable")
        title_query = (query or "").strip() or game.title
        response = client.search(title_query, game.system, exact=False)  # type: ignore[attr-defined]
        candidates = response.get("candidates") if isinstance(response, dict) else None
        if not isinstance(candidates, list):
            raise MetadataError("TheGamesDB returned invalid search candidates")
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            provider_id = str(candidate.get("provider_id", ""))
            title = str(candidate.get("title", ""))
            if provider_id and title:
                results.append(ManualCandidate(
                    "thegamesdb", provider_id, title, game.system, {"title": title},
                ))
    results.sort(key=lambda item: (item.title.casefold(), item.title, item.provider, item.provider_id))
    return results


def apply_manual_candidate(
    store: LibraryStore,
    game: Game,
    candidate: ManualCandidate,
    *,
    temp_dir: Path,
    screenscraper: Optional[ScreenScraperCredentials] = None,
    thegamesdb_api_key: Optional[str] = None,
    screenscraper_provider: Optional[MetadataProvider] = None,
    thegamesdb_provider: Optional[MetadataProvider] = None,
) -> Game:
    """Fetch and apply the provider record selected by the user."""

    metadata: Mapping[str, object] = candidate.metadata
    media: Optional[Mapping[str, object]] = candidate.media
    if candidate.provider == "screenscraper":
        client = screenscraper_provider
        if client is None:
            if screenscraper is None:
                raise MetadataError("ScreenScraper credentials are required")
            client = ScreenScraperProvider(screenscraper)
    elif candidate.provider == "thegamesdb":
        client = thegamesdb_provider or TheGamesDBProvider(thegamesdb_api_key or "")
        if not hasattr(client, "game"):
            raise MetadataError("TheGamesDB game lookup capability is unavailable")
        result = client.game(candidate.provider_id, game.system)  # type: ignore[attr-defined]
        if not isinstance(result, dict) or not isinstance(result.get("metadata"), dict):
            raise MetadataError("TheGamesDB returned invalid game metadata")
        metadata = result["metadata"]  # type: ignore[assignment]
        media = result.get("media") if isinstance(result.get("media"), dict) else None
    else:
        raise MetadataError(f"unsupported metadata provider: {candidate.provider}")

    values = dict(metadata)
    values.update({"provider": candidate.provider, "provider_id": candidate.provider_id})
    updated = store.update_metadata(game.id, values)
    if media is not None:
        data = client.download_artwork(media)
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="vectorforge-manual-art-", suffix=".png",
                                         dir=temp_dir, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        try:
            store.set_artwork(game.id, convert_artwork(temporary))
        finally:
            temporary.unlink(missing_ok=True)
        updated = store.get(game.id) or updated
    return updated


def _write_empty_matches(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "provider": "thegamesdb", "games": []}, indent=2) + "\n",
        encoding="ascii",
    )


def _apply_generated(store: LibraryStore, generated: Path) -> tuple[int, int]:
    manifest_path = generated / "games.yaml"
    if not manifest_path.is_file():
        raise MetadataError("metadata generation did not produce games.yaml")
    manifest = parse_manifest(manifest_path.read_bytes())
    by_rom = {game.rom_path.casefold(): game for game in store.list_games()}
    matched = 0
    artwork = 0
    for rom, values in manifest.items():
        game = by_rom.get(rom.casefold())
        if game is None:
            continue
        metadata = {key: value for key, value in values.items() if key not in {"rom", "id", "thumbnail"}}
        store.update_metadata(game.id, metadata)
        matched += 1
        thumbnail = values.get("thumbnail")
        if isinstance(thumbnail, str):
            artwork_path = generated / thumbnail
            if artwork_path.is_file():
                store.set_artwork(game.id, artwork_path.read_bytes())
                artwork += 1
    return matched, artwork


def scrape_library(
    store: LibraryStore,
    paths: AppPaths,
    *,
    providers: Sequence[str] = ("screenscraper",),
    screenscraper: Optional[ScreenScraperCredentials] = None,
    thegamesdb_api_key: Optional[str] = None,
    matches: Optional[Path] = None,
    offline: bool = False,
    refresh: bool = False,
    progress: Optional[Callable[[str], None]] = None,
) -> ScrapeResult:
    """Scan the library, enrich provider caches, and install generated metadata."""

    games = store.list_games()
    if not games:
        return ScrapeResult(0, 0, 0, ())
    scan_dir = paths.cache / "scans"
    report_dir = paths.cache / "reports"
    generated = paths.temp / "generated"
    provider_cache = paths.cache / "providers"
    scan_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    generated.mkdir(parents=True, exist_ok=True)
    scan_path = scan_dir / "library.json"
    document = scan_mappings([(str(game.stored_path), game.rom_path) for game in games])
    write_scan(document, scan_path, force=True)
    reports: list[Path] = []
    selected = list(dict.fromkeys(providers))
    if not selected:
        raise MetadataError("at least one metadata provider is required")
    if progress:
        progress(f"Scanned {len(games)} ROM(s)")
    for provider in selected:
        report = report_dir / f"{provider}.json"
        reports.append(report)
        if progress:
            progress(f"Enriching with {provider}")
        if provider == "screenscraper":
            enrich(
                scan_path, provider, provider_cache, report,
                offline=offline, refresh=refresh, force=True,
                credentials=screenscraper,
            )
        elif provider == "thegamesdb":
            enrich(
                scan_path, provider, provider_cache, report,
                offline=offline, refresh=refresh, force=True,
                matches_path=matches,
                thegamesdb_api_key=thegamesdb_api_key,
            )
        else:
            raise MetadataError(f"unsupported provider: {provider}")
    matches_path = matches
    if "thegamesdb" in selected and matches_path is None:
        matches_path = paths.temp / "empty-thegamesdb-matches.json"
        _write_empty_matches(matches_path)
    generated_dir = generated / "library"
    count, _ = generate(
        scan_path, generated_dir, force=True, provider=selected,
        provider_cache=provider_cache, matches_path=matches_path,
    )
    matched, artwork = _apply_generated(store, generated_dir)
    if progress:
        progress(f"Generated metadata for {count} game(s)")
    return ScrapeResult(len(games), matched, artwork, tuple(reports))
