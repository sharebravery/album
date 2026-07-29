#!/usr/bin/env python3
"""Normalize Pulse Article image assets to baseline RGB JPEG files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = ROOT / ".album-work"
SUMMARY_PATH = WORK_DIR / "summary.json"
SOURCE_PATHS_PATH = WORK_DIR / "normalized-source-paths.txt"
ARTICLE_PREFIX = "pulse/article/"
JPEG_QUALITY = 92


def fail(message: str) -> None:
    raise ValueError(message)


def normalized_target(target: str) -> str:
    path = Path(target)
    return path.with_suffix(".jpg").as_posix()


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
    if source != destination:
        source.unlink(missing_ok=True)
    return destination.stat().st_size


def normalize_summary(summary: dict[str, Any]) -> tuple[int, list[str]]:
    normalized = 0
    source_paths: list[str] = []
    for request in summary.get("requests", []):
        for image in request.get("images", []):
            if image.get("status") != "completed":
                continue
            target = image.get("targetPath")
            if not isinstance(target, str) or not target.startswith(ARTICLE_PREFIX):
                continue

            source = ROOT / target
            destination_target = normalized_target(target)
            destination = ROOT / destination_target
            size = normalize_file(source, destination)
            if target != destination_target:
                source_paths.append(target)
            image["targetPath"] = destination_target
            image["contentType"] = "image/jpeg"
            image["bytes"] = size
            normalized += 1
    return normalized, source_paths


def main() -> int:
    if not SUMMARY_PATH.exists():
        fail("missing preparation summary")
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    normalized, source_paths = normalize_summary(summary)
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if source_paths:
        SOURCE_PATHS_PATH.write_text(
            "\n".join(dict.fromkeys(source_paths)) + "\n",
            encoding="utf-8",
        )
    else:
        SOURCE_PATHS_PATH.unlink(missing_ok=True)
    print(f"Normalized {normalized} Article image asset(s) to baseline RGB JPEG.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
