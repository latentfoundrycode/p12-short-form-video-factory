# TASK: Fix the disk-space preflight so it survives a missing runs directory

## Context
`launch_run` in `app/api/runs.py` refuses a launch when free disk space is below 5 GB
(R-036). The current check calls `shutil.disk_usage(_runs_dir(request))` inside a
`try/except OSError: pass`. On a fresh install the runs directory does not exist yet — it
is only created later, inside `admit_run`. `shutil.disk_usage` on a missing path raises
`FileNotFoundError` (a subclass of `OSError`), which the `except` swallows, so the launch
**proceeds** even on a low-disk volume. That is the exact case the check exists for.

## The frozen test (already written, do NOT edit)
`tests/api/test_launch_preflight.py::test_low_disk_refuses_on_fresh_data_dir` is RED. It
sets `runs_dir` to a path that does not exist (`tmp_path/"data"/"runs"`) and stubs
`shutil.disk_usage` to raise `FileNotFoundError` for any missing path and return `free=3 GB`
for any existing path. It expects a **422** and `run_request` never called.

## What to change
Edit **only** `app/api/runs.py`. In `launch_run`, replace the disk-space block so it reads
the disk of the **nearest existing ancestor** of the runs directory (the volume the output
will land on), instead of the runs directory itself:

- Walk up from `_runs_dir(request)` through its parents and use the first path that exists
  for the `shutil.disk_usage` call. (The drive root always exists, so the walk terminates.)
- If free space on that existing ancestor is below `5 * 1024**3`, raise the same
  `HTTPException(status_code=422, detail="Not enough free disk space to start a run (need at least 5 GB).")`.
- Keep `except OSError: pass` **only** around the `disk_usage` call on that existing
  ancestor — i.e. swallow the error only when the volume itself genuinely cannot be read,
  never because the directory was merely absent. `HTTPException` must still propagate (it is
  not an `OSError`, so a real low-disk reading still becomes a 422 — do not catch it).

Suggested shape (adapt to house style):
```python
target = _runs_dir(request)
for candidate in (target, *target.parents):
    if candidate.exists():
        target = candidate
        break
try:
    free = shutil.disk_usage(target).free
except OSError:
    free = None
if free is not None and free < 5 * 1024**3:
    raise HTTPException(
        status_code=422,
        detail="Not enough free disk space to start a run (need at least 5 GB).",
    )
```

## Constraints
- Touch **only** `app/api/runs.py`. Do NOT edit any test file.
- The `HTTPException` for low disk must NOT be caught by the `except`.
- Do not change the key/program checks, the 5 GB threshold, or the message text.

## Boundary
Work only inside this checkout (`Workspace/`). Do not read or write outside it.

## Verify before you hand back
```
.\.venv\Scripts\python.exe -m pytest tests/api/test_launch_preflight.py -q
.\.venv\Scripts\python.exe -m ruff check app/api/runs.py
.\.venv\Scripts\python.exe -m ruff format --check app/api/runs.py
.\.venv\Scripts\python.exe -m mypy
```
All 6 preflight tests must pass; ruff/format/mypy clean.
