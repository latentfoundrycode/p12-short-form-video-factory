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
Replace the bare reserve with the `_budget_reserved` context manager, wrapping ONLY the paid-call
region (the HTTP client + retry loop + `resp.json()` + cost reconcile). Concretely:
- Keep `instructions`/`body` assembly and `key = ctx.secret("OPENROUTER_API_KEY")` where they are
  (not paid).
- Change `token = ctx._budget_reserve("openrouter", "usd")` to
  `with ctx._budget_reserved("openrouter", "usd") as token:` and indent the existing
  `with _http_client() as client: ...` block, the `data = resp.json()`, `cost = _usage_cost(data)`,
  and the success-path `ctx.emit(...)` / `ctx._budget_reconcile(token, actual=cost)` inside it.
- `return data` stays after the `with` block (or at its end) — unchanged behaviour on success.

The effect: every non-success exit (402 raise, non-2xx raise, 429-exhausted raise, or any exception)
propagates through `_budget_reserved`, which reconciles the reserve to 0.0 ("released"); the 200 path
still reconciles the real `usage.cost`. Do not otherwise change the retry/limiter/error semantics
(the bearer key must still never be logged or put in an error message).

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_agents_budget_release.py tests/integration/test_agents_openrouter_llm.py -q`
  → **all pass** (4 release-contract + the existing openrouter llm tests).
- `python -m ruff format --check sdk/sfvf/agents.py` and `python -m ruff check sdk/sfvf/agents.py` → clean.
- `git diff --name-only` shows **only** `sdk/sfvf/agents.py`.
