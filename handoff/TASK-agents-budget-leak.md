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
The reserved region must wrap **ONLY** the HTTP retry loop, and the HTTP client `with` must nest
**OUTSIDE** the reserved region. A received HTTP 200 means the provider has already billed, so NOTHING
that runs after a 200 — parsing, the cost reconcile, the CLIENT TEARDOWN (`_http_client().__exit__`),
telemetry, or the return — may sit inside `_budget_reserved` (the ledger is last-actual-wins, so a
release on any of those would overwrite the real cost and under-count genuine spend). Use exactly this
structure:

```
key = ctx.secret("OPENROUTER_API_KEY")
with _http_client() as client:                       # OUTSIDE the reserved region
    with ctx._budget_reserved("openrouter", "usd") as token:   # wraps ONLY the retry loop
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
                raise RuntimeError("OpenRouter: insufficient credits (402)")
            raise RuntimeError(f"OpenRouter error {resp.status_code}: {resp.text}")
        else:
            raise RuntimeError("OpenRouter: rate limited after retries (429)")
    # _budget_reserved has exited CLEANLY here (a 200 was received; the loop only raises on
    # UNBILLED failures, which release). The client is still open — parse the billed response,
    # capturing any error so it does NOT escape as a bare exception:
    try:
        data = resp.json()
        cost = _usage_cost(data)
    except Exception as exc:
        post_error, data, cost = exc, None, None
    else:
        post_error = None
    if cost is not None:
        ctx._budget_reconcile(token, actual=cost)    # real billed cost; outside the reserved region
# client closed here (teardown is OUTSIDE the reserved region -> cannot release)
if post_error is not None:
    raise RuntimeError("OpenRouter: unreadable 200 response body") from post_error
if cost is not None:
    ctx.emit({"t": "cost", "meter": "openrouter", "unit": "usd", "amount": cost, "cached": False})
if data is None:
    raise RuntimeError("OpenRouter: unreadable 200 response body")
return data
```

Why the nesting matters: pre-200 failures (402 / non-2xx / 429-exhausted / transport error) raise
INSIDE `_budget_reserved`, which reconciles `actual=0.0` ("released") — correct, not billed. A 200
`break` exits `_budget_reserved` with no exception, so the reserve is NOT released; it stands at its
estimate until reconciled. Everything after that — parse, reconcile, `_http_client` teardown, emit,
return — is OUTSIDE the reserved region, so no post-billing failure can release a genuine spend.

Net: a failed (unbilled) call releases the reserve; a billed 200 reconciles the real `usage.cost`; a
billed 200 whose body is unreadable or lacks `usage.cost` keeps the reserve at its estimate and raises
a clean `RuntimeError` (never a raw JSONDecodeError, never a release to 0); and a client-teardown error
after a 200 cannot release. Do not change the retry/limiter/error semantics for the 402/non-2xx/429
paths, and never log the bearer key.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_agents_budget_release.py tests/integration/test_agents_openrouter_llm.py -q`
  → **all pass** (4 release-contract + the existing openrouter llm tests).
- `python -m ruff format --check sdk/sfvf/agents.py` and `python -m ruff check sdk/sfvf/agents.py` → clean.
- `git diff --name-only` shows **only** `sdk/sfvf/agents.py`.
