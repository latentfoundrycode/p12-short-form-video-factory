# TASK-F2 — Hand out a run id only after its record exists

## One-line task and why
In `app/core/supervisor.py`, the `on_started(run_id)` callback fires **before** `request.json` is
written, so the run API returns the run id from `POST /runs` before the run is readable — a client
that reads the run immediately after the 202 races a not-yet-written file and gets a spurious 404.
Fix the ordering so the id is only handed out once the run's record exists. (Supervisor §5.3; the
run API built in 005-1 relies on `on_started` to learn the id.)

## The failing test to make pass (already written — DO NOT modify it)
`tests/core/test_supervisor.py::test_run_id_handed_out_only_after_request_json_is_written` — it
calls `run_request` with an `on_started` that reads the run's `request.json` at the moment the id is
handed out and asserts the record is already readable. It **fails on current `main`** with
`FileNotFoundError`. This test is reviewer-authored; **do not edit, weaken, or delete it, or any
other test/assertion** — make it pass by fixing the code only.

## The fix (precise; keep it minimal)
In `run_request` (`app/core/supervisor.py`), the setup order is currently:
`allocate_run` → set `_active[workflow_id]` → **`on_started(run_id)`** → `create_run_skeleton` →
build `_RunState` → set `_runs[run_id]` → `create_request(...)` (writes `request.json`) → prepare/videos.

**Move the `on_started(run_id)` call to immediately AFTER `create_request(...)`** (and before the
prepare/video work begins). After the move, when `on_started` fires: the folder skeleton exists,
the run is registered in `_runs` (so `stop()` works), and `request.json` is written (so a read
succeeds). `on_started` must still be called **exactly once**, and still only for an allocated run
(never on the `RunBusy` or `EnvBlocked` early returns — those return before `allocate_run`, so
leaving the call in the post-`create_request` position preserves that).

Do not change `on_started`'s signature, the admission/`_active`/`_runs` logic, or anything else.

## Scope — files you may change
- `app/core/supervisor.py` (move the single `on_started` call; no other change)

## Do NOT touch
- `tests/**` (the reviewer test stays exactly as written — make it pass by fixing the code),
  `app/api/*`, `app/core/records.py`, the SDK, the frontend, CI (`.github/`), or anything under
  `docs/` or `handoff/`. Do not add dependencies. Do not weaken any test, assertion, or the gate.

## Acceptance
- `test_run_id_handed_out_only_after_request_json_is_written` passes.
- The existing `test_on_started_fires_once_with_run_id_only_when_allocated` and every other test
  still pass unchanged.
- The full six-command gate is green.

## Gate — run all six before committing (worktree root, PowerShell)
```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```
Expected: all clean; pytest count is 151 (the current 150 plus the reviewer test now passing).

## Commit message (house style — imperative subject stating change and rationale)
```
Hand out a run's id only after its request.json is written so a client reading the run right after start cannot race a missing file and 404.
```
(Cursor appends its `Co-authored-by` trailer automatically.)

## Report back
Print the files you changed, the commit hash, and the final pytest count.
