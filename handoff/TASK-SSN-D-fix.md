# TASK-SSN-D-fix — Close the two cross-family Review B blockers (Stage D)

Cross-family Review B REJECTed Stage D with two real blockers plus advisories. This task fixes them.
It touches THREE files (two small SDK additions + the workflow). Frozen tests are committed and RED.

## Scope

- `sdk/sfvf/media/image.py` — add a `price` function only.
- `sdk/sfvf/media/video.py` — add a `price` function only.
- `workflows/sensational-science-news/main.py` — the rest.

No other files. No new third-party imports. Stay in this checkout.

## Frozen tests to make green (read them first)

- `tests/sdk/test_media_price.py` (2)
- `tests/integration/test_ssn_cost.py` (5) — reworked estimate + sanitize hardening
- `tests/integration/test_ssn_visual_bed.py::test_source_visual_bed_sources_commons_once_via_web_source` (+ keep the other 4 in that file green)
- keep `test_ssn_assemble.py`, `test_ssn_composite.py`, `test_ssn_captions.py`, `test_ssn_workflow_dry_run.py` green.

## Fix 1 (SDK) — expose pre-call prices

These are PURE registry lookups (no network, no context), used by the workflow's gate estimate.

- `sdk/sfvf/media/image.py`:
  ```python
  def price(model: str, size: str | None = None) -> float:
      provider, mdl = resolve(model)
      adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
      return float(adapter.image_price(mdl, size))
  ```
- `sdk/sfvf/media/video.py`:
  ```python
  def price(model: str, duration_s: float | None = None) -> float:
      provider, mdl = resolve(model)
      adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
      return float(adapter.video_estimate(mdl, duration_s, None))
  ```
  (`resolve` and `importlib` are already imported in both modules.)

## Fix 2 (workflow) — BLOCKING: source commons via `media.web.source` once + paid step

The manual per-beat `media.web.search`/`fetch`/`check_relevance` loop re-pays the PAID vision check for
the same candidates every beat, and does not apply the `min_score` gate. Replace it with ONE
`media.web.source` call (it wraps each URL's fetch+relevance in a PAID `ctx.step`, so a resume/re-run
does not repay, and it filters by `min_score`).

Add constants: `_RELEVANCE_COST_USD = 0.03` (a conservative per-relevance-check vision cost),
`_WEB_CONSIDER = 24` (commons fan-out; must stay under the SDK's 50 ceiling).

Rework `_source_visual_bed(ctx, *, subject, beats)`:
- `clip_indices`: derive from `_clip_count` (Fix 4) — `{0}` when at least 1 clip, plus the last beat
  index when `_clip_count(len(beats)) >= 2`.
- `static_beats = [b for b in beats if b["index"] not in clip_indices]`.
- If `static_beats`: `sourced = media.web.source(subject, subject=subject, want=len(static_beats),
  consider=_WEB_CONSIDER)` (a list of `SourcedImage` TypedDicts: `{"path","candidate","relevance"}`);
  else `sourced = []`. Iterate the beats in order; for a static beat pop the next `sourced` item ->
  a `"web"` asset (`path=s["path"]`, `url=s["candidate"]["url"]`, `ken_burns=True`, and append the
  url to `source_urls`); when `sourced` is exhausted, generate an AI still (`media.image.generate`,
  `"still"`, `ken_burns=True`). Clip beats -> `media.video.generate` (`"clip"`, `ken_burns=False`) as
  before. One asset per beat, in beat order. Keep the returned shape `{"assets", "source_urls"}`.
- You no longer need the `del ctx` / manual `used_urls` / `media.web.search` code — remove it.

In `run()`, mark the visual-bed step PAID so the expensive bed survives cheap-cache eviction and a
re-run does not re-reserve the clips:
`with ctx.step("visual-bed", inputs={...}, paid=True) as step:`

## Fix 3 (workflow) — BLOCKING: gate cost estimates the REAL reserve

A paid call reserves `max(adapter_price, owner_estimate)`, and each static beat also incurs a paid
vision relevance check. Rework `_estimate_bed_cost(ctx, narration)`:
```python
words = len(narration.split())
beats = _beat_count(words / _WORDS_PER_SEC)          # Fix 4
clips = _clip_count(beats)                            # Fix 4
statics = max(0, beats - clips)
still_unit = max(media.image.price(_IMAGE_MODEL), ctx.budget_estimate(_IMAGE_METER) or 0.0)
clip_unit = max(media.video.price(_CLIP_MODEL, _CLIP_DURATION_S), ctx.budget_estimate(_CLIP_METER) or 0.0)
# conservative: every static beat priced as a paid AI still + one paid relevance check
return round(clips * clip_unit + statics * (still_unit + _RELEVANCE_COST_USD), 2)
```

## Fix 4 (workflow refactor) — share the beat/clip formula (refactor-scout)

Extract two pure helpers so the estimate and the real bed cannot drift:
- `_beat_count(duration_s) -> int`: `max(1, round(duration_s / _BEAT_S))`.
- `_clip_count(n_beats) -> int`: `min(_MAX_CLIPS, 2 if n_beats >= 4 else 1)`.
Use `_beat_count` in `_beats` and `_estimate_bed_cost`; use `_clip_count` in `_estimate_bed_cost` and
to build `clip_indices` in `_source_visual_bed`. Also inline the dead `bed_markup = ""` initializer in
`_composition_html` if trivial.

## Fix 5 (workflow) — harden `_sanitize_source_urls` (Review B advisory)

Keep the existing strip + `isprintable()` + `scheme in ("http","https")` checks, and ALSO drop a URL
with no host or with userinfo:
```python
if not parsed.hostname:      # e.g. "https:javascript:alert(1)"
    continue
if parsed.username or parsed.password:   # drop "http://user:pass@host/p"
    continue
```

## Done when (run from Workspace/ with the repo venv)

- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_media_price.py tests/integration/test_ssn_cost.py tests/integration/test_ssn_visual_bed.py tests/integration/test_ssn_assemble.py tests/integration/test_ssn_composite.py::test_composition_includes_visual_bed tests/integration/test_ssn_captions.py -q` — all pass.
- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_workflow_dry_run.py -q` — still green.
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/media workflows/sensational-science-news` and `./.venv/Scripts/python.exe -m ruff format --check .` — clean.
- `./.venv/Scripts/python.exe -m mypy` — clean.

Print the new SDK `price` functions, the reworked `_source_visual_bed`, `_estimate_bed_cost`, the
`_beat_count`/`_clip_count` helpers, and the hardened `_sanitize_source_urls`.
