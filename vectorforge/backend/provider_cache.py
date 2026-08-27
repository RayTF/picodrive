"""Hardened content-addressed cache for metadata providers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from .identity import MetadataError
from .overrides import INTEGER_RANGES, STRING_LIMITS, metadata_ascii

MAX_CACHE_JSON_BYTES = 4 * 1024 * 1024
MAX_BLOB_BYTES = 16 * 1024 * 1024
PROVIDER_METADATA_FIELDS = {
    "title", "release_year", "genre", "information", "players", "region",
    "rating", "publisher", "developer",
}


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def cache_key_document(provider: str, adapter: int, system: int,
                       candidate: Mapping[str, object]) -> Dict[str, object]:
    return {
        "adapter": adapter,
        "hash": {name: candidate[name] for name in ("crc32", "md5", "sha1")},
        "provider": provider,
        "size": candidate["size"],
        "system": system,
    }


def cache_key(provider: str, adapter: int, system: int,
              candidate: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(
        cache_key_document(provider, adapter, system, candidate)
    )).hexdigest()


def _secure_directory(path: Path) -> None:
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    if current.is_symlink() or not current.is_dir():
        raise MetadataError(f"cache directory is unsafe: {current}")
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if directory.is_symlink() or not directory.is_dir():
            raise MetadataError(f"cache directory is unsafe: {directory}")
        try:
            directory.chmod(0o700)
        except OSError:
            pass
    _safe_ancestors(path)


def _safe_ancestors(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise MetadataError(f"cache directory is unsafe: {current}")
        if current.parent == current:
            break
        current = current.parent


def _regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISREG(mode)


def _atomic_write(path: Path, data: bytes, replace: bool) -> None:
    _secure_directory(path.parent)
    if path.is_symlink() or (path.exists() and not _regular_file(path)):
        raise MetadataError(f"cache target is not a regular file: {path}")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
            os.unlink(temporary)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _unique_object(pairs: object) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for key, value in pairs:  # type: ignore[assignment]
        if key in result:
            raise MetadataError(f"duplicate cache JSON key: {key}")
        result[key] = value
    return result


def _bounded_ascii(value: object, limit: int, allow_empty: bool = False) -> bool:
    if not isinstance(value, str) or metadata_ascii(value) != value:
        return False
    return (allow_empty or bool(value)) and len(value.encode("ascii")) <= limit


def _validate_match(metadata: object, provider_id: object, artwork: object,
                    label: str) -> None:
    if (not isinstance(metadata, dict) or set(metadata) - PROVIDER_METADATA_FIELDS or
            not _bounded_ascii(provider_id, 63)):
        raise MetadataError(f"{label} provider match is invalid")
    for field, value in metadata.items():
        if field in STRING_LIMITS:
            if not _bounded_ascii(value, STRING_LIMITS[field]):
                raise MetadataError(f"{label} provider metadata is invalid")
        elif field in INTEGER_RANGES:
            minimum, maximum = INTEGER_RANGES[field]
            if (isinstance(value, bool) or not isinstance(value, int) or
                    not minimum <= value <= maximum):
                raise MetadataError(f"{label} provider metadata is invalid")
        else:
            raise MetadataError(f"{label} provider metadata is invalid")
    if artwork is None:
        return
    if (not isinstance(artwork, dict) or set(artwork) != {"blob", "type", "region"} or
            not isinstance(artwork.get("blob"), str) or
            not re.fullmatch(r"[0-9a-f]{64}", str(artwork.get("blob"))) or
            not _bounded_ascii(artwork.get("type"), 31) or
            not _bounded_ascii(artwork.get("region"), 23, allow_empty=True)):
        raise MetadataError(f"{label} provider artwork is invalid")


class ProviderCache:
    def __init__(self, root: Path, provider: str, adapter: int = 1) -> None:
        if type(adapter) is not int or adapter <= 0:
            raise MetadataError("provider cache adapter must be a positive integer")
        self.root = Path(root)
        self.provider = provider
        self.adapter = adapter

    def lookup_path(self, system: int, candidate: Mapping[str, object]) -> Path:
        digest = cache_key(self.provider, self.adapter, system, candidate)
        return self.root / "providers" / self.provider / "lookups" / f"{digest}.json"

    def read(self, system: int, candidate: Mapping[str, object]) -> Optional[Dict[str, object]]:
        path = self.lookup_path(system, candidate)
        _safe_ancestors(path.parent)
        if not path.exists():
            return None
        if not _regular_file(path):
            raise MetadataError(f"provider cache entry is not a regular file: {path}")
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_CACHE_JSON_BYTES + 1)
            if len(data) > MAX_CACHE_JSON_BYTES:
                raise MetadataError("provider cache JSON exceeds 4 MiB limit")
            document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                                  parse_constant=lambda value: (_ for _ in ()).throw(
                                      MetadataError(f"invalid cache JSON value: {value}")))
        except MetadataError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise MetadataError(f"corrupt provider cache entry: {path.name}") from error
        expected_key = cache_key_document(self.provider, self.adapter, system, candidate)
        if not isinstance(document, dict) or set(document) != {
                "version", "key", "result", "metadata", "provider_id", "artwork"}:
            raise MetadataError(f"corrupt provider cache entry: {path.name}")
        key_document = document["key"]
        if (type(document["version"]) is not int or document["version"] != 1 or
                not isinstance(key_document, dict) or
                type(key_document.get("adapter")) is not int or
                key_document != expected_key):
            raise MetadataError(f"provider cache key mismatch: {path.name}")
        result = document["result"]
        if not isinstance(result, str) or result not in {"matched", "unmatched"}:
            raise MetadataError(f"corrupt provider cache result: {path.name}")
        if result == "matched":
            _validate_match(
                document["metadata"], document["provider_id"], document["artwork"],
                f"corrupt provider cache entry {path.name}",
            )
        elif any(document[field] is not None for field in ("metadata", "provider_id", "artwork")):
            raise MetadataError(f"corrupt provider negative cache entry: {path.name}")
        artwork = document["artwork"]
        if artwork is not None:
            self.blob_path(str(artwork["blob"]), require=True)
        return document

    def write(self, system: int, candidate: Mapping[str, object], result: Mapping[str, object],
              refresh: bool = False) -> Dict[str, object]:
        result_value = result.get("result")
        if not isinstance(result_value, str) or result_value not in {"matched", "unmatched"}:
            raise MetadataError("provider cache result must be matched or unmatched")
        matched = result_value == "matched"
        artwork = result.get("artwork")
        if matched:
            _validate_match(result.get("metadata"), result.get("provider_id"), artwork,
                            "provider cache")
            if isinstance(artwork, dict):
                self.blob_path(str(artwork["blob"]), require=True)
        document: Dict[str, object] = {
            "version": 1,
            "key": cache_key_document(self.provider, self.adapter, system, candidate),
            "result": "matched" if matched else "unmatched",
            "metadata": result.get("metadata") if matched else None,
            "provider_id": result.get("provider_id") if matched else None,
            "artwork": result.get("artwork") if matched else None,
        }
        data = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True).encode("ascii") + b"\n"
        _atomic_write(self.lookup_path(system, candidate), data, refresh)
        cached = self.read(system, candidate)
        if cached is None:
            raise MetadataError("provider cache write did not create an entry")
        return cached

    def blob_path(self, digest: str, require: bool = False) -> Path:
        path = self.root / "blobs" / "sha256" / digest
        if require:
            _safe_ancestors(path.parent)
            if not _regular_file(path):
                raise MetadataError(f"provider artwork blob is missing or unsafe: {digest}")
            try:
                size = path.stat().st_size
            except OSError as error:
                raise MetadataError(f"cannot inspect provider artwork blob: {digest}") from error
            if size > MAX_BLOB_BYTES:
                raise MetadataError(f"provider artwork blob exceeds 16 MiB: {digest}")
            hasher = hashlib.sha256()
            try:
                with path.open("rb") as stream:
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        hasher.update(chunk)
            except OSError as error:
                raise MetadataError(f"cannot read provider artwork blob: {digest}") from error
            if hasher.hexdigest() != digest:
                raise MetadataError(f"provider artwork blob is corrupt: {digest}")
        return path

    def store_blob(self, data: bytes) -> str:
        if len(data) > MAX_BLOB_BYTES:
            raise MetadataError("provider artwork exceeds 16 MiB")
        digest = hashlib.sha256(data).hexdigest()
        path = self.blob_path(digest)
        _atomic_write(path, data, False)
        self.blob_path(digest, require=True)
        return digest


def _read_cache_json(path: Path) -> object:
    _safe_ancestors(path.parent)
    if not path.exists():
        return None
    if not _regular_file(path):
        raise MetadataError(f"provider cache entry is not a regular file: {path}")
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_CACHE_JSON_BYTES + 1)
        if len(data) > MAX_CACHE_JSON_BYTES:
            raise MetadataError("provider cache JSON exceeds 4 MiB limit")
        return json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                MetadataError(f"invalid cache JSON value: {value}")),
        )
    except MetadataError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise MetadataError(f"corrupt provider cache entry: {path.name}") from error


def _write_cache_json(path: Path, document: Mapping[str, object], refresh: bool) -> None:
    data = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True).encode("ascii") + b"\n"
    _atomic_write(path, data, refresh)


class TheGamesDBCache:
    """Bounded records for title searches and explicitly selected games."""

    provider = "thegamesdb"

    def __init__(self, root: Path, adapter: int = 3) -> None:
        if type(adapter) is not int or adapter <= 0:
            raise MetadataError("TheGamesDB cache adapter must be a positive integer")
        self.root = Path(root)
        self.adapter = adapter
        self.blobs = ProviderCache(root, self.provider, adapter)

    def _search_key(self, system_ids: Sequence[int], title: str) -> Dict[str, object]:
        if (not system_ids or len(system_ids) > 8 or
                any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
                    for value in system_ids) or
                not _bounded_ascii(title, 255)):
            raise MetadataError("TheGamesDB search cache key is invalid")
        return {
            "adapter": self.adapter,
            "endpoint": "Games/ByGameName",
            "fields": "alternates",
            "platforms": list(system_ids),
            "provider": self.provider,
            "title": title,
        }

    def search_path(self, system_ids: Sequence[int], title: str) -> Path:
        digest = hashlib.sha256(canonical_json(self._search_key(system_ids, title))).hexdigest()
        return (self.root / "providers" / self.provider / "searches" /
                f"v{self.adapter}" / f"{digest}.json")

    @staticmethod
    def _validate_candidates(value: object, label: str) -> List[Dict[str, object]]:
        if not isinstance(value, list) or len(value) > 64:
            raise MetadataError(f"{label} candidates are invalid")
        result: List[Dict[str, object]] = []
        ids = set()
        for candidate in value:
            if not isinstance(candidate, dict) or set(candidate) != {
                    "provider_id", "title", "platform_id", "matched_title", "match_basis"}:
                raise MetadataError(f"{label} candidate is invalid")
            provider_id = candidate.get("provider_id")
            title = candidate.get("title")
            matched_title = candidate.get("matched_title")
            match_basis = candidate.get("match_basis")
            platform_id = candidate.get("platform_id")
            if (not _bounded_ascii(provider_id, 63) or
                    not re.fullmatch(r"[1-9][0-9]*", str(provider_id)) or
                    not _bounded_ascii(title, STRING_LIMITS["title"]) or
                    not _bounded_ascii(matched_title, STRING_LIMITS["title"]) or
                    match_basis not in {"game_title", "alternate"} or
                    isinstance(platform_id, bool) or not isinstance(platform_id, int) or
                    platform_id <= 0 or provider_id in ids):
                raise MetadataError(f"{label} candidate is invalid")
            ids.add(provider_id)
            result.append(dict(candidate))
        return result

    def read_search(self, system_ids: Sequence[int], title: str) -> Optional[Dict[str, object]]:
        path = self.search_path(system_ids, title)
        document = _read_cache_json(path)
        if document is None:
            return None
        if not isinstance(document, dict) or set(document) != {
                "version", "key", "candidates", "truncated"}:
            raise MetadataError(f"corrupt provider cache entry: {path.name}")
        key_document = document["key"]
        if (type(document["version"]) is not int or document["version"] != 1 or
                not isinstance(key_document, dict) or
                type(key_document.get("adapter")) is not int or
                key_document != self._search_key(system_ids, title)):
            raise MetadataError(f"provider cache key mismatch: {path.name}")
        candidates = self._validate_candidates(
            document["candidates"], f"corrupt provider cache entry {path.name}"
        )
        if any(int(candidate["platform_id"]) not in system_ids for candidate in candidates):
            raise MetadataError(f"corrupt provider cache entry: {path.name}")
        if not isinstance(document["truncated"], bool):
            raise MetadataError(f"corrupt provider cache entry: {path.name}")
        return document

    def write_search(self, system_ids: Sequence[int], title: str,
                     candidates: Sequence[Mapping[str, object]], truncated: bool,
                     refresh: bool = False) -> Dict[str, object]:
        normalized = self._validate_candidates(list(candidates), "provider search")
        if any(int(candidate["platform_id"]) not in system_ids for candidate in normalized):
            raise MetadataError("provider search candidate platform is incompatible")
        if not isinstance(truncated, bool):
            raise MetadataError("provider search truncation flag is invalid")
        document: Dict[str, object] = {
            "version": 1,
            "key": self._search_key(system_ids, title),
            "candidates": normalized,
            "truncated": truncated,
        }
        _write_cache_json(self.search_path(system_ids, title), document, refresh)
        cached = self.read_search(system_ids, title)
        if cached is None:
            raise MetadataError("provider search cache write did not create an entry")
        return cached

    def game_path(self, provider_id: str) -> Path:
        if len(provider_id) > 63 or not re.fullmatch(r"[1-9][0-9]*", provider_id):
            raise MetadataError("TheGamesDB provider ID is invalid")
        return (self.root / "providers" / self.provider / "games" /
                f"v{self.adapter}" / f"{provider_id}.json")

    def _validate_game(self, document: object, path: Path) -> Dict[str, object]:
        if not isinstance(document, dict) or set(document) != {
                "version", "provider", "adapter", "provider_id", "platform_id",
                "metadata", "artwork"}:
            raise MetadataError(f"corrupt provider cache entry: {path.name}")
        provider_id = document.get("provider_id")
        platform_id = document.get("platform_id")
        if (type(document["version"]) is not int or document["version"] != 1 or
                document["provider"] != self.provider or
                type(document["adapter"]) is not int or document["adapter"] != self.adapter or
                not isinstance(provider_id, str) or path != self.game_path(provider_id) or
                isinstance(platform_id, bool) or not isinstance(platform_id, int) or
                platform_id <= 0):
            raise MetadataError(f"corrupt provider cache entry: {path.name}")
        _validate_match(document["metadata"], provider_id, document["artwork"],
                        f"corrupt provider cache entry {path.name}")
        if "rating" in document["metadata"]:
            raise MetadataError(f"corrupt provider cache entry: {path.name}")
        artwork = document["artwork"]
        if artwork is not None:
            self.blobs.blob_path(str(artwork["blob"]), require=True)
        return dict(document)

    def read_game(self, provider_id: str) -> Optional[Dict[str, object]]:
        path = self.game_path(provider_id)
        document = _read_cache_json(path)
        return None if document is None else self._validate_game(document, path)

    def validate_game_data(self, provider_id: str, platform_id: object,
                           metadata: object) -> None:
        self.game_path(provider_id)
        if type(platform_id) is not int or platform_id <= 0:
            raise MetadataError("TheGamesDB provider platform is invalid")
        _validate_match(metadata, provider_id, None, "TheGamesDB provider")
        if isinstance(metadata, dict) and "rating" in metadata:
            raise MetadataError("TheGamesDB provider metadata is invalid")

    def write_game(self, provider_id: str, platform_id: int,
                   metadata: Mapping[str, object], artwork: object,
                   refresh: bool = False) -> Dict[str, object]:
        path = self.game_path(provider_id)
        document: Dict[str, object] = {
            "version": 1, "provider": self.provider, "adapter": self.adapter,
            "provider_id": provider_id, "platform_id": platform_id,
            "metadata": dict(metadata), "artwork": artwork,
        }
        self._validate_game(document, path)
        _write_cache_json(path, document, refresh)
        cached = self.read_game(provider_id)
        if cached is None:
            raise MetadataError("provider game cache write did not create an entry")
        return cached
