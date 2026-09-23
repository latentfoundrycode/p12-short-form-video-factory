# TASK — web-image-sourcing inc6 FIX round 5: correct the SerpApi per-search price

## Why this round
Cross-family review found a **P1 budget-ceiling bypass**. The SerpApi adapter reserves and reconciles
a flat `_SEARCH_PRICE_USD = 0.02`, but SerpApi's **priciest standard plan (Starter) is $25/1,000 =
$0.025/search**. Under-charging means a `$0.09/day` ceiling that should admit 3 searches admits 4
($0.08 recorded for $0.10 of real spend). Worse, `record_cost` reconciles the flat 0.02, so even
though `_budget_reserve` already takes `max(estimate, configured)`, the reconcile **overwrites** it —
an owner who configures a higher plan rate in `estimates["serpapi"]` is still under-counted.

The fix: a conservative **default** ≥ the priciest standard plan, that the owner can **override** with
their actual plan rate via the budget config's `estimates["serpapi"]`, used for **both** the reserve
and the reconciled cost.

A frozen RED contract is committed (HEAD), in `tests/integration/test_media_web_web.py`:
- `test_serpapi_default_price_bounds_the_daily_ceiling_at_the_starter_rate` (no configured estimate →
  default ≥ $0.025; a $0.09 ceiling admits exactly 3, refuses the 4th before dispatch)
- `test_a_configured_serpapi_rate_drives_both_the_reserve_and_the_recorded_cost` (configured
  `estimates["serpapi"]=0.04` → the emitted cost event is $0.04 and the ceiling uses $0.04)

## Changes (exactly two files)

### 1. `sdk/sfvf/context.py` — expose the configured per-meter estimate
Add a small public accessor on `Context` (near `_budget_reserve`, ~line 509):
```python
def budget_estimate(self, meter: str) -> float | None:
    """The owner-configured per-call cost estimate for `meter`, or None when unset/no budget.
    Adapters whose provider does not return a per-call cost (e.g. SerpApi) use this as the
    authoritative price, falling back to their own conservative default."""
    cfg = self._file.budget
    if cfg is None:
        return None
    value = cfg.estimates.get(meter)
    return value if isinstance(value, int | float) and not isinstance(value, bool) and value > 0 else None
```

### 2. `sdk/sfvf/providers/serpapi.py` — price = configured rate, else a conservative default
- Rename the constant and raise the default to the Starter rate:
```python
_SEARCH_PRICE_DEFAULT_USD = 0.025  # SerpApi's priciest standard plan (Starter, $25/1k). Conservative
#                                    default when the owner has not configured estimates["serpapi"];
#                                    they should set their actual plan rate there for precise accounting.
```
- Compute the effective price once, from the configured rate if the owner set one, else the default,
  and use it for BOTH the reserve and `record_cost`:
```python
    ctx = current_context()
    price = ctx.budget_estimate(provider.meter) or _SEARCH_PRICE_DEFAULT_USD
    ...  # existing limit<=0 / missing-key guards stay BEFORE the reserve
    token = ctx._budget_reserve(provider.meter, provider.unit, estimate=price)
    ...
        ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
```
(Passing `estimate=price` to `_budget_reserve` keeps its `max(price, configured)` a no-op since
`price` already equals the configured rate when one is set; the point is that `record_cost` now uses
the SAME `price`, so a configured rate is no longer under-counted.)
Keep the billed-flag / try-finally / mapping logic exactly as it is — only the price value and its
source change. Read `ctx = current_context()` once (it is already read for the reserve).

## Scope — do NOT touch anything else
Only `sdk/sfvf/context.py` and `sdk/sfvf/providers/serpapi.py`. No other adapter, no test, no
`web.py`/`_budget.py`/registry/meters. No new dependencies. Never read/log the api_key.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_web.py -q` → all pass (the 2 new
  price tests green; the existing budget/billing tests — which use `estimates={}` — still green,
  now reserving/recording $0.025 instead of $0.02; the permissive-ceiling tests are unaffected).
- `PYTHONPATH=sdk python -m pytest tests/sdk/test_budget.py tests/integration/test_budget_gate.py tests/integration/test_media_web_commons.py tests/integration/test_media_web_surface.py -q` → still pass.
- `ruff check sdk tests` and `ruff format --check sdk tests` clean.
