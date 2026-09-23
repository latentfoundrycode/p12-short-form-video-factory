# TASK — path-scope the result.json download block (H18) — COMPLETION

## Why (round 6)
Cross-family review found the round-5 block is too broad: it matches `result.json` by BASENAME
anywhere in the run tree, so a workflow's legitimate artifact (e.g. `ctx.artifacts / "result.json"`,
which lands at `shared/artifacts/result.json`) is wrongly hidden from the listing and 404'd on
download. Only ONE path carries the secret risk: the engine's prepare output, written at
`shared/result.json` (`_run_prepare`: `result_path = shared_dir / "result.json"`). The block must be
PATH-scoped to `shared/result.json`, not basename-scoped. This stays encoding-independent (the file
is still never served) while leaving every other file — including a workflow artifact that merely
shares the basename — served and listed. `context.json` stays basename-scoped (the engine writes it
at `shared/context.json` AND each `<video>/context.json`).

Frozen RED test (committed, do not modify):
`tests/api/test_secret_exposure.py::test_shared_result_json_is_not_downloadable` — GET
`shared/result.json` → 404 and absent from the listing; GET `shared/artifacts/result.json` → 200 and
present in the listing; `shared/note.txt` → 200/listed.

## Changes — only `app/api/runs.py`

### 1. `get_run_file` — revert result.json to a PATH-scoped check
Currently (round 5):
```python
    if resolved.name in ("context.json", "result.json"):
        raise HTTPException(status_code=404)
```
Change to (context.json stays basename-scoped; result.json is path-scoped to shared/result.json):
```python
    if (
        resolved.name == "context.json"
        or resolved.relative_to(run_dir.resolve()).as_posix() == "shared/result.json"
    ):
        raise HTTPException(status_code=404)
```
(`resolved` is already confirmed `is_relative_to(run_dir.resolve())` just above, so `relative_to`
is safe. Using `resolved` — the canonicalised path — keeps the symlink-alias safety the basename
check had.)

### 2. `list_run_files` — exclude only shared/result.json
Currently (round 5):
```python
        if (
            relative.name in ("context.json", "result.json")
            or resolved.name in ("context.json", "result.json")
            or any(part.startswith(".") for part in relative.parts)
        ):
            continue
```
Change to:
```python
        if (
            relative.name == "context.json"
            or resolved.name == "context.json"
            or relative.as_posix() == "shared/result.json"
            or resolved.relative_to(run_root).as_posix() == "shared/result.json"
            or any(part.startswith(".") for part in relative.parts)
        ):
            continue
```
(`run_root = run_dir.resolve()` already exists in this function; `resolved` is already confirmed
`is_relative_to(run_root)` above the exclusion.)

## Scope / do NOT
- ONLY `app/api/runs.py` (the two spots). Do NOT change `_scrub_result_secrets`, records.py, the
  finally call site, any other endpoint, any test, or any stub. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/api/test_secret_exposure.py -q` → all pass, including
  `test_shared_result_json_is_not_downloadable` (shared/result.json blocked+excluded;
  shared/artifacts/result.json served+listed) and the context.json tests.
- `PYTHONPATH=sdk python -m pytest tests/api -q -k "run_file or files or exposure or download"` → all pass.
- `ruff check app tests` and `ruff format --check app tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
