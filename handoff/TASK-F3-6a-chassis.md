# TASK F3-6a: per-request chassis settings on launch (backend)

Satisfies: R-023, R-027, R-028

## Methodology (read first)
RED-first. The supervisor has already written the frozen contract
`tests/api/test_launch_chassis.py` (16 failing, 6 passing). Do NOT edit any test file. Make the
failing tests pass without breaking any other test.

## Context
`POST /api/workflows/{id}/runs` is handled by `launch_run` in `app/api/runs.py`. Its body model is
`LaunchBody` (params, video_count, concurrency, gates_auto, per_video_budget, voice), parsed by
`_parse_launch_body`. `admit_run(...)` already accepts `dry_run: bool = False` and
`step_concurrency: int | None = None` (None -> `app_settings.default_step_concurrency()`), and forwards
both to `run_request` — but `launch_run` never passes them, and `LaunchBody` has no such fields.
The workflow manifest already has `max_videos: int | None` on its `[workflow]` section
(`app/registry/schema.py`, `entry.manifest.workflow.max_videos`), but nothing enforces or exposes it.

## What to change (only `app/api/runs.py` and `app/api/workflows.py`)
1. `LaunchBody` gains:
   - `dry_run: bool = False` — **strict**: only JSON `true`/`false` are accepted. Reject `1`, `0`,
     `"yes"`, `"true"`, `null` with a 422 (use `StrictBool` or a `mode="before"` validator).
   - `step_concurrency: int | None = None` — when not None it must be an int ≥ 1. **Reject bool
     before int** (`True`/`False` are ints in Python — check `isinstance(v, bool)` first), and reject
     floats like `1.5` and strings like `"2"` (strict int; 422).
   - `video_count`: additionally **reject bool** (`true` must be a 422, not 1) via a `mode="before"`
     validator, the same way `EstimateIn._video_count_not_bool` does.
2. `launch_run` passes `dry_run=body.dry_run` and `step_concurrency=body.step_concurrency` to
   `admit_run`.
3. In `launch_run`, before the disk/key/program preflight and before `admit_run`: when the manifest
   exists and `manifest.workflow.max_videos` is not None and `body.video_count > max_videos`, raise
   `HTTPException(status_code=422, detail=f"This workflow allows at most {max_videos} videos per request")`.
4. `WorkflowOut` (`app/api/workflows.py`) gains `max_videos: int | None = None`, filled from the
   entry's manifest (`None` when there is no manifest or no cap). Archived synthetic cards keep None.

## Constraints
- Do not change `admit_run`'s signature or defaults, the scheduler, the estimate endpoint, or
  `per_video_budget` (that is replaced later in F3-7).
- Do not edit tests. Do not touch frontend code.
- Workspace boundary: read/write only inside this checkout.

## Verify before handing back
```
.\.venv\Scripts\python.exe -m pytest tests/api -q
.\.venv\Scripts\python.exe -m ruff check app
.\.venv\Scripts\python.exe -m ruff format --check app
.\.venv\Scripts\python.exe -m mypy
```
All of `tests/api/test_launch_chassis.py` passes. The only acceptable `tests/api` failures are the two
known pre-existing httpx `..`-path ones (`test_clear_runs.py::test_delete_run_rejects_unsafe_run_id`,
`test_learning_run_api.py::test_unknown_workflow_is_404`). Report anything else.
