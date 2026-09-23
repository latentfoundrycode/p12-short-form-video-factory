# TASK — failed-prepare result.json redaction (H18) — COMPLETION (bytes + escaped forms)

## Why (round 4)
Review A found two more issues in `_scrub_result_secrets`:
1. **BLOCKING regression:** the v3 read is `raw = result_path.read_text(encoding="utf-8")` wrapped in
   `except OSError:` only. Invalid UTF-8 bytes raise `UnicodeDecodeError` (a `ValueError` subclass,
   NOT `OSError`), which escapes the helper, crashes teardown in the `finally`, and leaves the
   secret-bearing downloadable `result.json` unredacted. (The round-1 helper caught
   `(OSError, ValueError)`; the v3 restructure dropped `ValueError` on the read.)
2. **Advisory (fold in):** the text fallback matches the PLAIN secret against the raw JSON text, so a
   secret containing a JSON meta-character (`"`, `\`, …) survives in its ESCAPED on-disk form.

Fix: read BYTES (no decode step can crash), keep the structured redaction as the primary path (clean
JSON, correct handling of escaped values via parsed strings), and make the byte-level fallback strip
BOTH the plain and the JSON-escaped forms of each secret. The helper must never raise for any input.

Frozen RED tests (committed, do not modify):
`tests/core/test_secret_redaction.py::test_scrub_result_secrets_survives_invalid_utf8`,
`::test_scrub_result_secrets_fallback_strips_json_escaped_secret`, plus every prior `scrub_result`
test must stay green.

## Changes

### 1. `app/core/records.py` — rename the text writer to a BYTES writer
Replace `write_text_atomic(path, text)` with `write_bytes_atomic(path, data)` (same atomic pattern,
binary mode). Keep `write_json_value_atomic` and `write_json_atomic` exactly as they are.
```python
def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Atomically write raw bytes to path (temp file + fsync + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _retry_on_permission_error(lambda: os.replace(tmp_path, path))  # noqa: PTH105  # os.replace is atomic on Windows
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
```
(If anything other than `_scrub_result_secrets` imported `write_text_atomic`, it did not — this
increment introduced it — so the rename is self-contained.)

### 2. `app/core/supervisor.py` — read bytes; structured primary; byte fallback (plain + escaped)
Change the import from `write_text_atomic` to `write_bytes_atomic`, and rewrite the helper:
```python
def _scrub_result_secrets(result_path: Path, secret_values: frozenset[str]) -> None:
    """Strip any injected secret VALUE from an on-disk result.json, best-effort, so it cannot persist
    in a downloadable file. Reads raw bytes (no decode step can crash). Structured JSON redaction is
    tried first (clean output, handles escaped values); on ANY failure — unparsable, undecodable, or
    pathologically deep — a byte-level pass strips each secret's plain AND JSON-escaped forms without
    parsing. Never raises."""
    real = sorted((v for v in secret_values if v), key=len, reverse=True)
    if not real:
        return
    try:
        if not result_path.is_file():
            return
        raw = result_path.read_bytes()
    except OSError:
        return
    try:
        payload = json.loads(raw.decode("utf-8"))
        write_json_value_atomic(result_path, _redact_secrets(payload, secret_values))
        return
    except (OSError, ValueError, TypeError, RecursionError):
        pass  # undecodable / unparsable / pathologically deep -> byte-level fallback below
    targets: list[bytes] = []
    for value in real:
        targets.append(value.encode("utf-8"))
        escaped = json.dumps(value)[1:-1]  # the escaped inner form as it appears inside a JSON string
        if escaped != value:
            targets.append(escaped.encode("utf-8"))
    redacted = raw
    for target in sorted(targets, key=len, reverse=True):
        redacted = redacted.replace(target, b"[REDACTED]")
    if redacted != raw:
        try:
            write_bytes_atomic(result_path, redacted)
        except OSError:
            return
```
Notes:
- `UnicodeDecodeError` is a `ValueError` subclass, so `(ValueError, …)` catches the undecodable case;
  it then falls to the byte pass, which operates on the raw bytes and cannot decode-fail.
- Longest-first over ALL targets (plain and escaped) so a shorter value that is a prefix of another
  leaves no dangling suffix.
- Structured path is unchanged for normal payloads (clean JSON via `write_json_value_atomic`); the
  existing dict/null/string/array/scalar tests keep passing.

Leave the `_run_prepare` `finally` call site and the success-path redaction UNCHANGED. (The
pre-existing success-path re-parse crash on a pathological RETURN value is recorded separately as
H62 and is out of scope here.)

## Scope / do NOT
- Only `app/core/records.py` (rename write_text_atomic → write_bytes_atomic) and
  `app/core/supervisor.py` (import + helper body). Do NOT change `write_json_value_atomic`,
  `write_json_atomic`, `_redact_secrets`, `get_run_file`, the finally call site, the success path,
  any test, or any stub. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/core/test_secret_redaction.py -q -k "scrub_result"` → all
  pass, including `survives_invalid_utf8` and `fallback_strips_json_escaped_secret`, plus every prior
  case (dict, non-object, deep-nested, missing/bad-file).
- `PYTHONPATH=sdk python -m pytest tests/core/test_records.py -q` → all pass.
- `ruff check app tests` and `ruff format --check app tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
