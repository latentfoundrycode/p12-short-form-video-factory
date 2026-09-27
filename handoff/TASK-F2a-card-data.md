# TASK F2a — main-tab card data (avg cost per meter + archived state)

Satisfies R-005 (backend) and R-011 (backend), PRD §8.1. RED-first: the frozen tests
`tests/api/test_workflow_cards.py` and the updated `WORKFLOW_FIELDS` in
`tests/api/test_workflows.py` are in place and RED. **Do NOT edit any test file.** Read the test
file first — it fixes the exact shapes, the pool-size averaging, and the archived/browsable rules.

## 1. New WorkflowOut fields (app/api/workflows.py, class WorkflowOut ~line 91)
Additive; keep all existing fields:
- `avg_cost_per_meter: dict[str, float]` — default `{}`
- `runs_counted: int` — default `0`
- `archived: bool` — default `False`

## 2. Average cost helper (app/core/estimate.py, beside the existing helpers)
```
def average_cost_per_meter(runs_dir: Path, workflow_id: str, *, limit: int = 10) -> tuple[dict[str, float], int]
```
- Reuse `_candidates(runs_dir, workflow_id)` (already filters to status in {complete,partial}, non-dry,
  most-recent-first) and take `[:limit]`. That count is `runs_counted`.
- For each run in the pool, compute the run's ACTUAL cost per meter = sum over its video dirs of
  `video.cost["actual"][meter]` (reuse the summation logic in `app/core/statistics.py::_run_actual`)
  PLUS `request.prepare_cost["actual"][meter]` when present (guard like statistics does).
- **Divide each meter's grand total by the POOL SIZE (number of counted runs), not by the number of
  runs that had that meter.** (A meter absent from some runs must average lower — frozen by
  `test_meter_absent_from_some_runs_divides_by_pool_size`.) Apply the finite/non-negative guards used
  in statistics/estimate. Return `({}, 0)` when the pool is empty.

## 3. Archived detection (app/core/estimate.py or a sibling)
```
def archived_workflow_ids(runs_dir: Path, known_ids: set[str]) -> list[str]
```
- Sorted names of `runs_dir` subdirs that are NOT in `known_ids` and contain at least one run dir with
  a `request.json`. Guard each name with `app.paths.is_safe_path_segment` before using it as a path.

## 4. Wire into the endpoint (app/api/workflows.py)
- Plumb `runs_dir` (from `request.app.state.runs_dir`, same accessor pattern as
  app/api/runs.py `_runs_dir`) into `_serialize` / `_list_payload` / `list_workflows` /
  `rescan_workflows`. Compute the two cost fields per workflow in `_serialize`.
- In `_list_payload`, after serializing the scanned entries, append one synthetic archived card per
  `archived_workflow_ids(runs_dir, {e.folder_name for e in entries})`: `id=<that id>`, `name=None`,
  `description=None`, `thumbnail_url=None`, `valid=False`, `archived=True`, `problems=[]`,
  `quality_factors=[]`, `params=[]`, and its `avg_cost_per_meter`/`runs_counted` from the helper.
- Scanned entries get `archived=False`.

## 5. Keep archived workflows browsable (app/api/runs.py `_require_workflow` ~line 379)
Today it 404s when `_holder(request).get(workflow_id)` is None, which would hide an archived
workflow's runs. Change it (or the runs/files list routes) so an id that is NOT in the registry but
IS a subdir of `runs_dir` (with a run) is accepted for the read/list routes, so archived videos stay
browsable (frozen by `test_archived_workflow_runs_stay_browsable`). Do not weaken the guard for
launch/mutation routes — only the read/list of existing output needs to work for archived ids.

## Done when
- `./.venv/Scripts/python.exe -m pytest tests/api/test_workflow_cards.py tests/api/test_workflows.py -q` passes.
- Full `tests/api` + `tests/core` still pass (ignore the 2 pre-existing httpx `..`-path failures and
  the 3 test_supervisor silence-limit timing flakes under load).
- `ruff check .`, `ruff format --check .`, `mypy` clean. Frozen test files unmodified.
- Endpoint stays reasonably fast (bounded disk reads); do not precompute into the registry snapshot.
- End with an `Assumed, not verified` list (or `none`).
