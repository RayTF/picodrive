"""TheGamesDB strict title-search and confirmed game-record adapter."""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import PurePosixPath
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode, urlsplit

from ..identity import MetadataError, ProviderOperationalError
from ..net import HttpClient, HttpResponse
from ..overrides import STRING_LIMITS, metadata_ascii
from .base import MetadataProvider

API_ROOT = "https://api.thegamesdb.net/v1"
SYSTEM_IDS = {
    "Mega Drive / Genesis": (18, 36),
    "Master System": (35,),
    "Game Gear": (20,),
    "32X": (33,),
    "Sega / Mega CD": (21,),
    "Sega Pico": (4958,),
}
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_MEDIA_BYTES = 16 * 1024 * 1024
MAX_PAGES = 5
MAX_IMAGE_PAGES = 5
MAX_SEARCH_ROWS = 256
MAX_CANDIDATES = 64
MAX_ENTITY_IDS = 16
MAX_IMAGES_PER_PAGE = 256
MAX_IMAGES = 512
RECOGNIZED_EXTENSIONS = {
    "zip", "bin", "pco", "smd", "gen", "md", "iso", "cso", "cue", "chd",
    "32x", "sms", "gg", "sg", "sc",
}
REGION_TAG = re.compile(
    r"(?:usa|us|europe|eu|japan|jp|world|wor|asia|australia|brazil|korea)"
    r"(?:\s*[,;+]\s*(?:usa|us|europe|eu|japan|jp|world|wor|asia|australia|brazil|korea))*",
    re.IGNORECASE,
)
REVISION_TAG = re.compile(r"(?:rev(?:ision)?\s*[a-z0-9.]+|v(?:er(?:sion)?)?\s*\d[\w.]*)",
                          re.IGNORECASE)
DUMP_TAG = re.compile(r"(?:!|[abfhotp]\d*|bad dump|overdump|hack|prototype|proto|beta|sample)",
                      re.IGNORECASE)
ENTITY_ENDPOINTS = {
    "genre": ("Genres/ByGenreID", "genres"),
    "publisher": ("Publishers/ByPublisherID", "publishers"),
    "developer": ("Developers/ByDeveloperID", "developers"),
}


def _quota_text(value: str) -> bool:
    if any(term in value for term in (
        "quota", "rate limit", "too many requests", "allowance exhausted",
    )):
        return True
    try:
        document = json.loads(value)
    except (json.JSONDecodeError, RecursionError):
        return False
    if not isinstance(document, dict):
        return False
    counters = [
        document[key] for key in ("remaining_monthly_allowance", "extra_allowance")
        if key in document
    ]
    return bool(counters) and all(
        type(counter) in {int, float} and counter <= 0 for counter in counters
    )


def system_ids(system: str) -> Tuple[int, ...]:
    return SYSTEM_IDS.get(system, ())


def search_filename(game: Mapping[str, object]) -> str:
    archive = game.get("archive")
    if isinstance(archive, dict) and isinstance(archive.get("selected_member"), str):
        filename = str(archive["selected_member"]).replace("\\", "/").rsplit("/", 1)[-1]
        if filename:
            return filename
    return PurePosixPath(str(game["rom"])).name


def search_title(game: Mapping[str, object]) -> str:
    filename = search_filename(game)
    suffix = PurePosixPath(filename).suffix
    title = filename[:-len(suffix)] if suffix and suffix[1:].casefold() in RECOGNIZED_EXTENSIONS else filename
    while True:
        match = re.search(r"\s*([([])([^()[\]]+)([)\]])\s*$", title)
        if match is None:
            break
        opening, content, closing = match.groups()
        if (opening, closing) not in {("(", ")"), ("[", "]")}:
            break
        value = content.strip()
        code = value.casefold()
        short_region = (
            code == "w" or
            1 <= len(code) <= 3 and set(code) <= {"u", "j", "e"} and len(set(code)) == len(code)
        )
        if not (REGION_TAG.fullmatch(value) or short_region or REVISION_TAG.fullmatch(value) or
                DUMP_TAG.fullmatch(value)):
            break
        title = title[:match.start()].rstrip()
    normalized = metadata_ascii(title)
    if not normalized:
        raise MetadataError(f"cannot derive a TheGamesDB search title from {filename!r}")
    return normalized[:255]


