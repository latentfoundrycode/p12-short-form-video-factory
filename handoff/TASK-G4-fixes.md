# TASK G-4 fix — /api/learning must not mutate the registry on a read (Review B P2)

## Why
Cross-family Review B (REJECT/P2) and diff-reviewer (NOTED) both flagged: `list_learning` uses
`entries = holder.snapshot if holder.snapshot else holder.rescan()`. The `else holder.rescan()`
makes a read-only GET re-scan the filesystem and MUTATE the shared registry snapshot when it is empty
— a side effect on a read path, and inconsistent with `GET /api/workflows`, which reads
`_holder(request).snapshot` directly. The frozen test now seeds workflows before the app is built, so
the snapshot is populated at construction and the fallback is unnecessary.

## Scope
- `app/api/learning.py`

## Exact change (`app/api/learning.py` only)
Replace:
```python
entries = holder.snapshot if holder.snapshot else holder.rescan()
```
with:
```python
entries = holder.snapshot
```
Change nothing else.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_learning_api.py -q` → 5 passed.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m mypy sdk app` → clean.
