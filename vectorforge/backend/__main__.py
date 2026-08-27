"""Command-line interface for the VectorForge backend."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from .identity import MetadataError
from .enrich import enrich
from .install import THEMES, build_install
from .manifest import generate
from .providers.screenscraper import ScreenScraperCredentials
from .rom_scan import scan_mappings, write_scan
from .source_archive import build_source_archive


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="scan ROM sources into deterministic JSON")
    scan.add_argument("--input", action="append", nargs=2, required=True,
                      metavar=("SOURCE", "PSP_DEST"))
    scan.add_argument("--output", required=True, type=Path, metavar="SCAN_JSON")
    scan.add_argument("--force", action="store_true")

    generate_parser = subparsers.add_parser("generate", help="generate games.yaml and artwork")
    generate_parser.add_argument("--scan", required=True, type=Path, metavar="SCAN_JSON")
    generate_parser.add_argument("--overrides", type=Path, metavar="OVERRIDES_JSON")
    generate_parser.add_argument("--output-dir", required=True, type=Path, metavar="DIR")
    generate_parser.add_argument("--provider", action="append",
                                 choices=("screenscraper", "thegamesdb"))
    generate_parser.add_argument("--provider-cache", type=Path, metavar="DIR")
    generate_parser.add_argument("--matches", type=Path, metavar="MATCHES_JSON")
    generate_parser.add_argument("--force", action="store_true")

    enrich_parser = subparsers.add_parser("enrich", help="populate a provider cache")
    enrich_parser.add_argument("--scan", required=True, type=Path, metavar="SCAN_JSON")
    enrich_parser.add_argument("--provider", required=True,
                               choices=("screenscraper", "thegamesdb"))
    enrich_parser.add_argument("--cache-dir", required=True, type=Path, metavar="DIR")
    enrich_parser.add_argument("--report", required=True, type=Path, metavar="REPORT")
    mode = enrich_parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--refresh", action="store_true")
    enrich_parser.add_argument("--force", action="store_true")
    enrich_parser.add_argument("--screenscraper-dev-id")
    enrich_parser.add_argument("--screenscraper-dev-password")
    enrich_parser.add_argument("--screenscraper-user")
    enrich_parser.add_argument("--screenscraper-password")
    enrich_parser.add_argument("--screenscraper-soft-name")
    enrich_parser.add_argument("--thegamesdb-api-key")
    enrich_parser.add_argument("--matches", type=Path, metavar="MATCHES_JSON")

    install_parser = subparsers.add_parser("install", help="build a validated PSP install ZIP")
    install_parser.add_argument("--eboot", required=True, type=Path, metavar="EBOOT.PBP")
    install_parser.add_argument("--theme", required=True, choices=THEMES)
    install_parser.add_argument("--source-root", type=Path, metavar="DIR")
    install_parser.add_argument("--metadata-dir", type=Path, metavar="DIR")
    install_parser.add_argument("--output", required=True, type=Path, metavar="ZIP")
    install_parser.add_argument("--with-roms", action="store_true")
    install_parser.add_argument("--input", action="append", nargs=2, default=[],
                                metavar=("SOURCE", "PSP_DEST"))
    install_parser.add_argument("--force", action="store_true")

    source_parser = subparsers.add_parser(
        "source-archive", help="build a complete deterministic working-source ZIP"
    )
    source_parser.add_argument("--source-root", required=True, type=Path, metavar="DIR")
    source_parser.add_argument("--version", required=True)
    source_parser.add_argument("--output", required=True, type=Path, metavar="ZIP")
    return parser


def _credentials(arguments: argparse.Namespace) -> ScreenScraperCredentials:
    def value(name: str, environment: str) -> Optional[str]:
        return getattr(arguments, name) or os.environ.get(environment)

    return ScreenScraperCredentials(
        dev_id=value("screenscraper_dev_id", "SCREENSCRAPER_DEV_ID") or "",
        dev_password=value("screenscraper_dev_password", "SCREENSCRAPER_DEV_PASSWORD") or "",
        soft_name=value("screenscraper_soft_name", "SCREENSCRAPER_SOFT_NAME") or "",
        user=value("screenscraper_user", "SCREENSCRAPER_USER"),
        password=value("screenscraper_password", "SCREENSCRAPER_PASSWORD"),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "scan":
            document = scan_mappings(arguments.input)
            write_scan(document, arguments.output, arguments.force)
            count = len(document["games"])
            print(f"scan: {count} record(s)")
        elif arguments.command == "generate":
            count, artwork_count = generate(
                arguments.scan,
                arguments.output_dir,
                arguments.overrides,
                arguments.force,
                arguments.provider,
                arguments.provider_cache,
                arguments.matches,
            )
            print(f"generate: {count} game(s), {artwork_count} artwork file(s)")
        elif arguments.command == "enrich":
            document = enrich(
                arguments.scan,
                arguments.provider,
                arguments.cache_dir,
                arguments.report,
                arguments.offline,
                arguments.refresh,
                arguments.force,
                (None if arguments.offline or arguments.provider != "screenscraper"
                 else _credentials(arguments)),
                None,
                arguments.matches,
                (arguments.thegamesdb_api_key or os.environ.get("THEGAMESDB_API_KEY"))
                if not arguments.offline else None,
            )
            summary = document["summary"]
            print(f"enrich: {summary['processed']} record(s), {summary['matched']} matched")
        elif arguments.command == "install":
            result = build_install(
                arguments.eboot,
                arguments.theme,
                arguments.output,
                arguments.source_root,
                arguments.metadata_dir,
                arguments.with_roms,
                arguments.input,
                arguments.force,
            )
            print(f"install: {result.files} file(s), {result.roms} ROM(s), "
                  f"{result.artwork} artwork file(s)")
        else:
            count = build_source_archive(
                arguments.source_root, arguments.output, arguments.version
            )
            print(f"source-archive: {count} working source file(s)")
    except (MetadataError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
