#!/usr/bin/env python3
"""Process Pulse image-ingestion requests."""

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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
DOWNLOAD_WORKERS = 4
MAX_REQUEST_ASSETS = 12
MAX_CANDIDATES_PER_ASSET = 3
ARTICLE_PREFIX = ("pulse", "article")
ALLOWED_MIME = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
    "image/gif": {".gif"},
}
DOWNLOADABLE_MIME = set(ALLOWED_MIME) | {"image/avif"}


def fail(message: str) -> None:
    raise ValueError(message)


def is_article_path(path: Path) -> bool:
    return len(path.parts) >= 2 and tuple(path.parts[:2]) == ARTICLE_PREFIX


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

    # Article assets always publish as JPEG. Version 1 requests are normalized
    # for compatibility; version 2 fixed paths are separately required to
    # already use the resulting .jpg path.
    if is_article_path(posix):
        if not posix.name or posix.name in {".", ".."}:
            fail("targetPath must include a filename")
        return posix.with_suffix(".jpg")

    suffix = posix.suffix.lower()
    allowed_suffixes = {ext for values in ALLOWED_MIME.values() for ext in values}
    if suffix not in allowed_suffixes:
        fail("targetPath must end in .jpg, .jpeg, .png, .webp or .gif")
    return posix


def validate_fixed_target_path(value: Any) -> Path:
    target = validate_target_path(value)
    requested = Path(value.strip())
    if target.as_posix() != requested.as_posix():
        fail("version 2 Article targetPath must already end in .jpg")
    return target


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
    article_target = is_article_path(destination.relative_to(ROOT))
    accept = (
        "image/avif,image/webp,image/png,image/jpeg,image/gif,*/*;q=0.1"
        if article_target
        else f"{expected_mime},*/*;q=0.1"
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; PulseAlbumIngestion/2.0; +https://github.com/sharebravery/album)",
            "Accept": accept,
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
    if detected not in DOWNLOADABLE_MIME:
        temporary.unlink(missing_ok=True)
        fail(f"unsupported image type: {detected}")
    if detected != expected_mime and not article_target:
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

    version = payload.get("version")
    if version not in {1, 2}:
        fail("version must be 1 or 2")
    request_id = payload.get("requestId")
    if not isinstance(request_id, str) or not request_id.strip():
        fail("requestId must be a non-empty string")
    if request_id.strip() != path.stem:
        fail("requestId must match the request filename")

    entry_key = "images" if version == 1 else "assets"
    entries = payload.get(entry_key)
    if not isinstance(entries, list) or not entries:
        fail(f"{entry_key} must be a non-empty array")
    if len(entries) > MAX_REQUEST_ASSETS:
        fail(f"a request may contain at most {MAX_REQUEST_ASSETS} {entry_key}")
    return payload


def process_download(
    index: int,
    download_url: str,
    source_page_url: str,
    target: Path,
    alt: str,
) -> dict[str, Any]:
    item: dict[str, Any] = {"index": index, "status": "failed"}
    try:
        mime, size = download_image(download_url, ROOT / target)
        item.update(
            {
                "status": "completed",
                "sourcePageUrl": source_page_url,
                "downloadUrl": download_url,
                "targetPath": target.as_posix(),
                "alt": alt,
                "contentType": mime,
                "bytes": size,
            }
        )
    except Exception as exc:
        item["error"] = str(exc)
    return item


def normalize_v2_article(target: Path) -> tuple[str, int]:
    if not is_article_path(target):
        destination = ROOT / target
        return detect_mime(destination), destination.stat().st_size

    # Pillow is installed before prepare in the permanent workflow. Keeping
    # this import local leaves request validation and unit tests lightweight.
    from normalize_article_images import normalize_file

    destination = ROOT / target
    size = normalize_file(destination, destination)
    return "image/jpeg", size


def process_asset(
    index: int,
    candidates: Any,
    target: Path,
    alt: str,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "index": index,
        "status": "failed",
        "targetPath": target.as_posix(),
        "alt": alt,
        "attempts": [],
    }
    if not isinstance(candidates, list) or not candidates:
        item["error"] = "candidates must be a non-empty array"
        return item
    if len(candidates) > MAX_CANDIDATES_PER_ASSET:
        item["error"] = f"an asset may contain at most {MAX_CANDIDATES_PER_ASSET} candidates"
        return item

    seen_download_urls: set[str] = set()
    for candidate_index, candidate in enumerate(candidates):
        attempt: dict[str, Any] = {"index": candidate_index, "status": "failed"}
        try:
            if not isinstance(candidate, dict):
                fail("candidate must be an object")
            download_url = validate_public_http_url(candidate.get("downloadUrl"), "downloadUrl")
            source_page_url = validate_public_http_url(candidate.get("sourcePageUrl"), "sourcePageUrl")
            attempt.update({"sourcePageUrl": source_page_url, "downloadUrl": download_url})
            if download_url in seen_download_urls:
                fail("candidate downloadUrl must be unique within an asset")
            seen_download_urls.add(download_url)

            mime, size = download_image(download_url, ROOT / target)
            if is_article_path(target):
                mime, size = normalize_v2_article(target)

            attempt["status"] = "completed"
            item["attempts"].append(attempt)
            item.update(
                {
                    "status": "completed",
                    "selectedCandidateIndex": candidate_index,
                    "sourcePageUrl": source_page_url,
                    "downloadUrl": download_url,
                    "contentType": mime,
                    "bytes": size,
                    "normalized": is_article_path(target),
                }
            )
            return item
        except Exception as exc:
            (ROOT / target).unlink(missing_ok=True)
            attempt["error"] = str(exc)
            item["attempts"].append(attempt)

    item["error"] = "all candidates failed"
    return item


def claim_target(target: Path, claimed_targets: set[str]) -> None:
    target_key = target.as_posix()
    if target_key in claimed_targets:
        fail("targetPath must be unique across pending requests")
    if (ROOT / target).exists():
        fail("targetPath already exists")
    claimed_targets.add(target_key)


def prepare() -> int:
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    request_paths = sorted(REQUESTS_DIR.glob("*.json")) if REQUESTS_DIR.exists() else []
    if not request_paths:
        print("No album requests found.")
        SUMMARY_PATH.write_text(json.dumps({"requests": []}), encoding="utf-8")
        return 0

    summary: dict[str, Any] = {"requests": []}
    claimed_targets: set[str] = set()
    jobs: list[tuple[Any, ...]] = []

    for request_path in request_paths:
        request_result: dict[str, Any] = {
            "version": 1,
            "requestFile": request_path.relative_to(ROOT).as_posix(),
            "resultFile": f"results/{request_path.name}",
            "requestId": request_path.stem,
            "images": [],
        }
        try:
            payload = load_request(request_path)
            version = payload["version"]
            entry_key = "images" if version == 1 else "assets"
            entries = payload[entry_key]
            request_result["version"] = version
            request_result.pop("images", None)
            request_result[entry_key] = [
                {
                    "index": index,
                    "status": "failed",
                    "error": f"{entry_key[:-1]} was not prepared",
                }
                for index in range(len(entries))
            ]
            request_result["requestId"] = payload["requestId"].strip()

            for index, entry in enumerate(entries):
                item: dict[str, Any] = {"index": index, "status": "failed"}
                try:
                    if not isinstance(entry, dict):
                        fail(f"{entry_key[:-1]} entry must be an object")
                    alt = entry.get("alt")
                    if not isinstance(alt, str) or not alt.strip():
                        fail("alt must be a non-empty string")

                    if version == 1:
                        download_url = validate_public_http_url(entry.get("downloadUrl"), "downloadUrl")
                        source_page_url = validate_public_http_url(entry.get("sourcePageUrl"), "sourcePageUrl")
                        target = validate_target_path(entry.get("targetPath"))
                        claim_target(target, claimed_targets)
                        jobs.append(
                            (
                                "v1",
                                request_result,
                                entry_key,
                                index,
                                download_url,
                                source_page_url,
                                target,
                                alt.strip(),
                            )
                        )
                    else:
                        target = validate_fixed_target_path(entry.get("targetPath"))
                        claim_target(target, claimed_targets)
                        jobs.append(
                            (
                                "v2",
                                request_result,
                                entry_key,
                                index,
                                entry.get("candidates"),
                                target,
                                alt.strip(),
                            )
                        )
                except Exception as exc:
                    item["error"] = str(exc)
                    request_result[entry_key][index] = item
        except Exception as exc:
            request_result["requestError"] = str(exc)
        summary["requests"].append(request_result)

    if jobs:
        worker_count = min(DOWNLOAD_WORKERS, len(jobs))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_jobs: dict[Any, tuple[dict[str, Any], str, int]] = {}
            for job in jobs:
                kind, request_result, entry_key, index, *arguments = job
                if kind == "v1":
                    future = executor.submit(process_download, index, *arguments)
                else:
                    future = executor.submit(process_asset, index, *arguments)
                future_jobs[future] = (request_result, entry_key, index)

            for future in as_completed(future_jobs):
                request_result, entry_key, index = future_jobs[future]
                try:
                    request_result[entry_key][index] = future.result()
                except Exception as exc:
                    request_result[entry_key][index] = {
                        "index": index,
                        "status": "failed",
                        "error": str(exc),
                    }

    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    completed = sum(
        1
        for request in summary["requests"]
        for item in request.get("images", request.get("assets", []))
        if item.get("status") == "completed"
    )
    print(
        f"Prepared {completed} image asset(s) from {len(request_paths)} request(s) "
        f"with up to {DOWNLOAD_WORKERS} parallel asset download(s)."
    )
    return 0


def finalize(asset_commit: str) -> int:
    if not SUMMARY_PATH.exists():
        fail("missing preparation summary")
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    for request in summary.get("requests", []):
        version = request.get("version", 1)
        entry_key = "images" if version == 1 else "assets"
        entries = request.get(entry_key, [])
        completed = 0
        finalized_entries: list[dict[str, Any]] = []
        for item in entries:
            output = dict(item)
            output.pop("normalized", None)
            if item.get("status") == "completed":
                completed += 1
                target = item["targetPath"]
                if version == 1:
                    output["rawUrl"] = (
                        f"https://raw.githubusercontent.com/sharebravery/album/{asset_commit}/{target}"
                    )
                    output["cdnUrl"] = (
                        f"https://cdn.jsdelivr.net/gh/sharebravery/album@{asset_commit}/{target}"
                    )
                else:
                    output["rawUrl"] = (
                        f"https://raw.githubusercontent.com/sharebravery/album/master/{target}"
                    )
                    output["cdnUrl"] = (
                        f"https://cdn.jsdelivr.net/gh/sharebravery/album@master/{target}"
                    )
            finalized_entries.append(output)

        if request.get("requestError"):
            status = "failed"
        elif completed == len(entries) and completed > 0:
            status = "completed"
        elif completed > 0:
            status = "partial"
        else:
            status = "failed"

        result: dict[str, Any] = {
            "version": version,
            "requestId": request.get("requestId"),
            "status": status,
            entry_key: finalized_entries,
        }
        if version == 1:
            result["assetCommit"] = asset_commit if completed else None
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
