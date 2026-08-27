"""Strict manual confirmation records for title-search providers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .identity import MetadataError
from .overrides import ID_PATTERN, load_json
from .rom_scan import MAX_RECORDS, validate_runtime_path


def load_matches(
    path: Optional[Path], games: Sequence[Mapping[str, object]]
) -> Dict[str, Optional[str]]:
    if path is None:
        return {}
    document = load_json(path, "matches")
    if not isinstance(document, dict) or set(document) != {"version", "provider", "games"}:
        raise MetadataError("matches JSON must contain only version, provider, and games")
    if document["version"] != 1 or isinstance(document["version"], bool):
        raise MetadataError("matches version must be 1")
    if document["provider"] != "thegamesdb":
        raise MetadataError("matches provider must be thegamesdb")
    if not isinstance(document["games"], list):
        raise MetadataError("matches games must be a list")
    if len(document["games"]) > MAX_RECORDS:
        raise MetadataError(f"matches exceeds {MAX_RECORDS} records")

    by_id: Dict[str, list[str]] = {}
    by_rom: Dict[str, str] = {}
    for game in games:
        stable_id = str(game["id"])
        rom = str(game["rom"])
        by_id.setdefault(stable_id, []).append(rom)
        by_rom[rom.casefold()] = rom

    selectors = {"id": set(), "rom": set()}
    parsed: List[Tuple[str, List[str], Optional[str]]] = []
    for index, item in enumerate(document["games"], 1):
        if not isinstance(item, dict) or set(item) - {"id", "rom", "provider_id"}:
            raise MetadataError(f"matches game {index} has an invalid field set")
        selector_keys = [name for name in ("id", "rom") if name in item]
        if len(selector_keys) != 1 or "provider_id" not in item:
            raise MetadataError(f"matches game {index} must contain one selector and provider_id")
        selector = selector_keys[0]
        value = item[selector]
        if not isinstance(value, str):
            raise MetadataError(f"matches game {index} {selector} must be a string")
        if selector == "id":
            if not ID_PATTERN.fullmatch(value):
                raise MetadataError(f"matches game {index} has an invalid stable id")
            key = value
            targets = by_id.get(value, [])
        else:
            validate_runtime_path(value, "matches ROM selector")
            key = value.casefold()
            target = by_rom.get(key)
            targets = [] if target is None else [target]
        if key in selectors[selector]:
            raise MetadataError(f"duplicate matches selector: {value}")
        selectors[selector].add(key)
        if not targets:
            raise MetadataError(f"unmatched matches {selector}: {value}")
        provider_id = item["provider_id"]
        if provider_id is not None and (
                not isinstance(provider_id, str) or
                not re.fullmatch(r"[1-9][0-9]*", provider_id) or len(provider_id) > 63):
            raise MetadataError(f"matches game {index} provider_id must be a positive decimal string or null")
        parsed.append((selector, targets, provider_id))

    selected: Dict[str, Optional[str]] = {}
    selected_by: Dict[str, str] = {}
    for selector in ("id", "rom"):
        for _, targets, provider_id in (item for item in parsed if item[0] == selector):
            for rom in targets:
                if rom in selected and selected[rom] != provider_id:
                    previous_selector = selected_by[rom]
                    raise MetadataError(
                        f"conflicting matches selectors for {rom}: "
                        f"{previous_selector} and {selector}"
                    )
                if rom in selected:
                    continue
                selected[rom] = provider_id
                selected_by[rom] = selector
    return selected
