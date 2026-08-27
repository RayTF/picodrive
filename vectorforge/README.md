# VectorForge

VectorForge builds custom VectorDrive ZIP and PSP ISO packages.

## Direct Python

From this directory:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 main.py
```

The CLI and GUI is also available as:

```sh
python3 -m vectorforge
python3 -m vectorforge gui
```

## CLI Examples

```sh
python3 -m vectorforge import VectorDrive.zip
python3 -m vectorforge add ~/ROMs
python3 -m vectorforge build \
  --base zips/NoROM/VectorDrive.zip \
  --output VectorDrive-custom.zip \
  --iso VectorDrive-custom.iso

python3 -m vectorforge scrape --offline
python3 -m vectorforge edit --id sha1:... --title "My Title"
```

The installed console script is `vectorforge` when the project is installed
with `pip install -e .`.

## Distribution

- `build/windows.ps1` creates the Windows GUI bundle.
- `build/appimage.sh` creates the Linux AppImage when `appimagetool` is available.
