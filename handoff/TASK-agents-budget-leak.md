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
**Do NOT use the `_budget_reserved` context manager.** Use a bare `reserve` + an `unbilled` flag +
`try/finally` (like `app/learning/completion.py::make_openrouter_completion`), but with TWO refinements
that fix edges completion.py still has (Review B P1/P2). The release rule is: RELEASE the reserve iff
the call is CONFIRMED unbilled; RETAIN the estimate iff billing is AMBIGUOUS or confirmed billed.

- **Confirmed unbilled → release**: any failure BEFORE the first request is dispatched (e.g.
  `_http_client()` construction), a non-2xx error RESPONSE (incl. 402), and 429-retries-exhausted.
- **Ambiguous or billed → retain the estimate**: a transport exception FROM `client.post` (the request
  may have reached the server and billed), a post-200 parse/teardown/emit failure, or a 200 lacking
  `usage.cost`.
- **Billed 200 with a cost → reconcile the REAL `usage.cost`, recorded INSIDE the client block (before
  the client teardown) so a teardown error cannot lose it** (P1).

Implement it with `unbilled = True` initially (a pre-dispatch failure releases — P2), flipped to
`False` immediately before each `client.post` (from then on a transport error is ambiguous and
retains), and set back to `True` only on a confirmed-unbilled RESPONSE. Use exactly this structure:

```
key = ctx.secret("OPENROUTER_API_KEY")
token = ctx._budget_reserve("openrouter", "usd")
unbilled = True   # nothing dispatched yet -> a failure before the first request releases (P2)
try:
    with _http_client() as client:
        for _attempt in range(_MAX_ATTEMPTS):
            unbilled = False   # about to dispatch; a transport error from here is AMBIGUOUS -> retain
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

        # 200 (billed). Parse and reconcile the REAL cost INSIDE the client block, so it is recorded
        # BEFORE the client teardown (P1). unbilled stays False (retain on any further failure).
        try:
            data: dict[str, Any] = resp.json()
        except Exception as exc:
            raise RuntimeError("OpenRouter: unreadable 200 response body") from exc
        cost = _usage_cost(data)
        if cost is not None:
            ctx._budget_reconcile(token, actual=cost)   # BEFORE emit and BEFORE teardown
            ctx.emit({"t": "cost", "meter": "openrouter", "unit": "usd", "amount": cost, "cached": False})
        return data
finally:
    if unbilled:
        ctx._budget_reconcile(token, actual=0.0, note="released")
```

Note `return data` is INSIDE the `with _http_client()` block (so `data` is bound and the real cost is
already reconciled before teardown). Keep `data`'s type annotation for mypy; the parse `except` always
raises, so `data` is bound at `_usage_cost(data)`. Do not change the retry/limiter semantics, and never
log the bearer key.

Do not change the retry/limiter/error semantics for the 402/non-2xx/429 paths, and never log the
bearer key.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_agents_budget_release.py tests/integration/test_agents_openrouter_llm.py -q`
  → **all pass** (7 release-contract cases + the existing openrouter llm tests).
- `python -m ruff format --check sdk/sfvf/agents.py` and `python -m ruff check sdk/sfvf/agents.py` → clean.
- `git diff --name-only` shows **only** `sdk/sfvf/agents.py`.
