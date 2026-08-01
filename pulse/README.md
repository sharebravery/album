# Pulse Image Store

This directory stores normalized public images used by Pulse.

## Active layout

```text
article/YYYY/MM/<article-id>/<slot>.jpg
xhs/YYYY/MM/<note-id>/<asset>.<ext>
generated/YYYY/MM/<content-id>/<asset>.<ext>
```

## Rules

1. Select and inspect media before submitting it to Album.
2. Never use search-engine thumbnails or proxy URLs as source assets.
3. Use a unique, predetermined path for every editorial asset.
4. Never overwrite or reuse an existing target path.
5. Normalize Article assets to baseline JPEG.
6. Keep source provenance in the request and result records.
7. Use the predictable `@master` URL for new fixed-path assets.
8. Keep Relay independent from image ingestion and storage.
