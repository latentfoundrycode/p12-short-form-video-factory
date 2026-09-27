# TASK F3-1 — POST /api/workflows/{id}/estimate (pre-launch cost estimate)

Satisfies R-032 (backend), §7.3; also surfaces meter units (H-CARDS-2). RED-first: the frozen tests
tests/api/test_estimate_api.py are RED. Do NOT edit tests.

## Endpoint (app/api/runs.py, near launch_run)
`POST /api/workflows/{workflow_id}/estimate` with body `EstimateIn{ params: dict[str, Any], video_count: int }`.
- Registry-only: use `_require_workflow(request, workflow_id)` so an unknown workflow is 404 (you
  estimate what you can launch).
- `video_count`: int >= 1. **Reject bool explicitly** (a pydantic `int` field accepts `True`/`False` as
  1/0 — add a validator `if isinstance(v, bool) or v < 1: raise` so `video_count=true` is a 422, not 1).
- Compute:
  - `affects = frozenset(p.key for p in entry.manifest.params if p.affects_cost)` (mirror
    app/core/supervisor.py's admission use).
  - `est = estimate_cost(_runs_dir(request), workflow_id, body.params, affects)` then
    `scaled = scale_estimate(est, body.video_count)` (app/core/estimate.py).
  - Shape the response: for each meter in `scaled.per_meter`, emit
    `{amount: <float>, unit: <str>, kind: <str>}` using `app.core.meters.meter_info(meter)`
    (unit/kind). Return `EstimateOut{ per_meter: dict[str, MeterEstimateOut], confidence: str,
    matches: int, video_count: int }`.
- No history -> `per_meter={}`, `confidence="none"`, `matches=0` (estimate_cost already returns this).

## Response models (pydantic, in runs.py)
`MeterEstimateOut{ amount: float, unit: str, kind: str }`,
`EstimateOut{ per_meter: dict[str, MeterEstimateOut], confidence: str, matches: int, video_count: int }`.

## Notes
- Pure/read-only: no run is created, nothing spent. Bounded disk reads (estimate_cost already caps at
  MAX_HISTORY). Do not change estimate_cost/scale_estimate/meter_info.

## Done when
- `./.venv/Scripts/python.exe -m pytest tests/api/test_estimate_api.py -q` passes.
- Full tests/api + tests/core still pass (only the 2 pre-existing httpx `..`-path failures; supervisor
  silence-timer tests may flake under CPU load — unrelated).
- `ruff check .`, `ruff format --check .`, `mypy` clean. Frozen test unmodified.
- End with an `Assumed, not verified` list (or `none`).
