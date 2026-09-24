# TASK — per-video, complete-only cost estimate + video_count scaling (H27, Stage-C)

## Why
`estimate_cost` (`app/core/estimate.py`) produces a per-RUN total, and the atomic pre-flight
(`check_atomic_budget`) compares it to the budget WITHOUT scaling by the requested `video_count`. Two
bugs, one root (no per-video unit): (a) a run requesting more videos than history typically produced
is under-estimated (could be admitted over the per-run ceiling); (b) `_run_uncached` sums EVERY video
record — including non-`complete` videos of a `partial` run — so cost from unfinished videos leaks
into the average. Fix: make the estimate PER-VIDEO over `complete` videos only, and scale it by the
requested `video_count` at the pre-flight (keeping `check_atomic_budget`'s frozen signature).

Frozen RED tests (committed, do not modify): `tests/core/test_estimate.py::`
`test_estimate_is_per_video_average_over_complete_videos`,
`test_estimate_excludes_non_complete_videos_from_the_per_video_unit`,
`test_scale_estimate_multiplies_per_meter_by_the_count`. All existing estimate tests (1-video,
all-complete) must stay green — per-run == per-video there.

## Changes

### 1. `app/core/estimate.py` — `_run_uncached` becomes per-video over complete videos
Filter to `video.status == "complete"`, count them, and return the per-VIDEO average (per-meter sum
over complete videos / number of complete videos); return `{}` when there are no complete videos:
```python
def _run_uncached(run_dir: Path) -> dict[str, float]:
    totals: dict[str, float] = {}
    complete = 0
    try:
        children = list(run_dir.iterdir())
    except OSError:
        return totals
    for child in children:
        if not child.is_dir() or not (child / "video.json").is_file():
            continue
        try:
            video = read_video(child)
        except (OSError, TypeError, ValueError):
            continue
        if video.status != "complete":
            continue  # H27(b): non-complete videos' cost must not leak into the per-video unit
        complete += 1
        cost = video.cost
        if not isinstance(cost, dict):
            continue
        uncached = cost.get("uncached")
        if not isinstance(uncached, dict):
            continue
        for meter, raw in uncached.items():
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                continue
            try:
                amount = float(raw)
            except (OverflowError, ValueError):
                continue
            if not math.isfinite(amount) or amount < 0.0:
                continue
            total = totals.get(meter, 0.0) + amount
            if not math.isfinite(total):
                continue
            totals[meter] = total
    if complete == 0:
        return {}
    return {meter: total / complete for meter, total in totals.items()}
```
(For a 1-complete-video run this is `total / 1` == the old value, so the frozen 1-video tests are
unchanged. `_mean_uncached` then averages these per-video figures across runs unchanged.)

### 2. `app/core/estimate.py` — add `scale_estimate`
```python
def scale_estimate(estimate: Estimate, count: int) -> Estimate:
    """Scale a PER-VIDEO estimate to a whole run of `count` videos (multiply each per-meter amount).
    Confidence and matches are preserved."""
    return Estimate(
        per_meter={meter: amount * count for meter, amount in estimate.per_meter.items()},
        confidence=estimate.confidence,
        matches=estimate.matches,
    )
```

### 3. `app/core/supervisor.py` — scale by video_count before the pre-flight
Import `scale_estimate` from `app.core.estimate` (extend the existing import), and at the atomic
pre-flight (currently `check_atomic_budget(est, factor, wiring.budget, run_id, workflow_id=...)`),
scale the estimate by the requested `video_count` (in scope as the `run_request` parameter):
```python
            est = estimate_cost(run_dir.parent.parent, workflow_id, params, affects)
            factor = workflow.safety_factor if workflow.safety_factor is not None else 1.0
            refusal = check_atomic_budget(
                scale_estimate(est, video_count), factor, wiring.budget, run_id,
                workflow_id=wiring.workflow_id,
            )
```
Do NOT change `check_atomic_budget`'s signature.

## Scope / do NOT
- Only `app/core/estimate.py` (`_run_uncached`, add `scale_estimate`) and `app/core/supervisor.py`
  (import + the one call). Do NOT change `Estimate`, `estimate_cost`'s signature, `_candidates`,
  `_mean_uncached`, `check_atomic_budget`, any test, or any stub. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/core/test_estimate.py tests/core/test_preflight.py -q` → all
  pass (the 3 new H27 tests plus every existing estimate/preflight test — 1-video/all-complete runs
  are behavior-neutral).
- `ruff check app tests` and `ruff format --check app tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
