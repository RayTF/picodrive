"""Deterministic local artwork conversion using optional Pillow."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from .identity import MetadataError

ARTWORK_SIZE = (122, 84)
MAX_ARTWORK_BYTES = 256 * 1024
MAX_ARTWORK_SOURCE_BYTES = 16 * 1024 * 1024
MAX_ARTWORK_PIXELS = 16 * 1024 * 1024


def convert_artwork(path: Path) -> bytes:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as error:
        raise MetadataError("Pillow is required when artwork overrides are used") from error

    try:
        if path.stat().st_size > MAX_ARTWORK_SOURCE_BYTES:
            raise MetadataError(f"artwork source exceeds 16 MiB: {path}")
        with Image.open(path) as source:
            if source.format not in {"PNG", "JPEG"}:
                raise MetadataError(f"artwork must be PNG or JPEG: {path}")
            if getattr(source, "n_frames", 1) != 1:
                raise MetadataError(f"animated or multiframe artwork is unsupported: {path}")
            if source.width * source.height > MAX_ARTWORK_PIXELS:
                raise MetadataError(f"artwork dimensions exceed safety limits: {path}")
            source.seek(0)
            image = ImageOps.exif_transpose(source)
            if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
                image = Image.alpha_composite(background, rgba).convert("RGB")
            else:
                image = image.convert("RGB")
            image = ImageOps.fit(image, ARTWORK_SIZE, method=Image.Resampling.LANCZOS,
                                 centering=(0.5, 0.5))
            output = BytesIO()
            image.save(output, format="PNG", optimize=False, compress_level=9, interlace=0)
    except MetadataError:
        raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise MetadataError(f"cannot process artwork {path}: {error}") from error

    data = output.getvalue()
    if len(data) > MAX_ARTWORK_BYTES:
        raise MetadataError(f"converted artwork exceeds 256 KiB: {path}")
    try:
        with Image.open(BytesIO(data)) as verification:
            if verification.format != "PNG" or verification.mode != "RGB" or verification.size != ARTWORK_SIZE:
                raise MetadataError(f"converted artwork verification failed: {path}")
            if getattr(verification, "n_frames", 1) != 1:
                raise MetadataError(f"converted artwork is unexpectedly multiframe: {path}")
            verification.load()
    except OSError as error:
        raise MetadataError(f"converted artwork verification failed: {path}") from error
    return data
