# sharebravery/album

Public image assets used by Pulse Deliveries.

## Pulse image ingestion

The selected `pulse-platforms` Operator chooses real images, determines their editorial roles and alt text, and submits a JSON request under `requests/`.

The permanent workflow runs on each new request push. A five-minute scheduled scan is only a fallback for delayed or missed push processing.

The workflow then:

1. validates the request and public source URLs;
2. downloads raster images on GitHub Actions;
3. accepts JPEG, PNG, WebP, GIF and article-source AVIF files up to 10 MiB;
4. rejects SVG, non-image responses, private-network URLs and unsafe paths;
5. normalizes Article assets to JPEG and stores all assets under `pulse/`;
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

A request may contain up to 12 images. `targetPath` must be a safe relative path inside `pulse/`. Article assets use a `.jpg` target and are normalized by content; other assets must use an extension matching the downloaded image type.

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

A missing result file means processing is pending. A result with `status: completed`, `partial` or `failed` is terminal. The Operator inspects successful assets, makes at most one replacement request when allowed by its image flow, and only then creates the Markdown Delivery.

## Change hygiene

Temporary test requests, test assets, diagnostics and one-off workflows are removed in the same verification cycle. The active tree keeps only the permanent ingestion workflow, its processor, durable image assets and result records.
