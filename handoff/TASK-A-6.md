# TASK A-6 — `sfvf.finalize`, the mandatory last step

**Builder:** Cursor. **Product code only.** Do NOT modify, add, or delete anything under `tests/`
(including `tests/stubs/`), `docs/`, or `handoff/`. The reviewer contract `tests/sdk/test_finalize.py` is
FROZEN — make it pass by changing product code.

Sixth increment of **Stage A**. Implements `finalize(video, audio=None, captions=None)` (SDK §6.9) — every
workflow's required final call. Unlike the provider stubs, this is **real FFmpeg** work in both dry and
non-dry modes (FFmpeg is local/free): it applies the house format and runs a structural self-review.

Files you may touch: `sdk/sfvf/finalize.py` (new), `sdk/sfvf/media/__init__.py`, `sdk/sfvf/__init__.py`. Do
not add dependencies (use `ffmpeg`/`ffprobe` directly, mirroring the style of `sdk/sfvf/_ffmpeg.py`).

## 1. `sdk/sfvf/finalize.py` (new)

```python
finalize(video, audio=None, captions=None) -> str
```

- `video`, `audio`, `captions` are **video-relative path strings** (as produced by `media.graphics.render`,
  `media.speech.speak`, `media.graphics.captions`). Read the ambient Context via `from ._runtime import
  current_context`; do not accept `ctx`.
- **Resolve-then-confine each input** to the video folder, matching the project's path standard (as in
  `runner._result_event` / the cache restore): `root = ctx.paths.video.resolve()`;
  `p = (root / rel).resolve()`; if `not p.is_relative_to(root)` raise `ValueError`. Raise if a given input
  file does not exist.
- **Apply the house format** with one FFmpeg invocation producing `ctx.paths.video / "final.mp4"`:
  - Video: scale/pad to **1080×1920** (the PRD default vertical short), **30 fps**, `libx264`,
    `-pix_fmt yuv420p`. (Per-`[output]` sizing is deferred — `[output]` is not in the Context yet; use these
    fixed house values.)
  - Audio (only if `audio` given): include it, AAC, and normalise loudness toward **-14 LUFS**
    (`loudnorm`, single pass is fine). If no `audio`, the output has no audio track.
  - Captions (only if `captions` given): mux the subtitle file as a **soft** subtitle stream
    (`-c:s mov_text` in the mp4). Do not burn — soft-mux is reliable across FFmpeg builds and satisfies
    "captions present".
  - Deterministic: no clock/RNG. Overwrite (`-y`).
- **Structural self-review** on the output (probe it with the same ffprobe approach as `_ffmpeg.probe`, or
  reuse `_ffmpeg.probe`): the file must exist and be valid; have a **video** stream; `duration > 0`;
  resolution exactly **1080×1920**; an **audio** stream present iff `audio` was given; a **subtitle** stream
  present iff `captions` was given. If any check fails, **raise** (a clear `RuntimeError`) so the video is
  marked failed (SDK §3.4/§5.8). Do NOT run content checks (silence/clipping, black frames, slideshow) — on
  dry-run stubs (silent audio, static colour-bars) they would false-fail; they are deferred to Stage E.
- Return the finished file's path **relative to `ctx.paths.video`** as a POSIX string — i.e. `"final.mp4"`.
- No cost event.

`_ffmpeg.probe` currently reports `duration`, `width`, `height`, `has_audio`. You may need to know whether a
**subtitle** stream is present for the self-review; compute that yourself in `finalize` (e.g. a small
ffprobe call for `codec_type == "subtitle"`), OR extend `_ffmpeg` — but if you touch `_ffmpeg.py` keep its
existing API and tests intact (they are frozen elsewhere). Prefer computing it locally in `finalize.py`.

## 2. Exposure — `sfvf.finalize` and `media.finalize`

Both names must resolve to the **same function** (SDK §6.9 calls it `sfvf.finalize`; §11.1 calls it
`media.finalize`):
- `sdk/sfvf/__init__.py` — `from .finalize import finalize`; add `"finalize"` to `__all__`.
- `sdk/sfvf/media/__init__.py` — `from ..finalize import finalize`; add `"finalize"` to `__all__`
  (alongside `graphics`, `speech`). (`sfvf.finalize is media.finalize` must hold.)

## Acceptance (the frozen contract `tests/sdk/test_finalize.py`)

- `sfvf.finalize is media.finalize`.
- `finalize` raises (via `current_context`) with no active Context.
- Full path (video+audio+captions, built from the A-4/A-5 stubs) → returns `"final.mp4"`; the file is a
  valid 1080×1920 mp4 with `duration > 0` and an audio stream.
- Video-only → valid 1080×1920 mp4.
- A missing input path raises; a `..`-escaping input path raises.

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
