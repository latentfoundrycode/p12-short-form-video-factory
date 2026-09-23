# TASK — vendor GSAP so the local renderer makes no CDN call (H1)

## Why
`sfvf.media.graphics._index_html` injects `<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js">`
into the HTML that both `render` (`_render_with_hyperframes`) and `check` load in a headless browser.
So EVERY render/check makes a live jsDelivr fetch — a network call inside the "otherwise zero-cost
local renderer"; offline (or when jsDelivr is slow/down) renders stall or fail. Fix: vendor the pinned
GSAP locally and inline it into the render/check HTML, so no network call happens at render time.

The SDK is installed editable (`pip install -e sdk`) and `_index_html` already loads a sibling data
file pattern (see `dom_check.mjs` via `Path(__file__).with_name(...)`), so a vendored
`sdk/sfvf/media/gsap.min.js` is available at runtime with no packaging change (hatchling's
`packages = ["sfvf"]` also ships it in a wheel).

Frozen RED test (committed, do not modify):
`tests/sdk/test_graphics.py::test_index_html_inlines_gsap_and_makes_no_cdn_call` — `_index_html(...)`
must contain no `cdn.jsdelivr.net`, must still use `gsap.timeline`, must inline the module constant
`_GSAP_JS`, and `sdk/sfvf/media/gsap.min.js` must exist.

## Changes

### 1. Vendor the pinned GSAP (exact version already used)
Download the EXACT pinned file the code currently references to `sdk/sfvf/media/gsap.min.js`:
```
curl -fsSL https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js -o sdk/sfvf/media/gsap.min.js
```
Verify it is genuine before proceeding: the file must be ~70 KB of minified JS, contain the GreenSock
license banner (`grep -c GreenSock sdk/sfvf/media/gsap.min.js` ≥ 1), and define `gsap` (contains the
token `gsap`). Do NOT modify the downloaded contents. (GSAP 3.14.2 core is under the GreenSock
standard "no charge" license; this is a straight vendoring of the dependency already in use.)

### 2. `sdk/sfvf/media/graphics.py` — load it once and inline it
Add a module-level constant that reads the vendored file at import (near the other module constants):
```python
_GSAP_JS = (Path(__file__).resolve().with_name("gsap.min.js")).read_text(encoding="utf-8")
```
In `_index_html`, replace the CDN script tag:
```python
        '    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>\n'
```
with the inlined runtime:
```python
        "    <script>\n" + _GSAP_JS + "\n</script>\n"
```
(Keep everything else in `_index_html` unchanged — the `gsap.timeline` bootstrap script, styles,
`data-*` attributes. The inlined `<script>` must come before the body's timeline bootstrap, exactly
where the CDN tag was, so `gsap` is defined when the bootstrap runs.)

## Scope / do NOT
- Only `sdk/sfvf/media/graphics.py` and the new vendored `sdk/sfvf/media/gsap.min.js`. Do NOT change
  `render`, `check`, `_render_with_hyperframes`'s node invocation, the hyperframes.json, any test, or
  any other file. No new Python dependencies. Do NOT edit the vendored GSAP source.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/sdk/test_graphics.py -q` → all pass, including
  `test_index_html_inlines_gsap_and_makes_no_cdn_call`.
- `ruff check sdk tests` and `ruff format --check sdk tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
  (Note: `ruff`/`mypy` target Python; the vendored `.js` is data and is not linted.)
- The render/check integration tests (`tests/integration/test_graphics_render.py`,
  `tests/integration/test_composition_check.py`) drive the HyperFrames node toolchain and are
  environment-flaky on some Windows dev boxes; they are the CI signal, not the local gate. Do not
  chase them locally — the unit test above is the local signal.
