# TASK — release the budget reservation on a failed learning call + log the run failure

## Goal (one sentence)
A learning completion that never returns a billed 200 must reconcile its budget reservation to 0 (so
repeated failures don't accumulate and exhaust the daily learning budget), and the learning-run API
endpoint must log the underlying cause of a failure (today its 502 is undiagnosable).

## Frozen contract (already committed — do NOT edit)
`tests/integration/test_learning_completion.py::test_failed_call_releases_its_budget_reservation`
(plus all existing tests in that file must stay green).

## Fix 1 — `app/learning/completion.py`: release the reservation on a non-billed failure
Today `make_openrouter_completion`'s `complete()` reserves, then on a non-200 / exhausted-429 it
raises `CompletionError` WITHOUT reconciling — so the estimate stays reserved forever. A 200 (even a
malformed/missing-content one) WAS billed, so its reservation must stand (or reconcile the actual
`usage.cost`, as today); only a path where NO 200 was received should release.

Restructure `complete()` so:
- Track whether a 200 was received, e.g. `got_response = False` set to `True` right after
  `if resp.status_code == 200: got_response = True; break`.
- Wrap everything AFTER `token = guard.reserve(...)` in `try: ... finally:`; in the `finally`, if NOT
  `got_response`, call `guard.reconcile(token, actual=0.0)` (release — the call was not billed).
- Keep the existing 200 handling exactly: parse guard, `cost = _usage_cost(data)` and
  `if cost is not None: guard.reconcile(token, actual=cost)`, then content extraction / return.
  (A 200 with `cost is None` leaves the estimate standing, unchanged — it was billed, cost unknown;
  do NOT release it — that is why the release is gated on `got_response`, not on "did we reconcile".)
Net effect: 402/other-non-200, exhausted-429, and a transport error after reserve all release the
reservation; a real (billed) 200 keeps its reconcile-actual (or standing estimate when cost is
absent). The bearer key / secret handling and the 429 retry are otherwise unchanged.

## Fix 2 — `app/api/learning.py`: log the underlying cause of a learning-run failure
In `run_learning_for_workflow`, the `except LearningError as exc:` currently raises a bare
`HTTPException(502, detail="learning run failed")`. Before raising, log the real cause so a 502 is
diagnosable in the server console:
```python
import logging
_log = logging.getLogger("app.api.learning")   # module level
...
except LearningError as exc:
    _log.warning("learning run failed for %s: %r", workflow_id, exc.__cause__ or exc)
    raise HTTPException(status_code=502, detail="learning run failed") from exc
```
Add the module-level logger and `import logging` at the top. Do not change the 502 response body or
status (the existing API test asserts 502). `%r` keeps it a single safe repr; do not log secrets (the
cause is a LearningError/CompletionError/OptimizerError message — none carry the key).

## Constraints / do-nots
- Touch ONLY `app/learning/completion.py` and `app/api/learning.py`. Do NOT edit any test or the SDK.
- Keep `ruff check .`, `ruff format --check .`, `mypy sdk app` clean; ≤100 cols.

## Scope
- `app/learning/completion.py`
- `app/api/learning.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/integration/test_learning_completion.py tests/api/test_learning_run_api.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
