"""VectorForge command line wizard and automation commands."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from backend.identity import MetadataError
from backend.providers.screenscraper import ScreenScraperCredentials
from backend.rom_scan import SUPPORTED_EXTENSIONS

from .builder import build_zip
from .iso import build_iso
from .library import LibraryStore
from .paths import AppPaths
from .package import PackageReader
from .scrape import scrape_library
from .settings import SettingsStore


def _paths(value: Optional[Path]) -> AppPaths:
    root = value.expanduser() if value else AppPaths.default().root
    base = AppPaths(root)
    try:
        settings = SettingsStore(base.config).load()
    except (OSError, ValueError):
        settings = {}
    paths = AppPaths.from_settings(root, settings)
    return paths.ensure()


def _rom_files(folder: Path) -> Iterable[Path]:
    for path in sorted(folder.rglob("*"), key=lambda item: str(item).casefold()):
        if path.is_file() and not path.is_symlink() and path.suffix.lower().lstrip(".") in SUPPORTED_EXTENSIONS:
            yield path


def _add_inputs(store: LibraryStore, inputs: Sequence[Path], category: str = "main") -> int:
    count = 0
    for source in inputs:
        if source.is_dir():
            candidates = _rom_files(source)
        else:
            candidates = (source,)
        for path in candidates:
            store.add_path(path, category=category)
            count += 1
    return count


def _entered_path(value: str) -> Path:
    """Accept paths pasted with a matching pair of shell-style quotes."""

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return Path(value).expanduser()


def _manual_review(store: LibraryStore) -> None:
    for game in store.list_games():
        print(f"\n{game.id} | {game.rom_path}")
        title = input(f"Title [{game.title}]: ").strip()
        system = input(f"System [{game.system}]: ").strip()
        values = {}
        if title:
            values["title"] = title
        if system:
            values["system"] = system
        if values:
            store.update_metadata(game.id, values)


def _wizard(paths: AppPaths) -> int:
    print("VectorForge CLI Wizard")
    print(f"Library: {paths.library}")
    base_value = input("VectorDrive ZIP: ").strip()
    if not base_value:
        raise MetadataError("a base VectorDrive ZIP is required for building")
    base = _entered_path(base_value)
    reader = PackageReader(base)
    store = LibraryStore(paths.library)
    info, imported = reader.import_into(store)
    print(f"Loaded {info.root}/ ({info.roms} existing ROM(s)); imported {len(imported)} game(s).")
    while True:
        value = input("ROM folder or file (blank when finished): ").strip()
        if not value:
            break
        category = input("ROM category [main/extra] (main): ").strip().casefold() or "main"
        if category not in {"main", "extra"}:
            raise MetadataError("ROM category must be main or extra")
        added = _add_inputs(store, [_entered_path(value)], category)
        print(f"Added {added} ROM(s).")
    if input("Run automatic metadata scraping now? [y/N]: ").strip().lower() == "y":
        dev_id = os.environ.get("SCREENSCRAPER_DEV_ID", "")
        dev_password = os.environ.get("SCREENSCRAPER_DEV_PASSWORD", "")
        soft_name = os.environ.get("SCREENSCRAPER_SOFT_NAME", "")
        user = os.environ.get("SCREENSCRAPER_USER", "")
        password = os.environ.get("SCREENSCRAPER_PASSWORD", "")
        if not dev_id:
            dev_id = input("ScreenScraper developer ID: ").strip()
        if not dev_password:
            dev_password = getpass.getpass("ScreenScraper developer password: ").strip()
        if not soft_name:
            soft_name = input("ScreenScraper software name [VectorForge]: ").strip() or "VectorForge"
        if not dev_id or not dev_password:
            raise MetadataError("ScreenScraper developer ID and developer password are required")
        credentials = ScreenScraperCredentials(
            dev_id, dev_password, soft_name, user or None, password or None,
        )
        providers = ["screenscraper"]
        if os.environ.get("THEGAMESDB_API_KEY"):
            providers.append("thegamesdb")
        result = scrape_library(
            store, paths, providers=providers, screenscraper=credentials,
            thegamesdb_api_key=os.environ.get("THEGAMESDB_API_KEY"), progress=print,
        )
        print(f"Scraped {result.matched} game(s); review ambiguous provider matches separately.")
    if input("Edit metadata manually now? [y/N]: ").strip().lower() == "y":
        _manual_review(store)
    output_value = input("Output ZIP path: ").strip()
    if not output_value:
        raise MetadataError("an output ZIP path is required")
    result = build_zip(base, _entered_path(output_value), store)
    print(f"Built {result.output} ({result.roms} ROM(s), {result.artwork} artwork file(s)).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vectorforge", description="Build custom VectorDrive packages")
    parser.add_argument("--data-root", type=Path, help="application data root")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("gui", help="launch the PySide6 GUI")

    import_parser = subparsers.add_parser("import", help="import a VectorDrive ZIP and its ROMs")
    import_parser.add_argument("base", type=Path)

    add_parser = subparsers.add_parser("add", help="add ROM files or folders to the library")
    add_parser.add_argument("inputs", nargs="+", type=Path)
    add_parser.add_argument("--category", choices=("main", "extra"), default="main")

    build_parser = subparsers.add_parser("build", help="build a deterministic VectorDrive ZIP")
    build_parser.add_argument("--base", required=True, type=Path)
    build_parser.add_argument("--output", required=True, type=Path)
    build_parser.add_argument("--iso", type=Path, help="also build an ISO at this path")
    build_parser.add_argument("--game", action="append", dest="games", help="stable SHA-1 game ID to include")
    build_parser.add_argument("--force", action="store_true")

    scrape_parser = subparsers.add_parser("scrape", help="scrape the current library")
    scrape_parser.add_argument("--provider", action="append", choices=("screenscraper", "thegamesdb"))
    scrape_parser.add_argument("--offline", action="store_true")
    scrape_parser.add_argument("--refresh", action="store_true")
    scrape_parser.add_argument("--matches", type=Path)
    scrape_parser.add_argument("--screenscraper-dev-id")
    scrape_parser.add_argument("--screenscraper-dev-password")
    scrape_parser.add_argument("--screenscraper-soft-name", default="VectorForge")
    scrape_parser.add_argument("--screenscraper-user")
    scrape_parser.add_argument("--screenscraper-password")
    scrape_parser.add_argument("--thegamesdb-api-key")

    edit_parser = subparsers.add_parser("edit", help="edit one library game's metadata")
    edit_parser.add_argument("--id", required=True, help="stable SHA-1 game ID")
    for field in ("title", "system", "genre", "information", "region", "publisher", "developer"):
        edit_parser.add_argument(f"--{field}")
    edit_parser.add_argument("--release-year", type=int)
    edit_parser.add_argument("--players", type=int)
    edit_parser.add_argument("--rating", type=int)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    paths = _paths(arguments.data_root)
    try:
        if arguments.command is None:
            return _wizard(paths)
        if arguments.command == "gui":
            from .gui import run_gui
            return run_gui(paths)
        store = LibraryStore(paths.library)
        if arguments.command == "import":
            info, imported = PackageReader(arguments.base).import_into(store)
            print(f"Imported {len(imported)} game(s) from {info.root}/ into {paths.library}")
            return 0
        if arguments.command == "add":
            count = _add_inputs(store, arguments.inputs, arguments.category)
            print(f"Added {count} ROM(s) to {paths.library}")
            return 0
        if arguments.command == "scrape":
            providers = arguments.provider or ["screenscraper"]
            credentials = ScreenScraperCredentials(
                arguments.screenscraper_dev_id or os.environ.get("SCREENSCRAPER_DEV_ID", ""),
                arguments.screenscraper_dev_password or os.environ.get("SCREENSCRAPER_DEV_PASSWORD", ""),
                arguments.screenscraper_soft_name or os.environ.get("SCREENSCRAPER_SOFT_NAME", "VectorForge"),
                arguments.screenscraper_user or os.environ.get("SCREENSCRAPER_USER"),
                arguments.screenscraper_password or os.environ.get("SCREENSCRAPER_PASSWORD"),
            )
            result = scrape_library(
                store, paths, providers=providers,
                screenscraper=credentials,
                thegamesdb_api_key=arguments.thegamesdb_api_key or os.environ.get("THEGAMESDB_API_KEY"),
                matches=arguments.matches,
                offline=arguments.offline,
                refresh=arguments.refresh,
                progress=print,
            )
            print(f"Scraped {result.matched} of {result.scanned} game(s); {result.artwork} artwork file(s)")
            return 0
        if arguments.command == "edit":
            values = {
                key.replace("_", "-"): value
                for key, value in vars(arguments).items()
                if key in {"title", "system", "genre", "information", "region", "publisher", "developer",
                           "release_year", "players", "rating"} and value is not None
            }
            values = {key.replace("-", "_"): value for key, value in values.items()}
            game = store.update_metadata(arguments.id, values)
            print(f"Updated {game.title} ({game.id})")
            return 0
        result = build_zip(
            arguments.base, arguments.output, store,
            stable_ids=arguments.games, force=arguments.force,
        )
        print(f"Built {result.output}: {result.files} file(s), {result.roms} ROM(s)")
        if arguments.iso:
            iso_result = build_iso(
                arguments.base, arguments.iso, store,
                stable_ids=arguments.games, force=arguments.force,
            )
            print(f"Built {iso_result.output}")
        return 0
    except (MetadataError, OSError, RuntimeError, ValueError) as error:
        print(f"vectorforge: error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
