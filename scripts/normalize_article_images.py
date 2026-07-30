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


def normalize_summary(summary: dict[str, Any]) -> tuple[int, int]:
    normalized = 0
    failed = 0

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

            try:
                size = normalize_file(source, destination)
            except Exception as exc:
                source.unlink(missing_ok=True)
                image["status"] = "failed"
                image["error"] = f"JPEG normalization failed: {exc}"
                image.pop("contentType", None)
                image.pop("bytes", None)
                failed += 1
                continue

            image["targetPath"] = destination_target
            image["contentType"] = "image/jpeg"
            image["bytes"] = size
            normalized += 1

    return normalized, failed


def main() -> int:
    if not SUMMARY_PATH.exists():
        fail("missing preparation summary")

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    normalized, failed = normalize_summary(summary)
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Normalized {normalized} Article image asset(s) to baseline RGB JPEG; "
        f"{failed} image(s) failed normalization."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
