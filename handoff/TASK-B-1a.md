# TASK B-1a — HyperFrames render toolchain (pinned) + CI

**Builder:** Cursor. **Config + CI only** (no product/SDK code this increment). Do NOT modify, add, or
delete anything under `tests/`, `docs/`, `handoff/`, or `sdk/`/`app/`. The reviewer contract
`tests/integration/test_hyperframes_toolchain.py` is FROZEN — make it pass by adding the toolchain and CI.

First increment of **Stage B** (the provider layer). It lands the local, zero-cost **HyperFrames**
renderer toolchain that the `media.graphics` adapter will wire onto next (B-1b). Sourcing is the published
npm package, pinned (approved). No auth, no live keys, no cost.

Files you may create/modify: `tools/hyperframes/package.json` (new), `tools/hyperframes/package-lock.json`
(new, generated), `.gitignore`, `.github/workflows/ci.yml`. Do not commit `node_modules`.

## 1. `tools/hyperframes/` — the pinned toolchain

- Create `tools/hyperframes/package.json` with `"dependencies": { "hyperframes": "0.8.26" }` (an **exact**
  version, no `^`/`~`), a `"name"` like `sfvf-hyperframes-toolchain`, `"private": true`, and
  `"description"`. Then run `npm install` in `tools/hyperframes/` to generate `package-lock.json` (commit
  the lock; it pins the whole dependency tree). Do **not** commit `tools/hyperframes/node_modules/`.
- Add `tools/hyperframes/node_modules/` (or `tools/**/node_modules/`) to `.gitignore`.

The renderer entry point after install is `tools/hyperframes/node_modules/hyperframes/bin/hyperframes.mjs`,
invoked via `node`. The frozen test asserts `package.json` pins `hyperframes` to exactly `0.8.26` and that
`package-lock.json` exists, then (when installed) renders a 1s 1080×1920 composition and probes it.

## 2. `.github/workflows/ci.yml` — install + exercise the toolchain in CI

HyperFrames needs **Node 22+** and a headless Chrome; the render is the least-CI-testable surface, so CI
must install and exercise it.

- **Bump the job's Node from 20 to 22** in the existing `Set up Node` step (`node-version: "22"`). Vite 8 +
  React 19 support Node 22 (Vite 8 wants ≥ 20.19/22), so the frontend checks still pass; keep everything
  else about that step (npm cache, cache-dependency-path) unchanged. Update the step name to match.
- Add a **`Install HyperFrames toolchain`** step (id `deps_hf`) after the other installs and before the
  checks:
  - `npm ci` in `tools/hyperframes` (working-directory or `--prefix`), then
  - install its browser so rendering works headless in CI:
    `node tools/hyperframes/node_modules/hyperframes/bin/hyperframes.mjs browser install`
    (set env `HYPERFRAMES_SKIP_SKILLS: "1"` on this step and on the pytest step to skip the network skills
    check). If `hyperframes browser` uses a different install subcommand in 0.8.26, use `hyperframes browser
    --help` to find it; the goal is that `chrome-headless-shell` is present for the render.
- The **pytest** step must additionally require `steps.deps_hf.conclusion == 'success'` in its `if:` guard
  (so the render test actually runs in CI, not skips), and set `env: HYPERFRAMES_SKIP_SKILLS: "1"`. Leave
  the other five checks' guards as they are — they don't need HyperFrames. FFmpeg (already installed via
  `deps_ffmpeg`) must remain on PATH for the render.

## Acceptance (frozen contract `tests/integration/test_hyperframes_toolchain.py`)

- `test_hyperframes_toolchain_is_pinned` — `tools/hyperframes/package.json` exists and pins
  `hyperframes == 0.8.26`; `package-lock.json` exists. (This one must pass everywhere, installed or not.)
- `test_hyperframes_renders_a_composition_to_mp4` — with the toolchain installed (your `npm ci` + browser),
  rendering a minimal composition yields a valid **1080×1920** MP4. It is `skipif` the toolchain isn't
  installed, so **you must actually run `npm ci` in `tools/hyperframes` and install the browser in your
  worktree** and confirm this test RUNS (not skips) and passes before reporting.

## Full local gate (run from the worktree venv; install the toolchain first)

```
npm ci --prefix tools/hyperframes
node tools/hyperframes/node_modules/hyperframes/bin/hyperframes.mjs browser install
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```

Report whether `test_hyperframes_renders_a_composition_to_mp4` RAN (not skipped) and passed. Do not weaken,
skip, or edit any test.
