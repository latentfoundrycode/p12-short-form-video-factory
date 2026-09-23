# TASK — web-image-sourcing inc6 FIX: budget-gate the paid SerpApi search

## Context
Increment 6 added the paid SerpApi "web" image tier. Cross-family review found a **P1**: the
SerpApi search dispatches a **paid** upstream HTTP request **without a budget reservation**. That
violates the SDK paid-call invariant (H21 / design §6): a missing budget, a missing per-meter
ceiling, or the engaged kill switch must **refuse the call before any network request**, and every
paid call must reserve → reconcile against its meter. The FREE commons/Openverse tier is correct
as-is (no budget); only the PAID `web` (serpapi) tier needs the gate.

A frozen RED contract is already committed (`tests/integration/test_media_web_web.py`). Your job is
to make it GREEN by mirroring the **exact** reserve/reconcile pattern the image adapters already use.

## The reference pattern — copy it (do not invent a new one)
`sdk/sfvf/media/image.py::generate` (lines ~32-36):
```python
price = adapter.image_price(mdl, size)
with ctx._budget_reserved(provider.meter, provider.unit, estimate=price) as token:
    out = adapter.generate(prompt, model=mdl, provider=provider, size=size, secrets=secrets)
# paid call returned (provider billed) -> reconcile the KNOWN cost before any filesystem write:
ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
```
`ctx._budget_reserved(meter, unit, estimate=price)` (context.py): reserves on enter — raising
`BudgetError` when there is no budget config, no per_run/per_day ceiling for the meter, the ceiling
is exceeded, or the kill switch is engaged — and **releases the reserve on any exception** (a failed
provider call is not billed, so its reserve must not leak toward the daily total). On success the
caller reconciles the real cost with `ctx.record_cost(...)`, which emits the `{"t":"cost"}` event and
turns the reservation into an `actual` ledger entry. This release-on-exception semantics is CORRECT
for SerpApi: SerpApi bills per **successful** search, so a 4xx/5xx/transport failure is unbilled.

## Changes (exactly two files)

### 1. `sdk/sfvf/providers/serpapi.py` — expose a conservative per-search price
Add a module-level flat estimate and accessor (SerpApi does not return a per-search cost; its
per-search rate is plan-dependent, so use a conservative constant at/above SerpApi's standard plan
rates — the owner's `per_day` ceiling is the real cap, and `_budget_reserve` already takes
`max(estimate, configured_estimate)` so an owner override still wins when higher):
```python
_SEARCH_PRICE_USD = 0.02  # conservative per-search estimate; >= SerpApi's standard plan rates

def search_price() -> float:
    """Per-search cost used to reserve budget (SerpApi bills per successful search)."""
    return _SEARCH_PRICE_USD
```
(You may retire the dead `_MAX_PER_PAGE` constant while here — a diff-reviewer cosmetic note.)

### 2. `sdk/sfvf/media/web.py` — wrap the web-tier dispatch in the budget gate
In `search()`, the `else:  # "web"` branch currently is:
```python
else:  # "web"
    provider = PROVIDERS["serpapi"]
    secrets = {name: ctx.secret(name) for name in provider.secret_names}
    adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
    out.extend(
        adapter.search(query, limit=limit, licence=licence, provider=provider, secrets=secrets)
    )
```
Replace it with a budget-gated dispatch that mirrors image.py. Skip the reserve entirely when
`limit <= 0` (the adapter would make no request anyway — do not reserve for a no-op):
```python
else:  # "web" — PAID tier: reserve serpapi/usd BEFORE dispatch (H21), reconcile on success
    if limit <= 0:
        continue
    provider = PROVIDERS["serpapi"]
    secrets = {name: ctx.secret(name) for name in provider.secret_names}
    adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
    price = adapter.search_price()
    with ctx._budget_reserved(provider.meter, provider.unit, estimate=price) as token:
        results = adapter.search(
            query, limit=limit, licence=licence, provider=provider, secrets=secrets
        )
    ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
    out.extend(results)
```
Leave the `commons` branch **unchanged** (free, un-metered).

## Scope — do NOT touch anything else
- Do not change the commons/Openverse branch, `fetch`, `check_relevance`, `source`, the SSRF guard,
  the candidate-mapping logic, or the dedup tail.
- Do not change `sdk/sfvf/providers/_http.py`, the registry row, or `app/core/meters.py`
  (the `serpapi` meter entry already exists and is what `record_cost`/`reserve` key on).
- Do not add dependencies. Do not read or print the `SERPAPI_API_KEY`.
- Reserve/reconcile lives in `web.py` (it holds `ctx`); the adapter only exposes `search_price()`.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_web.py -q` → all pass
  (the 4 previously-RED budget-gate tests now green; the 9 existing tests stay green).
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_commons.py tests/integration/test_media_web_surface.py tests/integration/test_media_web_fetch.py -q` → still pass.
- `ruff check sdk tests` and `ruff format --check sdk tests` clean (mind E501 on the new lines).
- No behavioural change to the commons tier or to any non-web path.