def normalize_match_title(value: object) -> str:
    if not isinstance(value, str):
        return ""
    unescaped = html.unescape(value)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", metadata_ascii(unescaped).casefold()).split())


def _unique_object(pairs: object) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for key, value in pairs:  # type: ignore[assignment]
        if key in result:
            raise ProviderOperationalError("TheGamesDB returned duplicate JSON keys", "malformed")
        result[key] = value
    return result


def _decode(response: HttpResponse) -> Mapping[str, object]:
    try:
        document = json.loads(
            response.body.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except ProviderOperationalError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise ProviderOperationalError("TheGamesDB returned malformed JSON", "malformed") from error
    if not isinstance(document, dict):
        raise ProviderOperationalError("TheGamesDB returned malformed JSON", "malformed")
    code = document.get("code")
    if code is not None and (isinstance(code, bool) or str(code) != "200"):
        status = str(document.get("status", "")).casefold()
        if str(code) in {"400", "406"}:
            category = "request"
        elif str(code) in {"401", "418"}:
            category = "auth"
        elif str(code) == "403":
            category = "quota" if _quota_text(status) else "auth"
        else:
            category = "service"
        raise ProviderOperationalError("TheGamesDB rejected the request", category)
    return document


def _data(document: Mapping[str, object]) -> Mapping[str, object]:
    data = document.get("data")
    if not isinstance(data, dict):
        raise ProviderOperationalError("TheGamesDB response has no data object", "malformed")
    return data


def _game_rows(data: Mapping[str, object]) -> List[Mapping[str, object]]:
    games = data.get("games")
    if games is None:
        return []
    if isinstance(games, dict):
        if any(not isinstance(value, dict) for value in games.values()):
            raise ProviderOperationalError("TheGamesDB games data is malformed", "malformed")
        rows = [value for _, value in sorted(games.items(), key=lambda item: str(item[0]))
                if isinstance(value, dict)]
    elif isinstance(games, list):
        if any(not isinstance(value, dict) for value in games):
            raise ProviderOperationalError("TheGamesDB games data is malformed", "malformed")
        rows = [value for value in games if isinstance(value, dict)]
    else:
        raise ProviderOperationalError("TheGamesDB games data is malformed", "malformed")
    if len(rows) > MAX_SEARCH_ROWS:
        raise ProviderOperationalError("TheGamesDB returned too many game records", "malformed")
    return rows


def _positive_id(value: object) -> Optional[str]:
    if isinstance(value, bool):
        return None
    text = str(value) if isinstance(value, (str, int)) else ""
    return text if len(text) <= 63 and re.fullmatch(r"[1-9][0-9]*", text) else None


def _platform_id(game: Mapping[str, object]) -> Optional[int]:
    value = game.get("platform")
    if isinstance(value, dict):
        value = value.get("id", value.get("platform_id"))
    if value is None:
        value = game.get("platform_id")
    return value if type(value) is int and value > 0 else None


def _text_values(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        if len(value) > 128:
            raise ProviderOperationalError("TheGamesDB field has too many values", "malformed")
        for item in value:
            yield from _text_values(item)
    elif isinstance(value, dict):
        for key in ("name", "title", "game_title"):
            if key in value and isinstance(value[key], str):
                yield str(value[key])
                return


def _alternates(game: Mapping[str, object]) -> List[str]:
    values = list(_text_values(game.get("alternates", game.get("alternate_titles"))))
    return values[:32]


def _has_next_page(document: Mapping[str, object], data: Mapping[str, object],
                   label: str) -> bool:
    pages = data.get("pages", document.get("pages"))
    if not isinstance(pages, dict) or not {"previous", "current", "next"} <= set(pages):
        raise ProviderOperationalError(f"TheGamesDB {label} pagination is malformed", "malformed")
    if any(value is not None and (
            not isinstance(value, str) or not value or len(value) > 2048)
           for value in (pages["previous"], pages["current"], pages["next"])):
        raise ProviderOperationalError(f"TheGamesDB {label} pagination is malformed", "malformed")
    return pages["next"] is not None


def normalize_search_page(document: Mapping[str, object], title: str,
                          compatible_platforms: Sequence[int],
                          exact: bool = True) -> Tuple[List[Dict[str, object]], bool]:
    data = _data(document)
    wanted = normalize_match_title(title)
    candidates: List[Dict[str, object]] = []
    seen: Dict[str, Tuple[str, int, str, str]] = {}
    for game in _game_rows(data):
        provider_id = _positive_id(game.get("id"))
        platform_id = _platform_id(game)
        game_title = game.get("game_title", game.get("title"))
        alternates = _alternates(game)
        primary_match = normalize_match_title(game_title) == wanted
        alternate_matches = sorted(
            (value for value in alternates if normalize_match_title(value) == wanted),
            key=lambda value: (metadata_ascii(html.unescape(value)).casefold(), value),
        )
        if (provider_id is None or platform_id not in compatible_platforms or
                exact and not primary_match and not alternate_matches):
            continue
        bounded_title = metadata_ascii(html.unescape(str(game_title))) if isinstance(game_title, str) else ""
        if not bounded_title:
            raise ProviderOperationalError("TheGamesDB search result has no title", "malformed")
        bounded_title = bounded_title[:STRING_LIMITS["title"]]
        matched_title = game_title if primary_match or not exact else alternate_matches[0]
        bounded_match = metadata_ascii(html.unescape(str(matched_title)))[:STRING_LIMITS["title"]]
        if not bounded_match:
            raise ProviderOperationalError("TheGamesDB search match has no title", "malformed")
        match_basis = "game_title" if primary_match or not exact else "alternate"
        identity = (bounded_title, int(platform_id), bounded_match, match_basis)
        if provider_id in seen and seen[provider_id] != identity:
            raise ProviderOperationalError("TheGamesDB returned conflicting game IDs", "malformed")
        if provider_id not in seen:
            seen[provider_id] = identity
            candidates.append({
                "provider_id": provider_id, "title": bounded_title,
                "platform_id": int(platform_id), "matched_title": bounded_match,
                "match_basis": match_basis,
            })
    return candidates, _has_next_page(document, data, "search")


def _bounded(field: str, value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = metadata_ascii(html.unescape(value))
    if not text:
        return None
    limit = STRING_LIMITS[field]
    if len(text) <= limit:
        return text
    clipped = text[:limit + 1]
    boundary = clipped.rfind(" ", 0, limit + 1)
    return clipped[:boundary if boundary > 0 else limit].rstrip()


def _entity_ids(value: object, namespace: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_ENTITY_IDS:
        raise ProviderOperationalError(
            f"TheGamesDB {namespace} IDs are malformed", "malformed"
        )
    result = []
    for item in value:
        if type(item) is not int or item <= 0:
            raise ProviderOperationalError(
                f"TheGamesDB {namespace} IDs are malformed", "malformed"
            )
        identifier = str(item)
        if len(identifier) > 63:
            raise ProviderOperationalError(
                f"TheGamesDB {namespace} IDs are malformed", "malformed"
            )
        if identifier not in result:
            result.append(identifier)
    return sorted(result, key=int)


def normalize_entities(document: Mapping[str, object], namespace: str,
                       requested_ids: Sequence[str]) -> Dict[str, str]:
    if namespace not in ENTITY_ENDPOINTS:
        raise ValueError("unknown TheGamesDB entity namespace")
    if (not requested_ids or len(requested_ids) > MAX_ENTITY_IDS or
            len(set(requested_ids)) != len(requested_ids) or
            any(not re.fullmatch(r"[1-9][0-9]{0,62}", identifier)
                for identifier in requested_ids)):
        raise ProviderOperationalError(
            f"TheGamesDB requested {namespace} IDs are malformed", "malformed"
        )
    requested = set(requested_ids)
    data = _data(document)
    collection = ENTITY_ENDPOINTS[namespace][1]
    value = data.get(collection)
    if isinstance(value, dict):
        rows = list(value.values())
    elif isinstance(value, list):
        rows = value
    else:
        raise ProviderOperationalError(
            f"TheGamesDB {namespace} data is malformed", "malformed"
        )
    if len(rows) > MAX_ENTITY_IDS or any(not isinstance(row, dict) for row in rows):
        raise ProviderOperationalError(
            f"TheGamesDB {namespace} data is malformed", "malformed"
        )
    result: Dict[str, str] = {}
    for row in rows:
        identifier = _positive_id(row.get("id"))
        if identifier is None or identifier not in requested or identifier in result:
            raise ProviderOperationalError(
                f"TheGamesDB {namespace} IDs are invalid or duplicated", "malformed"
            )
        name = _bounded(namespace, row.get("name"))
        if name is None:
            raise ProviderOperationalError(
                f"TheGamesDB {namespace} has no name", "malformed"
            )
        result[identifier] = name
    return result


def _players(value: object) -> Optional[int]:
    text = " ".join(_text_values(value)) if not isinstance(value, (int, float)) else str(value)
    numbers = [int(number) for number in re.findall(r"\d+", text)]
    valid = [number for number in numbers if 1 <= number <= 8]
    return max(valid) if valid else None


def normalize_game(document: Mapping[str, object], provider_id: str,
                   compatible_platforms: Sequence[int]) -> Dict[str, object]:
    data = _data(document)
    rows = [game for game in _game_rows(data) if _positive_id(game.get("id")) == provider_id]
    if len(rows) != 1:
        raise ProviderOperationalError("TheGamesDB selected game is missing or duplicated", "malformed")
    game = rows[0]
    platform_id = _platform_id(game)
    if platform_id not in compatible_platforms:
        raise ProviderOperationalError("TheGamesDB selected game has an incompatible platform", "platform")
    metadata: Dict[str, object] = {}
    title = _bounded("title", game.get("game_title", game.get("title")))
    information = _bounded("information", game.get("overview"))
    date = game.get("release_date")
    year_match = re.search(r"(?:^|\D)(\d{4})(?:\D|$)", date) if isinstance(date, str) else None
    year = int(year_match.group(1)) if year_match else None
    players = _players(game.get("players"))
    for field, value in (
        ("title", title),
        ("release_year", year if year is not None and 1000 <= year <= 9999 else None),
        ("information", information),
        ("players", players),
    ):
        if value is not None:
            metadata[field] = value
    entities = {
        "genre": _entity_ids(game.get("genres"), "genre"),
        "publisher": _entity_ids(game.get("publishers"), "publisher"),
        "developer": _entity_ids(game.get("developers"), "developer"),
    }
    return {
        "provider_id": provider_id, "platform_id": int(platform_id),
        "metadata": metadata, "entity_ids": entities,
    }


def _validate_cdn_url(url: object) -> str:
    if (not isinstance(url, str) or not url or len(url) > 2048 or
            any(ord(character) < 0x21 or ord(character) > 0x7E for character in url)):
        raise ProviderOperationalError("TheGamesDB artwork URL is not permitted", "media")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
        username = parsed.username
        password = parsed.password
    except (ValueError, UnicodeError) as error:
        raise ProviderOperationalError(
            "TheGamesDB artwork URL is not permitted", "media"
        ) from error
    if (parsed.scheme != "https" or (hostname or "").casefold() != "cdn.thegamesdb.net" or
            port not in {None, 443} or username is not None or password is not None or
            parsed.query or parsed.fragment or not parsed.path.startswith("/")):
        raise ProviderOperationalError("TheGamesDB artwork URL is not permitted", "media")
    return url


def _cdn_media(base: object, filename: object, media_type: str) -> Dict[str, str]:
    base_url = _validate_cdn_url(base)
    if (not isinstance(filename, str) or not filename or len(filename) > 512 or
            any(ord(character) < 0x21 or ord(character) > 0x7E for character in filename) or
            filename.startswith("/") or "\\" in filename or ":" in filename or
            "?" in filename or "#" in filename or
            any(part in {"", ".", ".."} for part in filename.split("/"))):
        raise ProviderOperationalError("TheGamesDB artwork filename is not permitted", "media")
    url = base_url + ("" if base_url.endswith("/") else "/") + filename
    return {"url": _validate_cdn_url(url), "type": media_type, "region": ""}


def validate_media(media: object) -> Dict[str, str]:
    if not isinstance(media, dict) or set(media) != {"url", "type", "region"}:
        raise ProviderOperationalError("TheGamesDB artwork data is malformed", "malformed")
    media_type = media.get("type")
    region = media.get("region")
    if media_type not in {"titlescreen", "screenshot", "boxart"} or region != "":
        raise ProviderOperationalError("TheGamesDB artwork data is malformed", "malformed")
    return {"url": _validate_cdn_url(media.get("url")), "type": media_type, "region": ""}


def normalize_image_page(document: Mapping[str, object], provider_id: str) -> Tuple[
        str, List[Tuple[int, str, str, str]], bool]:
    data = _data(document)
    base_urls = data.get("base_url")
    base = base_urls.get("original") if isinstance(base_urls, dict) else None
    base = _validate_cdn_url(base)
    images = data.get("images")
    if not isinstance(images, dict):
        raise ProviderOperationalError("TheGamesDB image data is malformed", "media")
    values = images.get(provider_id)
    if values is None:
        values = []
    if not isinstance(values, list) or len(values) > MAX_IMAGES_PER_PAGE:
        raise ProviderOperationalError("TheGamesDB image data is malformed", "media")
    choices: List[Tuple[int, str, str, str]] = []
    priorities = {"titlescreen": 0, "title screen": 0, "screenshot": 1, "boxart": 2}
    for image in values:
        if not isinstance(image, dict):
            raise ProviderOperationalError("TheGamesDB image data is malformed", "media")
        raw_type = image.get("type", "")
        raw_side = image.get("side", "")
        if not isinstance(raw_type, str):
            raise ProviderOperationalError("TheGamesDB image data is malformed", "media")
        media_type = raw_type.casefold()
        if raw_side is None:
            side = ""
        elif isinstance(raw_side, str):
            side = raw_side.casefold()
        else:
            raise ProviderOperationalError("TheGamesDB image data is malformed", "media")
        filename = image.get("filename")
        if media_type not in priorities or (media_type == "boxart" and side != "front"):
            continue
        normalized_type = "titlescreen" if media_type == "title screen" else media_type
        _cdn_media(base, filename, normalized_type)
        assert isinstance(filename, str)
        choices.append((priorities[media_type], filename.casefold(), filename, media_type))
    return base, choices, _has_next_page(document, data, "image")


def normalize_images(document: Mapping[str, object], provider_id: str) -> Optional[Dict[str, str]]:
    base, choices, has_next = normalize_image_page(document, provider_id)
    if has_next:
        raise ProviderOperationalError("TheGamesDB image pagination is incomplete", "media")
    if not choices:
        return None
    _, _, filename, media_type = min(choices)
    normalized_type = "titlescreen" if media_type == "title screen" else media_type
    return _cdn_media(base, filename, normalized_type)


class TheGamesDBProvider(MetadataProvider):
    name = "thegamesdb"
    adapter_version = 3

    @classmethod
    def system_id(cls, system: str) -> Optional[int]:
        ids = system_ids(system)
        return ids[0] if ids else None

    @classmethod
    def system_ids(cls, system: str) -> Tuple[int, ...]:
        return system_ids(system)

    def __init__(self, api_key: str, http: Optional[HttpClient] = None,
                 transport: Optional[Callable[[str, float, int], HttpResponse]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if (not api_key or len(api_key) > 512 or
                any(ord(character) < 0x21 or ord(character) > 0x7E for character in api_key)):
            raise ProviderOperationalError("TheGamesDB API key is required", "auth")
        if http is not None and transport is not None:
            raise ValueError("supply either http or transport, not both")
        self.api_key = api_key
        self.http = http or HttpClient(transport=transport, clock=clock, sleep=sleep)

    def _url(self, endpoint: str, parameters: Mapping[str, object]) -> str:
        query = {key: str(value) for key, value in parameters.items()}
        query["apikey"] = self.api_key
        return f"{API_ROOT}/{endpoint}?{urlencode(query)}"

    def _get(self, endpoint: str, parameters: Mapping[str, object]) -> Mapping[str, object]:
        response = self.http.get(self._url(endpoint, parameters), 30.0, MAX_METADATA_BYTES)
        if response.status != 200:
            if response.status in {400, 406}:
                category = "request"
            elif response.status in {401, 418}:
                category = "auth"
            elif response.status == 403:
                body = response.body[:4096].decode("utf-8", errors="replace").casefold()
                category = "quota" if _quota_text(body) else "auth"
            else:
                category = "service"
            raise ProviderOperationalError(
                f"TheGamesDB request failed with HTTP {response.status}", category
            )
        return _decode(response)

    def search(self, title: str, system: str, exact: bool = True) -> Dict[str, object]:
        platforms = system_ids(system)
        if not platforms:
            return {"candidates": [], "truncated": False}
        candidates: Dict[str, Dict[str, object]] = {}
        truncated = False
        for page in range(1, MAX_PAGES + 1):
            document = self._get("Games/ByGameName", {
                "name": title, "filter[platform]": ",".join(str(value) for value in platforms),
                "fields": "alternates", "page": page,
            })
            rows, has_next = normalize_search_page(document, title, platforms, exact)
            for row in rows:
                identifier = str(row["provider_id"])
                if identifier in candidates and candidates[identifier] != row:
                    raise ProviderOperationalError("TheGamesDB returned conflicting game IDs", "malformed")
                candidates[identifier] = row
            if len(candidates) > MAX_CANDIDATES:
                truncated = True
                break
            if not has_next:
                break
            if page == MAX_PAGES:
                truncated = True
        ordered = sorted(candidates.values(), key=lambda row: (
            str(row["title"]).casefold(), str(row["title"]), int(row["platform_id"]),
            int(str(row["provider_id"])),
        ))[:MAX_CANDIDATES]
        return {"candidates": ordered, "truncated": truncated}

    def game(self, provider_id: str, system: str) -> Dict[str, object]:
        platforms = system_ids(system)
        document = self._get("Games/ByGameID", {
            "id": provider_id,
            "fields": "players,publishers,genres,overview",
        })
        result = normalize_game(document, provider_id, platforms)
        entities = result.pop("entity_ids")
        metadata = result["metadata"]
        if not isinstance(entities, dict) or not isinstance(metadata, dict):
            raise ProviderOperationalError("TheGamesDB game data is malformed", "malformed")
        for namespace, (endpoint, _) in ENTITY_ENDPOINTS.items():
            identifiers = entities.get(namespace)
            if not isinstance(identifiers, list):
                raise ProviderOperationalError("TheGamesDB entity IDs are malformed", "malformed")
            if not identifiers:
                continue
            names = list(normalize_entities(
                self._get(endpoint, {"id": ",".join(identifiers)}), namespace, identifiers
            ).values())
            if names:
                metadata[namespace] = sorted(
                    set(names), key=lambda name: (name.casefold(), name)
                )[0]
        try:
            base: Optional[str] = None
            choices: List[Tuple[int, str, str, str]] = []
            truncated = False
            for page in range(1, MAX_IMAGE_PAGES + 1):
                images = self._get("Games/Images", {
                    "games_id": provider_id,
                    "filter[type]": "titlescreen,screenshot,boxart",
                    "page": page,
                })
                page_base, page_choices, has_next = normalize_image_page(images, provider_id)
                if base is not None and page_base != base:
                    raise ProviderOperationalError(
                        "TheGamesDB artwork base URL changed between pages", "media"
                    )
                base = page_base
                choices.extend(page_choices)
                if len(choices) > MAX_IMAGES:
                    raise ProviderOperationalError(
                        "TheGamesDB returned too many images", "media"
                    )
                if not has_next:
                    break
                if page == MAX_IMAGE_PAGES:
                    truncated = True
            if truncated:
                result["media_truncated"] = True
            elif choices and base is not None:
                _, _, filename, media_type = min(set(choices))
                normalized_type = "titlescreen" if media_type == "title screen" else media_type
                result["media"] = _cdn_media(base, filename, normalized_type)
        except ProviderOperationalError:
            result["media_error"] = True
        return result

    def download_artwork(self, media: Mapping[str, object]) -> bytes:
        url = _validate_cdn_url(media.get("url"))
        response = self.http.get(url, 30.0, MAX_MEDIA_BYTES)
        if response.status != 200:
            raise ProviderOperationalError(
                f"TheGamesDB artwork request failed with HTTP {response.status}", "media"
            )
        return response.body
