"""ScreenScraper API adapter and response normalization."""

from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import urlencode, urlsplit

from ..net import HttpClient, HttpResponse
from ..overrides import STRING_LIMITS, metadata_ascii
from .base import MetadataProvider, ProviderOperationalError

ENDPOINT = "https://api.screenscraper.fr/api2/jeuInfos.php"
SYSTEM_IDS = {
    "Mega Drive / Genesis": 1,
    "Master System": 2,
    "32X": 19,
    "Sega / Mega CD": 20,
    "Game Gear": 21,
    "Sega Pico": 250,
}
REGION_ORDER = ("us", "eu", "wor", "jp", "ss")
MEDIA_TYPES = ("sstitle", "ss", "box-2D")
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_MEDIA_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ScreenScraperCredentials:
    dev_id: str
    dev_password: str
    soft_name: str
    user: Optional[str] = None
    password: Optional[str] = None

    def validate(self) -> None:
        if not self.dev_id or not self.dev_password or not self.soft_name:
            raise ProviderOperationalError(
                "ScreenScraper developer ID, developer password, and software name are required",
                "auth",
            )
        if bool(self.user) != bool(self.password):
            raise ProviderOperationalError(
                "ScreenScraper user and password must be supplied together", "auth"
            )


def system_id(system: str) -> Optional[int]:
    return SYSTEM_IDS.get(system)


def _objects(value: object) -> List[Mapping[str, object]]:
    if isinstance(value, dict):
        wrappers = {"jeu", "game", "nom", "name", "genre", "media", "date", "rom", "synopsis"}
        if len(value) == 1:
            key = next(iter(value))
            if key.casefold() in wrappers and isinstance(value[key], (dict, list)):
                return _objects(value[key])
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict):
        for key in ("text", "nom", "name", "value", "region"):
            if key in value:
                result = _text(value[key])
                if result:
                    return result
    if isinstance(value, list):
        for item in value:
            result = _text(item)
            if result:
                return result
    return ""


def _code(item: Mapping[str, object], *names: str) -> str:
    for name in names:
        value = item.get(name)
        if isinstance(value, str):
            return value.casefold()
    return ""


def _bounded(field: str, value: object) -> Optional[str]:
    normalized = metadata_ascii(html.unescape(_text(value)))
    if not normalized:
        return None
    limit = STRING_LIMITS[field]
    if len(normalized.encode("ascii")) <= limit:
        return normalized
    clipped = normalized[:limit + 1]
    boundary = clipped.rfind(" ", 0, limit + 1)
    if boundary > 0:
        clipped = clipped[:boundary]
    else:
        clipped = clipped[:limit]
    return clipped.rstrip()


def _localized(value: object, regions: Sequence[str], language: Optional[str] = None) -> str:
    items = _objects(value)
    if not items:
        return _text(value)
    if language:
        for item in items:
            if _code(item, "langue", "language", "lang") == language:
                return _text(item)
        return ""
    for region in regions:
        for item in items:
            if _code(item, "region", "regions") == region:
                return _text(item)
    return _text(items[0])


def _value(game: Mapping[str, object], *names: str) -> object:
    for name in names:
        if name in game:
            return game[name]
    return None


def _returned_rom(game: Mapping[str, object]) -> Optional[Mapping[str, object]]:
    for name in ("rom", "roms"):
        items = _objects(game.get(name))
        if items:
            return items[0]
    return None


def _hash_value(rom: Mapping[str, object], name: str) -> str:
    aliases = {
        "crc32": ("romcrc", "crc", "crc32"),
        "md5": ("rommd5", "md5"),
        "sha1": ("romsha1", "sha1"),
    }
    for key in aliases[name]:
        value = rom.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower().removeprefix("0x")
    return ""


def _system_value(game: Mapping[str, object]) -> Optional[int]:
    values: List[object] = [game.get("systemeid"), game.get("systemid"), game.get("systeme")]
    for value in values:
        if isinstance(value, dict):
            value = value.get("id", value.get("systemeid"))
        try:
            if value is not None:
                return int(str(value))
        except ValueError:
            continue
    return None


