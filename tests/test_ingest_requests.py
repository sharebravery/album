from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import ingest_requests as ingest


class RequestValidationTests(unittest.TestCase):
    def write_request(self, directory: Path, request_id: str, payload: dict) -> Path:
        request_path = directory / f"{request_id}.json"
        request_path.write_text(json.dumps(payload), encoding="utf-8")
        return request_path

    def test_rejects_version_1_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request_id = "legacy-request"
            request_path = self.write_request(
                Path(directory),
                request_id,
                {"version": 1, "requestId": request_id, "images": [{"placeholder": True}]},
            )
            with self.assertRaisesRegex(ValueError, "version must be 2"):
                ingest.load_request(request_path)

    def test_loads_version_2_fixed_asset_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request_id = "fixed-assets"
            request_path = self.write_request(
                Path(directory),
                request_id,
                {"version": 2, "requestId": request_id, "assets": [{"placeholder": True}]},
            )
            self.assertEqual(ingest.load_request(request_path)["version"], 2)

    def test_rejects_non_jpg_fixed_article_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "must end in .jpg"):
            ingest.validate_target_path("pulse/article/2026/08/topic/lead.png")

    def test_does_not_cap_the_number_of_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request_id = "many-assets"
            request_path = self.write_request(
                Path(directory),
                request_id,
                {
                    "version": 2,
                    "requestId": request_id,
                    "assets": [{"placeholder": index} for index in range(20)],
                },
            )
            self.assertEqual(len(ingest.load_request(request_path)["assets"]), 20)


class CandidateFallbackTests(unittest.TestCase):
    def test_uses_the_first_successful_candidate(self) -> None:
        candidates = [
            {"sourcePageUrl": "https://source.example/one", "downloadUrl": "https://img.example/one.png"},
            {"sourcePageUrl": "https://source.example/two", "downloadUrl": "https://img.example/two.png"},
        ]
        target = Path("pulse/xhs/2026/08/note/lead.png")

        with (
            patch.object(ingest, "validate_public_http_url", side_effect=lambda value, _field: value),
            patch.object(ingest, "download_image", side_effect=[ValueError("blocked"), ("image/png", 321)]),
        ):
            result = ingest.process_asset(0, candidates, target, "Lead image")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["selectedCandidateIndex"], 1)
        self.assertEqual(result["downloadUrl"], "https://img.example/two.png")
        self.assertEqual([attempt["status"] for attempt in result["attempts"]], ["failed", "completed"])

    def test_fails_after_all_candidates_fail(self) -> None:
        candidates = [
            {"sourcePageUrl": "https://source.example/one", "downloadUrl": "https://img.example/one.png"},
            {"sourcePageUrl": "https://source.example/two", "downloadUrl": "https://img.example/two.png"},
        ]
        target = Path("pulse/xhs/2026/08/note/lead.png")

        with (
            patch.object(ingest, "validate_public_http_url", side_effect=lambda value, _field: value),
            patch.object(ingest, "download_image", side_effect=ValueError("blocked")),
        ):
            result = ingest.process_asset(0, candidates, target, "Lead image")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "all candidates failed")
        self.assertEqual(len(result["attempts"]), 2)

    def test_article_fallback_survives_jpeg_normalization(self) -> None:
        candidates = [
            {"sourcePageUrl": "https://source.example/one", "downloadUrl": "https://img.example/one.png"},
            {"sourcePageUrl": "https://source.example/two", "downloadUrl": "https://img.example/two.png"},
        ]
        target = Path("pulse/article/2026/08/topic/lead.jpg")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def fake_download(url: str, destination: Path) -> tuple[str, int]:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if url.endswith("one.png"):
                    destination.write_bytes(b"not a decodable image")
                else:
                    Image.new("RGBA", (640, 360), (20, 80, 160, 180)).save(destination, format="PNG")
                return "image/png", destination.stat().st_size

            with (
                patch.object(ingest, "ROOT", root),
                patch.object(ingest, "validate_public_http_url", side_effect=lambda value, _field: value),
                patch.object(ingest, "download_image", side_effect=fake_download),
            ):
                result = ingest.process_asset(0, candidates, target, "Article lead")

            destination = root / target
            with Image.open(destination) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertEqual(image.mode, "RGB")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["selectedCandidateIndex"], 1)
        self.assertEqual(result["contentType"], "image/jpeg")
        self.assertEqual([attempt["status"] for attempt in result["attempts"]], ["failed", "completed"])

    def test_rejects_a_tiny_decodable_article_placeholder(self) -> None:
        candidates = [
            {"sourcePageUrl": "https://source.example/tiny", "downloadUrl": "https://img.example/tiny.png"}
        ]
        target = Path("pulse/article/2026/08/topic/tiny.jpg")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def fake_download(_url: str, destination: Path) -> tuple[str, int]:
                destination.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (64, 64), "white").save(destination, format="PNG")
                return "image/png", destination.stat().st_size

            with (
                patch.object(ingest, "ROOT", root),
                patch.object(ingest, "validate_public_http_url", side_effect=lambda value, _field: value),
                patch.object(ingest, "download_image", side_effect=fake_download),
            ):
                result = ingest.process_asset(0, candidates, target, "Tiny placeholder")

        self.assertEqual(result["status"], "failed")
        self.assertIn("too small for publication", result["attempts"][0]["error"])


