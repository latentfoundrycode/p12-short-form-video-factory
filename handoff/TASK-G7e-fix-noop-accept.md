# TASK G-7e fix — a no-op accept must not advance the checkpoint

One review defect (P1c). Touch ONLY `app/api/learning.py`.

## Defect
`accept_staged_learning` writes the last-learned marker unconditionally after `accept_learning`
returns. But `accept_learning` returns `applied=[]` without raising when the staging area is empty
(no run, a run that proposed nothing, a second accept, or an accept after a reject). Advancing the
marker then hides existing labels from future learning even though nothing was applied.

A new regression test (`tests/api/test_learning_checkpoint.py::
test_accept_without_applied_edits_does_not_advance_marker`) currently FAILS on this.

## Fix
In `accept_staged_learning`, write the marker ONLY when `accept_learning` actually applied something.
Guard the write on the result:
```python
result = accept_learning(entry.path, _staging_for(request, workflow_id))
if result.applied:
    write_last_learned(
        _learning_state_dir(request),
        workflow_id,
        ids.format_utc_z(ids.utc_now()),
    )
return AcceptOut(applied=result.applied)
```
Nothing else changes (reject still writes no marker; run still passes `since`).

## Constraints
- ONLY `app/api/learning.py`. Do NOT edit any test or other file.
- Keep `ruff check .`, `ruff format --check .`, `mypy sdk app` clean; ≤100 cols.

## Scope
- `app/api/learning.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_learning_checkpoint.py tests/api/test_learning_api.py tests/api/test_learning_run_api.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
