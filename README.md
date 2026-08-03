# sharebravery/album

Public image assets used by Pulse Deliveries.

## Pulse image ingestion

`pulse-operators` selects and inspects public images, assigns their editorial roles and submits one JSON request under `requests/`.

The permanent workflow runs on each request push. A five-minute scheduled scan is only a fallback for delayed or missed push processing.

The workflow:

1. validates the request, public source URLs and fixed target paths;
2. downloads up to four assets in parallel;
3. tries the already approved candidates for each version 2 asset in order;
4. accepts JPEG, PNG, WebP, GIF and Article-source AVIF files up to 10 MiB;
5. rejects SVG, non-image responses, private-network URLs, unsafe paths, HTML error pages and undecodable image payloads;
6. rejects tiny Article placeholders: the short side must be at least 240 pixels and total area at least 160,000 pixels;
7. normalizes Article assets to baseline JPEG;
8. stores successful assets under their predetermined `pulse/` paths;
9. writes a terminal result, removes the processed request and commits assets, results and request removal together.

Relay does not inspect Album results or wait for image ingestion. Version 2 paths are unique and never overwritten, so Operators can derive their predictable `@master` URLs before upload.

## Request v2: fixed assets with fallbacks

Create `requests/<requestId>.json` before substantive writing:

```json
{
  "version": 2,
  "requestId": "20260801-agent-sandbox",
  "assets": [
    {
      "targetPath": "pulse/article/2026/08/agent-sandbox/01-lead.jpg",
      "alt": "Agent sandbox control interface",
      "candidates": [
        {
          "sourcePageUrl": "https://example.com/primary-page",
          "downloadUrl": "https://example.com/primary.jpg"
        },
        {
          "sourcePageUrl": "https://example.com/fallback-page",
          "downloadUrl": "https://example.com/fallback.jpg"
        }
      ]
    }
  ]
}
```

Rules:

- a request has no editorial asset limit; Album processes at most four downloads concurrently;
- one asset contains one to three candidates in preference order;
- every candidate has already passed editorial inspection and a real download check for the same slot;
- `targetPath` is unique across all requests and must not already exist;
- an Article target already ends in `.jpg`;
- Xiaohongshu and other non-Article targets use an extension matching the downloaded file type;
- candidates may use verified Google Images, Bing Images or Baidu Images proxy/cache URLs, official CDN URLs or other public image URLs;
- domain type is not a quality gate: the URL must work without authentication, cookies or JavaScript and return a decodable raster image rather than HTML, an error page or a tiny placeholder;
- webpage-style download endpoints that return `401`, `403`, session redirects or HTML are not valid candidates.

Search-engine proxy URLs are first-class sources because Album only needs them to remain valid long enough to ingest the image. The published Delivery references the permanent Album path, not the temporary source URL.

Album tries candidates sequentially inside each asset. A candidate is selected only after its download, MIME validation, decode and Article quality/normalization checks succeed.

The predictable public URL is:

```text
https://cdn.jsdelivr.net/gh/sharebravery/album@master/<targetPath>
```

## Result v2

The result is operational evidence and is not a publication gate. `completed`, `partial` and `failed` are terminal processing records. The processed request is removed and is not retried automatically. Pulse Operators do not poll results during the publication run. A manual repair may submit a new request containing only missing target paths and new candidates; the fixed public URLs do not change.

## Change hygiene

Temporary requests, test assets, diagnostics and one-off workflows are removed in the same verification cycle. Unit tests use temporary directories and never create durable image assets.
