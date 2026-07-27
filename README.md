# sharebravery/album

Public image assets used by Pulse Deliveries.

## Pulse image ingestion

`pulse-agents` selects real images, determines their paragraph position and alt text, and submits a JSON request under `requests/`.

The permanent workflow then:

1. validates the request and public source URLs;
2. downloads raster images on GitHub Actions;
3. accepts JPEG, PNG, WebP and GIF files up to 10 MiB;
4. rejects SVG, non-image responses, private-network URLs and unsafe paths;
5. stores assets under `pulse/`;
6. commits the image assets;
7. writes commit-pinned Raw and jsDelivr URLs to `results/`;
8. removes the processed request.

Relay does not download, transform, inspect or upload images. It only renders the final URLs already present in a Delivery.

### Request

Create one file such as `requests/20260727-agent-sandbox.json`:

```json
{
  "version": 1,
  "requestId": "20260727-agent-sandbox",
  "images": [
    {
      "sourcePageUrl": "https://example.com/original-page",
      "downloadUrl": "https://example.com/image.jpg",
      "targetPath": "pulse/article/2026/07/agent-sandbox/image.jpg",
      "alt": "Useful description of the image"
    }
  ]
}
```

A request may contain up to 12 images. `targetPath` must be a safe relative path inside `pulse/`, and its extension must match the downloaded image type.

### Result

The workflow writes `results/<request-file-name>.json`:

```json
{
  "version": 1,
  "requestId": "20260727-agent-sandbox",
  "status": "completed",
  "assetCommit": "COMMIT_SHA",
  "images": [
    {
      "status": "completed",
      "sourcePageUrl": "https://example.com/original-page",
      "downloadUrl": "https://example.com/image.jpg",
      "targetPath": "pulse/article/2026/07/agent-sandbox/image.jpg",
      "alt": "Useful description of the image",
      "contentType": "image/jpeg",
      "bytes": 123456,
      "rawUrl": "https://raw.githubusercontent.com/sharebravery/album/COMMIT_SHA/pulse/article/2026/07/agent-sandbox/image.jpg",
      "cdnUrl": "https://cdn.jsdelivr.net/gh/sharebravery/album@COMMIT_SHA/pulse/article/2026/07/agent-sandbox/image.jpg"
    }
  ]
}
```

`status` is `completed`, `partial` or `failed`. The Operator reads the result, replaces failed candidates when necessary, verifies the final URLs, and only then creates the Markdown Delivery.

## Change hygiene

Temporary test requests, test assets, test results, diagnostics and one-off workflows are removed in the same verification cycle. The active tree keeps only the permanent ingestion workflow, its processor, durable image assets and current result records needed by an unfinished Delivery.
