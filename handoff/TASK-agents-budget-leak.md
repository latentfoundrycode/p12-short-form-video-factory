# TASK — increment 0: agents.llm must release its budget reserve on failure

## Context
`sdk/sfvf/agents.py::_post_chat_completion` reserves budget with the BARE
`token = ctx._budget_reserve("openrouter", "usd")` (~line 141) and reconciles the real cost only on
the HTTP-200 path. On a 402, a generic non-2xx, or retries-exhausted (429) — and on any exception
from the client/JSON parse — it raises WITHOUT reconciling, so the reserve leaks toward the per-day
ceiling (a token's effective spend falls back to its reserved amount). This is the agents.llm
analogue of the media-layer fix (H52); the SDK already has the exact tool for it:
`Context._budget_reserved(meter, unit)` (a context manager that reserves on enter and reconciles
`actual=0.0` — "released" — if the block raises, per sdk/sfvf/context.py:557).

A frozen RED contract is committed: `tests/integration/test_agents_budget_release.py` (do not edit it).

## Scope
- **Edit ONLY** `sdk/sfvf/agents.py`, function `_post_chat_completion`.
- No new dependencies. No test edits. No notes/markdown files.

## Required change
Use `with ctx._budget_reserved("openrouter", "usd") as token:` but END the reserved region at the
BILLABLE BOUNDARY — a received HTTP 200 means the provider has already billed, so a failure AFTER
that point must NOT release the reserve to 0.0 (the ledger is last-actual-wins, so a release would
overwrite a real cost and under-count genuine spend, breaching the per-day ceiling). Concretely:

- Keep `instructions`/`body` assembly and `key = ctx.secret("OPENROUTER_API_KEY")` OUTSIDE (not paid).
- `with ctx._budget_reserved("openrouter", "usd") as token:` wraps the `with _http_client()` retry
  loop. The PRE-200 failures — 402 raise, generic non-2xx raise, 429-retries-exhausted raise, or any
  transport exception — propagate out of the block, so `_budget_reserved` reconciles `actual=0.0`
  ("released"). This is correct: those calls were not billed.
- Once the loop `break`s on a 200 (billed), determine the cost WITHOUT letting a failure escape the
  reserved block as a bare exception. Parse defensively, e.g.:
  ```
      try:
          data = resp.json()
          cost = _usage_cost(data)
      except Exception as exc:
          post_error, data, cost = exc, None, None
      else:
          post_error = None
      if cost is not None:
          ctx._budget_reconcile(token, actual=cost)   # real billed cost
      # cost is None (missing usage OR unreadable body): leave the reserve at its estimate — do NOT
      # release. effective_amount falls back to the reserved estimate (conservative over-count).
  ```
- AFTER the `with` block (outside the reserved region, so these cannot trigger a release): surface a
  parse failure and emit telemetry:
  ```
  if post_error is not None:
      raise RuntimeError("OpenRouter: unreadable 200 response body") from post_error
  if cost is not None:
      ctx.emit({"t": "cost", "meter": "openrouter", "unit": "usd", "amount": cost, "cached": False})
  return data
  ```
  (Move the `ctx.emit(...)` cost event OUT of the reserved region — a telemetry/stdout failure must
  never release a genuine spend.)

Net: a failed (unbilled) call releases the reserve; a billed 200 reconciles the real `usage.cost`; a
billed 200 whose body is unreadable or lacks `usage.cost` keeps the reserve at its estimate and raises
a clean `RuntimeError` (never a raw JSONDecodeError, never a release to 0). Do not change the
retry/limiter/error semantics for the 402/non-2xx/429 paths, and never log the bearer key.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_agents_budget_release.py tests/integration/test_agents_openrouter_llm.py -q`
  → **all pass** (4 release-contract + the existing openrouter llm tests).
- `python -m ruff format --check sdk/sfvf/agents.py` and `python -m ruff check sdk/sfvf/agents.py` → clean.
- `git diff --name-only` shows **only** `sdk/sfvf/agents.py`.
