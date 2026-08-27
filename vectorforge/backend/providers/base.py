"""Generic metadata provider interfaces and scan lookup candidates."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Dict, List, Mapping, Optional

from ..identity import MetadataError, ProviderOperationalError

HASH_LENGTHS = {"crc32": 8, "md5": 32, "sha1": 40}


class MetadataProvider:
    name = ""
    adapter_version = 1

    @classmethod
    def system_id(cls, system: str) -> Optional[int]:
        return None

    def lookup(self, candidate: Mapping[str, object]) -> Dict[str, object]:
        raise NotImplementedError

    def download_artwork(self, media: Mapping[str, object]) -> bytes:
        raise NotImplementedError


def _hash_set(value: object, label: str) -> Dict[str, object]:
    if not isinstance(value, dict):
        raise MetadataError(f"scan {label} hashes are invalid")
    size = value.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise MetadataError(f"scan {label} size is invalid")
    result: Dict[str, object] = {"size": size}
    for name, length in HASH_LENGTHS.items():
        digest = value.get(name)
        if not isinstance(digest, str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", digest):
            raise MetadataError(f"scan {label} {name} is invalid")
        result[name] = digest
    return result


def lookup_candidates(game: Mapping[str, object]) -> List[Dict[str, object]]:
    """Derive ordered, internally consistent provider lookup identities."""
    rom = game.get("rom")
    system = game.get("system")
    if not isinstance(rom, str) or not isinstance(system, str):
        raise MetadataError("scan game cannot be used for provider lookup")
    runtime_name = PurePosixPath(rom).name
    candidates: List[Dict[str, object]] = []

    def add(basis: str, filename: str, hashes: object) -> None:
        values = _hash_set(hashes, basis)
        candidate = {
            "basis": basis,
            "filename": filename,
            "system": system,
            **values,
        }
        identity = (system, values["size"], values["crc32"], values["md5"], values["sha1"])
        if not any(item["_identity"] == identity for item in candidates):
            candidate["_identity"] = identity
            candidates.append(candidate)

    add("raw", runtime_name, game.get("raw"))
    archive = game.get("archive")
    member_name: Optional[str] = None
    if archive is not None:
        if not isinstance(archive, dict) or not isinstance(archive.get("selected_member"), str):
            raise MetadataError("scan ZIP archive details are invalid")
        member_name = str(archive["selected_member"]).replace("\\", "/").rsplit("/", 1)[-1]
        if not member_name:
            member_name = runtime_name
        add("zip-member", member_name, archive.get("member"))
    canonical = game.get("canonical")
    if canonical is not None:
        add("canonical", member_name or runtime_name, canonical)

    for candidate in candidates:
        del candidate["_identity"]
    return candidates
