# TASK E-4a fix — exclude a context.json symlink alias from the files listing

## Why (Review B REJECT)
`list_run_files` excludes `context.json` by its on-disk name (`relative.name == "context.json"`),
but the sibling `get_run_file` blocks it by its RESOLVED name (`resolved.name == "context.json"`). So
a symlink alias inside the run dir (e.g. `notes.txt -> context.json`) would be LISTED by the alias
name — advertising the secret file's size — while the serving endpoint 404s it. Align the listing to
the established `resolved.name` invariant so the alias is excluded from the listing too. The locking
test `tests/api/test_run_files_listing.py::test_listing_excludes_context_json_symlink_alias` (already
committed — do NOT edit it) covers this (it creates the symlink and asserts the alias is not listed;
it skips where the platform forbids symlink creation and runs on CI).

## Apply EXACTLY this one edit to `app/api/runs.py` (inside `list_run_files`)
Find this exact block:

```python
        relative = path.relative_to(run_dir)
        if relative.name == "context.json" or any(part.startswith(".") for part in relative.parts):
            continue
```

Replace it with exactly:

```python
        relative = path.relative_to(run_dir)
        if (
            relative.name == "context.json"
            or resolved.name == "context.json"
            or any(part.startswith(".") for part in relative.parts)
        ):
            continue
```

(`resolved` is already computed just above as `resolved = path.resolve()`.) Change nothing else.

## Scope
- `app/api/runs.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_run_files_listing.py tests/api/test_run_files.py -q` → all pass (the
  symlink-alias test skips on a platform without symlink support).
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
