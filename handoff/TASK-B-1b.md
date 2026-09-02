# TASK B-1b — `media.graphics.render` on real HyperFrames

**Builder:** Cursor. **Product code only.** Do NOT modify, add, or delete anything under `tests/`,
`docs/`, or `handoff/`. The reviewer contracts `tests/integration/test_graphics_render.py` and
`tests/sdk/test_graphics.py` are FROZEN — make them pass by changing product code.

Wire `media.graphics.render` to render **real composed video** through the pinned HyperFrames toolchain
(installed at `tools/hyperframes/` by B-1a), replacing the A-5 colour-bar stub. The renderer is free/local,
so per SDK §10 it runs **REAL in both dry and non-dry modes** — `dry_run` means "no paid spend", not "no
rendering". This is what makes real composed video appear at zero cost.

Files you may touch: `sdk/sfvf/media/graphics.py` only. Do not add Python dependencies. Do not change
`captions`, `safe_zone_css`, or `check`.

## Rewrite `render`

```python
render(composition_html, *, duration_s) -> str
```

- Keep reading the ambient Context via `current_context()` (so calling with no active context still raises).
- **Remove the dry-run gate / `NotImplementedError`** — render in both modes.
- Keep the deterministic filename: `f"render-{_sha8([composition_html, duration_s])}.mp4"` under
  `ctx.paths.artifacts`, and keep returning the path **relative to `ctx.paths.video`** (POSIX). The frozen
  determinism test relies on the same relative name for the same `(html, duration_s)` across video folders.
- **Render via HyperFrames:**
  0. **Copy the video's artifacts into the project so video-relative assets resolve (ROUND-2 FIX, P1).**
     A composition may reference assets the workflow wrote to `ctx.paths.artifacts` (e.g. the safe-zone CSS,
     via `@import url("artifacts/…")`). HyperFrames serves the project over its own HTTP server, so a
     `file://` base does NOT work and the assets must live **inside the project**. Before rendering, copy
     `ctx.paths.artifacts` into `<project>/artifacts/` (e.g. `shutil.copytree(ctx.paths.artifacts,
     project/"artifacts")`), so the served composition's `artifacts/…` references resolve. (Verified: a
     co-located `@import` applies; a `file://` base does not.)
  1. Build a minimal HyperFrames project in a fresh temp dir (`tempfile.mkdtemp()` — clean it up):
     - `hyperframes.json`:
       `{"$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
         "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"}}`
     - `index.html` — the workflow's `composition_html` wrapped so HyperFrames renders it cleanly and fast:
       load GSAP, a `<div id="root" data-composition-id="main" data-start="0" data-duration="{duration_s}"
       data-width="1080" data-height="1920">` containing `composition_html`, and a trailing script that
       provides the readiness signal **without clobbering one the composition registered itself**
       (ROUND-3 FIX): `window.__timelines = window.__timelines || {}; window.__timelines["main"] =
       window.__timelines["main"] || gsap.timeline({ paused: true });`. **That `__timelines["main"]`
       registration is HyperFrames' readiness signal — without it the renderer stalls ~45s and warns; but a
       composition may register its OWN animation timeline under "main", so use `||` to keep an existing one
       and create the empty fallback only when absent.** An unconditional assignment discards the
       composition's animations → static video. Give `<html>`/`<body>` the 1080×1920 size.
  2. Resolve the renderer entry point:
     - `os.environ.get("SFVF_HYPERFRAMES_ENTRY")` if set, else the repo-relative path
       `Path(__file__).resolve().parents[3] / "tools" / "hyperframes" / "node_modules" / "hyperframes" /
       "bin" / "hyperframes.mjs"` (the SDK is editable-installed from `sdk/`, so `parents[3]` is the repo
       root). If neither exists, raise a clear `RuntimeError` naming the missing toolchain and the
       `npm ci` / `tools/hyperframes` install hint.
  3. Run it: `node <entry> render <project_dir> -o <dest> -f 30 --quiet`, with env
     `HYPERFRAMES_SKIP_SKILLS=1` merged into `os.environ`, `check=True`, `capture_output=True`, `text=True`,
     a generous `timeout` (e.g. 300s). On failure raise a `RuntimeError` including the command and captured
     stderr (mirror `sdk/sfvf/_ffmpeg.py`'s `_run` style). **On `TimeoutExpired`, decode `exc.stderr` if it
     is `bytes` (`.decode(errors="replace")`) rather than dropping it (ROUND-2 FIX, P2)** — in text mode
     `TimeoutExpired.stderr` can still be `bytes`, and discarding it loses the renderer's diagnostics.
     FFmpeg and the browser are already present.
  4. Return the video-relative POSIX path (`"artifacts/render-<sha>.mp4"`).
- 1080×1920 @ 30fps is the house format (matches `finalize` and A-6). No cost event.

## Acceptance

- `tests/integration/test_graphics_render.py` (skipped unless `tools/hyperframes` is installed):
  - a red-background composition renders to a valid 1080×1920 ~1s MP4 whose sampled centre pixel is red
    (proving the supplied HTML actually rendered);
  - render succeeds in **non-dry** mode (no `NotImplementedError`);
  - the same `(html, duration_s)` yields the same relative path across two video folders.
- `tests/sdk/test_graphics.py` still passes (captions / safe_zone_css / check / no-active-context unchanged).

## Full local gate (from the worktree venv; the toolchain is installed under tools/hyperframes)

```
$env:HYPERFRAMES_SKIP_SKILLS = "1"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```

Confirm `test_render_produces_real_composed_video` RAN (not skipped) and passed. Do not weaken, skip, or
edit any test.
