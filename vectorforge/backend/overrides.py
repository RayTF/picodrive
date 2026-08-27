"""Strict JSON override loading and precedence handling."""

from __future__ import annotations

import json
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .identity import MetadataError
from .rom_scan import validate_runtime_path

MAX_JSON_BYTES = 8 * 1024 * 1024

ID_PATTERN = re.compile(r"sha1:[0-9a-f]{40}\Z")
OPTIONAL_STRINGS = {
    "genre", "information", "region", "publisher", "developer",
}
REQUIRED_STRINGS = {"title", "system"}
INTEGER_RANGES = {
    "release_year": (1000, 9999),
    "players": (1, 8),
    "rating": (0, 100),
}
ALLOWED_KEYS = {
    "id", "rom", "title", "system", "release_year", "genre", "information",
    "players", "region", "rating", "publisher", "developer", "artwork", "exclude",
}
STRING_LIMITS = {
    "title": 95,
    "system": 31,
    "genre": 31,
    "information": 511,
    "region": 23,
    "publisher": 63,
    "developer": 63,
}
CHARACTER_MAP = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    "\u2015": "-", "\u2212": "-", "\u2026": "...", "\u00a0": " ",
})


def metadata_ascii(value: str) -> str:
    mapped = value.translate(CHARACTER_MAP)
    decomposed = unicodedata.normalize("NFKD", mapped)
    printable = "".join(character for character in decomposed if 0x20 <= ord(character) <= 0x7E)
    return " ".join(printable.split())


def _unique_object(pairs: Sequence[tuple[str, object]]) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MetadataError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise MetadataError(f"nonstandard JSON value is not allowed: {value}")


def load_json(path: Path, label: str) -> object:
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            raise MetadataError(f"{label} JSON exceeds 8 MiB limit")
        text = data.decode("utf-8", errors="strict")
    except (OSError, UnicodeError) as error:
        raise MetadataError(f"cannot read {label} {path}: {error}") from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except MetadataError:
        raise
    except json.JSONDecodeError as error:
        raise MetadataError(f"invalid {label} JSON at line {error.lineno}: {error.msg}") from error


def _artwork_path(value: str, override_path: Path) -> Path:
    relative = Path(value)
    if not value or relative.is_absolute() or "\\" in value or ":" in value:
        raise MetadataError("artwork must be a relative local path")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise MetadataError(f"artwork path may not traverse directories: {value!r}")
    base = override_path.parent.resolve()
    resolved = (base / relative).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as error:
        raise MetadataError(f"artwork path escapes the override directory: {value!r}") from error
    return resolved


def load_overrides(path: Optional[Path]) -> List[Dict[str, object]]:
    if path is None:
        return []
    document = load_json(path, "override")
    if not isinstance(document, dict):
        raise MetadataError("override JSON must be an object")
    if set(document) != {"version", "games"}:
        raise MetadataError("override JSON must contain only version and games")
    if document["version"] != 1 or isinstance(document["version"], bool):
        raise MetadataError("override version must be 1")
    if not isinstance(document["games"], list):
        raise MetadataError("override games must be a list")

    overrides: List[Dict[str, object]] = []
    selectors = {"id": set(), "rom": set()}
    for index, item in enumerate(document["games"], 1):
        if not isinstance(item, dict):
            raise MetadataError(f"override game {index} must be an object")
        unknown = set(item) - ALLOWED_KEYS
        if unknown:
            raise MetadataError(f"override game {index} has unknown field: {sorted(unknown)[0]}")
        selector_keys = [key for key in ("id", "rom") if key in item]
        if len(selector_keys) != 1:
            raise MetadataError(f"override game {index} must match exactly one of id or rom")
        selector = selector_keys[0]
        selector_value = item[selector]
        if not isinstance(selector_value, str):
            raise MetadataError(f"override game {index} {selector} must be a string")
        if selector == "id":
            if not ID_PATTERN.fullmatch(selector_value):
                raise MetadataError(f"override game {index} has an invalid stable id")
            duplicate_key = selector_value
        else:
            validate_runtime_path(selector_value, "override ROM selector")
            duplicate_key = selector_value.casefold()
        if duplicate_key in selectors[selector]:
            raise MetadataError(f"duplicate override selector: {selector_value}")
        selectors[selector].add(duplicate_key)

        parsed = dict(item)
        for key in REQUIRED_STRINGS | OPTIONAL_STRINGS:
            if key not in parsed:
                continue
            value = parsed[key]
            if value is None and key in OPTIONAL_STRINGS:
                continue
            if not isinstance(value, str) or not metadata_ascii(value):
                raise MetadataError(f"override game {index} {key} must be a non-empty string")
            if len(metadata_ascii(value).encode("ascii")) > STRING_LIMITS[key]:
                raise MetadataError(f"override game {index} {key} exceeds the runtime limit")
        for key, (minimum, maximum) in INTEGER_RANGES.items():
            if key not in parsed or parsed[key] is None:
                continue
            value = parsed[key]
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise MetadataError(f"override game {index} {key} must be {minimum}..{maximum} or null")
        if "exclude" in parsed and not isinstance(parsed["exclude"], bool):
            raise MetadataError(f"override game {index} exclude must be boolean")
        if "artwork" in parsed and parsed["artwork"] is not None:
            if not isinstance(parsed["artwork"], str):
                raise MetadataError(f"override game {index} artwork must be a string or null")
            parsed["_artwork_source"] = _artwork_path(parsed["artwork"], path)
        overrides.append(parsed)
    return overrides


def apply_overrides(
    games: Sequence[Dict[str, object]], overrides: Sequence[Dict[str, object]]
) -> List[Dict[str, object]]:
    result = deepcopy(list(games))
    for selector in ("id", "rom"):
        for override in (item for item in overrides if selector in item):
            value = override[selector]
            if selector == "rom":
                matches = [game for game in result if
                           isinstance(game.get("rom"), str) and
                           str(game["rom"]).casefold() == str(value).casefold()]
            else:
                matches = [game for game in result if game.get(selector) == value]
            if not matches:
                raise MetadataError(f"unmatched override {selector}: {value}")
            for game in matches:
                for key, replacement in override.items():
                    if key in {"id", "rom", "artwork"}:
                        continue
                    game[key] = replacement
                    contributions = game.get("_provider_contributions", [])
                    if isinstance(contributions, list):
                        for contribution in contributions:
                            if isinstance(contribution, dict) and isinstance(
                                    contribution.get("fields"), list):
                                contribution["fields"] = [
                                    field for field in contribution["fields"] if field != key
                                ]
                if "artwork" in override:
                    game["_artwork_source"] = override.get("_artwork_source")
                    contributions = game.get("_provider_contributions", [])
                    if isinstance(contributions, list):
                        for contribution in contributions:
                            if isinstance(contribution, dict):
                                contribution.pop("artwork", None)
                                contribution.pop("artwork_source", None)
    for game in result:
        contributions = game.get("_provider_contributions")
        if not isinstance(contributions, list):
            continue
        contributions[:] = [
            contribution for contribution in contributions
            if isinstance(contribution, dict) and
            (contribution.get("fields") or contribution.get("artwork") is not None)
        ]
        if contributions:
            game["provider"] = contributions[0]["provider"]
            game["provider_id"] = contributions[0]["provider_id"]
        else:
            game.pop("provider", None)
            game.pop("provider_id", None)
    return result
