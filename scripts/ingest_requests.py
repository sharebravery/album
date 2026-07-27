#!/usr/bin/env python3
"""Process Pulse image-ingestion requests using only the Python standard library."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUESTS_DIR = ROOT / "requests"
RESULTS_DIR = ROOT / "results"
WORK_DIR = ROOT / ".album-work"
SUMMARY_PATH = WORK_DIR / "summary.json"
MAX_BYTES = 10 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_ATTEMPTS = 2
ALLOWED_MIME = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
    "image/gif": {".gif"},
}


def fail(message: str) -> None:
    raise ValueError(message)


def validate_public_http_url(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{field} must be a non-empty string")
    url = value.strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        fail(f"{field} must be an HTTP(S) URL")
    if parsed.username or parsed.password:
        fail(f"{field} must not contain credentials")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        fail(f"{field} hostname could not be resolved: {exc}")

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            fail(f"{field} resolves to a non-public address")
    return url


def validate_target_path(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        fail("targetPath must be a non-empty string")
    posix = Path(value.strip())
    if posix.is_absolute() or ".." in posix.parts:
        fail("targetPath must be a safe relative path")
    if not posix.parts or posix.parts[0] != "pulse":
        fail("targetPath must be inside pulse/")
    suffix = posix.suffix.lower()
    allowed_suffixes = {ext for values in ALLOWED_MIME.values() for ext in values}
    if suffix not in allowed_suffixes:
        fail("targetPath must end in .jpg, .jpeg, .png, .webp or .gif")
    return posix


def detect_mime(path: Path) -> str:
    result = subprocess.run(
        ["file", "--brief", "--mime-type", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().lower()


def expected_mime_for(destination: Path) -> str:
    suffix = destination.suffix.lower()
    for mime, suffixes in ALLOWED_MIME.items():
        if suffix in suffixes:
            return mime
    fail(f"unsupported target extension: {suffix}")


def download_image(url: str, destination: Path) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".download")
    expected_mime = expected_mime_for(destination)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; PulseAlbumIngestion/1.0; +https://github.com/sharebravery/album)",
            "Accept": f"{expected_mime},*/*;q=0.1",
            "Accept-Encoding": "identity",
        },
    )

    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        temporary.unlink(missing_ok=True)
        try:
            with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, temporary.open("wb") as output:
                declared = response.headers.get_content_type().lower()
                if declared == "image/svg+xml":
                    fail("SVG images are not accepted")
                total = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES:
                        fail(f"image exceeds {MAX_BYTES} bytes")
                    output.write(chunk)
            break
        except (TimeoutError, socket.timeout):
            temporary.unlink(missing_ok=True)
            if attempt == DOWNLOAD_ATTEMPTS:
                raise
            time.sleep(2 * attempt)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    detected = detect_mime(temporary)
    if detected not in ALLOWED_MIME:
        temporary.unlink(missing_ok=True)
        fail(f"unsupported image type: {detected}")
    if detected != expected_mime:
        temporary.unlink(missing_ok=True)
        fail(f"target extension does not match detected type {detected}")

    os.replace(temporary, destination)
    return detected, destination.stat().st_size


def load_request(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid JSON: {exc}")
    if not isinstance(payload, dict):
        fail("request must be a JSON object")
    if payload.get("version") != 1:
        fail("version must be 1")
    request_id = payload.get("requestId")
    if not isinstance(request_id, str) or not request_id.strip():
        fail("requestId must be a non-empty string")
    images = payload.get("images")
    if not isinstance(images, list) or not images:
        fail("images must be a non-empty array")
    if len(images) > 12:
        fail("a request may contain at most 12 images")
    return payload


def prepare() -> int:
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    request_paths = sorted(REQUESTS_DIR.glob("*.json")) if REQUESTS_DIR.exists() else []
    if not request_paths:
        print("No album requests found.")
        SUMMARY_PATH.write_text(json.dumps({"requests": []}), encoding="utf-8")
        return 0

    summary: dict[str, Any] = {"requests": []}
    for request_path in request_paths:
        request_result: dict[str, Any] = {
            "requestFile": request_path.relative_to(ROOT).as_posix(),
            "resultFile": f"results/{request_path.name}",
            "requestId": request_path.stem,
            "images": [],
        }
        try:
            payload = load_request(request_path)
            request_result["requestId"] = payload["requestId"].strip()
            for index, image in enumerate(payload["images"]):
                item: dict[str, Any] = {"index": index, "status": "failed"}
                try:
                    if not isinstance(image, dict):
                        fail("image entry must be an object")
                    download_url = validate_public_http_url(image.get("downloadUrl"), "downloadUrl")
                    source_page_url = validate_public_http_url(image.get("sourcePageUrl"), "sourcePageUrl")
                    target = validate_target_path(image.get("targetPath"))
                    alt = image.get("alt")
                    if not isinstance(alt, str) or not alt.strip():
                        fail("alt must be a non-empty string")
                    destination = ROOT / target
                    mime, size = download_image(download_url, destination)
                    item.update(
                        {
                            "status": "completed",
                            "sourcePageUrl": source_page_url,
                            "downloadUrl": download_url,
                            "targetPath": target.as_posix(),
                            "alt": alt.strip(),
                            "contentType": mime,
                            "bytes": size,
                        }
                    )
                except Exception as exc:  # Record per-image failures for operator retry.
                    item["error"] = str(exc)
                request_result["images"].append(item)
        except Exception as exc:
            request_result["requestError"] = str(exc)
        summary["requests"].append(request_result)

    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    completed = sum(
        1
        for request in summary["requests"]
        for image in request.get("images", [])
        if image.get("status") == "completed"
    )
    print(f"Prepared {completed} image asset(s) from {len(request_paths)} request(s).")
    return 0


def finalize(asset_commit: str) -> int:
    if not SUMMARY_PATH.exists():
        fail("missing preparation summary")
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    for request in summary.get("requests", []):
        images = request.get("images", [])
        completed = 0
        finalized_images: list[dict[str, Any]] = []
        for item in images:
            output = dict(item)
            if item.get("status") == "completed":
                completed += 1
                target = item["targetPath"]
                output["rawUrl"] = (
                    f"https://raw.githubusercontent.com/sharebravery/album/{asset_commit}/{target}"
                )
                output["cdnUrl"] = (
                    f"https://cdn.jsdelivr.net/gh/sharebravery/album@{asset_commit}/{target}"
                )
            finalized_images.append(output)

        if request.get("requestError"):
            status = "failed"
        elif completed == len(images) and completed > 0:
            status = "completed"
        elif completed > 0:
            status = "partial"
        else:
            status = "failed"

        result = {
            "version": 1,
            "requestId": request.get("requestId"),
            "status": status,
            "assetCommit": asset_commit if completed else None,
            "images": finalized_images,
        }
        if request.get("requestError"):
            result["error"] = request["requestError"]

        result_path = ROOT / request["resultFile"]
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (ROOT / request["requestFile"]).unlink(missing_ok=True)

    shutil.rmtree(WORK_DIR, ignore_errors=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices={"prepare", "finalize"})
    parser.add_argument("--asset-commit")
    args = parser.parse_args()
    if args.mode == "prepare":
        return prepare()
    if not args.asset_commit:
        parser.error("--asset-commit is required for finalize")
    return finalize(args.asset_commit)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Album ingestion failed: {exc}", file=sys.stderr)
        sys.exit(1)
