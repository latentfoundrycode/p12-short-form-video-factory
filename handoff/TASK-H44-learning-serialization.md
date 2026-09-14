# TASK H44 — serialize learning ops per workflow + clean accept error mapping

## Goal (one sentence)
Serialize the learning run/accept/reject endpoints per workflow with a lock so concurrent ops can't
race on that workflow's staging directory, and map `accept_learning`'s `AcceptError` to a clean 502.

## Frozen contract (already committed — do NOT edit)
`tests/api/test_learning_concurrency.py`.

## What to change — `app/api/learning.py` only

### 1) A per-workflow lock registry
Add (module level):
```python
import threading
_WORKFLOW_LOCKS: dict[str, threading.Lock] = {}
_WORKFLOW_LOCKS_GUARD = threading.Lock()


def _workflow_lock(workflow_id: str) -> threading.Lock:
    with _WORKFLOW_LOCKS_GUARD:
        lock = _WORKFLOW_LOCKS.get(workflow_id)
        if lock is None:
            lock = threading.Lock()
            _WORKFLOW_LOCKS[workflow_id] = lock
        return lock
```
It must return the SAME lock object for the same id and DIFFERENT locks for different ids, and be a
plain (non-reentrant) `threading.Lock`. The tiny guard lock only protects the registry dict; do not
hold it around the learning work.

### 2) Hold the workflow lock across each learning endpoint
In `run_learning_for_workflow`, `get_staged_learning` is READ-ONLY — leave it UNLOCKED (do not
serialize reads). Wrap the bodies of the three MUTATING endpoints — `run_learning_for_workflow`,
`accept_staged_learning`, `reject_staged_learning` — so the per-workflow lock is held for the whole
operation:
```python
with _workflow_lock(workflow_id):
    ... existing body ...
```
Acquire the lock AFTER `_entry(request, workflow_id)` validates the id (so an invalid id still 404s
without touching the lock registry), then do the existing work (run/accept/reject) inside the `with`.
The lock is released automatically on return or exception. A run holds the lock for the whole
`run_learning` call (including the paid completion) — that is intended (it serialises that workflow).

### 3) Map `AcceptError` to 502
In `accept_staged_learning`, wrap the `accept_learning(...)` call so its `AcceptError` becomes a clean
HTTP 502 (mirroring how `run` maps `LearningError`), instead of escaping as a bare 500:
```python
try:
    result = accept_learning(entry.path, _staging_for(request, workflow_id))
except AcceptError as exc:
    raise HTTPException(status_code=502, detail="could not apply learning proposals") from exc
```
Import `AcceptError` from `app.learning.accept` (alongside the existing `accept_learning`,
`reject_learning`). The existing `result.applied` guard on the marker write stays.

## Constraints / do-nots
- Touch ONLY `app/api/learning.py`. Do NOT edit any test or other file. Reuse existing helpers.
- `get_staged_learning` stays unlocked (read-only). Do not introduce a global lock across workflows —
  the lock is PER workflow id (different workflows must not block each other).
- Process-local serialization only (a `threading.Lock`); cross-process is out of scope (consistent
  with H37/H39). Keep `ruff check .`, `ruff format --check .`, `mypy sdk app` clean; ≤100 cols.

## Scope
- `app/api/learning.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_learning_concurrency.py tests/api/test_learning_run_api.py tests/api/test_learning_checkpoint.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
