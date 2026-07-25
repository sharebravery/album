# Pulse Image Cache

This directory stores optimized, verified images used by Pulse Article and X deliveries.

## Layout

- `article/YYYY/MM/DD/<topic>-<content-hash>.<ext>`
- `x/YYYY/MM/DD/<topic>-<content-hash>.<ext>`
- `generated/YYYY/MM/DD/<topic>-<content-hash>.<ext>`

## Rules

1. Discover images from multiple sources, but never use search-engine thumbnails or proxy URLs directly.
2. Download the original image, follow redirects, verify HTTP 200, supported image bytes, dimensions and size.
3. Optimize before upload. Prefer 1200–1280 px width and usually 150–500 KB.
4. Use content-hash filenames so identical files are reused rather than duplicated.
5. After upload, reference immutable Raw URLs pinned to the commit SHA whenever practical.
6. Keep original source and license notes outside publishable Markdown.
7. Do not overwrite an existing asset with different bytes.

Pulse Relay remains a transport layer. It may further optimize an image for email, but it must not choose, move or redistribute images.
