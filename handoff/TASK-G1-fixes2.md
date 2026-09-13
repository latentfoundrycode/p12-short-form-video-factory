# TASK G-1 fixes (round 2) — redact configured secrets from quality answers

## Why
Cross-family Review B (BLOCKING): the quality endpoint writes user free-text answers straight into
`video.json` without secret redaction, bypassing the system's mandatory "no secret value is ever
written to a record" invariant (upheld for cost/self_review/context via `_redact_secrets`). A
configured secret value pasted into an answer would persist in plaintext. A committed locking test
(`tests/api/test_quality_api.py::test_answers_redact_configured_secrets`) is RED.

## Scope
- `app/api/quality.py`

## Exact change (`app/api/quality.py` only)
1. Imports: add `from app.api.runs import _secrets` (alongside the existing
   `from app.api.runs import _TERMINAL_STATUSES, _holder, _runs_dir` — merge into that line) and
   `from app.core.supervisor import _redact_secrets`.
2. In `submit_quality`, after resolving the request but before/at the write step, compute the
   configured secret values once:
   ```python
   secret_values = frozenset(v for v in _secrets(request).values() if v)
   ```
   `_secrets(request)` returns the app's configured secrets mapping (name -> value); filter out empty
   strings.
3. Redact each `quality` dict against those values immediately before it is written, reusing the
   existing helper (it walks str/dict/list and replaces every occurrence of each secret value with
   "[REDACTED]"):
   ```python
   quality = _redact_secrets(quality, secret_values)
   ```
   Apply it to the `quality` dict for each video AFTER it is fully built and AFTER the `if not
   quality: continue` check, so both the persisted `video.json` value AND the value echoed in the
   response `written` list are redacted. `rankings` (ints) and `accepted` (bool) are untouched by
   redaction; only string answer values change.
Do NOT change validation, status codes, the skip-missing-video.json logic, or the ranking maths.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_quality_api.py -q` → all pass (incl. `test_answers_redact_configured_secrets`).
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
