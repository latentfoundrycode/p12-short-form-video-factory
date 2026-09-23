# TASK — web-image-sourcing inc6 FIX round 2: SerpApi billing boundary

## Why this round
Round 1 budget-gated the web search by wrapping the adapter call in
`ctx._budget_reserved(...)` inside `media/web.py`. Cross-family review found that incomplete
(**P1**): `_budget_reserved` releases the reserve to **$0 on ANY exception** — including a
parse/mapping failure that happens **after** a billable HTTP 200. SerpApi bills per **successful**
search, so a malformed 200 body (or a malformed field) would incur real spend that never counts
toward the ceilings; repeated failures then bypass the daily cap.

The billing boundary (did we get a 200?) is observable **only inside the adapter** — the media layer
sees only "adapter.search raised or returned" and cannot tell a pre-200 non-2xx (unbilled) from a
post-200 parse failure (billed), because `_http.request()` and `_http.parse_json()` raise the **same**
`AdapterError`. So the reserve/reconcile discipline must **move into the serpapi adapter**, mirroring
the blessed pattern in `app/learning/completion.py::make_openrouter_completion` and
`sdk/sfvf/agents.py::_post_chat_completion` (bare `_budget_reserve` + a billed flag + `try/finally`
that releases only on a confirmed-unbilled outcome).

A frozen RED contract is already committed (`tests/integration/test_media_web_web.py`, HEAD). Make it
green. There are **15** web-tier tests; 13 pass now, 2 are RED (`...retains_the_charge...`,
`...accumulate_toward_the_serpapi_ceiling`).

## Reference pattern — study it first
`sdk/sfvf/agents.py::_post_chat_completion` (lines ~140-191): `token = ctx._budget_reserve(...)`;
an `unbilled`/billed flag flipped around the dispatch; on a 200 the flag says "billed" so any later
parse failure retains; a `finally` reconciles `actual=0.0` (release) **only** when still unbilled;
on success it reconciles the real cost. Also read `sdk/sfvf/context.py` `_budget_reserve` /
`_budget_reconcile` / `record_cost` (~509-590) and `sdk/sfvf/providers/_http.py` `request` (returns
**only** on 2xx; raises `AdapterError` on non-2xx after its own 429 retries) and `parse_json`.

## Changes (exactly two files)

### 1. `sdk/sfvf/media/web.py` — REVERT the round-1 wrapper
Return the `else: # "web"` branch of `search()` to the simple dispatch (the budget now lives in the
adapter). Remove the `if limit <= 0: continue` guard, the `price = adapter.search_price()` line, the
`with ctx._budget_reserved(...)` wrapper, and the `ctx.record_cost(...)` call. It should read exactly:
```python
        else:  # "web" — PAID tier; the serpapi adapter owns the budget reserve/reconcile
            provider = PROVIDERS["serpapi"]
            secrets = {name: ctx.secret(name) for name in provider.secret_names}
            adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
            out.extend(
                adapter.search(
                    query, limit=limit, licence=licence, provider=provider, secrets=secrets
                )
            )
```
Leave the `commons` branch unchanged.

### 2. `sdk/sfvf/providers/serpapi.py` — own the reserve/reconcile at the billing boundary
- Keep the `_SEARCH_PRICE_USD = 0.02` constant. **Remove** the now-unused `search_price()` function
  (the adapter uses the constant directly).
- Add imports: `from .._runtime import current_context` and `from .base import AdapterError`.
- Rewrite `search(...)` so the reserve is taken BEFORE dispatch and released only when confirmed
  unbilled. Keep the existing pre-dispatch guards (`if limit <= 0: return []`; the missing-key
  `RuntimeError`) BEFORE the reserve. Keep the existing param build, the candidate mapping, and the
  return value byte-identical — only wrap the dispatch/parse in the budget discipline:
```python
    ctx = current_context()
    ...  # existing limit<=0 short-circuit, key read + missing-key RuntimeError, params, url
    token = ctx._budget_reserve(provider.meter, provider.unit, estimate=_SEARCH_PRICE_USD)
    billed = True  # about to dispatch; an ambiguous transport failure from here RETAINS (fail closed)
    try:
        with _client() as client:
            try:
                resp = request(
                    client, "GET", url, provider="serpapi", auth=_Anon(), limiter=LIMITER
                )
            except AdapterError:
                # request() raises only for a non-2xx response (after its 429 retries); SerpApi does
                # not bill a failed search, so this is CONFIRMED unbilled -> release in finally.
                billed = False
                raise
        # request() returned -> a 2xx -> SerpApi billed this search. From here (parse + mapping) any
        # failure RETAINS the estimate: the search was billed even if the body is unusable.
        data = parse_json(resp, provider="serpapi", where="GET /search")
        results = data.get("images_results")
        ...  # EXISTING mapping loop, unchanged
        ctx.record_cost(provider.meter, provider.unit, _SEARCH_PRICE_USD, "priced", token=token)
        return out
    finally:
        if not billed:
            ctx._budget_reconcile(token, actual=0.0, note="released")
```
Notes:
- Do NOT catch `parse_json`'s `AdapterError` — it must propagate with `billed=True` so the charge is
  retained. The inner `except AdapterError` wraps ONLY the `request(...)` call.
- `record_cost` both emits the `{"t":"cost"}` event and reconciles the reservation to the price.
- The mapping loop body stays exactly as it is (do not add per-field try/except; a malformed body
  raising is acceptable and is now correctly retained).

## Scope — do NOT touch anything else
Only `sdk/sfvf/media/web.py` and `sdk/sfvf/providers/serpapi.py`. Do not change the commons branch,
`fetch`, `check_relevance`, `source`, `_http.py`, `_budget.py`, `context.py`, the registry, or
`meters.py`. No new dependencies. Never read/log/print `SERPAPI_API_KEY`.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_web.py -q` → **15 passed**.
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_commons.py tests/integration/test_media_web_surface.py tests/integration/test_media_web_fetch.py -q` → still pass.
- `ruff check sdk tests` and `ruff format --check sdk tests` clean.
