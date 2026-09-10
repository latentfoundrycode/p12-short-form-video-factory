# TASK E-2a — composition-DOM `check()` (§5.8 rows 6-8, §6.5)

## Goal (one sentence)
Implement `media.graphics.check(composition_html, *, safe_zone=True) -> list[Violation]` as a real
headless-browser DOM inspection (four violation classes) that loads the composition once and reports
the failures a rendered frame cannot reveal — replacing the A-5 stub.

## Governing spec (verbatim — SDK §6.5 "`check()` — the failures that render perfectly")
> A composition written by an agent fails in ways no frame-sampling check catches: a chart
> positioned off-screen, a heading clipped mid-word, text under the platform's own buttons, a font
> that did not load so every glyph is an empty box. The video encodes cleanly, the frames are not
> black, the audio is fine, and the result is unusable.
>
> `check()` loads the page once, headless, and inspects the DOM:
>
> | Check | How |
> |---|---|
> | Element outside the viewport | bounding box against the viewport |
> | Element intersecting the safe zone | bounding box against `safe_zone_css()` margins |
> | Truncated text | `scrollWidth`/`scrollHeight` exceeding the client box |
> | Missing font | text nodes rendering at fallback metrics |
>
> No AI, deterministic, and effectively free. `finalize()` runs it automatically whenever a
> composition render is among its inputs, and violations fail the video rather than warning — a chart
> drawn off-screen is not a borderline case. Call it yourself while iterating, before spending
> anything on narration.

(The `finalize()` auto-invocation is the NEXT increment, E-2b — do NOT wire finalize here.)

Also Architecture §5.8 rows 6-8:
> | Nothing is drawn outside the frame or under the platform's interface | query the composition's DOM for bounding boxes crossing the viewport or the safe zone |
> | No text is clipped mid-word | compare each element's scroll extent against its client box |
> | Fonts actually loaded | check text nodes for fallback metrics |

## Frozen contract (already committed — do NOT edit any test)
`tests/integration/test_composition_check.py` (toolchain-gated). Frozen surface:
`check(composition_html, *, safe_zone=True) -> list[Violation]` where each `Violation` is the
existing `{"kind": str, "detail": str}` TypedDict in `sdk/sfvf/media/graphics.py`. The four `kind`
values are EXACTLY: `"outside-viewport"`, `"safe-zone"`, `"text-clipped"`, `"missing-font"`. A clean
composition returns `[]`. `tests/sdk/test_graphics.py` (the non-render surface) must stay green.

## What to implement

### 1. A headless DOM-inspection Node script (new file, e.g. `sdk/sfvf/media/dom_check.mjs`)
Launch headless Chrome with **puppeteer-core** (already in `tools/hyperframes/node_modules`), load the
composition, measure, and print a JSON array of `{kind, detail}` to stdout (and nothing else on
stdout). Exit 0 on success; on any internal error, write the message to stderr and exit non-zero.

- **Module resolution.** The script lives in the SDK but its deps live in the toolchain. Resolve them
  with `createRequire` anchored at the toolchain, whose path Python passes as an argument:
  ```js
  import { createRequire } from "node:module";
  const require = createRequire(toolchainPkgJsonUrl); // e.g. file://…/tools/hyperframes/package.json
  const puppeteer = require("puppeteer-core");
  const browsers = require("@puppeteer/browsers");
  ```
- **Chrome resolution** (mirror how the toolchain resolves it, so it works in dev AND CI where the
  renderer already runs): in order — (a) env `PUPPETEER_EXECUTABLE_PATH` / `HYPERFRAMES_BROWSER_PATH`
  if set and exists; (b) `browsers.getInstalledBrowsers({ cacheDir })` for the default puppeteer cache
  dir (`PUPPETEER_CACHE_DIR` or `~/.cache/puppeteer`), picking an installed Chrome or
  chrome-headless-shell and using its `.executablePath`. Launch `puppeteer.launch({ headless: true,
  executablePath, args: ["--no-sandbox","--disable-dev-shot-usage"] })` (whatever flags the platform
  needs; keep it minimal).
- **Serve the composition over HTTP** (not `file://`, so `@import url("artifacts/…")` and fonts
  resolve exactly as in a real render). Start a tiny local static server on an ephemeral port over the
  temp project dir Python provides, `page.goto("http://127.0.0.1:<port>/index.html", {waitUntil:
  "networkidle0"})`, and close it in a `finally`.
