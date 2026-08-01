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
5. rejects SVG, non-image responses, private-network URLs and unsafe paths;
6. normalizes Article assets to baseline JPEG;
7. stores successful assets under their predetermined `pulse/` paths;
8. writes a terminal result, removes the processed request and commits all three changes together.

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
- every candidate has already passed editorial inspection for the same slot;
- `targetPath` is unique across all requests and must not already exist;
- an Article target already ends in `.jpg`;
- Xiaohongshu and other non-Article targets use an extension matching the downloaded file type;
- candidates use public direct URLs without authentication, cookies, JavaScript or expiring sessions.

Album tries candidates sequentially inside each asset. A candidate is selected only after its download, type validation and required Article JPEG normalization succeed.

The predictable public URL is:

```text
https://cdn.jsdelivr.net/gh/sharebravery/album@master/<targetPath>
```

## Result v2

The result is operational evidence and is not a publication gate:

```json
{
  "version": 2,
  "requestId": "20260801-agent-sandbox",
  "status": "completed",
  "assets": [
    {
      "index": 0,
      "status": "completed",
      "targetPath": "pulse/article/2026/08/agent-sandbox/01-lead.jpg",
      "alt": "Agent sandbox control interface",
      "selectedCandidateIndex": 0,
      "sourcePageUrl": "https://example.com/primary-page",
      "downloadUrl": "https://example.com/primary.jpg",
      "contentType": "image/jpeg",
      "bytes": 123456,
      "rawUrl": "https://raw.githubusercontent.com/sharebravery/album/master/pulse/article/2026/08/agent-sandbox/01-lead.jpg",
      "cdnUrl": "https://cdn.jsdelivr.net/gh/sharebravery/album@master/pulse/article/2026/08/agent-sandbox/01-lead.jpg",
      "attempts": [
        {
          "index": 0,
          "status": "completed",
          "sourcePageUrl": "https://example.com/primary-page",
          "downloadUrl": "https://example.com/primary.jpg"
        }
      ]
    }
  ]
}
```

`completed`, `partial` and `failed` are terminal processing records. The processed request is removed and is not retried automatically. Pulse Operators do not poll results during the publication run. A manual repair may submit a new request containing only missing target paths and new candidates; the fixed public URLs do not change.

## Change hygiene

Temporary requests, test assets, diagnostics and one-off workflows are removed in the same verification cycle. Unit tests use temporary directories and never create durable image assets.
