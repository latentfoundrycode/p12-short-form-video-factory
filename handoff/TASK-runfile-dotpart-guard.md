# TASK — get_run_file must refuse dot-prefixed run files (H61)

## Why
`list_run_files` excludes any path with a dot-prefixed part (`any(part.startswith(".") ...)`), so the
`.steps/` step cache is hidden from the file listing. But `get_run_file` has NO such guard, so a file
under a dot-prefixed dir (e.g. `shared/.steps/cache.json`) is still fetchable by path. A cached step
result could carry a secret, so a listing-hidden file must not be fetchable by guessing its path.
Mirror the listing's dot exclusion in `get_run_file`.

Frozen RED test (committed, do not modify):
`tests/api/test_secret_exposure.py::test_dot_prefixed_run_files_are_not_downloadable`.

## Change — only `app/api/runs.py`, `get_run_file`
The existing block (after the `resolved.is_file()` check) is:
```python
    if (
        resolved.name == "context.json"
        or resolved.relative_to(run_dir.resolve()).as_posix() == "shared/result.json"
    ):
        raise HTTPException(status_code=404)
```
Add a dot-part guard (compute the run-relative path once). `resolved` is already confirmed
`is_relative_to(run_dir.resolve())` just above, so `relative_to` is safe:
```python
    relative = resolved.relative_to(run_dir.resolve())
    if (
        resolved.name == "context.json"
        or relative.as_posix() == "shared/result.json"
        or any(part.startswith(".") for part in relative.parts)
    ):
        raise HTTPException(status_code=404)
```

## Scope / do NOT
- Only `app/api/runs.py` `get_run_file`. Do NOT change `list_run_files`, other endpoints, any test,
  or any stub. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/api/test_secret_exposure.py tests/api/test_run_files.py -q`
  (and `PYTHONPATH=sdk python -m pytest tests/api -q -k "run_file or files or exposure or download"`)
  → all pass, including `test_dot_prefixed_run_files_are_not_downloadable` and the existing
  context.json / result.json / listing tests (no regression — ordinary files still served).
- `ruff check app tests` and `ruff format --check app tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
