# TASK G-5 fix (round 2) — refuse a staging_dir that overlaps the workflow (Review B)

## Why
Review B (REJECT) with a concrete scenario: `run_learning` does `shutil.rmtree(staging_dir)`, trusting
the caller's `staging_dir`. If a caller passes `staging_dir = workflow_dir / "rules"`, the rmtree
DELETES the live rules before staging into them — violating §5.11's "the live workflow untouched /
returns entirely to its state before it began". §5.11 says the module ENFORCES its constraints rather
than leaving them to convention, so the engine must guarantee its rmtree/writes can never touch the
live workflow. Committed locking test (RED):
`tests/core/test_learning_engine.py::test_rejects_staging_dir_inside_workflow`.

## Scope
- `app/learning/engine.py`

## Exact change (`app/learning/engine.py` only)
At the VERY START of `run_learning`, BEFORE the `try` block (so the failure never reaches the
`except` cleanup that would rmtree a dangerous `staging_dir`), add a guard that refuses any overlap
between `staging_dir` and `workflow_dir`:
```python
workflow_resolved = workflow_dir.resolve()
staging_resolved = staging_dir.resolve()
if (
    staging_resolved == workflow_resolved
    or workflow_resolved in staging_resolved.parents   # staging is inside the workflow
    or staging_resolved in workflow_resolved.parents   # workflow is inside staging
):
    raise LearningError(
        f"staging_dir must be disjoint from the workflow directory: {staging_dir}"
    )
```
Put this ABOVE the existing `try:` (raise here directly — do NOT let this raise inside the try, or the
`except`'s `rmtree(staging_dir)` could delete the overlapping directory). Keep `workflow_id =
workflow_dir.name` (or use `workflow_resolved.name`). Change nothing else.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_learning_engine.py -q` → ALL pass (incl. test_rejects_staging_dir_inside_workflow).
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
