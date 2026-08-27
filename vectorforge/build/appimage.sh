#!/usr/bin/env sh
set -eu

FORGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$FORGE_ROOT"

python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller
pyinstaller --noconfirm --clean --windowed \
  --name VectorForge \
  --specpath build \
  --icon assets/icon.png \
  --add-data "../assets:assets" \
  --paths . \
  vectorforge/gui_entry.py

APPDIR="$FORGE_ROOT/build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a dist/VectorForge/. "$APPDIR/usr/bin/"
cp assets/icon.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/vectorforge.png"
cp build/vectorforge.desktop "$APPDIR/usr/share/applications/vectorforge.desktop"
cp assets/icon.png "$APPDIR/vectorforge.png"
cp build/vectorforge.desktop "$APPDIR/vectorforge.desktop"
cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env sh
exec "$(dirname "$0")/usr/bin/VectorForge" "$@"
EOF
chmod +x "$APPDIR/AppRun"

if ! command -v appimagetool >/dev/null 2>&1; then
    printf '%s\n' 'appimagetool is required to finish the AppImage build.' >&2
    exit 1
fi
appimagetool "$APPDIR" "dist/VectorForge.AppImage"
