# TASK — web-image-sourcing inc6 FIX round 11: reconcile a cached hit to $0 BEFORE mapping

## Why this round
Cross-family review (P1): the round-10 cache-hit fix reconciles a cached SerpApi response to $0 only
AFTER the result-mapping loop. But a cached response is KNOWN free the moment it is parsed. If a cached
result has a malformed dimension, the mapping's `int(...)` raises while `billed=True`, so the `finally`
does not release and the full reservation stays charged. Repeated free-but-malformed cache hits could
exhaust the per-day ceiling. Reconcile the cached response to $0 BEFORE the mapping loop, so a later
mapping failure cannot leave a free hit charged.

A frozen RED contract is committed (HEAD): `tests/integration/test_media_web_web.py::test_a_cached_response_is_free_even_if_result_mapping_fails`.

## Change (one file) — `sdk/sfvf/providers/serpapi.py`
Currently `search()` computes `cached` after `parse_json`, then maps, then does the cached/priced
`record_cost` at the end. MOVE the cached reconciliation to immediately after the `cached` check
(before the mapping loop), and keep only the priced (non-cached) `record_cost` after the loop:
```python
        data = parse_json(resp, provider="serpapi", where="GET /search")
        meta = data.get("search_metadata")
        cached = isinstance(meta, dict) and str(meta.get("status") or "").lower() == "cached"
        if cached:
            # a cached SerpApi response is free regardless of whether its body maps cleanly;
            # reconcile to $0 NOW so a later mapping failure cannot leave the reservation charged.
            ctx.record_cost(provider.meter, provider.unit, 0.0, "cached", token=token)
        results = data.get("images_results")
        ...  # EXISTING mapping loop, unchanged
        if not cached:
            ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
        return out
```
So: cached → one `record_cost(0.0, "cached")` BEFORE mapping (reconciles the token to $0 exactly once;
`billed` stays True so the `finally` is a no-op — no double-reconcile, no dangling reserve). Non-cached
→ `record_cost(price, "priced")` AFTER mapping, exactly as today (a post-200 mapping failure still
RETAINS for a billed search — the correct fail-safe from round 2). Do NOT change the reserve, the
`billed` flag, the `except AdapterError`/release, the `finally`, or the mapping loop itself.

## Scope
Only `sdk/sfvf/providers/serpapi.py`. No other file, no test. No new dependencies. Never read/log the
api_key. Create no notes/docs files.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_web.py -q` → all pass (the new
  cached-malformed test green; the round-10 cached tests, the priced/price-floor/malformed-200/budget
  tests all still green).
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_commons.py tests/integration/test_media_web_surface.py tests/integration/test_media_web_fetch.py -q` → still pass.
- `ruff check sdk tests` and `ruff format --check sdk tests` clean.
