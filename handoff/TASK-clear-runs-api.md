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

## Review follow-up (SECOND delegation — apply these to `app/api/runs.py`)
The first implementation is committed. Cross-family + security review found three fixes; apply all
three (the frozen test now expects clear-failed as a DELETE):

1. **clear-failed must be a `DELETE`, declared BEFORE the per-run delete route.** Change
   `@router.post("/workflows/{workflow_id}/runs/clear-failed")` to
   `@router.delete("/workflows/{workflow_id}/runs/clear-failed", response_model=ClearFailedOut)`
   (DELETE is CORS-preflighted, so a cross-origin drive-by can't trigger it — the per-run delete is
   already a DELETE). CRITICAL: the `clear-failed` route MUST be registered ABOVE the
   `@router.delete("/workflows/{workflow_id}/runs/{run_id}")` route, otherwise `{run_id}` matches the
   literal string "clear-failed" and shadows it. Put `clear_failed_runs` first.

2. **Exact-path guard (not just containment) to defeat in-tree symlink/junction redirection.** A
   junction `runs/<wf>/alias -> runs/<wf>/real-run` passes the current `is_relative_to` containment
   check yet `rmtree`s the WRONG run (a junction to the workflow root deletes ALL runs). Require the
   resolved path to EQUAL the expected literal path, in BOTH endpoints:
   - per-run: replace the containment check with
     `expected = (_runs_dir(request) / workflow_id).resolve() / run_id` and
     `if run_dir.resolve() != expected: raise HTTPException(status_code=404)` (compute this BEFORE
     the `request.json` check is fine, but it MUST be before `rmtree`).
   - clear-failed sweep: for each `child`, require `child.resolve() == root_resolved / child.name`
     else `continue` (skip a redirected entry).
   (A legit run dir is not a link, so its `resolve()` equals the literal expected path; a junction
   leaf resolves elsewhere and is rejected.)

3. **Per-`rmtree` failure isolation.** A locked/undeletable file (common on Windows) makes
   `shutil.rmtree` raise `OSError`. In the clear-failed sweep, wrap each `shutil.rmtree(child)` in
   `try/except OSError: continue` so one bad run cannot abort the sweep or lose the already-deleted
   ids (only add to `deleted` on success). In the per-run delete, wrap the single
   `shutil.rmtree(resolved)` in `try/except OSError` and on failure
   `raise HTTPException(status_code=500, detail="could not delete run")`.

(Deliberately NOT changing: the run-id-reuse TOCTOU Review B raised — near-impossible given
second-granularity timestamp run ids plus single-active-run admission; tracked as hardening.)

## Scope
- `app/api/runs.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_clear_runs.py -q` → all pass.
- `-m pytest tests/api/test_runs.py -q` → still green.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
