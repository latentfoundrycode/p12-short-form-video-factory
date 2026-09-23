# TASK — web-image-sourcing inc6 FIX round 9: canonicalize `sources` (no duplicate paid dispatch)

## Why this round
Cross-family review (P2): `sources` is documented as "a subset of ('commons','web')" (set semantics),
but a repeated tier is not de-duplicated before dispatch. `media.web.search(sources=("web","web"))`
passes validation, then the `for tier in sources` loop dispatches the paid SerpApi search **twice** —
two `$0.025` charges — before the URL-dedup tail discards the second (identical) response. Wasted paid
spend. `("commons","web","commons")` likewise queries commons twice.

A frozen RED contract is committed (HEAD) in `tests/integration/test_media_web_web.py`:
`test_duplicate_sources_dispatch_and_charge_each_tier_once` (one dispatch, one cost event) and
`test_duplicate_mixed_sources_are_canonicalized` (each tier queried once).

## Change (one file) — `sdk/sfvf/media/web.py`
In `search()`, immediately AFTER the `sources` subset validation (`if not sources or any(...): raise
ValueError(...)`) and BEFORE the `WebTierDisabledError` off-switch check, canonicalize `sources` to
its unique tiers preserving first-seen order:
```python
    sources = tuple(dict.fromkeys(sources))  # subset semantics: a repeated tier dispatches once
```
`dict.fromkeys(("web","web"))` → `("web",)`; `dict.fromkeys(("commons","web","commons"))` →
`("commons","web")`. Everything after (off-switch check, dry-run stub loop, the real per-tier dispatch
loop, dedup, `[:limit]`) is unchanged and now iterates unique tiers.

Nothing else changes. Do NOT alter the subset validation, the off-switch check, the dispatch/reserve
logic, the URL-dedup tail, or `source()` (it composes `search()`, so it inherits the fix).

## Scope
Only `sdk/sfvf/media/web.py`. No other file, no test, no adapter. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_web.py -q` → all pass (the two new
  duplicate-source tests green; the existing single-tier and mixed-dedup tests still green — a mixed
  `("commons","web")` with distinct tiers is unaffected by dedup).
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_commons.py tests/integration/test_media_web_surface.py tests/integration/test_media_web_fetch.py -q` → still pass.
- `ruff check sdk tests` and `ruff format --check sdk tests` clean.
