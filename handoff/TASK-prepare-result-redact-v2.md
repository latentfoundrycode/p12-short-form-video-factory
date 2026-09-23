# TASK — redact a failed-prepare result.json (H18) — COMPLETION (non-object payloads)

## Why (round 2)
Cross-family security review found the round-1 `_scrub_result_secrets` is broken for non-object
`result.json`: it passes the redacted payload straight to `write_json_atomic`, which does
`dict(payload)` internally (`app/core/records.py`). Therefore:
1. **Crash on the standard success path:** `prepare()` returning `None` makes the runner write
   `result.json = null`. `dict(None)` raises `TypeError` (NOT in the caught `(OSError, ValueError)`),
   so the new `finally` scrub **crashes every `prepare()->None` run** before `_run_prepare` returns.
2. **Still leaks:** a top-level JSON **string**/**array** carrying the secret → `dict("sk-…")`
   raises `ValueError`, which IS swallowed, leaving the secret un-rewritten on disk (downloadable).

Fix: write the redacted payload with an atomic writer that accepts ANY JSON value (not only a
Mapping), and make the scrub never raise on any JSON type while still redacting string/array/scalar
payloads.

Frozen RED tests (committed, do not modify):
`tests/core/test_secret_redaction.py::test_scrub_result_secrets_handles_non_object_result`
(parametrized: `None`, top-level string, array-with-secret, scalar `42`) — plus the existing
`test_scrub_result_secrets_redacts_an_on_disk_result` and
`test_scrub_result_secrets_is_best_effort_on_missing_or_bad_file` must stay green.

## Changes

### 1. `app/core/records.py` — a JSON-VALUE atomic writer
Add a writer that serializes any JSON value, and make `write_json_atomic` delegate to it (so the
Windows-safe temp+fsync+`os.replace` logic stays in one place):
```python
def write_json_value_atomic(path: Path, value: Any) -> None:
    """Atomically write any JSON-serialisable VALUE (object, array, string, number, null) to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _retry_on_permission_error(lambda: os.replace(tmp_path, path))  # noqa: PTH105  # os.replace is atomic on Windows
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    write_json_value_atomic(path, dict(payload))
```
(`write_json_atomic` keeps its `Mapping` signature and existing behaviour — it still coerces to a
`dict` for its callers. Only `_scrub_result_secrets` uses the general writer.)

### 2. `app/core/supervisor.py` — use the value writer; never raise on any type
Import `write_json_value_atomic` from `app.core.records` (add it to the existing import block), and
change the helper to use it:
```python
def _scrub_result_secrets(result_path: Path, secret_values: frozenset[str]) -> None:
    """Redact any injected secret VALUES from an on-disk result.json, best-effort. Covers the
    prepare FAILURE path (prepare wrote result.json then exited non-zero, so the success-path
    redaction was skipped) AND the ordinary null/scalar/string/array payloads; result.json, unlike
    context.json, is downloadable. Never raises."""
    try:
        if not result_path.is_file():
            return
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        write_json_value_atomic(result_path, _redact_secrets(payload, secret_values))
    except (OSError, ValueError, TypeError):
        return
```
(`_redact_secrets` already handles any JSON node — dict/list/str/scalar/None — returning the same
shape. `write_json_value_atomic` serialises any of them without `dict()`. `TypeError` is caught too
so an unforeseen non-serialisable value can never crash teardown.)

Leave the `_run_prepare` `finally` call site and the success-path redaction UNCHANGED.

## Scope / do NOT
- Only `app/core/records.py` (add `write_json_value_atomic`, delegate `write_json_atomic`) and
  `app/core/supervisor.py` (import + helper body). Do NOT change the `finally` call site, the
  success path, `_redact_secrets`, `get_run_file`, any test, or any stub. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/core/test_secret_redaction.py -q -k "scrub_result"` → all
  pass (the four non-object cases plus the dict and missing/bad-file cases; none raises).
- `PYTHONPATH=sdk python -m pytest tests/core/test_records.py tests/core/test_secret_redaction.py tests/api/test_secret_exposure.py -q` → all prior records/redaction/exposure tests still pass (the `write_json_atomic` refactor must be behaviour-preserving). Real-subprocess integration tests may be env-flaky on Windows dev boxes but pass in CI; the `scrub_result` UNIT tests must pass everywhere.
- `ruff check app tests` and `ruff format --check app tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
