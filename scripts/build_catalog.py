#!/usr/bin/env python3
"""Build a deterministic reusable image catalog from completed Album results."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
CATALOG_PATH = ROOT / "catalog" / "assets.json"


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def keywords_for(*values: str) -> list[str]:
    text = " ".join(value for value in values if value).lower()
    tokens = re.findall(r"[a-z0-9][a-z0-9._+-]*|[\u4e00-\u9fff]{2,}", text)
    return sorted(set(tokens))


def main() -> int:
    assets_by_path: dict[str, dict[str, Any]] = {}

    for result_path in sorted(RESULTS_DIR.glob("*.json")) if RESULTS_DIR.exists() else []:
        result = load_json(result_path)
        if not result:
            continue

        request_id = str(result.get("requestId") or result_path.stem)
        asset_commit = result.get("assetCommit")
        images = result.get("images")
        if not isinstance(images, list):
            continue

        for index, image in enumerate(images):
            if not isinstance(image, dict) or image.get("status") != "completed":
                continue
            target_path = image.get("targetPath")
            if not isinstance(target_path, str) or not target_path:
                continue

            alt = str(image.get("alt") or "")
            source_page_url = str(image.get("sourcePageUrl") or "")
            download_url = str(image.get("downloadUrl") or "")
            asset = {
                "id": f"{request_id}:{index}",
                "requestId": request_id,
                "targetPath": target_path,
                "alt": alt,
                "keywords": keywords_for(request_id, target_path, alt, source_page_url),
                "sourcePageUrl": source_page_url,
                "downloadUrl": download_url,
                "rawUrl": image.get("rawUrl"),
                "cdnUrl": image.get("cdnUrl"),
                "contentType": image.get("contentType"),
                "bytes": image.get("bytes"),
                "assetCommit": asset_commit,
            }
            assets_by_path[target_path] = asset

    assets = [assets_by_path[path] for path in sorted(assets_by_path)]
    payload = {"version": 1, "count": len(assets), "assets": assets}
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Cataloged {len(assets)} reusable image asset(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
