# TASK A-5 — `sfvf.media.graphics` dry-run stubs (composition)

**Builder:** Cursor. **Product code only.** Do NOT modify, add, or delete anything under `tests/`
(including `tests/stubs/`), `docs/`, or `handoff/`. The reviewer contract `tests/sdk/test_graphics.py` is
FROZEN — make it pass by changing product code.

Fifth increment of **Stage A**. Adds `sfvf.media.graphics` (SDK §6.5) as FFmpeg-backed dry-run stubs; the
real HyperFrames provider is Stage B. Follows the A-3/A-4 pattern: file-producing results are
**video-relative path strings** (JSON-native) so a `render` result caches via `ctx.step` (SDK §5.5).

Files you may touch: `sdk/sfvf/media/graphics.py` (new), `sdk/sfvf/media/__init__.py`. Do not add
dependencies (use the A-1 FFmpeg core).

## `sdk/sfvf/media/graphics.py`

```python
render(composition_html, *, duration_s) -> str
captions(audio, timings, style) -> str
safe_zone_css() -> str
check(composition_html, *, safe_zone=True) -> list[Violation]
```

- `Violation` — a JSON-native `TypedDict` (e.g. `class Violation(TypedDict): kind: str; detail: str`).
- Read the ambient Context with `from .._runtime import current_context`. Do not accept `ctx`.
- All file-producing functions write into `ctx.paths.artifacts`, using **deterministic content-derived
  filenames** (first 8 hex of a `sha256` over the relevant inputs), and return the file's path **relative to
  `ctx.paths.video`** as a POSIX string (e.g. `"artifacts/render-<sha>.mp4"`). Create `ctx.paths.artifacts`
  if needed. Same inputs → identical relative path (deterministic, even across video folders).
- **`render(composition_html, *, duration_s)`** — dry-run: a colour-bars clip of `duration_s` via
  `sfvf._ffmpeg.color_bars(dest, duration_s=duration_s, width=W, height=H, fps=FPS)`. A fixed default size
  is fine (e.g. 1080×1920 @ 30, the default vertical short); real per-`[output]` sizing is Stage B/later.
  Filename from `sha256(composition_html + duration_s)`. **Not dry-run → `NotImplementedError`** (HyperFrames
  is Stage B).
- **`captions(audio, timings, style)`** — dry-run: write a minimal subtitle file (a `.srt` or `.vtt`) built
  from `timings` (each `{word,start,end}` → a cue) into artifacts; return its video-relative path. Filename
  from `sha256` over `audio` + the JSON of `timings` + `style`. **Not dry-run → `NotImplementedError`.**
- **`safe_zone_css()`** — write a small CSS file (a fixed safe-zone: e.g. padding margins) into artifacts and
  return its video-relative path. This is format logic, not a HyperFrames call, so it works in **both** dry
  and non-dry modes (do not raise). (`[output]`-aware margins are deferred — `[output]` is not in the
  runtime Context yet.)
- **`check(composition_html, *, safe_zone=True)`** — dry-run: return `[]` (no violations). **Not dry-run →
  `NotImplementedError`** (real DOM inspection is HyperFrames, Stage B).
- Do not emit a cost event (deferred to Stage C).

## `sdk/sfvf/media/__init__.py` — expose `graphics`

Add `graphics` alongside `speech`: `from . import graphics, speech` and `__all__ = ["graphics", "speech"]`.

## Acceptance (the frozen contract `tests/sdk/test_graphics.py`)

- `render` raises (via `current_context`) with no active Context.
- Dry-run: `render` returns a video-relative path to a real clip whose probed duration ≈ `duration_s`
  (±0.2s), and is deterministic across video folders; `captions` and `safe_zone_css` return video-relative
  paths to real files; `check` returns `[]`. All returns are JSON-serializable.
- `render` raises `NotImplementedError` outside dry-run.

## Full local gate (all six must pass — run from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```

Do not weaken, skip, or edit any test to make the gate pass.
