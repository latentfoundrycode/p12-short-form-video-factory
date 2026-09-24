# TASK-pkg2 — relocatable DATA_ROOT for runtime data

## Goal

For an installed SFVF, program files live under `%LOCALAPPDATA%\Programs\SFVF` and are replaced on upgrade; runtime data must live elsewhere so an upgrade never wipes it. Introduce `app.paths.DATA_ROOT` — `$SFVF_DATA_DIR` when set, else `APP_ROOT` (so development is unchanged until the installer sets the variable) — and root all runtime-generated data and user state on it, while shipped program dirs stay under `APP_ROOT`. See `docs/DELIVERY.md`.

## Files to change

1. `app/paths.py`
2. `app/core/secrets.py`
3. `app/core/schedules.py`
4. `app/core/budget_config.py`

Do not touch any test or other module. Frozen contract: `tests/core/test_data_root.py`.

## The change

### `app/paths.py`

Add `import os` and, after `APP_ROOT`:

```python
DATA_ROOT = Path(os.environ["SFVF_DATA_DIR"]).resolve() if os.environ.get("SFVF_DATA_DIR") else APP_ROOT
```

Re-root the DATA dirs on `DATA_ROOT` (leave the PROGRAM dirs on `APP_ROOT`):

- `RUNS_DIR = DATA_ROOT / "runs"`, `CACHE_DIR = DATA_ROOT / "cache"`, `LIBRARY_DIR = DATA_ROOT / "library"`, `VENVS_DIR = DATA_ROOT / "venvs"` — change from `APP_ROOT` to `DATA_ROOT`.
- `WORKFLOWS_DIR`, `WEB_DIR`, `SDK_DIR` stay `APP_ROOT`-relative (unchanged).

### `app/core/secrets.py`

Import `DATA_ROOT` from `app.paths` and change the default store from `APP_ROOT / "secrets.enc"` to `DATA_ROOT / "secrets.enc"` (i.e. `_DEFAULT_STORE = DATA_ROOT / "secrets.enc"`). The `SFVF_SECRETS_PATH` override is unchanged.

### `app/core/schedules.py`

Import `DATA_ROOT` and change `SCHEDULES_PATH = APP_ROOT / "schedules.json"` to `DATA_ROOT / "schedules.json"`. (Keep `is_safe_path_segment` import as is.)

### `app/core/budget_config.py`

Import `DATA_ROOT` and change the default budget-state root from `APP_ROOT / "state" / "budget"` to `DATA_ROOT / "state" / "budget"` (the `os.environ.get("SFVF_BUDGET_STATE") or …` fallback). The `SFVF_BUDGET_STATE` override is unchanged.

If any of these modules no longer references `APP_ROOT` after the change, drop `APP_ROOT` from its import to keep the import clean (but keep it if still used, e.g. `secrets.py`/`schedules.py` may import both `APP_ROOT` and `DATA_ROOT` — import only what remains used).

## Constraints

- Backward-compatible: with `SFVF_DATA_DIR` unset, `DATA_ROOT == APP_ROOT`, so every path is byte-for-byte what it is today. No behaviour change in development or the existing test suite.
- `DATA_ROOT` is a module constant read once at import (correct: the installer sets `SFVF_DATA_DIR` before launching the server). Do not turn the dir constants into functions.
- No new dependency. One paragraph is one line in any Markdown you write (no hard wraps).

## Done when

- `tests/core/test_data_root.py` is fully green (it references `paths.DATA_ROOT`, which is new).
- The existing suites that use these paths stay green: `tests/core/test_secret_redaction.py`, `tests/api/test_schedules_api.py`, `tests/core/test_scheduler*.py`, `tests/integration/test_budget_status.py`, and the run/statistics tests.
- Full suite passes: `.\.venv\Scripts\python.exe -m pytest -q`.
- Gate clean: `.\.venv\Scripts\python.exe -m ruff check .`, `-m ruff format --check .`, `-m mypy`.

## Builder notes

Record any tooling friction in `docs/BUILDER_NOTES.md` for Bridge Feedback; record any defect/pitfall learning there too, for the Issues file.
