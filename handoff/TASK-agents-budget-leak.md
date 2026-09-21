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
**Do NOT use the `_budget_reserved` context manager** — its "release on ANY exception" is wrong for a
paid call, because a transport error (or a post-200 failure) is AMBIGUOUS: the provider may have
already billed. Mirror the EXISTING, TESTED sibling on the identical OpenRouter path,
`app/learning/completion.py::make_openrouter_completion` — a bare `reserve` + an `unbilled` flag +
`try/finally` that releases ONLY on a CONFIRMED-unbilled outcome. Only two outcomes are
confirmed-unbilled and release: a non-2xx error RESPONSE (incl. 402) and 429-retries-exhausted.
Everything else — a transport exception from `client.post`, a post-200 parse/teardown/emit failure,
or a 200 with unknown cost — RETAINS the estimate (conservative over-count), matching
`completion.py` and `test_learning_completion.py::test_transport_error_keeps_the_reservation`.

Use exactly this structure:

```
key = ctx.secret("OPENROUTER_API_KEY")
token = ctx._budget_reserve("openrouter", "usd")
unbilled = False
try:
    with _http_client() as client:
        for _attempt in range(_MAX_ATTEMPTS):
            with _LIMITER.slot("openrouter"):
                resp = client.post("/chat/completions",
                                   headers={"Authorization": f"Bearer {key}"}, json=body)
            if resp.status_code == 200:
                break
            if resp.status_code == 429:
                _LIMITER.penalize("openrouter", _retry_after_s(resp.headers.get("Retry-After")))
                continue
            if resp.status_code == 402:
                unbilled = True
                raise RuntimeError("OpenRouter: insufficient credits (402)")
            unbilled = True
            raise RuntimeError(f"OpenRouter error {resp.status_code}: {resp.text}")
        else:
            unbilled = True
            raise RuntimeError("OpenRouter: rate limited after retries (429)")

        try:
            data: dict[str, Any] = resp.json()
        except Exception as exc:
            raise RuntimeError("OpenRouter: unreadable 200 response body") from exc
    cost = _usage_cost(data)
    if cost is not None:
        ctx._budget_reconcile(token, actual=cost)   # reconcile the real cost BEFORE emit
        ctx.emit({"t": "cost", "meter": "openrouter", "unit": "usd", "amount": cost, "cached": False})
    return data
finally:
    if unbilled:
        ctx._budget_reconcile(token, actual=0.0, note="released")
```

Semantics (each verified by a frozen test): 402 / non-2xx / 429-exhausted set `unbilled=True` before
raising, so the `finally` releases (`actual=0.0`) — these are confirmed unbilled. A transport error
from `client.post`, a post-200 `resp.json()` failure, the client teardown, or a 200 lacking
`usage.cost` all leave `unbilled=False`, so the `finally` does NOT release and the reserve stands at
its estimate (the ledger's `effective_amount` falls back to the reserved amount — a safe over-count).
A billed 200 reconciles the real `usage.cost` (before the fragile `emit`, so a telemetry failure
cannot lose it). Keep `data`'s type annotation for mypy; the parse `except` always raises, so `data`
is bound at `_usage_cost(data)`.

Do not change the retry/limiter/error semantics for the 402/non-2xx/429 paths, and never log the
bearer key.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_agents_budget_release.py tests/integration/test_agents_openrouter_llm.py -q`
  → **all pass** (7 release-contract cases + the existing openrouter llm tests).
- `python -m ruff format --check sdk/sfvf/agents.py` and `python -m ruff check sdk/sfvf/agents.py` → clean.
- `git diff --name-only` shows **only** `sdk/sfvf/agents.py`.
