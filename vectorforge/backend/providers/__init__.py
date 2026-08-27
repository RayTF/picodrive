"""Metadata provider registry."""

from __future__ import annotations

from typing import Type

from ..identity import MetadataError
from .base import MetadataProvider
from .screenscraper import ScreenScraperProvider
from .thegamesdb import TheGamesDBProvider

PROVIDERS = {"screenscraper": ScreenScraperProvider, "thegamesdb": TheGamesDBProvider}


def provider_class(name: str) -> Type[MetadataProvider]:
    try:
        return PROVIDERS[name]
    except KeyError as error:
        raise MetadataError(f"unsupported metadata provider: {name}") from error


__all__ = [
    "MetadataProvider", "ScreenScraperProvider", "TheGamesDBProvider", "provider_class",
]
