# TASK — web-sourcing inc3b: byte validation + normalise pipeline

## Context
`sdk/sfvf/media/web.py::fetch` currently downloads untrusted bytes under the SSRF/byte-cap guard
(increment 3a) and writes them raw. Per docs/DESIGN §7.2 the bytes are STILL untrusted and must be
validated and normalised before anything is written. Frozen RED contracts are committed:
`tests/integration/test_media_web_normalise.py` (the pipeline seam) and the updated happy-path in
`tests/integration/test_media_web_fetch.py`. **Do not edit any test file.**

## Scope
- **Edit ONLY** `sdk/sfvf/media/web.py`.
- No new dependencies beyond Pillow, which is already declared (the SDK `web` extra) — **lazy-import**
  it (`from PIL import Image`) inside the pipeline and raise a clear `RuntimeError`/`ImportError`-style
  message if absent, exactly like the `edit`/`speech` adapters do for their heavy deps. Do NOT import
  PIL at module top-level (keep core import-light).
- Do NOT create any notes/markdown files.

## Required behaviour
Add a module constant and a function, and wire it into `fetch`.

1. `_MAX_IMAGE_PIXELS = 40_000_000` (module constant; a sane ceiling well under Pillow's ~89 Mpx
   default bomb threshold).

2. `_normalise_image(data: bytes) -> tuple[bytes, str]` — returns `(canonical_bytes, extension)` or
   raises `ValueError`. Steps, in order:
   a. **Magic-byte type gate** (NOT suffix): sniff the leading bytes to one of `png` / `jpeg` /
      `webp` / `gif`. PNG `\x89PNG\r\n\x1a\n`; JPEG `\xff\xd8\xff`; GIF `GIF87a`/`GIF89a`; WebP
      `RIFF....WEBP` (`data[:4]==b"RIFF" and data[8:12]==b"WEBP"`). Anything else — including SVG/XML,
      HTML, PDF, empty, or a valid magic followed by a non-decodable body — raises `ValueError`. SVG is
      explicitly excluded.
   b. **Bound the decode BEFORE allocating the bitmap.** Set `Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS`
      (so Pillow raises `Image.DecompressionBombError` on decode), open with
      `Image.open(io.BytesIO(data))`, and reject via the header size first:
      `if img.width * img.height > _MAX_IMAGE_PIXELS: raise ValueError(...)` — this must fire on a file
      that merely DECLARES gigapixels (e.g. a 40000x40000 PNG whose IHDR is read without decoding IDAT),
      before any `.load()`. Also confirm the PIL-detected `img.format` matches the sniffed type (reject
      on mismatch — polyglot/format-confusion defence). Wrap Pillow errors so only `ValueError` escapes.
   c. **Reject animated:** `if getattr(img, "n_frames", 1) > 1: raise ValueError(...)` (GIF/WebP/APNG
      frame bombs). Use frame 0 only.
   d. **Decode -> re-encode -> strip.** Fully decode (e.g. `img.convert(...)`) and re-encode to a
      canonical image with NO metadata (no `exif=`, no ICC, no text chunks) and no trailing data:
      - png or gif input  -> re-encode as **PNG**, extension `"png"` (convert to `"RGBA"` or `"RGB"`);
      - jpeg input        -> re-encode as **JPEG**, extension `"jpg"` (convert to `"RGB"`, quality ~90,
        no exif);
      - webp input        -> re-encode as **WebP**, extension `"webp"`.
      Re-encoding is what defeats polyglot/EXIF-tracker/embedded payloads — the original bytes must
      never be returned or written. Output must be deterministic for identical input.
   Return `(canonical_bytes, extension)`.

3. **Wire into `fetch`.** After `_download_guarded(url)` returns the raw bytes, call
   `_normalise_image` on them; hash the **canonical** bytes with the existing `_content_hash`
   (sha256[:16]); write the artifact as `web-{stem}.{ext}` (NOT `.bin`); return its workspace-relative
   path. The raw download bytes must not be written or retained.

Preserve every 3a guarantee (SSRF guard, byte cap, redirect re-validation, content-encoding reject).

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_normalise.py tests/integration/test_media_web_fetch.py -q`
  → **all pass** (16 normalise + 33 fetch).
- `python -m ruff format --check sdk/sfvf/media/web.py` and `python -m ruff check sdk/sfvf/media/web.py` → clean.
- `git diff --name-only` shows **only** `sdk/sfvf/media/web.py`.
