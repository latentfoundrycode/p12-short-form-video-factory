# TASK — failed-prepare result.json redaction (H18) — COMPLETION (pathological payloads)

## Why (round 3)
Cross-family review found `_scrub_result_secrets` still crashes teardown on a pathologically nested
`result.json`: `json.loads` (and the recursive `_redact_secrets`) raise `RecursionError` on ~2000
levels of nesting. `RecursionError` is not in the caught `(OSError, ValueError, TypeError)`, so it
escapes the `finally`, crashes `_run_prepare`, and leaves the secret-bearing (downloadable) file
unredacted. In the H18 threat model (a third-party workflow leaking the operator's injected key), a
hostile workflow can craft this deliberately.

Fix: make the scrub robust and never-raising by adding a TEXT-LEVEL redaction fallback that does not
parse JSON (so no structure/depth can defeat or crash it), used whenever the structured parse+redact
fails. The structured path stays primary for normal payloads (clean JSON output); the text fallback
guarantees a leaked value cannot survive on disk.

Frozen RED test (committed, do not modify):
`tests/core/test_secret_redaction.py::test_scrub_result_secrets_survives_pathologically_nested_json`
(2000 nested arrays around `sk-secret-xyz` → must not raise, secret gone). All other existing
`scrub_result` tests must stay green.

## Changes

### 1. `app/core/records.py` — an atomic TEXT writer
Add next to `write_json_value_atomic` (same temp+fsync+`os.replace`+cleanup logic, writing raw text):
```python
def write_text_atomic(path: Path, text: str) -> None:
    """Atomically write raw text to path (temp file + fsync + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _retry_on_permission_error(lambda: os.replace(tmp_path, path))  # noqa: PTH105  # os.replace is atomic on Windows
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
```

### 2. `app/core/supervisor.py` — text-level fallback in `_scrub_result_secrets`
Import `write_text_atomic` (add to the existing `app.core.records` import), and restructure the helper
so structured redaction is attempted first, with a never-recursing text fallback on ANY failure:
```python
def _scrub_result_secrets(result_path: Path, secret_values: frozenset[str]) -> None:
    """Redact any injected secret VALUES from an on-disk result.json, best-effort, covering the
    prepare FAILURE path and any payload shape. Structured redaction is attempted first; if it fails
    (unparsable, or a pathologically deep payload that would raise RecursionError), a text-level
    replacement strips the secret VALUES without parsing JSON. Never raises."""
    try:
        if not result_path.is_file():
            return
        raw = result_path.read_text(encoding="utf-8")
    except OSError:
        return
    try:
        payload = json.loads(raw)
        write_json_value_atomic(result_path, _redact_secrets(payload, secret_values))
        return
    except (OSError, ValueError, TypeError, RecursionError):
        pass  # fall through to a text-level pass that cannot recurse or be defeated by structure
    real = sorted((v for v in secret_values if v), key=len, reverse=True)
    redacted = raw
    for value in real:
        redacted = redacted.replace(value, "[REDACTED]")
    if redacted != raw:
        try:
            write_text_atomic(result_path, redacted)
        except OSError:
            return
```
Notes:
- The primary structured path is unchanged for normal payloads (still emits clean JSON via
  `write_json_value_atomic`), so `null`/scalar/string/array/object all keep their current behaviour
  and the existing tests stay green.
- The fallback only runs when the structured attempt raised; it replaces the longest secret values
  first (so a shorter value that is a prefix of a longer one cannot leave a dangling suffix), and
  writes nothing when no secret value is present (a no-secret unparsable file is left as-is, matching
  the existing best-effort test).
- Both the structured `write_json_value_atomic` and the fallback `write_text_atomic` are atomic; a
  read/write `OSError` is swallowed. The helper never raises.

Leave the `_run_prepare` `finally` call site and the success-path redaction UNCHANGED.

## Scope / do NOT
- Only `app/core/records.py` (add `write_text_atomic`) and `app/core/supervisor.py` (import + helper
  body). Do NOT change `write_json_value_atomic`, `write_json_atomic`, `_redact_secrets`,
  `get_run_file`, the finally call site, the success path, any test, or any stub. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/core/test_secret_redaction.py -q -k "scrub_result"` → all
  pass, including `test_scrub_result_secrets_survives_pathologically_nested_json` (no crash, secret
  gone) and every prior case (dict, non-object null/string/array/scalar, missing/bad-file).
- `PYTHONPATH=sdk python -m pytest tests/core/test_records.py -q` → all pass.
- `ruff check app tests` and `ruff format --check app tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
