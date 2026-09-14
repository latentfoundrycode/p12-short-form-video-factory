# TASK H43 — learning completion: untrusted-response error contract + 429 retry

## Goal (one sentence)
Harden `app/learning/completion.py` so a malformed OpenRouter 200 body surfaces as `CompletionError`
(never a raw exception), and a 429 is retried (bounded) honoring `Retry-After` — mirroring the
`agents.llm` reference — before the first real learning run.

## Frozen contract (already committed — do NOT edit)
`tests/integration/test_learning_completion.py` (the four new H43 tests plus all existing ones).

## Reference to MIRROR (do not modify it)
`sdk/sfvf/agents.py`: `_retry_after_s` (Retry-After parse with `_RETRY_AFTER_DEFAULT_S`), the
`_MAX_ATTEMPTS`/429 loop in `_post_chat_completion`, and `_usage_cost`.

## What to change — `app/learning/completion.py` only
1. **Injected sleep seam + retry constants.** Add `import time`. Add module constants
   `_RETRY_AFTER_DEFAULT_S = 1.0` and `_MAX_ATTEMPTS = 3`. Add a `_retry_after_s(header: str | None)
   -> float` helper mirroring `agents._retry_after_s` (non-numeric/negative/non-finite → the default).
2. **New keyword param** on `make_openrouter_completion(...)`:
   `sleep: Callable[[float], None] = time.sleep` (keyword, defaulted — existing callers unaffected).
3. **Retry loop.** Inside `with client_factory() as client:`, replace the single POST with a bounded
   loop of up to `_MAX_ATTEMPTS`:
   - POST `/chat/completions` (same headers/body).
   - `200` → break out and parse.
   - `429` → `sleep(_retry_after_s(resp.headers.get("Retry-After")))` and retry (do not raise yet).
   - any other non-200 → `raise CompletionError(f"OpenRouter error {resp.status_code}")` (no body/key).
   - if the loop exhausts all attempts still on 429 → `raise CompletionError("OpenRouter rate
     limited after retries (429)")`.
   Keep the reservation (`guard.reserve`) BEFORE the loop (one reservation per logical call, as now);
   reconciliation stays after a 200, unchanged.
4. **Guard the response parse.** After a 200:
   - `try: data = resp.json()` / `except Exception → raise CompletionError("OpenRouter returned a
     malformed response body")`. (A non-JSON body must not escape as `JSONDecodeError`.)
   - if `not isinstance(data, dict)` → `raise CompletionError("OpenRouter response has the wrong
     shape")` BEFORE calling `_usage_cost(data)` (a non-dict must not hit `.get`).
   - then the existing `_usage_cost` / reconcile / content-extraction path, unchanged.

Everything else stays exactly as is: key-validated first; fail-closed budget reserve before any
client is built; the bearer key never appears in a log or error; reconcile the actual `usage.cost`
(reservation stands at the estimate when cost is absent).

## Constraints / do-nots
- Touch ONLY `app/learning/completion.py`. Do NOT edit the test, the SDK (`agents.py`), or anything
  else. Do not import the private `agents._retry_after_s` — mirror it locally.
- Keep `ruff check .`, `ruff format --check .`, and `mypy sdk app` clean; ≤100 cols.

## Scope
- `app/learning/completion.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/integration/test_learning_completion.py -q` → all pass (11 tests).
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
