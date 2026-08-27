"""Online/offline provider enrichment into the immutable provider cache."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from .identity import MetadataError
from .manifest import load_scan
from .matches import load_matches
from .provider_cache import ProviderCache, TheGamesDBCache
from .providers import provider_class
from .providers.base import MetadataProvider, ProviderOperationalError, lookup_candidates
from .providers.screenscraper import ScreenScraperCredentials
from .providers.thegamesdb import TheGamesDBProvider, search_title, validate_media


def _write_report(report: Path, document: Mapping[str, object], force: bool) -> None:
    if report.exists() and not force:
        raise MetadataError(f"output already exists (use --force): {report}")
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.is_symlink() or (report.exists() and not report.is_file()):
        raise MetadataError(f"report target is not a regular file: {report}")
    data = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True).encode("ascii") + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{report.name}.", dir=report.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temporary, report)
        else:
            os.link(temporary, report)
            os.unlink(temporary)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _report_document(provider: str, total: int, games: List[Dict[str, object]],
                      error: Optional[ProviderOperationalError] = None) -> Dict[str, object]:
    names = ["matched", "unmatched", "unsupported_system", "cache_miss"]
    if provider == "thegamesdb":
        names.extend(["confirmation_required", "ambiguous", "rejected", "error"])
    outcomes = {name: 0 for name in names}
    for game in games:
        status = str(game["status"])
        if status in outcomes:
            outcomes[status] += 1
    document: Dict[str, object] = {
        "version": 1,
        "provider": provider,
        "summary": {"total": total, "processed": len(games), **outcomes},
        "games": games,
    }
    if error is not None:
        document["error"] = {"category": error.category}
    return document


def _row(rom: str, status: str, source: str, basis: Optional[str] = None,
         provider_id: Optional[str] = None, artwork_status: str = "not_available",
         detail: Optional[str] = None) -> Dict[str, object]:
    row: Dict[str, object] = {
        "rom": rom,
        "status": status,
        "source": source,
        "lookup_basis": basis,
        "provider_id": provider_id,
        "artwork_status": artwork_status,
    }
    if detail:
        row["detail"] = detail
    return row


def _cached_match_row(rom: str, basis: str, result: Mapping[str, object]) -> Dict[str, object]:
    artwork = result.get("artwork")
    return _row(
        rom, "matched", "cache", basis, str(result["provider_id"]),
        "available" if artwork is not None else "not_available",
    )


def enrich(
    scan_path: Path,
    provider_name: str,
    cache_dir: Path,
    report_path: Path,
    offline: bool = False,
    refresh: bool = False,
    force: bool = False,
    credentials: Optional[ScreenScraperCredentials] = None,
    provider_instance: Optional[MetadataProvider] = None,
    matches_path: Optional[Path] = None,
    thegamesdb_api_key: Optional[str] = None,
) -> Dict[str, object]:
    if offline and refresh:
        raise MetadataError("--offline and --refresh are mutually exclusive")
    if report_path.exists() and not force:
        raise MetadataError(f"output already exists (use --force): {report_path}")
    provider_type = provider_class(provider_name)
    games = load_scan(scan_path)
    if provider_name == "thegamesdb":
        return _enrich_thegamesdb(
            games, cache_dir, report_path, offline, refresh, force, matches_path,
            thegamesdb_api_key, provider_instance,
        )
    cache = ProviderCache(cache_dir, provider_name, provider_type.adapter_version)
    rows: List[Dict[str, object]] = []
    operational_error: Optional[ProviderOperationalError] = None
    try:
        client = provider_instance
        if not offline and client is None:
            if provider_name != "screenscraper" or credentials is None:
                raise ProviderOperationalError("ScreenScraper credentials are required", "auth")
            client = provider_type(credentials)  # type: ignore[call-arg]
        for game in games:
            rom = str(game["rom"])
            requested_system = provider_type.system_id(str(game["system"]))
            if requested_system is None:
                rows.append(_row(rom, "unsupported_system", "none"))
                continue
            candidates = lookup_candidates(game)
            missing = False
            last_basis: Optional[str] = None
            matched = False
            for candidate in candidates:
                basis = str(candidate["basis"])
                last_basis = basis
                cached = None if refresh else cache.read(requested_system, candidate)
                if cached is not None:
                    if cached["result"] == "matched":
                        rows.append(_cached_match_row(rom, basis, cached))
                        matched = True
                        break
                    continue
                missing = True
                if offline:
                    continue
                assert client is not None
                result = client.lookup(candidate)
                if result.get("result") == "matched":
                    artwork_status = "not_available"
                    detail = None
                    cached_result = dict(result)
                    media = cached_result.pop("media", None)
                    if isinstance(media, dict):
                        try:
                            blob = cache.store_blob(client.download_artwork(media))
                            cached_result["artwork"] = {
                                "blob": blob,
                                "type": str(media.get("type", "")),
                                "region": str(media.get("region", "")),
                            }
                            artwork_status = "available"
                        except ProviderOperationalError:
                            artwork_status = "failed"
                            detail = "artwork download failed; metadata retained"
                    cached = cache.write(requested_system, candidate, cached_result, refresh)
                    rows.append(_row(
                        rom, "matched", "network", basis, str(cached["provider_id"]),
                        artwork_status, detail,
                    ))
                    matched = True
                    break
                if result.get("result") != "unmatched":
                    raise ProviderOperationalError("provider returned an invalid lookup result", "malformed")
                cache.write(requested_system, candidate, result, refresh)
            if matched:
                continue
            if offline and missing:
                rows.append(_row(rom, "cache_miss", "cache", last_basis))
            else:
                rows.append(_row(rom, "unmatched", "cache" if offline else "network", last_basis))
    except ProviderOperationalError as error:
        operational_error = error
    except MetadataError:
        cache_error = ProviderOperationalError("provider cache operation failed", "cache")
        _write_report(
            report_path, _report_document(provider_name, len(games), rows, cache_error), force
        )
        raise

    document = _report_document(provider_name, len(games), rows, operational_error)
    _write_report(report_path, document, force)
    if operational_error is not None:
        raise operational_error
    return document


def _thegamesdb_row(rom: str, status: str, source: str,
                    provider_id: Optional[str] = None,
                    artwork_status: str = "not_available",
                    **extra: object) -> Dict[str, object]:
    row: Dict[str, object] = {
        "rom": rom, "status": status, "source": source,
        "provider_id": provider_id, "artwork_status": artwork_status,
    }
    row.update(extra)
    return row


def _enrich_thegamesdb(
    games: List[Dict[str, object]], cache_dir: Path, report_path: Path,
    offline: bool, refresh: bool, force: bool, matches_path: Optional[Path],
    api_key: Optional[str], provider_instance: Optional[MetadataProvider],
) -> Dict[str, object]:
    if report_path.exists() and not force:
        raise MetadataError(f"output already exists (use --force): {report_path}")
    matches = load_matches(matches_path, games)
    cache = TheGamesDBCache(cache_dir, TheGamesDBProvider.adapter_version)
    rows: List[Dict[str, object]] = []
    operational_error: Optional[ProviderOperationalError] = None
    current_rom: Optional[str] = None
    current_source = "network"
    try:
        client = provider_instance
        if not offline and client is None:
            client = TheGamesDBProvider(api_key or "")
        for game in games:
            rom = str(game["rom"])
            current_rom = rom
            platforms = TheGamesDBProvider.system_ids(str(game["system"]))
            if not platforms:
                rows.append(_thegamesdb_row(rom, "unsupported_system", "none"))
                continue
            if rom in matches:
                selected_id = matches[rom]
                if selected_id is None:
                    rows.append(_thegamesdb_row(rom, "rejected", "matches"))
                    continue
                cached = None if refresh else cache.read_game(selected_id)
                current_source = "cache" if cached is not None or offline else "network"
                if cached is not None:
                    if int(cached["platform_id"]) not in platforms:
                        raise MetadataError(
                            f"cached TheGamesDB game {selected_id} is incompatible with {rom}"
                        )
                    rows.append(_thegamesdb_row(
                        rom, "matched", "cache", selected_id,
                        "available" if cached.get("artwork") is not None else "not_available",
                    ))
                    continue
                if offline:
                    rows.append(_thegamesdb_row(rom, "cache_miss", "cache", selected_id))
                    continue
                if client is None or not hasattr(client, "game"):
                    raise ProviderOperationalError("TheGamesDB provider capability is unavailable", "service")
                result = client.game(selected_id, str(game["system"]))  # type: ignore[attr-defined]
                if not isinstance(result, dict):
                    raise ProviderOperationalError("TheGamesDB returned an invalid game result", "malformed")
                allowed_result = {
                    "provider_id", "platform_id", "metadata", "media",
                    "media_error", "media_truncated",
                }
                if (set(result) - allowed_result or
                        result.get("provider_id") != selected_id or
                        not isinstance(result.get("provider_id"), str)):
                    raise ProviderOperationalError("TheGamesDB returned an invalid game ID", "malformed")
                platform_id = result.get("platform_id")
                if type(platform_id) is not int:
                    raise ProviderOperationalError(
                        "TheGamesDB returned an invalid game platform", "malformed"
                    )
                if platform_id not in platforms:
                    raise ProviderOperationalError(
                        "TheGamesDB selected game has an incompatible platform", "platform"
                    )
                for flag in ("media_error", "media_truncated"):
                    if flag in result and not isinstance(result[flag], bool):
                        raise ProviderOperationalError(
                            "TheGamesDB returned an invalid artwork status", "malformed"
                        )
                try:
                    cache.validate_game_data(selected_id, platform_id, result.get("metadata"))
                except MetadataError as error:
                    raise ProviderOperationalError(
                        "TheGamesDB returned invalid metadata", "malformed"
                    ) from error
                artwork_status = "not_available"
                detail = None
                media = result.get("media")
                artwork = None
                if media is not None and not isinstance(media, dict):
                    raise ProviderOperationalError(
                        "TheGamesDB returned invalid artwork data", "malformed"
                    )
                if isinstance(media, dict):
                    media = validate_media(media)
                    try:
                        blob = cache.blobs.store_blob(client.download_artwork(media))
                        artwork = {
                            "blob": blob, "type": str(media.get("type", "")),
                            "region": str(media.get("region", "")),
                        }
                        artwork_status = "available"
                    except ProviderOperationalError:
                        artwork_status = "failed"
                        detail = "artwork download failed; metadata retained"
                elif result.get("media_error") is True:
                    artwork_status = "failed"
                    detail = "artwork lookup failed; metadata retained"
                elif result.get("media_truncated") is True:
                    artwork_status = "truncated"
                    detail = "artwork unavailable; image results truncated"
                cached = cache.write_game(
                    selected_id, platform_id,
                    result.get("metadata", {}), artwork, refresh,
                )
                extra = {"detail": detail} if detail else {}
                rows.append(_thegamesdb_row(
                    rom, "matched", "network", selected_id, artwork_status, **extra
                ))
                continue

            title = search_title(game)
            cached_search = None if refresh else cache.read_search(platforms, title)
            current_source = "cache" if cached_search is not None or offline else "network"
            if cached_search is None:
                if offline:
                    rows.append(_thegamesdb_row(
                        rom, "cache_miss", "cache", search_title=title,
                    ))
                    continue
                if client is None or not hasattr(client, "search"):
                    raise ProviderOperationalError("TheGamesDB provider capability is unavailable", "service")
                result = client.search(title, str(game["system"]))  # type: ignore[attr-defined]
                if (not isinstance(result, dict) or set(result) != {"candidates", "truncated"} or
                        not isinstance(result.get("truncated"), bool)):
                    raise ProviderOperationalError(
                        "TheGamesDB returned an invalid search result", "malformed"
                    )
                cached_search = cache.write_search(
                    platforms, title, result.get("candidates", []),
                    result.get("truncated"), refresh,
                )
                source = "network"
            else:
                source = "cache"
            candidates = list(cached_search["candidates"])
            truncated = bool(cached_search["truncated"])
            if truncated or len(candidates) > 1:
                status = "ambiguous"
            elif candidates:
                status = "confirmation_required"
            else:
                status = "unmatched"
            rows.append(_thegamesdb_row(
                rom, status, source, search_title=title,
                candidates=candidates, truncated=truncated,
            ))
    except ProviderOperationalError as error:
        operational_error = error
        if current_rom is not None:
            rows.append(_thegamesdb_row(
                current_rom, "error", current_source, detail=error.category,
            ))
    except MetadataError:
        cache_error = ProviderOperationalError("provider cache operation failed", "cache")
        if current_rom is not None:
            rows.append(_thegamesdb_row(current_rom, "error", "cache", detail="cache"))
        _write_report(
            report_path, _report_document("thegamesdb", len(games), rows, cache_error), force
        )
        raise

    document = _report_document("thegamesdb", len(games), rows, operational_error)
    _write_report(report_path, document, force)
    if operational_error is not None:
        raise operational_error
    return document
