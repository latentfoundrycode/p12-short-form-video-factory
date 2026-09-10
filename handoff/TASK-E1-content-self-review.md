# TASK E-1 — content self-review (black / silence / clipping / slideshow) — §5.8

## Goal (one sentence)
Implement `content_review` (the frame/audio §5.8 checks) and wire `finalize` to run it on a real run,
failing the video on any failure — while a dry run skips it.

## Governing spec (verbatim — Architecture §5.8, the rows this increment covers)
> | No black or visibly broken frames | sample frames at several positions and inspect them |
> | Audio is neither silent nor clipping | measure audio levels |
> | The video is not effectively a slideshow | measure how much the image actually changes over time |
>
> **Thresholds follow the declared `[output]` format.** The slideshow measurement in particular
> cannot be one number… None of this involves AI. All of it is cheap.
> Failure marks the video failed rather than presenting it.

`[output]` is not yet in the runtime Context (house format is fixed), so use the module-level
house-format default thresholds already in `sdk/sfvf/_review.py`; per-`[output]` calibration is
deferred (record it as the reason, don't invent an `[output]` plumbing here).

## Frozen contract (already committed — do NOT edit any test)
`tests/sdk/test_content_review.py`. Frozen: the `ContentReview` dataclass (fields + `failures`
property) and `content_review(path, *, expect_audio) -> ContentReview` in `sdk/sfvf/_review.py`.
The existing A-6 `tests/sdk/test_finalize.py` (dry-run) must stay green.

## What to implement

### 1. `content_review(path, *, expect_audio)` in `sdk/sfvf/_review.py`
Use FFmpeg via the module's `_binary`/`_run` (see `sdk/sfvf/_ffmpeg.py`). Measure, then set the
verdicts against the module thresholds:
- **black**: detect black/broken frames — e.g. the `blackdetect` filter over the whole clip (read the
  reported black duration from stderr/metadata); `black=True` when a non-trivial fraction of the clip
  is black. A fully black clip must read True; a normal moving clip must read False.
- **audio** (only when `expect_audio`; else `silent=clipping=False`, `audio_*_dbfs=None`): measure
  mean and peak levels — e.g. the `volumedetect` filter (parse `mean_volume` / `max_volume` in dB).
  `silent = mean <= SILENCE_MEAN_DBFS`; `clipping = peak >= CLIPPING_PEAK_DBFS`. Set
  `audio_mean_dbfs`/`audio_peak_dbfs` to the measured values.
- **slideshow**: measure how much the image changes over time — e.g. the scene score
  (`select='gte(scene,0)',metadata=print` and average the printed `lavfi.scene_score` values, or an
  equivalent motion measure). `motion_score` is that mean; `slideshow = motion_score < SLIDESHOW_MOTION_MIN`.
  A static/solid-colour clip must read True; a moving clip (testsrc2) must read False.
Read-only and tolerant — a normal file must never raise (the caller decides what a failure means).
Return a fully-populated `ContentReview`.

### 2. Wire `finalize` (`sdk/sfvf/finalize.py`) to run it — real runs only
In `_self_review` (or right after it in `finalize`), after the existing structural checks, and ONLY
when the run is NOT a dry run (`current_context().dry_run` is available as `ctx.dry_run` in
`finalize`; thread it into `_self_review` or check it in `finalize`):
```python
review = content_review(dest, expect_audio=expect_audio)
if review.failures:
    raise RuntimeError("finalize self-review failed: " + "; ".join(review.failures))
```
A dry run must NOT call `content_review` — stub assets are static/silent and would always fail; the
structural checks already cover dry runs. Do not change the structural checks or the house-format step.

## Constraints / do-nots
- Do NOT edit any test or change a frozen signature; keep `tests/sdk/test_finalize.py` green.
- Do NOT record results into `video.json` and do NOT add composition-DOM checks — those are later
  Stage-E increments. Do NOT add `[output]` plumbing.
- No new dependencies (FFmpeg + stdlib only). Keep `ruff`, `ruff format`, and `mypy --strict` clean;
  match the SDK style (see `sdk/sfvf/finalize.py` / `_ffmpeg.py`).

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_content_review.py tests/sdk/test_finalize.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
