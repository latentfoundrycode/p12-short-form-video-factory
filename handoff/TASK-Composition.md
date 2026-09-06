# TASK Composition — legible, word-timed caption composition for the explainer

**Builder:** Cursor. **Product code only** in `workflows/explainer/main.py` (the `_composition_html`
function). Do NOT touch `tests/`, `docs/`, `handoff/`, the SDK, or anything else. The reviewer contract
`tests/integration/test_explainer_composition.py` is FROZEN.

The first real end-to-end video rendered dark-grey text on a near-black background (unreadable) and dumped
the entire script as a static paragraph. Rework `_composition_html` into a proper short-form caption
composition: high-contrast, real webfont, and **karaoke-style word timing** — each spoken word appears in
sync with the narration, animated on the GSAP timeline HyperFrames drives. This is modelled on
HyperFrames' own `caption-highlight` example (studied); the pattern below is proven.

## The runtime contract (how HyperFrames drives it)

`_composition_html(script, timings, css_path)` returns an HTML **fragment** that is embedded inside
`_index_html`'s `<div id="root" data-composition-id="main" data-start="0" data-duration="…">`. That
wrapper already: loads GSAP (`gsap@3.14.2`), sets `background:#101418`, and after the fragment runs
`window.__timelines["main"] ||= gsap.timeline({paused:true})`. HyperFrames then **seeks the timeline
registered at `window.__timelines["main"]`** to each frame's time.

So the fragment must **build a paused GSAP timeline with the caption animation and assign it to
`window.__timelines["main"]`** (the `||=` in the wrapper then keeps yours). Return a fragment —
`<style>…</style>` + the caption container `<div>` + a `<script>` — NOT a full `<!doctype html>` document
(the current code wrongly returns a nested document; drop that, drop the `@import`-of-css_path full-doc
wrapper, and drop the static full-`script` paragraph). `script` and `css_path` params stay in the
signature but are no longer rendered as on-screen text (the on-screen text is the timed words); you may
ignore `css_path` now.

## What to generate

Frame is portrait **1080×1920** on the wrapper's dark `#101418`. Build (all sizes/colours are the spec):

1. **Webfont + styles** (in a `<style>`): load **Montserrat 800** from Google Fonts
   (`@import url("https://fonts.googleapis.com/css2?family=Montserrat:wght@800&display=swap");`).
   A caption container fixed to the frame, words centred in the lower-middle safe area:
   - container: `position:absolute; left:0; right:0; bottom:22%;` (inside the TikTok safe zone),
     `display:flex; flex-wrap:wrap; justify-content:center; align-items:flex-end; gap:10px;
     padding:0 90px;`
   - `.cap-word`: `font-family:"Montserrat",sans-serif; font-weight:800; font-size:76px;
     text-transform:uppercase; color:#ffffff; letter-spacing:0.02em; line-height:1.05;
     position:relative; padding:6px 14px; text-shadow:0 6px 20px rgba(0,0,0,0.5);`
   - `.cap-word .bg` (the karaoke pill): `position:absolute; inset:0; z-index:-1; border-radius:12px;
     background:linear-gradient(135deg,#38bdf8,#2563eb); opacity:0; transform:scaleX(0);
     transform-origin:0% 50%;`
   - `.cap-group`: `opacity:0; visibility:hidden;` (shown per-group by the timeline)

2. **Word/group data → markup + timeline.** In the `<script>`:
   - Escape every word's text for BOTH markup and the JS string (words are model output — untrusted).
     Prefer building the JS `WORDS` array in Python with `json.dumps` (safe), and HTML-escape the word
     when writing span text (use `html.escape`). Never interpolate a raw word into markup or JS.
   - **Group** the words into phrases of **up to 4 words**. For group `g` (words `[i..j]`):
     `g.start = words[i].start`; `g.end = min(words[j].end + 0.4, nextGroupStart - 0.05)` where
     `nextGroupStart` is the next group's first word start (or `words[j].end + 0.4` for the last group).
   - Render each group as a `.cap-group` div containing one `.cap-word` span per word (each span holds a
     `.bg` pill span + the escaped word text). Give words stable ids so the script can target them.
   - Build `var tl = gsap.timeline({paused:true});` and per group:
     `tl.set(group,{visibility:"visible"}, g.start);`
     `tl.fromTo(group,{opacity:0},{opacity:1,duration:0.12,ease:"power2.out"}, g.start);`
     and per word: `tl.to(bg,{opacity:1,scaleX:1,duration:0.12,ease:"power2.out"}, w.start);`
     `tl.to(bg,{opacity:0,scaleX:1.02,duration:0.1,ease:"power2.in"}, w.end);`
     then `tl.to(group,{opacity:0,duration:0.1}, g.end-0.1); tl.set(group,{visibility:"hidden"}, g.end);`
   - `tl.seek(0); window.__timelines["main"] = tl;`
   - **Empty `timings`:** still emit the `<style>` + an empty container + a script that creates
     `var tl = gsap.timeline({paused:true}); window.__timelines["main"] = tl;` (no crash, valid fragment).

Keep the Python readable and ruff-clean; a small helper to build groups is fine. Do not add new imports
beyond stdlib (`html`, `json` are fine). mypy does not check `workflows/`.

## Acceptance

`tests/integration/test_explainer_composition.py` passes (3): every word + its start/end appear; the
fragment registers `window.__timelines["main"]` and uses `gsap.timeline`; an explicit light colour
(`#ffffff`) and a Google webfont are present; model word text is HTML-escaped; empty timings still yield a
valid fragment with a timeline. The rest of the suite still passes (dry-run explainer, graphics render).

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -q tests/integration/test_explainer_composition.py
```
(The supervisor renders the composition and inspects real frames for legibility before merge — visual
quality is judged there, not in CI. Pre-existing HyperFrames `finalize`/`example_workflow` failures in a
bare worktree are the missing toolchain; ignore them.)
