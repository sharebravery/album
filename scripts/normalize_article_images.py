#!/usr/bin/env python3
"""Normalize Pulse Article image assets to baseline RGB JPEG files."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageOps

JPEG_QUALITY = 92


def flatten_to_rgb(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if getattr(image, "is_animated", False):
        image.seek(0)

    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background

    return image.convert("RGB")


def normalize_file(source: Path, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".normalize")
    temporary.unlink(missing_ok=True)

    try:
        with Image.open(source) as opened:
            rgb = flatten_to_rgb(opened)
            rgb.save(
                temporary,
                format="JPEG",
                quality=JPEG_QUALITY,
                optimize=True,
                progressive=False,
                subsampling=0,
            )
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    if source != destination:
        source.unlink(missing_ok=True)
    return destination.stat().st_size
