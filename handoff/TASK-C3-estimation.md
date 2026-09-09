# TASK C-3 — cost estimation from run history (PRD §7.3)

## Goal (one sentence)
Fill in `app/core/estimate.py::estimate_cost` (skeleton already committed) and record `dry_run` on
run records, so a prospective run's per-meter cost can be estimated from comparable history.

## Frozen contract (already committed — do not edit any test)
`tests/core/test_estimate.py` pins the behaviour; make it pass. The `Estimate` dataclass and the
`estimate_cost(runs_dir, workflow_id, params, affects_cost_keys) -> Estimate` signature are frozen in
the skeleton — do not change them.

## Algorithm for `estimate_cost` (fill the body)
1. Enumerate run dirs under `runs_dir / workflow_id` (each child dir is a run). For each, read the
   record via `records.read_request(run_dir)`; skip a run whose `status` is in
   `EXCLUDED_STATUSES` **or** whose `dry_run` is `True`. Keep `(run_dir, record)` for the rest — these
   are the *candidates*. Ignore dirs without a readable `request.json`.
2. Sort candidates by run id (the dir name) **descending** (most recent first).
3. `matched` = candidates whose `record.params.get(k) == params.get(k)` for every `k` in
   `affects_cost_keys`. (Params outside that set — e.g. topic — are irrelevant.)
4. `pool` = `matched[:MAX_HISTORY]` if `matched` else `candidates[:MAX_HISTORY]`.
   `confidence` = `"matched"` if `matched` else (`"crude"` if candidates else `"none"`).
5. For each run in `pool`, compute its per-meter **uncached** cost: for each video dir in the run,
   `records.read_video(video_dir).cost` and sum `cost["uncached"][meter]` across videos (a video with
   no `cost` or no `uncached` contributes nothing; use `.get`). Then `per_meter[meter]` = the mean,
   over the pool runs that recorded that meter, of each run's summed uncached amount for it.
6. Return `Estimate(per_meter=..., confidence=..., matches=len(pool))`. Empty history → `Estimate({},
   "none", 0)`.
Pure and read-only. Be tolerant of malformed/partial records (skip, don't crash — §8). Do not use the
`actual` figure; only `uncached`.

## Record `dry_run` (so dry runs are excludable)
- `app/core/records.py`: add `dry_run: bool = False` to `RequestRecord` (place it near the other
  optional-ish fields; it is required-with-default, written always — it need NOT go in
  `REQUEST_OPTIONAL_FIELDS` since a bool default is fine to persist). Add a `dry_run: bool = False`
  parameter to `create_request` and set it on the constructed `RequestRecord`.
- `app/core/supervisor.py`: at the `create_request(...)` call in `run_request`, pass
  `dry_run=wiring.dry_run` so real runs record their mode.

## Constraints / do-nots
- Do NOT edit any test. Do NOT change the budget ledger/gate, the cost recording (C-1), or forecasts
  (C-2). No API endpoint / frontend in this increment — the estimator is a pure function that C-4
  (atomic pre-flight) and C-5 (Statistics/settings UI) will call.
- Keep `ruff` and `mypy --strict` clean; match surrounding style.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_estimate.py tests/core/test_records.py tests/core/test_supervisor.py -q` → all pass.
- `-m ruff check .` and `-m mypy sdk app` → clean.