class PrepareIntegrationTests(unittest.TestCase):
    def test_prepare_processes_version_2_assets_into_the_internal_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requests = root / "requests"
            results = root / "results"
            work = root / ".album-work"
            requests.mkdir()
            request_id = "article-assets"
            (requests / f"{request_id}.json").write_text(
                json.dumps(
                    {
                        "version": 2,
                        "requestId": request_id,
                        "assets": [
                            {
                                "targetPath": "pulse/article/2026/08/topic/lead.jpg",
                                "alt": "Article lead",
                                "candidates": [
                                    {
                                        "sourcePageUrl": "https://source.example/lead",
                                        "downloadUrl": "https://img.example/lead.png",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_download(_url: str, destination: Path) -> tuple[str, int]:
                destination.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (640, 360), "navy").save(destination, format="PNG")
                return "image/png", destination.stat().st_size

            with (
                patch.object(ingest, "ROOT", root),
                patch.object(ingest, "REQUESTS_DIR", requests),
                patch.object(ingest, "RESULTS_DIR", results),
                patch.object(ingest, "WORK_DIR", work),
                patch.object(ingest, "SUMMARY_PATH", work / "summary.json"),
                patch.object(ingest, "validate_public_http_url", side_effect=lambda value, _field: value),
                patch.object(ingest, "download_image", side_effect=fake_download),
            ):
                self.assertEqual(ingest.prepare(), 0)
                summary = json.loads((work / "summary.json").read_text(encoding="utf-8"))

            request = summary["requests"][0]
            asset = request["assets"][0]
            self.assertEqual(request["version"], 2)
            self.assertEqual(asset["status"], "completed")
            self.assertEqual(asset["contentType"], "image/jpeg")
            self.assertEqual(asset["selectedCandidateIndex"], 0)


class ResultTests(unittest.TestCase):
    def test_version_2_result_uses_predictable_master_urls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requests = root / "requests"
            results = root / "results"
            work = root / ".album-work"
            requests.mkdir()
            work.mkdir()
            request_path = requests / "fixed-assets.json"
            request_path.write_text("{}", encoding="utf-8")
            summary_path = work / "summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "requests": [
                            {
                                "version": 2,
                                "requestFile": "requests/fixed-assets.json",
                                "resultFile": "results/fixed-assets.json",
                                "requestId": "fixed-assets",
                                "assets": [
                                    {
                                        "index": 0,
                                        "status": "completed",
                                        "targetPath": "pulse/article/2026/08/topic/lead.jpg",
                                        "alt": "Lead",
                                        "normalized": True,
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(ingest, "ROOT", root),
                patch.object(ingest, "REQUESTS_DIR", requests),
                patch.object(ingest, "RESULTS_DIR", results),
                patch.object(ingest, "WORK_DIR", work),
                patch.object(ingest, "SUMMARY_PATH", summary_path),
            ):
                ingest.finalize()

            result = json.loads((results / "fixed-assets.json").read_text(encoding="utf-8"))
            asset = result["assets"][0]
            self.assertEqual(result["version"], 2)
            self.assertNotIn("assetCommit", result)
            self.assertNotIn("normalized", asset)
            self.assertIn("/master/pulse/article/2026/08/topic/lead.jpg", asset["rawUrl"])
            self.assertIn("@master/pulse/article/2026/08/topic/lead.jpg", asset["cdnUrl"])


if __name__ == "__main__":
    unittest.main()