- **Settle before measuring** (inspect the initial loaded state — a single sample at t=0, matching
  "loads the page once"): set viewport 1080×1920; `await page.evaluateHandle("document.fonts.ready")`;
  await all `document.images` load/error; a couple of `requestAnimationFrame` ticks. (Time-sampling of
  animated compositions is explicitly out of scope for E-2a — note it, do not build it.)
- **Measure** in one `page.evaluate` over every element under `#root` (skip `script`/`style`/`head`;
  skip elements whose `getBoundingClientRect()` has width≤0 or height≤0 — not rendered). Use a pixel
  tolerance `EPS = 2`. W=1080, H=1920. Safe-zone margins from the tiktok percentages: top=0.10·H=192,
  right=0.15·W=162, bottom=0.15·H=288, left=0 → safe area x∈[0,918], y∈[192,1632].
  - **content element** = one with a DIRECT non-whitespace text child node, OR a replaced element
    (`IMG`,`SVG`,`CANVAS`,`VIDEO`,`PICTURE`). Only content elements get the geometry/text checks.
  - **full-frame background** = rect covers the whole frame within EPS (`left≤EPS && top≤EPS &&
    right≥W-EPS && bottom≥H-EPS`). These are intentional backgrounds → SKIP outside-viewport AND
    safe-zone for them (they legitimately fill the frame and its margins).
  - **outside-viewport**: content, not full-frame, and `left<-EPS || top<-EPS || right>W+EPS ||
    bottom>H+EPS` → `{kind:"outside-viewport", detail: "<selector/tag> extends to (l,t,r,b) outside 1080x1920"}`.
  - **safe-zone** (only when the `safe_zone` arg is true, and only for elements NOT already flagged
    outside-viewport): content, not full-frame, and `top<192-EPS || right>918+EPS || bottom>1632+EPS
    || left<0-EPS` → `{kind:"safe-zone", detail: "<selector/tag> intersects the reserved safe zone"}`.
  - **text-clipped** (content with direct text): the element clips its overflow (computed `overflow-x`
    or `overflow-y` ∈ {hidden, clip, scroll, auto}) AND `scrollWidth-clientWidth>EPS ||
    scrollHeight-clientHeight>EPS` → `{kind:"text-clipped", detail: "…"}`.
  - **missing-font** (content with direct text): after `document.fonts.ready`, collect the family
    names of every `FontFace` in `document.fonts` whose `.status === "error"` (normalise: strip
    quotes, lowercase). If the element's computed primary `font-family` token matches one of those
    errored families, it is rendering at fallback metrics → `{kind:"missing-font", detail: "…"}`.
  Every `detail` must be a non-empty human-readable string (selector/tag + the measurement).

### 2. `check()` in `sdk/sfvf/media/graphics.py`
Replace the stub body. Require an active context (`current_context()` — raises when none, keep that).
Remove the `dry_run` gate entirely (check runs identically in both modes). Build a temp project the
same way `_render_with_hyperframes` does — write `index.html` via the existing `_index_html(...)`
(use the composition duration `0.0` or a small default; it only affects the paused timeline, not the
static inspection), and `shutil.copytree(ctx.paths.artifacts, project/"artifacts")` **only if that
dir exists**. Run the node script (reuse the module's `_run(...)` runner and the `node`/`_hyperframes_entry`
patterns — pass the script path, the toolchain `package.json` URL for `createRequire`, the project
dir, and `safe_zone`). Parse the stdout JSON array into `list[Violation]` and return it. A non-zero
exit or unparseable output → `RuntimeError` (do not silently return `[]`). Clean up the temp project
in a `finally` (like `_render_with_hyperframes`).

## Constraints / do-nots
- Do NOT edit any test or change the frozen `check()` signature or the `Violation` shape.
- Do NOT wire `finalize()` here and do NOT persist composition HTML — that is E-2b.
- Do NOT add time-sampling of animated compositions, motion checks, or the HyperFrames layout-audit
  machinery. Implement the SIMPLE §6.5 methods only (getBoundingClientRect, scrollWidth/clientWidth,
  errored @font-face). Keep it deterministic and free.
- No new Python or npm dependencies (puppeteer-core + @puppeteer/browsers are already in the pinned
  toolchain; stdlib + node only). Keep `ruff`, `ruff format`, and `mypy --strict` clean; match the SDK
  style in `graphics.py`.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/integration/test_composition_check.py -q` → all pass.
- `-m pytest tests/sdk/test_graphics.py tests/integration/test_graphics_render.py -q` → green.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
