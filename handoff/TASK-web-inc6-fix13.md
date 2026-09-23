# TASK — web-image-sourcing inc6 FIX round 13: a cached hit records the fresh price with cached=True

## Why this round
Cross-family review (P2): the cached path calls `record_cost(..., 0.0, "cached")`, but
`Context.record_cost()` hardcodes `cached=False` in the emitted cost event. The supervisor's cost
aggregation (`app/core/supervisor.py` ~774-793) sums EVERY cost event's `amount` into the `uncached`
forecast total, and only `cached=False` amounts into `actual` (spend). Cost forecasting
(`app/core/estimate.py`) averages the `uncached` figure to estimate a fresh run's cost. So a cached
serpapi hit emitting `amount=0, cached=False` corrupts the forecast — teaching future estimates that a
fresh serpapi search is free.

The correct model: a cached hit is free (no budget consumed), but should record the FRESH per-search
price flagged `cached=True` — so it counts toward the `uncached` forecast (the real fresh price) and is
EXCLUDED from `actual` spend, while the budget LEDGER is reconciled to $0.

A frozen RED contract is committed (HEAD):
`tests/integration/test_media_web_web.py::test_a_cached_serpapi_hit_bills_zero_but_records_the_fresh_price`.

## Changes (two files)

### 1. `sdk/sfvf/context.py` — `record_cost` gains a `cached` flag
Currently `record_cost` emits `"cached": False` and reconciles the token to `amount`. Add a keyword-only
`cached: bool = False`: emit that flag, and derive the LEDGER reconcile as `$0` when cached (a cached hit
is free) else `amount`:
```python
    def record_cost(
        self,
        meter: str,
        unit: str,
        amount: float,
        source: str,
        *,
        token: str | None = None,
        cached: bool = False,
    ) -> None:
        self.emit(
            {
                "t": "cost",
                "meter": meter,
                "unit": unit,
                "amount": amount,
                "source": source,
                "cached": cached,
            }
        )
        self._budget_reconcile(token, actual=(0.0 if cached else amount), note=source)
```
Backward-compatible: every existing caller omits `cached` → `cached=False`, reconcile `amount` — byte-for-
byte unchanged behaviour.

### 2. `sdk/sfvf/providers/serpapi.py` — the cached branch passes the price with cached=True
The cached reconciliation (moved before the mapping loop in round 11) currently is
`ctx.record_cost(provider.meter, provider.unit, 0.0, "cached", token=token)`. Change it to pass the fresh
`price` with `cached=True` (so the event carries the real price and `record_cost` reconciles the ledger to
$0 itself):
```python
        if cached:
            ctx.record_cost(provider.meter, provider.unit, price, "cached", token=token, cached=True)
```
Leave the non-cached (`"priced"`) call, the reserve, the `billed` flag, the release/finally, and the
mapping loop exactly as they are.

## Scope
Only `sdk/sfvf/context.py` and `sdk/sfvf/providers/serpapi.py`. Do NOT change the supervisor cost
aggregation, `estimate.py`, media.web, other adapters, or the frozen tests. No new dependencies. Never
read/log the api_key. Create no notes/docs files.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_web.py -q` → all pass (the updated
  cached test green; the repeated-cached-ceiling and cached-malformed tests — which assert the LEDGER is
  $0 — still green; the priced/price-floor/budget tests unchanged since they don't pass `cached=True`).
- `PYTHONPATH=sdk python -m pytest tests/sdk/test_cost_events.py tests/core/test_cost_recording.py tests/core/test_forecast_recording.py tests/integration/test_image_openai.py tests/integration/test_video_veo.py -q` → still pass (record_cost's default path is unchanged; confirm the cost-event/forecast recording tests still pass with the new optional param).
- `ruff check sdk tests` and `ruff format --check sdk tests` clean.
