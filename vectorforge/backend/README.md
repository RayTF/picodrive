# VectorForge Backend

The host-side tooling scans ROMs, optionally enriches them through a reusable provider cache, and generates the constrained metadata files read by VectorDrive. Run commands from the `source/` directory with Python 3.

## Commands

Scan one or more source files or directories. Directory contents are mapped below the supplied application-relative PSP destination; a file maps to the complete destination.

```sh
python3 -m backend scan \
  --input ./my-roms rom \
  --input ./bonus.gg rom_extra/bonus.gg \
  --output scan.json
```

Generate `games.yaml` and optional artwork below an output directory:

```sh
python3 -m backend generate \
  --scan scan.json \
  --overrides overrides.json \
  --output-dir build
```

ScreenScraper enrichment is a separate online step. Obtain API approval and developer credentials from ScreenScraper before using it:

```sh
export SCREENSCRAPER_DEV_ID='developer-id'
export SCREENSCRAPER_DEV_PASSWORD='developer-password'
export SCREENSCRAPER_SOFT_NAME='VectorDrive metadata'

python3 -m backend enrich \
  --scan scan.json \
  --provider screenscraper \
  --cache-dir cache \
  --report enrich-report.json
```

`SCREENSCRAPER_USER` and `SCREENSCRAPER_PASSWORD` optionally supply a paired ScreenScraper account. Every credential also has a matching command-line flag, but environment variables are recommended because command-line arguments may be visible to other local processes and retained in shell history. Developer ID, developer password, and software name are required online. Credentials and credential-bearing URLs are not written to cache entries or reports.

TheGamesDB uses a strict title-search and manual-confirmation workflow. Set an API key, run enrichment without `--matches`, and inspect the deterministic report. A unique exact title is reported as `confirmation_required`; multiple exact titles or a bounded/truncated search are `ambiguous`. Reports identify whether the exact match came from `game_title` or an alternate. Nothing from a search enters generated metadata until it is confirmed.

```sh
export THEGAMESDB_API_KEY='api-key'

python3 -m backend enrich \
  --scan scan.json \
  --provider thegamesdb \
  --cache-dir cache \
  --report thegamesdb-search.json
```

Create a strict version 1 matches file from reviewed candidates. Each entry selects exactly one stable ID or runtime ROM path. `provider_id` is a positive decimal string; `null` explicitly rejects the ROM. Directly selected IDs are allowed and are still checked against the ROM's compatible platform when fetched.

```json
{
  "version": 1,
  "provider": "thegamesdb",
  "games": [
    {
      "rom": "rom/Sonic.bin",
      "provider_id": "53"
    },
    {
      "id": "sha1:0123456789abcdef0123456789abcdef01234567",
      "provider_id": null
    }
  ]
}
```

Fetch and cache confirmed records with the same file:

```sh
python3 -m backend enrich \
  --scan scan.json \
  --provider thegamesdb \
  --matches matches.json \
  --cache-dir cache \
  --report thegamesdb-confirmed.json
```

`--thegamesdb-api-key` is also available, but the environment is safer than command-line history. TheGamesDB keys and API pagination URLs are never stored in reports or cache records. The tool does not use TheGamesDB hash search.

Enrichment can be repeated without network access or credentials. A cache miss and a definitive unmatched result are successful report outcomes:

```sh
python3 -m backend enrich \
  --scan scan.json \
  --provider screenscraper \
  --cache-dir cache \
  --report offline-report.json \
  --offline
```

Generate from the cache. Generation is always offline:

```sh
python3 -m backend generate \
  --scan scan.json \
  --provider screenscraper \
  --provider thegamesdb \
  --provider-cache cache \
  --matches matches.json \
  --overrides overrides.json \
  --output-dir build
```

Provider order on the command line does not change results. ScreenScraper always has first priority per metadata field and for artwork; TheGamesDB fills only missing fields or absent artwork. Duplicate providers are rejected. Generation is cache-only, and manual overrides are applied last.

Build a deterministic no-ROM PSP install. `--source-root` defaults to the inferred `source/` checkout, and `--metadata-dir` defaults to that source root:

