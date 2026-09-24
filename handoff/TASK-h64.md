# TASK-h64 — prepare-phase cost as a per-run overhead in estimation

## Goal

Close H64: cost estimation is per-video (H27) but a run also pays a one-off SHARED prepare cost (now persisted to `request.prepare_cost` by the statistics increment). Estimation ignores it, so a multi-video run's estimate omits the prepare spend and the C-3 atomic pre-flight admits over the true cost. Add the prepare overhead to the estimate as a PER-RUN term that `scale_estimate` adds ONCE (never multiplied by the video count).

## The one file to change

`app/core/estimate.py` only. Do not touch any test or any other module. The frozen contract is `tests/core/test_estimate_prepare.py`; the existing `tests/core/test_estimate.py` must stay green unchanged.

## Current code (for orientation)

`Estimate` is a frozen dataclass `(per_meter: dict[str, float], confidence: str, matches: int)`. `estimate_cost` builds a pool of comparable runs (`list[tuple[Path, RequestRecord]]`) and calls `_mean_uncached(pool)` for the per-video `per_meter`. `_mean_uncached` sums each run's per-video uncached cost and divides each meter by the count of runs that HAD that meter. `scale_estimate(est, count)` multiplies `per_meter` by `count`, preserving `confidence`/`matches`. `RequestRecord` now has `prepare_cost: dict[str, Any] | None` (shaped `{"uncached": {meter: amount}, "actual": {meter: amount}}`); the pool's `RequestRecord`s carry it — no extra file read needed.

## The change

1. **Add a field to `Estimate`:** `prepare_per_meter: dict[str, float] = field(default_factory=dict)` (import `field` from `dataclasses`). The default empty dict keeps every existing `Estimate(...)` construction and equality valid.

2. **Compute it in `estimate_cost`** from the same `pool` used for `per_meter`. Add a `_mean_prepare(pool)` helper that mirrors `_mean_uncached`'s averaging but at the RUN level: for each `(_, record)` in the pool, read `record.prepare_cost` — when it is a dict and its `"uncached"` is a dict, take each meter's amount as ONE per-run value; average each meter over the runs that HAVE that meter (sum / count-of-runs-with-that-meter), applying the SAME tolerant-amount guards `_run_uncached` uses (reject `bool`, non-`int|float`, `float()` overflow, non-finite, negative; drop a meter whose running sum goes non-finite). Return `Estimate(..., prepare_per_meter=_mean_prepare(pool))`. The no-history early return stays `Estimate(per_meter={}, confidence="none", matches=0)` — its `prepare_per_meter` defaults to `{}`.

3. **Fold it in `scale_estimate(estimate, count)`:** return an `Estimate` whose `per_meter[m] = estimate.per_meter.get(m, 0.0) * count + estimate.prepare_per_meter.get(m, 0.0)` over the union of both meter sets, with `confidence`/`matches` preserved and **`prepare_per_meter={}`** on the result (the overhead is folded into `per_meter`, so scaling twice never double-adds). A meter present only in `prepare_per_meter` appears in the scaled `per_meter` at its overhead value (× nothing).

## Constraints

- Behaviour-preserving for runs with no prepare cost: `prepare_per_meter` is `{}`, so `scale_estimate` reduces to the old `per_meter * count`. The existing `test_estimate.py` scale/estimate tests must stay green.
- Pure and read-only; no new dependency; the frozen signatures `estimate_cost`, `scale_estimate`, and `Estimate`'s existing fields are unchanged (only the additive field is new).
- One paragraph is one line in any Markdown you write (no hard wraps).

## Done when

- `tests/core/test_estimate_prepare.py` is fully green (RED now).
- `tests/core/test_estimate.py` stays green (backward compatibility).
- Full suite passes: `.\.venv\Scripts\python.exe -m pytest -q`.
- Gate clean: `.\.venv\Scripts\python.exe -m ruff check .`, `-m ruff format --check .`, `-m mypy`.

## Builder notes

Record any tooling friction in `docs/BUILDER_NOTES.md` for the supervisor to route to Bridge Feedback; record anything you learn about the defect or a pitfall there too, for the Issues file.