def _identity_status(game: Mapping[str, object], candidate: Mapping[str, object],
                     requested_system: int) -> str:
    returned_system = _system_value(game)
    if returned_system is not None and returned_system != requested_system:
        return "contradictory"
    rom = _returned_rom(game)
    if rom is None:
        return "missing"
    returned_hashes = {name: _hash_value(rom, name) for name in ("crc32", "md5", "sha1")}
    present = [(name, value) for name, value in returned_hashes.items() if value]
    if not present:
        return "missing"
    if not any(value == str(candidate[name]).lower() for name, value in present):
        return "contradictory"
    if any(value != str(candidate[name]).lower() for name, value in present):
        return "contradictory"
    size_value = rom.get("romtaille", rom.get("size"))
    size_present = size_value not in (None, "")
    if size_present:
        try:
            if int(str(size_value)) != candidate["size"]:
                return "contradictory"
        except ValueError:
            return "contradictory"
    return "matched"


def verify_match(game: Mapping[str, object], candidate: Mapping[str, object],
                 requested_system: int) -> bool:
    return _identity_status(game, candidate, requested_system) == "matched"


def _regions(game: Mapping[str, object]) -> List[str]:
    result: List[str] = []
    rom = _returned_rom(game)
    values: Iterable[object] = ()
    if rom is not None:
        raw = rom.get("romregions", rom.get("region"))
        values = raw if isinstance(raw, list) else [raw]
    for value in values:
        code = _text(value).casefold()
        if code and code not in result:
            result.append(code)
    return result


def _genre(game: Mapping[str, object]) -> str:
    genres = _objects(_value(game, "genres", "genre"))
    ordered = sorted(genres, key=lambda item: _text(item.get("principale")) not in {"1", "true"})
    for item in ordered:
        value = _localized(item.get("noms", item), (), "en")
        if value:
            return value
    return ""


def _players(value: object) -> Optional[int]:
    numbers = [int(number) for number in re.findall(r"\d+", _text(value))]
    valid = [number for number in numbers if 1 <= number <= 8]
    return max(valid) if valid else None


def _rating(value: object) -> Optional[int]:
    match = re.search(r"\d+(?:[.,]\d+)?", _text(value))
    if not match:
        return None
    try:
        return max(0, min(100, int(float(match.group().replace(",", ".")) * 5 + 0.5)))
    except ValueError:
        return None


def select_media(game: Mapping[str, object], regions: Sequence[str]) -> Optional[Dict[str, str]]:
    media = _objects(_value(game, "medias", "media"))
    region_order = list(regions) + [region for region in REGION_ORDER if region not in regions]
    for media_type in MEDIA_TYPES:
        typed = [item for item in media if _code(item, "type", "mediatype") == media_type.casefold()]
        for region in region_order + [""]:
            for item in typed:
                item_region = _code(item, "region")
                if region and item_region != region:
                    continue
                url = _text(item.get("url", item.get("source")))
                if url:
                    return {"url": url, "type": media_type, "region": item_region}
    return None