```sh
python3 -m backend install \
  --eboot EBOOT.PBP \
  --theme sugc \
  --metadata-dir build \
  --output VectorDrive-sugc.zip
```

ROMs are never inferred from scan JSON or host directory names. A with-ROM install requires both the explicit mode and at least one source-to-PSP mapping. From the `source/` checkout, SUGC uses `../rom`, SMDUC uses `../rom_eu`, and the shared extra-ROM directory is `../rom_extra`:

```sh
python3 -m backend install \
  --eboot EBOOT.PBP \
  --theme smduc \
  --metadata-dir build \
  --output VectorDrive-smduc.zip \
  --with-roms \
  --input ../rom_eu rom \
  --input ../rom_extra rom_extra
```

For SUGC, replace `../rom_eu` with `../rom`. VectorDrive has no implicit region and requires the caller to choose every source explicitly, for example `--input ../rom rom`. The PSP destination must start with `rom` or `rom_extra`; `rom_eu` is never a runtime destination. A source file maps to a complete destination filename, while a source directory is copied below its destination.

The install contains only `COPYING`, `EBOOT.PBP`, `game_def.cfg`, the runtime-used shared PSP skin assets, all three selected theme backgrounds, and validated optional metadata. SMDUC selects `games-smduc.yaml` and `metadata/attribution-smduc.json`; other themes select `games.yaml` and `metadata/attribution.json`. The selected files are always named `games.yaml` and `metadata/attribution.json` inside the install. Only artwork referenced by the selected manifest is included; attribution is included only when a manifest exists. With-ROM builds require every manifest ROM path to be present in the explicit mappings. Archives use a single `VectorDrive-THEME/` top-level directory, stored entries, normalized file metadata, sorted members, CRC validation, and atomic output replacement with `--force`. Determinism means identical install ZIP bytes for identical input bytes; it does not claim that rebuilding `EBOOT.PBP` with changing external packages is reproducible.

`tools/release.sh VERSION [THEME]` pins the PSP SDK container digest, requires initialized recorded submodules, builds every requested theme, synchronizes the directly runnable root `skin/`, and publishes one themed `EBOOT.PBP` per build. It performs no Python-driven packaging; run the metadata installer and source-archive commands explicitly when distribution ZIPs are required. `COPYING` requires modified binary releases to be accompanied by their complete corresponding source. The container is pinned, but external toolchain components can still change the resulting `EBOOT.PBP`. `platform/psp/Makefile rel` performs a clean local build of the requested theme without packaging it.

Commands refuse to replace their managed output files unless `--force` is supplied. Unrelated output files are retained.
Explicit file mappings must keep the same supported extension at the source and PSP destination.

## Overrides

Overrides are strict UTF-8 JSON, version 1. Match exactly one stable ID or runtime ROM path per entry. Provider metadata is applied first, ID overrides apply second to every matching game, and path overrides apply last and win. Manual `null` values clear optional provider metadata or artwork; manual artwork replaces provider artwork. Artwork paths are relative to the override file.

```json
{
  "version": 1,
  "games": [
    {
      "id": "sha1:0123456789abcdef0123456789abcdef01234567",
      "genre": "Platform",
      "publisher": "SEGA"
    },
    {
      "rom": "rom/My Game.bin",
      "title": "My Game",
      "release_year": 1994,
      "players": 2,
      "rating": 85,
      "artwork": "art/My Game.png"
    }
  ]
}
```

Optional metadata and artwork can be cleared with `null`; `exclude` removes a matched game. Generated metadata is printable ASCII and respects the PSP runtime's entry, file, line, path, and field limits.

When provider data is used, generation also writes deterministic `metadata/attribution.json` entries for every contributing provider, including its game ID, source page, and selected provider artwork type/region where applicable. `games.yaml` retains the highest-priority provider that actually contributed. ScreenScraper identifies its contributed content as CC BY-NC-SA 4.0. Users are responsible for checking and following each provider's current API terms, content license, and attribution requirements.