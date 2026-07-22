#!/bin/bash
#
# VectorDrive release build script
# Builds all 3 theme variants (SUGC, SMDUC, VectorDrive) for PSP
#
# usage: release.sh <version>
#
# expects pspdev SDK toolchain:
#   docker.io/pspdev/pspdev

trap "exit" ERR

rel=$1
if [ -z "$rel" ]; then
	echo "usage: release.sh <version>"
	exit 1
fi

mkdir -p release-$rel

echo "=== VectorDrive release build v$rel ==="
echo ""

# Pull the PSP toolchain
docker pull --platform=linux/amd64 pspdev/pspdev

for theme in sugc smduc vectordrive; do
	echo "=== Building theme: $theme ==="

	docker run --platform=linux/amd64 -i -v"$PWD":/home/picodrive -w/home/picodrive --rm pspdev/pspdev sh <<EOF
apk add git gcc g++ zip make &&
export CROSS_COMPILE=psp- &&
git config --global --add safe.directory /home/picodrive &&
./configure --platform=psp &&
make clean &&
make THEME=$theme -j2 all
EOF

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

	# Create zip for this theme
	cd "release-$rel"
	zip -9 -r "${pkg_name}_${rel}.zip" "$pkg_name"
	cd ..
	rm -rf "release-$rel/$pkg_name"

	echo "=== $theme done ==="
	echo ""
done

echo "=== All builds complete ==="
echo "Output files in release-$rel/"
ls -la release-$rel/
