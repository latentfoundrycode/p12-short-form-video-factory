# TASK F-1 fix — retry-guard the schedules read; correct the ScheduleError docstring

Apply these two edits to `app/core/schedules.py` only. Change nothing else. Do not edit tests.

## FIX A — survive the Windows atomic-replace/open race on read
The F-2 scheduler will poll `schedules.json` while the F-3 API rewrites it via `os.replace`; on
Windows a read landing mid-replace raises a transient `PermissionError`. `records.read_json` already
guards its read with `_retry_on_permission_error` — do the same here (this module already imports
that helper for the writer). Keep the `FileNotFoundError` → `[]` handling OUTSIDE the retry.

Find:
```python
def read_schedules(path: Path) -> list[ScheduleEntry]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
```
Replace with:
```python
def read_schedules(path: Path) -> list[ScheduleEntry]:
    try:
        text = _retry_on_permission_error(lambda: path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
```
(`_retry_on_permission_error` retries only the transient `PermissionError` and re-raises everything
else, so a genuine `FileNotFoundError` still reaches the `except` and returns `[]`. Confirm that is
how it behaves in `app/core/records.py`; if it swallows `FileNotFoundError`, instead guard only the
read with a `path.exists()` check before the retry so a missing file still returns `[]`.)

## FIX B — correct the misleading ScheduleError docstring
A missing file is NOT an error (it returns `[]`). Find:
```python
class ScheduleError(Exception):
    """schedules.json is missing-as-malformed, not a list, or contains an invalid entry."""
```
Replace with:
```python
class ScheduleError(Exception):
    """schedules.json is malformed JSON, not a list, or contains an invalid entry."""
```

## Scope
- `app/core/schedules.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_schedules.py -q` → all pass.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
