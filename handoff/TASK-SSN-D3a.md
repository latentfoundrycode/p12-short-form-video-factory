# TASK-SSN-D3a — Composite the visual bed behind the centered captions

## Context

D2 sources a visual `bed` (a dict `{"assets": [...], "source_urls": [...]}`; each asset is
`{"kind": "clip"|"web"|"still", "path": <rel>, "start": <s>, "end": <s>, "url": ..., "ken_burns":
<bool>}`). This task DRAWS that bed behind the centered captions in ONE HyperFrames composition
(approach a). D3b (next) adds audio + description. Compositing approach a is confirmed: HyperFrames
composes timed `<img>`/`<video>` elements and captures a GSAP timeline frame-by-frame.

## Scope — edit ONLY this file

- `workflows/sensational-science-news/main.py`

Change `_composition_html` (add a `bed` parameter and render it) and the `run()` call site (pass the
bed). Do not touch tests, SDK, other workflows, or deps. Stay in this checkout.

## Frozen tests to make green (read them first)

- `tests/integration/test_ssn_composite.py`:
  - `test_composition_includes_visual_bed` (fast): bed asset paths present; a clip is a `<video>`; a
    static image has a GSAP `scale` (Ken-Burns); captions still present.
  - `test_nondry_kenburns_clears_slideshow` (SLOW — real render via node/HyperFrames + ffmpeg): a
    Ken-Burns still over a textured fixture must render with enough motion that
    `_review.content_review(...).slideshow is False`. **This is the acceptance checkpoint — tune the
    Ken-Burns magnitude until it passes.**
- Keep `tests/integration/test_ssn_captions.py` and `test_ssn_workflow_dry_run.py` green.

## What to build

### `_composition_html(script, timings, css_path, bed=None)`

Add a fourth parameter `bed` (default `None`). When `bed` is falsy, behave exactly as today
(captions only — keeps existing tests green). When `bed` has assets, render a BED LAYER behind the
captions and drive it from the SAME GSAP timeline.

1. **Markup** — build a bed layer placed in the DOM BEFORE `<div id="captions">` so it paints under
   the captions:
   ```
   <div id="bed">{bed_markup}</div>
   ```
   For each asset `i` (use the artifact path as the element `src`; `html.escape` it):
   - static (`kind` in `("web","still")`):
     `<img id="bed{i}" class="bed-item" src="{escape(path)}">`
   - clip (`kind == "clip"`):
     `<video id="bed{i}" class="bed-item" src="{escape(path)}" data-start="{start}"
       data-duration="{end-start}" data-media-start="0" muted></video>`
     (the `data-start`/`data-duration` let HyperFrames play the correct video window).

2. **CSS** — add rules (in the same `<style>`):
   - `#bed {{ position:absolute; inset:0; z-index:0; overflow:hidden; }}`
   - `.bed-item {{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover;
     opacity:0; visibility:hidden; will-change:transform,opacity; }}`
   - Ensure the captions paint ABOVE the bed: give `#captions` and `.cap-group` a `z-index:2` (add it;
     keep their existing centering rules).

3. **GSAP timeline** — in the existing `<script>` that builds `var tl = gsap.timeline({{paused:true}})`,
   BEFORE `window.__timelines["main"] = tl;`, add tweens for each bed asset onto `tl`:
   - show at its start, hide at its end:
     `tl.set("#bed{i}", {{visibility:"visible"}}, {start}); tl.fromTo("#bed{i}", {{opacity:0}},
     {{opacity:1, duration:0.2}}, {start}); tl.to("#bed{i}", {{opacity:0, duration:0.2}}, {end}-0.2);
     tl.set("#bed{i}", {{visibility:"hidden"}}, {end});`
   - for STATIC assets (`ken_burns` true), add a KEN-BURNS pan/zoom tween spanning the beat:
     `tl.fromTo("#bed{i}", {{scale:1.0, xPercent:0, yPercent:0}}, {{scale:1.18, xPercent:-5,
     yPercent:-4, duration:{end}-{start}, ease:"none"}}, {start});`
     Alternate the pan direction per still (e.g. sign by index parity) so consecutive stills don't all
     drift the same way. The `scale`/pan MAGNITUDE must be large enough that the real render clears the
     slideshow motion threshold — the non-dry test is the arbiter; increase the zoom/pan if it fails.
   - Do NOT use a CSS `@keyframes animation` for Ken-Burns — the seek-based renderer would not capture
     it and it would not generate inter-frame motion. It MUST be a GSAP tween on `tl`.
   - Clips already move; give them show/hide only, no Ken-Burns.
   - Build the per-asset JS by string-joining over `bed["assets"]` (mirror how the caption GROUPS JS is
     built). You may compute the values in Python and interpolate, or emit a small JSON array and
     `forEach` it — either is fine; keep `json.dumps(..., ensure_ascii=True)` if you emit JSON.

Do not change the caption markup/animation itself (only add `z-index:2`).

### `run()`

Pass the bed to the composition:
`html = _composition_html(narration, speech["timings"], media.graphics.safe_zone_css(), bed)`
(`bed` is already available from the D2 `visual-bed` step.) Everything else (render, finalize, Result)
stays as-is for D3a — audio + description come in D3b.

## Done when (run from Workspace/ with the repo venv)

- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_composite.py -q` — both pass,
  INCLUDING the non-dry `test_nondry_kenburns_clears_slideshow` (it really renders; ensure the
  Ken-Burns motion clears the slideshow verdict — tune magnitude if needed).
- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_captions.py tests/integration/test_ssn_workflow_dry_run.py -q` — still green (the dry-run pipeline renders the finished video with the bed behind the captions).
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news` and
  `./.venv/Scripts/python.exe -m ruff format --check .` — clean.
- `./.venv/Scripts/python.exe -m mypy` — no new errors from `main.py`.

Print the new `_composition_html` bed markup + CSS + the bed GSAP block, and one line on the Ken-Burns
magnitude you settled on to clear the slideshow check.
