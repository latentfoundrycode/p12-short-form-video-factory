# TASK — redact a failed-prepare result.json (H18)

## Why
`_run_prepare` (`app/core/supervisor.py`) scrubs `context.json` in its `finally` (both success and
failure paths) via `_scrub_context_secrets`, but redacts `result.json` ONLY on the success path
(`_redact_secrets` at the end of the function, after the early `return False, None` on a non-zero
returncode). So a `prepare()` that writes `shared/result.json` (its cwd) carrying an injected secret
VALUE and then exits non-zero leaves that secret UNREDACTED on disk — and `result.json`, unlike
`context.json`, is downloadable via `get_run_file`. Same defect class as the already-closed
success-path leak; narrow trigger, but a real secret-exposure residual.

Fix: add a best-effort `_scrub_result_secrets` helper (mirroring `_scrub_context_secrets`) and call
it in the `_run_prepare` `finally`, so `result.json` is redacted uniformly on BOTH paths.

Frozen RED tests (committed, do not modify):
- `tests/core/test_secret_redaction.py::test_scrub_result_secrets_redacts_an_on_disk_result`
- `tests/core/test_secret_redaction.py::test_scrub_result_secrets_is_best_effort_on_missing_or_bad_file`
- `tests/core/test_secret_redaction.py::test_failed_prepare_result_secret_is_redacted_on_disk_and_download`
  (uses the new stub `tests/stubs/leaks_secret_prepare_fail`)

## Changes — only `app/core/supervisor.py`

### 1. Add the helper next to `_scrub_context_secrets`
```python
def _scrub_result_secrets(result_path: Path, secret_values: frozenset[str]) -> None:
    """Redact any injected secret VALUES from an on-disk result.json, best-effort. Covers the
    prepare FAILURE path (prepare wrote result.json then exited non-zero, so the success-path
    redaction was skipped); result.json, unlike context.json, is downloadable. Never raises."""
    try:
        if not result_path.is_file():
            return
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        write_json_atomic(result_path, _redact_secrets(payload, secret_values))
    except (OSError, ValueError):
        return
```
(`_redact_secrets` already recursively redacts any JSON payload — dict, list, str — so it handles
whatever a workflow wrote. Catch only `OSError`/`ValueError` so scrubbing never crashes teardown.)

### 2. Call it in the `_run_prepare` `finally`
```python
    finally:
        state.unregister_proc("prep")
        _scrub_context_secrets(context_path)
        _scrub_result_secrets(result_path, state.secret_values)
```
Leave the success-path redaction (`redacted = _redact_secrets(payload, state.secret_values)` +
`write_json_atomic(result_path, redacted)` + `return True, redacted`) UNCHANGED — it still produces
the return value; the finally scrub of the already-redacted file is idempotent and harmless.

## Scope / do NOT
- ONLY `app/core/supervisor.py`. Do NOT change `get_run_file`, `_redact_secrets`,
  `_scrub_context_secrets`, the success-path logic, any test, or any stub.
- No new dependencies. `result_path` and `state.secret_values` are already in scope in `_run_prepare`.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/core/test_secret_redaction.py tests/api/test_secret_exposure.py tests/api/test_secret_injection.py -q` → all pass (the three new H18 tests plus every prior redaction/exposure/injection test). NOTE: the integration tests that spawn a real runner subprocess may be environment-flaky on some Windows dev boxes but pass in CI; the two `_scrub_result_secrets` UNIT tests must pass everywhere.
- `ruff check app tests` and `ruff format --check app tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
