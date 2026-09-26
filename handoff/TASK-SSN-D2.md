# TASK-SSN-D2 — Source a per-beat visual bed (mostly Ken-Burns stills + 1-2 clips)

## Context

The workflow currently renders centered captions over a plain background. This task SOURCES a visual
bed: the narration is split into time BEATS, and each beat gets a visual — a static image (free-commons
web image, or an AI still) or a short AI clip. Balanced default (design §3.5): MOSTLY STILLS + AT MOST
2 CLIPS, static images flagged for Ken-Burns pan/zoom, web source URLs collected for the description,
all under an ~$8/video budget. **D2 only sources the bed; D3 composites it** into the final video and
runs the non-dry motion check — so here the bed is produced and stored, not yet drawn.

## Scope — edit ONLY this file

- `workflows/sensational-science-news/main.py`

No new third-party imports (stdlib + the existing `from sfvf import Context, Result, agents, media`).
Do not touch tests, the SDK, other workflows, or dependencies. Stay in this checkout.

## The frozen tests to make green (read them first)

- `tests/integration/test_ssn_visual_bed.py` (4 tests): `_beats`, and `_source_visual_bed`
  (mostly-stills/≤2-clips, Ken-Burns on statics, web source URLs collected).

## SDK you will use (all stub in dry-run — no keys needed for tests)

- `media.web.search(query, *, sources=("commons",), limit=, licence=None) -> list[ImageCandidate]`
  (a candidate is a dict with `url`, `licence`, `title`, …); `media.web.fetch(candidate) -> str`
  (local rel path); `media.web.check_relevance(image_relpath, *, subject) -> Relevance` (a dict-like
  with `.["relevant"]` / `["score"]`). Dry-run: search returns stub candidates, fetch writes a stub
  image, relevance returns relevant=True.
- `media.image.generate(prompt, *, model, size=None) -> str` (rel path). Dry-run: writes a stub image.
- `media.video.generate(prompt, *, model, duration_s=None) -> str` (rel path). Dry-run: writes stub
  color-bars video.
- `ctx.step(...)`, `ctx.video_count`, `ctx.dry_run`.

## What to build

### 1. Module constants

```python
_BEAT_S = 6.0            # target seconds per beat
_MAX_CLIPS = 2           # balanced default: at most 2 short clips (hook + one hypothetical)
_CLIP_DURATION_S = 5.0   # ~4-5 s AI clips
_IMAGE_MODEL = "google/gemini-3.1-flash-image"
_CLIP_MODEL = "byteplus/seedance-2.5"
_WEB_SEARCH_LIMIT = 6
```

### 2. `_beats(duration_s: float) -> list[dict]` (pure)

Segment `[0, duration_s]` into contiguous, non-overlapping beats of ~`_BEAT_S` seconds. Compute
`n = max(1, round(duration_s / _BEAT_S))`, then produce `n` equal beats each
`{"index": i, "start": <float>, "end": <float>}`, with `beats[0]["start"] == 0.0` and
`beats[-1]["end"] == duration_s` (spread any rounding into the last beat so coverage is exact and
contiguous).

### 3. `_source_visual_bed(ctx, *, subject: str, beats: list[dict]) -> dict`

Return `{"assets": [<one per beat, in beat order>], "source_urls": [<web image URLs used>]}`. Each
asset is `{"kind": "clip"|"web"|"still", "path": <rel>, "start": beat["start"], "end": beat["end"],
"url": <str|None>, "ken_burns": <bool>}`.

Selection (deterministic):
- **Clips** — reserve clips for the HOOK (beat 0) and, when `len(beats) >= 4`, ONE closing
  hypothetical (the last beat). Never more than `_MAX_CLIPS`. For a clip beat, call
  `media.video.generate(f"<a vivid ~5s shot for: {subject}>", model=_CLIP_MODEL,
  duration_s=_CLIP_DURATION_S)`; asset kind `"clip"`, `url=None`, `ken_burns=False` (a clip already
  moves).
- **Static beats** (all others) — prefer a FREE COMMONS web image, else an AI still:
  1. `cands = media.web.search(subject, sources=("commons",), limit=_WEB_SEARCH_LIMIT)`; for each
     candidate in order, `img = media.web.fetch(cand)` then `rel = media.web.check_relevance(img,
     subject=subject)`; take the FIRST relevant one. Use each commons image for at most one beat
     (don't repeat the same URL across beats — track used URLs). If a relevant, unused commons image
     is found: asset kind `"web"`, `path=img`, `url=cand["url"]`, `ken_burns=True`, and append
     `cand["url"]` to `source_urls`.
  2. Otherwise generate an AI still: `media.image.generate(f"<a striking still for: {subject}>",
     model=_IMAGE_MODEL)`; asset kind `"still"`, `url=None`, `ken_burns=True`.
- Do NOT use the paid `"web"` tier by default (keeps the bed within the ~$8 budget); commons is free
  and AI stills are the paid-but-cheap fallback. (A budget-gated paid-web enrichment can come later;
  leave a one-line comment noting it.)

Every asset's `path` must be a real produced artifact (in dry-run the stubs are written by the SDK).

### 4. Wire it into `run()`

After the `speech` step (so the duration is known), add a step that builds the bed and keep it for D3:

```python
    with ctx.step("visual-bed", inputs={"subject": subject, "duration": speech["duration"]}) as step:
        if not step.cached:
            step.set(_source_visual_bed(ctx, subject=subject, beats=_beats(speech["duration"])))
    bed = step.value
```

Do NOT change the composition/finalize yet — D3 consumes `bed`. So it is used (and observable) in D2
without an unused-variable warning, add one line right after: `ctx.log(f"visual bed: {len(bed['assets'])} assets")`.

Everything after (captions composition, render, finalize, Result) stays as it is for D2.

## Done when (run from Workspace/ with the repo venv)

- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_visual_bed.py -q` — all 4 pass.
- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_workflow_dry_run.py -q` — still
  green (the dry-run pipeline now also builds the bed and still renders the finished video).
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news` and
  `./.venv/Scripts/python.exe -m ruff format --check .` — clean.
- `./.venv/Scripts/python.exe -m mypy` — no new errors from `main.py`.

Print `_beats`, `_source_visual_bed`, and the new `run()` step.
