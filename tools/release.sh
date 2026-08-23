#!/bin/bash
#
# VectorDrive release build script
# Builds all 3 theme variants (SUGC, SMDUC, VectorDrive) for PSP
#
# usage: release.sh <version> <theme_optional>
#
# expects pspdev SDK toolchain:
#   docker.io/pspdev/pspdev

set -euo pipefail

rel=$1
image='pspdev/pspdev@latest'
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_root=$(dirname -- "$script_dir")

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
	printf 'usage: %s VERSION [sugc|smduc|vectordrive]\n' "$0" >&2
	exit 1
fi

version=$1
case "$version" in
	''|*[!A-Za-z0-9._-]*|.*|-*)
		printf 'error: unsafe release version: %s\n' "$version" >&2
		exit 1
		;;
esac

# Pull the PSP toolchain
docker pull --platform=linux/amd64 pspdev/pspdev
if [ "$#" -eq 2 ]; then
	case "$2" in
		sugc|smduc|vectordrive) themes=$2 ;;
		*)
			printf 'error: unsupported theme: %s\n' "$2" >&2
			exit 1
			;;
	esac
else
	themes='sugc smduc vectordrive'
fi

release_dir="$source_root/release-$version"
if [ -e "$release_dir" ]; then
	printf 'error: release directory already exists: %s\n' "$release_dir" >&2
	exit 1
fi
if git -C "$source_root" submodule status --recursive | grep -Eq '^[+-U]'; then
	printf 'error: release builds require initialized recorded submodules\n' >&2
	exit 1
fi

staging=$(mktemp -d "$source_root/.release-$version.XXXXXX")
trap 'rm -rf "$staging"' EXIT

printf '=== VectorDrive Release Build %s ===\n\n' "$version"

for theme in $themes; do
	printf '=== Building Theme: %s ===\n' "$theme"
	docker run --platform=linux/amd64 -i -v"$PWD":/home/picodrive -w/home/picodrive --rm pspdev/pspdev sh <<EOF
apk add git gcc g++ zip make &&
export CROSS_COMPILE=psp- &&
git config --global --add safe.directory /home/picodrive &&
./configure --platform=psp &&
make clean &&
make THEME=$theme -j2 all
EOF
	# Keep the directly runnable EBOOT paired with the selected theme.
	cp "platform/psp/themes/$theme/background.png" "skin/background.png"
	cp "platform/psp/themes/$theme/background_selector.png" "skin/background_selector.png"
	cp "platform/psp/themes/$theme/background_title.png" "skin/background_title.png"

	# Package the result
	pkg_name="VectorDrive-${theme}"
	mkdir -p "release-$rel/$pkg_name"

	# Copy EBOOT and config files
	cp EBOOT.PBP "release-$rel/$pkg_name/"
	cp platform/game_def.cfg "release-$rel/$pkg_name/"

	# Copy skin directory (shared assets + theme-specific backgrounds)
	mkdir -p "release-$rel/$pkg_name/skin"
	cp platform/psp/skin/* "release-$rel/$pkg_name/skin/"
	cp "platform/psp/themes/$theme/background.png" "release-$rel/$pkg_name/skin/"
	cp "platform/psp/themes/$theme/background_selector.png" "release-$rel/$pkg_name/skin/"
	cp "platform/psp/themes/$theme/background_title.png" "release-$rel/$pkg_name/skin/"

	# Create zip for this theme
	cd "release-$rel"
	zip -9 -r "${pkg_name}_${rel}.zip" "$pkg_name"
	cd ..
	rm -rf "release-$rel/$pkg_name"

	echo "=== $theme done ==="
	echo ""
done

mv "$staging" "$release_dir"
trap - EXIT
printf '=== All builds complete ===\nOutput files in %s/\n' "$release_dir"