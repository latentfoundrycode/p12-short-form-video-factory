# TASK — delete-a-run + clear-failed-runs API (Runs list cleanup)

## Goal (one sentence)
Add two endpoints that hard-delete run directories: a per-run `DELETE` (refusing an active run) and a
bulk `POST .../runs/clear-failed` (failed/stopped/stopped-budget only), so the frontend can offer a
per-run Delete and a "Clear failed" button.

## Why
The owner asked to declutter the Runs list. Per an owner decision: per-run delete + a "Clear failed"
bulk action, both PERMANENT hard-deletes (behind a UI confirm, added in the frontend increment).

## Frozen contract (already committed — do NOT edit)
`tests/api/test_clear_runs.py`. All existing run tests must stay green.

## What to change — `app/api/runs.py` only
Both routes use the existing `_require_workflow(request, workflow_id)` (404s on unknown/invalid
workflow) and `_runs_dir(request)`. Import `shutil` if not already imported (it is used in tests but
check the module — add the import to `runs.py` if absent).

### 1. `DELETE /api/workflows/{workflow_id}/runs/{run_id}` → `{"deleted": run_id}`
```python
class DeleteRunOut(BaseModel):
    deleted: str
```
- `_require_workflow(request, workflow_id)`.
- `if not is_safe_path_segment(run_id): raise HTTPException(404)`.
- `run_dir = _runs_dir(request) / workflow_id / run_id`; `if not (run_dir / "request.json").is_file(): raise HTTPException(404)`.
- Refuse an active run: `if read_request(run_dir).status == "running": raise HTTPException(status_code=409, detail="run is still active")`.
- Defence in depth before deleting: `resolved = run_dir.resolve()`; require
  `resolved.is_relative_to((_runs_dir(request) / workflow_id).resolve())` else `raise HTTPException(404)`.
- `shutil.rmtree(resolved)`.
- `return DeleteRunOut(deleted=run_id)`.

### 2. `POST /api/workflows/{workflow_id}/runs/clear-failed` → `{"deleted": [run_id, ...]}`
```python
class ClearFailedOut(BaseModel):
    deleted: list[str]
```
- `_require_workflow(request, workflow_id)`.
- `root = _runs_dir(request) / workflow_id`; if not a dir, return `ClearFailedOut(deleted=[])`.
- Define the disposable set: `_CLEARABLE = frozenset({"failed", "stopped", "stopped-budget"})`
  (module-level constant). Iterate `root.iterdir()`:
  - skip non-dirs and dirs without `request.json`.
  - read the record; if `record.status in _CLEARABLE`, and the resolved child is within
    `root.resolve()` (containment guard), `shutil.rmtree(child)` and collect `child.name`.
  - Wrap each record read in `try/except (OSError, ValueError): continue` so one unreadable run
    can't abort the sweep.
- Return `ClearFailedOut(deleted=sorted(deleted))`.

Place both routes near the other `/runs` routes. Do NOT change any existing route.

## Constraints / do-nots
- Touch ONLY `app/api/runs.py`. Do NOT edit any test or other file.
- NEVER delete outside `runs/<workflow_id>/`. The safe-segment check on `run_id` plus the
  resolved-containment guard are both required.
- Never delete a `running` run (per-run → 409; clear-failed only targets the terminal disposable set).
- Keep `ruff check .`, `ruff format --check .`, `mypy sdk app` clean; ≤100 cols.

## Scope
- `app/api/runs.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_clear_runs.py -q` → all pass.
- `-m pytest tests/api/test_runs.py -q` → still green.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
