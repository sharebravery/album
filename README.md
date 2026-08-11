# sharebravery/album

Public sourced-image assets used by Pulse Deliveries.

## Responsibility Boundary

`pulse-operators` owns editorial intent:

- decide which sourced visual slots are actually needed after candidate text and visual roles are locked;
- choose fixed target paths;
- screen candidate sources for relevance, provenance and basic public accessibility;
- submit one version-2 request containing only the sourced slots.

Album owns media ingestion:

- actual HTTP download and redirect handling;
- network/path safety checks;
- MIME/image validation and decoding;
- size/quality checks;
- format normalization;
- fixed asset storage and terminal result records.

Operators should **not duplicate Album's byte-level download/decode validation**. Generated base64 images are self-contained in Relay Markdown and never enter Album.

Relay does not inspect Album results or wait for ingestion.

## Pulse image ingestion

The ingestion workflow runs on each request push. A five-minute scheduled scan is only a fallback for delayed or missed push processing.

For each request Album:

1. validates request structure, public URL shape and fixed target paths;
2. downloads up to four assets concurrently;
3. tries each asset's candidate URLs in preference order;
4. accepts JPEG, PNG, WebP, GIF and Article-source AVIF files up to 10 MiB;
5. rejects SVG, non-image responses, private-network URLs, unsafe paths, HTML error pages and undecodable payloads;
6. rejects tiny Article placeholders: short side below 240 px or total area below 160,000 px;
7. normalizes Article assets to baseline JPEG;
8. stores successful assets under predetermined `pulse/` paths;
9. writes a terminal result, removes the processed request and commits the resulting state.

Version-2 target paths are unique and never overwritten, so Operators may reference the predictable `@master` URL in the locked Delivery after the request commit succeeds. They do not need to poll ingestion results during the publication run.

## Request v2 — fixed assets with fallbacks

Create `requests/<requestId>.json` **after candidate text and visual roles are locked, and before the Relay Delivery is committed**. Include only sourced slots; generated base64 slots are omitted.

```json
{
  "version": 2,
  "requestId": "20260811-wechat-reconnect",
  "assets": [
    {
      "targetPath": "pulse/article/2026/08/reconnect/01-evidence.jpg",
      "alt": "Reconnect sequence evidence",
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
- one asset contains one to three public HTTP(S) candidates in preference order;
- candidate URLs have already passed editorial relevance/provenance screening, but Album performs the authoritative download, MIME, decode and quality validation;
- `targetPath` is unique and must not already exist;
- Article targets end in `.jpg` because Album normalizes them to JPEG;
- candidates may use suitable search-engine proxy/cache URLs, official CDN URLs or other public image URLs;
- credentials, cookies, private-network URLs and placeholders are not allowed.

Album tries candidates sequentially inside each asset. A candidate succeeds only after Album's actual download, validation, decode and Article normalization checks pass.

The predictable public URL is:

```text
https://cdn.jsdelivr.net/gh/sharebravery/album@master/<targetPath>
```

## Result v2

`completed`, `partial` and `failed` are terminal ingestion records, not synchronous publication gates.

Pulse Operators do not poll these results during the content run. If later repair is needed, a new request may contain only missing target paths with new candidates; fixed public URLs do not change.

## Change hygiene

Temporary requests, test assets, diagnostics and one-off workflows are removed in the same verification cycle. Unit tests use temporary directories and never create durable image assets.
