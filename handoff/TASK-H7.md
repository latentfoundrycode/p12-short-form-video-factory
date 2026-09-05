# TASK H7 — make atomic-record I/O resilient to the Windows replace/open race

**Builder:** Cursor. **Product code only.** Modify ONLY `app/core/records.py`. Do NOT touch `tests/`, `docs/`,
or `handoff/`. The reviewer contract `tests/core/test_records_atomic_retry.py` is FROZEN — make it pass by
changing product code.

## The flake being fixed (HARDENING H7)

On windows-latest CI, app-layer subprocess-run tests intermittently fail with
`PermissionError [Errno 13]` on `video.json` / `request.json` (blocked CI three times: `test_runs`,
`test_run_events`, `test_supervisor`). Root cause: `write_json_atomic` swaps the record with
`os.replace(tmp, path)` while another party concurrently **reads** the same record via `read_json`
(`path.read_text`). On Windows the in-flight atomic replace and a concurrent `open` produce a transient
file-sharing violation (`PermissionError`) on **either** side — the reader's `open`, or the `os.replace` if a
reader is holding the target. The swap completes in microseconds, so a **small bounded retry on
`PermissionError`** around both operations removes the flake. This is not weakening — it is making the record
I/O correct under the platform's file-sharing semantics.

## Implement in `app/core/records.py`

Add module-level tunables and a tiny retry helper:

```python
import time  # add to imports

_RETRY_ATTEMPTS = 10
_RETRY_DELAY_S = 0.02   # tests monkeypatch this to 0.0

def _retry_on_permission_error(op: Callable[[], _T]) -> _T:
    """Run op(); on a transient PermissionError (Windows atomic-replace/open race), retry a
    bounded number of times with a short delay, then re-raise the last error."""
    last: PermissionError | None = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return op()
        except PermissionError as exc:
            last = exc
            if attempt + 1 < _RETRY_ATTEMPTS:
                time.sleep(_RETRY_DELAY_S)
    assert last is not None
    raise last
```

(Use whatever `TypeVar`/`Callable` typing keeps mypy-strict happy — `from collections.abc import Callable`
is already imported; add a `TypeVar` if needed.)

Then wire it in:

- **`write_json_atomic`** — wrap only the swap:
  `_retry_on_permission_error(lambda: os.replace(tmp_path, path))` in place of the bare `os.replace(...)`.
  Keep the surrounding `try/except Exception: tmp_path.unlink(missing_ok=True); raise` — so when the retries
  are exhausted and `PermissionError` propagates, the temp file is still cleaned up (the frozen test asserts no
  `.tmp` leftover and that the target was never created).
- **`read_json`** — wrap only the read:
  `text = _retry_on_permission_error(lambda: path.read_text(encoding="utf-8"))`, then `json.loads(text)`,
  keeping the existing `isinstance(payload, dict)` check and `TypeError`.

Do not change any other behaviour, signatures, or the fsync/`mkstemp` logic. No new dependency. mypy-strict
clean; touch only `app/core/records.py`.

## Acceptance

- `tests/core/test_records_atomic_retry.py` passes (5 tests): replace retries then succeeds (no `.tmp`
  leftover); replace re-raises after exhausting retries and cleans up; read retries then succeeds; read
  re-raises after exhausting; happy-path round-trip unaffected.
- The existing `tests/core/test_records.py` and the rest of the suite still pass.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest -q tests/core/test_records_atomic_retry.py tests/core/test_records.py
```
(The full `pytest` run also shows 3 pre-existing `finalize`/`example_workflow` failures — ONLY the HyperFrames
toolchain missing in this worktree; CI installs it and runs them green. Ignore them.)