def normalize_response(document: object, candidate: Mapping[str, object],
                       requested_system: int) -> Dict[str, object]:
    if not isinstance(document, dict):
        raise ProviderOperationalError("ScreenScraper returned malformed JSON", "malformed")
    response = document.get("response", document)
    if not isinstance(response, dict):
        raise ProviderOperationalError("ScreenScraper returned malformed JSON", "malformed")
    error_value = next((response[key] for key in ("erreur", "error", "errors")
                        if key in response), None)
    if error_value is not None:
        error_text = _text(error_value).casefold()
        if any(word in error_text for word in ("quota", "request limit", "maximum")):
            category = "quota"
        elif any(word in error_text for word in ("password", "auth", "login", "developer")):
            category = "auth"
        else:
            category = "service"
        raise ProviderOperationalError("ScreenScraper rejected the request", category)
    games = _objects(response.get("jeu", response.get("game")))
    if not games:
        return {"result": "unmatched"}
    statuses = [(_identity_status(item, candidate, requested_system), item) for item in games]
    game = next((item for status, item in statuses if status == "matched"), None)
    if game is None:
        if any(status == "missing" for status, _ in statuses):
            raise ProviderOperationalError(
                "ScreenScraper game response has no ROM identity evidence", "malformed"
            )
        return {"result": "unmatched"}
    provider_id = metadata_ascii(_text(_value(game, "id", "gameid", "jeuid")))[:63]
    if not provider_id:
        raise ProviderOperationalError("ScreenScraper match has no game ID", "malformed")
    matched_regions = _regions(game)
    preferred = matched_regions + [region for region in REGION_ORDER if region not in matched_regions]
    metadata: Dict[str, object] = {}
    title = _bounded("title", _localized(_value(game, "noms", "names", "nom"), preferred))
    synopsis = _bounded("information", _localized(_value(game, "synopsis", "synopses"), (), "en"))
    genre = _bounded("genre", _genre(game))
    date = _localized(_value(game, "dates", "date"), preferred)
    year_match = re.search(r"\d{4}", date)
    players = _players(_value(game, "joueurs", "players"))
    rating = _rating(_value(game, "note", "rating"))
    region = _bounded("region", matched_regions[0].upper() if matched_regions else "")
    publisher = _bounded("publisher", _value(game, "editeur", "publisher"))
    developer = _bounded("developer", _value(game, "developpeur", "developer"))
    for field, value in (
        ("title", title), ("information", synopsis), ("genre", genre),
        ("release_year", int(year_match.group())
         if year_match and 1000 <= int(year_match.group()) <= 9999 else None),
        ("players", players), ("rating", rating), ("region", region),
        ("publisher", publisher), ("developer", developer),
    ):
        if value is not None:
            metadata[field] = value
    result: Dict[str, object] = {
        "result": "matched", "metadata": metadata, "provider_id": provider_id,
    }
    media = select_media(game, preferred)
    if media is not None:
        result["media"] = media
    return result


class ScreenScraperProvider(MetadataProvider):
    name = "screenscraper"
    adapter_version = 1

    @classmethod
    def system_id(cls, system: str) -> Optional[int]:
        return system_id(system)

    def __init__(self, credentials: ScreenScraperCredentials,
                 http: Optional[HttpClient] = None,
                 transport: Optional[Callable[[str, float, int], HttpResponse]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        credentials.validate()
        self.credentials = credentials
        if http is not None and transport is not None:
            raise ValueError("supply either http or transport, not both")
        self.http = http or HttpClient(transport=transport, clock=clock, sleep=sleep)

    def _url(self, candidate: Mapping[str, object], requested_system: int) -> str:
        query = {
            "output": "json",
            "devid": self.credentials.dev_id,
            "devpassword": self.credentials.dev_password,
            "softname": self.credentials.soft_name,
            "systemeid": str(requested_system),
            "romtype": "rom",
            "romnom": str(candidate["filename"]),
            "romtaille": str(candidate["size"]),
            "crc": str(candidate["crc32"]),
            "md5": str(candidate["md5"]),
            "sha1": str(candidate["sha1"]),
        }
        if self.credentials.user:
            query["ssid"] = self.credentials.user
            query["sspassword"] = str(self.credentials.password)
        return ENDPOINT + "?" + urlencode(query)

    def lookup(self, candidate: Mapping[str, object]) -> Dict[str, object]:
        requested_system = system_id(str(candidate["system"]))
        if requested_system is None:
            return {"result": "unsupported_system"}
        response = self.http.get(self._url(candidate, requested_system), 30.0, MAX_METADATA_BYTES)
        if response.status == 404:
            return {"result": "unmatched"}
        if response.status != 200:
            categories = {400: "request", 401: "auth", 403: "auth", 423: "quota", 426: "service",
                          430: "quota", 431: "quota"}
            raise ProviderOperationalError(
                f"ScreenScraper request failed with HTTP {response.status}",
                categories.get(response.status, "service"),
            )
        try:
            document = json.loads(response.body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise ProviderOperationalError("ScreenScraper returned malformed JSON", "malformed") from error
        return normalize_response(document, candidate, requested_system)

    def download_artwork(self, media: Mapping[str, object]) -> bytes:
        url = str(media.get("url", ""))
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or not (host == "screenscraper.fr" or host.endswith(".screenscraper.fr")):
            raise ProviderOperationalError("ScreenScraper artwork URL is not permitted", "media")
        response = self.http.get(url, 30.0, MAX_MEDIA_BYTES)
        if response.status != 200:
            raise ProviderOperationalError(
                f"ScreenScraper artwork request failed with HTTP {response.status}", "media"
            )
        return response.body
