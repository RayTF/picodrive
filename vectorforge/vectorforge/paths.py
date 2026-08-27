"""Application data locations and directory initialization."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


def default_data_root() -> Path:
    override = os.environ.get("VECTORFORGE_DATA")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return Path(base or Path.home()) / "VectorForge"
    base = os.environ.get("XDG_DATA_HOME")
    return Path(base).expanduser() / "VectorForge" if base else Path.home() / ".local" / "share" / "VectorForge"


@dataclass(frozen=True)
class AppPaths:
    """Writable application paths.

    Keeping these paths in one value makes the GUI, wizard, and build services
    independent of the current working directory or bundled executable path.
    """

    root: Path
    config_dir: Optional[Path] = None
    library_dir: Optional[Path] = None
    cache_dir: Optional[Path] = None
    temp_dir: Optional[Path] = None
    projects_dir: Optional[Path] = None

    @property
    def config(self) -> Path:
        return self.config_dir or self.root / "config"

    @property
    def library(self) -> Path:
        return self.library_dir or self.root / "library"

    @property
    def cache(self) -> Path:
        return self.cache_dir or self.root / "cache"

    @property
    def temp(self) -> Path:
        return self.temp_dir or self.root / "temp"

    @property
    def projects(self) -> Path:
        return self.projects_dir or self.root / "projects"

    @classmethod
    def default(cls) -> "AppPaths":
        return cls(default_data_root())

    @classmethod
    def from_settings(cls, root: Path, settings: Mapping[str, Any]) -> "AppPaths":
        values = settings.get("paths", {})
        if not isinstance(values, Mapping):
            return cls(root)

        def value(name: str) -> Optional[Path]:
            raw = values.get(name)
            return Path(str(raw)).expanduser() if raw else None

        return cls(root, value("config"), value("library"), value("cache"),
                   value("temp"), value("projects"))

    def ensure(self) -> "AppPaths":
        for path in (self.root, self.config, self.library, self.cache, self.temp, self.projects):
            path.mkdir(parents=True, exist_ok=True)
        return self
