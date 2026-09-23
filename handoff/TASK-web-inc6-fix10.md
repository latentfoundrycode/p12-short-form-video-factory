# TASK — web-image-sourcing inc6 FIX round 10: don't charge free SerpApi cache hits

## Why this round
Cross-family review (P2): the serpapi adapter reserves the per-search price and, on any 2xx, records
that full price. But SerpApi serves a repeated query from its own cache and marks it **free** with
`search_metadata.status == "Cached"` (fresh searches are `"Success"`). Charging a cached hit falsely
consumes the SFVF budget and can exhaust the per-day ceiling, blocking later real searches.

Fix: reserve before dispatch as now, but reconcile a **cached** 200 to **$0** (a zero-amount cost
event) instead of the per-search price. A fresh 200 (status `"Success"`, or missing/unknown) is still
charged the price (fail toward charging, never under-charge on an unknown status).

A frozen RED contract is committed (HEAD) in `tests/integration/test_media_web_web.py`:
`test_a_cached_serpapi_response_is_not_charged` and
`test_repeated_cached_searches_do_not_exhaust_the_ceiling`.

## Change (one file) — `sdk/sfvf/providers/serpapi.py`
In `search()`, after `data = parse_json(resp, ...)`, detect a cached response and reconcile the cost
accordingly. Keep the reserve/billed-flag/finally structure exactly as it is; only the amount and
source passed to `record_cost` change:
```python
        data = parse_json(resp, provider="serpapi", where="GET /search")
        # SerpApi serves repeated queries from its cache and marks them free ("Cached"); only a fresh
        # ("Success"/unknown) 200 is billed. Fail toward charging on an unknown status.
        meta = data.get("search_metadata")
        cached = isinstance(meta, dict) and str(meta.get("status") or "").lower() == "cached"
        results = data.get("images_results")
        ...  # EXISTING mapping loop, unchanged
        if cached:
            ctx.record_cost(provider.meter, provider.unit, 0.0, "cached", token=token)
        else:
            ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
        return out
```
Notes:
- `record_cost(..., 0.0, "cached", token=token)` reconciles the reservation to $0 AND emits a
  zero-amount cost event for observability — so the ceiling is not consumed by a free hit.
- Do NOT change the reserve, the `billed` flag, the `except AdapterError`/release logic, the finally
  block, or the candidate mapping. A cached response still maps candidates normally.
- `price` is the already-computed effective per-search price (configured rate or default); reuse it.

## Scope
Only `sdk/sfvf/providers/serpapi.py`. No other file, no test, no `web.py`/`context.py`/`_budget.py`,
no registry. No new dependencies. Never read/log the api_key.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_web.py -q` → all pass (the two new
  cached tests green; the existing "reserves and records a priced cost", price-floor, malformed-200,
  and budget tests — which use `_ok` with an empty `search_metadata` (not "Cached") — still charge the
  price and stay green).
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_commons.py tests/integration/test_media_web_surface.py tests/integration/test_media_web_fetch.py -q` → still pass.
- `ruff check sdk tests` and `ruff format --check sdk tests` clean. Do NOT create any notes/docs files.
